"""A § 205.601 entry the rule allows only under a condition is never a plain "allowed".

WHY THIS EXISTS (2026-11-16, overall review 2026-11, OV-MT-C01)
---------------------------------------------------------------
The input lookup said "allowed" and the buyer chip said "Allowed input · National List § 205.601"
for every § 205.601 hit. Most entries allow the substance only as their words say: zinc, boron and
the other micronutrients need a deficiency documented by soil or tissue testing ((j)(7)), magnesium
sulfate a documented soil deficiency ((j)(6)), the fixed coppers must be used so copper does not
build up in the soil ((i)(2)), and boric acid is for structural pest control with no contact with
crops ((e)(3)). An orchard looking up zinc for its walnuts read "allowed" and nothing about a tissue
test.

The split between an entry that limits the USE and one that only says what qualifies as the
substance ("Lime sulfur—including calcium polysulfide") is typed by paragraph in
`national_list_citations.USE_CONDITION_601`, never read from the prose. These tests pin that table
against the rule, against the seeded rows, and through every surface that reads it: the lookup,
the plan's approved inputs, the buyer chip, the trace and the buyer page's evidence tier.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from rest_framework.test import APIClient

from certifications.management.commands.seed_national_list import SECTION_601_ALLOWED
from certifications.models import NationalListSubstance
from certifications.services import national_list_citations as nlc
from history.services.claim_authority import (
    LABEL_INPUT_NATIONAL_LIST,
    LABEL_INPUT_NATIONAL_LIST_WITH_CONDITION,
    may_claim_input_listing,
)
from history.services.claim_resolver import resolve_input_status

#: Every § 205.601 paragraph whose entry carries words beyond the substance's name, read from the
#: eCFR text (Title 7 issue of 2026-11-12). Entries that are a name alone, or a name and a CAS number,
#: are not here.
PARAGRAPHS_WITH_WORDS = {
    "(a)(2)",
    "(a)(2)(iii)",
    "(a)(2)(iv)",
    "(a)(3)",
    "(a)(5)",
    "(a)(6)",
    "(a)(8)",
    "(b)(1)",
    "(b)(2)(i)",
    "(b)(2)(ii)",
    "(b)(2)(iii)",
    "(c)",
    "(d)",
    "(e)(1)",
    "(e)(2)",
    "(e)(3)",
    "(e)(4)",
    "(e)(6)",
    "(e)(7)",
    "(e)(10)",
    "(i)(1)",
    "(i)(2)",
    "(i)(3)",
    "(i)(7)",
    "(i)(8)",
    "(j)(1)",
    "(j)(3)",
    "(j)(4)",
    "(j)(5)",
    "(j)(6)",
    "(j)(7)",
    "(j)(8)",
    "(j)(10)",
    "(j)(11)",
    "(k)(1)",
    "(k)(2)",
    "(l)",
    "(m)(2)",
    "(n)",
    "(o)(1)",
    "(o)(2)",
}

#: The seeded § 205.601 rows the rule allows only under a condition of use, by catalogue name.
ROWS_WITH_A_CONDITION = {
    "Calcium hypochlorite",
    "Chlorine dioxide",
    "Hypochlorous acid (from electrolyzed water)",
    "Potassium hypochlorite",
    "Sodium hypochlorite",
    "Copper sulfate (algicide)",
    "Ozone gas",
    "Peracetic acid",
    "Sodium carbonate peroxyhydrate",
    "Soap-based herbicides",
    "Ammonium soaps",
    "Ammonium carbonate",
    "Boric acid",
    "Copper sulfate (insecticide)",
    "Sucrose octanoate esters",
    "Copper hydroxide",
    "Copper oxide",
    "Copper oxychloride",
    "Copper sulfate (fungicide)",
    "Peracetic acid (fire blight)",
    "Lignin sulfonate",
    "Magnesium oxide",
    "Magnesium sulfate",
    "Soluble boron products",
    "Zinc/copper/iron/manganese/molybdenum/selenium/cobalt (sulfates, carbonates, oxides, silicates)",
    "Sulfurous acid",
    "Ethylene gas",
    "Fatty alcohols (C6, C8, C10, C12)",
    "Sodium silicate",
    "EPA List 3 inerts (Unknown Toxicity)",
    "Hydrogen chloride",
    "Microcrystalline cheesewax",
}

ZINC = "Zinc/copper/iron/manganese/molybdenum/selenium/cobalt (sulfates, carbonates, oxides, silicates)"


def _row(name, section="205.601", status="allowed"):
    return NationalListSubstance(
        substance_name=name,
        substance_name_normalized=" ".join(name.lower().split()),
        cfr_section=section,
        status=status,
    )


class TheTableIsTheRuleTests(SimpleTestCase):
    def test_the_paragraphs_with_words_are_the_ones_the_rule_has(self):
        self.assertEqual(set(nlc.RULE_WORDS_601), PARAGRAPHS_WITH_WORDS)

    def test_every_condition_of_use_has_the_rule_s_words(self):
        self.assertLessEqual(set(nlc.USE_CONDITION_601), set(nlc.RULE_WORDS_601))

    def test_the_held_annotations_are_the_same_words(self):
        # One copy of the coppers, magnesium sulfate and micronutrient text, not two that can drift.
        for (_section, name), (paragraph, text) in nlc.ANNOTATIONS.items():
            with self.subTest(row=name):
                self.assertEqual(nlc.RULE_WORDS_601[paragraph], text)

    def test_a_qualifying_description_is_not_a_condition_of_use(self):
        # What the product must be, not how it may be used. Anti-overreach: these stay "allowed".
        for paragraph in ("(e)(2)", "(e)(6)", "(e)(7)", "(i)(7)", "(j)(1)", "(j)(8)", "(b)(2)(ii)"):
            with self.subTest(paragraph=paragraph):
                self.assertNotIn(paragraph, nlc.USE_CONDITION_601)


class EverySeededRowTests(SimpleTestCase):
    def test_the_rows_with_a_condition_are_exactly_these(self):
        flagged = {name for _sub, _cat, name, _note in SECTION_601_ALLOWED if _row(name).allowed_with_condition}
        self.assertEqual(flagged, ROWS_WITH_A_CONDITION)

    def test_every_seeded_row_is_named_by_the_paragraph_table(self):
        # A row the table does not name answers None everywhere, silently. None may be missing.
        for _sub, _cat, name, _note in SECTION_601_ALLOWED:
            with self.subTest(row=name):
                self.assertTrue(nlc.paragraphs(_row(name)))

    def test_zinc_and_boron_carry_the_deficiency_words(self):
        for name in ("Soluble boron products", ZINC):
            with self.subTest(row=name):
                paragraph, words = _row(name).rule_words
                self.assertEqual(paragraph, "(j)(7)")
                self.assertIn("Micronutrient deficiency must be documented by soil or tissue testing", words)

    def test_a_chlorine_material_carries_the_entry_above_it(self):
        paragraph, words = _row("Potassium hypochlorite").rule_words
        self.assertEqual(paragraph, "(a)(2)(iv)")
        self.assertTrue(words.startswith("Chlorine materials—For pre-harvest use"))
        self.assertTrue(words.endswith("Potassium hypochlorite—for use in water for irrigation purposes."))

    def test_lime_sulfur_has_words_and_no_condition(self):
        lime = _row("Lime sulfur")
        self.assertEqual(lime.rule_words, ("(e)(6)", "Lime sulfur—including calcium polysulfide."))
        self.assertFalse(lime.allowed_with_condition)

    def test_elemental_sulfur_has_neither(self):
        sulfur = _row("Elemental sulfur")
        self.assertIsNone(sulfur.rule_words)
        self.assertFalse(sulfur.allowed_with_condition)

    def test_only_an_allowed_601_row_is_flagged(self):
        # § 205.602 has its own typed path (`is_conditionally_permitted`); a nonsynthetic row and a
        # row of another section never answer here.
        self.assertFalse(_row("Boric acid", status="prohibited").allowed_with_condition)
        self.assertFalse(_row("Calcium chloride (brine process)", section="205.602").allowed_with_condition)
        self.assertIsNone(_row("Calcium hypochlorite", section="205.605").rule_words)


class TheLookupSaysSoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for name in (
            "Boric acid",
            "Soluble boron products",
            "Copper hydroxide",
            "Elemental sulfur",
            "Lime sulfur",
            ZINC,
            "Soap-based herbicides",
            "Insecticidal soaps",
        ):
            row = _row(name)
            row.subsection = nlc.paragraphs(row)[0][1]
            row.save()

    def setUp(self):
        from users.models import User

        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.create_user(email="lookup601@test.com", password="x"))

    def _get(self, name):
        res = self.client.get("/api/certifications/verify-input/", {"name": name})
        self.assertEqual(res.status_code, 200)
        return res.json()

    def test_boric_acid_is_allowed_with_a_condition_and_says_which(self):
        body = self._get("Boric acid")
        self.assertEqual(body["national_list_substance_name"], "Boric acid")
        self.assertIs(body["national_list_allowed_with_condition"], True)
        self.assertEqual(body["national_list_rule_paragraph"], "(e)(3)")
        self.assertEqual(
            body["national_list_rule_words"],
            "Boric acid—structural pest control, no direct contact with organic food or crops.",
        )

    def test_boron_names_the_deficiency_record(self):
        body = self._get("Soluble boron products")
        self.assertIs(body["national_list_allowed_with_condition"], True)
        self.assertEqual(body["national_list_rule_paragraph"], "(j)(7)")
        self.assertIn("documented by soil or tissue testing", body["national_list_rule_words"])
        candidate = body["national_list_candidates"][0]
        self.assertIs(candidate["allowed_with_condition"], True)
        self.assertEqual(candidate["rule_paragraph"], "(j)(7)")

    def test_zinc_sulfate_reaches_the_micronutrient_row_and_its_condition(self):
        # How a walnut grower names it. The catalogue row is "Zinc/copper/iron/... (sulfates, ...)",
        # which neither contains nor is contained in "zinc sulfate", so the lookup answered "no
        # match" until it read the alias table the saved record is classified by.
        for typed in ("zinc sulfate", "Zinc Sulphate", "Solubor"):
            with self.subTest(typed=typed):
                body = self._get(typed)
                self.assertIs(body["national_list_allowed_with_condition"], True)
                self.assertEqual(body["national_list_rule_paragraph"], "(j)(7)")

    def test_an_ambiguous_term_is_still_not_resolved(self):
        # "soap" could be four listings; the alias table refuses it, so the lookup offers them all
        # by containment and the grower picks.
        names = {c["substance_name"] for c in self._get("soap")["national_list_candidates"]}
        self.assertEqual(names, {"Soap-based herbicides", "Insecticidal soaps"})

    def test_elemental_sulfur_stays_plain_allowed(self):
        body = self._get("Elemental sulfur")
        self.assertIs(body["national_list_allowed_with_condition"], False)
        self.assertIsNone(body["national_list_rule_words"])

    def test_lime_sulfur_shows_its_words_without_a_condition(self):
        body = self._get("Lime sulfur")
        self.assertIs(body["national_list_allowed_with_condition"], False)
        self.assertEqual(body["national_list_rule_words"], "Lime sulfur—including calcium polysulfide.")


def _event(substance):
    """A confirmed classification on a record the grower marked organic-approved, nothing else."""
    return SimpleNamespace(
        organic_approved="omri_listed",
        omri_product_id=None,
        omri_product=None,
        wsda_material_id=None,
        national_list_substance=substance,
        national_list_basis="operator",
        restricted_use_pesticide=False,
        extra_data={},
    )


class TheBuyerChipSaysSoTests(SimpleTestCase):
    def test_copper_reads_allowed_with_a_condition(self):
        decision = may_claim_input_listing(_event(_row("Copper hydroxide")))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.safe_label, LABEL_INPUT_NATIONAL_LIST_WITH_CONDITION)
        self.assertEqual(
            resolve_input_status(_event(_row("Copper hydroxide")))["status"], "national_list_allowed_condition"
        )

    def test_elemental_sulfur_keeps_the_plain_label(self):
        self.assertEqual(
            may_claim_input_listing(_event(_row("Elemental sulfur"))).safe_label, LABEL_INPUT_NATIONAL_LIST
        )
        self.assertEqual(resolve_input_status(_event(_row("Elemental sulfur")))["status"], "national_list_allowed")

    def test_the_grower_s_not_organic_answer_still_outranks_it(self):
        event = _event(_row("Copper hydroxide"))
        event.organic_approved = "not_organic"
        self.assertEqual(resolve_input_status(event)["status"], "conventional_documented")

    def test_the_buyer_page_files_it_as_conditional(self):
        from history.transparency_views import _organic_input_evidence

        evidence = _organic_input_evidence([_event(_row("Soluble boron products")), _event(_row("Elemental sulfur"))])
        self.assertEqual(evidence["organic_input_evidence"]["conditional"], 1)
        self.assertEqual(evidence["organic_input_evidence"]["national_list"], 1)
        self.assertEqual(evidence["organic_input_basis"], "conditional")

    def test_the_trace_names_it_with_its_own_code(self):
        from history.services.traceback import _listing_code

        self.assertEqual(_listing_code(_event(_row("Boric acid"))), "national_list_allowed_condition")
        self.assertEqual(_listing_code(_event(_row("Elemental sulfur"))), "national_list_allowed")
