from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from .models import CustomerProfile, ShopkeeperProfile, UserProfile
from shops.models import Shop


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
    list_display = ('shopkeeper_name', 'business_name', 'phone', 'email', 'registered_shop_names', 'created_at')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'user__email', 'business_name', 'contact_email', 'phone', 'user__shops__name')
    readonly_fields = ('user_details', 'registered_shops', 'created_at', 'updated_at')
    fieldsets = (
        ('User and registered shops', {'fields': ('user', 'user_details', 'registered_shops')}),
        ('Shopkeeper contact', {'fields': ('business_name', 'phone', 'contact_email')}),
        ('Record dates', {'fields': ('created_at', 'updated_at')}),
    )

    @admin.display(description='Shopkeeper', ordering='user__first_name')
    def shopkeeper_name(self, obj):
        return obj.user.get_full_name().strip() or obj.user.get_username()

    @admin.display(description='Email')
    def email(self, obj):
        return obj.contact_email or obj.user.email or '—'

    @admin.display(description='Registered shops')
    def registered_shop_names(self, obj):
        names = list(Shop.objects.filter(owner=obj.user).order_by('name').values_list('name', flat=True))
        return ', '.join(names) or 'No registered shops'

    @admin.display(description='User details')
    def user_details(self, obj):
        full_name = obj.user.get_full_name().strip() or 'Name not provided'
        email = obj.contact_email or obj.user.email or 'Email not provided'
        return format_html('{} · {} · {}', full_name, obj.phone or 'Phone not provided', email)

    @admin.display(description='Registered shops')
    def registered_shops(self, obj):
        shops = Shop.objects.filter(owner=obj.user).order_by('name')
        links = format_html_join(
            ', ', '<a href="{}">{}</a>',
            ((reverse('admin:shops_shop_change', args=(shop.pk,)), shop.name) for shop in shops),
        )
        return links or 'No registered shops'
