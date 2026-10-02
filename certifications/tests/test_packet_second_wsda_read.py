"""The renewal packet reads as the grower's filing: the second WSDA read (2026-09-11).

WHY THIS EXISTS
---------------
Two fresh-eyes reads of a WSDA specimen packet, as a Yakima Valley grower and then as a WSDA
reviewer, found defects that every operation's packet would carry, not only the specimen's:

  * the plan's first page printed "Submitted: 2026-02-17T18:40:00+00:00", said its structure was
    "the same six-part ... used by CCOF, Oregon Tilth", and carried an "I, the undersigned"
    attestation with no line anywhere in the packet to sign on;
  * the filing said "reporting year 2026" for the year it continues, and filled § 205.406(a)(3) with
    a sentence about what Trazo does not track, inside the grower's own filing;
  * the coverage page printed "parcels/parcel-application-<parcel>.pdf", told an apple grower to
    file WSDA's mushroom section, and misstated the handler rules ("WSDA licenses", "5% threshold
    ... Made with Organic");
  * the audit exhibit printed a model field name ("History.lot_id"), two unanswered prompts, and
    asked the operator to explain a gap between harvest and sale that the pack-out figures on the
    same harvest records already explained;
  * "§ 11" read as a CFR section that does not exist, and a plain count of form rows read as 25
    records the operation failed to keep.

Each test renders the real document and reads it back.
"""

import io
import zipfile
from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from certifications.osp_modules import MODULES_BY_KEY
from certifications.services.audit_trail_exhibit import document_table, sample_trail
from certifications.services.common_osp_records import COMMON_OSP_RECORD_TYPES
from certifications.services.osp_module_pdf import (
    _audit_trail_exhibit_pdf,
    _coverage_pdf,
    generate_module_pdf,
    generate_osp_packet,
)
from certifications.services.osp_pdf_snapshot import generate_osp_snapshot_pdf
from company.models import Company, Establishment
from history.models import History, ProductionEvent, SalesRecord
from product.models import Parcel, ParcelCropHistory
from users.models import User


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="read2@test.com", password="x")
        self.company = Company.objects.create(name="Read Two LLC")
        self.est = Establishment.objects.create(
            name="Read Two Orchards", company=self.company, state="WA", contact_person="Dana Reader"
        )
        self.parcel = Parcel.objects.create(name="Ridge Block", establishment=self.est, area=11.5)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="submitted",
            created_by=self.user,
            submitted_at=datetime(2026, 2, 17, 18, 40, tzinfo=dt_tz.utc),
            certifier_name="Washington State Department of Agriculture",
        )

    def _filing(self, **extra):
        return OSPAnnualUpdate.objects.create(
            prior_osp=self.osp,
            reporting_year=2026,
            submitted_at=datetime(2026, 2, 17, 18, 55, tzinfo=dt_tz.utc),
            changes_summary="Serenade added for fire blight.",
            additions=["Serenade ASO"],
            **extra,
        )

    def _season(self, name="Honeycrisp 2025", finish=datetime(2025, 9, 24, tzinfo=dt_tz.utc)):
        return History.objects.create(
            name=name,
            parcel=self.parcel,
            start_date=datetime(2025, 3, 15, tzinfo=dt_tz.utc),
            finish_date=finish,
            lot_id="RT-2025-RB",
        )

    def _sale(self, season, when, amount, organic=True, voided=False):
        return SalesRecord.objects.create(
            production=season,
            sale_date=when,
            buyer_name="Sample Packer",
            quantity=Decimal("1000"),
            quantity_unit="lb",
            sale_amount=Decimal(amount),
            organic_on_invoice=organic,
            voided_at=datetime(2026, 1, 5, tzinfo=dt_tz.utc) if voided else None,
        )


