from django.contrib import admin
from django.db.models import Q, Sum
from django.utils import timezone
from .models import CoinLedger, CoinRedemption, CoinRule, CoinValue, Wallet, WebsiteEngagement, WebsiteEngagementStats


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('customer', 'balance', 'updated_at')
    search_fields = ('customer__user__first_name', 'customer__user__last_name', 'customer__phone')
    readonly_fields = ('updated_at',)

    def save_model(self, request, obj, form, change):
        previous_balance = Wallet.objects.get(pk=obj.pk).balance if change else 0
        super().save_model(request, obj, form, change)
        delta = obj.balance - previous_balance
        if delta:
            CoinLedger.objects.create(
                wallet=obj, shop=obj.customer.connected_shop,
                entry_type=CoinLedger.EntryType.ADJUSTMENT,
                coin_source=CoinLedger.Source.PURCHASE,
                coin_value_per_coin=10,
                coin_delta=delta, balance_before=previous_balance,
                balance_after=obj.balance,
                description='Administrator wallet balance adjustment.',
            )


@admin.register(CoinLedger)
class CoinLedgerAdmin(admin.ModelAdmin):
    list_display = ('wallet', 'shop', 'bill', 'entry_type', 'coin_source', 'coin_delta', 'coin_value_per_coin', 'balance_before', 'balance_after', 'redemption', 'is_reversed', 'expires_at', 'created_at')
    list_filter = ('entry_type', 'coin_source', 'is_reversed', 'shop', 'expires_at', 'created_at')
    readonly_fields = ('created_at',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        active_entries = CoinLedger.objects.filter(wallet=obj.wallet, is_reversed=False).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()),
        )
        balance = active_entries.aggregate(total=Sum('coin_delta'))['total'] or 0
        obj.wallet.balance = max(0, balance)
        obj.wallet.save(update_fields=('balance', 'updated_at'))

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(CoinValue)
class CoinValueAdmin(admin.ModelAdmin):
    list_display = ('shop', 'value_per_coin', 'is_active', 'is_demo', 'updated_at')
    list_filter = ('is_active', 'is_demo')


@admin.register(CoinRule)
class CoinRuleAdmin(admin.ModelAdmin):
    list_display = ('shop', 'purchase_amount', 'coin_value_per_coin', 'is_active', 'is_demo', 'sort_order')
    list_filter = ('shop', 'is_active', 'is_demo')
    fields = ('shop', 'purchase_amount', 'coins_awarded', 'coin_value_per_coin', 'is_active', 'is_demo', 'sort_order')


@admin.register(CoinRedemption)
class CoinRedemptionAdmin(admin.ModelAdmin):
    list_display = ('shop', 'customer', 'coins_redeemed', 'purchase_coins_redeemed', 'website_coins_redeemed', 'remaining_coin_balance', 'purchase_reward_value', 'website_reward_value', 'reward_value', 'redeemed_by', 'status', 'redeemed_at')
    list_filter = ('shop', 'status', 'redeemed_at')
    search_fields = ('customer__phone', 'customer__user__first_name', 'customer__user__last_name', 'redeemed_by__username')
    readonly_fields = ('idempotency_key', 'redeemed_at')

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(WebsiteEngagement)
class WebsiteEngagementAdmin(admin.ModelAdmin):
    list_display = ('customer', 'shop', 'visit_date', 'active_seconds', 'rewarded_at', 'reward_ledger')
    list_filter = ('shop', 'visit_date', 'rewarded_at')
    search_fields = ('customer__phone', 'customer__user__username', 'shop__name')
    readonly_fields = ('customer', 'shop', 'visit_date', 'active_seconds', 'session_token', 'last_ping_at', 'rewarded_at', 'reward_ledger')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(WebsiteEngagementStats)
class WebsiteEngagementStatsAdmin(admin.ModelAdmin):
    list_display = ('customer', 'current_streak', 'longest_streak', 'last_visit_date', 'total_website_coins', 'thirty_day_milestone_at')
    search_fields = ('customer__phone', 'customer__user__username')
