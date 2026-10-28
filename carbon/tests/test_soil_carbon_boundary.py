"""What a soil record may add to the carbon figure (Astra follow-up 2026-10-28, Part B1).

Tillage: no soil CO2 flux term. The calculator charged 50/150/300 kg CO2e per hectare per pass by
depth, and a missing depth read as "medium", so one acre of tillage with nothing but an area on it
showed 61 kg. The cited sources do not support a per-pass factor: Reicosky, Dugas & Torbert 1997
is a 24-hour post-tillage pulse on one Texas vertisol; West & Post 2002 and IPCC 2019 Vol 4 Ch 5
are multi-year soil stock change (20-year default period); Lal 2004 is farm-operation energy, which
recorded fuel already counts. Oscar's decision: remove it. Tillage counts recorded fuel, plus the
1.2 kg/ha operation default, which stays labelled `area_estimate` when it stands alone.

Lime: IPCC 2006 Vol 4 Ch 11 section 11.3 (Eq. 11.12) applies carbonate factors to limestone
(0.12 t C/t) and dolomite (0.13 t C/t), on the annual applied mass. It counts only when the record
names a carbonate material AND carries the applied quantity. Quicklime (CaO) and hydrated lime
(Ca(OH)2) are not carbonates; IPCC treats them separately, so they get no carbonate factor.
"""

from decimal import Decimal

from django.test import SimpleTestCase

from carbon.services.emission_factors import EmissionFactorsRegistry
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from history.models import SoilManagementEvent

ONE_ACRE_HA = 0.404686


def _soil(subtype, **fields):
    """An unsaved soil record: the calculator only reads attributes."""
    fields.setdefault("area_covered", Decimal("1"))
    fields.setdefault("area_unit", "acres")
    event = SoilManagementEvent(type=subtype, **fields)
    event.extra_data = {}
    return event


def _calc(event):
    return EventCarbonCalculator().calculate_soil_management_event_impact(event)


class TillageCarriesNoSoilFluxTerm(SimpleTestCase):
    def assertNoFluxAnywhere(self, result):
        self.assertNotIn("soil_flux_emissions", result["breakdown"])
        self.assertNotIn("soil_flux_emissions", result["calculation_details"])
        self.assertNotIn("tillage_soil_flux_details", result)
        self.assertNotIn("flux", result["calculation_method"])
        self.assertNotIn("Soil Flux", result["calculation_details"]["calculation"])
        self.assertNotIn("Reicosky", result["data_source"])

    def test_tillage_with_no_fuel_and_no_depth_is_only_the_area_default(self):
        """Astra's 'tillage post-fix test': 1 acre, no depth, no fuel showed 61 kg."""
        result = _calc(_soil("TI"))
        self.assertAlmostEqual(result["co2e"], 1.2 * ONE_ACRE_HA, places=2)
        self.assertNoFluxAnywhere(result)
        self.assertEqual(result["verification_status"], "area_estimate")
        self.assertFalse(result["usda_factors_based"])

    def test_a_recorded_depth_adds_nothing_either(self):
        """Depth used to pick 50/150/300 kg/ha. With the term gone, depth changes nothing."""
        shallow = _calc(_soil("TI", working_depth=Decimal("2"), depth_unit="in", description="Cultivator pass"))
        deep = _calc(_soil("TI", working_depth=Decimal("14"), depth_unit="in", description="Deep moldboard plow"))
        for result in (shallow, deep):
            self.assertAlmostEqual(result["co2e"], 1.2 * ONE_ACRE_HA, places=2)
            self.assertNoFluxAnywhere(result)

    def test_tillage_with_recorded_fuel_counts_the_fuel_and_no_flux(self):
        result = _calc(_soil("TI", fuel_consumed=Decimal("3"), fuel_unit="gal", fuel_type="diesel"))
        fuel = result["breakdown"]["fuel_emissions"]
        self.assertAlmostEqual(fuel, 3 * 10.21, delta=0.5)
        self.assertAlmostEqual(result["co2e"], fuel + 1.2 * ONE_ACRE_HA, places=2)
        self.assertNoFluxAnywhere(result)
        self.assertNotEqual(result["verification_status"], "area_estimate")

    def test_no_caller_can_reach_a_flux_factor(self):
        self.assertNotIn("tillage_soil_flux", EmissionFactorsRegistry.SOIL_MANAGEMENT_FACTORS)
        self.assertFalse(hasattr(EmissionFactorsRegistry, "get_tillage_soil_flux_factor"))
        self.assertFalse(hasattr(EventCarbonCalculator, "_detect_tillage_depth"))
        notes = EmissionFactorsRegistry.SOIL_MANAGEMENT_FACTORS["tillage"]["notes"]
        self.assertNotIn("FLUX", notes.upper())


