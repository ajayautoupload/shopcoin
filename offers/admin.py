from django.contrib import admin
from .models import ShopAd, ShopOffer


@admin.register(ShopOffer)
class ShopOfferAdmin(admin.ModelAdmin):
    list_display = ('title', 'shop', 'badge', 'is_active', 'is_demo', 'starts_at', 'ends_at')
    list_filter = ('is_active', 'is_demo', 'shop')
    search_fields = ('title', 'shop__name')


@admin.register(ShopAd)
class ShopAdAdmin(admin.ModelAdmin):
    list_display = ('title', 'shop', 'start_date', 'end_date', 'is_active', 'is_demo')
    list_filter = ('is_active', 'is_demo', 'shop')
    search_fields = ('title', 'shop__name')
