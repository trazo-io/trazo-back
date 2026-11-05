"""Every event has one Activity: the record's identity across the eight event tables (2026-11).

CommonEvent is abstract, so each event table numbers its own rows: production had 100 ids that
were the same number in two or more tables. The Activity table is additive (no event pk changes)
and becomes the target of real foreign keys in the next slice.
"""

import io
from importlib import import_module

from django.apps import apps
from django.core.management import call_command
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from carbon.models import CarbonEntry
from company.models import Company, Establishment
from history.models import Activity, ChemicalEvent, GeneralEvent, History, ProductionEvent
from history.services.records_export import export_establishment_records_zip
from history.taxonomy import BY_SLUG
from product.models import Parcel


class ActivityIdentityTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Identity Co")
        self.est = Establishment.objects.create(name="Identity Farm", company=company)
        self.parcel = Parcel.objects.create(name="North", establishment=self.est, area=1)
        self.history = History.objects.create(parcel=self.parcel, name="2026")

    def _general(self, **kw):
        return GeneralEvent.objects.create(
            history=self.history, name="g", description="general", date=timezone.now(), **kw
        )

    def _chemical(self):
        return ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Fish",
            description="chemical",
            date=timezone.now(),
        )

    def test_creating_an_event_gives_it_an_activity_of_its_kind(self):
        general, chemical = self._general(), self._chemical()
        self.assertEqual(general.activity.kind, BY_SLUG["general"].code)
        self.assertEqual(chemical.activity.kind, BY_SLUG["chemical"].code)
        self.assertNotEqual(general.activity_id, chemical.activity_id)

    def test_activity_ids_never_equal_an_event_id(self):
        """The sequence starts above every event id (migration 0250)."""
        general = self._general()
        self.assertGreater(general.activity_id, 1_000_000)

    def test_saving_again_keeps_the_same_activity(self):
        general = self._general()
        first = general.activity_id
        general.description = "edited"
        general.save()
        general.save(update_fields=["description"])
        self.assertEqual(general.activity_id, first)
        self.assertEqual(Activity.objects.count(), 1)

    def test_an_identity_less_row_saved_with_update_fields_stores_its_new_identity(self):
        """A row written before the backfill, saved through a narrow update, must keep the
        Activity it gets, not mint one nobody holds."""
        general = self._general()
        GeneralEvent.objects.filter(pk=general.pk).update(activity=None)
        Activity.objects.all().delete()
        general.refresh_from_db()
        general.description = "narrow"
        general.save(update_fields=["description"])
        general.refresh_from_db()
        self.assertIsNotNone(general.activity_id)
        self.assertEqual(Activity.objects.count(), 1)

    def test_positional_update_fields_also_store_the_new_identity(self):
        """Review of back #303: Model.save's 4th positional argument is update_fields."""
        general = self._general()
        GeneralEvent.objects.filter(pk=general.pk).update(activity=None)
        Activity.objects.all().delete()
        general.refresh_from_db()
        general.description = "positional"
        general.save(False, False, None, ["description"])
        general.refresh_from_db()
        self.assertIsNotNone(general.activity_id)
        self.assertEqual(Activity.objects.count(), 1)

    def test_clone_production_reports_every_cloned_table(self):
        """Review of back #303: the per-table line had slipped into the reseal block."""
        self._general()
        self._chemical()
        out = io.StringIO()
        call_command("clone_production", str(self.history.pk), stdout=out)
        self.assertIn("Cloned 1 general event(s)", out.getvalue())
        self.assertIn("Cloned 1 chemical event(s)", out.getvalue())

    def test_deleting_an_event_tombstones_its_activity(self):
        general = self._general()
        activity_id = general.activity_id
        GeneralEvent.objects.filter(pk=general.pk).delete()  # a queryset delete, as views do
        activity = Activity.objects.get(pk=activity_id)
        self.assertIsNotNone(activity.deleted_at)

    def test_an_activity_cannot_be_deleted_under_its_event(self):
        general = self._general()
        with self.assertRaises(ProtectedError):
            Activity.objects.filter(pk=general.activity_id).delete()

    def test_the_identity_is_not_writable_through_the_api_or_a_correction(self):
        from history.amendments import amendable_fields

        self.assertNotIn("activity", [f.name for f in amendable_fields(GeneralEvent)])
        self.assertFalse(GeneralEvent._meta.get_field("activity").editable)

    def test_the_records_export_is_unchanged_by_the_identity(self):
        self._general()
        import zipfile

        archive = zipfile.ZipFile(io.BytesIO(export_establishment_records_zip(self.est)))
        header = archive.read("general_events.csv").decode().splitlines()[0]
        self.assertNotIn("activity", header.split(","))

    def test_the_backfill_gives_every_existing_row_an_activity_without_saving(self):
        general, chemical = self._general(), self._chemical()
        for model in (GeneralEvent, ChemicalEvent):
            model.objects.update(activity=None)
        # Before 0251 nothing pointed at an Activity: the chemical event's carbon entry (linked
        # since carbon 0046, PROTECT) must be unlinked too, or the reset itself is refused.
        CarbonEntry.objects.update(activity=None)
        Activity.objects.all().delete()
        migration = import_module("history.migrations.0251_backfill_activity_identity")
        migration.backfill(apps, None)
        general.refresh_from_db()
        chemical.refresh_from_db()
        self.assertEqual(general.activity.kind, BY_SLUG["general"].code)
        self.assertEqual(chemical.activity.kind, BY_SLUG["chemical"].code)
        migration.backfill(apps, None)  # idempotent
        self.assertEqual(Activity.objects.count(), 2)

    def test_clone_production_gives_clones_their_own_identity_and_seal(self):
        from history import seals

        self._general()
        ProductionEvent.objects.create(history=self.history, type="HA", description="pick", date=timezone.now())
        seals.seal(self.history)
        call_command("clone_production", str(self.history.pk), stdout=io.StringIO())
        clone = History.objects.exclude(pk=self.history.pk).get()
        originals = set(GeneralEvent.objects.filter(history=self.history).values_list("activity_id", flat=True))
        copies = set(GeneralEvent.objects.filter(history=clone).values_list("activity_id", flat=True))
        self.assertTrue(copies)
        self.assertFalse(originals & copies, "a clone must not share its original's identity")
        self.assertEqual(seals.verify(clone).status, seals.INTACT)