class ThePlanAndTheFilingTests(_Farm):
    def test_the_plan_prints_its_submission_as_a_date_and_names_no_other_agency(self):
        text = _text(generate_osp_snapshot_pdf(self.osp))
        self.assertIn("Submitted: 2026-02-17", text)
        self.assertNotIn("T18:40", text)
        self.assertNotIn("Oregon Tilth", text)
        self.assertNotIn("CCOF", text)
        self.assertNotIn("Approved Inputs", text)

    def test_the_attestation_has_lines_to_sign_on_the_plan_and_a_draft_filing(self):
        """A draft filing gets lines to sign on, like the plan. A filing that already reached
        the agent without a signature in Trazo does not (2026-10-01): blank lines on a filed
        document invite a signature on a page nobody signed when it was filed."""
        OSPAnnualUpdate.objects.create(
            prior_osp=self.osp, reporting_year=2026, changes_summary="Serenade added for fire blight."
        )
        plan = _text(generate_osp_snapshot_pdf(self.osp))
        filing = _text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))).read("02-annual-update.pdf"))
        for doc in (plan, filing):
            self.assertIn("Signature:", doc)
            self.assertIn("Printed name: Dana Reader", doc)

    def test_a_filed_unsigned_filing_says_no_signature_was_recorded(self):
        self._filing()
        filing = _text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))).read("02-annual-update.pdf"))
        self.assertIn("No signature was recorded in Trazo", filing)
        self.assertNotIn("Signature:", filing)

    def test_the_cover_says_which_year_the_filing_continues(self):
        self._filing()
        cover = _text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))).read("00-cover.pdf"))
        self.assertIn("Continues certification for: 2026", cover)
        self.assertNotIn("Reporting year", cover)
        self.assertIn("1 addition, no deletions", cover)
        self.assertNotIn("addition(s)", cover)

    def test_a_3_prints_the_operators_statement_when_made(self):
        self._filing(sections_unchanged_attestation={"application_information": True, "monitoring_plan": True})
        filing = _text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))).read("02-annual-update.pdf"))
        self.assertIn("205.406(a)(1)–(4)", filing)
        self.assertIn("No changes. The operator attests", filing)
        # Not a § 205.201(a) section, so never listed among the section attestations.
        attested = filing[filing.index("Sections attested unchanged") :]
        self.assertNotIn("application information", attested.lower()[:300])

    def test_a_3_says_not_stated_otherwise_and_never_speaks_for_trazo(self):
        self._filing()
        filing = _text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))).read("02-annual-update.pdf"))
        self.assertIn("205.406(a)(1)–(4)", filing)
        self.assertIn("Not stated on this filing", filing)
        self.assertNotIn("Trazo does not track", filing)

    def test_gross_organic_sales_counts_the_prior_years_live_organic_invoices_only(self):
        season = self._season()
        self._sale(season, date(2025, 10, 14), "500000.00")
        self._sale(season, date(2025, 11, 2), "250000.50")
        self._sale(season, date(2025, 11, 3), "99999.00", organic=False)  # not invoiced as organic
        self._sale(season, date(2025, 11, 4), "88888.00", voided=True)  # voided
        self._sale(season, date(2026, 1, 20), "77777.00")  # the continuation year, not the prior one
        self._filing()
        filing = _text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))).read("02-annual-update.pdf"))
        self.assertIn("Sales records subtotal, 2025 (not reconciled)", filing)
        self.assertIn("$750,000.50 across 2 sales", filing)
        # Run 3, R3-03: named as a subtotal, never as the figure an agent's fee form asks for.
        self.assertIn("it is not any certifying agent's fee figure", filing)
        self.assertIn("Renewal Fee Form (AGR 2521) asks for income received", filing)
        self.assertNotIn("ask for this figure", filing)


class TheCoveragePageTests(_Farm):
    def test_the_parcel_placeholder_is_the_operations_own_parcels(self):
        Parcel.objects.create(name="Creek Block", establishment=self.est, area=6.8)
        text = _text(_coverage_pdf(self.osp))
        self.assertNotIn("<parcel>", text)
        self.assertIn("one Parcel Application per parcel (Ridge Block, Creek Block)", text)

    def test_a_form_only_some_growers_owe_is_qualified(self):
        text = _text(_coverage_pdf(self.osp))
        self.assertIn("Fungi / Mushroom Production (AGR 2121) — only where it applies to the operation", text)

    def test_the_handler_rules_are_not_misstated(self):
        text = _text(_coverage_pdf(self.osp))
        self.assertNotIn("licenses", text)
        self.assertNotIn("5% threshold", text)


