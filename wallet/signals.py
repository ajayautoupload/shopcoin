from decimal import Decimal

from django.db.models.signals import post_save
from django.dispatch import receiver

from shops.models import Shop
from .models import CoinRule


DEFAULT_SLABS = (
    (0, Decimal('1000.00'), Decimal('10.00')),
    (100, Decimal('5000.00'), Decimal('12.00')),
    (500, Decimal('10000.00'), Decimal('15.00')),
)


@receiver(post_save, sender=Shop)
def create_default_shop_coin_rules(sender, instance, **kwargs):
    """Create missing standard slab rows for each newly created shop."""
    for threshold, legacy_purchase_amount, value_per_coin in DEFAULT_SLABS:
        CoinRule.objects.get_or_create(
            shop=instance,
            coin_balance_threshold=threshold,
            defaults={
                'purchase_amount': legacy_purchase_amount,
                'coins_awarded': threshold,
                'coin_value_per_coin': value_per_coin,
                'reward_value': Decimal(threshold) * value_per_coin,
                'is_active': True,
            },
        )
