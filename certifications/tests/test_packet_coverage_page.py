"""
The packet's coverage page (04-coverage-and-scope.pdf).

CCOF's Guide routes an operation to forms by activity, so a reviewer opening the packet already
knows which forms a crop operation owes. Stating what is absent, and why, is the difference between
a scope decision and an omission — and the page is only worth having if every claim on it is true:

  * it must not describe a form as absent while the ZIP contains it (the first cut listed W2.0
    under "forms Trazo does not generate" while shipping `modules/W2_0.pdf`);
  * every file path it points a reviewer at must exist in the packet;
  * it must survive the conformance register being unreadable, because a packet may not fail to
    generate over a documentation file.
"""

import io
import zipfile

from django.test import TestCase

from certifications.models import OrganicSystemPlan
from certifications.services.osp_module_pdf import _coverage_pdf, generate_osp_packet
from certifications.services.packet_coverage import _PACKET_LOCATION, coverage_rows, exclusion_rows, outstanding_modules
from company.models import Company, Establishment
from product.models import Parcel


def _pdf_text(data: bytes) -> str:
    """Rendered text with whitespace collapsed.

    ReportLab wraps prose at the frame width, so "the producer is the author" arrives split across
    a newline. Asserting on the raw extraction makes a test that fails on line-breaking rather than
    on meaning.
    """
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        raw = "\n".join(page.extract_text() or "" for page in doc.pages)
    return " ".join(raw.split())


class CoveragePageTruthTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Coverage Co")
        self.establishment = Establishment.objects.create(name="Coverage Farm", company=self.company, state="OR")
        Parcel.objects.create(name="Home Block", establishment=self.establishment, area=4.0)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")

    def test_no_form_is_both_generated_and_declared_absent(self):
        generated = {r.document_id for r in coverage_rows() if r.generated}
        absent = {r.document_id for r in exclusion_rows()}
        self.assertEqual(
            generated & absent,
            set(),
            "The page would tell a certifier a form is absent while the same ZIP contains it.",
        )

    def test_every_path_the_page_cites_exists_in_the_packet(self):
        """A wayfinding page that points at files which are not there is worse than none."""
        names = set(zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))).namelist())

        missing = []
        for _title, location in _PACKET_LOCATION.values():
            if "<parcel>" in location:
                # One per parcel; the name carries the parcel, so match the folder and suffix.
                prefix = location.split("<parcel>")[0]
                if not any(n.startswith(prefix) and n.endswith(".pdf") for n in names):
                    missing.append(location)
            elif location not in names:
                missing.append(location)

        self.assertEqual(missing, [], f"coverage page points at files the packet does not contain: {missing}")

    def test_the_page_states_who_authored_the_plan(self):
        # § 205.201(a) makes the PRODUCER the author. A packet that reads as machine-authored is
        # the consultant-written-OSP pathology a certifier is trained to distrust.
        text = _pdf_text(_coverage_pdf(self.osp))
        self.assertIn("producer is the author", text)
        self.assertIn("205.201(a)", text)
        self.assertIn("certifying agent", text)

    def test_the_page_names_the_forms_trazo_does_not_generate(self):
        text = _pdf_text(_coverage_pdf(self.osp))
        self.assertIn("Exempt Handler Affidavit", text)
        self.assertIn("Co-Packer", text)

    def test_the_page_carries_no_internal_severity_language(self):
        # The register is internal and honest about blockers. This page is for the certifying
        # agent, and "P0" is a sentence about our backlog, not about this farm's plan.
        text = _pdf_text(_coverage_pdf(self.osp))
        for internal in ("P0", "P1", "blocker", "root_cause", "not_covered"):
            self.assertNotIn(internal, text, f"internal register language leaked onto the packet page: {internal}")

    def test_the_packet_contains_the_coverage_page_and_the_cover_lists_it(self):
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp)))
        self.assertIn("04-coverage-and-scope.pdf", zf.namelist())
        self.assertIn("04.", _pdf_text(zf.read("00-cover.pdf")))


class CoveragePageDegradationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Degrade Co")
        self.establishment = Establishment.objects.create(name="Degrade Farm", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")

    def test_an_unreadable_register_reduces_the_page_instead_of_breaking_the_packet(self):
        from unittest.mock import patch

        with (
            patch(
                "certifications.services.certifier_register.load_forms",
                side_effect=OSError("register directory missing"),
            ),
            patch(
                "certifications.services.certifier_register.load_scope",
                side_effect=OSError("register directory missing"),
            ),
        ):
            self.assertEqual(exclusion_rows(), [])
            # The packet still builds, and the page still states authorship.
            text = _pdf_text(_coverage_pdf(self.osp))
            self.assertIn("producer is the author", text)
            # Forms the ZIP actually contains are still listed: that map lives in code, not docs.
            self.assertIn("G8.0", text)


class OutstandingModulesTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Pending Co")
        self.establishment = Establishment.objects.create(name="Pending Farm", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")

    def test_a_module_holding_an_attestation_over_an_empty_list_is_reported_unfinished(self):
        # The Class A gate, surfacing where the operation will actually see it.
        self.osp.module_responses = {
            "modules": {
                "g8_0_record_keeping": {
                    "answers": {
                        "records_retention_attestation": {"value": True, "at": "2026-01-01T00:00:00Z"},
                        "lot_numbering": {"value": "trazo_lots", "at": "2026-01-01T00:00:00Z"},
                        "import_export_activity": {"value": ["none"], "at": "2026-01-01T00:00:00Z"},
                    },
                    "completed_at": "2026-01-01T00:00:00Z",
                }
            }
        }
        self.osp.save(update_fields=["module_responses"])
        self.assertIn("G8.0 Record Keeping", outstanding_modules(self.osp))

    def test_a_module_attested_not_applicable_is_not_reported_as_unfinished(self):
        self.osp.module_responses = {"modules": {"w2_0_wild_crop": {"not_applicable": True}}}
        self.osp.save(update_fields=["module_responses"])
        self.assertNotIn("W2.0 Wild Crop Harvesting", outstanding_modules(self.osp))
