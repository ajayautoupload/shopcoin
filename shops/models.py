from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils.text import slugify


class Shop(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        SUSPENDED = 'SUSPENDED', 'Suspended'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shops')
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to='shops/logos/', blank=True)
    banner = models.ImageField(upload_to='shops/banners/', blank=True)
    phone = models.CharField(max_length=16, validators=[RegexValidator(r'^\+?[0-9]{10,15}$', 'Enter a valid phone number (10–15 digits, optional leading +).')])
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10, validators=[RegexValidator(r'^[0-9A-Za-z -]{4,10}$', 'Enter a valid postal code.')])
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    is_demo = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)
        indexes = [models.Index(fields=('owner', 'status'))]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'shop'
            candidate = base
            suffix = 2
            while Shop.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{suffix}'
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='products/', blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    category = models.CharField(max_length=100, blank=True)
    sizes = models.CharField(max_length=180, blank=True, help_text='Comma-separated sizes, for example S, M, L, XL.')
    colors = models.CharField(max_length=180, blank=True, help_text='Comma-separated colors.')
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_new = models.BooleanField(default=False)
    is_demo = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [models.UniqueConstraint(fields=('shop', 'slug'), name='unique_product_slug_per_shop')]
        indexes = [models.Index(fields=('shop', 'is_active', '-created_at'))]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.discount_price is not None and self.discount_price >= self.price:
            raise ValidationError({'discount_price': 'Discounted price must be lower than the regular price.'})

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'product'
            candidate = base
            suffix = 2
            while Product.objects.filter(shop=self.shop, slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{suffix}'
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def effective_price(self):
        return self.discount_price if self.discount_price is not None else self.price

    def __str__(self):
        return f'{self.name} · {self.shop.name}'
