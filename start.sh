#!/bin/bash

# Dynamic Django startup script that respects DJANGO_SETTINGS_MODULE
set -e

# Use DJANGO_SETTINGS_MODULE from environment or default to prod
SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-backend.settings.prod}

echo "=== Starting Django with settings: $SETTINGS_MODULE ==="
python debug_startup.py || echo "=== Debug script reported issues (non-fatal) ==="

echo "=== Debug Complete, Starting Migration ==="
python manage.py migrate --settings=$SETTINGS_MODULE

echo "=== Migration Complete, Collecting Static ==="  
python manage.py collectstatic --noinput --settings=$SETTINGS_MODULE

echo "=== Static Complete, Starting Gunicorn ==="
# 2 processes x 4 threads: a page fires 8-12 API calls in parallel and a single sync worker
# serialised them (page wall time = SUM of call times, ~10 s, while the box sat at 3% CPU).
# gthread keeps memory at ~2 workers' worth (fits the 1 GB instance); tune via env.
exec gunicorn backend.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --worker-class gthread \
    --workers "${GUNICORN_WORKERS:-2}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout 120 \
    --max-requests 1000 --max-requests-jitter 100 \
    --log-level "${GUNICORN_LOG_LEVEL:-info}"