"""
Every explanatory note on an input calculation carries a code the app can word (2026-11-09).

The calculator explains why a product got its factor ("Organic pesticide (neem, pyrethrin) uses
lower emission factor than synthetic pesticides") as an English sentence in `breakdown.note`,
and the app's carbon box printed it verbatim: English on a Spanish screen. Each note now comes
with a `note_code`, which the app turns into a sentence in the reader's language
(`carbonPreview.note.<code>`); the English `note` stays for anything else that reads it.

The frontend parity test (`carbonNotesHaveCopy.test.ts`) reads the codes from this module's
source, so a code added here without copy there fails on that side.
"""

import unittest

from carbon.services.verified_emission_factors import VerifiedEmissionFactors

CASES = [
    ("PE", "organic_pesticide", "organic_pesticide"),
    ("PE", "biological_pesticide", "biological_pesticide"),
    ("HE", "organic_herbicide", "organic_herbicide"),
    ("FU", "copper_fungicide", "copper_fungicide"),
    ("FU", "sulfur_fungicide", "sulfur_fungicide"),
    ("FU", "biological_fungicide", "biological_fungicide"),
    ("FU", "organic_fungicide", "organic_fungicide"),
    ("FE", "organic_fertilizer", "organic_fertilizer"),
    ("FE", "slow_release_fertilizer", "slow_release_fertilizer"),
]


def _breakdown(chemical_type, subtype):
    npk = {"N": 10, "P": 5, "K": 5} if chemical_type == "FE" else {"N": 0, "P": 0, "K": 0}
    return VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type=chemical_type,
        volume_liters=20.0,
        area_hectares=1.0,
        npk_content=npk,
        chemical_subtype=subtype,
        concentration=25.0,
    )["breakdown"]


class ChemicalNotesCarryCodes(unittest.TestCase):
    def test_each_noted_subtype_sends_its_code(self):
        for chemical_type, subtype, code in CASES:
            with self.subTest(subtype=subtype):
                breakdown = _breakdown(chemical_type, subtype)
                self.assertTrue(breakdown.get("note"), f"{subtype}: no note at all")
                self.assertEqual(breakdown.get("note_code"), code)

    def test_a_synthetic_product_sends_no_note_and_no_code(self):
        # Anti-vacuity: the code travels with a note, not on every breakdown.
        breakdown = _breakdown("PE", "synthetic_pesticide")
        self.assertNotIn("note_code", breakdown)

    def test_slow_release_note_makes_no_efficiency_claim(self):
        # It said "has better efficiency", with nothing behind it. The fact is the premium.
        note = _breakdown("FE", "slow_release_fertilizer")["note"]
        self.assertIn("10%", note)
        self.assertNotIn("efficien", note.lower())


if __name__ == "__main__":
    unittest.main()
