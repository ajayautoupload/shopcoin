from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import CustomerProfile
from shops.access import shop_is_owned_by
from wallet.models import CoinLedger, Wallet
from wallet.services import calculate_coins_for_purchase, get_coin_source_summary

from .models import Bill, BillPayment, BillPaymentReversal, Credit, CreditPayment, CreditPaymentReversal


@transaction.atomic
def create_credit(*, shopkeeper, shop, customer_id, amount, description='', due_date=None, reference='', bill_id=None):
    if not shop_is_owned_by(shopkeeper, shop):
        raise ValidationError('You can only create credit for your own shop.')
    try:
        amount = Decimal(amount).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError('Enter a valid credit amount.')
    if amount <= 0:
        raise ValidationError('Credit amount must be greater than zero.')
    customer = CustomerProfile.objects.select_for_update().filter(
        pk=customer_id, connected_shop=shop, is_deleted=False, user__is_active=True,
        user__profile__role='CUSTOMER', user__profile__is_deleted=False,
    ).first()
    if customer is None:
        raise ValidationError('Select an active customer connected to your shop.')
    bill = None
    if bill_id:
        bill = Bill.objects.select_for_update().filter(pk=bill_id, shop=shop, customer=customer).first()
        if bill is None:
            raise ValidationError('The selected bill does not belong to this shop and customer.')
        if bill.credits.exists():
            raise ValidationError('This bill is already linked to a credit record.')
        if bill.payment_status == Bill.PaymentStatus.PAID or amount != bill.remaining_amount:
            raise ValidationError('A linked credit must equal the bill’s current outstanding amount.')
    return Credit.objects.create(
        shop=shop, customer=customer, created_by=shopkeeper, original_amount=amount,
        description=(description or '').strip(), due_date=due_date,
        reference=(reference or '').strip(), bill=bill,
    )


@transaction.atomic
def receive_credit_payment(*, shopkeeper, shop, credit_id, amount, payment_reference):
    try:
        reference = UUID(str(payment_reference))
        amount = Decimal(amount).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError, AttributeError):
        raise ValidationError('Payment form expired or amount is invalid. Reload and try again.')
    if amount <= 0:
        raise ValidationError('Payment must be greater than zero.')
    if not shop_is_owned_by(shopkeeper, shop):
        raise ValidationError('You can only receive payments for your own shop.')
    existing = CreditPayment.objects.select_for_update().filter(payment_reference=reference).select_related('credit').first()
    if existing:
        if existing.credit_id == credit_id and existing.credit.shop_id == shop.pk:
            return existing, False
        raise ValidationError('This payment reference has already been used.')
    credit = Credit.objects.select_for_update().filter(pk=credit_id, shop=shop).first()
    if credit is None:
        raise ValidationError('Credit entry not found for this shop.')
    # Recheck after acquiring the credit row lock so two concurrent submissions
    # using the same reference converge on the first committed payment.
    existing = CreditPayment.objects.select_for_update().filter(payment_reference=reference).select_related('credit').first()
    if existing:
        if existing.credit_id == credit.pk and existing.credit.shop_id == shop.pk:
            return existing, False
        raise ValidationError('This payment reference has already been used.')
    customer = CustomerProfile.objects.select_for_update().filter(pk=credit.customer_id, connected_shop=shop, is_deleted=False).first()
    if customer is None:
        raise ValidationError('This customer is no longer connected to your shop.')
    remaining = credit.original_amount - credit.paid_amount
    if amount > remaining:
        raise ValidationError('Payment cannot exceed the remaining credit balance.')
    payment = CreditPayment.objects.create(credit=credit, amount=amount, payment_reference=reference, received_by=shopkeeper, balance_after=remaining - amount)
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
    get_coin_source_summary(wallet)
    wallet.refresh_from_db(fields=('balance',))
    rule, coins = calculate_coins_for_purchase(shop, amount, wallet.balance)
    if coins:
        before = wallet.balance
        wallet.balance += coins
        wallet.save(update_fields=('balance', 'updated_at'))
        ledger = CoinLedger.objects.create(
            wallet=wallet, shop=shop, bill=credit.bill, entry_type=CoinLedger.EntryType.EARN,
            coin_source=CoinLedger.Source.PURCHASE,
            coin_value_per_coin=rule.coin_value_per_coin if rule else Decimal('10.00'),
            coin_delta=coins, balance_before=before, balance_after=wallet.balance,
            transaction_reference=f'CREDIT-{payment.payment_reference.hex[:32]}',
            description=f'Coins for ₹{amount:.2f} credit payment at {shop.name}',
        )
        payment.coin_ledger = ledger
        payment.save(update_fields=('coin_ledger',))
    credit.paid_amount += amount
    credit.status = Credit.Status.PAID if credit.paid_amount == credit.original_amount else Credit.Status.PARTIAL
    credit.save(update_fields=('paid_amount', 'status', 'updated_at'))
    if credit.bill_id:
        bill = Bill.objects.select_for_update().get(pk=credit.bill_id)
        bill.paid_amount += amount
        bill.payment_status = Bill.PaymentStatus.PAID if bill.paid_amount == bill.total_amount else Bill.PaymentStatus.PARTIAL
        bill.coins_earned += coins
        if coins:
            bill.coin_value_per_coin = rule.coin_value_per_coin
            bill.coin_value_amount += Decimal(coins) * rule.coin_value_per_coin
        bill.wallet_balance_after = wallet.balance
        bill.save(update_fields=('paid_amount', 'payment_status', 'coins_earned', 'coin_value_per_coin', 'coin_value_amount', 'wallet_balance_after'))
    return payment, True


