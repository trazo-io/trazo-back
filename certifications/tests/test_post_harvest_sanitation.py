"""
Cleaning and sanitation are asked of every handler; water is its own block; the §D row is a row.

WHY (2026-09-12): every sanitation question on G6.4 sat behind the water gate — `uses_water`,
itself visible only when handling_activities included washing or cooling. An operation that wipes
a sorting table with a quaternary-ammonium sanitizer and never wets the crop had no field to say
so, and three certifiers ask it of every handler (CCOF G6.4 B1, WSDA AGR 2121 §L 4-5b, OTCO C7
7.6). CCOF's Materials Application §E asks a ten-type table with Used / Rinsed / Where used; §D
asks a post-harvest contact table whose prefill was dead code (it filtered ChemicalEvent for a
type that model never carries).

Rules pinned here:
  * cleaning methods and the sanitizer boolean are visible with no washing/cooling activity;
  * the water block gates its own children; chlorine's final-rinse radio sits behind chlorine;
  * the §D prefill and the none-used check read ProductionEvent PH `sanitizer_name`;
  * the workbook's logged rows include a wash-water sanitizer; the materials page prints the
    operator's post-harvest rows under their own heading;
  * the module page prints the ten types and the rinsed set.
"""

import io
import os
from datetime import date

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from certifications.models import OrganicSystemPlan, PlanMaterialEntry
from certifications.osp_modules.conditions import visible_questions
from certifications.osp_modules.materials_application import MATERIALS_APPLICATION
from certifications.osp_modules.stubs import G6_4_HANDLING
from certifications.services.common_osp_workbooks import _material_rows
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.plan_materials import logged_post_harvest_sanitizers, none_used_contradictions
from company.models import Company, Establishment
from history.models import Production, ProductionEvent
from product.models import Parcel

DUMP_DIR = os.environ.get("TRAZO_DUMP_PDF_DIR")


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


def _visible(answers: dict) -> set:
    return {q.key for _page, q in visible_questions(G6_4_HANDLING, answers)}


DRY_HANDLER = {"handling_activities": ["sorting_grading", "packing"]}


class VisibilityTests(SimpleTestCase):
    def test_cleaning_and_sanitizer_questions_do_not_wait_for_water(self):
        visible = _visible(DRY_HANDLER)
        self.assertIn("food_contact_cleaning_methods", visible)
        self.assertIn("uses_equipment_sanitizer_or_cleaner", visible)
        self.assertIn("uses_water", visible)
        self.assertNotIn("post_harvest_water_uses", visible)
        self.assertNotIn("water_source_sanitizer", visible)

    def test_the_sanitizer_boolean_opens_the_type_table_and_residue_questions(self):
        visible = _visible({**DRY_HANDLER, "uses_equipment_sanitizer_or_cleaner": True})
        for key in (
            "equipment_sanitizer_types",
            "equipment_sanitizer_types_rinsed",
            "equipment_sanitizer_where_used",
            "sanitizer_residual_free_assurance",
        ):
            self.assertIn(key, visible, key)
        self.assertNotIn("sanitizer_residual_testing_protocol", visible)
        visible = _visible(
            {
                **DRY_HANDLER,
                "uses_equipment_sanitizer_or_cleaner": True,
                "sanitizer_residual_free_assurance": ["residue_testing"],
            }
        )
        self.assertIn("sanitizer_residual_testing_protocol", visible)

    def test_water_gates_its_own_block_and_chlorine_gates_the_rinse_radio(self):
        wet = {**DRY_HANDLER, "uses_water": True}
        visible = _visible(wet)
        for key in (
            "post_harvest_water_uses",
            "post_harvest_water_source",
            "water_source_sanitizer",
            "wash_water_additives_added",
        ):
            self.assertIn(key, visible, key)
        self.assertNotIn("wash_water_chlorine_added", visible)
        self.assertNotIn("wash_water_chlorine_final_rinse", visible)
        visible = _visible({**wet, "wash_water_additives_added": True, "wash_water_chlorine_added": True})
        self.assertIn("wash_water_chlorine_final_rinse", visible)
        self.assertNotIn("wash_water_chlorine_final_rinse_other", visible)
        visible = _visible(
            {
                **wet,
                "wash_water_additives_added": True,
                "wash_water_chlorine_added": True,
                "wash_water_chlorine_final_rinse": "other",
            }
        )
        self.assertIn("wash_water_chlorine_final_rinse_other", visible)

    def test_the_ten_ccof_types_are_offered_and_the_rinsed_set_mirrors_them(self):
        by_key = {q.key: q for p in G6_4_HANDLING.pages for q in p.questions}
        types = [o.value for o in by_key["equipment_sanitizer_types"].options]
        self.assertEqual(len(types), 10)
        for expected in ("detergent_soap_cleaner", "chlorine", "peracetic_acid", "quaternary_ammonium", "ozone"):
            self.assertIn(expected, types)
        rinsed = [o.value for o in by_key["equipment_sanitizer_types_rinsed"].options]
        self.assertEqual(rinsed[:-1], types)
        self.assertTrue(by_key["equipment_sanitizer_types_rinsed"].options[-1].exclusive)


