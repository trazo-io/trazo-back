"""
Celery tasks for the history app.

When Redis is not available, CELERY_TASK_ALWAYS_EAGER=True runs these
synchronously.  The gdpr_cleanup_scan_data task can also be triggered
manually via:  poetry run python manage.py cleanup_scan_data
"""

import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task(name="history.tasks.gdpr_cleanup_scan_data")
def gdpr_cleanup_scan_data():
    """
    Daily GDPR-compliant cleanup:
    1. Anonymise expired consented scans (past data_retention_until)
    2. Delete non-consented scans older than 7 days
    3. Remove old duplicate scans (>90 days)
    """
    logger.info("Starting GDPR scan data cleanup task")
    call_command("cleanup_scan_data")
    logger.info("GDPR scan data cleanup task completed")
