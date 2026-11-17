from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from wallet.models import CoinLedger, CoinRedemptionRequest, Wallet
from wallet.services import (
    _available_bill_redemption_summary,
    calculate_redemption_allocation,
    calculate_coins_for_purchase,
    get_coin_source_summary,
    redeem_customer_coins,
)
from .models import Bill, BillPayment, Credit


def _settle_pending_bill(*, bill, payment_received, redemption=None):
    """Settle payment/credit/earn records only after approval or fallback."""
    wallet, _ = Wallet.objects.get_or_create(customer=bill.customer)
    wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
    get_coin_source_summary(wallet)
    wallet.refresh_from_db(fields=('balance',))
    balance_before_earning = wallet.balance

    merchant_discount = bill.discount
    if redemption:
        bill.discount = merchant_discount + redemption.reward_value
        bill.total_amount = bill.subtotal - bill.discount
    total_amount = bill.total_amount
    payment_received = Decimal(payment_received or 0).quantize(Decimal('0.01'))
    if payment_received < 0 or payment_received > total_amount:
        raise ValidationError('Payment received must be between zero and the final payable amount.')

    rule, coins_earned = calculate_coins_for_purchase(bill.shop, payment_received, balance_before_earning)
    balance_after = balance_before_earning + coins_earned
    outstanding = total_amount - payment_received
    previous_shopping = Bill.objects.filter(
        shop=bill.shop, customer=bill.customer, status=Bill.Status.COMPLETED,
    ).exclude(pk=bill.pk).aggregate(
        total=Coalesce(Sum('total_amount'), Decimal('0.00')),
    )['total']
    bill.paid_amount = payment_received
    bill.payment_status = (
        Bill.PaymentStatus.PAID if outstanding == 0
        else Bill.PaymentStatus.UNPAID if payment_received == 0
        else Bill.PaymentStatus.PARTIAL
    )
    bill.coin_rule = rule
    bill.coins_earned = coins_earned
    bill.coin_value_per_coin = rule.coin_value_per_coin if rule else Decimal('0.00')
    bill.coin_value_amount = (Decimal(coins_earned) * bill.coin_value_per_coin).quantize(Decimal('0.01'))
    bill.wallet_balance_after = balance_after
    bill.cumulative_shopping_after = previous_shopping + total_amount
    bill.status = Bill.Status.COMPLETED
    bill.save(update_fields=(
        'discount', 'total_amount', 'paid_amount', 'payment_status', 'coin_rule',
        'coins_earned', 'coin_value_per_coin', 'coin_value_amount',
        'wallet_balance_after', 'cumulative_shopping_after', 'status',
    ))

    payment = None
    if payment_received > 0:
        payment = BillPayment.objects.create(
            bill=bill, amount=payment_received, received_by=bill.created_by,
            coins_earned=coins_earned,
            coin_value_per_coin=bill.coin_value_per_coin if coins_earned else None,
        )
    if coins_earned:
        wallet.balance = balance_after
        wallet.save(update_fields=('balance', 'updated_at'))
        ledger = CoinLedger.objects.create(
            wallet=wallet, bill=bill, shop=bill.shop,
            entry_type=CoinLedger.EntryType.EARN,
            coin_source=CoinLedger.Source.PURCHASE,
            coin_value_per_coin=bill.coin_value_per_coin,
            transaction_reference=f'BILLPAY-{payment.payment_reference.hex[:32]}',
            coin_delta=coins_earned,
            balance_before=balance_before_earning,
            balance_after=balance_after,
            description=f'Bill {bill.bill_number} · {bill.shop.name}',
        )
        payment.coin_ledger = ledger
        payment.save(update_fields=('coin_ledger',))
    if outstanding > 0:
        Credit.objects.create(
            shop=bill.shop, customer=bill.customer, bill=bill,
            created_by=bill.created_by, original_amount=outstanding,
            description=f'Outstanding from bill {bill.bill_number}',
            reference=bill.bill_number,
        )
    from notifications.services import create_purchase_thank_you_notification
    create_purchase_thank_you_notification(bill=bill)
    return bill


