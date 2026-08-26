"""redact_own_vendor_names must remove the NAME, never the middle of a word.

2026-08-25: a demo supplier literally named "Test" turned the farmer's note
"Notes test" into "Notes [supplier withheld]" — correct — but the same matcher,
unanchored, also rewrote "tested" as "[supplier withheld]ed" and "Testing" as
"[supplier withheld]ing". These tests pin the lookaround boundaries and the
behaviours that must survive them (case-insensitive whole-name match, the
address-tail and corporate-suffix stems, the stopword guard).
"""

from types import SimpleNamespace

from django.test import SimpleTestCase

from history.services.privacy import redact_own_vendor_names

REDACTED = "[supplier withheld]"


def _event(**kwargs):
    base = {"seed_supplier_name": "", "supplier_name": ""}
    base.update(kwargs)
    return SimpleNamespace(**base)


class VendorRedactionBoundaryTests(SimpleTestCase):
    def test_whole_word_still_redacted(self):
        event = _event(seed_supplier_name="Test")
        self.assertEqual(redact_own_vendor_names("Notes test", event), f"Notes {REDACTED}")

    def test_name_inside_a_longer_word_survives(self):
        event = _event(seed_supplier_name="Test")
        self.assertEqual(
            redact_own_vendor_names("We tested germination on Testing day", event),
            "We tested germination on Testing day",
        )

    def test_full_business_name_and_head_form(self):
        event = _event(seed_supplier_name="Saticoy Grove Nursery, Saticoy CA")
        out = redact_own_vendor_names("Stock arrived from Saticoy Grove Nursery in good condition", event)
        self.assertNotIn("Saticoy Grove", out)
        self.assertIn(REDACTED, out)

    def test_stem_matches_without_corporate_suffix(self):
        event = _event(supplier_name="Brokaw Nursery, Saticoy CA")
        out = redact_own_vendor_names("Ordered rootstock from Brokaw this spring", event)
        self.assertNotIn("Brokaw", out)
        self.assertIn(REDACTED, out)

    def test_stopword_stem_does_not_eat_ordinary_prose(self):
        # "Organic Seeds Inc" must not redact the word "organic" out of a sentence.
        event = _event(seed_supplier_name="Organic Seeds Inc")
        out = redact_own_vendor_names("Planted certified organic seed as planned", event)
        self.assertIn("organic", out)

    def test_case_insensitive(self):
        event = _event(seed_supplier_name="Test")
        self.assertEqual(redact_own_vendor_names("TEST confirmed the lot", event), f"{REDACTED} confirmed the lot")

    def test_punctuation_adjacent_name_still_matches(self):
        event = _event(seed_supplier_name="Test")
        self.assertEqual(redact_own_vendor_names("Called (test) twice", event), f"Called ({REDACTED}) twice")

    def test_non_string_and_empty_passthrough(self):
        event = _event(seed_supplier_name="Test")
        self.assertIsNone(redact_own_vendor_names(None, event))
        self.assertEqual(redact_own_vendor_names("", event), "")
