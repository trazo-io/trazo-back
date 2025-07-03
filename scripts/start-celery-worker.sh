#!/bin/bash
set -e

echo "🔧 Starting Celery worker..."

# Wait for Django to be ready
echo "⏳ Waiting for Django to be ready..."
until curl -sf http://web:8000/admin/login/ > /dev/null 2>&1; do
    echo "Django is not ready yet, waiting..."
    sleep 2
done

echo "✅ Django is ready, starting Celery worker..."

# Start Celery worker with optimized settings for development
exec celery -A backend worker \
    --loglevel=INFO \
    --concurrency=2 \
    --prefetch-multiplier=1 \
    --max-tasks-per-child=1000 \
    --time-limit=300 \
    --soft-time-limit=240 