class _Farm(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Flume Co")
        self.establishment = Establishment.objects.create(name="Flume Farm", company=company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment, version_number=1, status="active", submitted_at=timezone.now()
        )
        parcel = Parcel.objects.create(name="Block 1", establishment=self.establishment, area=1.0)
        self.history = Production.objects.create(
            parcel=parcel, name="Apples 2026", start_date=date(2026, 1, 1), published=False
        )

    def _wash(self, sanitizer, **extra):
        return ProductionEvent.objects.create(
            history=self.history, type="PH", date=timezone.now(), sanitizer_name=sanitizer, **extra
        )

    def _module_answers(self, module, **answers):
        responses = self.osp.module_responses or {"schema_version": 1, "modules": {}}
        responses.setdefault("modules", {})[module] = {"answers": {k: {"value": v} for k, v in answers.items()}}
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])
        return {k: {"value": v} for k, v in answers.items()}


class RecordsTests(_Farm):
    def test_the_none_used_statement_is_set_against_the_wash_records(self):
        self._wash("SaniDate 5.0")
        answers = self._module_answers("materials_application", post_harvest_contact_none_used=True)
        lines = none_used_contradictions(self.osp, answers)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("no post-harvest contact materials", lines[0])
        self.assertIn("SaniDate 5.0", lines[0])
        self.assertEqual(logged_post_harvest_sanitizers(self.establishment), ["SaniDate 5.0"])

    def test_a_wash_record_with_no_sanitizer_is_not_a_material(self):
        self._wash("")
        self._wash(None)
        answers = self._module_answers("materials_application", post_harvest_contact_none_used=True)
        self.assertEqual(none_used_contradictions(self.osp, answers), [])

    def test_the_workbook_lists_the_wash_sanitizer_as_a_row(self):
        self._wash("SaniDate 5.0")
        rows = {r.name: r for r in _material_rows(self.establishment, osp=self.osp)}
        self.assertIn("SaniDate 5.0", rows)
        self.assertEqual(rows["SaniDate 5.0"].kind, "sanitizer")

    def test_the_d_prefill_fires_from_the_wash_records(self):
        """Dead until 2026-09-12: filtered ChemicalEvent for type PH, which only ProductionEvent carries."""
        from certifications.services.osp_prefill import resolve_suggestions

        self._wash("SaniDate 5.0", sanitizer_ppm=80)
        # The suggestion says the sanitizer is on the list, so it fires only when it is (2026-11-04).
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="SaniDate 5.0",
            category="post_harvest",
            listing_basis=PlanMaterialEntry.BASIS_NONE,
        )
        suggestions = resolve_suggestions(MATERIALS_APPLICATION, self.establishment, osp=self.osp)
        hit = suggestions.get("post_harvest_contact_listed")
        self.assertIsNotNone(hit, suggestions)
        self.assertIs(hit["value"], True)
        self.assertIn("SaniDate 5.0", hit["basis"])

    def test_the_water_booleans_prefill_from_a_named_sanitizer_and_chlorine_only_when_it_reads_as_chlorine(self):
        from certifications.services.osp_prefill import resolve_suggestions

        self._wash("SaniDate 5.0")
        hits = resolve_suggestions(G6_4_HANDLING, self.establishment)
        self.assertIs(hits["uses_water"]["value"], True)
        self.assertIs(hits["wash_water_additives_added"]["value"], True)
        self.assertNotIn("wash_water_chlorine_added", hits)
        self._wash("Sodium hypochlorite 100 ppm")
        hits = resolve_suggestions(G6_4_HANDLING, self.establishment)
        self.assertIs(hits["wash_water_chlorine_added"]["value"], True)
        self.assertIn("hypochlorite", hits["wash_water_chlorine_added"]["basis"])


