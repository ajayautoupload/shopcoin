from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts.models import CustomerProfile
from shops.access import shop_is_owned_by
from shops.models import Product
from wallet.models import CoinLedger, CoinRedemption, Wallet
from wallet.models import CoinRule
from wallet.services import COINS_PER_HUNDRED, calculate_coins_for_purchase, get_coin_source_summary

from .models import Bill, BillItem, BillPayment, Credit


CENT = Decimal('0.01')


@transaction.atomic
def create_bill(*, shopkeeper, shop, customer_id, idempotency_key, discount, items, payment_received=None):
    try:
        key = UUID(str(idempotency_key))
        discount = Decimal(discount).quantize(CENT)
    except (ValueError, TypeError, InvalidOperation):
        raise ValidationError('The bill form is invalid. Reload it and try again.')

    existing = Bill.objects.select_for_update().filter(idempotency_key=key).first()
    if existing:
        if existing.shop_id == shop.pk and existing.customer_id == int(customer_id):
            return existing, False
        raise ValidationError('This bill submission has already been used. Reload the form to create a new bill.')

    if not shop_is_owned_by(shopkeeper, shop):
        raise ValidationError('You can only create bills for your own shop.')
    active_tiers = set(CoinRule.objects.filter(shop=shop, is_active=True, purchase_amount__in=(Decimal('1000.00'), Decimal('5000.00'), Decimal('10000.00'))).values_list('purchase_amount', flat=True))
    if active_tiers != {Decimal('1000.00'), Decimal('5000.00'), Decimal('10000.00')}:
        raise ValidationError('Coin earning rule is not configured for this shop. Please configure a Coin Rule before creating the bill.')
    if discount < 0:
        raise ValidationError('Discount cannot be negative.')

    customer = CustomerProfile.objects.select_for_update().filter(
        pk=customer_id,
        connected_shop=shop,
        is_deleted=False,
        user__is_active=True,
        user__profile__is_deleted=False,
    ).first()
    if customer is None:
        raise ValidationError('This customer is not active and connected to your shop.')

    normalized_items = []
    catalog_quantities = {}
    subtotal = Decimal('0.00')
    for line in items:
        product = line.get('product')
        if product:
            product = Product.objects.filter(pk=product.pk, shop=shop, is_active=True).first()
            if product is None:
                raise ValidationError('A selected product does not belong to your shop.')
        name = (line.get('product_name') or '').strip()
        if not name and product:
            name = product.name
        if not name:
            raise ValidationError('Enter a product name for each bill item.')
        try:
            quantity = int(line.get('quantity'))
            unit_price = Decimal(line.get('unit_price')).quantize(CENT)
        except (ValueError, TypeError, InvalidOperation):
            raise ValidationError('Enter a valid quantity and price for each item.')
        if quantity < 1 or unit_price < 0:
            raise ValidationError('Quantity must be at least 1 and price cannot be negative.')
        if product:
            catalog_quantities[product.pk] = catalog_quantities.get(product.pk, 0) + quantity
        line_total = (unit_price * quantity).quantize(CENT)
        subtotal += line_total
        normalized_items.append({
            'product': product,
            'product_name': name[:180],
            'quantity': quantity,
            'unit_price': unit_price,
            'line_total': line_total,
        })

    subtotal = subtotal.quantize(CENT)
    if not normalized_items:
        raise ValidationError('Add at least one product to the bill.')
    if discount > subtotal:
        raise ValidationError('Discount cannot be greater than the subtotal.')

    locked_products = {
        product.pk: product
        for product in Product.objects.select_for_update().filter(
            pk__in=catalog_quantities, shop=shop, is_active=True,
        ).order_by('pk')
    }
    if set(locked_products) != set(catalog_quantities):
        raise ValidationError('A selected product is no longer available in your shop.')
    for product_id, quantity in catalog_quantities.items():
        product = locked_products[product_id]
        if product.stock < quantity:
            raise ValidationError(f'Insufficient stock for {product.name}. Only {product.stock} available.')

    total_amount = (subtotal - discount).quantize(CENT)
    if payment_received is None:
        # Preserve the previous service contract for trusted internal callers;
        # the bill form always submits the actual received amount explicitly.
        payment_received = total_amount
    try:
        payment_received = Decimal(payment_received).quantize(CENT)
    except (ValueError, TypeError, InvalidOperation):
        raise ValidationError('Enter a valid payment received amount.')
    if payment_received < 0:
        raise ValidationError('Payment received cannot be negative.')
    if payment_received > total_amount:
        raise ValidationError('Payment received cannot exceed the final bill amount.')
    outstanding = (total_amount - payment_received).quantize(CENT)
    previous_shopping = Bill.objects.filter(shop=shop, customer=customer, status=Bill.Status.COMPLETED).aggregate(
        total=Coalesce(Sum('total_amount'), Decimal('0.00')),
    )['total']
    cumulative_shopping_after = (previous_shopping + total_amount).quantize(CENT)
    for product_id, quantity in catalog_quantities.items():
        product = locked_products[product_id]
        product.stock -= quantity
        product.save(update_fields=('stock', 'updated_at'))
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
    get_coin_source_summary(wallet)
    wallet.refresh_from_db(fields=('balance',))
    balance_before = wallet.balance
    rule, coins_earned = calculate_coins_for_purchase(shop, payment_received, balance_before)
    balance_after = balance_before + coins_earned
    value_per_coin = rule.coin_value_per_coin if rule else Decimal('0.00')
    coin_value_amount = (Decimal(coins_earned) * value_per_coin).quantize(CENT) if value_per_coin is not None else Decimal('0.00')

    now = timezone.localtime()
    bill_number = f'SC{shop.pk}-{now:%Y%m%d%H%M%S}-{key.hex[:12].upper()}'
    bill = Bill.objects.create(
        bill_number=bill_number,
        idempotency_key=key,
        shop=shop,
        customer=customer,
        created_by=shopkeeper,
        coin_rule=rule,
        subtotal=subtotal,
        discount=discount,
        total_amount=total_amount,
        paid_amount=payment_received,
        payment_status=(Bill.PaymentStatus.PAID if outstanding == 0 else Bill.PaymentStatus.UNPAID if payment_received == 0 else Bill.PaymentStatus.PARTIAL),
        coins_earned=coins_earned,
        coin_value_per_coin=value_per_coin,
        coin_value_amount=coin_value_amount,
        wallet_balance_before=balance_before,
        wallet_balance_after=balance_after,
        cumulative_shopping_after=cumulative_shopping_after,
    )
    BillItem.objects.bulk_create([BillItem(bill=bill, **line) for line in normalized_items])

    payment = None
    if payment_received > 0:
        payment = BillPayment.objects.create(
            bill=bill, amount=payment_received, received_by=shopkeeper,
            coins_earned=coins_earned, coin_value_per_coin=value_per_coin if coins_earned else None,
        )
    if coins_earned:
        wallet.balance = balance_after
        wallet.save(update_fields=('balance', 'updated_at'))
        ledger = CoinLedger.objects.create(
            wallet=wallet,
            bill=bill,
            shop=shop,
            entry_type=CoinLedger.EntryType.EARN,
            coin_source=CoinLedger.Source.PURCHASE,
            coin_value_per_coin=value_per_coin,
            transaction_reference=f'BILLPAY-{payment.payment_reference.hex[:32]}',
            coin_delta=coins_earned,
            balance_before=balance_before,
            balance_after=balance_after,
            description=f'Bill {bill.bill_number} · {shop.name}',
        )
        payment.coin_ledger = ledger
        payment.save(update_fields=('coin_ledger',))
    if outstanding > 0:
        Credit.objects.create(
            shop=shop, customer=customer, bill=bill, created_by=shopkeeper,
            original_amount=outstanding, description=f'Outstanding from bill {bill.bill_number}',
            reference=bill.bill_number,
        )
    return bill, True


