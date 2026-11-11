"""Close a company's account on its written request (privacy policy 7.1, terms 13).

    # 1. What would go. Read-only, the default.
    python manage.py close_account --company 42
    # 2. Write the export to private storage and print a 7-day download link for the farm.
    python manage.py close_account --company 42 --export
    # 3. After the farm has the export: delete. Needs the exact company name.
    python manage.py close_account --company 42 --apply --confirm-name "Sunny Acres LLC"

`--apply` refuses unless step 2 left an export in storage. The export is deleted 30 days after it
was written, by `purge_closure_exports` in the daily maintenance job. The logic and the reasons are
in `common/services/account_closure.py`.

NEVER: run --apply on a request that has not been confirmed with the account's own email address.
It cannot be undone, and no restore report is kept, because keeping one would keep the data.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from common.services import account_closure
from company.models import Company


class Command(BaseCommand):
    help = "Export, then delete, a company's account and everything only it owns."

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, required=True, help="Company id.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--export", action="store_true", help="Write the closure export and print its link.")
        mode.add_argument("--apply", action="store_true", help="Delete. Requires an export and --confirm-name.")
        parser.add_argument("--confirm-name", default="", help="The company's exact name, required with --apply.")
        parser.add_argument("--run-by", default="", help="Who ran it, for the operation log.")

    def handle(self, *args, **options):
        try:
            company = Company.objects.get(pk=options["company"])
        except Company.DoesNotExist as exc:
            raise CommandError(f"No company with id {options['company']}.") from exc

        if options["export"]:
            key = account_closure.export(company)
            self.stdout.write(self.style.SUCCESS(f"Export written: {key}"))
            self.stdout.write(f"Download link (7 days): {account_closure.export_link(key)}")
            return

        if options["apply"]:
            try:
                counts = account_closure.apply(company, options["confirm_name"], run_by=options["run_by"])
            except account_closure.ClosureRefused as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(json.dumps(counts, indent=1, sort_keys=True, default=str))
            if counts.get("files_not_deleted"):
                raise CommandError(f"{len(counts['files_not_deleted'])} file(s) were not deleted from storage.")
            self.stdout.write(self.style.SUCCESS(f"Company {options['company']} closed."))
            return

        p = account_closure.plan(company)
        self.stdout.write(f"DRY RUN: closing company {p.company_id} would delete:")
        self.stdout.write(json.dumps(p.counts(), indent=1, sort_keys=True))
        existing = account_closure.find_export(company)
        self.stdout.write(f"Export in storage: {existing or 'none yet (run --export first)'}")
