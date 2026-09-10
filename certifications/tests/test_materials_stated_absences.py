"""
The materials list a certifier reads says what is missing, and "no materials used" is a statement.

WHY (2026-09-09): CCOF NOPB41 §A/§B, WSDA AGR 2196 and OTCO C11 ask three cells on EVERY row —
product (with formulation), manufacturer, reason for use — and OTCO says a row without a
manufacturer "cannot be reviewed and will not be approved". The printed list omitted a missing cell
silently, so a row that needed one read like a row that never did. And an operation with no inputs
at all printed "No input materials have been added…" — an unfinished list — followed by five
attestations that everything in use was on it (CCOF Header C, OTCO Hdr-2).

Rules pinned here:
  * the compact line is unchanged (editor, narrative); the certifier-facing line states absences;
  * a stated absence is never an assertion about the material — "not stated", not "none";
  * "no materials used" replaces the unfinished-list sentence only when the operator states it,
    and a record that disagrees is named beside it, never dropped.
"""

import io
from datetime import date

from django.test import TestCase
from django.utils import timezone

from certifications.models import NationalListSubstance, OrganicSystemPlan, PlanMaterialEntry
from certifications.osp_modules.conditions import visible_questions
from certifications.osp_modules.materials_application import MATERIALS_APPLICATION
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.plan_materials import PlanMaterial, none_used_contradictions, plan_materials
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


class DisplayLineTests(TestCase):
    def test_the_compact_line_is_unchanged(self):
        row = PlanMaterial(name="Feather Meal 13-0-0", source="Operator-entered", manufacturer="BioAg", entry_id=1)
        self.assertEqual(row.display(), "Feather Meal 13-0-0 — BioAg")

    def test_the_certifier_line_states_a_missing_manufacturer_and_reason(self):
        row = PlanMaterial(name="Rexius Organic Compost", source="Operator-entered", entry_id=1)
        line = row.display(stated_absences=True)
        self.assertEqual(line, "Rexius Organic Compost — manufacturer not stated — reason for use not stated")

    def test_a_filled_row_prints_its_reason(self):
        row = PlanMaterial(
            name="Tiger 90CR",
            source="Operator-entered",
            manufacturer="Tiger-Sul",
            identifier="National List substance",
            reason="Soil pH on the blueberry beds",
            entry_id=1,
        )
        self.assertEqual(
            row.display(stated_absences=True),
            "Tiger 90CR — Tiger-Sul — National List substance — for Soil pH on the blueberry beds",
        )

    def test_a_bare_national_list_substance_says_the_brand_is_not_stated(self):
        row = PlanMaterial(name="Elemental sulfur", source="National List", identifier="§ 205.601(i)(10)", source_id=1)
        line = row.display(stated_absences=True)
        self.assertIn("brand and formulation not stated", line)
        self.assertIn("manufacturer not stated", line)
        self.assertTrue(line.startswith("Elemental sulfur"))

    def test_a_folded_national_list_row_is_not_told_its_brand_is_missing(self):
        row = PlanMaterial(
            name="Tiger 90CR",
            source="National List",
            identifier="§ 205.601(i)(10)",
            manufacturer="Tiger-Sul",
            entry_id=7,
        )
        self.assertNotIn("brand and formulation", row.display(stated_absences=True))

    def test_a_prohibited_row_keeps_its_review_qualifier_and_is_not_asked_for_a_brand(self):
        row = PlanMaterial(name="Ash from manure burning", source="National List", prohibited=True, source_id=1)
        line = row.display(stated_absences=True)
        self.assertIn("PROHIBITED", line)
        self.assertNotIn("brand and formulation", line)

    def test_no_segment_contains_the_row_separator(self):
        row = PlanMaterial(name="X", source="Operator-entered", entry_id=1)
        for segment in row.display(stated_absences=True).split(" — "):
            self.assertNotIn(" — ", segment)


class NoneUsedTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Bare Ground Co")
        self.establishment = Establishment.objects.create(name="Bare Ground Farm", company=company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment, version_number=1, status="active", submitted_at=timezone.now()
        )

    def _answers(self, **answers):
        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {"materials_application": {"answers": {k: {"value": v} for k, v in answers.items()}}},
        }
        self.osp.save(update_fields=["module_responses"])
        return {k: {"value": v} for k, v in answers.items()}

    def _page(self) -> str:
        return _pdf_text(generate_module_pdf(self.osp, "materials_application"))

    def test_an_empty_list_with_no_statement_still_reads_as_unfinished(self):
        text = self._page()
        self.assertIn("No input materials have been added", text)
        self.assertNotIn("states that no input materials", text)

    def test_the_statement_replaces_the_unfinished_list_sentence(self):
        self._answers(no_materials_used=True)
        text = self._page()
        self.assertIn("The operator states that no input materials or substances are used", text)
        self.assertNotIn("No input materials have been added", text)
        self.assertNotIn("[REVIEW]", text)

    def test_the_statement_hides_the_completeness_attestation_and_page_b(self):
        answers = self._answers(no_materials_used=True)
        visible = {q.key for _page, q in visible_questions(MATERIALS_APPLICATION, answers)}
        self.assertIn("no_materials_used", visible)
        self.assertNotIn("materials_list_complete", visible)
        self.assertNotIn("fertilizers_listed", visible)
        self.assertNotIn("fertilizers_none_used", visible)

    def test_a_category_none_used_hides_only_its_own_attestation(self):
        answers = self._answers(fertilizers_none_used=True)
        visible = {q.key for _page, q in visible_questions(MATERIALS_APPLICATION, answers)}
        self.assertNotIn("fertilizers_listed", visible)
        self.assertIn("pest_disease_weed_listed", visible)
        self.assertIn("materials_list_complete", visible)

    def test_a_statement_over_a_plan_with_rows_is_flagged_not_hidden(self):
        PlanMaterialEntry.objects.create(
            osp=self.osp, product_name="Rexius Organic Compost", listing_basis=PlanMaterialEntry.BASIS_NONE
        )
        answers = self._answers(no_materials_used=True)
        lines = none_used_contradictions(self.osp, answers)
        self.assertEqual(len(lines), 1)
        self.assertIn("1 material(s) are on this plan's list", lines[0])
        text = self._page()
        self.assertIn("Rexius Organic Compost", text)
        self.assertIn("[REVIEW] The plan states that no input materials", text)

    def test_a_category_statement_over_logged_applications_is_flagged(self):
        parcel = Parcel.objects.create(name="Block 1", establishment=self.establishment, area=1.0)
        history = History.objects.create(
            parcel=parcel, name="Blueberries 2026", start_date=date(2026, 1, 1), published=False
        )
        ChemicalEvent.objects.create(
            history=history, type="FE", commercial_name="Feather Meal 13-0-0", date=timezone.now()
        )
        answers = self._answers(fertilizers_none_used=True, pest_disease_weed_none_used=True)
        lines = none_used_contradictions(self.osp, answers)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("no fertilizer or soil amendment materials are used", lines[0])
        self.assertIn("Feather Meal 13-0-0", lines[0])

    def test_the_compiled_narrative_states_absences_too(self):
        """The (a)(2) narrative is frozen into the plan at save time and printed as THE plan in
        `01-organic-system-plan.pdf`. On a rendered packet (2026-09-10) it said
        "Peracetic acid — 205.601 — National List." three pages before the live list said
        "manufacturer not stated" for the same row — a third author of the sentence."""
        from certifications.services.osp_module_compiler import compile_module_contributions

        PlanMaterialEntry.objects.create(
            osp=self.osp, product_name="Rexius Organic Compost", listing_basis=PlanMaterialEntry.BASIS_NONE
        )
        text = "\n".join(compile_module_contributions(self.osp)["inputs_list"])
        self.assertIn("Rexius Organic Compost", text)
        self.assertIn("manufacturer not stated", text)
        self.assertIn("reason for use not stated", text)

    def test_the_certifier_list_states_absences_on_the_page(self):
        sub = NationalListSubstance.objects.create(
            substance_name="Elemental sulfur", cfr_section="205.601", status="allowed"
        )
        self.osp.approved_national_list_substances.add(sub)
        text = " ".join(self._page().split())  # the line wraps mid-phrase in the PDF
        self.assertIn("brand and formulation not stated", text)
        self.assertIn("manufacturer not stated", text)
        self.assertIn("reason for use not stated", text)
        self.assertEqual(len(plan_materials(self.osp)), 1)
