"""A rate divided by an area is not a rate.

Soil amendments are recorded in the unit the bag and the soil report use — "lb/acre" — so
the derived per-area rate turned "300.00 lb/acre" into "142.86 lb/acre/acre" on a live
certifier packet. The unit does not exist, and the number is 143x smaller than what the
operator actually applied, printed beside the correct figure as though it clarified it.
"""

from django.test import SimpleTestCase

from history.services.audit_export_service import _qty_with_unit, _rate_per_area


class RatePerAreaTests(SimpleTestCase):
    def test_a_plain_amount_still_derives_a_rate(self):
        self.assertEqual(_rate_per_area(8, 12.5, "oz", "acres"), "0.64 oz/acre")

    def test_an_amount_already_expressed_per_area_derives_nothing(self):
        self.assertIsNone(_rate_per_area(300, 2.1, "lb/acre", "acres"))

    def test_the_word_form_is_caught_too(self):
        self.assertIsNone(_rate_per_area(300, 2.1, "lb per acre", "acres"))

    def test_a_missing_side_still_returns_none(self):
        self.assertIsNone(_rate_per_area(None, 12.5, "oz", "acres"))
        self.assertIsNone(_rate_per_area(8, None, "oz", "acres"))
        self.assertIsNone(_rate_per_area(8, 0, "oz", "acres"))

    def test_no_rate_without_a_numerator_unit(self):
        """ "12.50 /acre" is a number with no unit and a stray space.

        Reachable since the 2026-08-19 backfill populated `volume_numeric` on records whose
        `volume_unit` was never recorded — the numbers arrived, the units did not.
        """
        self.assertIsNone(_rate_per_area(12.5, 1.0, "", "acres"))
        self.assertIsNone(_rate_per_area(12.5, 1.0, None, "acres"))


class QuantityWithUnitTests(SimpleTestCase):
    """A magnitude with no unit must say so rather than look like a measurement."""

    def test_a_recorded_unit_is_used(self):
        self.assertEqual(_qty_with_unit(12.5, "acres"), "12.50 acres")

    def test_a_missing_unit_is_named_not_implied(self):
        # Acres and hectares differ by 2.47x; a reader cannot tell a missing unit from an
        # implied one, and the packet must not let them guess.
        self.assertEqual(_qty_with_unit(12.5, ""), "12.50 (unit not recorded)")
        self.assertEqual(_qty_with_unit(12.5, None), "12.50 (unit not recorded)")

    def test_no_value_returns_none_so_the_cell_falls_back_to_a_dash(self):
        self.assertIsNone(_qty_with_unit(None, "acres"))
        self.assertIsNone(_qty_with_unit("", "acres"))