@transaction.atomic
def reverse_credit_payment(*, actor, shop, payment_id):
    if not (getattr(actor, 'is_superuser', False) or shop_is_owned_by(actor, shop)):
        raise ValidationError('Only this shopkeeper or an administrator can reverse a payment.')
    payment = CreditPayment.objects.select_for_update().select_related('credit__customer').filter(pk=payment_id, credit__shop=shop).first()
    if payment is None:
        raise ValidationError('Payment not found for this shop.')
    existing = CreditPaymentReversal.objects.select_for_update().filter(payment=payment).first()
    if existing:
        return existing, False
    credit = Credit.objects.select_for_update().get(pk=payment.credit_id)
    customer = CustomerProfile.objects.select_for_update().get(pk=credit.customer_id)
    wallet = None
    reversal_ledger = None
    original_ledger = payment.coin_ledger
    if original_ledger and original_ledger.is_reversed:
        raise ValidationError('The coin award for this payment was already reversed.')
    if original_ledger:
        wallet = Wallet.objects.select_for_update().get(pk=original_ledger.wallet_id)
        source_totals = get_coin_source_summary(wallet)
        coins = original_ledger.coin_delta
        if coins > source_totals[CoinLedger.Source.PURCHASE]['coins']:
            raise ValidationError('These earned coins have already been spent. Resolve the wallet balance before reversing this payment.')
        before = wallet.balance
        wallet.balance = before - coins
        wallet.save(update_fields=('balance', 'updated_at'))
    reversal = CreditPaymentReversal.objects.create(payment=payment, amount=payment.amount, reversed_by=actor)
    if original_ledger and wallet:
        reversal_ledger = CoinLedger.objects.create(
            wallet=wallet, shop=shop, entry_type=CoinLedger.EntryType.ADJUSTMENT,
            coin_source=CoinLedger.Source.PURCHASE,
            coin_value_per_coin=original_ledger.coin_value_per_coin,
            coin_delta=-original_ledger.coin_delta,
            balance_before=before, balance_after=wallet.balance,
            transaction_reference=f'CREDIT-REV-{reversal.reference.hex[:28]}',
            description=f'Reversal of credit payment {payment.payment_reference}',
        )
        reversal.coin_ledger = reversal_ledger
        reversal.save(update_fields=('coin_ledger',))
    credit.paid_amount -= payment.amount
    credit.status = Credit.Status.UNPAID if credit.paid_amount == 0 else Credit.Status.PARTIAL
    credit.save(update_fields=('paid_amount', 'status', 'updated_at'))
    if credit.bill_id:
        bill = Bill.objects.select_for_update().get(pk=credit.bill_id)
        bill.paid_amount -= payment.amount
        bill.payment_status = Bill.PaymentStatus.PAID if bill.paid_amount == bill.total_amount else Bill.PaymentStatus.PARTIAL if bill.paid_amount else Bill.PaymentStatus.UNPAID
        coins_reversed = payment.coin_ledger.coin_delta if payment.coin_ledger else 0
        bill.coins_earned = max(0, bill.coins_earned - coins_reversed)
        if payment.coin_ledger:
            bill.coin_value_amount = max(Decimal('0.00'), bill.coin_value_amount - Decimal(coins_reversed) * payment.coin_ledger.coin_value_per_coin)
        bill.wallet_balance_after = wallet.balance if wallet else bill.wallet_balance_after
        bill.save(update_fields=('paid_amount', 'payment_status', 'coins_earned', 'coin_value_amount', 'wallet_balance_after'))
    return reversal, True


