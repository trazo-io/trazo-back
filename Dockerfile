FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create static directory
RUN mkdir -p /app/staticfiles

# Make startup script executable
RUN chmod +x /app/start.sh

# Expose port (Railway will override this with $PORT)
EXPOSE 8000

# Use dynamic startup script that respects DJANGO_SETTINGS_MODULE
CMD ["/app/start.sh"]