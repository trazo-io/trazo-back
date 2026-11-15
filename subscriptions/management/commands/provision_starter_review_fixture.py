"""Provision (or remove) the Starter review fixture: one organic demo farm on the free tier.

Run 8b residual F. The external review needs to see the readiness card as a Starter operation sees
it: the Compliance access notice next to three findings ("not on file in Trazo") and the fraud
prevention plan row actions. A reviewer account that signs up through the app stops at company
setup, so readiness has nothing to evaluate. This command builds the smallest state that makes the
card render, and nothing more.

Scope: the readiness card only. It does NOT stand in for a Starter event journey (logging,
templates, voice); that stays open.

What it writes, in one transaction (all marked as test data by name and `is_demo`):

  * Company "ASTRA TEST Starter Review"
  * a Starter subscription, created exactly as `CompanyViewSet.create` creates one (active, no
    period end, no trial end)
  * the reviewer's `WorksIn` row as Company Admin (a direct row: an invitation is a transfer)
  * Establishment "ASTRA TEST Organic Farm": `farming_method="organic"` (so the NOP checks apply),
    `is_demo=True`, US / WA, in the reviewer's farms in charge
  * one `DataOperationLog` row

Side effects of those writes: one `SubscriptionEvent` (MRR 0, from the subscription signal),
deleted with the company on `--remove`, and one auditlog entry for the Establishment, which
auditlog keeps (removal adds a delete entry next to it).

What it never does: parcels, productions, events, certificates, OSPs, plan files, invitations,
review links, publications, documents, the new-company alert email, any other email, or Stripe.

Refusals (nothing is written):
  * the email is not a reviewer alias (`oscar+astra...@trazo.io`)
  * the account does not exist or cannot sign in (same gates as `provision_pilot`)
  * Starter is missing, inactive, or carries `compliance_exports` (the card would not show the
    access notice, so the fixture would prove nothing)
  * the account holds any company other than an untouched copy of this fixture

Re-running on an account that already holds exactly this fixture and nothing else is a no-op that
prints the ids and runs the checks again.

Usage:

    poetry run python manage.py provision_starter_review_fixture --email oscar+astrastarter@trazo.io
    poetry run python manage.py provision_starter_review_fixture --email ... --commit
    poetry run python manage.py provision_starter_review_fixture --email ... --remove
    poetry run python manage.py provision_starter_review_fixture --email ... --remove --commit

`--remove` finds the company by its marker name among the account's memberships and deletes it
(cascade) only while it is still exactly what this command wrote.
"""

import hashlib
import json
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

COMPANY_NAME = "ASTRA TEST Starter Review"
FARM_NAME = "ASTRA TEST Organic Farm"
FARM_STATE = "WA"
FARM_COUNTRY = "US"
EMAIL_PATTERN = re.compile(r"^oscar\+astra[a-z0-9]*@trazo\.io$")
EXPECTED_BLOCKERS = frozenset({"ofpp.missing", "osp.none", "records.none"})
OPERATION = "provision_starter_review_fixture"
REMOVE_OPERATION = "remove_starter_review_fixture"


