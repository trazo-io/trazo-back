"""Signing up through an invitation runs the server's password policy.

Until 2026-11-24 `signup_with_invitation` called `create_user` with whatever password arrived, so
every rule on that path lived in the browser and a POST straight to the endpoint set any password
(overall review 2026-11, OV-FJ-C03). Password reset already validated (`users/views.py`); this
path now does the same, against the invitee's own email and names.
"""

from rest_framework.test import APITestCase

from company.models import Company
from users.constants import PRODUCER
from users.models import User, WorksIn
from users.models_invitation import CompanyInvitation

URL = "/api/auth/signup-with-invitation/"


class InvitationSignupPasswordTests(APITestCase):
    def setUp(self):
        inviter = User.objects.create_user(
            email="owner@loma.example", password="x", first_name="Owner", last_name="Loma", user_type=PRODUCER
        )
        self.company = Company.objects.create(name="Loma Orchards")
        self.invitation = CompanyInvitation.objects.create(
            email="marisol@orchardcrew.example", company=self.company, inviter=inviter, role="FM"
        )

    def _signup(self, password):
        return self.client.post(
            URL,
            {
                "first_name": "Marisol",
                "last_name": "Quintana",
                "password": password,
                "invitation_code": self.invitation.invitation_code,
                "accept_terms": True,
            },
            format="json",
        )

    def _assert_refused_and_nothing_written(self, response):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(response.data["error"], "the refusal names the rule it broke")
        self.assertFalse(User.objects.filter(email=self.invitation.email).exists())
        self.assertFalse(WorksIn.objects.filter(company=self.company, user__email=self.invitation.email).exists())
        self.invitation.refresh_from_db()
        self.assertTrue(self.invitation.can_be_accepted(), "a refused signup leaves the invitation usable")

    def test_a_weak_password_is_refused(self):
        self._assert_refused_and_nothing_written(self._signup("1"))

    def test_a_password_with_the_invitees_name_is_refused(self):
        # Passes every rule that ignores the user (length, mixed case, digit, symbol), so a
        # refusal here proves the validator was handed the invitee, not `None`.
        response = self._signup("Quintana-Harvest-2026!")
        self._assert_refused_and_nothing_written(response)
        self.assertIn("last name", " ".join(response.data["error"]))

    def test_a_password_with_the_invitation_email_is_refused(self):
        # The email comes from the invitation, never from the request body.
        response = self._signup("Orchardcrew-Ridge-2026!")
        self._assert_refused_and_nothing_written(response)
        self.assertIn("email", " ".join(response.data["error"]))

    def test_a_strong_password_still_creates_the_account(self):
        response = self._signup("Copper-Ridge-Walnut-73!")
        self.assertIn(response.status_code, (200, 201), response.content)
        user = User.objects.get(email=self.invitation.email)
        self.assertTrue(user.check_password("Copper-Ridge-Walnut-73!"))
        self.assertTrue(WorksIn.objects.filter(company=self.company, user=user).exists())
