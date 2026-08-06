"""Crop-type normalization must not borrow another crop's emission factors.

Regression pins for the D3 crop-gap audit. `_normalize_crop_type` used an
ordered if/elif chain whose generic rules were tested before the specific ones,
so several real crops resolved to a completely different crop's factors and were
reported with full confidence:

  * "peanut"    -> walnuts      (a bare "nut" rule ran before the peanut rule)
  * "hazelnut"  -> walnuts      (same)
  * "pecan"     -> walnuts      (explicitly, by the old rule)
  * "blueberry" -> strawberries (a bare "berr" rule)
  * "green bean"-> soybeans     (a bare "bean" rule)
  * "pineapple" -> apples       ("apple" is a substring of "pineapple")

A missing factor is recoverable — the confidence score drops and the API says
regional data is unavailable. A wrong factor presented confidently is not.
"""

from django.test import TestCase

from carbon.services.enhanced_usda_factors import EnhancedUSDAFactors


class NormalizeCropTypeTests(TestCase):
    def setUp(self):
        self.norm = EnhancedUSDAFactors()._normalize_crop_type

    def test_nuts_do_not_all_collapse_to_walnuts(self):
        self.assertEqual(self.norm("pecan"), "pecans")
        self.assertEqual(self.norm("Pecans"), "pecans")
        self.assertEqual(self.norm("hazelnut"), "hazelnuts")
        self.assertEqual(self.norm("Filberts"), "hazelnuts")
        self.assertEqual(self.norm("walnut"), "walnuts")
        self.assertEqual(self.norm("almond"), "almonds")

    def test_peanut_singular_is_a_legume_not_a_tree_nut(self):
        # The headline bug: "nut" matched before "peanut".
        self.assertEqual(self.norm("peanut"), "peanuts")
        self.assertEqual(self.norm("peanuts"), "peanuts")
        self.assertNotEqual(self.norm("peanut"), "walnuts")

    def test_berries_do_not_all_collapse_to_strawberries(self):
        self.assertEqual(self.norm("blueberry"), "blueberries")
        self.assertEqual(self.norm("Blueberries"), "blueberries")
        self.assertEqual(self.norm("strawberry"), "strawberries")

    def test_cane_berries_are_not_silently_called_strawberries(self):
        # No blackberry/raspberry crop type exists yet. They must fall through to
        # national factors rather than borrow strawberry's.
        for crop in ("raspberry", "blackberry", "cranberry", "boysenberry"):
            with self.subTest(crop=crop):
                self.assertNotEqual(self.norm(crop), "strawberries")

    def test_edible_beans_are_not_soybeans(self):
        for crop in ("green beans", "fava beans", "black beans", "lima beans"):
            with self.subTest(crop=crop):
                self.assertNotEqual(self.norm(crop), "soybeans")
        self.assertEqual(self.norm("soybean"), "soybeans")

    def test_pineapple_is_not_an_apple(self):
        self.assertNotEqual(self.norm("pineapple"), "apples")
        self.assertEqual(self.norm("apple"), "apples")
        self.assertEqual(self.norm("pear"), "apples")

    def test_new_regional_crops_resolve(self):
        self.assertEqual(self.norm("hops"), "hops")
        self.assertEqual(self.norm("spinach"), "spinach")

    def test_citrus_varieties(self):
        for crop in ("navel orange", "valencia", "lemon", "grapefruit", "mandarin"):
            with self.subTest(crop=crop):
                self.assertEqual(self.norm(crop), "citrus")

    def test_stone_fruit_varieties(self):
        for crop in ("peach", "cherry", "apricot", "nectarine", "plum"):
            with self.subTest(crop=crop):
                self.assertEqual(self.norm(crop), "stone_fruit")

    def test_unknown_crop_returns_itself_rather_than_guessing(self):
        self.assertEqual(self.norm("dragonfruit"), "dragonfruit")
        self.assertEqual(self.norm(""), "unknown")

    def test_all_configured_slugs_round_trip(self):
        # Every slug the seeder creates must normalize to a stable key, otherwise
        # the factor lookup silently drifts from the catalogue.
        for slug in (
            "corn",
            "wheat",
            "rice",
            "soybeans",
            "cotton",
            "citrus",
            "apples",
            "grapes",
            "avocados",
            "walnuts",
            "almonds",
            "tomatoes",
            "potatoes",
            "lettuce",
            "carrots",
            "onions",
            "strawberries",
            "peanuts",
            "hay_alfalfa",
            "stone_fruit",
            "mixed_vegetables",
            "pecans",
            "hazelnuts",
            "blueberries",
            "hops",
            "spinach",
        ):
            with self.subTest(slug=slug):
                self.assertEqual(self.norm(slug), slug)


class CropCatalogueCoverageTests(TestCase):
    """Every seeded crop must have its own template customization.

    `create_comprehensive_production_templates_v2.handle()` falls back to
    `corn_field`'s Midwest data for any crop missing from CROP_CUSTOMIZATIONS,
    so a gap here does not fail loudly — it silently gives (say) an Oregon
    hazelnut grower a corn calendar and corn commercial products.
    """

    def _seeded_slugs(self):
        from carbon.management.commands.populate_usda_crop_types import Command

        return {crop["slug"] for crop in Command()._get_crop_type_data()}

    def _customizations(self):
        from carbon.management.commands.create_comprehensive_production_templates_v2 import CROP_CUSTOMIZATIONS

        return CROP_CUSTOMIZATIONS

    def test_every_seeded_crop_has_a_customization(self):
        missing = sorted(self._seeded_slugs() - set(self._customizations()))
        self.assertEqual(missing, [], f"These crops would silently inherit corn's Midwest defaults: {missing}")

    def test_new_regional_crops_are_seeded(self):
        slugs = self._seeded_slugs()
        for slug in ("pecans", "hazelnuts", "blueberries", "hops", "spinach"):
            with self.subTest(slug=slug):
                self.assertIn(slug, slugs)

    def test_new_crops_are_not_labelled_california(self):
        # Region drives the compliance-note text; these crops are not CA crops.
        customizations = self._customizations()
        expected = {
            "pecans": "Southeast",
            "hazelnuts": "Oregon",
            "blueberries": "Michigan",
            "hops": "Washington",
            "spinach": "Arizona",
        }
        for slug, needle in expected.items():
            with self.subTest(slug=slug):
                region = customizations[slug]["region"]
                self.assertIn(needle, region)
                self.assertNotIn("California", region)

    def test_seed_certification_status_is_an_accepted_kwarg(self):
        """Four generators passed this and every one raised TypeError.

        It stayed hidden because all shipped templates are skipped on re-run, so
        the generators were not re-entered until a new crop was added.
        """
        from carbon.management.commands.create_comprehensive_production_templates_v2 import (
            build_production_event_fields,
        )

        fields = build_production_event_fields(subtype="PL", seed_certification_status="certified_organic")
        self.assertEqual(fields["seed_certification_status"], "certified_organic")

    def test_seed_certification_status_omitted_when_not_supplied(self):
        from carbon.management.commands.create_comprehensive_production_templates_v2 import (
            build_production_event_fields,
        )

        self.assertNotIn("seed_certification_status", build_production_event_fields(subtype="PL"))
