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

from rest_framework import serializers

from fieldnotes.models import FieldNote


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
