from django.contrib import admin
from django import forms
from decimal import Decimal
from .models import CoinLedger, CoinRedemption, CoinRule, CoinValue, Wallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('customer', 'balance', 'updated_at')
    search_fields = ('customer__user__first_name', 'customer__user__last_name', 'customer__phone')
    readonly_fields = ('updated_at',)


@admin.register(CoinLedger)
class CoinLedgerAdmin(admin.ModelAdmin):
    list_display = ('wallet', 'entry_type', 'coin_delta', 'balance_before', 'balance_after', 'redemption', 'created_at')
    list_filter = ('entry_type', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(CoinValue)
class CoinValueAdmin(admin.ModelAdmin):
    list_display = ('shop', 'value_per_coin', 'is_active', 'is_demo', 'updated_at')
    list_filter = ('is_active', 'is_demo')


@admin.register(CoinRule)
class CoinRuleAdmin(admin.ModelAdmin):
    list_display = ('shop', 'coin_balance_threshold', 'coin_value_per_coin', 'is_active', 'is_demo', 'sort_order')
    list_filter = ('shop', 'is_active', 'is_demo')
    fields = ('shop', 'coin_balance_threshold', 'coin_value_per_coin', 'is_active', 'is_demo', 'sort_order')

    class RuleForm(forms.ModelForm):
        coin_balance_threshold = forms.IntegerField(min_value=0)

        class Meta:
            model = CoinRule
            fields = ('shop', 'coin_balance_threshold', 'coin_value_per_coin', 'is_active', 'is_demo', 'sort_order')

    form = RuleForm

    def save_model(self, request, obj, form, change):
        if not change:
            obj.purchase_amount = Decimal('1000.00') + Decimal(obj.coin_balance_threshold)
            obj.coins_awarded = obj.coin_balance_threshold
            obj.reward_value = Decimal(obj.coin_balance_threshold) * obj.coin_value_per_coin
        super().save_model(request, obj, form, change)


@admin.register(CoinRedemption)
class CoinRedemptionAdmin(admin.ModelAdmin):
    list_display = ('shop', 'customer', 'coins_redeemed', 'remaining_coin_balance', 'coin_value_per_coin', 'reward_value', 'redeemed_by', 'status', 'redeemed_at')
    list_filter = ('shop', 'status', 'redeemed_at')
    search_fields = ('customer__phone', 'customer__user__first_name', 'customer__user__last_name', 'redeemed_by__username')
    readonly_fields = ('idempotency_key', 'redeemed_at')
