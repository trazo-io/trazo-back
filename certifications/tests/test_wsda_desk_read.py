"""WSDA desk read, 2026-09-10 — what a WSDA reviewer could not see, and what the packet misstated.

The renewal packet for a Washington orchard (WSDA certificate of record, all 19 modules answered)
was read against WSDA's own forms. Pinned here, one class per defect:

* The materials page printed one sentence when the plan's list was empty, hiding every logged input.
* The Materials List workbook left Comments blank for a product the records resolve to a § 205.602
  entry — calcium chloride, whose one permitted use is a foliar spray for a calcium-uptake disorder.
* The coverage page sent a reviewer looking for AGR 2196 to the module page, not to the workbook
  that lists the products.
* Document 02 printed storage keys and "changed" beside every section the operator left unticked.
* The plan snapshot printed "Certifier Template: —".
* The § 205.602 catalogue carried paraphrased notes and no paragraph letters.
"""

import importlib
import re
from datetime import date

from django.apps import apps
from django.test import TestCase

import openpyxl

from certifications.management.commands.seed_national_list import SECTION_602_PROHIBITED
from certifications.models import NationalListSubstance, OrganicSystemPlan, OSPAnnualUpdate
from certifications.services.common_osp_workbooks import build_workbook
from certifications.services.osp_module_pdf import _annual_update_pdf, generate_module_pdf
from certifications.services.osp_pdf_snapshot import generate_osp_snapshot_pdf
from certifications.services.packet_coverage import coverage_rows, exclusion_rows
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from product.models import Parcel, Product

from .test_renewal_packet_contents import _pdf_text

CALCIUM = "Calcium chloride (brine process)"
CALCIUM_NOTE = (
    "Prohibited for use except as a foliar spray to treat a physiological disorder associated with calcium uptake."
)
MIGRATION = "certifications.migrations.0039_national_list_205_602_text"
# Phase 5 slice 2 (commit 545adf8, 2026-10-02): a logged name that is not on the plan and that the
# operator has not identified carries this after its listing condition. Every product these tests
# log is such a name, so the cell is the condition followed by it (or the note alone when the
# condition is blank). Until 2026-10-18 the four tests below still expected the cell before it.
IDENTITY_NOT_CONFIRMED = "Identity not confirmed: this name is not on the plan and the operator has not identified it."


def _text(data):
    return " ".join(_pdf_text(data).split())


