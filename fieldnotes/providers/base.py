"""The provider seam.

Twilio's sandbox is what ships first, because it needs no Meta Business verification and gives a
working inbound number in minutes. Meta Cloud API is the permanent number later. This module exists
so that migration is a new file in this package rather than a hunt through the app.

THE SEAM RULE: no Twilio or Meta field name appears outside this package. A `grep "MessageSid"`
anywhere else in `fieldnotes/` is a violation, and a test asserts it. Everything above this package
sees only `InboundMessage`.

WHAT META NEEDS DIFFERENTLY, written down so the migration has a destination:
  * Signature is `X-Hub-Signature-256`, HMAC-SHA256 over the RAW BODY with the app secret, rather
    than Twilio's SHA1 over the URL plus sorted params.
  * A GET handshake (`hub.mode` / `hub.verify_token` / `hub.challenge`) must be answered once when
    the webhook is registered. `handshake()` exists for that and Twilio's adapter returns None.
  * Media arrives as an ID, not a URL: `GET /{media-id}` returns a URL valid for FIVE MINUTES, and
    downloading it needs the bearer token. The media ID itself lives 7 days. Voice notes are OGG,
    capped at 16 MB.
  * The payload is JSON with an envelope (`entry[].changes[].value.messages[]`) and can carry
    several messages, plus status callbacks that are not messages at all.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InboundMessage:
    """One message, in terms this app understands.

    Carries NO company and NO establishment. Where a message may be filed is decided by the
    roster lookup against a signature-verified sender, never by anything inside the payload. A
    company id read out of a message body would be the cross-tenant write this whole design closes.
    """

    provider: str
    provider_message_id: str
    from_e164: str
    kind: str  # "text" | "voice"
    body_text: str = ""
    media_ref: str = ""
    media_content_type: str = ""
    profile_name: str = ""
    raw: dict = field(default_factory=dict)


class InboundAdapter:
    """What every provider must answer. Not an ABC: these are plain classes with class methods."""

    slug = ""

    @classmethod
    def verify(cls, request, params):
        """True only if this request really came from the provider. Must FAIL CLOSED."""
        raise NotImplementedError

    @classmethod
    def parse(cls, request, params):
        """An `InboundMessage`, or None when the payload carries no message we handle."""
        raise NotImplementedError

    @classmethod
    def handshake(cls, request):
        """An HttpResponse for a provider's GET verification, or None if it has none."""
        return None
