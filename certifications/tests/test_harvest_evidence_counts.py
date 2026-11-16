"""Under an answer that names a kind of record, the module PDF says how many are logged in Trazo (2026.10.26).

G6.1 asks how harvest bins and transport units are shown to be clean ("Cleaning logs", "Clean-out
records", "Clean truck or equipment affidavits"). Trazo already holds those records: a cleanout
activity says WHAT it cleaned (`cleaning_asset_class`), and each shipment records how the truck was
kept clean (`SalesRecord.clean_transport_method`). The page now prints the count under the answer,
or says none are logged, from the same bundle the section 11 records list reads. A count is what is
in Trazo, never a verdict: paper logs are not in it, and the zero line says so.

OTCO C12 12.1 lists "Clean truck affidavits and/or other clean transport records" and "Documentation
of transactions with co-packers" as their own checkboxes; both are now section 11 rows.
"""

import io
from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import pdfplumber

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULE_REGISTRY
from certifications.services.common_osp_records import ANSWER_EVIDENCE, RECORD_TYPES_BY_KEY, derive_record_types
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from history.models import Production, ProductionEvent, SalesRecord
from product.models import Parcel

G61 = "g6_1_harvest_transport"


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Chelan Orchards")
        self.est = Establishment.objects.create(name="Chelan Orchard", company=self.company, state="WA")
        self.parcel = Parcel.objects.create(name="Block 7", establishment=self.est, area=10.0)
        self.season = Production.objects.create(
            name="2026 apples",
            parcel=self.parcel,
            start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc),
            finish_date=datetime(2026, 10, 1, tzinfo=dt_tz.utc),
        )
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")

    def answer(self, **values):
        self.osp.module_responses = {"modules": {G61: {"answers": values}}}
        self.osp.save(update_fields=["module_responses"])

    def cleanout(self, asset_class, **kw):
        defaults = dict(cleaning_date=timezone.now().date(), cleaning_method="Pressure wash")
        defaults.update(kw)
        return ProductionEvent.objects.create(
            history=self.season,
            type="EM",
            date=timezone.now(),
            area_covered=0.0,
            cleaning_asset_class=asset_class,
            **defaults,
        )

    def sale(self, **kw):
        return SalesRecord.objects.create(
            production=self.season,
            sale_date=datetime(2026, 9, 20, tzinfo=dt_tz.utc).date(),
            buyer_name="Valley Packers",
            quantity=Decimal("20"),
            quantity_unit="bins",
            **kw,
        )

    def text(self):
        self.osp.refresh_from_db()
        with pdfplumber.open(io.BytesIO(generate_module_pdf(self.osp, G61))) as doc:
            return " ".join(" ".join((p.extract_text() or "") for p in doc.pages).split())


class BinCleaningTests(_Farm):
    def test_cleaning_logs_print_the_bin_cleanouts_logged(self):
        self.cleanout("harvest_bins")
        self.cleanout("harvest_bins")
        self.cleanout("transport_vehicle")
        self.cleanout("harvest_bins", cleaning_date=None, cleaning_method=None)  # no cleaning recorded
        self.answer(container_safeguards=["cleaned_prior"], container_cleaning_records=["cleaning_logs"])
        self.assertIn("In Trazo: 2 cleaning records for harvest bins or totes logged.", self.text())

    def test_none_logged_says_so_and_that_paper_is_not_counted(self):
        self.answer(container_safeguards=["cleaned_prior"], container_cleaning_records=["cleaning_logs"])
        self.assertIn(
            "In Trazo: no cleaning records for harvest bins or totes logged. Records kept outside Trazo are not "
            "counted here.",
            self.text(),
        )

    def test_no_count_when_the_answer_does_not_name_logs(self):
        self.cleanout("harvest_bins")
        self.answer(container_safeguards=["cleaned_prior"], container_cleaning_records=["other"])
        self.assertNotIn("In Trazo:", self.text())


