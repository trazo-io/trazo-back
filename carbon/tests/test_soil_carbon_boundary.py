"""What a soil record may add to the carbon figure (Astra follow-up 2026-10-28, Part B1).

Tillage: no soil CO2 flux term. The calculator charged 50/150/300 kg CO2e per hectare per pass by
depth, and a missing depth read as "medium", so one acre of tillage with nothing but an area on it
showed 61 kg. The cited sources do not support a per-pass factor: Reicosky, Dugas & Torbert 1997
is a 24-hour post-tillage pulse on one Texas vertisol; West & Post 2002 and IPCC 2019 Vol 4 Ch 5
are multi-year soil stock change (20-year default period); Lal 2004 is farm-operation energy, which
recorded fuel already counts. Oscar's decision: remove it. Tillage counts recorded fuel; with no
fuel recorded it uses the production cultivation diesel estimate (3.2 gal/ha, a published Trazo
estimate), labelled `area_estimate`. The soil table's 1.2 kg/ha default was unsourced and ~25x
below that factor (review on landing #35).

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
# Tillage with no fuel: the production cultivation diesel estimate, 3.2 gal/ha x 10.21 kg/gal.
TILLAGE_KG_PER_HA = 3.2 * 10.21


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
        self.assertAlmostEqual(result["co2e"], TILLAGE_KG_PER_HA * ONE_ACRE_HA, places=2)
        self.assertNoFluxAnywhere(result)
        self.assertEqual(result["verification_status"], "area_estimate")
        self.assertFalse(result["usda_factors_based"])

    def test_a_recorded_depth_adds_nothing_either(self):
        """Depth used to pick 50/150/300 kg/ha. With the term gone, depth changes nothing."""
        shallow = _calc(_soil("TI", working_depth=Decimal("2"), depth_unit="in", description="Cultivator pass"))
        deep = _calc(_soil("TI", working_depth=Decimal("14"), depth_unit="in", description="Deep moldboard plow"))
        for result in (shallow, deep):
            self.assertAlmostEqual(result["co2e"], TILLAGE_KG_PER_HA * ONE_ACRE_HA, places=2)
            self.assertNoFluxAnywhere(result)

    def test_tillage_with_recorded_fuel_counts_the_fuel_and_no_flux(self):
        result = _calc(_soil("TI", fuel_consumed=Decimal("3"), fuel_unit="gal", fuel_type="diesel"))
        fuel = result["breakdown"]["fuel_emissions"]
        self.assertAlmostEqual(fuel, 3 * 10.21, delta=0.5)
        self.assertAlmostEqual(result["co2e"], fuel, places=3)
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


class RecordedFuelReplacesTheOperationDefault(SimpleTestCase):
    """The tillage area estimate (cultivation diesel per hectare) and the pH adjustment default
    stand in for the operation's equipment fuel. With the fuel recorded, adding them again counted the
    same diesel twice. Lime and amendment N2O are not fuel and stay additive."""

    def test_tillage_with_ten_gallons_on_ten_hectares_is_the_fuel_only(self):
        result = _calc(
            _soil(
                "TI",
                area_covered=Decimal("10"),
                area_unit="hectares",
                fuel_consumed=Decimal("10"),
                fuel_unit="gal",
                fuel_type="diesel",
            )
        )
        self.assertAlmostEqual(result["breakdown"]["fuel_emissions"], 102.1, places=1)
        self.assertEqual(result["breakdown"]["area_emissions"], 0)
        self.assertAlmostEqual(result["co2e"], result["breakdown"]["fuel_emissions"], places=3)
        self.assertNotEqual(result["verification_status"], "area_estimate")
        self.assertNotIn("Area:", result["calculation_details"]["calculation"])

    def test_ph_adjustment_with_fuel_and_lime_is_fuel_plus_lime(self):
        result = _calc(
            _soil(
                "PA",
                area_covered=Decimal("10"),
                area_unit="hectares",
                fuel_consumed=Decimal("2"),
                fuel_unit="gal",
                fuel_type="diesel",
                amendment_type="limestone",
                amendment_amount="1000",
                amendment_amount_numeric=Decimal("1000"),
                amendment_amount_unit="kg",
            )
        )
        breakdown = result["breakdown"]
        self.assertEqual(
            breakdown["area_emissions"], 0, "the 0.3 kg/ha application default was added on top of the fuel"
        )
        self.assertAlmostEqual(breakdown["lime_dissolution_emissions"], 440.0, places=1)
        self.assertAlmostEqual(result["co2e"], breakdown["fuel_emissions"] + 440.0, places=3)

    def test_without_fuel_the_operation_default_still_stands(self):
        result = _calc(_soil("TI", area_covered=Decimal("10"), area_unit="hectares"))
        self.assertAlmostEqual(result["co2e"], TILLAGE_KG_PER_HA * 10, places=2)
        self.assertEqual(result["verification_status"], "area_estimate")

    def test_a_factor_that_is_not_fuel_stays_additive(self):
        """Grazing's 0.2 kg/ha is soil compaction and disturbance, not equipment energy."""
        result = _calc(
            _soil("GR", area_covered=Decimal("10"), area_unit="hectares", fuel_consumed=Decimal("1"), fuel_unit="gal")
        )
        self.assertAlmostEqual(result["breakdown"]["area_emissions"], 2.0, places=3)
        self.assertAlmostEqual(result["co2e"], result["breakdown"]["fuel_emissions"] + 2.0, places=3)


