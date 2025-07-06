#!/bin/bash

# Trazo Staging Environment Deployment Script
# This script deploys the ultra-cost-optimized staging environment

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REGION="us-east-2"
ENVIRONMENT="staging"
PROJECT_NAME="trazo"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    # Check if AWS CLI is installed
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI is not installed. Please install it first."
        exit 1
    fi
    
    # Check if Terraform is installed
    if ! command -v terraform &> /dev/null; then
        print_error "Terraform is not installed. Please install it first."
        exit 1
    fi
    
    # Check if Docker is installed
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install it first."
        exit 1
    fi
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS credentials not configured. Please run 'aws configure'."
        exit 1
    fi
    
    # Check if terraform.tfvars exists
    if [ ! -f "terraform.tfvars" ]; then
        print_error "terraform.tfvars not found. Please copy from terraform.tfvars.example and configure."
        exit 1
    fi
    
    print_success "All prerequisites met!"
}

# Function to validate terraform.tfvars
validate_config() {
    print_status "Validating configuration..."
    
    # Check required variables
    required_vars=("database_password" "django_secret_key")
    
    for var in "${required_vars[@]}"; do
        if ! grep -q "^${var}" terraform.tfvars; then
            print_error "Required variable '${var}' not found in terraform.tfvars"
            exit 1
        fi
    done
    
    # Check if secret key is long enough
    secret_key=$(grep "django_secret_key" terraform.tfvars | cut -d'"' -f2)
    if [ ${#secret_key} -lt 50 ]; then
        print_error "Django secret key must be at least 50 characters long"
        exit 1
    fi
    
    print_success "Configuration validated!"
}

# Function to estimate costs
estimate_costs() {
    print_status "Estimating monthly costs for staging environment..."
    
    echo ""
    echo "┌─────────────────────────────────────────────────────────────┐"
    echo "│                    COST ESTIMATION                         │"
    echo "├─────────────────────────────────────────────────────────────┤"
    echo "│ Service              │ Configuration    │ Monthly Cost     │"
    echo "├─────────────────────────────────────────────────────────────┤"
    echo "│ ECS Fargate Spot     │ 128 CPU, 256MB  │ $3-5 USD        │"
    echo "│ RDS PostgreSQL       │ t3.micro, 20GB  │ $4-6 USD        │"
    echo "│ Application LB       │ Basic config     │ $2 USD          │"
    echo "│ S3 Storage          │ Standard storage │ $1 USD          │"
    echo "│ VPC/Secrets/Logs    │ Minimal usage    │ $1-2 USD        │"
    echo "├─────────────────────────────────────────────────────────────┤"
    echo "│ TOTAL ESTIMATED     │                  │ $8-15 USD       │"
    echo "└─────────────────────────────────────────────────────────────┘"
    echo ""
    
    print_warning "Costs may vary based on usage patterns and AWS pricing changes."
    print_status "Budget alert will notify you at 80% of \$15/month."
}

# Function to deploy infrastructure
deploy_infrastructure() {
    print_status "Deploying infrastructure..."
    
    # Initialize Terraform
    print_status "Initializing Terraform..."
    terraform init
    
    # Plan deployment
    print_status "Planning deployment..."
    terraform plan -var-file="terraform.tfvars" -out=tfplan
    
    # Ask for confirmation
    echo ""
    read -p "Do you want to proceed with the deployment? (y/N): " confirm
    if [[ $confirm != [yY] && $confirm != [yY][eE][sS] ]]; then
        print_warning "Deployment cancelled."
        rm -f tfplan
        exit 0
    fi
    
    # Apply deployment
    print_status "Applying deployment..."
    terraform apply tfplan
    rm -f tfplan
    
    print_success "Infrastructure deployed successfully!"
}

# Function to build and push Docker image
build_and_push_image() {
    print_status "Building and pushing Docker image..."
    
    # Get ECR repository URL
    ECR_REPO=$(terraform output -raw ecr_repository_url)
    
    if [ -z "$ECR_REPO" ]; then
        print_error "Could not get ECR repository URL. Infrastructure may not be deployed."
        exit 1
    fi
    
    # Get AWS account ID
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    
    # Login to ECR
    print_status "Logging in to ECR..."
    aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com
    
    # Build image
    print_status "Building Docker image..."
    cd ../../../  # Go to trazo-back directory
    docker build -t $PROJECT_NAME-backend-staging -f docker/Dockerfile.dev .
    
    # Tag image
    print_status "Tagging image..."
    docker tag $PROJECT_NAME-backend-staging:latest $ECR_REPO:latest
    
    # Push image
    print_status "Pushing image to ECR..."
    docker push $ECR_REPO:latest
    
    cd terraform/environments/staging/  # Return to terraform directory
    
    print_success "Docker image built and pushed successfully!"
}

# Function to update ECS service
update_ecs_service() {
    print_status "Updating ECS service with new image..."
    
    # Get cluster and service names
    CLUSTER_NAME=$(terraform output -raw ecs_cluster_name)
    SERVICE_NAME=$(terraform output -raw ecs_service_name)
    
    # Force new deployment
    aws ecs update-service \
        --cluster $CLUSTER_NAME \
        --service $SERVICE_NAME \
        --force-new-deployment \
        --region $REGION \
        > /dev/null
    
    print_success "ECS service update initiated!"
}

# Function to run database migrations
run_migrations() {
    print_status "Waiting for service to be running..."
    
    # Get cluster and service names
    CLUSTER_NAME=$(terraform output -raw ecs_cluster_name)
    SERVICE_NAME=$(terraform output -raw ecs_service_name)
    
    # Wait for service to be stable
    print_status "Waiting for ECS service to stabilize..."
    aws ecs wait services-stable --cluster $CLUSTER_NAME --services $SERVICE_NAME --region $REGION
    
    # Get running task
    TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER_NAME --service-name $SERVICE_NAME --region $REGION --query 'taskArns[0]' --output text)
    
    if [ "$TASK_ARN" = "None" ] || [ -z "$TASK_ARN" ]; then
        print_warning "No running tasks found. You may need to run migrations manually later."
        print_status "To run migrations manually:"
        echo "  aws ecs execute-command --cluster $CLUSTER_NAME --task <task-id> --container django --command 'python manage.py migrate' --interactive"
        return
    fi
    
    print_status "Running database migrations..."
    
    # Run migrations
    aws ecs execute-command \
        --cluster $CLUSTER_NAME \
        --task $TASK_ARN \
        --container django \
        --command "python manage.py migrate" \
        --interactive \
        --region $REGION || print_warning "Migration command failed. You may need to run it manually."
    
    print_success "Database migrations completed!"
}

# Function to display deployment information
show_deployment_info() {
    print_success "Deployment completed successfully!"
    
    echo ""
    echo "┌─────────────────────────────────────────────────────────────┐"
    echo "│                    DEPLOYMENT INFO                          │"
    echo "└─────────────────────────────────────────────────────────────┘"
    
    # Get outputs
    ALB_DNS=$(terraform output -raw alb_dns_name)
    ECR_REPO=$(terraform output -raw ecr_repository_url)
    CLUSTER_NAME=$(terraform output -raw ecs_cluster_name)
    SERVICE_NAME=$(terraform output -raw ecs_service_name)
    
    echo ""
    echo "🌐 API Endpoint:"
    echo "   http://$ALB_DNS"
    echo ""
    echo "🔍 Health Check:"
    echo "   http://$ALB_DNS/health/"
    echo ""
    echo "👤 Admin Panel:"
    echo "   http://$ALB_DNS/admin/"
    echo ""
    echo "📊 View Logs:"
    echo "   aws logs tail /ecs/staging --follow"
    echo ""
    echo "🔄 Scale Service:"
    echo "   aws ecs update-service --cluster $CLUSTER_NAME --service $SERVICE_NAME --desired-count 1"
    echo ""
    echo "🛑 Stop Service (to save costs):"
    echo "   aws ecs update-service --cluster $CLUSTER_NAME --service $SERVICE_NAME --desired-count 0"
    echo ""
    echo "💰 Cost Optimization Features:"
    echo "   ✅ Fargate Spot Instances (-70% cost)"
    echo "   ✅ Scheduled Scaling (8AM-8PM UTC)"
    echo "   ✅ Weekend Hibernation (Fri 10PM - Mon 8AM UTC)"
    echo "   ✅ Single AZ Deployment"
    echo "   ✅ Minimal Resources (128 CPU, 256MB RAM)"
    echo "   ✅ 1-day log retention"
    echo ""
    echo "📧 Budget alerts will be sent to the configured email address."
    echo ""
}

# Function to show help
show_help() {
    echo "Trazo Staging Deployment Script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  deploy         Deploy the complete staging environment"
    echo "  infrastructure Deploy only the infrastructure"
    echo "  image          Build and push Docker image only"
    echo "  update         Update ECS service with new image"
    echo "  migrate        Run database migrations"
    echo "  costs          Show cost estimation"
    echo "  destroy        Destroy the staging environment"
    echo "  help           Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 deploy      # Full deployment"
    echo "  $0 update      # Update application only"
    echo "  $0 costs       # Show cost breakdown"
    echo ""
}

# Function to destroy environment
destroy_environment() {
    print_warning "This will destroy the entire staging environment!"
    echo ""
    read -p "Are you sure you want to destroy the staging environment? (type 'yes' to confirm): " confirm
    if [[ $confirm != "yes" ]]; then
        print_warning "Destruction cancelled."
        exit 0
    fi
    
    print_status "Destroying staging environment..."
    terraform destroy -var-file="terraform.tfvars" -auto-approve
    print_success "Staging environment destroyed!"
}

# Main function
main() {
    echo "🚀 Trazo Staging Environment Deployment"
    echo "========================================"
    echo ""
    
    case "${1:-deploy}" in
        "deploy")
            check_prerequisites
            validate_config
            estimate_costs
            deploy_infrastructure
            build_and_push_image
            update_ecs_service
            run_migrations
            show_deployment_info
            ;;
        "infrastructure")
            check_prerequisites
            validate_config
            deploy_infrastructure
            ;;
        "image")
            check_prerequisites
            build_and_push_image
            ;;
        "update")
            check_prerequisites
            build_and_push_image
            update_ecs_service
            ;;
        "migrate")
            check_prerequisites
            run_migrations
            ;;
        "costs")
            estimate_costs
            ;;
        "destroy")
            check_prerequisites
            destroy_environment
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            print_error "Unknown command: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@" 