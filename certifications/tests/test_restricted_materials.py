"""
The National List materials a grower may apply only under a condition, asked and printed (WSDA AGR
2121 D4-D6a and H5/H5a, OTCO C4 4.5-1).

An orchard uses these every season: calcium chloride for bitter pit, fixed copper for fire blight,
zinc and boron, magnesium sulfate, muriate of potash. Until CONTENT_VERSION 2026.11.13 nothing in
the plan asked about them, so the inspector's first questions at an orchard had no answer in the
packet.

Pinned here:
  * the module PDF prints the rule's own words beside a Yes, and the plan's materials of the class
    with how the operator says each one's restriction is met;
  * the rule is applied when the page prints, never by refusing an answer: magnesium sulfate with no
    soil analysis, calcium chloride not sprayed on the foliage, a method other than testing the
    agent has not approved, and potassium chloride whose only plan row names no mined product, each
    print a [REVIEW] line;
  * a No the records contradict prints the records; copper fed as a micronutrient is not disease
    control;
  * class membership: a WSDA listing's own subtype counts, an OMRI-only product is never classified;
  * prefill suggests Yes from a record and never No; a substring suggestion and langbeinite count
    for nothing; "Muriate of Potash" classifies as § 205.602(e).
"""

import io
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, PlanMaterialEntry, WSDAMaterial
from certifications.osp_modules import MODULES_BY_KEY
from certifications.services.common_osp_records import EvidenceBundle
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.restricted_materials import (
    calcium_chloride_evidence,
    copper_evidence,
    deficiency_materials_evidence,
    module_lines,
    potassium_chloride_evidence,
)
from company.models import Company, Establishment
from history.models import ChemicalEvent, History, SoilManagementEvent
from product.models import Parcel

G4 = MODULES_BY_KEY["g4_0_rotation_soil"]
G5 = MODULES_BY_KEY["g5_0_pest"]


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


def _question(module, key):
    return next(q for page in module.pages for q in page.questions if q.key == key)


class _Orchard(TestCase):
    def setUp(self):
        call_command("seed_national_list", stdout=StringIO(), stderr=StringIO())
        self.company = Company.objects.create(name="Wenatchee Heights Orchards LLC")
        self.est = Establishment.objects.create(name="Wenatchee Heights", company=self.company, state="WA")
        parcel = Parcel.objects.create(name="Honeycrisp Block", establishment=self.est, area=12.0)
        self.history = History.objects.create(name="Honeycrisp 2026", start_date=timezone.now(), parcel=parcel)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")

    def _substance(self, name):
        return NationalListSubstance.objects.get(substance_name=name)

    def _store(self, module, **answers):
        responses = self.osp.module_responses or {"schema_version": 1, "modules": {}}
        responses.setdefault("modules", {})[module] = {"answers": {k: {"value": v} for k, v in answers.items()}}
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

    def _chem(self, name, type_code="FE", **fields):
        with self.captureOnCommitCallbacks(execute=True):
            return ChemicalEvent.objects.create(
                history=self.history,
                date=timezone.now(),
                description="application",
                type=type_code,
                commercial_name=name,
                **fields,
            )

    def _soil(self, name):
        return SoilManagementEvent.objects.create(
            history=self.history,
            type="OM",
            amendment_type="mineral",
            amendment_product_name=name,
            date=timezone.now(),
        )

    def _lines(self, module, key, value, answers=None):
        return module_lines(self.osp, module, _question(module, key), value, answers or {key: value}, {})

    def _bundle(self):
        return EvidenceBundle(self.est, osp=self.osp)


