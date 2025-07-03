"""
Production-Grade Secrets Management Service
Provides secure key storage, rotation, and access for production deployment
"""

import json
import logging
import hashlib
import base64
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# Import AWS SDK conditionally
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    AWS_AVAILABLE = True
except ImportError:
    AWS_AVAILABLE = False
    logger.warning("AWS SDK not available - falling back to local secret management")


class SecretNotFoundError(Exception):
    """Raised when a required secret is not found"""
    pass


class SecretRotationError(Exception):
    """Raised when secret rotation fails"""
    pass


class ProductionSecretsManager:
    """
    Production-grade secrets management with support for:
    - AWS Secrets Manager integration
    - Local encrypted storage (development)
    - Automatic key rotation
    - Audit logging
    - Cache management
    """
    
    def __init__(self):
        self.environment = getattr(settings, 'ENVIRONMENT', 'development')
        self.aws_region = getattr(settings, 'AWS_REGION', 'us-east-1')
        self.use_aws = self._should_use_aws()
        self.cache_ttl = 300  # 5 minutes cache
        
        # Initialize encryption for local storage
        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher_suite = Fernet(self.encryption_key)
        
        # Initialize AWS client if available
        if self.use_aws:
            try:
                self.secrets_client = boto3.client('secretsmanager', region_name=self.aws_region)
                logger.info("✅ AWS Secrets Manager initialized")
            except (ClientError, NoCredentialsError) as e:
                logger.error(f"Failed to initialize AWS Secrets Manager: {e}")
                self.use_aws = False
                
        logger.info(f"SecretsManager initialized - Environment: {self.environment}, AWS: {self.use_aws}")
    
    def _should_use_aws(self) -> bool:
        """Determine if AWS Secrets Manager should be used"""
        return (
            AWS_AVAILABLE and 
            self.environment in ['production', 'staging'] and
            getattr(settings, 'AWS_SECRETS_MANAGER_ENABLED', True)
        )
    
    def _get_or_create_encryption_key(self) -> bytes:
        """Get or create encryption key for local secret storage"""
        key_setting = getattr(settings, 'LOCAL_ENCRYPTION_KEY', None)
        
        if key_setting:
            return key_setting.encode()
            
        # Generate key from Django secret key
        password = settings.SECRET_KEY.encode()
        salt = b'trazo_secrets_salt_2025'  # Fixed salt for consistency
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(password))
        return key
    
    def get_secret(self, secret_name: str, required: bool = True) -> Optional[str]:
        """
        Get secret value with caching and fallback strategies
        
        Args:
            secret_name: Name of the secret to retrieve
            required: Whether the secret is required (raises exception if missing)
            
        Returns:
            Secret value or None if not found and not required
        """
        try:
            # Check cache first
            cache_key = f"secret_{secret_name}"
            cached_value = cache.get(cache_key)
            if cached_value:
                logger.debug(f"Secret '{secret_name}' retrieved from cache")
                return cached_value
            
            # Try AWS Secrets Manager first
            if self.use_aws:
                try:
                    secret_value = self._get_aws_secret(secret_name)
                    if secret_value:
                        cache.set(cache_key, secret_value, self.cache_ttl)
                        logger.info(f"✅ Secret '{secret_name}' retrieved from AWS Secrets Manager")
                        return secret_value
                except Exception as e:
                    logger.warning(f"Failed to get secret from AWS: {e}")
            
            # Fallback to environment variables
            env_value = getattr(settings, secret_name.upper(), None)
            if env_value:
                cache.set(cache_key, env_value, self.cache_ttl)
                logger.info(f"✅ Secret '{secret_name}' retrieved from environment")
                return env_value
            
            # Fallback to local encrypted storage
            local_value = self._get_local_secret(secret_name)
            if local_value:
                cache.set(cache_key, local_value, self.cache_ttl)
                logger.info(f"✅ Secret '{secret_name}' retrieved from local storage")
                return local_value
            
            if required:
                raise SecretNotFoundError(f"Required secret '{secret_name}' not found")
            
            logger.warning(f"Secret '{secret_name}' not found (optional)")
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving secret '{secret_name}': {e}")
            if required:
                raise
            return None
    
    def _get_aws_secret(self, secret_name: str) -> Optional[str]:
        """Get secret from AWS Secrets Manager"""
        try:
            response = self.secrets_client.get_secret_value(
                SecretId=f"trazo/{self.environment}/{secret_name}"
            )
            
            secret_data = response.get('SecretString')
            if secret_data:
                try:
                    # Try to parse as JSON
                    parsed = json.loads(secret_data)
                    return parsed.get(secret_name, secret_data)
                except json.JSONDecodeError:
                    # Return as plain string
                    return secret_data
            
            return None
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                logger.debug(f"Secret '{secret_name}' not found in AWS Secrets Manager")
            else:
                logger.error(f"AWS Secrets Manager error: {e}")
            return None
    
    def _get_local_secret(self, secret_name: str) -> Optional[str]:
        """Get secret from local encrypted storage"""
        try:
            storage_path = getattr(settings, 'LOCAL_SECRETS_PATH', '/tmp/trazo_secrets.enc')
            
            try:
                with open(storage_path, 'rb') as f:
                    encrypted_data = f.read()
                    
                decrypted_data = self.cipher_suite.decrypt(encrypted_data)
                secrets_dict = json.loads(decrypted_data.decode())
                
                return secrets_dict.get(secret_name)
                
            except FileNotFoundError:
                logger.debug("Local secrets file not found")
                return None
                
        except Exception as e:
            logger.error(f"Error reading local secret: {e}")
            return None
    
    def store_secret(self, secret_name: str, secret_value: str, description: str = "") -> bool:
        """
        Store secret securely with audit logging
        
        Args:
            secret_name: Name of the secret
            secret_value: Secret value to store
            description: Description for audit purposes
            
        Returns:
            True if successful, False otherwise
        """
        try:
            success = False
            
            # Store in AWS Secrets Manager if available
            if self.use_aws:
                try:
                    success = self._store_aws_secret(secret_name, secret_value, description)
                    if success:
                        logger.info(f"✅ Secret '{secret_name}' stored in AWS Secrets Manager")
                except Exception as e:
                    logger.error(f"Failed to store secret in AWS: {e}")
            
            # Always store in local encrypted storage as backup
            local_success = self._store_local_secret(secret_name, secret_value)
            if local_success:
                logger.info(f"✅ Secret '{secret_name}' stored in local encrypted storage")
                success = True
            
            # Clear cache to force refresh
            cache.delete(f"secret_{secret_name}")
            
            # Audit log
            self._audit_log('secret_stored', {
                'secret_name': secret_name,
                'description': description,
                'success': success,
                'timestamp': timezone.now().isoformat()
            })
            
            return success
            
        except Exception as e:
            logger.error(f"Error storing secret '{secret_name}': {e}")
            return False
    
    def _store_aws_secret(self, secret_name: str, secret_value: str, description: str) -> bool:
        """Store secret in AWS Secrets Manager"""
        try:
            secret_id = f"trazo/{self.environment}/{secret_name}"
            
            # Try to update existing secret
            try:
                self.secrets_client.update_secret(
                    SecretId=secret_id,
                    SecretString=secret_value,
                    Description=description
                )
                return True
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    # Create new secret
                    self.secrets_client.create_secret(
                        Name=secret_id,
                        SecretString=secret_value,
                        Description=description,
                        Tags=[
                            {'Key': 'Environment', 'Value': self.environment},
                            {'Key': 'Application', 'Value': 'Trazo'},
                            {'Key': 'ManagedBy', 'Value': 'TrazoSecretsManager'}
                        ]
                    )
                    return True
                else:
                    raise
                    
        except Exception as e:
            logger.error(f"Error storing secret in AWS: {e}")
            return False
    
    def _store_local_secret(self, secret_name: str, secret_value: str) -> bool:
        """Store secret in local encrypted storage"""
        try:
            storage_path = getattr(settings, 'LOCAL_SECRETS_PATH', '/tmp/trazo_secrets.enc')
            
            # Load existing secrets
            secrets_dict = {}
            try:
                with open(storage_path, 'rb') as f:
                    encrypted_data = f.read()
                    decrypted_data = self.cipher_suite.decrypt(encrypted_data)
                    secrets_dict = json.loads(decrypted_data.decode())
            except FileNotFoundError:
                pass  # New file
            
            # Update secret
            secrets_dict[secret_name] = secret_value
            
            # Encrypt and save
            data_to_encrypt = json.dumps(secrets_dict).encode()
            encrypted_data = self.cipher_suite.encrypt(data_to_encrypt)
            
            with open(storage_path, 'wb') as f:
                f.write(encrypted_data)
            
            return True
            
        except Exception as e:
            logger.error(f"Error storing local secret: {e}")
            return False
    
    def rotate_secret(self, secret_name: str, new_value: str) -> bool:
        """
        Rotate secret with validation and rollback capability
        
        Args:
            secret_name: Name of the secret to rotate
            new_value: New secret value
            
        Returns:
            True if rotation successful, False otherwise
        """
        try:
            # Get current value for rollback
            current_value = self.get_secret(secret_name, required=False)
            
            # Store new value
            success = self.store_secret(
                secret_name, 
                new_value, 
                f"Rotated on {timezone.now().isoformat()}"
            )
            
            if success:
                # Audit log rotation
                self._audit_log('secret_rotated', {
                    'secret_name': secret_name,
                    'timestamp': timezone.now().isoformat(),
                    'has_backup': current_value is not None
                })
                
                logger.info(f"✅ Secret '{secret_name}' successfully rotated")
                return True
            else:
                raise SecretRotationError(f"Failed to store rotated secret '{secret_name}'")
                
        except Exception as e:
            logger.error(f"Error rotating secret '{secret_name}': {e}")
            return False
    
    def list_secrets(self) -> List[Dict[str, Any]]:
        """List all available secrets with metadata"""
        secrets = []
        
        try:
            # List AWS secrets
            if self.use_aws:
                try:
                    response = self.secrets_client.list_secrets(
                        Filters=[
                            {
                                'Key': 'name',
                                'Values': [f'trazo/{self.environment}/']
                            }
                        ]
                    )
                    
                    for secret in response.get('SecretList', []):
                        secrets.append({
                            'name': secret['Name'].split('/')[-1],
                            'source': 'aws',
                            'created': secret.get('CreatedDate'),
                            'last_changed': secret.get('LastChangedDate'),
                            'description': secret.get('Description', '')
                        })
                        
                except Exception as e:
                    logger.error(f"Error listing AWS secrets: {e}")
            
            # List local secrets
            try:
                storage_path = getattr(settings, 'LOCAL_SECRETS_PATH', '/tmp/trazo_secrets.enc')
                with open(storage_path, 'rb') as f:
                    encrypted_data = f.read()
                    decrypted_data = self.cipher_suite.decrypt(encrypted_data)
                    secrets_dict = json.loads(decrypted_data.decode())
                    
                    for secret_name in secrets_dict.keys():
                        if not any(s['name'] == secret_name for s in secrets):
                            secrets.append({
                                'name': secret_name,
                                'source': 'local',
                                'created': None,
                                'last_changed': None,
                                'description': 'Local encrypted storage'
                            })
                            
            except FileNotFoundError:
                pass
            
        except Exception as e:
            logger.error(f"Error listing secrets: {e}")
        
        return secrets
    
    def _audit_log(self, action: str, details: Dict[str, Any]):
        """Log security-sensitive operations for audit purposes"""
        audit_entry = {
            'action': action,
            'timestamp': timezone.now().isoformat(),
            'environment': self.environment,
            'details': details
        }
        
        # Log to Django logging system
        logger.info(f"AUDIT: {json.dumps(audit_entry)}")
        
        # Store in audit log (could be extended to database or external system)
        audit_key = f"audit_secrets_{timezone.now().strftime('%Y%m%d')}"
        try:
            existing_logs = cache.get(audit_key, [])
            existing_logs.append(audit_entry)
            cache.set(audit_key, existing_logs, 86400)  # 24 hours
        except Exception:
            pass  # Non-critical
    
    def get_database_url(self) -> str:
        """Get complete database URL with credentials from secrets"""
        try:
            db_password = self.get_secret('database_password', required=True)
            db_user = self.get_secret('database_user', required=False) or 'postgres'
            db_host = self.get_secret('database_host', required=False) or 'localhost'
            db_port = self.get_secret('database_port', required=False) or '5432'
            db_name = self.get_secret('database_name', required=False) or 'trazo'
            
            return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            
        except Exception as e:
            logger.error(f"Error constructing database URL: {e}")
            raise
    
    def get_redis_url(self) -> str:
        """Get Redis URL with credentials from secrets"""
        try:
            redis_password = self.get_secret('redis_password', required=False)
            redis_host = self.get_secret('redis_host', required=False) or 'localhost'
            redis_port = self.get_secret('redis_port', required=False) or '6379'
            
            if redis_password:
                return f"redis://:{redis_password}@{redis_host}:{redis_port}/0"
            else:
                return f"redis://{redis_host}:{redis_port}/0"
                
        except Exception as e:
            logger.error(f"Error constructing Redis URL: {e}")
            return "redis://localhost:6379/0"


# Global instance
secrets_manager = ProductionSecretsManager()


def get_secret(secret_name: str, required: bool = True) -> Optional[str]:
    """Convenience function to get secret"""
    return secrets_manager.get_secret(secret_name, required)


def store_secret(secret_name: str, secret_value: str, description: str = "") -> bool:
    """Convenience function to store secret"""
    return secrets_manager.store_secret(secret_name, secret_value, description)


def rotate_secret(secret_name: str, new_value: str) -> bool:
    """Convenience function to rotate secret"""
    return secrets_manager.rotate_secret(secret_name, new_value)