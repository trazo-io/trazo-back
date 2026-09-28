"""What a supervisor is shown about a note.

EXPLICIT FIELD LIST, NEVER `__all__`. Two reasons, and the second is not hypothetical:

  * `provider_message_id` and `raw` provider identifiers are of no use to a farmer and are exactly
    the sort of value that ends up in a support screenshot.
  * When audio arrives, a `FileField` on the default storage serialises to a PERMANENT
    UNAUTHENTICATED PUBLIC URL, because `prod.py` records that the bucket policy on trazo-media
    grants public `s3:GetObject` with `AWS_QUERYSTRING_AUTH = False`. A `fields = "__all__"` here
    would publish a crew member's voice note to anyone with the JSON, and it would look correct in
    development because local storage is a filesystem. The habit has to be in place before the
    column is.
"""

from django.utils import timezone

from rest_framework import serializers

from fieldnotes.models import CrewSender, FieldNote
from fieldnotes.services.phone import normalise_phone


class FieldNoteSerializer(serializers.ModelSerializer):
    words = serializers.CharField(read_only=True)
    sender = serializers.SerializerMethodField()

    class Meta:
        model = FieldNote
        fields = (
            "public_id",
            "words",
            "sender",
            "kind",
            "status",
            "refusal_reason",
            "received_at",
            "establishment",
            "confirmed_at",
            "fulfilled_by_event_type",
            "fulfilled_by_id",
        )
        read_only_fields = fields

    def get_sender(self, obj):
        """Who sent it, as provenance.

        The last four digits only. A full number adds nothing a supervisor needs (they know their
        own crew) and would put arbitrary phone numbers into browser history, screenshots and every
        access log that records a JSON response.

        This is provenance, NOT authorship. `performed_by` prints in the certifier packet as the
        applicator of record, and a shared handset or a mayordomo reporting for twelve people would
        put one name against everyone's work.
        """
        return {
            "display_name": obj.sender_display_name,
            "phone_last4": (obj.sender_phone or "")[-4:],
        }


class CrewSenderSerializer(serializers.ModelSerializer):
    """The roster: which numbers may file notes, and against which farm.

    THE FULL NUMBER IS EXPOSED HERE, and that is the opposite of `FieldNoteSerializer`, which shows
    only the last four digits. The asymmetry is deliberate. A note is read by anyone who opens the
    inbox and the number adds nothing they need, so it stays out of screenshots and access logs. The
    roster is the form where a supervisor TYPED that number: they have to be able to read it back to
    spot the typo that would otherwise leave a crew member told they are not registered while their
    number is visibly on the list. Hiding it here would make the one screen that can fix a typo the
    one screen that cannot see it.

    `may_send` is served because `is_active` alone does not answer "can this number file anything".
    Three columns gate it, and a roster that showed only one would leave a supervisor looking at an
    active row that silently refuses every message.
    """

    # Write raw, store normalised. The webhook looks numbers up by exact string equality, so a row
    # holding "(415) 555-1234" can never match an inbound message.
    phone_e164 = serializers.CharField(max_length=32)
    may_send = serializers.SerializerMethodField()
    # Write-only, and the one on the model is never accepted from a client: see `validate`.
    consent_attested = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = CrewSender
        fields = (
            "id",
            "company",
            "establishment",
            "phone_e164",
            "display_name",
            "language",
            "is_active",
            "may_send",
            "consent_attested",
            "consent_attested_at",
            "stopped_at",
            "first_contact_at",
            "last_note_at",
            "created_at",
        )
        read_only_fields = (
            "id",
            "may_send",
            # STAMPED SERVER-SIDE, never taken from the request. These two are the record that a
            # person at the farm asserted the crew member agreed to be messaged, and a client that
            # could set the timestamp or the attester could manufacture that assertion.
            "consent_attested_at",
            "stopped_at",
            "first_contact_at",
            "last_note_at",
            "created_at",
        )

    def get_may_send(self, obj):
        # A PROPERTY on the model. `CrewSenderQuerySet.may_send()` is the queryset method of the same
        # name, which is the one the webhook calls; calling this one would be a TypeError.
        return obj.may_send

    def validate_phone_e164(self, value):
        normalised = normalise_phone(value)
        if not normalised:
            # Refusing beats storing a number that can never match. The message names the shape
            # rather than the regex, because the person reading it is a supervisor, not a developer.
            raise serializers.ValidationError("Enter the number with its country code, for example +1 415 555 1234.")
        return normalised

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        # TENANCY on the WRITE path. A serializer field for a ForeignKey accepts any primary key in
        # the table, so without this a caller could add a sender to a company they have nothing to do
        # with, and `unique_together (company, phone_e164)` would even tell them whether a number was
        # already registered there.
        company = attrs.get("company") or getattr(self.instance, "company", None)
        if company is not None and user is not None and not user.is_superuser:
            if not user.companies.filter(pk=company.pk).exists():
                raise serializers.ValidationError({"company": ["No matching company found."]})

        # A roster row may name a farm, and it must be a farm of the SAME company. Copying a foreign
        # establishment through would file that crew's notes against another operation's block, which
        # is what `CrewSender.filing_establishment` refuses at read time. Refusing it at write time
        # means the row never has to be second-guessed later.
        establishment = attrs.get("establishment") or getattr(self.instance, "establishment", None)
        if establishment is not None and company is not None and establishment.company_id != company.pk:
            raise serializers.ValidationError({"establishment": ["That farm belongs to a different company."]})

        # Consent is asserted on CREATE, because the crew member is not a Trazo user and cannot agree
        # here themselves. Without it `may_send()` is False and the webhook refuses the number, so a
        # row created without this is inert by design rather than by accident.
        if self.instance is None and not attrs.get("consent_attested"):
            raise serializers.ValidationError(
                {"consent_attested": ["Confirm that this person agreed to send work messages to this number."]}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop("consent_attested", None)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        validated_data["consent_attested_at"] = timezone.now()
        validated_data["consent_attested_by"] = user
        validated_data["added_by"] = user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Re-attesting is not a thing an update does. Consent was asserted once, by a named person,
        # at a recorded time; letting an edit refresh that stamp would make the record say the
        # assertion is newer than it is.
        validated_data.pop("consent_attested", None)
        return super().update(instance, validated_data)
