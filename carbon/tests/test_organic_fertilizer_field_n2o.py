"""Field N2O on organic fertiliser (2026-07-31 CA organic walnut pilot QA).

The fertiliser branch computed `n_kg` and then discarded it for
`is_organic_fertilizer`, charging a flat 0.5 kg CO2e per kg of PRODUCT. Two
consequences, both wrong for an organic-first product:

1. Post-application field N2O — a real, farmer-controlled, in-scope emission —
   was omitted entirely for the ONLY fertiliser path an organic grower uses,
   while the synthetic and slow-release branches carried it inside the 10.5
   kg CO2e/kg N nitrogen factor.
2. Emissions scaled with the WATER in a dilute liquid: applying twice the volume
   of a half-strength product doubled the reported footprint for the same
   delivered nitrogen.

Factor derivation (2019 Refinement to the 2006 IPCC Guidelines, Vol.4 Ch.11):
    direct     EF1                        = 0.010   kg N2O-N/kg N   (Table 11.1)
    volatilised FracGASM 0.21 x EF4 0.010 = 0.0021                  (Table 11.3)
    leached     FracLEACH 0.24 x EF5 0.011= 0.00264                 (Table 11.3)
    total 0.01474 x 44/28 x 265 GWP       = 6.14 kg CO2e/kg N
"""

from django.test import SimpleTestCase

from carbon.services.verified_emission_factors import VerifiedEmissionFactors as VEF


class NitrogenFieldN2OFactorTests(SimpleTestCase):
    def test_factor_matches_the_ipcc_derivation(self):
        n2o_n_per_kg_n = 0.010 + (0.21 * 0.010) + (0.24 * 0.011)
        expected = n2o_n_per_kg_n * (44 / 28) * 265
        self.assertAlmostEqual(VEF.EPA_CHEMICAL_FACTORS["nitrogen_field_n2o"].value, expected, places=2)

    def test_factor_is_per_kg_of_nitrogen_not_per_kg_of_product(self):
        self.assertEqual(VEF.EPA_CHEMICAL_FACTORS["nitrogen_field_n2o"].unit, "kg_CO2e_per_kg_N")

    def test_decomposition_of_the_synthetic_nitrogen_factor_stays_coherent(self):
        # 10.5 (manufacturing + field N2O) minus the field component must leave a
        # plausible manufacturing figure. If someone edits either constant, this fails.
        total = VEF.EPA_CHEMICAL_FACTORS["nitrogen_fertilizer"].value
        field = VEF.EPA_CHEMICAL_FACTORS["nitrogen_field_n2o"].value
        manufacturing = total - field
        self.assertGreater(manufacturing, 1.0)
        self.assertLess(manufacturing, 6.0)


class OrganicFertilizerEmissionTests(SimpleTestCase):
    """The pilot event: 425 gal of Organic Gem fish 3-3-0.3 on 42.5 acres."""

    PILOT_MASS_KG = 2010.9990625  # 425 gal -> 1608.8 L x 1.25 kg/L
    PILOT_N_PCT = 0.03

    def _calc(self, n_percentage=None, chemical_mass_kg=None, chemical_subtype="organic_fertilizer"):
        n = self.PILOT_N_PCT if n_percentage is None else n_percentage
        return VEF.calculate_chemical_application_emissions(
            chemical_type="FE",
            volume_liters=0,
            area_hectares=17.199155,
            npk_content={"N": n * 100, "P": 3.0, "K": 0.3},
            chemical_subtype=chemical_subtype,
            chemical_mass_kg=(self.PILOT_MASS_KG if chemical_mass_kg is None else chemical_mass_kg),
        )

    def test_field_n2o_is_reported_and_non_zero(self):
        res = self._calc()
        b = res["breakdown"]
        self.assertIn("field_n2o_emissions_kg_co2e", b)
        self.assertGreater(b["field_n2o_emissions_kg_co2e"], 0)

    def test_nitrogen_basis_is_visible_in_the_breakdown(self):
        # The applied N used to be invisible in the audit trail for organic inputs.
        b = self._calc()["breakdown"]
        self.assertAlmostEqual(b["nitrogen_kg"], self.PILOT_MASS_KG * self.PILOT_N_PCT, places=2)

    def test_total_is_processing_plus_field_n2o(self):
        b = self._calc()["breakdown"]
        self.assertAlmostEqual(
            b["product_emissions_kg_co2e"],
            b["processing_emissions_kg_co2e"] + b["field_n2o_emissions_kg_co2e"],
            places=1,
        )

    def test_pilot_event_numbers(self):
        b = self._calc()["breakdown"]
        # 2011 kg product x 0.5 = 1005.5 processing
        self.assertAlmostEqual(b["processing_emissions_kg_co2e"], 1005.5, delta=0.5)
        # 60.33 kg N x 6.14 = 370.4 field N2O — previously reported as zero.
        self.assertAlmostEqual(b["field_n2o_emissions_kg_co2e"], 370.4, delta=1.0)

    def test_zero_nitrogen_product_adds_no_field_n2o(self):
        # A K-only or micronutrient organic input must not be charged nitrogen N2O.
        b = self._calc(n_percentage=0.0)["breakdown"]
        self.assertEqual(b["field_n2o_emissions_kg_co2e"], 0.0)
        self.assertAlmostEqual(b["product_emissions_kg_co2e"], b["processing_emissions_kg_co2e"], places=1)

    def test_same_nitrogen_delivered_in_double_the_water_costs_the_same_n2o(self):
        # The defect made the footprint track the water content. Field N2O must
        # depend only on the nitrogen delivered.
        strong = self._calc(chemical_mass_kg=1000, n_percentage=0.06)["breakdown"]
        dilute = self._calc(chemical_mass_kg=2000, n_percentage=0.03)["breakdown"]
        self.assertAlmostEqual(
            strong["field_n2o_emissions_kg_co2e"],
            dilute["field_n2o_emissions_kg_co2e"],
            places=1,
        )

    def test_synthetic_fertilizer_is_not_double_charged(self):
        # nitrogen_fertilizer (10.5) already contains the field component; the synthetic
        # branch must not pick up nitrogen_field_n2o on top of it.
        syn = VEF.calculate_chemical_application_emissions(
            chemical_type="FE",
            volume_liters=0,
            area_hectares=10,
            npk_content={"N": 10.0, "P": 0.0, "K": 0.0},
            chemical_subtype="synthetic_fertilizer",
            chemical_mass_kg=1000,
        )["breakdown"]
        self.assertNotIn("field_n2o_emissions_kg_co2e", syn)
        # 100 kg N x 10.5 = 1050, not 1050 + 614.
        self.assertAlmostEqual(syn["product_emissions_kg_co2e"], 1050.0, delta=1.0)
