"""Run the periodic work for one cadence, and report that it ran.

WHY A COMMAND AND NOT A CELERY BEAT PROCESS
-------------------------------------------
This work is cron, not a queue: periodic maintenance in a single-service app with no async
request-time load. Celery beat needed a broker, a worker component and a second failure domain to
run a handful of management commands, and it was never deployed, so for its whole life it ran
nothing. DigitalOcean App Platform supports `kind: SCHEDULED` jobs with a cron expression, billed
only while running, so the platform already has the right primitive. `.do/jobs.yaml` holds the
intended job definitions.

THE HEARTBEAT IS THE POINT, NOT AN EXTRA
----------------------------------------
NEVER: do not deploy this without one. App Platform has no `JOB_FAILED` alert. Its app-level rules
are DEPLOYMENT_CANCELLED / FAILED / LIVE / STARTED, DOMAIN_FAILED / LIVE and AUTOSCALE_FAILED /
SUCCEEDED, and its component rules are CPU_UTILIZATION, MEM_UTILIZATION and RESTART_COUNT. Nothing
fires when a job fails, and nothing fires when a job was never created. So a failure-triggered alert
cannot catch the bug this whole exercise came from: work that silently never ran.

A dead-man's switch can. The command pings an external monitor on success and pings its `/fail`
endpoint on failure; the monitor alerts when an expected ping does not ARRIVE. That inverts the
signal, so absence is what raises the alarm. Set MAINTENANCE_HEARTBEAT_URL_DAILY and
MAINTENANCE_HEARTBEAT_URL_MONTHLY. Unset means no heartbeat, which the command says out loud rather
than treating as fine.

WHY IT LIVES IN `common` AND NOT `backend`
-----------------------------------------
NOTE: `backend` is NOT in INSTALLED_APPS, so Django never discovers management commands there. That
is also why the pre-existing `backend/management/commands/migrate_secrets.py` has never been
runnable, which is worth knowing separately.

ONE FAILURE MUST NOT STOP THE OTHERS. The GDPR deletion not running is not a reason to skip the
statutory renewal notice, so each item is caught separately and the exit code reports the total.
"""

import logging

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from backend.scheduled_work import PERIODIC_WORK

logger = logging.getLogger(__name__)

_HEARTBEAT_TIMEOUT_SECONDS = 10


def _heartbeat_url(cadence):
    return getattr(settings, f"MAINTENANCE_HEARTBEAT_URL_{cadence.upper()}", "") or ""


def _ping(cadence, failed):
    """Tell the monitor this run happened. Never raises: a monitor outage is not a work failure."""
    url = _heartbeat_url(cadence)
    if not url:
        logger.warning(
            "No MAINTENANCE_HEARTBEAT_URL_%s set, so nothing will notice if this job stops running. "
            "That is the failure mode this command exists to prevent.",
            cadence.upper(),
        )
        return False
    try:
        import requests

        requests.get(f"{url}/fail" if failed else url, timeout=_HEARTBEAT_TIMEOUT_SECONDS)
        return True
    except Exception as exc:  # noqa: BLE001 - a monitor we cannot reach must not fail the work
        logger.error("Heartbeat ping failed: %s", exc)
        return False


class Command(BaseCommand):
    help = "Run every piece of periodic work registered for one cadence, then ping the heartbeat."

    def add_arguments(self, parser):
        parser.add_argument("--cadence", required=True, choices=("daily", "monthly"))
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would run and ping nothing. Safe against production.",
        )

    def handle(self, *args, **options):
        cadence = options["cadence"]
        due = {key: spec for key, spec in PERIODIC_WORK.items() if spec.get("cadence") == cadence}
        if not due:
            raise CommandError(
                f"No work is registered with cadence={cadence!r} in backend/scheduled_work.py. A job "
                "that runs nothing is worse than no job: it reports success forever."
            )

        if options["dry_run"]:
            for key, spec in sorted(due.items()):
                self.stdout.write(f"would run {key}: {spec.get('command') or spec.get('run')}")
            self.stdout.write(self.style.SUCCESS(f"{len(due)} item(s) registered for {cadence}"))
            return

        failures = []
        for key, spec in sorted(due.items()):
            try:
                if spec.get("command"):
                    call_command(spec["command"])
                else:
                    import_string(spec["run"])()
                self.stdout.write(self.style.SUCCESS(f"ok   {key}"))
            except Exception as exc:  # noqa: BLE001 - one item's failure must not skip the rest
                failures.append(key)
                logger.exception("Periodic work %s failed", key)
                self.stderr.write(self.style.ERROR(f"FAIL {key}: {exc}"))

        _ping(cadence, failed=bool(failures))

        if failures:
            raise CommandError(f"{len(failures)} of {len(due)} failed: {sorted(failures)}")
        self.stdout.write(self.style.SUCCESS(f"{len(due)} item(s) completed for {cadence}"))
