"""The inbound webhook accepts only signed messages from rostered numbers (2026-09-26).

This endpoint is the one surface of this app a stranger can reach, and it writes rows scoped to a
farm. The cross-tenant write on event create (fixed 2026-09-16) is the shape it would re-open if the
roster lookup were ever weakened: there, any authenticated user could put an event on any farm's
parcel by numeric id. Here the caller is not even authenticated, so the signature and the roster are
the whole of the access control.

THE SIGNATURE VECTOR BELOW IS INDEPENDENT. It was computed from Twilio's documented scheme
(base64(HMAC-SHA1(token, url + concat(sorted(key + value))))) rather than by calling the adapter, so
these tests check the implementation against the specification instead of against itself. Rebuilding
it with the adapter's own helper would pass even if the helper were wrong.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from company.models import Company
from fieldnotes.models import CrewSender, FieldNote
from product.models import Establishment

TOKEN = "test-auth-token-not-a-real-secret"
URL = "https://api.trazo.io/api/field-notes/inbound/twilio/"
PATH = "/api/field-notes/inbound/twilio/"

# Independently computed for TOKEN, URL and exactly the params in PARAMS.
SIGNATURE = "LQxqEHl4T3biK63eYFBsFaLW+78="
PARAMS = {
    "MessageSid": "SM1234567890abcdef",
    "From": "whatsapp:+14155551234",
    "Body": "regamos el bloque 4 esta manana",
    "NumMedia": "0",
    "ProfileName": "Miguel",
}


@override_settings(TWILIO_AUTH_TOKEN=TOKEN, FIELD_NOTES_WEBHOOK_URL=URL)
class InboundWebhookTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="sup@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Field Notes Co")
        self.user.companies.add(self.company)
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company)
        self.sender = CrewSender.objects.create(
            company=self.company,
            establishment=self.establishment,
            phone_e164="+14155551234",
            display_name="Miguel",
            language=CrewSender.ES,
            consent_attested_at=timezone.now(),
            consent_attested_by=self.user,
        )

    def post(self, params=None, signature=SIGNATURE):
        return self.client.post(PATH, data=params if params is not None else PARAMS, HTTP_X_TWILIO_SIGNATURE=signature)

    # ---------------------------------------------------------------- the signature is the credential

    def test_a_signed_message_from_a_rostered_number_is_accepted(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        note = FieldNote.objects.get()
        self.assertEqual(note.company, self.company)
        self.assertEqual(note.establishment, self.establishment)
        self.assertEqual(note.status, FieldNote.PENDING)
        self.assertEqual(note.body_text, PARAMS["Body"])
        self.assertEqual(note.sender_phone, "+14155551234")

    def test_a_wrong_signature_is_refused_and_writes_nothing(self):
        response = self.post(signature="Zm9yZ2VkIHNpZ25hdHVyZQ==")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(FieldNote.objects.count(), 0)

    def test_a_missing_signature_is_refused(self):
        response = self.client.post(PATH, data=PARAMS)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(FieldNote.objects.count(), 0)

    @override_settings(TWILIO_AUTH_TOKEN="")
    def test_an_unset_secret_fails_CLOSED(self):
        # The one that matters most. A misconfigured deploy must not become an open write endpoint
        # on a farm's compliance records, so "no secret" means refuse everything, never accept
        # everything.
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(FieldNote.objects.count(), 0)

    def test_changing_one_character_of_the_body_invalidates_the_signature(self):
        tampered = dict(PARAMS, Body=PARAMS["Body"] + "!")
        self.assertEqual(self.post(tampered).status_code, 400)
        self.assertEqual(FieldNote.objects.count(), 0)

    # ---------------------------------------------------------------------------- the roster is the gate

    def test_an_unrostered_number_writes_nothing_and_is_answered_with_silence(self):
        self.sender.delete()
        response = self.post()
        # 200 rather than 403: a retry would produce the same refusal. And an empty body rather than
        # a message, because replying would confirm to a stranger that the line is live.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertEqual(FieldNote.objects.count(), 0)

    def test_a_deactivated_number_is_refused_like_an_unknown_one(self):
        self.sender.is_active = False
        self.sender.save(update_fields=["is_active"])
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(FieldNote.objects.count(), 0)

    def test_a_number_with_no_consent_attestation_is_refused(self):
        # Active is not enough. Somebody accountable has to have said that this person was told what
        # happens to their words.
        self.sender.consent_attested_at = None
        self.sender.save(update_fields=["consent_attested_at"])
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(FieldNote.objects.count(), 0)

    def test_a_number_rostered_by_two_companies_is_refused_rather_than_guessed(self):
        other = Company.objects.create(name="Second Co")
        CrewSender.objects.create(
            company=other,
            phone_e164="+14155551234",
            consent_attested_at=timezone.now(),
        )
        self.assertEqual(self.post().status_code, 200)
        # Picking one would be a routing decision about a compliance record made on heap order, and
        # telling either company would disclose that the crew also works for the other.
        self.assertEqual(FieldNote.objects.count(), 0)

    def test_the_company_comes_from_the_roster_and_never_from_the_payload(self):
        other = Company.objects.create(name="Attacker Co")
        smuggled = dict(PARAMS)
        smuggled["company"] = str(other.id)
        smuggled["company_id"] = str(other.id)
        # The signature covers exactly PARAMS, so adding keys invalidates it. That is the point: a
        # payload cannot name its own destination, signed or not.
        self.assertEqual(self.post(smuggled).status_code, 400)
        self.assertEqual(FieldNote.objects.count(), 0)

    # ------------------------------------------------------------------------------------ idempotency

    def test_the_same_message_delivered_twice_creates_exactly_one_note(self):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(FieldNote.objects.count(), 1)

    def test_a_concurrent_duplicate_answers_200_because_the_note_exists(self):
        # Losing the race on a constraint that lives on the OUTCOME row proves the work is done.
        # `stripe_webhook` returns 500 here to invite a retry, because its constraint is on a side
        # table and losing the race there says nothing about whether the work happened.
        self.assertEqual(self.post().status_code, 200)
        with patch("fieldnotes.views.FieldNote.objects.filter") as no_preflight:
            no_preflight.return_value.exists.return_value = False
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FieldNote.objects.count(), 1)

    # ------------------------------------------------------------------------------ shape of the reply

    def test_the_response_body_is_always_empty(self):
        # The promise written into the anonymous-endpoint allowlist entry: a stranger with this URL
        # can read no PII, no geodata and no claim.
        self.assertEqual(self.post().content, b"")

    def test_the_webhook_makes_no_network_call(self):
        # Slow work in here blows the provider's short inbound timeout, which triggers a retry and
        # turns one message into two deliveries.
        with patch("requests.get") as get, patch("requests.post") as post:
            self.post()
        get.assert_not_called()
        post.assert_not_called()

    # ------------------------------------------------------------------------------------- other paths

    def test_an_unknown_provider_is_404(self):
        response = self.client.post("/api/field-notes/inbound/carrier-pigeon/", data=PARAMS)
        self.assertEqual(response.status_code, 404)

    def test_stop_deactivates_the_number_and_writes_no_note(self):
        import base64
        import hashlib
        import hmac

        params = dict(PARAMS, Body="STOP", MessageSid="SMstop1")
        payload = URL + "".join(f"{k}{params[k]}" for k in sorted(params))
        signature = base64.b64encode(hmac.new(TOKEN.encode(), payload.encode(), hashlib.sha1).digest()).decode()

        self.assertEqual(self.post(params, signature=signature).status_code, 200)
        self.sender.refresh_from_db()
        self.assertFalse(self.sender.is_active)
        self.assertEqual(FieldNote.objects.count(), 0)

    def test_a_voice_note_is_recorded_as_refused_rather_than_dropped(self):
        import base64
        import hashlib
        import hmac

        params = dict(
            PARAMS,
            MessageSid="SMvoice1",
            NumMedia="1",
            MediaContentType0="audio/ogg",
            MediaUrl0="https://api.twilio.com/media/ME1",
            Body="",
        )
        payload = URL + "".join(f"{k}{params[k]}" for k in sorted(params))
        signature = base64.b64encode(hmac.new(TOKEN.encode(), payload.encode(), hashlib.sha1).digest()).decode()

        self.assertEqual(self.post(params, signature=signature).status_code, 200)
        note = FieldNote.objects.get()
        # Visible, with a reason. That somebody tried to file something at 14:02 is itself a
        # record-keeping fact, and a note that vanishes is worse than one that says why.
        self.assertEqual(note.kind, FieldNote.VOICE)
        self.assertEqual(note.status, FieldNote.REFUSED)
        self.assertEqual(note.refusal_reason, "voice_not_enabled")
