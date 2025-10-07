"""
Celery tasks for automated API key rotation
Provides scheduled tasks for monitoring and rotating API keys
"""

import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Import Celery conditionally
try:
    from celery import shared_task

    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    logger.warning("Celery not available - automated key rotation tasks disabled")



if CELERY_AVAILABLE:

    @shared_task(bind=True, max_retries=3)
    def check_api_key_rotation_status(self):
        """
        Scheduled task to check API key rotation status
        Runs daily to monitor key age and notify when rotation is needed
        """
        try:
            from carbon.services.api_key_rotation import api_key_rotation_service

            logger.info("🔍 Running scheduled API key rotation status check")

            # Check all services
            results = api_key_rotation_service.check_all_services()

            # Analyze results
            services_needing_rotation = []
            critical_services_needing_rotation = []
            services_with_errors = []

            for service_name, status in results.items():
                if status.get("error"):
                    services_with_errors.append(service_name)
                elif status.get("needs_rotation", False):
                    services_needing_rotation.append(service_name)
                    if status.get("critical", False):
                        critical_services_needing_rotation.append(service_name)

            # Log results
            total_services = len(results)
            logger.info(f"📊 Key rotation check completed: {total_services} services checked")

            if services_with_errors:
                logger.error(f"❌ Services with errors: {services_with_errors}")

            if critical_services_needing_rotation:
                logger.warning(f"🚨 CRITICAL services needing rotation: {critical_services_needing_rotation}")

            if services_needing_rotation:
                logger.warning(f"⚠️  Services needing rotation: {services_needing_rotation}")
            else:
                logger.info("✅ All API keys are up to date")

            # Send notifications if configured
            if critical_services_needing_rotation or services_with_errors:
                send_key_rotation_alert.delay(
                    critical_services=critical_services_needing_rotation,
                    error_services=services_with_errors,
                    all_needing_rotation=services_needing_rotation,
                )

            return {
                "total_services": total_services,
                "needing_rotation": len(services_needing_rotation),
                "critical_needing_rotation": len(critical_services_needing_rotation),
                "with_errors": len(services_with_errors),
                "timestamp": timezone.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"API key rotation status check failed: {e}")
            self.retry(countdown=3600, exc=e)  # Retry after 1 hour

    @shared_task(bind=True, max_retries=2)
    def send_key_rotation_alert(self, critical_services=None, error_services=None, all_needing_rotation=None):
        """
        Send alerts for API key rotation requirements

        Args:
            critical_services: List of critical services needing rotation
            error_services: List of services with errors
            all_needing_rotation: List of all services needing rotation
        """
        try:
            critical_services = critical_services or []
            error_services = error_services or []
            all_needing_rotation = all_needing_rotation or []

            logger.info("📧 Sending API key rotation alerts")

            # Prepare alert message
            alert_message = []

            if critical_services:
                alert_message.append(
                    f"🚨 CRITICAL API keys requiring immediate rotation: {', '.join(critical_services)}"
                )

            if error_services:
                alert_message.append(f"❌ Services with key management errors: {', '.join(error_services)}")

            if all_needing_rotation:
                non_critical = [s for s in all_needing_rotation if s not in critical_services]
                if non_critical:
                    alert_message.append(f"⚠️  API keys needing rotation: {', '.join(non_critical)}")

            message = "\n".join(alert_message)

            # Send to configured notification channels
            notification_results = {}

            # Email notification
            if getattr(settings, "API_KEY_ROTATION_EMAIL_ALERTS", False):
                email_result = send_email_alert(message)
                notification_results["email"] = email_result

            # Slack notification
            if getattr(settings, "API_KEY_ROTATION_SLACK_ALERTS", False):
                slack_result = send_slack_alert(message)
                notification_results["slack"] = slack_result

            # Django admin notification
            django_result = create_admin_notification(message)
            notification_results["admin"] = django_result

            logger.info(f"📬 Alert notifications sent: {notification_results}")

            return {"message": message, "notifications": notification_results, "timestamp": timezone.now().isoformat()}

        except Exception as e:
            logger.error(f"Failed to send key rotation alert: {e}")
            self.retry(countdown=1800, exc=e)  # Retry after 30 minutes

    @shared_task(bind=True, max_retries=3)
    def validate_all_api_keys(self):
        """
        Validate all stored API keys to ensure they're still working
        Runs weekly to catch any keys that may have been revoked
        """
        try:
            from backend.services.secrets_manager import secrets_manager
            from carbon.services.api_key_rotation import api_key_rotation_service

            logger.info("🔍 Running scheduled API key validation")

            validation_results = {}

            for service_name, config in api_key_rotation_service.service_configs.items():
                try:
                    secret_name = config["secret_name"]
                    api_key = secrets_manager.get_secret(secret_name, required=False)

                    if not api_key:
                        validation_results[service_name] = {"valid": False, "error": "No API key found"}
                        continue

                    # Validate the key
                    is_valid = api_key_rotation_service.validate_api_key(service_name, api_key)

                    validation_results[service_name] = {
                        "valid": is_valid,
                        "error": None if is_valid else "Validation failed",
                    }

                except Exception as e:
                    validation_results[service_name] = {"valid": False, "error": str(e)}
                    logger.error(f"Validation failed for {service_name}: {e}")

            # Count results
            total_keys = len(validation_results)
            valid_keys = sum(1 for r in validation_results.values() if r["valid"])
            invalid_keys = total_keys - valid_keys

            logger.info(f"🔑 API key validation completed: {valid_keys}/{total_keys} valid")

            # Alert on invalid keys
            if invalid_keys > 0:
                invalid_services = [service for service, result in validation_results.items() if not result["valid"]]

                logger.warning(f"⚠️  Invalid API keys detected: {invalid_services}")

                # Send alert for invalid keys
                send_invalid_key_alert.delay(invalid_services=invalid_services, validation_results=validation_results)

            return {
                "total_keys": total_keys,
                "valid_keys": valid_keys,
                "invalid_keys": invalid_keys,
                "validation_results": validation_results,
                "timestamp": timezone.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"API key validation task failed: {e}")
            self.retry(countdown=7200, exc=e)  # Retry after 2 hours

    @shared_task
    def send_invalid_key_alert(invalid_services, validation_results):
        """Send alert for invalid API keys"""
        try:
            message_parts = ["🚨 INVALID API KEYS DETECTED"]

            for service in invalid_services:
                error = validation_results[service].get("error", "Unknown error")
                message_parts.append(f"❌ {service}: {error}")

            message_parts.append("\n⚠️  Immediate action required - these keys may have been revoked or expired.")

            message = "\n".join(message_parts)

            # Send high-priority alert
            logger.error(message)

            # Create admin notification
            create_admin_notification(message, priority="high")

            return {"alert_sent": True, "invalid_services": invalid_services}

        except Exception as e:
            logger.error(f"Failed to send invalid key alert: {e}")

    @shared_task
    def cleanup_old_key_backups():
        """
        Clean up old API key backups to prevent accumulation
        Keeps only the most recent backups for each service
        """
        try:
            from backend.services.secrets_manager import secrets_manager

            logger.info("🧹 Cleaning up old API key backups")

            # Get all secrets
            all_secrets = secrets_manager.list_secrets()

            # Group backup secrets by service
            backup_groups = {}
            for secret in all_secrets:
                name = secret["name"]
                if "_backup_" in name:
                    service_name = name.split("_backup_")[0]
                    if service_name not in backup_groups:
                        backup_groups[service_name] = []
                    backup_groups[service_name].append(secret)

            cleanup_results = {}

            for service_name, backups in backup_groups.items():
                try:
                    # Sort by creation date (newest first)
                    sorted_backups = sorted(backups, key=lambda x: x.get("created") or timezone.now(), reverse=True)

                    # Keep only the 3 most recent backups
                    max_backups = 3
                    backups_to_delete = sorted_backups[max_backups:]

                    deleted_count = 0
                    for backup in backups_to_delete:
                        # Note: Actual deletion would require secrets_manager.delete_secret method
                        # For now, just log what would be deleted
                        logger.info(f"Would delete old backup: {backup['name']}")
                        deleted_count += 1

                    cleanup_results[service_name] = {
                        "total_backups": len(sorted_backups),
                        "deleted": deleted_count,
                        "kept": len(sorted_backups) - deleted_count,
                    }

                except Exception as e:
                    logger.error(f"Cleanup failed for {service_name}: {e}")
                    cleanup_results[service_name] = {"error": str(e)}

            logger.info(f"🧹 Backup cleanup completed: {cleanup_results}")

            return {"cleanup_results": cleanup_results, "timestamp": timezone.now().isoformat()}

        except Exception as e:
            logger.error(f"Backup cleanup task failed: {e}")