class PrintTests(_Farm):
    def _dump(self, name, data):
        if DUMP_DIR:
            os.makedirs(DUMP_DIR, exist_ok=True)
            with open(os.path.join(DUMP_DIR, name), "wb") as fh:
                fh.write(data)

    def test_the_module_page_prints_the_types_the_rinsed_set_and_the_chlorine_practice(self):
        self._module_answers(
            "g6_4_handling",
            handling_activities=["washing", "sorting_grading", "packing"],
            process_flow="harvest → dump tank → brush bed → sort → pack → cold room",
            food_contact_cleaning_methods=["manual_washing", "sanitizing", "sweeping"],
            uses_equipment_sanitizer_or_cleaner=True,
            equipment_sanitizer_types=["peracetic_acid", "quaternary_ammonium"],
            equipment_sanitizer_types_rinsed=["quaternary_ammonium"],
            equipment_sanitizer_where_used="SaniDate 5.0 — dump tank and brush bed; Quat 128 — sorting table, rinsed",
            sanitizer_residual_free_assurance=["thorough_rinse", "residue_testing"],
            sanitizer_residual_testing_protocol="Quat strips 0–500 ppm before each organic run, target 0; kept in the wash log",
            uses_water=True,
            post_harvest_water_uses=["crop_washing", "product_transport"],
            post_harvest_water_source=["on_site_well"],
            water_source_sanitizer="On-site well; SaniDate 5.0 at 80 ppm peracetic acid",
            wash_water_additives_added=True,
            wash_water_chlorine_added=True,
            wash_water_chlorine_final_rinse="chlorine_at_or_below_sdwa",
            commingling_controls=["organic_only_facility"],
        )
        data = generate_module_pdf(self.osp, "g6_4_handling")
        self._dump("g6_4-sanitation.pdf", data)
        text = _pdf_text(data)
        self.assertIn("Which types of sanitizer or cleaner are used?", text)
        self.assertIn("Peracetic / peroxyacetic acid", text)
        self.assertIn("Quaternary ammonium sanitizer", text)
        self.assertIn("rinsed with potable water", text)
        self.assertIn("Quat 128", text)
        self.assertIn("at or below the SDWA limit", text)
        self.assertIn("On-site well", text)
        self.assertIn("Quat strips", text)

    def test_the_materials_page_prints_post_harvest_rows_under_their_own_heading(self):
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="SaniDate 5.0",
            manufacturer="BioSafe Systems",
            reason_for_use="Dump-tank sanitizer",
            category="post_harvest",
            listing_basis=PlanMaterialEntry.BASIS_NONE,
        )
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Feather Meal 13-0-0",
            category="fertilizer_amendment",
            listing_basis=PlanMaterialEntry.BASIS_NONE,
        )
        data = generate_module_pdf(self.osp, "materials_application")
        self._dump("materials-post-harvest.pdf", data)
        text = _pdf_text(data)
        self.assertIn("Post-harvest contact materials", text)
        self.assertIn("§ 205.605", text)
        # the §D block carries the sanitizer, not the fertilizer
        block = text.split("Post-harvest contact materials", 1)[1]
        self.assertIn("SaniDate 5.0", block)
        self.assertIn("BioSafe Systems", block)
        self.assertNotIn("Feather Meal", block.split("[REVIEW]")[0])

    def test_no_post_harvest_rows_means_no_block(self):
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Feather Meal 13-0-0",
            category="fertilizer_amendment",
            listing_basis=PlanMaterialEntry.BASIS_NONE,
        )
        text = _pdf_text(generate_module_pdf(self.osp, "materials_application"))
        self.assertNotIn("Post-harvest contact materials", text)
