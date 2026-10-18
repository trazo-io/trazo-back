"""The crew notes review fixture: fictional notes in one ASTRA test company, and nothing else.

What each group protects:

  * the company guards (name, plan, one farm, attester) are what keep this command off a grower;
  * dry run, exact rows and the identical-rerun no-op are the production data-operation rules;
  * "nothing goes out" asserts the reply service, the provider adapter, the arrival ping and the
    mailer are never reached, with on_commit hooks executed so a deferred send would be caught;
  * the inbox tests read the notes back through the real viewset, as the app does;
  * remove deletes only fixture rows and refuses once a note is the provenance of a record.
"""

from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient

from common.models import DataOperationLog
from company.models import Company
from fieldnotes.management.commands import seed_crew_notes_review_fixture as fixture
from fieldnotes.models import CrewSender, FieldNote, FieldNoteConfirmation
from history.models import History
from notifications.models import Notification
from product.models import Establishment, Parcel
from subscriptions.models import Plan, Subscription
from users.models import WorksIn

COMMAND = "seed_crew_notes_review_fixture"
COMPANY_NAME = "ASTRA Test Pilot (not a farm)"


def rows_of(response):
    data = response.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


class FixtureTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", stdout=StringIO(), stderr=StringIO())

    def setUp(self):
        self.company = Company.objects.create(name=COMPANY_NAME)
        Subscription.objects.create(company=self.company, plan=Plan.objects.get(slug="pilot"), status="active")
        self.farm = Establishment.objects.create(name="ASTRA pilot farm", company=self.company)
        self.admin = get_user_model().objects.create_user(email="astra-admin@example.com", password="pw-for-tests")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)

    def run_command(self, *args, company=None):
        out = StringIO()
        call_command(COMMAND, "--company-id", str((company or self.company).pk), *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def counts(self):
        return (
            CrewSender.objects.count(),
            FieldNote.objects.count(),
            DataOperationLog.objects.count(),
            Notification.objects.count(),
        )

    def seed(self):
        return self.run_command("--commit", "--run-by", "test")


class SeedTests(FixtureTestCase):
    def test_dry_run_writes_nothing(self):
        before = self.counts()
        out = self.run_command()
        self.assertIn("DRY RUN", out)
        self.assertEqual(self.counts(), before)

    def test_commit_writes_exactly_the_fixture(self):
        out = self.seed()
        self.assertIn("Fixture seeded.", out)
        self.assertNotIn("FAIL", out)
        self.assertEqual(out.count("PASS"), 10, out)

        senders = list(CrewSender.objects.order_by("phone_e164"))
        self.assertEqual([s.phone_e164 for s in senders], ["+15095550101", "+15095550102"])
        for sender in senders:
            self.assertEqual(sender.company, self.company)
            self.assertEqual(sender.establishment, self.farm)
            self.assertTrue(sender.display_name.startswith("ASTRA TEST"))
            self.assertTrue(sender.may_send)
            self.assertEqual(sender.consent_attested_by, self.admin)
            self.assertEqual(sender.added_by, self.admin)
            self.assertIsNone(sender.first_contact_at)
            self.assertIsNone(sender.consented_at)
        self.assertEqual([s.language for s in senders], ["en-US", "es-419"])

        notes = {n.provider_message_id: n for n in FieldNote.objects.all()}
        self.assertEqual(set(notes), {f"ASTRATEST-CREWNOTE-0{i}" for i in range(1, 6)})
        self.assertEqual(
            {m: (n.status, n.refusal_reason) for m, n in notes.items()},
            {
                "ASTRATEST-CREWNOTE-01": ("pending", ""),
                "ASTRATEST-CREWNOTE-02": ("pending", ""),
                "ASTRATEST-CREWNOTE-03": ("pending", ""),
                "ASTRATEST-CREWNOTE-04": ("pending", ""),
                "ASTRATEST-CREWNOTE-05": ("refused", "empty_message"),
            },
        )
        self.assertIn("Sprayed Entrust 6 fl oz per acre on South Block", notes["ASTRATEST-CREWNOTE-01"].body_text)
        self.assertIn("Cosechamos 30 bins de Gala", notes["ASTRATEST-CREWNOTE-02"].body_text)
        self.assertIn("No fumigamos hoy", notes["ASTRATEST-CREWNOTE-03"].body_text)
        for note in notes.values():
            self.assertEqual(note.company, self.company)
            self.assertEqual(note.establishment, self.farm)
            self.assertEqual(note.kind, FieldNote.TEXT)
            self.assertEqual(note.provider_media_ref, "")
            self.assertTrue(note.sender_display_name.startswith("ASTRA TEST"))
            if note.body_text:
                self.assertTrue(note.body_text.endswith("(ASTRA TEST)"))
        self.assertEqual(notes["ASTRATEST-CREWNOTE-02"].sender.language, "es-419")
        self.assertFalse(FieldNoteConfirmation.objects.exists())

        log = DataOperationLog.objects.get()
        self.assertEqual(log.operation, "seed_crew_notes_review_fixture")
        self.assertEqual(log.run_by, "test")
        self.assertEqual(log.counts["field_note"], 5)
        self.assertEqual(log.counts["crew_sender"], 2)

    def test_identical_rerun_is_a_no_op(self):
        self.seed()
        before = self.counts()
        ids = set(FieldNote.objects.values_list("public_id", flat=True))
        out = self.seed()
        self.assertIn("already in place", out)
        self.assertNotIn("FAIL", out)
        self.assertEqual(self.counts(), before)
        self.assertEqual(set(FieldNote.objects.values_list("public_id", flat=True)), ids)
        for public_id in ids:
            self.assertIn(str(public_id), out)


class RefusalTests(FixtureTestCase):
    def assert_refused(self, fragment, *args, company=None):
        before = self.counts()
        with self.assertRaises(CommandError) as raised:
            self.run_command("--commit", *args, company=company)
        self.assertIn(fragment, str(raised.exception))
        self.assertEqual(self.counts(), before)

    def test_a_company_not_named_astra_test_is_refused(self):
        self.company.name = "Sierra Nut Farms"
        self.company.save()
        self.assert_refused("not an ASTRA test company")

    def test_an_astra_company_without_test_in_its_name_is_refused(self):
        self.company.name = "ASTRA Orchards"
        self.company.save()
        self.assert_refused("not an ASTRA test company")

    def test_a_paid_plan_is_refused(self):
        Subscription.objects.filter(company=self.company).update(plan=Plan.objects.get(slug="compliance-yearly"))
        self.assert_refused("compliance-yearly")

    def test_two_farms_are_refused(self):
        Establishment.objects.create(name="second farm", company=self.company)
        self.assert_refused("has 2 farms")

    def test_an_attester_who_is_not_a_writer_is_refused(self):
        viewer = get_user_model().objects.create_user(email="astra-viewer@example.com", password="pw-for-tests")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.assert_refused("cannot be", "--attested-by", viewer.email)

    def test_two_writers_need_an_explicit_attester(self):
        other = get_user_model().objects.create_user(email="astra-fm@example.com", password="pw-for-tests")
        WorksIn.objects.create(user=other, company=self.company, role=WorksIn.FARM_MANAGER)
        self.assert_refused("Pass --attested-by")
        out = self.run_command("--commit", "--attested-by", other.email)
        self.assertIn("Fixture seeded.", out)
        self.assertTrue(all(s.consent_attested_by == other for s in CrewSender.objects.all()))

    def test_a_rerun_after_the_fixture_changed_is_refused(self):
        self.seed()
        FieldNote.objects.filter(provider_message_id="ASTRATEST-CREWNOTE-03").update(status=FieldNote.DISCARDED)
        self.assert_refused("not exactly what this command writes")

    def test_a_rerun_with_different_words_is_refused(self):
        self.seed()
        FieldNote.objects.filter(provider_message_id="ASTRATEST-CREWNOTE-01").update(body_text="something else")
        self.assert_refused("ASTRATEST-CREWNOTE-01")

    def test_a_partial_fixture_is_refused(self):
        self.seed()
        FieldNote.objects.filter(provider_message_id="ASTRATEST-CREWNOTE-04").delete()
        self.assert_refused("expected")

    def test_a_fixture_phone_on_another_company_is_refused(self):
        other = Company.objects.create(name="Someone else")
        CrewSender.objects.create(company=other, phone_e164="+15095550101", consent_attested_at=timezone.now())
        self.assert_refused("another company")


class NothingGoesOutTests(FixtureTestCase):
    def test_no_reply_provider_notification_or_mail(self):
        # setUp's account and company creation send their own mail; only the seed is under test.
        mail.outbox.clear()
        with (
            mock.patch("fieldnotes.services.reply._send") as send,
            mock.patch("fieldnotes.services.reply.dispatch_first_contact") as first_contact,
            mock.patch("fieldnotes.services.reply.notify_refusal") as refusal,
            mock.patch("fieldnotes.services.reply.adapter_for") as reply_adapter,
            mock.patch("fieldnotes.providers.registry.adapter_for") as adapter,
            mock.patch("fieldnotes.providers.registry.active_adapter") as active,
            mock.patch("fieldnotes.providers.twilio.TwilioWhatsAppAdapter.send_text") as twilio_send,
            mock.patch("fieldnotes.services.transcribe.delete_media") as delete_media,
            mock.patch("fieldnotes.services.arrival.notify_field_note_arrived") as arrival,
            mock.patch("fieldnotes.services.intake.dispatch") as transcribe,
            self.captureOnCommitCallbacks(execute=True) as callbacks,
        ):
            self.seed()
        for patched in (
            send,
            first_contact,
            refusal,
            reply_adapter,
            adapter,
            active,
            twilio_send,
            delete_media,
            arrival,
            transcribe,
        ):
            patched.assert_not_called()
        self.assertEqual(callbacks, [], "the seed scheduled on_commit work")
        self.assertEqual([m.subject for m in mail.outbox], [])
        self.assertFalse(Notification.objects.exists())


class InboxTests(FixtureTestCase):
    def test_the_inbox_returns_the_waiting_notes_and_the_refused_list_the_refusal(self):
        self.seed()
        client = APIClient()
        client.force_authenticate(user=self.admin)

        waiting = rows_of(client.get(reverse("field-note-list"), {"status": "pending"}))
        self.assertEqual(len(waiting), 4)
        words = {row["words"] for row in waiting}
        self.assertIn("Cosechamos 30 bins de Gala en el bloque sur (ASTRA TEST)", words)
        self.assertTrue(all(row["sender"]["display_name"].startswith("ASTRA TEST") for row in waiting))
        entrust = next(row for row in waiting if row["words"].startswith("Sprayed Entrust"))
        self.assertEqual(entrust["suggested_route"], "application")

        refused = rows_of(client.get(reverse("field-note-list"), {"status": "refused"}))
        self.assertEqual([(r["status"], r["refusal_reason"]) for r in refused], [("refused", "empty_message")])

        roster = client.get(reverse("crew-sender-list"), {"company": self.company.pk}).data
        self.assertEqual(len(roster), 2)
        self.assertTrue(all(row["may_send"] for row in roster))

    def test_another_company_does_not_see_the_fixture(self):
        self.seed()
        stranger = get_user_model().objects.create_user(email="stranger@example.com", password="pw-for-tests")
        WorksIn.objects.create(user=stranger, company=Company.objects.create(name="Other"), role="CA")
        client = APIClient()
        client.force_authenticate(user=stranger)
        self.assertEqual(rows_of(client.get(reverse("field-note-list"), {"status": "all"})), [])


class RemoveTests(FixtureTestCase):
    def test_remove_dry_run_deletes_nothing(self):
        self.seed()
        before = self.counts()
        out = self.run_command("--remove")
        self.assertIn("DRY RUN", out)
        self.assertEqual(self.counts(), before)

    def test_remove_deletes_only_fixture_rows_and_logs(self):
        self.seed()
        real_sender = CrewSender.objects.create(
            company=self.company, phone_e164="+14155559999", consent_attested_at=timezone.now()
        )
        real_note = FieldNote.objects.create(
            company=self.company,
            sender=real_sender,
            sender_phone=real_sender.phone_e164,
            provider=FieldNote.TWILIO,
            provider_message_id="SMreal",
            kind=FieldNote.TEXT,
            body_text="regamos",
        )
        out = self.run_command("--remove", "--commit", "--run-by", "test")
        self.assertIn("Removed 5 notes and 2 roster rows", out)
        self.assertEqual(list(FieldNote.objects.all()), [real_note])
        self.assertEqual(list(CrewSender.objects.all()), [real_sender])
        log = DataOperationLog.objects.get(operation="remove_crew_notes_review_fixture")
        self.assertEqual(len(log.counts["ids"]["field_notes"]), 5)
        # And the fixture can be seeded again afterwards.
        self.assertIn("Fixture seeded.", self.seed())

    def test_remove_also_deletes_notes_the_reviewer_discarded_or_acknowledged(self):
        self.seed()
        FieldNote.objects.filter(provider_message_id="ASTRATEST-CREWNOTE-03").update(status=FieldNote.DISCARDED)
        FieldNote.objects.filter(provider_message_id="ASTRATEST-CREWNOTE-05").update(status=FieldNote.ACKNOWLEDGED)
        self.run_command("--remove", "--commit")
        self.assertFalse(FieldNote.objects.exists())

    def confirm_note_04(self):
        """Confirm a fixture note through the wizard's real save, as the reviewer would."""
        parcel = Parcel.objects.create(name="ASTRA lot", establishment=self.farm, area=1)
        season = History.objects.create(parcel=parcel, name="ASTRA season")
        parcel.current_history = season
        parcel.save(update_fields=["current_history"])
        note = FieldNote.objects.get(provider_message_id="ASTRATEST-CREWNOTE-04")
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.post(
            reverse("events-list"),
            {
                "event_type": 3,
                "parcels": [parcel.pk],
                "name": "drip repair",
                "description": "drip repair",
                "date": timezone.now().isoformat(),
                "field_note": str(note.public_id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        note.refresh_from_db()
        self.assertEqual(note.status, FieldNote.CONFIRMED)
        return client, note

    def test_remove_refuses_after_a_note_was_confirmed_into_a_record(self):
        self.seed()
        _client, note = self.confirm_note_04()
        before = self.counts()
        for args in (("--remove",), ("--remove", "--commit")):
            with self.assertRaises(CommandError) as raised:
                self.run_command(*args)
            message = str(raised.exception)
            self.assertIn("ASTRATEST-CREWNOTE-04", message)
            self.assertIn(f"3:{note.fulfilled_by_id}", message)
        self.assertEqual(self.counts(), before)

    def test_remove_refuses_while_a_voided_confirmation_names_a_note(self):
        """Deleting the record requeues the note, but the append-only confirmation history keeps naming it."""
        self.seed()
        client, note = self.confirm_note_04()
        event_id = note.fulfilled_by_id
        response = client.delete(f"{reverse('events-detail', args=[event_id])}?event_type=3")
        self.assertIn(response.status_code, (200, 204), getattr(response, "data", None))
        note.refresh_from_db()
        self.assertEqual(note.status, FieldNote.PENDING)
        self.assertTrue(FieldNoteConfirmation.objects.filter(note=note, voided_at__isnull=False).exists())

        with self.assertRaises(CommandError) as raised:
            self.run_command("--remove")
        self.assertIn(f"3:{event_id} (voided)", str(raised.exception))
        self.assertEqual(FieldNote.objects.count(), 5)

    def test_remove_refuses_a_note_marked_confirmed_without_a_confirmation_row(self):
        self.seed()
        FieldNote.objects.filter(provider_message_id="ASTRATEST-CREWNOTE-02").update(
            status=FieldNote.CONFIRMED, fulfilled_by_event_type=1, fulfilled_by_id=77
        )
        with self.assertRaises(CommandError) as raised:
            self.run_command("--remove", "--commit")
        self.assertIn("1:77", str(raised.exception))
        self.assertEqual(FieldNote.objects.count(), 5)

    def test_remove_refuses_when_a_fixture_phone_has_other_notes(self):
        self.seed()
        sender = CrewSender.objects.get(phone_e164="+15095550101")
        FieldNote.objects.create(
            company=self.company,
            sender=sender,
            sender_phone=sender.phone_e164,
            provider=FieldNote.TWILIO,
            provider_message_id="SMnotfixture",
            kind=FieldNote.TEXT,
            body_text="x",
        )
        with self.assertRaises(CommandError) as raised:
            self.run_command("--remove", "--commit")
        self.assertIn("did not write", str(raised.exception))
        self.assertEqual(FieldNote.objects.count(), 6)

    def test_remove_on_a_non_test_company_is_refused(self):
        self.seed()
        self.company.name = "Sierra Nut Farms"
        self.company.save()
        with self.assertRaises(CommandError):
            self.run_command("--remove", "--commit")
        self.assertEqual(FieldNote.objects.count(), 5)

    def test_remove_with_nothing_seeded_says_so(self):
        self.assertIn("Nothing to remove", self.run_command("--remove", "--commit"))


class FixtureContentTests(TestCase):
    def test_every_fixture_string_is_marked_and_every_phone_is_fictional(self):
        for sender in fixture.SENDERS:
            self.assertTrue(sender["name"].startswith("ASTRA TEST"))
            self.assertRegex(sender["phone"], r"^\+1\d{3}55501\d\d$")
        for _number, _key, words, _status, _reason, _minutes in fixture.NOTES:
            if words:
                self.assertTrue(words.endswith("(ASTRA TEST)"))
