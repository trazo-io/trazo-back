"""
What a browser and print check of the materials work found (2026-11-05), on the specimen farm.

  * The app showed the citation's uses in English on a Spanish screen ("insecticide, crop disease
    control"): the editor now carries the paragraphs alone; the packet keeps the uses.
  * Both materials sheets printed a soil event's amendment code ("sulfur", "bone_meal").
  * With the specimen line above them, the instruction and provenance rows were not wrapped, so the
    form's instruction ran off the sheet while the specimen line wrapped instead.
"""

import io

from django.test import TestCase
from django.utils import timezone

import openpyxl

from certifications.models import NationalListSubstance, OrganicSystemPlan
from certifications.services import national_list_citations as nlc
from certifications.services.common_osp_workbooks import _amendment_words, build_workbook
from certifications.services.plan_materials import materials_list_rows
from company.models import Company, Establishment
from history.models import Production, SoilManagementEvent
from product.models import Parcel


class TheAppShowsTheParagraphsAloneTests(TestCase):
    def test_the_paragraphs_without_the_uses(self):
        sulfur = NationalListSubstance(substance_name="Elemental sulfur", cfr_section="205.601")
        self.assertEqual(nlc.citation_paragraphs(sulfur), "§ 205.601(e)(5), (h)(2), (i)(10), (j)(2)")
        self.assertEqual(nlc.citation_paragraphs(NationalListSubstance(substance_name="X", cfr_section="205.601")), "")

    def test_the_editor_row_carries_the_paragraphs_and_the_packet_line_the_uses(self):
        from certifications.services.plan_materials import plan_materials

        company = Company.objects.create(name="Polish Co")
        est = Establishment.objects.create(name="Polish Farm", company=company)
        osp = OrganicSystemPlan.objects.create(establishment=est, version_number=1, status="draft")
        lime = NationalListSubstance.objects.create(
            substance_name="Lime sulfur", substance_name_normalized="lime sulfur", cfr_section="205.601"
        )
        osp.approved_national_list_substances.add(lime)
        row = next(r for r in materials_list_rows(osp) if r["name"] == "Lime sulfur")
        self.assertEqual(row["listing"], "§ 205.601(e)(6), (i)(6)")
        line = next(m for m in plan_materials(osp) if m.name == "Lime sulfur").display(stated_absences=True)
        self.assertIn("§ 205.601(e)(6) insecticide, (i)(6) crop disease control", line)


class AmendmentWordsTests(TestCase):
    def test_a_code_reads_as_words(self):
        self.assertEqual(
            [_amendment_words(c) for c in ("sulfur", "bone_meal", "fish_emulsion", "", None)],
            ["Sulfur", "Bone meal", "Fish emulsion", None, None],
        )

    def test_the_materials_sheet_prints_the_words(self):
        company = Company.objects.create(name="Amend Co")
        est = Establishment.objects.create(name="Amend Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=est, area=2.0)
        history = Production.objects.create(name="Pears", start_date=timezone.now(), parcel=parcel)
        SoilManagementEvent.objects.create(
            history=history,
            date=timezone.now(),
            type="OM",
            amendment_type="bone_meal",
            amendment_product_name="Bone Meal 6-9-0",
        )
        cells = [
            r
            for r in openpyxl.load_workbook(
                io.BytesIO(build_workbook(est, "materials_list").getvalue())
            ).active.iter_rows(values_only=True)
        ]
        row = next(r for r in cells if r[0] == "Bone Meal 6-9-0")
        self.assertEqual(row[2], "Bone meal")


class SpecimenSheetWrapTests(TestCase):
    def test_the_instruction_and_provenance_rows_wrap_under_the_specimen_line(self):
        company = Company.objects.create(name="Specimen Co")
        est = Establishment.objects.create(name="Specimen Farm", company=company, is_demo=True)
        ws = openpyxl.load_workbook(io.BytesIO(build_workbook(est, "materials_list").getvalue())).active
        instructions = next(c for c in ws["A"] if str(c.value or "").startswith("List ALL inputs"))
        provenance = ws.cell(row=instructions.row + 1, column=1)
        self.assertTrue(instructions.alignment.wrap_text)
        self.assertTrue(provenance.alignment.wrap_text)
