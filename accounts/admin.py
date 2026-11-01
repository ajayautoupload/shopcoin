from django.contrib import admin
from .models import CustomerProfile, ShopkeeperProfile, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'is_demo', 'created_at')
    list_filter = ('role', 'is_demo')
    search_fields = ('user__username', 'user__email')


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'connected_shop', 'city', 'date_joined')
    list_filter = ('connected_shop', 'city')
    search_fields = ('user__username', 'user__email', 'phone')


@admin.register(ShopkeeperProfile)
class ShopkeeperProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'business_name', 'phone', 'created_at')
    search_fields = ('user__username', 'user__email', 'business_name', 'phone')
