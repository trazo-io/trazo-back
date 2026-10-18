"""`WorksIn.is_setup_operator`: set by both pilot commands, on new and existing accounts.

The pilot checklist told the setup operator "The grower checks them before anything is filed",
and nothing made it true: the operator account is a Company Admin like the grower, so it could
sign the annual update (in the grower's name, from the farm profile) and submit the OSP. The flag
marks the account so the server can refuse those two acts (certifications tests
`test_setup_operator_cannot_attest`).

Until 2026-10-18 the only marker was the "(Trazo setup)" name suffix, which an existing account
attached by `add_pilot_operator --email` or `provision_pilot` does not carry (review of back #176).
"""

import importlib
from io import StringIO

from django.apps import apps
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from company.models import Company, Establishment
from subscriptions.models import Plan, Subscription
from subscriptions.pilot_operator import is_setup_operator, operator_last_name
from users.constants import PRODUCER
from users.models import User, WorksIn

backfill = importlib.import_module("users.migrations.0015_worksin_is_setup_operator")


def _run(name, *args):
    out = StringIO()
    call_command(name, *args, stdout=out, stderr=StringIO())
    return out.getvalue()


@override_settings(BASE_APP_URL="https://app.example.test/")
class AddPilotOperatorSetsTheFlagTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", stdout=StringIO(), stderr=StringIO())
        cls.pilot = Company.objects.create(name="Flag Pilot")
        Subscription.objects.create(company=cls.pilot, plan=Plan.objects.get(slug="pilot"), status="active")
        Establishment.objects.create(name="Flag Farm", company=cls.pilot, country="US", state="WA")

    def _add(self, email, *extra):
        try:
            return _run("add_pilot_operator", "--company-id", str(self.pilot.pk), "--email", email, *extra)
        except CommandError as exc:
            self.fail(f"add_pilot_operator refused: {exc}")

    def test_a_new_operator_account_is_flagged(self):
        output = self._add("oscar+flag@trazo.test", "--commit")
        operator = User.objects.get(email="oscar+flag@trazo.test")
        self.assertTrue(WorksIn.objects.get(user=operator, company=self.pilot).is_setup_operator)
        self.assertIn("PASS  operator is flagged as the setup account (cannot sign or submit)", output)

    def test_an_attached_account_already_a_member_is_flagged_on_a_rerun(self):
        # The account review of back #176 named: attached under its own name, no setup suffix,
        # and a membership from before the flag existed.
        attached = User.objects.create_user(
            email="attached@trazo.test",
            password="x",
            first_name="Oscar",
            last_name="Munoz",
            is_active=True,
            is_verified=True,
            user_type=PRODUCER,
        )
        WorksIn.objects.create(user=attached, company=self.pilot, role=WorksIn.COMPANY_ADMIN)
        self.assertFalse(is_setup_operator(attached))

        self._add("attached@trazo.test", "--commit")

        self.assertTrue(is_setup_operator(attached))
        attached.refresh_from_db()
        self.assertEqual(attached.last_name, "Munoz", "the account's own name is left alone")

    def test_the_dry_run_says_what_the_flag_does_and_writes_nothing(self):
        output = self._add("oscar+dry@trazo.test")
        self.assertIn("cannot sign annual updates or submit the OSP", output)
        self.assertIn("Never run this on the grower's own address.", output)
        self.assertFalse(WorksIn.objects.filter(is_setup_operator=True).exists())


@override_settings(BASE_APP_URL="https://app.example.test/")
class ProvisionPilotSetsTheFlagTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", stdout=StringIO(), stderr=StringIO())

    def _provision(self, operator_email):
        return _run(
            "provision_pilot",
            "--company",
            "Flag Bench Orchard",
            "--email",
            "dan@flagbench.test",
            "--farm",
            "Flag Bench",
            "--state",
            "WA",
            "--operator-email",
            operator_email,
            "--renewal-date",
            "2099-03-01",
            "--commit",
        )

    def test_the_operator_is_flagged_and_the_grower_is_not(self):
        self._provision("oscar+flagbench@trazo.test")
        company = Company.objects.get(name="Flag Bench Orchard")
        operator = User.objects.get(email="oscar+flagbench@trazo.test")
        self.assertTrue(WorksIn.objects.get(user=operator, company=company).is_setup_operator)
        # The grower has an invitation, not a membership, until they accept it; whatever rows
        # exist besides the operator's are never flagged.
        self.assertFalse(
            WorksIn.objects.filter(company=company, is_setup_operator=True).exclude(user=operator).exists()
        )

    def test_an_existing_operator_account_is_flagged_too(self):
        existing = User.objects.create_user(
            email="existing-op@trazo.test",
            password="x",
            first_name="Oscar",
            last_name="Munoz",
            is_active=True,
            is_verified=True,
            user_type=PRODUCER,
        )
        self._provision("existing-op@trazo.test")
        self.assertTrue(is_setup_operator(existing))


class BackfillTests(TestCase):
    """The migration flags only what the suffix proves; the rest is a re-run of the command."""

    def test_only_memberships_of_suffixed_accounts_are_flagged(self):
        company = Company.objects.create(name="Backfill Co")
        operator = User.objects.create_user(
            email="op@trazo.test", password="x", first_name="Oscar", last_name=operator_last_name("Munoz")
        )
        grower = User.objects.create_user(email="grower@farm.test", password="x", first_name="John", last_name="Doe")
        WorksIn.objects.create(user=operator, company=company, role=WorksIn.COMPANY_ADMIN)
        WorksIn.objects.create(user=grower, company=company, role=WorksIn.COMPANY_ADMIN)

        backfill.flag_suffixed_operators(apps, None)

        self.assertTrue(is_setup_operator(operator))
        self.assertFalse(is_setup_operator(grower))
        self.assertEqual(backfill.SETUP_SUFFIX, "(Trazo setup)")
