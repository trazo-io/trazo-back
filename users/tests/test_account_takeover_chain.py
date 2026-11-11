"""
A borrowed session cannot become permanent control of the account (overall review 2026-11,
OV-SEC-C03, reproduced against the API).

Before 2026-11-11:
- `PATCH /api/users/<id>/ {"email": ...}` changed the login email with no password, no
  re-verification and no notice to either address; the old address could no longer sign in.
- a password reset left every other session alive: the old session's `/me` and token refresh
  both still answered 200.

So someone holding a session (an unlocked laptop at the packing shed, a shared tablet) could move
the account to their own mailbox and keep it. Each test below drives the real endpoints with one
token pair per "browser".
"""

import re
from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.constants import PRODUCER
from users.models import EmailChangeRequest, PasswordResetToken, User

PASSWORD = "Blueberry#2026x"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountTakeoverChainTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="grower@calapooia.example",
            password=PASSWORD,
            first_name="Laurel",
            user_type=PRODUCER,
            is_active=True,
            is_verified=True,
        )
        # Issued a few seconds ago, like any session already open in another browser.
        self.other_browser = self._session(issued_seconds_ago=5)
        mail.outbox = []  # creating the account sends its own welcome mail

    def _session(self, issued_seconds_ago=0):
        refresh = RefreshToken.for_user(self.user)
        if issued_seconds_ago:
            backdated = int((timezone.now() - timedelta(seconds=issued_seconds_ago)).timestamp())
            refresh["iat"] = backdated
            access = refresh.access_token
            access["iat"] = backdated
        else:
            access = refresh.access_token
        return {"refresh": str(refresh), "access": str(access)}

    def _client(self, session):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {session['access']}")
        return client

    def _me_status(self, session):
        return self._client(session).get("/api/users/me/").status_code

    def _refresh_status(self, session):
        client = APIClient()
        client.cookies["refresh"] = session["refresh"]
        return client.post("/api/auth/refresh/").status_code

    # ---- the email ----------------------------------------------------------------------------

    def test_a_profile_patch_cannot_change_the_login_email(self):
        response = self._client(self.other_browser).patch(
            f"/api/users/{self.user.pk}/", {"email": "attacker@elsewhere.example"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "grower@calapooia.example")

    def test_a_profile_patch_that_keeps_the_email_still_saves_the_name(self):
        # ProfileUser sends the email back unchanged with every save.
        response = self._client(self.other_browser).patch(
            f"/api/users/{self.user.pk}/",
            {"email": "grower@calapooia.example", "first_name": "Laurel B."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Laurel B.")

    def test_another_account_cannot_touch_this_one(self):
        # The outsider proof for UserViewSet in backend/route_tenancy.py: an account from another
        # company sees this row as missing and cannot change it.
        outsider = User.objects.create_user(
            email="outsider@elsewhere.example", password=PASSWORD, is_active=True, user_type=PRODUCER
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(outsider).access_token}")
        self.assertEqual(client.get(f"/api/users/{self.user.pk}/").status_code, 404)
        response = client.patch(f"/api/users/{self.user.pk}/", {"first_name": "Mallory"}, format="json")
        self.assertEqual(response.status_code, 404)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Laurel")

    def test_requesting_a_change_needs_the_password(self):
        response = self._client(self.other_browser).post(
            "/api/users/request_email_change/",
            {"new_email": "attacker@elsewhere.example", "password": "a guess"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "wrong_password")
        self.assertFalse(EmailChangeRequest.objects.exists())
        self.assertEqual(mail.outbox, [])

    def _request_change(self, new_email="laurel@newfarm.example"):
        response = self._client(self.other_browser).post(
            "/api/users/request_email_change/",
            {"new_email": new_email, "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def _link_token(self, new_email):
        message = next(m for m in mail.outbox if m.to == [new_email])
        return re.search(r"confirm-email-change\?token=([\w-]+)", message.body).group(1)

    def test_the_new_address_gets_the_link_and_the_old_one_is_told(self):
        self._request_change()
        recipients = sorted(tuple(m.to) for m in mail.outbox)
        self.assertEqual(recipients, [("grower@calapooia.example",), ("laurel@newfarm.example",)])
        notice = next(m for m in mail.outbox if m.to == ["grower@calapooia.example"])
        self.assertIn("laurel@newfarm.example", notice.body)
        self.assertNotIn("confirm-email-change", notice.body)
        # Nothing changes until the link is opened, and only its hash is stored.
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "grower@calapooia.example")
        token = self._link_token("laurel@newfarm.example")
        self.assertFalse(EmailChangeRequest.objects.filter(token_hash=token).exists())

    def test_opening_the_link_changes_the_email_and_ends_every_session(self):
        self._request_change()
        token = self._link_token("laurel@newfarm.example")
        response = APIClient().post("/api/users/confirm_email_change/", {"token": token}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "laurel@newfarm.example")
        self.assertEqual(self._me_status(self.other_browser), 401)
        self.assertNotEqual(self._refresh_status(self.other_browser), 200)
        # The link works once.
        again = APIClient().post("/api/users/confirm_email_change/", {"token": token}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_an_address_another_account_uses_is_refused(self):
        User.objects.create_user(email="taken@farm.example", password=PASSWORD, is_active=True)
        response = self._client(self.other_browser).post(
            "/api/users/request_email_change/",
            {"new_email": "Taken@Farm.example", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "email_taken")

    # ---- the sessions -------------------------------------------------------------------------

    def test_a_password_reset_ends_every_other_session(self):
        self.assertEqual(self._me_status(self.other_browser), 200)
        PasswordResetToken.objects.create(
            user=self.user, token="reset-token-abc", expires_at=timezone.now() + timedelta(minutes=15)
        )
        response = APIClient().post(
            "/api/users/confirm_password_reset/",
            {"token": "reset-token-abc", "email": self.user.email, "new_password": "Walnut#Orchard2027"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self._me_status(self.other_browser), 401)
        self.assertNotEqual(self._refresh_status(self.other_browser), 200)

    def test_a_password_change_ends_sessions_in_other_browsers_too(self):
        this_browser = self._session(issued_seconds_ago=3)
        response = self._client(this_browser).post(
            "/api/users/change_password/",
            {"old_password": PASSWORD, "new_password": "Walnut#Orchard2027"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self._me_status(self.other_browser), 401)
        self.assertNotEqual(self._refresh_status(self.other_browser), 200)

    def test_a_password_change_cancels_a_pending_email_change(self):
        self._request_change()
        token = self._link_token("laurel@newfarm.example")
        self._client(self._session(issued_seconds_ago=3)).post(
            "/api/users/change_password/",
            {"old_password": PASSWORD, "new_password": "Walnut#Orchard2027"},
            format="json",
        )
        response = APIClient().post("/api/users/confirm_email_change/", {"token": token}, format="json")
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "grower@calapooia.example")

    def test_a_session_started_after_the_change_works(self):
        PasswordResetToken.objects.create(
            user=self.user, token="reset-token-xyz", expires_at=timezone.now() + timedelta(minutes=15)
        )
        APIClient().post(
            "/api/users/confirm_password_reset/",
            {"token": "reset-token-xyz", "email": self.user.email, "new_password": "Walnut#Orchard2027"},
            format="json",
        )
        # A sign-in a moment later (`iat` is whole seconds, the cutoff is not, so a token minted
        # in the very same second as the change is refused by design).
        User.objects.filter(pk=self.user.pk).update(credentials_changed_at=timezone.now() - timedelta(seconds=2))
        self.user.refresh_from_db()
        fresh = self._session()
        self.assertEqual(self._me_status(fresh), 200)

    def test_a_token_from_earlier_in_the_same_second_is_refused(self):
        # Review of #379: the cutoff used to be floored to the second, so this token passed.
        from types import SimpleNamespace

        from users.sessions import token_predates_credentials

        changed = timezone.now().replace(microsecond=700000)
        user = SimpleNamespace(credentials_changed_at=changed)
        self.assertTrue(token_predates_credentials(user, {"iat": int(changed.timestamp())}))
        self.assertFalse(token_predates_credentials(user, {"iat": int(changed.timestamp()) + 1}))
