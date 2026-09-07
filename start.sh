#!/bin/bash

# Dynamic Django startup script that respects DJANGO_SETTINGS_MODULE
set -e

# Use DJANGO_SETTINGS_MODULE from environment or default to prod
SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-backend.settings.prod}

echo "=== Starting Django with settings: $SETTINGS_MODULE ==="
# `debug_startup.py` was deleted in commit 9d5bc4b and is not tracked. The `||` kept this
# non-fatal, but it printed "Debug script reported issues" on EVERY boot — a permanent false
# alarm in the production log, which is worse than no diagnostic at all because it trains
# everyone to ignore the startup output. Only run it if it is actually there.
if [ -f debug_startup.py ]; then
    python debug_startup.py || echo "=== Debug script reported issues (non-fatal) ==="
fi

echo "=== Starting Migration ==="
python manage.py migrate --settings=$SETTINGS_MODULE

echo "=== Migration Complete, Collecting Static ==="  
python manage.py collectstatic --noinput --settings=$SETTINGS_MODULE

echo "=== Static Complete, Starting Gunicorn ==="
# 2 processes x 4 threads: a page fires 8-12 API calls in parallel and a single sync worker
# serialised them (page wall time = SUM of call times, ~10 s, while the box sat at 3% CPU).
# gthread keeps memory at ~2 workers' worth (fits the 1 GB instance); tune via env.
#
# `${PORT:-8000}` is load-bearing, not defensive noise. Until 2026-09-07 the Procfile carried
# its own gunicorn line with `${PORT:-8000}`; this script had a bare `$PORT`. Now that the
# Procfile delegates here, this is the ONLY boot path, so a bare `$PORT` would expand to
# nothing wherever PORT is unset and gunicorn would die on `--bind 0.0.0.0:`. DigitalOcean
# sets PORT; a local `./start.sh` or a plain `docker run` does not.
exec gunicorn backend.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --worker-class gthread \
    --workers "${GUNICORN_WORKERS:-2}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout 120 \
    --max-requests 1000 --max-requests-jitter 100 \
    --log-level "${GUNICORN_LOG_LEVEL:-info}"