class TheRuleIsPrintedBesideTheAnswer(_Orchard):
    def test_a_yes_prints_the_rule_and_the_plans_materials_with_their_statement(self):
        from certifications.services.material_restrictions import record_statement
        from users.models import User

        boron = self._substance("Soluble boron products")
        self.osp.approved_national_list_substances.add(boron)
        user = User.objects.create_user(email="block@test.com", password="x")
        record_statement(
            self.osp,
            user,
            {
                "material_kind": "national_list",
                "material_id": boron.pk,
                "restriction_source": "regulation",
                "how_met": "Leaf tissue test each July before any boron spray.",
            },
        )
        lines = self._lines(
            G4,
            "applies_deficiency_materials",
            True,
            {"applies_deficiency_materials": True, "deficiency_materials": ["micronutrients"]},
        )
        self.assertIn("other documented and verifiable method as approved by the certifying agent", lines[0])
        self.assertTrue(lines[0].startswith("§ 205.601(j)(7): "), lines[0])
        self.assertIn(
            "Soluble boron products (National List), how the restriction is met: Leaf tissue test each July "
            "before any boron spray.",
            lines[1],
        )
        self.assertFalse(any("(j)(6)" in line for line in lines), "magnesium sulfate was not chosen")

    def test_copper_prints_the_disease_control_proviso_and_both_paragraphs(self):
        lines = self._lines(G5, "applies_copper_materials", True)
        self.assertIn("§ 205.206(a) through (d) prove insufficient", lines[0])
        self.assertTrue(lines[1].startswith("§ 205.601(i)(2): "))
        self.assertTrue(lines[2].startswith("§ 205.601(i)(3): "))

    def test_the_whole_page_carries_the_answers_and_the_rule(self):
        self._store(
            "g4_0_rotation_soil",
            applies_deficiency_materials=True,
            deficiency_materials=["micronutrients", "magnesium_sulfate"],
            micronutrient_verification=["visual_observation"],
            micronutrient_method_agent_approval="for_agent_review",
            magnesium_sulfate_verification=["tissue_analysis"],
            applies_calcium_chloride=True,
            calcium_chloride_foliar=True,
            calcium_chloride_disorder="bitter pit",
            applies_potassium_chloride=True,
            chloride_accumulation_practices=["split_applications"],
        )
        page = _pdf_text(generate_module_pdf(self.osp, "g4_0_rotation_soil"))
        for words in (
            "Do you apply synthetic micronutrients or magnesium sulfate",
            "Visual observation",
            "Described here for my agent's approval",
            "bitter pit",
            "Split applications",
            '§ 205.602(c): "Calcium chloride, brine process is natural',
            "[REVIEW] § 205.601(j)(7) accepts a method other than soil or tissue testing only as approved",
            "[REVIEW] § 205.601(j)(6) allows magnesium sulfate with a documented soil deficiency",
        ):
            self.assertIn(words, page)


class TheRuleIsAppliedWhenThePagePrints(_Orchard):
    def test_magnesium_sulfate_needs_a_soil_analysis(self):
        self.assertEqual(len(self._lines(G4, "magnesium_sulfate_verification", ["tissue_analysis"])), 1)
        self.assertEqual(self._lines(G4, "magnesium_sulfate_verification", ["soil_analysis", "crop_advisor"]), [])

    def test_calcium_chloride_off_the_foliage_is_flagged(self):
        self.assertIn("§ 205.602(c) prohibits", self._lines(G4, "calcium_chloride_foliar", False)[0])
        self.assertEqual(self._lines(G4, "calcium_chloride_foliar", True), [])

    def test_potassium_chloride_with_no_product_on_the_plan_names_the_missing_source(self):
        self.osp.approved_national_list_substances.add(self._substance("Potassium chloride"))
        lines = self._lines(G4, "applies_potassium_chloride", True)
        self.assertIn(
            "[REVIEW] § 205.602(e) prohibits potassium chloride unless it is derived from a mined source.",
            " ".join(lines),
        )

        product = WSDAMaterial.objects.create(
            wsda_id="W-K1",
            brand_name="Muriate of Potash 0-0-60",
            category="fertilizer-and-soil-amendment",
            subtype="Potassium Chloride",
        )
        self.osp.approved_wsda_materials.add(product)
        lines = self._lines(G4, "applies_potassium_chloride", True)
        self.assertFalse(any("names no product" in line for line in lines), lines)
        self.assertIn("Muriate of Potash 0-0-60 (WSDA)", " ".join(lines))

    def test_calcium_chloride_is_never_read_as_a_rule_about_its_source(self):
        """Review of back #311: § 205.602(c) limits the USE, which the foliar question asks."""
        self.osp.approved_national_list_substances.add(self._substance("Calcium chloride (brine process)"))
        lines = self._lines(G4, "applies_calcium_chloride", True)
        self.assertTrue(any("Calcium chloride (brine process) (National List)" in line for line in lines), lines)
        self.assertFalse(any("source" in line for line in lines), lines)


