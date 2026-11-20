"""The input verifier's verdict (`found`, `status`, `notes`) says what the rule and the catalogue say.

Overall review 2026-11, OV-MT-C14. `verify_input` answers with the lookup's typed fields, which the
screens read, and with a verdict from `OMRIProductVerifier`, which no screen reads yet and any export
or integration could. The verdict said:

- "PROHIBITED ... Use disqualifies the crop from organic sale" for the three § 205.602 entries the rule
  allows for one stated use, so calcium chloride sprayed for bitter pit (the use § 205.602(c) names)
  read as a lost certification;
- `found: true` and one product's name for any OMRI name match, ahead of the National List: against
  the committed catalogue, "Potassium chloride" named a fertilizer whose name contains the words, so
  the § 205.602(e) condition never answered (independent review of PR 505, which ran the verdict
  against `certifications/data/omri_seed.csv`; the first version of these tests seeded no OMRI rows
  and could not see it);
- one product for a name several products hold ("Potassium humate", six makers);
- a listing match for an OMRI product OMRI has dropped, which the lookup reported as dropped;
- "not found on the National List" for "calcium chloride", while the lookup in the same response
  offered § 205.602(c), and for "zinc sulfate", which the save path classifies by its curated alias;
- a paraphrase ("Minimize soil accumulation.") for a § 205.601 entry the rule allows only under a
  condition of use, where the lookup gives the rule's own words (OV-MT-C01).
"""

from datetime import date
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from rest_framework.test import APIClient

from certifications.management.commands.seed_national_list import SECTION_602_PROHIBITED
from certifications.models import NationalListSubstance, OMRIProduct
from certifications.services import national_list_citations as nlc
from certifications.services.omri_verifier import OMRIProductVerifier, _omri_candidates_by_name

#: The § 205.602 entries the rule allows for one stated use, by the seeder's own table.
CONDITIONAL_602 = {name: letter for letter, _status, name, notes in SECTION_602_PROHIBITED if notes}

OMRI_CATALOGUE = Path(__file__).resolve().parents[1] / "data" / "omri_seed.csv"


def _client():
    from users.models import User

    client = APIClient()
    client.force_authenticate(user=User.objects.create_user(email="verdict@test.com", password="x"))
    return client


