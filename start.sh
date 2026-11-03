#!/usr/bin/env bash
set -o errexit

python manage.py migrate --noinput

# Render does not provide an interactive terminal. Create the initial admin
# only when credentials are configured and the username does not already exist.
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    if python manage.py shell -c 'import os; from django.contrib.auth import get_user_model; raise SystemExit(0 if get_user_model().objects.filter(username=os.environ["DJANGO_SUPERUSER_USERNAME"]).exists() else 1)'; then
        echo "Configured Django superuser already exists; skipping creation."
    else
        python manage.py createsuperuser --noinput
    fi
else
    echo "Superuser creation skipped; set DJANGO_SUPERUSER_USERNAME and DJANGO_SUPERUSER_PASSWORD to enable it."
fi

exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-10000}"
