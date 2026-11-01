import uuid
from django.utils import timezone

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Bill(models.Model):
    bill_number = models.CharField(max_length=48, unique=True, editable=False)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    shop = models.ForeignKey('shops.Shop', on_delete=models.CASCADE, related_name='bills')
    customer = models.ForeignKey('accounts.CustomerProfile', on_delete=models.CASCADE, related_name='bills')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_bills')
    coin_rule = models.ForeignKey('wallet.CoinRule', on_delete=models.SET_NULL, null=True, blank=True, related_name='bills')
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    coins_earned = models.PositiveIntegerField(default=0)
    coin_value_per_coin = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    coin_value_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    wallet_balance_before = models.PositiveIntegerField(default=0)
    wallet_balance_after = models.PositiveIntegerField(default=0)
    cumulative_shopping_after = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    issued_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('-issued_at', '-pk')
        indexes = [
            models.Index(fields=('shop', '-issued_at')),
            models.Index(fields=('customer', '-issued_at')),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(discount__lte=models.F('subtotal')), name='bill_discount_within_subtotal'),
            models.CheckConstraint(condition=models.Q(total_amount__gte=0), name='bill_total_nonnegative'),
        ]

    def __str__(self):
        return self.bill_number

    def save(self, *args, **kwargs):
        if not self.bill_number and self.shop_id:
            self.bill_number = f'SC{self.shop_id}-{timezone.localtime():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:12].upper()}'
        super().save(*args, **kwargs)


class BillItem(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('shops.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='bill_items')
    product_name = models.CharField(max_length=180)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    line_total = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ('pk',)
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gte=1), name='bill_item_quantity_positive')]

    def __str__(self):
        return f'{self.product_name} × {self.quantity}'
