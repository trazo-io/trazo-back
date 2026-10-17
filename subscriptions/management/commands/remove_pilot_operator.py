"""Take a stale operator membership off a pilot: delete one `WorksIn` row, nothing else.

From 2026-10-01 to 2026-10-17 `provision_pilot` added the operator's main account
(oscar@trazo.io) to every pilot as a second company. The app opens only an account's first company
and has no switcher (see `subscriptions/pilot_operator.py`), so that membership is a door that
cannot be opened, and it also puts a second company on the operator's own account. This command
removes it; `add_pilot_operator` gives the pilot a dedicated operator account instead.

Refusals (nothing is deleted):

  * the company does not exist, or is not on the `pilot` plan
  * the account is not a member of that company
  * the account has no OTHER company: removing the row would leave an account with no company
  * the account authored anything in that company: records (`created_by` and every other author
    column on a model that belongs to the company) or audit-log entries on the company's objects.
    The counts are listed. Those rows name the account as their author, and removing the
    membership would leave that author unable to open the records it wrote.

What it writes on --commit: the deletion of that one `WorksIn` row and one `DataOperationLog` row.

Usage:

    poetry run python manage.py remove_pilot_operator --company-id 17 --email oscar@trazo.io
    poetry run python manage.py remove_pilot_operator --company-id 17 --email oscar@trazo.io --commit
"""

import hashlib
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from subscriptions import pilot_operator

OPERATION = "remove_pilot_operator"


class Command(BaseCommand):
    help = "Remove one account's membership of a pilot company (dry run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--company-id", type=int, required=True, help="The pilot company's id.")
        parser.add_argument("--email", required=True, help="The account whose membership is removed.")
        parser.add_argument("--commit", action="store_true", help="Actually delete. Without it nothing changes.")
        parser.add_argument("--run-by", default="", help="Who ran it (stored on the DataOperationLog row).")

    def handle(self, *args, **options):
        from common.models import DataOperationLog
        from company.models import Company
        from users.models import User, WorksIn

        email = (options["email"] or "").strip().lower()
        company = Company.objects.filter(pk=options["company_id"]).first()
        if company is None:
            raise CommandError(f"No company with id {options['company_id']}. Nothing removed.")
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f"No account for {email}. Nothing removed.")

        membership = self._check(company, user)
        others = pilot_operator.other_companies(user, company)

        self.stdout.write(self.style.MIGRATE_HEADING(f"Remove {user.email} from {company.name} (id {company.pk})"))
        self.stdout.write(f"  WorksIn row : id {membership.pk}, role {membership.get_role_display()}")
        self.stdout.write("  Authored    : nothing in this company")
        self.stdout.write("  Keeps       : " + ", ".join(f"{c.name} (id {c.pk})" for c in others))

        if not options["commit"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY RUN: nothing removed. Re-run with --commit."))
            return

        with transaction.atomic():
            # Lock the account and re-check: a record written while this ran must still refuse.
            user = User.objects.select_for_update().get(pk=user.pk)
            membership = self._check(company, user)
            record = {"user": user.pk, "company": company.pk, "works_in": membership.pk, "role": membership.role}
            WorksIn.objects.filter(pk=membership.pk).delete()
            DataOperationLog.objects.create(
                operation=OPERATION,
                action=DataOperationLog.ACTION_APPLY,
                report_sha256=hashlib.sha256(json.dumps(record, sort_keys=True).encode("utf-8")).hexdigest(),
                counts={"works_in": 1, "ids": record},
                run_by=options["run_by"],
            )

        active = user.get_active_company()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Removed {user.email} from {company.name}."))
        self.stdout.write(
            f"  {user.email} now opens: " + (f"{active.name} (id {active.pk})" if active else "no company")
        )

    def _check(self, company, user):
        """The membership to delete, or CommandError naming why it must stay."""
        from users.models import WorksIn

        problem = pilot_operator.pilot_subscription_problem(company)
        if problem:
            raise CommandError(f"{problem}. This command only removes memberships from pilots. Nothing removed.")
        membership = WorksIn.objects.filter(user=user, company=company).first()
        if membership is None:
            raise CommandError(f"{user.email} is not a member of {company.name} (id {company.pk}). Nothing removed.")
        if not pilot_operator.other_companies(user, company):
            raise CommandError(
                f"{company.name} is the only company {user.email} belongs to. Removing it would leave the "
                "account with no company. Nothing removed."
            )
        authored = pilot_operator.authored_records(user, company)
        if authored:
            listed = ", ".join(f"{label}: {count}" for label, count in sorted(authored.items()))
            raise CommandError(
                f"{user.email} authored records in {company.name} ({listed}). They name this account as their "
                "author, so its membership stays. Nothing removed."
            )
        return membership
