"""recompute_soil_carbon: stale soil CarbonEntry rows after the 2026-10-28 soil methodology.

Rows written before the soil changes still carry the old tillage flux (61 kg for 1 acre), a
"from recorded inputs" label on an area estimate, and 0.41 kg on a lab analysis. The command
recomputes them under the production safety rule: dry run by default, a plan with fingerprints,
an apply that refuses a record changed since the plan, a restore file that reverts exactly.

Each test below pins one line of that contract.
"""

import io
import json
import os
import re
import tempfile
from decimal import Decimal
from pathlib import Path

from django.core import serializers
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.forms.models import model_to_dict
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from carbon.models import CarbonEntry, USDACalculationAudit, USDAComplianceRecord
from carbon.services.calculator_service import CarbonCalculatorService
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from common.models import DataOperationLog
from company.models import Company, Establishment
from history.models import EventAmendment, History, SoilManagementEvent
from product.models import Parcel, Product
from users.models import User

OLD_STATUS = "usda_ipcc_factors_verified"
ONE_ACRE_HA = 0.404686
#: Tillage with no fuel recorded: the published cultivation diesel estimate, 3.2 gal/ha x 10.21 kg/gal
#: (landing review #35, 2026-10-28), labelled area_estimate.
TILLAGE_KG_PER_HA = 3.2 * 10.21
TILLAGE_ONE_ACRE = TILLAGE_KG_PER_HA * ONE_ACRE_HA
#: Tables a recompute may write. Everything else (the event row, History, OSP filings, DMS
#: documents) must stay out of every INSERT, UPDATE and DELETE.
WRITABLE_TABLES = {
    "carbon_carbonentry",
    "carbon_carbonsource",
    "carbon_carbonauditlog",  # dependents of an entry, removed with it
    "carbon_verification_audit",
    "carbon_usda_compliance_record",
    "carbon_usda_calculation_audit",
    "common_dataoperationlog",
}


def _all_carbon_rows(history):
    """Every carbon row of the season, serialised, for exact before/after comparison."""
    entries = list(CarbonEntry.objects.filter(production=history).order_by("pk"))
    rows = list(entries)
    rows += list(USDAComplianceRecord.objects.filter(carbon_entry__in=entries).order_by("pk"))
    rows += list(USDACalculationAudit.objects.filter(carbon_entry__in=entries).order_by("pk"))
    return json.loads(serializers.serialize("json", rows))


class RecomputeSoilCarbonBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="soilrecompute@test.com", password="x")
        company = Company.objects.create(name="Orchard Co")
        self.establishment = Establishment.objects.create(name="Home Orchard", company=company, state="OR")
        self.company = company
        self.history = self._season("Duke 2026")
        self.tillage = self._event(self.history, "TI", description="Cultivator pass")
        self.lab = self._event(self.history, "LA", description="Irrigation water analysis", sample_matrix="water")
        self.fueled = self._event(
            self.history,
            "TI",
            description="Disc, fuel recorded",
            fuel_consumed=Decimal("3"),
            fuel_unit="gal",
            fuel_type="diesel",
        )
        # The signal wrote today's figures. Rewrite the first two as the old rule stored them.
        self.stale_tillage = self._stale(self.tillage, 61.0, OLD_STATUS, True, "usda_area_scaled_soil_factors")
        self.stale_lab = self._stale(self.lab, 0.405, OLD_STATUS, True, "usda_area_scaled_soil_factors")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    # -- builders --------------------------------------------------------------------
    def _season(self, name):
        return History.objects.create(
            name=name,
            start_date=timezone.now(),
            product=Product.objects.create(name="Blueberries"),
            parcel=Parcel.objects.create(name=f"Field {name}", establishment=self.establishment, area=5.0),
            operator=self.user,
            production_amount=1000,
            production_unit="kg",
        )

    def _event(self, history, subtype, **fields):
        fields.setdefault("area_covered", Decimal("1"))
        fields.setdefault("area_unit", "acres")
        event = SoilManagementEvent.objects.create(
            history=history, type=subtype, date=timezone.now(), created_by=self.user, **fields
        )
        event.refresh_from_db()
        return event

    def _entries(self, event):
        return CarbonEntry.objects.filter(
            production=event.history, description__icontains=f"SoilManagementEvent(ID={event.id})"
        )

    def _stale(self, event, co2e, status, flag, method, *, created_by=None):
        """An entry as the old rule stored it, with its compliance and audit rows."""
        self._entries(event).delete()
        entry = CarbonEntry.objects.create(
            production=event.history,
            establishment=self.establishment,
            type="emission",
            amount=co2e,
            co2e_amount=co2e,
            year=2026,
            timestamp=event.date,
            description=f"Auto-calculated from SoilManagementEvent(ID={event.id}) event: {method}",
            registry_verification_id=f"REG-SoilManagementEvent-{event.id}",
            usda_factors_based=flag,
            verification_status=status,
            data_source="USDA ARS | Reicosky 1997",
            created_by=created_by,
            baseline_data={"soil_activity": event.type},
        )
        USDAComplianceRecord.objects.create(
            carbon_entry=entry,
            production=event.history,
            compliance_status="compliant",
            confidence_score=0.9,
            confidence_level="high",
            crop_type="blueberries",
            state="OR",
        )
        USDACalculationAudit.objects.create(
            event_type="soil_management",
            event_id=event.id,
            carbon_entry=entry,
            input_data={"old": True},
            calculation_method=method,
            calculated_co2e=co2e,
            confidence_score=0.5,
            calculation_time_ms=3,
            calculated_by=self.user,
        )
        return entry

    # -- runners ---------------------------------------------------------------------
    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def run_cmd(self, *args):
        out = io.StringIO()
        call_command("recompute_soil_carbon", *args, stdout=out)
        return out.getvalue()

    def dry_run(self, name="plan.json", *extra):
        text = self.run_cmd("--report", self.path(name), *extra)
        return json.loads(Path(self.path(name)).read_text()), text

    def apply(self, plan="plan.json", restore="restore.json", *extra):
        return self.run_cmd("--apply", self.path(plan), "--restore-file", self.path(restore), *extra)

    @staticmethod
    def record(plan, event):
        return next(r for r in plan["records"] if r["event_id"] == event.pk)


