"""The inbox shows a supervisor their own company's notes, and nothing else (2026-09-26).

This viewset has no company in its URL, so nothing narrows it by default: `CompanyNestedViewSet`
does not apply and `ReadOnlyForViewersGlobal` gives read to ANY authenticated user. The tenancy
filter in `get_queryset` is therefore the only thing standing between a supervisor and another
operation's crew messages, which is the same shape as the flat /api/events/ route where exactly that
was missing until 2026-09-16.

It also deliberately cannot create, update or delete. Creating a note by hand would fabricate words
attributed to a named crew member; updating one would change what a person is recorded as having
said; deleting one would erase the fact that they tried to file anything.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company
from fieldnotes.models import FieldNote
from product.models import Establishment
from users.models import WorksIn


def rows_of(response):
    """The list, whether or not pagination is switched on.

    DRF returns a bare list when PAGE_SIZE is unset and an envelope when it is, and the project
    could turn that on at any time. A test that assumed one shape would fail for a reason that has
    nothing to do with what it is checking.
    """
    data = response.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


def make_note(company, establishment=None, *, message_id, words="regamos el bloque 4", **extra):
    return FieldNote.objects.create(
        company=company,
        establishment=establishment,
        sender_phone="+14155551234",
        sender_display_name="Miguel",
        provider=FieldNote.TWILIO,
        provider_message_id=message_id,
        kind=FieldNote.TEXT,
        body_text=words,
        **extra,
    )


class InboxTenancyTests(APITestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(email="own@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Inbox Co")
        WorksIn.objects.create(user=self.owner, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Inbox Farm", company=self.company)
        self.mine = make_note(self.company, self.establishment, message_id="SMmine")

        self.stranger = get_user_model().objects.create_user(email="str@example.com", password="pw-for-tests-only")
        self.other = Company.objects.create(name="Other Inbox Co")
        WorksIn.objects.create(user=self.stranger, company=self.other, role=WorksIn.COMPANY_ADMIN)
        self.theirs = make_note(self.other, message_id="SMtheirs")

    def test_a_supervisor_sees_only_their_own_companys_notes(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(reverse("field-note-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [row["public_id"] for row in rows_of(response)]
        self.assertEqual(ids, [str(self.mine.public_id)])

    def test_another_companys_note_is_404_not_403(self):
        # 404, so the endpoint does not confirm that the note exists.
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(reverse("field-note-detail", args=[self.theirs.public_id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_another_companys_note_cannot_be_discarded(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(reverse("field-note-discard", args=[self.theirs.public_id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.status, FieldNote.PENDING)

    def test_an_anonymous_caller_sees_nothing(self):
        self.assertIn(
            self.client.get(reverse("field-note-list")).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )


class InboxShapeTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="shape@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Shape Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.FARM_MANAGER)
        self.waiting = make_note(self.company, message_id="SMwait")
        self.refused = make_note(
            self.company, message_id="SMref", status=FieldNote.REFUSED, refusal_reason="voice_not_enabled"
        )
        self.client.force_authenticate(user=self.user)

    def test_the_default_list_is_the_queue(self):
        rows = rows_of(self.client.get(reverse("field-note-list")))
        self.assertEqual([r["public_id"] for r in rows], [str(self.waiting.public_id)])

    def test_refused_notes_stay_reachable_rather_than_hidden(self):
        # A note that vanishes is worse than one that says why it could not be read.
        rows = rows_of(self.client.get(reverse("field-note-list"), {"status": "all"}))
        self.assertEqual(len(rows), 2)
        rows = rows_of(self.client.get(reverse("field-note-list"), {"status": FieldNote.REFUSED}))
        self.assertEqual([r["refusal_reason"] for r in rows], ["voice_not_enabled"])

    def test_an_unknown_status_is_a_400_not_an_empty_list(self):
        # An empty list would read as "no notes waiting", which is a different and wrong answer.
        response = self.client.get(reverse("field-note-list"), {"status": "nonsense"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_the_last_four_digits_of_the_number_are_exposed(self):
        row = rows_of(self.client.get(reverse("field-note-list")))[0]
        self.assertEqual(row["sender"], {"display_name": "Miguel", "phone_last4": "1234"})
        self.assertNotIn("+14155551234", str(row))

    def test_provider_identifiers_are_not_exposed(self):
        row = rows_of(self.client.get(reverse("field-note-list")))[0]
        for leaked in ("provider", "provider_message_id", "body_text", "sender_phone"):
            self.assertNotIn(leaked, row, f"{leaked} reached the client")
        # The words themselves are the point, and they arrive under one reader.
        self.assertEqual(row["words"], "regamos el bloque 4")


class InboxCannotWriteNotesTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="ro@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="RO Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.note = make_note(self.company, message_id="SMro")
        self.client.force_authenticate(user=self.user)

    def test_a_note_cannot_be_created_through_the_api(self):
        response = self.client.post(reverse("field-note-list"), {"body_text": "invented"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_a_note_cannot_be_edited_through_the_api(self):
        url = reverse("field-note-detail", args=[self.note.public_id])
        for verb in (self.client.put, self.client.patch):
            self.assertEqual(
                verb(url, {"body_text": "rewritten"}, format="json").status_code,
                status.HTTP_405_METHOD_NOT_ALLOWED,
            )
        self.note.refresh_from_db()
        self.assertEqual(self.note.body_text, "regamos el bloque 4")

    def test_a_note_cannot_be_deleted_through_the_api(self):
        url = reverse("field-note-detail", args=[self.note.public_id])
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(FieldNote.objects.filter(pk=self.note.pk).exists())


class DiscardKeepsTheRowTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="dis@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Discard Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.note = make_note(self.company, message_id="SMdis")
        self.client.force_authenticate(user=self.user)

    def test_discarding_keeps_a_tombstone_with_who_and_why(self):
        response = self.client.post(
            reverse("field-note-discard", args=[self.note.public_id]),
            {"reason": "belongs to the neighbour's block"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.note.refresh_from_db()
        # Kept, not deleted: "we never received it" and "we looked and said no" must stay different
        # answers.
        self.assertEqual(self.note.status, FieldNote.DISCARDED)
        self.assertEqual(self.note.discarded_by, self.user)
        self.assertIsNotNone(self.note.discarded_at)
        self.assertEqual(self.note.discard_reason, "belongs to the neighbour's block")
        self.assertEqual(self.note.body_text, "regamos el bloque 4", "the words were destroyed")

    def test_discarding_twice_is_a_conflict(self):
        self.client.post(reverse("field-note-discard", args=[self.note.public_id]))
        response = self.client.post(reverse("field-note-discard", args=[self.note.public_id]))
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_a_viewer_may_read_but_not_discard(self):
        viewer = get_user_model().objects.create_user(email="vw@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.client.force_authenticate(user=viewer)

        self.assertEqual(self.client.get(reverse("field-note-list")).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.post(reverse("field-note-discard", args=[self.note.public_id])).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, FieldNote.PENDING)


class ConfirmingIsNotAnInboxActionTests(APITestCase):
    def test_there_is_no_confirm_endpoint_on_the_inbox(self):
        """A note becomes a record only through EventViewSet.perform_create.

        If a `confirm` action ever appears here it would be a second writer of the link, and almost
        certainly a writer of the event too. The absence is the design.
        """
        from fieldnotes.views import FieldNoteViewSet

        actions = {
            name for name in dir(FieldNoteViewSet) if getattr(getattr(FieldNoteViewSet, name, None), "mapping", None)
        }
        self.assertIn("discard", actions)
        self.assertNotIn("confirm", actions)
        self.assertNotIn("log", actions)
