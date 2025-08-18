#!/bin/bash
# =============================================================================
# Optimized Django Startup Script - 2025 Best Practices
# =============================================================================

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Configuration
SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-backend.settings.prod}
PORT=${PORT:-8000}
WORKERS=${WORKERS:-$(nproc)}
MAX_WORKERS=${MAX_WORKERS:-8}
TIMEOUT=${TIMEOUT:-30}
KEEPALIVE=${KEEPALIVE:-5}

# Logging configuration
exec > >(tee -a /tmp/django-startup.log)
exec 2>&1

echo "=============================================="
echo "🚀 Starting Trazo Backend"
echo "Settings: $SETTINGS_MODULE"
echo "Port: $PORT"
echo "Workers: $WORKERS (max: $MAX_WORKERS)"
echo "=============================================="

# Function for error handling
handle_error() {
    echo "❌ Error occurred during startup: $1"
    exit 1
}

# Function for health check
health_check() {
    echo "🔍 Performing health check..."
    python manage.py check --settings=$SETTINGS_MODULE || handle_error "Django health check failed"
}

# Function for database migration
run_migrations() {
    echo "📊 Running database migrations..."
    python manage.py migrate --settings=$SETTINGS_MODULE --noinput || handle_error "Database migration failed"
}

# Function for static files collection
collect_static() {
    echo "📁 Collecting static files..."
    python manage.py collectstatic --settings=$SETTINGS_MODULE --noinput --clear || handle_error "Static collection failed"
}

# Function to calculate optimal workers
calculate_workers() {
    local cpu_count=$(nproc)
    local calculated_workers=$((cpu_count * 2 + 1))
    
    if [ $calculated_workers -gt $MAX_WORKERS ]; then
        echo $MAX_WORKERS
    elif [ $calculated_workers -lt 2 ]; then
        echo 2
    else
        echo $calculated_workers
    fi
}

# Main startup sequence
main() {
    # Debug startup (existing functionality)
    if [ -f "debug_startup.py" ]; then
        echo "🐛 Running debug startup..."
        python debug_startup.py || true  # Don't fail on debug issues
    fi
    
    # Health check
    health_check
    
    # Database operations
    run_migrations
    
    # Static files
    collect_static
    
    # Calculate optimal worker count
    OPTIMAL_WORKERS=$(calculate_workers)
    
    echo "=============================================="
    echo "🌟 Startup complete! Starting Gunicorn..."
    echo "Workers: $OPTIMAL_WORKERS"
    echo "=============================================="
    
    # Start Gunicorn with optimized settings
    exec gunicorn backend.wsgi:application \
        --bind 0.0.0.0:$PORT \
        --workers $OPTIMAL_WORKERS \
        --worker-class sync \
        --worker-connections 1000 \
        --timeout $TIMEOUT \
        --keepalive $KEEPALIVE \
        --max-requests 1000 \
        --max-requests-jitter 100 \
        --preload \
        --log-level info \
        --access-logfile - \
        --error-logfile - \
        --capture-output \
        --enable-stdio-inheritance
}

# Run main function
main "$@"