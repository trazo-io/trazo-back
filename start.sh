#!/bin/bash

# Dynamic Django startup script that respects DJANGO_SETTINGS_MODULE
set -e

# Use DJANGO_SETTINGS_MODULE from environment or default to prod
SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-backend.settings.prod}

echo "=== Starting Django with settings: $SETTINGS_MODULE ==="
python debug_startup.py

echo "=== Debug Complete, Starting Migration ==="
python manage.py migrate --settings=$SETTINGS_MODULE

echo "=== Migration Complete, Collecting Static ==="  
python manage.py collectstatic --noinput --settings=$SETTINGS_MODULE

echo "=== Static Complete, Starting Gunicorn ==="
exec gunicorn backend.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --log-level debug