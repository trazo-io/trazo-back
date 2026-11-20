"""Natural resources and biodiversity: every practice the three agents name, asked once (2026-11-15).

WSDA AGR 2121 section E (R 02/25) names NRCS conservation practices under five purposes (biodiversity E 2, soil
stability E 6, water quality from nutrients E 13, pesticides E 15 and sediment E 17), asks permanent cover and slope
(E 4, 5), rotation records (E 1b), whether fertilizer is applied (E 11), other practices (E 3, 3a) and a notes space
(E 18). CCOF G4.2 (V1 R8) asks water, non-crop and habitat practices (A3 to A5), the conservation plan's practices
(A2a), measures in enclosed structures (A8) and additional measures (A9). OTCO C6 (rev. 2023/09/14) asks the agency
by name (1a), sharing water (2b), non-crop and habitat practices (3, 4) and additional measures (7).

Each practice is one option, asked once; a WSDA purpose row cites every list its practices live on. Every new
question is optional and every new option is appended, so filed plans keep their answers and stay complete.
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import progress, visible_questions
from certifications.services.osp_module_compiler import compile_module_contributions
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment

G42 = MODULES_BY_KEY["g4_2_natural_resources"]
G40 = MODULES_BY_KEY["g4_0_rotation_soil"]
G31 = MODULES_BY_KEY["g3_1_container_greenhouse"]
WSDA = "Washington State Department of Agriculture (WSDA)"
CCOF = "California Certified Organic Farmers (CCOF)"
OTCO = "Oregon Tilth Certified Organic (OTCO)"


def _options(module, key):
    return [o.value for page in module.pages for q in page.questions if q.key == key for o in q.options]


SOIL = set(_options(G42, "soil_water_practices"))
HABITAT = set(_options(G42, "habitat_biodiversity_practices"))
WATERWAY = set(_options(G42, "waterway_practices"))
EROSION = set(_options(G40, "erosion_practices"))

#: Every practice a row names, and the option that answers it. A practice answered elsewhere in the plan (annual crop
#: rotation is G4.0's rotation plan) is named with the question that answers it.
NAMED = {
    ("wsda", "E 2"): {
        "Alley cropping": "alley_cropping",
        "Cover crop - Annual": "cover_cropping",
        "Annual crop rotation": "g4_0_rotation_soil.rotation_plan",
        "Conservation cover - Perennial": "conservation_cover",
        "Hedgerow planting": "hedgerows",
        "Brush management": "brush_management",
        "Early successional habitat": "early_successional_habitat",
        "Field border": "field_border",
        "Rare or declining habitats": "rare_habitat_restoration",
        "Structure for wildlife": "wildlife_structures",
        "Tree-Shrub establishment": "tree_shrub_establishment",
        "Upland wildlife habitat management": "upland_wildlife_habitat",
        "Windbreak-shelterbelt establishment": "windbreaks",
        "Channel bank vegetation": "channel_bank_vegetation",
        "Riparian forest buffer": "riparian_forest_buffer",
        "Riparian herbaceous cover": "riparian_herbaceous_cover",
        "Shallow water development and management": "shallow_water_management",
        "Spring development": "spring_development",
        "Stream habitat improvement and management": "stream_habitat_improvement",
        "Streambank and shoreline protection": "streambank_shoreline_protection",
        "Wetland wildlife habitat management": "wetland_wildlife_habitat",
    },
    ("wsda", "E 6"): {
        "Alley cropping": "alley_cropping",
        "Conservation cover - Perennial": "conservation_cover",
        "Contour buffer strips": "contour_buffer_strips",
        "Contour farming": "contour_terracing",
        "Cover crop - Annual": "cover_cropping",
        "Critical area planting": "critical_area_planting",
        "Cross wind ridges": "cross_wind_ridges",
        "Cross wind trap strips": "cross_wind_trap_strips",
        "Field border": "field_border",
        "Herbaceous wind barriers": "herbaceous_wind_barriers",
        "Irrigation water management": "irrigation_efficiency",
        "Lined waterway or outlet": "lined_waterway",
        "Mulching": "mulching",
        "No till": "no_till",
        "Pond": "pond",
        "Reduced till": "reduced_tillage",
        "Ridge till": "ridge_till",
        "Row arrangement": "row_arrangement",
        "Seasonal till": "seasonal_till",
        "Strip-cropping": "strip_cropping",
        "Vegetative barriers": "vegetative_barriers",
        "Windbreak-shelterbelt establishment": "windbreaks",
    },
    ("wsda", "E 13"): {
        "Alley cropping": "alley_cropping",
        "Conservation cover - Perennial": "conservation_cover",
        "Contour buffer strips": "contour_buffer_strips",
        "Contour farming": "contour_terracing",
        "Field border": "field_border",
        "Filter strip": "filter_strip",
        "Grassed waterway": "grassed_waterways",
        "Heavy use area protection": "heavy_use_area_protection",
        "Irrigation water management": "irrigation_efficiency",
        "Lined waterway or outlet": "lined_waterway",
        "Micro-irrigation": "micro_irrigation",
        "Nutrient management": "nutrient_management",
        "Pond": "pond",
        "Prescribed grazing": "prescribed_grazing",
        "Riparian forest buffer": "riparian_forest_buffer",
        "Riparian herbaceous cover": "riparian_herbaceous_cover",
        "Seasonal till": "seasonal_till",
        "Stream crossing": "stream_crossing",
        "Strip-cropping": "strip_cropping",
        "Tree-Shrub establishment": "tree_shrub_establishment",
    },
    ("wsda", "E 15"): {
        "Agrichemical handling facility": "agrichemical_handling_facility",
        "Alley cropping": "alley_cropping",
        "Contour buffer strips": "contour_buffer_strips",
        "Contour farming": "contour_terracing",
        "Filter strip": "filter_strip",
        "Grassed waterway": "grassed_waterways",
        "Heavy use area protection": "heavy_use_area_protection",
        "Integrated pest management": "integrated_pest_management",
        "Irrigation water management": "irrigation_efficiency",
        "Lined waterway or outlet": "lined_waterway",
        "Micro-irrigation": "micro_irrigation",
        "Pond": "pond",
        "Riparian forest buffer": "riparian_forest_buffer",
        "Riparian herbaceous cover": "riparian_herbaceous_cover",
        "Seasonal till": "seasonal_till",
        "Strip-cropping": "strip_cropping",
        "Tailwater recovery": "tailwater_recovery",
        "Tree-Shrub establishment": "tree_shrub_establishment",
    },
    ("wsda", "E 17"): {
        "Channel bank vegetation": "channel_bank_vegetation",
        "Conservation cover": "conservation_cover",
        "Contour buffer strips": "contour_buffer_strips",
        "Contour farming": "contour_terracing",
        "Filter strip": "filter_strip",
        "Grassed waterway": "grassed_waterways",
        "Heavy use area protection": "heavy_use_area_protection",
        "Irrigation water management": "irrigation_efficiency",
        "Lined waterway or outlet": "lined_waterway",
        "Pond": "pond",
        "Riparian forest buffer": "riparian_forest_buffer",
        "Riparian herbaceous cover": "riparian_herbaceous_cover",
        "Seasonal till": "seasonal_till",
        "Stream crossing": "stream_crossing",
        "Streambank and shoreline protection": "streambank_shoreline_protection",
        "Tailwater recovery": "tailwater_recovery",
        "Tree or shrub establishment": "tree_shrub_establishment",
        "Vegetative barriers": "vegetative_barriers",
        "Water and sediment control basin": "water_sediment_basin",
    },
    ("ccof", "A3"): {
        "Efficient irrigation use": "irrigation_efficiency",
        "Allocate water to non-crop areas for wildlife": "water_for_wildlife",
        "Target and meter fertilizer use": "fertilizer_metering",
        "Manage excess water towards on-site retention and infiltration": "infiltration",
        "Vegetative cover filters": "filter_strip",
        "Use fish screens": "fish_screens",
    },
    ("ccof", "A4"): {
        "Preserve/restore wetlands and riparian areas": "wetland_woodland_protection",
        "Increase and protect native plants/wildlife": "native_plantings",
        "Minimize erosion": "erosion_control_plantings",
        "Preserve/restore wildlife corridors": "wildlife_corridors",
        "Leave areas as undisturbed habitat refuge": "undisturbed_refuge",
        "Wildlife friendly fences": "wildlife_friendly_fences",
        "Establish legal conservation areas": "legal_conservation_areas",
        "Restore degraded areas": "restore_degraded",
        "Native habitats not converted to farmland since certification": "habitat_not_converted",
    },
    ("ccof", "A5"): {
        "Hedgerows": "hedgerows",
        "Windbreaks": "windbreaks",
        "Raptor perches or trees at field edge": "owl_raptor_boxes",
        "Bird boxes": "bird_boxes",
        "Bat boxes": "bat_boxes",
        "Ensure a clean water source": "clean_water_source",
        "Plant flowers interspersed with crops": "pollinator_habitat",
        "Support a variety of bee species": "bee_diversity",
        "Allow non-invasive plants in non-cropped, fallow, and border areas": "non_invasive_borders",
        "Provide extended food supply": "extended_food_supply",
    },
    ("otco", "2b"): {
        "Use fish screens": "fish_screens",
        "Provide clean water sources": "clean_water_source",
        "Manage water for priority species": "priority_species_water",
        "Retain or restore vegetated riparian buffers and wetlands": "riparian_buffers",
        "Protect or improve natural hydrology of riparian areas": "riparian_hydrology",
    },
    ("otco", "3"): {
        "Manage native plants and wildlife specific to the site": "native_plantings",
        "Wildlife-friendly fences": "wildlife_friendly_fences",
        "Preserve or restore wildlife corridors": "wildlife_corridors",
        "Leave areas as undisturbed habitat refuge": "undisturbed_refuge",
        "Preserve or restore wetlands and riparian areas": "wetland_woodland_protection",
        "Preserve or restore grasslands": "grassland_protection",
        "Native habitats not converted to farmland since certification": "habitat_not_converted",
        "Establish legal conservation areas": "legal_conservation_areas",
        "Replace weedy areas with native plants": "replace_weedy_areas",
        "Minimize erosion": "erosion_control_plantings",
        "Standing deadwood, fallen or rotting trees": "standing_deadwood",
        "Allow degraded areas to be recolonized": "recolonize_degraded",
        "Recognize priority species and habitat and create protection plans": "priority_species_plan",
    },
    ("otco", "4"): {
        "Hedgerows": "hedgerows",
        "Windbreaks": "windbreaks",
        "Raptor perches or trees at field edge": "owl_raptor_boxes",
        "Bird boxes": "bird_boxes",
        "Bat boxes": "bat_boxes",
        "Ensure a clean water source": "clean_water_source",
        "Plant flowers interspersed with crops": "pollinator_habitat",
        "Brush piles": "brush_piles",
        "Support a variety of bee species": "bee_diversity",
        "Provide extended food supply": "extended_food_supply",
        "Allow non-invasive plants in non-cropped areas": "non_invasive_borders",
        "Short, medium and tall native habitat": "layered_native_habitat",
        "Timing of field activities": "field_activity_timing",
    },
}

#: What a plan answered before 2026.12.12: G4.2's required questions.
FILED = {
    "soil_water_practices": ["cover_cropping", "micro_irrigation"],
    "habitat_biodiversity_practices": ["hedgerows", "bat_boxes"],
    "conservation_plan_agency": ["none"],
    "invasive_species_practices": ["mowing"],
    "wildlife_habitat_pressure": ["neither"],
    "irrigation_source_types": ["well"],
    "irrigation_water_sources": "Two wells on the home block",
    "shared_irrigation_with_prohibited": False,
    "water_quality_tested": False,
    "water_from_irrigation_district": False,
    "monitoring_method": ["photo_points"],
}

ANSWERS = {
    **FILED,
    "permanent_ground_cover_90pct": True,
    "slope_under_10pct": False,
    "soil_water_practices": ["cover_cropping", "micro_irrigation", "filter_strip", "nutrient_management"],
    "habitat_biodiversity_practices": ["hedgerows", "bat_boxes", "bird_boxes", "brush_piles", "field_border"],
    "streams_or_channels_adjacent": True,
    "waterway_practices": ["riparian_forest_buffer", "fish_screens", "other"],
    "waterway_practices_other": "Beaver dam analogues on the lower creek",
    "other_conservation_measures": True,
    "other_conservation_measures_detail": "Owl nest boxes are cleaned and checked every February",
    "conservation_plan_agency": ["nrcs", "salmon_safe"],
    "conservation_plan_detail": "NRCS EQIP contract 2025: hedgerow planting, micro-irrigation, filter strips",
}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class EveryNamedPracticeHasAnOption(TestCase):
    """The register calls these rows covered because every practice the form names is an option a cited list
    carries. This pins it: a renamed or dropped option fails here, not on a reviewer's desk."""

    def test_each_named_practice_is_offered(self):
        lists = SOIL | HABITAT | WATERWAY | EROSION
        for (agent, ref), named in NAMED.items():
            for words, value in named.items():
                with self.subTest(agent=agent, ref=ref, practice=words):
                    if "." in value:
                        module, key = value.split(".")
                        self.assertTrue(any(q.key == key for p in MODULES_BY_KEY[module].pages for q in p.questions))
                    else:
                        self.assertIn(value, lists)


