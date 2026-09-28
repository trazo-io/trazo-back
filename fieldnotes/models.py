"""A message from the block, held until a human turns it into a record.

WHAT THIS APP IS
----------------
A crew member sends a WhatsApp message. It arrives here and becomes a FieldNote waiting in an
inbox. A supervisor opens it, reads it, and confirms it through the activity wizard, which is where
the record is authored.

NOTHING IN THIS APP WRITES A RECORD. `EventViewSet.perform_create` (history/views.py) is the only
place an event is created, and `created_by` there is forced to `request.user`. That is not a style
preference: 7 CFR 205.201(a) makes the producer the author of the plan, and 205.103(b)(2) needs
records that survive an inspector's trace-back. A record a model wrote and a tired supervisor
rubber-stamped at 9pm is the backdated-template class of defect, one channel over.

THE COUNTER-PRECEDENT THIS APP MUST NOT BECOME. `IoTDeviceViewSet.pending_events`
(carbon/views.py) holds machine proposals on `IoTDataPoint` in almost exactly the shape below, and
then auto-approves some of them into `CarbonEntry` rows with no human in the loop. The shape is
borrowed here. The auto-approve is not, and a guard test asserts a pending note produces zero events
until the wizard POSTs.

WHY THE MESSAGE IS NOT THE RECORD
---------------------------------
WhatsApp keeps messages for about 30 days; NOP needs 5 years and WA pesticide records 7. That is not
a conflict, because the message was never the record. It is transport, exactly as speech is
transport in the in-app voice flow, which stores the transcript on the event and never keeps the
audio. So this app archives nothing.

WHY TEXT ONLY, FOR NOW
----------------------
Voice notes are the differentiated half and every hard risk lives there. Two of them decided this
ordering:

  * `prod.py:185-189` records that the bucket policy on `trazo-media` grants public `s3:GetObject`,
    and `AWS_QUERYSTRING_AUTH = False`. So ANY `FileField` on the default storage is a permanent
    unauthenticated public URL. Storing a crew member's voice note there would publish it, and the
    mistake is invisible in development because local storage is a filesystem. Audio needs a
    PRIVATE store that does not exist yet, so it is not modelled here rather than modelled wrongly.
  * Server-side transcription is unmetered today. `consume_voice_session` has exactly two callers,
    both in `carbon/views.py`, and neither is reachable from a background job, so ASR would be free
    on the one deployment shape where audio actually costs money.

A voice note that arrives before that work lands is REFUSED and the sender is told to type it, so
nothing is silently dropped. `kind` exists from the start for exactly that.

WHY NO SUGGESTION IS STORED
---------------------------
An earlier draft ran the extractor at capture time and stored the result. It is better not to.
At capture nobody has chosen an activity, so the parse runs with `known_activity=""` and
`requested_fields=None`. At confirm time the supervisor has picked, so the same extractor gets the
activity plus the form's real field list from the display registry and gives a strictly better
answer. Storing the worse one buys inbox chips and costs an OpenAI call per note, a column whose
shape invites exactly the `ProductionPlanItem.prefill` mistake, and a failure branch in a daemon
thread. The words are the product; the parse is an accelerator that the wizard already performs.
"""

import logging
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


class CrewSenderQuerySet(models.QuerySet):
    def may_send(self):
        """Rows allowed to file a note: active, and somebody attested the person was told.

        ONE expression of the rule. The webhook used to spell it inline as
        `.filter(is_active=True).exclude(consent_attested_at__isnull=True)` while the model spelled
        it again as a property, and two gates that must agree while spelling it differently is
        exactly how the event-create tenancy gate drifted from its read-path sibling. Both callers
        now go through here.
        """
        return self.filter(is_active=True, consent_attested_at__isnull=False, stopped_at__isnull=True)