class TheAuditExhibitTests(_Farm):
    def _harvest(self, season, day, lbs, packed):
        return ProductionEvent.objects.create(
            history=season,
            type="HA",
            description="Harvest",
            date=datetime(2025, 9, day, 15, tzinfo=dt_tz.utc),
            yield_quantity=Decimal(lbs),
            yield_unit="lbs",
            quantity_returned_from_handler=Decimal(packed) if packed is not None else None,
            handler_return_unit="lbs",
            storage_location="Packer CA room 7",
        )

    def test_the_pack_out_explains_the_gap_between_harvest_and_sale(self):
        season = self._season()
        self._harvest(season, 12, "117000", "113490")
        self._harvest(season, 13, "112500", "109125")
        SalesRecord.objects.create(
            production=season,
            sale_date=date(2025, 10, 14),
            buyer_name="Sample Packer",
            quantity=Decimal("222615"),
            quantity_unit="lb",
            organic_on_invoice=True,
        )
        text = _text(_audit_trail_exhibit_pdf(self.osp))
        self.assertIn("packed out by the handler 222,615 lb", text)
        self.assertIn("Sales match the pack-out", text)
        # The pack-out records the difference; nothing records its cause (audit 2026-10, T22).
        self.assertIn("The handler's pack-out records 6,885 lb less than was harvested", text)
        self.assertNotIn("culls", text)
        self.assertNotIn("shrink", text)
        self.assertNotIn("State where it went", text)
        # One number format on the page: the harvest lines as well as the balance.
        self.assertIn("117,000 lb", text)
        self.assertNotIn("117000 lbs", text)

    def test_the_buffer_crop_is_counted_apart_and_its_sale_is_shown(self):
        """§ 205.202(c) crop is not organic crop, and the packet must show what became of it.

        Netted into the organic lot it made the organic harvest look bigger than the fruit that
        could be sold as organic; and because the exhibit walks one lot, a buffer row on another
        block appeared nowhere at all (2026-09-12).
        """
        season = self._season()
        self._harvest(season, 12, "117000", "93600")
        ProductionEvent.objects.create(
            history=season,
            type="HA",
            description="Harvest — buffer row, conventional",
            date=datetime(2025, 9, 24, 15, tzinfo=dt_tz.utc),
            yield_quantity=Decimal("10800"),
            yield_unit="lbs",
            buffer_disposition="sold_conventional",
            buffer_disposition_quantity="12 bins from the west buffer row",
            buffer_disposition_evidence="Delivery tag and conventional sales record, buffer-crop folder",
        )
        SalesRecord.objects.create(
            production=season,
            sale_date=date(2025, 10, 14),
            buyer_name="Sample Packer",
            quantity=Decimal("93600"),
            quantity_unit="lb",
            organic_on_invoice=True,
        )
        SalesRecord.objects.create(
            production=season,
            sale_date=date(2025, 10, 2),
            buyer_name="Sample Hills Fruit Co.",
            quantity=Decimal("10800"),
            quantity_unit="lb",
            invoice_number="SHF-2025-0331",
            organic_on_invoice=False,
        )
        text = _text(_audit_trail_exhibit_pdf(self.osp))
        # The organic lot balances on its own: neither the buffer pick nor its sale is netted in.
        self.assertIn("Harvested 117,000 lb (1 harvest record)", text)
        self.assertIn("Sales match the pack-out", text)
        # And the buffer crop is stated, with the sale that proves it was not sold as organic.
        self.assertIn("Buffer crop (7 CFR 205.202(c))", text)
        self.assertIn("Part C — Buffer crop", text)
        self.assertIn("Sample Hills Fruit Co.", text)
        self.assertIn("organic status on invoice: No", text)
        self.assertIn("Documentation: Delivery tag", text)

    def test_without_a_pack_out_the_operator_is_still_asked(self):
        season = self._season()
        self._harvest(season, 12, "117000", None)
        SalesRecord.objects.create(
            production=season,
            sale_date=date(2025, 10, 14),
            buyer_name="P",
            quantity=Decimal("100000"),
            quantity_unit="lb",
        )
        self.assertIsNone(sample_trail(self.est).balance.packed_out)
        text = _text(_audit_trail_exhibit_pdf(self.osp))
        self.assertIn("is on no sale, pack-out or loss record in Trazo for this lot. State where it went", text)
        self.assertNotIn("culled", text)
        self.assertNotIn("shrink", text)

    def test_no_field_name_and_the_settlement_link_is_stated(self):
        self.osp.sections = {
            "recordkeeping_description": {
                "common_osp_records": {
                    key: {"confirmed": True, "confirmed_at": "2026-02-16T19:30:00+00:00", "confirmed_by": self.user.pk}
                    for key in ("harvest_records", "settlement_statements")
                }
            }
        }
        self.osp.save(update_fields=["sections"])
        rows = {row.name: row for row in document_table(self.est, self.osp)}
        self.assertIn("Invoice number + Lot ID", rows["Settlement statements"].linking_element)
        text = _text(_audit_trail_exhibit_pdf(self.osp))
        self.assertNotIn("History.lot_id", text)
        self.assertNotIn("one real lot", text)


