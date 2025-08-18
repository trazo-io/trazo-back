"""
Secure AWS credential management utilities.
Handles AWS credential access with proper security practices.
"""

import logging

from django.conf import settings

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

logger = logging.getLogger(__name__)


class SecureAWSClient:
    """
    Secure AWS client factory that properly handles credentials.
    Prefers IAM roles over explicit credentials for better security.
    """

    @staticmethod
    def get_s3_client():
        """
        Get S3 client with proper credential handling.

        Returns:
            boto3.client: Configured S3 client

        Raises:
            NoCredentialsError: If no valid credentials are available
        """
        try:
            # First, try to use IAM role (preferred for ECS/EC2)
            if SecureAWSClient._is_running_on_aws():
                logger.info("Using IAM role for S3 access")
                return boto3.client("s3", region_name=settings.AWS_S3_REGION_NAME)

            # For local development, use credentials from settings
            # These should NEVER be hardcoded - only from environment variables
            if hasattr(settings, "AWS_ACCESS_KEY_ID") and hasattr(settings, "AWS_SECRET_ACCESS_KEY"):
                if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                    logger.info("Using explicit credentials for S3 access")
                    return boto3.client(
                        "s3",
                        region_name=settings.AWS_S3_REGION_NAME,
                        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    )

            # Try default credential chain (AWS CLI, instance metadata, etc.)
            logger.info("Using default credential chain for S3 access")
            return boto3.client("s3", region_name=settings.AWS_S3_REGION_NAME)

        except NoCredentialsError:
            logger.error("No AWS credentials found. Please configure IAM role or set environment variables.")
            raise
        except Exception as e:
            logger.error(f"Error creating S3 client: {str(e)}")
            raise

    @staticmethod
    def _is_running_on_aws():
        """
        Check if the application is running on AWS (ECS/EC2).

        Returns:
            bool: True if running on AWS, False otherwise
        """
        try:
            # Try to access instance metadata
            import requests

            response = requests.get("http://169.254.169.254/latest/meta-data/instance-id", timeout=1)
            return response.status_code == 200
        except:
            return False

    @staticmethod
    def validate_s3_configuration():
        """
        Validate S3 configuration and credentials.

        Returns:
            tuple: (is_valid, error_message)
        """
        try:
            # Check required settings
            if not hasattr(settings, "AWS_STORAGE_BUCKET_NAME") or not settings.AWS_STORAGE_BUCKET_NAME:
                return False, "AWS_STORAGE_BUCKET_NAME is not configured"

            if not hasattr(settings, "AWS_S3_REGION_NAME") or not settings.AWS_S3_REGION_NAME:
                return False, "AWS_S3_REGION_NAME is not configured"

            # Try to get client and list buckets as a test
            client = SecureAWSClient.get_s3_client()
            client.head_bucket(Bucket=settings.AWS_STORAGE_BUCKET_NAME)

            return True, None

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "404":
                return False, f"Bucket '{settings.AWS_STORAGE_BUCKET_NAME}' not found"
            elif error_code == "403":
                return False, "Access denied to S3 bucket. Check IAM permissions."
            else:
                return False, f"S3 configuration error: {str(e)}"
        except NoCredentialsError:
            return False, "No valid AWS credentials found"
        except Exception as e:
            return False, f"S3 configuration validation error: {str(e)}"
