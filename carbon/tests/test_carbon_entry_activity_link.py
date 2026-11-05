"""CarbonEntry carries a real link to the activity it was computed from (schema remodel, 2026-11-05).

The text link it replaces matched with `icontains`: a user's description could claim any event,
a pre-February card showed another event's figure, and the delete cleanup left REG-only rows
behind. carbon/event_link.py is the rule; migration 0047 froze a copy of it.
"""

from importlib import import_module

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from carbon.event_link import entries_for_event, link_all_unlinked, named_event
from carbon.models import CarbonAuditLog, CarbonEntry
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from common.services import census
from company.models import Company, Establishment
from history.models import History, PestManagementEvent
from product.models import Parcel


def _description(event, method="test"):
    return f"Auto-calculated from {type(event).__name__}(ID={event.pk}) event: {method}"


class NamedEventTests(TestCase):
    def test_the_writer_shapes_name_their_event(self):
        self.assertEqual(
            named_event("Auto-calculated from ChemicalEvent(ID=7) event: x", "REG-ChemicalEvent-7"),
            ("ChemicalEvent", 7),
        )
        self.assertEqual(
            named_event("Auto-calculated from ChemicalEvent event: x", "REG-ChemicalEvent-7"), ("ChemicalEvent", 7)
        )
        # The registry id names it when the description says nothing else (edited, or empty).
        self.assertEqual(named_event("edited by hand", "REG-ChemicalEvent-7"), ("ChemicalEvent", 7))
        # A suffix a fix command appended keeps the prefix.
        self.assertEqual(
            named_event("Auto-calculated from SoilManagementEvent(ID=3) event: m [CORRECTED: n]", ""),
            ("SoilManagementEvent", 3),
        )

    def test_anything_else_names_nothing(self):
        for description, registry in (
            ("Offset for ProductionEvent(ID=5) from my project", ""),  # contains, not the shape
            ("Auto-calculated from ChemicalEvent(ID=7) event: x", "REG-ChemicalEvent-8"),  # disagree
            ("Auto-calculated from ProductionEvent event: x", "REG-ChemicalEvent-7"),  # other class
            ("Auto-calculated from ChemicalEvent: x", "REG-EVENT-7-2025"),  # old seeder shape
            ("", "REG-12-2025-FUEL"),
        ):
            with self.subTest(description=description, registry=registry):
                self.assertIsNone(named_event(description, registry))


