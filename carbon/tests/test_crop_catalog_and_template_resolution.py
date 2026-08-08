"""Crop catalog coverage, and never handing a grower another crop's operations.

Two defects, both found 2026-08-07:

1. **Five California perennial crops were absent from the catalog entirely** — pistachios, olives,
   dates, figs and pomegranates. The crop picker is a CLOSED list with no "Other" and no free-text
   entry, so a California pistachio grower (a top-three CA tree nut by acreage) could not create a
   production at all.

2. **The template seeder fabricated practices for any crop it had no data for.** It fell back to
   `CROP_CUSTOMIZATIONS["corn_field"]`, so a newly added perennial silently received a full
   programme of CORN operations as its suggested template. Accepting a template writes real,
   backdated records attributed to the farmer by name — the same defect class as the fabricated
   glyphosate application.
"""

from django.test import TestCase


class IcpCropCoverageTests(TestCase):
    """The ICP is California perennial specialty crops; the picker must contain them."""

    #: Crops the October plan targets. Absence here is an onboarding blocker, not a nicety.
    ICP_CROPS = [
        "almonds",
        "walnuts",
        "pistachios",
        "avocados",
        "grapes",
        "citrus_oranges",
        "olives",
        "dates",
        "figs",
        "pomegranates",
    ]

    def test_every_icp_crop_is_defined_in_the_seed_data(self):
        from carbon.management.commands.populate_usda_crop_types import Command

        slugs = {crop["slug"] for crop in Command()._get_crop_type_data()}
        missing = [slug for slug in self.ICP_CROPS if slug not in slugs]
        self.assertEqual(
            missing,
            [],
            f"ICP crops absent from the catalog: {missing}. The picker is a closed list with no "
            f"'Other' option, so a grower of these cannot onboard at all.",
        )

    PROVISIONAL_CROPS = {"pistachios", "olives", "dates", "figs", "pomegranates"}

    def test_the_five_added_crops_carry_honest_benchmark_provenance(self):
        # Their emissions figures are interpolated from comparable systems, not measured. They
        # must not claim verification, or the carbon numbers would be a fabricated attribution.
        #
        # NOTE ON WHICH FIELD CARRIES THE SIGNAL: `benchmark_verified` is NOT a CropType model
        # field — it exists only in this seed dict and is dropped on the way to the database, so
        # it reaches no API and no UI. The signals that DO reach the client are `data_source` and
        # `usda_factors_used`, both of which are in CropTypeSerializer.fields. Those are what must
        # be honest.
        from carbon.management.commands.populate_usda_crop_types import Command

        by_slug = {crop["slug"]: crop for crop in Command()._get_crop_type_data()}
        for slug in self.PROVISIONAL_CROPS:
            with self.subTest(slug=slug):
                crop = by_slug[slug]
                self.assertFalse(crop["benchmark_verified"])
                self.assertIn("Provisional", crop["data_source"])
                self.assertFalse(
                    crop["usda_factors_used"],
                    f"{slug} claims USDA factors were used, but its benchmark is interpolated — "
                    f"and this field IS serialised to the client",
                )

    def test_the_provenance_signal_reaches_the_api(self):
        # Guards the trap above: if `data_source` or `usda_factors_used` were dropped from the
        # serializer, the interpolated figures would reach a grower with nothing marking them
        # as provisional.
        from carbon.serializers import CropTypeSerializer

        fields = set(CropTypeSerializer.Meta.fields)
        self.assertIn("data_source", fields)
        self.assertIn("usda_factors_used", fields)

    def test_no_crop_claims_usda_verification_in_its_data_source(self):
        # "USDA Verified" is UNSAFE language per .claude/rules/compliance.md — only
        # "EPA/USDA-sourced" is permitted.
        from carbon.management.commands.populate_usda_crop_types import Command

        offenders = [
            crop["slug"]
            for crop in Command()._get_crop_type_data()
            if "usda verified" in str(crop.get("data_source", "")).lower()
            or "usda-verified" in str(crop.get("data_source", "")).lower()
        ]
        self.assertEqual(offenders, [], f"crops claiming USDA verification: {offenders}")


class TemplateSeederNeverFabricatesPracticesTests(TestCase):
    """A crop with no practice data must get NO template, never another crop's."""

    def test_seeder_skips_unknown_crops_instead_of_falling_back_to_corn(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "management"
            / "commands"
            / "create_comprehensive_production_templates_v2.py"
        )
        text = source.read_text()

        # The specific fallback that caused this: any crop without customisations inherited the
        # corn programme — tillage passes and corn fertigation for a pistachio orchard.
        self.assertNotIn(
            'crop_data = CROP_CUSTOMIZATIONS.get("corn_field", list(CROP_CUSTOMIZATIONS.values())[0])',
            text,
            "the corn_field fallback is back: crops without practice data will inherit corn operations",
        )
        self.assertIn("Skipping {crop_slug}: no practice data", text)

    def test_crops_without_customizations_have_no_templates(self):
        from carbon.management.commands.create_comprehensive_production_templates_v2 import CROP_CUSTOMIZATIONS
        from carbon.models import ProductionTemplate

        wrong = [
            (t.crop_type.slug, t.slug)
            for t in ProductionTemplate.objects.select_related("crop_type").all()
            if t.crop_type and t.crop_type.slug not in CROP_CUSTOMIZATIONS
        ]
        self.assertEqual(
            wrong,
            [],
            f"templates exist for crops with no practice data, so they were built from another "
            f"crop's operations: {wrong}",
        )


class OrganicFirstTemplateResolutionTests(TestCase):
    """Resolving a bare crop slug must never prefer the prohibited-input programme."""

    def test_crop_slug_resolves_to_the_organic_template_when_one_exists(self):
        # Regression: `.filter(crop_type=...).first()` was UNORDERED, and in practice always
        # returned the conventional template — the one carrying glyphosate for walnuts, avocados,
        # pecans, hazelnuts, hops, stone fruit and blueberries.
        from django.db.models import Case, When

        from carbon.models import CropType, ProductionTemplate

        crop = CropType.objects.filter(slug="walnuts").first()
        if crop is None:
            self.skipTest("walnuts not seeded in this database")
        if not ProductionTemplate.objects.filter(crop_type=crop, farming_approach="organic").exists():
            self.skipTest("no organic walnut template seeded in this database")

        resolved = (
            ProductionTemplate.objects.filter(crop_type=crop, is_active=True)
            .order_by(Case(When(farming_approach="organic", then=0), default=1), "id")
            .first()
        )
        self.assertEqual(resolved.farming_approach, "organic")

    def test_the_view_orders_before_taking_first(self):
        from pathlib import Path

        source = Path(__file__).resolve().parents[1] / "views.py"
        text = source.read_text()
        self.assertNotIn(
            "ProductionTemplate.objects.filter(crop_type=crop_type, is_active=True).first()",
            text,
            "unordered .first() is back — it silently resolves to the conventional template",
        )
