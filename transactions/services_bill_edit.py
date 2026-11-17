from decimal import Decimal
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from shops.access import shop_is_owned_by
from .models import Bill, BillEditHistory, BillItem


EDIT_WINDOW_SECONDS = 10 * 60


def _snapshot(bill):
    return {
        'bill_number': bill.bill_number,
        'subtotal': str(bill.subtotal),
        'discount': str(bill.discount),
        'total_amount': str(bill.total_amount),
        'paid_amount': str(bill.paid_amount),
        'payment_status': bill.payment_status,
        'items': [
            {
                'product_id': item.product_id,
                'product_name': item.product_name,
                'quantity': item.quantity,
                'unit_price': str(item.unit_price),
                'line_total': str(item.line_total),
            }
            for item in bill.items.order_by('pk')
        ],
    }


@transaction.atomic
def edit_bill(*, bill_id, actor, shop, reason, discount, items):
    """Edit descriptive bill lines while preserving its settled financial total."""
    bill = Bill.objects.select_for_update().select_related('shop').get(pk=bill_id)
    if not shop_is_owned_by(actor, bill.shop) or bill.shop_id != shop.pk:
        raise ValidationError('You are not authorized to edit this shop bill.')
    if bill.created_by_id != actor.pk:
        raise ValidationError('Only the shopkeeper who created this bill may edit it.')
    if timezone.now() >= bill.issued_at + timedelta(seconds=EDIT_WINDOW_SECONDS):
        raise ValidationError('The 10-minute bill edit window has expired.')
    if bill.status != Bill.Status.COMPLETED:
        raise ValidationError('Only completed bills can be edited.')
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError('An edit reason is required.')

    subtotal = sum((item['unit_price'] * item['quantity'] for item in items), Decimal('0.00'))
    redemption_discount = bill.coin_redemption_discount
    if discount < 0 or discount + redemption_discount > subtotal:
        raise ValidationError('Discount cannot be greater than the subtotal.')
    final_discount = discount + redemption_discount
    total = subtotal - final_discount
    if total != bill.total_amount:
        raise ValidationError('The final bill amount must stay unchanged in this phase so existing payments, Udhar, coin ledger, and redemption records remain consistent.')
    if total < bill.paid_amount:
        raise ValidationError('The final bill amount cannot be less than the amount already paid.')

    before = _snapshot(bill)
    old_items = list(bill.items.order_by('pk'))
    for item in old_items:
        item.delete()
    for item in items:
        product = item.get('product')
        BillItem.objects.create(
            bill=bill, product=product,
            product_name=item['product_name'].strip(), quantity=item['quantity'],
            unit_price=item['unit_price'], line_total=item['unit_price'] * item['quantity'],
        )
    bill.subtotal = subtotal
    bill.discount = final_discount
    bill.total_amount = total
    bill.save(update_fields=('subtotal', 'discount', 'total_amount'))
    after = _snapshot(bill)
    history = BillEditHistory.objects.create(
        bill=bill, bill_number=bill.bill_number, edited_by=actor,
        reason=reason, before_snapshot=before, after_snapshot=after,
    )
    from notifications.services import create_bill_edit_notification
    create_bill_edit_notification(bill=bill, history=history)
    return bill
