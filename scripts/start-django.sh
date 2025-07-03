#!/bin/bash
set -e

echo "🚀 Starting Django development server..."

# Wait for database to be ready
echo "⏳ Waiting for database to be ready..."
python manage.py check --database default

# Run database migrations
echo "🔄 Running database migrations..."
python manage.py migrate --noinput

# Collect static files
echo "📁 Collecting static files..."
python manage.py collectstatic --noinput --clear

# Create superuser if it doesn't exist
echo "👤 Creating superuser if needed..."
python manage.py shell << END
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@trazo.com', 'admin123')
    print('✅ Superuser created: admin/admin123')
else:
    print('ℹ️ Superuser already exists')
END

# Start development server
echo "🌐 Starting Django development server on 0.0.0.0:8000..."
exec python manage.py runserver 0.0.0.0:8000 