"""The crew member hears back (2026-09-29).

Before this, nothing in the app ever sent a WhatsApp message. `CrewSender.first_contact_at` and
`consented_at` were columns with no writer: the notice they exist to record had no sender behind it,
so the operator attested to consent and the person it was about was told nothing. A crew member
whose recording could not be read got silence and believed they had filed something.

WHAT THESE TESTS HOLD, each one a mistake available here:

  * A STRANGER IS NEVER ANSWERED. The unrostered branch is silent on purpose, and so is a "stop"
    from a number on nobody's roster. A reply to either confirms the number is a live Trazo line and
    turns this endpoint into a way to send messages to arbitrary phones.
  * THE NOTICE GOES OUT ONCE. A conditional UPDATE claims the row, so a concurrent redelivery
    cannot send it twice, and a second message sends nothing.
  * A FAILED SEND IS NOT RECORDED AS SENT. Otherwise the notice is lost permanently for somebody
    whose words are about to be processed.
  * TRAZO'S OWN MISCONFIGURATION IS NEVER SENT TO THE CREW. `media_auth_unconfigured` means a key
    is missing on our side; asking them to send the recording again wastes their time and hides it.
  * NO REPLY REPEATS THE PRACTICE. A message echoing "you sprayed block 4" would be a machine
    asserting a farming event before any human confirmed it (7 CFR 205.201(a)).

EVERY SEND IS PATCHED AT THE ADAPTER, never at the service, so these exercise the real composing,
language selection and claim logic rather than a stub of it.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from company.models import Company
from fieldnotes.models import CrewSender, FieldNote
from fieldnotes.services import reply as crew_reply
from product.models import Establishment

TOKEN = "test-auth-token-not-a-real-secret"
URL = "https://api.trazo.io/api/field-notes/inbound/twilio/"
PATH = "/api/field-notes/inbound/twilio/"
SEND = "fieldnotes.providers.twilio.TwilioWhatsAppAdapter.send_text"


def sign(params):
    import base64
    import hashlib
    import hmac

    payload = URL + "".join(f"{key}{params[key]}" for key in sorted(params))
    return base64.b64encode(hmac.new(TOKEN.encode(), payload.encode(), hashlib.sha1).digest()).decode()


@override_settings(
    TWILIO_AUTH_TOKEN=TOKEN,
    TWILIO_ACCOUNT_SID="AC-test",
    FIELD_NOTES_WHATSAPP_FROM="+14155238886",
    FIELD_NOTES_WEBHOOK_URL=URL,
    FIELD_NOTE_RUNNER="eager",
)
class CrewReplyTests(TestCase):
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

    def post(self, **overrides):
        params = {
            "MessageSid": "SM0000000000000001",
            "From": "whatsapp:+14155551234",
            "Body": "regamos el bloque 4",
            "NumMedia": "0",
            "ProfileName": "Miguel",
        }
        params.update(overrides)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(PATH, data=params, HTTP_X_TWILIO_SIGNATURE=sign(params))

    # ------------------------------------------------------------------ the first-contact notice

    def test_the_first_message_gets_the_notice_and_stamps_it(self):
        with patch(SEND, return_value=True) as send:
            self.post()

        send.assert_called_once()
        to, body = send.call_args[0]
        self.assertEqual(to, "+14155551234")
        self.sender.refresh_from_db()
        self.assertIsNotNone(self.sender.first_contact_at)
        # In THEIR language, not the app default. A notice about data processing that the reader
        # cannot read is not a notice.
        self.assertIn("finca", body)
        self.assertIn("STOP", body)

    def test_the_notice_names_the_processors_and_the_deletion(self):
        # The substance the roster's consent checkbox promises the person was told. If this copy is
        # ever trimmed, it must not be trimmed to less than what the operator attested to.
        with patch(SEND, return_value=True) as send:
            self.post()
        body = send.call_args[0][1]
        for expected in ("Deepgram", "OpenAI", "Home Ranch"):
            self.assertIn(expected, body)

    def test_the_notice_is_sent_only_once(self):
        with patch(SEND, return_value=True) as send:
            self.post()
            self.post(MessageSid="SM0000000000000002", Body="podamos el bloque 2")
        self.assertEqual(send.call_count, 1)

    def test_the_claim_alone_stops_a_second_notice(self):
        """The SERVICE refuses the second send, independently of the view's own check.

        Found by running the breaking edit: dropping the conditional UPDATE from
        `notify_first_contact` left `test_the_notice_is_sent_only_once` GREEN, because the view
        also asks `if sender.first_contact_at is None`. Two gates is the right design, but a test
        that only exercises them together pins neither. This one calls the service directly, which
        is the path a concurrent redelivery takes: both deliveries read the row as unstamped and
        only the UPDATE can decide between them.
        """
        with patch(SEND, return_value=True) as send:
            self.assertTrue(crew_reply.notify_first_contact(self.sender, "twilio"))
            self.assertFalse(crew_reply.notify_first_contact(self.sender, "twilio"))
        self.assertEqual(send.call_count, 1)

    def test_a_failed_send_is_not_recorded_as_sent(self):
        # Otherwise the notice is lost forever for somebody whose words are about to be processed.
        with patch(SEND, return_value=False):
            self.post()
        self.sender.refresh_from_db()
        self.assertIsNone(self.sender.first_contact_at)

        with patch(SEND, return_value=True) as send:
            self.post(MessageSid="SM0000000000000003")
        self.assertEqual(send.call_count, 1)

    def test_a_raising_provider_does_not_500_the_webhook(self):
        # An anonymous webhook's 500 makes the provider redeliver a message already stored.
        with patch(SEND, side_effect=RuntimeError("provider down")):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FieldNote.objects.count(), 1)

    # ------------------------------------------------------------------ consent

    def test_the_message_after_the_notice_records_consent(self):
        with patch(SEND, return_value=True):
            self.post()
        self.sender.refresh_from_db()
        self.assertIsNone(self.sender.consented_at)

        with patch(SEND, return_value=True):
            self.post(MessageSid="SM0000000000000004", Body="podamos el bloque 2")
        self.sender.refresh_from_db()
        self.assertIsNotNone(self.sender.consented_at)

    def test_consent_cannot_be_recorded_for_somebody_never_told(self):
        # The stamp means "read it and kept going". Without a notice it would mean nothing at all.
        self.assertFalse(crew_reply.record_consent(self.sender))
        self.sender.refresh_from_db()
        self.assertIsNone(self.sender.consented_at)

    # ------------------------------------------------------------------ stop

    def test_stop_from_a_rostered_number_is_acknowledged_in_their_language(self):
        with patch(SEND, return_value=True) as send:
            self.post(MessageSid="SM0000000000000005", Body="STOP")
        self.sender.refresh_from_db()
        self.assertIsNotNone(self.sender.stopped_at)
        send.assert_called_once()
        self.assertIn("supervisor", send.call_args[0][1])

    def test_stop_from_a_stranger_is_silent(self):
        with patch(SEND, return_value=True) as send:
            self.post(MessageSid="SM0000000000000006", From="whatsapp:+14155559999", Body="stop")
        send.assert_not_called()

    def test_a_stranger_is_never_answered(self):
        # A reply would confirm to anyone who found the number that it is a live Trazo line.
        with patch(SEND, return_value=True) as send:
            response = self.post(MessageSid="SM0000000000000007", From="whatsapp:+14155559999")
        self.assertEqual(response.status_code, 200)
        send.assert_not_called()
        self.assertEqual(FieldNote.objects.count(), 0)

    # ------------------------------------------------------------------ refusals

    def test_a_refused_message_tells_the_sender_what_to_do(self):
        with patch(SEND, return_value=True) as send:
            # A photo with no caption: a text message with an empty body and a media reference.
            self.post(
                MessageSid="SM0000000000000008",
                Body="",
                NumMedia="1",
                MediaUrl0="https://api.twilio.com/media/ME1",
                MediaContentType0="image/jpeg",
            )

        note = FieldNote.objects.get()
        self.assertEqual(note.status, FieldNote.REFUSED)
        self.assertEqual(note.refusal_reason, "unsupported_media")
        # Two messages: the first-contact notice, then the refusal.
        self.assertEqual(send.call_count, 2)
        self.assertIn("palabras", send.call_args_list[1][0][1])

    def test_our_own_misconfiguration_is_never_sent_to_the_crew(self):
        note = FieldNote.objects.create(
            company=self.company,
            establishment=self.establishment,
            sender=self.sender,
            sender_phone=self.sender.phone_e164,
            provider="twilio",
            provider_message_id="SM-config",
            kind=FieldNote.VOICE,
            status=FieldNote.REFUSED,
            refusal_reason="media_auth_unconfigured",
        )
        with patch(SEND, return_value=True) as send:
            self.assertFalse(crew_reply.notify_refusal(note))
        send.assert_not_called()

    def test_a_reason_with_no_copy_sends_nothing(self):
        # `refusal_reason` is a plain CharField with no choices, so the server can grow a value
        # before its copy lands. Silence beats a message the reader cannot act on.
        note = FieldNote.objects.create(
            company=self.company,
            establishment=self.establishment,
            sender=self.sender,
            sender_phone=self.sender.phone_e164,
            provider="twilio",
            provider_message_id="SM-unknown",
            kind=FieldNote.VOICE,
            status=FieldNote.REFUSED,
            refusal_reason="some_new_reason_from_the_server",
        )
        with patch(SEND, return_value=True) as send:
            self.assertFalse(crew_reply.notify_refusal(note))
        send.assert_not_called()

    def test_a_note_that_is_not_refused_is_never_replied_to(self):
        note = FieldNote.objects.create(
            company=self.company,
            establishment=self.establishment,
            sender=self.sender,
            sender_phone=self.sender.phone_e164,
            provider="twilio",
            provider_message_id="SM-pending",
            kind=FieldNote.TEXT,
            body_text="regamos el bloque 4",
            status=FieldNote.PENDING,
            refusal_reason="media_unavailable",
        )
        with patch(SEND, return_value=True) as send:
            self.assertFalse(crew_reply.notify_refusal(note))
        send.assert_not_called()

    # ------------------------------------------------------------------ what a reply may say

    def test_no_reply_repeats_what_the_crew_reported(self):
        """A machine echoing the practice asserts a farming event nobody has confirmed.

        Checked against EVERY string this module can send rather than against one call, because the
        risk is a future string added without the rule in mind.
        """
        tables = [crew_reply.FIRST_CONTACT, crew_reply.STOP_CONFIRMED, *crew_reply.REFUSAL_COPY.values()]
        self.assertGreater(len(tables), 3, "the copy tables moved; this guard is checking nothing")

        for table in tables:
            for language, text in table.items():
                lowered = text.lower()
                for banned in ("bloque", "block", "spray", "apli", "irriga", "reg ", "podam"):
                    self.assertNotIn(
                        banned,
                        lowered,
                        f"{language} copy names a farming practice; a reply must never state one back",
                    )

    def test_every_roster_language_has_copy(self):
        """A fourth language cannot reach the roster without something to say in it.

        `_copy` falls back to English so a webhook never raises, and this is what stops that
        fallback quietly becoming the normal case.
        """
        languages = [code for code, _ in CrewSender.LANGUAGE_CHOICES]
        self.assertEqual(len(languages), 3, "LANGUAGE_CHOICES changed; add copy before changing this")

        for table in [crew_reply.FIRST_CONTACT, crew_reply.STOP_CONFIRMED, *crew_reply.REFUSAL_COPY.values()]:
            for language in languages:
                self.assertIn(language, table)
                self.assertTrue(table[language].strip())

    def test_an_unconfigured_deployment_sends_nothing_and_still_stores_the_note(self):
        # The inbox is the product; the reply is a courtesy. A deployment with no sender configured
        # must not lose notes over it.
        with override_settings(FIELD_NOTES_WHATSAPP_FROM=""):
            with patch("fieldnotes.providers.twilio.requests.post") as post:
                response = self.post(MessageSid="SM0000000000000009")
        self.assertEqual(response.status_code, 200)
        post.assert_not_called()
        self.assertEqual(FieldNote.objects.count(), 1)
        self.sender.refresh_from_db()
        self.assertIsNone(self.sender.first_contact_at)
