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
#   cleanup-old-audit-logs          deleted CarbonAuditLog over 365 days, an arbitrary constant
#                                   enforcing a retention policy nobody wrote, on rows that
#                                   include the gaming_detected fraud signal
#
# The three tasks in the first group are deleted outright in `carbon/tasks.py`. The other two tasks
# survive and are simply not scheduled.
# EMPTY, DELIBERATELY, since 2026-09-30. Every entry that used to live here is accounted for in
# `backend/scheduled_work.py`: three tasks deleted for writing a self-assigned grade, one deleted for
# deleting an audit trail inside a retention window, two kept as documented no-ops, two kept and
# simply not scheduled, and the rest now dispatched by `manage.py run_due_maintenance` from App
# Platform SCHEDULED jobs (`.do/jobs.yaml`).
#
# NEVER: do not add an entry here. Two reasons, and the second is the one that bites.
#
#   1. Nothing runs a beat schedule in production. The app spec has `services:` and no `jobs:` and no
#      `workers:`, and REDIS_URL is unset so Celery runs eager. An entry here has never fired and
#      would not fire now, so adding one declares work that does not happen.
#   2. DOUBLE DECLARATION. The work dispatched by `run_due_maintenance` was briefly declared BOTH
#      here and there. Nothing ran twice, because nothing ran the schedule at all, but anyone who
#      later deployed a beat process would have had every item execute twice a day. For
#      `send_renewal_reminders` that means a subscriber receiving the California ARL notice twice.
#      One declaration, in one place.
#
# Guard: `backend/tests/test_scheduled_work_has_a_runner.py` asserts this stays empty.
celery_app.conf.beat_schedule = {}


@celery_app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
