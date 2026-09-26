"""The inbound webhook.

POSTURE, AND WHY IT IS COPIED FROM `stripe_webhook` (subscriptions/views.py:1301)
---------------------------------------------------------------------------------
A plain Django function view with `@csrf_exempt`, deliberately NOT DRF, for that view's stated
reasons: DRF authentication would 401 a caller whose whole credential is a signature, DRF throttling
is session-scoped and meaningless for a vendor IP, and `request.data` would consume the body that
verification has to read for itself.

WHAT THIS ENDPOINT PUBLISHES: NOTHING. The response body is always empty. That is the claim-safety
argument that gets it onto the reviewed anonymous surface: a stranger with the URL can read no PII,
no geodata and no claim. Do not answer with TwiML or any acknowledgement text. The ack is
conditional on review work that has not happened yet, so it does not belong in this response.

WHAT IT WRITES: one `FieldNote` in `pending`, and only for a number on an active, consent-attested
roster row. Nothing else, and nothing network-bound. A provider's inbound webhook has a short
timeout (Twilio's is about 15 seconds and it retries once), so any slow work belongs in a job.
"""

import logging

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from fieldnotes.models import CrewSender, FieldNote
from fieldnotes.providers.registry import adapter_for

logger = logging.getLogger(__name__)

# Commands a sender can use to stop, in the languages the roster serves. Handled before anything
# else so a person can always leave, even mid-conversation.
STOP_WORDS = {"stop", "alto", "parar", "baja", "sair"}


def _tail(phone):
    """Last four digits, for logs.

    Never log a full inbound phone number. Arbitrary numbers written to a log store are a PII
    collection sitting outside every retention control this codebase has, created by the one
    endpoint a stranger can reach. Four digits are enough to recognise a number you already know,
    which is the only diagnosis this log has to support.
    """
    return (phone or "")[-4:]


@csrf_exempt
@require_http_methods(["GET", "POST"])
def inbound_message_webhook(request, provider):
    """Receive one message from a provider. Always answers with an empty body."""
    adapter = adapter_for(provider)  # 404 on a provider we do not serve

    if request.method == "GET":
        handshake = adapter.handshake(request)
        return handshake if handshake is not None else HttpResponse(status=405)

    # Read the form ONCE and hand the same dict to both verify and parse, so the two can never
    # disagree about what was signed.
    params = request.POST.dict()

    if not adapter.verify(request, params):
        # 400, exactly as the Stripe precedent answers a bad signature. Fails closed: an unset
        # secret makes `verify` return False rather than waving the request through.
        return HttpResponse(status=400)

    message = adapter.parse(request, params)
    if message is None:
        # A delivery with no message we handle (a status callback, an unparseable sender). Permanent
        # for this payload, so 200: a retry would produce the same nothing.
        return HttpResponse(status=200)

    if message.body_text.strip().lower() in STOP_WORDS:
        CrewSender.objects.filter(phone_e164=message.from_e164, is_active=True).update(
            is_active=False, updated_at=timezone.now()
        )
        logger.info("field-notes: STOP honoured for a number ending %s", _tail(message.from_e164))
        return HttpResponse(status=200)

    senders = list(
        CrewSender.objects.filter(phone_e164=message.from_e164, is_active=True)
        .exclude(consent_attested_at__isnull=True)
        .select_related("company", "establishment")
    )

    if not senders:
        # 200 AND SILENCE. Replying "you are not authorised" would confirm to a stranger that the
        # number is a live Trazo line, and would turn this endpoint into a way to send messages to
        # any number that reached it. The operator diagnoses a typo on the roster page, which shows
        # "no notes yet" beside the number they just added.
        logger.warning("field-notes: message from an unrostered number ending %s", _tail(message.from_e164))
        return HttpResponse(status=200)

    if len(senders) > 1:
        # REFUSE TO GUESS. `.first()` here would be a routing decision about a compliance record,
        # made by software, on the basis of heap order. And telling either company would disclose to
        # company A that its crew also works for company B. The roster is unique per company on
        # purpose (packing houses and custom crews serve several growers), so this state is
        # reachable and it is a known limitation rather than a bug: the fix is a per-company join
        # keyword, which is also how a real provider onboarding already works.
        logger.error(
            "field-notes: number ending %s is rostered by %d companies; refusing to route",
            _tail(message.from_e164),
            len(senders),
        )
        return HttpResponse(status=200)

    sender = senders[0]

    if FieldNote.objects.filter(provider=message.provider, provider_message_id=message.provider_message_id).exists():
        return HttpResponse(status=200)

    # A voice note before the private audio store and the ASR metering exist. Recorded as REFUSED
    # rather than dropped, because the fact that somebody tried to file something is itself a
    # record-keeping fact, and the supervisor can then ask them to type it.
    refusal = "" if message.kind == FieldNote.TEXT else "voice_not_enabled"
    if message.kind == FieldNote.TEXT and not message.body_text.strip():
        refusal = "empty_message"

    try:
        with transaction.atomic():
            FieldNote.objects.create(
                company=sender.company,
                establishment=sender.establishment,
                sender=sender,
                sender_phone=message.from_e164,
                sender_display_name=sender.display_name or message.profile_name,
                provider=message.provider,
                provider_message_id=message.provider_message_id,
                kind=message.kind,
                body_text=message.body_text,
                status=FieldNote.PENDING if not refusal else FieldNote.REFUSED,
                refusal_reason=refusal,
            )
            CrewSender.objects.filter(pk=sender.pk).update(last_note_at=timezone.now())
    except IntegrityError:
        # A concurrent duplicate delivery lost the race on the unique constraint.
        #
        # NOTE: 200 here, where `stripe_webhook` returns 500 to invite a retry, and the difference is
        # deliberate. There the constraint is on a side table, so losing the race says nothing about
        # whether the work happened. Here it is on the OUTCOME row, so losing the race proves the
        # note exists: the work IS done and a redelivery would achieve nothing. Do not "fix" this
        # back to 500.
        return HttpResponse(status=200)

    return HttpResponse(status=200)
