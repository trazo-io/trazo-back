"""`add_pilot_operator` and `remove_pilot_operator`: one company per account, on a live pilot.

From 2026-10-01 to 2026-10-17 `provision_pilot` added the operator's main account to every pilot
as a second company. The app loads only `user.companies[0]` and has no switcher, so a production
rehearsal found the operator could not open the pilot at all. These two commands repair a pilot
provisioned that way without re-provisioning it: add a dedicated operator account, then take the
stale membership off.

A refusal or an unknown command surfaces as CommandError, so the tests that expect success turn
any CommandError into an assertion failure, and the refusal tests check the message as well as the
exception type.
"""

from io import StringIO
from urllib.parse import parse_qs, urlparse

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from common.models import DataOperationLog
from company.models import Company, Establishment
from history.models import GeneralEvent, History
from product.models import Parcel
from subscriptions.models import Plan, Subscription
from users.constants import PRODUCER
from users.models import PasswordResetToken, WorksIn

User = get_user_model()

MAIN = "oscar@trazo.test"
DEDICATED = "oscar+astraop@trazo.test"


def _run(name, *args):
    out = StringIO()
    call_command(name, *args, stdout=out, stderr=StringIO())
    return out.getvalue()


class _PilotFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", stdout=StringIO(), stderr=StringIO())
        cls.pilot = Company.objects.create(name="ASTRA Test Pilot (not a farm)")
        Subscription.objects.create(company=cls.pilot, plan=Plan.objects.get(slug="pilot"), status="active")
        cls.farm = Establishment.objects.create(name="Pilot Farm", company=cls.pilot, country="US", state="WA")

        # The production state: the operator's main account owns its own company and was also
        # added to the pilot by the 2026-10-01 provision_pilot.
        cls.main = User.objects.create_user(
            email=MAIN, password="x", is_active=True, is_verified=True, user_type=PRODUCER
        )
        cls.own = Company.objects.create(name="Trazo Demo Orchard")
        WorksIn.objects.create(user=cls.main, company=cls.own, role=WorksIn.COMPANY_ADMIN)
        WorksIn.objects.create(user=cls.main, company=cls.pilot, role=WorksIn.COMPANY_ADMIN)
        # The grower, who accepted the invitation, so the pilot has a member besides the operator.
        cls.grower = User.objects.create_user(
            email="grower@pilot.test", password="x", is_active=True, is_verified=True, user_type=PRODUCER
        )
        WorksIn.objects.create(user=cls.grower, company=cls.pilot, role=WorksIn.COMPANY_ADMIN)

    def _ok(self, name, *args):
        try:
            return _run(name, *args)
        except CommandError as exc:
            self.fail(f"{name} refused: {exc}")


