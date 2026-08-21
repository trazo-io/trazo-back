"""Zero is a value the operator entered. Missing is the absence of one.

Conflating the two is how this codebase invents carbon. Found 2026-08-20 while sweeping
every activity that produces emissions:

    _convert_area_to_hectares(Decimal("0"))  ->  0.404686 ha   (one acre)
    _convert_area_to_hectares("0")           ->  1.0 ha        (one hectare)

`SoilManagementEvent.area_covered` is a Decimal, and `Decimal("0")` is falsy, so
`float(area_str) if area_str else 1.0` read an explicit zero as "not supplied" and
substituted a default. A tillage record with zero area reported **151.2 kg CO2e** — a
number with no input behind it, rendered in the wizard and printed into the certifier
packet like any other. The caller compounded it: `getattr(event, "area_covered", None) or
getattr(event, "area", "0")` turned Decimal("0") into the string "0", which then hit the
1-hectare "intelligent default".

The rule these tests pin: a supplied zero produces zero. Only None/""/"unknown" — the
operator genuinely not telling us — may fall back to a default.
"""

from decimal import Decimal

from django.test import SimpleTestCase

from carbon.services.event_carbon_calculator import EventCarbonCalculator


class _AreaEvent:
    """Minimal event carrying only what the area converter reads."""

    def __init__(self, area_unit="acres", **kwargs):
        self.area_unit = area_unit
        for key, value in kwargs.items():
            setattr(self, key, value)


class AreaZeroVersusMissingTests(SimpleTestCase):
    def setUp(self):
        self.calculator = EventCarbonCalculator()
        self.event = _AreaEvent()

    def test_explicit_zero_converts_to_zero_in_every_supported_type(self):
        """Decimal, int, float and str all reach this function from different call sites."""
        for supplied in (Decimal("0"), 0, 0.0, "0", "0 acres"):
            with self.subTest(supplied=repr(supplied)):
                self.assertEqual(
                    self.calculator._convert_area_to_hectares(supplied, event=self.event),
                    0.0,
                    f"{supplied!r} is a reported zero, not a missing value",
                )

    def test_genuinely_missing_area_still_falls_back(self):
        """The default exists for real gaps; removing it entirely would under-report."""
        for supplied in (None, "", "unknown"):
            with self.subTest(supplied=repr(supplied)):
                self.assertGreater(
                    self.calculator._convert_area_to_hectares(supplied, event=self.event),
                    0.0,
                    f"{supplied!r} means the operator told us nothing — a default is appropriate",
                )

    def test_real_area_still_converts_by_unit(self):
        """Guard against 'fix zero, break everything else'."""
        self.assertAlmostEqual(
            self.calculator._convert_area_to_hectares(Decimal("0.6"), event=_AreaEvent("acres")),
            0.6 * 0.404686,
            places=6,
        )
        self.assertAlmostEqual(
            self.calculator._convert_area_to_hectares(Decimal("5"), event=_AreaEvent("ha")),
            5.0,
            places=6,
        )

    def test_zero_area_soil_event_reports_zero_not_a_default_hectare(self):
        """End-to-end: the tillage case that reported 151.2 kg from nothing."""

        class _SoilEvent:
            id = 1
            history = None
            extra_data: dict = {}
            type = "TI"
            area_covered = Decimal("0")
            area_unit = "acres"
            fuel_consumed = None
            fuel_unit = "gal"
            fuel_type = "diesel"
            equipment_hours = None
            volume = None
            observation = ""

        result = self.calculator.calculate_soil_management_event_impact(_SoilEvent())
        self.assertEqual(
            float(result["co2e"]),
            0.0,
            "zero area must not be inflated to the 1-hectare default",
        )
