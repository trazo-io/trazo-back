"""No consumer surface may show a carbon LETTER GRADE, and none may attribute one to the USDA.

Found 2026-08-04 while auditing what survived the producer-dashboard score demotion.

``backend/constants.get_carbon_score_from_co2e()`` turned a production's recorded CO₂e into a grade
from A+ to F, using thresholds hardcoded in a class called ``USDAGrading`` whose docstring read
"USDA-based carbon footprint grading system". It was served to shoppers as ``carbon_score`` on the
consumer dashboard, the favorites list and the product-comparison endpoint.

Two independent violations:

* **The attribution.** There is no USDA carbon letter-grade programme. The five thresholds
  (0.5 / 1.0 / 2.0 / 3.0 / 5.0) were chosen in this repository. Naming the class ``USDAGrading``
  and calling the scale "USDA-based" is the "USDA Verified / USDA Certified" wording
  ``compliance.md`` forbids, and an unsourced attribution under FTC 16 CFR 260.6.
* **The grade itself.** Trazo grading a farm and showing that grade to a consumer is the
  self-created sustainability label EU ECGT 2024/825 bans from 2026-09-27 — the same artefact
  removed from the QR page in June 2026 and from the producer dashboard on 2026-08-04.

It survived both earlier passes because these endpoints are ``IsAuthenticated`` — a logged-in
shopper's own dashboard — so they sit outside the anonymous-surface sweep in
``test_cross_surface_claim_safety``. Login does not make a consumer claim safe; these tests exist
so the authenticated consumer surfaces are policed too.

Consumers keep the measurement (``carbon_footprint``: "1.23 kg CO₂e"), which is a fact.

The unit was wrong too. ``CarbonEntry.amount`` is a TOTAL ("Amount in kg CO2e"), but every consumer
surface rendered it as "kg CO₂e/kg" — an intensity per kilogram of product, with no yield anywhere
in the code path. The grade thresholds (0.5-5.0 per kg) were therefore compared against totals in
the hundreds or thousands, so EVERY production fell through to the last branch: shoppers were shown
an "F" for every farm on the platform. Both are fixed here.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

from history import serializers_consumer

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Every module that builds a payload for the authenticated consumer surfaces.
CONSUMER_SOURCES = (
    "history/serializers_consumer.py",
    "history/views_consumer.py",
    "backend/constants.py",
)


class CarbonGradeIsGoneTests(SimpleTestCase):
    def test_the_grading_helper_and_its_usda_named_thresholds_no_longer_exist(self):
        import backend.constants as constants

        self.assertFalse(
            hasattr(constants, "get_carbon_score_from_co2e"),
            "the A+-to-F carbon grade helper is back",
        )
        self.assertFalse(
            hasattr(constants, "USDAGrading"),
            "USDAGrading attributes an invented grading scale to a federal agency",
        )

    def test_no_consumer_module_emits_a_carbon_letter_grade(self):
        # The grade was always produced by returning one of these literals.
        grade_literals = re.compile(r"""return\s+["'](?:A\+|A|B|C|D|F)["']""")
        for rel in CONSUMER_SOURCES:
            source = (BACKEND_ROOT / rel).read_text()
            self.assertIsNone(
                grade_literals.search(source),
                f"{rel} returns a bare letter grade",
            )

    def test_no_consumer_serializer_exposes_a_carbon_score_field(self):
        """`carbon_score` was the field name the grade shipped under."""
        for name in ("EnhancedHistoryScanSerializer",):
            serializer_cls = getattr(serializers_consumer, name)
            fields = serializer_cls().get_fields()
            self.assertNotIn(
                "carbon_score",
                fields,
                f"{name} still exposes a carbon_score to consumers",
            )

    def test_the_measured_figure_is_still_offered(self):
        """Removing the grade must not remove the fact it was derived from."""
        for name in ("EnhancedHistoryScanSerializer",):
            fields = getattr(serializers_consumer, name)().get_fields()
            self.assertIn("carbon_footprint", fields, f"{name} lost the measured carbon figure")


class CarbonAmountFormatterTests(SimpleTestCase):
    """The replacement states the measurement and nothing more."""

    def test_formats_two_decimals_with_units(self):
        from backend.constants import format_carbon_amount

        self.assertEqual(format_carbon_amount(1.234), "1.23 kg CO₂e")
        self.assertEqual(format_carbon_amount(0), "0.00 kg CO₂e")

    def test_none_stays_none_rather_than_becoming_a_verdict(self):
        from backend.constants import format_carbon_amount

        self.assertIsNone(format_carbon_amount(None))

    def test_unit_does_not_claim_a_per_kilogram_intensity(self):
        """`CarbonEntry.amount` is a total; "/kg" would assert a denominator that does not exist."""
        from backend.constants import format_carbon_amount

        self.assertNotIn("/kg", format_carbon_amount(12.5))

    def test_output_carries_no_grade_vocabulary(self):
        from backend.constants import format_carbon_amount

        rendered = format_carbon_amount(4.9)
        for word in ("A+", "grade", "score", "excellent", "poor", "USDA"):
            self.assertNotIn(word.lower(), rendered.lower())
