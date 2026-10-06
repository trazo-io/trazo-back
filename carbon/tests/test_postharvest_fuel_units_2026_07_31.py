"""Post-harvest fuel accounting regression tests (2026-07-31 pilot QA pass).

Driving a real CA organic walnut season through the UI produced a hulling+drying
event for 153,000 lb of nuts that reported **1.18 kg CO2e**. Two independent
defects stacked:

1. A double litres->gallons conversion (`_extract_production_event_data` already
   normalised to gallons, then `_calculate_postharvest_emissions` forwarded the
   stale "L" unit so it was divided by 3.78541 again) — 3.79x under-report.
2. The EPA natural-gas factor is per STANDARD CUBIC FOOT (0.0544 kg CO2/scf) but
   was multiplied by a gallon count, and the fuel-unit dropdown offered no gas
   unit at all, so a gas-fired dryer could not be recorded correctly.

Post-harvest drying is the largest single post-harvest energy use for tree nuts,
and this figure reaches both the certifier packet and the consumer QR page.
"""

from django.test import SimpleTestCase

from carbon.services.verified_emission_factors import VerifiedEmissionFactors as VEF


class GasQuantityConversionTests(SimpleTestCase):
    def test_scf_is_identity(self):
        scf, err = VEF.gas_quantity_to_scf(1000, "scf")
        self.assertIsNone(err)
        self.assertAlmostEqual(scf, 1000.0)

    def test_ccf_is_one_hundred_cubic_feet(self):
        scf, err = VEF.gas_quantity_to_scf(10, "ccf")
        self.assertIsNone(err)
        self.assertAlmostEqual(scf, 1000.0)

    def test_therm_uses_the_epa_heat_content(self):
        # 1 therm = 100,000 Btu; EPA Table C-1 natural gas = 0.001026 mmBtu/scf
        # => 1,026 Btu/scf => 97.466 scf per therm.
        scf, err = VEF.gas_quantity_to_scf(1, "therm")
        self.assertIsNone(err)
        self.assertAlmostEqual(scf, 97.466, places=2)

    def test_cubic_metres_convert(self):
        scf, err = VEF.gas_quantity_to_scf(1, "m3")
        self.assertIsNone(err)
        self.assertAlmostEqual(scf, 35.3147, places=3)

    def test_unit_lookup_is_case_insensitive(self):
        self.assertEqual(VEF.gas_quantity_to_scf(1, "THERM")[0], VEF.gas_quantity_to_scf(1, "therm")[0])
        self.assertEqual(VEF.gas_quantity_to_scf(2, "MMBtu")[0], VEF.gas_quantity_to_scf(2, "mmbtu")[0])

    def test_liquid_units_are_refused_not_silently_converted(self):
        # This is the actual pilot input: the form defaulted fuel_unit to "L".
        scf, err = VEF.gas_quantity_to_scf(310, "L")
        self.assertIsNone(scf)
        self.assertIn("cannot describe a gas volume", err)

    def test_gallons_are_refused_too(self):
        scf, err = VEF.gas_quantity_to_scf(310, "gal")
        self.assertIsNone(scf)
        self.assertIsNotNone(err)


class PostHarvestEmissionTests(SimpleTestCase):
    def _calc(self, **kw):
        return VEF.calculate_production_event_emissions(production_type="PH", area_covered=42.5, **kw)

    def test_diesel_gallons_are_not_converted_twice(self):
        # The caller normalises to gallons and now says so. 100 gal diesel must be
        # 100 * 10.21, not (100 / 3.78541) * 10.21 = 269.7.
        res = self._calc(fuel_consumed=100, fuel_type="diesel", fuel_unit="gal")
        self.assertAlmostEqual(res["co2e_kg"], 1021.0, places=1)

    def test_litres_still_convert_once_when_the_unit_says_litres(self):
        res = self._calc(fuel_consumed=378.541, fuel_type="diesel", fuel_unit="L")
        self.assertAlmostEqual(res["co2e_kg"], 1021.0, places=1)

    def test_natural_gas_in_therms_is_costed_on_the_scf_basis(self):
        # 1,000 therms = 97,466 scf * 0.0544 kg/scf = 5,302 kg CO2e — the right order
        # of magnitude for drying a walnut crop, vs the 1.18 kg the bug produced.
        res = self._calc(fuel_consumed=1000, fuel_type="natural_gas", fuel_unit="therm")
        self.assertAlmostEqual(res["co2e_kg"], 5302.2, delta=2.0)
        self.assertIn("fuel_emission_factor_kg_per_scf", res["breakdown"])
        # It must never be labelled per-gallon again.
        self.assertNotIn("fuel_emission_factor_kg_per_gallon", res["breakdown"])

    def test_natural_gas_in_litres_reports_zero_and_says_why(self):
        # Silence is not acceptable: refusing to count it is correct, but the
        # limitation has to be visible or the packet reads as "drying was clean".
        res = self._calc(fuel_consumed=310, fuel_type="natural_gas", fuel_unit="L")
        self.assertEqual(res["breakdown"]["fuel_kg_co2e"], 0.0)
        self.assertIn("fuel_unit_error", res["breakdown"])
        self.assertIn("Fuel NOT counted", res["limitations"])

    def test_no_energy_reported_is_not_estimated(self):
        # Run 8 (R8-04): was "reported as no data" with 0.0. Unknown is not zero: the result is
        # not_estimated, which the signal stores as a status with no figure.
        res = self._calc(fuel_consumed=None)
        self.assertTrue(res.get("not_estimated"))
        self.assertEqual(res["calculation_method"], "not_estimated")


