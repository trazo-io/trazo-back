"""Guards for what a carbon number is allowed to CLAIM about where it came from.

Two failures motivated this file, both found on 2026-08-20 while reworking the activity
wizard's "How we calculated" panel:

1. 29 of the 57 emission factors carried a `source` string that names an agency but no
   document — "USDA Agricultural Research Service - Field Operations". The class docstring
   asserted "All factors are sourced from official government publications." The wizard
   read that confidence and printed an "EPA/USDA-sourced" badge over a figure whose
   driving input was a Trazo-chosen national average. `compliance.md` checklist item 1
   forbids exactly this: an attribution shaped like a citation.

2. The fuel figure itself was a substitution. With fuel left blank the calculator multiplies
   acreage by a per-hectare default, and the payload said nothing to distinguish that from a
   number the operator measured.

So provenance is a typed field, not prose to be regex'd at the call site, and `fuel_basis`
states measured-vs-assumed in one place every production activity writes.
"""

from django.test import SimpleTestCase

from carbon.services.verified_emission_factors import (
    PROVENANCE_INTERNAL_ESTIMATE,
    PROVENANCE_PUBLISHED,
    EmissionFactor,
    VerifiedEmissionFactors,
)

# A `source` may call itself published only if it names something a certifier could pull
# up: a CFR part/table, an eGRID edition, an IPCC volume, an author-year, or the stated
# engineering equation. Deliberately NOT a catch-all — the point is that relabelling a
# factor as published without fixing its source string fails here.
CITATION_MARKERS = (
    "40 CFR",
    "eGRID",
    "IPCC",
    "et al.",
    "Table C-1",
    "CAMMESA",
    "ONS Brazil",
    "CEN Chile",
    "XM Colombia",
    "CENACE",
    "COES",
    "Lal 2004",
    "MIEM/DNE",
    "pumping-energy equation",
)


def _all_factors():
    """Every EmissionFactor on the class, as (dict_name, key, factor)."""
    for dict_name in dir(VerifiedEmissionFactors):
        if not dict_name.isupper():
            continue
        container = getattr(VerifiedEmissionFactors, dict_name)
        if not isinstance(container, dict):
            continue
        for key, factor in container.items():
            if isinstance(factor, EmissionFactor):
                yield dict_name, key, factor


class FactorProvenanceTests(SimpleTestCase):
    def test_every_factor_declares_a_known_provenance(self):
        factors = list(_all_factors())
        self.assertGreater(len(factors), 40, "factor sweep found almost nothing — did the class move?")

        valid = {PROVENANCE_PUBLISHED, PROVENANCE_INTERNAL_ESTIMATE}
        for dict_name, key, factor in factors:
            self.assertIn(
                factor.provenance,
                valid,
                f"{dict_name}.{key} has provenance={factor.provenance!r}, expected one of {valid}",
            )

    def test_published_factors_name_a_findable_document(self):
        """A "published" label must be backed by a source string, not just by intent."""
        offenders = [
            f"{dict_name}.{key}: {factor.source!r}"
            for dict_name, key, factor in _all_factors()
            if factor.is_published and not any(m in factor.source for m in CITATION_MARKERS)
        ]
        self.assertEqual(
            offenders,
            [],
            "these factors claim provenance='published' but their source names no document a "
            "certifier could look up. Either cite the publication (part, table, edition, or "
            f"author-year) or label them {PROVENANCE_INTERNAL_ESTIMATE!r}:\n  " + "\n  ".join(offenders),
        )

    def test_per_hectare_fuel_defaults_are_not_sold_as_published(self):
        """The six per-area fuel rates are Trazo defaults. They drive the wizard's headline
        number whenever fuel is blank, so mislabelling one puts a citation badge over a guess."""
        for key, factor in VerifiedEmissionFactors.PRODUCTION_FACTORS.items():
            if factor.unit != "gallons_per_hectare":
                continue
            self.assertEqual(
                factor.provenance,
                PROVENANCE_INTERNAL_ESTIMATE,
                f"PRODUCTION_FACTORS.{key} is a per-hectare default; it cannot claim publication",
            )

    def test_unlabelled_factor_defaults_to_internal_estimate(self):
        """Omission must not buy a citation. Adding a factor is a decision to classify it."""
        unlabelled = EmissionFactor(
            value=1.0,
            unit="kg_CO2_per_gallon",
            source="Some agency, no document",
            confidence_level=0.5,
            last_updated="2026-08-20",
        )
        self.assertEqual(unlabelled.provenance, PROVENANCE_INTERNAL_ESTIMATE)
        self.assertFalse(unlabelled.is_published)


