"""`provision_starter_review_fixture` builds the readiness-card review state and nothing else.

Run 8b residual F: the reviewer's Starter account stopped at company setup, so the readiness card
had nothing to evaluate. The command writes one company, its Starter subscription, the reviewer's
membership and one organic demo farm, so the card shows the Compliance access notice and exactly
three findings. These tests pin that it writes those rows and no others (no email, no Stripe, no
records), refuses every account it should not touch, and removes only an untouched fixture.

The fixture covers the readiness card only, not a Starter event journey.
"""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from auditlog.models import LogEntry

from certifications.models import Certification, CertifierAccessLink, OrganicSystemPlan
from common.models import DataOperationLog
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from history.models import History
from history.services.operation_readiness_service import OperationReadinessService
from notifications.models import Notification
from product.models import Parcel
from subscriptions.management.commands import provision_starter_review_fixture as fixture_cmd
from subscriptions.models import Plan, Subscription, SubscriptionEvent
from users.constants import CONSUMER, PRODUCER
from users.models import User, WorksIn
from users.models_invitation import CompanyInvitation

EMAIL = "oscar+astrastarter@trazo.io"
COMMAND = "provision_starter_review_fixture"

COUNTED_MODELS = (
    Company,
    Subscription,
    SubscriptionEvent,
    WorksIn,
    Establishment,
    DataOperationLog,
    Parcel,
    History,
    Certification,
    OrganicSystemPlan,
    GeneratedDocument,
    CertifierAccessLink,
    Notification,
    CompanyInvitation,
)


def _counts():
    return {model.__name__: model.objects.count() for model in COUNTED_MODELS}


