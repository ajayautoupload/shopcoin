from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError
from .models import Bill, BillItem, Credit, CreditPayment, CreditPaymentReversal
from .services import set_bill_status
from .credit_services import reverse_credit_payment

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


@admin.action(description='Reverse selected credit payment(s) with audit entries')
def reverse_credit_payments(modeladmin, request, queryset):
    reversed_count = 0
    for payment in queryset.select_related('credit__shop'):
        try:
            _, created = reverse_credit_payment(actor=request.user, shop=payment.credit.shop, payment_id=payment.pk)
        except ValidationError as error:
            messages.error(request, f'Payment {payment.payment_reference}: {" ".join(error.messages)}')
        else:
            reversed_count += int(created)
    if reversed_count:
        messages.success(request, f'{reversed_count} credit payment(s) reversed.')


@admin.register(CreditPayment)
class CreditPaymentAdmin(admin.ModelAdmin):
    list_display = ('payment_reference', 'credit', 'amount', 'received_by', 'created_at')
    search_fields = ('payment_reference', 'credit__customer__phone', 'credit__customer__user__first_name')
    readonly_fields = ('payment_reference', 'credit', 'amount', 'balance_after', 'received_by', 'coin_ledger', 'created_at')
    actions = (reverse_credit_payments,)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CreditPaymentReversal)
class CreditPaymentReversalAdmin(admin.ModelAdmin):
    list_display = ('reference', 'payment', 'amount', 'reversed_by', 'created_at')
    readonly_fields = ('payment', 'amount', 'reference', 'reversed_by', 'coin_ledger', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Credit)
class CreditAdmin(admin.ModelAdmin):
    list_display = ('id', 'shop', 'customer', 'original_amount', 'paid_amount', 'status', 'created_at')
    list_filter = ('shop', 'status', 'created_at')
    search_fields = ('customer__phone', 'customer__user__first_name', 'customer__user__last_name', 'reference')
    readonly_fields = ('paid_amount', 'status', 'created_at', 'updated_at')
