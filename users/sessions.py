"""
Ending a user's sessions when the credentials change (overall review 2026-11, OV-SEC-C03).

Before 2026-11-11 a password reset left every other session alive: the review reset a password
and the old session's `/me` and token refresh both still answered 200. With the email change that
needed no password, a borrowed session could take the account and its five-year records for good.

A credential change (password changed, password reset, email change confirmed) does two things:

1. Stamps ``User.credentials_changed_at``. ``CustomAuthentication`` refuses an access token, and
   ``CustomTokenRefreshView`` a refresh token, issued (``iat``) before that second. This is what
   stops the 15-minute access tokens already in other browsers.
2. Blacklists every outstanding refresh token of the user, so no session can mint a new one.

The session that made the change ends too: the app sends the person to sign in again with the new
password or email, as the change-password form already did.
"""

from __future__ import annotations

from django.utils import timezone

SESSION_ENDED = "Your session ended because this account's password or email changed. Sign in again."


def token_predates_credentials(user, token) -> bool:
    """True when ``token`` was issued before the user's last credential change."""
    changed = getattr(user, "credentials_changed_at", None)
    if changed is None:
        return False
    try:
        issued = int(token["iat"])
    except (KeyError, TypeError, ValueError):
        # A token without an issue time cannot prove it is newer than the change.
        return True
    # Against the UNROUNDED change time (review of #379). `iat` is whole seconds; flooring the
    # cutoff too let a token issued earlier in the same second pass, and with refresh rotation one
    # such pass becomes access that never ends. The cost: a sign-in in the same second as the
    # change is refused once and works on the retry.
    return issued < changed.timestamp()


def end_sessions(user) -> None:
    """
    End every session of ``user``: stamp the change, cancel a pending email change and blacklist
    outstanding refresh tokens.
    """
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    from .models import EmailChangeRequest

    now = timezone.now()
    user.credentials_changed_at = now
    user.save(update_fields=["credentials_changed_at"])
    # A pending email change dies with the sessions: whoever asked for it knew the password, and
    # a password change is how the owner takes the account back.
    EmailChangeRequest.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
    outstanding = OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True)
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in outstanding], ignore_conflicts=True
    )
