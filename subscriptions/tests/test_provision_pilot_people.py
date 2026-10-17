"""`provision_pilot` puts two people on a pilot, each through the right door.

Found by the 2026-10-01 onboarding rehearsal (`documentation/gtm-v3/rehearsal/RESULTS-2026-10-01.md`
in the workspace repo):

1. Every record typed during setup was stored with `created_by` = the grower, because setup ran
   under the grower's own login. The operator now gets a membership of their own, so the audit
   trail names who typed the record.
2. The grower was created with a temporary password and never accepted the Terms
   (`terms_accepted_at` stayed None, no prompt at first login). The grower now gets an invitation
   link whose setup page requires the Terms, and `signup_with_invitation` stamps the acceptance.

One company per account (2026-10-17). The app loads `user.companies[0]` and has no company
switcher, so the 2026-10-01 design (the operator's own account added to every pilot as an extra
membership) left the operator unable to open the pilot; a production rehearsal found it. Each pilot
now gets a dedicated operator account that belongs to it alone, created by the command with a setup
link, and any account that already belongs to another company is refused.
"""

from io import StringIO
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import authenticate
from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from rest_framework.test import APIClient

from company.models import Company
from users.constants import CONSUMER, PRODUCER
from users.models import PasswordResetToken, User, WorksIn
from users.models_invitation import CompanyInvitation

OPERATOR = "operator@trazo.test"
NEW_OPERATOR = "oscar+coldwater@trazo.test"
GROWER = "dan@coldwater.test"


def _setup_link(output):
    for line in output.splitlines():
        if "OPERATOR SETUP LINK:" in line:
            return line.split("OPERATOR SETUP LINK:", 1)[1].strip()
    return None