@override_settings(SIGNUP_ALERT_EMAILS=["x@y.test"])
class StarterReviewFixtureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", stdout=StringIO(), stderr=StringIO())
        cls.user = User.objects.create_user(
            email=EMAIL, password="x", is_active=True, is_verified=True, user_type=PRODUCER
        )

    def _run(self, *extra, email=EMAIL):
        out = StringIO()
        call_command(COMMAND, "--email", email, *extra, stdout=out, stderr=StringIO())
        return out.getvalue()

    def _fixture(self):
        return Company.objects.get(name=fixture_cmd.COMPANY_NAME, company_workers__user=self.user)

    # -- what it writes -------------------------------------------------

    def test_dry_run_writes_nothing(self):
        before = _counts()

        output = self._run()

        self.assertEqual(_counts(), before)
        self.assertIn("DRY RUN", output)

    def test_commit_writes_exactly_the_fixture_rows(self):
        before = _counts()
        stripe_calls = [
            mock.patch("stripe.Customer.create"),
            mock.patch("stripe.Subscription.create"),
            mock.patch("stripe.Product.create"),
            mock.patch("stripe.Price.create"),
        ]
        mocks = [p.start() for p in stripe_calls]
        self.addCleanup(lambda: [p.stop() for p in stripe_calls])

        # Execute on_commit callbacks: alert_new_company sends from one, so without this the empty
        # outbox below would prove nothing.
        with self.captureOnCommitCallbacks(execute=True):
            output = self._run("--commit")

        after = _counts()
        delta = {name: after[name] - before[name] for name in after if after[name] != before[name]}
        self.assertEqual(
            delta,
            {
                "Company": 1,
                "Subscription": 1,
                "SubscriptionEvent": 1,
                "WorksIn": 1,
                "Establishment": 1,
                "DataOperationLog": 1,
            },
        )
        for stripe_mock in mocks:
            stripe_mock.assert_not_called()
        # Not vacuous: SIGNUP_ALERT_EMAILS is set, so alert_new_company would have sent one.
        self.assertEqual(mail.outbox, [])

        company = self._fixture()
        subscription = company.subscription
        self.assertEqual(subscription.plan.slug, "starter")
        self.assertEqual(subscription.status, "active")
        self.assertIsNone(subscription.current_period_end)
        self.assertIsNone(subscription.trial_end)
        membership = WorksIn.objects.get(user=self.user, company=company)
        self.assertEqual(membership.role, WorksIn.COMPANY_ADMIN)
        farm = Establishment.objects.get(company=company)
        self.assertEqual(
            (farm.name, farm.farming_method, farm.is_demo, farm.country, farm.state),
            (fixture_cmd.FARM_NAME, "organic", True, "US", "WA"),
        )
        self.assertEqual(list(membership.establishments_in_charge.all()), [farm])
        self.assertEqual(LogEntry.objects.get_for_object(farm).count(), 1)
        log = DataOperationLog.objects.get()
        self.assertEqual(log.operation, fixture_cmd.OPERATION)
        self.assertEqual(log.counts["ids"]["company"], company.pk)
        self.assertIn(f"company id  : {company.pk}", output)
        self.assertNotIn("FAIL", output)

    def test_the_new_company_alert_does_send_when_called(self):
        """Guards the guard: with these settings the alert path sends mail, so outbox==[] means something."""
        from users.signup_alerts import alert_new_company

        company = Company.objects.create(name="Elsewhere")
        with self.captureOnCommitCallbacks(execute=True):
            alert_new_company(company, self.user)

        self.assertEqual(len(mail.outbox), 1)

    def test_readiness_shows_the_three_findings(self):
        self._run("--commit")
        farm = Establishment.objects.get(company=self._fixture())

        readiness = OperationReadinessService(farm).evaluate()

        self.assertTrue(readiness["applicable"])
        self.assertEqual(
            {b["code"] for b in readiness["blockers"]},
            {"ofpp.missing", "osp.none", "records.none"},
        )
        self.assertEqual(self.user.get_active_company(), self._fixture())
        self.assertFalse((self._fixture().subscription_plan.features or {}).get("compliance_exports"))

    def test_identical_rerun_is_a_no_op(self):
        self._run("--commit")
        before = _counts()

        output = self._run("--commit")

        self.assertEqual(_counts(), before)
        self.assertIn("already in place", output)
        self.assertIn(f"company id  : {self._fixture().pk}", output)

    # -- refusals -------------------------------------------------------

    def _assert_refused(self, message, *extra, email=EMAIL):
        before = _counts()
        with self.assertRaises(CommandError) as ctx:
            self._run("--commit", *extra, email=email)
        self.assertIn(message, str(ctx.exception))
        self.assertEqual(_counts(), before)

    def test_refuses_an_email_that_is_not_a_review_alias(self):
        for email in ("grower@farm.test", "oscar@trazo.io", "oscar+astra@trazo.io.evil.test", "xoscar+astra@trazo.io"):
            with self.subTest(email):
                User.objects.get_or_create(
                    email=email, defaults={"is_active": True, "is_verified": True, "user_type": PRODUCER}
                )
                self._assert_refused("not a review account", email=email)

    def test_refuses_a_missing_account(self):
        self._assert_refused("No account", email="oscar+astranobody@trazo.io")

    def test_refuses_an_account_that_cannot_sign_in(self):
        cases = {
            "consumer": {"user_type": CONSUMER},
            "unverified": {"is_verified": False},
            "deactivated": {"is_active": False},
        }
        for label, attrs in cases.items():
            with self.subTest(label):
                User.objects.filter(pk=self.user.pk).update(
                    **{"is_active": True, "is_verified": True, "user_type": PRODUCER, **attrs}
                )
                self._assert_refused("cannot sign in")

    def test_refuses_a_starter_plan_that_carries_compliance_exports(self):
        starter = Plan.objects.get(slug="starter")
        starter.features = {**(starter.features or {}), "compliance_exports": True}
        starter.save()

        self._assert_refused("compliance_exports")

    def test_refuses_an_inactive_or_missing_starter(self):
        Plan.objects.filter(slug="starter").update(is_active=False)
        self._assert_refused("inactive")
        Plan.objects.filter(slug="starter").update(slug="starter-gone")
        self._assert_refused("No `starter` plan")

    def test_refuses_an_account_holding_other_company_data(self):
        other = Company.objects.create(name="Real Farm Co")
        WorksIn.objects.create(user=self.user, company=other, role=WorksIn.COMPANY_ADMIN)

        self._assert_refused("other company data")

    def test_refuses_a_fixture_that_has_been_written_to(self):
        self._run("--commit")
        Parcel.objects.create(name="Block A", area=1, establishment=Establishment.objects.get(company=self._fixture()))

        self._assert_refused("no longer the untouched fixture")

    # -- remove ---------------------------------------------------------

    def test_remove_dry_run_then_commit(self):
        self._run("--commit")
        company_id = self._fixture().pk
        farm_id = Establishment.objects.get(company_id=company_id).pk
        before = _counts()

        self.assertIn("DRY RUN", self._run("--remove"))
        self.assertEqual(_counts(), before)

        self._run("--remove", "--commit")

        self.assertFalse(Company.objects.filter(pk=company_id).exists())
        self.assertFalse(Establishment.objects.filter(company_id=company_id).exists())
        self.assertFalse(Subscription.objects.filter(company_id=company_id).exists())
        self.assertFalse(WorksIn.objects.filter(company_id=company_id).exists())
        self.assertFalse(SubscriptionEvent.objects.filter(company_id=company_id).exists())
        # auditlog keeps its history: the create entry stays and a delete entry is added.
        self.assertEqual(
            sorted(
                LogEntry.objects.filter(content_type__model="establishment", object_pk=str(farm_id)).values_list(
                    "action", flat=True
                )
            ),
            [LogEntry.Action.CREATE, LogEntry.Action.DELETE],
        )
        self.assertTrue(DataOperationLog.objects.filter(operation=fixture_cmd.REMOVE_OPERATION).exists())
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists(), "removal deleted the account")

    def test_remove_with_no_fixture_does_nothing(self):
        before = _counts()
        self.assertIn("Nothing to remove", self._run("--remove", "--commit"))
        self.assertEqual(_counts(), before)

    def _assert_remove_refused(self, message, mutate):
        self._run("--commit")
        company = self._fixture()
        mutate(company, Establishment.objects.get(company=company))
        before = _counts()

        with self.assertRaises(CommandError) as ctx:
            self._run("--remove", "--commit")

        self.assertIn(message, str(ctx.exception))
        self.assertEqual(_counts(), before)

    def test_remove_refuses_another_member(self):
        def mutate(company, farm):
            other = User.objects.create_user(email="someone@farm.test", password="x")
            WorksIn.objects.create(user=other, company=company, role=WorksIn.COMPANY_ADMIN)

        self._assert_remove_refused("another member", mutate)

    def test_remove_refuses_an_invitation(self):
        def mutate(company, farm):
            CompanyInvitation.objects.create(email="someone@farm.test", company=company, inviter=self.user)

        self._assert_remove_refused("an invitation", mutate)

    def test_remove_refuses_a_non_demo_farm(self):
        self._assert_remove_refused(
            "non-demo farm", lambda company, farm: Establishment.objects.filter(pk=farm.pk).update(is_demo=False)
        )

    def test_remove_refuses_a_parcel(self):
        self._assert_remove_refused(
            "a parcel", lambda company, farm: Parcel.objects.create(name="Block A", area=1, establishment=farm)
        )

    def test_remove_refuses_a_certificate(self):
        self._assert_remove_refused(
            "a certificate",
            lambda company, farm: Certification.objects.create(establishment=farm, certification_type="usda_organic"),
        )

    def test_remove_refuses_an_organic_system_plan(self):
        self._assert_remove_refused(
            "organic system plan",
            lambda company, farm: OrganicSystemPlan.objects.create(establishment=farm, version_number=1),
        )

    def test_remove_refuses_a_review_link(self):
        self._assert_remove_refused(
            "a review link",
            lambda company, farm: CertifierAccessLink.objects.create(
                establishment=farm, created_by=self.user, expires_at=timezone.now() + timedelta(days=7)
            ),
        )

    def test_remove_refuses_a_non_starter_subscription(self):
        self._assert_remove_refused(
            "not Starter",
            lambda company, farm: Subscription.objects.filter(company=company).update(
                plan=Plan.objects.get(slug="compliance-yearly")
            ),
        )
