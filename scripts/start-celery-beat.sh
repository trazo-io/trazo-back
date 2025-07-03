#!/bin/bash
set -e

echo "⏰ Starting Celery beat scheduler..."

# Wait for Django to be ready
echo "⏳ Waiting for Django to be ready..."
until curl -sf http://web:8000/admin/login/ > /dev/null 2>&1; do
    echo "Django is not ready yet, waiting..."
    sleep 2
done

echo "✅ Django is ready, starting Celery beat..."

# Remove existing celerybeat.pid file if it exists
rm -f /app/celerybeat.pid

# Start Celery beat scheduler
exec celery -A backend beat \
    --loglevel=INFO \
    --pidfile=/app/celerybeat.pid \
    --schedule=/app/celerybeat-schedule 