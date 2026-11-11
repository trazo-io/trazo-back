"""Delete account-closure exports 30 days after they were written (privacy policy 7.1).

The export is the farm's copy of its records, written by `close_account --export` so it can be
downloaded before the account is deleted. Kept in Trazo's storage any longer, it would be the data
the farm asked us to delete. Run daily by `run_due_maintenance`.
"""

from django.core.management.base import BaseCommand

from common.services.account_closure import EXPORT_RETENTION_DAYS, purge_old_exports


class Command(BaseCommand):
    help = "Delete account-closure exports older than 30 days."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=EXPORT_RETENTION_DAYS)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        removed = purge_old_exports(days=options["days"], dry_run=options["dry_run"])
        verb = "would delete" if options["dry_run"] else "deleted"
        self.stdout.write(f"{verb} {len(removed)} closure export(s)")
