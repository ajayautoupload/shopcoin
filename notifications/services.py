from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from .models import InAppNotification


def create_direct_bill_redemption_notification(*, bill, redemption):
    """Tell the bill's customer about a completed shopkeeper-authorized redemption."""
    customer = bill.customer
    if not customer.notifications_enabled:
        return None
    profile = getattr(customer.user, 'profile', None)
    language = profile.preferred_language if profile and profile.preferred_language == 'hi' else 'en'
    if language == 'hi':
        title = 'बिल पर ShopCoin रिडेम्पशन लागू हुआ'
        message = '\n'.join((
            f'दुकान: {bill.shop.name}', f'बिल नंबर: {bill.bill_number}',
            f'रिडीम किए गए कॉइन: {redemption.coins_redeemed}',
            f'कॉइन का सुरक्षित मूल्य: ₹{redemption.reward_value:.2f}',
            f'कॉइन छूट: ₹{redemption.reward_value:.2f}',
            f'अंतिम देय राशि: ₹{bill.total_amount:.2f}',
            f'रिडेम्पशन संदर्भ: {redemption.idempotency_key}',
            'रिडेम्पशन पूरा हुआ; आपकी वॉलेट और लेजर जानकारी अपडेट कर दी गई है।',
        ))
    else:
        title = 'ShopCoin redemption applied to your bill'
        message = '\n'.join((
            f'Shop: {bill.shop.name}', f'Bill number: {bill.bill_number}',
            f'Coins redeemed: {redemption.coins_redeemed}',
            f'Saved coin value: ₹{redemption.reward_value:.2f}',
            f'Coin discount: ₹{redemption.reward_value:.2f}',
            f'Final payable: ₹{bill.total_amount:.2f}',
            f'Redemption reference: {redemption.idempotency_key}',
            'Redemption is complete; your wallet and ledger have been updated.',
        ))
    return InAppNotification.objects.get_or_create(
        event_key=f'bill-redemption-direct:{redemption.pk}',
        defaults={
            'user_id': customer.user_id,
            'title': title,
            'message': message,
            'url': reverse('customers:bill_detail', args=(bill.pk,)),
        },
    )[0]


