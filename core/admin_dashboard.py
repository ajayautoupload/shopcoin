from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomerProfile, ShopkeeperProfile, UserProfile
from notifications.models import InAppNotification
from offers.models import ShopAd, ShopOffer
from shops.models import Product, Shop
from transactions.models import Bill, BillPayment, Credit, CreditPayment
from wallet.models import (
    CoinLedger, CoinRedemption, CoinRedemptionRequest, CoinRule, Wallet,
    WebsiteEngagement, WebsiteEngagementStats,
)

User = get_user_model()


def _admin_list_url(model, query=''):
    url = reverse(f'admin:{model._meta.app_label}_{model._meta.model_name}_changelist')
    return f'{url}?q={query}' if query else url


def _date_window(request):
    today = timezone.localdate()
    period = request.GET.get('period', '30d')
    if period == 'today':
        start, end = today, today
    elif period == '7d':
        start, end = today - timedelta(days=6), today
    elif period == 'month':
        start, end = today.replace(day=1), today
    elif period == 'custom':
        try:
            start = date.fromisoformat(request.GET.get('start', ''))
            end = date.fromisoformat(request.GET.get('end', ''))
            if start > end:
                raise ValueError
        except (TypeError, ValueError):
            start, end, period = today - timedelta(days=29), today, '30d'
    else:
        start, end, period = today - timedelta(days=29), today, '30d'
    return period, start, end


def _daily_series(queryset, field, start, end, aggregate='total'):
    grouped = queryset.filter(**{f'{field}__date__gte': start, f'{field}__date__lte': end})
    rows = grouped.annotate(day=TruncDate(field)).values('day').annotate(value=aggregate).order_by('day')
    values = {row['day']: float(row['value'] or 0) for row in rows}
    days = (end - start).days
    if days > 90:
        return [{'label': day.isoformat(), 'value': values.get(day, 0)} for day in sorted(values)]
    return [
        {'label': (start + timedelta(days=offset)).strftime('%d %b'), 'value': values.get(start + timedelta(days=offset), 0)}
        for offset in range(days + 1)
    ]


def _global_search(query):
    if not query:
        return []
    lookups = [
        (Shop, Q(name__icontains=query) | Q(city__icontains=query), 'Shops'),
        (Product, Q(name__icontains=query) | Q(shop__name__icontains=query), 'Products'),
        (Bill, Q(bill_number__icontains=query) | Q(customer__phone__icontains=query), 'Bills'),
        (CustomerProfile, Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query) | Q(phone__icontains=query), 'Customers'),
        (ShopkeeperProfile, Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query) | Q(business_name__icontains=query), 'Shopkeepers'),
    ]
    results = []
    for model, predicate, label in lookups:
        for obj in model.objects.filter(predicate).order_by('-pk')[:3]:
            if model is Shop:
                title, description = obj.name, obj.city
            elif model is Product:
                title, description = obj.name, obj.shop.name
            elif model is Bill:
                title, description = obj.bill_number, obj.shop.name
            elif model is CustomerProfile:
                title = ' '.join(part for part in (obj.user.first_name, obj.user.last_name) if part) or obj.user.username
                description = obj.phone
            else:
                title = ' '.join(part for part in (obj.user.first_name, obj.user.last_name) if part) or obj.user.username
                description = obj.business_name
            results.append({'title': title, 'description': description, 'label': label, 'url': _admin_list_url(model, query)})
    return results[:10]


