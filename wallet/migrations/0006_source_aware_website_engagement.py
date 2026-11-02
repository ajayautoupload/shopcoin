import uuid
from decimal import Decimal

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


def backfill_coin_source_snapshots(apps, schema_editor):
    CoinLedger = apps.get_model('wallet', 'CoinLedger')
    Bill = apps.get_model('transactions', 'Bill')
    CoinRedemption = apps.get_model('wallet', 'CoinRedemption')
    Wallet = apps.get_model('wallet', 'Wallet')
    database = schema_editor.connection.alias
    bills = {bill.bill_number: bill for bill in Bill.objects.using(database).all()}
    redemptions = {redemption.pk: redemption for redemption in CoinRedemption.objects.using(database).all()}
    for entry in CoinLedger.objects.using(database).all().iterator():
        updates = {}
        if entry.wallet_id:
            wallet_model = apps.get_model('wallet', 'Wallet')
            wallet = wallet_model.objects.using(database).select_related('customer').filter(pk=entry.wallet_id).first()
            if wallet and wallet.customer.connected_shop_id:
                updates['shop_id'] = wallet.customer.connected_shop_id
        if entry.redemption_id and entry.redemption_id in redemptions:
            redemption = redemptions[entry.redemption_id]
            updates['shop_id'] = redemption.shop_id
            updates['coin_value_per_coin'] = redemption.coin_value_per_coin
        description = entry.description or ''
        if description.startswith('Bill '):
            bill_number = description[5:].split(' · ', 1)[0]
            bill = bills.get(bill_number)
            if bill:
                updates.update(
                    shop_id=bill.shop_id,
                    coin_value_per_coin=bill.coin_value_per_coin or 10,
                    transaction_reference=bill.bill_number,
                    coin_source='PURCHASE',
                )
        if updates:
            CoinLedger.objects.using(database).filter(pk=entry.pk).update(**updates)

    for wallet in Wallet.objects.using(database).select_related('customer').all().iterator():
        active_total = sum(CoinLedger.objects.using(database).filter(
            wallet_id=wallet.pk, is_reversed=False, expires_at__isnull=True,
        ).values_list('coin_delta', flat=True))
        difference = wallet.balance - active_total
        if difference:
            CoinLedger.objects.using(database).create(
                wallet_id=wallet.pk,
                shop_id=wallet.customer.connected_shop_id,
                entry_type='ADJUSTMENT',
                coin_source='PURCHASE',
                coin_value_per_coin=Decimal('10.00'),
                coin_delta=difference,
                balance_before=max(0, active_total),
                balance_after=wallet.balance,
                description='Legacy wallet balance reconciliation.',
            )


def backfill_legacy_redemptions(apps, schema_editor):
    CoinRedemption = apps.get_model('wallet', 'CoinRedemption')
    database = schema_editor.connection.alias
    for redemption in CoinRedemption.objects.using(database).all().iterator():
        CoinRedemption.objects.using(database).filter(pk=redemption.pk).update(
            purchase_coins_redeemed=redemption.coins_redeemed,
            purchase_reward_value=redemption.reward_value,
            website_coins_redeemed=0,
            website_reward_value=Decimal('0.00'),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_alter_customerprofile_connected_shop'),
        ('shops', '0005_alter_shop_owner'),
        ('transactions', '0002_bill_cumulative_shopping_after'),
        ('wallet', '0005_coin_balance_slabs_and_reward_details'),
    ]

    operations = [
        migrations.AddField(
            model_name='coinledger', name='coin_source',
            field=models.CharField(choices=[('PURCHASE', 'Purchase'), ('WEBSITE_ENGAGEMENT', 'Website engagement')], db_index=True, default='PURCHASE', max_length=24),
        ),
        migrations.AddField(
            model_name='coinledger', name='coin_value_per_coin',
            field=models.DecimalField(decimal_places=2, default=10, max_digits=9, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AddField(
            model_name='coinledger', name='is_reversed',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name='coinledger', name='expires_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='coinledger', name='transaction_reference',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='coinledger', name='shop',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='coin_ledger_entries', to='shops.shop'),
        ),
        migrations.RunPython(backfill_coin_source_snapshots, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='coinledger', name='redemption',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ledger_entries', to='wallet.coinredemption'),
        ),
        migrations.AddField(
            model_name='coinredemption', name='purchase_coins_redeemed',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='coinredemption', name='website_coins_redeemed',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='coinredemption', name='purchase_reward_value',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='coinredemption', name='website_reward_value',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.RunPython(backfill_legacy_redemptions, migrations.RunPython.noop),
        migrations.CreateModel(
            name='WebsiteEngagement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('visit_date', models.DateField(db_index=True)),
                ('active_seconds', models.PositiveSmallIntegerField(default=0)),
                ('session_token', models.UUIDField(default=uuid.uuid4, editable=False)),
                ('last_ping_at', models.DateTimeField(blank=True, null=True)),
                ('rewarded_at', models.DateTimeField(blank=True, null=True)),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='website_engagements', to='accounts.customerprofile')),
                ('shop', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='website_engagements', to='shops.shop')),
                ('reward_ledger', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='website_engagement', to='wallet.coinledger')),
            ],
            options={'ordering': ('-visit_date', '-pk')},
        ),
        migrations.AddConstraint(
            model_name='websiteengagement',
            constraint=models.UniqueConstraint(fields=('customer', 'visit_date'), name='unique_customer_website_engagement_day'),
        ),
        migrations.CreateModel(
            name='WebsiteEngagementStats',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('current_streak', models.PositiveIntegerField(default=0)),
                ('longest_streak', models.PositiveIntegerField(default=0)),
                ('last_visit_date', models.DateField(blank=True, null=True)),
                ('total_website_coins', models.PositiveIntegerField(default=0)),
                ('customer', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='website_engagement_stats', to='accounts.customerprofile')),
            ],
        ),
        migrations.AddField(
            model_name='websiteengagementstats', name='thirty_day_milestone_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