class NoSoilCarbonCredit(SimpleTestCase):
    """No per-hectare soil-carbon credit (2026-11-11).

    The soil table carried no_till -0.5, cover_crops -0.8, composting -1.0 and organic_matter -0.6
    kg CO2e/ha, impact_type "carbon_sequestration", each sourced to a "USDA-ARS ... Research 2025"
    study no one could find. With fuel or amendment nitrogen also recorded, the credit was netted
    into a figure labelled "from recorded inputs" (24 production rows on 2026-11-11). Soil-carbon
    stock change is excluded until a stock-accounting method exists, the rule the tillage flux
    removal above applied to the positive side.
    """

    def test_no_soil_factor_is_a_credit(self):
        for key, factor in EmissionFactorsRegistry.SOIL_MANAGEMENT_FACTORS.items():
            if not (isinstance(factor, dict) and "value" in factor):
                continue
            with self.subTest(key=key):
                self.assertGreaterEqual(factor["value"], 0)
                self.assertNotEqual(factor.get("impact_type"), "carbon_sequestration")
                if factor["value"] == 0:  # a zero cites the methodology, not a study that was never found
                    self.assertNotIn("USDA-ARS", factor["source"])

    def test_cover_crop_composting_and_organic_matter_count_only_the_fuel(self):
        for subtype in ("CC", "CO", "OM"):
            with self.subTest(subtype=subtype):
                result = _calc(
                    _soil(
                        subtype,
                        area_covered=Decimal("10"),
                        area_unit="hectares",
                        fuel_consumed=Decimal("10"),
                        fuel_unit="gal",
                        fuel_type="diesel",
                    )
                )
                self.assertAlmostEqual(result["breakdown"]["fuel_emissions"], 102.1, places=1)
                self.assertEqual(result["breakdown"]["area_emissions"], 0)
                self.assertAlmostEqual(result["co2e"], result["breakdown"]["fuel_emissions"], places=3)

    def test_with_nothing_recorded_a_cover_crop_has_no_figure(self):
        """An area alone is not an input: no estimate, and never a stored negative."""
        result = _calc(_soil("CC", area_covered=Decimal("10"), area_unit="hectares"))
        self.assertEqual(result["co2e"], 0)
        self.assertEqual(result["verification_status"], "no_factor_applied")
