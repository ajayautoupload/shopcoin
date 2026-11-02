from django.shortcuts import redirect
from django.urls import path
from accounts.views import CustomerLoginView
from . import views

app_name = 'customers'
urlpatterns = [
    path('customer/login/', CustomerLoginView.as_view(), name='login'),
    path('customer/', views.dashboard, name='dashboard'),
    path('customer/engagement/start/', views.website_engagement_start, name='engagement_start'),
    path('customer/engagement/heartbeat/', views.website_engagement_heartbeat, name='engagement_heartbeat'),
    path('customer/wallet/', views.wallet, name='wallet'),
    path('customer/history/', views.shopping_history, name='history'),
    path('customer/history/<int:bill_id>/', views.bill_detail, name='bill_detail'),
    path('customer/shop/', views.shop, name='shop'),
    path('customer/coin-rules/', views.coin_rules, name='coin_rules'),
    path('customer/shop/<slug:slug>/', views.product_detail, name='product_detail'),
    path('customer/rewards/', lambda request: redirect('customers:shop'), name='rewards'),
    path('customer/shops/', lambda request: redirect('customers:shop'), name='shops'),
    path('customer/profile/', views.profile, name='profile'),
    path('customer/profile/edit/', views.edit_profile, name='edit_profile'),
    path('customer/profile/delete/', views.delete_account, name='delete_account'),
    path('customer/notifications/', views.notification_settings, name='notifications'),
    path('customer/scan/', views.placeholder, {'title': 'Scan QR'}, name='scan'),
    path('customer/privacy/', views.privacy_settings, name='privacy'),
    path('about/', views.public_placeholder, {'title': 'About Shop Coin'}, name='about'),
    path('terms/', views.public_placeholder, {'title': 'Terms & Conditions'}, name='terms'),
    path('privacy-policy/', views.public_placeholder, {'title': 'Privacy Policy'}, name='privacy_policy'),
    path('help/', views.public_placeholder, {'title': 'Help & Support'}, name='help'),
    path('account/password/', views.CustomerPasswordChangeView.as_view(), name='password_change'),
    path('account/password/done/', views.CustomerPasswordChangeDoneView.as_view(), name='password_change_done'),
]
