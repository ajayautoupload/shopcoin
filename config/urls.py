"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path

from core.admin_dashboard import admin_dashboard
from core.views import serve_local_media

urlpatterns = [
    path('admin/', admin_dashboard, name='admin_dashboard'),
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('', include('accounts.urls')),
    path('', include('customers.urls')),
    path('', include('shops.urls')),
]

if not settings.MEDIA_STORAGE_ENABLED:
    media_prefix = urlsplit(settings.MEDIA_URL).path.lstrip('/')
    if media_prefix:
        urlpatterns.append(re_path(
            rf'^{re.escape(media_prefix)}(?P<path>.*)$',
            serve_local_media,
        ))
