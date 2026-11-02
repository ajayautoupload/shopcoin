from decimal import Decimal
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import CoinLedger, CoinRedemption, CoinRule, Wallet, WebsiteEngagement, WebsiteEngagementStats

COIN_SLAB_THRESHOLDS = (0, 100, 500)
COINS_PER_HUNDRED = Decimal('100')


def get_coin_rule_for_balance(shop, coin_balance):
    """Return the active shop rule for the customer's current coin quantity."""
    if not shop or coin_balance is None:
        return None
    return CoinRule.objects.filter(
        shop=shop,
        is_active=True,
        coin_balance_threshold__in=COIN_SLAB_THRESHOLDS,
        coin_balance_threshold__lte=int(coin_balance),
    ).order_by('-coin_balance_threshold', 'sort_order').first()


def get_coin_rule_for_purchase_amount(shop, purchase_amount):
    """Return the configured purchase-value tier, independent of wallet balance."""
    if not shop or purchase_amount is None:
        return None
    return CoinRule.objects.filter(
        shop=shop, is_active=True, purchase_amount__lte=Decimal(purchase_amount),
        purchase_amount__in=(Decimal('1000.00'), Decimal('5000.00'), Decimal('10000.00')),
    ).order_by('-purchase_amount', 'sort_order').first()


def calculate_coins_for_purchase(shop, purchase_amount, current_coin_balance=None):
    """Apply the purchase-value tier and award coins only on bills of ₹1,000+."""
    amount = Decimal(purchase_amount)
    coins = int(amount // COINS_PER_HUNDRED) if amount >= Decimal('1000.00') else 0
    rule = get_coin_rule_for_purchase_amount(shop, amount)
    return rule, coins


def get_coin_source_summary(wallet):
    """Return current source balances and their snapshotted reward values."""
    balances = {source: {'coins': 0, 'value': Decimal('0.00')} for source, _ in CoinLedger.Source.choices}
    entries = wallet.entries.filter(is_reversed=False).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())).only('coin_source', 'coin_delta', 'coin_value_per_coin')
    for entry in entries.iterator():
        bucket = balances.setdefault(entry.coin_source, {'coins': 0, 'value': Decimal('0.00')})
        bucket['coins'] += entry.coin_delta
        bucket['value'] += Decimal(entry.coin_delta) * entry.coin_value_per_coin

    for bucket in balances.values():
        bucket['coins'] = max(0, bucket['coins'])
        bucket['value'] = max(Decimal('0.00'), bucket['value']).quantize(Decimal('0.01'))
    active_balance = sum(bucket['coins'] for bucket in balances.values())
    if wallet.balance != active_balance:
        wallet.balance = active_balance
        wallet.save(update_fields=('balance', 'updated_at'))
    return balances


def get_customer_coin_summary(customer, shop=None):
    """Summarize lifetime shopping and the current value of active wallet coins."""
    from transactions.models import Bill

    shop = shop or customer.connected_shop
    bills = Bill.objects.filter(customer=customer)
    if shop:
        bills = bills.filter(shop=shop)
    valid_bills = bills.filter(status=Bill.Status.COMPLETED)
    totals = valid_bills.aggregate(
        total_shopping=Coalesce(Sum('total_amount'), Decimal('0.00')),
        total_bills=Count('pk'),
        coins_earned=Coalesce(Sum('coins_earned'), 0),
    )
    latest_bill = valid_bills.order_by('-issued_at').first()
    rule = get_coin_rule_for_purchase_amount(shop, latest_bill.total_amount if latest_bill else None)
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    source_summary = get_coin_source_summary(wallet)
    purchase = source_summary[CoinLedger.Source.PURCHASE]
    website = source_summary[CoinLedger.Source.WEBSITE_ENGAGEMENT]
    total_value = (purchase['value'] + website['value']).quantize(Decimal('0.01'))
    coin_value = (total_value / wallet.balance).quantize(Decimal('0.01')) if wallet.balance else Decimal('0.00')
    engagement, _ = WebsiteEngagementStats.objects.get_or_create(customer=customer)
    qualifying_bill_count = valid_bills.filter(total_amount__gt=Decimal('1000.00')).count()
    website_redeemable = website['value'] >= Decimal('500.00') or qualifying_bill_count >= 3
    website_redemption_reason = (
        'coins_value' if website['value'] >= Decimal('500.00')
        else 'qualifying_bills' if qualifying_bill_count >= 3
        else ''
    )
    today = timezone.localdate()
    if engagement.last_visit_date and (today - engagement.last_visit_date).days >= 3 and engagement.current_streak:
        engagement.current_streak = 0
        engagement.save(update_fields=('current_streak',))
    redeemable_website_coins = website['coins'] if website_redeemable else 0
    redeemable_coins = purchase['coins'] + redeemable_website_coins
    redeemable_value = purchase['value'] + (website['value'] if redeemable_website_coins else Decimal('0.00'))
    return {
        **totals,
        'active_coins': wallet.balance,
        'current_coin_value': coin_value,
        'purchase_coins': purchase['coins'],
        'purchase_reward_value': purchase['value'],
        'website_coins': website['coins'],
        'website_reward_value': website['value'],
        'combined_reward_value': total_value,
        'current_reward_value': total_value,
        'website_streak': engagement.current_streak,
        'longest_website_streak': engagement.longest_streak,
        'website_milestone_completed': bool(engagement.thirty_day_milestone_at),
        'last_website_visit': engagement.last_visit_date,
        'total_website_coins': engagement.total_website_coins,
        'qualifying_website_redemption_bills': qualifying_bill_count,
        'website_redeemable': website_redeemable,
        'website_redemption_reason': website_redemption_reason,
        'redeemable_coins': redeemable_coins,
        'redeemable_reward_value': redeemable_value.quantize(Decimal('0.01')),
        'wallet': wallet,
        'current_rule': rule,
    }