class DryRunReport(RecomputeSoilCarbonBase):
    def test_stale_tillage_shows_old_vs_new_and_a_dry_run_saves_nothing(self):
        before = _all_carbon_rows(self.history)
        plan, text = self.dry_run()

        rec = self.record(plan, self.tillage)
        self.assertEqual(rec["classification"], "figure_changed")
        self.assertEqual(rec["old"]["co2e"], 61.0)
        self.assertEqual(rec["old"]["basis"]["verification_status"], OLD_STATUS)
        self.assertTrue(rec["old"]["basis"]["usda_factors_based"])
        self.assertAlmostEqual(rec["new"]["co2e"], TILLAGE_ONE_ACRE, places=3)
        self.assertEqual(rec["new"]["basis"]["verification_status"], "area_estimate")
        self.assertFalse(rec["new"]["basis"]["usda_factors_based"])
        self.assertEqual(rec["new"]["basis"]["calculation_basis"], "usda_standard_per_hectare")
        # Where it sits: event, type, farm and company, season.
        self.assertEqual(rec["subtype"], "TI")
        self.assertEqual(rec["farm"], "Home Orchard")
        self.assertEqual(rec["company"], "Orchard Co")
        self.assertEqual(rec["season_id"], self.history.pk)
        self.assertEqual(rec["entry_ids"], [self.stale_tillage.pk])
        self.assertTrue(rec["event_fingerprint"] and rec["entry_fingerprint"])
        # The report text carries the same facts.
        self.assertIn(f"event {self.tillage.pk} | TI", text)
        self.assertIn("figure_changed", text)
        self.assertIn("Dry run, nothing saved", text)

        self.assertEqual(_all_carbon_rows(self.history), before, "a dry run changed a carbon row")
        self.assertFalse(DataOperationLog.objects.exists())

    def test_a_stale_lab_analysis_is_not_estimated_never_a_zero(self):
        plan, text = self.dry_run()
        rec = self.record(plan, self.lab)
        self.assertEqual(rec["classification"], "now_not_estimated")
        self.assertEqual(rec["old"]["co2e"], 0.405)
        self.assertFalse(rec["new"]["stored"])
        self.assertIsNone(rec["new"]["co2e"])
        self.assertIn("no entry (not estimated)", text)

    def test_a_stale_ph_adjustment_with_no_fuel_and_no_lime_is_not_estimated(self):
        """The 0.3 kg/ha pH default is gone: nothing recorded, so nothing estimated (entry removed)."""
        history = self._season("pH 2026")
        ph = self._event(history, "PA", description="Sulfur / lime, nothing recorded")
        self.assertFalse(self._entries(ph).exists(), "today's signal stores no entry for it")
        self._stale(ph, 0.121, "area_estimate", False, "usda_area_scaled_soil_factors")
        plan, text = self.dry_run("ph.json", "--history", str(history.pk))
        rec = self.record(plan, ph)
        self.assertEqual(rec["classification"], "now_not_estimated")
        self.assertEqual(rec["old"]["co2e"], 0.121)
        self.assertFalse(rec["new"]["stored"])
        self.apply("ph.json", "ph-restore.json")
        self.assertFalse(self._entries(ph).exists())
        self.assertFalse(CarbonEntry.objects.filter(production=history, amount=0).exists())
        self.run_cmd("--restore", self.path("ph-restore.json"))
        self.assertEqual(self._entries(ph).get().co2e_amount, 0.121)

    def test_the_three_outcomes_are_counted_apart(self):
        plan, _ = self.dry_run()
        self.assertEqual(plan["counts"], {"figure_changed": 1, "now_not_estimated": 1, "unchanged": 1})
        self.assertEqual(self.record(plan, self.fueled)["classification"], "unchanged")

    def test_totals_before_and_after_come_from_the_calculator_service(self):
        service = CarbonCalculatorService()
        live = service.calculate_production_carbon(self.history.pk)
        plan, text = self.dry_run()

        (season,) = plan["seasons"]
        self.assertEqual(season["season_id"], self.history.pk)
        fuel = self._entries(self.fueled).first().amount
        # Producer total = every emission row; buyer total = recorded-basis rows only.
        self.assertAlmostEqual(season["before"]["producer_total"], live["total_emissions"], places=3)
        self.assertAlmostEqual(season["before"]["buyer_total"], live["recorded_emissions"], places=3)
        self.assertAlmostEqual(season["before"]["producer_total"], 61.0 + 0.405 + fuel, places=2)
        self.assertAlmostEqual(season["before"]["buyer_total"], 61.0 + 0.405 + fuel, places=2)
        # After: the tillage is an area estimate (producer sees it, buyer does not), the lab is gone.
        self.assertAlmostEqual(season["after"]["producer_total"], TILLAGE_ONE_ACRE + fuel, places=2)
        self.assertAlmostEqual(season["after"]["buyer_total"], fuel, places=2)
        self.assertLess(season["after"]["buyer_per_kg"], season["before"]["buyer_per_kg"])
        self.assertIn("SEASON TOTALS", text)
        self.assertIn("producer total", text)
        self.assertIn("buyer total", text)
        # The dry run left the live totals as they were.
        again = service.calculate_production_carbon(self.history.pk)
        self.assertEqual(again["total_emissions"], live["total_emissions"])
        self.assertEqual(again["recorded_emissions"], live["recorded_emissions"])

    def test_scope_flags_narrow_the_run(self):
        other = self._season("Other 2026")
        other_event = self._event(other, "TI", description="Other tillage")
        self._stale(other_event, 61.0, OLD_STATUS, True, "usda_area_scaled_soil_factors")

        plan, _ = self.dry_run("one.json", "--history", str(other.pk))
        self.assertEqual({r["event_id"] for r in plan["records"]}, {other_event.pk})
        self.assertEqual(plan["scope"], {"history": [other.pk]})
        plan, _ = self.dry_run(
            "two.json", "--establishment", str(self.establishment.pk), "--company", str(self.company.pk)
        )
        self.assertEqual(len(plan["records"]), 4)
        plan, _ = self.dry_run("three.json", "--company", "999999")
        self.assertEqual(plan["records"], [])

    def test_a_calculator_error_leaves_the_entry_alone(self):
        from unittest import mock

        error = {"co2e": 0.0, "verification_status": "calculation_error", "error": "boom", "usda_factors_based": False}
        with mock.patch.object(EventCarbonCalculator, "calculate_soil_management_event_impact", return_value=error):
            plan, _ = self.dry_run()
            self.assertEqual({r["classification"] for r in plan["records"]}, {"calculation_error"})
            self.run_cmd("--apply", self.path("plan.json"), "--restore-file", self.path("restore.json"))
        self.assertTrue(CarbonEntry.objects.filter(pk=self.stale_tillage.pk).exists())
        self.assertTrue(CarbonEntry.objects.filter(pk=self.stale_lab.pk).exists())

    def test_an_event_with_no_entry_that_now_has_a_figure_is_reported_apart(self):
        self._entries(self.fueled).delete()
        plan, _ = self.dry_run()
        self.assertEqual(self.record(plan, self.fueled)["classification"], "estimate_created")
        self.assertEqual(plan["counts"]["estimate_created"], 1)