class WhichMaterialsAreOfAClass(_Orchard):
    def test_a_wsda_listing_counts_by_its_own_subtype_and_omri_is_never_guessed(self):
        champ = WSDAMaterial.objects.create(
            wsda_id="W-CU1", brand_name="Champ WG", category="disease-and-pest-control", subtype="Copper Hydroxide"
        )
        chb = WSDAMaterial.objects.create(
            wsda_id="W-CU2",
            brand_name="CHB Copper 5%",
            category="fertilizer-and-soil-amendment",
            subtype="Copper Sulfate",
        )
        self.osp.approved_wsda_materials.add(champ, chb)
        self.osp.approved_omri_products.add(OMRIProduct.objects.create(product_name="Cueva", omri_id="cer-1"))
        lines = " ".join(self._lines(G5, "applies_copper_materials", True))
        self.assertIn("Champ WG (WSDA)", lines)
        self.assertNotIn("CHB Copper", lines, "a copper sulfate fertilizer is a micronutrient, not disease control")

        self.osp.approved_wsda_materials.remove(champ)
        lines = " ".join(self._lines(G5, "applies_copper_materials", True))
        self.assertIn("the 1 OMRI-listed product(s) on it are not classified by Trazo", lines)

    def test_an_operator_entry_linked_to_a_listing_counts(self):
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Epsom salt (farm store)",
            national_list_substance=self._substance("Magnesium sulfate"),
        )
        lines = self._lines(
            G4,
            "applies_deficiency_materials",
            True,
            {"applies_deficiency_materials": True, "deficiency_materials": ["magnesium_sulfate"]},
        )
        self.assertIn("Epsom salt (farm store)", " ".join(lines))


class ANoTheRecordsContradict(_Orchard):
    def test_copper_sprays_are_named_under_a_no(self):
        self._chem("Kocide 3000", type_code="FU", chemical_subtype="copper_fungicide")
        self._chem("Badge X2", type_code="FU", chemical_subtype="copper_fungicide")
        lines = self._lines(G5, "applies_copper_materials", False)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("2 application(s) of products classified as copper sulfate or fixed coppers", lines[0])
        self.assertIn("Badge X2, Kocide 3000", lines[0])

    def test_copper_fed_as_a_micronutrient_is_not_disease_control(self):
        self._chem("Copper sulfate fertilizer", type_code="FE", micronutrient_type="copper")
        self.assertEqual(self._lines(G5, "applies_copper_materials", False), [])
        lines = self._lines(G4, "applies_deficiency_materials", False)
        self.assertIn("synthetic micronutrients", lines[0])

    def test_a_soil_record_named_by_a_listed_synonym_counts_against_a_no(self):
        """Review of back #311: it suggested a Yes, so it has to count against a No as well."""
        self._soil("Muriate of Potash")
        lines = self._lines(G4, "applies_potassium_chloride", False)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("1 application(s) of products classified as potassium chloride", lines[0])
        self._soil("Sulfate of Potash-Magnesia")
        self.assertIn("1 application(s)", self._lines(G4, "applies_potassium_chloride", False)[0])

    def test_a_no_with_nothing_logged_prints_nothing(self):
        self.assertEqual(self._lines(G4, "applies_potassium_chloride", False), [])


class RecordsSuggestYesNeverNo(_Orchard):
    def test_a_zinc_application_suggests_yes(self):
        self._chem("Zinc sulfate 36%", micronutrient_type="zinc")
        suggestion = deficiency_materials_evidence(self._bundle(), None)
        self.assertIsNotNone(suggestion)
        self.assertIs(suggestion["value"], True)
        self.assertIn("Zinc sulfate 36%", suggestion["basis"])

    def test_calcium_and_magnesium_as_logged_nutrients_suggest_nothing(self):
        self._chem("Calcium nitrate", micronutrient_type="calcium")
        self._chem("Mag product", micronutrient_type="magnesium")
        self.assertIsNone(deficiency_materials_evidence(self._bundle(), None))

    def test_muriate_of_potash_suggests_potassium_chloride_and_langbeinite_does_not(self):
        self._soil("Sulfate of Potash-Magnesia")
        self.assertIsNone(potassium_chloride_evidence(self._bundle(), None))
        self.assertIsNone(deficiency_materials_evidence(self._bundle(), None))
        self._soil("Muriate of Potash")
        suggestion = potassium_chloride_evidence(self._bundle(), None)
        self.assertIsNotNone(suggestion)
        self.assertIs(suggestion["value"], True)

    def test_a_substring_suggestion_counts_for_nothing(self):
        event = self._chem("Calcium chloride flakes")
        event.refresh_from_db()
        self.assertIsNone(event.national_list_basis or None)
        self.assertIsNone(calcium_chloride_evidence(self._bundle(), None))

    def test_no_records_suggest_nothing_never_no(self):
        for resolver in (deficiency_materials_evidence, calcium_chloride_evidence, copper_evidence):
            self.assertIsNone(resolver(self._bundle(), None))

    def test_muriate_of_potash_on_a_spray_record_classifies_as_section_602_e(self):
        event = self._chem("Muriate of Potash")
        event.refresh_from_db()
        self.assertIsNotNone(event.national_list_substance)
        self.assertEqual(event.national_list_substance.substance_name, "Potassium chloride")
        self.assertEqual(event.national_list_basis, "alias")
