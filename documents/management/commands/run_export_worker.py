"""
Claim and run background document builds (documents/services/export_jobs.py).

    poetry run python manage.py run_export_worker            # run until stopped
    poetry run python manage.py run_export_worker --once     # drain the queue and exit

Pair with EXPORT_JOB_RUNNER=worker on the web process so requests only enqueue. Postgres is
the queue (SELECT … FOR UPDATE SKIP LOCKED), so any number of these can run side by side.
"""

from django.core.management.base import BaseCommand

from documents.services.export_jobs import run_worker_loop


class Command(BaseCommand):
    help = "Run queued export jobs (operation dossiers) outside the request cycle."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Drain the queue once and exit.")
        parser.add_argument("--idle-seconds", type=float, default=2.0, help="Sleep between empty polls.")

    def handle(self, *args, **options):
        ran = run_worker_loop(once=options["once"], idle_seconds=options["idle_seconds"])
        if options["once"]:
            self.stdout.write(f"Ran {ran} job(s).")
