from functools import wraps
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import redirect
from .models import UserProfile


def role_required(role, login_url=None):
    def decorator(view):
        @login_required(login_url=login_url)
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            profile = getattr(request.user, 'profile', None)
            if profile and (profile.is_deleted or not request.user.is_active):
                messages.error(request, 'This account is inactive.')
                return redirect('core:home')
            if profile is None or profile.role != role or profile.is_deleted or not request.user.is_active:
                messages.error(request, 'You do not have access to that page.')
                if request.user.is_superuser:
                    return redirect('/admin/')
                if profile and profile.role == UserProfile.Role.CUSTOMER:
                    return redirect('customers:dashboard')
                if profile and profile.role == UserProfile.Role.SHOPKEEPER:
                    return redirect('shops:dashboard')
                return redirect('core:home')
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


customer_required = role_required(UserProfile.Role.CUSTOMER, login_url='customers:login')
shopkeeper_required = role_required(UserProfile.Role.SHOPKEEPER)
