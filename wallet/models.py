from django.core.validators import MinValueValidator
from django.conf import settings
from django.db import models
import uuid
from accounts.models import CustomerProfile


class Wallet(models.Model):
    customer = models.OneToOneField(CustomerProfile, on_delete=models.CASCADE, related_name='wallet')
    balance = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Wallet: {self.customer.user}'


class CoinLedger(models.Model):
    class EntryType(models.TextChoices):
        EARN = 'EARN', 'Earned'
        REDEEM = 'REDEEM', 'Redeemed'
        ADJUSTMENT = 'ADJUSTMENT', 'Adjustment'
        ACCOUNT_DELETION = 'ACCOUNT_DELETION', 'Account deletion'

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='entries')
    redemption = models.OneToOneField('CoinRedemption', on_delete=models.SET_NULL, null=True, blank=True, related_name='ledger')
    entry_type = models.CharField(max_length=24, choices=EntryType.choices)
    coin_delta = models.IntegerField()
    balance_before = models.PositiveIntegerField()
    balance_after = models.PositiveIntegerField()
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('-created_at', '-pk')
        constraints = [
            models.CheckConstraint(condition=models.Q(balance_before__gte=0), name='ledger_balance_before_nonnegative'),
            models.CheckConstraint(condition=models.Q(balance_after__gte=0), name='ledger_balance_after_nonnegative'),
        ]

    def __str__(self):
        return f'{self.get_entry_type_display()} · {self.coin_delta} coins'


class CoinValue(models.Model):
    shop = models.OneToOneField('shops.Shop', on_delete=models.CASCADE, related_name='coin_value_settings')
    value_per_coin = models.DecimalField(max_digits=9, decimal_places=2, validators=[MinValueValidator(0)])
    is_active = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.shop.name}: ₹{self.value_per_coin} per coin'


class CoinRule(models.Model):
    shop = models.ForeignKey('shops.Shop', on_delete=models.CASCADE, related_name='coin_rules')
    # purchase_amount is retained for historical configuration compatibility.
    purchase_amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    coin_balance_threshold = models.PositiveIntegerField(null=True, blank=True)
    coins_awarded = models.PositiveIntegerField()
    coin_value_per_coin = models.DecimalField(max_digits=9, decimal_places=2, default=10, validators=[MinValueValidator(0)])
    reward_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    is_active = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=False, db_index=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ('sort_order', 'coin_balance_threshold', 'purchase_amount')
        constraints = [
            models.UniqueConstraint(fields=('shop', 'purchase_amount'), name='unique_coin_rule_per_shop_purchase'),
            models.UniqueConstraint(
                fields=('shop', 'coin_balance_threshold'),
                condition=models.Q(coin_balance_threshold__isnull=False),
                name='unique_coin_rule_shop_balance_threshold',
            ),
        ]

    def __str__(self):
        return f'{self.shop.name}: {self.coin_balance_threshold}+ coins at ₹{self.coin_value_per_coin} each'


class CoinRedemption(models.Model):
    class Status(models.TextChoices):
        COMPLETED = 'COMPLETED', 'Completed'

    customer = models.ForeignKey(CustomerProfile, on_delete=models.CASCADE, related_name='coin_redemptions')
    shop = models.ForeignKey('shops.Shop', on_delete=models.CASCADE, related_name='coin_redemptions')
    redeemed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='coin_redemptions')
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    coins_redeemed = models.PositiveIntegerField()
    remaining_coin_balance = models.PositiveIntegerField(default=0)
    coin_value_per_coin = models.DecimalField(max_digits=9, decimal_places=2)
    reward_value = models.DecimalField(max_digits=12, decimal_places=2)
    reward_description = models.TextField(blank=True)
    cumulative_shopping = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.COMPLETED)
    redeemed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('-redeemed_at', '-pk')
        indexes = [models.Index(fields=('shop', '-redeemed_at'))]

    def __str__(self):
        return f'{self.coins_redeemed} coins redeemed · {self.customer}'