class EveryNewQuestionIsOptional(TestCase):
    def test_a_plan_filed_before_them_stays_complete(self):
        new = [
            (
                G42,
                (
                    "permanent_ground_cover_90pct",
                    "slope_under_10pct",
                    "waterway_practices",
                    "waterway_practices_other",
                    "other_conservation_measures",
                    "other_conservation_measures_detail",
                    "conservation_plan_agency_other",
                ),
            ),
            (G40, ("rotation_records_kept", "applies_fertilizers")),
            (G31, ("enclosed_structure_conservation", "enclosed_structure_conservation_other")),
        ]
        for module, keys in new:
            questions = {q.key: q for page in module.pages for q in page.questions}
            for key in keys:
                with self.subTest(question=key):
                    self.assertFalse(questions[key].required)
        self.assertEqual(progress(G42, {**FILED, "streams_or_channels_adjacent": True})["missing"], [])


class TheOldAnswersKeepTheirMeaning(TestCase):
    def test_new_options_are_appended_before_other(self):
        soil = _options(G42, "soil_water_practices")
        self.assertEqual(soil[:3], ["cover_cropping", "reduced_tillage", "contour_terracing"])
        self.assertEqual(soil.index("micro_irrigation"), 16)
        self.assertEqual(soil[-1], "other")
        habitat = _options(G42, "habitat_biodiversity_practices")
        self.assertEqual(
            habitat[:7],
            [
                "hedgerows",
                "native_plantings",
                "pollinator_habitat",
                "owl_raptor_boxes",
                "bat_boxes",
                "wetland_woodland_protection",
                "wildlife_corridors",
            ],
        )
        self.assertEqual(habitat[-1], "other")

    def test_the_joint_federal_agency_is_retired_not_remapped(self):
        options = {
            o.value: o for p in G42.pages for q in p.questions if q.key == "conservation_plan_agency" for o in q.options
        }
        self.assertTrue(options["federal_agency"].retired)
        self.assertFalse(options["nrcs"].retired)
        # A plan that answered it still shows its detail question.
        shown = {q.key for _p, q in visible_questions(G42, {"conservation_plan_agency": ["federal_agency"]})}
        self.assertIn("conservation_plan_detail", shown)