class ProductionTypeCoverageTests(SimpleTestCase):
    """Every subtype the wizard offers must be MAPPED, not silently estimated as field diesel.

    `calculate_production_event_emissions` falls back to the general production factor
    (2.5 gal diesel/hectare) for any code missing from PRODUCTION_TYPE_MAPPING. Four codes
    the Production Activity dropdown offers were missing on 2026-08-20, so each returned
    6.198 kg CO2e on 0.6 acres:

      PO  pollination — bees. The SAVED path returned 0.0, so preview and saved disagreed
          on the same event, and the wizard rendered "no fuel burned, so no direct
          emissions" directly above a non-zero number.
      SS  § 205.204(a)(1) organic-seed availability search — a phone-and-catalogue task.
      BU  § 205.202(c) buffer-zone harvest/disposal record.
      TP  a load moving off-farm — real fuel, but it scales with distance, not with the
          acreage of the parcel it left.

    The fallback logs a warning nobody reads. This test is the thing that fails.
    """

    @property
    def WIZARD_SUBTYPES(self):
        """Read from the MODEL, never a copy.

        A hand-maintained list here would pass while the dropdown grew past it — which is
        exactly how PO/TP/BU/SS went unmapped in the first place. Deriving from
        `ProductionEvent.type.choices` means adding a subtype to the model without adding it
        to PRODUCTION_TYPE_MAPPING fails this test on the next run.
        """
        from history.models import ProductionEvent

        return [choice[0] for choice in ProductionEvent._meta.get_field("type").choices]

    def test_no_wizard_subtype_falls_back_to_the_general_field_estimate(self):
        offenders = []
        for code in self.WIZARD_SUBTYPES:
            result = VerifiedEmissionFactors.calculate_production_event_emissions(
                production_type=code, area_covered=0.6
            )
            basis = (result.get("breakdown") or {}).get("calculation_basis")
            # The unknown-code fallback lands on the general per-hectare diesel path and
            # produces exactly the general-production figure.
            if (
                code not in ("PL", "HA", "IR", "TR", "CU", "TH", "EM", "FP", "MO")
                and basis == "usda_standard_per_hectare"
            ):
                offenders.append(f"{code} (basis={basis}, co2e={result['co2e_kg']})")
        self.assertEqual(
            offenders,
            [],
            "these subtypes are not in PRODUCTION_TYPE_MAPPING and are being charged the "
            "general 2.5 gal/hectare field-diesel estimate:\n  " + "\n  ".join(offenders),
        )

    def test_non_area_driven_subtypes_report_zero_without_reported_fuel(self):
        """Documenting a seed search or a buffer strip burns nothing."""
        for code in ("PO", "SS", "BU", "TP"):
            with self.subTest(code=code):
                result = VerifiedEmissionFactors.calculate_production_event_emissions(
                    production_type=code, area_covered=0.6
                )
                self.assertEqual(result["co2e_kg"], 0.0, f"{code} invented emissions from acreage alone")

    def test_transport_and_buffer_still_count_fuel_the_operator_reported(self):
        """Zero-by-default must not become zero-always: haul diesel is a real emission."""
        for code in ("TP", "BU", "SS"):
            with self.subTest(code=code):
                result = VerifiedEmissionFactors.calculate_production_event_emissions(
                    production_type=code, area_covered=0.6, fuel_consumed=2.0, fuel_type="diesel"
                )
                self.assertAlmostEqual(result["co2e_kg"], 2.0 * 10.21, places=2)

    def test_pollination_is_zero_even_if_fuel_is_reported(self):
        """PO is a biological service. The SAVED path has always returned 0.0 unconditionally;
        preview must agree or the two paths disagree on the same event again."""
        result = VerifiedEmissionFactors.calculate_production_event_emissions(
            production_type="PO", area_covered=0.6, fuel_consumed=2.0, fuel_type="diesel"
        )
        self.assertEqual(result["co2e_kg"], 0.0)
        self.assertEqual(result["calculation_method"], "zero_emission_biological_service")

    def test_postharvest_electric_is_priced_as_electricity_not_diesel(self):
        """EPA_FUEL_FACTORS has no "electric" key, so `.get(fuel_type, diesel)` charged an
        electric huller's kWh as litres of diesel — 10 kWh billed as 26.97 kg instead of 3.9.
        The wizard offers Electric on every subtype including Post-Harvest."""
        result = VerifiedEmissionFactors.calculate_production_event_emissions(
            production_type="PH", area_covered=0.6, fuel_consumed=10.0, fuel_type="electric"
        )
        self.assertAlmostEqual(result["co2e_kg"], 10.0 * 0.39, places=2)


