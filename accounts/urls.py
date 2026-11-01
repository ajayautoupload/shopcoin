from django.urls import path
from . import views

app_name = 'accounts'
urlpatterns = [
    path('register/shopkeeper/', views.register_shopkeeper, name='register_shopkeeper'),
    path('login/', views.ShopCoinLoginView.as_view(), name='login'),
    path('logout/', views.ShopCoinLogoutView.as_view(), name='logout'),
    path('account/continue/', views.role_redirect, name='role_redirect'),
]
