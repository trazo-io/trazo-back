"""A crew member sends a voice note and a supervisor reviews words, having been able to listen.

WHY THIS IS DIFFERENT FROM THE IN-APP VOICE FLOW. There, the browser mints a 60-second Deepgram key
and streams straight to Deepgram, so Trazo never receives audio and the farmer who spoke is also the
person who confirms. Here the recording sits at the provider and the speaker is NEVER the confirmer,
which is the whole reason playback matters: ASR dropping a negation ("I applied nothing in block 4")
is undetectable by anyone who was not the speaker, and the result would be a confirmed chemical
application that nobody performed.

THE BYTES NEVER ENTER TRAZO'S STORAGE, and that is the design rather than an optimisation. The
provider enforces HTTP Basic auth on media URLs and keeps the file until it is deleted through the
API, so the note holds a REFERENCE, playback is proxied through an authenticated view, and confirm or
discard deletes the file where it lives. Trazo's own default storage is the public one: the bucket
policy on `trazo-media` grants public `s3:GetObject` with `AWS_QUERYSTRING_AUTH = False`, so a
`FileField` here would be a permanent unauthenticated URL for a crew member's recording, and local
development would look correct because dev storage is the filesystem.
"""

import base64
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APITestCase

from company.models import Company
from fieldnotes.models import CrewSender, FieldNote
from fieldnotes.services.transcribe import TranscriptionRefused, language_for, media_host_allowed
from notifications.models import Notification
from product.models import Establishment
from users.models import WorksIn

TOKEN = "test-auth-token-not-a-real-secret"
ACCOUNT_SID = "ACtest0000000000000000000000000000"
URL = "https://api.trazo.io/api/field-notes/inbound/twilio/"
PATH = "/api/field-notes/inbound/twilio/"
MEDIA = "https://api.twilio.com/2010-04-01/Accounts/AC/Messages/MM/Media/ME1"

SPOKEN = "regamos el bloque 4 esta manana, dos horas"


def deepgram_body(transcript=SPOKEN, language="es"):
    return {
        "results": {
            "channels": [
                {
                    "detected_language": language,
                    "alternatives": [{"transcript": transcript}],
                }
            ]
        }
    }


