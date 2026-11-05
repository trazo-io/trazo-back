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
from history.models import ChemicalEvent, EventAmendment, GeneralEvent, History, ProductionPlanItem
from history.services.records_export import export_establishment_records_zip
from product.models import Parcel


class _LinkFixture(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Link Co")
        self.est = Establishment.objects.create(name="Link Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=self.est, area=1)
        self.history = History.objects.create(parcel=parcel, name="2026")
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
        if self.general.pk != self.chemical.pk:
            ChemicalEvent.objects.filter(pk=self.chemical.pk).update(history=self.history)
        amendment = EventAmendment.objects.create(
            history=self.history, event_type=3, event_id=self.general.pk, field_name="x", reason="r"
        )
        self.assertEqual(amendment.activity_id, self.general.activity_id)
        self.assertNotEqual(amendment.activity_id, self.chemical.activity_id)

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
