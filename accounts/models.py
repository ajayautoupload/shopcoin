from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

phone_validator = RegexValidator(r'^\+?[0-9]{10,15}$', 'Enter a valid phone number (10–15 digits, optional leading +).')


class UserProfile(models.Model):
    class Role(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer'
        SHOPKEEPER = 'SHOPKEEPER', 'Shopkeeper'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=12, choices=Role.choices)
    is_demo = models.BooleanField(default=False, db_index=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='deleted_customer_accounts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user} ({self.get_role_display()})'


class CustomerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_profile')
    connected_shop = models.ForeignKey('shops.Shop', on_delete=models.SET_NULL, related_name='connected_customers', null=True, blank=True)
    phone = models.CharField(max_length=16, validators=[phone_validator], blank=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    image = models.ImageField(upload_to='profiles/customers/', blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    notifications_enabled = models.BooleanField(default=True, verbose_name='Enable Shop Coin notifications', help_text='Receive account and rewards updates.')
    privacy_show_name = models.BooleanField(default=False, verbose_name='Show my name to my connected shop', help_text='Let your connected shop see your name with your customer account.')
    date_joined = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('phone',), condition=Q(is_deleted=False) & ~Q(phone=''), name='unique_active_customer_phone')]

    def __str__(self):
        return f'Customer: {self.user}'


class ShopkeeperProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shopkeeper_profile')
    phone = models.CharField(max_length=16, validators=[phone_validator])
    business_name = models.CharField(max_length=160, blank=True)
    contact_email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Shopkeeper: {self.user}'