def ok_response(body, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    response.content = b"fake-ogg-bytes"
    response.iter_content.return_value = iter([b"fake-ogg-bytes"])
    return response


@override_settings(
    TWILIO_AUTH_TOKEN=TOKEN,
    TWILIO_ACCOUNT_SID=ACCOUNT_SID,
    FIELD_NOTES_WEBHOOK_URL=URL,
    DEEPGRAM_API_KEY="dg-test-key-not-real",
    # Inline, so the job runs in the request and the assertions are about behaviour rather than
    # about whether a thread happened to have started yet.
    FIELD_NOTE_RUNNER="eager",
)
class VoiceNoteIntakeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(email="voice-sup@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Voice Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.user.companies.add(self.company)
        self.farm = Establishment.objects.create(name="Voice Farm", company=self.company)
        self.sender = CrewSender.objects.create(
            company=self.company,
            establishment=self.farm,
            phone_e164="+14155551234",
            display_name="Miguel",
            language=CrewSender.ES,
            consent_attested_at=timezone.now(),
            consent_attested_by=self.user,
        )

    def post_voice(self, message_id="SMvoice", media=MEDIA, content_type="audio/ogg"):
        params = {
            "MessageSid": message_id,
            "From": "whatsapp:+14155551234",
            "Body": "",
            "NumMedia": "1",
            "MediaContentType0": content_type,
            "ProfileName": "Miguel",
        }
        if media:
            params["MediaUrl0"] = media
        payload = URL + "".join(f"{key}{params[key]}" for key in sorted(params))
        signature = base64.b64encode(hmac.new(TOKEN.encode(), payload.encode(), hashlib.sha1).digest()).decode()
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(PATH, data=params, HTTP_X_TWILIO_SIGNATURE=signature)

    # ------------------------------------------------------------------ the happy path, end to end

    def test_a_voice_note_becomes_reviewable_words(self):
        with (
            patch("fieldnotes.services.transcribe.requests.get", return_value=ok_response({})) as fetch,
            patch("fieldnotes.services.transcribe.requests.post", return_value=ok_response(deepgram_body())) as asr,
        ):
            self.assertEqual(self.post_voice().status_code, 200)

        note = FieldNote.objects.get()
        self.assertEqual(note.status, FieldNote.PENDING, "the note never became reviewable")
        self.assertEqual(note.transcript, SPOKEN)
        self.assertEqual(note.transcript_language, "es-419")
        # ONE reader, so no surface has to choose between two columns.
        self.assertEqual(note.words, SPOKEN)
        # `body_text` stays empty: the sender typed nothing, and a transcript is not something they
        # wrote. The distinction is what lets the buyer page refuse to republish it as their words.
        self.assertEqual(note.body_text, "")

        # The media was fetched WITH credentials, from the provider, not from Trazo storage.
        self.assertEqual(fetch.call_args.kwargs["auth"], (ACCOUNT_SID, TOKEN))
        self.assertEqual(fetch.call_args.args[0], MEDIA)
        self.assertEqual(asr.call_args.kwargs["data"], b"fake-ogg-bytes")

    def test_the_transcription_request_never_asks_for_smart_format(self):
        """⛔ MEASURED 2026-09-10: `smart_format` DELETES WORDS from finals on this project.

        A missing word in a chemical application is a different record from the one that was reported,
        so this is a correctness assertion rather than a preference. `numerals` is the replacement for
        the part of it that was wanted.
        """
        with (
            patch("fieldnotes.services.transcribe.requests.get", return_value=ok_response({})),
            patch("fieldnotes.services.transcribe.requests.post", return_value=ok_response(deepgram_body())) as asr,
        ):
            self.post_voice()

        params = asr.call_args.kwargs["params"]
        self.assertNotIn("smart_format", params)
        self.assertEqual(params["numerals"], "true")
        self.assertEqual(params["detect_language"], "true")
        self.assertEqual(params["model"], "nova-3")

    def test_no_parse_is_stored_at_arrival(self):
        """The extractor runs at CONFIRM time, where the supervisor has chosen an activity and the
        form's real field list is known, so a parse stored here would be strictly worse and would
        invite the `ProductionPlanItem.prefill` mistake."""
        with (
            patch("fieldnotes.services.transcribe.requests.get", return_value=ok_response({})),
            patch("fieldnotes.services.transcribe.requests.post", return_value=ok_response(deepgram_body())),
            patch("carbon.services.ai_voice_processor.process_voice_with_ai") as extractor,
        ):
            self.post_voice()

        extractor.assert_not_called()
        self.assertFalse(hasattr(FieldNote.objects.get(), "extraction"))

    # --------------------------------------------------------------------------------- metering

    def test_one_unit_is_charged_before_anything_is_spent(self):
        with (
            patch("fieldnotes.services.transcribe.requests.get", return_value=ok_response({})),
            patch("fieldnotes.services.transcribe.requests.post", return_value=ok_response(deepgram_body())),
            patch("carbon.services.voice_budget.consume_voice_session", return_value=(True, 1, 50)) as meter,
        ):
            self.post_voice()

        meter.assert_called_once()
        self.assertEqual(FieldNote.objects.get().status, FieldNote.PENDING)

    def test_over_budget_refuses_without_fetching_or_transcribing(self):
        """Server-side transcription was free before this: `consume_voice_session` had two callers,
        both in `carbon/views.py`, neither reachable from a background job."""
        with (
            patch("fieldnotes.services.transcribe.requests.get") as fetch,
            patch("fieldnotes.services.transcribe.requests.post") as asr,
            patch("carbon.services.voice_budget.consume_voice_session", return_value=(False, 50, 50)),
        ):
            self.post_voice()

        note = FieldNote.objects.get()
        self.assertEqual(note.status, FieldNote.REFUSED)
        self.assertEqual(note.refusal_reason, "voice_daily_limit")
        fetch.assert_not_called()
        asr.assert_not_called()

    # ------------------------------------------------------------------------------ language

    def test_an_unsupported_language_is_refused_rather_than_parsed_as_english(self):
        """`prompt_key_for` silently falls back to the English prompt, English keywords and an English
        numeral table for anything it does not know, so a wrong parse would arrive with full
        confidence. Refusing gives the supervisor something they can act on."""
        with (
            patch("fieldnotes.services.transcribe.requests.get", return_value=ok_response({})),
            patch(
                "fieldnotes.services.transcribe.requests.post",
                return_value=ok_response(deepgram_body(transcript="nous avons irrigue", language="fr")),
            ),
        ):
            self.post_voice()

        note = FieldNote.objects.get()
        self.assertEqual(note.status, FieldNote.REFUSED)
        self.assertEqual(note.refusal_reason, "language_not_supported")
        self.assertEqual(note.transcript, "", "an unparseable transcript was stored anyway")

    def test_deepgram_multi_is_not_a_parser_language(self):
        self.assertIsNone(language_for("multi"))
        self.assertEqual(language_for("es"), "es-419")
        self.assertEqual(language_for("es-419"), "es-419")
        self.assertEqual(language_for("pt-BR"), "pt-BR")
        self.assertIsNone(language_for(""))
        self.assertIsNone(language_for(None))

    def test_silence_is_refused_rather_than_stored_as_an_empty_note(self):
        with (
            patch("fieldnotes.services.transcribe.requests.get", return_value=ok_response({})),
            patch(
                "fieldnotes.services.transcribe.requests.post", return_value=ok_response(deepgram_body(transcript="  "))
            ),
        ):
            self.post_voice()

        note = FieldNote.objects.get()
        self.assertEqual(note.status, FieldNote.REFUSED)
        self.assertEqual(note.refusal_reason, "nothing_heard")

    # -------------------------------------------------------------------------------- SSRF

    def test_a_media_reference_off_the_provider_hosts_is_never_fetched(self):
        """The signature answers "did the provider send this", not "is this URL safe to fetch". A
        media reference is fetched SERVER-SIDE with credentials attached, so a URL naming an internal
        address would turn this into a way to read the metadata service."""
        with patch("fieldnotes.services.transcribe.requests.get") as fetch:
            self.post_voice(media="http://169.254.169.254/latest/meta-data/")

        fetch.assert_not_called()
        self.assertEqual(FieldNote.objects.get().refusal_reason, "media_unavailable")

    def test_the_host_check_is_on_the_parsed_host_not_a_substring(self):
        self.assertTrue(media_host_allowed(MEDIA))
        # The two a substring test would wave through.
        self.assertFalse(media_host_allowed("https://api.twilio.com.evil.test/x"))
        self.assertFalse(media_host_allowed("https://evil.test/?x=api.twilio.com"))
        # And plain HTTP, which would put the credentials on the wire.
        self.assertFalse(media_host_allowed("http://api.twilio.com/x"))

    # ------------------------------------------------------------------- announced at the right time

    @override_settings(FIELD_NOTE_RUNNER="worker")
    def test_a_note_still_being_read_announces_nothing(self):
        """The ORDERING, and it needs its own test.

        `test_words_are_announced_once_they_exist` asserts a notification exists after the transcript
        lands. That is true whether or not a second ping also fired at arrival, so it cannot prove
        this. With the `worker` runner nothing transcribes, so the note stays TRANSCRIBING and the
        count is the whole claim: a ping when the audio arrived would send a supervisor to read words
        that do not exist yet.
        """
        with (
            patch("fieldnotes.services.transcribe.requests.get") as fetch,
            patch("fieldnotes.services.transcribe.requests.post") as asr,
        ):
            self.assertEqual(self.post_voice().status_code, 200)

        fetch.assert_not_called()
        asr.assert_not_called()
        self.assertEqual(FieldNote.objects.get().status, FieldNote.TRANSCRIBING)
        self.assertEqual(Notification.objects.count(), 0, "a note nobody can read yet was announced")

    def test_words_are_announced_once_they_exist(self):
        """Paired with the test above, which is the half that pins the ordering."""
        with (
            patch("fieldnotes.services.transcribe.requests.get", return_value=ok_response({})),
            patch("fieldnotes.services.transcribe.requests.post", return_value=ok_response(deepgram_body())),
        ):
            self.post_voice()

        self.assertEqual(FieldNote.objects.get().status, FieldNote.PENDING)
        self.assertGreater(Notification.objects.count(), 0, "a readable note announced nothing")
        for title, message, extra in Notification.objects.values_list("title", "message", "extra_data"):
            body = f"{title} {message} {extra}"
            self.assertNotIn(SPOKEN, body, "the transcript was copied into the notification store")
            self.assertNotIn("bloque 4", body)

    def test_a_note_that_cannot_be_read_still_announces_itself(self):
        with patch("fieldnotes.services.transcribe.requests.get", return_value=ok_response({}, status_code=404)):
            self.post_voice()

        self.assertEqual(FieldNote.objects.get().status, FieldNote.REFUSED)
        self.assertGreater(Notification.objects.count(), 0, "a refusal told nobody")

    def test_a_transcription_failure_parks_the_note_rather_than_leaving_it_being_read(self):
        with patch("fieldnotes.services.transcribe.requests.get", side_effect=RuntimeError("network gone")):
            response = self.post_voice()

        # Still 200: a 500 here makes the provider redeliver a message already stored.
        self.assertEqual(response.status_code, 200)
        note = FieldNote.objects.get()
        self.assertNotEqual(note.status, FieldNote.TRANSCRIBING, "the note is stuck on 'being read' forever")
        self.assertEqual(note.status, FieldNote.REFUSED)

    def test_a_note_discarded_while_the_job_was_queued_is_left_alone(self):
        """The supervisor's decision wins over a job that started before it."""
        from fieldnotes.services.intake import run

        note = FieldNote.objects.create(
            company=self.company,
            establishment=self.farm,
            sender=self.sender,
            sender_phone=self.sender.phone_e164,
            provider=FieldNote.TWILIO,
            provider_message_id="SM-raced",
            kind=FieldNote.VOICE,
            provider_media_ref=MEDIA,
            status=FieldNote.DISCARDED,
        )
        with patch("fieldnotes.services.transcribe.requests.get") as fetch:
            run(note.pk)

        fetch.assert_not_called()
        note.refresh_from_db()
        self.assertEqual(note.status, FieldNote.DISCARDED)


@override_settings(
    TWILIO_AUTH_TOKEN=TOKEN,
    TWILIO_ACCOUNT_SID=ACCOUNT_SID,
    DEEPGRAM_API_KEY="dg-test-key-not-real",
    FIELD_NOTE_RUNNER="eager",
)
class VoicePlaybackAndRetentionTests(APITestCase):
    """Listening is what makes keeping the audio worth anything, and deletion is what bounds it."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(email="play-sup@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Play Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.user.companies.add(self.company)
        self.farm = Establishment.objects.create(name="Play Farm", company=self.company)

        self.stranger = User.objects.create_user(email="play-str@example.com", password="pw-for-tests-only")
        other = Company.objects.create(name="Play Other Co")
        WorksIn.objects.create(user=self.stranger, company=other, role=WorksIn.COMPANY_ADMIN)
        self.stranger.companies.add(other)

        self.note = FieldNote.objects.create(
            company=self.company,
            establishment=self.farm,
            sender_phone="+14155551234",
            sender_display_name="Miguel",
            provider=FieldNote.TWILIO,
            provider_message_id="SM-play-1",
            kind=FieldNote.VOICE,
            provider_media_ref=MEDIA,
            media_content_type="audio/ogg",
            transcript=SPOKEN,
            transcript_language="es-419",
            status=FieldNote.PENDING,
        )

    def audio_url(self, note=None):
        return reverse("field-note-audio", args=[(note or self.note).public_id])

    def test_a_supervisor_can_listen_and_the_bytes_come_through_trazo(self):
        self.client.force_authenticate(user=self.user)
        with patch("fieldnotes.services.transcribe.requests.get", return_value=ok_response({})) as fetch:
            response = self.client.get(self.audio_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "audio/ogg")
        # Proxied, NOT redirected. A 302 would hand the browser a URL carrying no Trazo authorisation,
        # which anyone it was forwarded to could then fetch.
        self.assertNotIn(response.status_code, (301, 302, 303, 307, 308))
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(fetch.call_args.kwargs["auth"], (ACCOUNT_SID, TOKEN))
        self.assertTrue(fetch.call_args.kwargs["stream"], "a 16MB voice note was loaded into memory")

    def test_another_operation_cannot_listen(self):
        self.client.force_authenticate(user=self.stranger)
        with patch("fieldnotes.services.transcribe.requests.get") as fetch:
            response = self.client.get(self.audio_url())

        self.assertEqual(response.status_code, 404)
        fetch.assert_not_called()

    def test_an_anonymous_caller_cannot_listen(self):
        with patch("fieldnotes.services.transcribe.requests.get") as fetch:
            response = self.client.get(self.audio_url())

        self.assertIn(response.status_code, (401, 403))
        fetch.assert_not_called()

    def test_a_deleted_recording_says_so_rather_than_404ing(self):
        FieldNote.objects.filter(pk=self.note.pk).update(audio_deleted_at=timezone.now())
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.audio_url())
        # The supervisor is looking at a transcript and needs to know why there is nothing to play.
        self.assertEqual(response.status_code, 410)

    def test_discarding_a_note_deletes_the_recording_at_the_provider(self):
        self.client.force_authenticate(user=self.user)
        with patch("fieldnotes.services.transcribe.requests.delete", return_value=ok_response({}, 204)) as deleted:
            response = self.client.post(reverse("field-note-discard", args=[self.note.public_id]), {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        deleted.assert_called_once()
        self.assertEqual(deleted.call_args.args[0], MEDIA)
        self.note.refresh_from_db()
        self.assertIsNotNone(self.note.audio_deleted_at, "the row does not record that the audio was released")

    def test_a_failed_delete_does_not_claim_the_audio_is_gone(self):
        self.client.force_authenticate(user=self.user)
        with patch("fieldnotes.services.transcribe.requests.delete", return_value=ok_response({}, 500)):
            self.client.post(reverse("field-note-discard", args=[self.note.public_id]), {}, format="json")

        self.note.refresh_from_db()
        self.assertIsNone(self.note.audio_deleted_at)
        # The reference is KEPT so a later sweep can finish the job.
        self.assertEqual(self.note.provider_media_ref, MEDIA)

    def test_a_failed_delete_does_not_undo_the_discard(self):
        """Every caller of the release is finishing something that already succeeded."""
        self.client.force_authenticate(user=self.user)
        with patch("fieldnotes.services.transcribe.requests.delete", side_effect=RuntimeError("provider down")):
            response = self.client.post(reverse("field-note-discard", args=[self.note.public_id]), {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, FieldNote.DISCARDED)

    def test_a_text_note_has_nothing_to_play(self):
        text = FieldNote.objects.create(
            company=self.company,
            sender_phone="+14155551234",
            provider=FieldNote.TWILIO,
            provider_message_id="SM-play-text",
            kind=FieldNote.TEXT,
            body_text="regamos el bloque 4",
            status=FieldNote.PENDING,
        )
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(self.audio_url(text)).status_code, 404)

    def test_a_text_note_words_are_what_the_sender_typed(self):
        text = FieldNote(kind=FieldNote.TEXT, body_text="typed", transcript="machine guess")
        voice = FieldNote(kind=FieldNote.VOICE, body_text="", transcript="machine guess")
        self.assertEqual(text.words, "typed")
        self.assertEqual(voice.words, "machine guess")