class TheModulePagesTests(_Farm):
    def test_section_eleven_is_never_printed_as_a_section_sign(self):
        text = _text(generate_module_pdf(self.osp, "g8_0_record_keeping"))
        self.assertNotIn("§ 11", text)
        self.assertIn("G8.0", text)  # the document's own name leads the footer

    def test_a_certified_parcel_is_not_described_as_merely_eligible(self):
        for year in (2023, 2024, 2025):
            ParcelCropHistory.objects.create(
                parcel=self.parcel, year=year, crop_grown="Apples", production_method="organic"
            )
        self.parcel.application_answers = {"currently_certified": "yes"}
        self.parcel.buffer_zones = [
            {"direction": "West", "adjoining_land_use": "Conventional orchard", "drift_risk": "medium"}
        ]
        self.parcel.save(update_fields=["application_answers", "buffer_zones"])
        text = _text(generate_module_pdf(self.osp, "parcel_application", parcel=self.parcel))
        # Certification status is the operation's statement, on its own line. It is not turned into
        # a declaration about prohibited inputs, which is not even asked of a certified parcel.
        self.assertIn("The operation states this parcel is currently certified organic", text)
        self.assertIn("not asked of a parcel the operation states is currently certified", text)
        self.assertNotIn("Certified organic, as the operation states", text)
        self.assertNotIn("declares no prohibited material", text)
        self.assertIn("drift risk: Medium", text)
        self.assertIn("Parcel Application — Ridge Block", text)

    def test_parcels_print_in_the_order_the_operation_entered_them(self):
        Parcel.objects.create(name="Alpha Block", establishment=self.est, area=1.0)
        names = [
            n
            for n in zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))).namelist()
            if n.startswith("parcels/parcel-application")
        ]
        self.assertEqual(
            names, ["parcels/parcel-application-Ridge Block.pdf", "parcels/parcel-application-Alpha Block.pdf"]
        )


class TheCitationsTests(TestCase):
    """Checked against the eCFR text of 7 CFR 205 on 2026-09-11."""

    def test_annual_seedlings_cite_the_variance_clause(self):
        self.assertEqual(MODULES_BY_KEY["g3_1_seedlings"].nop_cites, ("§ 205.204(a)(3)",))

    def test_purchase_and_certificate_records_cite_traceability(self):
        cites = {rt.key: rt.cfr_cite for rt in COMMON_OSP_RECORD_TYPES}
        for key in ("purchase_receipts_invoices", "organic_certificates", "purchase_records", "purchase_receipts"):
            self.assertEqual(cites[key], "7 CFR 205.103(b)(2)", key)