class _Seeded(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_national_list", stdout=StringIO())

    def setUp(self):
        self.verifier = OMRIProductVerifier()


class AConditionalProhibitionIsNotAProhibitionTests(_Seeded):
    def test_the_three_conditional_entries_are_restricted_use_with_the_rule_s_text(self):
        self.assertEqual(
            set(CONDITIONAL_602), {"Calcium chloride (brine process)", "Potassium chloride", "Sodium nitrate"}
        )
        for name, letter in CONDITIONAL_602.items():
            with self.subTest(name=name):
                result = self.verifier.verify(name)
                self.assertTrue(result.found)
                self.assertEqual(result.status, "restricted_use")
                self.assertNotIn("PROHIBITED", result.notes)
                self.assertNotIn("disqualif", result.notes)
                # The rule's whole entry, not the stored excerpt.
                self.assertIn(f'§ 205.602({letter}): "{nlc.RULE_TEXT[("205.602", f"({letter})")]}"', result.notes)
                self.assertEqual(result.certifier_name, f"7 CFR § 205.602({letter})")

    def test_a_product_name_carrying_the_substance_reads_the_same(self):
        result = self.verifier.verify("Muriate of potash, Potassium chloride 0-0-60")
        self.assertEqual(result.status, "restricted_use")
        self.assertEqual(result.confidence_score, 0.75)

    def test_a_conditional_row_with_no_words_points_at_the_rule_and_quotes_nothing(self):
        row = NationalListSubstance.objects.get(substance_name="Sodium nitrate")
        row.subsection = "z"  # a paragraph RULE_TEXT does not hold
        row.restriction_notes = ""
        notes = self.verifier._build_nl_result(row, confidence=1.0, match_type="exact").notes
        self.assertNotIn('""', notes)
        self.assertIn("See § 205.602", notes)

    def test_an_absolute_prohibition_still_says_so(self):
        for name in ("Rotenone", "Arsenic", "Strychnine"):
            with self.subTest(name=name):
                result = self.verifier.verify(name)
                self.assertEqual(result.status, "revoked")
                self.assertIn("PROHIBITED", result.notes)


class AConditionOfUseIsQuotedTests(_Seeded):
    def test_copper_hydroxide_quotes_the_fixed_coppers_condition(self):
        result = self.verifier.verify("Copper hydroxide")
        self.assertEqual(result.status, "listing_match")
        self.assertIn("Allowed only under a condition of use", result.notes)
        self.assertIn(f"§ 205.601(i)(2): {nlc.RULE_WORDS_601['(i)(2)']}", result.notes)
        self.assertNotIn("Minimize soil accumulation", result.notes)

    def test_every_condition_row_says_so_and_no_other_allowed_row_does(self):
        checked = 0
        for row in NationalListSubstance.objects.filter(cfr_section="205.601", status="allowed"):
            with self.subTest(row=row.substance_name):
                notes = self.verifier._build_nl_result(row, confidence=1.0, match_type="exact").notes
                condition = nlc.use_condition(row)
                if condition:
                    self.assertIn(f"§ 205.601{condition[0]}: {condition[1]}", notes)
                else:
                    self.assertNotIn("condition of use", notes)
                checked += 1
        # The walk read the seeded rows, not an empty table.
        self.assertGreater(checked, 40)

    def test_elemental_sulfur_has_no_condition(self):
        result = self.verifier.verify("Elemental sulfur")
        self.assertEqual(result.status, "listing_match")
        self.assertNotIn("condition of use", result.notes)


class TheVerdictReadsTheNamesTheRecordIsClassifiedByTests(_Seeded):
    def test_a_curated_alias_reaches_its_row(self):
        for typed in ("zinc sulfate", "boron", "Solubor"):
            with self.subTest(typed=typed):
                result = self.verifier.verify(typed)
                self.assertTrue(result.found)
                self.assertIn("(alias)", result.notes)
                self.assertIn(f"§ 205.601(j)(7): {nlc.RULE_WORDS_601['(j)(7)']}", result.notes)

    def test_a_partial_name_is_a_possible_match_that_names_the_listing(self):
        result = self.verifier.verify("Calcium chloride")
        self.assertFalse(result.found)
        self.assertEqual(result.status, "possible_match")
        self.assertIn(
            "Calcium chloride (brine process), § 205.602(c), prohibited except for one stated use", result.notes
        )
        self.assertNotIn("not found on the National List", result.notes)
        # The lookup's fields in the same response offer the same row.
        body = _client().get("/api/certifications/verify-input/", {"name": "Calcium chloride"}).json()
        self.assertEqual(body["status"], "possible_match")
        self.assertEqual(body["national_list_substance_name"], "Calcium chloride (brine process)")

    def test_a_name_nothing_matches_is_still_not_found(self):
        result = self.verifier.verify("Totally Made Up Chemical")
        self.assertEqual(result.status, "not_found")


class AnOMRIProductAnswersOnlyWhenTheInputIdentifiesItTests(_Seeded):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for i, name in enumerate(
            (
                "Neptune's Harvest Fish Fertilizer 2-4-1",
                "Neptune's Harvest Fish & Seaweed 2-3-1",
                "Neptune's Harvest Kelp Meal",
                "Neptune's Harvest Seaweed Plant Food",
            )
        ):
            OMRIProduct.objects.create(omri_id=f"nep-{1000 + i}", product_name=name, manufacturer="Neptune's Harvest")
        OMRIProduct.objects.create(omri_id="tst-2001", product_name="Elemental Sulfur 90 DF", manufacturer="A")
        OMRIProduct.objects.create(omri_id="tst-2002", product_name="Elemental Sulfur Dust", manufacturer="B")
        OMRIProduct.objects.create(
            omri_id="sqm-3001", product_name="SQM Allganic maKro 60 Potassium Chloride Granular", manufacturer="SQM"
        )
        OMRIProduct.objects.create(omri_id="hum-4001", product_name="Potassium humate", manufacturer="Maker One")
        OMRIProduct.objects.create(omri_id="hum-4002", product_name="Potassium humate", manufacturer="Maker Two")
        OMRIProduct.objects.create(omri_id="agt-5001", product_name="Champ WG Agricultural Fungicide", manufacturer="C")
        OMRIProduct.objects.create(omri_id="agt-5002", product_name="Championship Copper", manufacturer="D")
        OMRIProduct.objects.create(omri_id="spn-6001", product_name="Spinosad 480 SC", manufacturer="E")

    def test_a_name_several_products_share_chooses_none(self):
        result = self.verifier.verify("Neptune's Harvest")
        self.assertFalse(result.found)
        self.assertEqual(result.status, "possible_match")
        self.assertIsNone(result.source_url)
        self.assertIn("4 products in OMRI's catalogue match", result.notes)
        self.assertIn("(OMRI #nep-1000)", result.notes)
        self.assertIn("and 1 more", result.notes)

    def test_the_exact_product_name_is_an_identity(self):
        result = self.verifier.verify("Neptune's Harvest Kelp Meal")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "listing_match")
        self.assertIn("nep-1002", result.notes)

    def test_one_fuzzy_product_does_not_outrank_the_national_list(self):
        result = self.verifier.verify("Potassium chloride")
        self.assertEqual(result.status, "restricted_use")
        self.assertIn("One product in OMRI's catalogue matches", result.notes)
        self.assertIn("sqm-3001", result.notes)

    def test_one_fuzzy_product_alone_is_a_possible_match(self):
        result = self.verifier.verify("Champ WG")
        self.assertFalse(result.found)
        self.assertEqual(result.status, "possible_match")
        self.assertIn("agt-5001", result.notes)

    def test_a_name_two_makers_hold_is_two_candidates(self):
        self.assertEqual({p.omri_id for p in _omri_candidates_by_name("Potassium humate")}, {"hum-4001", "hum-4002"})
        result = self.verifier.verify("Potassium humate")
        self.assertFalse(result.found)
        self.assertIn("2 products in OMRI's catalogue match", result.notes)

    def test_the_verdict_counts_what_the_lookup_counts(self):
        body = _client().get("/api/certifications/verify-input/", {"name": "Champ"}).json()
        self.assertEqual(body["omri_candidate_count"], 2)
        self.assertEqual(body["status"], "possible_match")
        self.assertIn("2 products in OMRI's catalogue match", body["notes"])

    def test_a_nonsynthetic_row_with_a_product_candidate_is_a_possible_match(self):
        result = self.verifier.verify("Spinosad")
        self.assertFalse(result.found)
        self.assertEqual(result.status, "possible_match")
        self.assertIn("nonsynthetic", result.notes)
        self.assertIn("spn-6001", result.notes)

    def test_a_substance_match_still_answers_and_says_the_products_were_several(self):
        result = self.verifier.verify("Elemental sulfur")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "listing_match")
        self.assertIn("205.601", result.certifier_name)
        self.assertIn("2 products in OMRI's catalogue match", result.notes)


