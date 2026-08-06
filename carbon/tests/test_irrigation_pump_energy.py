"""
Phase 3 / A1 — irrigation pump energy must be physically defensible.

The previous implementation used `pump_depth_ft * 0.0175 kWh/1000 gal`, labelled a
"USDA NRCS standard pump curve". Two problems:

  * The label was fabricated. NRCS publishes no such curve, and `compliance.md` forbids
    unsourced attributions.
  * The coefficient was ~3.9x too high. At a 120 ft lift it produced 684 kWh/acre-foot;
    CPUC's California groundwater study reports ~175 kWh/acre-foot for a 120 ft well, and
    the statewide range is 170-600.

Irrigation is the largest energy line in a California orchard and kWh/acre-foot is a number
a grower can read off their own utility bill, so this was both the biggest and the most
easily falsified figure in the product.

The subtlest part is the INCENTIVE: supplying a measured pump depth could make a farmer's
number WORSE than recording nothing, which inverts transparency-first.
`test_supplying_depth_never_penalises_a_shallow_well` pins that down — the arithmetic tests
alone would not catch a regression that merely re-scaled the coefficient.

Fixing the depth formula then exposed a larger, adjacent error that the static
`water_source` factors were hiding: `well_groundwater` at 3.5 kWh/1000 gal was 1,140
kWh/acre-foot and the no-source default at 2.0 was 652 — both above California's published
maximum, and both applied far more often than a measured pump depth, since most events record
a water source and few record a depth. Those are corrected in
`WaterSourceFactorPlausibilityTests` below.
"""

from django.test import TestCase

from carbon.services.verified_emission_factors import VerifiedEmissionFactors as VEF

GALLONS_PER_ACRE_FOOT = 325_851.0

# CPUC / California Energy Commission groundwater-pumping studies.
CA_MIN_KWH_PER_ACRE_FOOT = 170.0
CA_MAX_KWH_PER_ACRE_FOOT = 600.0


def kwh_per_acre_foot(result):
    """Convert a calculation result's pump factor into kWh per acre-foot."""
    per_1000gal = result["breakdown"]["pump_efficiency_kwh_per_1000_gallons"]
    return per_1000gal * (GALLONS_PER_ACRE_FOOT / 1000.0)


class IrrigationPumpEnergyTests(TestCase):
    def _irrigate(self, **kwargs):
        kwargs.setdefault("water_volume_gallons", GALLONS_PER_ACRE_FOOT)
        return VEF.calculate_drought_irrigation_emissions(**kwargs)

    # ---- Physical plausibility -------------------------------------------

    def test_typical_california_well_lands_in_the_published_range(self):
        result = self._irrigate(pump_depth_ft=120, irrigation_method="drip")
        value = kwh_per_acre_foot(result)
        self.assertGreater(value, CA_MIN_KWH_PER_ACRE_FOOT)
        self.assertLess(value, CA_MAX_KWH_PER_ACRE_FOOT)

    def test_the_old_coefficient_would_now_fail_this_range(self):
        """Pins the magnitude of the bug so a re-introduction is caught, not just its shape."""
        old_kwh_per_acre_foot = (120 * 0.0175) * (GALLONS_PER_ACRE_FOOT / 1000.0)
        self.assertGreater(old_kwh_per_acre_foot, CA_MAX_KWH_PER_ACRE_FOOT)
        self.assertLess(kwh_per_acre_foot(self._irrigate(pump_depth_ft=120)), old_kwh_per_acre_foot / 2)

    def test_deep_and_shallow_wells_both_stay_plausible(self):
        for depth in (40, 75, 120, 200, 300):
            value = kwh_per_acre_foot(self._irrigate(pump_depth_ft=depth, irrigation_method="drip"))
            self.assertGreater(value, 50, f"{depth} ft implausibly low")
            self.assertLess(value, 900, f"{depth} ft implausibly high")

    def test_energy_rises_monotonically_with_lift(self):
        values = [kwh_per_acre_foot(self._irrigate(pump_depth_ft=d)) for d in (40, 80, 160, 320)]
        self.assertEqual(values, sorted(values))

    # ---- The incentive invariant (the actual defect) ----------------------

    def test_supplying_depth_never_penalises_a_shallow_well(self):
        """Extra information must not make a farmer's number worse.

        A shallow well pumped through drip should come out at or below the generic
        no-depth default. Under the old coefficient a 75 ft well reported ~428
        kWh/acre-foot against a 277 default — so recording the pump test raised the
        farmer's reported emissions by half again.
        """
        default = kwh_per_acre_foot(self._irrigate(water_source=None))
        measured = kwh_per_acre_foot(self._irrigate(pump_depth_ft=75, irrigation_method="drip"))
        self.assertLessEqual(
            measured,
            default,
            "supplying a measured shallow pump depth produced a HIGHER figure than the "
            "generic default — the transparency-first incentive is inverted again",
        )

    # ---- Total dynamic head components ----------------------------------

    def test_pressurised_methods_cost_more_than_flood(self):
        flood = kwh_per_acre_foot(self._irrigate(pump_depth_ft=100, irrigation_method="flood"))
        drip = kwh_per_acre_foot(self._irrigate(pump_depth_ft=100, irrigation_method="drip"))
        sprinkler = kwh_per_acre_foot(self._irrigate(pump_depth_ft=100, irrigation_method="sprinkler"))
        self.assertLess(flood, drip)
        self.assertLess(drip, sprinkler)

    def test_a_measured_pump_efficiency_is_honoured(self):
        efficient = kwh_per_acre_foot(self._irrigate(pump_depth_ft=100, pump_efficiency=0.80))
        neglected = kwh_per_acre_foot(self._irrigate(pump_depth_ft=100, pump_efficiency=0.45))
        self.assertLess(efficient, neglected)

    def test_absurd_efficiency_values_are_clamped(self):
        # A bad parcel attribute must not drive emissions to zero or to the moon.
        for bad in (0.0, -1.0, 0.01, 5.0, 100.0):
            value = kwh_per_acre_foot(self._irrigate(pump_depth_ft=100, pump_efficiency=bad))
            self.assertGreater(value, 0)
            self.assertLess(value, 1500)

    def test_explicit_pressure_overrides_the_method_default(self):
        detail = self._irrigate(pump_depth_ft=100, irrigation_method="drip", system_pressure_psi=60)["breakdown"]
        self.assertEqual(detail["system_pressure_psi"], 60)

    # ---- Provenance -----------------------------------------------------

    def test_the_fabricated_usda_nrcs_attribution_is_gone(self):
        result = self._irrigate(pump_depth_ft=120)
        provenance = " ".join(result["data_sources"]) + " " + str(result.get("limitations", ""))
        self.assertNotIn("NRCS standard pump curve", provenance)
        self.assertIn("1.0241", provenance)

    def test_breakdown_exposes_the_head_build_up(self):
        breakdown = self._irrigate(pump_depth_ft=120, irrigation_method="drip")["breakdown"]
        for key in (
            "kwh_per_acre_foot",
            "total_dynamic_head_ft",
            "pumping_plant_efficiency",
            "system_pressure_psi",
        ):
            self.assertIn(key, breakdown, f"{key} missing — a grower cannot reconcile the figure")
        # 120 ft lift + 15 psi drip (~35 ft) — the pressure head must actually be included.
        self.assertGreater(breakdown["total_dynamic_head_ft"], 120)

    # ---- Unchanged paths -------------------------------------------------

    def test_water_source_lookup_is_untouched_when_no_depth_given(self):
        result = self._irrigate(water_source="municipal")
        self.assertAlmostEqual(result["breakdown"]["pump_efficiency_kwh_per_1000_gallons"], 0.20, places=3)

    def test_emissions_scale_with_volume(self):
        one = self._irrigate(water_volume_gallons=GALLONS_PER_ACRE_FOOT, pump_depth_ft=120)["co2e_kg"]
        two = self._irrigate(water_volume_gallons=2 * GALLONS_PER_ACRE_FOOT, pump_depth_ft=120)["co2e_kg"]
        self.assertAlmostEqual(two, one * 2, delta=one * 0.01)

    def test_solar_pump_emits_far_less_than_grid(self):
        grid = self._irrigate(pump_depth_ft=120)["co2e_kg"]
        solar = self._irrigate(pump_depth_ft=120, electricity_source="solar")["co2e_kg"]
        self.assertLess(solar, grid)


