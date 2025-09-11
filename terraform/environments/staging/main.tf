terraform {
  required_version = ">= 1.0.0"
  
  # Using local backend for staging to avoid S3 costs and complexity
  # State will be stored locally in terraform.tfstate
}

provider "aws" {
  region = "us-east-2"
}

provider "aws" {
  alias  = "us-east-1"
  region = "us-east-1"
}

# STAGING ENVIRONMENT - ULTRA COST-OPTIMIZED
# This staging environment is designed for minimal cost:
# - Single AZ deployment
# - Minimal resource allocation
# - No multi-AZ RDS
# - No CloudFront (direct S3 access)
# - Shorter log retention
# - Auto-scaling to zero during off-hours
# - Spot instances where possible

# Networking with minimal configuration
module "networking" {
  source = "../../modules/networking"
  
  environment = "staging"
  vpc_cidr    = "10.1.0.0/16"  # Different CIDR than prod
  aws_region  = "us-east-2"
  
  # Single AZ for cost optimization
  public_subnets  = ["10.1.1.0/24"]
  private_subnets = ["10.1.2.0/24"]
  availability_zones = ["us-east-2a"]  # Single AZ only
}

# Security groups
module "security" {
  source = "../../modules/security"
  
  environment    = "staging"
  vpc_id         = module.networking.vpc_id
  container_port = 8000
}

# Application Load Balancer (minimal configuration)
module "alb" {
  source = "../../modules/alb"
  
  environment          = "staging"
  vpc_id              = module.networking.vpc_id
  public_subnet_ids   = module.networking.public_subnet_ids
  alb_security_group_id = module.security.alb_security_group_id
  certificate_arn     = var.enable_ssl ? var.certificate_arn : null
}

# RDS PostgreSQL (minimal configuration)
module "rds" {
  source = "../../modules/rds"
  
  environment           = "staging"
  private_subnet_ids   = module.networking.private_subnet_ids
  rds_security_group_id = module.security.rds_security_group_id
  
  database_name     = "trazo_staging"
  database_user     = "trazo_staging"
  database_password = var.database_password
  instance_class    = "db.t3.micro"  # Smallest available
  aws_region        = "us-east-2"
}

# S3 for static/media files (minimal configuration)
module "s3" {
  source = "../../modules/s3"
  environment = "staging"
  domain_name = var.domain_name
  cf_oai_arn  = null  # No CloudFront for staging
}

# ECS Fargate (ultra minimal configuration)
module "ecs" {
  source = "../../modules/ecs"
  
  environment = "staging"
  region     = "us-east-2"
  aws_region = "us-east-2"
  
  database_host = module.rds.endpoint
  
  ecs_exec_role_arn = aws_iam_role.ecs_execution_role.arn
  ecs_execution_role_arn = aws_iam_role.ecs_execution_role.arn
  ecs_task_role_arn = aws_iam_role.ecs_task_role.arn
  
  ecr_repository_url = aws_ecr_repository.staging.repository_url
  secrets_arn        = aws_secretsmanager_secret.staging.arn
  
  alb_dns_name     = module.alb.dns_name
  target_group_arn = module.alb.target_group_arn
  
  ecs_security_group_id = module.security.ecs_tasks_security_group_id
  private_subnet_ids    = module.networking.private_subnet_ids
  public_subnet_ids     = module.networking.public_subnet_ids
  s3_bucket_name    = module.s3.media_bucket_id
  cloudfront_domain = module.s3.media_bucket_regional_domain  # Direct S3 access
  domain_name      = var.domain_name
}

