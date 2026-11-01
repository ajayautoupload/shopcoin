from django.contrib import admin
from .models import Bill, BillItem

class BillItemInline(admin.TabularInline):
    model = BillItem
    extra = 0
    readonly_fields = ('line_total',)

@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ('bill_number', 'shop', 'customer', 'total_amount', 'coins_earned', 'issued_at')
    list_filter = ('shop', 'issued_at')
    search_fields = ('bill_number', 'customer__phone', 'customer__user__first_name', 'customer__user__last_name')
    readonly_fields = ('bill_number', 'idempotency_key', 'issued_at', 'wallet_balance_before', 'wallet_balance_after')
    inlines = (BillItemInline,)

@admin.register(BillItem)
class BillItemAdmin(admin.ModelAdmin):
    list_display = ('product_name', 'bill', 'quantity', 'unit_price', 'line_total')
    search_fields = ('product_name', 'bill__bill_number')