class _Orchard(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Whitfield Organic Partners LLC")
        self.est = Establishment.objects.create(name="Cascade Ridge Orchards", company=company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        parcel = Parcel.objects.create(name="Ridge Block", establishment=self.est, area=11.49)
        self.season = Production.objects.create(
            name="Honeycrisp 2026",
            parcel=parcel,
            product=Product.objects.create(name="Apples"),
            start_date=date(2026, 3, 18),
        )
        self.calcium = NationalListSubstance.objects.create(
            substance_name=CALCIUM,
            substance_name_normalized=CALCIUM.lower(),
            cfr_section="205.602",
            subsection="c",
            category="prohibited",
            status="prohibited",
            restriction_notes=CALCIUM_NOTE,
            annotation_kind=NationalListSubstance.ANNOTATION_CONDITION,
        )

    def _log(self, name, substance=None, type_="FE"):
        event = ChemicalEvent.objects.create(
            history=self.season, type=type_, date=date(2026, 6, 24), commercial_name=name
        )
        # Set after the save: the pre-save classifier is not what these tests are about.
        ChemicalEvent.objects.filter(pk=event.pk).update(
            national_list_substance=substance, national_list_basis="operator"
        )
        return event


class TheMaterialsListStatesTheListingConditionTests(_Orchard):
    def _rows(self):
        sheet = openpyxl.load_workbook(build_workbook(self.est, "materials_list", osp=self.osp)).active
        header, rows = None, {}
        for row in sheet.iter_rows(values_only=True):
            if row and row[0] == "Product":
                header = row
            elif header and row and row[0]:
                rows[row[0]] = dict(zip(header, row))
        return rows

    def test_calcium_chloride_carries_its_602_condition(self):
        self._log("Calcium chloride 33%", self.calcium)
        row = self._rows()["Calcium chloride 33%"]
        self.assertEqual(row["Reason for use"], "Fertilizer")
        self.assertEqual(
            row["Comments"], f"National List § 205.602(c) {CALCIUM}: {CALCIUM_NOTE} {IDENTITY_NOT_CONFIRMED}"
        )

    def test_a_crop_production_note_is_not_quoted(self):
        """§ 205.601 notes in the catalogue are descriptive, not the rule's words; only the identity note remains."""
        lime_sulfur = NationalListSubstance.objects.create(
            substance_name="Lime sulfur",
            substance_name_normalized="lime sulfur",
            cfr_section="205.601",
            subsection="e",
            category="insecticide",
            status="allowed",
            restriction_notes="Including calcium polysulfide.",
        )
        self._log("Rex Lime Sulfur", lime_sulfur, "FU")
        # No condition quoted; only the identity note remains.
        self.assertEqual(self._rows()["Rex Lime Sulfur"]["Comments"], IDENTITY_NOT_CONFIRMED)

    def test_a_205_105_prohibition_is_cited_to_its_own_section(self):
        glyphosate = NationalListSubstance.objects.create(
            substance_name="Glyphosate",
            substance_name_normalized="glyphosate",
            cfr_section="205.105",
            category="herbicide",
            status="prohibited",
            restriction_notes="Synthetic herbicide; not on § 205.601",
        )
        self._log("Roundup PowerMax", glyphosate, "HE")
        self.assertEqual(
            self._rows()["Roundup PowerMax"]["Comments"],
            f"§ 205.105 Glyphosate: prohibited in organic crop production. {IDENTITY_NOT_CONFIRMED}",
        )

    def test_an_unclassified_product_still_carries_the_identity_note(self):
        self._log("CYD-X HP", None, "PE")
        # No listing condition to state; only the identity note remains.
        self.assertEqual(self._rows()["CYD-X HP"]["Comments"], IDENTITY_NOT_CONFIRMED)

    def test_a_national_list_row_on_the_plan_carries_it_too(self):
        self.osp.approved_national_list_substances.add(self.calcium)
        self.assertIn("§ 205.602(c)", self._rows()[CALCIUM]["Comments"])


class TheEmptyMaterialsPageNamesTheLoggedInputsTests(_Orchard):
    def _page(self):
        return _text(generate_module_pdf(self.osp, "materials_application"))

    def test_logged_products_are_named_under_an_empty_list(self):
        self._log("Calcium chloride 33%", self.calcium)
        self._log("Surround WP Crop Protectant", None, "PE")
        page = self._page()
        self.assertIn("No input materials have been added to this plan's materials list.", page)
        self.assertIn("[REVIEW] The list is empty, but 2 product(s) appear in the logged applications:", page)
        self.assertIn("Calcium chloride 33%", page)
        self.assertIn("Surround WP Crop Protectant", page)

    def test_nothing_logged_adds_nothing(self):
        self.assertNotIn("The list is empty", self._page())


class EveryMaterialsFormNamesTheWorkbookFirstTests(TestCase):
    def test_each_agents_materials_form_points_at_the_workbook(self):
        """The workbook (every product, logged or declared) before the module page (the plan's list
        alone). An agent's own materials form, where Trazo drafts one, comes first of all: WSDA's AGR
        2196 sheet (2026-11-04)."""
        own_form_first = {("wsda", "AGR 2196"): "workbooks/Input Material List - WSDA AGR 2196.xlsx; "}
        for certifier in ("ccof", "otco", "wsda"):
            rows = [r for r in coverage_rows(certifier) if "modules/materials_application.pdf" in r.location]
            self.assertTrue(rows, certifier)
            for row in rows:
                lead = own_form_first.get((certifier, row.document_id), "")
                self.assertTrue(
                    row.location.startswith(f"{lead}workbooks/Materials List.xlsx; "),
                    (certifier, row.document_id, row.location),
                )

    def test_the_handler_osp_line_quotes_no_section_count(self):
        """The title said "sections A-P" and the reason "17-lettered-section": two counts for one form,
        neither checked against it, on the page a WSDA reviewer reads."""
        row = next(r for r in exclusion_rows("wsda") if r.document_id == "AGR 2180")
        self.assertNotIn("17", row.reason)
        self.assertNotIn("A-P", row.form)


class TheFilingStatesOnlyWhatWasAttestedTests(_Orchard):
    def _section(self, attestation):
        OSPAnnualUpdate.objects.create(
            prior_osp=self.osp,
            reporting_year=2026,
            changes_summary="Serenade ASO added for fire blight at bloom.",
            sections_unchanged_attestation=attestation,
        )
        page = _text(_annual_update_pdf(self.osp))
        if "Sections attested unchanged" not in page:
            return None
        return page.split("Sections attested unchanged since the prior plan", 1)[1].split("Producer attestation", 1)[0]

    def test_sections_print_by_their_plan_names_in_rule_order(self):
        section = self._section({"recordkeeping_description": True, "practices_procedures": True})
        self.assertLess(
            section.index("§ 205.201(a)(1) — Practices & Procedures"),
            section.index("§ 205.201(a)(4) — Recordkeeping System"),
        )
        self.assertNotIn("practices procedures", section)

    def test_an_unticked_section_is_not_reported_as_changed(self):
        """The form sends all six keys, unticked as False. "changed" beside each was a report the
        operator never made."""
        section = self._section({"practices_procedures": True, "inputs_list": False, "monitoring_plan": False})
        self.assertNotRegex(section, r"\bchanged\b")
        self.assertNotIn("Inputs / Materials List", section)

    def test_nothing_ticked_prints_no_heading(self):
        self.assertIsNone(self._section({"inputs_list": False}))


class TheSnapshotHeadTests(_Orchard):
    def test_a_blank_template_is_omitted(self):
        self.assertNotIn("Certifier Template", _text(generate_osp_snapshot_pdf(self.osp)))

    def test_a_set_template_is_stated(self):
        self.osp.certifier_template_name = "WSDA Crop Producer OSP (AGR 2121)"
        self.osp.save(update_fields=["certifier_template_name"])
        self.assertIn(
            "Certifier Template: WSDA Crop Producer OSP (AGR 2121)", _text(generate_osp_snapshot_pdf(self.osp))
        )


class The602CatalogueTests(TestCase):
    def test_the_seeder_carries_the_ecfr_letters(self):
        self.assertEqual([row[0] for row in SECTION_602_PROHIBITED], list("abcdefghij"))
        by_name = {name: (letter, notes) for letter, _category, name, notes in SECTION_602_PROHIBITED}
        self.assertEqual(by_name[CALCIUM], ("c", CALCIUM_NOTE))

    def test_the_migration_and_the_seeder_agree(self):
        migration = importlib.import_module(MIGRATION)
        self.assertEqual(
            migration.ROWS, [(letter, name, notes) for letter, _category, name, notes in SECTION_602_PROHIBITED]
        )

    def test_the_migration_corrects_existing_rows_and_creates_none(self):
        """⛔ Update only. A created row would make a fresh database report the list as seeded."""
        NationalListSubstance.objects.create(
            substance_name=CALCIUM,
            substance_name_normalized=CALCIUM.lower(),
            cfr_section="205.602",
            category="prohibited",
            status="prohibited",
            restriction_notes="Allowed only as foliar spray for calcium uptake disorders.",
            annotation_kind=NationalListSubstance.ANNOTATION_CONDITION,
        )
        before = NationalListSubstance.objects.count()
        importlib.import_module(MIGRATION).correct(apps, None)
        row = NationalListSubstance.objects.get(cfr_section="205.602", substance_name=CALCIUM)
        self.assertEqual((row.subsection, row.restriction_notes), ("c", CALCIUM_NOTE))
        self.assertTrue(row.is_conditionally_permitted)
        self.assertEqual(NationalListSubstance.objects.count(), before)

    def test_every_annotation_is_quoted_from_the_rule(self):
        """The three annotated paragraphs, as eCFR prints them after the substance name."""
        notes = {name: notes for _l, _c, name, notes in SECTION_602_PROHIBITED if notes}
        self.assertEqual(set(notes), {CALCIUM, "Potassium chloride", "Sodium nitrate"})
        self.assertTrue(all(re.match(r"^(Prohibited for use except|Unless) ", n) for n in notes.values()))
