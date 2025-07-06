# Trazo Staging Environment Deployment Guide

## Overview

This staging environment is designed for **ultra-cost optimization** with an estimated monthly cost of **$8-15 USD**. It includes aggressive cost-saving measures while maintaining core functionality for testing and development.

## 🏗️ Architecture

```
Internet → ALB → ECS Fargate (Staging) → RDS PostgreSQL (t3.micro)
                                      ↓
                                    S3 (Direct Access)
```

### Key Cost Optimizations

- **Single AZ deployment** (no redundancy)
- **Minimal resources**: 0.125 vCPU, 256MB RAM
- **Fargate Spot instances** (up to 70% cheaper)
- **Auto-scaling to zero** during off-hours
- **Weekend hibernation** (Friday 10 PM - Monday 8 AM)
- **No CloudFront, SSL, or Redis** by default
- **Minimal logging** (1-day retention)
- **Direct S3 access** (no CDN)

## 💰 Cost Breakdown (Monthly)

| Service            | Configuration             | Estimated Cost |
| ------------------ | ------------------------- | -------------- |
| ECS Fargate        | 0.125 vCPU, 256MB, Spot   | ~$3-5          |
| RDS PostgreSQL     | t3.micro, 20GB, Single AZ | ~$4-6          |
| ALB                | Basic configuration       | ~$2            |
| S3                 | Standard storage          | ~$1            |
| VPC, Secrets, Logs | Minimal usage             | ~$1            |
| **Total**          |                           | **~$8-15 USD** |

## 🚀 Quick Start

### Prerequisites

1. **AWS CLI** configured with appropriate permissions
2. **Terraform** >= 1.0.0
3. **Docker** (for building container images)
4. **AWS account** with billing alerts enabled

### Step 1: Configure Variables

```bash
cd trazo-back/terraform/environments/staging
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your values:

```hcl
# Required variables
domain_name = "api-staging.trazo.io"
database_password = "your-secure-password"
django_secret_key = "your-50-character-secret-key"
alert_email = "your-email@example.com"

# Optional: Enable additional features (increases cost)
enable_ssl = false        # Add $0.50/month for certificate
enable_cloudfront = false # Add $5-10/month for CDN
enable_redis = false      # Add $5-10/month for cache
```

### Step 2: Build and Push Docker Image

```bash
# Build the Docker image
cd trazo-back
docker build -t trazo-backend-staging -f docker/Dockerfile.dev .

# Tag and push to ECR (after applying terraform)
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-2.amazonaws.com
docker tag trazo-backend-staging:latest <account-id>.dkr.ecr.us-east-2.amazonaws.com/trazo/backend-staging:latest
docker push <account-id>.dkr.ecr.us-east-2.amazonaws.com/trazo/backend-staging:latest
```

### Step 3: Deploy Infrastructure

```bash
# Initialize Terraform
terraform init

# Plan deployment
terraform plan

# Apply infrastructure
terraform apply -auto-approve
```

### Step 4: Configure DNS (Optional)

If you want a custom domain:

```bash
# Get ALB DNS name
terraform output alb_dns_name

# Add CNAME record in your DNS provider:
# api-staging.trazo.io → <alb-dns-name>
```

## 🎯 Deployment Process

### 1. Infrastructure Provisioning

```bash
# Navigate to staging directory
cd trazo-back/terraform/environments/staging

# Initialize backend
terraform init

# Review planned changes
terraform plan -var-file="terraform.tfvars"

# Deploy infrastructure
terraform apply -var-file="terraform.tfvars"
```

### 2. Application Deployment

```bash
# Get ECR repository URL
export ECR_REPO=$(terraform output -raw ecr_repository_url)

# Build and push application
docker build -t trazo-backend-staging .
docker tag trazo-backend-staging:latest $ECR_REPO:latest
docker push $ECR_REPO:latest

# Update ECS service to use new image
aws ecs update-service \
  --cluster staging-cluster \
  --service staging-django-service \
  --force-new-deployment
```

### 3. Database Migration

```bash
# Get database endpoint
export DB_ENDPOINT=$(terraform output -raw database_endpoint)

# Run migrations using ECS Exec
aws ecs execute-command \
  --cluster staging-cluster \
  --task <task-id> \
  --container django \
  --command "python manage.py migrate" \
  --interactive
```

## 🔧 Configuration

### Environment Variables

The staging environment sets these automatically:

```bash
DEBUG=True
DJANGO_SETTINGS_MODULE=backend.settings.prod
ENVIRONMENT=staging
ALLOWED_HOSTS=api-staging.trazo.io,<alb-dns-name>
DATABASE_HOST=<rds-endpoint>
DATABASE_NAME=trazo_staging
# ... other variables from Secrets Manager
```

### Scaling Configuration

```hcl
# Daily scaling (8 AM - 8 PM UTC)
scale_up_schedule   = "cron(0 8 * * ? *)"  # 8 AM UTC
scale_down_schedule = "cron(0 20 * * ? *)" # 8 PM UTC

