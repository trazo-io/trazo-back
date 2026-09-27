"""
Two things a sign-up has to leave behind, added 2026-09-27 after the first outside accounts
turned out to be a competitor's staff and were found two days late, by scrolling the admin:

1. An alert to the owner, the day it happens, tagged when the address is a known competitor's.
2. A server-side record of which Terms the person agreed to. The sign-up checkbox was
   enforced only in the browser and never sent, so nothing showed who had agreed to what.
"""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from rest_framework.test import APIClient

from company.models import Company
from users.constants import PRODUCER, TERMS_VERSION
from users.models_invitation import CompanyInvitation
from users.signup_alerts import send_new_company_alert

User = get_user_model()

SIGNUP_URL = "/api/auth/register/"
ALERTS_ON = override_settings(SIGNUP_ALERT_EMAILS=["owner@example.com"])


def _payload(email="paula@example.com", **extra):
    return {
        "first_name": "Paula",
        "last_name": "Reyes",
        "email": email,
        "password": "OrchardRoad2026!",
        "user_type": "PRODUCER",
        **extra,
    }


class TermsAcceptanceRecordedTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_email_signup_with_accept_terms_records_version(self):
        response = self.client.post(SIGNUP_URL, _payload(accept_terms=True), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        user = User.objects.get(email="paula@example.com")
        self.assertEqual(user.terms_version, TERMS_VERSION)
        self.assertIsNotNone(user.terms_accepted_at)

    def test_email_signup_without_accept_terms_records_nothing_but_still_succeeds(self):
        # Not yet required: an older frontend build that does not send the field must keep working.
        response = self.client.post(SIGNUP_URL, _payload(), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        user = User.objects.get(email="paula@example.com")
        self.assertEqual(user.terms_version, "")
        self.assertIsNone(user.terms_accepted_at)

    def test_invitation_signup_records_terms(self):
        inviter = User.objects.create_user(
            email="owner@farm.example", password="x", first_name="O", last_name="W", user_type=PRODUCER
        )
        company = Company.objects.create(name="Loma Orchards")
        invitation = CompanyInvitation.objects.create(
            email="crew@farm.example", company=company, inviter=inviter, role="FM"
        )
        response = self.client.post(
            "/api/auth/signup-with-invitation/",
            {
                "first_name": "Crew",
                "last_name": "Lead",
                "password": "OrchardRoad2026!",
                "invitation_code": invitation.invitation_code,
                "accept_terms": True,
            },
            format="json",
        )
        self.assertIn(response.status_code, (200, 201), response.content)
        self.assertEqual(User.objects.get(email="crew@farm.example").terms_version, TERMS_VERSION)

    def test_record_terms_acceptance_reads_raw_request_values(self):
        user = User.objects.create_user(email="a@example.com", password="x", first_name="A", last_name="B")
        for falsy in (None, False, "false", "", "0"):
            user.record_terms_acceptance(falsy)
            self.assertIsNone(user.terms_accepted_at, falsy)
        user.record_terms_acceptance("true")
        user.refresh_from_db()
        self.assertEqual(user.terms_version, TERMS_VERSION)

    def test_record_terms_acceptance_never_overwrites_the_first_acceptance(self):
        user = User.objects.create_user(email="a@example.com", password="x", first_name="A", last_name="B")
        user.record_terms_acceptance(True)
        first = user.terms_accepted_at
        user.record_terms_acceptance(True)
        user.refresh_from_db()
        self.assertEqual(user.terms_accepted_at, first)


class SignupAlertTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _signup(self, email, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(SIGNUP_URL, _payload(email=email, **extra), format="json")
        self.assertEqual(response.status_code, 201, response.content)

    @ALERTS_ON
    def test_new_account_alerts_the_owner(self):
        self._signup("paula@example.com", accept_terms=True)
        alerts = [m for m in mail.outbox if m.to == ["owner@example.com"]]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].subject, "New Trazo account: paula@example.com")
        self.assertIn(f"Terms accepted: {TERMS_VERSION}", alerts[0].body)
        self.assertIn("Sign-up method: email", alerts[0].body)

    @ALERTS_ON
    def test_competitor_domain_is_tagged_in_the_subject(self):
        self._signup("collins@quickorganics.com")
        (alert,) = [m for m in mail.outbox if m.to == ["owner@example.com"]]
        self.assertTrue(alert.subject.startswith("[COMPETITOR] "), alert.subject)
        self.assertIn("Terms accepted: NOT RECORDED", alert.body)

    def test_no_alert_when_no_recipient_is_configured(self):
        # The default everywhere: dev and CI must never mail the owner.
        self._signup("paula@example.com")
        self.assertFalse([m for m in mail.outbox if "New Trazo account" in m.subject])

    @ALERTS_ON
    def test_new_company_alert_names_company_and_creator(self):
        creator = User.objects.create_user(
            email="ellie@example.com", password="x", first_name="E", last_name="S", user_type=PRODUCER
        )
        company = Company.objects.create(name="Silver Reef Farms")
        mail.outbox.clear()
        send_new_company_alert(company.pk, creator.pk)
        (alert,) = mail.outbox
        self.assertEqual(alert.subject, "New Trazo company: Silver Reef Farms")
        self.assertIn("Email: ellie@example.com", alert.body)

    @ALERTS_ON
    def test_company_create_endpoint_sends_the_alert(self):
        creator = User.objects.create_user(
            email="ellie@example.com", password="x", first_name="E", last_name="S", user_type=PRODUCER
        )
        creator.is_active = True
        creator.save()
        self.client.force_authenticate(creator)
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/companies/",
                {"name": "Silver Reef Farms", "address": "1 Main St", "city": "Wellington", "country": "US"},
                format="json",
            )
        self.assertEqual(response.status_code, 201, response.content)
        subjects = [m.subject for m in mail.outbox if m.to == ["owner@example.com"]]
        self.assertIn("New Trazo company: Silver Reef Farms", subjects)
