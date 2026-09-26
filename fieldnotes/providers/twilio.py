"""Twilio WhatsApp, verified with the standard library.

Deliberately NOT the `twilio` SDK. It is not a dependency of this project, the
`requirements-in-sync` CI job is blocking so adding one is a two-file change, and the scheme is
nine lines: base64(HMAC-SHA1(url + "".join(k + v for k, v in sorted(params)), auth_token)).
Stripe's is worth delegating because it is timestamped and versioned. This one is not.

The HMAC precedent in this repo is `backend/security/qr_security.py:134-136`, which also uses
`hmac.compare_digest` for the comparison. Do the same: a `==` on a signature is a timing oracle.
"""

import base64
import hashlib
import hmac
import logging

from django.conf import settings

from fieldnotes.providers.base import InboundAdapter, InboundMessage
from fieldnotes.services.phone import normalise_phone

logger = logging.getLogger(__name__)

# Twilio sends WhatsApp addresses as "whatsapp:+14155551234".
_WHATSAPP_PREFIX = "whatsapp:"


class TwilioWhatsAppAdapter(InboundAdapter):
    slug = "twilio"

    @classmethod
    def _signing_url(cls, request):
        """The URL Twilio signed.

        NOTE: THE MOST LIKELY "works locally, 403s in production" FAILURE. Twilio HMACs the exact URL
        it called. Behind a TLS terminator `build_absolute_uri()` only reconstructs `https://`
        because `SECURE_PROXY_SSL_HEADER` is set, and `USE_X_FORWARDED_HOST` is set NOWHERE in this
        project, so a platform that rewrites `Host` breaks verification with no clue on screen.
        `FIELD_NOTES_WEBHOOK_URL` makes that one configurable failure instead of one mysterious one.
        """
        configured = getattr(settings, "FIELD_NOTES_WEBHOOK_URL", "")
        if configured:
            return configured.rstrip("/") + "/" if configured.endswith("/") else configured
        return request.build_absolute_uri()

    @classmethod
    def verify(cls, request, params):
        token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
        if not token:
            # FAIL CLOSED. An unset secret must never mean "accept everything"; that would turn a
            # misconfigured deploy into an open write endpoint on a farm's records.
            logger.error("field-notes inbound refused: TWILIO_AUTH_TOKEN is not configured")
            return False

        sent = request.headers.get("X-Twilio-Signature", "")
        if not sent:
            return False

        url = cls._signing_url(request)
        payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
        digest = hmac.new(token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
        expected = base64.b64encode(digest).decode("ascii")

        if not hmac.compare_digest(expected, sent):
            # The URL, never the signature: knowing which URL was signed is the whole diagnosis,
            # and logging a signature would put a credential-shaped string in the log store.
            logger.warning("field-notes inbound signature mismatch (signed against %s)", url)
            return False
        return True

    @classmethod
    def parse(cls, request, params):
        message_id = params.get("MessageSid", "")
        sender = params.get("From", "")
        if not message_id or not sender:
            return None

        from_e164 = normalise_phone(sender.replace(_WHATSAPP_PREFIX, ""))
        if not from_e164:
            return None

        media_count = params.get("NumMedia", "0")
        try:
            has_media = int(media_count) > 0
        except (TypeError, ValueError):
            has_media = False

        content_type = params.get("MediaContentType0", "") if has_media else ""
        is_voice = has_media and content_type.startswith("audio")

        return InboundMessage(
            provider=cls.slug,
            provider_message_id=message_id,
            from_e164=from_e164,
            kind="voice" if is_voice else "text",
            body_text=(params.get("Body") or "").strip(),
            media_ref=params.get("MediaUrl0", "") if has_media else "",
            media_content_type=content_type,
            profile_name=(params.get("ProfileName") or "").strip(),
            raw=dict(params),
        )
