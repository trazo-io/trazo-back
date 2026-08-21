"""Regression tests: irrigation (IR) preview == saved carbon parity.

Covers the F06 bug (2026-06 product audit): the SAVED carbon path
(`EventCarbonCalculator.calculate_production_event_impact`) previously called
the bare `VerifiedEmissionFactors.calculate_drought_irrigation_emissions`,
which has no fuel parameter and therefore silently DROPPED auxiliary diesel
(~51 kg CO2e on a typical 5-gallon service-vehicle / standby-pump setup).

The PREVIEW path (`carbon/views.py` ->
`VerifiedEmissionFactors.calculate_production_event_emissions`) includes that
auxiliary diesel via the 2026-04-10 add_auxiliary_diesel logic.

These tests pin the invariant: for the SAME IR event, preview CO2e == saved
CO2e, and the auxiliary diesel is present in both. Rule (feedback_ir_carbon_calc):
IR must SUM pump electricity + auxiliary diesel, never substitute one for the other.
"""

from decimal import Decimal

from django.test import TestCase

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.services.verified_emission_factors import VerifiedEmissionFactors


class _FakeIrrigationEvent:
    """Minimal duck-typed IR event.

    Only the attributes the IR branch of `calculate_production_event_impact`
    (and its `_extract_production_event_data` helper) actually read are set.
    `water_volume_total` is provided so water resolution short-circuits before
    the estimation helper, and `fuel_unit="gal"` keeps fuel in gallons (no
    L->gal conversion) so inputs match a gallons-based preview exactly.

    ⚠️ This fixture must carry EVERY attribute the extractor touches, including the
    ones a real `ProductionEvent` inherits from `CommonEvent` and never thinks about
    (`history`, `id`). It originally omitted `history`; the extractor raised
    AttributeError, its `except Exception` swallowed that into zero defaults, and the
    suite reported 34.32 vs 85.37 — which reads exactly like the auxiliary-diesel
    regression these tests exist to catch. It was not: the production path was correct
    the whole time. The swallow is gone (it now re-raises), so an incomplete fixture
    fails loudly as AttributeError instead of impersonating a carbon bug.

    `history=None` is the faithful default: the FK is `null=True`, so on a real event
    the attribute EXISTS and is None — it does not raise.
    """

    def __init__(self, **kwargs):
        # Event identity
        self.type = "IR"
        self.id = 1
        # Inherited from CommonEvent — nullable FK, so present-but-None on a real row.
        self.history = None
        # Area / water
        self.area_covered = Decimal("5")
        self.area_unit = "acres"
        self.water_volume_total = Decimal("100000")
        self.water_volume_unit = "gallons"
        self.volume = None
        self.irrigation_depth = None
        self.irrigation_depth_unit = "inches"
        # Fuel (auxiliary diesel reported alongside an electric grid pump)
        self.fuel_consumed = Decimal("5")
        self.fuel_unit = "gal"
        self.fuel_type = "diesel"
        self.energy_source = "grid"
        self.electricity_source = "grid"
        # Irrigation specifics
        self.water_source = None
        self.pump_depth_ft = None
        self.equipment_hours = None
        self.extra_data = {}
        # Allow per-test overrides
        for key, value in kwargs.items():
            setattr(self, key, value)