# Weekend hibernation
hibernation_start_schedule = "cron(0 22 ? * FRI *)"  # Friday 10 PM
hibernation_end_schedule   = "cron(0 8 ? * MON *)"   # Monday 8 AM
```

### Resource Limits

```hcl
# ECS Task Resources
ecs_task_cpu    = 128   # 0.125 vCPU
ecs_task_memory = 256   # 256 MB

# Auto-scaling
min_capacity = 0  # Can scale to zero
max_capacity = 2  # Maximum tasks
desired_count = 1 # Normal operation
```

## 📊 Monitoring & Alerts

### Budget Alerts

- **Monthly budget**: $10-15 USD
- **Alert threshold**: 80% of budget
- **Notification**: Email alert

### Health Checks

- **ALB health check**: `/health/`
- **Check interval**: 30 seconds
- **Timeout**: 5 seconds
- **Healthy threshold**: 2 consecutive successes

### Logging

- **CloudWatch logs**: 1-day retention
- **ECS logs**: `/ecs/staging`
- **Access logs**: Disabled (cost optimization)

## 🛠️ Operations

### Start/Stop Services

```bash
# Scale up manually
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id service/staging-cluster/staging-django-service \
  --scalable-dimension ecs:service:DesiredCount \
  --min-capacity 1 \
  --max-capacity 2

# Scale down manually
aws ecs update-service \
  --cluster staging-cluster \
  --service staging-django-service \
  --desired-count 0
```

### Debugging

```bash
# Access container shell
aws ecs execute-command \
  --cluster staging-cluster \
  --task <task-id> \
  --container django \
  --command "/bin/bash" \
  --interactive

# View logs
aws logs tail /ecs/staging --follow
```

### Database Access

```bash
# Connect to RDS via ECS task
aws ecs execute-command \
  --cluster staging-cluster \
  --task <task-id> \
  --container django \
  --command "psql -h $DATABASE_HOST -U $DATABASE_USER -d $DATABASE_NAME" \
  --interactive
```

## 🔐 Security Considerations

### Staging-Specific Security

- **HTTP only** (no SSL by default)
- **Minimal IAM permissions**
- **No multi-AZ deployment**
- **Immediate secret deletion**
- **No deletion protection**

### Production-Ready Security

To enable production-like security:

```hcl
enable_ssl = true
enable_multi_az = true
enable_deletion_protection = true
storage_encrypted = true
```

## 🚨 Troubleshooting

### Common Issues

1. **Task fails to start**

   ```bash
   # Check ECS events
   aws ecs describe-services --cluster staging-cluster --services staging-django-service

   # Check task logs
   aws logs tail /ecs/staging --follow
   ```

2. **Database connection issues**

   ```bash
   # Verify security groups
   aws ec2 describe-security-groups --group-ids <ecs-sg-id>

   # Test database connectivity
   aws ecs execute-command \
     --cluster staging-cluster \
     --task <task-id> \
     --container django \
     --command "nc -zv $DATABASE_HOST 5432" \
     --interactive
   ```

3. **Cost overruns**
   ```bash
   # Check current spend
   aws ce get-cost-and-usage \
     --time-period Start=2024-01-01,End=2024-01-31 \
     --granularity MONTHLY \
     --metrics BlendedCost \
     --group-by Type=DIMENSION,Key=SERVICE
   ```

### Resource Cleanup

```bash
# Destroy staging environment
terraform destroy -var-file="terraform.tfvars" -auto-approve

# Clean up ECR images
aws ecr batch-delete-image \
  --repository-name trazo/backend-staging \
  --image-ids imageTag=latest
```

## 📈 Scaling Up

### Adding Features

```hcl
# Enable SSL
enable_ssl = true
certificate_arn = "arn:aws:acm:us-east-2:123456789012:certificate/..."

# Enable CloudFront
enable_cloudfront = true

# Enable Redis
enable_redis = true

# Increase resources
ecs_task_cpu = 256
ecs_task_memory = 512
```

### Production Migration

When ready for production:

1. **Copy staging configuration** to production environment
2. **Enable all security features**
3. **Use larger instance types**
4. **Enable multi-AZ deployment**
5. **Set up proper monitoring**
6. **Configure CI/CD pipeline**

## 📝 Notes

- **Cost optimization** is prioritized over high availability
- **Single AZ** means potential downtime during maintenance
- **Minimal resources** may cause performance issues under load
- **No redundancy** - not suitable for production workloads
- **Scheduled scaling** reduces costs but may affect availability

## 🤝 Support

For issues or questions:

1. Check CloudWatch logs: `/ecs/staging`
2. Review ECS service events
3. Verify budget alerts and spending
4. Check security group configurations
5. Validate environment variables in Secrets Manager

---

**Remember**: This is a staging environment optimized for cost, not production reliability. Use appropriate configuration for production deployments.
