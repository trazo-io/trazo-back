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
