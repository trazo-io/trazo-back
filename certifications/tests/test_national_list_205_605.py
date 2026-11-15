"""§ 205.605(b) post-harvest sanitizers: in the catalogue, findable, and named when missing.

🔴 2026-09-10 — an OTCO desk read found the flume sanitizer printed as "Peracetic acid —
§ 205.601". § 205.601(a) lists sanitizers for crop production; post-harvest wash and rinse water
is § 205.605(b). The catalogue held no § 205.605 row, so the operator had no correct row to
attach, and the packet had no way to say the plan cited the production section for a handling use.
"""

from django.test import TestCase
from django.utils import timezone

from certifications.management.commands.seed_national_list import SECTION_605_ALLOWED
from certifications.models import NationalListSubstance, OrganicSystemPlan, PlanMaterialEntry
from certifications.services.omri_verifier import national_list_candidates_by_name
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.plan_materials import post_harvest_listing_review
from company.models import Company, Establishment
from history.models import Production, ProductionEvent
from product.models import Parcel

from .test_materials_stated_absences import _pdf_text


class CatalogueTests(TestCase):
    def test_the_seeder_and_the_migration_agree(self):
        """Migration 0038 puts the rows in production; the seeder keeps them through `--reset`."""
        for _subsection, _category, name, notes in SECTION_605_ALLOWED:
            row = NationalListSubstance.objects.get(substance_name=name, cfr_section="205.605")
            self.assertEqual(row.status, "allowed", name)
            self.assertEqual(row.restriction_notes, notes, name)

    def test_peracetic_acid_carries_the_wash_water_annotation(self):
        row = NationalListSubstance.objects.get(cfr_section="205.605", substance_name__startswith="Peracetic")
        self.assertIn("wash and/or rinse water according to FDA limitations", row.restriction_notes)

    def test_search_offers_both_sections_for_a_name_on_both(self):
        NationalListSubstance.objects.create(
            substance_name="Hydrogen peroxide",
            substance_name_normalized="hydrogen peroxide",
            cfr_section="205.601",
            subsection="a",
            category="sanitizer",
            status="allowed",
        )
        sections = [row.cfr_section for row in national_list_candidates_by_name("Hydrogen peroxide")]
        self.assertEqual(sections, ["205.601", "205.605"])


class ListingReviewTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Flume Co")
        self.est = Establishment.objects.create(name="Flume Farm", company=company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        parcel = Parcel.objects.create(name="Bottom Ground", establishment=self.est, area=2.0)
        season = Production.objects.create(parcel=parcel, name="Carrots 2026", published=False)
        ProductionEvent.objects.create(
            history=season,
            type="PH",
            description="wash line",
            date=timezone.now(),
            sanitizer_name="SaniDate 5.0 (peracetic acid)",
        )
        self.crop_row = NationalListSubstance.objects.create(
            substance_name="Peracetic acid",
            substance_name_normalized="peracetic acid",
            cfr_section="205.601",
            subsection="a",
            category="sanitizer",
            status="allowed",
        )

    def _page(self):
        return " ".join(_pdf_text(generate_module_pdf(self.osp, "materials_application")).split())

    def test_a_crop_section_sanitizer_is_named_against_the_logged_wash_water(self):
        self.osp.approved_national_list_substances.add(self.crop_row)
        page = self._page()
        self.assertIn(
            "[REVIEW] The post-harvest records log a wash-water sanitizer (SaniDate 5.0 (peracetic acid))", page
        )
        self.assertIn("this plan lists Peracetic acid only under § 205.601", page)

    def test_the_handling_row_silences_it(self):
        handling = NationalListSubstance.objects.get(cfr_section="205.605", substance_name__startswith="Peracetic")
        self.osp.approved_national_list_substances.add(self.crop_row, handling)
        self.assertEqual(post_harvest_listing_review(self.osp), [])
        self.assertNotIn("post-harvest records log a wash-water sanitizer", self._page())

    def test_an_operator_post_harvest_row_silences_it(self):
        PlanMaterialEntry.objects.create(osp=self.osp, product_name="SaniDate 5.0", category="post_harvest")
        self.assertEqual(post_harvest_listing_review(self.osp), [])

    def test_no_logged_sanitizer_no_line(self):
        ProductionEvent.objects.filter(type="PH").update(sanitizer_name=None)
        self.osp.approved_national_list_substances.add(self.crop_row)
        self.assertEqual(post_harvest_listing_review(self.osp), [])


class CropInputsNeverClassifyAsHandlingTests(TestCase):
    """🔴 Review, 2026-09-10. The three crop-input classifiers matched names against every row, so
    once 0038 seeded the handling list a spray named "Ozone" became a § 205.605 input, and
    "hypochlorous acid" — contained in one row per section — fell through as ambiguous."""

    def setUp(self):
        for name in ("Ozone gas", "Hypochlorous acid (from electrolyzed water)"):
            NationalListSubstance.objects.create(
                substance_name=name,
                substance_name_normalized=name.lower(),
                cfr_section="205.601",
                subsection="a",
                category="sanitizer",
                status="allowed",
            )

    def _classify(self, name):
        from history.models import ChemicalEvent
        from history.signals import auto_classify_chemical_against_national_list

        event = ChemicalEvent(commercial_name=name)
        auto_classify_chemical_against_national_list(sender=ChemicalEvent, instance=event)
        # Which SECTION a match lands in is the question here; since Phase 5 slice 1 a partial match
        # is a suggestion rather than a classification, so either field is the answer.
        return event.national_list_substance or event.national_list_suggestion

    def test_the_save_signal_never_picks_a_handling_row(self):
        for name in ("Ozone", "Peroxyacetic acid", "Acidified sodium chlorite"):
            row = self._classify(name)
            self.assertTrue(row is None or row.cfr_section == "205.601", f"{name} -> {row and row.cfr_section}")

    def test_a_name_contained_in_both_sections_still_resolves_to_the_crop_row(self):
        row = self._classify("Hypochlorous acid")
        self.assertIsNotNone(row)
        self.assertEqual(row.cfr_section, "205.601")

    def test_the_drift_resolver_never_returns_a_handling_row(self):
        from certifications.services.drift_detector import _resolve_national_list_by_name

        for name in ("Ozone", "Peracetic acid/Peroxyacetic acid", "Acidified sodium chlorite"):
            row = _resolve_national_list_by_name(name)
            self.assertTrue(row is None or row.cfr_section == "205.601", f"{name} -> {row and row.cfr_section}")

    def test_the_verifier_does_not_call_a_handling_row_a_crop_listing(self):
        from certifications.services.omri_verifier import OMRIProductVerifier

        result = OMRIProductVerifier().verify(operation_name="Acidified sodium chlorite")
        self.assertFalse(result.found)
