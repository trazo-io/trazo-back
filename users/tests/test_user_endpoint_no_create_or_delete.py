"""`/api/users/` reads and edits a profile. It never creates or deletes an account.

`UserViewSet` is a full ModelViewSet scoped to the caller's own row, so it also answered:

- `DELETE /api/users/<own id>/`. The overall review (2026-11, OV-SEC-C01) reproduced it: a
  sole Company Admin with no records deleted their account and left a company with a season in it
  and no member, and every SET_NULL authorship column on their records went blank. With records
  of their own the delete stopped only because an audit-log foreign key failed with a 500, not
  because anything refused it. Records are kept five years (7 CFR 205.103(b)(4)), and an account
  closes through `close_account` (export first, then delete), never through this route.
- `POST /api/users/`, which made a user row for any email a signed-in caller typed, so that address
  was taken before its owner signed up.

The app uses GET `me`, PATCH on its own row and the POST actions (`ProfileUser.tsx`,
`store/api/userApi.js`); none of those change here.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from company.models import Company
from users.constants import PRODUCER
from users.models import User, WorksIn


class UserEndpointNoCreateOrDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="sole-admin@example.com",
            password="x",
            first_name="Sole",
            last_name="Admin",
            user_type=PRODUCER,
            is_active=True,
        )
        cls.company = Company.objects.create(name="Sole Admin Orchards")
        WorksIn.objects.create(user=cls.user, company=cls.company, role=WorksIn.COMPANY_ADMIN)
        cls.superuser = User.objects.create_superuser(email="root@example.com", password="x")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_an_account_cannot_delete_itself(self):
        response = self.client.delete(f"/api/users/{self.user.id}/")
        self.assertEqual(response.status_code, 405)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        # The company keeps its member.
        self.assertEqual(WorksIn.objects.filter(company=self.company).count(), 1)

    def test_a_superuser_cannot_delete_an_account_through_the_api_either(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.delete(f"/api/users/{self.user.id}/")
        self.assertEqual(response.status_code, 405)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_no_account_is_created_for_an_email_typed_by_someone_else(self):
        response = self.client.post(
            "/api/users/",
            {"email": "not-yet-signed-up@example.com", "first_name": "Squat"},
            format="json",
        )
        self.assertEqual(response.status_code, 405)
        self.assertFalse(User.objects.filter(email="not-yet-signed-up@example.com").exists())

    def test_the_profile_still_reads_and_edits(self):
        """Anti-vacuity: the routes the app uses still answer."""
        self.assertEqual(self.client.get("/api/users/me/").status_code, 200)
        response = self.client.patch(f"/api/users/{self.user.id}/", {"first_name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Renamed")
