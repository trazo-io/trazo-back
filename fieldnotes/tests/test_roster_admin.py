"""The roster form and the webhook must agree on how a phone number is spelled (2026-09-26).

THE DEFECT THIS PREVENTS is not a crash, it is a support call nobody can diagnose. The webhook looks
numbers up by exact E.164 string. A supervisor who types "(415) 555-1234" into the roster creates a
row that can never match an inbound message, so the crew member is told they are not registered
while their number sits visibly on the list. The last test here is the one that matters: a number
entered the way a person actually types it must be found by a real signed message.

Notes are view only, and the three refusals are tested because each is a different kind of harm:
adding fabricates words attributed to a named crew member, changing rewrites what somebody is
recorded as having said, and deleting destroys the fact that they tried to file anything at all.
"""

import base64
import hashlib
import hmac

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from company.models import Company
from fieldnotes.admin import CrewSenderAdmin, CrewSenderForm, FieldNoteAdmin
from fieldnotes.models import CrewSender, FieldNote
from product.models import Establishment

TOKEN = "admin-test-token"
URL = "https://x.test/api/field-notes/inbound/twilio/"


class TheRosterFormNormalisesTheNumber(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Admin Co")
        self.establishment = Establishment.objects.create(name="Admin Farm", company=self.company)

    def form(self, phone, **extra):
        data = {
            "company": self.company.pk,
            "establishment": self.establishment.pk,
            "phone_e164": phone,
            "display_name": "Miguel",
            "language": CrewSender.ES,
            "is_active": True,
            "consent_attested": True,
        }
        data.update(extra)
        return CrewSenderForm(data=data)

    def test_a_humanly_typed_number_is_stored_in_the_shape_the_webhook_looks_up(self):
        form = self.form("+1 (415) 555-1234")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone_e164"], "+14155551234")

    def test_a_bare_number_is_refused_with_a_reason(self):
        form = self.form("4155551234")
        self.assertFalse(form.is_valid())
        self.assertIn("phone_e164", form.errors)
        # Refused rather than completed to +1, because assuming a country would route another
        # country's crew to the wrong place.
        self.assertIn("country code", str(form.errors["phone_e164"]))

    def test_active_without_an_attestation_is_refused(self):
        form = self.form("+14155551234", consent_attested=False)
        self.assertFalse(form.is_valid())
        self.assertIn("consent_attested", form.errors)

    def test_a_farm_from_another_company_is_refused_by_the_model_clean(self):
        other = Company.objects.create(name="Neighbour Co")
        foreign = Establishment.objects.create(name="Neighbour Farm", company=other)
        form = self.form("+14155551234", establishment=foreign.pk)
        self.assertFalse(form.is_valid())
        self.assertIn("establishment", form.errors)


class TheAttestationIsStamped(TestCase):
    def test_ticking_it_records_who_and_when(self):
        user = get_user_model().objects.create_user(email="admin@example.com", password="pw-for-tests-only")
        company = Company.objects.create(name="Stamp Co")
        form = CrewSenderForm(
            data={
                "company": company.pk,
                "phone_e164": "+14155557777",
                "display_name": "Ana",
                "language": CrewSender.ES,
                "is_active": True,
                "consent_attested": True,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        class Request:
            pass

        request = Request()
        request.user = user
        obj = form.save(commit=False)
        CrewSenderAdmin(CrewSender, None).save_model(request, obj, form, change=False)

        obj.refresh_from_db()
        self.assertIsNotNone(obj.consent_attested_at)
        self.assertEqual(obj.consent_attested_by, user)
        self.assertEqual(obj.added_by, user)
        self.assertTrue(obj.may_send)


class NotesAreViewOnly(TestCase):
    def setUp(self):
        self.admin = FieldNoteAdmin(FieldNote, None)

    def test_a_note_cannot_be_created_by_hand(self):
        self.assertFalse(self.admin.has_add_permission(None))

    def test_a_note_cannot_be_edited(self):
        self.assertFalse(self.admin.has_change_permission(None))

    def test_a_note_cannot_be_deleted(self):
        self.assertFalse(self.admin.has_delete_permission(None))

    def test_every_field_is_read_only(self):
        names = {f.name for f in FieldNote._meta.fields}
        self.assertEqual(set(self.admin.get_readonly_fields(None)), names)


@override_settings(TWILIO_AUTH_TOKEN=TOKEN, FIELD_NOTES_WEBHOOK_URL=URL)
class TheFormAndTheWebhookAgree(TestCase):
    def test_a_number_added_the_way_a_supervisor_types_it_receives_a_real_message(self):
        """The end-to-end claim: what the roster stores is what the webhook finds.

        Both halves in one test on purpose. Testing the form's normalisation alone would pass even if
        the webhook looked numbers up some other way, and that mismatch is invisible until a crew
        member says "it is not working" and the number looks correct on screen.
        """
        user = get_user_model().objects.create_user(email="e2e@example.com", password="pw-for-tests-only")
        company = Company.objects.create(name="E2E Co")
        user.companies.add(company)

        form = CrewSenderForm(
            data={
                "company": company.pk,
                "phone_e164": "+1 (415) 555-8888",  # as a person types it
                "display_name": "Miguel",
                "language": CrewSender.ES,
                "is_active": True,
                "consent_attested": True,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        class Request:
            pass

        request = Request()
        request.user = user
        CrewSenderAdmin(CrewSender, None).save_model(request, form.save(commit=False), form, change=False)

        params = {
            "MessageSid": "SMadmin1",
            "From": "whatsapp:+14155558888",  # as Twilio sends it
            "Body": "regamos el bloque 4",
            "NumMedia": "0",
            "ProfileName": "Miguel",
        }
        payload = URL + "".join(f"{key}{params[key]}" for key in sorted(params))
        signature = base64.b64encode(hmac.new(TOKEN.encode(), payload.encode(), hashlib.sha1).digest()).decode()

        response = self.client.post("/api/field-notes/inbound/twilio/", data=params, HTTP_X_TWILIO_SIGNATURE=signature)
        self.assertEqual(response.status_code, 200)
        note = FieldNote.objects.get()
        self.assertEqual(note.company, company)
        self.assertEqual(note.body_text, "regamos el bloque 4")
        self.assertEqual(note.sender_phone, "+14155558888")

        sender = CrewSender.objects.get()
        self.assertIsNotNone(sender.last_note_at)
        self.assertLessEqual(sender.last_note_at, timezone.now())
