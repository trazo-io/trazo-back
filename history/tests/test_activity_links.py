"""Loose (event_type, event_id) pairs carry a real foreign key to the record's Activity (2026-11).

Phase 2 of the schema remodel plan, expand step: each mutable model that points at an event
through a pair gets an Activity FK written by every writer, next to the pair. Readers move in a
later slice. These tests pin the writers that are not covered by the plan-item and crew-note tests
(which assert the identity at their own fulfil, confirm, reopen and requeue points).
"""

import io
from importlib import import_module

from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from common.services import census as census_svc
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from documents.services.filing import file_document
from history.activity_ref import activity_id_for
from history.models import ChemicalEvent, EventAmendment, GeneralEvent, Production, ProductionPlanItem
from history.services.records_export import export_establishment_records_zip
from product.models import Parcel


class _LinkFixture(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Link Co")
        self.est = Establishment.objects.create(name="Link Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=self.est, area=1)
        self.history = Production.objects.create(parcel=parcel, name="2026")
        self.general = GeneralEvent.objects.create(
            history=self.history, name="g", description="general", date=timezone.now()
        )
        self.chemical = ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Fish",
            description="chemical",
            date=timezone.now(),
        )

    def chemical_sharing_the_general_pk(self):
        """A ChemicalEvent whose pk IS the GeneralEvent's: the collision the identity exists for.

        Made explicitly (review of #424): the per-table sequences only coincide by luck, and the
        guard this replaces (`update(history=...)`) never changed a pk, so the assertion against
        the other table could pass without the collision ever existing.
        """
        if self.chemical.pk == self.general.pk:
            return self.chemical
        return ChemicalEvent.objects.create(
            pk=self.general.pk,
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Fish",
            description="chemical at the general pk",
            date=timezone.now(),
        )


class ActivityLinkTests(_LinkFixture):
    def test_the_resolver_answers_the_identity_or_none(self):
        self.assertEqual(activity_id_for(2, self.chemical.pk), self.chemical.activity_id)
        self.assertIsNone(activity_id_for(2, 999_999))
        self.assertIsNone(activity_id_for(None, None))
        self.assertIsNone(activity_id_for(42, self.chemical.pk))

    def test_an_amendment_links_the_record_it_corrects(self):
        amendment = EventAmendment.objects.create(
            history=self.history, event_type=2, event_id=self.chemical.pk, field_name="x", reason="r"
        )
        self.assertEqual(amendment.activity_id, self.chemical.activity_id)

    def test_a_season_header_amendment_links_nothing(self):
        amendment = EventAmendment.objects.create(history=self.history, field_name="x", reason="r")
        self.assertIsNone(amendment.activity_id)

    def test_same_number_other_table_is_never_confused(self):
        """The bug class the identity exists for: one pk, two tables."""
        twin = self.chemical_sharing_the_general_pk()
        self.assertEqual(twin.pk, self.general.pk)
        amendment = EventAmendment.objects.create(
            history=self.history, event_type=3, event_id=self.general.pk, field_name="x", reason="r"
        )
        self.assertEqual(amendment.activity_id, self.general.activity_id)
        self.assertNotEqual(amendment.activity_id, twin.activity_id)

    def test_a_filed_document_links_its_record_and_follows_a_changed_pair(self):
        doc = file_document(
            establishment=self.est,
            source=GeneratedDocument._meta.get_field("source").choices[0][0],
            folder=GeneratedDocument._meta.get_field("folder").choices[0][0],
            title="receipt",
            filename="r.txt",
            content=b"x",
            event_type=2,
            event_id=self.chemical.pk,
        )
        self.assertEqual(doc.activity_id, self.chemical.activity_id)
        doc.event_type, doc.event_id = 3, self.general.pk
        doc.save(update_fields=["event_type", "event_id"])
        doc.refresh_from_db()
        self.assertEqual(doc.activity_id, self.general.activity_id)

    def test_the_backfill_links_existing_pairs_and_leaves_orphans_unlinked(self):
        linked = EventAmendment.objects.create(
            history=self.history, event_type=2, event_id=self.chemical.pk, field_name="x", reason="r"
        )
        orphan = EventAmendment.objects.create(
            history=self.history, event_type=2, event_id=999_999, field_name="x", reason="r"
        )
        item = ProductionPlanItem.objects.create(
            history=self.history, event_type=2, name="t", fulfilled_by_event_type=3, fulfilled_by_id=self.general.pk
        )
        EventAmendment.objects.update(activity=None)
        migration = import_module("history.migrations.0253_backfill_activity_link")
        migration.backfill(apps, None)
        for row in (linked, orphan, item):
            row.refresh_from_db()
        self.assertEqual(linked.activity_id, self.chemical.activity_id)
        self.assertIsNone(orphan.activity_id)
        self.assertEqual(item.fulfilled_by_activity_id, self.general.activity_id)

    def test_the_census_finds_an_unlinked_or_disagreeing_link(self):
        a = EventAmendment.objects.create(
            history=self.history, event_type=2, event_id=self.chemical.pk, field_name="x", reason="r"
        )
        facts = census_svc._loose_pair_facts()["history.EventAmendment"]["activity_link"]
        self.assertEqual((facts["live_target_unlinked"]["count"], facts["disagrees_with_pair"]["count"]), (0, 0))
        EventAmendment.objects.filter(pk=a.pk).update(activity_id=self.general.activity_id)
        facts = census_svc._loose_pair_facts()["history.EventAmendment"]["activity_link"]
        self.assertEqual(facts["disagrees_with_pair"]["ids"], [a.pk])
        EventAmendment.objects.filter(pk=a.pk).update(activity=None)
        facts = census_svc._loose_pair_facts()["history.EventAmendment"]["activity_link"]
        self.assertEqual(facts["live_target_unlinked"]["ids"], [a.pk])

    def test_the_records_export_does_not_grow_identity_columns(self):
        import zipfile

        archive = zipfile.ZipFile(io.BytesIO(export_establishment_records_zip(self.est)))
        for name in archive.namelist():
            header = archive.read(name).decode().splitlines()
            header = next((line for line in header if "," in line), "")
            columns = set(header.split(","))
            with self.subTest(csv=name):
                # GeneralEvent's own `activity_type` / `activity_name` are recorded fields and stay.
                self.assertFalse(
                    columns & {"activity", "activity_id", "fulfilled_by_activity", "fulfilled_by_activity_id"},
                    header,
                )


class TombstoneLinksSurviveResavesTests(_LinkFixture):
    """Review of back #306: re-deriving the link from the pair on every save nulled it once the
    event was gone, so a PATCH of a document's title after its record was deleted lost the link
    to the record's tombstone."""

    def test_a_document_keeps_its_link_to_a_deleted_records_tombstone(self):
        doc = file_document(
            establishment=self.est,
            source=GeneratedDocument._meta.get_field("source").choices[0][0],
            folder=GeneratedDocument._meta.get_field("folder").choices[0][0],
            title="receipt",
            filename="r.txt",
            content=b"x",
            event_type=2,
            event_id=self.chemical.pk,
        )
        activity_id = self.chemical.activity_id
        ChemicalEvent.objects.filter(pk=self.chemical.pk).delete()
        doc.title = "renamed"
        doc.save(update_fields=["title"])
        doc.refresh_from_db()
        self.assertEqual(doc.activity_id, activity_id)
        self.assertIsNotNone(doc.activity.deleted_at)

    def test_an_amendment_keeps_its_link_to_a_deleted_records_tombstone(self):
        amendment = EventAmendment.objects.create(
            history=self.history, event_type=2, event_id=self.chemical.pk, field_name="x", reason="r"
        )
        activity_id = amendment.activity_id
        ChemicalEvent.objects.filter(pk=self.chemical.pk).delete()
        amendment.reason = "resaved"
        amendment.save()
        amendment.refresh_from_db()
        self.assertEqual(amendment.activity_id, activity_id)

    def test_a_pair_changed_to_nothing_unlinks(self):
        amendment = EventAmendment.objects.create(
            history=self.history, event_type=2, event_id=self.chemical.pk, field_name="x", reason="r"
        )
        amendment.event_id = 999_999
        amendment.save()
        amendment.refresh_from_db()
        self.assertIsNone(amendment.activity_id)


class ConfirmationLinkTests(_LinkFixture):
    """Slice B (2026-11-14): FieldNoteConfirmation, the append-only record of a crew note confirmed
    into a record, gets the identity next to its pair."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model

        from fieldnotes.models import CrewSender, FieldNote

        self.user = get_user_model().objects.create_user(email="confirm@example.com", password="pw-for-tests-only")
        sender = CrewSender.objects.create(
            company=self.est.company,
            establishment=self.est,
            phone_e164="+14155550199",
            display_name="Miguel",
            consent_attested_at=timezone.now(),
            consent_attested_by=self.user,
        )
        self.note = FieldNote.objects.create(
            company=self.est.company,
            establishment=self.est,
            sender=sender,
            sender_phone=sender.phone_e164,
            sender_display_name="Miguel",
            provider=FieldNote.TWILIO,
            provider_message_id="SM-link",
            kind=FieldNote.TEXT,
            body_text="regamos el bloque 4",
        )

    def _confirm(self, event_type, event):
        from fieldnotes.services.confirmation import record_confirmation

        return record_confirmation(self.note, event, event_type, self.user, {}, timezone.now())

    def test_a_confirmation_links_the_record_it_confirmed(self):
        self.assertEqual(self._confirm(2, self.chemical).activity_id, self.chemical.activity_id)

    def test_the_other_table_with_the_same_number_is_never_named(self):
        twin = self.chemical_sharing_the_general_pk()
        self.assertEqual(twin.pk, self.general.pk)
        row = self._confirm(3, self.general)
        self.assertEqual(row.activity_id, self.general.activity_id)
        self.assertNotEqual(row.activity_id, twin.activity_id)

    def test_a_writer_that_only_holds_the_pair_still_links(self):
        """save() resolves the pair, so it is the path where the table must decide: the pair names
        the GeneralEvent while a ChemicalEvent holds the same pk."""
        from fieldnotes.models import FieldNoteConfirmation

        twin = self.chemical_sharing_the_general_pk()
        row = FieldNoteConfirmation.objects.create(
            note=self.note,
            company=self.est.company,
            event_type=3,
            event_id=self.general.pk,
            confirmed_at=timezone.now(),
        )
        self.assertEqual(row.activity_id, self.general.activity_id)
        self.assertNotEqual(row.activity_id, twin.activity_id)

    def test_voiding_after_the_record_is_deleted_keeps_the_tombstone_link(self):
        from fieldnotes.services.confirmation import void_confirmations

        row = self._confirm(2, self.chemical)
        activity_id = row.activity_id
        ChemicalEvent.objects.filter(pk=self.chemical.pk).delete()
        self.assertEqual(void_confirmations(2, self.chemical.pk, "record deleted", timezone.now()), 1)
        row.refresh_from_db()
        self.assertIsNotNone(row.voided_at)
        self.assertEqual(row.activity_id, activity_id)
        self.assertIsNotNone(row.activity.deleted_at)

    def test_the_backfill_writes_only_the_link_on_the_append_only_rows(self):
        """Run against the migration's own historical models: the live manager refuses `.update()`,
        which is the guard the backfill must step around without touching any recorded value."""
        from django.db import connection
        from django.db.migrations.loader import MigrationLoader

        from fieldnotes.models import FieldNoteConfirmation

        linked = self._confirm(2, self.chemical)
        orphan = FieldNoteConfirmation.objects.create(
            note=self.note, company=self.est.company, event_type=2, event_id=999_999, confirmed_at=timezone.now()
        )
        before = dict(FieldNoteConfirmation.objects.filter(pk=linked.pk).values("confirmed_values", "source")[0])
        state_apps = (
            MigrationLoader(connection).project_state(("fieldnotes", "0009_backfill_confirmation_activity_link")).apps
        )
        state_apps.get_model("fieldnotes", "FieldNoteConfirmation").objects.update(activity=None)
        import_module("fieldnotes.migrations.0009_backfill_confirmation_activity_link").backfill(state_apps, None)
        linked.refresh_from_db()
        orphan.refresh_from_db()
        self.assertEqual(linked.activity_id, self.chemical.activity_id)
        self.assertIsNone(orphan.activity_id)
        self.assertEqual(
            dict(FieldNoteConfirmation.objects.filter(pk=linked.pk).values("confirmed_values", "source")[0]), before
        )

    def test_the_census_checks_the_confirmation_link(self):
        from fieldnotes.models import FieldNoteConfirmation

        row = self._confirm(2, self.chemical)
        facts = census_svc._loose_pair_facts()["fieldnotes.FieldNoteConfirmation"]["activity_link"]
        self.assertEqual((facts["linked"], facts["live_target_unlinked"]["count"]), (1, 0))
        FieldNoteConfirmation._base_manager.filter(pk=row.pk).update(activity=None)
        facts = census_svc._loose_pair_facts()["fieldnotes.FieldNoteConfirmation"]["activity_link"]
        self.assertEqual(facts["live_target_unlinked"]["ids"], [row.pk])