class AddPilotOperatorTests(_PilotFixture):
    def _add(self, *extra, email=DEDICATED, company=None):
        return self._ok("add_pilot_operator", "--company-id", str((company or self.pilot).pk), "--email", email, *extra)

    def test_dry_run_writes_nothing(self):
        output = self._add()

        self.assertIn("DRY RUN", output)
        self.assertFalse(User.objects.filter(email=DEDICATED).exists())
        self.assertFalse(DataOperationLog.objects.filter(operation="add_pilot_operator").exists())

    @override_settings(BASE_APP_URL="https://app.example.test/", SIGNUP_ALERT_EMAILS=["owner@example.test"])
    def test_commit_creates_the_operator_with_a_setup_link_and_one_membership(self):
        with self.captureOnCommitCallbacks(execute=True):
            output = self._add("--commit", "--run-by", "test")

        operator = User.objects.get(email=DEDICATED)
        self.assertEqual(operator.get_full_name(), "Oscar Munoz (Trazo setup)")
        self.assertFalse(operator.has_usable_password())
        self.assertEqual(list(operator.companies.all()), [self.pilot])
        membership = WorksIn.objects.get(user=operator)
        self.assertEqual(membership.role, WorksIn.COMPANY_ADMIN)
        self.assertEqual(list(membership.establishments_in_charge.all()), [self.farm])
        self.assertEqual(operator.get_active_company(), self.pilot)

        line = next(line for line in output.splitlines() if "OPERATOR SETUP LINK:" in line)
        link = line.split("OPERATOR SETUP LINK:", 1)[1].strip()
        self.assertTrue(link.startswith("https://app.example.test/auth/reset-password?"), link)
        token = parse_qs(urlparse(link).query)["token"][0]
        self.assertTrue(PasswordResetToken.objects.get(user=operator, token=token).is_valid())
        self.assertEqual(mail.outbox, [])

        log = DataOperationLog.objects.get(operation="add_pilot_operator")
        self.assertEqual(log.counts["ids"]["user"], operator.pk)
        self.assertEqual(log.counts["account_created"], 1)
        self.assertNotIn(token, str(log.counts), "the setup token must never be stored in the log")
        self.assertIn("PASS  operator belongs to exactly one company (this one)", output)

        # The main account is untouched: removing it is a separate, checked step.
        self.assertEqual(set(self.main.companies.all()), {self.own, self.pilot})

    def test_an_operator_with_another_company_is_refused(self):
        other_pilot = Company.objects.create(name="Second Pilot")
        Subscription.objects.create(company=other_pilot, plan=Plan.objects.get(slug="pilot"), status="active")
        with self.assertRaises(CommandError) as ctx:
            _run("add_pilot_operator", "--company-id", str(other_pilot.pk), "--email", MAIN, "--commit")

        self.assertIn("no company switcher", str(ctx.exception))
        self.assertIn("oscar+secondpilot@trazo.io", str(ctx.exception))
        self.assertFalse(WorksIn.objects.filter(user=self.main, company=other_pilot).exists())

    def test_an_existing_member_with_another_role_is_promoted(self):
        operator = User.objects.create_user(
            email=DEDICATED, password="x", is_active=True, is_verified=True, user_type=PRODUCER
        )
        WorksIn.objects.create(user=operator, company=self.pilot, role=WorksIn.VIEWER)

        output = self._add("--commit")

        self.assertIn("promoted to Company Admin", output)
        self.assertEqual(WorksIn.objects.get(user=operator, company=self.pilot).role, WorksIn.COMPANY_ADMIN)

    def test_a_company_that_is_not_a_pilot_is_refused(self):
        with self.assertRaises(CommandError) as ctx:
            _run("add_pilot_operator", "--company-id", str(self.own.pk), "--email", DEDICATED, "--commit")

        self.assertIn("only adds operators to pilots", str(ctx.exception))
        self.assertFalse(User.objects.filter(email=DEDICATED).exists())


class RemovePilotOperatorTests(_PilotFixture):
    def _remove(self, *extra, email=MAIN, company=None):
        return _run("remove_pilot_operator", "--company-id", str((company or self.pilot).pk), "--email", email, *extra)

    def test_dry_run_removes_nothing(self):
        try:
            output = self._remove()
        except CommandError as exc:
            self.fail(f"remove_pilot_operator refused: {exc}")

        self.assertIn("DRY RUN", output)
        self.assertTrue(WorksIn.objects.filter(user=self.main, company=self.pilot).exists())

    def test_commit_deletes_only_that_membership(self):
        membership = WorksIn.objects.get(user=self.main, company=self.pilot)
        try:
            self._remove("--commit", "--run-by", "test")
        except CommandError as exc:
            self.fail(f"remove_pilot_operator refused: {exc}")

        self.assertEqual(list(self.main.companies.all()), [self.own])
        self.assertTrue(Company.objects.filter(pk=self.pilot.pk).exists())
        self.assertTrue(Establishment.objects.filter(pk=self.farm.pk).exists())
        log = DataOperationLog.objects.get(operation="remove_pilot_operator")
        self.assertEqual(log.counts["ids"]["works_in"], membership.pk)
        self.assertEqual(log.run_by, "test")

    def test_a_company_that_is_not_a_pilot_is_refused(self):
        WorksIn.objects.create(user=self.main, company=Company.objects.create(name="Third"), role="CA")

        with self.assertRaises(CommandError) as ctx:
            self._remove("--commit", company=self.own)

        self.assertIn("only removes memberships from pilots", str(ctx.exception))
        self.assertTrue(WorksIn.objects.filter(user=self.main, company=self.own).exists())

    def test_it_never_leaves_an_account_with_no_company(self):
        WorksIn.objects.filter(user=self.main, company=self.own).delete()

        with self.assertRaises(CommandError) as ctx:
            self._remove("--commit")

        self.assertIn("leave the account with no company", str(ctx.exception))
        self.assertEqual(list(self.main.companies.all()), [self.pilot])

    def test_it_never_leaves_the_pilot_with_no_member(self):
        WorksIn.objects.filter(user=self.grower, company=self.pilot).delete()

        with self.assertRaises(CommandError) as ctx:
            self._remove("--commit")

        self.assertIn("only member", str(ctx.exception))
        self.assertTrue(WorksIn.objects.filter(user=self.main, company=self.pilot).exists())

    def test_an_account_that_authored_records_keeps_its_membership(self):
        parcel = Parcel.objects.create(name="Block A", area=1, establishment=self.farm)
        history = History.objects.create(parcel=parcel, name="2026 season")
        GeneralEvent.objects.create(
            history=history, name="x", description="x", date="2026-10-01T00:00Z", created_by=self.main
        )

        with self.assertRaises(CommandError) as ctx:
            self._remove("--commit")

        message = str(ctx.exception)
        self.assertIn("authored records", message)
        self.assertIn("history.GeneralEvent.created_by: 1", message)
        self.assertTrue(WorksIn.objects.filter(user=self.main, company=self.pilot).exists())

    def test_records_in_another_company_do_not_block(self):
        from subscriptions import pilot_operator

        parcel = Parcel.objects.create(
            name="Own block", area=1, establishment=Establishment.objects.create(name="Own", company=self.own)
        )
        history = History.objects.create(parcel=parcel, name="Own season", operator=self.main)
        GeneralEvent.objects.create(
            history=history, name="x", description="x", date="2026-10-01T00:00Z", created_by=self.main
        )

        self.assertEqual(pilot_operator.authored_records(self.main, self.pilot), {})
        self.assertEqual(
            pilot_operator.authored_records(self.main, self.own),
            {"history.GeneralEvent.created_by": 1, "history.History.operator": 1},
        )