class FuelBasisTests(SimpleTestCase):
    """`fuel_basis` is the one key a client reads to tell measured from assumed."""

    def test_blank_fuel_reports_an_assumed_rate_with_its_own_provenance(self):
        result = VerifiedEmissionFactors.calculate_production_event_emissions(
            production_type="planting", area_covered=0.6
        )
        basis = result["breakdown"]["fuel_basis"]

        self.assertFalse(basis["measured"])
        self.assertIsNotNone(basis["assumed_rate"], "fuel was not supplied, so a rate was substituted")
        self.assertEqual(basis["assumed_rate"]["provenance"], PROVENANCE_INTERNAL_ESTIMATE)
        # The combustion factor IS citable even when the fuel quantity is not. The whole
        # point of splitting them is that one badge can no longer cover both.
        self.assertEqual(basis["emission_factor"]["provenance"], PROVENANCE_PUBLISHED)
        self.assertIn("40 CFR", basis["emission_factor"]["source"])

    def test_supplied_fuel_reports_measured_and_no_assumed_rate(self):
        result = VerifiedEmissionFactors.calculate_production_event_emissions(
            production_type="planting", area_covered=0.6, fuel_consumed=2.0
        )
        basis = result["breakdown"]["fuel_basis"]

        self.assertTrue(basis["measured"])
        self.assertIsNone(basis["assumed_rate"])

    def test_electric_equipment_also_reports_fuel_basis(self):
        """The annotation call originally sat inside the non-electric branch, so an electric
        machine produced no `fuel_basis` at all and the wizard fell back to its
        published-factor badge over an estimate."""
        result = VerifiedEmissionFactors.calculate_production_event_emissions(
            production_type="planting", area_covered=0.6, fuel_consumed=10.0, fuel_type="electric"
        )
        basis = result["breakdown"]["fuel_basis"]

        self.assertTrue(basis["measured"])
        self.assertEqual(basis["emission_factor"]["unit"], "kg_CO2_per_kWh")
        self.assertFalse(basis["assumed_fuel_is_diesel"])

    def test_reported_factor_is_the_one_that_produced_the_number(self):
        """With fuel blank the calculators multiply by the DIESEL factor whatever fuel type
        was selected. Reporting the electricity factor there would credit a factor that never
        touched the result — the same misattribution this whole field exists to prevent."""
        for fuel_type, expect_flag in (("electric", True), ("gasoline", True), ("diesel", False)):
            with self.subTest(fuel_type=fuel_type):
                result = VerifiedEmissionFactors.calculate_production_event_emissions(
                    production_type="planting", area_covered=0.6, fuel_type=fuel_type
                )
                basis = result["breakdown"]["fuel_basis"]

                self.assertFalse(basis["measured"])
                self.assertEqual(
                    basis["emission_factor"]["unit"],
                    "kg_CO2_per_gallon",
                    f"{fuel_type} with no fuel entered is costed in gallons of diesel",
                )
                self.assertEqual(
                    basis["assumed_fuel_is_diesel"],
                    expect_flag,
                    f"{fuel_type}: the diesel-substitution flag must match what the math did",
                )

    def test_every_area_based_production_type_reports_fuel_basis(self):
        """Regression: cultivation wrote `cultivation_intensity_factor` while its five siblings
        wrote `usda_<verb>_factor_gallons_per_hectare`. The wizard's hand-written key chain
        fell through to 0 and rendered "0.0 liters (estimated)" for every cultivation event.
        A key only some activities write is a key the client will read wrong."""
        for production_type in ("planting", "harvesting", "transplanting", "thinning", "cultivation"):
            with self.subTest(production_type=production_type):
                result = VerifiedEmissionFactors.calculate_production_event_emissions(
                    production_type=production_type, area_covered=0.6
                )
                basis = result["breakdown"].get("fuel_basis")

                self.assertIsNotNone(basis, f"{production_type} wrote no fuel_basis")
                self.assertFalse(basis["measured"])
                self.assertIsNotNone(basis["assumed_rate"], f"{production_type} substituted a rate but did not say so")
                self.assertGreater(
                    basis["assumed_rate"]["value"],
                    0,
                    f"{production_type} reported a 0 gal/ha assumed rate — the factor did not reach the payload",
                )
