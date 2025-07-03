#!/bin/bash
set -e

echo "🌸 Starting Flower (Celery monitoring)..."

# Wait for Celery worker to be ready
echo "⏳ Waiting for Celery worker to be ready..."
until celery -A backend inspect ping > /dev/null 2>&1; do
    echo "Celery worker is not ready yet, waiting..."
    sleep 3
done

echo "✅ Celery worker is ready, starting Flower..."

# Start Flower with security settings for development
exec celery -A backend flower \
    --port=5555 \
    --address=0.0.0.0 \
    --basic_auth=admin:flower123 \
    --broker_api=http://guest:guest@redis:5672/api/ \
    --persistent=true \
    --db=/app/flower.db 