class WaterSourceFactorPlausibilityTests(TestCase):
    """The static water_source factors are hit far more often than a measured pump depth.

    Fixing only the depth formula left two of them out of range: well_groundwater at 1,140
    kWh/acre-foot (nearly double California's published maximum) and the no-source default at
    652. Groundwater is what a California orchard actually uses, so that was the most
    frequently applied wrong number in the model — a bigger practical error than the
    depth-based one that prompted this work, and only visible once the depth path was correct
    enough to compare against.
    """

    def _kwh_per_acre_foot(self, factor_value):
        return factor_value * (GALLONS_PER_ACRE_FOOT / 1000.0)

    def test_lift_driven_sources_sit_inside_the_published_california_range(self):
        for source in ("well_groundwater", "river_stream", "irrigation_canal", "pond_reservoir"):
            value = self._kwh_per_acre_foot(VEF.IRRIGATION_PUMP_FACTORS[source].value)
            self.assertLess(
                value,
                CA_MAX_KWH_PER_ACRE_FOOT,
                f"{source} = {value:.0f} kWh/acre-foot exceeds the published CA maximum",
            )
            self.assertGreater(value, 20, f"{source} implausibly low")

    def test_pre_pressurised_sources_may_be_below_the_range(self):
        # Municipal / reclaimed / rainwater are not lift-driven — the utility already did the
        # pumping — so a low figure is correct, not a bug.
        for source in ("municipal", "recycled_water", "rainwater_harvesting"):
            value = self._kwh_per_acre_foot(VEF.IRRIGATION_PUMP_FACTORS[source].value)
            self.assertLess(value, CA_MIN_KWH_PER_ACRE_FOOT)
            self.assertGreater(value, 0)

    def test_unknown_source_default_is_not_punitive(self):
        default = self._kwh_per_acre_foot(VEF.IRRIGATION_PUMP_DEFAULT.value)
        self.assertGreater(default, CA_MIN_KWH_PER_ACRE_FOOT)
        self.assertLess(default, CA_MAX_KWH_PER_ACRE_FOOT)

    def test_groundwater_is_the_most_expensive_on_farm_source(self):
        """Ordering sanity: lifting from a deep well beats every surface or supplied option."""
        groundwater = VEF.IRRIGATION_PUMP_FACTORS["well_groundwater"].value
        for cheaper in ("river_stream", "irrigation_canal", "pond_reservoir", "municipal"):
            self.assertGreater(groundwater, VEF.IRRIGATION_PUMP_FACTORS[cheaper].value)

    def test_corrected_factors_no_longer_claim_an_unverifiable_nrcs_guideline(self):
        # These two values are now derived from the pumping-energy equation, so their stated
        # provenance has to say that rather than cite a guideline document for a number that
        # does not come from it.
        for factor in (VEF.IRRIGATION_PUMP_FACTORS["well_groundwater"], VEF.IRRIGATION_PUMP_DEFAULT):
            self.assertIn("1.0241", factor.source)
            self.assertNotIn("NRCS", factor.source)