class TransportTests(_Farm):
    def legacy_season(self):
        return Production.objects.create(
            name="2025 apples",
            parcel=self.parcel,
            start_date=datetime(2025, 3, 1, tzinfo=dt_tz.utc),
            finish_date=datetime(2025, 10, 1, tzinfo=dt_tz.utc),
            transport_affidavit_on_file=True,
        )

    def test_affidavits_count_live_shipments_and_a_legacy_only_season(self):
        self.sale(clean_transport_method="affidavit")
        self.sale(clean_transport_method="inspected")
        self.sale(clean_transport_method="affidavit", voided_at=timezone.now(), void_reason="Entered twice")
        self.legacy_season()
        self.answer(transport_unit_cleaning_documentation=["clean_truck_affidavits"])
        self.assertIn("In Trazo: 2 shipments recorded with a clean-transport affidavit on file.", self.text())

    def test_the_legacy_flag_is_not_counted_again_beside_documented_shipments(self):
        """The season flag and the per-shipment method are one fact from two editors (audit export rule)."""
        self.sale(clean_transport_method="affidavit")
        self.season.transport_affidavit_on_file = True
        self.season.save(update_fields=["transport_affidavit_on_file"])
        self.answer(transport_unit_cleaning_documentation=["clean_truck_affidavits"])
        self.assertIn("In Trazo: 1 shipment recorded with a clean-transport affidavit on file.", self.text())
        row = next(r for r in derive_record_types(self.est, osp=self.osp) if r["key"] == "clean_transport_records")
        self.assertEqual(row["count"], 1)

    def test_cleanout_records_count_vehicle_cleanouts(self):
        self.cleanout("transport_vehicle")
        self.cleanout("harvest_bins")
        self.answer(transport_unit_cleaning_documentation=["cleanout_records", "clean_truck_affidavits"])
        text = self.text()
        self.assertIn("In Trazo: 1 cleaning record for a transport vehicle or trailer logged.", text)
        self.assertIn("In Trazo: no shipments recorded with a clean-transport affidavit on file.", text)

    def test_one_bundle_per_pdf(self):
        """Three counted answers read the records once, not once per answer."""
        self.answer(container_safeguards=["cleaned_prior"], container_cleaning_records=["cleaning_logs"])
        with CaptureQueriesContext(connection) as one:
            self.text()
        self.answer(
            container_safeguards=["cleaned_prior"],
            container_cleaning_records=["cleaning_logs"],
            transport_unit_cleaning_documentation=["cleanout_records", "clean_truck_affidavits"],
        )
        with CaptureQueriesContext(connection) as three:
            self.text()
        self.assertEqual(len(three), len(one))


class RecordsListTests(_Farm):
    def test_clean_transport_is_a_section_11_row_counted_from_shipments(self):
        self.sale(clean_transport_method="dedicated_organic")
        self.sale(transport_cleaning_method="swept")
        self.sale()
        row = next(r for r in derive_record_types(self.est, osp=self.osp) if r["key"] == "clean_transport_records")
        self.assertEqual(row["label"], "Clean truck affidavits and/or other clean transport records")
        self.assertEqual(row["count"], 2)
        self.assertEqual(row["basis"], "2 shipments recording how the transport unit was kept clean")
        self.assertTrue(row["suggested"])
        self.assertFalse(row["confirmed"], "a count is a suggestion; only the operator confirms")


class DeclarationTests(SimpleTestCase):
    def test_every_declared_evidence_key_exists(self):
        declared = {
            (m.key, q.key, o.value, o.evidence)
            for m in MODULE_REGISTRY
            for p in m.pages
            for q in p.questions
            for o in q.options
            if o.evidence
        }
        self.assertTrue(declared)
        for module, question, option, key in declared:
            with self.subTest(f"{module}.{question}.{option}"):
                self.assertIn(key, ANSWER_EVIDENCE)

    def test_the_c12_rows_carry_its_labels(self):
        self.assertEqual(
            RECORD_TYPES_BY_KEY["copacker_transaction_records"].label, "Documentation of transactions with co-packers"
        )
        self.assertTrue(RECORD_TYPES_BY_KEY["copacker_transaction_records"].external_by_design)