class Command(BaseCommand):
    help = "Provision or remove the Starter readiness review fixture (dry run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="The reviewer's existing account (oscar+astra...@trazo.io)")
        parser.add_argument("--remove", action="store_true", help="Remove the fixture instead of creating it.")
        parser.add_argument("--commit", action="store_true", help="Actually write. Without it nothing is saved.")
        parser.add_argument("--run-by", default="", help="Who ran it (stored on the DataOperationLog row).")

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        from users.models import User

        email = (options["email"] or "").strip().lower()
        if not EMAIL_PATTERN.match(email):
            raise CommandError(
                f"{email!r} is not a review account. This command only touches oscar+astra...@trazo.io "
                "aliases, so it cannot be pointed at a grower."
            )
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f"No account for {email}. Sign up through the app first, then re-run.")

        if options["remove"]:
            return self._remove(user, options)
        return self._provision(user, options)

    # ------------------------------------------------------------------
    # Provision
    # ------------------------------------------------------------------

    def _provision(self, user, options):
        from subscriptions.management.commands.provision_pilot import Command as PilotCommand

        problems = PilotCommand._login_gate_problems(user)
        if problems:
            raise CommandError(
                f"{user.email} cannot sign in to the app: " + "; ".join(problems) + ". Sort the account out first."
            )
        starter = self._starter_plan()

        existing = self._existing_fixture(user)
        if existing is not None:
            company, farm = existing
            self.stdout.write(self.style.SUCCESS("Fixture already in place; nothing written."))
            self._print_ids(company, farm)
            self._verify(user, company, farm)
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Starter review fixture"))
        self.stdout.write(f"  Account     : {user.email}")
        self.stdout.write(f"  Company     : {COMPANY_NAME}")
        self.stdout.write(f"  Plan        : {starter.slug} (active, no period end, no trial)")
        self.stdout.write("  Membership  : Company Admin")
        self.stdout.write(f"  Farm        : {FARM_NAME} (organic, demo, {FARM_STATE}, {FARM_COUNTRY})")
        self.stdout.write("  Not created : parcels, records, certificates, OSP, plan file, invitations, review links")

        if not options["commit"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY RUN: nothing written. Re-run with --commit."))
            return

        company, farm = self._create(user, starter, options["run_by"])
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Fixture provisioned."))
        self._print_ids(company, farm)
        self._verify(user, company, farm)

    def _create(self, user, starter, run_by):
        from common.models import DataOperationLog
        from company.models import Company, Establishment
        from subscriptions.models import Subscription
        from users.models import User, WorksIn

        with transaction.atomic():
            # Lock the account so two concurrent runs cannot both see "no company" and provision
            # twice; re-read the state under the lock.
            locked = User.objects.select_for_update().get(pk=user.pk)
            if locked.companies.exists():
                raise CommandError(f"{locked.email} gained a company while this ran. Nothing written; re-run.")

            company = Company.objects.create(name=COMPANY_NAME)
            # Same row CompanyViewSet.create writes for a new company: Starter is free forever,
            # never a trial, and has no period end.
            subscription = Subscription.objects.create(
                company=company,
                plan=starter,
                status="active",
                current_period_start=timezone.now(),
                current_period_end=None,
                trial_end=None,
            )
            membership = WorksIn.objects.create(user=locked, company=company, role=WorksIn.COMPANY_ADMIN)
            farm = Establishment.objects.create(
                name=FARM_NAME,
                company=company,
                farming_method="organic",
                is_demo=True,
                country=FARM_COUNTRY,
                state=FARM_STATE,
            )
            membership.establishments_in_charge.add(farm)

            record = {
                "user": locked.pk,
                "company": company.pk,
                "subscription": subscription.pk,
                "works_in": membership.pk,
                "establishment": farm.pk,
            }
            DataOperationLog.objects.create(
                operation=OPERATION,
                action=DataOperationLog.ACTION_APPLY,
                report_sha256=self._sha(record),
                counts={"company": 1, "subscription": 1, "works_in": 1, "establishment": 1, "ids": record},
                run_by=run_by,
            )
        return company, farm

    def _starter_plan(self):
        from subscriptions.models import Plan

        starter = Plan.objects.filter(slug="starter").first()
        if starter is None:
            raise CommandError("No `starter` plan exists. Run `manage.py create_plans` first.")
        if not starter.is_active:
            raise CommandError("The `starter` plan is inactive; new companies would get no subscription.")
        if (starter.features or {}).get("compliance_exports"):
            raise CommandError(
                "The `starter` plan carries compliance_exports, so the readiness card would not show the "
                "Compliance access notice. Fix the plan (create_plans) before provisioning the fixture."
            )
        return starter

    def _existing_fixture(self, user):
        """(company, farm) when the account holds exactly an untouched fixture; None when it holds nothing.

        Anything else refuses: the command must never add a second company to an account that has
        real data, or treat someone's own company as the fixture.
        """
        companies = list(user.companies.all())
        if not companies:
            return None
        if len(companies) == 1 and companies[0].name == COMPANY_NAME:
            company = companies[0]
            problems = self._fixture_problems(user, company)
            if not problems:
                return company, company.establishment_set.get()
            raise CommandError(
                f"{user.email} already holds '{COMPANY_NAME}' but it is no longer the untouched fixture: "
                + "; ".join(problems)
                + ". Nothing written."
            )
        names = ", ".join(sorted(c.name for c in companies))
        raise CommandError(
            f"{user.email} already belongs to other company data ({names}). The fixture needs an account with "
            "no company. Nothing written."
        )

    # ------------------------------------------------------------------
    # Remove
    # ------------------------------------------------------------------

    def _remove(self, user, options):
        from common.models import DataOperationLog

        companies = list(user.companies.filter(name=COMPANY_NAME))
        if not companies:
            self.stdout.write(f"No '{COMPANY_NAME}' company on {user.email}. Nothing to remove.")
            return
        if len(companies) > 1:
            raise CommandError(
                f"{user.email} belongs to {len(companies)} companies named '{COMPANY_NAME}'. Remove them by hand."
            )
        company = companies[0]
        problems = self._fixture_problems(user, company)
        if problems:
            raise CommandError(
                f"'{COMPANY_NAME}' (id {company.pk}) holds more than the fixture: "
                + "; ".join(problems)
                + ". Nothing removed."
            )

        self.stdout.write(f"Would remove company {company.pk} '{company.name}' and everything it cascades to.")
        if not options["commit"]:
            self.stdout.write(self.style.WARNING("DRY RUN: nothing removed. Re-run with --commit."))
            return

        with transaction.atomic():
            record = {"user": user.pk, "company": company.pk}
            _, deleted = company.delete()
            DataOperationLog.objects.create(
                operation=REMOVE_OPERATION,
                action=DataOperationLog.ACTION_APPLY,
                report_sha256=self._sha(record),
                counts={"deleted": deleted, "ids": record},
                run_by=options["run_by"],
            )
        self.stdout.write(self.style.SUCCESS(f"Removed company {record['company']}."))

    def _fixture_problems(self, user, company):
        """Why `company` is not exactly what this command wrote. Empty means it is."""
        from certifications.models import Certification, CertifierAccessLink, OrganicSystemPlan
        from company.models import Establishment
        from documents.models import GeneratedDocument
        from history.models import Production
        from product.models import Parcel
        from users.models import WorksIn
        from users.models_invitation import CompanyInvitation

        problems = []
        if WorksIn.objects.filter(company=company).exclude(user=user).exists():
            problems.append("it has another member")
        if CompanyInvitation.objects.filter(company=company).exists():
            problems.append("it has an invitation")

        farms = Establishment.objects.filter(company=company)
        if farms.filter(is_demo=False).exists():
            problems.append("it has a non-demo farm")
        if farms.count() != 1:
            problems.append(f"it has {farms.count()} farms, not 1")
        # `fraud_prevention_plan_uploaded` is what readiness and `ofpp_on_file` read, and it can be
        # set without a file, so both are checked (review of back #158).
        if (
            farms.filter(fraud_prevention_plan_uploaded=True).exists()
            or farms.exclude(fraud_prevention_plan_document="").exclude(fraud_prevention_plan_document=None).exists()
        ):
            problems.append("a fraud prevention plan was recorded")

        checks = (
            ("parcel", Parcel.objects.filter(establishment__company=company)),
            ("record", Production.objects.filter(parcel__establishment__company=company)),
            ("certificate", Certification.objects.filter(establishment__company=company)),
            ("organic system plan", OrganicSystemPlan.objects.filter(establishment__company=company)),
            ("document", GeneratedDocument.objects.filter(establishment__company=company)),
            ("review link", CertifierAccessLink.objects.filter(establishment__company=company)),
        )
        for label, queryset in checks:
            if queryset.exists():
                problems.append(f"it has a {label}")

        subscription = getattr(company, "subscription", None)
        if subscription is None or subscription.plan.slug != "starter":
            problems.append("its subscription is not Starter")
        return problems

    # ------------------------------------------------------------------

    @staticmethod
    def _sha(record):
        return hashlib.sha256(json.dumps(record, sort_keys=True).encode("utf-8")).hexdigest()

    def _print_ids(self, company, farm):
        self.stdout.write(f"  company id  : {company.pk}")
        self.stdout.write(f"  farm id     : {farm.pk}")

    def _verify(self, user, company, farm):
        """PASS/FAIL for each fact the readiness review depends on."""
        from history.services.operation_readiness_service import OperationReadinessService

        company.refresh_from_db()
        user.refresh_from_db()
        plan = company.subscription_plan
        readiness = OperationReadinessService(farm).evaluate()
        blocker_codes = {b.get("code") for b in readiness["blockers"]}
        checks = [
            ("plan is starter", plan is not None and plan.slug == "starter"),
            (
                "plan has no compliance_exports",
                plan is not None and not (plan.features or {}).get("compliance_exports"),
            ),
            ("active company is the fixture", getattr(user.get_active_company(), "pk", None) == company.pk),
            ("readiness applies (organic)", readiness["applicable"] is True),
            (
                "readiness blockers are exactly " + ", ".join(sorted(EXPECTED_BLOCKERS)),
                blocker_codes == EXPECTED_BLOCKERS,
            ),
        ]
        self.stdout.write("")
        self.stdout.write("  Post-provision checks:")
        for name, ok in checks:
            self.stdout.write(f"    {'PASS' if ok else 'FAIL'}  {name}")
        failed = [name for name, ok in checks if not ok]
        if failed:
            self.stdout.write(f"    blockers seen: {sorted(c for c in blocker_codes if c)}")
            raise CommandError("The fixture does not show the intended readiness state: " + ", ".join(failed))
