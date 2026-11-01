from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce

from .models import CoinLedger, CoinRedemption, CoinRule, Wallet

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


def calculate_coins_for_purchase(shop, purchase_amount, current_coin_balance=None):
    """Return floored bill coins and the slab for the resulting coin balance."""
    coins = int(Decimal(purchase_amount) // COINS_PER_HUNDRED)
    balance = coins if current_coin_balance is None else int(current_coin_balance)
    rule = get_coin_rule_for_balance(shop, balance)
    return rule, coins


def get_customer_coin_summary(customer, shop=None):
    """Summarize lifetime shopping and the current value of active wallet coins."""
    from transactions.models import Bill

    shop = shop or customer.connected_shop
    bills = Bill.objects.filter(customer=customer)
    if shop:
        bills = bills.filter(shop=shop)
    totals = bills.aggregate(
        total_shopping=Coalesce(Sum('total_amount'), Decimal('0.00')),
        total_bills=Count('pk'),
        coins_earned=Coalesce(Sum('coins_earned'), 0),
    )
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    rule = get_coin_rule_for_balance(shop, wallet.balance)
    coin_value = rule.coin_value_per_coin if rule else Decimal('0.00')
    return {
        **totals,
        'active_coins': wallet.balance,
        'current_coin_value': coin_value,
        'current_reward_value': (Decimal(wallet.balance) * coin_value).quantize(Decimal('0.01')),
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
    totals = Bill.objects.filter(shop=shop, customer=customer).aggregate(
        total_shopping=Coalesce(Sum('total_amount'), Decimal('0.00')),
    )
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
    coins = wallet.balance
    if coins <= 0:
        raise ValidationError('There are no active coins to clear.')
    rule = get_coin_rule_for_balance(shop, coins)
    if rule is None:
        raise ValidationError('No active coin value rule is configured for this balance.')

    reward_value = (Decimal(coins) * rule.coin_value_per_coin).quantize(Decimal('0.01'))
    redemption = CoinRedemption.objects.create(
        customer=customer,
        shop=shop,
        redeemed_by=shopkeeper,
        idempotency_key=key,
        coins_redeemed=coins,
        remaining_coin_balance=0,
        coin_value_per_coin=rule.coin_value_per_coin,
        reward_value=reward_value,
        reward_description=reward_description,
        cumulative_shopping=totals['total_shopping'],
        status=CoinRedemption.Status.COMPLETED,
    )
    wallet.balance = 0
    wallet.save(update_fields=('balance', 'updated_at'))
    CoinLedger.objects.create(
        wallet=wallet,
        redemption=redemption,
        entry_type=CoinLedger.EntryType.REDEEM,
        coin_delta=-coins,
        balance_before=coins,
        balance_after=0,
        description=f'Redeemed {coins} coins for ₹{reward_value} · {shop.name}',
    )
    return redemption, True
