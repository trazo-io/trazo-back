"""
The signup / sign-in / reset triangle, tested as one loop rather than three endpoints.

Every screen in this triangle used to point at the next one, and the loop never let go:

    signup  -> "A user with this email address already exists. Please sign in instead."
    sign-in -> "No active account found with the given credentials."   (is_active is False)
    reset   -> "Password reset successfully. You can now sign in with your new password."
    sign-in -> "No active account found with the given credentials."   (still False)

Each sentence is individually defensible and the sequence is a dead end, which is why no
per-endpoint test caught it. These tests assert the TRANSITIONS, not the messages.
"""

from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from users.constants import EMAIL_EXISTS_UNVERIFIED, EMAIL_EXISTS_VERIFIED, PRODUCER
from users.models import PasswordResetToken

User = get_user_model()

SIGNUP_URL = "/api/auth/register/"
RESET_CONFIRM_URL = "/api/users/confirm_password_reset/"


def _signup_payload(email="paula@example.com"):
    return {
        "first_name": "Paula",
        "last_name": "Reyes",
        "email": email,
        "password": "OrchardRoad2026!",
        "user_type": "PRODUCER",
    }


class DuplicateEmailCodeTests(TestCase):
    """The duplicate-email refusal has to say WHICH recovery is open, in a machine code."""

    def setUp(self):
        self.client = APIClient()

    def _post_signup(self, email):
        return self.client.post(SIGNUP_URL, _signup_payload(email), format="json")

    def test_unverified_duplicate_returns_unverified_code(self):
        User.objects.create_user(
            email="paula@example.com",
            password="OrchardRoad2026!",
            first_name="Paula",
            last_name="Reyes",
            user_type=PRODUCER,
        )
        # create_user leaves is_verified False — this is the state a farmer lands in by
        # signing up and not clicking the link, which is the COMMON way to hit this error.
        self.assertFalse(User.objects.get(email="paula@example.com").is_verified)

        response = self._post_signup("paula@example.com")

        self.assertEqual(response.status_code, 400)
        # DRF's as_serializer_error wraps a bare string value in a list. Asserting the
        # unwrapped shape here is the point: the client reads data["code"][0], and if this
        # ever stops being a list the client silently falls through to the generic message.
        self.assertEqual(response.data["code"], [EMAIL_EXISTS_UNVERIFIED])
        self.assertIn("verified", response.data["email"][0].lower())

    def test_verified_duplicate_returns_verified_code(self):
        user = User.objects.create_user(
            email="paula@example.com",
            password="OrchardRoad2026!",
            first_name="Paula",
            last_name="Reyes",
            user_type=PRODUCER,
        )
        user.is_verified = True
        user.is_active = True
        user.save(update_fields=["is_verified", "is_active"])

        response = self._post_signup("paula@example.com")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], [EMAIL_EXISTS_VERIFIED])

    def test_the_two_codes_are_distinguishable(self):
        """
        Anti-vacuity. Both branches returning the same code would satisfy each test above
        read on its own, and would hand the UI one action for two different situations.
        """
        self.assertNotEqual(EMAIL_EXISTS_VERIFIED, EMAIL_EXISTS_UNVERIFIED)

    def test_case_differing_duplicate_is_still_a_duplicate(self):
        User.objects.create_user(email="paula@example.com", password="OrchardRoad2026!", user_type=PRODUCER)

        response = self._post_signup("Paula@Example.com")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], [EMAIL_EXISTS_UNVERIFIED])

    def test_fresh_email_still_creates_an_account(self):
        """The check moved from a field validator to validate(); prove it did not stop letting
        legitimate signups through."""
        response = self._post_signup("nuevo@example.com")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(User.objects.filter(email="nuevo@example.com").exists())


class PasswordResetUnlocksAccountTests(TestCase):
    """`confirm_password_reset` promises "You can now sign in" — prove that is now true."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="paula@example.com",
            password="OldOrchard2026!",
            first_name="Paula",
            last_name="Reyes",
            user_type=PRODUCER,
        )
        self.token = PasswordResetToken.objects.create(
            user=self.user,
            token="a" * 48,
            expires_at=timezone.now() + timedelta(minutes=15),
        )

    def _confirm(self, password="BrandNewOrchard2026!"):
        return self.client.post(
            RESET_CONFIRM_URL,
            {"token": self.token.token, "email": self.user.email, "new_password": password},
            format="json",
        )

    def test_unverified_account_cannot_authenticate_before_reset(self):
        """The precondition. Without this the test below could pass for the wrong reason."""
        self.assertIsNone(authenticate(username="paula@example.com", password="OldOrchard2026!"))

    def test_reset_activates_and_verifies(self):
        response = self._confirm()

        self.assertEqual(response.status_code, 200, response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.is_verified)

    def test_the_promise_in_the_response_body_holds(self):
        """
        The endpoint answers "You can now sign in with your new password." This asserts the
        sentence, not the flags: authenticate() is what the sign-in screen actually calls.
        """
        self._confirm(password="BrandNewOrchard2026!")

        self.assertIsNotNone(authenticate(username="paula@example.com", password="BrandNewOrchard2026!"))

    def test_already_verified_account_is_untouched(self):
        self.user.is_verified = True
        self.user.is_active = True
        self.user.save(update_fields=["is_verified", "is_active"])

        self._confirm()

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.is_verified)

    def test_pending_verification_codes_survive_the_reset(self):
        """
        Deliberate: `verify_email` answers an already-verified user with "User is already
        verified", which is legible. Deleting the code would make that same click answer
        "Verification code is invalid", which is worse for someone who resets and then finds
        the older email in their inbox.
        """
        from users.models import VerificationCode

        VerificationCode.objects.create(user=self.user, code="123456")

        self._confirm()

        self.assertTrue(VerificationCode.objects.filter(user=self.user).exists())
