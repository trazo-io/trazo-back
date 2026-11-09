"""
Every explanatory note on an input calculation carries a code the app can word (2026-11-09).

The calculator explains why a product got its factor ("Organic pesticide (neem, pyrethrin) uses
lower emission factor than synthetic pesticides") as an English sentence in `breakdown.note`,
and the app's carbon box printed it verbatim: English on a Spanish screen. Each note now comes
with a `note_code`, which the app turns into a sentence in the reader's language
(`carbonPreview.note.<code>`); the English `note` stays for anything else that reads it.

The app's parity test (`carbonNotesHaveCopy.test.tsx`) reads every `note_code` literal from the
SOURCE of `carbon/services/verified_emission_factors.py` and `carbon/views.py` (not from `CASES`
below), so a code added in either file without copy in the app fails on that side.
"""

import unittest
from pathlib import Path

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

    def test_the_aggregate_summary_note_carries_its_code_and_count(self):
        # The multi-application summary note is built in carbon/views.py, behind the optimized
        # calculate endpoint, out of reach of the service helper above. Check the payload it
        # builds names the code and the count the app words it with (review of back #357).
        views = (Path(__file__).resolve().parents[1] / "views.py").read_text()
        start = views.index('"note": f"Aggregate of {event_count}')
        block = views[start : start + 400]
        self.assertIn('"note_code": "aggregate_applications"', block)
        self.assertIn('"aggregate_application_count": event_count', block)

    def test_slow_release_note_makes_no_efficiency_claim(self):
        # It said "has better efficiency", with nothing behind it. The fact is the premium.
        note = _breakdown("FE", "slow_release_fertilizer")["note"]
        self.assertIn("10%", note)
        self.assertNotIn("efficien", note.lower())


if __name__ == "__main__":
    unittest.main()
