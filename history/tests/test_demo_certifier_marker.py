"""
The DEMO marker has to survive the frontend's certifier-name split.

WHY: `CarbonHeroSection.tsx` and `TrustSummaryHeader.tsx` both render
``certifierName.split(' (')[0]`` — the full legal name is too long for a one-line clamp, so
only the text BEFORE the first " (" reaches the most prominent claim on the consumer page.

That makes the demo dataset's disclosure positional. "Pacific Slope Organic Certifiers (DEMO)"
looks honest in the database and renders on the page as a real-sounding accredited certifier
with the marker silently cut off — a fabricated organisation presented as genuine on a page
whose whole premise is verifiability.

The prefix was "DEMO Certifier (…)" until 2026-08-01, which satisfied this rule but read as an
organisation literally named "DEMO Certifier" and wrapped to two lines in a Key Details box.
"DEMO · <name> (sample data, not an accredited agent)" keeps the marker in the surviving
position and stays short. The separator became a middle dot on 2026-08-01: an em dash reads as
machine-written, and this string is the most prominent claim on the consumer page. This test is
what stops the next rename from quietly undoing any of it.
"""

from django.test import SimpleTestCase

from history.management.commands.backfill_demo_claim_safety import CERTIFIER_FIELD_VALUES


class DemoCertifierMarkerTests(SimpleTestCase):
    def test_the_map_is_not_empty(self):
        """Guards the harness: a build error here would make every assertion below vacuous."""
        self.assertGreaterEqual(len(CERTIFIER_FIELD_VALUES), 3)

    def test_marker_survives_the_frontend_split(self):
        for source, stored in CERTIFIER_FIELD_VALUES.items():
            visible = stored.split(" (")[0]
            self.assertIn(
                "DEMO",
                visible,
                f'"{source}" stores "{stored}", which the consumer hero renders as "{visible}" — '
                "the DEMO marker is cut off, so invented sample data reads as a real certifier.",
            )

    def test_full_disclosure_is_retained(self):
        """Shortening the string for looks must not cost the disclosure itself."""
        for stored in CERTIFIER_FIELD_VALUES.values():
            self.assertIn("sample data", stored)
            self.assertIn("not an accredited agent", stored)

    def test_no_em_dash_in_the_stored_name(self):
        """The em dash reads as machine-written; this string is consumer-facing."""
        for stored in CERTIFIER_FIELD_VALUES.values():
            self.assertNotIn("\u2014", stored)

    def test_visible_portion_fits_a_one_line_clamp(self):
        """The hero clamps to `noOfLines={1}`; an over-long marker is a truncated marker."""
        for stored in CERTIFIER_FIELD_VALUES.values():
            visible = stored.split(" (")[0]
            self.assertLessEqual(len(visible), 45, f'"{visible}" is too long for the hero\'s single-line clamp')

    def test_every_mapping_lands_on_a_current_format_value(self):
        """Old-format keys exist to MIGRATE rows; none may map to another old-format string."""
        for stored in CERTIFIER_FIELD_VALUES.values():
            self.assertTrue(
                stored.startswith("DEMO · "),
                f'"{stored}" is not in the current "DEMO · <name>" format',
            )
