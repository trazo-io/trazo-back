"""
`/api/companies/` must only ever show a user their own companies.

Until 2026-09-28 `CompanyViewSet` never set `self.company` (it is not nested under a
`company_pk`), and every permission in `backend/permissions.py` returns True when
`self.company` is None. A probe signed in as an unrelated account listed every company with
its join code, read another company's members and renamed it. The join code then gave Viewer
access to all of that company's farms. These tests pin each step of that chain shut.
"""

from django.conf import settings
from django.core import mail
from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from company.models import Company
from users.constants import PRODUCER
from users.models import User, WorksIn


def _user(email):
    return User.objects.create_user(
        email=email,
        password="x",
        first_name=email[0].upper(),
        last_name="Test",
        user_type=PRODUCER,
        is_active=True,
    )


class CompanyTenantIsolationTests(TestCase):
    def setUp(self):
        self.victim_co = Company.objects.create(name="Victim Farms")
        self.victim_admin = _user("admin@victim.example")
        WorksIn.objects.create(user=self.victim_admin, company=self.victim_co, role=WorksIn.COMPANY_ADMIN)

        self.outsider_co = Company.objects.create(name="Outsider Co")
        self.outsider = _user("admin@outsider.example")
        WorksIn.objects.create(user=self.outsider, company=self.outsider_co, role=WorksIn.COMPANY_ADMIN)

        self.client = APIClient()

    def _as(self, user):
        self.client.force_authenticate(user)
        return self.client

    def test_list_shows_only_own_companies(self):
        response = self._as(self.outsider).get("/api/companies/")
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        # A negative assertion has to prove it read something: the outsider's own row is there.
        self.assertEqual([r["name"] for r in rows], ["Outsider Co"])

    def test_outsider_cannot_retrieve_another_company(self):
        response = self._as(self.outsider).get(f"/api/companies/{self.victim_co.id}/")
        self.assertIn(response.status_code, (403, 404))
        self.assertNotIn(self.victim_co.invitation_code, response.content.decode())

    def test_outsider_cannot_read_another_companys_members(self):
        response = self._as(self.outsider).get(f"/api/companies/{self.victim_co.id}/members/")
        self.assertIn(response.status_code, (403, 404))
        self.assertNotIn("admin@victim.example", response.content.decode())

    def test_outsider_cannot_edit_another_company(self):
        response = self._as(self.outsider).patch(
            f"/api/companies/{self.victim_co.id}/", {"name": "PWNED"}, format="json"
        )
        self.assertIn(response.status_code, (403, 404))
        self.victim_co.refresh_from_db()
        self.assertEqual(self.victim_co.name, "Victim Farms")

    def test_outsider_cannot_rotate_another_companys_code(self):
        before = self.victim_co.invitation_code
        response = self._as(self.outsider).post(f"/api/companies/{self.victim_co.id}/rotate-invitation-code/")
        self.assertIn(response.status_code, (403, 404))
        self.victim_co.refresh_from_db()
        self.assertEqual(self.victim_co.invitation_code, before)

    def test_admin_still_reads_and_edits_own_company(self):
        client = self._as(self.victim_admin)
        response = client.get(f"/api/companies/{self.victim_co.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["invitation_code"], self.victim_co.invitation_code)
        response = client.patch(
            f"/api/companies/{self.victim_co.id}/",
            {"name": "Victim Farms LLC"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)


class JoinCodeVisibilityAndRotationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Loma Orchards")
        self.admin = _user("admin@loma.example")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.viewer = _user("viewer@loma.example")
        WorksIn.objects.create(user=self.viewer, company=self.company, role=WorksIn.VIEWER)
        self.client = APIClient()

    def test_viewer_does_not_receive_the_join_code(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.get(f"/api/companies/{self.company.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Loma Orchards")
        self.assertIsNone(response.json()["invitation_code"])

    def test_viewer_cannot_rotate(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.post(f"/api/companies/{self.company.id}/rotate-invitation-code/")
        self.assertEqual(response.status_code, 403)

    def test_admin_rotation_kills_the_old_code(self):
        old_code = self.company.invitation_code
        self.client.force_authenticate(self.admin)
        response = self.client.post(f"/api/companies/{self.company.id}/rotate-invitation-code/")
        self.assertEqual(response.status_code, 200)
        new_code = response.json()["invitation_code"]
        self.assertNotEqual(new_code, old_code)
        self.company.refresh_from_db()
        self.assertEqual(self.company.invitation_code, new_code)

        self.client.force_authenticate(None)
        response = self.client.post(
            "/api/auth/register/",
            {
                "first_name": "Late",
                "last_name": "Joiner",
                "email": "late@example.com",
                "password": "OrchardRoad2026!",
                "user_type": "PRODUCER",
                "company_code": old_code,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(WorksIn.objects.filter(company=self.company, user__email="late@example.com").exists())

    def test_code_join_emails_the_company_admins(self):
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/auth/register/",
                {
                    "first_name": "New",
                    "last_name": "Member",
                    "email": "new@example.com",
                    "password": "OrchardRoad2026!",
                    "user_type": "PRODUCER",
                    "company_code": self.company.invitation_code,
                },
                format="json",
            )
        self.assertEqual(response.status_code, 201, response.content)
        notices = [m for m in mail.outbox if "joined Loma Orchards with your company code" in m.subject]
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].to, ["admin@loma.example"])
        self.assertIn("new@example.com", notices[0].body)
        self.assertIn("generate a new code", notices[0].body)


class RequestLogTests(TestCase):
    def test_api_request_is_logged_with_user_and_without_query_string(self):
        company = Company.objects.create(name="Loma Orchards")
        user = _user("admin@loma.example")
        WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
        client = APIClient()
        # Signed in the way the app is: the JWT access cookie, which the middleware resolves.
        client.cookies[settings.SIMPLE_JWT.get("AUTH_COOKIE", "access_token")] = str(
            RefreshToken.for_user(user).access_token
        )
        with self.assertLogs("backend.access", level="INFO") as logs:
            client.get("/api/companies/?secret=token123", HTTP_DO_CONNECTING_IP="203.0.113.7")
        line = logs.output[-1]
        self.assertIn("GET /api/companies/ 200", line)
        self.assertIn(f"user={user.pk}", line)
        self.assertIn("ip=203.0.113.7", line)
        self.assertNotIn("token123", line)


class RotateAllCompanyCodesCommandTests(TestCase):
    def test_dry_run_changes_nothing_and_apply_replaces_every_code(self):
        from io import StringIO

        from django.core.management import call_command

        a = Company.objects.create(name="A Farms")
        b = Company.objects.create(name="B Farms")
        before = {a.pk: a.invitation_code, b.pk: b.invitation_code}

        out = StringIO()
        call_command("rotate_company_codes", stdout=out)
        self.assertIn("Dry run: 2 companies", out.getvalue())
        for company in (a, b):
            company.refresh_from_db()
            self.assertEqual(company.invitation_code, before[company.pk])

        call_command("rotate_company_codes", "--apply", stdout=StringIO())
        for company in (a, b):
            company.refresh_from_db()
            self.assertTrue(company.invitation_code)
            self.assertNotEqual(company.invitation_code, before[company.pk])
