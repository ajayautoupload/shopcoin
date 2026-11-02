from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError
from .models import Bill, BillItem
from .services import set_bill_status

class BillItemInline(admin.TabularInline):
    model = BillItem
    extra = 0
    readonly_fields = ('line_total',)

@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ('bill_number', 'shop', 'customer', 'total_amount', 'coins_earned', 'status', 'issued_at')
    list_filter = ('shop', 'status', 'issued_at')
    search_fields = ('bill_number', 'customer__phone', 'customer__user__first_name', 'customer__user__last_name')
    readonly_fields = ('bill_number', 'idempotency_key', 'issued_at', 'wallet_balance_before', 'wallet_balance_after')
    inlines = (BillItemInline,)

    def save_model(self, request, obj, form, change):
        if change:
            previous = Bill.objects.get(pk=obj.pk)
            if obj.status != previous.status:
                try:
                    set_bill_status(bill_id=obj.pk, status=obj.status)
                except ValidationError as error:
                    obj.status = previous.status
                    messages.error(request, ' '.join(error.messages))
        super().save_model(request, obj, form, change)

@admin.register(BillItem)
class BillItemAdmin(admin.ModelAdmin):
    list_display = ('product_name', 'bill', 'quantity', 'unit_price', 'line_total')
    search_fields = ('product_name', 'bill__bill_number')
