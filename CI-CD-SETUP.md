# 🚀 CI/CD Pipeline Setup Guide

## Prerequisites Setup

### 1. Configure GitHub Repository Secrets

In your `trazo-back` GitHub repository, go to **Settings → Secrets and variables → Actions** and add:

```bash
AWS_ACCESS_KEY_ID: your-aws-access-key-id
AWS_SECRET_ACCESS_KEY: your-aws-secret-access-key
```

### 2. Verify AWS IAM Permissions

Your AWS credentials need these permissions:
- `ecr:GetAuthorizationToken`
- `ecr:BatchCheckLayerAvailability`
- `ecr:GetDownloadUrlForLayer`
- `ecr:BatchGetImage`
- `ecr:BatchImportLayerPart`
- `ecr:InitiateLayerUpload`
- `ecr:UploadLayerPart`
- `ecr:CompleteLayerUpload`
- `ecr:PutImage`
- `ecs:DescribeTaskDefinition`
- `ecs:RegisterTaskDefinition`
- `ecs:UpdateService`
- `ecs:DescribeServices`

### 3. Test the Pipeline

#### Option A: Push to develop branch
```bash
git checkout develop
git add .
git commit -m "feat: trigger CI/CD pipeline test"
git push origin develop
```

#### Option B: Manual trigger
1. Go to **Actions** tab in GitHub
2. Click **🚀 Deploy to Staging**
3. Click **Run workflow**
4. Select branch and click **Run workflow**

## Pipeline Overview

### 🔍 **Job 1: Quality & Security** (15 min)
- Python 3.11 setup with pip caching
- Security scanning with Bandit
- Dependency vulnerability check with Safety
- Code formatting check (Black, isort)
- Linting with flake8
- Django system checks

### 🧪 **Job 2: Tests** (20 min)
- PostgreSQL 15 + Redis 7 services
- Full test suite with coverage
- Coverage reports uploaded to Codecov
- Pytest with Django settings

### 🏗️ **Job 3: Build & Push** (30 min)
- Multi-stage Docker build (Dockerfile.optimized)
- linux/amd64 platform targeting
- Image tagged with timestamp + git SHA
- GitHub Actions cache for faster builds
- Trivy security scanning
- Push to AWS ECR

### 🚀 **Job 4: Deploy** (15 min)
- Updates both ECS services:
  - `staging-django-service`
  - `staging-django`
- Waits for service stability
- Health check verification
- Dashboard metrics endpoint test

### 📊 **Job 5: Monitoring** (10 min)
- Performance testing
- Response time measurement
- Success/failure notifications

## Expected Results

### ✅ Success Indicators
- **Health endpoint**: `https://api-staging.trazo.io/health/` returns 200
- **Dashboard metrics**: `https://api-staging.trazo.io/api/companies/62/establishments/173/dashboard_metrics/` returns 401/403 (auth required) instead of 404
- **Build time**: ~8-12 minutes total
- **Image size**: ~60% smaller than current

### 🚨 Troubleshooting

#### Build fails with "exec format error"
- Verify Docker Buildx is using `linux/amd64` platform
- Check ECR repository exists: `trazo-backend`

#### Deployment fails with task definition errors
- Verify ECS cluster exists: `staging-cluster`
- Check service names: `staging-django-service`, `staging-django`
- Confirm container name: `django`

#### Health checks fail
- Check if health URLs are properly configured in Django
- Verify ALB health check settings
- Review ECS task logs: `aws ecs describe-tasks`

## Files Created/Modified

### 🆕 New Files
- `.github/workflows/staging-deploy.yml` - Complete CI/CD pipeline
- `Dockerfile.optimized` - Multi-stage optimized build
- `start-optimized.sh` - Performance-tuned startup script
- `health/__init__.py` - Health check module
- `health/urls.py` - Health check URL routing
- `health/views.py` - Health check endpoints
- `.dockerignore` - Build context optimization

### ✏️ Modified Files
- `backend/urls.py` - Added health check URL patterns

## Monitoring

### GitHub Actions
- **Actions tab**: View pipeline execution
- **Security tab**: View Trivy security scan results
- **Pull requests**: Automatic checks on PRs

### AWS CloudWatch
- **ECS logs**: Container logs for debugging
- **Application logs**: Django application logs

## Next Steps

1. **Configure secrets** (required)
2. **Test pipeline** with a small change
3. **Monitor first deployment**
4. **Set up notifications** (optional) - Slack/email
5. **Add staging environment protection** (optional)

The pipeline will now automatically deploy your latest code to staging, resolving the dashboard_metrics 404 error!