#!/bin/bash

# Create dedicated CI/CD user with minimal permissions
# Run this script to create secure credentials for GitHub Actions

echo "🔑 Creating dedicated CI/CD user for Trazo Backend deployment..."

# Create IAM user for CI/CD
aws iam create-user --user-name trazo-ci-cd --tags Key=Purpose,Value=GitHubActions Key=Project,Value=Trazo

# Create IAM policy with minimal required permissions
cat > trazo-ci-policy.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ECRPermissions",
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:BatchImportLayerPart",
                "ecr:InitiateLayerUpload",
                "ecr:UploadLayerPart",
                "ecr:CompleteLayerUpload",
                "ecr:PutImage"
            ],
            "Resource": [
                "arn:aws:ecr:us-east-2:013640213707:repository/trazo-backend"
            ]
        },
        {
            "Sid": "ECRTokenPermission",
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken"
            ],
            "Resource": "*"
        },
        {
            "Sid": "ECSPermissions",
            "Effect": "Allow",
            "Action": [
                "ecs:DescribeTaskDefinition",
                "ecs:RegisterTaskDefinition",
                "ecs:UpdateService",
                "ecs:DescribeServices",
                "ecs:DescribeTasks",
                "ecs:ListTasks"
            ],
            "Resource": [
                "arn:aws:ecs:us-east-2:013640213707:cluster/staging-cluster",
                "arn:aws:ecs:us-east-2:013640213707:service/staging-cluster/staging-django-service",
                "arn:aws:ecs:us-east-2:013640213707:service/staging-cluster/staging-django",
                "arn:aws:ecs:us-east-2:013640213707:task-definition/staging-django:*"
            ]
        },
        {
            "Sid": "IAMPassRolePermission",
            "Effect": "Allow",
            "Action": [
                "iam:PassRole"
            ],
            "Resource": [
                "arn:aws:iam::013640213707:role/ecsTaskExecutionRole"
            ]
        }
    ]
}
EOF

# Create the policy
aws iam create-policy \
    --policy-name TrazoCICDPolicy \
    --policy-document file://trazo-ci-policy.json \
    --description "Minimal permissions for Trazo CI/CD pipeline"

# Attach policy to user
aws iam attach-user-policy \
    --user-name trazo-ci-cd \
    --policy-arn "arn:aws:iam::013640213707:policy/TrazoCICDPolicy"

# Create access key
echo "Creating access key for trazo-ci-cd user..."
aws iam create-access-key --user-name trazo-ci-cd --output table

echo ""
echo "✅ CI/CD user created successfully!"
echo "🔒 Use the AccessKeyId and SecretAccessKey shown above for GitHub Secrets"
echo ""
echo "Next steps:"
echo "1. Copy the AccessKeyId and SecretAccessKey from above"
echo "2. Add them as GitHub repository secrets:"
echo "   AWS_ACCESS_KEY_ID: <AccessKeyId>"
echo "   AWS_SECRET_ACCESS_KEY: <SecretAccessKey>"

# Clean up temporary policy file
rm trazo-ci-policy.json