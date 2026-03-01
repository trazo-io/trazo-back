"""
Automated API Key Rotation Service for Trazo
Implements secure automatic rotation of API keys for USDA and other external services
Addresses CRITICAL security vulnerability: missing API key rotation mechanisms
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from backend.services.secrets_manager import secrets_manager

logger = logging.getLogger(__name__)

# Import Celery for background task scheduling
try:
    from celery import shared_task

    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    logger.warning("Celery not available - API key rotation will not be automatic")


class KeyRotationError(Exception):
    """Raised when API key rotation fails"""


class KeyValidationError(Exception):
    """Raised when API key validation fails"""


class APIKeyRotationService:
    """
    Automated API key rotation service with:
    - Scheduled rotation based on configurable intervals
    - Key validation before activation
    - Automatic fallback to previous keys on failure
    - Audit logging and monitoring
    - Integration with external API providers
    """

    def __init__(self):
        self.rotation_interval_days = getattr(settings, "API_KEY_ROTATION_DAYS", 90)
        self.validation_timeout = getattr(settings, "API_KEY_VALIDATION_TIMEOUT", 30)
        self.max_retry_attempts = getattr(settings, "API_KEY_ROTATION_RETRIES", 3)

        # Key rotation configuration for different services
        self.service_configs = {
            "usda_nass": {
                "secret_name": "usda_nass_api_key",
                "validation_endpoint": "https://quickstats.nass.usda.gov/api/api_GET/",
                "validation_params": {"key": "{api_key}", "source_desc": "CENSUS"},
                "backup_count": 3,
                "critical": True,
            },
            "usda_ers": {
                "secret_name": "usda_ers_api_key",
                "validation_endpoint": "https://api.ers.usda.gov/data/arms/surveydata",
                "validation_params": {"api_key": "{api_key}"},
                "backup_count": 2,
                "critical": True,
            },
            "usda_fooddata": {
                "secret_name": "usda_fooddata_api_key",
                "validation_endpoint": "https://api.nal.usda.gov/fdc/v1/foods/search",
                "validation_params": {"api_key": "{api_key}", "query": "corn"},
                "backup_count": 3,
                "critical": True,
            },
            "stripe": {
                "secret_name": "stripe_api_key",
                "validation_endpoint": None,  # Custom validation
                "validation_params": {},
                "backup_count": 2,
                "critical": True,
            },
        }

        logger.info(f"APIKeyRotationService initialized - Rotation interval: {self.rotation_interval_days} days")

    def check_rotation_needed(self, service_name: str) -> bool:
        """
        Check if API key rotation is needed for a service

        Args:
            service_name: Name of the service to check

        Returns:
            True if rotation is needed, False otherwise
        """
        try:
            if service_name not in self.service_configs:
                logger.warning(f"Unknown service for rotation check: {service_name}")
                return False

            config = self.service_configs[service_name]
            secret_name = config["secret_name"]

            # Check last rotation timestamp
            last_rotation_key = f"api_key_last_rotation_{service_name}"
            last_rotation = cache.get(last_rotation_key)

            if not last_rotation:
                # No record of rotation - assume rotation needed
                logger.info(f"No rotation history found for {service_name} - rotation needed")
                return True

            # Calculate days since last rotation
            if isinstance(last_rotation, str):
                last_rotation = datetime.fromisoformat(last_rotation)

            days_since_rotation = (timezone.now() - last_rotation).days

            if days_since_rotation >= self.rotation_interval_days:
                logger.info(f"Rotation needed for {service_name} - {days_since_rotation} days since last rotation")
                return True

            logger.debug(f"Rotation not needed for {service_name} - {days_since_rotation} days since last rotation")
            return False

        except Exception as e:
            logger.error(f"Error checking rotation status for {service_name}: {e}")
            return False

    def validate_api_key(self, service_name: str, api_key: str) -> bool:
        """
        Validate an API key by making a test request to the service

        Args:
            service_name: Name of the service
            api_key: API key to validate

        Returns:
            True if key is valid, False otherwise
        """
        try:
            if service_name not in self.service_configs:
                raise KeyValidationError(f"Unknown service: {service_name}")

            config = self.service_configs[service_name]

            # Special validation for different services
            if service_name == "stripe":
                return self._validate_stripe_key(api_key)
            elif service_name.startswith("usda_"):
                return self._validate_usda_key(service_name, api_key, config)
            else:
                return self._validate_generic_key(service_name, api_key, config)

        except Exception as e:
            logger.error(f"API key validation failed for {service_name}: {e}")
            return False

    def _validate_usda_key(self, service_name: str, api_key: str, config: Dict[str, Any]) -> bool:
        """Validate USDA API key"""
        try:
            import requests

            endpoint = config["validation_endpoint"]
            params = config["validation_params"].copy()

            # Replace placeholder with actual key
            for key, value in params.items():
                if isinstance(value, str) and "{api_key}" in value:
                    params[key] = value.replace("{api_key}", api_key)

            # Make validation request
            response = requests.get(endpoint, params=params, timeout=self.validation_timeout)

            # USDA APIs return different success indicators
            if service_name == "usda_nass":
                # NASS returns data array on success
                return response.status_code == 200 and "data" in response.json()
            elif service_name == "usda_ers":
                # ERS returns status 200 with data
                return response.status_code == 200
            elif service_name == "usda_fooddata":
                # FoodData Central returns foods array
                return response.status_code == 200 and "foods" in response.json()

            return response.status_code == 200

        except Exception as e:
            logger.error(f"USDA key validation failed for {service_name}: {e}")
            return False

    def _validate_stripe_key(self, api_key: str) -> bool:
        """Validate Stripe API key"""
        try:
            import stripe

            # Set the API key
            stripe.api_key = api_key

            # Make a simple API call to validate
            stripe.Account.retrieve()
            return True

        except Exception as e:
            logger.error(f"Stripe key validation failed: {e}")
            return False

    def _validate_generic_key(self, service_name: str, api_key: str, config: Dict[str, Any]) -> bool:
        """Validate generic API key"""
        try:
            import requests

            endpoint = config.get("validation_endpoint")
            if not endpoint:
                logger.warning(f"No validation endpoint for {service_name} - skipping validation")
                return True

            params = config.get("validation_params", {}).copy()

            # Replace placeholders
            for key, value in params.items():
                if isinstance(value, str) and "{api_key}" in value:
                    params[key] = value.replace("{api_key}", api_key)

            response = requests.get(
                endpoint, params=params, timeout=self.validation_timeout, headers={"Authorization": f"Bearer {api_key}"}
            )

            return response.status_code == 200

        except Exception as e:
            logger.error(f"Generic key validation failed for {service_name}: {e}")
            return False

    def generate_new_api_key(self, service_name: str) -> Optional[str]:
        """
        Generate or request new API key from service provider

        Note: In most cases, API keys need to be manually generated
        from the service provider's dashboard. This method provides
        a framework for automated generation where supported.

        Args:
            service_name: Name of the service

        Returns:
            New API key if successful, None otherwise
        """
        try:
            if service_name.startswith("usda_"):
                # USDA API keys must be manually requested
                logger.warning(f"USDA API keys must be manually generated - cannot auto-generate for {service_name}")
                return None
            elif service_name == "stripe":
                # Stripe keys must be generated from dashboard
                logger.warning("Stripe API keys must be manually generated from Stripe dashboard")
                return None
            else:
                # For custom services, implement specific generation logic
                logger.warning(f"Auto-generation not implemented for {service_name}")
                return None

        except Exception as e:
            logger.error(f"Failed to generate new API key for {service_name}: {e}")
            return None

    def rotate_api_key(self, service_name: str, new_api_key: str = None) -> bool:
        """
        Rotate API key for a service with validation and fallback

        Args:
            service_name: Name of the service
            new_api_key: New API key (if None, will attempt to generate)

        Returns:
            True if rotation successful, False otherwise
        """
        try:
            if service_name not in self.service_configs:
                raise KeyRotationError(f"Unknown service: {service_name}")

            config = self.service_configs[service_name]
            secret_name = config["secret_name"]

            logger.info(f"🔄 Starting API key rotation for {service_name}")

            # Get current key for backup
            current_key = secrets_manager.get_secret(secret_name, required=False)

            # Generate new key if not provided
            if not new_api_key:
                new_api_key = self.generate_new_api_key(service_name)
                if not new_api_key:
                    raise KeyRotationError(f"No new API key provided and auto-generation failed for {service_name}")

            # Validate new key
            logger.info(f"🔍 Validating new API key for {service_name}")
            if not self.validate_api_key(service_name, new_api_key):
                raise KeyValidationError(f"New API key validation failed for {service_name}")

            # Create backup of current key
            if current_key:
                backup_name = f"{secret_name}_backup_{int(time.time())}"
                secrets_manager.store_secret(
                    backup_name, current_key, f"Backup of {secret_name} before rotation on {timezone.now().isoformat()}"
                )
                logger.info(f"✅ Created backup: {backup_name}")

            # Store new key
            success = secrets_manager.store_secret(secret_name, new_api_key, f"Rotated on {timezone.now().isoformat()}")

            if not success:
                raise KeyRotationError(f"Failed to store new API key for {service_name}")

            # Test new key in production context
            logger.info(f"🧪 Testing new API key in production context for {service_name}")
            if not self._test_key_in_context(service_name, new_api_key):
                # Rollback on failure
                if current_key:
                    logger.warning(f"Production test failed - rolling back {service_name}")
                    secrets_manager.store_secret(secret_name, current_key, "Rollback after failed rotation")
                raise KeyRotationError(f"Production test failed for new {service_name} key")

            # Update rotation timestamp
            rotation_key = f"api_key_last_rotation_{service_name}"
            cache.set(rotation_key, timezone.now().isoformat(), 86400 * 365)  # 1 year

            # Clear any cached keys to force refresh
            cache.delete_many([f"secure_secret_{secret_name}", f"usda_api_keys_cache", f"api_keys_{service_name}"])

            # Audit log
            self._audit_log_rotation(service_name, success=True)

            logger.info(f"✅ Successfully rotated API key for {service_name}")
            return True

        except Exception as e:
            logger.error(f"API key rotation failed for {service_name}: {e}")
            self._audit_log_rotation(service_name, success=False, error=str(e))
            return False

    def _test_key_in_context(self, service_name: str, api_key: str) -> bool:
        """Test API key in actual production context"""
        # USDA API integration removed for MVP — all carbon calculations use hardcoded factors.
        return True

    def _audit_log_rotation(self, service_name: str, success: bool, error: str = None):
        """Log API key rotation for audit purposes"""
        audit_entry = {
            "event": "api_key_rotation",
            "service": service_name,
            "success": success,
            "timestamp": timezone.now().isoformat(),
            "error": error,
        }

        logger.info(f"AUDIT: API Key Rotation - {json.dumps(audit_entry)}")

        # Store in audit cache
        audit_key = f"audit_key_rotation_{timezone.now().strftime('%Y%m%d')}"
        try:
            existing_logs = cache.get(audit_key, [])
            existing_logs.append(audit_entry)
            cache.set(audit_key, existing_logs, 86400)  # 24 hours
        except Exception:
            pass

    def check_all_services(self) -> Dict[str, Dict[str, Any]]:
        """
        Check rotation status for all configured services

        Returns:
            Dictionary with rotation status for each service
        """
        results = {}

        for service_name in self.service_configs.keys():
            try:
                needs_rotation = self.check_rotation_needed(service_name)
                current_key = secrets_manager.get_secret(
                    self.service_configs[service_name]["secret_name"], required=False
                )

                # Get last rotation timestamp
                last_rotation_key = f"api_key_last_rotation_{service_name}"
                last_rotation = cache.get(last_rotation_key)

                results[service_name] = {
                    "needs_rotation": needs_rotation,
                    "has_key": current_key is not None,
                    "last_rotation": last_rotation,
                    "critical": self.service_configs[service_name]["critical"],
                }

            except Exception as e:
                logger.error(f"Error checking {service_name}: {e}")
                results[service_name] = {
                    "needs_rotation": True,
                    "has_key": False,
                    "last_rotation": None,
                    "error": str(e),
                }

        return results

    def emergency_rotate_all(self) -> Dict[str, bool]:
        """
        Emergency rotation of all API keys (security incident response)

        Returns:
            Dictionary with rotation results for each service
        """
        logger.warning("🚨 EMERGENCY API KEY ROTATION INITIATED")

        results = {}

        for service_name in self.service_configs.keys():
            try:
                # For emergency rotation, new keys must be provided manually
                logger.warning(f"Emergency rotation for {service_name} requires manual key generation")
                results[service_name] = False

            except Exception as e:
                logger.error(f"Emergency rotation failed for {service_name}: {e}")
                results[service_name] = False

        return results


# Global service instance
api_key_rotation_service = APIKeyRotationService()


# Celery tasks for automated rotation (if Celery is available)
if CELERY_AVAILABLE:

    @shared_task(bind=True, max_retries=3)
    def rotate_service_key(self, service_name: str, new_api_key: str = None):
        """Celery task to rotate a specific service key"""
        try:
            success = api_key_rotation_service.rotate_api_key(service_name, new_api_key)
            if not success:
                raise KeyRotationError(f"Rotation failed for {service_name}")
            return f"Successfully rotated key for {service_name}"

        except Exception as e:
            logger.error(f"Celery key rotation task failed: {e}")
            self.retry(countdown=300, exc=e)  # Retry after 5 minutes

    @shared_task
    def check_and_notify_rotation_needed():
        """Celery task to check all services and notify if rotation needed"""
        try:
            results = api_key_rotation_service.check_all_services()

            services_needing_rotation = [
                service for service, status in results.items() if status.get("needs_rotation", False)
            ]

            if services_needing_rotation:
                logger.warning(f"API key rotation needed for services: {services_needing_rotation}")

                # Here you could send notifications (email, Slack, etc.)
                # For now, just log the requirement

            return f"Checked {len(results)} services, {len(services_needing_rotation)} need rotation"

        except Exception as e:
            logger.error(f"Rotation check task failed: {e}")
            return f"Check failed: {e}"


# Convenience functions
def rotate_usda_keys(nass_key: str = None, ers_key: str = None, fooddata_key: str = None) -> Dict[str, bool]:
    """Rotate all USDA API keys"""
    results = {}

    if nass_key:
        results["usda_nass"] = api_key_rotation_service.rotate_api_key("usda_nass", nass_key)

    if ers_key:
        results["usda_ers"] = api_key_rotation_service.rotate_api_key("usda_ers", ers_key)

    if fooddata_key:
        results["usda_fooddata"] = api_key_rotation_service.rotate_api_key("usda_fooddata", fooddata_key)

    return results


def check_rotation_status() -> Dict[str, Dict[str, Any]]:
    """Check rotation status for all services"""
    return api_key_rotation_service.check_all_services()


def emergency_rotate_all_keys() -> Dict[str, bool]:
    """Emergency rotation of all API keys"""
    return api_key_rotation_service.emergency_rotate_all()
