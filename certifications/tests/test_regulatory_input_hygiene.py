"""Placeholder text must not reach a regulatory filing.

From the 2026-08-03 dossier review: a live Annual Continuation (7 CFR 205.406)
rendered `Changes Summary: "Test"`, `Additions: "TNe"`, `Deletions: "test"`
verbatim into the certifier packet, and a State Organic Program registration
showed a Ventura farm registered in Tulare County with its renewal date equal to
its registration date.
"""

import datetime

from django.test import TestCase

from certifications.serializers import (
    OSPAnnualUpdateSerializer,
    StateOrganicRegistrationSerializer,
    looks_like_placeholder,
)


class PlaceholderDetectionTests(TestCase):
    def test_scratch_input_is_detected(self):
        for value in ("test", "Test", "TESTING", "tbd", "n/a", "asdf", "placeholder", "prueba", "None."):
            with self.subTest(value=value):
                self.assertTrue(looks_like_placeholder(value))

    def test_real_answers_are_not_flagged(self):
        # A length floor would have failed these, which is why the check matches the
        # failure mode instead.
        for value in ("No material changes.", "Added one OMRI compost supplier", "Lime", ""):
            with self.subTest(value=value):
                self.assertFalse(looks_like_placeholder(value))

    def test_contains_is_not_enough(self):
        # "Latest soil test results" contains "test" but is a real answer.
        self.assertFalse(looks_like_placeholder("Latest soil test results"))

    def test_repeated_scratch_words_are_detected(self):
        # Whole-string matching passed these straight through to a certifier filing:
        # "test test" was live in the annual-update summary on 2026-08-03.
        for value in ("test test", "TBD tbd", "test, test.", "none  n/a"):
            with self.subTest(value=value):
                self.assertTrue(looks_like_placeholder(value))

    def test_one_scratch_word_among_real_ones_is_allowed(self):
        for value in ("test block moved north", "Removed the sample plot"):
            with self.subTest(value=value):
                self.assertFalse(looks_like_placeholder(value))


class AnnualUpdateHygieneTests(TestCase):
    def setUp(self):
        self.serializer = OSPAnnualUpdateSerializer()

    def test_placeholder_summary_is_rejected(self):
        with self.assertRaises(Exception):
            self.serializer.validate_changes_summary("Test")

    def test_real_summary_is_accepted(self):
        self.assertEqual(
            self.serializer.validate_changes_summary("No material changes."),
            "No material changes.",
        )

    def test_unmatchable_junk_entry_is_caught_by_the_length_floor(self):
        # "TNe" is not a recognisable placeholder word; the floor is what stops it.
        with self.assertRaises(Exception):
            self.serializer.validate_additions(["TNe"])

    def test_short_but_real_entry_is_allowed(self):
        self.assertEqual(self.serializer.validate_additions(["Lime"]), ["Lime"])

    def test_descriptive_entry_is_allowed(self):
        value = ["New OMRI compost supplier: Sonoma Compost"]
        self.assertEqual(self.serializer.validate_additions(value), value)

    def test_repeated_scratch_summary_is_rejected(self):
        # The live 2026-08-03 filing read "test test" and saved cleanly.
        with self.assertRaises(Exception):
            self.serializer.validate_changes_summary("test test")

    def test_placeholder_and_short_entries_get_separate_instructions(self):
        # One shared sentence told the grower neither what was wrong nor what to do.
        with self.assertRaises(Exception) as ctx:
            self.serializer.validate_deletions(["test", "tst"])
        message = " ".join(str(m) for m in ctx.exception.detail)
        self.assertIn('Placeholder text, not a change: "test"', message)
        self.assertIn('Too short to describe a change: "tst"', message)
        self.assertIn("at least 4 characters", message)

    def test_message_does_not_repeat_the_field_name(self):
        # DRF keys the error under "additions" already; the old text restated it, so the
        # UI rendered "additions: Additions contains entries that do not describe...".
        with self.assertRaises(Exception) as ctx:
            self.serializer.validate_additions(["tst"])
        message = " ".join(str(m) for m in ctx.exception.detail)
        self.assertNotIn("Additions", message)

    def test_message_uses_plain_quotes_not_python_repr(self):
        with self.assertRaises(Exception) as ctx:
            self.serializer.validate_additions(["tst"])
        message = " ".join(str(m) for m in ctx.exception.detail)
        self.assertIn('"tst"', message)
        self.assertNotIn("'tst'", message)


class StateRegistrationHygieneTests(TestCase):
    def setUp(self):
        self.serializer = StateOrganicRegistrationSerializer()

    def test_real_california_counties_pass(self):
        for county in ("Ventura", "Tulare", "Ventura County"):
            with self.subTest(county=county):
                self.assertEqual(self.serializer.validate_county(county), county)

    def test_out_of_state_or_misspelled_county_is_rejected(self):
        # Catching it here beats discovering it on a PUR headed to the County
        # Agricultural Commissioner.
        for county in ("Polk", "Ventora"):
            with self.subTest(county=county):
                with self.assertRaises(Exception):
                    self.serializer.validate_county(county)

    def test_renewal_on_the_registration_date_is_rejected(self):
        same = datetime.date(2026, 8, 3)
        with self.assertRaises(Exception):
            self.serializer.validate({"registration_date": same, "renewal_date": same})

    def test_renewal_after_registration_is_accepted(self):
        attrs = {
            "registration_date": datetime.date(2026, 1, 15),
            "renewal_date": datetime.date(2027, 1, 15),
        }
        self.assertEqual(self.serializer.validate(attrs), attrs)
