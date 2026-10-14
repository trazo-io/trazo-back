"""`provision_pilot` puts two people on a pilot, each through the right door.

Found by the 2026-10-01 onboarding rehearsal (`documentation/gtm-v3/rehearsal/RESULTS-2026-10-01.md`
in the workspace repo):

1. Every record typed during setup was stored with `created_by` = the grower, because setup ran
   under the grower's own login. The operator now gets a membership of their own, so the audit
   trail names who typed the record.
2. The grower was created with a temporary password and never accepted the Terms
   (`terms_accepted_at` stayed None, no prompt at first login). The grower now gets an invitation
   link whose setup page requires the Terms, and `signup_with_invitation` stamps the acceptance.

The operator membership must be a direct `WorksIn` row: `CompanyInvitation.accept()` is a company
TRANSFER and deletes the accepting user's other memberships. The two-pilot test below is what
stops anyone "simplifying" the operator onto the invitation path.
"""

from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from rest_framework.test import APIClient

from users.constants import CONSUMER, PRODUCER
from users.models import User, WorksIn
from users.models_invitation import CompanyInvitation

OPERATOR = "operator@trazo.test"
GROWER = "dan@coldwater.test"


@override_settings(BASE_APP_URL="https://app.example.test/")
class ProvisionPilotPeopleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", stdout=StringIO(), stderr=StringIO())
        cls.operator = User.objects.create_user(email=OPERATOR, password="x", is_active=True)

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

    def test_the_operator_stays_a_member_of_every_pilot(self):
        """The reason the operator is never invited: accept() would transfer them out of pilot #1."""
        self._provision(company="Pilot One", email="one@farm.test")
        self._provision(company="Pilot Two", email="two@farm.test")

        companies = set(WorksIn.objects.filter(user=self.operator).values_list("company__name", flat=True))
        self.assertEqual(companies, {"Pilot One", "Pilot Two"})

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

    def test_the_operator_must_already_have_an_account(self):
        with self.assertRaises(CommandError) as ctx:
            self._provision(operator="nobody@trazo.test")
        self.assertIn("No active account", str(ctx.exception))
