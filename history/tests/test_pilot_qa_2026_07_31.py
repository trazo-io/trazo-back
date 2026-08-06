"""Regression tests for the 2026-07-31 CA organic walnut pilot QA pass.

Each test pins a defect found by driving a full season (13 events) through the real
UI forms and then reading the three certifier/consumer outputs. All of them were
silent: nothing errored, every request returned 2xx, and the wrong value simply
appeared in a regulator- or certifier-facing document.
"""

from decimal import Decimal

from django.test import SimpleTestCase

from history.services.audit_export_service import _fmt_credential
from history.services.pur_export_service import _fmt_rei


class PURReentryIntervalUnitTests(SimpleTestCase):
    """DPR-PML-017C box 25 is titled "Days Reentry".

    ChemicalEvent.rei_hours stores HOURS because that is how modern labels state
    short REIs (Entrust SC, EPA Reg. 62719-621: "REI of 4 hours"). The export wrote
    the raw number into the Days box, so a 4-hour interval was filed with the county
    agricultural commissioner as a 4-DAY interval — a 24x misstatement of a
    worker-safety interval on a regulatory form.
    """

    def test_sub_day_rei_is_labelled_in_hours(self):
        # The real Entrust SC walnut case from the pilot season.
        self.assertEqual(_fmt_rei(Decimal("4.0")), "4 hours")

    def test_bare_number_is_never_emitted(self):
        # The bug: "4" in a box headed "Days" reads as four days.
        self.assertNotEqual(_fmt_rei(4), "4")
        self.assertNotEqual(_fmt_rei(4), "4.0")

    def test_singular_hour(self):
        self.assertEqual(_fmt_rei(1), "1 hour")

    def test_whole_days_are_reported_as_days(self):
        self.assertEqual(_fmt_rei(24), "1 day")
        self.assertEqual(_fmt_rei(48), "2 days")

    def test_non_whole_day_multiple_stays_in_hours(self):
        self.assertEqual(_fmt_rei(72.5), "72.5 hours")

    def test_blank_and_zero_render_empty(self):
        # Box 25 is optional; an empty box is honest, "0" is a claim.
        self.assertEqual(_fmt_rei(None), "")
        self.assertEqual(_fmt_rei(""), "")
        self.assertEqual(_fmt_rei(0), "")

    def test_unparseable_value_is_passed_through_not_dropped(self):
        self.assertEqual(_fmt_rei("see label"), "see label")


class ApplicatorCredentialRenderTests(SimpleTestCase):
    """The audit PDF "Cert #" column head-truncated at 20 characters.

    Growers type prose into the free-text applicator_certification field, so the
    certificate NUMBER — the only reason the column exists — was the part that got
    cut. In the pilot run "C-0-123456" appeared ZERO times in the generated PDF.
    """

    def test_certificate_number_survives_a_long_prose_value(self):
        raw = "CA DPR Qualified Applicator Certificate C-0-123456 (Cat. B, exp. 2027-06-30)"
        out = _fmt_credential(raw)
        self.assertIn("C-0-123456", out)
        # And it must still fit the column's truncation guard (26).
        self.assertLessEqual(len(out), 26)

    def test_expiry_is_preserved_when_stated(self):
        raw = "CA DPR Qualified Applicator Certificate C-0-123456 (Cat. B, exp. 2027-06-30)"
        self.assertEqual(_fmt_credential(raw), "C-0-123456 exp 2027-06-30")

    def test_expiry_year_is_not_mistaken_for_the_licence_number(self):
        out = _fmt_credential("Applicator licence 88231, expires 2029-01-01")
        self.assertTrue(out.startswith("88231"), out)

    def test_bare_number_is_left_alone(self):
        self.assertEqual(_fmt_credential("128844"), "128844")

    def test_california_credential_type_is_preserved(self):
        # QAL / QAC / PAC / PCA are not interchangeable; an inspector reads the type as
        # closely as the number, so reducing "QAL 128844" to "128844" loses real meaning.
        self.assertEqual(_fmt_credential("QAL 128844"), "QAL 128844")
        self.assertEqual(_fmt_credential("QAC C-0-98765"), "QAC C-0-98765")

    def test_type_is_not_duplicated_when_the_number_already_carries_it(self):
        self.assertEqual(
            _fmt_credential("Private Applicator Certificate PAC-54-2211, expires 2028-03-15"),
            "PAC-54-2211 exp 2028-03-15",
        )

    def test_a_second_credential_is_not_silently_dropped(self):
        # A PCA who also holds a QAL records both; dropping one is the same class of loss
        # as the head-truncation this function exists to fix.
        out = _fmt_credential("PCA license #128844 / QAL 55512")
        self.assertIn("128844", out)
        self.assertIn("55512", out)

    def test_ambiguous_type_is_not_guessed(self):
        # Two type abbreviations present -> render neither rather than pick one.
        out = _fmt_credential("QAL 128844 and QAC 55512")
        self.assertNotIn("QAL ", out)
        self.assertIn("128844", out)

    def test_value_with_no_digits_is_returned_unchanged(self):
        # Inventing structure from an unparseable value would be worse than showing it.
        self.assertEqual(_fmt_credential("private applicator"), "private applicator")

    def test_empty_values_pass_through(self):
        self.assertIsNone(_fmt_credential(None))
        self.assertEqual(_fmt_credential(""), "")
