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
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from backend.permissions import ReadOnlyForViewersGlobal
from fieldnotes.models import CrewSender, FieldNote
from fieldnotes.permissions import MayWriteCrewSender
from fieldnotes.providers.registry import adapter_for
from fieldnotes.serializers import CrewSenderSerializer, FieldNoteSerializer
from fieldnotes.services.arrival import notify_field_note_arrived
from fieldnotes.services.intake import dispatch as dispatch_transcription
from fieldnotes.services.retention import release_note_audio
from fieldnotes.services.transcribe import TranscriptionRefused, stream_media

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

    # BOUND THE ID BEFORE IT IS USED FOR ANYTHING, so the duplicate check and the write agree on
    # one string. Truncating at the create alone would have the check ask about the raw value and
    # the constraint hold the cut one, so a redelivery would look new and then collide.
    #
    # Same reason as the display name below: an unbounded payload value reaching a CharField is a
    # DataError, which is a 500, which makes the provider retry. Lower risk here and bounded
    # anyway: `MessageSid` is generated by Twilio (34 characters) rather than typed by the sender,
    # and it only arrives after the signature has been verified, so producing an over-long one
    # needs the account's auth token. The display name is the opposite, picked by the crew member
    # and forwarded inside a perfectly valid signed request. Bounded regardless, because "this
    # provider field is short today" is the assumption the display-name incident falsified.
    id_limit = FieldNote._meta.get_field("provider_message_id").max_length
    message_id = message.provider_message_id[:id_limit]

    if FieldNote.objects.filter(provider=message.provider, provider_message_id=message_id).exists():
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

    # A VOICE NOTE IS NOW ACCEPTED, and held as TRANSCRIBING until it has words.
    #
    # It used to be refused outright with `voice_not_enabled`, because storing audio meant a
    # `FileField` on a bucket whose policy grants public `s3:GetObject`. That premise was wrong: the
    # provider already keeps the recording behind HTTP Basic auth and offers a delete endpoint, so
    # Trazo holds a REFERENCE, proxies playback through an authenticated view, and deletes the file at
    # the provider on confirm or discard. The bytes never enter Trazo's own storage.
    #
    # A voice note with no media reference is the one case still refused here: there is nothing to
    # fetch, so the job would have nothing to do and the note would sit on "being read" forever.
    refusal = ""
    if message.kind == FieldNote.VOICE and not message.media_ref:
        refusal = "media_unavailable"
    elif message.kind == FieldNote.TEXT and not message.body_text.strip():
        # A photo or a document with no caption arrives here as a text message with an empty body,
        # because only audio is classified as voice. Calling that "empty_message" told the supervisor
        # the crew sent nothing, when they sent a picture of the block. Name what actually happened,
        # so the supervisor asks for the right thing.
        refusal = "unsupported_media" if message.media_ref else "empty_message"

    if refusal:
        status_at_rest = FieldNote.REFUSED
    elif message.kind == FieldNote.VOICE:
        status_at_rest = FieldNote.TRANSCRIBING
    else:
        status_at_rest = FieldNote.PENDING

    try:
        with transaction.atomic():
            note = FieldNote.objects.create(
                company=sender.company,
                # Not `sender.establishment` directly: a roster row may name a farm belonging to
                # another operation, and copying that through would put one company's note against
                # another company's farm. `filing_establishment` refuses and logs instead.
                establishment=sender.filing_establishment,
                sender=sender,
                sender_phone=message.from_e164,
                sender_display_name=display_name,
                provider=message.provider,
                provider_message_id=message_id,
                kind=message.kind,
                body_text=message.body_text,
                # Where the audio is, never the audio. See the column's own comment.
                provider_media_ref=message.media_ref or "",
                media_content_type=message.media_content_type or "",
                status=status_at_rest,
                refusal_reason=refusal,
            )
            CrewSender.objects.filter(pk=sender.pk).update(last_note_at=timezone.now())

            # ON COMMIT, not here. The duplicate-delivery path below raises IntegrityError and rolls
            # this transaction back, and a ping for a row that never existed is a lie. `on_commit`
            # also means the notification cannot slow the response the provider is waiting on.
            #
            # `notify_field_note_arrived` swallows its own exceptions, and that is load-bearing
            # rather than lazy: this is an anonymous webhook, an uncaught exception is a 500, and a
            # 500 makes the provider redeliver a message that was already stored.
            # A note still being read is NOT announced yet: a ping now would send a supervisor to
            # read words that do not exist. `intake.dispatch` announces it when the transcript lands,
            # and announces the refusal if it cannot be read. Everything else pings here.
            if status_at_rest == FieldNote.TRANSCRIBING:
                dispatch_transcription(note)
            else:
                transaction.on_commit(lambda: notify_field_note_arrived(note))
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
            # VALIDATED, not passed through. `.filter(establishment_id="abc")` raises ValueError
            # while the queryset is being BUILT, which is uncaught, which is a 500 on a value a
            # caller types into the address bar. Exactly the shape `?field_note=not-a-uuid` had.
            # The `?status=` check right above already answers 400 for a bad value; this one was
            # the odd surface out.
            try:
                establishment_id = int(establishment)
            except (TypeError, ValueError):
                return Response(
                    {"error": "establishment must be a number.", "got": establishment[:40]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(establishment_id=establishment_id)
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
        # The recording has done its job the moment somebody decides this is not an event.
        release_note_audio(note)
        return Response(self.get_serializer(note).data)

    @action(detail=True, methods=["get"])
    def audio(self, request, public_id=None):
        """Play the voice note, proxied, with the bytes never entering Trazo's storage.

        THIS VIEW IS THE REASON THE AUDIO CAN BE KEPT AT ALL. The plan wants a supervisor to be able
        to LISTEN, because ASR dropping a negation ("I applied nothing in block 4") is undetectable by
        anyone who was not the speaker, and on this channel the speaker is never the person who
        confirms. The obvious way to offer that is to copy the file into Trazo, which would publish it:
        the bucket policy on `trazo-media` grants public `s3:GetObject` with `AWS_QUERYSTRING_AUTH =
        False`. So the file stays at the provider, behind its Basic auth, and this view streams it to a
        caller the viewset has already scoped to their own companies.

        Deliberately NOT a redirect to the provider URL. A 302 would hand the browser a URL that
        carries no Trazo authorisation, and anyone it was forwarded to could fetch it.
        """
        note = self.get_object()
        if note.kind != FieldNote.VOICE:
            return Response({"error": "This note is not a voice note."}, status=status.HTTP_404_NOT_FOUND)
        if note.audio_deleted_at or not note.provider_media_ref:
            # A deleted recording is gone on purpose, and saying so is better than a bare 404: the
            # supervisor is looking at a transcript and needs to know why there is nothing to play.
            return Response(
                {"error": "The recording for this note has been deleted.", "deleted_at": note.audio_deleted_at},
                status=status.HTTP_410_GONE,
            )

        try:
            upstream = stream_media(note.provider_media_ref)
        except TranscriptionRefused:
            return Response({"error": "The recording could not be fetched."}, status=status.HTTP_502_BAD_GATEWAY)

        response = StreamingHttpResponse(
            upstream.iter_content(chunk_size=8192),
            content_type=note.media_content_type or "audio/ogg",
        )
        # No caching intermediary should hold a crew member's voice note.
        response["Cache-Control"] = "private, no-store"
        return response


class CrewSenderViewSet(viewsets.ModelViewSet):
    """The roster: which numbers may file notes, and against which farm.

    THE REASON THIS EXISTS. The webhook shipped before any roster API, so the only way to register a
    number was `manage.py shell` and later a staff-only Django admin page. `fieldnotes/admin.py` says
    as much and calls itself a stopgap. Meanwhile the inbox's own empty state told a first-time user
    that messages would appear here when someone on their crew sent one, which no grower could make
    happen: the channel was reachable and unusable at the same time.

    DEACTIVATE RATHER THAN DELETE, which is why `destroy` is overridden below. A roster row is the
    provenance of every note it ever accepted: `FieldNote.sender` is SET_NULL, so deleting the row
    leaves the notes standing with the denormalised phone and display name and no roster entry
    explaining where they came from. `is_active=False` stops the number at the webhook
    (`CrewSender.objects.may_send()`) and keeps the trail.
    """

    serializer_class = CrewSenderSerializer
    # `ReadOnlyForViewersGlobal` is the cheap outer gate (no elevated role anywhere, no writes at
    # all). `MayWriteCrewSender` is the one that matters: CA or FM in the company of the row being
    # changed. Both, because the global one asks a question that is not the question, and `destroy`
    # never reaches the serializer where the create-path check lives.
    permission_classes = [IsAuthenticated, ReadOnlyForViewersGlobal, MayWriteCrewSender]

    def get_queryset(self):
        """Every roster row in the caller's own companies.

        Same shape as the inbox's scope, and for the same reason: this viewset has no company in its
        URL, so nothing in the routing layer can apply tenancy and it has to be done here.
        """
        user = self.request.user
        if not user.is_authenticated:
            return CrewSender.objects.none()
        queryset = CrewSender.objects.select_related("company", "establishment").order_by(
            "-is_active", "display_name", "phone_e164"
        )
        if user.is_superuser:
            return queryset
        return queryset.filter(company__in=user.companies.all())

    def list(self, request, *args, **kwargs):
        """Optionally narrowed to one farm, with the filter VALIDATED rather than passed through.

        Same shape as `FieldNoteViewSet.list`: `.filter(establishment_id="abc")` raises ValueError
        while the queryset is evaluated, which is an uncaught 500 on a hand-edited query string.
        """
        queryset = self.get_queryset()

        # NARROWED TO ONE COMPANY when asked, and the client always asks.
        #
        # `get_queryset` scopes to every company the caller belongs to, which is right for "may this
        # person see this row" and wrong for a page that shows one company's roster under one
        # company's heading: a desk serving several growers saw all of their numbers mixed together,
        # with no column saying which grower each belonged to. Filtering here also gives the client a
        # cache key that changes when the active company does, which is what stops a company switch
        # from being served the previous company's list.
        company = request.query_params.get("company")
        if company:
            try:
                company_id = int(company)
            except (TypeError, ValueError):
                return Response(
                    {"error": "company must be a number.", "got": company[:40]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Intersected with the caller's own scope, never substituted for it.
            queryset = queryset.filter(company_id=company_id)

        establishment = request.query_params.get("establishment")
        if establishment:
            try:
                establishment_id = int(establishment)
            except (TypeError, ValueError):
                return Response(
                    {"error": "establishment must be a number.", "got": establishment[:40]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(establishment_id=establishment_id)
        return Response(self.get_serializer(queryset, many=True).data)

    def destroy(self, request, *args, **kwargs):
        """Deactivate. The row and its trail are kept.

        Answers 200 with the updated row rather than 204, because the caller needs the new state to
        render, and because a 204 would read as "it is gone" when it is not.
        """
        sender = self.get_object()
        if sender.is_active:
            sender.is_active = False
            sender.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(sender).data)
