"""A field note becomes a record only through the wizard, and the link is written server-side.

This lives in `history` because it tests `EventViewSet.perform_create`, which is the only place an
event is written. The note app cannot test it: a guard there fails if any of its modules so much as
names an event model.

WHAT EACH RULE IS FOR:

  * `created_by` is the CONFIRMING USER, never anything derived from the note. 7 CFR 205.201(a) makes
    the producer the author, and the packet prints that person. A crew member sending a message is
    the source of the words, not the author of the record.
  * A foreign or stale note is a SILENT NO-OP. Both halves are asserted, because a test that checked
    only for a refusal would pass over a version that loses the grower's save to a stale link.
  * `observation` may not be the sender's words, because that box reaches the ANONYMOUS buyer page.
  * Deleting the record puts the note back in the queue, because `fulfilled_by_*` is a loose
    (type, id) pair with nothing in the database maintaining it.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company
from fieldnotes.models import CrewSender, FieldNote
from history.models import GeneralEvent, History
from product.models import Establishment, Parcel

WORDS = "regamos el bloque 4 esta manana, dos horas"


class FieldNoteConfirmationTests(APITestCase):
    def setUp(self):
        def build(prefix):
            user = get_user_model().objects.create_user(email=f"{prefix}-fn@example.com", password="pw-for-tests-only")
            company = Company.objects.create(name=f"{prefix} FN Co")
            user.companies.add(company)
            est = Establishment.objects.create(name=f"{prefix} FN Farm", company=company)
            parcel = Parcel.objects.create(name=f"{prefix} FN Parcel", establishment=est, area=1)
            history = History.objects.create(parcel=parcel, name=f"{prefix} FN Season")
            parcel.current_history = history
            parcel.save(update_fields=["current_history"])
            sender = CrewSender.objects.create(
                company=company,
                establishment=est,
                phone_e164=f"+1415555{abs(hash(prefix)) % 10000:04d}",
                display_name="Miguel",
                consent_attested_at=timezone.now(),
                consent_attested_by=user,
            )
            note = FieldNote.objects.create(
                company=company,
                establishment=est,
                sender=sender,
                sender_phone=sender.phone_e164,
                sender_display_name="Miguel",
                provider=FieldNote.TWILIO,
                provider_message_id=f"SM-{prefix}",
                kind=FieldNote.TEXT,
                body_text=WORDS,
            )
            return user, parcel, history, note

        self.owner, self.parcel, self.history, self.note = build("owner")
        self.stranger, self.s_parcel, self.s_history, self.s_note = build("stranger")

    def payload(self, **extra):
        body = {
            "event_type": 3,
            "parcels": [self.parcel.pk],
            "name": "irrigation",
            "description": "irrigation",
            "date": timezone.now().isoformat(),
        }
        body.update(extra)
        return body

    # ------------------------------------------------------------------ the happy path, server-side

    def test_confirming_links_the_note_to_the_record_it_answered(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            reverse("events-list"), self.payload(field_note=str(self.note.public_id)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        event = GeneralEvent.objects.get(history=self.history)
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, FieldNote.CONFIRMED)
        self.assertEqual(self.note.fulfilled_by_id, event.id)
        self.assertEqual(self.note.fulfilled_by_event_type, 3)
        self.assertEqual(self.note.confirmed_by, self.owner)
        self.assertIsNotNone(self.note.confirmed_at)

    def test_the_author_of_the_record_is_the_person_who_confirmed_it(self):
        # Never the sender, and never anything derived from the note. The packet prints this person.
        self.client.force_authenticate(user=self.owner)
        self.client.post(reverse("events-list"), self.payload(field_note=str(self.note.public_id)), format="json")
        event = GeneralEvent.objects.get(history=self.history)
        self.assertEqual(event.created_by, self.owner)

    # ------------------------------------------------------------------------- stale and foreign links

    def test_a_note_from_another_company_is_a_silent_no_op(self):
        """BOTH halves. A test that only checked for a refusal would pass over a version that
        throws away the grower's save because a link went stale."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            reverse("events-list"), self.payload(field_note=str(self.s_note.public_id)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, "the grower's save was lost")
        self.assertEqual(GeneralEvent.objects.filter(history=self.history).count(), 1)
        self.s_note.refresh_from_db()
        self.assertEqual(self.s_note.status, FieldNote.PENDING, "a foreign note was touched")
        self.assertIsNone(self.s_note.fulfilled_by_id)

    def test_an_unparseable_field_note_does_not_fail_the_save(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(reverse("events-list"), self.payload(field_note="not-a-uuid"), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_an_already_confirmed_note_is_not_repointed(self):
        """Covered by the RESOLVE, not by the update filter, and that distinction was measured.

        Removing `status=FieldNote.PENDING` from `_confirm_field_note`'s update changed no test:
        `_resolve_field_note` already filters on PENDING, so a confirmed note never reaches the
        update at all. This test therefore passes for a different reason than its name suggests, and
        saying so beats leaving a reader to assume the inner filter is what holds. The unit test
        below covers that filter directly, so both layers are actually exercised.
        """
        self.client.force_authenticate(user=self.owner)
        self.client.post(reverse("events-list"), self.payload(field_note=str(self.note.public_id)), format="json")
        self.note.refresh_from_db()
        first_event_id = self.note.fulfilled_by_id

        self.client.post(reverse("events-list"), self.payload(field_note=str(self.note.public_id)), format="json")
        self.note.refresh_from_db()
        self.assertEqual(self.note.fulfilled_by_id, first_event_id, "a second record repointed the note")

    def test_the_update_itself_also_refuses_a_note_that_is_no_longer_waiting(self):
        """Defence in depth, exercised directly.

        `_confirm_field_note` is handed a note that was resolved earlier in the same request, so
        between the resolve and the update another request could have confirmed or discarded it. The
        update filters on PENDING for that window. Calling the method with an already-confirmed note
        is the only way to reach that filter, since the resolve would otherwise screen it out.
        """
        from history.views import EventViewSet

        event = GeneralEvent.objects.create(history=self.history, name="x", date=timezone.now())
        other_event_id = event.id + 1000

        self.note.status = FieldNote.CONFIRMED
        self.note.fulfilled_by_event_type = 3
        self.note.fulfilled_by_id = other_event_id
        self.note.save(update_fields=["status", "fulfilled_by_event_type", "fulfilled_by_id"])

        class Request:
            pass

        request = Request()
        request.user = self.owner
        viewset = EventViewSet()
        viewset.request = request
        viewset._confirm_field_note(event, 3, self.note)

        self.note.refresh_from_db()
        self.assertEqual(self.note.fulfilled_by_id, other_event_id, "the update repointed a closed note")

    # ------------------------------------------------------------- the sender's words are not published

    def test_observation_identical_to_the_senders_words_is_refused(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            reverse("events-list"),
            self.payload(field_note=str(self.note.public_id), observation=WORDS),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(GeneralEvent.objects.filter(history=self.history).count(), 0)
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, FieldNote.PENDING)

    def test_the_growers_own_words_are_accepted(self):
        # The rule is about republishing somebody else's sentence, not about forbidding notes.
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            reverse("events-list"),
            self.payload(field_note=str(self.note.public_id), observation="Checked the lines myself after."),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_observation_is_unrestricted_when_no_note_is_named(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(reverse("events-list"), self.payload(observation=WORDS), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    # ------------------------------------------------------------------------------ deleting the record

    def test_deleting_the_record_puts_the_note_back_in_the_queue(self):
        self.client.force_authenticate(user=self.owner)
        self.client.post(reverse("events-list"), self.payload(field_note=str(self.note.public_id)), format="json")
        event = GeneralEvent.objects.get(history=self.history)
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, FieldNote.CONFIRMED)

        # ?event_type= is the NUMERIC code; the route does int() on it. Passing "general" was a
        # ValueError in get_queryset, i.e. my test was wrong, not the view.
        response = self.client.delete(f"{reverse('events-detail', args=[event.id])}?event_type=3")
        self.assertIn(response.status_code, (status.HTTP_204_NO_CONTENT, status.HTTP_200_OK), response.data)

        self.note.refresh_from_db()
        # A note reading "logged" whose record is gone is an assertion with nothing behind it.
        self.assertEqual(self.note.status, FieldNote.PENDING)
        self.assertIsNone(self.note.fulfilled_by_id)
        self.assertIsNone(self.note.confirmed_by)
