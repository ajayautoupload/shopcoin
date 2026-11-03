from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth import views as auth_views
from django.contrib.auth import logout
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.utils.decorators import method_decorator
from accounts.decorators import customer_required
from accounts.forms import CustomerProfileForm, NotificationSettingsForm, PrivacySettingsForm
from offers.models import ShopAd
from shops.models import Product, Shop
from accounts.services import deactivate_customer_account
from wallet.models import CoinRedemption, CoinRule, WebsiteEngagement
from wallet.services import begin_website_engagement, get_customer_coin_summary, record_website_engagement_heartbeat
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from decimal import Decimal
from transactions.models import Bill
from transactions.models import Credit


@customer_required
def dashboard(request):
    profile = request.user.customer_profile
    shop = profile.connected_shop
    products = Product.objects.none()
    offers = []
    ads = []
    if shop and shop.status == Shop.Status.APPROVED:
        products = Product.objects.filter(shop=shop, is_active=True).order_by('-is_new', '-created_at')[:8]
        today = timezone.localdate()
        ads = ShopAd.objects.filter(
            shop=shop, is_active=True, start_date__lte=today, end_date__gte=today,
        ).order_by('display_order', 'start_date', '-created_at')
        offers = shop.offers.filter(is_active=True).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=timezone.now()),
            Q(ends_at__isnull=True) | Q(ends_at__gt=timezone.now()),
        )
    coin_summary = get_customer_coin_summary(profile, shop)
    wallet = coin_summary['wallet']
    recent_bills = Bill.objects.filter(customer=profile).select_related('shop').prefetch_related('items')[:5]
    historical = Bill.objects.filter(customer=profile, status=Bill.Status.COMPLETED).aggregate(total_bills=Count('pk'), total_coins_earned=Coalesce(Sum('coins_earned'), 0))
    summary = {**coin_summary, **historical, 'total_spent': coin_summary['total_shopping'], 'total_coins': coin_summary['active_coins']}
    today_engagement = WebsiteEngagement.objects.filter(customer=profile, visit_date=timezone.localdate()).first()
    return render(request, 'customer/dashboard.html', {'profile': profile, 'shop': shop, 'products': products, 'offers': offers, 'ads': ads, 'wallet': wallet, 'current_worth': summary['current_reward_value'], 'recent_bills': recent_bills, 'summary': summary, 'coin_worth': summary['current_reward_value'], 'today_engagement': today_engagement})


@customer_required
def my_credit(request):
    profile = request.user.customer_profile
    credits = Credit.objects.filter(customer=profile, shop=profile.connected_shop).select_related('shop', 'bill').prefetch_related('payments__coin_ledger') if profile.connected_shop_id else Credit.objects.none()
    totals = credits.aggregate(original=Coalesce(Sum('original_amount'), Decimal('0.00')), paid=Coalesce(Sum('paid_amount'), Decimal('0.00')))
    return render(request, 'customer/credit.html', {'credits': credits, 'total_original': totals['original'], 'total_paid': totals['paid'], 'total_remaining': totals['original'] - totals['paid']})


@customer_required
@require_POST
def website_engagement_start(request):
    profile = request.user.customer_profile
    engagement = begin_website_engagement(customer=profile)
    if engagement is None:
        return JsonResponse({'eligible': False}, status=400)
    return JsonResponse({
        'eligible': True,
        'session_token': str(engagement.session_token),
        'active_seconds': engagement.active_seconds,
        'complete': bool(engagement.rewarded_at),
    })


@customer_required
@require_POST
def website_engagement_heartbeat(request):
    result = record_website_engagement_heartbeat(
        customer=request.user.customer_profile,
        session_token=request.POST.get('session_token'),
    )
    if result.get('reason'):
        return JsonResponse(result, status=400)
    return JsonResponse(result)


@customer_required
def shopping_history(request):
    profile = request.user.customer_profile
    bills = Bill.objects.filter(customer=profile).select_related('shop').prefetch_related('items')
    summary = bills.filter(status=Bill.Status.COMPLETED).aggregate(total_spent=Coalesce(Sum('total_amount'), Decimal('0.00')), total_bills=Count('pk', distinct=True), total_coins=Coalesce(Sum('coins_earned'), 0), reward_value=Coalesce(Sum('coin_value_amount'), Decimal('0.00')))
    coin_summary = get_customer_coin_summary(profile)
    summary.update(active_coins=coin_summary['active_coins'], current_reward_value=coin_summary['current_reward_value'])
    redemptions = CoinRedemption.objects.filter(customer=profile).select_related('shop').order_by('-redeemed_at')
    return render(request, 'customer/shopping_history.html', {'bills': bills, 'summary': summary, 'redemptions': redemptions})


@customer_required
def bill_detail(request, bill_id):
    bill = get_object_or_404(Bill.objects.select_related('shop', 'coin_rule').prefetch_related('items'), pk=bill_id, customer=request.user.customer_profile)
    return render(request, 'customer/bill_detail.html', {'bill': bill})


@customer_required
def placeholder(request, title):
    return render(request, 'shared/placeholder.html', {'title': title})


def public_placeholder(request, title):
    return render(request, 'shared/placeholder.html', {'title': title})


