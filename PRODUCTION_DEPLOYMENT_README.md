# Trazo Production Deployment Guide

This comprehensive guide covers the complete deployment process for Trazo's agricultural carbon transparency platform in production environments.

## 📋 Overview

Trazo is a Django-based agricultural carbon transparency platform with React frontend. This guide ensures proper production deployment with all critical data, security configurations, and required integrations.

## 🛡️ Critical Security Notice

**BEFORE DEPLOYING**: Address the critical security vulnerabilities identified in `CLAUDE.md`:
- Blockchain private key storage issues (CRITICAL)
- API key encryption and rotation (CRITICAL) 
- USDA API key management (HIGH)

These must be resolved before production deployment.

## 🚀 Deployment Phases

### Phase 1: Infrastructure Setup

#### 1.1 System Requirements
```bash
# Minimum Production Requirements
- Python 3.11+
- PostgreSQL 14+
- Redis 6+
- Node.js 18+ (for frontend)
- 4GB RAM minimum (8GB recommended)
- 50GB storage minimum
```

#### 1.2 Environment Variables
Create a comprehensive `.env` file:

```env
# Django Core
DJANGO_SETTINGS_MODULE=backend.settings.prod
SECRET_KEY=your-super-secure-secret-key-here
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Database
DATABASE_URL=postgresql://username:password@localhost:5432/trazo_prod
REDIS_URL=redis://localhost:6379/0

# AWS Services (for production)
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret
AWS_STORAGE_BUCKET_NAME=trazo-production-media
AWS_S3_REGION_NAME=us-west-2

# Blockchain Security (MUST USE SECURE KEY MANAGEMENT)
POLYGON_NETWORK_URL=https://polygon-mainnet.infura.io/v3/your-project-id
POLYGON_PRIVATE_KEY_ENCRYPTED=encrypted-key-here  # NEVER store plain keys

# USDA API Integration
USDA_FOODDATA_API_KEY=encrypted-api-key-here  # ENCRYPT IN PRODUCTION
USDA_API_BASE_URL=https://api.nal.usda.gov/fdc/v1

# Email Configuration
EMAIL_HOST=smtp.your-provider.com
EMAIL_HOST_USER=your-email@domain.com
EMAIL_HOST_PASSWORD=encrypted-password-here
EMAIL_PORT=587
EMAIL_USE_TLS=True

# Celery Configuration
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# Security
SECURE_SSL_REDIRECT=True
SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

#### 1.3 Database Setup
```bash
# Create production database
sudo -u postgres createdb trazo_prod
sudo -u postgres createuser trazo_user --createdb
sudo -u postgres psql -c "ALTER USER trazo_user WITH PASSWORD 'secure_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE trazo_prod TO trazo_user;"
```

### Phase 2: Code Deployment

#### 2.1 Backend Deployment
```bash
# Clone repository
git clone https://github.com/your-org/trazo-back.git
cd trazo-back

# Install dependencies
poetry install --only=main

# Collect static files
poetry run python manage.py collectstatic --noinput

# Apply database migrations
poetry run python manage.py migrate

# Verify installation
poetry run python manage.py check --deploy
```

#### 2.2 Frontend Deployment
```bash
# Navigate to frontend directory
cd trazo-app

# Install dependencies
npm ci --production

# Build for production
npm run build

# Deploy build files to web server
```

### Phase 3: Critical Data Seeding

**IMPORTANT**: Run these commands in exact order for proper platform functionality.

#### 3.1 Essential Foundation Data (CRITICAL - Must Run)
```bash
# 1. USDA Crop Types (PRIORITY #1)
# Creates 16 USDA-compliant crop types required for all production forms
poetry run python manage.py populate_usda_crop_types

# 2. Carbon Benchmarks (PRIORITY #2)  
# Creates industry carbon benchmarks for 25+ crops with USDA verification
poetry run python manage.py seed_crop_benchmarks

