"""The input verifier's verdict (`found`, `status`, `notes`) says what the rule and the catalogue say.

Overall review 2026-11, OV-MT-C14. `verify_input` answers with the lookup's typed fields, which the
screens read, and with a verdict from `OMRIProductVerifier`, which no screen reads yet and any export
or integration could. The verdict said:

- "PROHIBITED ... Use disqualifies the crop from organic sale" for the three § 205.602 entries the rule
  allows for one stated use, so calcium chloride sprayed for bitter pit (the use § 205.602(c) names)
  read as a lost certification;
- `found: true` and one product's name when a name matched several OMRI products, which is the guessed
  listing the lookup's candidate list exists to stop;
- a listing match for an OMRI product OMRI has dropped, which the lookup reported as dropped;
- a paraphrase ("Minimize soil accumulation.") for a § 205.601 entry the rule allows only under a
  condition of use, where the lookup gives the rule's own words (OV-MT-C01).
"""

from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from rest_framework.test import APIClient

from certifications.management.commands.seed_national_list import SECTION_602_PROHIBITED
from certifications.models import OMRIProduct
from certifications.services import national_list_citations as nlc
from certifications.services.omri_verifier import OMRIProductVerifier

#: The § 205.602 entries the rule allows for one stated use, with the rule's words, from the seeder.
CONDITIONAL_602 = {name: (letter, notes) for letter, _status, name, notes in SECTION_602_PROHIBITED if notes}


class _Seeded(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_national_list", stdout=StringIO())

    def setUp(self):
        self.verifier = OMRIProductVerifier()


class AConditionalProhibitionIsNotAProhibitionTests(_Seeded):
    def test_the_three_conditional_entries_are_restricted_use_with_the_rule_s_words(self):
        self.assertEqual(
            set(CONDITIONAL_602), {"Calcium chloride (brine process)", "Potassium chloride", "Sodium nitrate"}
        )
        for name, (letter, words) in CONDITIONAL_602.items():
            with self.subTest(name=name):
                result = self.verifier.verify(name)
                self.assertTrue(result.found)
                self.assertEqual(result.status, "restricted_use")
                self.assertNotIn("PROHIBITED", result.notes)
                self.assertNotIn("disqualif", result.notes)
                self.assertIn(f"§ 205.602({letter}): {words}", result.notes)
                self.assertEqual(result.certifier_name, f"7 CFR § 205.602({letter})")

    def test_a_product_name_carrying_the_substance_reads_the_same(self):
        result = self.verifier.verify("Muriate of potash, Potassium chloride 0-0-60")
        self.assertEqual(result.status, "restricted_use")
        self.assertEqual(result.confidence_score, 0.75)

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
        from certifications.models import NationalListSubstance

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


class SeveralOMRIProductsAreNotOneTests(_Seeded):
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

    def test_a_name_several_products_share_chooses_none(self):
        result = self.verifier.verify("Neptune's Harvest")
        self.assertFalse(result.found)
        self.assertEqual(result.status, "several_matches")
        self.assertIsNone(result.source_url)
        self.assertIn("4 OMRI-listed products match", result.notes)
        self.assertIn("and 1 more", result.notes)

    def test_the_exact_product_name_is_one_match(self):
        result = self.verifier.verify("Neptune's Harvest Kelp Meal")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "listing_match")
        self.assertIn("nep-1002", result.notes)

    def test_a_substance_match_still_answers_and_says_the_products_were_several(self):
        result = self.verifier.verify("Elemental sulfur")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "listing_match")
        self.assertIn("205.601", result.certifier_name)
        self.assertIn("2 OMRI-listed products match", result.notes)


class ADroppedOMRIProductIsNotListedTests(_Seeded):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        OMRIProduct.objects.create(
            omri_id="old-0042", product_name="Retired Fungicide X", manufacturer="C", delisted_on=date(2026, 10, 1)
        )

    def test_by_code_and_by_name(self):
        for result in (
            self.verifier.verify("whatever", certification_number="old-0042"),
            self.verifier.verify("Retired Fungicide X"),
        ):
            with self.subTest(notes=result.notes):
                self.assertEqual(result.status, "delisted")
                self.assertIn("2026-10-01", result.notes)
                self.assertNotIn("cross-check", result.notes)


class TheEndpointCarriesTheVerdictTests(_Seeded):
    def test_verify_input_answers_restricted_use(self):
        from users.models import User

        client = APIClient()
        client.force_authenticate(user=User.objects.create_user(email="verdict@test.com", password="x"))
        body = client.get("/api/certifications/verify-input/", {"name": "Sodium nitrate"}).json()
        self.assertTrue(body["found"])
        self.assertEqual(body["status"], "restricted_use")
        self.assertNotIn("PROHIBITED", body["notes"])
        # The verdict and the lookup's typed fields agree.
        self.assertIs(body["national_list_conditional"], True)
