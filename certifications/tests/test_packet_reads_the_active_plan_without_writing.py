"""The renewal packet reads the active plan; it does not write it.

Recordkeeping review, 2026-10-07 (F-06, F-07, F-17). Downloading the v3 packet of the
Calapooia specimen moved `OrganicSystemPlan.updated_at` from 2026-08-21 to the download time,
because `_refresh_narratives_if_editable` recompiled and SAVED the active plan's narratives;
document 01 then printed "Last updated: <today>" on a plan "Submitted 2026-08-21" and said
nothing about holding no submission copy. The same packet's annual update printed "(a)(2)
Additions intended for the coming year (2028)" on a continuation for 2027, and none of its
PDFs carried an outline.

Each test here went red on the code before the fix, on an assertion.
"""

import io
import zipfile
from datetime import date

import pdfplumber
from pdfminer.pdfdocument import PDFDocument, PDFNoOutlines
from pdfminer.pdfparser import PDFParser
from rest_framework.test import APITestCase

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from company.models import Company, Establishment
from users.models import User, WorksIn


def _text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return " ".join((page.extract_text() or "") for page in pdf.pages).replace("\n", " ")


def _outline_titles(pdf_bytes: bytes) -> list:
    doc = PDFDocument(PDFParser(io.BytesIO(pdf_bytes)))
    try:
        return [entry[1] for entry in doc.get_outlines()]
    except PDFNoOutlines:
        return []  # no outline at all: the assertion below is the failure, not this call


class PacketReadsTheActivePlanTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="active-plan@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Active Plan Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Home Ranch", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=3, status="active", created_by=self.user
        )
        self.client.force_authenticate(user=self.user)
        self.materials_url = (
            f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{self.osp.pk}/plan-materials/"
        )

    def _add_material(self, osp=None, name="Rexius Organic Compost"):
        osp = osp or self.osp
        url = f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{osp.pk}/plan-materials/"
        response = self.client.post(
            url,
            {
                "product_name": name,
                "manufacturer": "Rexius",
                "category": "fertilizer_amendment",
                "reason_for_use": "Soil organic matter on the blueberry beds",
                "listing_basis": "none_unlisted",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def _packet(self, osp=None):
        from certifications.services.osp_module_pdf import generate_osp_packet

        return zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp or self.osp)))

    # -- F-06: read, not write ---------------------------------------------

    def test_a_download_leaves_the_active_plan_row_untouched_and_the_packet_still_agrees(self):
        """The 2026-08-28 guarantee (materials module and (a)(2) narrative name the same
        material) must hold WITHOUT the write that produced it on an active plan."""
        self._add_material()  # the only write after activation: an approved-inputs panel edit
        before = OrganicSystemPlan.objects.get(pk=self.osp.pk)
        stored_sections = dict(before.sections or {})

        with self._packet() as zf:
            narrative = _text(zf.read("01-organic-system-plan.pdf"))
            materials_module = _text(zf.read("modules/materials_application.pdf"))

        self.assertIn("Rexius Organic Compost", narrative)
        self.assertIn("Rexius Organic Compost", materials_module)
        after = OrganicSystemPlan.objects.get(pk=self.osp.pk)
        self.assertEqual(after.updated_at, before.updated_at, "downloading a packet wrote the active plan")
        self.assertEqual(after.sections, stored_sections, "downloading a packet rewrote the on-file narrative")

    def test_a_draft_packet_still_persists_the_compiled_narrative(self):
        # Anti-vacuity for the test above: the in-memory path is for ACTIVE plans only. A draft
        # is the operator's working copy and keeps the 2026-08-28 behaviour of writing back.
        draft = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=4, status="draft", created_by=self.user
        )
        self._add_material(osp=draft)
        with self._packet(osp=draft) as zf:
            self.assertIn("Rexius Organic Compost", _text(zf.read("01-organic-system-plan.pdf")))
        draft.refresh_from_db()
        self.assertIn("Rexius Organic Compost", (draft.sections.get("inputs_list") or {}).get("narrative", ""))

    # -- F-06: say what 01 is -----------------------------------------------

    def test_an_active_plan_with_no_submission_copy_says_01_is_generated_from_current_records(self):
        with self._packet() as zf:
            narrative = _text(zf.read("01-organic-system-plan.pdf"))
        self.assertIn("generated from the operation's current records", narrative)
        self.assertIn("holds no copy generated at submission for this version", narrative)
        self.assertIn(f"Generated from current records: {date.today().isoformat()}", narrative)
        self.assertNotIn("Last updated:", narrative)

    def test_the_submission_copy_itself_is_never_labelled_a_reconstruction(self):
        # Review of back #129: the submit flow saves status "submitted" before rendering and
        # assigns submission_pdf after, so the frozen copy looked like a reconstruction while it
        # was being made. The submit call site passes the flag explicitly.
        from certifications.services.osp_pdf_snapshot import GENERATED_FROM_RECORDS_NOTE, generate_osp_snapshot_pdf

        OrganicSystemPlan.objects.filter(pk=self.osp.pk).update(status="submitted", submission_pdf="")
        self.osp.refresh_from_db()
        text = _text(generate_osp_snapshot_pdf(self.osp, generated_from_records=False))
        self.assertNotIn(GENERATED_FROM_RECORDS_NOTE.split(".")[0], text)
        self.assertNotIn("Generated from current records", text)
        self.assertIn("Last updated", text)
        # And the submit view is wired to that flag, not to the derived state.
        import inspect

        from certifications import views as cert_views

        self.assertIn("generate_osp_snapshot_pdf(osp, generated_from_records=False)", inspect.getsource(cert_views))

    def test_a_draft_is_not_labelled_generated_from_current_records(self):
        draft = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=4, status="draft", created_by=self.user
        )
        with self._packet(osp=draft) as zf:
            narrative = _text(zf.read("01-organic-system-plan.pdf"))
        self.assertNotIn("holds no copy generated at submission", narrative)
        self.assertIn("Draft, not submitted", narrative)

    # -- F-07: the coming year is the continuation year ---------------------

    def test_the_additions_heading_names_the_continuation_year(self):
        from certifications.services.osp_module_pdf import render_filing_pdf

        filing = OSPAnnualUpdate.objects.create(
            prior_osp=self.osp,
            reporting_year=2027,
            changes_summary="No change to parcels or inputs.",
            additions=[],
            deletions=[],
        )
        text = _text(render_filing_pdf(filing))
        self.assertIn("Additions intended for the coming year (2027)", text)
        self.assertIn("Deletions intended for the coming year (2027)", text)
        self.assertNotIn("(2028)", text)

    def test_the_model_defines_the_year_as_the_continuation_year(self):
        # The two definitions split once (form help text vs model help text); pin the model's.
        field = OSPAnnualUpdate._meta.get_field("reporting_year")
        self.assertIn("continuation year", field.help_text.lower())
        self.assertIn("intended for this year", field.help_text)

    # -- F-17: navigable PDFs ------------------------------------------------

    def test_the_plan_and_the_question_index_carry_outlines(self):
        self.osp.certifier_name = "Oregon Tilth Certified Organic"
        self.osp.save(update_fields=["certifier_name"])
        with self._packet() as zf:
            plan_titles = _outline_titles(zf.read("01-organic-system-plan.pdf"))
            index_titles = _outline_titles(zf.read("06-question-index.pdf"))
        # 2026-11 citation review: § 205.401(d) is "other information", not an attestation rule.
        self.assertIn("Producer Attestation", plan_titles)
        self.assertTrue(any("(a)(2)" in t for t in plan_titles), plan_titles)
        self.assertTrue(any(t.startswith("O1") for t in index_titles), index_titles)
