"""
Secure settings override for Trazo
Uses secure key manager for sensitive configuration
"""

import logging
import os

from django.conf import settings

from backend.security import get_secure_key

logger = logging.getLogger(__name__)


def apply_secure_settings(settings_dict):
    """
    Apply secure settings by replacing sensitive values with secure key manager values

    Args:
        settings_dict: Dictionary of Django settings to update
    """

    # Map of setting names to secure key names and fallback environment variables
    SECURE_SETTINGS_MAP = {
        "BLOCKCHAIN_PRIVATE_KEY": ("blockchain_private_key", "BLOCKCHAIN_PRIVATE_KEY"),
        "USDA_API_KEY": ("usda_api_key", "USDA_API_KEY"),
        "USDA_NASS_API_KEY": ("usda_nass_api_key", "USDA_NASS_API_KEY"),
        "STRIPE_SECRET_KEY": ("stripe_secret_key", "STRIPE_SECRET_KEY"),
        "STRIPE_WEBHOOK_SECRET": ("stripe_webhook_secret", "STRIPE_WEBHOOK_SECRET"),
        "OPENAI_API_KEY": ("openai_api_key", "OPENAI_API_KEY"),
        "SENDGRID_API_KEY": ("sendgrid_api_key", "SENDGRID_API_KEY"),
        "AWS_ACCESS_KEY_ID": ("aws_access_key_id", "AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": ("aws_secret_access_key", "AWS_SECRET_ACCESS_KEY"),
        "GOOGLE_CLIENT_SECRET": ("google_client_secret", "GOOGLE_CLIENT_SECRET"),
        "FACEBOOK_APP_SECRET": ("facebook_app_secret", "FACEBOOK_APP_SECRET"),
        "APPLE_PRIVATE_KEY": ("apple_private_key", "APPLE_PRIVATE_KEY"),
        "ICR_API_KEY": ("icr_api_key", "ICR_API_KEY"),
    }

    # Special handling for EMAIL_HOST_PASSWORD (uses SENDGRID_API_KEY)
    sendgrid_key = get_secure_key("sendgrid_api_key", "SENDGRID_API_KEY")
    if sendgrid_key:
        settings_dict["EMAIL_HOST_PASSWORD"] = sendgrid_key

    # Apply secure settings
    for setting_name, (secure_key_name, fallback_env_var) in SECURE_SETTINGS_MAP.items():
        secure_value = get_secure_key(secure_key_name, fallback_env_var)
        if secure_value:
            settings_dict[setting_name] = secure_value
            logger.info(f"Applied secure setting for {setting_name}")
        else:
            logger.warning(f"No secure value found for {setting_name}")

    return settings_dict


def get_blockchain_config():
    """
    Get blockchain configuration from secure storage

    Returns:
        Dict with blockchain configuration
    """
    return {
        "private_key": get_secure_key("blockchain_private_key", "BLOCKCHAIN_PRIVATE_KEY"),
        "rpc_url": os.environ.get("POLYGON_RPC_URL"),
        "contract_address": os.environ.get("CARBON_CONTRACT_ADDRESS"),
        "credit_contract_address": os.environ.get("CARBON_CREDIT_CONTRACT_ADDRESS"),
    }


def get_usda_config():
    """
    Get USDA API configuration from secure storage

    Returns:
        Dict with USDA API configuration
    """
    return {
        "api_key": get_secure_key("usda_api_key", "USDA_API_KEY"),
        "nass_api_key": get_secure_key("usda_nass_api_key", "USDA_NASS_API_KEY"),
    }


def get_stripe_config():
    """
    Get Stripe configuration from secure storage

    Returns:
        Dict with Stripe configuration
    """
    return {
        "secret_key": get_secure_key("stripe_secret_key", "STRIPE_SECRET_KEY"),
        "webhook_secret": get_secure_key("stripe_webhook_secret", "STRIPE_WEBHOOK_SECRET"),
        "public_key": os.environ.get("STRIPE_PUBLIC_KEY"),  # Public key can remain in env
    }


def get_aws_config():
    """
    Get AWS configuration from secure storage

    Returns:
        Dict with AWS configuration
    """
    return {
        "access_key_id": get_secure_key("aws_access_key_id", "AWS_ACCESS_KEY_ID"),
        "secret_access_key": get_secure_key("aws_secret_access_key", "AWS_SECRET_ACCESS_KEY"),
        "region": os.environ.get("AWS_REGION", "us-east-1"),
        "kms_key_id": os.environ.get("AWS_KMS_KEY_ID"),
    }


def validate_secure_configuration():
    """
    Validate that all required secure configuration is available

    Returns:
        Tuple of (is_valid, missing_keys)
    """
    required_keys = [
        "blockchain_private_key",
        "stripe_secret_key",
        "sendgrid_api_key",
    ]

    missing_keys = []

    for key in required_keys:
        if not get_secure_key(key):
            missing_keys.append(key)

    return len(missing_keys) == 0, missing_keys