def create_purchase_thank_you_notification(*, bill):
    """Create a single localized thank-you notice after a completed bill."""
    from django.db.models import Q
    from offers.models import ShopOffer
    from wallet.models import CoinRule
    from wallet.services import get_customer_coin_summary

    if bill.status != 'COMPLETED':
        return None
    customer = bill.customer
    if not customer.notifications_enabled:
        return None

    profile = getattr(customer.user, 'profile', None)
    language = profile.preferred_language if profile and profile.preferred_language == 'hi' else 'en'
    now = timezone.now()
    shopping_at = timezone.localtime(bill.issued_at).strftime('%d-%m-%Y %H:%M')
    customer_name = customer.user.get_full_name().strip()
    summary = get_customer_coin_summary(customer, bill.shop)
    shop_discount = bill.merchant_discount
    coin_discount = bill.coin_redemption_discount
    rules = CoinRule.objects.filter(
        shop=bill.shop, is_active=True,
        purchase_amount__in=(Decimal('1000.00'), Decimal('5000.00'), Decimal('10000.00')),
    ).order_by('purchase_amount')
    offers = ShopOffer.objects.filter(shop=bill.shop, is_active=True).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now),
        Q(ends_at__isnull=True) | Q(ends_at__gt=now),
    ).order_by('starts_at', 'pk')
    items = list(bill.items.all())

    if language == 'hi':
        title = f'{bill.shop.name} की ओर से धन्यवाद!'
        lines = [
            f'नमस्ते {customer_name},' if customer_name else 'नमस्ते,',
            f'{bill.shop.name} से खरीदारी करने के लिए धन्यवाद।',
            f'बिल नंबर: {bill.bill_number}', f'खरीदारी की तारीख और समय: {shopping_at}',
            'आज खरीदे गए उत्पाद:',
        ]
        lines.extend(f'• {item.product_name} × {item.quantity} — ₹{item.line_total:.2f}' for item in items)
        lines.extend((
            f'मूल बिल राशि: ₹{bill.subtotal:.2f}', f'दुकान की छूट: ₹{shop_discount:.2f}',
            f'कॉइन रिडेम्पशन छूट: ₹{coin_discount:.2f}', f'अंतिम देय राशि: ₹{bill.total_amount:.2f}',
            f'वास्तव में प्राप्त भुगतान: ₹{bill.paid_amount:.2f}', f'बाकी उधार: ₹{bill.remaining_amount:.2f}',
            f'इस खरीद पर मिले Purchase Coins: {bill.coins_earned} · सुरक्षित मूल्य ₹{bill.coin_value_amount:.2f}',
            f'आपका वर्तमान confirmed balance: {summary["active_coins"]} कॉइन · वास्तविक इनाम मूल्य ₹{summary["current_reward_value"]:.2f}',
            '', 'अगली खरीदारी पर उपलब्ध लाभ:',
        ))
        if rules:
            lines.append('Purchase Coins केवल वास्तविक भुगतान पर, दुकान के मौजूदा नियमों के अनुसार मिलते हैं:')
            lines.extend(f'• ₹{rule.purchase_amount:.0f}+ योग्य भुगतान · प्रति कॉइन सुरक्षित मूल्य ₹{rule.coin_value_per_coin:.2f}' for rule in rules)
        else:
            lines.append('आगे के Purchase Coins वास्तविक भुगतान और दुकान के उस समय लागू नियमों पर निर्भर होंगे।')
        if offers:
            lines.append('अभी सक्रिय दुकान ऑफ़र:')
            lines.extend(f'• {offer.title}{f" ({offer.badge})" if offer.badge else ""}{f" — {offer.description}" if offer.description else ""}' for offer in offers)
        else:
            lines.append('इस समय दुकान का कोई सक्रिय ऑफ़र सूचीबद्ध नहीं है। अगली बार नए ऑफ़र देख सकते हैं।')
    else:
        title = f'Thank you for shopping at {bill.shop.name}!'
        lines = [
            f'Hi {customer_name},' if customer_name else 'Hello,',
            f'Thank you for shopping at {bill.shop.name}.',
            f'Bill number: {bill.bill_number}', f'Shopping date and time: {shopping_at}',
            'Products purchased today:',
        ]
        lines.extend(f'• {item.product_name} × {item.quantity} — ₹{item.line_total:.2f}' for item in items)
        lines.extend((
            f'Original bill amount: ₹{bill.subtotal:.2f}', f'Shop discount: ₹{shop_discount:.2f}',
            f'Coin redemption discount: ₹{coin_discount:.2f}', f'Final payable: ₹{bill.total_amount:.2f}',
            f'Payment actually received: ₹{bill.paid_amount:.2f}', f'Remaining Udhar: ₹{bill.remaining_amount:.2f}',
            f'Purchase Coins actually earned: {bill.coins_earned} · saved value ₹{bill.coin_value_amount:.2f}',
            f'Your current confirmed balance: {summary["active_coins"]} coins · actual reward value ₹{summary["current_reward_value"]:.2f}',
            '', 'Benefits available on a future visit:',
        ))
        if rules:
            lines.append('Purchase Coins are based on the amount actually paid and the shop’s current rules:')
            lines.extend(f'• ₹{rule.purchase_amount:.0f}+ qualifying payment · saved value ₹{rule.coin_value_per_coin:.2f} per coin' for rule in rules)
        else:
            lines.append('Future Purchase Coins depend on the amount actually paid and the shop’s rules at that time.')
        if offers:
            lines.append('Currently active shop offers:')
            lines.extend(f'• {offer.title}{f" ({offer.badge})" if offer.badge else ""}{f" — {offer.description}" if offer.description else ""}' for offer in offers)
        else:
            lines.append('There are no active offers listed by this shop right now. Check again on a future visit.')

    return InAppNotification.objects.get_or_create(
        event_key=f'bill-purchase-thank-you:{bill.pk}',
        defaults={
            'user_id': customer.user_id,
            'title': title,
            'message': '\n'.join(lines),
            'url': reverse('customers:bill_detail', args=(bill.pk,)),
        },
    )[0]


