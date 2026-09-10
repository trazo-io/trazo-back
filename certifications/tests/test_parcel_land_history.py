"""
The Parcel Application page prints what § 205.202(b) asks a reviewer to see: who managed the land
during the 36 months, when, under which certificate, and what was applied — on the PARCEL page,
which is the form every certifier asks it on.

WHY (2026-09-09): the packet cover printed the certificate, the per-production audit dossier printed
the prior-manager table, and the parcel page printed "2 landowner affidavit(s) on file." CCOF Parcel
Application §F/§G, OTCO C2 2.1/2.4/2.5 and WSDA AGR 2264/2262 all ask on the parcel form. Same
defect class as the 2026-08-20 sweep — fixed on one surface, absent on its sibling.

Three rules these tests pin:
  * absences are stated, never rendered as an affirmative ("Not answered", "cannot be accounted
    for", "No certificate is on file");
  * a contradiction is shown and flagged, never resolved by hiding one side;
  * the accounting names dates; it never says "eligible".
"""

import io
import zipfile
from datetime import date, timedelta
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from certifications.models import Certification, LandownerAffidavit, OrganicSystemPlan
from certifications.services.osp_module_pdf import generate_module_pdf, generate_osp_packet
from certifications.services.parcel_land_history import (
    CURRENT_MANAGER,
    DECLARED_NONE,
    DECLARED_NOT_ANSWERED,
    PRIOR_MANAGER,
    ManagerRow,
    affidavit_attachment_name,
    certificate_line,
    coverage,
    current_manager_row,
    prior_manager_rows,
)
from company.models import Company, Establishment
from product.models import Parcel, ParcelCropHistory

TODAY = date(2026, 9, 9)
WINDOW_START = date(2023, 9, 9)


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


def _prior(start, end, name="Dale Hobbs") -> ManagerRow:
    return ManagerRow(
        name=name,
        role=PRIOR_MANAGER,
        period_start=start,
        period_end=end,
        last_prohibited=None,
        declared=DECLARED_NOT_ANSWERED,
    )


class CoverageTests(SimpleTestCase):
    """The 36-month window, accounted for from tenure plus affidavit periods. Dates, not verdicts."""

    def _parcel(self, began):
        return SimpleNamespace(date_began_managing=began)

    def test_no_tenure_start_cannot_be_accounted_for(self):
        c = coverage(self._parcel(None), [], today=TODAY)
        self.assertIsNone(c.complete)
        self.assertIn("cannot be accounted for", c.text)
        self.assertNotIn("[REVIEW]", c.text)

    def test_full_tenure_needs_no_affidavit(self):
        c = coverage(self._parcel(date(2020, 1, 1)), [], today=TODAY)
        self.assertTrue(c.complete)
        self.assertEqual(c.gaps, ())
        self.assertIn("full 36 months", c.text)
        self.assertIn("since 2020-01-01", c.text)

    def test_tenure_starting_on_the_window_start_is_full(self):
        self.assertTrue(coverage(self._parcel(WINDOW_START), [], today=TODAY).complete)

    def test_a_short_tenure_with_no_affidavit_names_the_gap_in_dates(self):
        c = coverage(self._parcel(date(2025, 9, 1)), [], today=TODAY)
        self.assertFalse(c.complete)
        self.assertEqual(c.gaps, ((WINDOW_START, date(2025, 8, 31)),))
        self.assertIn("[REVIEW] not accounted for: 2023-09-09 to 2025-08-31", c.text)
        self.assertIn("no prior-manager affidavit on file", c.text)

    def test_an_affidavit_ending_the_day_before_tenure_closes_the_window(self):
        c = coverage(self._parcel(date(2025, 9, 1)), [_prior(date(2019, 1, 1), date(2025, 8, 31))], today=TODAY)
        self.assertTrue(c.complete, c.text)
        self.assertEqual(c.gaps, ())
        self.assertIn("every day of the window is accounted for", c.text)

    def test_a_partial_affidavit_leaves_exactly_the_uncovered_days(self):
        c = coverage(self._parcel(date(2025, 9, 1)), [_prior(date(2024, 1, 1), date(2025, 8, 31))], today=TODAY)
        self.assertFalse(c.complete)
        self.assertEqual(c.gaps, ((WINDOW_START, date(2023, 12, 31)),))

    def test_an_affidavit_without_an_end_is_taken_to_run_until_tenure_began(self):
        c = coverage(self._parcel(date(2025, 9, 1)), [_prior(date(2022, 1, 1), None)], today=TODAY)
        self.assertTrue(c.complete, c.text)

    def test_an_affidavit_without_a_period_is_counted_but_not_placed(self):
        c = coverage(self._parcel(date(2025, 9, 1)), [_prior(None, None)], today=TODAY)
        self.assertEqual(c.unplaced, 1)
        self.assertFalse(c.complete)
        self.assertIn("carry no management period", c.text)

    def test_the_accounting_never_rules_on_eligibility(self):
        for began, prior in (
            (None, []),
            (date(2020, 1, 1), []),
            (date(2025, 9, 1), []),
            (date(2025, 9, 1), [_prior(None, None)]),
        ):
            text = coverage(self._parcel(began), prior, today=TODAY).text.lower()
            self.assertNotIn("eligible", text)


class ManagerRowsTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Cascade Ridge Co")
        self.establishment = Establishment.objects.create(name="Cascade Ridge Orchards", company=company, state="WA")
        self.parcel = Parcel.objects.create(
            name="North Block", establishment=self.establishment, area=3.2, date_began_managing=date(2025, 9, 1)
        )

    def _affidavit(self, **kw):
        base = dict(
            parcel=self.parcel,
            previous_manager_name="Dale Hobbs",
            management_period_start=date(2022, 1, 1),
            management_period_end=date(2025, 8, 31),
            last_prohibited_date=date(2022, 6, 10),
            previous_manager_signed_date=date(2025, 9, 2),
        )
        base.update(kw)
        return LandownerAffidavit.objects.create(**base)

    def test_a_prior_manager_row_carries_the_four_facts_every_certifier_asks(self):
        self._affidavit(
            yearly_history=[
                {"year": 2022, "inputs": "glyphosate", "manufacturer": "Bayer", "date_applied": "2022-06-10"}
            ]
        )
        rows = prior_manager_rows(self.parcel)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row.name, row.role), ("Dale Hobbs", PRIOR_MANAGER))
        self.assertEqual((row.period_start, row.period_end), (date(2022, 1, 1), date(2025, 8, 31)))
        self.assertEqual(row.last_prohibited, date(2022, 6, 10))
        self.assertEqual(row.declared, "1 year(s) listed")
        self.assertFalse(row.contradiction)
        self.assertEqual(row.attachment, "")

    def test_declared_none_over_a_row_naming_an_input_is_flagged_not_hidden(self):
        self._affidavit(no_materials_applied=True, yearly_history=[{"year": 2023, "inputs": "2,4-D"}])
        row = prior_manager_rows(self.parcel)[0]
        self.assertTrue(row.contradiction)
        self.assertIn("CONTRADICTION", row.declared)

    def test_an_empty_table_is_not_a_declaration_of_none(self):
        self._affidavit(no_materials_applied=None, yearly_history=[])
        self.assertEqual(prior_manager_rows(self.parcel)[0].declared, DECLARED_NOT_ANSWERED)
        self._affidavit(no_materials_applied=True, yearly_history=[], previous_manager_name="Ana Ruiz")
        self.assertEqual([r.declared for r in prior_manager_rows(self.parcel) if r.name == "Ana Ruiz"], [DECLARED_NONE])

    def test_the_current_manager_row_is_the_operation(self):
        row = current_manager_row(self.parcel, {})
        self.assertEqual((row.name, row.role), ("Cascade Ridge Orchards", CURRENT_MANAGER))
        self.assertEqual((row.period_start, row.period_end), (date(2025, 9, 1), None))
        self.assertEqual(row.declared, DECLARED_NOT_ANSWERED)
        self.assertFalse(row.contradiction)

    def test_the_operators_no_prohibited_declaration_over_a_dated_application_is_flagged(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=2025,
            crop_grown="Apples",
            last_prohibited_substance="Glyphosate",
            date_last_prohibited=date(2025, 10, 1),
        )
        flagged = current_manager_row(self.parcel, {"dlpm_none_within_tenure": True})
        self.assertTrue(flagged.contradiction)
        self.assertEqual(flagged.last_prohibited, date(2025, 10, 1))
        # Envelope-shaped answers are read the same way.
        self.assertTrue(current_manager_row(self.parcel, {"dlpm_none_within_tenure": {"value": True}}).contradiction)

    def test_answering_no_to_the_negated_statement_is_not_printed_as_an_application(self):
        """ "No" to "no prohibited material has been applied" is ambiguous; the records, not the
        inverted answer, are what may say a material was applied."""
        row = current_manager_row(self.parcel, {"dlpm_none_within_tenure": False})
        self.assertEqual(row.declared, "Declaration not made (answered No)")
        self.assertNotIn("applied during", row.declared)
        self.assertFalse(row.contradiction)

    def test_a_reversed_affidavit_period_counts_its_start_day_only(self):
        c = coverage(
            SimpleNamespace(date_began_managing=date(2025, 9, 1)),
            [_prior(date(2025, 6, 1), date(2024, 1, 1))],
            today=TODAY,
        )
        self.assertFalse(c.complete)
        self.assertEqual(c.gaps[0][0], WINDOW_START)

    def test_a_prohibited_application_before_tenure_does_not_contradict_the_declaration(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=2024,
            crop_grown="Apples",
            last_prohibited_substance="Glyphosate",
            date_last_prohibited=date(2024, 6, 1),
        )
        self.assertFalse(current_manager_row(self.parcel, {"dlpm_none_within_tenure": True}).contradiction)

    def test_attachment_name_only_when_a_signed_document_exists(self):
        bare = self._affidavit()
        self.assertEqual(affidavit_attachment_name(bare), "")
        signed = self._affidavit(
            previous_manager_name="Ana Ruiz", signed_document=SimpleUploadedFile("ruiz.pdf", b"%PDF-1.4 signed")
        )
        self.assertEqual(affidavit_attachment_name(signed), f"{signed.pk}-Ana Ruiz.pdf")
        self.assertEqual(
            [r.attachment for r in prior_manager_rows(self.parcel) if r.name == "Ana Ruiz"],
            [f"parcels/affidavits/{signed.pk}-Ana Ruiz.pdf"],
        )


class CertificateLineTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Cert Co")
        self.establishment = Establishment.objects.create(name="Cert Ranch", company=company, state="WA")

    def test_no_certificate_is_stated_as_absent(self):
        self.assertFalse(certificate_line(self.establishment).on_file)

    def test_the_certification_row_supplies_number_agent_dates_and_document(self):
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certification_number="WSDA-2024-118",
            certifier_name="Washington State Department of Agriculture",
            effective_date=date(2024, 3, 1),
            expiry_date=date(2027, 3, 1),
            document_url="https://example.org/wsda-2024-118.pdf",
        )
        line = certificate_line(self.establishment)
        self.assertTrue(line.on_file)
        self.assertEqual((line.number, line.agent), ("WSDA-2024-118", "Washington State Department of Agriculture"))
        self.assertEqual((line.effective, line.expiry), (date(2024, 3, 1), date(2027, 3, 1)))
        self.assertEqual(line.document_url, "https://example.org/wsda-2024-118.pdf")
        self.assertEqual(line.source, "certification")

    def test_a_number_from_the_plans_approval_gate_borrows_no_dates_from_another_record(self):
        OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            approval_certificate_number="OT-44-1201",
            approval_certifier_name="Oregon Tilth",
        )
        line = certificate_line(self.establishment)
        self.assertEqual((line.number, line.agent, line.source), ("OT-44-1201", "Oregon Tilth", "osp"))
        self.assertIsNone(line.effective)
        self.assertEqual(line.document_url, "")


class ParcelPagePrintsTheEvidenceTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Cascade Ridge Co")
        self.establishment = Establishment.objects.create(name="Cascade Ridge Orchards", company=company, state="WA")
        self.parcel = Parcel.objects.create(
            name="North Block",
            establishment=self.establishment,
            area=3.2,
            apn="123-456-789",
            date_began_managing=date.today() - timedelta(days=365),
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment, version_number=1, status="active", submitted_at=timezone.now()
        )

    def _page(self) -> str:
        return _pdf_text(generate_module_pdf(self.osp, "parcel_application", parcel=self.parcel))

    def _answer(self, **answers):
        self.parcel.application_answers = {**(self.parcel.application_answers or {}), **answers}
        self.parcel.save(update_fields=["application_answers"])

    def test_typed_years_print_their_materials_by_name_and_date(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=2024,
            crop_grown="Pears",
            substances_applied="Roundup on the alleys",
            substance_applications=[
                {"material": "Roundup PowerMAX", "manufacturer": "Bayer", "application_dates": "3/14/2024 and 6/2/2024"}
            ],
        )
        text = self._page()
        self.assertIn("Roundup on the alleys", text)
        self.assertIn("Roundup PowerMAX", text)
        self.assertIn("Bayer", text)
        self.assertIn("3/14/2024 and 6/2/2024", text)

    def test_the_prior_manager_table_replaces_the_count(self):
        LandownerAffidavit.objects.create(
            parcel=self.parcel,
            previous_manager_name="Dale Hobbs",
            management_period_start=date(2022, 1, 1),
            management_period_end=date(2025, 8, 31),
            last_prohibited_date=date(2022, 6, 10),
            landowner_name="Hobbs Family Trust",
        )
        text = self._page()
        self.assertNotIn("affidavit(s) on file", text)
        self.assertIn("Dale Hobbs", text)
        self.assertIn("prior manager", text)
        self.assertIn("01/22", text)
        self.assertIn("08/25", text)
        self.assertIn("2022-06-10", text)
        self.assertIn("Hobbs Family Trust", text)
        # pdfplumber interleaves the wrapped cells of one table row, so multi-word cell phrases are
        # asserted on the rows (ManagerRowsTests) and only single tokens are asserted on the PDF.
        self.assertIn("Cascade Ridge", text)
        self.assertIn("current", text)
        self.assertIn("prior", text)
        # The affidavit dated the clock (2022-06-10 + 36 months has passed) while no field history
        # exists. Until 2026-09-09 §B printed "Eligible for organic harvest." directly under
        # "Not established — no field history on file" — a self-assigned determination next to its
        # own contradiction. The note now states the arithmetic and leaves the call to the agent.
        self.assertNotIn("Eligible for organic harvest", text)
        self.assertIn("certifying agent's determination", text)

    def test_a_short_tenure_with_no_affidavit_is_flagged_with_dates_not_a_verdict(self):
        text = self._page()
        self.assertIn("No prior-manager affidavit on file", text)
        self.assertIn("not accounted for", text)
        self.assertNotIn("Eligible for organic harvest", text)

    def test_the_certificate_prints_on_the_parcel_page_only_when_the_parcel_is_stated_certified(self):
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certification_number="WSDA-2024-118",
            certifier_name="Washington State Department of Agriculture",
            effective_date=date(2024, 3, 1),
        )
        self._answer(currently_certified="no")
        self.assertNotIn("Certificate of record", self._page())
        self._answer(currently_certified="yes", no_lapse_attested=True)
        text = self._page()
        self.assertIn("Certificate of record: WSDA-2024-118", text)
        self.assertIn("Washington State Department of Agriculture", text)
        self.assertIn("effective 2024-03-01", text)
        self.assertIn("no lapse in organic management", text)
        self.assertIn("Whether this parcel is listed on it", text)

    def test_no_certificate_on_file_is_stated_not_invented(self):
        self._answer(currently_certified="yes")
        text = self._page()
        self.assertIn("No certificate is on file", text)
        self.assertNotIn("Certificate of record:", text)

    def test_the_operators_declaration_prints_and_a_contradiction_is_flagged(self):
        self._answer(currently_certified="no", dlpm_none_within_tenure=True)
        text = self._page()
        self.assertIn("None applied since", text)
        self.assertIn("(declared)", text)
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=date.today().year,
            crop_grown="Apples",
            last_prohibited_substance="Glyphosate",
            date_last_prohibited=date.today() - timedelta(days=30),
        )
        text = self._page()
        self.assertIn("[REVIEW] Cascade Ridge Orchards", text)
        self.assertIn("None applied since", text)

    def test_the_signed_affidavit_rides_in_the_packet_under_the_path_the_page_names(self):
        aff = LandownerAffidavit.objects.create(
            parcel=self.parcel,
            previous_manager_name="Dale Hobbs",
            management_period_start=date(2022, 1, 1),
            management_period_end=date(2025, 8, 31),
            signed_document=SimpleUploadedFile("hobbs-signed.pdf", b"%PDF-1.4 signed affidavit"),
        )
        expected = f"parcels/affidavits/{aff.pk}-Dale Hobbs.pdf"
        with zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))) as zf:
            self.assertIn(expected, zf.namelist())
            self.assertEqual(zf.read(expected), b"%PDF-1.4 signed affidavit")
        self.assertIn(f"signed affidavit attached at {expected}", self._page().replace("\n", " "))