@transaction.atomic
def finalize_bill_without_redemption(*, request_id):
    request_obj = CoinRedemptionRequest.objects.select_for_update().select_related('requested_bill', 'customer').get(pk=request_id)
    if request_obj.requested_bill_id is None:
        return None
    if request_obj.status not in (CoinRedemptionRequest.Status.REJECTED, CoinRedemptionRequest.Status.EXPIRED):
        raise ValidationError('The customer must reject or the request must expire before this bill can be finalized without coins.')
    bill = Bill.objects.select_for_update().get(pk=request_obj.requested_bill_id)
    if bill.status == Bill.Status.COMPLETED:
        return bill
    if bill.status != Bill.Status.PENDING_REDEMPTION:
        raise ValidationError('This bill is no longer pending redemption approval.')
    return _settle_pending_bill(
        bill=bill, payment_received=request_obj.pending_payment_received,
    )


@transaction.atomic
def finalize_bill_redemption(*, request_obj, shopkeeper, shop):
    request_obj = CoinRedemptionRequest.objects.select_for_update().select_related(
        'customer', 'requested_bill', 'source_bill',
    ).get(pk=request_obj.pk)
    if request_obj.requested_bill_id is None:
        raise ValidationError('This is not a bill-linked redemption request.')
    if request_obj.shop_id != shop.pk or request_obj.requested_bill.shop_id != shop.pk:
        raise ValidationError('This redemption does not belong to the selected shop.')
    if request_obj.requested_bill.created_by_id != shopkeeper.pk:
        raise ValidationError('Only the shopkeeper who generated this bill may finalize its redemption.')
    if request_obj.status != CoinRedemptionRequest.Status.PENDING_SHOPKEEPER:
        raise ValidationError('The customer must approve this redemption before shopkeeper confirmation.')
    if request_obj.expires_at <= timezone.now():
        request_obj.status = CoinRedemptionRequest.Status.EXPIRED
        request_obj.save(update_fields=('status',))
        return finalize_bill_without_redemption(request_id=request_obj.pk), None

    bill = Bill.objects.select_for_update().get(pk=request_obj.requested_bill_id)
    if bill.status != Bill.Status.PENDING_REDEMPTION:
        raise ValidationError('The linked bill is no longer pending redemption approval.')

    from accounts.models import CustomerProfile
    customer = CustomerProfile.objects.select_for_update().get(pk=request_obj.customer_id)
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    Wallet.objects.select_for_update().get(pk=wallet.pk)
    summary = _available_bill_redemption_summary(
        customer=customer, shop=shop, exclude_request_id=request_obj.pk,
    )
    allocation = calculate_redemption_allocation(summary, request_obj.coins_requested)
    if (
        allocation['purchase_coins'] != request_obj.purchase_coins_requested
        or allocation['website_coins'] != request_obj.website_coins_requested
        or allocation['reward_value'] != request_obj.reward_value
    ):
        raise ValidationError('Eligible coin balances or saved values changed. Resolve this request without redemption and create a new bill if needed.')

    redemption, _ = redeem_customer_coins(
        shopkeeper=shopkeeper, shop=shop, customer_id=customer.pk,
        idempotency_key=request_obj.idempotency_key, confirmed=True,
        reward_description=request_obj.reward_description or f'Bill {bill.bill_number}',
        expected_coins=request_obj.coins_requested,
        requested_coins=request_obj.coins_requested,
        expected_purchase_coins=request_obj.purchase_coins_requested,
        expected_website_coins=request_obj.website_coins_requested,
        expected_reward_value=request_obj.reward_value,
    )
    redemption.source_bill = request_obj.source_bill
    redemption.applied_bill = bill
    redemption.customer_confirmed_at = request_obj.customer_confirmed_at
    redemption.shopkeeper_confirmed_at = timezone.now()
    redemption.save(update_fields=(
        'source_bill', 'applied_bill', 'customer_confirmed_at', 'shopkeeper_confirmed_at',
    ))
    CoinLedger.objects.filter(redemption=redemption).update(bill=bill)
    request_obj.redemption = redemption
    request_obj.status = CoinRedemptionRequest.Status.COMPLETED
    request_obj.shopkeeper_confirmed_at = redemption.shopkeeper_confirmed_at
    request_obj.completed_at = redemption.shopkeeper_confirmed_at
    request_obj.save(update_fields=('redemption', 'status', 'shopkeeper_confirmed_at', 'completed_at'))
    bill = _settle_pending_bill(
        bill=bill, payment_received=request_obj.pending_payment_received,
        redemption=redemption,
    )
    request_obj.requested_bill = bill
    from notifications.services import create_bill_redemption_notification
    create_bill_redemption_notification(redemption_request=request_obj, event='completed')
    return bill, redemption
