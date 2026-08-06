"""Field N2O from nitrogen applied in a SOIL AMENDMENT (2026-07-31).

`ChemicalEvent` fertilisers declared nitrogen via `nitrogen_percentage` and were charged
for post-application N2O. `SoilManagementEvent` had **no nitrogen field at all**, so on an
organic orchard — where compost is normally the LARGEST nitrogen source — the biggest
contributor to field N2O was counted as zero.

Pilot magnitude: 170 metric tons of compost at 1% N is 1,700 kg N. At the shared
`nitrogen_field_n2o` factor (6.14 kg CO2e/kg N, IPCC 2019 Refinement Vol.4 Ch.11) that is
~10,438 kg CO2e which the model previously did not see at all — roughly 28x the nitrogen
in the same season's fertigation.

Also underpins California's Irrigated Lands Regulatory Program: every irrigated CA grower
files an Irrigation & Nitrogen Management Plan summary reporting total nitrogen applied
"from all sources", which includes compost and manure.
"""

from decimal import Decimal

from django.test import SimpleTestCase

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.services.verified_emission_factors import VerifiedEmissionFactors as VEF
from history.models import SoilManagementEvent

FACTOR = VEF.EPA_CHEMICAL_FACTORS["nitrogen_field_n2o"].value


class AmendmentNitrogenFieldTests(SimpleTestCase):
    def test_soil_event_has_a_nitrogen_column(self):
        names = {f.name for f in SoilManagementEvent._meta.get_fields()}
        self.assertIn("amendment_nitrogen_percentage", names)

    def test_shares_the_factor_with_the_fertiliser_path(self):
        # One factor, one derivation — the two N2O paths must not diverge.
        self.assertAlmostEqual(FACTOR, 6.14, places=2)


class AmendmentNitrogenCarbonTests(SimpleTestCase):
    """Unsaved in-memory events: the calculator only reads attributes."""

    def _event(self, amount, unit="tons", n_pct=None, etype="OM"):
        e = SoilManagementEvent(
            type=etype,
            amendment_type="compost",
            amendment_amount_numeric=Decimal(str(amount)),
            amendment_amount_unit=unit,
            amendment_nitrogen_percentage=(Decimal(str(n_pct)) if n_pct is not None else None),
            area_covered=Decimal("42.5"),
            area_unit="acres",
        )
        e.extra_data = {}
        return e

    def _n2o(self, event):
        r = EventCarbonCalculator().calculate_soil_management_event_impact(event)
        return r["breakdown"].get("amendment_field_n2o_emissions", 0.0)

    def test_no_nitrogen_declared_means_no_n2o_charged(self):
        # Absence of a figure must not be treated as a figure — this is the
        # "absence of evidence is not evidence" rule applied to carbon.
        self.assertEqual(self._n2o(self._event(170, "tons", None)), 0.0)

    def test_metric_tons_convert_to_kilograms(self):
        # 170 t x 1% = 1,700 kg N x 6.14 = 10,438 kg CO2e
        self.assertAlmostEqual(self._n2o(self._event(170, "tons", 1.0)), 1700 * FACTOR, delta=1.0)

    def test_pounds_convert(self):
        # 2,000 lb x 2% = 18.14 kg N
        expected = 2000 * 0.453592 * 0.02 * FACTOR
        self.assertAlmostEqual(self._n2o(self._event(2000, "lbs", 2.0)), expected, delta=0.5)

    def test_kilograms_are_used_directly(self):
        self.assertAlmostEqual(self._n2o(self._event(1000, "kg", 1.5)), 1000 * 0.015 * FACTOR, delta=0.5)

    def test_n2o_reaches_the_event_total_not_just_the_breakdown(self):
        calc = EventCarbonCalculator()
        without = calc.calculate_soil_management_event_impact(self._event(170, "tons", None))["co2e"]
        with_n = calc.calculate_soil_management_event_impact(self._event(170, "tons", 1.0))["co2e"]
        self.assertAlmostEqual(with_n - without, 1700 * FACTOR, delta=1.0)

    def test_nitrogen_kg_is_exposed_for_the_ca_ilrp_filing(self):
        # CA growers report total nitrogen APPLIED from all sources; the amendment's
        # contribution has to be readable, not buried inside a CO2e total.
        r = EventCarbonCalculator().calculate_soil_management_event_impact(self._event(170, "tons", 1.0))
        self.assertAlmostEqual(r["breakdown"]["amendment_nitrogen_kg"], 1700.0, delta=0.5)

    def test_zero_percent_nitrogen_charges_nothing(self):
        # A gypsum or lime application legitimately carries no nitrogen.
        self.assertEqual(self._n2o(self._event(170, "tons", 0)), 0.0)