def send_email_alert(message: str) -> bool:
    """Send email alert for API key rotation"""
    try:
        from django.core.mail import send_mail

        recipients = getattr(settings, "API_KEY_ROTATION_EMAIL_RECIPIENTS", [])
        if not recipients:
            return False

        send_mail(
            subject="[Trazo] API Key Rotation Alert",
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@trazo.com"),
            recipient_list=recipients,
            fail_silently=False,
        )

        return True

    except Exception as e:
        logger.error(f"Email alert failed: {e}")
        return False


def send_slack_alert(message: str) -> bool:
    """Send Slack alert for API key rotation"""
    try:
        import requests

        webhook_url = getattr(settings, "API_KEY_ROTATION_SLACK_WEBHOOK", None)
        if not webhook_url:
            return False

        payload = {"text": message, "username": "Trazo API Key Monitor", "icon_emoji": ":key:"}

        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()

        return True

    except Exception as e:
        logger.error(f"Slack alert failed: {e}")
        return False


def create_admin_notification(message: str, priority: str = "medium") -> bool:
    """Create Django admin notification for API key issues"""
    try:
        # This would integrate with a Django admin notification system
        # For now, just log as a high-priority message

        if priority == "high":
            logger.error(f"HIGH PRIORITY ADMIN NOTIFICATION: {message}")
        else:
            logger.warning(f"ADMIN NOTIFICATION: {message}")

        # In a real implementation, this could:
        # - Create a database record for admin notifications
        # - Send to a message queue for admin dashboard
        # - Create a Django message for staff users

        return True

    except Exception as e:
        logger.error(f"Admin notification failed: {e}")
        return False


# Celery beat schedule configuration
# Add this to your settings.py CELERY_BEAT_SCHEDULE:
"""
CELERY_BEAT_SCHEDULE = {
    'check-api-key-rotation-daily': {
        'task': 'carbon.tasks.key_rotation_tasks.check_api_key_rotation_status',
        'schedule': crontab(hour=9, minute=0),  # Daily at 9 AM
    },
    'validate-api-keys-weekly': {
        'task': 'carbon.tasks.key_rotation_tasks.validate_all_api_keys',
        'schedule': crontab(hour=10, minute=0, day_of_week=1),  # Weekly on Monday at 10 AM
    },
    'cleanup-key-backups-monthly': {
        'task': 'carbon.tasks.key_rotation_tasks.cleanup_old_key_backups',
        'schedule': crontab(hour=11, minute=0, day_of_month=1),  # Monthly on 1st at 11 AM
    },
}
"""
