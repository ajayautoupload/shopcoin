#!/usr/bin/env bash
set -o errexit

python -m pip install -r requirements.txt
python manage.py collectstatic --no-input

# Render build and pre-deploy environments cannot access a service's persistent
# disk. Run migrations from start.sh after that disk is mounted. Local builds
# still apply migrations here.
if [ "${RENDER:-}" = "true" ]; then
    echo "Skipping build-time migrations on Render; start.sh migrates the mounted SQLite database."
else
    python manage.py migrate --noinput
fi