class Apply(RecomputeSoilCarbonBase):
    def test_apply_updates_the_stale_tillage_entry_and_removes_the_lab_entry(self):
        plan, _ = self.dry_run()
        fueled_entry = self._entries(self.fueled).get()
        out = self.apply()

        (tillage_entry,) = self._entries(self.tillage)
        self.assertNotEqual(tillage_entry.pk, self.stale_tillage.pk)
        self.assertAlmostEqual(tillage_entry.co2e_amount, TILLAGE_ONE_ACRE, places=3)
        self.assertEqual(tillage_entry.verification_status, "area_estimate")
        self.assertFalse(tillage_entry.usda_factors_based)
        self.assertNotIn("flux", tillage_entry.description)
        # The lab analysis counts no emission: the entry is gone, and no zero took its place.
        self.assertFalse(self._entries(self.lab).exists())
        self.assertFalse(CarbonEntry.objects.filter(production=self.history, amount=0).exists())
        # A record already right is not rewritten.
        self.assertEqual(self._entries(self.fueled).get().pk, fueled_entry.pk)
        self.assertIn("applied                      2", out)
        self.assertEqual(DataOperationLog.objects.filter(action="apply").count(), 1)

    def test_the_totals_after_the_apply_are_the_totals_the_plan_showed(self):
        plan, _ = self.dry_run()
        out = self.apply()
        live = CarbonCalculatorService().calculate_production_carbon(self.history.pk)
        (season,) = plan["seasons"]
        self.assertAlmostEqual(live["total_emissions"], season["after"]["producer_total"], places=6)
        self.assertAlmostEqual(live["recorded_emissions"], season["after"]["buyer_total"], places=6)
        self.assertIn("SEASON TOTALS after the apply", out)

    def test_the_update_is_a_system_recalculation_attributed_to_no_one(self):
        # The old row was authored by nobody; the event's creator must not become the author now.
        self.assertIsNotNone(self.tillage.created_by_id)
        self.dry_run()
        self.apply()
        (entry,) = self._entries(self.tillage)
        self.assertIsNone(entry.created_by_id)
        marker = entry.calculation_details["system_recalculation"]
        self.assertEqual(marker["method_version"], "soil-2026-10-28")
        self.assertEqual(marker["source"], "system")
        self.assertEqual(marker["replaces_entry_ids"], [self.stale_tillage.pk])
        self.assertEqual(marker["previous"][0]["co2e"], 61.0)
        audits = USDACalculationAudit.objects.filter(carbon_entry=entry)
        self.assertTrue(audits.exists())
        for audit in audits:
            self.assertIsNone(audit.calculated_by_id)
            self.assertIn("soil-2026-10-28", audit.processor_version)
        for record in USDAComplianceRecord.objects.filter(carbon_entry=entry):
            self.assertIsNone(record.validated_by_id)
        self.assertFalse(EventAmendment.objects.exists(), "a correction/amendment record was created")

    def test_a_replaced_entry_keeps_the_author_it_already_had(self):
        entry = self._stale(self.tillage, 61.0, OLD_STATUS, True, "usda_area_scaled_soil_factors", created_by=self.user)
        self.dry_run()
        self.apply()
        self.assertEqual(self._entries(self.tillage).get().created_by_id, self.user.pk)
        self.assertNotEqual(self._entries(self.tillage).get().pk, entry.pk)

    def test_the_event_rows_and_the_season_are_untouched(self):
        events = [self.tillage, self.lab, self.fueled]
        before = {e.pk: model_to_dict(SoilManagementEvent.objects.get(pk=e.pk)) for e in events}
        updated_before = History.objects.get(pk=self.history.pk).updated_at
        has_updated_at = hasattr(SoilManagementEvent, "updated_at")
        stamps = {e.pk: SoilManagementEvent.objects.get(pk=e.pk).updated_at for e in events} if has_updated_at else {}

        self.dry_run()
        self.apply()

        for e in events:
            fresh = SoilManagementEvent.objects.get(pk=e.pk)
            self.assertEqual(model_to_dict(fresh), before[e.pk], "a farmer-entered field changed")
            if has_updated_at:
                self.assertEqual(fresh.updated_at, stamps[e.pk])
        self.assertEqual(History.objects.get(pk=self.history.pk).updated_at, updated_before)

    def test_only_carbon_tables_are_ever_written(self):
        with CaptureQueriesContext(connection) as queries:
            self.dry_run()
            self.apply()
            self.run_cmd("--restore", self.path("restore.json"))
        written = set()
        for q in queries.captured_queries:
            match = re.match(r'\s*(?:INSERT INTO|UPDATE|DELETE FROM)\s+"([a-z_]+)"', q["sql"])
            if match:
                written.add(match.group(1))
        self.assertTrue(written, "the capture saw no writes at all")
        self.assertLessEqual(written, WRITABLE_TABLES, f"wrote outside the carbon tables: {written - WRITABLE_TABLES}")

    def test_a_record_changed_after_the_dry_run_is_skipped(self):
        self.dry_run()
        # The event's inputs change after the plan was reviewed (queryset update: no signal, so the
        # stored entry stays stale and only the fingerprint can notice).
        SoilManagementEvent.objects.filter(pk=self.tillage.pk).update(area_covered=Decimal("4"))
        # The stored entry changes after the plan was reviewed.
        CarbonEntry.objects.filter(pk=self.stale_lab.pk).update(co2e_amount=9.0, amount=9.0)

        out = self.apply()

        self.assertIn("skipped, changed since dry run 2", out)
        self.assertIn("the event's inputs changed", out)
        self.assertIn("the stored entry changed", out)
        tillage = CarbonEntry.objects.get(pk=self.stale_tillage.pk)
        self.assertEqual(tillage.co2e_amount, 61.0)
        lab = CarbonEntry.objects.get(pk=self.stale_lab.pk)
        self.assertEqual(lab.co2e_amount, 9.0)
        self.assertFalse(DataOperationLog.objects.filter(action="apply").exists())
        self.assertFalse(Path(self.path("restore.json")).exists(), "a restore file for an apply that changed nothing")

    def test_only_the_stale_record_is_skipped_the_rest_apply(self):
        self.dry_run()
        SoilManagementEvent.objects.filter(pk=self.tillage.pk).update(area_covered=Decimal("4"))
        self.apply()
        self.assertTrue(CarbonEntry.objects.filter(pk=self.stale_tillage.pk).exists())
        self.assertFalse(self._entries(self.lab).exists())

    def test_the_second_apply_changes_nothing(self):
        self.dry_run()
        self.apply()
        after_first = _all_carbon_rows(self.history)
        first_restore = Path(self.path("restore.json")).read_text()

        out = self.apply("plan.json", "restore-again.json")

        self.assertEqual(_all_carbon_rows(self.history), after_first)
        self.assertIn("applied                      0", out)
        self.assertIn("already at the planned value 2", out)
        self.assertEqual(DataOperationLog.objects.filter(action="apply").count(), 1)
        self.assertFalse(Path(self.path("restore-again.json")).exists())
        self.assertEqual(Path(self.path("restore.json")).read_text(), first_restore)
        # A fresh dry run finds nothing to change.
        plan, _ = self.dry_run("check.json")
        self.assertEqual(plan["counts"], {"unchanged": 3})
        self.assertEqual(plan["seasons"], [])

    def test_a_restore_file_is_never_written_over(self):
        self.dry_run()
        Path(self.path("restore.json")).write_text("{}")
        with self.assertRaises(CommandError):
            self.apply()
        self.assertTrue(CarbonEntry.objects.filter(pk=self.stale_tillage.pk).exists(), "a change was kept")
        self.assertTrue(CarbonEntry.objects.filter(pk=self.stale_lab.pk).exists())

    def test_an_apply_needs_a_plan_from_this_command(self):
        Path(self.path("other.json")).write_text(json.dumps({"kind": "something-else"}))
        with self.assertRaises(CommandError):
            self.apply("other.json")
        with self.assertRaises(CommandError):
            self.run_cmd("--apply", self.path("plan.json"))  # no --restore-file

    def test_an_estimate_created_where_none_existed_is_applied_and_restored(self):
        self._entries(self.fueled).delete()
        before = _all_carbon_rows(self.history)
        self.dry_run()
        self.apply()
        self.assertEqual(self._entries(self.fueled).count(), 1)
        self.run_cmd("--restore", self.path("restore.json"))
        self.assertFalse(self._entries(self.fueled).exists())
        self.assertEqual(_all_carbon_rows(self.history), before)