class TheGates(TestCase):
    def _shown(self, module, answers):
        return {q.key for _p, q in visible_questions(module, answers)}

    def test_waterway_practices_follow_streams_by_the_land(self):
        self.assertNotIn("waterway_practices", self._shown(G42, {}))
        self.assertNotIn("waterway_practices", self._shown(G42, {"streams_or_channels_adjacent": False}))
        self.assertIn("waterway_practices", self._shown(G42, {"streams_or_channels_adjacent": True}))

    def test_details_open_on_their_answers(self):
        self.assertNotIn("other_conservation_measures_detail", self._shown(G42, {"other_conservation_measures": False}))
        self.assertIn("other_conservation_measures_detail", self._shown(G42, {"other_conservation_measures": True}))
        self.assertIn("conservation_plan_agency_other", self._shown(G42, {"conservation_plan_agency": ["other"]}))
        self.assertNotIn("rotation_records_kept", self._shown(G40, {"system_type": ["perennial"]}))
        self.assertIn("rotation_records_kept", self._shown(G40, {"system_type": ["annual"]}))


class _Plan(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Creekside Orchards LLC")
        self.est = Establishment.objects.create(name="Creekside Orchards", company=company, state="WA")

    def plan(self, modules, certifier=WSDA):
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.filter(establishment=self.est).count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={
                "schema_version": 1,
                "modules": {
                    key: (
                        {"not_applicable": True, "na_attestation": {"by": None, "at": "2026-11-15T00:00:00+00:00"}}
                        if answers is None
                        else {
                            "answers": {k: {"value": v} for k, v in answers.items()},
                            "definition_version": "2026.12.12",
                        }
                    )
                    for key, answers in modules.items()
                },
            },
        )
        return self.osp

    def row(self, agent, stem, ref):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms(agent) if f.path.stem == stem)
        return next(r for r in form_answer_states(self.osp, [form])[id(form)] if r.ref == ref)


