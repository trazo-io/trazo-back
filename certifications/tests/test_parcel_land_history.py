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
    land_history_summary,
    prior_manager_rows,
    stated_last_in_tenure,
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
    """The 36-month window, accounted for from the operator's declaration for its tenure plus the
    affidavit periods. Dates, not verdicts.

    2026-10-01 (audit T21): tenure alone used to count. These cases now make the declaration
    explicit (`declared=True`); `UndeclaredTenureTests` below covers the parcel nobody declared
    anything about."""

    def _parcel(self, began, declared=True):
        answers = {"dlpm_none_within_tenure": True} if declared else {}
        return SimpleNamespace(date_began_managing=began, application_answers=answers)

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
        self.assertIn("Every day of the window is accounted for", c.text)
        # Joined to the sentence before it: a lowercase start after a full stop read as a typo.
        self.assertNotIn(". every day", c.text)

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

    def test_an_explicit_no_to_no_materials_with_no_table_is_not_printed_as_not_answered(self):
        self._affidavit(no_materials_applied=False)
        # Printed as the answer it is, never as a statement that materials were applied (local review
        # of back #437); the dossier prints the same words.
        self.assertEqual(
            prior_manager_rows(self.parcel)[0].declared, '"No materials applied" answered No; no materials listed'
        )
        # Never answered stays "Not answered".
        LandownerAffidavit.objects.all().delete()
        self._affidavit()
        self.assertEqual(prior_manager_rows(self.parcel)[0].declared, "Not answered")

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
        self.assertIn("2022-01", text)
        self.assertIn("2025-08", text)
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
        # Reworded 2026-09-11: "Whether this parcel is listed on it is the certificate's own
        # content, not something this page determines" was Trazo hedging about its own scope.
        self.assertIn("The parcels it covers are listed on the certificate itself", text)

    def test_no_certificate_on_file_is_stated_not_invented(self):
        self._answer(currently_certified="yes")
        text = self._page()
        self.assertIn("No certificate is on file", text)
        self.assertNotIn("Certificate of record:", text)
        # The line that follows used to read "This is the operation's certificate" under the absence.
        self.assertNotIn("This is the operation's certificate", text)

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


class LandHistorySummaryTests(TestCase):
    """The wizard reads the same facts the PDF prints, as JSON, from one source."""

    def setUp(self):
        company = Company.objects.create(name="Summary Co")
        self.establishment = Establishment.objects.create(name="Summary Farm", company=company, state="OR")
        self.parcel = Parcel.objects.create(
            name="Block A", establishment=self.establishment, area=2.0, date_began_managing=date(2006, 3, 15)
        )

    def test_the_summary_is_json_shaped_and_names_the_operation_as_current_manager(self):
        import json

        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certification_number="COC-1463",
            certifier_name="Cascadia Organic Certifiers (COC)",
            effective_date=date(2006, 5, 15),
        )
        summary = land_history_summary(self.parcel, {})
        json.dumps(summary)  # every value is serialisable
        self.assertEqual(summary["certificate"]["number"], "COC-1463")
        self.assertEqual(summary["certificate"]["effective"], "2006-05-15")
        self.assertEqual(summary["current_manager"]["name"], "Summary Farm")
        self.assertEqual(summary["current_manager"]["period_start"], "2006-03-15")
        self.assertIsNone(summary["current_manager"]["period_end"])
        # Twenty years of tenure and no declaration: not accounted for (audit T21).
        self.assertFalse(summary["coverage"]["complete"])
        self.parcel.application_answers = {"dlpm_none_within_tenure": True}
        self.parcel.save(update_fields=["application_answers"])
        summary = land_history_summary(self.parcel, {})
        self.assertTrue(summary["coverage"]["complete"])
        self.assertEqual(summary["coverage"]["gaps"], [])
        self.assertEqual(summary["prior_managers"], [])

    def test_no_certificate_is_null_not_an_empty_record(self):
        self.assertIsNone(land_history_summary(self.parcel, {})["certificate"])

    def test_the_parcel_application_endpoint_carries_the_summary(self):
        from rest_framework.test import APIClient

        from users.models import User, WorksIn

        user = User.objects.create_user(email="summary@test.com", password="x", is_verified=True)
        WorksIn.objects.create(user=user, company=self.establishment.company, role=WorksIn.COMPANY_ADMIN)
        client = APIClient()
        client.force_authenticate(user=user)
        url = (
            f"/api/companies/{self.establishment.company.pk}/establishments/{self.establishment.pk}"
            f"/parcels/{self.parcel.pk}/application/"
        )
        response = client.get(url)
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertIn("land_history", response.data)
        self.assertEqual(response.data["land_history"]["current_manager"]["role"], "current manager")
        self.assertEqual(response.data["adjoining_affidavits"], [])