# 3. USDA Production Templates (PRIORITY #3)
# Creates comprehensive production templates with USDA-verified practices
poetry run python manage.py comprehensive_usda_seed

# 4. Carbon Offset Actions (PRIORITY #4)
# Creates carbon offset compensation options for neutrality features
poetry run python manage.py seed_offset_actions
```

#### 3.2 Business Logic Data (IMPORTANT - Should Run)
```bash
# 5. Enhanced Production Templates (HELPFUL)
# Provides additional template options for all 16 crop types
poetry run python manage.py create_comprehensive_production_templates

# 6. Alternative Crop Templates (HELPFUL)
# Creates pre-configured crop templates with carbon sources
poetry run python manage.py create_crop_templates
```

#### 3.3 Security Implementation (CRITICAL - When Infrastructure Ready)
```bash
# 7. Secure Key Management (ADDRESSES CRITICAL SECURITY ISSUES)
# Implements proper blockchain and API key security
poetry run python manage.py manage_secure_keys setup
poetry run python manage.py manage_secure_keys migrate

# 8. API Key Rotation (SECURITY)
# Implements missing API key rotation system
poetry run python manage.py rotate_api_keys --setup
```

### Phase 4: Service Configuration

#### 4.1 Gunicorn Configuration
Create `/etc/systemd/system/trazo.service`:

```ini
[Unit]
Description=Trazo Django Application
After=network.target

[Service]
User=trazo
Group=trazo
WorkingDirectory=/opt/trazo/trazo-back
ExecStart=/opt/trazo/trazo-back/.venv/bin/gunicorn --workers 3 --bind 0.0.0.0:8000 backend.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

#### 4.2 Nginx Configuration
Create `/etc/nginx/sites-available/trazo`:

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    ssl_certificate /path/to/ssl/cert.pem;
    ssl_certificate_key /path/to/ssl/private.key;

    location / {
        try_files $uri $uri/ /index.html;
        root /opt/trazo/trazo-app/build;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /opt/trazo/trazo-back/staticfiles/;
    }

    location /media/ {
        alias /opt/trazo/trazo-back/media/;
    }
}
```

#### 4.3 Celery Configuration
Create `/etc/systemd/system/trazo-celery.service`:

```ini
[Unit]
Description=Trazo Celery Worker
After=network.target

[Service]
User=trazo
Group=trazo
WorkingDirectory=/opt/trazo/trazo-back
ExecStart=/opt/trazo/trazo-back/.venv/bin/celery -A backend worker -l info
Restart=always

[Install]
WantedBy=multi-user.target
```

### Phase 5: Monitoring & Maintenance

#### 5.1 Health Checks
```bash
# Database connectivity
poetry run python manage.py check --database default

# External API connectivity  
poetry run python manage.py circuit_breaker_status

# System health overview
poetry run python manage.py system_health
```

#### 5.2 Backup Strategy
```bash
# Database backups (run daily)
pg_dump trazo_prod > trazo_backup_$(date +%Y%m%d).sql

# Media file backups
rsync -av /opt/trazo/trazo-back/media/ /backup/trazo/media/

