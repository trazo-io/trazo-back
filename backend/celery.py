# from __future__ import absolute_import, unicode_literals

import os

from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

celery_app = Celery("trazo")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
celery_app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
celery_app.autodiscover_tasks()

# Authoritative periodic-task schedule — all beat tasks live here.
# Do NOT define CELERY_BEAT_SCHEDULE in settings files; that would silently
# overwrite this dict because celery_app.config_from_object() is called first.
celery_app.conf.beat_schedule = {
    # --- Subscription tasks ---
    "reset-monthly-scan-counts": {
        "task": "subscriptions.tasks.reset_monthly_scan_counts",
        "schedule": crontab(hour=0, minute=0, day_of_month=1),
    },
    "expire-starter-trials": {
        "task": "subscriptions.tasks.expire_trials",
        "schedule": crontab(hour=1, minute=0),  # Daily at 1 AM
    },
    "send-trial-lifecycle-emails": {
        "task": "subscriptions.tasks.send_trial_emails",
        "schedule": crontab(hour=8, minute=0),  # Daily at 8 AM
    },
    # --- Carbon nightly tasks ---
    "generate-nightly-reports": {
        "task": "carbon.tasks.generate_nightly_reports",
        "schedule": crontab(hour=0, minute=0),  # Midnight UTC
        "options": {"queue": "carbon"},
    },
    "award-sustainability-badges": {
        "task": "carbon.tasks.award_sustainability_badges",
        "schedule": crontab(hour=1, minute=0),  # 1 AM UTC
        "options": {"queue": "carbon"},
    },
    "cleanup-old-audit-logs": {
        "task": "carbon.tasks.cleanup_old_audit_logs",
        "schedule": crontab(hour=2, minute=0),  # 2 AM UTC
        "options": {"queue": "carbon"},
    },
    "update-industry-benchmarks": {
        "task": "carbon.tasks.update_industry_benchmarks",
        "schedule": crontab(hour=3, minute=0),  # 3 AM UTC
        "options": {"queue": "carbon"},
    },
    # --- Blockchain monthly tasks ---
    "batch-submit-monthly-summaries": {
        "task": "carbon.tasks.batch_submit_monthly_summaries",
        "schedule": crontab(hour=2, minute=0, day_of_month=1),  # 2 AM UTC on 1st of each month
    },
}


@celery_app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