def create_bill_redemption_notification(*, redemption_request, event):
    """Create one customer-only notification for a bill redemption transition."""
    customer = redemption_request.customer
    if not customer.notifications_enabled:
        return None

    bill = redemption_request.requested_bill
    if bill is None:
        return None
    profile = getattr(customer.user, 'profile', None)
    language = profile.preferred_language if profile and profile.preferred_language == 'hi' else 'en'
    shop_name = redemption_request.shop.name
    shop_discount = bill.merchant_discount
    original_payable = bill.subtotal - shop_discount
    if event == 'completed':
        final_amount = bill.total_amount
        final_label_en, final_label_hi = 'Final payable', 'अंतिम देय राशि'
    elif event in ('rejected', 'expired'):
        final_amount = original_payable
        final_label_en, final_label_hi = 'Payable without coin redemption', 'कॉइन रिडेम्पशन के बिना देय राशि'
    elif event == 'cancelled':
        final_amount = None
        final_label_en = final_label_hi = None
    else:
        final_amount = original_payable - redemption_request.reward_value
        final_label_en, final_label_hi = 'Proposed final payable', 'प्रस्तावित अंतिम देय राशि'
    details_en = (
        f'Shop: {shop_name}\nBill number: {bill.bill_number}\n'
        f'Original amount: ₹{bill.subtotal:.2f}\nShop discount: ₹{shop_discount:.2f}\n'
        f'Selected coins: {redemption_request.coins_requested}\n'
        f'Actual coin value / discount: ₹{redemption_request.reward_value:.2f}'
    )
    details_hi = (
        f'दुकान: {shop_name}\nबिल नंबर: {bill.bill_number}\n'
        f'मूल राशि: ₹{bill.subtotal:.2f}\nदुकान की छूट: ₹{shop_discount:.2f}\n'
        f'चुने गए कॉइन: {redemption_request.coins_requested}\n'
        f'कॉइन का वास्तविक मूल्य / छूट: ₹{redemption_request.reward_value:.2f}'
    )
    if final_amount is not None:
        details_en += f'\n{final_label_en}: ₹{final_amount:.2f}'
        details_hi += f'\n{final_label_hi}: ₹{final_amount:.2f}'
    if event == 'requested':
        title_en, title_hi = 'ShopCoin redemption approval needed', 'शॉपकॉइन रिडेम्पशन की पुष्टि आवश्यक'
        body_en, body_hi = 'Please review and approve or reject this request. Coins are not deducted until you approve and the shopkeeper confirms.', 'कृपया अनुरोध देखकर स्वीकार या अस्वीकार करें। आपकी पुष्टि और दुकानदार की अंतिम पुष्टि से पहले कॉइन नहीं कटेंगे।'
    elif event == 'approved':
        title_en, title_hi = 'Redemption approved by you', 'आपने रिडेम्पशन स्वीकार किया'
        body_en, body_hi = 'Your approval is recorded. The shopkeeper must confirm before coins are deducted and this bill is finalized.', 'आपकी पुष्टि दर्ज है। कॉइन कटने और बिल पूरा होने से पहले दुकानदार की अंतिम पुष्टि ज़रूरी है।'
    elif event == 'rejected':
        title_en, title_hi = 'Redemption request rejected', 'रिडेम्पशन अनुरोध अस्वीकार'
        body_en, body_hi = 'The bill will be finalized without this coin discount. No coins were deducted.', 'बिल इस कॉइन छूट के बिना पूरा किया जाएगा। कोई कॉइन नहीं काटा गया।'
    elif event == 'completed':
        title_en, title_hi = 'ShopCoin redemption confirmed', 'शॉपकॉइन रिडेम्पशन पूरा हुआ'
        body_en, body_hi = 'The shopkeeper confirmed. Coins were deducted and the bill was finalized.', 'दुकानदार ने पुष्टि कर दी। कॉइन काटे गए और बिल पूरा हुआ।'
    elif event == 'expired':
        title_en, title_hi = 'Redemption request expired', 'रिडेम्पशन अनुरोध की समय-सीमा समाप्त'
        body_en, body_hi = 'No coins were deducted. The shopkeeper can finalize the bill without this redemption.', 'कोई कॉइन नहीं काटा गया। दुकानदार इस रिडेम्पशन के बिना बिल पूरा कर सकता है।'
    elif event == 'cancelled':
        title_en, title_hi = 'Redemption bill cancelled', 'रिडेम्पशन वाला बिल रद्द हुआ'
        body_en, body_hi = 'The bill was cancelled. No coins were deducted.', 'बिल रद्द कर दिया गया। कोई कॉइन नहीं काटा गया।'
    else:
        raise ValueError(f'Unsupported bill redemption notification event: {event}')

    from django.urls import reverse

    return InAppNotification.objects.get_or_create(
        event_key=f'bill-redemption:{redemption_request.pk}:{event}',
        defaults={
            'user_id': customer.user_id,
            'redemption_request': redemption_request,
            'title': title_hi if language == 'hi' else title_en,
            'message': '\n'.join((details_hi, body_hi)) if language == 'hi' else '\n'.join((details_en, body_en)),
            'url': reverse('customers:bill_detail', args=(bill.pk,)),
        },
    )[0]


