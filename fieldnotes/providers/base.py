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


class OutboundAdapter:
    """Sending one message back to a crew member.

    WHY THIS EXISTS AT ALL, and why every message it sends is a REPLY.

    A crew member is not a Trazo user. They agreed to message their boss, and the operator attests
    to their consent on the roster page because this app cannot ask them directly. The one thing
    this product owes them in return is that the first time their words reach it, they are told so,
    in their own language, once. That notice is what `CrewSender.first_contact_at` was added for and
    it had no sender behind it.

    NO MESSAGE TEMPLATES ARE NEEDED FOR ANY OF IT, and the reason is worth writing down because the
    opposite was assumed. VERIFIED against Twilio's WhatsApp documentation, 2026-09-29: an inbound
    message opens a 24-hour customer service window, and inside that window "text and media
    messages require no templates and no WhatsApp approval". Every message this adapter sends is
    triggered BY an inbound message, so every one of them is inside the window by construction.
    Templates are only needed for business-INITIATED messages, and this app sends none.

    THE RULE THAT FOLLOWS FROM THAT: never send except in response to something the person just
    sent. A scheduled reminder, a digest or a nudge would be business-initiated, would need an
    approved template, and would also be a farm's software messaging a worker who never signed up
    for it. If one is ever wanted, it is a new decision and not an extension of this class.

    FAIL SOFT, ALWAYS. The one caller chain starts at an anonymous webhook, where an uncaught
    exception is a 500 and a 500 makes the provider redeliver. `send_text` returns a bool and
    raises nothing; losing a reply is recoverable, a retry storm is not. Same rule as
    `services/arrival.py`.
    """

    slug = ""

    @classmethod
    def unconfigured_reason(cls):
        """A short reason this provider cannot send right now, or "" when it can.

        Separate from `send_text` so a caller can decline BEFORE composing anything, and so the
        reason can be logged once at startup rather than per message.
        """
        raise NotImplementedError

    @classmethod
    def send_text(cls, to_e164, body):
        """True if the provider accepted the message. Never raises."""
        raise NotImplementedError

    @classmethod
    def channel_details(cls):
        """What a supervisor has to hand their crew, as a plain dict.

        `{"configured": bool, "number": str, "join_phrase": str}`.

        WHY THIS IS ON THE ADAPTER AND NOT READ FROM SETTINGS IN A VIEW. The seam rule at the top of
        this module says no provider field name appears outside this package, and the number and the
        join phrase are the most provider-specific facts in the whole feature: Meta has a permanent
        sender and no join step at all, so its adapter will answer this with an empty
        `join_phrase` and nothing above has to learn that.

        NEVER return `unconfigured_reason()` to a client. It names SETTING NAMES, which is the right
        detail for a log line and the wrong detail for a farmer looking at a roster page. The boolean
        is the part a person outside Trazo can act on.
        """
        raise NotImplementedError
