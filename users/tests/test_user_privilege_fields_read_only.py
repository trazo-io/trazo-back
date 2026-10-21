"""A user cannot grant themselves privileges through their own profile.

`BasicUserSerializer` declared `read_only_field = [...]` (no s) from 2023-09-25 to 2026-10-20. DRF
ignores an unknown Meta attribute, so every field in `fields` was writable, `is_superuser` included,
and `UserViewSet` lets a user PATCH their own row. One request made any signed-in account a
superuser, which `IsSuperUser` on every company-nested route turns into every tenant's data.

The fix is the spelling. The guard is the allowlist: the test pins the exact set of WRITABLE fields,
so a new privilege field, or the next typo of the same kind, fails here instead of shipping. A
deny-list of "fields that must be read-only" would have passed through the original bug.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from users.constants import PRODUCER, SUPERUSER
from users.models import User
from users.serializers import BasicUserSerializer, MeSerializer

# What ProfileUser.tsx sends: the only legitimate writes through /api/users/<id>/.
PROFILE_FIELDS = {"email", "phone", "first_name", "last_name", "image"}


def _writable(serializer_class):
    return {name for name, field in serializer_class().fields.items() if not field.read_only}


class PrivilegeFieldsAreReadOnlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="plain@example.com",
            password="x",
            first_name="Plain",
            last_name="Producer",
            user_type=PRODUCER,
            is_active=True,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_writable_fields_are_exactly_the_profile_fields(self):
        for serializer_class in (BasicUserSerializer, MeSerializer):
            with self.subTest(serializer=serializer_class.__name__):
                self.assertEqual(_writable(serializer_class), PROFILE_FIELDS)

    def test_self_patch_cannot_grant_superuser(self):
        response = self.client.patch(f"/api/users/{self.user.id}/", {"is_superuser": True}, format="json")
        self.assertEqual(response.status_code, 200)  # the field is ignored, not refused
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    def test_self_patch_cannot_change_user_type(self):
        self.client.patch(f"/api/users/{self.user.id}/", {"user_type": SUPERUSER}, format="json")
        self.user.refresh_from_db()
        self.assertEqual(self.user.user_type, PRODUCER)

    def test_self_patch_cannot_touch_memberships(self):
        response = self.client.patch(
            f"/api/users/{self.user.id}/", {"companies": [{"company": 1, "role": "CA"}]}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.user.worksin_set.exists())

    def test_profile_edit_still_works(self):
        """The control: the same request shape ProfileUser.tsx sends (multipart) still saves."""
        response = self.client.patch(
            f"/api/users/{self.user.id}/",
            {"first_name": "Renamed", "last_name": "Grower", "phone": "+15095550100"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.phone), ("Renamed", "+15095550100"))


class SignUpCannotChoosePrivilegedTypeTests(TestCase):
    """`RegisterSerializer.create` maps "SUPERUSER" to 1, and the frontend opens its superuser UI on it."""

    def _register(self, user_type, email):
        return APIClient().post(
            "/api/auth/register/",
            {
                "first_name": "New",
                "last_name": "Grower",
                "email": email,
                "password": "Str0ng!Passw0rd",
                "user_type": user_type,
            },
        )

    def test_privileged_types_are_refused(self):
        for i, user_type in enumerate(("SUPERUSER", "staff", "1", "2")):
            with self.subTest(user_type=user_type):
                email = f"climber{i}@example.com"
                response = self._register(user_type, email)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertFalse(User.objects.filter(email=email).exists())

    def test_producer_signup_still_works(self):
        response = self._register("PRODUCER", "grower@example.com")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(User.objects.get(email="grower@example.com").user_type, PRODUCER)