class _Farm(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Link Co")
        self.est = Establishment.objects.create(name="Link Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=self.est, area=1)
        self.season = History.objects.create(parcel=parcel, name="2026", start_date=timezone.now())
        self.other_season = History.objects.create(parcel=parcel, name="2025", start_date=timezone.now())
        self.event = self._pest()
        self.other = self._pest()
        CarbonEntry.objects.all().delete()  # whatever the save receivers wrote
        self.user = get_user_model().objects.create_user(email="link@example.com", password="x")

    def _pest(self, season=None):
        return PestManagementEvent.objects.create(
            history=season or self.season, type="SC", description="scouting", date=timezone.now()
        )

    def _entry(self, description="", registry="", season=None, **kw):
        values = dict(
            production=season or self.season,
            establishment=self.est,
            type="emission",
            amount=2,
            co2e_amount=2,
            year=timezone.now().year,
            description=description,
            registry_verification_id=registry,
        )
        values.update(kw)
        return CarbonEntry.objects.create(**values)

    def _cases(self):
        """One row per rule outcome, all unlinked."""
        gone = self._pest()
        gone_description = _description(gone)
        gone.delete()
        forged = self._entry(_description(self.event), type="offset", co2e_amount=-1)
        CarbonAuditLog.objects.create(carbon_entry=forged, user=self.user, action="create")
        return {
            "current": self._entry(_description(self.event), f"REG-PestManagementEvent-{self.event.pk}"),
            "legacy": self._entry(
                "Auto-calculated from PestManagementEvent event: m", f"REG-PestManagementEvent-{self.other.pk}"
            ),
            "contains_only": self._entry(f"note about PestManagementEvent(ID={self.event.pk})"),
            "disagrees": self._entry(_description(self.event), f"REG-PestManagementEvent-{self.other.pk}"),
            "other_production": self._entry(_description(self.event), season=self.other_season),
            "user_written": forged,
            "event_gone": self._entry(gone_description),
            "manual": self._entry("Diesel for the season"),
        }

    def _activity(self, row):
        row.refresh_from_db()
        return row.activity_id


class WriterTests(_Farm):
    def test_an_entry_written_from_an_event_carries_its_activity(self):
        entry = EventCarbonCalculator().create_carbon_entry_from_event(
            self.event, {"co2e": 1.5, "verification_status": "factors_verified", "data_source": "test"}
        )
        self.assertEqual(entry.activity_id, self.event.activity_id)


class BackfillMigrationTests(_Farm):
    def test_only_the_strict_rule_links_and_no_entry_is_created_or_deleted(self):
        rows = self._cases()
        before = CarbonEntry.objects.count()
        migration = import_module("carbon.migrations.0047_backfill_activity_link")
        migration.backfill(apps, None)
        self.assertEqual(CarbonEntry.objects.count(), before)
        expected = {"current": self.event.activity_id, "legacy": self.other.activity_id}
        for name, row in rows.items():
            with self.subTest(name):
                self.assertEqual(self._activity(row), expected.get(name))

        migration.backfill(apps, None)  # runs again without change
        self.assertEqual(self._activity(rows["current"]), self.event.activity_id)

        migration.unlink(apps, None)
        self.assertFalse(CarbonEntry.objects.filter(activity__isnull=False).exists())

    def test_the_runtime_rule_matches_the_frozen_one(self):
        rows = self._cases()
        counts = link_all_unlinked(apply=False)
        self.assertFalse(CarbonEntry.objects.filter(activity__isnull=False).exists(), "dry run wrote")
        self.assertEqual(counts["linked"], 2)
        self.assertEqual((counts["user_touched"], counts["event_gone"]), (1, 1))
        link_all_unlinked(apply=True)
        linked = set(CarbonEntry.objects.filter(activity__isnull=False).values_list("pk", flat=True))
        self.assertEqual(linked, {rows["current"].pk, rows["legacy"].pk})
        self.assertEqual(link_all_unlinked(apply=True)["linked"], 0)

    def test_the_command_is_a_dry_run_unless_applied(self):
        self._cases()
        call_command("link_carbon_entries", stdout=open("/dev/null", "w"))
        self.assertFalse(CarbonEntry.objects.filter(activity__isnull=False).exists())
        call_command("link_carbon_entries", "--apply", stdout=open("/dev/null", "w"))
        self.assertEqual(CarbonEntry.objects.filter(activity__isnull=False).count(), 2)


class ReadersTests(_Farm):
    def test_a_read_only_lookup_writes_nothing(self):
        straggler = self._entry(_description(self.event))
        self.assertEqual(list(entries_for_event(self.event, link=False)), [straggler])
        self.assertIsNone(self._activity(straggler))
        self.assertEqual(list(entries_for_event(self.event)), [straggler])
        self.assertEqual(self._activity(straggler), self.event.activity_id)

    def test_resaving_an_event_replaces_its_entry_and_spares_a_users_text(self):
        own = self._entry(_description(self.event), activity=self.event.activity)
        forged = self._cases()["user_written"]
        self.event.description = "scouting, edited"
        self.event.save()
        self.assertFalse(CarbonEntry.objects.filter(pk=own.pk).exists())
        self.assertTrue(CarbonEntry.objects.filter(pk=forged.pk).exists(), "a user's offset was deleted")

    def test_deleting_an_event_removes_a_registry_only_entry(self):
        """The delete cleanup matched the description only; REG-only rows outlived the event."""
        legacy = self._entry(
            "Auto-calculated from PestManagementEvent event: m", f"REG-PestManagementEvent-{self.other.pk}"
        )
        self.other.delete()
        self.assertFalse(CarbonEntry.objects.filter(pk=legacy.pk).exists())

    def test_the_event_card_shows_its_own_entry_and_never_anothers(self):
        from history.serializers import PestManagementEventSerializer

        def card(event):
            return PestManagementEventSerializer(event).data.get("carbon_data")

        # Another event's pre-February entry used to be shown on any card of the class.
        self._entry("Auto-calculated from PestManagementEvent event: m", f"REG-PestManagementEvent-{self.other.pk}")
        self._cases()  # forged, contains-only, other production...
        self.assertIsNone(card(self.event))
        self._entry(_description(self.event), activity=self.event.activity, co2e_amount=4.25)
        self.assertEqual(card(self.event)["co2e"], 4.25)


class CensusTests(_Farm):
    def test_the_census_counts_stragglers_and_a_compare_flags_growth(self):
        rows = self._cases()
        facts = census._class_name_as_data_facts()["carbon_entry_activity_link"]
        self.assertEqual(facts["live_target_unlinked"]["ids"], sorted([rows["current"].pk, rows["legacy"].pk]))
        self.assertEqual(facts["linked"], 0)

        link_all_unlinked(apply=True)
        after = census._class_name_as_data_facts()["carbon_entry_activity_link"]
        self.assertEqual((after["linked"], after["live_target_unlinked"]["count"]), (2, 0))
        self.assertEqual(after["disagrees_with_text"]["count"], 0)

        CarbonEntry.objects.filter(pk=rows["current"].pk).update(activity_id=self.other.activity_id)
        moved = census._class_name_as_data_facts()["carbon_entry_activity_link"]
        self.assertEqual(moved["disagrees_with_text"]["ids"], [rows["current"].pk])
