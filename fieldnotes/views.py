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

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from backend.permissions import ReadOnlyForViewersGlobal
from fieldnotes.models import CrewSender, FieldNote
from fieldnotes.providers.registry import adapter_for
from fieldnotes.serializers import FieldNoteSerializer

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
        # Across EVERY company, deliberately. The person is asking to stop, not to stop for one of
        # the growers they work for, and they have no way to know how many rosters they are on.
        #
        # `stopped_at` is stamped as well as `is_active`, because those are different facts. Without
        # it, a supervisor re-ticking "active" on the roster page would silently re-enrol somebody
        # who had explicitly opted out, and nothing on the row would say so. `may_send()` reads
        # both, so re-activation alone cannot undo a STOP.
        stopped = CrewSender.objects.filter(phone_e164=message.from_e164).update(
            is_active=False, stopped_at=timezone.now(), updated_at=timezone.now()
        )
        logger.info(
            "field-notes: STOP honoured for a number ending %s (%d roster rows)",
            _tail(message.from_e164),
            stopped,
        )
        return HttpResponse(status=200)

    senders = list(
        CrewSender.objects.may_send().filter(phone_e164=message.from_e164).select_related("company", "establishment")
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
    # BOUND EVERY PAYLOAD VALUE THAT REACHES A CharField.
    #
    # MEASURED 2026-09-26: `ProfileName` is whatever the sender set as their WhatsApp display name,
    # and it went straight into a varchar(120). Postgres raised
    # `StringDataRightTruncation: value too long`, which is an uncaught DataError, which is a 500,
    # and a 500 makes the provider RETRY. So a display name of 400 characters was a retry loop that
    # anybody could start without even meaning to. Truncation is the right answer rather than a
    # refusal: this value is a label in an inbox list, not a fact about the farm.
    #
    # The limit is read off the column so the two cannot drift.
    name_limit = FieldNote._meta.get_field("sender_display_name").max_length
    display_name = (sender.display_name or message.profile_name)[:name_limit]

    refusal = "" if message.kind == FieldNote.TEXT else "voice_not_enabled"
    if message.kind == FieldNote.TEXT and not message.body_text.strip():
        # A photo or a document with no caption arrives here as a text message with an empty body,
        # because only audio is classified as voice. Calling that "empty_message" told the supervisor
        # the crew sent nothing, when they sent a picture of the block. Name what actually happened,
        # so the supervisor asks for the right thing.
        refusal = "unsupported_media" if message.media_ref else "empty_message"

    try:
        with transaction.atomic():
            FieldNote.objects.create(
                company=sender.company,
                # Not `sender.establishment` directly: a roster row may name a farm belonging to
                # another operation, and copying that through would put one company's note against
                # another company's farm. `filing_establishment` refuses and logs instead.
                establishment=sender.filing_establishment,
                sender=sender,
                sender_phone=message.from_e164,
                sender_display_name=display_name,
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


# ----------------------------------------------------------------------------------------------
# The inbox
# ----------------------------------------------------------------------------------------------


class FieldNoteViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read the queue, and discard from it. There is no create, update or delete, on purpose.

    Creating a note by hand would fabricate words attributed to a named crew member, and updating one
    would change what a person is recorded as having said. Both are the authorship problem this app
    exists to avoid, so the mixins that would allow them are simply not inherited.

    CONFIRMING IS NOT AN ACTION HERE. A note becomes a record through
    `EventViewSet.perform_create`, which is the only place an event is written and which forces
    `created_by = request.user`. This viewset never writes an event, and a guard test asserts that no
    module in this app so much as names one. The link between the record and the note it answers is
    written server-side inside that same request, mirroring `_fulfil_plan_item`.

    Deleting is refused too: that somebody tried to file something at 14:02 is itself a
    record-keeping fact, and a discarded note keeps a tombstone rather than disappearing.
    """

    serializer_class = FieldNoteSerializer
    permission_classes = [IsAuthenticated, ReadOnlyForViewersGlobal]
    lookup_field = "public_id"

    def get_queryset(self):
        """Scoped to the caller's own companies.

        The same membership test the event-create tenancy floor uses (`user.companies`). Stated
        rather than inherited because this viewset has no company in its URL, so
        `CompanyNestedViewSet` does not apply and nothing else would narrow it.
        """
        user = self.request.user
        if not user.is_authenticated:
            return FieldNote.objects.none()
        queryset = FieldNote.objects.select_related("company", "establishment", "sender")
        if user.is_superuser:
            return queryset
        return queryset.filter(company__in=user.companies.all())

    def get_queryset_for_status(self):
        return self.get_queryset()

    def list(self, request, *args, **kwargs):
        """Waiting notes by default; `?status=` for the rest.

        The default is the queue, because that is the question a supervisor opens this to answer.
        Refused and discarded notes stay reachable rather than hidden: a note that vanishes is worse
        than one that says why it could not be read.
        """
        queryset = self.filter_queryset(self.get_queryset())
        wanted = request.query_params.get("status", FieldNote.PENDING)
        if wanted != "all":
            valid = {choice for choice, _label in FieldNote.STATUS_CHOICES}
            if wanted not in valid:
                return Response(
                    {"error": f"Unknown status {wanted!r}.", "valid": sorted(valid) + ["all"]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(status=wanted)
        establishment = request.query_params.get("establishment")
        if establishment:
            queryset = queryset.filter(establishment_id=establishment)
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    @action(detail=True, methods=["post"])
    def discard(self, request, public_id=None):
        """Refuse a note without making a record of it.

        The row is KEPT. A crew member reported something and the operation decided it was not an
        event, and deleting the row would make "we never received it" and "we looked and said no"
        indistinguishable. Only the status changes, with who and why.
        """
        note = self.get_object()
        if note.status != FieldNote.PENDING:
            return Response(
                {"error": "Only a waiting note can be discarded.", "status": note.status},
                status=status.HTTP_409_CONFLICT,
            )
        note.status = FieldNote.DISCARDED
        note.discarded_by = request.user
        note.discarded_at = timezone.now()
        note.discard_reason = (request.data.get("reason") or "")[:200]
        note.save(update_fields=["status", "discarded_by", "discarded_at", "discard_reason", "updated_at"])
        return Response(self.get_serializer(note).data)
