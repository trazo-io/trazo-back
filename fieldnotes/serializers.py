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
from rest_framework.exceptions import PermissionDenied

from fieldnotes.models import CrewSender, FieldNote
from fieldnotes.permissions import may_write_roster
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
            # SERVED BECAUSE THE CLIENT BRANCHES ON IT. The inbox renders an audio player unless the
            # recording is gone, and without this field that check read `undefined` forever: the
            # player rendered for a deleted recording and answered 410 when somebody pressed play.
            # A field the UI reads and the API never sends is invisible to a component test, because
            # the fixture supplies it.
            "audio_deleted_at",
            "confirmed_at",
            # Served so the client can tell a refusal nobody has looked at from one somebody has.
            # Not used to decide whether it renders (the `?status=` filter does that); used so a
            # surface that lists acknowledged notes can say when, rather than only that.
            "acknowledged_at",
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
            # SERVED BECAUSE THE ROSTER HAS TO BE ABLE TO SHOW IT. `first_contact_at` was
            # already here and nothing rendered it, and `consented_at` was not here at all, so
            # a supervisor who ticked "I told this person" had no way to see whether the notice
            # Trazo promises to send on their behalf ever went out. A column written on the
            # server and read by no surface is the `audio_deleted_at` shape; a parity guard now
            # covers this serializer too.
            "consented_at",
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
            # Same reason as the two above: this is the record that the person carried on
            # messaging AFTER being told, which is the only consent signal this channel can
            # observe. A client that could set it could manufacture that observation.
            "consented_at",
            "last_note_at",
            "created_at",
        )

    def get_may_send(self, obj):
        # A PROPERTY on the model. `CrewSenderQuerySet.may_send()` is the queryset method of the same
        # name, which is the one the webhook calls; calling this one would be a TypeError.
        return obj.may_send

    def validate_company(self, value):
        """FIELD-level, and that is the whole point: it has to speak before the unique validator.

        FOUND IN REVIEW OF #50. `UniqueConstraint(company, phone_e164)` makes DRF generate a
        `UniqueTogetherValidator`, and class-level validators run inside `run_validators()`, which
        `Serializer.run_validation()` calls BEFORE `self.validate(attrs)`. So the membership check
        this class used to do in `validate()` never got to answer first: posting a company the caller
        has nothing to do with returned "must make a unique set" when the number was already on that
        roster and "No matching company found" when it was not. A working probe for whether any given
        phone number is registered to another operation.

        A field validator runs inside `to_internal_value`, which raises before `run_validators` is
        reached, so the unique validator never speaks at all.

        THE ROLE IS CHECKED HERE TOO, not only membership. `user.companies` is role-agnostic, so a
        VIEWER passed it, and `ReadOnlyForViewersGlobal` only asks whether an elevated role exists in
        SOME company. Neither answers "may this person write to THIS company".
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or getattr(user, "is_superuser", False):
            return value

        if not user.companies.filter(pk=value.pk).exists():
            # The same answer whatever is on that roster, so a stranger learns nothing.
            raise serializers.ValidationError("No matching company found.")
        if not may_write_roster(user, value.pk):
            # A member who may read and not write. Saying so plainly leaks nothing they do not
            # already know, and a vague error would send them hunting for a typo instead.
            raise PermissionDenied("You do not have permission to change this company's roster.")
        return value

    def validate_phone_e164(self, value):
        normalised = normalise_phone(value)
        if not normalised:
            # Refusing beats storing a number that can never match. The message names the shape
            # rather than the regex, because the person reading it is a supervisor, not a developer.
            raise serializers.ValidationError("Enter the number with its country code, for example +1 415 555 1234.")
        return normalised

    def validate(self, attrs):
        # No `request` or `user` here any more: the only thing that needed them was the company
        # membership check, and that had to move up into `validate_company` to run before the
        # unique-together validator. Nothing left in this method is about who is asking.
        #
        # Tenancy and the write role for `company` live in `validate_company` above. Do NOT move
        # that check back down here.
        company = attrs.get("company") or getattr(self.instance, "company", None)

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
        needs_consent = self.instance is None

        # CONSENT IS ABOUT A NUMBER, not about a row. Found in review of #50: `phone_e164` is
        # writable, so a PATCH could repoint the row at a different number while
        # `consent_attested_at` and `consent_attested_by` went on naming whoever attested for the
        # ORIGINAL one. The row then claimed consent from somebody who never gave it, and `may_send`
        # stayed True because it reads only `is_active`, the stamp and `stopped_at`.
        # `fieldnotes/admin.py` already re-required consent on edit; this path did not.
        if self.instance is not None:
            incoming = attrs.get("phone_e164")
            if incoming and incoming != self.instance.phone_e164:
                needs_consent = True

        if needs_consent and not attrs.get("consent_attested"):
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
        attested = validated_data.pop("consent_attested", False)
        moved = "phone_e164" in validated_data and validated_data["phone_e164"] != instance.phone_e164

        # An unrelated edit must NOT refresh the stamp: consent was asserted once, by a named person,
        # at a recorded time, and renewing it on a display-name change would make the record claim
        # the assertion is newer than it is. A MOVED number is the opposite case, and `validate`
        # already refused that without a fresh attestation, so the stamp moves with it.
        if moved and attested:
            request = self.context.get("request")
            validated_data["consent_attested_at"] = timezone.now()
            validated_data["consent_attested_by"] = getattr(request, "user", None)
        return super().update(instance, validated_data)