class PageFooterTests(TestCase):
    """The definition stamp is a canvas footer on every page, never the story's last paragraph.

    As a paragraph it landed alone on a third page of parcel 49's application (2026-09-10): a
    sheet in a certifier's packet that said nothing but "generated by Trazo".
    """

    def test_the_stamp_and_a_page_number_are_on_the_page(self):
        company = Company.objects.create(name="Footer Co")
        establishment = Establishment.objects.create(name="Footer Farm", company=company, state="OR")
        osp = OrganicSystemPlan.objects.create(
            establishment=establishment, version_number=1, status="active", submitted_at=timezone.now()
        )
        parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=1.0)
        text = _pdf_text(generate_module_pdf(osp, "parcel_application", parcel=parcel))
        self.assertIn("Definition version", text)
        self.assertIn("generated by Trazo", text)
        self.assertIn("Page 1", text)


class OwnTransitionTests(SimpleTestCase):
    """A grower converting their own ground (overall review OV-PK-F03, deferred half).

    They applied a prohibited material themselves inside their tenure, so they cannot answer "No
    prohibited material has been applied since I began managing it" Yes. Until 2026-11-15 nothing else
    covered their own period: the page printed the whole window as not accounted for and named a prior
    manager's affidavit as missing. CCOF ORGB49 F4 asks the DLPM; F6 asks for prior controllers only when
    the operation has not managed the parcel "for the full past three years (or since the DLPM)", and
    OTCO C2 2.4 begins the history the day after the last prohibited application.
    """

    def _parcel(self, began=date(2018, 4, 1), **answers):
        base = {"currently_certified": "no", "dlpm_none_within_tenure": False}
        base.update(answers)
        return SimpleNamespace(date_began_managing=began, application_answers=base)

    def test_a_stated_dlpm_and_none_since_account_for_the_window_from_that_day(self):
        parcel = self._parcel(dlpm_in_tenure_date="2025-05-10", dlpm_none_since_in_tenure_date=True)
        c = coverage(parcel, [], today=TODAY)
        self.assertTrue(c.complete, c.text)
        self.assertEqual(c.gaps, ())
        self.assertIn("states its last prohibited application on it was 2025-05-10 and declares none since", c.text)
        self.assertIn("run from 2025-05-10", c.text)
        self.assertNotIn("[REVIEW]", c.text)
        self.assertNotIn("affidavit", c.text)

    def test_the_old_reading_named_the_whole_window_and_an_affidavit(self):
        """The same parcel without the date: what every own-transition parcel printed before."""
        c = coverage(self._parcel(), [], today=TODAY)
        self.assertIn(f"[REVIEW] not accounted for: {WINDOW_START.isoformat()} to {TODAY.isoformat()}", c.text)
        self.assertIn("no prior-manager affidavit on file", c.text)

    def test_a_dlpm_before_the_window_with_none_since_is_the_full_36_months(self):
        parcel = self._parcel(dlpm_in_tenure_date="2022-06-01", dlpm_none_since_in_tenure_date=True)
        c = coverage(parcel, [], today=TODAY)
        self.assertTrue(c.complete, c.text)
        self.assertIn("full 36 months (since 2018-04-01)", c.text)
        self.assertIn("2022-06-01, before the window", c.text)

    def test_a_date_with_no_statement_leaves_only_the_days_after_it_open(self):
        for none_since in (None, False):
            with self.subTest(none_since=none_since):
                answers = {"dlpm_in_tenure_date": "2025-05-10"}
                if none_since is not None:
                    answers["dlpm_none_since_in_tenure_date"] = none_since
                c = coverage(self._parcel(**answers), [], today=TODAY)
                self.assertFalse(c.complete)
                self.assertEqual(c.gaps, ((date(2025, 5, 11), TODAY),))
                self.assertIn("[REVIEW] not accounted for: 2025-05-11 to 2026-09-09", c.text)
                self.assertIn("has not declared that none followed", c.text)
                # A declined statement is never turned into "an application followed".
                self.assertNotIn("applied after", c.text)
                self.assertNotIn("affidavit", c.text)

    def test_a_date_outside_the_tenure_is_flagged_and_not_used(self):
        for day, said in (("2016-01-01", "before it began managing it (2018-04-01)"), ("2027-01-01", "after today")):
            with self.subTest(day=day):
                parcel = self._parcel(dlpm_in_tenure_date=day, dlpm_none_since_in_tenure_date=True)
                c = coverage(parcel, [], today=TODAY)
                self.assertFalse(c.complete)
                self.assertIn("[REVIEW] The stated date of the last prohibited application", c.text)
                self.assertIn(said, c.text)
                self.assertIn("[REVIEW] not accounted for", c.text)

    def test_an_answer_left_behind_where_the_questions_are_not_asked_is_not_read(self):
        stale = {"dlpm_in_tenure_date": "2025-05-10", "dlpm_none_since_in_tenure_date": True}
        for changed in (
            {"dlpm_none_within_tenure": True},
            {"currently_certified": "yes"},
            {"dlpm_none_within_tenure": None},
        ):
            with self.subTest(changed=changed):
                parcel = self._parcel(**{**stale, **changed})
                self.assertFalse(stated_last_in_tenure(parcel).placed)
                if changed.get("currently_certified") != "yes":
                    # A certified parcel's accounting reads its agent's route from the database; the
                    # stated date is already shown unread above.
                    self.assertNotIn("states its last prohibited application", coverage(parcel, [], today=TODAY).text)

    def test_envelope_answers_are_read_the_same_way(self):
        parcel = self._parcel(
            dlpm_in_tenure_date={"value": "2025-05-10"}, dlpm_none_since_in_tenure_date={"value": True}
        )
        self.assertTrue(coverage(parcel, [], today=TODAY).complete)

    def test_the_accounting_never_rules_on_eligibility(self):
        for answers in (
            {"dlpm_in_tenure_date": "2025-05-10", "dlpm_none_since_in_tenure_date": True},
            {"dlpm_in_tenure_date": "2022-06-01", "dlpm_none_since_in_tenure_date": True},
            {"dlpm_in_tenure_date": "2025-05-10"},
        ):
            self.assertNotIn("eligible", coverage(self._parcel(**answers), [], today=TODAY).text.lower())


