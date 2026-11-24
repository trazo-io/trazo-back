"""A National List annotation is part of the regulation — the packet must print it.

§ 205.601 and § 205.602 entries carry use restrictions. Calcium chloride (brine process) sits
on § 205.602 (prohibited nonsynthetics) with the annotation *"Allowed only as foliar spray for
calcium uptake disorders"* — and that annotation is already stored on the substance row.

The packet ignored it and printed a flat **PROHIBITED**, with a warning that "use of these
inputs disqualifies the crop from organic sale". A Honeycrisp block's calcium programme for
bitter pit IS the exception the annotation names — bitter pit is the physiological
calcium-uptake disorder — so the packet was reporting a compliant, textbook practice as a
disqualifying violation, to the certifier.

Found 2026-08-20 on a real WA apple operation.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from certifications.models import NationalListSubstance
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product


def _text(elements):
    out = []
    for el in elements:
        out.append(getattr(el, "text", "") or "")
        for row in getattr(el, "_cellvalues", None) or []:
            for cell in row:
                out.append(getattr(cell, "text", "") or "")
    return " ".join(out)


class _AnnotationFixture(TestCase):
    def setUp(self):
        company = Company.objects.create(name="NL Co")
        est = Establishment.objects.create(name="NL Farm", company=company)
        parcel = Parcel.objects.create(name="P", establishment=est, area=11.5)
        crop = CropType.objects.create(
            name="Apple",
            slug="apple-nl",
            category="tree_fruit",
            description="d",
            typical_farm_size="1",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        product = Product.objects.create(name="Apple")
        self.history = Production.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
        )

    def _substance(self, name, status, notes, section="205.602", kind=None):
        if kind is None:
            kind = NationalListSubstance.ANNOTATION_CONDITION if notes else NationalListSubstance.ANNOTATION_NONE
        return NationalListSubstance.objects.create(
            substance_name=name,
            substance_name_normalized=name.lower(),
            cfr_section=section,
            subsection="c",
            category="amendment",
            status=status,
            restriction_notes=notes or "",
            annotation_kind=kind,
        )

    def _event(self, substance, name="Calcium chloride 33%"):
        return ChemicalEvent.objects.create(
            history=self.history,
            type="FE",
            date=timezone.now() - timedelta(days=60),
            description=f"{name} application",
            commercial_name=name,
            national_list_substance=substance,
            national_list_basis="operator",
            organic_approved="omri_listed",
        )

    def _packet_text(self):
        svc = AuditExportService(self.history, certification_type="organic")
        return _text(svc._build_chemical_log())


class NationalListAnnotationTests(_AnnotationFixture):
    def test_an_annotated_entry_is_restricted_not_prohibited(self):
        self._event(
            self._substance(
                "Calcium chloride (brine process)",
                "prohibited",
                "Allowed only as foliar spray for calcium uptake disorders.",
            )
        )
        text = self._packet_text()
        self.assertIn("Restricted use", text)
        self.assertNotIn("PROHIBITED", text)

    def test_the_annotation_itself_is_printed(self):
        """Without the annotation the certifier cannot check the use against the rule."""
        self._event(
            self._substance(
                "Calcium chloride (brine process)",
                "prohibited",
                "Allowed only as foliar spray for calcium uptake disorders.",
            )
        )
        self.assertIn("foliar spray for calcium uptake disorders", self._packet_text())

    def test_a_genuinely_prohibited_entry_still_says_so(self):
        """The guard must not soften a substance with no annotation — that IS disqualifying."""
        self._event(self._substance("Strychnine", "prohibited", ""), name="Strychnine bait")
        text = self._packet_text()
        self.assertIn("PROHIBITED", text)
        self.assertIn("disqualifies the crop", text)

    def test_an_allowed_entry_is_unaffected(self):
        self._event(self._substance("Spinosad", "allowed", "", section="205.601"), name="Entrust SC")
        text = self._packet_text()
        self.assertIn("Allowed", text)
        self.assertNotIn("PROHIBITED", text)

    def test_a_rationale_annotation_never_softens_a_prohibition(self):
        """The fix that almost shipped: `if restriction_notes:` would have let glyphosate through.

        § 205.105 rows carry annotations too, but theirs explain WHY the substance is banned —
        they grant nothing. Testing for the presence of prose rather than the typed
        `annotation_kind` moves glyphosate out of the packet's [WARNING] block and reports a
        synthetic herbicide on an organic block as merely "Restricted use".
        """
        self._event(
            self._substance(
                "Glyphosate",
                "prohibited",
                "Synthetic herbicide; not on § 205.601 (NOP 5034-2).",
                section="205.105",
                kind=NationalListSubstance.ANNOTATION_RATIONALE,
            ),
            name="Roundup PowerMAX",
        )
        text = self._packet_text()
        self.assertIn("PROHIBITED", text)
        self.assertIn("disqualifies the crop", text)
        self.assertNotIn("Restricted use", text)


class Section601RuleWordsTests(_AnnotationFixture):
    """OV-MT-C13: a § 205.601 row's stored note is a paraphrase, and the dossier printed it beside
    the citation as if it were the rule. It now prints the rule's own words, or nothing."""

    def test_a_601_row_prints_the_rules_words_not_the_paraphrase(self):
        from certifications.services.national_list_citations import RULE_WORDS_601

        self._event(
            self._substance(
                "Peracetic acid",
                "allowed",
                "Equipment, seed, and asexual plant material disinfection only.",
                section="205.601",
                kind=NationalListSubstance.ANNOTATION_CONDITION,
            ),
            name="Jet-Ag",
        )
        text = " ".join(self._packet_text().split())
        self.assertNotIn("Equipment, seed, and asexual plant material disinfection only.", text)
        # The half the paraphrase dropped.
        self.assertIn("Also permitted in hydrogen peroxide formulations", text)
        self.assertIn(" ".join(RULE_WORDS_601["(a)(6)"].split())[:80], text)

    def test_a_chlorine_material_prints_the_residual_limit_it_is_held_to(self):
        self._event(
            self._substance(
                "Sodium hypochlorite",
                "allowed",
                "Same SDWA chlorine limit applies.",
                section="205.601",
                kind=NationalListSubstance.ANNOTATION_CONDITION,
            ),
            name="Clorox Germicidal Bleach",
        )
        text = " ".join(self._packet_text().split())
        self.assertNotIn("Same SDWA chlorine limit applies.", text)
        self.assertIn("maximum residual disinfectant limit under the Safe Drinking Water Act", text)

    def test_a_601_row_with_no_words_of_its_own_prints_no_note(self):
        """§ 205.601(f) lists pheromones by name only; a stored note there is Trazo's, not the rule's."""
        self._event(
            self._substance(
                "Pheromones",
                "allowed",
                "Mating disruption dispensers only.",
                section="205.601",
                kind=NationalListSubstance.ANNOTATION_CONDITION,
            ),
            name="Isomate CM Flex",
        )
        text = self._packet_text()
        self.assertIn("Pheromones", text)
        self.assertNotIn("Mating disruption dispensers only.", text)
