"""A refusal a person has seen can be cleared, and nothing else can be (2026-09-30).

WHAT WAS WRONG. `discard` answers 409 for anything that is not PENDING, so a REFUSED note could not
be cleared by anyone, ever. The waiting queue drains as notes are logged or discarded; the refused
list did not. Every unsupported-language message, failed transcription, photo with no caption and
over-budget day stayed on the page for the life of the account, and the crew roster and channel
cards render BELOW it, so the scroll to reach setup grew without bound. Found by the product owner
asking whether a farmer with a lot of field notes has to scroll to add a crew number.

WHY A THIRD STATUS. Letting `discard` take a refused note needs no migration and is wrong.
DISCARDED records that the OPERATION decided the message was not an event; a refusal is Trazo
failing to read one. Collapsing them leaves anyone reading the trail unable to tell "we looked and
said no" from "we never got to look".

WHAT THESE GUARD, each one a way this can go wrong:

  * A WAITING note cannot be acknowledged. Otherwise this is a way to make a crew member's message
    disappear without logging it or recording a decision about it, which is the one outcome the
    whole surface exists to prevent.
  * The three terminal facts stay DISTINCT on the row, so the trail can still be read.
  * The recording is released, and playback stops. A refused voice note keeps its audio because the
    recording is its only content; once a person has seen the refusal that reason is spent.
  * Cross-tenant acknowledge is refused, and a VIEWER cannot acknowledge. Clearing somebody else's
    queue item is a write.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company
from fieldnotes.models import FieldNote
from users.models import WorksIn


def make_note(company, *, message_id, note_status, **extra):
    return FieldNote.objects.create(
        company=company,
        sender_phone="+14155551234",
        sender_display_name="Miguel",
        provider=FieldNote.TWILIO,
        provider_message_id=message_id,
        kind=FieldNote.TEXT,
        body_text="regamos el bloque 4",
        status=note_status,
        **extra,
    )


class AcknowledgeTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Ack Co")
        self.admin = get_user_model().objects.create_user(email="ack@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.refused = make_note(
            self.company, message_id="SMref", note_status=FieldNote.REFUSED, refusal_reason="language_not_supported"
        )
        self.client.force_authenticate(user=self.admin)

    def url_for(self, note):
        return reverse("field-note-acknowledge", args=[note.public_id])

    def test_a_refusal_can_be_cleared(self):
        response = self.client.post(self.url_for(self.refused))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.refused.refresh_from_db()
        self.assertEqual(self.refused.status, FieldNote.ACKNOWLEDGED)
        self.assertEqual(self.refused.acknowledged_by, self.admin)
        self.assertIsNotNone(self.refused.acknowledged_at)

    def test_it_leaves_the_refused_list(self):
        """The whole point: the list has to drain or the page grows forever."""
        self.client.post(self.url_for(self.refused))
        listed = self.client.get(reverse("field-note-list"), {"status": "refused"})
        rows = listed.data["results"] if isinstance(listed.data, dict) and "results" in listed.data else listed.data
        self.assertEqual(rows, [])

    def test_the_row_still_says_why_it_could_not_be_read(self):
        # `refusal_reason` is NOT cleared. The machine's answer is the record of what happened, and
        # acknowledging is a second fact on top of it, not a replacement for it.
        self.client.post(self.url_for(self.refused))
        self.refused.refresh_from_db()
        self.assertEqual(self.refused.refusal_reason, "language_not_supported")

    def test_the_three_terminal_facts_stay_distinct(self):
        """DISCARDED is not reused, and this is the reason the migration exists.

        A reader of the trail has to be able to tell a message the operation judged not to be an
        event from one Trazo could not read. Acknowledging must not touch the discard stamps.
        """
        self.client.post(self.url_for(self.refused))
        self.refused.refresh_from_db()
        self.assertEqual(self.refused.status, FieldNote.ACKNOWLEDGED)
        self.assertIsNone(self.refused.discarded_at)
        self.assertIsNone(self.refused.discarded_by)
        self.assertEqual(self.refused.discard_reason, "")
        self.assertIsNone(self.refused.confirmed_at)

    def test_a_waiting_note_cannot_be_acknowledged(self):
        """The dangerous case. Otherwise this endpoint is a way to make a crew member's message
        vanish without logging it or recording a decision about it."""
        waiting = make_note(self.company, message_id="SMwait", note_status=FieldNote.PENDING)
        response = self.client.post(self.url_for(waiting))
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, FieldNote.PENDING)

    def test_a_note_still_being_read_cannot_be_acknowledged(self):
        # There are no words yet, so there is nothing anybody could have seen.
        reading = make_note(self.company, message_id="SMtr", note_status=FieldNote.TRANSCRIBING)
        self.assertEqual(self.client.post(self.url_for(reading)).status_code, status.HTTP_409_CONFLICT)

    def test_acknowledging_twice_is_refused_rather_than_restamped(self):
        # A second call must not move `acknowledged_at`, which would make the row claim a person
        # looked at it later than they did.
        self.client.post(self.url_for(self.refused))
        self.refused.refresh_from_db()
        first = self.refused.acknowledged_at
        self.assertEqual(self.client.post(self.url_for(self.refused)).status_code, status.HTTP_409_CONFLICT)
        self.refused.refresh_from_db()
        self.assertEqual(self.refused.acknowledged_at, first)

    def test_a_logged_note_cannot_be_acknowledged(self):
        logged = make_note(
            self.company, message_id="SMdone", note_status=FieldNote.CONFIRMED, confirmed_at=timezone.now()
        )
        self.assertEqual(self.client.post(self.url_for(logged)).status_code, status.HTTP_409_CONFLICT)


class AcknowledgeReleasesTheRecordingTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Ack Audio Co")
        self.admin = get_user_model().objects.create_user(email="acka@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.note = FieldNote.objects.create(
            company=self.company,
            sender_phone="+14155551234",
            provider=FieldNote.TWILIO,
            provider_message_id="SMvoice",
            kind=FieldNote.VOICE,
            status=FieldNote.REFUSED,
            refusal_reason="nothing_heard",
            provider_media_ref="https://api.twilio.com/2010-04-01/Accounts/ACx/Messages/MMx/Media/MEx",
            media_content_type="audio/ogg",
        )
        self.client.force_authenticate(user=self.admin)

    def test_the_recording_is_deleted_at_the_provider(self):
        """A refused voice note keeps its audio ON PURPOSE: the recording is its only content, and a
        supervisor listening and typing it out is the reason the channel does not silently drop it.
        Acknowledging is the moment that reason is spent."""
        with patch("fieldnotes.services.transcribe.delete_media", return_value=True) as deleted:
            response = self.client.post(reverse("field-note-acknowledge", args=[self.note.public_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deleted.assert_called_once()
        self.note.refresh_from_db()
        self.assertIsNotNone(self.note.audio_deleted_at)

    def test_playback_stops_even_if_the_provider_delete_failed(self):
        """The status is the authority on whether anyone still has business listening; the stamp only
        records whether the cleanup succeeded. Same rule `audio` already applies to logged and
        discarded notes."""
        with patch("fieldnotes.services.transcribe.delete_media", return_value=False):
            self.client.post(reverse("field-note-acknowledge", args=[self.note.public_id]))
        self.note.refresh_from_db()
        self.assertIsNone(self.note.audio_deleted_at)  # the delete really did fail
        playback = self.client.get(reverse("field-note-audio", args=[self.note.public_id]))
        self.assertEqual(playback.status_code, status.HTTP_410_GONE)

    def test_the_sweep_treats_it_as_finished_rather_than_waiting_out_a_window(self):
        """`release_stale_field_note_audio` has two groups. ACKNOWLEDGED belongs with confirmed and
        discarded: a person has acted, so a failed release is a retry rather than something to age
        out. Leaving it in the time-based group would keep a recording for the whole window after
        the operator was done with it."""
        from io import StringIO

        from django.core.management import call_command

        with patch("fieldnotes.services.transcribe.delete_media", return_value=False):
            self.client.post(reverse("field-note-acknowledge", args=[self.note.public_id]))
        with patch("fieldnotes.services.transcribe.delete_media", return_value=True) as deleted:
            call_command("release_stale_field_note_audio", stdout=StringIO())
        # Swept on this run, with no --days elapsed, because the note is finished.
        deleted.assert_called_once()


class AcknowledgeTenancyTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Mine Co")
        self.other = Company.objects.create(name="Theirs Co")
        self.owner = get_user_model().objects.create_user(email="own2@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.owner, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.viewer = get_user_model().objects.create_user(email="vw2@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.viewer, company=self.company, role=WorksIn.VIEWER)
        self.theirs = make_note(self.other, message_id="SMtheirs", note_status=FieldNote.REFUSED)
        self.mine = make_note(self.company, message_id="SMmine", note_status=FieldNote.REFUSED)

    def test_another_operations_refusal_is_404_not_403(self):
        # 404, so the endpoint does not confirm the note exists. Same as the detail route.
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(reverse("field-note-acknowledge", args=[self.theirs.public_id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.status, FieldNote.REFUSED)

    def test_a_viewer_cannot_acknowledge(self):
        # Clearing a queue item is a write. `ReadOnlyForViewersGlobal` refuses a POST from somebody
        # holding no elevated role anywhere.
        self.client.force_authenticate(user=self.viewer)
        response = self.client.post(reverse("field-note-acknowledge", args=[self.mine.public_id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, FieldNote.REFUSED)

    def test_an_anonymous_caller_cannot_acknowledge(self):
        response = self.client.post(reverse("field-note-acknowledge", args=[self.mine.public_id]))
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