class OwnTransitionRecordsTests(TestCase):
    """The stated DLPM on the current manager's row, the transition clock and the operator's statements."""

    def setUp(self):
        company = Company.objects.create(name="Own Ground Co")
        self.establishment = Establishment.objects.create(name="Own Ground Orchard", company=company, state="WA")
        self.day = date.today() - timedelta(days=200)
        self.parcel = Parcel.objects.create(
            name="Home Block",
            establishment=self.establishment,
            area=8.0,
            date_began_managing=date.today() - timedelta(days=3650),
            application_answers={
                "currently_certified": "no",
                "dlpm_none_within_tenure": False,
                "dlpm_in_tenure_date": self.day.isoformat(),
                "dlpm_none_since_in_tenure_date": True,
            },
        )

    def test_the_current_manager_row_carries_the_date_and_the_statement(self):
        row = current_manager_row(self.parcel, self.parcel.application_answers)
        self.assertEqual(row.declared, f"None applied since {self.day.isoformat()} (declared)")
        self.assertEqual(row.last_prohibited, self.day)
        self.assertFalse(row.contradiction)

    def test_a_dated_prohibited_record_after_the_stated_day_is_flagged(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=date.today().year,
            crop_grown="Apples",
            last_prohibited_substance="Glyphosate",
            date_last_prohibited=self.day + timedelta(days=30),
        )
        row = current_manager_row(self.parcel, self.parcel.application_answers)
        self.assertTrue(row.contradiction)
        self.assertEqual(row.declared, f"None applied since {self.day.isoformat()} (declared)")

    def test_the_transition_clock_reads_the_stated_day(self):
        from product.services.transition_status_service import compute_transition_status

        status = compute_transition_status(self.parcel)
        self.assertEqual(status.last_prohibited_date, self.day)
        self.assertIn("ParcelApplication", [f.source for f in status.findings])

    def test_a_future_or_unasked_date_never_moves_the_clock(self):
        from product.services.transition_status_service import compute_transition_status

        for answers in (
            {"dlpm_in_tenure_date": (date.today() + timedelta(days=30)).isoformat()},
            {"dlpm_none_within_tenure": True},
        ):
            with self.subTest(answers=answers):
                self.parcel.application_answers = {**self.parcel.application_answers, **answers}
                self.parcel.save(update_fields=["application_answers"])
                self.assertIsNone(compute_transition_status(self.parcel).last_prohibited_date)

    def test_the_operator_statements_name_the_date(self):
        from product.services.transition_status_service import operator_statement_lines

        lines = operator_statement_lines(self.parcel)
        self.assertIn(
            f"The operator states the last prohibited material it applied to this parcel was applied on "
            f"{self.day.isoformat()}, and declares none has been applied since.",
            lines,
        )

    def test_the_parcel_page_prints_the_accounting_and_no_affidavit_gap(self):
        osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment, version_number=1, status="draft", submitted_at=timezone.now()
        )
        text = " ".join(_pdf_text(generate_module_pdf(osp, "parcel_application", parcel=self.parcel)).split())
        # The manager table wraps its cells, so the declared state is read as its two halves.
        self.assertIn("None applied since", text)
        self.assertIn(f"{self.day.isoformat()} (declared)", text)
        self.assertIn(f"states its last prohibited application on it was {self.day.isoformat()}", text)
        self.assertIn(f"run from {self.day.isoformat()}", text)
        self.assertNotIn("[REVIEW] not accounted for", text)
        self.assertNotIn("; no prior-manager affidavit on file", text)
        self.assertNotIn("a declaration of no prohibited material sits over a record", text)

    def test_the_questions_are_asked_only_after_a_no_to_the_tenure_declaration(self):
        from certifications.osp_modules.conditions import visible_questions
        from certifications.osp_modules.parcel_application import PARCEL_APPLICATION as module

        keys = {"dlpm_in_tenure_date", "dlpm_none_since_in_tenure_date"}
        for answers, shown in (
            ({"currently_certified": "no", "dlpm_none_within_tenure": False}, True),
            ({"currently_certified": "previously", "dlpm_none_within_tenure": False}, True),
            ({"currently_certified": "no", "dlpm_none_within_tenure": True}, False),
            ({"currently_certified": "no"}, False),
            ({"currently_certified": "yes", "dlpm_none_within_tenure": False}, False),
        ):
            with self.subTest(answers=answers):
                visible = {q.key for _page, q in visible_questions(module, answers)}
                self.assertEqual(keys <= visible, shown)
                if not shown:
                    self.assertFalse(keys & visible)
