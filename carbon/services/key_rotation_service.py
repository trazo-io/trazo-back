"""
Key Rotation Service for Trazo
Implements automated key rotation and compliance tracking for sensitive credentials.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict

from django.core.cache import cache
from django.db import models

from carbon.services.secure_key_management import SecureKeyManager

logger = logging.getLogger(__name__)


class KeyRotationRecord(models.Model):
    """Track key rotation history for compliance"""

    key_name = models.CharField(max_length=255, db_index=True)
    rotated_at = models.DateTimeField(auto_now_add=True)
    rotated_by = models.CharField(max_length=255)
    rotation_method = models.CharField(max_length=50)  # automatic, manual
    old_key_hash = models.CharField(max_length=64)  # SHA256 hash of old key
    new_key_hash = models.CharField(max_length=64)  # SHA256 hash of new key
    status = models.CharField(max_length=20, default="success")
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-rotated_at"]
        indexes = [
            models.Index(fields=["key_name", "-rotated_at"]),
        ]


class KeyRotationService:
    """
    Automated key rotation service with compliance tracking.
    Ensures keys are rotated according to security policy.
    """

    def __init__(self):
        self.key_manager = SecureKeyManager()
        self.rotation_policies = {
            "blockchain_private_key": {
                "rotation_days": 90,
                "alert_days": 7,
                "requires_multisig": True,
                "notification_channels": ["email", "slack"],
            },
            "usda_api_keys": {
                "rotation_days": 180,
                "alert_days": 14,
                "requires_multisig": False,
                "notification_channels": ["email"],
            },
            "stripe_keys": {
                "rotation_days": 365,
                "alert_days": 30,
                "requires_multisig": True,
                "notification_channels": ["email", "slack"],
            },
        }

    def check_rotation_required(self, key_name: str) -> Dict[str, Any]:
        """
        Check if a key requires rotation based on policy.

        Returns:
            Dict with rotation status and details
        """
        try:
            policy = self.rotation_policies.get(key_name, {})
            if not policy:
                return {"requires_rotation": False, "reason": "No rotation policy defined"}

            # Get last rotation record
            last_rotation = KeyRotationRecord.objects.filter(key_name=key_name, status="success").first()

            if not last_rotation:
                return {"requires_rotation": True, "reason": "No rotation history found", "urgent": True}

            # Calculate days since last rotation
            days_since_rotation = (datetime.now() - last_rotation.rotated_at).days
            rotation_days = policy.get("rotation_days", 90)
            alert_days = policy.get("alert_days", 7)

            if days_since_rotation >= rotation_days:
                return {
                    "requires_rotation": True,
                    "reason": f"Key expired ({days_since_rotation} days old)",
                    "urgent": True,
                    "days_overdue": days_since_rotation - rotation_days,
                }
            elif days_since_rotation >= (rotation_days - alert_days):
                return {
                    "requires_rotation": False,
                    "reason": f"Key rotation due soon ({rotation_days - days_since_rotation} days remaining)",
                    "urgent": False,
                    "warning": True,
                    "days_remaining": rotation_days - days_since_rotation,
                }
            else:
                return {
                    "requires_rotation": False,
                    "reason": f"Key is current ({days_since_rotation} days old)",
                    "urgent": False,
                    "days_remaining": rotation_days - days_since_rotation,
                }

        except Exception as e:
            logger.error(f"Error checking rotation for {key_name}: {e}")
            return {"requires_rotation": False, "reason": f"Error checking rotation: {str(e)}", "error": True}

    def rotate_key(self, key_name: str, new_key_value: str, rotated_by: str = "system") -> bool:
        """
        Rotate a key with full audit trail.

        Args:
            key_name: Name of the key to rotate
            new_key_value: New key value
            rotated_by: User or system initiating rotation

        Returns:
            bool: Success status
        """
        try:
            # Get current key for comparison (hash only)
            try:
                if key_name == "blockchain_private_key":
                    current_key = self.key_manager.get_blockchain_private_key()
                elif key_name == "usda_api_keys":
                    current_key = json.dumps(self.key_manager.get_usda_api_keys())
                else:
                    current_key = self.key_manager.get_secret(f"trazo/{key_name}")
            except:
                current_key = None

            # Hash keys for audit log (never store actual keys)
            old_key_hash = hashlib.sha256(str(current_key).encode() if current_key else b"").hexdigest()
            new_key_hash = hashlib.sha256(str(new_key_value).encode()).hexdigest()

            # Store new key securely
            secret_name = f"trazo/{key_name}"
            if key_name == "usda_api_keys" and isinstance(new_key_value, dict):
                # Handle USDA keys as dict
                success = self.key_manager.store_secret(secret_name, new_key_value)
            else:
                success = self.key_manager.store_secret(secret_name, {"value": new_key_value})

            if success:
                # Record successful rotation
                KeyRotationRecord.objects.create(
                    key_name=key_name,
                    rotated_by=rotated_by,
                    rotation_method="manual" if rotated_by != "system" else "automatic",
                    old_key_hash=old_key_hash,
                    new_key_hash=new_key_hash,
                    status="success",
                )

                # Clear any cached keys
                cache_key = f"secure_key_{key_name}"
                cache.delete(cache_key)

                logger.info(f"Successfully rotated key: {key_name}")
                return True
            else:
                # Record failed rotation
                KeyRotationRecord.objects.create(
                    key_name=key_name,
                    rotated_by=rotated_by,
                    rotation_method="manual" if rotated_by != "system" else "automatic",
                    old_key_hash=old_key_hash,
                    new_key_hash=new_key_hash,
                    status="failed",
                    error_message="Failed to store new key",
                )
                return False

        except Exception as e:
            logger.error(f"Error rotating key {key_name}: {e}")

            # Record error
            KeyRotationRecord.objects.create(
                key_name=key_name,
                rotated_by=rotated_by,
                rotation_method="manual" if rotated_by != "system" else "automatic",
                old_key_hash="error",
                new_key_hash="error",
                status="error",
                error_message=str(e),
            )
            return False

    def get_rotation_compliance_report(self) -> Dict[str, Any]:
        """
        Generate compliance report for key rotation.

        Returns:
            Dict with compliance status for all keys
        """
        report = {"generated_at": datetime.now().isoformat(), "compliant": True, "keys": {}}

        for key_name, policy in self.rotation_policies.items():
            rotation_status = self.check_rotation_required(key_name)

            # Get rotation history
            rotation_history = KeyRotationRecord.objects.filter(key_name=key_name).order_by("-rotated_at")[:5]

            key_report = {
                "policy": policy,
                "current_status": rotation_status,
                "rotation_history": [
                    {"date": record.rotated_at.isoformat(), "method": record.rotation_method, "status": record.status}
                    for record in rotation_history
                ],
                "compliant": not rotation_status.get("urgent", False),
            }

            report["keys"][key_name] = key_report

            # Update overall compliance
            if not key_report["compliant"]:
                report["compliant"] = False

        return report

    def schedule_automated_rotation(self):
        """
        Schedule automated key rotation based on policies.
        This should be called by a Celery task.
        """
        for key_name, policy in self.rotation_policies.items():
            try:
                rotation_status = self.check_rotation_required(key_name)

                if rotation_status.get("requires_rotation") and rotation_status.get("urgent"):
                    logger.warning(f"Urgent key rotation required for {key_name}")
                    # In production, this would trigger automated rotation
                    # For now, just log and notify
                    self._send_rotation_alert(key_name, rotation_status)
                elif rotation_status.get("warning"):
                    logger.info(f"Key rotation warning for {key_name}")
                    self._send_rotation_warning(key_name, rotation_status)

            except Exception as e:
                logger.error(f"Error in automated rotation check for {key_name}: {e}")

    def _send_rotation_alert(self, key_name: str, status: Dict[str, Any]):
        """Send urgent rotation alert"""
        # In production, integrate with notification system
        logger.critical(f"URGENT: Key rotation required for {key_name} - {status}")

    def _send_rotation_warning(self, key_name: str, status: Dict[str, Any]):
        """Send rotation warning"""
        # In production, integrate with notification system
        logger.warning(f"Key rotation due soon for {key_name} - {status}")


# Singleton instance
key_rotation_service = KeyRotationService()