def _pa(**fields):
    return _calc(_soil("PA", **fields))


class LimeNeedsACarbonateMaterialAndAnAmount(SimpleTestCase):
    def test_either_half_missing_produces_no_lime_term(self):
        """The old detector defaulted an unnamed material to limestone."""
        for fields in (
            {"amendment_type": "limestone"},
            {"amendment_amount": "1000 kg"},
            {"amendment_amount": "1000", "amendment_amount_numeric": Decimal("1000"), "amendment_amount_unit": "kg"},
            {"amendment_type": "other", "amendment_amount": "1000 kg"},
            {"amendment_type": "compost", "amendment_amount": "1000 kg"},
        ):
            with self.subTest(**{k: str(v) for k, v in fields.items()}):
                result = _pa(**fields)
                self.assertEqual(result["breakdown"]["lime_dissolution_emissions"], 0)
                self.assertNotIn("lime_dissolution_details", result)

    def test_quicklime_and_hydrated_lime_get_no_carbonate_factor(self):
        for fields in (
            {"amendment_type": "calcium_oxide"},
            {"amendment_type": "calcium_hydroxide"},
            {"amendment_type": "other", "amendment_product_name": "Hydrated lime 50 lb bag"},
            {"amendment_type": "other", "amendment_product_name": "Quicklime"},
            {"amendment_type": "other", "amendment_product_name": "Dolomitic hydrated lime"},
        ):
            with self.subTest(**fields):
                result = _pa(amendment_amount="1000 kg", **fields)
                self.assertEqual(result["breakdown"]["lime_dissolution_emissions"], 0)
                self.assertNotIn("lime_dissolution_details", result)

    def test_the_registry_refuses_a_non_carbonate_lime_type(self):
        """It used to fall back to limestone for any name it did not know."""
        with self.assertRaises(ValueError):
            EmissionFactorsRegistry.get_lime_dissolution_factor("quicklime")

    def test_limestone_and_dolomite_with_an_amount_are_counted_and_disclosed(self):
        cases = (
            ({"amendment_type": "limestone"}, 0.44),
            ({"amendment_type": "dolomite"}, 0.477),
            ({"amendment_type": "other", "amendment_product_name": "Ag lime, calcitic"}, 0.44),
        )
        for fields, factor in cases:
            with self.subTest(**fields):
                result = _pa(
                    amendment_amount="1000",
                    amendment_amount_numeric=Decimal("1000"),
                    amendment_amount_unit="kg",
                    **fields,
                )
                self.assertAlmostEqual(result["breakdown"]["lime_dissolution_emissions"], 1000 * factor, places=1)
                details = result["lime_dissolution_details"]
                self.assertEqual(details.get("calculation_basis"), "IPCC 2006 Tier 1, assigned to application year")
                self.assertIn("not a measured release", details.get("note", ""))
                self.assertEqual(
                    result["breakdown"].get("lime_calculation_basis"), "IPCC 2006 Tier 1, assigned to application year"
                )

    def test_a_structured_amount_alone_is_enough_quantity(self):
        """The legacy string column used to gate the branch even when the numeric pair was set."""
        result = _pa(amendment_type="limestone", amendment_amount_numeric=Decimal("500"), amendment_amount_unit="kg")
        self.assertAlmostEqual(result["breakdown"]["lime_dissolution_emissions"], 220.0, places=1)
