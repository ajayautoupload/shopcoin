from django.db import models
from django.utils import timezone


class ShopOffer(models.Model):
    shop = models.ForeignKey('shops.Shop', on_delete=models.CASCADE, related_name='offers')
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    badge = models.CharField(max_length=60, blank=True, help_text='For example: 20% OFF')
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    @property
    def is_current(self):
        now = timezone.now()
        return self.is_active and (self.starts_at is None or self.starts_at <= now) and (self.ends_at is None or self.ends_at > now)

    def __str__(self):
        return f'{self.title} · {self.shop.name}'


class ShopAd(models.Model):
    shop = models.ForeignKey('shops.Shop', on_delete=models.CASCADE, related_name='ads')
    image = models.ImageField(upload_to='shop_ads/')
    title = models.CharField(max_length=180)
    description = models.CharField(max_length=280)
    offer_text = models.CharField(max_length=120, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('start_date', '-created_at')
        indexes = [models.Index(fields=('shop', 'is_active', 'start_date', 'end_date'))]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'End date must be on or after the start date.'})

    def __str__(self):
        return f'{self.title} · {self.shop.name}'
