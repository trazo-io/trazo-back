variable "domain_name" {
  description = "Base domain name for the application"
  type        = string
  default     = "api-staging.trazo.io"
}

variable "database_password" {
  description = "Database password for staging"
  type        = string
  sensitive   = true
}

variable "django_secret_key" {
  description = "Django secret key for staging"
  type        = string
  sensitive   = true
}

variable "sendgrid_api_key" {
  description = "SendGrid API key for email"
  type        = string
  sensitive   = true
  default     = ""
}

variable "usda_nass_api_key" {
  description = "USDA NASS API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "usda_ers_api_key" {
  description = "USDA ERS API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "usda_fooddata_api_key" {
  description = "USDA FoodData Central API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "alert_email" {
  description = "Email address for budget alerts"
  type        = string
  default     = "admin@trazo.io"
}

variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-2"
}

variable "enable_ssl" {
  description = "Enable SSL certificate for staging (increases cost)"
  type        = bool
  default     = false
}

variable "enable_cloudfront" {
  description = "Enable CloudFront for staging (increases cost)"
  type        = bool
  default     = false
}

variable "enable_redis" {
  description = "Enable Redis for staging (increases cost)"
  type        = bool
  default     = false
}

variable "max_budget_amount" {
  description = "Maximum monthly budget for staging in USD"
  type        = string
  default     = "10"
}

variable "ecs_task_cpu" {
  description = "CPU units for ECS task (256 = 0.25 vCPU)"
  type        = number
  default     = 256  # Minimum CPU for Fargate
}

variable "ecs_task_memory" {
  description = "Memory in MiB for ECS task"
  type        = number
  default     = 512  # Minimum memory for 256 CPU on Fargate
}

variable "rds_backup_retention_days" {
  description = "Number of days to retain RDS backups"
  type        = number
  default     = 1  # Minimal for staging
}

variable "log_retention_days" {
  description = "Number of days to retain CloudWatch logs"
  type        = number
  default     = 1  # Minimal for staging
}

variable "desired_count" {
  description = "Desired number of ECS tasks"
  type        = number
  default     = 1
}

variable "max_capacity" {
  description = "Maximum number of ECS tasks"
  type        = number
  default     = 2
}

variable "min_capacity" {
  description = "Minimum number of ECS tasks"
  type        = number
  default     = 0  # Can scale to zero
}

variable "enable_auto_scaling" {
  description = "Enable auto-scaling for ECS service"
  type        = bool
  default     = true
}

variable "enable_scheduled_scaling" {
  description = "Enable scheduled scaling (scale to zero during off-hours)"
  type        = bool
  default     = true
}

variable "scale_down_schedule" {
  description = "Cron schedule for scaling down (UTC)"
  type        = string
  default     = "cron(0 20 * * ? *)"  # 8 PM UTC daily
}

variable "scale_up_schedule" {
  description = "Cron schedule for scaling up (UTC)"
  type        = string
  default     = "cron(0 8 * * ? *)"  # 8 AM UTC daily
}

variable "enable_deletion_protection" {
  description = "Enable deletion protection for resources"
  type        = bool
  default     = false  # Disabled for staging
}

variable "enable_multi_az" {
  description = "Enable multi-AZ deployment"
  type        = bool
  default     = false  # Disabled for staging
}

variable "enable_enhanced_monitoring" {
  description = "Enable enhanced monitoring for RDS"
  type        = bool
  default     = false  # Disabled for staging
}

variable "enable_performance_insights" {
  description = "Enable performance insights for RDS"
  type        = bool
  default     = false  # Disabled for staging
}

variable "storage_encrypted" {
  description = "Enable storage encryption"
  type        = bool
  default     = true  # Keep security
}

variable "backup_window" {
  description = "RDS backup window"
  type        = string
  default     = "03:00-04:00"
}

variable "maintenance_window" {
  description = "RDS maintenance window"
  type        = string
  default     = "Sun:04:00-Sun:05:00"
}

variable "allocated_storage" {
  description = "Initial storage allocation for RDS (GB)"
  type        = number
  default     = 20  # Minimal
}

variable "max_allocated_storage" {
  description = "Maximum storage allocation for RDS (GB)"
  type        = number
  default     = 100
}

variable "storage_type" {
  description = "RDS storage type"
  type        = string
  default     = "gp3"  # More cost-effective than gp2
}

variable "enable_spot_instances" {
  description = "Use Fargate Spot instances (up to 70% cheaper)"
  type        = bool
  default     = true
}

variable "container_insights" {
  description = "Enable Container Insights for ECS"
  type        = bool
  default     = false  # Disabled for staging
}

variable "enable_execute_command" {
  description = "Enable ECS Exec for debugging"
  type        = bool
  default     = true  # Useful for staging debugging
}

variable "health_check_grace_period" {
  description = "Health check grace period in seconds"
  type        = number
  default     = 60
}

variable "health_check_interval" {
  description = "Health check interval in seconds"
  type        = number
  default     = 30
}

variable "health_check_timeout" {
  description = "Health check timeout in seconds"
  type        = number
  default     = 5
}

variable "healthy_threshold" {
  description = "Number of consecutive health checks successes required"
  type        = number
  default     = 2
}

variable "unhealthy_threshold" {
  description = "Number of consecutive health check failures required"
  type        = number
  default     = 5
}

variable "deregistration_delay" {
  description = "ALB target group deregistration delay in seconds"
  type        = number
  default     = 30  # Faster for staging
}

variable "enable_access_logs" {
  description = "Enable ALB access logs"
  type        = bool
  default     = false  # Disabled for staging
}

variable "certificate_arn" {
  description = "SSL certificate ARN (optional for staging)"
  type        = string
  default     = null
}

variable "enable_waf" {
  description = "Enable WAF for ALB"
  type        = bool
  default     = false  # Disabled for staging
}

variable "environment_variables" {
  description = "Additional environment variables for the container"
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Additional secrets for the container"
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Additional tags for resources"
  type        = map(string)
  default     = {}
}

# Cost optimization variables
variable "enable_hibernation" {
  description = "Enable hibernation mode (scale to zero) during weekends"
  type        = bool
  default     = true
}

variable "hibernation_start_schedule" {
  description = "When to start hibernation (scale to zero)"
  type        = string
  default     = "cron(0 22 ? * FRI *)"  # Friday 10 PM UTC
}

variable "hibernation_end_schedule" {
  description = "When to end hibernation (scale up)"
  type        = string
  default     = "cron(0 8 ? * MON *)"  # Monday 8 AM UTC
}

variable "enable_budget_alerts" {
  description = "Enable budget alerts for cost monitoring"
  type        = bool
  default     = true
}

variable "budget_alert_threshold" {
  description = "Budget alert threshold percentage"
  type        = number
  default     = 80
} 