class CrewSender(models.Model):
    """A phone number allowed to send notes to one company.

    An unregistered number is refused. Without this the webhook is the cross-tenant write that
    `_scope_parcels_to_caller` was added to close, re-opened on a channel anyone can reach: any
    phone in the world could put a practice record into a farm's certifier packet.
    """

    EN = "en-US"
    ES = "es-419"
    PT = "pt-BR"
    # Exactly the families `ai_voice_processor._PROMPT_KEY_BY_FAMILY` serves, spelled as the
    # app's own locale tags (es-419, never es-ES). A tag outside this set silently gets the ENGLISH
    # prompt, English keyword set and English numeral table, and returns plausible values, so the
    # failure reads as a bad note rather than a misconfiguration. A guard test pins the two sets
    # equal so adding a language here without a prompt fails loudly.
    LANGUAGE_CHOICES = [(EN, "English"), (ES, "Spanish"), (PT, "Portuguese")]

    company = models.ForeignKey("company.Company", on_delete=models.CASCADE, related_name="crew_senders")

    # Which farm this number's notes belong to. Optional: a single-farm company does not need the
    # question asked, and the supervisor picks the parcel at confirm time either way.
    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crew_senders",
    )

    phone_e164 = models.CharField(
        max_length=20,
        db_index=True,
        help_text="E.164, normalised by fieldnotes.services.phone.normalise_phone",
    )

    # What the supervisor calls this person, for the inbox list only.
    #
    # NEVER written to `performed_by`. The certifier packet prints that field as the applicator of
    # record, and shared handsets, recycled numbers and a mayordomo reporting for a twelve-person
    # crew all end with one name against everyone's work. `voiceFields.ts` already excludes
    # `performed_by` from voice for the same reason. Two rosters, never one.
    display_name = models.CharField(max_length=120, blank=True, default="")

    # Set only when the sender also happens to have a Trazo account. Used to LABEL a note.
    # Never to attribute a record: `perform_create` forces `created_by = request.user`, and the
    # person who confirms is the author. Crew have no accounts and `WorksIn` has no worker role;
    # do not invent one.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    language = models.CharField(max_length=8, choices=LANGUAGE_CHOICES, default=EN)

    is_active = models.BooleanField(default=True, db_index=True)

    # A STOP from the person themselves, which is a different fact from a supervisor deactivating
    # the row. Kept separate so that re-ticking "active" on a roster page cannot silently re-enrol
    # somebody who explicitly opted out; `may_send()` requires this to be null.
    stopped_at = models.DateTimeField(null=True, blank=True)

    # THE OPERATOR ATTESTS TO CONSENT, because this slice cannot ask for it.
    #
    # A crew member is not a Trazo user and agreed to message their boss, not a platform. The
    # automated first-contact notice needs outbound sending, which needs template approval outside
    # Twilio's sandbox, so it is not in this slice. Rather than process someone's words with nobody
    # having told them, the supervisor states that they did, and a number cannot go active without
    # it. That is the same shape as every other attestation in this product: a named, accountable
    # operator asserts a fact, and the timestamp records who and when.
    #
    # Not a checkbox that defaults to ticked, and not inferable. `activate()` refuses without it.
    consent_attested_at = models.DateTimeField(null=True, blank=True)
    consent_attested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    # When the first-contact notice was sent. A crew member is not a Trazo user and agreed to
    # message their boss, not a platform, so they are told once what happens to their words.
    first_contact_at = models.DateTimeField(null=True, blank=True)
    # The message AFTER the notice: an unambiguous "I read it and kept going".
    consented_at = models.DateTimeField(null=True, blank=True)
    # So the roster page can show "quiet for 5 days", which is the Twilio-sandbox-expiry tell.
    last_note_at = models.DateTimeField(null=True, blank=True)

    objects = CrewSenderQuerySet.as_manager()

    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fieldnotes_crew_sender"
        constraints = [
            # Per COMPANY, never globally unique. WA packing houses and custom harvest crews work
            # for several growers on one handset, so a global key would either refuse the second
            # grower who registered a number or route that crew's notes to whichever farm got there
            # first. Both are wrong by construction, and the mistake is invisible from the migration
            # because `unique=True` on the column reads like a tidy-up.
            models.UniqueConstraint(fields=["company", "phone_e164"], name="fieldnotes_sender_unique_per_company"),
        ]
        indexes = [models.Index(fields=["phone_e164", "is_active"], name="fieldnotes_sender_lookup")]

    def __str__(self):
        return f"{self.display_name or self.phone_e164} (company {self.company_id})"

    @property
    def may_send(self):
        """Active AND someone attested that this person was told. Both, or neither.

        Mirrors `CrewSenderQuerySet.may_send()` for a row already in hand. A guard test asserts the
        two agree on every combination, so the property cannot drift from the query the webhook runs.
        """
        return bool(self.is_active and self.consent_attested_at and not self.stopped_at)

    @property
    def filing_establishment(self):
        """The farm this number may file to, and only if it really belongs to this company.

        MEASURED 2026-09-26: nothing stopped a roster row pointing at another company's
        establishment, and the webhook copied it straight onto the note. That produced a note whose
        `company` was one operation and whose `establishment` belonged to a different one, which is
        the cross-tenant shape the whole roster exists to prevent, arriving through a
        misconfiguration rather than an attack.

        A database CHECK cannot express this (it spans two tables), and `full_clean` does not run on
        `objects.create`, so the gate has to be at the point of use. `clean()` below covers the
        roster form for when one exists; this covers the write that happens today.
        """
        establishment = self.establishment
        if establishment is None:
            return None
        if establishment.company_id != self.company_id:
            logger.error(
                "field-notes: CrewSender %s points at establishment %s owned by company %s, not %s; "
                "filing to the company only",
                self.pk,
                establishment.pk,
                establishment.company_id,
                self.company_id,
            )
            return None
        return establishment

    def clean(self):
        super().clean()
        if self.establishment_id and self.establishment.company_id != self.company_id:
            raise ValidationError({"establishment": "That farm belongs to a different operation."})


