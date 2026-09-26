"""Roster management, so the channel is reachable before its UI exists.

The webhook shipped before the roster API, which left no way to add a phone number except
`manage.py shell`. This is the stopgap: staff-only, deliberately narrow, and it exists so the
channel can be exercised end to end while the real per-company roster page is built.

TWO THINGS HERE ARE NOT CONVENIENCE FEATURES.

The phone number is normalised on save. The webhook looks numbers up by exact E.164 string, so a
supervisor who types "(415) 555-1234" would create a row that can never match an inbound message,
and the crew member would be told they are not registered while their number is visibly on the list.
Refusing a number this module cannot normalise is better than storing one that silently never works.

Notes are VIEW ONLY. Hand-creating a FieldNote would fabricate words attributed to a named crew
member, which is the authorship problem this whole app exists to avoid, and editing one would let
somebody change what a person is recorded as having said. Deleting one destroys the record-keeping
fact that somebody tried to file something. Confirm and discard are status transitions that arrive
with the inbox, not admin buttons.
"""

from django import forms
from django.contrib import admin, messages
from django.utils import timezone

from fieldnotes.models import CrewSender, FieldNote
from fieldnotes.services.phone import normalise_phone


class CrewSenderForm(forms.ModelForm):
    # Not a model field. A tick here is an assertion by the person making it, so it is stamped with
    # who and when rather than stored as a boolean somebody could later flip with no trace.
    consent_attested = forms.BooleanField(
        required=False,
        label="I have told this person their messages are read by Trazo and reviewed by me",
        help_text=(
            "Required before this number can send anything. A crew member is not a Trazo user and "
            "agreed to message their supervisor, not a platform."
        ),
    )

    class Meta:
        model = CrewSender
        fields = ("company", "establishment", "phone_e164", "display_name", "language", "is_active")

    def clean_phone_e164(self):
        raw = self.cleaned_data["phone_e164"]
        normalised = normalise_phone(raw)
        if not normalised:
            raise forms.ValidationError(
                "Enter the number in full international form, starting with a plus and the country "
                "code, for example +14155551234. A bare number is refused rather than assumed to be "
                "American, because guessing would route another country's crew to the wrong place."
            )
        return normalised

    def clean(self):
        cleaned = super().clean()
        # A row that cannot send is allowed to exist (somebody may be mid-setup), but saying so up
        # front is kinder than a number that silently never works.
        if cleaned.get("is_active") and not (cleaned.get("consent_attested") or self.instance.consent_attested_at):
            self.add_error(
                "consent_attested",
                "Tick this, or untick Active. An active number with no attestation is refused by the "
                "webhook anyway, so the row would look ready and do nothing.",
            )
        return cleaned


@admin.register(CrewSender)
class CrewSenderAdmin(admin.ModelAdmin):
    form = CrewSenderForm
    list_display = (
        "display_name",
        "phone_e164",
        "company",
        "establishment",
        "language",
        "may_send_now",
        "last_note_at",
        "stopped_at",
    )
    list_filter = ("company", "language", "is_active")
    search_fields = ("display_name", "phone_e164")
    readonly_fields = (
        "consent_attested_at",
        "consent_attested_by",
        "stopped_at",
        "last_note_at",
        "first_contact_at",
        "consented_at",
        "added_by",
        "created_at",
        "updated_at",
    )
    actions = ("clear_the_stop",)

    @admin.display(boolean=True, description="May send")
    def may_send_now(self, obj):
        return obj.may_send

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("company", "establishment")

    def save_model(self, request, obj, form, change):
        if form.cleaned_data.get("consent_attested") and not obj.consent_attested_at:
            obj.consent_attested_at = timezone.now()
            obj.consent_attested_by = request.user
        if not change:
            obj.added_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Clear the stop (this person asked to start sending again)")
    def clear_the_stop(self, request, queryset):
        """An explicit action, never an editable field.

        `stopped_at` is read-only on the form on purpose: a STOP came from the person themselves, and
        a supervisor clearing it by re-ticking a box would be undoing somebody else's decision with
        nothing on screen to mark it. Rejoining is legitimate, so it gets a named action that says
        what it means and who did it.
        """
        cleared = queryset.filter(stopped_at__isnull=False).update(stopped_at=None, updated_at=timezone.now())
        self.message_user(
            request,
            f"Cleared the stop on {cleared} number(s). They still need Active ticked to send.",
            messages.SUCCESS if cleared else messages.WARNING,
        )


@admin.register(FieldNote)
class FieldNoteAdmin(admin.ModelAdmin):
    """View only. See the module docstring for why each verb is refused."""

    list_display = ("received_at", "sender_display_name", "sender_phone", "company", "kind", "status", "refusal_reason")
    list_filter = ("status", "kind", "provider", "company")
    search_fields = ("sender_phone", "sender_display_name", "body_text", "provider_message_id")
    date_hierarchy = "received_at"

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        # Hand-creating a note would fabricate words attributed to a named crew member.
        return False

    def has_change_permission(self, request, obj=None):
        # Editing one would change what a person is recorded as having said.
        return False

    def has_delete_permission(self, request, obj=None):
        # That somebody tried to file something at 14:02 is itself a record-keeping fact.
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("company", "establishment", "sender")
