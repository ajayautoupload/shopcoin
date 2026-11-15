from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from .models import Product, Shop


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner_name', 'city', 'status', 'is_demo', 'created_at')
    list_filter = ('status', 'is_demo', 'city', 'created_at')
    search_fields = ('name', 'owner__username', 'owner__email', 'city', 'phone')
    readonly_fields = ('slug', 'created_at', 'updated_at')
    actions = ('approve_shops', 'reject_shops', 'suspend_shops')

    @admin.display(description='Owner', ordering='owner__first_name')
    def owner_name(self, obj):
        first_name = (obj.owner.first_name or '').strip()
        last_name = (obj.owner.last_name or '').strip()
        return ' '.join(part for part in (first_name, last_name) if part) or 'Name not provided'

    def _set_status(self, request, queryset, status, label):
        if not request.user.is_superuser:
            raise PermissionDenied
        count = 0
        for shop in queryset:
            shop.status = status
            shop.save(update_fields=('status', 'updated_at'))
            count += 1
        self.message_user(request, f'{count} shop(s) {label}.', messages.SUCCESS)

    @admin.action(description='Approve selected shops')
    def approve_shops(self, request, queryset):
        self._set_status(request, queryset, Shop.Status.APPROVED, 'approved')

    @admin.action(description='Reject selected shops')
    def reject_shops(self, request, queryset):
        self._set_status(request, queryset, Shop.Status.REJECTED, 'rejected')

    @admin.action(description='Suspend selected shops')
    def suspend_shops(self, request, queryset):
        self._set_status(request, queryset, Shop.Status.SUSPENDED, 'suspended')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'shop', 'price', 'discount_price', 'is_active', 'is_new', 'is_demo')
    list_filter = ('shop', 'is_active', 'is_new', 'is_demo', 'category')
    search_fields = ('name', 'shop__name', 'category')
    prepopulated_fields = {'slug': ('name',)}
    exclude = ('stock',)