@override_settings(BASE_APP_URL="https://app.example.test/")
class ProvisionPilotPeopleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", stdout=StringIO(), stderr=StringIO())
        # An existing operator must be able to sign in now (producer, verified), the same gates
        # the grower has always been held to. It belongs to no company.
        cls.operator = User.objects.create_user(
            email=OPERATOR, password="x", is_active=True, is_verified=True, user_type=PRODUCER
        )

    def _provision(self, company="Coldwater Bench Orchard", email=GROWER, operator=OPERATOR):
        out = StringIO()
        call_command(
            "provision_pilot",
            "--company",
            company,
            "--email",
            email,
            "--farm",
            "Coldwater Bench",
            "--state",
            "WA",
            "--operator-email",
            operator,
            "--renewal-date",
            "2099-03-01",
            "--commit",
            stdout=out,
            stderr=StringIO(),
        )
        return out.getvalue()

    def _provision_or_fail(self, **kwargs):
        """A refusal here is the behaviour under test failing, so it reports as an AssertionError."""
        try:
            return self._provision(**kwargs)
        except CommandError as exc:
            self.fail(f"provision_pilot refused: {exc}")

    def test_the_operator_gets_a_membership_of_their_own(self):
        self._provision()

        membership = WorksIn.objects.get(user=self.operator, company__name="Coldwater Bench Orchard")
        self.assertEqual(membership.role, WorksIn.COMPANY_ADMIN)

    def test_the_company_payload_names_the_pilot_plan(self):
        """The app shows the pilot setup checklist from `subscription.plan.slug == "pilot"`.

        Run 8b (8b-02): the dashboard and the onboarding checklist read the company payload,
        never a separate flag, so this is the one fact the pilot view depends on.
        """
        from company.models import Company

        self._provision()
        company = Company.objects.get(name="Coldwater Bench Orchard")
        client = APIClient()
        client.force_authenticate(user=self.operator)

        response = client.get(reverse("companies-detail", args=[company.id]))

        self.assertEqual(response.status_code, 200, response.data)
        plan = response.data["subscription"]["plan"]
        self.assertEqual(plan["slug"], "pilot")
        self.assertIs(plan["features"].get("is_pilot"), True)

    def test_the_grower_gets_an_invitation_not_a_password(self):
        output = self._provision()

        self.assertFalse(
            User.objects.filter(email=GROWER).exists(),
            "the grower account was created by the command, so no Terms were ever accepted",
        )
        invitation = CompanyInvitation.objects.get(email=GROWER, company__name="Coldwater Bench Orchard")
        self.assertTrue(invitation.can_be_accepted())
        self.assertEqual(invitation.inviter, self.operator)
        self.assertIn(f"https://app.example.test/invitation/{invitation.invitation_code}/setup", output)
        self.assertNotIn("TEMPORARY PASSWORD", output)

    def test_accepting_the_link_records_the_terms_and_keeps_the_operator(self):
        self._provision()
        invitation = CompanyInvitation.objects.get(email=GROWER)

        response = APIClient().post(
            reverse("signup_with_invitation"),
            {
                "first_name": "Dan",
                "last_name": "Tollefsen",
                "password": "a-Strong-pass-2026",
                "invitation_code": invitation.invitation_code,
                "accept_terms": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        grower = User.objects.get(email=GROWER)
        self.assertIsNotNone(grower.terms_accepted_at, "the pilot grower never accepted the Terms")
        company = invitation.company
        self.assertTrue(WorksIn.objects.filter(user=grower, company=company).exists())
        self.assertTrue(
            WorksIn.objects.filter(user=self.operator, company=company).exists(),
            "the grower's acceptance removed the operator from the pilot",
        )

    def test_one_operator_account_cannot_serve_two_pilots(self):
        """Replaces "the operator stays a member of every pilot", which encoded the defect.

        The app opens only an account's first company, so a second pilot on the same account is a
        pilot the operator can never reach.
        """
        self._provision(company="Pilot One", email="one@farm.test")

        with self.assertRaises(CommandError) as ctx:
            self._provision(company="Pilot Two", email="two@farm.test")

        self.assertIn("already belongs to Pilot One", str(ctx.exception))
        self.assertIn("oscar+pilottwo@trazo.io", str(ctx.exception))
        self.assertFalse(Company.objects.filter(name="Pilot Two").exists(), "a refusal must write nothing")
        companies = set(WorksIn.objects.filter(user=self.operator).values_list("company__name", flat=True))
        self.assertEqual(companies, {"Pilot One"})

    def test_an_operator_with_another_company_is_refused(self):
        """oscar@trazo.io owns its own company: adding it to a pilot hides one of the two."""
        own = Company.objects.create(name="Trazo Demo Orchard")
        WorksIn.objects.create(user=self.operator, company=own, role=WorksIn.COMPANY_ADMIN)

        with self.assertRaises(CommandError) as ctx:
            self._provision()

        message = str(ctx.exception)
        self.assertIn("Trazo Demo Orchard", message)
        self.assertIn("no company switcher", message)
        self.assertIn("oscar+coldwaterbenchorchard@trazo.io", message)
        self.assertEqual(list(self.operator.companies.all()), [own])
        self.assertFalse(Company.objects.filter(name="Coldwater Bench Orchard").exists())

    def test_an_existing_grower_with_another_company_is_refused(self):
        grower = User.objects.create_user(
            email=GROWER, password="x", is_active=True, is_verified=True, user_type=PRODUCER
        )
        WorksIn.objects.create(user=grower, company=Company.objects.create(name="Their Own Farm"), role="CA")

        with self.assertRaises(CommandError) as ctx:
            self._provision()

        self.assertIn("--email", str(ctx.exception))
        self.assertIn("Their Own Farm", str(ctx.exception))
        self.assertEqual(grower.companies.count(), 1)

    def test_a_new_operator_account_is_created_with_a_setup_link_and_one_membership(self):
        output = self._provision_or_fail(operator=NEW_OPERATOR)

        operator = User.objects.get(email=NEW_OPERATOR)
        company = Company.objects.get(name="Coldwater Bench Orchard")
        self.assertEqual((operator.first_name, operator.last_name), ("Oscar", "Munoz (Trazo setup)"))
        self.assertEqual(operator.user_type, PRODUCER)
        self.assertTrue(operator.is_active)
        self.assertFalse(operator.has_usable_password(), "no password exists until the operator sets one")
        self.assertEqual(list(operator.companies.all()), [company])
        self.assertEqual(WorksIn.objects.get(user=operator).role, WorksIn.COMPANY_ADMIN)
        self.assertEqual(CompanyInvitation.objects.get(email=GROWER).inviter, operator)

        link = _setup_link(output)
        self.assertIsNotNone(link, output)
        self.assertTrue(link.startswith("https://app.example.test/auth/reset-password?"), link)
        token = parse_qs(urlparse(link).query)["token"][0]
        self.assertTrue(PasswordResetToken.objects.get(user=operator, token=token).is_valid())
        self.assertNotIn("password:", output.lower())
        self.assertIn("PASS  operator belongs to exactly one company (this one)", output)
        self.assertIn("PASS  operator setup link can be accepted", output)

    def test_the_operator_names_come_from_the_new_arguments(self):
        out = StringIO()
        try:
            call_command(
                "provision_pilot",
                "--company",
                "Name Pilot",
                "--email",
                "g@name.test",
                "--farm",
                "F",
                "--operator-email",
                NEW_OPERATOR,
                "--operator-first-name",
                "Ana",
                "--operator-last-name",
                "Rivera",
                "--renewal-date",
                "2099-03-01",
                "--commit",
                stdout=out,
                stderr=StringIO(),
            )
        except CommandError as exc:
            self.fail(f"provision_pilot refused: {exc}")
        self.assertEqual(User.objects.get(email=NEW_OPERATOR).get_full_name(), "Ana Rivera (Trazo setup)")

    @override_settings(SIGNUP_ALERT_EMAILS=["owner@example.test"])
    def test_creating_the_operator_sends_no_email(self):
        # Not vacuous: with the alert list set, an ordinary account creation does send mail.
        with self.captureOnCommitCallbacks(execute=True):
            User.objects.create_user(email="control@example.test", password="x", user_type=PRODUCER)
        self.assertGreater(len(mail.outbox), 0, "the control sign-up sent nothing; the check below is vacuous")
        mail.outbox = []

        with self.captureOnCommitCallbacks(execute=True):
            self._provision_or_fail(operator=NEW_OPERATOR)

        self.assertTrue(User.objects.filter(email=NEW_OPERATOR).exists())
        self.assertEqual([m.subject for m in mail.outbox], [])

    def test_rerunning_renews_the_operator_setup_link(self):
        first = _setup_link(self._provision_or_fail(operator=NEW_OPERATOR))
        second = _setup_link(self._provision_or_fail(operator=NEW_OPERATOR))

        self.assertNotEqual(first, second)
        operator = User.objects.get(email=NEW_OPERATOR)
        valid = [t for t in PasswordResetToken.objects.filter(user=operator) if t.is_valid()]
        self.assertEqual(len(valid), 1, "only the newest setup link may work")
        self.assertEqual(operator.companies.count(), 1)

    def test_full_flow_the_operator_opens_the_pilot(self):
        """Provision, open the operator link, the grower accepts: the operator lands on the pilot."""
        output = self._provision_or_fail(operator=NEW_OPERATOR)
        company = Company.objects.get(name="Coldwater Bench Orchard")
        query = parse_qs(urlparse(_setup_link(output) or "").query)

        response = APIClient().post(
            reverse("user-confirm-password-reset"),
            {"token": query["token"][0], "email": query["email"][0], "new_password": "Rq7#vLm2-Tzpw!x"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

        invitation = CompanyInvitation.objects.get(email=GROWER)
        response = APIClient().post(
            reverse("signup_with_invitation"),
            {
                "first_name": "Dan",
                "last_name": "Tollefsen",
                "password": "a-Strong-pass-2026",
                "invitation_code": invitation.invitation_code,
                "accept_terms": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

        operator = authenticate(email=NEW_OPERATOR, password="Rq7#vLm2-Tzpw!x")
        self.assertIsNotNone(operator, "the operator cannot sign in after using the setup link")
        self.assertTrue(operator.is_verified)
        self.assertEqual(operator.get_active_company(), company)
        self.assertEqual(list(operator.companies.all()), [company])
        self.assertEqual(set(company.company_users.values_list("email", flat=True)), {NEW_OPERATOR, GROWER})

    def test_rerunning_renews_the_invitation_instead_of_failing(self):
        self._provision()
        self._provision()

        self.assertEqual(
            CompanyInvitation.objects.filter(email=GROWER, status=CompanyInvitation.STATUS_PENDING).count(), 1
        )

    def test_an_existing_producer_account_is_added_directly(self):
        grower = User.objects.create_user(
            email=GROWER, password="x", is_active=True, is_verified=True, user_type=PRODUCER
        )

        output = self._provision()

        self.assertTrue(WorksIn.objects.filter(user=grower, company__name="Coldwater Bench Orchard").exists())
        self.assertFalse(CompanyInvitation.objects.filter(email=GROWER).exists())
        self.assertIn("already had an account", output)

    def test_an_existing_account_that_cannot_sign_in_is_refused(self):
        """back#82 review: a consumer, unverified or deactivated account must not print PASS.

        `user_type` defaults to CONSUMER, so a consumer sign-up on the grower's email would have
        been added as a company admin and then stopped by the app login with "Access denied".
        """
        cases = {
            "consumer": {"is_active": True, "is_verified": True, "user_type": CONSUMER},
            "unverified": {"is_active": True, "is_verified": False, "user_type": PRODUCER},
            "deactivated": {"is_active": False, "is_verified": True, "user_type": PRODUCER},
        }
        for label, attrs in cases.items():
            with self.subTest(label):
                email = f"{label}@coldwater.test"
                User.objects.create_user(email=email, password="x", **attrs)

                with self.assertRaises(CommandError) as ctx:
                    self._provision(company=f"Pilot {label}", email=email)

                self.assertIn("cannot sign in", str(ctx.exception))
                self.assertFalse(WorksIn.objects.filter(user__email=email).exists())

    def test_the_operator_cannot_be_the_grower(self):
        with self.assertRaises(CommandError) as ctx:
            self._provision(email=OPERATOR)
        self.assertIn("same account", str(ctx.exception))

    def test_an_existing_operator_that_cannot_sign_in_is_refused(self):
        """Replaces "the operator must already have an account": a missing account is now created.

        An existing one still has to pass the login gates (a consumer sign-up would get "Access
        denied" in the app).
        """
        User.objects.create_user(email="consumer@trazo.test", password="x", is_active=True, is_verified=True)

        with self.assertRaises(CommandError) as ctx:
            self._provision(operator="consumer@trazo.test")

        self.assertIn("cannot be the operator", str(ctx.exception))
        self.assertFalse(Company.objects.filter(name="Coldwater Bench Orchard").exists())