class FieldNote(models.Model):
    """One inbound message, held outside any record until a human confirms it."""

    # A voice note is TRANSCRIBING until it has words, and that is a different fact from waiting for
    # review: the inbox must not offer "Log this" on a note nobody can read yet, and a supervisor
    # looking at an empty queue deserves to know something is on its way rather than that nothing
    # arrived.
    TRANSCRIBING = "transcribing"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"
    REFUSED = "refused"
    STATUS_CHOICES = [
        (TRANSCRIBING, "Being read"),
        (PENDING, "Waiting for review"),
        (CONFIRMED, "Logged"),
        (DISCARDED, "Discarded"),
        (REFUSED, "Could not be accepted"),
    ]

    TEXT = "text"
    VOICE = "voice"
    KIND_CHOICES = [(TEXT, "Text"), (VOICE, "Voice note")]

    TWILIO = "twilio"
    META = "meta"
    PROVIDER_CHOICES = [(TWILIO, "Twilio"), (META, "Meta Cloud API")]

    # The only id that appears in a URL. An integer pk on something reachable by link is
    # enumerable, which is how two anonymous endpoints in this codebase leaked.
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)

    company = models.ForeignKey("company.Company", on_delete=models.CASCADE, related_name="field_notes")
    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="field_notes",
    )

    # SET_NULL, not CASCADE: removing someone from the roster must not delete the notes they already
    # sent. The denormalised columns below are what keep provenance readable after that.
    sender = models.ForeignKey(CrewSender, on_delete=models.SET_NULL, null=True, blank=True, related_name="notes")
    sender_phone = models.CharField(max_length=20)
    sender_display_name = models.CharField(max_length=120, blank=True, default="")

    # The seam. Twilio's sandbox ships first because it needs no Meta Business verification; Meta
    # Cloud API is the permanent number later. Signature verification and reply sending are
    # per-provider; nothing else in this app knows which provider it is talking to.
    provider = models.CharField(max_length=16, choices=PROVIDER_CHOICES, db_index=True)
    provider_message_id = models.CharField(max_length=255)

    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)

    # What the sender typed, verbatim. They wrote it, so it may be shown and it may print.
    body_text = models.TextField(blank=True, default="")

    # WHERE THE AUDIO IS, never the audio itself.
    #
    # Twilio enforces HTTP Basic auth on media URLs and keeps the file until it is deleted through
    # the API, so the recording already sits in a private store with a delete endpoint. Copying the
    # bytes into Trazo would move them to a PUBLIC one: the bucket policy on `trazo-media` grants
    # public `s3:GetObject` and `AWS_QUERYSTRING_AUTH = False`, so any `FileField` here would be a
    # permanent unauthenticated URL for a crew member's voice note, and local development would look
    # fine because dev storage is the filesystem.
    #
    # So this is a CharField holding the provider's own URL, playback is proxied through an
    # authenticated view, and confirm or discard deletes the file at the provider.
    provider_media_ref = models.CharField(max_length=500, blank=True, default="")
    media_content_type = models.CharField(max_length=80, blank=True, default="")

    # ASR OUTPUT, AND NOT THE SAME KIND OF THING AS `body_text`.
    #
    # `body_text` is what a person typed: they wrote it, so it may print. This is a machine's guess at
    # what somebody said, and the surface that shows it says so. It is a working aid for the human who
    # confirms, never testimony, and the wizard already refuses to republish a sender's sentence as
    # the grower's own observation.
    transcript = models.TextField(blank=True, default="")
    transcript_language = models.CharField(max_length=16, blank=True, default="")

    # Stamped when the audio is deleted at the provider, so "we removed it" and "it was never there"
    # stay different answers. The plan keeps audio only while a note is pending: once the record is
    # written or the note is discarded, the recording has done its job.
    audio_deleted_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    # A reason a farmer can read, not a stack trace. A refused note stays VISIBLE: the fact that
    # somebody tried to file something at 14:02 is itself a record-keeping fact, and a note that
    # vanishes is worse than one that says "we could not read this, ask Miguel to send it again".
    refusal_reason = models.CharField(max_length=64, blank=True, default="")

    # A loose (type, id) pair rather than an FK, because an event is one of eight concrete models
    # behind EVENT_TYPE_TO_MODEL. Same shape as `ProductionPlanItem.fulfilled_by_*` and
    # `EventAmendment`, and it carries the same consequence, which must be honoured rather than
    # rediscovered: nothing in the database maintains this link, so deleting the event has to
    # reopen the note explicitly, the way `EventViewSet.destroy` already reopens a plan item.
    # A note reading "confirmed" whose record is gone is an assertion with nothing behind it.
    fulfilled_by_event_type = models.PositiveSmallIntegerField(null=True, blank=True)
    fulfilled_by_id = models.PositiveIntegerField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    discarded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    discarded_at = models.DateTimeField(null=True, blank=True)
    discard_reason = models.CharField(max_length=200, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fieldnotes_field_note"
        ordering = ["-received_at"]
        constraints = [
            # THE IDEMPOTENCY GUARD, and deliberately on the OUTCOME row rather than in a side
            # table like `ProcessedWebhookEvent`. A provider retries for days and documents that
            # duplicates happen; two deliveries of one message would otherwise become two dated
            # applications in a certifier packet. Because the constraint is on the row itself it
            # cannot drift from the thing it protects, and losing a concurrent race PROVES the note
            # exists, which is why the view answers 200 there rather than Stripe's 500.
            models.UniqueConstraint(
                fields=["provider", "provider_message_id"],
                name="fieldnotes_note_unique_per_provider_message",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status", "-received_at"], name="fieldnotes_company_status"),
            models.Index(fields=["establishment", "status", "-received_at"], name="fieldnotes_est_status"),
            models.Index(fields=["company", "-created_at"], name="fieldnotes_company_recent"),
        ]

    def __str__(self):
        return f"{self.kind} from {self.sender_phone} ({self.status})"

    @property
    def is_open(self):
        return self.status == self.PENDING

    @property
    def words(self):
        """What a reviewer reads. One reader, so callers never choose between columns.

        For a voice note that is the TRANSCRIPT, which is a machine's guess rather than something the
        sender wrote. Callers that print these words to anyone other than the confirming supervisor
        must therefore check `kind`: the buyer page already refuses to republish a sender's sentence
        as the grower's own observation, and a transcript has strictly less standing than typed text.
        """
        return self.transcript if self.kind == self.VOICE else self.body_text