@transaction.atomic
def reverse_bill_payment(*, actor, shop, payment_id):
    if not (getattr(actor, 'is_superuser', False) or shop_is_owned_by(actor, shop)):
        raise ValidationError('Only this shopkeeper or an administrator can reverse a payment.')
    payment = BillPayment.objects.select_for_update().select_related('bill__customer').filter(pk=payment_id, bill__shop=shop).first()
    if payment is None:
        raise ValidationError('Payment not found for this shop.')
    existing = BillPaymentReversal.objects.select_for_update().filter(payment=payment).first()
    if existing:
        return existing, False
    bill = Bill.objects.select_for_update().get(pk=payment.bill_id)
    if payment.amount > bill.paid_amount:
        raise ValidationError('The bill balance no longer supports reversing this payment.')
    original_ledger = payment.coin_ledger
    wallet = None
    if original_ledger:
        wallet = Wallet.objects.select_for_update().get(pk=original_ledger.wallet_id)
        source_totals = get_coin_source_summary(wallet)
        coins = original_ledger.coin_delta
        if coins > source_totals[CoinLedger.Source.PURCHASE]['coins']:
            raise ValidationError('These earned coins have already been spent. Resolve the wallet balance before reversing this payment.')
        before = wallet.balance
        wallet.balance = before - coins
        wallet.save(update_fields=('balance', 'updated_at'))
    reversal = BillPaymentReversal.objects.create(payment=payment, amount=payment.amount, reversed_by=actor)
    if original_ledger and wallet:
        ledger = CoinLedger.objects.create(
            wallet=wallet, shop=shop, bill=bill, entry_type=CoinLedger.EntryType.ADJUSTMENT,
            coin_source=CoinLedger.Source.PURCHASE,
            coin_value_per_coin=original_ledger.coin_value_per_coin,
            coin_delta=-original_ledger.coin_delta,
            balance_before=before, balance_after=wallet.balance,
            transaction_reference=f'BILL-REV-{reversal.reference.hex[:30]}',
            description=f'Reversal of bill payment {payment.payment_reference}',
        )
        reversal.coin_ledger = ledger
        reversal.save(update_fields=('coin_ledger',))
    bill.paid_amount -= payment.amount
    bill.payment_status = Bill.PaymentStatus.PAID if bill.paid_amount == bill.total_amount else Bill.PaymentStatus.PARTIAL if bill.paid_amount else Bill.PaymentStatus.UNPAID
    if original_ledger:
        bill.coins_earned = max(0, bill.coins_earned - original_ledger.coin_delta)
        bill.coin_value_amount = max(Decimal('0.00'), bill.coin_value_amount - Decimal(original_ledger.coin_delta) * original_ledger.coin_value_per_coin)
        bill.wallet_balance_after = wallet.balance
    bill.save(update_fields=('paid_amount', 'payment_status', 'coins_earned', 'coin_value_amount', 'wallet_balance_after'))
    credit = Credit.objects.select_for_update().filter(bill=bill).first()
    if credit:
        credit.original_amount += payment.amount
        credit.status = Credit.Status.PAID if credit.paid_amount == credit.original_amount else Credit.Status.PARTIAL if credit.paid_amount else Credit.Status.UNPAID
        credit.save(update_fields=('original_amount', 'status', 'updated_at'))
    else:
        Credit.objects.create(
            shop=bill.shop, customer=bill.customer, bill=bill, created_by=actor,
            original_amount=payment.amount, description=f'Payment reversal for bill {bill.bill_number}',
            reference=bill.bill_number,
        )
    return reversal, True