@transaction.atomic
def set_bill_status(*, bill_id, status):
    """Cancel/refund a bill without deleting its audit history or retaining its coins."""
    bill = Bill.objects.select_for_update().get(pk=bill_id)
    if status not in (Bill.Status.CANCELLED, Bill.Status.REFUNDED):
        raise ValidationError('Bills can only be moved to cancelled or refunded status here.')
    if bill.status == status:
        return bill, False
    if bill.status != Bill.Status.COMPLETED:
        raise ValidationError('A cancelled or refunded bill cannot be changed again.')

    if CoinRedemption.objects.filter(
        customer=bill.customer, shop=bill.shop,
        redeemed_at__gte=bill.issued_at, purchase_coins_redeemed__gt=0,
    ).exists():
        raise ValidationError('Purchase Coins have already been redeemed after this bill. Resolve that redemption before refunding the bill.')

    wallet, _ = Wallet.objects.select_for_update().get_or_create(customer=bill.customer)
    purchase_entries = CoinLedger.objects.select_for_update().filter(
        wallet=wallet, bill=bill, entry_type=CoinLedger.EntryType.EARN,
        coin_source=CoinLedger.Source.PURCHASE, is_reversed=False,
    )
    coins_to_reverse = sum(purchase_entries.values_list('coin_delta', flat=True))
    source_totals = get_coin_source_summary(wallet)
    if coins_to_reverse > source_totals[CoinLedger.Source.PURCHASE]['coins']:
        raise ValidationError('There are not enough active Purchase Coins to reverse this bill safely.')
    purchase_entries.update(is_reversed=True)
    get_coin_source_summary(wallet)
    wallet.refresh_from_db(fields=('balance',))
    bill.status = status
    bill.save(update_fields=('status',))
    return bill, True
