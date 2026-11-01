from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from urllib.parse import urlencode


def csrf_failure(request, reason=''):
    """Keep CSRF checks strict while giving users a recoverable application response."""
    login_paths = {reverse('accounts:login'), reverse('customers:login')}
    if request.path_info in login_paths:
        login_url = reverse('customers:login') if request.path_info == reverse('customers:login') else reverse('accounts:login')
        next_url = request.POST.get('next', '').strip()
        messages.warning(request, 'Your login form expired. Please try again.')
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
        ):
            return redirect(f'{login_url}?{urlencode({"next": next_url})}')
        return redirect(login_url)
    return render(request, 'core/csrf_failure.html', status=403)


def home(request):
    return render(request, 'core/home.html')