class ADroppedOMRIProductIsNotListedTests(_Seeded):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        OMRIProduct.objects.create(
            omri_id="old-0042", product_name="Retired Fungicide X", manufacturer="C", delisted_on=date(2026, 10, 1)
        )

    def test_a_dropped_product_among_candidates_is_marked_and_counted(self):
        OMRIProduct.objects.create(omri_id="new-0043", product_name="Retired Fungicide X Plus", manufacturer="C")
        result = self.verifier.verify("Retired Fungicide")
        self.assertEqual(result.status, "possible_match")
        self.assertIn("Retired Fungicide X (OMRI #old-0042, dropped from OMRI's list as of 2026-10-01)", result.notes)
        self.assertIn("1 of them OMRI no longer lists", result.notes)
        self.assertNotIn("OMRI-listed", result.notes)

    def test_by_code_and_by_name(self):
        for result in (
            self.verifier.verify("whatever", certification_number="old-0042"),
            self.verifier.verify("Retired Fungicide X"),
            self.verifier.verify("old-0042"),
        ):
            with self.subTest(notes=result.notes):
                self.assertEqual(result.status, "delisted")
                self.assertIn("2026-10-01", result.notes)
                self.assertNotIn("cross-check", result.notes)


class AgainstTheCommittedOMRICatalogueTests(_Seeded):
    """The catalogue Trazo ships, loaded whole. The first version of this module seeded no OMRI rows, and
    every National List verdict it pinned was overridden in production by a product name that happened to
    contain the substance's words."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("seed_omri_from_csv", path=str(OMRI_CATALOGUE), stdout=StringIO())

    def test_the_catalogue_loaded(self):
        self.assertGreater(OMRIProduct.objects.count(), 9000)

    def test_the_rule_answers_for_substances_products_also_name(self):
        expected = {
            "Potassium chloride": "restricted_use",
            "Sodium nitrate": "restricted_use",
            "Ammonium nitrate": "revoked",
            "Copper hydroxide": "listing_match",
            "Lignin sulfonate": "listing_match",
        }
        for typed, status in expected.items():
            with self.subTest(typed=typed):
                result = self.verifier.verify(typed)
                self.assertEqual(result.status, status, result.notes)
                # Answered from the National List, not from a product whose name holds the words.
                self.assertIn("7 CFR § 205.", result.certifier_name)
        self.assertIn("Allowed only under a condition of use", self.verifier.verify("Lignin sulfonate").notes)

    def test_a_pasted_code_is_still_an_identity(self):
        result = self.verifier.verify("gus-4423")
        self.assertEqual(result.status, "listing_match")
        self.assertIn("gus-4423", result.notes)

    def test_the_verdict_and_the_lookup_agree_on_the_count(self):
        client = _client()
        for typed in ("Champ", "Neem", "Fulvic acid"):
            with self.subTest(typed=typed):
                body = client.get("/api/certifications/verify-input/", {"name": typed}).json()
                count = body["omri_candidate_count"]
                self.assertGreater(count, 1)
                self.assertFalse(body["found"])
                self.assertIn(f"{count} products in OMRI's catalogue match", body["notes"])