# Configuration backups
cp .env /backup/trazo/config/env_$(date +%Y%m%d)
```

## 🚨 Production Validation Checklist

### ✅ Pre-Deployment Security
- [ ] All critical security vulnerabilities from CLAUDE.md addressed
- [ ] Blockchain private keys properly encrypted and managed
- [ ] API keys encrypted at rest with rotation implemented  
- [ ] AWS KMS or equivalent secure key management configured
- [ ] All environment variables properly secured

### ✅ Essential Data Verification
- [ ] USDA crop types populated (16 types minimum)
- [ ] Carbon benchmarks created (25+ crops)
- [ ] Production templates available (multiple approaches per crop)
- [ ] Carbon offset actions configured
- [ ] All seed commands completed without errors

### ✅ Infrastructure Health
- [ ] Database migrations applied successfully
- [ ] Static files collected and served properly
- [ ] Redis connectivity confirmed
- [ ] Celery workers running
- [ ] SSL certificates configured
- [ ] Domain DNS properly configured

### ✅ Platform Functionality
- [ ] User registration and authentication working
- [ ] Production creation with crop type selection
- [ ] Carbon calculation engine functional
- [ ] QR code generation working
- [ ] File uploads to configured storage
- [ ] Email notifications sending

### ✅ Integration Verification
- [ ] USDA API connectivity confirmed
- [ ] Blockchain network connectivity (if enabled)
- [ ] Payment processing (Stripe) configured
- [ ] External storage (AWS S3) working
- [ ] Monitoring and logging operational

## 🔧 Common Issues & Solutions

### Database Connection Issues
```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Verify database exists
sudo -u postgres psql -l | grep trazo

# Test connection
poetry run python manage.py dbshell
```

### Static Files Not Loading
```bash
# Recollect static files
poetry run python manage.py collectstatic --clear --noinput

# Check nginx configuration
sudo nginx -t
sudo systemctl reload nginx
```

### USDA API Integration Issues
```bash
# Test USDA API connectivity
poetry run python manage.py test_usda_integration

# Check API key configuration
poetry run python manage.py check_api_keys
```

### Blockchain Connection Issues
```bash
# Verify blockchain configuration
poetry run python manage.py test_blockchain_production

# Check network connectivity
poetry run python manage.py blockchain_status
```

## 📊 Post-Deployment Monitoring

### Key Metrics to Track
- **Response Times**: API endpoints < 500ms
- **Database Performance**: Query times < 100ms average
- **Carbon Calculations**: Accuracy vs USDA benchmarks
- **QR Code Performance**: Generation < 2s
- **Error Rates**: < 1% across all endpoints

### Monitoring Commands
```bash
# System health check
poetry run python manage.py system_health

# Database optimization
poetry run python manage.py optimize_database

# Circuit breaker status
poetry run python manage.py circuit_breaker_status
```

## 🔄 Ongoing Maintenance

### Daily Tasks
- Monitor system health and error logs
- Check backup completion
- Verify external API connectivity
- Review security logs

### Weekly Tasks  
- Update carbon benchmarks if needed
- Review and rotate API keys
- Database performance optimization
- Security scan and updates

### Monthly Tasks
- Update USDA emission factors
- Blockchain network status review
- Storage cleanup and optimization
- Comprehensive security audit

## 📚 Additional Resources

### Documentation
- [Django Deployment Checklist](https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/)
- [Gunicorn Documentation](https://docs.gunicorn.org/)
- [Nginx Configuration](https://nginx.org/en/docs/)
- [PostgreSQL Administration](https://www.postgresql.org/docs/current/admin.html)

### Trazo-Specific
- `CLAUDE.md` - Critical security vulnerabilities and fixes
- `documentation/flows/` - Technical system flow documentation
- Carbon calculation verification guides
- USDA integration troubleshooting

## 🆘 Emergency Procedures

### Critical System Failure
1. Check system health: `poetry run python manage.py system_health`
2. Review error logs: `tail -f logs/error.log`
3. Restart services: `sudo systemctl restart trazo trazo-celery`
4. Verify database connectivity
5. Check external API status

### Data Corruption
1. Stop all services immediately
2. Restore from latest backup
3. Verify data integrity
4. Restart services in correct order
5. Run data validation checks

### Security Breach
1. Immediately rotate all API keys
2. Review access logs
3. Update all passwords
4. Verify blockchain key security
5. Conduct comprehensive security audit

---

**⚠️ CRITICAL REMINDER**: The security vulnerabilities identified in CLAUDE.md must be addressed before production deployment. The platform handles sensitive agricultural and financial data requiring enterprise-grade security measures.

This deployment guide ensures Trazo operates as a professional, secure, and scalable agricultural carbon transparency platform ready for production use.