@login_required(login_url='/admin/login/')
def admin_dashboard(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    today = timezone.localdate()
    period, start, end = _date_window(request)
    completed_bills = Bill.objects.filter(status=Bill.Status.COMPLETED)
    completed_coins = CoinLedger.objects.filter(entry_type=CoinLedger.EntryType.EARN)
    total_sales = completed_bills.aggregate(value=Sum('total_amount'))['value'] or Decimal('0.00')
    outstanding_expression = ExpressionWrapper(F('original_amount') - F('paid_amount'), output_field=DecimalField(max_digits=12, decimal_places=2))
    outstanding_credit = Credit.objects.filter(status__in=(Credit.Status.UNPAID, Credit.Status.PARTIAL)).aggregate(value=Sum(outstanding_expression))['value'] or Decimal('0.00')
    purchase_issued = completed_coins.filter(coin_source=CoinLedger.Source.PURCHASE).aggregate(value=Sum('coin_delta'))['value'] or 0
    website_issued = completed_coins.filter(coin_source=CoinLedger.Source.WEBSITE_ENGAGEMENT).aggregate(value=Sum('coin_delta'))['value'] or 0
    pending_statuses = (CoinRedemptionRequest.Status.PENDING_CUSTOMER, CoinRedemptionRequest.Status.PENDING_SHOPKEEPER)

    cards = [
        {'label': 'Total Customers', 'value': CustomerProfile.objects.filter(is_deleted=False).count(), 'icon': 'fa-users', 'tone': 'blue', 'url': _admin_list_url(CustomerProfile)},
        {'label': 'Total Shopkeepers', 'value': ShopkeeperProfile.objects.count(), 'icon': 'fa-user-tie', 'tone': 'violet', 'url': _admin_list_url(ShopkeeperProfile)},
        {'label': 'Registered Shops', 'value': Shop.objects.count(), 'icon': 'fa-store', 'tone': 'green', 'url': _admin_list_url(Shop)},
        {'label': 'Total Products', 'value': Product.objects.count(), 'icon': 'fa-box-open', 'tone': 'orange', 'url': _admin_list_url(Product)},
        {'label': 'Total Bills', 'value': Bill.objects.count(), 'icon': 'fa-receipt', 'tone': 'cyan', 'url': _admin_list_url(Bill)},
        {'label': 'Total Sales', 'value': f'₹{total_sales:,.2f}', 'icon': 'fa-indian-rupee-sign', 'tone': 'green', 'url': _admin_list_url(Bill)},
        {'label': 'Purchase Coins Issued', 'value': f'{purchase_issued:,}', 'icon': 'fa-coins', 'tone': 'gold', 'url': _admin_list_url(CoinLedger)},
        {'label': 'Website Coins Issued', 'value': f'{website_issued:,}', 'icon': 'fa-globe', 'tone': 'blue', 'url': _admin_list_url(WebsiteEngagementStats)},
        {'label': 'Coins Redeemed', 'value': f'{CoinRedemption.objects.aggregate(value=Sum("coins_redeemed"))["value"] or 0:,}', 'icon': 'fa-arrow-rotate-left', 'tone': 'violet', 'url': _admin_list_url(CoinRedemption)},
        {'label': 'Pending Redemption Requests', 'value': CoinRedemptionRequest.objects.filter(status__in=pending_statuses).count(), 'icon': 'fa-hourglass-half', 'tone': 'orange', 'url': _admin_list_url(CoinRedemptionRequest)},
        {'label': 'Outstanding Udhar', 'value': f'₹{outstanding_credit:,.2f}', 'icon': 'fa-hand-holding-dollar', 'tone': 'red', 'url': _admin_list_url(Credit)},
    ]

    sales_window = completed_bills.filter(issued_at__date__gte=start, issued_at__date__lte=end)
    customer_window = CustomerProfile.objects.filter(date_joined__date__gte=start, date_joined__date__lte=end)
    shopkeeper_window = ShopkeeperProfile.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
    purchase_window = completed_coins.filter(coin_source=CoinLedger.Source.PURCHASE, created_at__date__gte=start, created_at__date__lte=end)
    redemption_window = CoinRedemption.objects.filter(redeemed_at__date__gte=start, redeemed_at__date__lte=end)
    engagement_window = WebsiteEngagement.objects.filter(visit_date__gte=start, visit_date__lte=end)

    sales_series = _daily_series(sales_window, 'issued_at', start, end, Sum('total_amount'))
    customers_series = _daily_series(customer_window, 'date_joined', start, end, Count('pk'))
    shopkeepers_series = _daily_series(shopkeeper_window, 'created_at', start, end, Count('pk'))
    purchases_series = _daily_series(purchase_window, 'created_at', start, end, Sum('coin_delta'))
    redemptions_series = _daily_series(redemption_window, 'redeemed_at', start, end, Sum('coins_redeemed'))
    engagement_rows = engagement_window.values('visit_date').annotate(value=Count('pk')).order_by('visit_date')
    engagement_values = {row['visit_date']: row['value'] for row in engagement_rows}
    engagement_series = [
        {'label': (start + timedelta(days=i)).strftime('%d %b'), 'value': engagement_values.get(start + timedelta(days=i), 0)}
        for i in range((end - start).days + 1)
    ]
    month_start = (today.replace(day=1) - timedelta(days=335)).replace(day=1)
    monthly_rows = completed_bills.filter(issued_at__date__gte=month_start, issued_at__date__lte=today).annotate(month=TruncMonth('issued_at')).values('month').annotate(value=Sum('total_amount')).order_by('month')
    monthly_sales = [{'label': row['month'].strftime('%b %Y'), 'value': float(row['value'] or 0)} for row in monthly_rows]
    shop_rows = completed_bills.filter(issued_at__date__gte=start, issued_at__date__lte=end).values('shop__name').annotate(value=Sum('total_amount')).order_by('-value')[:7]

    query = request.GET.get('q', '').strip()[:100]
    context = {
        'cards': cards,
        'period': period, 'start': start, 'end': end, 'today': today,
        'query': query, 'search_results': _global_search(query),
        'sales_total_window': sales_window.aggregate(value=Sum('total_amount'))['value'] or Decimal('0.00'),
        'sales_series': sales_series, 'monthly_sales': monthly_sales,
        'customers_series': customers_series, 'shopkeepers_series': shopkeepers_series,
        'purchases_series': purchases_series, 'redemptions_series': redemptions_series,
        'engagement_series': engagement_series,
        'shop_sales': [{'label': row['shop__name'], 'value': float(row['value'] or 0)} for row in shop_rows],
        'chart_payload': {
            'sales': sales_series,
            'monthly': monthly_sales,
            'customers': customers_series,
            'shopkeepers': shopkeepers_series,
            'purchases': purchases_series,
            'redemptions': redemptions_series,
            'engagement': engagement_series,
            'shops': [{'label': row['shop__name'], 'value': float(row['value'] or 0)} for row in shop_rows],
        },
        'recent_customers': CustomerProfile.objects.select_related('user').order_by('-date_joined')[:6],
        'recent_shopkeepers': ShopkeeperProfile.objects.select_related('user').order_by('-created_at')[:6],
        'recent_bills': Bill.objects.select_related('shop', 'customer__user').order_by('-issued_at')[:6],
        'recent_redemptions': CoinRedemption.objects.select_related('customer__user', 'shop', 'redeemed_by').order_by('-redeemed_at')[:6],
        'pending_requests': CoinRedemptionRequest.objects.filter(status__in=pending_statuses).select_related('customer__user', 'shop', 'requested_by').order_by('-created_at')[:6],
        'recent_notifications': InAppNotification.objects.select_related('user').order_by('-created_at')[:6],
        'unread_notifications': InAppNotification.objects.filter(user=request.user, read_at__isnull=True).count(),
        'quick_links': [
            {'label': 'All Users', 'url': _admin_list_url(User), 'icon': 'fa-users'},
            {'label': 'Customers', 'url': _admin_list_url(CustomerProfile), 'icon': 'fa-user-group'},
            {'label': 'Shopkeepers', 'url': _admin_list_url(ShopkeeperProfile), 'icon': 'fa-user-tie'},
            {'label': 'Registered Shops', 'url': _admin_list_url(Shop), 'icon': 'fa-store'},
            {'label': 'Products', 'url': _admin_list_url(Product), 'icon': 'fa-box-open'},
            {'label': 'Bills', 'url': _admin_list_url(Bill), 'icon': 'fa-receipt'},
            {'label': 'Payments', 'url': _admin_list_url(BillPayment), 'icon': 'fa-money-bill-transfer'},
            {'label': 'Udhar / Credit', 'url': _admin_list_url(Credit), 'icon': 'fa-hand-holding-dollar'},
            {'label': 'Purchase Coin Rules', 'url': _admin_list_url(CoinRule), 'icon': 'fa-coins'},
            {'label': 'Website Coins', 'url': _admin_list_url(WebsiteEngagementStats), 'icon': 'fa-globe'},
            {'label': 'Coin Wallets', 'url': _admin_list_url(Wallet), 'icon': 'fa-wallet'},
            {'label': 'Coin Redemption Requests', 'url': _admin_list_url(CoinRedemptionRequest), 'icon': 'fa-circle-check'},
            {'label': 'Redemption History', 'url': _admin_list_url(CoinRedemption), 'icon': 'fa-clock-rotate-left'},
            {'label': 'Coin Ledger', 'url': _admin_list_url(CoinLedger), 'icon': 'fa-list'},
            {'label': 'Website Engagement', 'url': _admin_list_url(WebsiteEngagement), 'icon': 'fa-chart-line'},
            {'label': 'Offers', 'url': _admin_list_url(ShopOffer), 'icon': 'fa-tags'},
            {'label': 'Advertisements', 'url': _admin_list_url(ShopAd), 'icon': 'fa-rectangle-ad'},
            {'label': 'Notifications', 'url': _admin_list_url(InAppNotification), 'icon': 'fa-bell'},
        ],
        'profile_url': reverse('admin:auth_user_change', args=(request.user.pk,)),
    }
    return render(request, 'admin/dashboard.html', context)