class IrrigationPreviewSavedParityTestCase(TestCase):
    """IR saved path must match preview path (auxiliary diesel included)."""

    def setUp(self):
        self.calculator = EventCarbonCalculator()
        self.diesel_factor = 10.21  # kg CO2e/gal (EPA 40 CFR Part 98)

    def _preview_co2e(self, **overrides):
        """Replicate the preview entry-point call (carbon/views.py:1291)."""
        params = {
            "production_type": "IR",
            "area_covered": Decimal("5"),
            "fuel_consumed": Decimal("5"),
            "equipment_hours": None,
            "fuel_type": "diesel",
            "energy_source": "grid",
            "electricity_source": "grid",
            "water_volume_gallons": 100000.0,
            "water_source": None,
            "pump_depth_ft": None,
        }
        params.update(overrides)
        result = VerifiedEmissionFactors.calculate_production_event_emissions(**params)
        return float(result["co2e_kg"]), result

    def test_saved_includes_auxiliary_diesel(self):
        """SAVED IR path must add auxiliary diesel (not drop it)."""
        event = _FakeIrrigationEvent()
        saved = self.calculator.calculate_production_event_impact(event)
        saved_co2e = float(saved["co2e"])

        # Auxiliary diesel for 5 gal must be ~51 kg and present in the total.
        aux_expected = 5 * self.diesel_factor  # 51.05 kg CO2e
        self.assertGreaterEqual(
            saved_co2e,
            aux_expected,
            f"Saved IR CO2e {saved_co2e} dropped auxiliary diesel " f"(expected >= {aux_expected} kg from 5 gal).",
        )
        # Breakdown must explicitly record the auxiliary diesel line.
        breakdown = saved.get("breakdown", {})
        self.assertIn(
            "auxiliary_diesel_emissions_kg",
            breakdown,
            "Saved IR breakdown is missing auxiliary_diesel_emissions_kg.",
        )

    def test_preview_equals_saved(self):
        """Same IR event -> identical CO2e on preview and saved paths."""
        event = _FakeIrrigationEvent()
        saved = self.calculator.calculate_production_event_impact(event)
        saved_co2e = float(saved["co2e"])

        preview_co2e, _ = self._preview_co2e()

        self.assertAlmostEqual(
            saved_co2e,
            preview_co2e,
            places=2,
            msg=(
                f"Preview ({preview_co2e}) != Saved ({saved_co2e}) for the same "
                f"IR event. Auxiliary diesel must be summed identically."
            ),
        )

    def test_preview_equals_saved_diesel_pump(self):
        """Diesel pump (no electricity_source) -> preview == saved, fuel honored."""
        event = _FakeIrrigationEvent(electricity_source=None)
        saved = self.calculator.calculate_production_event_impact(event)
        saved_co2e = float(saved["co2e"])

        preview_co2e, _ = self._preview_co2e(electricity_source=None)

        # Pure diesel pump: 5 gal * 10.21 = 51.05 kg
        self.assertAlmostEqual(saved_co2e, 5 * self.diesel_factor, places=2)
        self.assertAlmostEqual(saved_co2e, preview_co2e, places=2)

    def test_extraction_failure_raises_instead_of_returning_zeros(self):
        """A broken event must NOT yield a plausible carbon number.

        `_extract_production_event_data` used to catch every exception and return
        `area_covered=0.0, fuel_consumed=None, water_volume_gallons=None`. The caller
        carried on and produced a figure from those zeros that was indistinguishable, in
        the wizard and in the certifier packet, from a real calculation. Nothing in the
        result said it came from a failure.

        Now it propagates, and `calculate_production_event_impact` converts it into an
        explicitly-marked error result — which a surface can refuse to display.
        """

        class _BrokenEvent(_FakeIrrigationEvent):
            # Raise on READ only. A `@property` would also intercept the parent
            # __init__'s `self.history = None` assignment and blow up in the
            # constructor, before the code under test ever runs.
            def __getattribute__(self, name):
                if name == "history":
                    raise RuntimeError("simulated DB/attribute failure during extraction")
                return super().__getattribute__(name)

        with self.assertRaises(RuntimeError):
            self.calculator._extract_production_event_data(_BrokenEvent())

        # And the public entry point marks it rather than fabricating a clean number.
        result = self.calculator.calculate_production_event_impact(_BrokenEvent())
        self.assertEqual(result["verification_status"], "error")
        self.assertEqual(result["calculation_method"], "calculation_error")
        self.assertIn("error", result)
