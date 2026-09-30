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
# NEVER: five entries were REMOVED from this schedule on 2026-09-30, and removing them is the fix,
# not a step towards scheduling them. Nothing has ever run this schedule in production (the DO app
# spec has no jobs: and no workers:, and REDIS_URL is unset so Celery runs eager), so "turning it on"
# would have STARTED them. Each removal, and the six pieces of periodic work that remain declared
# somewhere, are recorded in `backend/scheduled_work.py` with what runs them and what breaks:
#
#   generate-nightly-reports        wrote CarbonReport.carbon_score, 0-100, per establishment,
#                                   nightly, off a figure that nets offsets out of emissions
#   update-industry-benchmarks      wrote the denominator of that score from our own rows
#   award-sustainability-badges     wrote SustainabilityBadge rows, same class
#   batch-submit-monthly-summaries  selected companies with an active blockchain subscription, and
#                                   that add-on is is_active=False, so the query cannot match
#   reset-monthly-scan-counts       reset Subscription.scan_count, a column the API does not read:
#                                   the served value is computed from HistoryScan rows
#
# The three tasks in the first group are deleted outright in `carbon/tasks.py`. The other two tasks
# survive and are simply not scheduled.
celery_app.conf.beat_schedule = {
    # --- Subscription tasks ---
    "expire-starter-trials": {
        "task": "subscriptions.tasks.expire_trials",
        "schedule": crontab(hour=1, minute=0),  # Daily at 1 AM
    },
    "send-trial-lifecycle-emails": {
        "task": "subscriptions.tasks.send_trial_emails",
        "schedule": crontab(hour=8, minute=0),  # Daily at 8 AM
    },
    # Statutory: California's ARL requires an annual-renewal reminder 15-45 days out.
    # Daily, so a single missed run cannot push a customer past the window.
    "send-renewal-reminders": {
        "task": "subscriptions.tasks.send_renewal_reminders",
        "schedule": crontab(hour=8, minute=30),  # Daily at 8:30 AM
    },
    # --- Carbon nightly tasks ---
    "cleanup-old-audit-logs": {
        "task": "carbon.tasks.cleanup_old_audit_logs",
        "schedule": crontab(hour=2, minute=0),  # 2 AM UTC
        "options": {"queue": "carbon"},
    },
    # --- Blockchain monthly tasks ---
    # --- GDPR data retention ---
    "gdpr-cleanup-scan-data": {
        "task": "history.tasks.gdpr_cleanup_scan_data",
        "schedule": crontab(hour=3, minute=30),  # Daily at 3:30 AM UTC
    },
    # --- Certification re-verification ---
    "reverify-certifications-monthly": {
        "task": "certifications.tasks.reverify_all_certifications",
        "schedule": crontab(hour=4, minute=0, day_of_month=1),  # 4 AM UTC on 1st of each month
    },
}


@celery_app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
