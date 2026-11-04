"""
Secure Key Management System for Trazo
Handles AWS Secrets Manager integration and key rotation
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.cache import cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Every production boot imports settings three times (migrate, collectstatic, gunicorn), and each
# import looks up ~14 secrets here before falling back to environment variables. botocore's
# defaults are a 60 s connect timeout and a 60 s read timeout with retries, so one stalled
# connection to Secrets Manager held the import for a minute: on 2026-11-04 the container spent
# 63 s before its first secret lookup returned, App Platform's readiness probe gave up after 13
# attempts, and the deploy was rolled back. A lookup that cannot answer in a few seconds is
# treated like any other failure: logged, and the environment variable is used.
SECRETS_CLIENT_CONFIG = Config(
    connect_timeout=3,
    read_timeout=5,
    retries={"max_attempts": 2, "mode": "standard"},
)

#: After a connection timeout, how long lookups skip Secrets Manager and use the environment. A
#: window, not a permanent switch (review of back #288): `SecureKeyManager` is a process-lifetime
#: singleton that also serves request-time lookups and `/api/security/health/`, so a flag that
#: never reset would turn one network blip into a worker that never asks again.
UNREACHABLE_BACKOFF_SECONDS = 60


class SecureKeyManager:
    """
    Manages secure storage and retrieval of API keys and blockchain private keys
    Uses AWS Secrets Manager for production and encrypted local storage for development
    """

    def __init__(self):
        self.is_production = getattr(settings, "ENVIRONMENT", "development") == "production"
        self.aws_region = getattr(settings, "AWS_SECRETS_MANAGER_REGION", "us-east-1")
        self.cache_ttl = 3600  # 1 hour cache TTL
        # time.monotonic() before which lookups skip Secrets Manager (see UNREACHABLE_BACKOFF_SECONDS).
        self._unreachable_until = 0.0

        # Initialize AWS Secrets Manager client if in production
        if self.is_production:
            try:
                self.secrets_client = boto3.client(
                    "secretsmanager",
                    region_name=self.aws_region,
                    aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", None),
                    aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", None),
                    config=SECRETS_CLIENT_CONFIG,
                )
            except Exception as e:
                logger.error(f"Failed to initialize AWS Secrets Manager client: {e}")
                self.secrets_client = None
        else:
            self.secrets_client = None

        # Initialize encryption key for local development
        self.encryption_key = self._get_or_create_encryption_key()

    def _get_or_create_encryption_key(self) -> bytes:
        """Get or create encryption key for local development"""
        key_file = os.path.join(settings.BASE_DIR, ".encryption_key")

        if os.path.exists(key_file):
            with open(key_file, "rb") as f:
                return f.read()
        else:
            # Generate new key
            key = Fernet.generate_key()
            with open(key_file, "wb") as f:
                f.write(key)
            # Make file readable only by owner
            os.chmod(key_file, 0o600)
            return key

    def store_secret(self, secret_name: str, secret_value: str, description: str = "") -> bool:
        """
        Store a secret securely

        Args:
            secret_name: Name of the secret
            secret_value: Value to store
            description: Optional description

        Returns:
            True if successful, False otherwise
        """
        try:
            if self.is_production and self.secrets_client:
                # Use AWS Secrets Manager
                response = self.secrets_client.create_secret(
                    Name=f"trazo/{secret_name}",
                    SecretString=secret_value,
                    Description=description or f"Trazo {secret_name} secret",
                )
                logger.info(f"Secret {secret_name} stored in AWS Secrets Manager")
                return True
            else:
                # Use local encrypted storage for development
                fernet = Fernet(self.encryption_key)
                encrypted_value = fernet.encrypt(secret_value.encode())

                # Store in local file
                secrets_dir = os.path.join(settings.BASE_DIR, ".secrets")
                os.makedirs(secrets_dir, exist_ok=True)

                secret_file = os.path.join(secrets_dir, f"{secret_name}.enc")
                with open(secret_file, "wb") as f:
                    f.write(encrypted_value)

                # Make file readable only by owner
                os.chmod(secret_file, 0o600)
                logger.info(f"Secret {secret_name} stored locally (encrypted)")
                return True

        except Exception as e:
            logger.error(f"Failed to store secret {secret_name}: {e}")
            return False

    def get_secret(self, secret_name: str, fallback_env_var: str = None) -> Optional[str]:
        """
        Retrieve a secret securely

        Args:
            secret_name: Name of the secret
            fallback_env_var: Environment variable to use as fallback

        Returns:
            Secret value if found, None otherwise
        """
        # Check cache first
        cache_key = f"secret_{secret_name}"
        cached_value = cache.get(cache_key)
        if cached_value:
            return cached_value

        try:
            if self.is_production and self.secrets_client:
                if not self.secrets_unreachable():
                    # Use AWS Secrets Manager. Inside the back-off window this is skipped and the
                    # environment fallback below answers.
                    response = self.secrets_client.get_secret_value(SecretId=f"trazo/{secret_name}")
                    secret_value = response["SecretString"]

                    # Cache the value
                    cache.set(cache_key, secret_value, self.cache_ttl)
                    return secret_value
            else:
                # Use local encrypted storage for development
                secrets_dir = os.path.join(settings.BASE_DIR, ".secrets")
                secret_file = os.path.join(secrets_dir, f"{secret_name}.enc")

                if os.path.exists(secret_file):
                    with open(secret_file, "rb") as f:
                        encrypted_value = f.read()

                    fernet = Fernet(self.encryption_key)
                    secret_value = fernet.decrypt(encrypted_value).decode()

                    # Cache the value
                    cache.set(cache_key, secret_value, self.cache_ttl)
                    return secret_value

        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.warning(f"Secret {secret_name} not found in AWS Secrets Manager")
            else:
                logger.error(f"AWS Secrets Manager error for {secret_name}: {e}")
        except (ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError) as e:
            # Unreachable, not missing. Stop asking for a while: the next ~13 lookups of a boot
            # would each wait out the same timeout, which is the minute-long stall
            # SECRETS_CLIENT_CONFIG exists to prevent. Callers fall back to the environment, and
            # the first lookup after the window tries Secrets Manager again.
            self._unreachable_until = time.monotonic() + UNREACHABLE_BACKOFF_SECONDS
            logger.error(
                f"AWS Secrets Manager unreachable ({e}); using environment variables for "
                f"{UNREACHABLE_BACKOFF_SECONDS} s"
            )
        except Exception as e:
            logger.error(f"Failed to retrieve secret {secret_name}: {e}")

        # Fallback to environment variable
        if fallback_env_var:
            env_value = os.environ.get(fallback_env_var)
            if env_value:
                logger.warning(f"Using environment variable {fallback_env_var} for {secret_name}")
                return env_value

        return None

    def secrets_unreachable(self) -> bool:
        """True inside the back-off window that follows a connection timeout."""
        return time.monotonic() < self._unreachable_until

    def rotate_secret(self, secret_name: str, new_value: str) -> bool:
        """
        Rotate a secret to a new value

        Args:
            secret_name: Name of the secret
            new_value: New value for the secret

        Returns:
            True if successful, False otherwise
        """
        try:
            if self.is_production and self.secrets_client:
                # Update in AWS Secrets Manager
                self.secrets_client.update_secret(SecretId=f"trazo/{secret_name}", SecretString=new_value)
                logger.info(f"Secret {secret_name} rotated in AWS Secrets Manager")
            else:
                # Update local encrypted storage
                if self.store_secret(secret_name, new_value):
                    logger.info(f"Secret {secret_name} rotated locally")
                else:
                    return False

            # Clear cache
            cache_key = f"secret_{secret_name}"
            cache.delete(cache_key)

            return True

        except Exception as e:
            logger.error(f"Failed to rotate secret {secret_name}: {e}")
            return False

    def list_secrets(self) -> Dict[str, Dict[str, Any]]:
        """
        List all secrets with metadata

        Returns:
            Dictionary of secrets with metadata
        """
        secrets = {}

        try:
            if self.is_production and self.secrets_client:
                # List from AWS Secrets Manager
                response = self.secrets_client.list_secrets()

                for secret in response.get("SecretList", []):
                    if secret["Name"].startswith("trazo/"):
                        secret_name = secret["Name"].replace("trazo/", "")
                        secrets[secret_name] = {
                            "last_changed": secret.get("LastChangedDate"),
                            "description": secret.get("Description", ""),
                            "source": "aws_secrets_manager",
                        }
            else:
                # List from local encrypted storage
                secrets_dir = os.path.join(settings.BASE_DIR, ".secrets")
                if os.path.exists(secrets_dir):
                    for filename in os.listdir(secrets_dir):
                        if filename.endswith(".enc"):
                            secret_name = filename.replace(".enc", "")
                            secret_file = os.path.join(secrets_dir, filename)
                            stat = os.stat(secret_file)

                            secrets[secret_name] = {
                                "last_changed": datetime.fromtimestamp(stat.st_mtime),
                                "description": "Local encrypted storage",
                                "source": "local_encrypted",
                            }

        except Exception as e:
            logger.error(f"Failed to list secrets: {e}")

        return secrets

    def health_check(self) -> Dict[str, Any]:
        """
        Check the health of the key management system

        Returns:
            Health check results
        """
        health = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "environment": "production" if self.is_production else "development",
            "issues": [],
        }

        try:
            if self.is_production:
                if not self.secrets_client:
                    health["issues"].append("AWS Secrets Manager client not initialized")
                    health["status"] = "unhealthy"
                elif self.secrets_unreachable():
                    # Temporary by construction: lookups resume after the back-off window.
                    health["issues"].append("AWS Secrets Manager unreachable; using environment variables for now")
                    health["status"] = "degraded"
                else:
                    # Test AWS connectivity
                    try:
                        self.secrets_client.list_secrets(MaxResults=1)
                    except Exception as e:
                        health["issues"].append(f"AWS Secrets Manager connectivity issue: {e}")
                        health["status"] = "degraded"
            else:
                # Check local encryption key
                if not os.path.exists(os.path.join(settings.BASE_DIR, ".encryption_key")):
                    health["issues"].append("Local encryption key not found")
                    health["status"] = "unhealthy"

        except Exception as e:
            health["issues"].append(f"Health check failed: {e}")
            health["status"] = "unhealthy"

        return health


# Global instance - lazy initialization to avoid import issues
_secure_key_manager = None


def get_secure_key_manager():
    global _secure_key_manager
    if _secure_key_manager is None:
        _secure_key_manager = SecureKeyManager()
    return _secure_key_manager


# Note: secure_key_manager is available via get_secure_key_manager() function


def get_secure_key(key_name: str, fallback_env_var: str = None) -> Optional[str]:
    """
    Convenience function to get a secure key

    Args:
        key_name: Name of the key
        fallback_env_var: Environment variable to use as fallback

    Returns:
        Key value if found, None otherwise
    """
    return get_secure_key_manager().get_secret(key_name, fallback_env_var)
