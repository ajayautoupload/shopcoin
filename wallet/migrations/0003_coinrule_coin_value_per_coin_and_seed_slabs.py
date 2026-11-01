from decimal import Decimal

import django.core.validators
from django.db import migrations, models


SLABS = (
    (Decimal('1000.00'), 10, Decimal('10.00')),
    (Decimal('5000.00'), 50, Decimal('12.00')),
    (Decimal('10000.00'), 100, Decimal('15.00')),
)


def seed_shop_slabs(apps, schema_editor):
    CoinRule = apps.get_model('wallet', 'CoinRule')
    Shop = apps.get_model('shops', 'Shop')
    db = schema_editor.connection.alias
    for shop in Shop.objects.using(db).all().iterator():
        for threshold, coins, value_per_coin in SLABS:
            CoinRule.objects.using(db).update_or_create(
                shop_id=shop.pk,
                purchase_amount=threshold,
                defaults={
                    'coins_awarded': coins,
                    'coin_value_per_coin': value_per_coin,
                    'reward_value': Decimal(coins) * value_per_coin,
                    'is_active': True,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ('shops', '0005_alter_shop_owner'),
        ('wallet', '0002_alter_coinledger_wallet_alter_coinvalue_shop_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='coinrule',
            name='coin_value_per_coin',
            field=models.DecimalField(decimal_places=2, default=10, max_digits=9, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.RunPython(seed_shop_slabs, migrations.RunPython.noop),
    ]