@transaction.atomic
def redeem_customer_coins(*, shopkeeper, shop, customer_id, idempotency_key, confirmed, reward_description):
    """Redeem a shop's customer's full active balance once, with an audit ledger row."""
    from accounts.models import CustomerProfile
    from shops.access import shop_is_owned_by
    if not confirmed:
        raise ValidationError('Confirm that the eligible products have been provided before clearing coins.')
    reward_description = (reward_description or '').strip()
    if not reward_description:
        raise ValidationError('Describe the products or reward provided before clearing coins.')
    try:
        key = UUID(str(idempotency_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('The redemption confirmation expired. Reload the customer profile and try again.')

    existing = CoinRedemption.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.shop_id == shop.pk and existing.customer_id == int(customer_id):
            return existing, False
        raise ValidationError('This redemption confirmation has already been used.')
    if not shop_is_owned_by(shopkeeper, shop):
        raise ValidationError('You can only redeem coins for customers connected to your own shop.')

    customer = CustomerProfile.objects.select_for_update().filter(
        pk=customer_id, connected_shop=shop, is_deleted=False,
        user__is_active=True, user__profile__role='CUSTOMER', user__profile__is_deleted=False,
    ).first()
    if customer is None:
        raise ValidationError('This customer is not active and connected to your shop.')

    existing = CoinRedemption.objects.select_for_update().filter(idempotency_key=key).first()
    if existing:
        if existing.shop_id == shop.pk and existing.customer_id == customer.pk:
            return existing, False
        raise ValidationError('This redemption confirmation has already been used.')

    from transactions.models import Bill
    bills = Bill.objects.filter(shop=shop, customer=customer, status=Bill.Status.COMPLETED)
    totals = bills.aggregate(total_shopping=Coalesce(Sum('total_amount'), Decimal('0.00')))
    qualifying_bill_count = bills.filter(total_amount__gt=Decimal('1000.00')).count()
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
    sources = get_coin_source_summary(wallet)
    purchase = sources[CoinLedger.Source.PURCHASE]
    website = sources[CoinLedger.Source.WEBSITE_ENGAGEMENT]
    website_eligible = website['value'] >= Decimal('500.00') or qualifying_bill_count >= 3
    purchase_coins = purchase['coins']
    website_coins = website['coins'] if website_eligible else 0
    coins = purchase_coins + website_coins
    if coins <= 0:
        raise ValidationError('There are no active coins to clear.')
    purchase_value = purchase['value'] if purchase_coins else Decimal('0.00')
    website_value = website['value'] if website_coins else Decimal('0.00')
    reward_value = (purchase_value + website_value).quantize(Decimal('0.01'))
    average_value = (reward_value / coins).quantize(Decimal('0.01'))
    redemption = CoinRedemption.objects.create(
        customer=customer,
        shop=shop,
        redeemed_by=shopkeeper,
        idempotency_key=key,
        coins_redeemed=coins,
        purchase_coins_redeemed=purchase_coins,
        website_coins_redeemed=website_coins,
        remaining_coin_balance=wallet.balance - coins,
        coin_value_per_coin=average_value,
        reward_value=reward_value,
        purchase_reward_value=purchase_value,
        website_reward_value=website_value,
        reward_description=reward_description,
        cumulative_shopping=totals['total_shopping'],
        status=CoinRedemption.Status.COMPLETED,
    )
    balance_before = wallet.balance
    wallet.balance = balance_before - coins
    wallet.save(update_fields=('balance', 'updated_at'))
    remaining = balance_before
    for source, count, unit_value in (
        (CoinLedger.Source.PURCHASE, purchase_coins, (purchase_value / purchase_coins if purchase_coins else Decimal('0.00'))),
        (CoinLedger.Source.WEBSITE_ENGAGEMENT, website_coins, Decimal('5.00')),
    ):
        if not count:
            continue
        next_balance = remaining - count
        CoinLedger.objects.create(
            wallet=wallet, shop=shop, redemption=redemption,
            entry_type=CoinLedger.EntryType.REDEEM, coin_source=source,
            coin_value_per_coin=unit_value, coin_delta=-count,
            balance_before=remaining, balance_after=next_balance,
            description=f'Redeemed {count} {source.lower()} coins · {shop.name}',
        )
        remaining = next_balance
    return redemption, True


@transaction.atomic
def record_website_engagement_heartbeat(*, customer, session_token, now=None):
    """Accumulate visible-tab heartbeats and award at most one coin per local day."""
    from datetime import timedelta
    from django.utils import timezone
    from shops.models import Shop

    now = now or timezone.now()
    shop = customer.connected_shop
    if not shop or shop.status != Shop.Status.APPROVED or not customer.user.is_active or customer.is_deleted:
        return {'awarded': False, 'reason': 'inactive'}
    day = timezone.localdate(now)
    engagement, _ = WebsiteEngagement.objects.select_for_update().get_or_create(
        customer=customer, visit_date=day, defaults={'shop': shop},
    )
    if engagement.rewarded_at:
        return {'awarded': False, 'complete': True, 'active_seconds': engagement.active_seconds}
    if engagement.shop_id != shop.pk:
        engagement.shop = shop
        engagement.active_seconds = 0
        engagement.session_token = uuid4()
    try:
        token = UUID(str(session_token))
    except (ValueError, TypeError, AttributeError):
        return {'awarded': False, 'reason': 'invalid_session'}
    if token != engagement.session_token:
        return {'awarded': False, 'reason': 'stale_session'}

    if engagement.last_ping_at is None:
        engagement.last_ping_at = now
    else:
        elapsed = int((now - engagement.last_ping_at).total_seconds())
        if elapsed < 8:
            return {'awarded': False, 'active_seconds': engagement.active_seconds}
        if elapsed > 25:
            engagement.active_seconds = 0
        else:
            engagement.active_seconds = min(121, engagement.active_seconds + elapsed)
        engagement.last_ping_at = now

    awarded = False
    if engagement.active_seconds > 120:
        wallet, _ = Wallet.objects.select_for_update().get_or_create(customer=customer)
        get_coin_source_summary(wallet)
        wallet.refresh_from_db(fields=('balance',))
        before = wallet.balance
        wallet.balance = before + 1
        wallet.save(update_fields=('balance', 'updated_at'))
        entry = CoinLedger.objects.create(
            wallet=wallet, shop=shop, entry_type=CoinLedger.EntryType.EARN,
            coin_source=CoinLedger.Source.WEBSITE_ENGAGEMENT,
            coin_value_per_coin=Decimal('5.00'), coin_delta=1,
            balance_before=before, balance_after=wallet.balance,
            transaction_reference=f'WEBSITE-{day:%Y%m%d}',
            description=f'Daily website engagement reward · {day:%d %b %Y}',
        )
        engagement.reward_ledger = entry
        engagement.rewarded_at = now
        stats, _ = WebsiteEngagementStats.objects.select_for_update().get_or_create(customer=customer)
        if stats.last_visit_date is None or (day - stats.last_visit_date).days > 2:
            stats.current_streak = 1
        else:
            stats.current_streak += 1
        stats.longest_streak = max(stats.longest_streak, stats.current_streak)
        stats.last_visit_date = day
        stats.total_website_coins += 1
        if stats.current_streak >= 30 and stats.thirty_day_milestone_at is None:
            stats.thirty_day_milestone_at = now
        stats.save(update_fields=('current_streak', 'longest_streak', 'last_visit_date', 'total_website_coins', 'thirty_day_milestone_at'))
        awarded = True
    else:
        stats, _ = WebsiteEngagementStats.objects.get_or_create(customer=customer)
    engagement.save(update_fields=('shop', 'active_seconds', 'session_token', 'last_ping_at', 'rewarded_at', 'reward_ledger'))
    return {
        'awarded': awarded, 'complete': bool(engagement.rewarded_at),
        'active_seconds': engagement.active_seconds,
        'website_streak': stats.current_streak,
        'milestone_completed': bool(stats.thirty_day_milestone_at),
    }


@transaction.atomic
def begin_website_engagement(*, customer, now=None):
    from datetime import timedelta
    from django.utils import timezone
    from shops.models import Shop

    now = now or timezone.now()
    shop = customer.connected_shop
    if not shop or shop.status != Shop.Status.APPROVED or not customer.user.is_active or customer.is_deleted:
        return None
    day = timezone.localdate(now)
    engagement, _ = WebsiteEngagement.objects.select_for_update().get_or_create(
        customer=customer, visit_date=day, defaults={'shop': shop, 'last_ping_at': now},
    )
    if engagement.rewarded_at:
        return engagement
    stale = engagement.shop_id != shop.pk or engagement.last_ping_at is None or now - engagement.last_ping_at > timedelta(seconds=25)
    if stale:
        engagement.session_token = uuid4()
        engagement.active_seconds = 0
        engagement.last_ping_at = now
        engagement.shop = shop
        engagement.save(update_fields=('session_token', 'active_seconds', 'last_ping_at', 'shop'))
    return engagement
