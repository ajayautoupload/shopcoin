from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.urls import reverse
from .forms import CustomerLoginForm, LoginForm, ShopkeeperRegistrationForm
from .models import UserProfile


def register_shopkeeper(request):
    form = ShopkeeperRegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user, backend='accounts.backends.MobileOrUsernameBackend')
        return redirect('shops:dashboard')
    return render(request, 'accounts/register.html', {'form': form, 'role_label': 'Shopkeeper', 'form_title': 'Register as a shopkeeper'})


class ShopCoinLoginView(LoginView):
    template_name = 'accounts/login.html'
    authentication_form = LoginForm
    # Keep the form available so the public Shopkeeper Login link can be used
    # to switch accounts even when a different role is already signed in.
    redirect_authenticated_user = False


class CustomerLoginView(LoginView):
    template_name = 'accounts/customer_login.html'
    authentication_form = CustomerLoginForm
    # A customer-login click must still show this form if an admin or
    # shopkeeper session is already active in the browser.
    redirect_authenticated_user = False

    def get_success_url(self):
        return reverse('customers:shop')


class ShopCoinLogoutView(LogoutView):
    next_page = 'core:home'


def role_redirect(request):
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    if request.user.is_superuser:
        return redirect('/admin/')
    profile = getattr(request.user, 'profile', None)
    if profile and (profile.is_deleted or not request.user.is_active):
        return redirect('core:home')
    if profile and profile.role == UserProfile.Role.CUSTOMER:
        return redirect('customers:dashboard')
    if profile and profile.role == UserProfile.Role.SHOPKEEPER:
        return redirect('shops:dashboard')
    return redirect('core:home')
