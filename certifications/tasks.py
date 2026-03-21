import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="certifications.tasks.reverify_all_certifications")
def reverify_all_certifications():
    """Monthly batch re-verification of all active certifications."""
    from .services.verification_manager import VerificationManager

    manager = VerificationManager()
    result = manager.reverify_all_active(days_ahead=36500)
    logger.info(
        f"Certification re-verification complete: " f"{result['total']} checked, {result['changed']} status changes"
    )
    return result