class AuthorshipClassificationTests(TestCase):
    """Every link to User is classified, so a new author column cannot go uncounted.

    `authored_records` counts every User link on a model that reaches a company, minus
    NOT_AUTHORSHIP. A link on a model with no company path is skipped, which is only right for
    rows that do not belong to a company. That list is pinned here: a new model with an author
    column and no company path fails this test until someone decides.
    """

    NO_COMPANY_SCOPE = {
        ("admin.LogEntry", "user"),
        ("token_blacklist.OutstandingToken", "user"),
        ("users.VerificationCode", "user"),
        ("users.PasswordResetToken", "user"),
        ("users.EmailChangeRequest", "user"),
        ("support.SupportMessage", "author"),
        ("support.SupportAttachment", "uploaded_by"),
        ("education.UserEducationProgress", "user"),
        ("education.EducationCertificate", "user"),
        ("education.EducationBookmark", "user"),
        ("notifications.Notification", "recipient"),
        ("notifications.Notification", "actor"),
        ("notifications.NotificationPreference", "user"),
        ("notifications.NotificationChannel", "user"),
        ("certifications.OMRIProduct", "added_by"),
        ("certifications.WSDAMaterial", "added_by"),
        ("account.EmailAddress", "user"),
        ("socialaccount.SocialAccount", "user"),
        # Counted separately, scoped to the company's objects.
        ("auditlog.LogEntry", "actor"),
    }

    def test_every_user_link_is_counted_or_classified(self):
        from subscriptions import pilot_operator

        unclassified = []
        for model in apps.get_models():
            if model._meta.abstract or model._meta.proxy:
                continue
            for field in model._meta.get_fields():
                if not (getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False)):
                    continue
                if not field.concrete or getattr(field, "related_model", None) is not User:
                    continue
                key = (model._meta.label, field.name)
                if pilot_operator.company_paths(model) or key in self.NO_COMPANY_SCOPE:
                    continue
                unclassified.append(key)
        self.assertEqual(unclassified, [], "classify these in NO_COMPANY_SCOPE or give them a company path")

    def test_the_records_a_pilot_operator_writes_are_counted(self):
        from subscriptions import pilot_operator

        for label in (
            "history.GeneralEvent",
            "history.History",
            "certifications.OrganicSystemPlan",
            "certifications.OSPAnnualUpdate",
            "documents.GeneratedDocument",
            "fieldnotes.FieldNote",
            "certifications.CertifierAccessLink",
            "carbon.CarbonAuditLog",
        ):
            with self.subTest(label):
                self.assertTrue(pilot_operator.company_paths(apps.get_model(label)), label)