def _format_bill_snapshot(snapshot, language):
    if language == 'hi':
        lines = [
            f"उप-योग: ₹{snapshot['subtotal']}",
            f"छूट: ₹{snapshot['discount']}",
            f"कुल राशि: ₹{snapshot['total_amount']}",
            f"भुगतान: ₹{snapshot['paid_amount']}",
            'सामान:',
        ]
        lines.extend(
            f"• {item['product_name']} × {item['quantity']} — ₹{item['line_total']}"
            for item in snapshot['items']
        )
    else:
        lines = [
            f"Subtotal: ₹{snapshot['subtotal']}",
            f"Discount: ₹{snapshot['discount']}",
            f"Total amount: ₹{snapshot['total_amount']}",
            f"Paid: ₹{snapshot['paid_amount']}",
            'Items:',
        ]
        lines.extend(
            f"• {item['product_name']} × {item['quantity']} — ₹{item['line_total']}"
            for item in snapshot['items']
        )
    return '\n'.join(lines)


def create_bill_edit_notification(*, bill, history):
    """Create one localized in-app notice for the edited bill's customer.

    Call from the bill edit transaction so the audit row and notification commit
    or roll back together. The existing customer notification preference is
    honored; skipped events are not recorded as sent.
    """
    customer = bill.customer
    if not customer.notifications_enabled:
        return None

    profile = getattr(customer.user, 'profile', None)
    language = profile.preferred_language if profile and profile.preferred_language == 'hi' else 'en'
    edited_at = timezone.localtime(history.edited_at).strftime('%d-%m-%Y %H:%M')
    before = history.before_snapshot
    after = history.after_snapshot
    if language == 'hi':
        title = 'आपका बिल अपडेट किया गया'
        message = '\n'.join((
            f'दुकान: {bill.shop.name}',
            f'बिल नंबर: {bill.bill_number}',
            f'संपादन की तारीख और समय: {edited_at}',
            f'कारण: {history.reason}',
            '', 'पहले की जानकारी:', _format_bill_snapshot(before, language),
            '', 'नई जानकारी:', _format_bill_snapshot(after, language),
        ))
    else:
        title = 'Your bill was updated'
        message = '\n'.join((
            f'Shop: {bill.shop.name}',
            f'Bill number: {bill.bill_number}',
            f'Edited on: {edited_at}',
            f'Reason: {history.reason}',
            '', 'Previous details:', _format_bill_snapshot(before, language),
            '', 'Updated details:', _format_bill_snapshot(after, language),
        ))

    return InAppNotification.objects.get_or_create(
        event_key=f'bill-edit-history:{history.pk}',
        defaults={
            'user_id': customer.user_id,
            'title': title,
            'message': message,
            'url': reverse('customers:bill_detail', args=(bill.pk,)),
        },
    )[0]