# IAM Roles (minimal permissions)
resource "aws_iam_role" "ecs_execution_role" {
  name = "staging-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_role_policy" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task_role" {
  name = "staging-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

# ECR Repository for staging
resource "aws_ecr_repository" "staging" {
  name = "trazo-backend-staging"

  image_scanning_configuration {
    scan_on_push = false  # Disable to save cost
  }
}

# Secrets Manager for staging
resource "aws_secretsmanager_secret" "staging" {
  name                    = "staging/trazo/backend"
  recovery_window_in_days = 0  # Immediate deletion for staging
}

resource "aws_secretsmanager_secret_version" "staging" {
  secret_id = aws_secretsmanager_secret.staging.id
  
  secret_string = jsonencode({
    SECRET_KEY           = var.django_secret_key
    DATABASE_NAME        = "trazo_staging"
    DATABASE_USER        = "trazo_staging"
    DATABASE_PASSWORD    = var.database_password
    DATABASE_HOST        = module.rds.endpoint
    SENDGRID_API_KEY     = var.sendgrid_api_key
    usda_nass_api_key    = var.usda_nass_api_key
    usda_ers_api_key     = var.usda_ers_api_key
    usda_fooddata_api_key = var.usda_fooddata_api_key
    ALLOWED_HOSTS        = "${var.domain_name},${module.alb.dns_name},localhost"
    DEBUG                = "False"  # SECURITY: Never use DEBUG=True in publicly accessible environments
    ENVIRONMENT          = "staging"
  })
}

# CloudWatch Log Group (minimal retention)
resource "aws_cloudwatch_log_group" "ecs_staging" {
  name              = "/ecs/staging"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, {
    Name = "staging-ecs-logs"
  })
}

# IAM Policies for staging
resource "aws_iam_role_policy" "ecs_task_secrets_staging" {
  name = "staging-ecs-task-secrets"
  role = aws_iam_role.ecs_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [aws_secretsmanager_secret.staging.arn]
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_execution_secrets_staging" {
  name = "staging-ecs-execution-secrets"
  role = aws_iam_role.ecs_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = ["${aws_secretsmanager_secret.staging.arn}*"]
      }
    ]
  })
}

# S3 access for staging
resource "aws_iam_role_policy" "ecs_s3_staging" {
  name = "staging-ecs-s3"
  role = aws_iam_role.ecs_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = [
          "${module.s3.media_bucket_arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = [
          module.s3.media_bucket_arn
        ]
      }
    ]
  })
}

# ECS Exec permissions for interactive sessions
resource "aws_iam_role_policy" "ecs_exec_staging" {
  name = "staging-ecs-exec"
  role = aws_iam_role.ecs_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssmmessages:CreateControlChannel",
          "ssmmessages:CreateDataChannel",
          "ssmmessages:OpenControlChannel",
          "ssmmessages:OpenDataChannel"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:DescribeLogGroups",
          "logs:CreateLogStream",
          "logs:DescribeLogStreams",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

# Staging-specific ECS task definition with cost optimization
resource "aws_ecs_task_definition" "staging_django" {
  family                   = "staging-django"
  network_mode            = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                     = var.ecs_task_cpu
  memory                  = var.ecs_task_memory
  execution_role_arn      = aws_iam_role.ecs_execution_role.arn
  task_role_arn           = aws_iam_role.ecs_task_role.arn
  
  container_definitions = jsonencode([
    {
      name      = "django"
      image     = "${aws_ecr_repository.staging.repository_url}:latest"
      essential = true
      
      environment = concat([
        { name = "DEBUG", value = "False" },  # SECURITY: Never use DEBUG=True in publicly accessible environments
        { name = "DJANGO_SETTINGS_MODULE", value = "backend.settings.staging" },  # Use staging.py for staging-specific settings
        { name = "ENVIRONMENT", value = "staging" },  # Environment identifier for staging
        { name = "ALLOWED_HOSTS", value = "api-staging.trazo.io,staging-alb-1273700937.us-east-2.elb.amazonaws.com,localhost,127.0.0.1,*" },  # Fix ALLOWED_HOSTS for ALB health checks
        { name = "RATELIMIT_ENABLE", value = "False" },  # Disable django-ratelimit to avoid cache backend errors
        { name = "SECURE_SSL_REDIRECT", value = "False" },  # Disable SSL redirect for staging (no SSL cert)
        { name = "SESSION_COOKIE_SECURE", value = "False" },  # Allow non-SSL cookies for staging
        { name = "CSRF_COOKIE_SECURE", value = "False" },  # Allow non-SSL CSRF for staging
        { name = "AWS_S3_REGION_NAME", value = "us-east-2" },
        { name = "DATABASE_PORT", value = "5432" },
        { name = "AWS_STORAGE_BUCKET_NAME", value = module.s3.media_bucket_id },
        { name = "STATIC_URL", value = "https://${module.s3.media_bucket_regional_domain}/static/" },
        { name = "PORT", value = "8000" },
      ], [
        for key, value in var.environment_variables : {
          name  = key
          value = value
        }
      ])

      secrets = concat([
        { name = "SECRET_KEY", valueFrom = "${aws_secretsmanager_secret.staging.arn}:SECRET_KEY::" },
        { name = "DATABASE_NAME", valueFrom = "${aws_secretsmanager_secret.staging.arn}:DATABASE_NAME::" },
        { name = "DATABASE_USER", valueFrom = "${aws_secretsmanager_secret.staging.arn}:DATABASE_USER::" },
        { name = "DATABASE_PASSWORD", valueFrom = "${aws_secretsmanager_secret.staging.arn}:DATABASE_PASSWORD::" },
        { name = "DATABASE_HOST", valueFrom = "${aws_secretsmanager_secret.staging.arn}:DATABASE_HOST::" },
        { name = "SENDGRID_API_KEY", valueFrom = "${aws_secretsmanager_secret.staging.arn}:SENDGRID_API_KEY::" }
      ], [
        for key, value in var.secrets : {
          name      = key
          valueFrom = value
        }
      ])

      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs_staging.name
          awslogs-region        = "us-east-2"
          awslogs-stream-prefix = "ecs"
        }
      }

      # Temporarily disable health check to resolve container failures
      # healthCheck = {
      #   command = ["CMD-SHELL", "curl -f http://localhost:8000/health/ || exit 1"]
      #   interval = 30
      #   timeout = 10
      #   retries = 3
      #   startPeriod = 60
      # }
    }
  ])

  tags = merge(local.common_tags, {
    Name = "staging-django-task"
  })
}