class TheModulePdfPrintsThem(_Plan):
    def test_every_answer_prints(self):
        text = _text(generate_module_pdf(self.plan({"g4_2_natural_resources": ANSWERS}), "g4_2_natural_resources"))
        for words in (
            "Is permanent ground cover, such as sod, established on at least 90% of the ground",
            "Filter strips",
            "Nutrient management",
            "Bird boxes",
            "Brush piles",
            "Field borders",
            "Which practices protect the streams, shorelines and channels on or next to your land?",
            "Riparian forest buffer",
            "Fish screens on water diversions",
            "Beaver dam analogues on the lower creek",
            "Owl nest boxes are cleaned and checked every February",
            "USDA Natural Resources Conservation Service (NRCS)",
            "Salmon Safe",
        ):
            with self.subTest(words=words):
                self.assertIn(words, text)

    def test_a_no_compiles_to_what_was_said(self):
        self.plan({"g4_2_natural_resources": ANSWERS, "g4_0_rotation_soil": {"applies_fertilizers": False}})
        narrative = " ".join(" ".join(v) for v in compile_module_contributions(self.osp).values())
        self.assertIn("Some certified ground slopes 10% or more.", narrative)
        self.assertIn("No fertilizer or other nutrient is applied to the certified land.", narrative)


class TheRegisterReadsThem(_Plan):
    WSDA_ROWS = ("2", "3", "3a", "4", "5", "6", "13", "15", "17", "18")

    def test_wsda_section_e_closes_with_the_answers(self):
        self.plan(
            {
                "g4_2_natural_resources": ANSWERS,
                "g4_0_rotation_soil": {
                    "system_type": ["annual"],
                    "rotation_plan": "Squash, then winter rye, then beans",
                    "rotation_records_kept": "Seasons in Trazo per block",
                    "in_lieu_practices": ["cover_crops"],
                    "erosion_practices": ["cover_cropping"],
                    "applies_fertilizers": True,
                    "fertility_components": ["compost"],
                },
                "g4_1_compost_manure": {"materials_applied": ["purchased_compost"]},
            }
        )
        for ref in self.WSDA_ROWS + ("1b", "11"):
            with self.subTest(ref=ref):
                # E 17 is answered in full and still `partial`: the blind re-grade of 2026-11-19 found nothing in the
                # packet stating which practices address sedimentation (register gap).
                expected = "partial" if ref == "17" else "answered"
                self.assertEqual(self.row("wsda", "2121-E-biodiversity", ref).state, expected)

    def test_streams_by_the_land_need_their_practices(self):
        answers = {**ANSWERS}
        del answers["waterway_practices"], answers["waterway_practices_other"]
        erosion = {"erosion_practices": ["cover_cropping"]}
        # Everything else E 17 cites is answered, so the waterway list is the one thing open.
        self.plan({"g4_2_natural_resources": answers, "g4_0_rotation_soil": erosion})
        state = self.row("wsda", "2121-E-biodiversity", "17")
        self.assertTrue(state.is_open)
        self.assertIn("waterway", state.detail)
        self.plan(
            {
                "g4_2_natural_resources": {**answers, "streams_or_channels_adjacent": False},
                "g4_0_rotation_soil": erosion,
            }
        )
        # Closed as far as the register allows: `partial` since the blind re-grade of 2026-11-19.
        self.assertEqual(self.row("wsda", "2121-E-biodiversity", "17").state, "partial")

    def test_no_other_measures_is_an_answer(self):
        self.plan({"g4_2_natural_resources": {**FILED, "other_conservation_measures": False}}, certifier=CCOF)
        self.assertEqual(self.row("ccof", "G4.2-natural-resources", "A9").state, "answered")
        self.assertEqual(self.row("otco", "C6-natural-resources-biodiversity", "7").state, "answered")

    def test_a_filed_plan_is_open_on_the_new_asks(self):
        self.plan({"g4_2_natural_resources": FILED})
        for ref in ("3", "4", "5"):
            with self.subTest(ref=ref):
                self.assertTrue(self.row("wsda", "2121-E-biodiversity", ref).is_open)

    def test_otco_1a_reads_the_named_agency_and_not_the_retired_one(self):
        self.plan(
            {
                "g4_2_natural_resources": {
                    **FILED,
                    "conservation_plan_agency": ["federal_agency"],
                    "conservation_plan_detail": "EQIP",
                }
            },
            certifier=OTCO,
        )
        self.assertTrue(self.row("otco", "C6-natural-resources-biodiversity", "1a").is_open)
        self.plan(
            {
                "g4_2_natural_resources": {
                    **FILED,
                    "conservation_plan_agency": ["nrcs"],
                    "conservation_plan_detail": "EQIP",
                }
            },
            certifier=OTCO,
        )
        self.assertEqual(self.row("otco", "C6-natural-resources-biodiversity", "1a").state, "answered")

    def test_ccof_a8_follows_the_structures(self):
        self.plan({"g3_1_container_greenhouse": None}, certifier=CCOF)
        self.assertFalse(self.row("ccof", "G4.2-natural-resources", "A8").is_open)
        self.plan({"g3_1_container_greenhouse": {"structure_production_types": ["annual_seedlings"]}}, certifier=CCOF)
        self.assertTrue(self.row("ccof", "G4.2-natural-resources", "A8").is_open)
        self.plan(
            {
                "g3_1_container_greenhouse": {
                    "structure_production_types": ["annual_seedlings"],
                    "enclosed_structure_conservation": ["water_conservation"],
                }
            },
            certifier=CCOF,
        )
        self.assertEqual(self.row("ccof", "G4.2-natural-resources", "A8").state, "answered")
