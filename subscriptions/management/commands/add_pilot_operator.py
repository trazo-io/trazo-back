"""Give an already provisioned pilot its own operator account, without re-provisioning it.

`provision_pilot` creates the operator account when a pilot is provisioned. A pilot provisioned
before 2026-10-17 had the operator's main account (oscar@trazo.io) added as a second membership,
which the app cannot open: it loads only an account's first company and has no switcher (see
`subscriptions/pilot_operator.py`). This command adds a dedicated operator account to that pilot,
and `remove_pilot_operator` takes the stale membership off.

What it writes (one transaction, on --commit only):

  * the operator account, if `--email` has none: "<first> <last> (Trazo setup)", producer, no
    usable password, no mail sent
  * a Company Admin `WorksIn` row in the pilot, with every farm of the pilot in its charge
  * a setup link token (`/auth/reset-password`), printed once, never emailed
  * one `DataOperationLog` row (ids only, never the token)

Refusals (nothing is written):

  * the company does not exist, or is not on the `pilot` plan
  * the account belongs to any other company (one company per account)
  * the account exists but cannot be an operator (consumer, deactivated or unverified with a
    password of its own)

Re-running on an account that is already this pilot's operator renews its setup link if it has
never set a password, and otherwise only runs the checks again.

Usage:

    poetry run python manage.py add_pilot_operator --company-id 17 --email oscar+sierranut@trazo.io
    poetry run python manage.py add_pilot_operator --company-id 17 --email ... --commit
"""

import hashlib
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from subscriptions import pilot_operator

DEFAULT_LINK_DAYS = 30
OPERATION = "add_pilot_operator"


class Command(BaseCommand):
    help = "Add a dedicated operator account to a provisioned pilot and print its setup link (dry run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--company-id", type=int, required=True, help="The pilot company's id.")
        parser.add_argument(
            "--email", required=True, help="The operator account for this pilot only (e.g. oscar+<farm>@trazo.io)."
        )
        parser.add_argument(
            "--first-name",
            default=pilot_operator.DEFAULT_FIRST_NAME,
            help=f"First name for a NEW account (default {pilot_operator.DEFAULT_FIRST_NAME}).",
        )
        parser.add_argument(
            "--last-name",
            default=pilot_operator.DEFAULT_LAST_NAME,
            help=(
                f"Last name for a NEW account (default {pilot_operator.DEFAULT_LAST_NAME}); "
                f"'{pilot_operator.SETUP_SUFFIX}' is appended."
            ),
        )
        parser.add_argument(
            "--link-days",
            type=int,
            default=DEFAULT_LINK_DAYS,
            help=f"Days the setup link stays valid (default {DEFAULT_LINK_DAYS}).",
        )
        parser.add_argument("--commit", action="store_true", help="Actually write. Without it nothing is saved.")
        parser.add_argument("--run-by", default="", help="Who ran it (stored on the DataOperationLog row).")

    def handle(self, *args, **options):
        from company.models import Company
        from users.models import User

        if options["link_days"] < 1:
            raise CommandError("--link-days must be at least 1.")
        email = (options["email"] or "").strip().lower()
        company = Company.objects.filter(pk=options["company_id"]).first()
        if company is None:
            raise CommandError(f"No company with id {options['company_id']}. Nothing written.")
        problem = pilot_operator.pilot_subscription_problem(company)
        if problem:
            raise CommandError(f"{problem}. This command only adds operators to pilots. Nothing written.")

        operator = User.objects.filter(email__iexact=email).first()
        if operator is not None:
            problems = pilot_operator.existing_operator_problems(operator)
            if problems:
                raise CommandError(
                    f"{email} has an account that cannot be the operator: "
                    + "; ".join(problems)
                    + f". Use a dedicated address such as {pilot_operator.suggested_email(company.name)}."
                )
            pilot_operator.refuse_other_companies(operator, company, company.name, role="--email")
        needs_link = operator is None or pilot_operator.needs_setup_link(operator)
        already_member = operator is not None and operator.companies.filter(pk=company.pk).exists()
        name = f"{options['first_name'].strip()} {pilot_operator.operator_last_name(options['last_name'])}".strip()

        self.stdout.write(self.style.MIGRATE_HEADING(f"Pilot operator for {company.name} (id {company.pk})"))
        if operator is None:
            self.stdout.write(f"  Account     : {email}  [NEW, '{name}', producer, no password until the setup link]")
        else:
            self.stdout.write(f"  Account     : {email}  [existing, belongs to no other company]")
        self.stdout.write(
            "  Membership  : " + ("already Company Admin here" if already_member else "Company Admin (new row)")
        )
        self.stdout.write(
            "  Setup link  : " + (f"yes, valid {options['link_days']} days" if needs_link else "no (has a password)")
        )

        if not options["commit"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY RUN: nothing written. Re-run with --commit."))
            return

        operator, setup_token, setup_link = self._apply(company, operator, email, needs_link, options)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{operator.email} is the operator of {company.name}."))
        if setup_link is not None:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(f"  OPERATOR SETUP LINK: {setup_link}"))
            self.stdout.write(
                f"  Valid until {setup_token.expires_at:%d %b %Y}. Open it yourself: it sets the password for "
                f"{operator.email}. Nothing was emailed."
            )
        pilot_operator.print_checks(
            self.stdout,
            pilot_operator.operator_checks(operator, company, setup_token),
            "The operator was added but cannot work in the pilot",
        )

    def _apply(self, company, operator, email, needs_link, options):
        from common.models import DataOperationLog
        from users.models import User, WorksIn

        setup_token = setup_link = None
        with transaction.atomic():
            created = operator is None
            if created:
                operator = pilot_operator.create_operator_account(email, options["first_name"], options["last_name"])
            else:
                operator = User.objects.select_for_update().get(pk=operator.pk)
                pilot_operator.refuse_other_companies(operator, company, company.name, role="--email")

            membership, _ = WorksIn.objects.get_or_create(
                user=operator, company=company, defaults={"role": WorksIn.COMPANY_ADMIN}
            )
            membership.establishments_in_charge.add(*company.establishment_set.all())
            if needs_link:
                setup_token, setup_link = pilot_operator.issue_setup_link(operator, options["link_days"])

            record = {"user": operator.pk, "company": company.pk, "works_in": membership.pk}
            DataOperationLog.objects.create(
                operation=OPERATION,
                action=DataOperationLog.ACTION_APPLY,
                report_sha256=hashlib.sha256(json.dumps(record, sort_keys=True).encode("utf-8")).hexdigest(),
                counts={
                    "account_created": int(created),
                    "setup_link_issued": int(setup_token is not None),
                    "ids": record,
                },
                run_by=options["run_by"],
            )
        return operator, setup_token, setup_link
