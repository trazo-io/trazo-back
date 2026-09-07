"""An emailed verification code has to stop working.

WHAT WENT WRONG. `VerificationCode` wrote `created_at` on every row and NOTHING read it.
`verify_email` accepted the newest code whatever its age, so a signup code stayed a valid
bearer credential forever: it survives a mailbox being resold, a shared laptop, a forwarded
"welcome to Trazo" email. The address it proves control of is the address the account is
recovered through, so the code is worth exactly as much as the account.

The sibling `PasswordResetToken` in the same file has carried `expires_at` + `is_expired()`
from the day it was written, with a docstring calling out its 15-minute life. The pattern was
already here. Verification simply never adopted it, and no test asked.

WHY THESE ASSERTIONS. A TTL is trivially satisfiable in a way that helps nobody, so each test
below pins a property that a plausible-looking fix could still get wrong:

  * expiry is measured from the ROW, not from "now minus a constant" applied to a query;
  * the expired answer is DISTINGUISHABLE from the invalid one, because only one of them has
    "resend" as its way out, and the screen used to tell them apart by comparing English;
  * an expired code does not survive its own rejection, or `last()` keeps handing it back;
  * a fresh code still works, which is the assertion that stops a TTL of zero from passing.
"""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient

from users.constants import ALREADY_VERIFIED, PRODUCER, VERIFICATION_CODE_EXPIRED, VERIFICATION_CODE_INVALID
from users.models import User, VerificationCode

# Resolved, not typed: the router owns the path, and a hard-coded literal here would answer
# 404 after any prefix change while every assertion below still "passed".
VERIFY_URL = reverse("user-verify-email")
RESEND_URL = reverse("user-resend-verification-email")


def _age(code, minutes):
    """Backdate a row. `created_at` is auto_now_add, so it cannot be set on create()."""
    VerificationCode.objects.filter(pk=code.pk).update(created_at=timezone.now() - timedelta(minutes=minutes))
    code.refresh_from_db()
    return code


class VerificationCodeExpiryModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="expiry-model@example.com", password="Str0ng!Passw0rd", user_type=PRODUCER
        )
        # The post_save signal already made one; work with that row rather than a second,
        # because `unique_together = (user, code)` makes a duplicate a silent trap.
        self.code = self.user.verification_code.last()
        self.assertIsNotNone(self.code, "signup did not create a verification code")

    @override_settings(EMAIL_VERIFICATION_CODE_TTL_MINUTES=1440)
    def test_a_fresh_code_is_not_expired(self):
        self.assertFalse(self.code.is_expired())

    @override_settings(EMAIL_VERIFICATION_CODE_TTL_MINUTES=1440)
    def test_expiry_is_measured_from_created_at(self):
        """The column that was dead is the one that now decides."""
        _age(self.code, minutes=1439)
        self.assertFalse(self.code.is_expired(), "a code one minute inside the TTL was rejected")

        _age(self.code, minutes=1441)
        self.assertTrue(self.code.is_expired(), "a code one minute past the TTL was accepted")

    @override_settings(EMAIL_VERIFICATION_CODE_TTL_MINUTES=60)
    def test_the_ttl_setting_is_actually_read(self):
        """Guards against the lifetime being hard-coded next to the setting that names it."""
        _age(self.code, minutes=120)
        self.assertTrue(self.code.is_expired())
        self.assertEqual(self.code.expires_at, self.code.created_at + timedelta(minutes=60))

    def test_an_unsaved_row_does_not_explode(self):
        """`created_at` is None before the first save; a caller checking eagerly must not crash."""
        self.assertFalse(VerificationCode(user=self.user, code="ABC123").is_expired())


class VerifyEmailExpiryEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="expiry-view@example.com", password="Str0ng!Passw0rd", user_type=PRODUCER
        )
        self.code = self.user.verification_code.last()

    @override_settings(EMAIL_VERIFICATION_CODE_TTL_MINUTES=1440)
    def test_a_fresh_code_still_verifies(self):
        """Non-vacuity: a TTL of zero would make every rejection below pass for nothing."""
        response = self.client.post(VERIFY_URL, {"email": self.user.email, "code": self.code.code}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_verified)
        self.assertTrue(self.user.is_active)

    @override_settings(EMAIL_VERIFICATION_CODE_TTL_MINUTES=1440)
    def test_an_expired_code_is_refused(self):
        _age(self.code, minutes=1441)
        response = self.client.post(VERIFY_URL, {"email": self.user.email, "code": self.code.code}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_verified, "an expired code verified the account anyway")

    @override_settings(EMAIL_VERIFICATION_CODE_TTL_MINUTES=1440)
    def test_expired_is_told_apart_from_invalid(self):
        """The screen picks the RECOVERY off this code; conflating the two removes the resend.

        Seeing `verification_code_expired` requires already holding a code that matched, so
        the distinction leaks nothing an attacker did not have.
        """
        _age(self.code, minutes=1441)
        expired = self.client.post(VERIFY_URL, {"email": self.user.email, "code": self.code.code}, format="json")
        self.assertEqual(expired.data.get("code"), VERIFICATION_CODE_EXPIRED)

        wrong = self.client.post(VERIFY_URL, {"email": self.user.email, "code": "ZZZZZZ"}, format="json")
        self.assertEqual(wrong.data.get("code"), VERIFICATION_CODE_INVALID)

    @override_settings(EMAIL_VERIFICATION_CODE_TTL_MINUTES=1440)
    def test_an_expired_code_is_deleted_on_rejection(self):
        """Otherwise `last()` keeps returning a dead row and resend is the only way out."""
        _age(self.code, minutes=1441)
        self.client.post(VERIFY_URL, {"email": self.user.email, "code": self.code.code}, format="json")
        self.assertEqual(self.user.verification_code.count(), 0)

    @override_settings(EMAIL_VERIFICATION_CODE_TTL_MINUTES=1440)
    def test_resend_issues_a_code_that_works_after_expiry(self):
        """The documented way out has to actually be a way out."""
        _age(self.code, minutes=1441)
        self.client.post(VERIFY_URL, {"email": self.user.email, "code": self.code.code}, format="json")

        resend = self.client.post(RESEND_URL, {"email": self.user.email}, format="json")
        self.assertEqual(resend.status_code, status.HTTP_200_OK, resend.data)

        fresh = self.user.verification_code.last()
        self.assertIsNotNone(fresh, "resend did not issue a new code")
        self.assertFalse(fresh.is_expired())

        verified = self.client.post(VERIFY_URL, {"email": self.user.email, "code": fresh.code}, format="json")
        self.assertEqual(verified.status_code, status.HTTP_200_OK, verified.data)

    def test_an_unknown_email_is_indistinguishable_from_a_wrong_code(self):
        """Pre-existing anti-enumeration behaviour, re-asserted now that a `code` is on the wire.

        The new field is a place a membership oracle could reappear: answering an unknown
        address with anything other than `verification_code_invalid` would leak.
        """
        response = self.client.post(VERIFY_URL, {"email": "nobody@example.com", "code": "ZZZZZZ"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), VERIFICATION_CODE_INVALID)

    def test_an_already_verified_user_is_named_by_code(self):
        """The screen treats this as SUCCESS; it used to detect it by comparing English."""
        self.user.is_verified = True
        self.user.save(update_fields=["is_verified"])
        response = self.client.post(VERIFY_URL, {"email": self.user.email, "code": self.code.code}, format="json")
        self.assertEqual(response.data.get("code"), ALREADY_VERIFIED)
