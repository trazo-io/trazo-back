# AWS Budget Auto-Shutdown System

This document describes the automatic service shutdown system triggered when AWS costs exceed the budget threshold.

## Overview

When the AWS budget threshold is exceeded, a Lambda function automatically stops all staging services to prevent further charges.

```
AWS Budget ($10 threshold)
    ↓ (100% exceeded)
SNS Topic (us-east-1: trazo-budget-alert)
    ↓
Lambda Function (us-east-1: trazo-budget-shutdown)
    ↓ (targets us-east-2 resources)
Stop Services:
  • ECS Services → desired_count = 0
  • RDS Instances → stopped
  • EC2 Instances → stopped
```

## Resources

| Resource | Region | ARN/Name |
|----------|--------|----------|
| SNS Topic | us-east-1 | `arn:aws:sns:us-east-1:013640213707:trazo-budget-alert` |
| Lambda Function | us-east-1 | `arn:aws:lambda:us-east-1:013640213707:function:trazo-budget-shutdown` |
| IAM Role | Global | `TrazoBudgetShutdownRole` |
| Budget | Global | `My Monthly Cost Budget` |

## Manual Operations

### Trigger Emergency Shutdown

To manually stop all services when budget is exceeded:

```bash
# Execute the shutdown Lambda
aws lambda invoke \
  --function-name trazo-budget-shutdown \
  --region us-east-1 \
  /tmp/shutdown_response.json

# Check the response
cat /tmp/shutdown_response.json | python3 -m json.tool
```

### Verify Services Are Stopped

```bash
# Check ECS services
aws ecs describe-services \
  --cluster staging-cluster \
  --services staging-django-service staging-django \
  --region us-east-2 \
  --query 'services[*].{Name:serviceName,Desired:desiredCount,Running:runningCount}' \
  --output table

# Check RDS instances
aws rds describe-db-instances \
  --region us-east-2 \
  --query 'DBInstances[*].{ID:DBInstanceIdentifier,Status:DBInstanceStatus}' \
  --output table

# Check EC2 instances
aws ec2 describe-instances \
  --region us-east-2 \
  --query 'Reservations[*].Instances[*].{ID:InstanceId,Name:Tags[?Key==`Name`].Value|[0],State:State.Name}' \
  --output table
```

### Restart Services After Shutdown

To bring services back online:

```bash
# 1. Start EC2 NAT instance first (required for private subnet connectivity)
aws ec2 start-instances \
  --instance-ids i-016624b129261be89 \
  --region us-east-2

# 2. Start RDS instance
aws rds start-db-instance \
  --db-instance-identifier staging-postgres \
  --region us-east-2

# 3. Wait for RDS to be available (~5-10 minutes)
aws rds wait db-instance-available \
  --db-instance-identifier staging-postgres \
  --region us-east-2

# 4. Scale up ECS services
aws ecs update-service \
  --cluster staging-cluster \
  --service staging-django-service \
  --desired-count 1 \
  --region us-east-2

aws ecs update-service \
  --cluster staging-cluster \
  --service staging-django \
  --desired-count 1 \
  --region us-east-2
```

### Update Budget Threshold

To change the budget limit:

```bash
# Update to new threshold (e.g., $75)
aws budgets update-budget \
  --account-id 013640213707 \
  --new-budget '{
    "BudgetName": "My Monthly Cost Budget",
    "BudgetLimit": {
      "Amount": "75",
      "Unit": "USD"
    },
    "TimeUnit": "MONTHLY",
    "BudgetType": "COST"
  }' \
  --region us-east-1
```

### Check Current Budget Status

```bash
aws budgets describe-budgets \
  --account-id 013640213707 \
  --region us-east-1
```

## Lambda Function Details

### What It Stops

1. **ECS Services**: Sets `desiredCount` to 0 for all services in all clusters
2. **RDS Instances**: Stops all `available` database instances
3. **EC2 Instances**: Stops all `running` instances (NAT instance, etc.)

### Lambda Code Location

The Lambda function code is deployed to AWS. Source reference:

```python
# Key logic in trazo-budget-shutdown Lambda
region = os.environ.get('TARGET_REGION', 'us-east-2')

# Stop ECS services
ecs.update_service(cluster=cluster_arn, service=service_arn, desiredCount=0)

# Stop RDS instances
rds.stop_db_instance(DBInstanceIdentifier=db_id)

# Stop EC2 instances
ec2.stop_instances(InstanceIds=instance_ids)
```

### IAM Permissions

The `TrazoBudgetShutdownRole` has permissions for:
- `ecs:UpdateService`, `ecs:ListClusters`, `ecs:ListServices`, `ecs:DescribeServices`
- `rds:StopDBInstance`, `rds:DescribeDBInstances`
- `ec2:StopInstances`, `ec2:DescribeInstances`
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`

## Budget Notifications

The budget has the following notification thresholds:

| Threshold | Type | Subscribers |
|-----------|------|-------------|
| 85% | ACTUAL | Email (osmunogue@gmail.com) |
| 100% | ACTUAL | Email + SNS (triggers Lambda) |
| 100% | FORECASTED | Email |

## Cost Savings

When all services are stopped:

| Service | Running Cost | Stopped Cost |
|---------|--------------|--------------|
| ECS Fargate | ~$5-6/month | $0 |
| RDS t3.micro | ~$15/month | $0 (storage only: ~$2) |
| EC2 NAT t3.nano | ~$4/month | $0 |
| ALB | ~$16/month | ~$16/month (fixed) |
| **Total** | ~$40-45/month | ~$18/month |

**Note**: ALB continues to incur hourly charges even when no targets are healthy.

## Troubleshooting

### Lambda Permission Errors

If the Lambda fails with permission errors, check the IAM policy:

```bash
aws iam get-role-policy \
  --role-name TrazoBudgetShutdownRole \
  --policy-name TrazoBudgetShutdownPolicy
```

### View Lambda Logs

```bash
aws logs tail /aws/lambda/trazo-budget-shutdown \
  --region us-east-1 \
  --follow
```

### Budget Not Triggering

AWS Budgets checks costs periodically (not real-time). If the budget is already in ALARM state, it won't re-trigger. You may need to:

1. Manually invoke the Lambda
2. Or wait for the next billing cycle

## Created

- **Date**: 2025-12-06
- **Reason**: Cost control for staging environment
- **Budget**: $10/month (exceeded at time of creation)
