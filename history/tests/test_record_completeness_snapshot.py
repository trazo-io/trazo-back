"""Integration: the record-completeness registry reaching compliance_snapshot_rows().

Proves the wiring, not just the registry — a chemical event missing required fields must produce
a FAIL row from `AuditExportService.compliance_snapshot_rows()`, which is the single chokepoint
also read by the certifier-readiness card (`company/views.py::certifier_readiness`) and the
certifier link dossier (`certifications/views.py`). One row, three surfaces; this only needs to
test the row.

Fixture pattern copied from `test_audit_export_snapshot.py`. `Establishment(state="CA")` is
required — an Establishment built without `state` poisons an atomic block via the
`USDAComplianceRecord.state` NOT NULL constraint (see the 2026-07-30 fixture-trap postmortem).
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User

RECORD_COMPLETENESS_LABEL = "Record completeness — chemical (§ 205.103(b)(2))"


class RecordCompletenessSnapshotTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="rc-snap@test.com", password="x")
        self.company = Company.objects.create(name="RC Snap Farm")
        self.establishment = Establishment.objects.create(name="RC1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="RCP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Almond")
        self.history = History.objects.create(
            name="RCH1",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _row(self):
        rows = AuditExportService(self.history, certification_type="organic").compliance_snapshot_rows()
        matches = [r for r in rows if r["label"] == RECORD_COMPLETENESS_LABEL]
        self.assertEqual(len(matches), 1, "exactly one record-completeness row must be present")
        return matches[0]

    def test_no_chemical_events_is_not_applicable(self):
        """NA, not PASS — and the distinction is load-bearing.

        A season with no chemical inputs has no chemical records to be complete or incomplete.
        PASS would claim Trazo checked something and found it good; NA says the question does
        not arise. The sibling "Input traceability (§ 205.103)" row directly above says NA for
        the same fixture, and `ACTIONABLE_READINESS_STATUSES` (company/views.py) keeps both off
        the readiness card for the same reason. This test asserted PASS and had been failing.
        """
        row = self._row()
        self.assertEqual(row["status"], "NA")
        self.assertIn("No chemical inputs", row["detail"])
        self.assertIsNone(row["section_hint"])

    def test_the_actual_blind_spot_a_blank_spray_record_fails(self):
        """The record the plan set out to catch: every certifier-relevant field left blank."""
        ChemicalEvent.objects.create(history=self.history, type="PE", date=timezone.now())

        row = self._row()
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("1/1", row["detail"])
        for label in ("product name", "amount applied", "area treated", "target pest or disease"):
            self.assertIn(label, row["detail"])
        # Renamed 2026-09-07: the packet has no "Chemical Log" section and never did — the
        # pointer named an event-model family instead of the heading a certifier reads, so an
        # inspector following it found nothing. The real heading is CCOF's and USDA C7's own
        # name. Guard: `history/tests/test_packet_section_vocabulary.py` asserts every
        # "… section" pointer resolves to a heading that exists.
        self.assertEqual(row["section_hint"], "Input Material Application Records section")

    def test_a_complete_spray_record_passes(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type="PE",
            commercial_name="Example 10G",
            volume="5",
            area="2",
            target_pest_disease="Aphids",
            date=timezone.now(),
        )
        row = self._row()
        self.assertEqual(row["status"], "PASS")
        self.assertIn("1/1", row["detail"])

    def test_fertilizer_missing_only_target_pest_still_passes(self):
        """A fertilizer with no target pest is complete — § 205.206(a) does not apply to it."""
        ChemicalEvent.objects.create(
            history=self.history,
            type="FE",
            commercial_name="Urea 46-0-0",
            volume="50",
            area="10",
            date=timezone.now(),
        )
        row = self._row()
        self.assertEqual(row["status"], "PASS")

    def test_mixed_records_report_the_incomplete_fraction(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type="PE",
            commercial_name="Example 10G",
            volume="5",
            area="2",
            target_pest_disease="Aphids",
            date=timezone.now(),
        )
        ChemicalEvent.objects.create(history=self.history, type="HE", date=timezone.now())

        row = self._row()
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("1/2", row["detail"])

    def test_distinct_from_input_traceability_which_only_checks_supplier(self):
        """A record can have a supplier on file (traceability PASS) and still be missing the
        fields an inspector reads on the event itself (this row FAILs) — the two checks measure
        different things and must not be conflated into one another."""
        ChemicalEvent.objects.create(
            history=self.history,
            type="PE",
            supplier_name="Ag Supply Co",
            date=timezone.now(),
        )
        rows = AuditExportService(self.history, certification_type="organic").compliance_snapshot_rows()
        by_label = {r["label"]: r["status"] for r in rows}
        self.assertEqual(by_label["Input traceability (§ 205.103)"], "PASS")
        self.assertEqual(by_label[RECORD_COMPLETENESS_LABEL], "FAIL")
