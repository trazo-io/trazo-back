#!/bin/bash

# Trazo Terraform-based Deployment Script
# This script updates your existing Terraform infrastructure with the new Docker image

set -e

echo "🚀 Trazo Terraform Deployment"
echo "============================="

# Configuration
NEW_IMAGE="013640213707.dkr.ecr.us-east-1.amazonaws.com/trazo-backend:v1.1.0-20250716-131005"
LATEST_IMAGE="013640213707.dkr.ecr.us-east-1.amazonaws.com/trazo-backend:latest"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# Check if we're in a terraform directory
check_terraform() {
    if [[ ! -f "*.tf" && ! -d "terraform" && ! -f "main.tf" ]]; then
        print_warning "No Terraform files found in current directory."
        print_status "Please run this script from your Terraform directory, or provide the path:"
        read -p "Enter path to Terraform directory (or press Enter to continue anyway): " terraform_path
        if [[ -n "$terraform_path" ]]; then
            cd "$terraform_path"
        fi
    fi
}

# Update terraform variables or configuration
update_terraform_image() {
    print_status "Updating Terraform configuration with new image..."
    
    # Look for common Terraform variable files
    for file in terraform.tfvars terraform.tfvars.json variables.tf main.tf; do
        if [[ -f "$file" ]]; then
            print_status "Found $file - you may need to update the Docker image reference"
            
            # Check if file contains image references
            if grep -q "trazo-backend" "$file"; then
                print_status "Found trazo-backend references in $file"
                
                # Ask user if they want to update automatically
                echo "Current image references:"
                grep -n "trazo-backend\|docker.*image" "$file" || true
                echo ""
                
                read -p "Do you want to update the image reference to ${NEW_IMAGE}? (y/n): " update_image
                if [[ "$update_image" == "y" ]]; then
                    # Backup original file
                    cp "$file" "$file.backup.$(date +%Y%m%d-%H%M%S)"
                    
                    # Update image reference (this is a basic approach)
                    sed -i.bak "s|013640213707\.dkr\.ecr\.us-east-1\.amazonaws\.com/trazo-backend:[^\"]*|${NEW_IMAGE}|g" "$file"
                    
                    print_success "Updated image reference in $file"
                    print_status "Backup saved as $file.backup.$(date +%Y%m%d-%H%M%S)"
                fi
            fi
        fi
    done
}

# Run terraform plan
run_terraform_plan() {
    print_status "Running Terraform plan..."
    
    if command -v terraform &> /dev/null; then
        terraform init
        terraform plan -out=tfplan
        
        print_status "Terraform plan completed. Review the changes above."
        read -p "Do you want to apply these changes? (y/n): " apply_changes
        
        if [[ "$apply_changes" == "y" ]]; then
            terraform apply tfplan
            print_success "Terraform apply completed!"
        else
            print_warning "Terraform apply skipped."
        fi
    else
        print_error "Terraform not found. Please install Terraform or run the deployment manually."
    fi
}

# Alternative: Direct ECS deployment if no Terraform changes needed
deploy_direct_ecs() {
    print_status "Attempting direct ECS deployment..."
    
    # Check if service exists
    if aws ecs describe-services --cluster trazo-cluster --services trazo-backend-service --region us-east-1 &>/dev/null; then
        print_status "Found existing ECS service. Forcing new deployment..."
        
        aws ecs update-service \
            --cluster trazo-cluster \
            --service trazo-backend-service \
            --force-new-deployment \
            --region us-east-1
            
        print_success "ECS service deployment initiated!"
        
        # Wait for deployment to complete
        print_status "Waiting for deployment to complete..."
        aws ecs wait services-stable --cluster trazo-cluster --services trazo-backend-service --region us-east-1
        
        print_success "Deployment completed successfully!"
    else
        print_warning "No existing ECS service found. Please deploy using Terraform first."
    fi
}

# Main execution
main() {
    print_status "New Docker image ready: ${NEW_IMAGE}"
    print_status "Latest tag: ${LATEST_IMAGE}"
    echo ""
    
    check_terraform
    
    echo "Choose deployment method:"
    echo "1. Update Terraform configuration and apply"
    echo "2. Direct ECS service update (if service already exists)"
    echo "3. Manual - just show deployment commands"
    
    read -p "Enter your choice (1-3): " choice
    
    case $choice in
        1)
            update_terraform_image
            run_terraform_plan
            ;;
        2)
            deploy_direct_ecs
            ;;
        3)
            echo ""
            print_status "Manual deployment commands:"
            echo ""
            echo "If using Terraform:"
            echo "1. Update your Terraform configuration with the new image:"
            echo "   ${NEW_IMAGE}"
            echo "2. Run: terraform plan"
            echo "3. Run: terraform apply"
            echo ""
            echo "If using direct AWS CLI:"
            echo "1. Update ECS service:"
            echo "   aws ecs update-service --cluster trazo-cluster --service YOUR_SERVICE --force-new-deployment"
            echo ""
            echo "2. Run post-deployment tasks:"
            echo "   aws ecs execute-command --cluster trazo-cluster --task TASK_ARN --container trazo-backend --interactive --command 'python manage.py migrate'"
            echo "   aws ecs execute-command --cluster trazo-cluster --task TASK_ARN --container trazo-backend --interactive --command 'python manage.py cache_production_members'"
            ;;
        *)
            print_error "Invalid choice. Exiting."
            exit 1
            ;;
    esac
}

# Run main function
main

print_success "Deployment script completed!"