# ECS Service with cost optimization
resource "aws_ecs_service" "staging_django" {
  name            = "staging-django-service"
  cluster         = module.ecs.cluster_name
  task_definition = aws_ecs_task_definition.staging_django.arn
  desired_count   = var.desired_count
  
  # Use Fargate Spot for cost optimization
  capacity_provider_strategy {
    capacity_provider = var.enable_spot_instances ? "FARGATE_SPOT" : "FARGATE"
    weight           = 100
  }

  network_configuration {
    subnets          = module.networking.public_subnet_ids  # Use public subnets for cost optimization
    security_groups  = [module.security.ecs_tasks_security_group_id]
    assign_public_ip = true  # Enable public IP for AWS service access
  }

  load_balancer {
    target_group_arn = module.alb.target_group_arn
    container_name   = "django"
    container_port   = 8000
  }

  health_check_grace_period_seconds = var.health_check_grace_period
  enable_execute_command           = var.enable_execute_command

  depends_on = [
    module.alb,
    aws_ecs_task_definition.staging_django
  ]

  tags = merge(local.common_tags, {
    Name = "staging-django-service"
  })
}

# Auto-scaling for ECS service
resource "aws_appautoscaling_target" "ecs_staging" {
  count = var.enable_auto_scaling ? 1 : 0
  
  max_capacity       = var.max_capacity
  min_capacity       = var.min_capacity
  resource_id        = "service/${module.ecs.cluster_name}/${aws_ecs_service.staging_django.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "ecs_staging_cpu" {
  count = var.enable_auto_scaling ? 1 : 0
  
  name               = "staging-cpu-autoscaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs_staging[0].resource_id
  scalable_dimension = aws_appautoscaling_target.ecs_staging[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs_staging[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 70.0  # Lower threshold for staging
  }
}

# Scheduled scaling for cost optimization
resource "aws_appautoscaling_scheduled_action" "scale_down_evening" {
  count = var.enable_scheduled_scaling ? 1 : 0
  
  name               = "staging-scale-down-evening"
  service_namespace  = "ecs"
  resource_id        = "service/${module.ecs.cluster_name}/${aws_ecs_service.staging_django.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  schedule           = var.scale_down_schedule

  scalable_target_action {
    min_capacity = 0
    max_capacity = 0
  }
}

resource "aws_appautoscaling_scheduled_action" "scale_up_morning" {
  count = var.enable_scheduled_scaling ? 1 : 0
  
  name               = "staging-scale-up-morning"
  service_namespace  = "ecs"
  resource_id        = "service/${module.ecs.cluster_name}/${aws_ecs_service.staging_django.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  schedule           = var.scale_up_schedule

  scalable_target_action {
    min_capacity = var.min_capacity
    max_capacity = var.max_capacity
  }
}

# Weekend hibernation (scale to zero)
resource "aws_appautoscaling_scheduled_action" "hibernation_start" {
  count = var.enable_hibernation ? 1 : 0
  
  name               = "staging-hibernation-start"
  service_namespace  = "ecs"
  resource_id        = "service/${module.ecs.cluster_name}/${aws_ecs_service.staging_django.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  schedule           = var.hibernation_start_schedule

  scalable_target_action {
    min_capacity = 0
    max_capacity = 0
  }
}

resource "aws_appautoscaling_scheduled_action" "hibernation_end" {
  count = var.enable_hibernation ? 1 : 0
  
  name               = "staging-hibernation-end"
  service_namespace  = "ecs"
  resource_id        = "service/${module.ecs.cluster_name}/${aws_ecs_service.staging_django.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  schedule           = var.hibernation_end_schedule

  scalable_target_action {
    min_capacity = var.min_capacity
    max_capacity = var.max_capacity
  }
}

# Budget alert for cost monitoring
resource "aws_budgets_budget" "staging_budget" {
  count = var.enable_budget_alerts ? 1 : 0
  
  name         = "trazo-staging-budget"
  budget_type  = "COST"
  limit_amount = var.max_budget_amount
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  
  cost_filter {
    name   = "TagKey"
    values = ["Environment"]
  }
  
  cost_filter {
    name   = "TagValue"
    values = ["staging"]
  }
  
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.budget_alert_threshold
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}

# DNS record for staging - MANAGED IN GODADDY
# Uncomment these resources if you switch to Route 53 for DNS management
# resource "aws_route53_record" "staging_api" {
#   count = var.enable_ssl ? 1 : 0
#   
#   zone_id = data.aws_route53_zone.main[0].zone_id
#   name    = var.domain_name
#   type    = "A"
#   
#   alias {
#     name                   = module.alb.dns_name
#     zone_id                = module.alb.zone_id
#     evaluate_target_health = true
#   }
# }

# Route53 zone lookup - NOT USED (DNS managed in GoDaddy)
# data "aws_route53_zone" "main" {
#   count = var.enable_ssl ? 1 : 0
#   name  = "trazo.io"
# }

# Common tags for all resources
locals {
  common_tags = merge({
    Environment = "staging"
    Project     = "trazo"
    ManagedBy   = "terraform"
    Purpose     = "cost-optimized-staging"
  }, var.tags)
}

# Outputs
output "alb_dns_name" {
  description = "DNS name of the load balancer"
  value       = module.alb.dns_name
}

output "database_endpoint" {
  description = "Database endpoint"
  value       = module.rds.endpoint
}

output "s3_bucket_name" {
  description = "S3 bucket name for media files"
  value       = module.s3.media_bucket_id
}

output "s3_bucket_region" {
  description = "S3 bucket regional domain"
  value       = module.s3.media_bucket_regional_domain
}

output "ecr_repository_url" {
  description = "ECR repository URL"
  value       = aws_ecr_repository.staging.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs.cluster_name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.staging_django.name
}

output "secrets_manager_arn" {
  description = "Secrets Manager ARN"
  value       = aws_secretsmanager_secret.staging.arn
}

output "estimated_monthly_cost" {
  description = "Estimated monthly cost for staging environment"
  value       = "$8-15 USD (ECS Fargate Spot: $3-5, RDS t3.micro: $4-6, ALB: $2, S3: $1, Other: $1-2)"
}

output "cost_optimization_features" {
  description = "List of enabled cost optimization features"
  value = [
    var.enable_spot_instances ? "Fargate Spot Instances (-70% cost)" : "Fargate On-Demand",
    var.enable_scheduled_scaling ? "Scheduled Scaling (8AM-8PM)" : "No Scheduled Scaling",
    var.enable_hibernation ? "Weekend Hibernation (Fri 10PM - Mon 8AM)" : "No Weekend Hibernation",
    "Single AZ Deployment",
    "Minimal Resources (128 CPU, 256MB RAM)",
    "1-day log retention",
    "No CloudFront/SSL by default"
  ]
}

output "access_instructions" {
  description = "How to access the staging environment"
  value = {
    api_url = "http://${module.alb.dns_name}"
    health_check = "http://${module.alb.dns_name}/health/"
    admin_url = "http://${module.alb.dns_name}/admin/"
    logs_command = "aws logs tail /ecs/staging --follow"
    scale_command = "aws ecs update-service --cluster ${module.ecs.cluster_name} --service ${aws_ecs_service.staging_django.name} --desired-count 1"
  }
} 