@customer_required
def wallet(request):
    profile = request.user.customer_profile
    coin_summary = get_customer_coin_summary(profile)
    wallet = coin_summary['wallet']
    rules = CoinRule.objects.filter(shop=profile.connected_shop, is_active=True, purchase_amount__in=(Decimal('1000.00'), Decimal('5000.00'), Decimal('10000.00'))) if profile.connected_shop else CoinRule.objects.none()
    redemptions = CoinRedemption.objects.filter(customer=profile).select_related('shop').order_by('-redeemed_at')
    return render(request, 'customer/wallet.html', {
        'profile': profile, 'shop': profile.connected_shop, 'wallet': wallet,
        'coin_summary': coin_summary, 'rules': rules, 'redemptions': redemptions,
        'entries': wallet.entries.all()[:10],
    })


@customer_required
def shop(request):
    profile = request.user.customer_profile
    connected_shop = profile.connected_shop
    products = Product.objects.none()
    offers = []
    ads = []
    if connected_shop and connected_shop.status == Shop.Status.APPROVED:
        products = Product.objects.filter(shop=connected_shop, is_active=True).order_by('-is_new', '-created_at')
        today = timezone.localdate()
        ads = ShopAd.objects.filter(
            shop=connected_shop, is_active=True, start_date__lte=today, end_date__gte=today,
        ).order_by('display_order', 'start_date', '-created_at')
        offers = connected_shop.offers.filter(is_active=True).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=timezone.now()),
            Q(ends_at__isnull=True) | Q(ends_at__gt=timezone.now()),
        )
    categories = products.exclude(category='').values_list('category', flat=True).distinct()
    return render(request, 'customer/shop.html', {'profile': profile, 'shop': connected_shop, 'products': products, 'offers': offers, 'ads': ads, 'categories': categories})


@customer_required
def coin_rules(request):
    profile = request.user.customer_profile
    shop = profile.connected_shop
    rules = CoinRule.objects.filter(shop=shop, is_active=True, purchase_amount__in=(Decimal('1000.00'), Decimal('5000.00'), Decimal('10000.00'))) if shop else CoinRule.objects.none()
    ranges = {Decimal('1000.00'): '₹1,000–₹4,999', Decimal('5000.00'): '₹5,000–₹9,999', Decimal('10000.00'): '₹10,000+'}
    rule_slabs = [{'rule': rule, 'range': ranges[rule.purchase_amount]} for rule in rules if rule.purchase_amount in ranges]
    return render(request, 'shared/coin_rules.html', {
        'shop': shop, 'rules': rules,
        'rule_slabs': rule_slabs,
        'audience': 'customer',
    })


@customer_required
def product_detail(request, slug):
    profile = request.user.customer_profile
    if not profile.connected_shop_id:
        get_object_or_404(Product, pk=-1)
    product = get_object_or_404(
        Product.objects.select_related('shop'),
        slug=slug,
        shop_id=profile.connected_shop_id,
        shop__status=Shop.Status.APPROVED,
        is_active=True,
    )
    return render(request, 'customer/product_detail.html', {'product': product, 'shop': profile.connected_shop})


@customer_required
def profile(request):
    profile = request.user.customer_profile
    summary = get_customer_coin_summary(profile)
    wallet = summary['wallet']
    return render(request, 'accounts/profile_overview.html', {
        'profile': profile, 'shop': profile.connected_shop, 'wallet': wallet,
        'summary': {**summary, 'total_spent': summary['total_shopping'], 'total_coins': summary['active_coins']},
    })


@customer_required
@require_http_methods(['GET', 'POST'])
def delete_account(request):
    if request.method == 'POST':
        if request.POST.get('confirm_delete') != 'yes':
            return render(request, 'customer/delete_account.html', {'confirmation_error': 'Please confirm account deletion.'})
        deactivate_customer_account(request.user)
        logout(request)
        messages.success(request, 'Your account has been deactivated.')
        return redirect('core:home')
    return render(request, 'customer/delete_account.html')


@customer_required
def edit_profile(request):
    instance = request.user.customer_profile
    data = request.POST if request.method == 'POST' else None
    files = request.FILES if request.method == 'POST' else None
    form = CustomerProfileForm(data, files, instance=instance, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Your profile has been updated.')
        return redirect('customers:profile')
    return render(request, 'accounts/profile.html', {'form': form, 'profile_title': 'Edit profile', 'profile': instance})


@customer_required
def notification_settings(request):
    profile = request.user.customer_profile
    data = request.POST if request.method == 'POST' else None
    form = NotificationSettingsForm(data, instance=profile)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Notification settings saved.')
        return redirect('customers:notifications')
    return render(request, 'accounts/preferences.html', {
        'form': form, 'settings_title': 'Notification settings',
        'settings_description': 'Choose whether Shop Coin can send account and rewards updates.',
    })


@customer_required
def privacy_settings(request):
    profile = request.user.customer_profile
    data = request.POST if request.method == 'POST' else None
    form = PrivacySettingsForm(data, instance=profile)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Privacy settings saved.')
        return redirect('customers:privacy')
    return render(request, 'accounts/preferences.html', {
        'form': form, 'settings_title': 'Privacy settings',
        'settings_description': 'Manage how your profile information is used in Shop Coin.',
    })


@method_decorator(customer_required, name='dispatch')
class CustomerPasswordChangeView(auth_views.PasswordChangeView):
    template_name = 'accounts/password_change.html'
    success_url = '/customer/profile/'


@method_decorator(customer_required, name='dispatch')
class CustomerPasswordChangeDoneView(auth_views.PasswordChangeDoneView):
    template_name = 'accounts/password_change_done.html'