class Restore(RecomputeSoilCarbonBase):
    def test_restore_brings_back_the_exact_prior_state_including_the_removed_entry(self):
        before = _all_carbon_rows(self.history)
        self.assertTrue(any(row["model"] == "carbon.usdacalculationaudit" for row in before))
        self.dry_run()
        self.apply()
        self.assertNotEqual(_all_carbon_rows(self.history), before)

        out = self.run_cmd("--restore", self.path("restore.json"))

        self.assertIn("Restored 2 record(s)", out)
        self.assertEqual(_all_carbon_rows(self.history), before, "the restore was not exact")
        self.assertTrue(CarbonEntry.objects.filter(pk=self.stale_lab.pk).exists())
        self.assertEqual(DataOperationLog.objects.filter(action="restore").count(), 1)

    def test_a_restore_does_not_overwrite_an_entry_saved_after_the_apply(self):
        self.dry_run()
        self.apply()
        # The grower re-saves the tillage record: the signal writes a new entry.
        self.tillage.save()
        newer = list(self._entries(self.tillage).values_list("pk", flat=True))
        out = self.run_cmd("--restore", self.path("restore.json"))
        self.assertIn(f"event {self.tillage.pk} NOT restored", out)
        self.assertEqual(list(self._entries(self.tillage).values_list("pk", flat=True)), newer)

    def test_a_dry_run_plan_is_not_a_restore_file(self):
        self.dry_run()
        with self.assertRaises(CommandError):
            self.run_cmd("--restore", self.path("plan.json"))

    def test_a_plan_path_that_holds_a_restore_file_is_refused(self):
        self.dry_run()
        self.apply()
        with self.assertRaises(CommandError):
            self.run_cmd("--report", self.path("restore.json"))


class SamplePrinted(RecomputeSoilCarbonBase):
    def test_print_the_report(self):
        """`SOIL_RECOMPUTE_PRINT=1` prints the dry-run, apply and restore text this contract produces."""
        _, dry = self.dry_run()
        applied = self.apply()
        restored = self.run_cmd("--restore", self.path("restore.json"))
        if os.environ.get("SOIL_RECOMPUTE_PRINT"):
            print("\n" + dry + "\n\n" + applied + "\n" + restored + "\n")
        self.assertTrue(dry and applied and restored)
