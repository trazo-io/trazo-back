"""
Compliance Snapshot classifier tests — P0-4 (2026-04-15).

Covers:
- Input traceability § 205.103: FAIL on missing supplier, REVIEW on supplier-name
  variants that collapse to same normalized form, PASS otherwise.
- Contamination prevention § 205.272: PASS when no shared-equipment exposure
  OR all EM cleaning events fully documented; FAIL when shared equipment
  but zero EM cleaning events; REVIEW on partial documentation.
"""

import re
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from reportlab.platypus import Table

from company.models import Company, Establishment
from history.models import ChemicalEvent, Production, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class ComplianceSnapshotTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="snap@test.com", password="x")
        self.company = Company.objects.create(name="Snap Farm")
        self.establishment = Establishment.objects.create(name="S1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Tomato")
        self.history = Production.objects.create(
            name="H1",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _rows_by_requirement(self):
        """Invoke the snapshot builder and return {requirement: (status, detail)}
        by extracting text from the Table flowable it emits."""
        service = AuditExportService(self.history, certification_type="organic")
        flowables = service._build_compliance_snapshot()
        table = next((f for f in flowables if isinstance(f, Table)), None)
        assert table is not None, "Snapshot must emit a Table"
        # Each row is [label-Paragraph, status-Paragraph, detail-Paragraph].
        # Status is the documentation mark wrapped in <b><font color=...>DOCUMENTED
        # </font></b> (DOCUMENTED / REVIEW / GAP) — strip tags to get the bare word.
        out = {}
        for row in table._cellvalues[1:]:  # skip header row
            req = row[0].text if hasattr(row[0], "text") else str(row[0])
            status_html = row[1].text if hasattr(row[1], "text") else str(row[1])
            detail = row[2].text if hasattr(row[2], "text") else str(row[2])
            status = re.sub(r"<[^>]+>", "", status_html).strip()
            out[req] = (status, detail)
        return out

    def test_an_empty_plan_inputs_list_is_named_as_the_plan_not_the_records(self):
        """Handoff rehearsal 2026-10-18, H-2. The (a)(2) row measures the PLAN's inputs list. It read
        "No production or handling inputs are on file" two rows above "3/3 inputs have supplier on
        file", as if nothing had been applied."""
        from certifications.models import OrganicSystemPlan

        # A written (a)(2) narrative with no structured Materials rows is a normal state before
        # reconciling; the row must not call the narrative empty (review of back #181).
        narrative = "Feather meal 12-0-0 for nitrogen; kaolin clay for sunburn; spinosad for codling moth. " * 8
        OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="draft",
            sections={"inputs_list": {"narrative": narrative, "last_updated": None}},
        )
        rows = self._rows_by_requirement()
        status, detail = rows["OSP completeness (\u00a7 205.201(a)(2))"]
        self.assertEqual(status, "REVIEW")
        self.assertIn("No materials are on the plan's Materials list", detail)
        self.assertIn("not the (a)(2) narrative or the season's application records", detail)
        for wrong in ("No production or handling inputs are on file", "inputs list is empty"):
            self.assertNotIn(wrong, detail)

    # ---- Input traceability § 205.103 ----

    def test_no_absence_row_renders_as_the_pass_state(self):
        """Structural guard, not a per-row assertion.

        The defect this file now encodes was systemic: FOUR separate rows printed DOCUMENTED
        with a detail that said nothing existed to check. Asserting them one at a time only
        pins the ones someone remembered. This walks every row the snapshot emits and fails if
        any row marked DOCUMENTED describes an absence.
        """
        rows = self._rows_by_requirement()
        self.assertTrue(rows, "snapshot emitted no rows — the assertions below would be vacuous")
        offenders = [
            f"{req}: {detail!r}"
            for req, (status, detail) in rows.items()
            if status == "DOCUMENTED"
            and re.search(r"\bno\b[^.]*\b(events?|records?|inputs?|findings?)\b", detail or "", re.I)
            # "No equipment shared with conventional operations" is a genuine positive finding
            # about the operation, not an absence of records. Same for a zero incident count on
            # an active log.
            and "shared with conventional" not in (detail or "") and "logging system active" not in (detail or "")
        ]
        self.assertEqual(
            offenders,
            [],
            "These rows render the PASS word for an absence of records:\n  " + "\n  ".join(offenders),
        )

    def test_input_traceability_no_chemicals_is_not_applicable_not_a_pass(self):
        """No inputs applied is NOT the same as inputs verified.

        This asserted DOCUMENTED until 2026-08-18. The snapshot had three states, so an
        absence of records and a verified record printed the same green word, and a certifier
        reading down the Documentation column could not tell them apart. N/A is the fourth state. Compare the contamination-log row, which always got this right by wording
        ("0 incidents (logging system active)").
        """
        rows = self._rows_by_requirement()
        status, detail = rows["Input traceability (§ 205.103)"]
        self.assertEqual(status, "N/A")
        self.assertNotEqual(status, "DOCUMENTED", "an absence must never render as the pass state")
        self.assertIn("No chemical inputs", detail)

    def test_input_traceability_missing_supplier_is_fail(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Sulfur",
            supplier_name="",
            date=timezone.now(),
        )
        rows = self._rows_by_requirement()
        status, _ = rows["Input traceability (§ 205.103)"]
        self.assertEqual(status, "GAP")

    def test_input_traceability_supplier_variants_is_review(self):
        # Three chemical events, two supplier names that normalize to the same key.
        ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="A",
            supplier_name="Hydra Gardens",
            date=timezone.now(),
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="B",
            supplier_name="Hydra-Gardens",
            date=timezone.now(),
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="C",
            supplier_name="Hydra",
            date=timezone.now(),
        )
        rows = self._rows_by_requirement()
        status, detail = rows["Input traceability (§ 205.103)"]
        self.assertEqual(status, "REVIEW")
        self.assertIn("Supplier name variants", detail)
        self.assertIn("Hydra", detail)

    def test_input_traceability_all_distinct_suppliers_is_pass(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="A",
            supplier_name="Vendor One Inc",
            date=timezone.now(),
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="B",
            supplier_name="Completely Different Vendor",
            date=timezone.now(),
        )
        rows = self._rows_by_requirement()
        status, _ = rows["Input traceability (§ 205.103)"]
        self.assertEqual(status, "DOCUMENTED")

    # ---- § 205.272 contamination prevention ----

    def test_contamination_prevention_no_shared_is_pass(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            area_covered=1.0,
            shared_with_conventional=False,
        )
        rows = self._rows_by_requirement()
        status, detail = rows["Contamination prevention (§ 205.272)"]
        self.assertEqual(status, "DOCUMENTED")
        self.assertIn("No equipment shared", detail)

    def test_contamination_prevention_shared_but_no_em_is_fail(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            area_covered=1.0,
            shared_with_conventional=True,
        )
        rows = self._rows_by_requirement()
        status, _ = rows["Contamination prevention (§ 205.272)"]
        self.assertEqual(status, "GAP")

    def test_contamination_prevention_empty_em_event_is_review(self):
        # Regression: EM events exist but have no cleaning data.
        # Must be REVIEW (farmer started documenting), NOT FAIL ("no EM events on file"),
        # because an inspector distinguishes "never tried" from "tried but incomplete".
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            area_covered=1.0,
            shared_with_conventional=True,
        )
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=timezone.now(),
            area_covered=0.0,
            # No cleaning_date / cleaning_method / cleaned_by.
        )
        rows = self._rows_by_requirement()
        status, detail = rows["Contamination prevention (§ 205.272)"]
        self.assertEqual(status, "REVIEW")
        self.assertIn("missing date / method / performer", detail)

    def test_contamination_prevention_shared_with_em_documented_is_pass(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            area_covered=1.0,
            shared_with_conventional=True,
        )
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=timezone.now(),
            area_covered=0.0,
            cleaning_date=timezone.now().date(),
            cleaning_method="Pressure wash + scrub",
            cleaned_by="Miguel Ramirez",
        )
        rows = self._rows_by_requirement()
        status, _ = rows["Contamination prevention (§ 205.272)"]
        self.assertEqual(status, "DOCUMENTED")

    # ---- M7-I3: "shared" is read from the register, custom hire and hired sprays too ----

    def _harvest(self, **kw):
        kw.setdefault("shared_with_conventional", False)
        return ProductionEvent.objects.create(
            history=self.history, type="HA", date=timezone.now(), area_covered=1.0, **kw
        )

    def _documented_cleaning(self, days_ago=1):
        return ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=timezone.now() - timedelta(days=days_ago),
            area_covered=0.0,
            cleaning_date=timezone.now().date(),
            cleaning_method="Pressure wash",
            cleaned_by="Miguel",
        )

    def _contamination_row(self):
        return self._rows_by_requirement()["Contamination prevention (§ 205.272)"]

    def _coverage_cells(self):
        service = AuditExportService(self.history, certification_type="organic")
        table = next(f for f in service._build_shared_equipment_coverage_subtable() if isinstance(f, Table))
        return " ".join(getattr(c, "text", "") or "" for row in table._cellvalues for c in row)

    def _register(self, **kw):
        from certifications.models import ProductionEquipment

        kw.setdefault("use", "harvest")
        return ProductionEquipment.objects.create(establishment=self.establishment, name="Bin trailer", **kw)

    def test_register_item_not_dedicated_is_a_review_never_a_pass_or_a_fail(self):
        self._harvest()
        self._register(dedicated_organic=False, ownership="own")
        status, detail = self._contamination_row()
        self.assertEqual(status, "REVIEW")
        self.assertNotIn("No equipment shared", detail)
        self.assertIn("confirm whether any was used this season", detail)

    def test_a_rented_register_item_is_a_review_too(self):
        self._harvest()
        self._register(dedicated_organic=True, ownership="rent")
        status, _ = self._contamination_row()
        self.assertEqual(status, "REVIEW")

    def test_the_register_review_does_not_turn_on_the_cleaning_log(self):
        """A farm-wide, undated register cannot make an earlier season FAIL for lacking a cleaning."""
        self._harvest()
        self._register(dedicated_organic=False)
        self.assertEqual(self._contamination_row()[0], "REVIEW")
        self._documented_cleaning()
        self.assertEqual(self._contamination_row()[0], "REVIEW")

    def test_a_dedicated_owned_register_item_still_reads_as_nothing_shared(self):
        self._harvest()
        self._register(dedicated_organic=True, ownership="own")
        status, detail = self._contamination_row()
        self.assertEqual(status, "DOCUMENTED")
        self.assertIn("No equipment shared", detail)

    def test_a_register_query_failure_is_not_swallowed_into_a_pass(self):
        from unittest import mock

        from company.models import Establishment as Est

        self._harvest()
        with mock.patch.object(
            Est, "production_equipment", new_callable=mock.PropertyMock, side_effect=RuntimeError("db")
        ):
            with self.assertRaises(RuntimeError):
                self._rows_by_requirement()

    def test_custom_operator_pass_is_reviewed_by_its_link_and_the_coverage_table_agrees(self):
        self._harvest(operator_is_custom=True, performed_by="Valley Custom Harvest")
        # Another cleaning on file elsewhere does not cover a custom operator's machine.
        self._documented_cleaning()
        status, detail = self._contamination_row()
        self.assertEqual(status, "REVIEW")
        self.assertIn("0/1 custom-operator or hired-applicator pass(es)", detail)
        cells = self._coverage_cells()
        self.assertIn("Valley Custom Harvest", cells)
        self.assertIn("REVIEW \u2014 no cleaning event linked", cells)

    def test_a_custom_operator_pass_with_its_cleaning_linked_is_covered_in_both_places(self):
        self._harvest(
            operator_is_custom=True,
            performed_by="Valley Custom Harvest",
            equipment_cleaning_event=self._documented_cleaning(),
        )
        status, detail = self._contamination_row()
        self.assertEqual(status, "DOCUMENTED")
        self.assertIn("All 1 custom-operator pass(es)", detail)
        cells = self._coverage_cells()
        self.assertIn("Cleaned", cells)
        self.assertNotIn("REVIEW", cells)

    def test_ticked_passes_keep_the_aggregate_verdict_beside_an_unlinked_custom_pass(self):
        """Four harvests ticked shared and a documented cleaning log were PASS. One custom hulling
        pass added later must add its own REVIEW, not turn the ticked four into 0/5."""
        for _ in range(4):
            self._harvest(shared_with_conventional=True)
        self._documented_cleaning()
        self.assertEqual(self._contamination_row()[0], "DOCUMENTED")
        self._harvest(operator_is_custom=True, performed_by="Valley Custom Huller")
        status, detail = self._contamination_row()
        self.assertEqual(status, "REVIEW")
        self.assertIn("0/1 custom-operator or hired-applicator pass(es)", detail)
        self.assertNotIn("0/5", detail)

    def _pcb_spray(self):
        return ChemicalEvent.objects.create(
            history=self.history,
            type="PE",
            commercial_name="Spinosad",
            date=timezone.now(),
            applied_by_pcb=True,
            pcb_name="Valley Aerial Spray",
        )

    def test_a_hired_spray_is_a_review_asking_for_the_contractors_statement_even_with_an_unrelated_cleaning(self):
        self._harvest()
        self._pcb_spray()
        self._documented_cleaning()
        status, detail = self._contamination_row()
        self.assertEqual(status, "REVIEW")
        self.assertIn("contractor's cleaning statement", detail)
        self.assertIn("Valley Aerial Spray", self._coverage_cells())

    def test_a_hired_spray_with_no_cleaning_log_is_a_review_not_a_fail(self):
        self._harvest()
        self._pcb_spray()
        status, _ = self._contamination_row()
        self.assertEqual(status, "REVIEW")

    def test_a_linked_custom_pass_and_a_hired_spray_share_one_tally(self):
        self._harvest(operator_is_custom=True, equipment_cleaning_event=self._documented_cleaning())
        self._pcb_spray()
        status, detail = self._contamination_row()
        self.assertEqual(status, "REVIEW")
        self.assertIn("1/2 custom-operator or hired-applicator pass(es)", detail)

    def test_a_shared_ticked_pass_with_a_documented_cleaning_still_takes_the_existing_branch(self):
        self._harvest(shared_with_conventional=True)
        self._documented_cleaning()
        status, detail = self._contamination_row()
        self.assertEqual(status, "DOCUMENTED")
        self.assertIn("EM cleaning event(s) on file", detail)

    def test_contamination_prevention_partial_em_is_review(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            area_covered=1.0,
            shared_with_conventional=True,
        )
        # One fully documented EM event + one with missing performer.
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=timezone.now(),
            area_covered=0.0,
            cleaning_date=timezone.now().date(),
            cleaning_method="Pressure wash",
            cleaned_by="Miguel",
        )
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=timezone.now(),
            area_covered=0.0,
            cleaning_date=timezone.now().date(),
            cleaning_method="Steam",
            cleaned_by="",  # missing performer
        )
        rows = self._rows_by_requirement()
        status, _ = rows["Contamination prevention (§ 205.272)"]
        self.assertEqual(status, "REVIEW")
