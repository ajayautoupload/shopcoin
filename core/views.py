from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.static import serve
from urllib.parse import urlencode
from django.http import JsonResponse
from django.utils import translation
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET
from .translations import HI


@require_POST
def set_language_preference(request):
    language = request.POST.get('language', '')
    if language not in {code for code, _ in settings.LANGUAGES}:
        return JsonResponse({'ok': False}, status=400)
    response = JsonResponse({'ok': True, 'language': language})
    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language, max_age=settings.LANGUAGE_COOKIE_AGE, samesite='Lax')
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        request.user.profile.preferred_language = language
        request.user.profile.save(update_fields=('preferred_language', 'updated_at'))
    translation.activate(language)
    return response


@require_GET
def translation_catalogue(request):
    language = request.GET.get('language', 'en')
    if language == 'hi':
        return JsonResponse(HI)
    return JsonResponse({key: key for key in HI})


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


def serve_local_media(request, path):
    """Serve uploaded files when the configured media backend is local disk."""
    return serve(request, path, document_root=settings.MEDIA_ROOT)