class GasUnitBasisAcrossAllProductionPathsTests(SimpleTestCase):
    """The scf-as-gallons mistake was replicated at EIGHT call sites, not one.

    The original fix only corrected the post-harvest branch. Harvesting, planting,
    transplanting, general, thinning, manual-operation and cultivation each carried an
    identical `co2e_kg = fuel_consumed * fuel_factor.value` line, plus the aggregate
    (summary-mode) path in EventCarbonCalculator. All now route through
    `VerifiedEmissionFactors.fuel_co2e`.
    """

    # production_type strings accepted by calculate_production_event_emissions
    PATHS = ["HA", "PL", "TR", "TH", "CU", "PH", "general production"]

    def test_therms_are_costed_on_the_scf_basis_on_every_path(self):
        for ptype in self.PATHS:
            res = VEF.calculate_production_event_emissions(
                production_type=ptype,
                area_covered=42.5,
                fuel_consumed=1000,
                fuel_type="natural_gas",
                fuel_unit="therm",
            )
            # 1,000 therms = 97,466 scf x 0.0544 = 5,302 kg. The bug produced 54.4.
            self.assertGreater(res["co2e_kg"], 5000, f"{ptype} still under-reporting natural gas: {res['co2e_kg']}")

    def test_a_gas_reported_in_gallons_is_never_silently_costed(self):
        for ptype in self.PATHS:
            res = VEF.calculate_production_event_emissions(
                production_type=ptype,
                area_covered=42.5,
                fuel_consumed=310,
                fuel_type="natural_gas",
                fuel_unit="gal",
            )
            # 310 gal x 0.0544 = 16.9 kg was the fabricated figure. Refusing yields 0.
            self.assertLess(res["co2e_kg"], 1.0, f"{ptype} fabricated a gas figure from gallons: {res['co2e_kg']}")

    def test_diesel_is_unaffected_by_the_gas_handling(self):
        for ptype in self.PATHS:
            res = VEF.calculate_production_event_emissions(
                production_type=ptype,
                area_covered=42.5,
                fuel_consumed=100,
                fuel_type="diesel",
                fuel_unit="gal",
            )
            self.assertAlmostEqual(res["co2e_kg"], 1021.0, delta=1.0, msg=ptype)

    def test_fuel_co2e_choke_point_contract(self):
        co2e, factor, err = VEF.fuel_co2e(100, "diesel", "gal")
        self.assertAlmostEqual(co2e, 1021.0, places=1)
        self.assertIsNone(err)
        co2e, factor, err = VEF.fuel_co2e(1000, "natural_gas", "therm")
        self.assertAlmostEqual(co2e, 5302.2, delta=2.0)
        self.assertIsNone(err)
        co2e, factor, err = VEF.fuel_co2e(310, "natural_gas", "L")
        self.assertEqual(co2e, 0.0)
        self.assertIsNotNone(err)
        # A missing quantity is not an error, just nothing to count.
        co2e, factor, err = VEF.fuel_co2e(None, "diesel", "gal")
        self.assertEqual(co2e, 0.0)
        self.assertIsNone(err)


class AggregateSummaryModeGasTests(SimpleTestCase):
    """Summary/aggregate events (a season of dryer runs logged as one) shared the bug."""

    def test_aggregate_natural_gas_uses_the_scf_basis(self):
        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        calc = EventCarbonCalculator()
        co2e = calc._calculate_aggregate_fuel_emissions(1000, "natural_gas", "therm")
        self.assertAlmostEqual(co2e, 5302.2, delta=2.0)

    def test_aggregate_diesel_still_converts_litres_once(self):
        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        calc = EventCarbonCalculator()
        self.assertAlmostEqual(calc._calculate_aggregate_fuel_emissions(378.541, "diesel", "L"), 1021.0, delta=1.0)
        self.assertAlmostEqual(calc._calculate_aggregate_fuel_emissions(100, "diesel", "gal"), 1021.0, delta=1.0)


class MeasuredFuelIsNeverSilentlyCappedTests(SimpleTestCase):
    """A grower's measured fuel must reach the packet unmodified.

    Every production branch documents the same posture — "farmers provide measured values
    that should be trusted, not capped" — but cultivation was the one path that never set
    `skip_validation`, so `_validate_production_emissions` rewrote 100 measured gallons
    (1021 kg) down to 859.96 kg with reason "Exceeded realistic cultivation emissions
    range". Silently reporting LESS than the farmer measured is still fabrication.
    """

    MEASURED_PATHS = ["HA", "PL", "TR", "TH", "CU", "general production"]

    def test_measured_diesel_is_reported_exactly(self):
        for ptype in self.MEASURED_PATHS:
            res = VEF.calculate_production_event_emissions(
                production_type=ptype,
                area_covered=42.5,
                fuel_consumed=100,
                fuel_type="diesel",
                fuel_unit="gal",
            )
            self.assertAlmostEqual(
                res["co2e_kg"],
                1021.0,
                delta=1.0,
                msg=f"{ptype} altered the farmer's measured fuel: {res['co2e_kg']}",
            )
            self.assertNotIn(
                "corrected_result_kg",
                res["breakdown"],
                f"{ptype} silently corrected a measured value",
            )

    def test_usda_estimate_path_still_validates(self):
        # With no measured fuel, the per-hectare estimate SHOULD still be sanity-checked —
        # the guard must not disable validation wholesale.
        res = VEF.calculate_production_event_emissions(production_type="CU", area_covered=42.5, fuel_consumed=None)
        self.assertEqual(res["breakdown"]["calculation_basis"], "usda_standard_per_hectare")
        self.assertGreater(res["co2e_kg"], 0)
