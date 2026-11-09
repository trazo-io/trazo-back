"""
Verified Emission Factors for Agricultural Carbon Calculations
Sources: EPA GHG Hub, EPA eGRID, EIA, IPCC, USDA NRCS, Audsley et al. 2009, Hillier et al. 2009

Last Comprehensive Audit: 2025-12-03
Partial Review: 2026-03-21 (chemical factors cross-validated)

CRITICAL UPDATE 2025-12-03:
- Electricity factor CORRECTED from 0.821 to 0.39 kg CO2/kWh (was 2.1x too high)
- All factors verified against primary sources with detailed citations added
- Nitrogen fertilizer factor (10.5) confirmed as high-end of literature range (includes N2O)

UPDATE 2026-09-07:
- Electricity factor corrected from 0.39 to 0.365 kg CO2e/kWh delivered. 0.39 is EPA's
  Equivalencies Calculator figure (823.1 lb CO2/MWh, eGRID2022, 5.12% T&D) but the code cited
  eGRID2023 Summary Tables, which do not produce it. Re-derived from the cited source.
- Grid loss corrected: eGRID publishes 4.2% U.S. grid gross loss, not 5.12%.

UPDATE 2026-03-21:
- Herbicide factor raised from 5.5 to 6.3 kg CO2/kg AI (Lal 2004 original, better validated)
- Pesticide and herbicide source notes updated to cite Audsley et al. 2009 and Hillier et al. 2009
- last_reviewed dates updated on both chemical factors

Primary Data Sources:
- EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98): Fuel combustion factors
- EPA eGRID2023 Summary Tables rev.2 (U.S. 770.9 lb CO2e/MWh, 4.2% grid gross loss): US electricity grid
- EIA 2023 Annual Energy Review: Electricity validation (0.81 lbs/kWh = 0.367 kg/kWh)
- IPCC 2006/2019 Guidelines: N2O emission factors (EF1 = 1%, GWP = 265)
- Audsley et al. 2009 / Hillier et al. 2009: Pesticide/herbicide manufacturing LCA (supersedes Lal 2004 citations)
- USDA NRCS: Irrigation pumping energy guidelines
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


# Provenance is what the UI is allowed to CLAIM about a number, and it is a typed field
# precisely so no surface has to parse `source` prose to decide. Two values only:
#
#   "published"         — `source` names a document a certifier could pull up: a CFR part
#                         and table, an eGRID edition, an IPCC volume/chapter, or an
#                         author-year that resolves to one paper.
#   "internal_estimate" — a Trazo-chosen default. Usually a national or regional average
#                         reconciled from several places, no one of which publishes THIS
#                         number. Defensible as a starting point, NOT as a citation.
#
# `compliance.md` checklist item 1 asks whether a statistic is sourced (publication, year,
# author) and forbids fabricated attributions. A string like "USDA Agricultural Research
# Service - Field Operations" names an agency, not a publication — it reads as a citation
# and cannot be followed to one, which is the failure mode that rule exists to catch. So
# those entries are labelled honestly rather than dressed up with an invented reference.
#
# The default is deliberately "internal_estimate": an unlabelled factor must not be able to
# claim publication by omission. Adding a factor is a decision to classify it.
PROVENANCE_PUBLISHED = "published"
PROVENANCE_INTERNAL_ESTIMATE = "internal_estimate"

# 🔴 2026-09-07 — a third state, and it exists because the two above were not enough to stop a
# real failure. `phosphorus_fertilizer` and `potassium_fertilizer` sat as PUBLISHED under
# "EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98)". That publication carries fuel
# combustion factors and no fertilizer manufacturing factors at all, so the citation could not be
# followed — and it had reached the public methodology page on the marketing site.
#
# Both have since moved on to INTERNAL_ESTIMATE, because a decision was made about them: hold
# each at the conservative end of the published range and say so. That makes them numbers WE
# derived and can explain, which is what INTERNAL_ESTIMATE means.
#
# UNVERIFIED remains for the state they passed through — a factor in use whose origin we cannot
# establish and about which no decision has been taken yet. It is a landing state, not a resting
# place, and `test_factor_sources_are_citable.py` makes it impossible to occupy silently: an
# unverified factor must be named in that test's register, with a reason, or the suite fails.
PROVENANCE_UNVERIFIED = "unverified"


@dataclass
class EmissionFactor:
    """Represents an emission factor with its source documentation and provenance."""

    value: float
    unit: str
    source: str
    confidence_level: float  # 0.0 to 1.0
    last_updated: str
    notes: Optional[str] = None
    provenance: str = PROVENANCE_INTERNAL_ESTIMATE

    @property
    def is_published(self) -> bool:
        """True only when `source` resolves to a document a certifier could look up."""
        return self.provenance == PROVENANCE_PUBLISHED


class VerifiedEmissionFactors:
    """
    Emission factors for agricultural activities, each carrying its own provenance.

    TRANSPARENCY PRINCIPLE: every factor states where it came from and whether that
    "where" is a document anyone can pull up.

    This docstring used to read "All factors are sourced from official government
    publications." That was not true of 29 of the 57 factors below, and the claim was
    load-bearing: the activity wizard rendered an "EPA/USDA-sourced" badge over a
    calculation whose driving input was a Trazo-chosen national average. Check
    `factor.is_published` before any surface claims a citation — never the `source` prose,
    and never the containing dict's name (EPA_CHEMICAL_FACTORS holds LCA-derived
    estimates too).
    """

    # EPA VERIFIED DIESEL EMISSION FACTORS
    EPA_DIESEL_FACTORS = {
        "diesel_fuel": EmissionFactor(
            value=10.18,  # kg CO2 per gallon
            unit="kg_CO2_per_gallon",
            source="EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2024-03-15",
            notes="Stationary combustion emission factor for diesel fuel",
        ),
        "diesel_fuel_mobile": EmissionFactor(
            value=10.21,  # kg CO2 per gallon
            unit="kg_CO2_per_gallon",
            source="EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2024-03-15",
            notes="Mobile combustion emission factor for diesel fuel",
        ),
        "agricultural_equipment": EmissionFactor(
            value=10.21,  # kg CO2 per gallon - same as mobile diesel
            unit="kg_CO2_per_gallon",
            source="EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2024-03-15",
            notes="Agricultural equipment mobile diesel emission factor",
        ),
    }

    # EPA VERIFIED FUEL EMISSION FACTORS (ALL FUEL TYPES)
    # Source: EPA 40 CFR Part 98 Table C-1
    # Used for multi-fuel-type calculations (chemical application, pest management, etc.)
    EPA_FUEL_FACTORS = {
        "diesel": EmissionFactor(
            value=10.21,  # kg CO2 per gallon
            unit="kg_CO2_per_gallon",
            source="EPA 40 CFR Part 98 Table C-1 (0.138 mmBtu/gal × 73.96 kg CO₂/mmBtu)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2026-02-15",
            notes="Mobile combustion for agricultural diesel fuel",
        ),
        "gasoline": EmissionFactor(
            value=8.78,  # kg CO2 per gallon
            unit="kg_CO2_per_gallon",
            source="EPA 40 CFR Part 98 Table C-1 (0.125 mmBtu/gal × 70.22 kg CO₂/mmBtu)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2026-02-15",
            notes="Motor gasoline combustion",
        ),
        "propane": EmissionFactor(
            value=5.72,  # kg CO2 per gallon
            unit="kg_CO2_per_gallon",
            source="EPA 40 CFR Part 98 Table C-1 (0.091 mmBtu/gal × 62.87 kg CO₂/mmBtu)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2026-02-15",
            notes="Propane/LPG combustion",
        ),
        "natural_gas": EmissionFactor(
            value=0.0544,  # kg CO2 per standard cubic foot
            unit="kg_CO2_per_scf",
            source="EPA 40 CFR Part 98 Table C-1 (0.001026 mmBtu/scf × 53.06 kg CO₂/mmBtu)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2026-02-15",
            notes="Natural gas combustion (weighted US average)",
        ),
        "biodiesel": EmissionFactor(
            value=8.76,  # kg CO2 per gallon
            unit="kg_CO2_per_gallon",
            source="EPA 40 CFR Part 98 Table C-1",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.90,
            last_updated="2026-02-15",
            notes="Biodiesel (B100) combustion",
        ),
    }

    # Conversions into STANDARD CUBIC FEET for gaseous fuels. The EPA natural-gas
    # factor above is per scf (0.001026 mmBtu/scf), so any gas quantity a farmer
    # reports has to be resolved to scf before the factor is applied.
    # 1 therm = 100,000 Btu; at 1,026 Btu/scf that is 97.466 scf.
    GAS_UNIT_TO_SCF = {
        "scf": 1.0,
        "cf": 1.0,
        "ft3": 1.0,
        "ccf": 100.0,  # 100 cubic feet — the unit on most US gas bills
        "mcf": 1000.0,
        "therm": 97.466,
        "therms": 97.466,
        "mmbtu": 974.659,
        "m3": 35.3147,
        "cubic_meters": 35.3147,
    }
    # Liquid-volume and mass units cannot describe a gas billed by volume or energy.
    # Reporting "310 L of natural gas" against a per-scf factor produced 1.18 kg CO2e for
    # drying 153,000 lb of walnuts. Refuse rather than under-report by ~2 orders of magnitude.
    NON_GAS_UNITS = {"l", "liter", "liters", "litre", "litres", "gal", "gallon", "gallons", "kg", "kwh"}

    @classmethod
    def gas_quantity_to_scf(cls, quantity, unit):
        """Convert a reported natural-gas quantity to standard cubic feet.

        Returns (scf, None) on success, or (None, reason) when the unit cannot
        describe a gas volume — callers must surface `reason` as a limitation
        instead of emitting a fabricated number.
        """
        try:
            qty = float(quantity)
        except (TypeError, ValueError):
            return None, "natural gas quantity is not numeric"
        if qty <= 0:
            return 0.0, None
        key = str(unit or "").strip().lower()
        if key in cls.GAS_UNIT_TO_SCF:
            return qty * cls.GAS_UNIT_TO_SCF[key], None
        if key in cls.NON_GAS_UNITS:
            return None, (
                f"natural gas reported in '{unit}', which cannot describe a gas volume; "
                "report gas in therms, ccf, scf, m3 or MMBtu for EPA factors to apply"
            )
        return None, f"unrecognised natural gas unit '{unit}'"

    @classmethod
    def fuel_co2e(cls, fuel_quantity, fuel_type: str, fuel_unit=None):
        """Emissions for a measured fuel quantity, resolved against the FACTOR'S OWN basis.

        Every liquid-fuel factor in EPA_FUEL_FACTORS is per US GALLON, and callers
        normalise litres/kg to gallons before arriving here. Natural gas is per STANDARD
        CUBIC FOOT — so multiplying a gallon count by it under-reports by roughly two
        orders of magnitude. That mistake was replicated at eight independent call sites
        (harvesting, planting, transplanting, general, thinning, manual, cultivation,
        post-harvest, plus the aggregate/summary path), each doing the same
        `co2e = fuel_consumed * fuel_factor.value` line.

        This is the single choke point. Gaseous fuels resolve to their own basis; a
        liquid/mass unit for a gas is REFUSED (0.0 + reason) rather than silently
        producing a plausible-looking near-zero.

        Returns (co2e_kg, factor, error_or_None).
        """
        factor, _basis = cls._get_fuel_factor_for_type(fuel_type)
        if fuel_quantity in (None, ""):
            return 0.0, factor, None
        if str(fuel_type or "").lower() == "natural_gas":
            scf, reason = cls.gas_quantity_to_scf(fuel_quantity, fuel_unit)
            if scf is None:
                return 0.0, factor, reason
            return scf * factor.value, factor, None
        return float(fuel_quantity) * factor.value, factor, None

    @classmethod
    def _get_fuel_factor_for_type(cls, fuel_type: str):
        """Get emission factor and calculation basis for a given fuel type.

        Returns (EmissionFactor, calculation_basis) tuple.
        Falls back to diesel for unknown types.
        Used by all production calculation functions to support gasoline, propane, biodiesel, etc.
        """
        fuel_type_lower = fuel_type.lower() if fuel_type else "diesel"
        if fuel_type_lower in cls.EPA_FUEL_FACTORS:
            factor = cls.EPA_FUEL_FACTORS[fuel_type_lower]
            return factor, f"actual_{fuel_type_lower}_consumption"
        # Unknown fuel type — fallback to diesel
        return cls.EPA_FUEL_FACTORS["diesel"], "actual_diesel_consumption"

    # EPA VERIFIED ELECTRICITY EMISSION FACTORS (US AVERAGE)
    #
    # 2025-12-03: corrected from 0.821 to 0.39 kg CO2/kWh.
    # 2026-09-07: corrected again, to 0.365 kg CO2e/kWh, because 0.39 did not follow from the
    #   source this file cited for it. 0.39 is EPA's *Equivalencies Calculator* figure
    #   (823.1 lb CO2/MWh, eGRID2022 data, 5.12% T&D losses) — a real EPA number, but a year older
    #   and a different publication from the eGRID2023 Summary Tables named here. Deriving the
    #   value from the source actually cited gives 0.365, and the T&D figure eGRID publishes for
    #   the U.S. is 4.2%, not 5.12%. See documentation/reference/emission-factors.md.
    #
    # DERIVATION (eGRID2023 Summary Tables, Revision 2, released 2025-06-12, U.S. row):
    #   U.S. total output emission rate  CO2  767.2 lb/MWh, CO2e 770.9 lb/MWh
    #   U.S. grid gross loss             4.2%
    #   770.9 lb/MWh x 0.45359237 kg/lb / 1000 = 0.34967 kg CO2e/kWh at the generator
    #   0.34967 / (1 - 0.042)                  = 0.365   kg CO2e/kWh delivered
    #
    # CO2e (not CO2-only) because every downstream label in this product says CO2e.
    # Re-check when eGRID2024 lands: https://www.epa.gov/egrid/summary-data
    EPA_ELECTRICITY_FACTORS = {
        "electricity_us_avg": EmissionFactor(
            value=0.365,  # kg CO2e per kWh delivered (eGRID2023 data year 2023)
            unit="kg_CO2_per_kWh",  # label kept for consistency with the country factors; the value is CO2e
            source="EPA eGRID2023 Summary Tables rev.2 (U.S. 770.9 lb CO2e/MWh, 4.2% grid gross loss)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2026-09-07",
            notes="US average delivered electricity. 770.9 lb CO2e/MWh at the generator / (1 - 0.042) = 0.365 kg CO2e/kWh delivered.",
        )
    }

    # COUNTRY-SPECIFIC ELECTRICITY EMISSION FACTORS
    # Each country's grid operator provides annual emission intensity data.
    COUNTRY_ELECTRICITY_FACTORS = {
        "US": EmissionFactor(
            value=0.365,
            unit="kg_CO2_per_kWh",
            source="EPA eGRID2023 Summary Tables rev.2 (U.S. 770.9 lb CO2e/MWh, 4.2% grid gross loss)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2026-09-07",
            notes="US average delivered electricity. Same derivation as EPA_ELECTRICITY_FACTORS above.",
        ),
        "UY": EmissionFactor(
            value=0.006263,
            unit="kg_CO2_per_kWh",
            source="MIEM/DNE Balance Energético Nacional (BEN) 2024 — Factor de emisión de CO2 del SIN (FE_SIN 6.263 tCO2/GWh)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.90,
            last_updated="2026-06-13",
            notes=(
                "Official MIEM/DNE BEN 2024 grid factor (99% renewable: hydro 50%, wind 33%, "
                "biomass 13%, solar 3%, fossil 1% per ADME Informe Anual 2024). NOTE: the BEN "
                "factor is highly volatile YoY (0.101 in 2021 -> 0.006 in 2024) as it tracks the "
                "hydro/thermal mix; a 3-yr trailing average (~0.041) is a defensible conservative "
                "alternative if stability is preferred. Corrected 2026-06-13 from stale 0.04 "
                "(~6.4x too high vs 2024)."
            ),
        ),
        "AR": EmissionFactor(
            value=0.35,
            unit="kg_CO2_per_kWh",
            source="CAMMESA Argentina 2023",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.85,
            last_updated="2025-06-01",
            notes="Argentina mix of thermal + hydro + nuclear",
        ),
        "BR": EmissionFactor(
            value=0.07,
            unit="kg_CO2_per_kWh",
            source="ONS Brazil 2023 (~80% hydro)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.90,
            last_updated="2025-06-01",
            notes="Brazil grid dominated by hydroelectric",
        ),
        "CL": EmissionFactor(
            value=0.31,
            unit="kg_CO2_per_kWh",
            source="CEN Chile 2023",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.85,
            last_updated="2025-06-01",
            notes="Chile transitioning to solar + wind",
        ),
        "CO": EmissionFactor(
            value=0.13,
            unit="kg_CO2_per_kWh",
            source="XM Colombia 2023 (~70% hydro)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.85,
            last_updated="2025-06-01",
            notes="Colombia grid largely hydroelectric",
        ),
        "MX": EmissionFactor(
            value=0.42,
            unit="kg_CO2_per_kWh",
            source="CENACE Mexico 2023",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.85,
            last_updated="2025-06-01",
            notes="Mexico grid mix of gas, oil, hydro, wind",
        ),
        "PE": EmissionFactor(
            value=0.19,
            unit="kg_CO2_per_kWh",
            source="COES Peru 2023 (~60% hydro)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.85,
            last_updated="2025-06-01",
            notes="Peru grid predominantly hydroelectric",
        ),
    }

    @classmethod
    def get_country_electricity_factor(cls, country_code=None):
        """
        Return the EmissionFactor for the operating country's electricity grid.
        Falls back to US average with a warning if country is not mapped.
        """
        if country_code is None:
            country_code = getattr(settings, "TRAZO_OPERATING_COUNTRY", "US")
        factor = cls.COUNTRY_ELECTRICITY_FACTORS.get(country_code)
        if factor is None:
            logger.warning(
                "No electricity factor for country '%s'; falling back to US average (0.365 kg CO2e/kWh)",
                country_code,
            )
            factor = cls.COUNTRY_ELECTRICITY_FACTORS["US"]
        return factor

    # EPA VERIFIED CHEMICAL EMISSION FACTORS
    EPA_CHEMICAL_FACTORS = {
        "nitrogen_fertilizer": EmissionFactor(
            value=10.5,  # kg CO2 per kg N (manufacturing + direct N2O emissions)
            unit="kg_CO2_per_kg_N",
            source="EPA 40 CFR Part 98 + IPCC 2006/2019 Guidelines Direct N2O (EF1=1%)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.90,
            last_updated="2025-12-03",
            notes="Manufacturing (1-5 kg CO2e/kg N, avg 2.6 for urea) + N2O field emissions (IPCC 1% default × 44/28 × 265 GWP = ~4.2 kg CO2e/kg N) + indirect N2O (~3.7 kg). Total 10.5 is high-end of 4-12 kg range from scientific literature (Nature 2022). Conservative for transparency.",
        ),
        "phosphorus_fertilizer": EmissionFactor(
            value=1.19,  # kg CO2 per kg P2O5 (manufacturing emissions)
            unit="kg_CO2_per_kg_P2O5",
            source="Trazo conservative estimate, upper end of Walling & Vaneeckhaute 2020 (1.0-1.5 kg CO2e/kg P2O5)",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.60,
            last_updated="2026-09-07",
            notes=(
                "Phosphorus fertilizer manufacturing. Held at 1.19 deliberately rather than "
                "re-sourced to a lower published figure. Walling & Vaneeckhaute 2020 put P "
                "production at 1.0-1.5 kg CO2e/kg P2O5; Brentrup et al. 2018 implies ~0.52 for "
                "triple superphosphate, but that is European production and US phosphate is "
                "largely domestic (FL/LA), so adopting it would swap an unsourced number for a "
                "mis-scoped one AND move the estimate DOWN. For a transparency product, "
                "overstating our own footprint is the safe direction and understating it is the "
                "greenwashing direction, so the high end of the published range is the right "
                "place to sit while the number is imprecise. Labelled internal_estimate, not "
                "published: this is our choice within a cited range, not an agency's figure."
            ),
        ),
        "potassium_fertilizer": EmissionFactor(
            value=0.65,  # kg CO2 per kg K2O (manufacturing emissions)
            unit="kg_CO2_per_kg_K2O",
            source="Trazo conservative estimate; literature is sparse (Walling & Vaneeckhaute 2020), Brentrup et al. 2018 implies ~0.42",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.55,
            last_updated="2026-09-07",
            notes=(
                "Potassium fertilizer manufacturing. 0.65 sits ABOVE every published figure found "
                "— Brentrup et al. 2018 implies ~0.42 per kg K2O from muriate of potash — and it "
                "is held there on purpose. Walling & Vaneeckhaute 2020 call knowledge of potash "
                "production emissions 'greatly lacking', US potash is largely Canadian rather "
                "than European, and K2O is the smallest of the three NPK terms in any realistic "
                "application. Erring high in a poorly characterised area costs a farmer nothing "
                "they would notice and keeps us on the safe side of an environmental claim. "
                "Labelled internal_estimate, not published: it is our judgement, not a citation."
            ),
        ),
        "pesticide_manufacturing": EmissionFactor(
            value=8.8,  # kg CO2 per kg active ingredient
            unit="kg_CO2_per_kg_active_ingredient",
            source="Audsley et al. 2009, range 5.1-19 kg; cross-validated Hillier et al. 2009",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.85,
            last_updated="2026-03-21",
            notes=(
                "Insecticide/pesticide manufacturing. Updated review 2026-03-21: factors "
                "cross-validated against Hillier et al. 2009, Audsley et al. 2009. "
                "Literature range: 5.1 kg (Lal 2004) to 18-19 kg (Audsley et al. 2009). "
                "8.8 retained as midpoint for generic insecticides. Higher for synthetic "
                "pyrethroids, lower for older organophosphates. "
                "source_note: Updated review 2026-03-21: factors cross-validated against "
                "Hillier et al. 2009, Audsley et al. 2009"
            ),
        ),
        "herbicide_manufacturing": EmissionFactor(
            value=6.3,  # kg CO2 per kg active ingredient — updated from 5.5 to Lal 2004 original
            unit="kg_CO2_per_kg_active_ingredient",
            source="Lal 2004 (6.3±2.7 kg), Audsley et al. 2009 (18-27 kg); Hillier et al. 2009",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.85,
            last_updated="2026-03-21",
            notes=(
                "Herbicide manufacturing. Updated 2026-03-21: raised from 5.5 to 6.3 kg CO2/kg AI, "
                "aligning with Lal 2004 original central estimate (6.3±2.7 kg) which is better "
                "validated than the previous conservative floor. Audsley et al. 2009: 18-27 kg "
                "(high end). Glyphosate specifically: 31.3 kg. Organic/acetic acid herbicides "
                "use the organic_herbicide_manufacturing factor (1.2 kg). "
                "source_note: Updated review 2026-03-21: factors cross-validated against "
                "Hillier et al. 2009, Audsley et al. 2009"
            ),
        ),
        "organic_herbicide_manufacturing": EmissionFactor(
            value=1.2,  # kg CO2 per kg (acetic acid/vinegar herbicides)
            unit="kg_CO2_per_kg",
            source="ScienceDirect LCA Studies - Acetic Acid Production (0.64-1.2 kg CO2e/kg)",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.85,
            last_updated="2025-01-21",
            notes="Organic herbicides (acetic acid/vinegar-based) - much lower than synthetic herbicides due to simpler fermentation production process",
        ),
        "fungicide_manufacturing": EmissionFactor(
            value=4.5,  # kg CO2 per kg active ingredient (verified against LCA literature)
            unit="kg_CO2_per_kg_active_ingredient",
            source="Lal 2004 (3.9±2.2 kg), agricultural LCA studies",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.85,
            last_updated="2025-12-03",
            notes="Fungicide manufacturing. Lal 2004: 3.9 kg. Using 4.5 as conservative estimate. Copper-based: 5.5 kg, Sulfur-based: 1.8 kg, Biological: 2.0 kg factors apply for specific types.",
        ),
        "copper_fungicide_manufacturing": EmissionFactor(
            value=5.5,  # kg CO2 per kg active ingredient (copper-based fungicides)
            unit="kg_CO2_per_kg_active_ingredient",
            source="International Copper Association - Copper Production LCA (3-5 kg CO2e/kg Cu) + processing",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.85,
            last_updated="2025-01-21",
            notes="Copper-based fungicides (copper sulfate, copper hydroxide) - higher than generic due to copper mining/refining energy intensity",
        ),
        "sulfur_fungicide_manufacturing": EmissionFactor(
            value=1.8,  # kg CO2 per kg sulfur (elemental sulfur production)
            unit="kg_CO2_per_kg",
            source="EPA Industrial Manufacturing + Sulfur Recovery LCA Studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.85,
            last_updated="2025-01-21",
            notes="Sulfur-based fungicides - lower emissions as sulfur is often a byproduct of oil/gas refining",
        ),
        "biological_fungicide_manufacturing": EmissionFactor(
            value=2.0,  # kg CO2 per kg (fermentation-based production)
            unit="kg_CO2_per_kg",
            source="LCA Studies - Biological Agent Fermentation Production",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2025-01-21",
            notes="Biological fungicides (Bacillus, Trichoderma) - lower emissions due to fermentation-based production",
        ),
        "organic_fungicide_manufacturing": EmissionFactor(
            value=2.5,  # kg CO2 per kg (naturally-derived extraction)
            unit="kg_CO2_per_kg",
            source="LCA Studies - Natural Fungicide Extraction (Neem Oil, Potassium Bicarbonate)",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.75,
            last_updated="2026-04-09",
            notes="Organic fungicides (neem oil, potassium bicarbonate, essential oils) - moderate emissions from extraction/purification",
        ),
        "organic_pesticide_manufacturing": EmissionFactor(
            value=3.5,  # kg CO2 per kg (naturally-derived pesticides)
            unit="kg_CO2_per_kg",
            source="LCA Studies - Natural Pesticide Extraction (Neem, Pyrethrin)",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2025-01-21",
            notes="Organic pesticides (neem, pyrethrin) - moderate emissions from extraction processes",
        ),
        "biological_pesticide_manufacturing": EmissionFactor(
            value=2.5,  # kg CO2 per kg (microbial-based pesticides)
            unit="kg_CO2_per_kg",
            source="LCA Studies - Microbial Pesticide Production (Bt, Spinosad)",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2025-01-21",
            notes="Biological pesticides (Bt, Spinosad) - lower emissions from fermentation-based production",
        ),
        # Field N2O from APPLIED NITROGEN, independent of where the N came from.
        # Once nitrogen is in the soil, nitrification/denitrification does not care whether
        # it arrived via Haber-Bosch or a fish hydrolysate — so this component applies to
        # organic fertilisers exactly as it does to synthetic ones. It is already baked into
        # `nitrogen_fertilizer` (10.5 = ~4.4 manufacturing + this); organic fertiliser was
        # previously charged ONLY a per-kg-of-product processing rate and therefore omitted
        # field N2O entirely (found 2026-07-31, CA organic walnut pilot QA).
        #
        # Derivation from the 2019 Refinement to the 2006 IPCC Guidelines, Vol. 4 Ch. 11,
        # using the AGGREGATED (climate-agnostic) defaults, consistent with the EF1=0.01
        # already used by `nitrogen_fertilizer`:
        #   direct              EF1                      = 0.010   kg N2O-N / kg N   (Table 11.1)
        #   indirect, volatilised  FracGASM 0.21 x EF4 0.010 = 0.0021                (Table 11.3)
        #   indirect, leached      FracLEACH 0.24 x EF5 0.011 = 0.00264              (Table 11.3)
        #   total                                        = 0.01474 kg N2O-N / kg N
        #   x 44/28 -> 0.023163 kg N2O / kg N;  x 265 GWP100 (AR5) = 6.14 kg CO2e / kg N
        #
        # FracGASM is IPCC's organic-specific volatilisation fraction ("all organic N
        # fertilisers applied, and dung and urine deposited by grazing animals"), so this
        # factor is, if anything, tuned to organic inputs rather than borrowed from synthetic.
        # Cross-check: 10.5 - 6.14 = 4.36 kg CO2e/kg N of manufacturing, which sits at the
        # high end of the documented 1-5 range for urea/ammonia — the decomposition is coherent.
        #
        # Deliberately conservative in TWO ways, both of which over-report rather than
        # under-report — the safe direction for a transparency claim:
        #
        #  1. IPCC disaggregates EF1 DOWN for organic amendments (0.006 wet, 0.005 dry vs
        #     0.016 synthetic-wet). Applying the 0.010 aggregate slightly over-states an
        #     organic grower. Revisit if per-event climate zone becomes available.
        #  2. EF1 is applied to TOTAL nitrogen applied, which is the IPCC Tier 1 convention.
        #     For composted amendments only ~15% of that nitrogen mineralises in the year of
        #     application (WSU Tree Fruit, "Compost Considerations"), so a Tier 2 treatment
        #     would attribute less to year one and spread the remainder forward. Tier 1 is
        #     the defensible default for a farmer-reported system with no multi-year model.
        #
        # NOTE on asymmetry: this charges the N2O from compost but takes NO credit for the
        # soil carbon compost builds, because carbon-methodology.md scopes Trazo to direct
        # operational emissions. That is internally consistent, but it does mean an organic
        # grower's number carries a cost without its paired benefit — worth saying plainly
        # wherever this figure is presented rather than letting it read as a full verdict.
        "nitrogen_field_n2o": EmissionFactor(
            value=6.14,  # kg CO2e per kg N applied (direct + indirect N2O, no manufacturing)
            unit="kg_CO2e_per_kg_N",
            source="IPCC 2019 Refinement Vol.4 Ch.11 Tables 11.1 & 11.3 (EF1 0.010, EF4 0.010, EF5 0.011, FracGASM 0.21, FracLEACH-(H) 0.24); GWP100 265 (IPCC AR5)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.85,
            last_updated="2026-07-31",
            notes="Post-application field N2O (direct + indirect) per kg of nitrogen applied, independent of N source. Applies to organic and synthetic N alike; already included inside the 10.5 nitrogen_fertilizer factor, so do NOT add both.",
        ),
        "organic_fertilizer_manufacturing": EmissionFactor(
            value=0.5,  # kg CO2 per kg (composting/manure processing)
            unit="kg_CO2_per_kg",
            source="USDA/EPA Composting LCA Studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.75,
            last_updated="2025-01-21",
            notes="Organic fertilizers (compost, manure) - minimal manufacturing emissions, primarily processing/transport",
        ),
        "application_fuel": EmissionFactor(
            value=10.21,  # kg CO2 per gallon diesel for application equipment
            unit="kg_CO2_per_gallon",
            source="EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2024-03-15",
            notes="Mobile diesel emission factor for chemical application equipment",
        ),
    }

    # EQUIPMENT ENERGY CONSUMPTION ESTIMATES (ENHANCED REAL-WORLD DATA)
    EQUIPMENT_CONSUMPTION = {
        "orchard_heater": EmissionFactor(
            value=6.0,  # gallons diesel per hour (CALIBRATED - realistic orchard heater)
            unit="gallons_diesel_per_hour",
            source="UC Davis Agricultural Engineering + Equipment manufacturer data (Smudge Pot/Orchard Heater)",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.85,
            last_updated="2025-01-21",
            notes="Commercial orchard heaters (150,000-250,000 BTU) calibrated to UC Davis frost protection studies",
        ),
        "wind_machine": EmissionFactor(
            value=35.0,  # kWh per hour (CALIBRATED - realistic wind machine consumption)
            unit="kWh_per_hour",
            source="Agricultural equipment specifications (Orchard-Rite, Schmeiser) + UC Davis frost protection studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2025-01-21",
            notes="75-100 HP wind machines, calibrated to commercial frost protection operations",
        ),
        "irrigation_pump": EmissionFactor(
            value=3.5,  # kWh per 1000 gallons pumped (deep well scenario, 200-300 ft lift)
            unit="kWh_per_1000_gallons",
            source="USDA NRCS Irrigation Energy Guidelines + agricultural engineering studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.85,
            last_updated="2025-12-03",
            notes="Deep well pumping (200-300 ft). Literature: 1.5-2.5 kWh/1000 gal for moderate lift (50-150 ft), 3-5 kWh for deep wells (200+ ft). Using 3.5 for conservative deep well/drought scenario. Actual varies with pump efficiency (50-75%) and lift depth.",
        ),
        "misting_system": EmissionFactor(
            value=12.0,  # kWh per hour per acre (CALIBRATED - realistic cooling system)
            unit="kWh_per_hour_per_acre",
            source="Agricultural cooling system studies + Equipment manufacturer specifications",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.75,
            last_updated="2025-01-21",
            notes="High-pressure misting systems calibrated to commercial farm cooling operations",
        ),
    }

    # IRRIGATION PUMP FACTORS BY WATER SOURCE (USDA NRCS)
    # Pump energy varies significantly by water source due to lift depth and pressure requirements.
    # Sources: USDA NRCS NEH Chapter 8, agricultural engineering pumping studies
    IRRIGATION_PUMP_FACTORS = {
        # CORRECTED 2026-07 (was 3.5 kWh/1000 gal = 1,140 kWh/acre-foot, nearly double the
        # top of California's published 170-600 kWh/AF range, and ~2.6x what this factor's
        # own "200-300 ft lift" description implies). Groundwater is the most common source
        # for a California orchard, so this was the single most frequently applied wrong
        # number in the carbon model.
        #
        # Now derived from the same pumping-energy equation used for measured pump depths
        # (kWh/AF = 1.0241 × TDH / OPE), at a 200 ft lift + 20 psi system pressure and 70%
        # plant efficiency = 360 kWh/AF. Brackets CPUC's California groundwater figures
        # (120 ft well ~175 kWh/AF, 200 ft ~292 kWh/AF, lift only) once pressurization is
        # added. Deeper wells should record `pump_depth_ft` rather than rely on this.
        "well_groundwater": EmissionFactor(
            value=1.11,
            unit="kWh_per_1000_gallons",
            source="Irrigation pumping-energy equation (kWh/AF = 1.0241 × TDH / OPE) at 200 ft lift, 20 psi, 70% OPE",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.75,
            last_updated="2026-07-30",
            notes=(
                "Representative California agricultural well: 200 ft lift + 20 psi = 246 ft TDH "
                "at 70% pumping-plant efficiency = 360 kWh/acre-foot. Record pump_depth_ft for a "
                "well-specific figure; confidence lowered from 0.85 because this stands in for an "
                "unmeasured lift."
            ),
        ),
        "municipal": EmissionFactor(
            value=0.20,
            unit="kWh_per_1000_gallons",
            source="USDA NRCS + Municipal Water Distribution Studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2026-02-19",
            notes="Pre-pressurized municipal supply. On-farm energy is minimal booster pump only.",
        ),
        "rainwater_harvesting": EmissionFactor(
            value=0.15,
            unit="kWh_per_1000_gallons",
            source="USDA NRCS + Rainwater Harvesting LCA Studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.75,
            last_updated="2026-02-19",
            notes="Gravity-fed collection systems. Minimal energy for transfer pump from cistern to field.",
        ),
        "irrigation_canal": EmissionFactor(
            value=0.50,
            unit="kWh_per_1000_gallons",
            source="USDA NRCS Irrigation Energy Guidelines - Surface Water",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2026-02-19",
            notes="Low-lift surface pump (5-20 ft) from canal to field. Typical for irrigation district delivery.",
        ),
        "river_stream": EmissionFactor(
            value=0.85,
            unit="kWh_per_1000_gallons",
            source="USDA NRCS Irrigation Energy Guidelines - Surface Water Pumping",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2026-02-19",
            notes="Moderate-lift surface pump (20-50 ft). Varies with bank height and distance to field.",
        ),
        "pond_reservoir": EmissionFactor(
            value=0.40,
            unit="kWh_per_1000_gallons",
            source="USDA NRCS Irrigation Energy Guidelines - On-Farm Storage",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2026-02-19",
            notes="Low-lift from on-farm storage (5-15 ft). Minimal pumping for gravity-assisted systems.",
        ),
        "recycled_water": EmissionFactor(
            value=0.30,
            unit="kWh_per_1000_gallons",
            source="USDA NRCS + Reclaimed Water Distribution Studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.75,
            last_updated="2026-02-19",
            notes="Pre-treated and pressurized reclaimed water. On-farm energy similar to municipal.",
        ),
    }

    # Default pump factor when water_source is unknown or 'other'.
    #
    # CORRECTED 2026-07 (was 2.0 kWh/1000 gal = 652 kWh/acre-foot, above the top of
    # California's published 170-600 range). Its "midpoint of 0.5-3.5" derivation was
    # anchored on the well_groundwater value that was itself wrong, so the error compounded.
    #
    # Now a mid-range agricultural lift through the same equation: 150 ft + 20 psi at 70%
    # OPE = 287 kWh/acre-foot. This is the figure a farmer gets for recording NOTHING, so it
    # must not be punitive — the previous value meant almost any measured input improved the
    # number, which is the mirror image of the pump-depth bug fixed alongside it.
    IRRIGATION_PUMP_DEFAULT = EmissionFactor(
        value=0.88,
        unit="kWh_per_1000_gallons",
        source="Irrigation pumping-energy equation (kWh/AF = 1.0241 × TDH / OPE) at 150 ft lift, 20 psi, 70% OPE",
        provenance=PROVENANCE_PUBLISHED,
        confidence_level=0.60,
        last_updated="2026-07-30",
        notes=(
            "Stand-in for an unrecorded water source: mid-range 150 ft lift + 20 psi = 196 ft TDH "
            "at 70% pumping-plant efficiency = 287 kWh/acre-foot. Lowest confidence of any pump "
            "factor because neither the source nor the lift is known."
        ),
    )

    # Human-readable labels for water source types
    WATER_SOURCE_LABELS = {
        "well_groundwater": "Well/Groundwater (deep well)",
        "municipal": "Municipal Water Supply",
        "rainwater_harvesting": "Rainwater Harvesting",
        "irrigation_canal": "Irrigation Canal/District",
        "river_stream": "River/Stream",
        "pond_reservoir": "Pond/Reservoir",
        "recycled_water": "Recycled/Reclaimed Water",
        "other": "Other (US average estimate)",
    }

    # AGRICULTURAL PRODUCTION FACTORS (EPA/USDA VERIFIED)
    PRODUCTION_FACTORS = {
        # EPA Mobile Source Emission Factors (40 CFR Part 98)
        "agricultural_equipment": EmissionFactor(
            value=10.21,  # kg CO2 per gallon diesel (agricultural equipment)
            unit="kg_CO2_per_gallon",
            source="EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2024-03-15",
            notes="EPA mobile source emission factors for agricultural equipment",
        ),
        "irrigation_pump": EmissionFactor(
            value=0.365,  # kg CO2e per kWh delivered, electric irrigation pumps
            unit="kg_CO2_per_kWh",
            source="EPA eGRID2023 Summary Tables rev.2 (U.S. 770.9 lb CO2e/MWh, 4.2% grid gross loss)",
            provenance=PROVENANCE_PUBLISHED,
            confidence_level=0.95,
            last_updated="2026-09-07",
            notes="US average delivered electricity applied to irrigation pumps. Same derivation as EPA_ELECTRICITY_FACTORS above (0.821 -> 0.39 in 2025-12, 0.39 -> 0.365 in 2026-09).",
        ),
        # USDA Agricultural Research Service Data
        "crop_production_diesel": EmissionFactor(
            value=2.5,  # gallons diesel per hectare (typical agricultural operations)
            unit="gallons_per_hectare",
            source="USDA Agricultural Research Service - Farm Energy Use",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2024-01-01",
            notes="Average diesel consumption for crop production operations",
        ),
        "harvesting_diesel": EmissionFactor(
            value=0.7,  # gallons diesel per hectare for harvesting (modern efficient equipment)
            unit="gallons_per_hectare",
            source="USDA Agricultural Research Service - Machinery Energy Use (2025 efficiency standards)",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.85,
            last_updated="2025-01-21",
            notes="Modern high-efficiency harvesting equipment with GPS guidance and variable rate technology",
        ),
        "planting_diesel": EmissionFactor(
            value=1.8,  # gallons diesel per hectare for planting
            unit="gallons_per_hectare",
            source="USDA Agricultural Research Service - Field Operations",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2024-01-01",
            notes="Average diesel consumption for planting operations",
        ),
        "transplanting_diesel": EmissionFactor(
            value=2.4,  # gallons diesel per hectare for transplanting (higher than planting due to careful handling)
            unit="gallons_per_hectare",
            source="USDA Agricultural Research Service - Transplanting Operations & UC Davis Nursery Studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.82,
            last_updated="2025-10-11",
            notes="Transplanting operations require careful plant handling, transport, and more precise field work than direct seeding",
        ),
        "thinning_diesel": EmissionFactor(
            value=0.75,  # gallons diesel per hectare for thinning (lightweight manual operation)
            unit="gallons_per_hectare",
            source="USDA Agricultural Research Service - Lightweight Field Operations & Fruit Crop Management",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2025-12-10",
            notes="Thinning is primarily manual labor with minimal fuel-intensive equipment. Lower than general production (2.5) due to hand-selection nature. Includes minimal mechanical assistance for removed fruit transport.",
        ),
        "cultivation_diesel": EmissionFactor(
            value=3.2,  # gallons diesel per hectare for cultivation/weed control (high fuel intensity)
            unit="gallons_per_hectare",
            source="USDA Agricultural Research Service - Soil Preparation & Mechanical Weed Control",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.82,
            last_updated="2025-12-11",
            notes="Mechanical cultivation and weed removal operations requiring powered equipment. Higher than general production due to repeated passes and soil disturbance equipment (cultivators, row tillers).",
        ),
        "irrigation_water": EmissionFactor(
            value=0.85,  # kWh per 1000 gallons pumped (shallow to moderate lift)
            unit="kWh_per_1000_gallons",
            source="USDA NRCS Irrigation Energy Guidelines + agricultural engineering studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.85,
            last_updated="2025-12-03",
            notes="Standard irrigation pumping (50-100 ft head). Literature: 0.5-2.5 kWh/1000 gal typical. For deep wells (200+ ft), use EQUIPMENT_CONSUMPTION['irrigation_pump'] at 3.5 kWh. Theoretical minimum ~1.02 kWh per acre-ft per ft of lift.",
        ),
    }

    # CLEANUP AND DAMAGE RESPONSE ESTIMATES (ENHANCED REAL-WORLD)
    DAMAGE_RESPONSE = {
        "debris_cleanup": EmissionFactor(
            value=4.5,  # gallons diesel per hour of equipment operation (ENHANCED)
            unit="gallons_diesel_per_hour",
            source="Agricultural insurance claims data + Construction equipment fuel consumption averages",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2025-01-21",
            notes="Heavy tractor/loader operation for agricultural debris cleanup, includes transport to disposal",
        ),
        "replanting_prep": EmissionFactor(
            value=8.0,  # gallons diesel per acre for soil prep and replanting (ENHANCED)
            unit="gallons_diesel_per_acre",
            source="USDA Farm Operations fuel use surveys + Agricultural disaster response studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.85,
            last_updated="2025-01-21",
            notes="Complete replanting operation including tillage, soil amendment, planting, and initial irrigation setup",
        ),
        "hail_protection_repair": EmissionFactor(
            value=3.2,  # gallons diesel per hour for protection system repair
            unit="gallons_diesel_per_hour",
            source="Agricultural equipment repair fuel consumption studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.75,
            last_updated="2025-01-21",
            notes="Netting replacement, structure repair, and irrigation system fixes after hail damage",
        ),
        "wind_damage_repair": EmissionFactor(
            value=6.0,  # gallons diesel per hour for wind damage repair
            unit="gallons_diesel_per_hour",
            source="Agricultural storm damage response data + Equipment fuel studies",
            provenance=PROVENANCE_INTERNAL_ESTIMATE,
            confidence_level=0.80,
            last_updated="2025-01-21",
            notes="Tree/structure stabilization, irrigation repair, fence/trellis reconstruction after wind damage",
        ),
    }

    @classmethod
    def get_emission_factor(cls, category: str, factor_name: str) -> Optional[EmissionFactor]:
        """Get a specific emission factor by category and name"""
        categories = {
            "diesel": cls.EPA_DIESEL_FACTORS,
            "electricity": cls.EPA_ELECTRICITY_FACTORS,
            "equipment": cls.EQUIPMENT_CONSUMPTION,
            "damage": cls.DAMAGE_RESPONSE,
        }

        category_factors = categories.get(category)
        if category_factors:
            return category_factors.get(factor_name)
        return None

    @classmethod
    def get_weather_calculation_metadata(cls) -> Dict[str, Any]:
        """Get metadata about weather calculation methods and limitations"""
        return {
            "calculation_method": "verified_epa_usda_factors",
            "data_sources": [
                "EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98) - Fuel combustion",
                "EPA eGRID2023 Summary Tables rev.2 (770.9 lb CO2e/MWh, 4.2% grid gross loss) - Electricity",
                "EIA 2023 Annual Energy Review - Electricity validation",
                "IPCC 2006/2019 Guidelines - N2O emission factors",
                "Audsley et al. 2009 / Hillier et al. 2009 - Pesticide manufacturing LCA (updated from Lal 2004)",
                "USDA NRCS Irrigation Energy Guidelines - Pump efficiency",
                "International Copper Association - Copper LCA data",
            ],
            "limitations": [
                "Equipment fuel/energy consumption rates are estimates based on manufacturer data",
                "Regional electricity emission factors vary from US average (0.365 kg CO2e/kWh)",
                "Actual consumption depends on equipment age, maintenance, and operating conditions",
                "Weather event duration and severity estimates require field validation",
                "Chemical manufacturing factors vary widely (5-30 kg CO2e/kg AI) by specific active ingredient",
            ],
            "transparency_note": "Trazo uses only published government emission factors where available. The US electricity factor is 0.365 kg CO2e/kWh delivered, derived from EPA eGRID2023 Summary Tables rev.2 (770.9 lb CO2e/MWh, 4.2% grid gross loss).",
            "last_updated": "2026-09-07",
            "verification_status": "comprehensive_audit_completed",
            "confidence_range": "80-95% depending on factor type",
            "critical_updates": [
                "2025-12-03: Electricity factor corrected from 0.821 to 0.39 kg CO2/kWh (was 2.1x too high)",
                "2025-12-03: Added detailed source citations for all chemical factors",
                "2025-12-03: Clarified nitrogen fertilizer calculation (manufacturing + N2O field emissions)",
                "2026-03-21: Herbicide factor updated from 5.5 to 6.3 kg CO2/kg AI (Lal 2004 original, better validated)",
                "2026-03-21: Pesticide source note updated to cite Audsley et al. 2009 and Hillier et al. 2009",
                "2026-03-21: last_reviewed date and cross-validation note added to chemical factors",
                "2026-09-07: Electricity factor corrected from 0.39 to 0.365 kg CO2e/kWh. 0.39 came from EPA's Equivalencies Calculator (eGRID2022, 5.12% T&D) while the citation named eGRID2023; re-derived from the cited source (770.9 lb CO2e/MWh, 4.2% grid gross loss).",
            ],
        }

    @classmethod
    def calculate_frost_protection_emissions(
        cls, temperature_f: float, protection_method: str = "heaters", area_acres: float = 1.0
    ) -> Dict[str, Any]:
        """Calculate frost protection emissions using verified factors"""

        if temperature_f > 32:
            return {
                "co2e_kg": 0.0,
                "calculation_method": "no_protection_needed",
                "breakdown": {"temperature_f": temperature_f, "protection_needed": False},
            }

        # Calculate protection hours based on temperature (ENHANCED - realistic duration)
        temp_differential = 32 - temperature_f
        # Severe frosts require longer protection periods
        if temp_differential >= 8:  # 24°F or below - severe frost
            protection_hours = 10  # All night protection
        elif temp_differential >= 4:  # 28°F - moderate frost
            protection_hours = 8  # Extended protection
        else:  # Light frost
            protection_hours = 6  # Standard protection

        # Multiple protection units per acre for commercial operations
        protection_units_per_acre = 2  # Calibrated for commercial orchards/vineyards

        if protection_method == "heaters":
            # Use EPA diesel emission factor
            diesel_factor = cls.EPA_DIESEL_FACTORS["diesel_fuel"]
            equipment_consumption = cls.EQUIPMENT_CONSUMPTION["orchard_heater"]

            # Calculate fuel consumption and emissions (ENHANCED - multiple units)
            fuel_gallons = equipment_consumption.value * protection_hours * area_acres * protection_units_per_acre
            co2e_kg = fuel_gallons * diesel_factor.value

            breakdown = {
                "protection_method": "diesel_orchard_heaters",
                "temperature_f": temperature_f,
                "protection_hours": protection_hours,
                "area_acres": area_acres,
                "fuel_gallons": fuel_gallons,
                "protection_units_per_acre": protection_units_per_acre,
                "diesel_emission_factor_kg_per_gallon": diesel_factor.value,
                "equipment_consumption_gallons_per_hour": equipment_consumption.value,
                "confidence_level": min(diesel_factor.confidence_level, equipment_consumption.confidence_level),
            }

        elif protection_method == "wind_machines":
            # Use EPA electricity emission factor
            electricity_factor = cls.get_country_electricity_factor()
            equipment_consumption = cls.EQUIPMENT_CONSUMPTION["wind_machine"]

            # Calculate electricity consumption and emissions (ENHANCED - multiple units)
            kwh_consumed = equipment_consumption.value * protection_hours * area_acres * protection_units_per_acre
            co2e_kg = kwh_consumed * electricity_factor.value

            breakdown = {
                "protection_method": "electric_wind_machines",
                "temperature_f": temperature_f,
                "protection_hours": protection_hours,
                "area_acres": area_acres,
                "kwh_consumed": kwh_consumed,
                "protection_units_per_acre": protection_units_per_acre,
                "electricity_emission_factor_kg_per_kwh": electricity_factor.value,
                "equipment_consumption_kwh_per_hour": equipment_consumption.value,
                "confidence_level": min(electricity_factor.confidence_level, equipment_consumption.confidence_level),
            }
        else:
            # Default to heaters for unknown protection methods
            return cls.calculate_frost_protection_emissions(temperature_f, "heaters", area_acres)

        return {
            "co2e_kg": round(co2e_kg, 3),
            "calculation_method": "verified_epa_factors",
            "breakdown": breakdown,
            "data_sources": [
                diesel_factor.source if protection_method == "heaters" else electricity_factor.source,
                equipment_consumption.source,
            ],
            "limitations": equipment_consumption.notes,
        }

    # Item #13: Electricity emission factors by source (kg CO2/kWh)
    # Used when electricity_source is set on a ProductionEvent irrigation event.
    # F08 fix (2026-06): "grid" intentionally NOT in this dict. A literal grid
    # constant (0.39, US) bypassed the per-country factor — a UY grid-irrigation
    # event was reported at US 0.39 instead of the true UY grid (~0.006). With
    # "grid" absent, every lookup site (the `electricity_source in …` guard at
    # ~L795 and the `.get(source, electricity_factor.value)` fallbacks at ~L1228,
    # ~L1240) falls through to get_country_electricity_factor(), which honours
    # TRAZO_OPERATING_COUNTRY. Only genuinely source-specific factors (renewables,
    # on-site generator) belong here.
    ELECTRICITY_SOURCE_FACTORS = {
        "solar": 0.02,  # Life-cycle average for utility-scale solar PV
        "wind": 0.01,  # Life-cycle average for wind turbines
        "diesel_generator": 0.65,  # Diesel generator (less efficient than grid diesel)
        "mixed": 0.20,  # Blended renewable + grid assumption
    }

    # Energy required to lift one acre-foot of water one foot, at 100% efficiency.
    # Physics, not an emission factor: 1 ac-ft = 1233.5 m³ = 1.2335e6 kg; lifting it 1 ft
    # (0.3048 m) takes m·g·h = 3.688e6 J = 1.0241 kWh. This is the constant in the standard
    # irrigation pumping-energy equation used by USBR/NRCS and the CPUC groundwater studies:
    #     kWh per acre-foot = 1.0241 × TDH_ft / OPE
    KWH_PER_ACRE_FOOT_PER_FOOT_OF_LIFT = 1.0241

    GALLONS_PER_ACRE_FOOT = 325_851.0

    # Overall pumping-plant efficiency (wire-to-water): motor × pump × drive losses.
    # 0.70 is a reasonable mid-range for a maintained agricultural plant; well-maintained
    # plants reach ~0.75 and neglected ones fall below 0.50. Conservative in the sense that
    # a LOWER efficiency yields HIGHER emissions, so this does not understate impact.
    DEFAULT_PUMPING_PLANT_EFFICIENCY = 0.70

    # Pressure the system must add on top of the lift, by irrigation method (psi).
    # Converted to feet of head at 2.31 ft/psi. Without this the depth-only figure
    # understates a pressurized drip or sprinkler system, which does real work pushing
    # water through emitters, not just raising it.
    SYSTEM_PRESSURE_PSI_BY_METHOD = {
        "drip": 15.0,
        "drip_irrigation": 15.0,
        "micro_sprinkler": 30.0,
        "microsprinkler": 30.0,
        "sprinkler": 50.0,
        "center_pivot": 50.0,
        "flood": 5.0,
        "furrow": 5.0,
        "surface": 5.0,
    }
    DEFAULT_SYSTEM_PRESSURE_PSI = 20.0
    FEET_OF_HEAD_PER_PSI = 2.31

    @classmethod
    def _pump_energy_kwh_per_1000gal(
        cls,
        pump_depth_ft: float,
        irrigation_method: str = None,
        pump_efficiency: float = None,
        system_pressure_psi: float = None,
    ) -> Dict[str, Any]:
        """Pump energy from total dynamic head, via the standard pumping-energy equation.

        Replaces a previous `pump_depth_ft * 0.0175` shortcut that was labelled a
        "USDA NRCS standard pump curve". That label was fabricated — NRCS publishes no such
        curve — and the coefficient was roughly 3.9x too high: at a 120 ft lift it produced
        684 kWh/acre-foot, where CPUC's California groundwater study reports about 175
        kWh/acre-foot for a 120 ft well. Irrigation is the largest energy line in a
        California orchard, and a grower can check kWh/acre-foot against their own utility
        bill, so the error was both large and falsifiable.

        Note what the old shortcut did to incentives: the no-depth default
        (0.85 kWh/1000 gal ≈ 277 kWh/acre-foot) sat inside the real 170–600 range, so a
        farmer who supplied MORE information — their actual pump depth — got a WORSE number.
        That inverts the transparency-first premise. See the regression test in
        carbon/tests/test_irrigation_pump_energy.py.
        """
        efficiency = (
            pump_efficiency if pump_efficiency and pump_efficiency > 0 else cls.DEFAULT_PUMPING_PLANT_EFFICIENCY
        )
        # Guard against a bad parcel attribute making emissions implausibly small/large.
        efficiency = min(max(efficiency, 0.30), 0.85)

        if system_pressure_psi is None:
            system_pressure_psi = cls.SYSTEM_PRESSURE_PSI_BY_METHOD.get(
                (irrigation_method or "").lower(), cls.DEFAULT_SYSTEM_PRESSURE_PSI
            )

        pressure_head_ft = system_pressure_psi * cls.FEET_OF_HEAD_PER_PSI
        total_dynamic_head_ft = pump_depth_ft + pressure_head_ft

        kwh_per_acre_foot = cls.KWH_PER_ACRE_FOOT_PER_FOOT_OF_LIFT * total_dynamic_head_ft / efficiency
        kwh_per_1000gal = kwh_per_acre_foot / (cls.GALLONS_PER_ACRE_FOOT / 1000.0)

        return {
            "kwh_per_1000gal": kwh_per_1000gal,
            "kwh_per_acre_foot": kwh_per_acre_foot,
            "total_dynamic_head_ft": total_dynamic_head_ft,
            "pump_efficiency": efficiency,
            "system_pressure_psi": system_pressure_psi,
        }

    @classmethod
    def calculate_drought_irrigation_emissions(
        cls,
        water_volume_gallons: float,
        water_source: str = None,
        pump_depth_ft: float = None,
        electricity_source: str = None,
        irrigation_method: str = None,
        pump_efficiency: float = None,
        system_pressure_psi: float = None,
    ) -> Dict[str, Any]:
        """Calculate irrigation emissions using verified factors.

        Pump energy factor resolution order (Item #13):
        1. pump_depth_ft — if provided, compute from total dynamic head:
               kWh/acre-foot = 1.0241 × TDH / OPE,  TDH = depth + pressure head
           (see _pump_energy_kwh_per_1000gal)
        2. water_source lookup (USDA NRCS guidelines):
           - well_groundwater: 3.5 kWh/1000 gal (deep well, 200-300 ft)
           - municipal: 0.20 kWh/1000 gal (pre-pressurized)
           - rainwater_harvesting: 0.15 kWh/1000 gal (gravity-fed)
           - irrigation_canal: 0.50 kWh/1000 gal (low-lift surface pump)
           - river_stream: 0.85 kWh/1000 gal (moderate-lift)
           - pond_reservoir: 0.40 kWh/1000 gal (low-lift on-farm)
           - recycled_water: 0.30 kWh/1000 gal (pre-treated)
           - other/None: 2.0 kWh/1000 gal (US agricultural average)

        Electricity emission factor resolution order (Item #13):
        1. electricity_source — specific emission factor by source type
        2. Default: EPA eGRID2023 grid factor (0.365 kg CO2e/kWh delivered)
        """

        electricity_factor = cls.get_country_electricity_factor()

        # Item #13: Override electricity emission factor if electricity_source is specified
        if electricity_source and electricity_source in cls.ELECTRICITY_SOURCE_FACTORS:
            effective_electricity_factor_value = cls.ELECTRICITY_SOURCE_FACTORS[electricity_source]
            electricity_source_label = electricity_source.replace("_", " ").title()
        else:
            effective_electricity_factor_value = electricity_factor.value
            electricity_source_label = "Grid (EPA eGRID 2023)"

        # Item #13: Override pump factor if pump_depth_ft is provided.
        pump_head_detail = None
        if pump_depth_ft is not None and pump_depth_ft > 0:
            pump_head_detail = cls._pump_energy_kwh_per_1000gal(
                pump_depth_ft=pump_depth_ft,
                irrigation_method=irrigation_method,
                pump_efficiency=pump_efficiency,
                system_pressure_psi=system_pressure_psi,
            )
            pump_kwh_per_1000gal = pump_head_detail["kwh_per_1000gal"]
            pump_source = (
                "Irrigation pumping-energy equation (kWh/AF = 1.0241 × TDH / OPE); "
                "constant is the physical work to lift 1 acre-foot 1 foot"
            )
            pump_confidence = 0.85
            pump_notes = (
                f"Pump energy from total dynamic head: {pump_depth_ft} ft lift + "
                f"{pump_head_detail['system_pressure_psi']} psi system pressure "
                f"= {pump_head_detail['total_dynamic_head_ft']:.0f} ft TDH at "
                f"{pump_head_detail['pump_efficiency']:.0%} pumping-plant efficiency "
                f"({pump_head_detail['kwh_per_acre_foot']:.0f} kWh/acre-foot)"
            )
        elif water_source and water_source in cls.IRRIGATION_PUMP_FACTORS:
            pump_consumption = cls.IRRIGATION_PUMP_FACTORS[water_source]
            pump_kwh_per_1000gal = pump_consumption.value
            pump_source = pump_consumption.source
            pump_confidence = pump_consumption.confidence_level
            pump_notes = pump_consumption.notes
        else:
            pump_consumption = cls.IRRIGATION_PUMP_DEFAULT
            pump_kwh_per_1000gal = pump_consumption.value
            pump_source = pump_consumption.source
            pump_confidence = pump_consumption.confidence_level
            pump_notes = pump_consumption.notes

        water_source_label = cls.WATER_SOURCE_LABELS.get(water_source or "other", "Unknown")

        # Calculate electricity consumption for pumping
        kwh_consumed = (water_volume_gallons / 1000) * pump_kwh_per_1000gal
        co2e_kg = kwh_consumed * effective_electricity_factor_value

        breakdown = {
            "water_volume_gallons": water_volume_gallons,
            "kwh_consumed": kwh_consumed,
            "electricity_emission_factor_kg_per_kwh": effective_electricity_factor_value,
            "electricity_source": electricity_source or "grid",
            "electricity_source_label": electricity_source_label,
            "pump_efficiency_kwh_per_1000_gallons": pump_kwh_per_1000gal,
            "pump_depth_ft": pump_depth_ft,
            "water_source": water_source or "unknown",
            "water_source_label": water_source_label,
            "confidence_level": min(electricity_factor.confidence_level, pump_confidence),
        }

        # Surface the head build-up when it drove the calculation, so a grower (or an
        # inspector) can reconcile kWh/acre-foot against their own pump test and utility bill
        # instead of taking a single opaque coefficient on trust.
        if pump_head_detail:
            breakdown["kwh_per_acre_foot"] = round(pump_head_detail["kwh_per_acre_foot"], 1)
            breakdown["total_dynamic_head_ft"] = round(pump_head_detail["total_dynamic_head_ft"], 1)
            breakdown["pumping_plant_efficiency"] = pump_head_detail["pump_efficiency"]
            breakdown["system_pressure_psi"] = pump_head_detail["system_pressure_psi"]
            breakdown["irrigation_method"] = irrigation_method

        return {
            "co2e_kg": round(co2e_kg, 3),
            "calculation_method": "verified_epa_usda_factors",
            "breakdown": breakdown,
            "data_sources": [electricity_factor.source, pump_source],
            "limitations": pump_notes,
        }

    @classmethod
    def calculate_hailstorm_response_emissions(
        cls, hail_severity: float = 5.0, damage_duration_hours: float = 2.0, area_acres: float = 1.0
    ) -> Dict[str, Any]:
        """Calculate hailstorm response emissions using verified factors"""

        # Get verified EPA diesel emission factor
        diesel_factor = cls.EPA_DIESEL_FACTORS["diesel_fuel_mobile"]
        cleanup_factor = cls.DAMAGE_RESPONSE["debris_cleanup"]
        repair_factor = cls.DAMAGE_RESPONSE["hail_protection_repair"]

        # Calculate response activities based on severity (0-10 scale)
        severity_factor = min(hail_severity / 10.0, 1.0)

        # Cleanup operations (debris removal, damaged crop removal)
        cleanup_hours = damage_duration_hours * severity_factor * 2  # Cleanup takes 2x damage duration
        cleanup_fuel = cleanup_hours * cleanup_factor.value * area_acres
        cleanup_emissions = cleanup_fuel * diesel_factor.value

        # Protection system repair (netting, structures, irrigation)
        repair_hours = hail_severity * 0.5 * area_acres  # 0.5 hours per severity point per acre
        repair_fuel = repair_hours * repair_factor.value
        repair_emissions = repair_fuel * diesel_factor.value

        total_emissions = cleanup_emissions + repair_emissions

        breakdown = {
            "weather_event": "hailstorm",
            "hail_severity_0_10": hail_severity,
            "damage_duration_hours": damage_duration_hours,
            "area_acres": area_acres,
            "cleanup_hours": cleanup_hours,
            "cleanup_fuel_gallons": cleanup_fuel,
            "cleanup_emissions_kg": cleanup_emissions,
            "repair_hours": repair_hours,
            "repair_fuel_gallons": repair_fuel,
            "repair_emissions_kg": repair_emissions,
            "diesel_emission_factor_kg_per_gallon": diesel_factor.value,
            "confidence_level": min(
                diesel_factor.confidence_level, cleanup_factor.confidence_level, repair_factor.confidence_level
            ),
        }

        return {
            "co2e_kg": round(total_emissions, 3),
            "calculation_method": "verified_epa_factors",
            "breakdown": breakdown,
            "data_sources": [diesel_factor.source, cleanup_factor.source, repair_factor.source],
            "limitations": "Hailstorm response emissions vary significantly with crop type, protection systems, and damage severity",
        }

    @classmethod
    def calculate_high_winds_response_emissions(
        cls, wind_speed_mph: float = 45.0, duration_hours: float = 6.0, area_acres: float = 1.0
    ) -> Dict[str, Any]:
        """Calculate high winds response emissions using verified factors"""

        # Get verified EPA diesel emission factor
        diesel_factor = cls.EPA_DIESEL_FACTORS["diesel_fuel_mobile"]
        repair_factor = cls.DAMAGE_RESPONSE["wind_damage_repair"]

        # Calculate wind damage severity based on speed
        if wind_speed_mph >= 60:  # Severe wind damage
            damage_severity = 1.0
        elif wind_speed_mph >= 45:  # Moderate wind damage
            damage_severity = 0.7
        elif wind_speed_mph >= 30:  # Light wind damage
            damage_severity = 0.4
        else:  # Minimal damage
            damage_severity = 0.1

        # Wind damage repair operations
        repair_hours = duration_hours * damage_severity * area_acres
        repair_fuel = repair_hours * repair_factor.value
        repair_emissions = repair_fuel * diesel_factor.value

        breakdown = {
            "weather_event": "high_winds",
            "wind_speed_mph": wind_speed_mph,
            "duration_hours": duration_hours,
            "area_acres": area_acres,
            "damage_severity_factor": damage_severity,
            "repair_hours": repair_hours,
            "repair_fuel_gallons": repair_fuel,
            "diesel_emission_factor_kg_per_gallon": diesel_factor.value,
            "confidence_level": min(diesel_factor.confidence_level, repair_factor.confidence_level),
        }

        return {
            "co2e_kg": round(repair_emissions, 3),
            "calculation_method": "verified_epa_factors",
            "breakdown": breakdown,
            "data_sources": [diesel_factor.source, repair_factor.source],
            "limitations": "Wind damage varies significantly with crop type, support structures, and terrain exposure",
        }

    # Keywords that indicate manual labor in a farmer's free-text "method" field.
    # Used by _is_manual_method() to short-circuit USDA blanket averages when the
    # farmer explicitly documents hand-only work.
    _MANUAL_METHOD_KEYWORDS = (
        "hand",  # hand thinning, hand harvest, hand pruning, by hand
        "manual",  # manual work, manual operation, manual labor
        "shears",  # pruning shears, hand shears
        "handheld",  # handheld tools only
        "a mano",  # Spanish: by hand
        "a pie",  # Spanish: on foot / manual
    )
    _MECHANICAL_METHOD_KEYWORDS = (
        "mechanical",
        "tractor",
        "harvester",
        "sprayer",
        "machine",
        "powered",
        "motorized",
    )
    # Structured harvest_method dropdown values that represent manual/hand labor.
    # Matched by exact value (not substring) so we don't get false positives on
    # free-text like "strip-cleaned by machine". Dropdown values are defined in
    # ProductionTab.jsx / HARVEST_METHOD_LABELS (productionEvent.ts). `shake_and_catch`
    # is mechanical (tree shaker + catcher) so intentionally excluded; `mixed` is
    # ambiguous (manual + mechanical) and defaults to mechanical routing via the
    # USDA averages path.
    _STRUCTURED_MANUAL_HARVEST_VALUES = frozenset(
        {
            "hand_picking",
            "selective_hand_picking",
            "strip_picking",  # Hand stripping (berries, olives, tea leaves)
            "manual",
        }
    )

    @classmethod
    def _is_manual_method(cls, method: str = None) -> bool:
        """Detect manual/hand-labor operations from a method field.

        Trazo's Direct Operational Emissions philosophy: carbon calculations should
        reflect what the farmer *actually did*. When the farmer documents manual
        methods (hand thinning, pruning shears, etc.), applying mechanical USDA
        averages produces incorrect carbon values that penalize transparency.

        Handles two input shapes:
          1. Structured dropdown value (e.g. "hand_picking", "strip_picking") —
             exact-match against `_STRUCTURED_MANUAL_HARVEST_VALUES`.
          2. Free-text description (e.g. "Hand thinning with pruning shears",
             "by hand") — keyword search with mechanical-wins tie-break.

        Returns True only when manual is indicated AND no mechanical keyword is
        present (mechanical wins on ambiguous strings like "tractor-mounted hand
        sprayer").
        """
        if not method:
            return False
        method_lower = method.lower().strip()
        # 1. Structured dropdown exact-match — reliable, no substring false-positives
        if method_lower in cls._STRUCTURED_MANUAL_HARVEST_VALUES:
            return True
        # 2. Free-text keyword search — mechanical wins precedence
        if any(kw in method_lower for kw in cls._MECHANICAL_METHOD_KEYWORDS):
            return False
        return any(kw in method_lower for kw in cls._MANUAL_METHOD_KEYWORDS)

    @classmethod
    def production_type_codes(cls):
        """Every production code this class can route. Read by the subtype-coverage guard."""
        return set(cls._production_type_mapping())

    @classmethod
    def _production_type_mapping(cls):
        """Production subtype code -> the calculator that knows its physical model.

        Hoisted out of `calculate_production_event_emissions` (2026-08-22) so a guard can read
        the real mapping instead of a hand-copied list. `test_non_area_driven_subtypes_carbon`
        asserts every code in `ProductionEvent.PRODUCTION_EVENTS` appears here — an unmapped
        code silently collects the 2.5 gal/hectare general-production estimate, which is a
        decision nobody made.
        """
        return {
            # Standard codes (primary)
            "PL": cls._calculate_planting_emissions,
            "HA": cls._calculate_harvesting_emissions,
            "IR": cls.calculate_drought_irrigation_emissions,
            "TR": cls._calculate_transplanting_emissions,
            "CU": cls._calculate_cultivation_emissions,
            "TH": cls._calculate_thinning_emissions,
            "PR": lambda ac, fc, eh, **kw: cls._calculate_manual_operation_emissions(ac, fc, eh, "pruning", **kw),
            "EM": cls._calculate_general_production_emissions,
            "CM": lambda ac, fc, eh, **kw: cls._calculate_manual_operation_emissions(
                ac, fc, eh, "canopy_management", **kw
            ),  # Canopy management (leaf pulling, hedging) - same fuel profile as pruning
            # Batch 3 (2026-06): frost protection & mowing are fuel-driven equipment
            # operations — use the general-production calculator (honours reported
            # fuel_consumed; falls back to a light area-based estimate) like EM.
            "FP": cls._calculate_general_production_emissions,
            "MO": cls._calculate_general_production_emissions,
            # A7 (2026-07): post-harvest is facility energy, not field fuel — it had no entry
            # here and was silently charged the general per-hectare diesel estimate.
            "PH": cls._calculate_postharvest_emissions,
            # PO (2026-08-20): pollination had NO entry here, so it fell through to the
            # unknown-code fallback and was charged the general production estimate —
            # 2.5 gal diesel/hectare, 6.198 kg CO2e for 0.6 acres of bees doing their job.
            # The SAVED path (EventCarbonCalculator, `elif event.type == "PO"`) has always
            # returned 0.0 with `zero_emission_biological_service`, so preview and saved
            # disagreed on the same event — the divergence class the IR parity suite exists
            # to catch. The wizard also renders "no fuel burned, so no direct emissions"
            # for PO, which sat directly above a non-zero number.
            "PO": cls._calculate_pollination_emissions,
            # TP/BU/SS (2026-08-20): also absent from this map, also charged the general
            # 2.5 gal/ha field estimate — 6.198 kg on 0.6 acres for documenting a seed
            # search. None of the three is area-driven; see
            # `_calculate_reported_fuel_only_emissions`.
            "TP": cls._calculate_reported_fuel_only_emissions,
            "BU": cls._calculate_reported_fuel_only_emissions,
            "SS": cls._calculate_reported_fuel_only_emissions,
            # Full name aliases (safety net for any code path that passes descriptive names)
            "PLANTING": cls._calculate_planting_emissions,
            "HARVESTING": cls._calculate_harvesting_emissions,
            "IRRIGATION": cls.calculate_drought_irrigation_emissions,
            "TRANSPLANTING": cls._calculate_transplanting_emissions,
            "CULTIVATION": cls._calculate_cultivation_emissions,
            "THINNING": cls._calculate_thinning_emissions,
            "PRUNING": lambda ac, fc, eh, **kw: cls._calculate_manual_operation_emissions(ac, fc, eh, "pruning", **kw),
            "CANOPY_MANAGEMENT": lambda ac, fc, eh, **kw: cls._calculate_manual_operation_emissions(
                ac, fc, eh, "canopy_management", **kw
            ),
        }

    #: Run 8 (R8-04, 2026-10-05). Work that is not driven by area: a number for it can only come
    #: from fuel or energy the operator reported.
    NOT_AREA_DRIVEN_CODES = ("EM", "PH", "TP", "BU", "SS")

    @classmethod
    def not_estimated_result(cls, production_type_code: str, reason: str) -> Dict[str, Any]:
        """The answer when the record holds nothing to compute from: no number, and why."""
        return {
            "co2e_kg": 0.0,  # numeric for callers that do arithmetic; never stored (see signals)
            "not_estimated": True,
            "calculation_method": "not_estimated",
            "verification_status": "not_estimated",
            "breakdown": {
                "production_activity": production_type_code,
                "calculation_basis": "not_estimated",
                "confidence_level": 0.0,
                "carbon_notes": reason,
            },
            "data_sources": [],
            "limitations": reason,
            "validation_warnings": [],
        }

    @classmethod
    def calculate_production_event_emissions(
        cls,
        production_type: str,
        area_covered: float,
        fuel_consumed: float = None,
        equipment_hours: float = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Production-event emissions, or `not_estimated` when the record holds nothing to count.

        Run 8 (R8-04, Astra 2026-10-05): a post-harvest cleanout saved with no fuel was shown as
        129 kg CO2e with an EPA/USDA badge, while its edit form previewed 0. The saved path
        borrowed the PARCEL's area and charged a per-hectare diesel estimate on it; the preview
        did neither. Unknown is not zero and not a guess, so a number now exists only when the
        record holds what it is computed from:
          * reported fuel or energy, for any activity;
          * the area recorded ON THE EVENT, for field work estimated per hectare.
        Otherwise the result is `not_estimated` and nothing is stored. A per-hectare result is
        marked `area_estimate`, so no surface presents it as a reported-fuel figure.
        """
        code = (production_type or "").strip().upper()
        try:
            fuel_reported = float(fuel_consumed) > 0 if fuel_consumed not in (None, "") else False
        except (TypeError, ValueError):
            fuel_reported = False
        energy_reported = any(float(kwargs.get(k) or 0) > 0 for k in ("fuel_consumed_kwh", "processing_energy_kwh"))
        if code in cls.NOT_AREA_DRIVEN_CODES and not (fuel_reported or energy_reported):
            return cls.not_estimated_result(
                code, "No fuel or energy recorded for this activity, so there is nothing to estimate from."
            )
        result = cls._calculate_production_event_emissions_raw(
            production_type, area_covered, fuel_consumed, equipment_hours, **kwargs
        )
        basis = (result.get("breakdown") or {}).get("calculation_basis")
        if basis == "usda_standard_per_hectare":
            try:
                area = float(area_covered or 0)
            except (TypeError, ValueError):
                area = 0.0
            if area <= 0:
                return cls.not_estimated_result(
                    code,
                    "No fuel recorded and no area recorded on this activity, so there is nothing to estimate from.",
                )
            result["verification_status"] = "area_estimate"
            result.setdefault("breakdown", {})[
                "estimate_note"
            ] = "Estimated from the area recorded on this activity with a per-hectare fuel factor; no fuel was recorded."
        return result

    @classmethod
    def _calculate_production_event_emissions_raw(
        cls,
        production_type: str,
        area_covered: float,
        fuel_consumed: float = None,
        equipment_hours: float = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Calculate production event emissions using verified EPA/USDA factors

        Production types map to database model codes:
        - PL: Planting
        - HA: Harvesting
        - IR: Irrigation
        - PR: Pruning
        - TR: Transplanting
        - EM: Equipment Maintenance
        - CU: Cultivation
        - TH: Thinning
        """

        PRODUCTION_TYPE_MAPPING = cls._production_type_mapping()

        # Normalize production type to uppercase (database stores uppercase codes)
        production_type_code = production_type.strip().upper()

        # For electric equipment, fuel_consumed is None because the preview pipeline
        # converts fuel to gallons (inapplicable for kWh). The actual kWh value is
        # passed via fuel_consumed_kwh kwarg. Promote it to fuel_consumed so all
        # downstream calculators see actual consumption instead of falling back to
        # area-based estimation. Use `is None` (not falsy) so an explicit 0 from the
        # farmer is respected, not overwritten.
        if fuel_consumed is None and kwargs.get("fuel_type") == "electric":
            fuel_consumed = kwargs.get("fuel_consumed_kwh")

        # METHOD-AWARE SHORT-CIRCUIT (Trazo Direct Operational Emissions philosophy):
        # If the farmer documented a manual method (hand thinning, hand harvest, pruning
        # shears, etc.) AND didn't report fuel consumption or a powered-equipment fuel
        # type, route to the manual operation calculator (~0.1 kg CO2e/acre) instead of
        # applying USDA blanket averages (which assume mechanical operations).
        #
        # NOTE on `equipment_hours`: the form label "Equipment Operating Hours" is
        # ambiguous — farmers documenting a hand harvest often fill it with crew-hours
        # (e.g. 5 days × 8 hours = 40) rather than tractor-hours. We therefore gate on
        # `fuel_type` instead: if no fuel_type was selected (or it's an empty string),
        # the farmer is explicitly signalling "no powered equipment" and the 40 hours
        # are worker hours. This matches the form helper text: "Select a fuel type
        # only if powered equipment was used. Leave blank for hand/manual operations."
        method = kwargs.get("method")
        fuel_type_kw = (kwargs.get("fuel_type") or "").strip().lower()
        # Fuel takes priority over manual detection. If the farmer reported *any*
        # positive fuel consumption (bin transport ATV, auxiliary diesel, etc.),
        # we MUST honor it — even if method="hand_picking" or method="Hand thinning".
        # Example: hand avocado harvest with 8 gal diesel for bin-hauling ATV must
        # produce 8 × 10.21 = 81.68 kg CO2e via the harvesting calculator, not the
        # 0.1 kg/acre manual shortcut. `not fuel_consumed` treats None/0/"" as "no
        # fuel reported" — farmers who explicitly enter 0 get manual routing (correct).
        try:
            fuel_value_numeric = float(fuel_consumed) if fuel_consumed is not None else 0.0
        except (TypeError, ValueError):
            fuel_value_numeric = 0.0
        no_powered_equipment = fuel_value_numeric <= 0 and fuel_type_kw in ("", "none")
        if (
            cls._is_manual_method(method)
            and no_powered_equipment
            and production_type_code in ("TH", "HA", "PL", "PR", "TR", "CU", "CM")
        ):
            # Use the same friendly labels as the USDA-averaged branch so the frontend
            # renders "Manual Thinning" / "Manual Pruning" instead of truncation
            # artifacts like "Manual Th" / "Manual Pr" (subtype code capitalized).
            friendly_labels = {
                "TH": "thinning",
                "HA": "harvesting",
                "PL": "planting",
                "PR": "pruning",
                "TR": "transplanting",
                "CU": "cultivation",
                "CM": "canopy_management",
            }
            friendly_label = friendly_labels.get(production_type_code, production_type_code.lower())
            result = cls._calculate_manual_operation_emissions(
                area_covered,
                None,
                None,
                operation_type=f"manual_{friendly_label}",
            )
            # Enrich breakdown with farmer-documented context
            result["breakdown"]["method_documented"] = method
            result["breakdown"]["manual_operation_detected"] = True
            result["breakdown"]["production_type_code"] = production_type_code
            result["limitations"] = (
                "Manual operation detected from documented method — emissions reflect "
                "hand-tool wear and worker logistics only (no fuel, no powered equipment)."
            )
            return result

        # Get the calculation method for this production type
        if production_type_code in PRODUCTION_TYPE_MAPPING:
            calc_method = PRODUCTION_TYPE_MAPPING[production_type_code]

            # Special handling for irrigation which can use diesel or electric pumps
            # SPRINT 6 FIX (2025-12-25): Support diesel-powered irrigation pumps
            # 2026-04-10 FIX: Don't silently drop pump emissions when electricity_source
            # is set alongside diesel fuel. `electricity_source` explicitly identifies
            # the pump as electric, so any diesel reported is auxiliary (service truck,
            # maintenance tractor, etc.) and must be ADDED to pump emissions — unless
            # the selected power source is "diesel_generator", in which case the
            # generator fuel is already baked into the 0.65 kg CO2e/kWh factor.
            if production_type_code == "IR":
                fuel_type = kwargs.get("fuel_type", "electric")  # Default to electric for irrigation
                energy_source = kwargs.get("energy_source", "grid")
                explicit_electricity_source = kwargs.get("electricity_source")

                # Semantic classification of the reported diesel fuel (if any):
                #
                #   electricity_source  fuel_type  fuel_consumed  →  interpretation
                #   ------------------  ---------  -------------  ------------------
                #   (not set)           diesel     > 0            →  diesel pump fuel (direct calc)
                #   diesel_generator    diesel     > 0            →  generator fuel (already in 0.65 factor)
                #   grid/solar/wind/mix diesel     > 0            →  auxiliary equipment (add on top)
                #   any                 electric   -              →  electric — handled elsewhere
                #
                has_diesel_fuel = bool(fuel_consumed) and fuel_type == "diesel"
                # Diesel pump: the only case where fuel_consumed *replaces* the
                # water-volume-based pump calc. Requires diesel fuel AND no explicit
                # electric power source. A "diesel_generator" selection means the pump
                # is electric (driven by a generator) — not a diesel mechanical pump.
                diesel_pump_mode = has_diesel_fuel and not explicit_electricity_source
                # Auxiliary diesel: reported alongside a non-diesel electric pump.
                # Grid/solar/wind/mixed pumps cannot have burned the reported diesel,
                # so it must be auxiliary (service vehicle, standby tractor, etc.).
                # "diesel_generator" is EXCLUDED to avoid double-counting — its 0.65
                # kg CO2e/kWh factor already amortizes generator diesel consumption.
                add_auxiliary_diesel = (
                    has_diesel_fuel
                    and explicit_electricity_source
                    and explicit_electricity_source != "diesel_generator"
                )

                if diesel_pump_mode:
                    diesel_factor = cls.EPA_DIESEL_FACTORS["agricultural_equipment"]
                    co2e_kg = float(fuel_consumed) * diesel_factor.value
                    breakdown = {
                        "production_activity": "irrigation",
                        "fuel_type": "diesel",
                        "actual_fuel_consumed_gallons": float(fuel_consumed),
                        "diesel_emission_factor_kg_per_gallon": diesel_factor.value,
                        "calculation_basis": "actual_diesel_consumption",
                        "confidence_level": diesel_factor.confidence_level,
                        "note": "Diesel-powered irrigation pump - actual fuel consumption provided",
                    }
                    return {
                        "co2e_kg": round(co2e_kg, 3),
                        "calculation_method": "verified_epa_diesel_irrigation",
                        "breakdown": breakdown,
                        "data_sources": [diesel_factor.source],
                        "limitations": "Diesel-powered irrigation is less common but used for mobile/remote systems",
                    }

                # Electric irrigation pump (grid / solar / wind / mixed / diesel_generator)
                # Resolve electricity_source → emission factor override
                # electricity_source (form field) takes precedence over energy_source (generic)
                electricity_source = explicit_electricity_source
                effective_energy_source = electricity_source or energy_source

                # Compute water volume from area × irrigation_depth when available
                # This is more accurate than text-based heuristics
                GALLONS_PER_INCH_PER_ACRE = 27154.0
                irrigation_depth_inches = kwargs.get("irrigation_depth_inches")
                water_gallons = kwargs.get("water_volume_gallons")
                if not water_gallons and area_covered and irrigation_depth_inches:
                    water_gallons = area_covered * irrigation_depth_inches * GALLONS_PER_INCH_PER_ACRE
                elif not water_gallons and area_covered:
                    # Fallback: crude estimate (1 inch default)
                    water_gallons = area_covered * 1.0 * GALLONS_PER_INCH_PER_ACRE

                pump_depth_ft = kwargs.get("pump_depth_ft")

                fuel_consumed_kwh = kwargs.get("fuel_consumed_kwh")
                if fuel_consumed_kwh and fuel_consumed_kwh > 0 and not water_gallons:
                    # Farmer provided actual kWh but no water volume — use kWh directly
                    electricity_factor = cls.get_country_electricity_factor()
                    if effective_energy_source in ["solar", "wind"]:
                        effective_factor = cls.ELECTRICITY_SOURCE_FACTORS.get(effective_energy_source, 0.02)
                        co2e_kg = fuel_consumed_kwh * effective_factor
                        calc_basis = f"actual_electric_consumption_{effective_energy_source}"
                    else:
                        co2e_kg = fuel_consumed_kwh * electricity_factor.value
                        calc_basis = "actual_electric_consumption_grid"
                    breakdown = {
                        "production_activity": "irrigation",
                        "fuel_type": "electric",
                        "actual_kwh_consumed": fuel_consumed_kwh,
                        "kwh_consumed": fuel_consumed_kwh,
                        "electricity_emission_factor_kg_per_kwh": (
                            cls.ELECTRICITY_SOURCE_FACTORS.get(effective_energy_source, electricity_factor.value)
                        ),
                        "energy_source": effective_energy_source,
                        "electricity_source": effective_energy_source,
                        "area_covered_acres": area_covered,
                        "water_volume_gallons": 0,
                        "calculation_basis": calc_basis,
                        "confidence_level": electricity_factor.confidence_level,
                        "note": "Electric irrigation pump - actual kWh provided by farmer, no water volume available",
                    }
                    return {
                        "co2e_kg": round(co2e_kg, 3),
                        "calculation_method": "verified_epa_electric_irrigation",
                        "breakdown": breakdown,
                        "data_sources": [electricity_factor.source],
                        "limitations": "Based on farmer-reported electricity consumption",
                    }

                # Water-volume-based calculation (primary path for irrigation)
                # Computes pump energy from water volume × pump factor × electricity factor
                if not water_gallons:
                    water_gallons = area_covered * 1000 if area_covered else 0
                pump_result = calc_method(
                    water_gallons,
                    water_source=kwargs.get("water_source"),
                    pump_depth_ft=pump_depth_ft,
                    electricity_source=electricity_source,
                    # Threaded so the pressure component of total dynamic head matches the
                    # system: a drip line needs ~15 psi, a sprinkler ~50. pump_efficiency /
                    # system_pressure_psi come from the parcel's pump test when recorded
                    # (falling back to defaults), so a farmer who measures gets a figure
                    # matching their own plant rather than a generic one.
                    irrigation_method=kwargs.get("irrigation_method"),
                    pump_efficiency=kwargs.get("pump_efficiency"),
                    system_pressure_psi=kwargs.get("system_pressure_psi"),
                )

                # Record the pump-only emissions as a first-class breakdown field so
                # the frontend doesn't have to re-derive it from kWh × factor. Keeps
                # one source of truth when aux diesel is added below.
                pump_only_kg = round(float(pump_result.get("co2e_kg", 0.0)), 3)
                pump_result.setdefault("breakdown", {})["pump_electricity_emissions_kg"] = pump_only_kg

                # 2026-04-10 FIX: When the pump is explicitly electric (grid/solar/wind/
                # mixed — NOT diesel_generator) but the farmer ALSO reports diesel fuel,
                # that diesel must be auxiliary equipment (service vehicle, standby
                # tractor, maintenance) and is ADDED on top of pump electricity.
                if add_auxiliary_diesel:
                    diesel_factor = cls.EPA_DIESEL_FACTORS["agricultural_equipment"]
                    aux_diesel_kg = round(float(fuel_consumed) * diesel_factor.value, 3)
                    pump_result["co2e_kg"] = round(pump_only_kg + aux_diesel_kg, 3)
                    breakdown = pump_result["breakdown"]
                    breakdown["auxiliary_diesel_fuel_gallons"] = float(fuel_consumed)
                    breakdown["auxiliary_diesel_emissions_kg"] = aux_diesel_kg
                    breakdown["auxiliary_diesel_emission_factor_kg_per_gallon"] = diesel_factor.value
                    breakdown["auxiliary_diesel_note"] = (
                        "Diesel fuel reported alongside electric pump — counted as "
                        "auxiliary equipment (service vehicle, standby tractor, or "
                        "maintenance) in addition to pump electricity."
                    )
                    pump_result.setdefault("data_sources", []).append(diesel_factor.source)
                    # Append (don't clobber) so downstream EPA-badge detection still
                    # matches `verified_epa_usda_factors` prefix checks.
                    pump_result["calculation_method"] = (
                        pump_result.get("calculation_method", "verified_epa_usda_factors") + "+auxiliary_diesel"
                    )

                return pump_result
            else:
                return calc_method(
                    area_covered, fuel_consumed, equipment_hours, production_type_code=production_type_code, **kwargs
                )
        else:
            # Fallback for unknown production types — log a warning so silent
            # miscalculations are visible in production (Trazo carbon correctness).
            logger.warning(
                "Unknown production_type_code=%r — falling back to general production "
                "factor (2.5 gal/ha). Add this code to PRODUCTION_TYPE_MAPPING if it "
                "represents a distinct operation.",
                production_type_code,
            )
            return cls._calculate_general_production_emissions(
                area_covered, fuel_consumed, equipment_hours, production_type_code=production_type_code, **kwargs
            )

    @classmethod
    def _calculate_reported_fuel_only_emissions(
        cls, area_covered: float, fuel_consumed: float = None, equipment_hours: float = None, **kwargs
    ) -> Dict[str, Any]:
        """Count fuel the operator actually reported. Never estimate from acreage.

        For TP (a load moving off-farm), BU (§ 205.202(c) buffer harvest/disposal) and
        SS (§ 205.204(a)(1) organic-seed availability search), a per-hectare field-diesel
        rate is the wrong physical model:

          * SS is a phone-and-catalogue search. It burns nothing.
          * BU is a recordkeeping act about a boundary strip.
          * TP scales with DISTANCE and load, not with the parcel's area. Charging it
            2.5 gal/hectare of the parcel it left is meaningless.

        None of the three had an entry in PRODUCTION_TYPE_MAPPING, so all three hit the
        unknown-code fallback and were charged the general field-operation estimate —
        6.198 kg CO2e on 0.6 acres for documenting a seed search. Same defect as PO.

        Reported fuel still counts: haul diesel is a real direct emission, and an operator
        who enters it should see it.
        """
        fuel_type = kwargs.get("fuel_type") or "diesel"
        energy_source = kwargs.get("energy_source", "grid")
        area_covered = float(area_covered or 0)

        breakdown: Dict[str, Any] = {
            "production_activity": kwargs.get("production_type_code", "reported_fuel_only"),
            "area_covered_acres": area_covered,
            "area_covered_hectares": area_covered * 0.404686,
            "fuel_type": fuel_type,
            "calculation_basis": "reported_fuel_only",
            "confidence_level": 1.0,
            "carbon_notes": (
                "Counted from reported fuel only. This activity is not area-driven, so no "
                "per-hectare estimate is applied when no fuel is entered."
            ),
        }

        if not fuel_consumed:
            breakdown["confidence_level"] = 1.0
            return {
                "co2e_kg": 0.0,
                "calculation_method": "reported_fuel_only",
                "breakdown": breakdown,
                "data_sources": ["Trazo Methodology - non-area-driven activity, reported fuel only"],
                "limitations": "No fuel reported. Excludes off-farm transport distance not captured on this record.",
                "validation_warnings": [],
            }

        if fuel_type == "electric":
            electricity_factor = cls.get_country_electricity_factor()
            factor = cls.ELECTRICITY_SOURCE_FACTORS.get(energy_source, electricity_factor.value)
            co2e_kg = float(fuel_consumed) * factor
            breakdown["electricity_emission_factor_kg_per_kwh"] = factor
            breakdown["actual_fuel_consumed_kWh"] = float(fuel_consumed)
            emission_factor = electricity_factor
        else:
            co2e_kg, emission_factor, _unit_error = cls.fuel_co2e(fuel_consumed, fuel_type, kwargs.get("fuel_unit"))
            breakdown["diesel_emission_factor_kg_per_gallon"] = emission_factor.value
            breakdown["fuel_emission_factor_kg_per_unit"] = emission_factor.value
            breakdown["actual_fuel_consumed_gallons"] = float(fuel_consumed)

        # No per-area factor exists for these activities, so the "assumed rate" half of
        # fuel_basis is deliberately the emission factor itself — there is nothing assumed.
        cls._annotate_fuel_basis(breakdown, emission_factor, emission_factor, fuel_consumed)

        return {
            "co2e_kg": round(co2e_kg, 3),
            "calculation_method": "reported_fuel_only",
            "breakdown": breakdown,
            "data_sources": [emission_factor.source],
            "limitations": "Excludes off-farm transport distance not captured on this record.",
            "validation_warnings": [],
        }

    @classmethod
    def _calculate_pollination_emissions(
        cls, area_covered: float, fuel_consumed: float = None, equipment_hours: float = None, **kwargs
    ) -> Dict[str, Any]:
        """Pollination (PO): a biological service, zero DIRECT operational emissions.

        Placing hives is work bees do. There is no fuel combustion and no powered
        equipment in the operation itself, so under the direct-operational scope
        (`carbon-methodology.md`) it contributes nothing. Hive DELIVERY fuel is a
        transport emission outside that boundary and is stated as a limitation rather
        than silently folded in.

        Mirrors `EventCarbonCalculator.calculate_production_event_impact`'s PO branch so
        the preview and the saved record agree on the same event.
        """
        area_covered = float(area_covered or 0)
        return {
            "co2e_kg": 0.0,
            "calculation_method": "zero_emission_biological_service",
            "breakdown": {
                "production_activity": "pollination",
                "area_covered_acres": area_covered,
                "area_covered_hectares": area_covered * 0.404686,
                "carbon_impact": "zero",
                "calculation_basis": "zero_emission_biological_service",
                "confidence_level": 1.0,
                "carbon_notes": (
                    "Pollination is a biological service performed by bees or other "
                    "pollinators. No direct fuel combustion or chemical inputs are involved."
                ),
            },
            "data_sources": ["Trazo Methodology - Biological pollination services produce zero direct emissions"],
            "limitations": "Excludes indirect transportation emissions for hive delivery/pickup",
            "validation_warnings": [],
        }

    @classmethod
    def _annotate_fuel_basis(
        cls,
        breakdown: Dict[str, Any],
        emission_factor: EmissionFactor,
        per_area_factor: EmissionFactor,
        fuel_consumed: Optional[float],
    ) -> Dict[str, Any]:
        """State plainly whether the fuel driving this number was MEASURED or ASSUMED.

        When the operator leaves fuel blank we multiply their acreage by a per-hectare
        default and carry on. That is a reasonable starting point, but the resulting
        figure is an estimate of an estimate, and until now nothing in the payload said
        so — the wizard printed "1.7 liters" beside a genuinely-cited EPA combustion
        factor, under one "EPA/USDA-sourced" badge, and the farmer had no way to tell
        which half was theirs.

        `measured` is the flag a surface should branch on. `assumed_rate` is present
        only when we substituted, and carries its own provenance so the UI never has to
        infer a citation from the fact that a number exists.

        `emission_factor` must be the factor that ACTUALLY produced `co2e_kg`, which is not
        always the one implied by the selected fuel type — see `assumed_fuel_is_diesel`.

        ⚠️ KNOWN METHODOLOGY GAP (pre-existing, not introduced here): when fuel is blank the
        calculators fall back to `area_hectares * <per_area_factor> * diesel_factor`
        unconditionally, so an ELECTRIC or GASOLINE machine with nothing entered is costed as
        diesel and returns a byte-identical figure to the diesel case.
        `assumed_fuel_is_diesel` marks that combination so it is visible in the payload
        instead of silently wrong. Fixing the arithmetic means choosing per-hectare defaults
        per fuel type (a kWh/ha rate for electric above all), which do not exist in
        PRODUCTION_FACTORS yet — a separate decision, not a rename.
        """
        measured = fuel_consumed is not None
        breakdown["fuel_basis"] = {
            "measured": measured,
            "emission_factor": {
                "value": emission_factor.value,
                "unit": emission_factor.unit,
                "source": emission_factor.source,
                "provenance": emission_factor.provenance,
            },
            "assumed_fuel_is_diesel": (not measured and breakdown.get("fuel_type") not in (None, "", "diesel")),
            "assumed_rate": (
                None
                if measured
                else {
                    "value": per_area_factor.value,
                    "unit": per_area_factor.unit,
                    "source": per_area_factor.source,
                    "provenance": per_area_factor.provenance,
                    "confidence_level": per_area_factor.confidence_level,
                }
            ),
        }
        return breakdown

    @classmethod
    def _calculate_harvesting_emissions(
        cls, area_covered: float, fuel_consumed: float = None, equipment_hours: float = None, **kwargs
    ) -> Dict[str, Any]:
        """Calculate harvesting emissions using USDA factors - supports diesel and electric equipment"""

        diesel_factor = cls.EPA_DIESEL_FACTORS["agricultural_equipment"]
        electricity_factor = cls.get_country_electricity_factor()
        harvesting_factor = cls.PRODUCTION_FACTORS["harvesting_diesel"]

        # Convert Decimal types to float to prevent type errors in calculations
        area_covered = float(area_covered)

        # Extract fuel_type and energy_source from kwargs
        fuel_type = kwargs.get("fuel_type", "diesel")  # Default to diesel for backwards compatibility
        energy_source = kwargs.get("energy_source", "grid")  # Default to grid for electric

        if fuel_consumed is not None:
            # Use actual fuel consumption
            fuel_consumed = float(fuel_consumed)  # Convert Decimal to float for calculation
            if fuel_type == "electric":
                # Electric equipment - fuel_consumed is in kWh
                if energy_source in ["solar", "wind"]:
                    # Renewable energy sources have zero emissions
                    co2e_kg = 0
                    calculation_basis = "actual_electric_consumption_renewable"
                else:
                    # Grid-powered electricity
                    co2e_kg = fuel_consumed * electricity_factor.value  # 0.365 kg CO₂e/kWh (US default)
                    calculation_basis = "actual_electric_consumption_grid"
                area_hectares = area_covered * 0.404686
            else:
                # Non-electric fuel — use correct factor for fuel type (gasoline, diesel, propane, etc.)
                # fuel_co2e resolves gaseous fuels against their own (per-scf) basis instead
                # of multiplying a gallon count by a per-cubic-foot factor.
                fuel_factor, calculation_basis = cls._get_fuel_factor_for_type(fuel_type)
                co2e_kg, fuel_factor, _fuel_unit_error = cls.fuel_co2e(
                    fuel_consumed, fuel_type, kwargs.get("fuel_unit")
                )
                area_hectares = area_covered * 0.404686
            # Skip validation for actual fuel consumption - farmers provide measured values
            skip_validation = True
        else:
            # Use USDA standard consumption per hectare (fixed: removed equipment_hours multiplier)
            # USDA factors are designed for area-based calculations, not time-based
            # Equipment hours are informational but should not scale the USDA factor
            area_hectares = area_covered * 0.404686  # Convert acres to hectares
            fuel_gallons = area_hectares * harvesting_factor.value
            co2e_kg = fuel_gallons * diesel_factor.value
            calculation_basis = "usda_standard_per_hectare"
            skip_validation = False

        breakdown = {
            "production_activity": "harvesting",
            "area_covered_acres": area_covered,
            "area_covered_hectares": area_covered * 0.404686,
            "fuel_type": fuel_type,
            "calculation_basis": calculation_basis,
            "confidence_level": (
                electricity_factor.confidence_level if fuel_type == "electric" else diesel_factor.confidence_level
            ),
        }

        # Add fuel-type specific breakdown information
        if fuel_type == "electric":
            breakdown["electricity_emission_factor_kg_per_kwh"] = electricity_factor.value
            if energy_source in ["solar", "wind"]:
                breakdown["energy_source"] = energy_source
                breakdown["note"] = f"{energy_source.capitalize()}-powered equipment - zero emissions"
            else:
                breakdown["energy_source"] = "grid"
                breakdown["electricity_emission_factor"] = f"{electricity_factor.value} kg CO₂/kWh (EPA eGRID)"
        else:
            actual_fuel_factor = cls.EPA_FUEL_FACTORS.get(fuel_type, diesel_factor)
            breakdown["fuel_emission_factor_kg_per_unit"] = actual_fuel_factor.value
            breakdown["diesel_emission_factor_kg_per_gallon"] = actual_fuel_factor.value
            breakdown["usda_harvesting_factor_gallons_per_hectare"] = harvesting_factor.value

        # Annotated for BOTH fuel paths. This call used to live inside the
        # `else` (non-electric) branch above, so an electric machine produced no
        # `fuel_basis` at all and the wizard fell back to its published-factor
        # badge over an estimate.
        cls._annotate_fuel_basis(
            breakdown,
            (
                (electricity_factor if fuel_type == "electric" else actual_fuel_factor)
                if fuel_consumed is not None
                # With no fuel entered the calculation falls back to the diesel per-hectare
                # path REGARDLESS of the selected fuel type (see the `else` branch above:
                # `fuel_gallons * diesel_factor.value`). Naming the electricity factor here
                # would credit a factor that never touched the number.
                else diesel_factor
            ),
            harvesting_factor,
            fuel_consumed,
        )

        if fuel_consumed is not None:
            fuel_unit = "kWh" if fuel_type == "electric" else "gallons"
            breakdown[f"actual_fuel_consumed_{fuel_unit}"] = fuel_consumed
        if equipment_hours:
            breakdown["equipment_hours"] = equipment_hours

        # Add validation for unrealistic results - only for USDA-based estimates
        if skip_validation:
            validated_result = {"co2e_kg": co2e_kg, "breakdown": breakdown, "warnings": [], "limitations": []}
        else:
            validated_result = cls._validate_production_emissions(co2e_kg, area_covered, "harvesting", breakdown)

        return {
            "co2e_kg": round(validated_result["co2e_kg"], 3),
            "calculation_method": "verified_epa_usda_factors_with_electric_support",
            "breakdown": validated_result["breakdown"],
            "data_sources": [
                diesel_factor.source if fuel_type != "electric" else electricity_factor.source,
                harvesting_factor.source,
            ],
            "limitations": validated_result.get("limitations", harvesting_factor.notes),
            "validation_warnings": validated_result.get("warnings", []),
        }

    @classmethod
    def _calculate_planting_emissions(
        cls, area_covered: float, fuel_consumed: float = None, equipment_hours: float = None, **kwargs
    ) -> Dict[str, Any]:
        """Calculate planting emissions using USDA factors - supports diesel and electric equipment"""

        diesel_factor = cls.EPA_DIESEL_FACTORS["agricultural_equipment"]
        electricity_factor = cls.get_country_electricity_factor()
        planting_factor = cls.PRODUCTION_FACTORS["planting_diesel"]

        # Convert Decimal types to float to prevent type errors in calculations
        area_covered = float(area_covered)

        # Extract fuel_type and energy_source from kwargs
        fuel_type = kwargs.get("fuel_type", "diesel")  # Default to diesel for backwards compatibility
        energy_source = kwargs.get("energy_source", "grid")  # Default to grid for electric

        if fuel_consumed is not None:
            # Use actual fuel consumption
            fuel_consumed = float(fuel_consumed)  # Convert Decimal to float for calculation
            if fuel_type == "electric":
                # Electric equipment - fuel_consumed is in kWh
                if energy_source in ["solar", "wind"]:
                    # Renewable energy sources have zero emissions
                    co2e_kg = 0
                    calculation_basis = "actual_electric_consumption_renewable"
                else:
                    # Grid-powered electricity
                    co2e_kg = fuel_consumed * electricity_factor.value  # 0.365 kg CO₂e/kWh (US default)
                    calculation_basis = "actual_electric_consumption_grid"
                area_hectares = area_covered * 0.404686
            else:
                # Non-electric fuel — use correct factor for fuel type (gasoline, diesel, propane, etc.)
                # fuel_co2e resolves gaseous fuels against their own (per-scf) basis instead
                # of multiplying a gallon count by a per-cubic-foot factor.
                fuel_factor, calculation_basis = cls._get_fuel_factor_for_type(fuel_type)
                co2e_kg, fuel_factor, _fuel_unit_error = cls.fuel_co2e(
                    fuel_consumed, fuel_type, kwargs.get("fuel_unit")
                )
                area_hectares = area_covered * 0.404686
            # Skip validation for actual fuel consumption - farmers provide measured values
            skip_validation = True
        else:
            # Use USDA standard consumption per hectare (fixed: removed equipment_hours multiplier)
            # USDA factors are designed for area-based calculations, not time-based
            # Equipment hours are informational but should not scale the USDA factor
            area_hectares = area_covered * 0.404686  # Convert acres to hectares
            fuel_gallons = area_hectares * planting_factor.value
            co2e_kg = fuel_gallons * diesel_factor.value
            calculation_basis = "usda_standard_per_hectare"
            skip_validation = False

        breakdown = {
            "production_activity": "planting",
            "area_covered_acres": area_covered,
            "area_covered_hectares": area_covered * 0.404686,
            "fuel_type": fuel_type,
            "calculation_basis": calculation_basis,
            "confidence_level": (
                electricity_factor.confidence_level if fuel_type == "electric" else diesel_factor.confidence_level
            ),
        }

        # Add fuel-type specific breakdown information
        if fuel_type == "electric":
            breakdown["electricity_emission_factor_kg_per_kwh"] = electricity_factor.value
            if energy_source in ["solar", "wind"]:
                breakdown["energy_source"] = energy_source
                breakdown["note"] = f"{energy_source.capitalize()}-powered equipment - zero emissions"
            else:
                breakdown["energy_source"] = "grid"
                breakdown["electricity_emission_factor"] = f"{electricity_factor.value} kg CO₂/kWh (EPA eGRID)"
        else:
            actual_fuel_factor = cls.EPA_FUEL_FACTORS.get(fuel_type, diesel_factor)
            breakdown["fuel_emission_factor_kg_per_unit"] = actual_fuel_factor.value
            breakdown["diesel_emission_factor_kg_per_gallon"] = actual_fuel_factor.value
            breakdown["usda_planting_factor_gallons_per_hectare"] = planting_factor.value

        # Annotated for BOTH fuel paths. This call used to live inside the
        # `else` (non-electric) branch above, so an electric machine produced no
        # `fuel_basis` at all and the wizard fell back to its published-factor
        # badge over an estimate.
        cls._annotate_fuel_basis(
            breakdown,
            (
                (electricity_factor if fuel_type == "electric" else actual_fuel_factor)
                if fuel_consumed is not None
                # With no fuel entered the calculation falls back to the diesel per-hectare
                # path REGARDLESS of the selected fuel type (see the `else` branch above:
                # `fuel_gallons * diesel_factor.value`). Naming the electricity factor here
                # would credit a factor that never touched the number.
                else diesel_factor
            ),
            planting_factor,
            fuel_consumed,
        )

        if fuel_consumed is not None:
            fuel_unit = "kWh" if fuel_type == "electric" else "gallons"
            breakdown[f"actual_fuel_consumed_{fuel_unit}"] = fuel_consumed
        if equipment_hours:
            breakdown["equipment_hours"] = equipment_hours

        # Add validation for unrealistic results (FIX #2) - only for USDA-based estimates
        if skip_validation:
            validated_result = {"co2e_kg": co2e_kg, "breakdown": breakdown, "warnings": [], "limitations": []}
        else:
            validated_result = cls._validate_production_emissions(co2e_kg, area_covered, "planting", breakdown)

        return {
            "co2e_kg": round(validated_result["co2e_kg"], 3),
            "calculation_method": "verified_epa_usda_factors_with_electric_support",
            "breakdown": validated_result["breakdown"],
            "data_sources": [
                diesel_factor.source if fuel_type != "electric" else electricity_factor.source,
                planting_factor.source,
            ],
            "limitations": validated_result.get("limitations", planting_factor.notes),
            "validation_warnings": validated_result.get("warnings", []),
        }

    @classmethod
    def _calculate_transplanting_emissions(
        cls, area_covered: float, fuel_consumed: float = None, equipment_hours: float = None, **kwargs
    ) -> Dict[str, Any]:
        """Calculate transplanting emissions using USDA factors - higher than planting due to careful handling, supports diesel and electric equipment"""

        diesel_factor = cls.EPA_DIESEL_FACTORS["agricultural_equipment"]
        electricity_factor = cls.get_country_electricity_factor()
        transplanting_factor = cls.PRODUCTION_FACTORS["transplanting_diesel"]

        # Convert Decimal types to float to prevent type errors in calculations
        area_covered = float(area_covered)

        # Extract fuel_type and energy_source from kwargs
        fuel_type = kwargs.get("fuel_type", "diesel")  # Default to diesel for backwards compatibility
        energy_source = kwargs.get("energy_source", "grid")  # Default to grid for electric

        if fuel_consumed is not None:
            # Use actual fuel consumption
            fuel_consumed = float(fuel_consumed)  # Convert Decimal to float for calculation
            if fuel_type == "electric":
                # Electric equipment - fuel_consumed is in kWh
                if energy_source in ["solar", "wind"]:
                    # Renewable energy sources have zero emissions
                    co2e_kg = 0
                    calculation_basis = "actual_electric_consumption_renewable"
                else:
                    # Grid-powered electricity
                    co2e_kg = fuel_consumed * electricity_factor.value  # 0.365 kg CO₂e/kWh (US default)
                    calculation_basis = "actual_electric_consumption_grid"
                area_hectares = area_covered * 0.404686
            else:
                # Non-electric fuel — use correct factor for fuel type (gasoline, diesel, propane, etc.)
                # fuel_co2e resolves gaseous fuels against their own (per-scf) basis instead
                # of multiplying a gallon count by a per-cubic-foot factor.
                fuel_factor, calculation_basis = cls._get_fuel_factor_for_type(fuel_type)
                co2e_kg, fuel_factor, _fuel_unit_error = cls.fuel_co2e(
                    fuel_consumed, fuel_type, kwargs.get("fuel_unit")
                )
                area_hectares = area_covered * 0.404686
            # SPRINT 6 FIX (2025-12-25): Skip validation for actual fuel consumption
            # Farmers provide real measured values that should be trusted, not capped
            skip_validation = True
        else:
            # Use USDA standard consumption per hectare (fixed: removed equipment_hours multiplier)
            # USDA factors are designed for area-based calculations, not time-based
            # Equipment hours are informational but should not scale the USDA factor
            area_hectares = area_covered * 0.404686  # Convert acres to hectares
            fuel_gallons = area_hectares * transplanting_factor.value
            co2e_kg = fuel_gallons * diesel_factor.value
            calculation_basis = "usda_standard_per_hectare"
            skip_validation = False

        breakdown = {
            "production_activity": "transplanting",
            "area_covered_acres": area_covered,
            "area_covered_hectares": area_covered * 0.404686,
            "fuel_type": fuel_type,
            "calculation_basis": calculation_basis,
            "confidence_level": (
                electricity_factor.confidence_level if fuel_type == "electric" else diesel_factor.confidence_level
            ),
            "note": "Higher emissions than direct planting due to careful plant handling and transport requirements",
        }

        # Add fuel-type specific breakdown information
        if fuel_type == "electric":
            breakdown["electricity_emission_factor_kg_per_kwh"] = electricity_factor.value
            if energy_source in ["solar", "wind"]:
                breakdown["energy_source"] = energy_source
                breakdown["note"] = f"{energy_source.capitalize()}-powered equipment - zero emissions"
            else:
                breakdown["energy_source"] = "grid"
                breakdown["electricity_emission_factor"] = f"{electricity_factor.value} kg CO₂/kWh (EPA eGRID)"
        else:
            actual_fuel_factor = cls.EPA_FUEL_FACTORS.get(fuel_type, diesel_factor)
            breakdown["fuel_emission_factor_kg_per_unit"] = actual_fuel_factor.value
            breakdown["diesel_emission_factor_kg_per_gallon"] = actual_fuel_factor.value
            breakdown["usda_transplanting_factor_gallons_per_hectare"] = transplanting_factor.value

        # Annotated for BOTH fuel paths. This call used to live inside the
        # `else` (non-electric) branch above, so an electric machine produced no
        # `fuel_basis` at all and the wizard fell back to its published-factor
        # badge over an estimate.
        cls._annotate_fuel_basis(
            breakdown,
            (
                (electricity_factor if fuel_type == "electric" else actual_fuel_factor)
                if fuel_consumed is not None
                # With no fuel entered the calculation falls back to the diesel per-hectare
                # path REGARDLESS of the selected fuel type (see the `else` branch above:
                # `fuel_gallons * diesel_factor.value`). Naming the electricity factor here
                # would credit a factor that never touched the number.
                else diesel_factor
            ),
            transplanting_factor,
            fuel_consumed,
        )

        if fuel_consumed is not None:
            fuel_unit = "kWh" if fuel_type == "electric" else "gallons"
            breakdown[f"actual_fuel_consumed_{fuel_unit}"] = fuel_consumed
        if equipment_hours:
            breakdown["equipment_hours"] = equipment_hours

        # Add validation for unrealistic results - only for USDA estimates, not actual fuel data
        # SPRINT 6 FIX (2025-12-25): Skip validation when farmer provides actual fuel consumption
        if skip_validation:
            validated_result = {"co2e_kg": co2e_kg, "breakdown": breakdown, "warnings": [], "limitations": []}
        else:
            validated_result = cls._validate_production_emissions(co2e_kg, area_covered, "transplanting", breakdown)

        return {
            "co2e_kg": round(validated_result["co2e_kg"], 3),
            "calculation_method": "verified_epa_usda_factors_with_electric_support",
            "breakdown": validated_result["breakdown"],
            "data_sources": [
                diesel_factor.source if fuel_type != "electric" else electricity_factor.source,
                transplanting_factor.source,
            ],
            "limitations": validated_result.get("limitations", transplanting_factor.notes),
            "validation_warnings": validated_result.get("warnings", []),
        }

    # Farm-to-first-receiver hauling. Derived from the EPA mobile-combustion diesel factor
    # (10.21 kg CO2/gal) at a loaded heavy-duty fuel economy of 6 mpg = 1.70 kg CO2e/mile.
    # The ton-mile figure is used when a load weight is known, which is the more accurate
    # basis for a part-full truck.
    TRANSPORT_KG_CO2E_PER_MILE = 1.70
    TRANSPORT_KG_CO2E_PER_TON_MILE = 0.209
    MILES_PER_KM = 0.621371

    @classmethod
    def calculate_transport_emissions(
        cls, distance: float, distance_unit: str = "miles", load_tons: float = None
    ) -> Dict[str, Any]:
        """Emissions from hauling harvested crop off the farm.

        A4 fix (2026-07). `transportation_distance` has been collected on ProductionEvent and
        SoilManagementEvent, validated in clean() (>500 raises a warning), surfaced on the
        consumer card and packed into the structured production data — and consumed by no
        formula at all. A farmer could record a 40-mile haul to the huller and it contributed
        nothing.

        This is in scope under carbon-methodology.md: hauling the crop from the farm to the
        first receiver is farmer-controlled and operational. It is NOT full-chain freight
        (distribution to retail, consumer travel), which remains excluded.
        """
        if not distance or float(distance) <= 0:
            return {"co2e_kg": 0.0, "breakdown": {"transport_distance": 0}, "data_sources": []}

        distance = float(distance)
        unit = (distance_unit or "miles").lower()
        miles = distance * cls.MILES_PER_KM if unit in ("km", "kilometer", "kilometers", "kilometre") else distance

        if load_tons and float(load_tons) > 0:
            co2e_kg = miles * float(load_tons) * cls.TRANSPORT_KG_CO2E_PER_TON_MILE
            basis = "ton_miles"
        else:
            co2e_kg = miles * cls.TRANSPORT_KG_CO2E_PER_MILE
            basis = "vehicle_miles"

        return {
            "co2e_kg": round(co2e_kg, 3),
            "breakdown": {
                "transport_distance": distance,
                "transport_distance_unit": unit,
                "transport_miles": round(miles, 2),
                "transport_load_tons": float(load_tons) if load_tons else None,
                "transport_basis": basis,
                "transport_emission_factor": (
                    cls.TRANSPORT_KG_CO2E_PER_TON_MILE if basis == "ton_miles" else cls.TRANSPORT_KG_CO2E_PER_MILE
                ),
                "transport_emissions_kg_co2e": round(co2e_kg, 3),
            },
            "data_sources": ["EPA 40 CFR Part 98 Table C-1 diesel (10.21 kg CO2/gal) at 6 mpg loaded heavy-duty"],
            "limitations": (
                "Farm to first receiver only. Onward distribution, retail and consumer travel are "
                "outside Trazo's direct-operational-emissions scope."
            ),
        }

    @classmethod
    def _calculate_postharvest_emissions(
        cls, area_covered: float, fuel_consumed: float = None, equipment_hours: float = None, **kwargs
    ) -> Dict[str, Any]:
        """Post-harvest processing (PH): hulling, drying, cooling — a FACILITY operation.

        A7 fix (2026-07). PH had no entry in PRODUCTION_TYPE_MAPPING, so it fell through to
        the general-production calculator and was charged a field-tillage-scale area estimate
        (~2.5 gal diesel/ha). That is the wrong physical model twice over:

          * ProductionEvent.clean() explicitly ALLOWS area_covered = 0 for PH because the work
            happens in a huller or drying shed, not across a block. Any area recorded on a PH
            event describes the block the crop came FROM, so multiplying it by a per-hectare
            field-fuel rate invents diesel nobody burned.
          * The real input is electricity (and sometimes propane for drying), which the form
            already collects as `processing_energy_kwh` in extra_data — read by nothing until
            now.

        Order of preference: measured energy, then reported fuel, then nothing. There is no
        area fallback on purpose — a fabricated figure is worse than an absent one, and this
        is the same judgement applied to general events in A2.
        """
        electricity_factor = cls.get_country_electricity_factor()
        processing_kwh = kwargs.get("processing_energy_kwh")
        energy_source = kwargs.get("energy_source") or "grid"
        fuel_type = kwargs.get("fuel_type") or "diesel"

        components = {}
        co2e_kg = 0.0

        if processing_kwh:
            kwh = float(processing_kwh)
            factor = cls.ELECTRICITY_SOURCE_FACTORS.get(energy_source, electricity_factor.value)
            electricity_emissions = kwh * factor
            co2e_kg += electricity_emissions
            components["processing_electricity_kwh"] = kwh
            components["processing_electricity_kg_co2e"] = round(electricity_emissions, 3)
            components["electricity_emission_factor_kg_per_kwh"] = factor

        if fuel_consumed:
            fuel_unit = (kwargs.get("fuel_unit") or "L").lower()
            fuel_factor = cls.EPA_FUEL_FACTORS.get(fuel_type, cls.EPA_FUEL_FACTORS["diesel"])

            if fuel_type == "electric":
                # EPA_FUEL_FACTORS holds diesel/gasoline/propane/biodiesel/natural_gas —
                # there is no "electric" key, so `.get(fuel_type, diesel)` silently priced
                # an electric huller's kWh as LITRES OF DIESEL: 10 kWh reported as 26.97 kg
                # CO2e instead of 3.9. The wizard offers "Electric" in the fuel-type select
                # for every production subtype including Post-Harvest, so this was reachable
                # from the form, not just in theory.
                #
                # `processing_energy_kwh` remains the preferred input for facility energy;
                # this branch handles the operator who enters the same figure in the general
                # fuel field with Electric selected.
                kwh = float(fuel_consumed)
                factor = cls.ELECTRICITY_SOURCE_FACTORS.get(energy_source, electricity_factor.value)
                electric_fuel_emissions = kwh * factor
                co2e_kg += electric_fuel_emissions
                components["fuel_type"] = fuel_type
                components["equipment_electricity_kwh"] = kwh
                components["equipment_electricity_kg_co2e"] = round(electric_fuel_emissions, 3)
                components["electricity_emission_factor_kg_per_kwh"] = factor
            elif fuel_type == "natural_gas":
                # UNIT-BASIS FIX (2026-07-31): the natural-gas factor is per STANDARD
                # CUBIC FOOT (see EPA_FUEL_FACTORS). It was previously multiplied by a
                # gallon count, so a dryer run reported as 310 L produced 1.18 kg CO2e
                # for hulling 153,000 lb of walnuts. Shares the fuel_co2e choke point with
                # the seven per-event paths so the two cannot drift apart.
                fuel_emissions, fuel_factor, reason = cls.fuel_co2e(fuel_consumed, fuel_type, kwargs.get("fuel_unit"))
                components["fuel_type"] = fuel_type
                if reason:
                    components["fuel_quantity_reported"] = f"{fuel_consumed} {kwargs.get('fuel_unit')}"
                    components["fuel_kg_co2e"] = 0.0
                    components["fuel_unit_error"] = reason
                else:
                    co2e_kg += fuel_emissions
                    scf, _ = cls.gas_quantity_to_scf(fuel_consumed, kwargs.get("fuel_unit"))
                    components["fuel_scf"] = round(scf, 3)
                    components["fuel_emission_factor_kg_per_scf"] = fuel_factor.value
                    components["fuel_kg_co2e"] = round(fuel_emissions, 3)
            else:
                # Litres are the form default; gallons is what the EPA factors are per.
                gallons = (
                    float(fuel_consumed) / 3.78541
                    if fuel_unit in ("l", "liter", "liters", "litre", "litres")
                    else float(fuel_consumed)
                )
                fuel_emissions = gallons * fuel_factor.value
                co2e_kg += fuel_emissions
                components["fuel_gallons"] = round(gallons, 3)
                components["fuel_type"] = fuel_type
                components["fuel_emission_factor_kg_per_gallon"] = fuel_factor.value
                components["fuel_kg_co2e"] = round(fuel_emissions, 3)

        has_inputs = bool(components)
        breakdown = {
            "production_activity": "post_harvest_processing",
            "processing_type": kwargs.get("processing_type"),
            "area_covered_acres": area_covered,
            "calculation_basis": ("measured_facility_energy" if has_inputs else "no_energy_reported"),
            "confidence_level": electricity_factor.confidence_level if has_inputs else 0.0,
            **components,
        }

        return {
            "co2e_kg": round(co2e_kg, 3),
            "calculation_method": ("verified_epa_postharvest" if has_inputs else "postharvest_no_data"),
            "breakdown": breakdown,
            "data_sources": [electricity_factor.source] if has_inputs else [],
            "limitations": (
                (
                    "Facility energy for hulling/drying/cooling. Direct operational emissions only."
                    + (
                        " Fuel NOT counted: " + components["fuel_unit_error"] + "."
                        if components.get("fuel_unit_error")
                        else ""
                    )
                )
                if has_inputs
                else "No processing energy or fuel reported — record processing_energy_kwh for a "
                "calculated figure. No area-based estimate is applied: post-harvest work is "
                "facility-based, so a per-hectare field rate would fabricate diesel."
            ),
        }

    @classmethod
    def _calculate_general_production_emissions(
        cls, area_covered: float, fuel_consumed: float = None, equipment_hours: float = None, **kwargs
    ) -> Dict[str, Any]:
        """Calculate general production emissions using USDA factors - supports diesel and electric equipment"""

        diesel_factor = cls.EPA_DIESEL_FACTORS["agricultural_equipment"]
        electricity_factor = cls.get_country_electricity_factor()
        production_factor = cls.PRODUCTION_FACTORS["crop_production_diesel"]

        # Convert Decimal types to float to prevent type errors in calculations
        area_covered = float(area_covered)

        # Extract fuel_type and energy_source from kwargs
        fuel_type = kwargs.get("fuel_type", "diesel")  # Default to diesel for backwards compatibility
        energy_source = kwargs.get("energy_source", "grid")  # Default to grid for electric

        # For electric equipment, fuel_consumed may be None because the preview
        # pipeline sets fuel_consumed_gallons=None for electric (kWh != gallons).
        # The actual kWh value is passed separately via fuel_consumed_kwh kwarg.
        # Use `is None` so an explicit 0 kWh from the farmer is respected.
        if fuel_consumed is None and fuel_type == "electric":
            fuel_consumed = kwargs.get("fuel_consumed_kwh")

        if fuel_consumed is not None:
            # Use actual fuel consumption
            fuel_consumed = float(fuel_consumed)  # Convert Decimal to float for calculation
            if fuel_type == "electric":
                # Electric equipment - fuel_consumed is in kWh
                if energy_source in ["solar", "wind"]:
                    # Renewable energy sources have zero emissions
                    co2e_kg = 0
                    calculation_basis = "actual_electric_consumption_renewable"
                else:
                    # Grid-powered electricity
                    co2e_kg = fuel_consumed * electricity_factor.value  # 0.365 kg CO₂e/kWh (US default)
                    calculation_basis = "actual_electric_consumption_grid"
                area_hectares = area_covered * 0.404686
            else:
                # Non-electric fuel — use correct factor for fuel type (gasoline, diesel, propane, etc.)
                # fuel_co2e resolves gaseous fuels against their own (per-scf) basis instead
                # of multiplying a gallon count by a per-cubic-foot factor.
                fuel_factor, calculation_basis = cls._get_fuel_factor_for_type(fuel_type)
                co2e_kg, fuel_factor, _fuel_unit_error = cls.fuel_co2e(
                    fuel_consumed, fuel_type, kwargs.get("fuel_unit")
                )
                area_hectares = area_covered * 0.404686
            # Skip validation for actual fuel consumption - farmers provide measured values
            skip_validation = True
        else:
            # Use USDA standard consumption per hectare (fixed: removed equipment_hours multiplier)
            # USDA factors are designed for area-based calculations, not time-based
            # Equipment hours are informational but should not scale the USDA factor
            area_hectares = area_covered * 0.404686  # Convert acres to hectares
            fuel_gallons = area_hectares * production_factor.value
            co2e_kg = fuel_gallons * diesel_factor.value
            calculation_basis = "usda_standard_per_hectare"
            skip_validation = False

        # Use production_type_code for activity label if available
        production_type_code = kwargs.get("production_type_code", "")
        activity_labels = {
            "PL": "planting",
            "HA": "harvesting",
            "IR": "irrigation",
            "PR": "pruning",
            "TR": "transplanting",
            "CU": "cultivation",
            "TH": "thinning",
            "PO": "pollination",
            "PH": "post_harvest_processing",
            "CM": "canopy_management",
            "EM": "equipment_maintenance",
            "FP": "frost_protection",
            "MO": "mowing_floor_management",
        }
        activity_label = activity_labels.get(production_type_code, "general_crop_production")

        breakdown = {
            "production_activity": activity_label,
            "area_covered_acres": area_covered,
            "area_covered_hectares": area_covered * 0.404686,
            "fuel_type": fuel_type,
            "calculation_basis": calculation_basis,
            "confidence_level": (
                electricity_factor.confidence_level if fuel_type == "electric" else diesel_factor.confidence_level
            ),
        }

        # Add fuel-type specific breakdown information
        if fuel_type == "electric":
            breakdown["electricity_emission_factor_kg_per_kwh"] = electricity_factor.value
            if energy_source in ["solar", "wind"]:
                breakdown["energy_source"] = energy_source
                breakdown["note"] = f"{energy_source.capitalize()}-powered equipment - zero emissions"
            else:
                breakdown["energy_source"] = "grid"
                breakdown["electricity_emission_factor"] = f"{electricity_factor.value} kg CO₂/kWh (EPA eGRID)"
        else:
            actual_fuel_factor = cls.EPA_FUEL_FACTORS.get(fuel_type, diesel_factor)
            breakdown["fuel_emission_factor_kg_per_unit"] = actual_fuel_factor.value
            # Also include diesel-specific key expected by frontend CarbonImpactPreview
            breakdown["diesel_emission_factor_kg_per_gallon"] = actual_fuel_factor.value
            breakdown["usda_production_factor_gallons_per_hectare"] = production_factor.value

        # Annotated for BOTH fuel paths. This call used to live inside the
        # `else` (non-electric) branch above, so an electric machine produced no
        # `fuel_basis` at all and the wizard fell back to its published-factor
        # badge over an estimate.
        cls._annotate_fuel_basis(
            breakdown,
            (
                (electricity_factor if fuel_type == "electric" else actual_fuel_factor)
                if fuel_consumed is not None
                # With no fuel entered the calculation falls back to the diesel per-hectare
                # path REGARDLESS of the selected fuel type (see the `else` branch above:
                # `fuel_gallons * diesel_factor.value`). Naming the electricity factor here
                # would credit a factor that never touched the number.
                else diesel_factor
            ),
            production_factor,
            fuel_consumed,
        )

        if fuel_consumed is not None:
            fuel_unit = "kWh" if fuel_type == "electric" else "gallons"
            breakdown[f"actual_fuel_consumed_{fuel_unit}"] = fuel_consumed
        if equipment_hours:
            breakdown["equipment_hours"] = equipment_hours

        # Add validation for unrealistic results (FIX #2) - skip for actual fuel data
        if skip_validation:
            validated_result = {"co2e_kg": co2e_kg, "breakdown": breakdown, "warnings": [], "limitations": []}
        else:
            validated_result = cls._validate_production_emissions(co2e_kg, area_covered, activity_label, breakdown)

        return {
            "co2e_kg": round(validated_result["co2e_kg"], 3),
            "calculation_method": "verified_epa_usda_factors_with_electric_support",
            "breakdown": validated_result["breakdown"],
            "data_sources": [
                diesel_factor.source if fuel_type != "electric" else electricity_factor.source,
                production_factor.source,
            ],
            "limitations": validated_result.get("limitations", production_factor.notes),
            "validation_warnings": validated_result.get("warnings", []),
        }

    @classmethod
    def _calculate_thinning_emissions(
        cls, area_covered: float, fuel_consumed: float = None, equipment_hours: float = None, **kwargs
    ) -> Dict[str, Any]:
        """Calculate thinning emissions using USDA factors - lightweight manual operation (FIX #3), supports diesel and electric equipment"""

        diesel_factor = cls.EPA_DIESEL_FACTORS["agricultural_equipment"]
        electricity_factor = cls.get_country_electricity_factor()
        thinning_factor = cls.PRODUCTION_FACTORS["thinning_diesel"]  # 0.75 gal/ha (not 2.5)

        # Convert Decimal types to float to prevent type errors in calculations
        # (BUG FIX: was missing — all other calculators have this guard)
        area_covered = float(area_covered)

        # Extract fuel_type and energy_source from kwargs
        fuel_type = kwargs.get("fuel_type", "diesel")  # Default to diesel for backwards compatibility
        energy_source = kwargs.get("energy_source", "grid")  # Default to grid for electric

        if fuel_consumed is not None:
            # Use actual fuel consumption
            fuel_consumed = float(fuel_consumed)  # Convert Decimal to float
            if fuel_type == "electric":
                # Electric equipment - fuel_consumed is in kWh
                if energy_source in ["solar", "wind"]:
                    # Renewable energy sources have zero emissions
                    co2e_kg = 0
                    calculation_basis = "actual_electric_consumption_renewable"
                else:
                    # Grid-powered electricity
                    co2e_kg = fuel_consumed * electricity_factor.value  # 0.365 kg CO₂e/kWh (US default)
                    calculation_basis = "actual_electric_consumption_grid"
                area_hectares = area_covered * 0.404686
            else:
                # Non-electric fuel — use correct factor for fuel type (gasoline, diesel, propane, etc.)
                # fuel_co2e resolves gaseous fuels against their own (per-scf) basis instead
                # of multiplying a gallon count by a per-cubic-foot factor.
                fuel_factor, calculation_basis = cls._get_fuel_factor_for_type(fuel_type)
                co2e_kg, fuel_factor, _fuel_unit_error = cls.fuel_co2e(
                    fuel_consumed, fuel_type, kwargs.get("fuel_unit")
                )
                area_hectares = area_covered * 0.404686
            # Skip validation for actual fuel consumption - farmers provide measured values
            # (BUG FIX: was missing — validation cap silently lowered actual farmer data)
            skip_validation = True
        else:
            # Use USDA standard for thinning (0.75 gal/ha - lightweight operation)
            # Fixed: Do NOT multiply by equipment_hours - thinning factor is area-based
            area_hectares = area_covered * 0.404686  # Convert acres to hectares
            fuel_gallons = area_hectares * thinning_factor.value
            co2e_kg = fuel_gallons * diesel_factor.value
            calculation_basis = "usda_standard_per_hectare"
            skip_validation = False

        breakdown = {
            "production_activity": "thinning",
            "area_covered_acres": area_covered,
            "area_covered_hectares": area_covered * 0.404686,
            "fuel_type": fuel_type,
            "calculation_basis": calculation_basis,
            "confidence_level": (
                electricity_factor.confidence_level if fuel_type == "electric" else diesel_factor.confidence_level
            ),
            "note": "Thinning is primarily manual labor with minimal fuel-intensive equipment",
        }

        # Add fuel-type specific breakdown information
        if fuel_type == "electric":
            breakdown["electricity_emission_factor_kg_per_kwh"] = electricity_factor.value
            if energy_source in ["solar", "wind"]:
                breakdown["energy_source"] = energy_source
                breakdown["note"] = f"{energy_source.capitalize()}-powered equipment - zero emissions"
            else:
                breakdown["energy_source"] = "grid"
                breakdown["electricity_emission_factor"] = f"{electricity_factor.value} kg CO₂/kWh (EPA eGRID)"
        else:
            actual_fuel_factor = cls.EPA_FUEL_FACTORS.get(fuel_type, diesel_factor)
            breakdown["fuel_emission_factor_kg_per_unit"] = actual_fuel_factor.value
            breakdown["diesel_emission_factor_kg_per_gallon"] = actual_fuel_factor.value
            breakdown["usda_thinning_factor_gallons_per_hectare"] = thinning_factor.value

        # Annotated for BOTH fuel paths. This call used to live inside the
        # `else` (non-electric) branch above, so an electric machine produced no
        # `fuel_basis` at all and the wizard fell back to its published-factor
        # badge over an estimate.
        cls._annotate_fuel_basis(
            breakdown,
            (
                (electricity_factor if fuel_type == "electric" else actual_fuel_factor)
                if fuel_consumed is not None
                # With no fuel entered the calculation falls back to the diesel per-hectare
                # path REGARDLESS of the selected fuel type (see the `else` branch above:
                # `fuel_gallons * diesel_factor.value`). Naming the electricity factor here
                # would credit a factor that never touched the number.
                else diesel_factor
            ),
            thinning_factor,
            fuel_consumed,
        )

        if fuel_consumed is not None:
            fuel_unit = "kWh" if fuel_type == "electric" else "gallons"
            breakdown[f"actual_fuel_consumed_{fuel_unit}"] = fuel_consumed
        if equipment_hours:
            breakdown["equipment_hours"] = equipment_hours

        # Add validation for unrealistic results (FIX #2) - skip for actual fuel data
        if skip_validation:
            validated_result = {"co2e_kg": co2e_kg, "breakdown": breakdown, "warnings": [], "limitations": []}
        else:
            validated_result = cls._validate_production_emissions(co2e_kg, area_covered, "thinning", breakdown)

        return {
            "co2e_kg": round(validated_result["co2e_kg"], 3),
            "calculation_method": "verified_epa_usda_factors_with_electric_support",
            "breakdown": validated_result["breakdown"],
            "data_sources": [
                diesel_factor.source if fuel_type != "electric" else electricity_factor.source,
                thinning_factor.source,
            ],
            "limitations": validated_result.get("limitations", thinning_factor.notes),
            "validation_warnings": validated_result.get("warnings", []),
        }

    @classmethod
    def _calculate_manual_operation_emissions(
        cls,
        area_covered: float,
        fuel_consumed: float = None,
        equipment_hours: float = None,
        operation_type: str = "manual",
        **kwargs,
    ) -> Dict[str, Any]:
        """Calculate manual operations (pruning) emissions using EPA factors - supports diesel and electric equipment

        SPRINT 6 FIX (2025-12-25): Added **kwargs to accept fuel_type and energy_source
        from calculate_production_event_emissions() for electric equipment support.
        """

        diesel_factor = cls.EPA_DIESEL_FACTORS["agricultural_equipment"]
        electricity_factor = cls.get_country_electricity_factor()

        # Convert Decimal types to float to prevent type errors in calculations
        area_covered = float(area_covered)

        # Extract fuel_type and energy_source from kwargs
        fuel_type = kwargs.get("fuel_type", "diesel")  # Default to diesel for backwards compatibility
        energy_source = kwargs.get("energy_source", "grid")  # Default to grid for electric

        if fuel_consumed is not None:
            # Use actual fuel consumption
            fuel_consumed = float(fuel_consumed)  # Convert Decimal to float for calculation
            if fuel_type == "electric":
                # Electric equipment - fuel_consumed is in kWh
                if energy_source in ["solar", "wind"]:
                    # Renewable energy sources have zero emissions
                    co2e_kg = 0
                    calculation_basis = "actual_electric_consumption_renewable"
                else:
                    # Grid-powered electricity
                    co2e_kg = fuel_consumed * electricity_factor.value  # 0.365 kg CO₂e/kWh (US default)
                    calculation_basis = "actual_electric_consumption_grid"
            else:
                # Non-electric fuel — use correct factor for fuel type (gasoline, diesel, propane, etc.)
                # fuel_co2e resolves gaseous fuels against their own (per-scf) basis instead
                # of multiplying a gallon count by a per-cubic-foot factor.
                fuel_factor, calculation_basis = cls._get_fuel_factor_for_type(fuel_type)
                co2e_kg, fuel_factor, _fuel_unit_error = cls.fuel_co2e(
                    fuel_consumed, fuel_type, kwargs.get("fuel_unit")
                )
        elif equipment_hours:
            # Estimate minimal fuel for manual operations with light equipment
            estimated_fuel = equipment_hours * 0.5  # 0.5 gal/hour for light equipment
            co2e_kg = estimated_fuel * diesel_factor.value
            calculation_basis = "estimated_light_equipment"
        else:
            # Very low emissions for manual operations
            co2e_kg = area_covered * 0.1  # 0.1 kg CO2e per acre
            calculation_basis = "manual_operation_estimate"

        breakdown = {
            "production_activity": operation_type,
            "area_covered_acres": area_covered,
            "fuel_type": fuel_type,
            "calculation_basis": calculation_basis,
            "confidence_level": 0.75,  # Lower confidence for manual operations
        }

        # Add fuel-type specific breakdown information
        if fuel_consumed is not None:
            if fuel_type == "electric":
                breakdown["electricity_emission_factor_kg_per_kwh"] = electricity_factor.value
                breakdown["actual_fuel_consumed_kwh"] = fuel_consumed
                if energy_source in ["solar", "wind"]:
                    breakdown["energy_source"] = energy_source
                    breakdown["note"] = f"{energy_source.capitalize()}-powered equipment - zero emissions"
                else:
                    breakdown["energy_source"] = "grid"
            else:
                actual_fuel_factor = cls.EPA_FUEL_FACTORS.get(fuel_type, diesel_factor)
                breakdown["actual_fuel_consumed_gallons"] = fuel_consumed
                breakdown["fuel_emission_factor_kg_per_unit"] = actual_fuel_factor.value
                breakdown["diesel_emission_factor_kg_per_gallon"] = actual_fuel_factor.value

        return {
            "co2e_kg": round(co2e_kg, 3),
            "calculation_method": "verified_epa_usda_factors_with_electric_support",
            "breakdown": breakdown,
            "data_sources": (
                [
                    (
                        electricity_factor.source
                        if fuel_type == "electric"
                        else cls.EPA_FUEL_FACTORS.get(fuel_type, diesel_factor).source
                    )
                ]
                if fuel_consumed
                else ["Manual operation estimate"]
            ),
            "limitations": "Manual operations have minimal fuel use, estimates may vary significantly",
        }

    @classmethod
    def _calculate_cultivation_emissions(
        cls, area_covered: float, fuel_consumed: float = None, equipment_hours: float = None, **kwargs
    ) -> Dict[str, Any]:
        """Calculate soil cultivation emissions using USDA factors - high fuel intensity, supports diesel and electric equipment"""

        diesel_factor = cls.EPA_DIESEL_FACTORS["agricultural_equipment"]
        electricity_factor = cls.get_country_electricity_factor()
        cultivation_factor = cls.PRODUCTION_FACTORS["cultivation_diesel"]

        # Convert Decimal types to float to prevent type errors in calculations
        area_covered = float(area_covered)

        # Extract fuel_type and energy_source from kwargs
        fuel_type = kwargs.get("fuel_type", "diesel")  # Default to diesel for backwards compatibility
        energy_source = kwargs.get("energy_source", "grid")  # Default to grid for electric

        if fuel_consumed is not None:
            # Use actual fuel consumption
            fuel_consumed = float(fuel_consumed)  # Convert Decimal to float for calculation
            # 2026-07-31: cultivation was the ONLY production path that did not set this,
            # so `_validate_production_emissions` silently rewrote a grower's MEASURED fuel
            # down to a per-hectare "realistic range" — 100 measured gallons was reported as
            # 859.96 kg instead of 1021 kg ("Exceeded realistic cultivation emissions range").
            # Every sibling branch already carries the same guard with the same rationale:
            # farmers provide measured values, which are trusted, not capped. A deep-ripping
            # or heavy-disc pass legitimately exceeds the per-hectare average.
            skip_validation = True
            if fuel_type == "electric":
                # Electric equipment - fuel_consumed is in kWh
                if energy_source in ["solar", "wind"]:
                    # Renewable energy sources have zero emissions
                    co2e_kg = 0
                    calculation_basis = "actual_electric_consumption_renewable"
                else:
                    # Grid-powered electricity
                    co2e_kg = fuel_consumed * electricity_factor.value  # 0.365 kg CO₂e/kWh (US default)
                    calculation_basis = "actual_electric_consumption_grid"
                area_hectares = area_covered * 0.404686
            else:
                # Non-electric fuel — use correct factor for fuel type (gasoline, diesel, propane, etc.)
                # fuel_co2e resolves gaseous fuels against their own (per-scf) basis instead
                # of multiplying a gallon count by a per-cubic-foot factor.
                fuel_factor, calculation_basis = cls._get_fuel_factor_for_type(fuel_type)
                co2e_kg, fuel_factor, _fuel_unit_error = cls.fuel_co2e(
                    fuel_consumed, fuel_type, kwargs.get("fuel_unit")
                )
                area_hectares = area_covered * 0.404686
        else:
            # Use USDA standard for cultivation (fixed: removed equipment_hours multiplier)
            # USDA factors are designed for area-based calculations, not time-based
            # Equipment hours are informational but should not scale the USDA factor
            skip_validation = False
            area_hectares = area_covered * 0.404686
            fuel_gallons = area_hectares * cultivation_factor.value
            co2e_kg = fuel_gallons * diesel_factor.value
            calculation_basis = "usda_standard_per_hectare"

        breakdown = {
            "production_activity": "soil_cultivation",
            "area_covered_acres": area_covered,
            "area_covered_hectares": area_covered * 0.404686,
            "fuel_type": fuel_type,
            "calculation_basis": calculation_basis,
            "confidence_level": (
                electricity_factor.confidence_level if fuel_type == "electric" else diesel_factor.confidence_level
            ),
        }

        # Add fuel-type specific breakdown information
        if fuel_type == "electric":
            breakdown["electricity_emission_factor_kg_per_kwh"] = electricity_factor.value
            if energy_source in ["solar", "wind"]:
                breakdown["energy_source"] = energy_source
                breakdown["note"] = f"{energy_source.capitalize()}-powered equipment - zero emissions"
            else:
                breakdown["energy_source"] = "grid"
                breakdown["electricity_emission_factor"] = f"{electricity_factor.value} kg CO₂/kWh (EPA eGRID)"
        else:
            actual_fuel_factor = cls.EPA_FUEL_FACTORS.get(fuel_type, diesel_factor)
            breakdown["fuel_emission_factor_kg_per_unit"] = actual_fuel_factor.value
            breakdown["diesel_emission_factor_kg_per_gallon"] = actual_fuel_factor.value
            breakdown["cultivation_intensity_factor"] = cultivation_factor.value
            # This branch is the reason `fuel_basis` exists rather than another
            # `usda_<verb>_factor_gallons_per_hectare` key: cultivation names its factor
            # differently from its five siblings, so the wizard's hand-written key chain
            # fell through to 0 and printed "0.0 liters (estimated)" for every cultivation
            # event. One key every activity writes, instead of six the client must know.

        # Annotated for BOTH fuel paths. This call used to live inside the
        # `else` (non-electric) branch above, so an electric machine produced no
        # `fuel_basis` at all and the wizard fell back to its published-factor
        # badge over an estimate.
        cls._annotate_fuel_basis(
            breakdown,
            (
                (electricity_factor if fuel_type == "electric" else actual_fuel_factor)
                if fuel_consumed is not None
                # With no fuel entered the calculation falls back to the diesel per-hectare
                # path REGARDLESS of the selected fuel type (see the `else` branch above:
                # `fuel_gallons * diesel_factor.value`). Naming the electricity factor here
                # would credit a factor that never touched the number.
                else diesel_factor
            ),
            cultivation_factor,
            fuel_consumed,
        )

        if fuel_consumed is not None:
            fuel_unit = "kWh" if fuel_type == "electric" else "gallons"
            breakdown[f"actual_fuel_consumed_{fuel_unit}"] = fuel_consumed
        if equipment_hours:
            breakdown["equipment_hours"] = equipment_hours

        # Add validation for unrealistic results
        if skip_validation:
            validated_result = {"co2e_kg": co2e_kg, "breakdown": breakdown, "warnings": [], "limitations": []}
        else:
            validated_result = cls._validate_production_emissions(co2e_kg, area_covered, "cultivation", breakdown)

        return {
            "co2e_kg": round(validated_result["co2e_kg"], 3),
            "calculation_method": "verified_epa_usda_factors_with_electric_support",
            "breakdown": validated_result["breakdown"],
            "data_sources": [
                diesel_factor.source if fuel_type != "electric" else electricity_factor.source,
                "USDA Agricultural Energy Use - Cultivation Operations",
            ],
            "limitations": validated_result.get(
                "limitations", "Cultivation fuel use varies significantly with soil conditions and equipment"
            ),
            "validation_warnings": validated_result.get("warnings", []),
        }

    @classmethod
    def _calculate_application_emissions(
        cls,
        area_covered: float,
        fuel_consumed: float = None,
        equipment_hours: float = None,
        application_type: str = "application",
    ) -> Dict[str, Any]:
        """Calculate application emissions (fertilizer, weeding, mulching) using EPA factors"""

        diesel_factor = cls.EPA_DIESEL_FACTORS["agricultural_equipment"]

        # Application factors (gallons per hectare)
        application_factors = {
            "fertilization": 1.2,  # Moderate fuel use for fertilizer application
            "weeding": 0.8,  # Light equipment for weeding
            "mulching": 2.0,  # Higher fuel for mulch spreading
        }

        intensity_factor = application_factors.get(application_type, 1.0)

        if fuel_consumed is not None:
            co2e_kg = fuel_consumed * diesel_factor.value
            calculation_basis = "actual_fuel_consumption"
        elif equipment_hours and area_covered:
            area_hectares = area_covered * 0.404686
            estimated_fuel = (area_hectares * intensity_factor) * (equipment_hours / 6.0)  # 6-hour application day
            co2e_kg = estimated_fuel * diesel_factor.value
            calculation_basis = f"estimated_{application_type}_intensity"
        else:
            area_hectares = area_covered * 0.404686
            fuel_gallons = area_hectares * intensity_factor
            co2e_kg = fuel_gallons * diesel_factor.value
            calculation_basis = f"usda_{application_type}_standard"

        breakdown = {
            "production_activity": application_type,
            "area_covered_acres": area_covered,
            "area_covered_hectares": area_covered * 0.404686,
            "diesel_emission_factor_kg_per_gallon": diesel_factor.value,
            "application_intensity_factor": intensity_factor,
            "calculation_basis": calculation_basis,
            "confidence_level": 0.80,
        }

        return {
            "co2e_kg": round(co2e_kg, 3),
            "calculation_method": "verified_epa_usda_factors",
            "breakdown": breakdown,
            "data_sources": [
                diesel_factor.source,
                f"USDA Agricultural Energy Use - {application_type.title()} Operations",
            ],
            "limitations": f"{application_type.title()} fuel use varies with application rate and equipment efficiency",
        }

    @classmethod
    def calculate_chemical_application_emissions(
        cls,
        chemical_type: str,
        volume_liters: float,
        area_hectares: float,
        npk_content: dict,
        application_method: str = "broadcast",
        product_name: str = "",
        chemical_subtype: str = "",
        application_fuel_type: str = "",
        application_fuel_consumed: float = None,
        application_fuel_unit: str = "L",
        concentration: float = None,
        organic_approved: str = "",
        is_fertigation: bool = False,
        chemical_mass_kg: float = None,
    ) -> Dict[str, Any]:
        """
        Calculate chemical application emissions using EPA/USDA verified emission factors.

        ENHANCED: Uses only credible, government-sourced data for transparency.
        Includes both manufacturing and application emissions.

        UPDATED 2025-01-21: Added explicit `chemical_subtype` parameter for accurate emission factors.
        Supports specific emission factors for:
        - Organic/vinegar herbicides (acetic acid): 1.2 kg CO2e/kg (vs 5.5 for synthetic)
        - Copper-based fungicides: 5.5 kg CO2e/kg AI (vs 4.5 for generic)
        - Sulfur-based fungicides, biological agents, organic pesticides, etc.

        UPDATED 2025-12-11: Added application fuel tracking for electric and alternative fuels.
        - Enables tracking of actual fuel consumed by application equipment
        - Supports electric equipment with kWh units
        - Falls back to estimated fuel consumption if actual consumption not provided

        UPDATED 2025-12-23: Added concentration parameter for accurate active ingredient calculation.
        - Uses user-entered concentration percentage for pesticides/herbicides/fungicides
        - Falls back to typical defaults when concentration not provided

        Args:
            chemical_type: Type of chemical (herbicide, fungicide, pesticide, etc.)
            volume_liters: Volume applied in liters
            area_hectares: Area treated in hectares
            npk_content: NPK content dictionary for fertilizers
            application_method: Method of application
            product_name: Product name for detecting specific chemical types (DEPRECATED - use chemical_subtype)
            chemical_subtype: Explicit chemical subtype for accurate emission factor selection.
                            Takes precedence over product_name keyword detection.
                            Values: organic_herbicide, organic_fungicide, copper_fungicide, sulfur_fungicide,
                                    biological_fungicide, organic_pesticide, biological_pesticide,
                                    organic_fertilizer, etc.
            application_fuel_type: Actual fuel type for application equipment (diesel, electric, etc.)
                                  If provided, overrides estimated fuel consumption method
            application_fuel_consumed: Actual fuel consumed by application equipment (in specified unit)
                                      If provided with application_fuel_type, used instead of estimation
            application_fuel_unit: Unit of application_fuel_consumed (L, gal, kg, kWh)
            concentration: Active ingredient concentration as percentage (e.g., 2.5 for 2.5%).
                          Used to calculate actual active ingredient mass for pesticides/herbicides/fungicides.
        """

        has_volume = volume_liters > 0 or (chemical_mass_kg is not None and chemical_mass_kg > 0)
        if not has_volume or area_hectares <= 0:
            return {
                "co2e_kg": 0.0,
                "calculation_method": "verified_epa_usda_factors",
                "breakdown": {"error": "Invalid input parameters"},
                "data_sources": [],
                "limitations": "No emissions calculated due to invalid inputs",
            }

        # Get EPA emission factors
        nitrogen_factor = cls.EPA_CHEMICAL_FACTORS["nitrogen_fertilizer"]
        phosphorus_factor = cls.EPA_CHEMICAL_FACTORS["phosphorus_fertilizer"]
        potassium_factor = cls.EPA_CHEMICAL_FACTORS["potassium_fertilizer"]
        fuel_factor = cls.EPA_CHEMICAL_FACTORS["application_fuel"]
        # The factors this calculation actually applies, so `data_sources` names those and
        # no others. It listed the N, P, K and fuel sources for EVERY chemical, pesticides
        # included, plus a fixed USDA ARS line (review of back #308, 2026-11-05).
        manufacturing_factors = []
        fuel_factors_used = []

        # Calculate manufacturing emissions from NPK content OR chemical type
        n_percentage = npk_content.get("N", 0) / 100.0
        p_percentage = npk_content.get("P", 0) / 100.0
        k_percentage = npk_content.get("K", 0) / 100.0

        # Determine total product mass in kg
        # When chemical_mass_kg is provided (input was in mass units like kg/lbs),
        # use it directly — no density conversion needed.
        # When only volume_liters is available, convert using density.
        #
        # FIX 2026-04-11: Route PE/FU/HE through a chemical-formulation density
        # lookup instead of the fertilizer density table. Fertilizer densities
        # (1.25 kg/L for "spray" method) overestimate the mass of d-limonene,
        # neem oil, and other low-density organic formulations by ~40%, which
        # inflates manufacturing emissions and undermines the audit-ready
        # transparency pitch. Pesticide/herbicide/fungicide densities come from
        # EPA Pesticide Product Label System and industry formulation guides.
        #
        # `density_applied` is None when mass was supplied directly — the
        # breakdown should not claim a density was used in that case.
        if chemical_mass_kg is not None and chemical_mass_kg > 0:
            total_fertilizer_kg = chemical_mass_kg
            fertilizer_density = 1.0  # placeholder for any downstream readers
            density_applied = None
        else:
            if chemical_type.lower() in ["pesticide", "pe", "herbicide", "he", "fungicide", "fu"]:
                fertilizer_density = cls._get_chemical_density(
                    chemical_type=chemical_type,
                    chemical_subtype=chemical_subtype,
                    product_name=product_name,
                    organic_approved=organic_approved,
                )
            else:
                fertilizer_density = cls._get_fertilizer_density(npk_content, application_method)
            total_fertilizer_kg = volume_liters * fertilizer_density
            density_applied = fertilizer_density

        # Determine specific chemical subtype using priority order:
        # 1. Explicit chemical_subtype parameter (highest priority - from UI dropdown)
        # 2. Keyword detection from product_name (fallback for backwards compatibility)
        chemical_subtype_lower = chemical_subtype.lower() if chemical_subtype else ""
        product_name_lower = product_name.lower() if product_name else ""

        # SPRINT 6 FIX (2025-12-24): Check organic_approved field for organic certification
        # organic_approved can contain: "omri_listed", "organic_equivalent", "organic_certified", etc.
        organic_approved_lower = (organic_approved or "").lower()
        is_certified_organic = organic_approved_lower in [
            "omri_listed",
            "organic_equivalent",
            "organic_certified",
            "organic",
            "usda_organic",
            "certified_organic",
        ]

        # Check explicit subtype first, then organic_approved, then fall back to keyword detection
        is_organic_herbicide = (
            chemical_subtype_lower == "organic_herbicide"
            or chemical_subtype_lower == "organic"
            or (not chemical_subtype and cls._is_organic_herbicide(product_name_lower))
            # SPRINT 6 FIX: Also check organic_approved for herbicides
            or (is_certified_organic and chemical_type.lower() in ["herbicide", "he"])
        )
        # SPRINT 6 FIX (2025-12-24): Always check product name for copper, not just when subtype is empty
        # This ensures products like "Copper Hydroxide" with subtype "biological_fungicide" are correctly detected
        is_copper_fungicide = (
            chemical_subtype_lower == "copper_fungicide"
            or chemical_subtype_lower == "copper"
            or cls._is_copper_fungicide(product_name_lower)  # Always check product name
        )
        is_sulfur_fungicide = chemical_subtype_lower in ["sulfur_fungicide", "sulfur"]
        is_biological_fungicide = chemical_subtype_lower in ["biological_fungicide", "biological"]
        is_organic_fungicide = chemical_subtype_lower in ["organic_fungicide"]
        is_organic_pesticide = (
            chemical_subtype_lower in ["organic_pesticide", "organic"]
            # SPRINT 6 FIX: Also check organic_approved for pesticides
            or (is_certified_organic and chemical_type.lower() in ["pesticide", "pe"])
        )
        is_biological_pesticide = chemical_subtype_lower in ["biological_pesticide", "biological"]
        is_organic_fertilizer = (
            chemical_subtype_lower in ["organic_fertilizer", "organic"]
            # SPRINT 6 FIX: Also check organic_approved for fertilizers
            or (is_certified_organic and chemical_type.lower() in ["fertilizer", "fe"])
        )
        is_slow_release_fertilizer = chemical_subtype_lower in ["slow_release_fertilizer", "slow_release"]

        # Manufacturing emissions (upstream) - ENHANCED for all chemical subtypes
        # SPRINT 6 FIX (2025-12-23): Use user-provided concentration instead of hardcoded defaults
        # Convert concentration percentage to decimal (e.g., 2.5% -> 0.025, 0.625% -> 0.00625)
        user_concentration = None
        if concentration is not None and concentration > 0:
            # Concentration is always a percentage (per docstring contract)
            # Always divide by 100 to convert to decimal fraction
            user_concentration = concentration / 100.0

        # F03-consistent fix (2026-06): do NOT fabricate an active-ingredient % for
        # non-fertilizer chemicals (PE/HE/FU) when the farmer left concentration blank.
        # The per-subtype defaults below (0.25-0.99) silently invented manufacturing
        # emissions — over- or under-stating by up to ~10x — and presented them as
        # EPA-sourced, contradicting the no-phantom policy already applied to fertilizer
        # NPK (F03). When the AI% is unknown we OMIT the manufacturing portion (set 0)
        # and flag it; the application-fuel emissions below are real and still counted.
        ai_concentration_missing = (
            chemical_type.lower() in ["pesticide", "pe", "herbicide", "he", "fungicide", "fu"]
            and user_concentration is None
        )

        if chemical_type.lower() in ["pesticide", "pe"]:
            # Check for organic or biological pesticide subtypes
            if is_organic_pesticide:
                organic_pesticide_factor = cls.EPA_CHEMICAL_FACTORS["organic_pesticide_manufacturing"]
                # Use user concentration if provided, else default for organic pesticides
                active_ingredient_percentage = user_concentration if user_concentration else 0.25
                active_ingredient_kg = total_fertilizer_kg * active_ingredient_percentage
                manufacturing_emissions = active_ingredient_kg * organic_pesticide_factor.value
                manufacturing_factors.append(organic_pesticide_factor)
            elif is_biological_pesticide:
                biological_pesticide_factor = cls.EPA_CHEMICAL_FACTORS["biological_pesticide_manufacturing"]
                # Use user concentration if provided, else default for biological pesticides
                active_ingredient_percentage = user_concentration if user_concentration else 0.30
                active_ingredient_kg = total_fertilizer_kg * active_ingredient_percentage
                manufacturing_emissions = active_ingredient_kg * biological_pesticide_factor.value
                manufacturing_factors.append(biological_pesticide_factor)
            else:
                # Use standard synthetic pesticide manufacturing emission factor
                pesticide_factor = cls.EPA_CHEMICAL_FACTORS["pesticide_manufacturing"]
                # SPRINT 6 FIX: Use user-entered concentration instead of hardcoded 48%
                active_ingredient_percentage = user_concentration if user_concentration else 0.48
                active_ingredient_kg = total_fertilizer_kg * active_ingredient_percentage
                manufacturing_emissions = active_ingredient_kg * pesticide_factor.value
                manufacturing_factors.append(pesticide_factor)
        elif chemical_type.lower() in ["herbicide", "he"]:
            # Check if organic/vinegar herbicide (acetic acid-based)
            if is_organic_herbicide:
                # Use organic herbicide factor (acetic acid production: 0.64-1.2 kg CO2e/kg)
                organic_herbicide_factor = cls.EPA_CHEMICAL_FACTORS["organic_herbicide_manufacturing"]
                # Use user concentration if provided, else default for organic herbicides
                active_ingredient_percentage = user_concentration if user_concentration else 0.25
                active_ingredient_kg = total_fertilizer_kg * active_ingredient_percentage
                manufacturing_emissions = active_ingredient_kg * organic_herbicide_factor.value
                manufacturing_factors.append(organic_herbicide_factor)
            else:
                # Use standard synthetic herbicide manufacturing emission factor
                herbicide_factor = cls.EPA_CHEMICAL_FACTORS["herbicide_manufacturing"]
                # SPRINT 6 FIX: Use user-entered concentration instead of hardcoded 41%
                active_ingredient_percentage = user_concentration if user_concentration else 0.41
                active_ingredient_kg = total_fertilizer_kg * active_ingredient_percentage
                manufacturing_emissions = active_ingredient_kg * herbicide_factor.value
                manufacturing_factors.append(herbicide_factor)
        elif chemical_type.lower() in ["fungicide", "fu"]:
            # Check specific fungicide subtypes
            if is_copper_fungicide:
                # Use copper-specific fungicide factor (higher due to copper mining/refining)
                copper_fungicide_factor = cls.EPA_CHEMICAL_FACTORS["copper_fungicide_manufacturing"]
                # Use user concentration if provided, else default for copper fungicides
                active_ingredient_percentage = user_concentration if user_concentration else 0.99
                active_ingredient_kg = total_fertilizer_kg * active_ingredient_percentage
                manufacturing_emissions = active_ingredient_kg * copper_fungicide_factor.value
                manufacturing_factors.append(copper_fungicide_factor)
            elif is_sulfur_fungicide:
                # Use sulfur-specific fungicide factor (lower due to byproduct nature)
                sulfur_fungicide_factor = cls.EPA_CHEMICAL_FACTORS["sulfur_fungicide_manufacturing"]
                # Use user concentration if provided, else default for sulfur fungicides
                active_ingredient_percentage = user_concentration if user_concentration else 0.90
                active_ingredient_kg = total_fertilizer_kg * active_ingredient_percentage
                manufacturing_emissions = active_ingredient_kg * sulfur_fungicide_factor.value
                manufacturing_factors.append(sulfur_fungicide_factor)
            elif is_biological_fungicide:
                # Use biological fungicide factor (fermentation-based production)
                biological_fungicide_factor = cls.EPA_CHEMICAL_FACTORS["biological_fungicide_manufacturing"]
                # Use user concentration if provided, else default for biological fungicides
                active_ingredient_percentage = user_concentration if user_concentration else 0.30
                active_ingredient_kg = total_fertilizer_kg * active_ingredient_percentage
                manufacturing_emissions = active_ingredient_kg * biological_fungicide_factor.value
                manufacturing_factors.append(biological_fungicide_factor)
            elif is_organic_fungicide:
                # Use organic fungicide factor (neem oil, potassium bicarbonate, essential oils)
                organic_fungicide_factor = cls.EPA_CHEMICAL_FACTORS["organic_fungicide_manufacturing"]
                active_ingredient_percentage = user_concentration if user_concentration else 0.25
                active_ingredient_kg = total_fertilizer_kg * active_ingredient_percentage
                manufacturing_emissions = active_ingredient_kg * organic_fungicide_factor.value
                manufacturing_factors.append(organic_fungicide_factor)
            else:
                # Use generic synthetic fungicide manufacturing emission factor
                fungicide_factor = cls.EPA_CHEMICAL_FACTORS["fungicide_manufacturing"]
                # SPRINT 6 FIX: Use user-entered concentration instead of hardcoded 99%
                active_ingredient_percentage = user_concentration if user_concentration else 0.45
                active_ingredient_kg = total_fertilizer_kg * active_ingredient_percentage
                manufacturing_emissions = active_ingredient_kg * fungicide_factor.value
                manufacturing_factors.append(fungicide_factor)
        else:
            # Fertilizer calculation - check for organic or slow-release subtypes
            if is_organic_fertilizer:
                organic_fertilizer_factor = cls.EPA_CHEMICAL_FACTORS["organic_fertilizer_manufacturing"]
                # Organic fertilizers have much lower manufacturing emissions
                manufacturing_emissions = total_fertilizer_kg * organic_fertilizer_factor.value
                manufacturing_factors.append(organic_fertilizer_factor)
                # 2026-07-31: field N2O was missing entirely. `n_kg` was computed further up
                # and then discarded for this branch, so an organic grower's applied nitrogen
                # produced ZERO soil emissions while the synthetic and slow-release branches
                # both carried it (inside nitrogen_factor's 10.5). Field N2O is a real,
                # farmer-controlled, in-scope emission — it depends on the nitrogen, not on
                # how the nitrogen was made.
                n_kg = total_fertilizer_kg * n_percentage
                field_n2o_factor = cls.EPA_CHEMICAL_FACTORS["nitrogen_field_n2o"]
                organic_field_n2o_emissions = n_kg * field_n2o_factor.value
                manufacturing_factors.append(field_n2o_factor)
                manufacturing_emissions += organic_field_n2o_emissions
            elif is_slow_release_fertilizer:
                # Slow-release fertilizers have similar manufacturing to synthetic but better efficiency
                # Use standard NPK calculation with a small premium for coating
                n_kg = total_fertilizer_kg * n_percentage
                p_kg = total_fertilizer_kg * p_percentage
                k_kg = total_fertilizer_kg * k_percentage
                manufacturing_emissions = (
                    n_kg * nitrogen_factor.value + p_kg * phosphorus_factor.value + k_kg * potassium_factor.value
                ) * 1.1  # 10% premium for coating process
                manufacturing_factors.extend(
                    f for f, kg in ((nitrogen_factor, n_kg), (phosphorus_factor, p_kg), (potassium_factor, k_kg)) if kg
                )
            else:
                # Traditional synthetic fertilizer calculation (NPK-based)
                n_kg = total_fertilizer_kg * n_percentage
                p_kg = total_fertilizer_kg * p_percentage
                k_kg = total_fertilizer_kg * k_percentage

                manufacturing_emissions = (
                    n_kg * nitrogen_factor.value + p_kg * phosphorus_factor.value + k_kg * potassium_factor.value
                )
                manufacturing_factors.extend(
                    f for f, kg in ((nitrogen_factor, n_kg), (phosphorus_factor, p_kg), (potassium_factor, k_kg)) if kg
                )

        # F03-consistent fix (2026-06): override the phantom-default manufacturing
        # emissions with 0 when the AI concentration was not provided (see flag above).
        # No fabricated active-ingredient assumption is presented as EPA-sourced.
        if ai_concentration_missing:
            manufacturing_emissions = 0.0
            manufacturing_factors = []  # nothing was applied, so nothing is cited

        # Application emissions (fuel for equipment)
        # SPRINT 3 EPIC 3.3: Application Fuel Tracking
        # UPDATED 2025-12-11: Support for actual fuel tracking (diesel, electric, etc.)
        # Falls back to estimated fuel consumption if actual consumption not provided

        # Track the actual fuel factor used for breakdown transparency.
        # Defaults to the generic `application_fuel` (diesel) factor; each branch
        # below overrides this with the real factor applied to the selected fuel
        # type so the breakdown line stays self-consistent with the emissions total.
        used_fuel_factor_value = fuel_factor.value
        used_fuel_factor_unit = "gal"

        # Item #14: Fertigation — fertilizer injected through irrigation system.
        # Application fuel is already counted in the irrigation event, so skip it here
        # to avoid double-counting. Only manufacturing emissions (NPK factors) are calculated.
        if is_fertigation:
            application_emissions = 0.0
            total_fuel_liters = 0.0
            total_fuel_gallons = 0.0
            calculation_basis = "fertigation_no_application_fuel"
            calculation_method_note = "Fertigation — application fuel skipped (counted in irrigation event)"

        # Check if actual fuel consumption is provided
        elif application_fuel_consumed is not None and application_fuel_consumed > 0 and application_fuel_type:
            # Use actual application fuel data
            application_fuel_consumed = float(application_fuel_consumed)  # Convert Decimal to float for calculation
            calculation_basis = "actual_application_fuel"

            # Convert to standard liters for tracking
            if application_fuel_unit == "gal":
                fuel_liters = application_fuel_consumed * 3.78541
            elif application_fuel_unit == "kWh":
                # For electricity, keep as-is for direct conversion to emissions
                fuel_liters = application_fuel_consumed  # Will be treated as kWh below
            elif application_fuel_unit == "kg":
                # For solids, assume 1 kg ≈ 1 L volumetrically for estimation
                fuel_liters = application_fuel_consumed
            else:  # liters
                fuel_liters = application_fuel_consumed

            # Route to correct emission factor based on fuel type
            # (used_fuel_factor_value is pre-initialized above; each branch
            # below updates it with the real factor applied)
            if application_fuel_type.lower() == "electric":
                # Electric equipment: use kWh consumption and electricity factor
                application_fuel_kwh = fuel_liters  # Already in kWh if unit was kWh
                electricity_factor = cls.get_country_electricity_factor()
                application_emissions = application_fuel_kwh * electricity_factor.value
                fuel_factors_used.append(electricity_factor)
                used_fuel_factor_value = electricity_factor.value
                used_fuel_factor_unit = "kWh"
                calculation_method_note = "Actual electric consumption (kWh)"
            elif application_fuel_type.lower() == "diesel":
                fuel_gallons = fuel_liters / 3.78541  # Convert to gallons
                application_emissions = fuel_gallons * fuel_factor.value
                fuel_factors_used.append(fuel_factor)
                used_fuel_factor_value = fuel_factor.value
                calculation_method_note = "Actual diesel consumption"
            elif application_fuel_type.lower() == "gasoline":
                gasoline_factor = cls.EPA_FUEL_FACTORS.get("gasoline", fuel_factor)
                fuel_gallons = fuel_liters / 3.78541  # Convert to gallons
                application_emissions = fuel_gallons * gasoline_factor.value
                fuel_factors_used.append(gasoline_factor)
                used_fuel_factor_value = gasoline_factor.value
                calculation_method_note = "Actual gasoline consumption"
            elif application_fuel_type.lower() == "propane":
                propane_factor = cls.EPA_FUEL_FACTORS.get("propane", fuel_factor)
                fuel_gallons = fuel_liters / 3.78541  # Convert to gallons
                application_emissions = fuel_gallons * propane_factor.value
                fuel_factors_used.append(propane_factor)
                used_fuel_factor_value = propane_factor.value
                calculation_method_note = "Actual propane consumption"
            elif application_fuel_type.lower() == "natural_gas":
                # Natural gas factor is per cubic foot, estimate 1 cf ≈ 0.0283 m³
                natural_gas_factor = cls.EPA_FUEL_FACTORS.get("natural_gas", fuel_factor)
                # Assume 1 L natural gas ≈ 0.035 cubic feet
                fuel_cubic_feet = fuel_liters * 0.035
                application_emissions = fuel_cubic_feet * natural_gas_factor.value
                fuel_factors_used.append(natural_gas_factor)
                used_fuel_factor_value = natural_gas_factor.value
                used_fuel_factor_unit = "cf"
                calculation_method_note = "Actual natural gas consumption"
            elif application_fuel_type.lower() == "biodiesel":
                # Biodiesel is similar to diesel (slightly lower emissions)
                biodiesel_factor = cls.EPA_FUEL_FACTORS.get("biodiesel", fuel_factor)
                fuel_gallons = fuel_liters / 3.78541  # Convert to gallons
                application_emissions = fuel_gallons * biodiesel_factor.value
                fuel_factors_used.append(biodiesel_factor)
                used_fuel_factor_value = biodiesel_factor.value
                calculation_method_note = "Actual biodiesel consumption"
            elif application_fuel_type.lower() == "none" or application_fuel_type == "":
                # Manual or non-fuel equipment
                application_emissions = 0.0
                used_fuel_factor_value = 0.0
                calculation_method_note = "Manual application (no fuel)"
            else:
                # Unknown fuel type, use diesel as fallback
                fuel_gallons = fuel_liters / 3.78541  # Convert to gallons
                application_emissions = fuel_gallons * fuel_factor.value
                fuel_factors_used.append(fuel_factor)
                used_fuel_factor_value = fuel_factor.value
                calculation_method_note = f"Actual fuel consumption ({application_fuel_type}) - using diesel factor"

            # For tracking
            total_fuel_liters = fuel_liters
            total_fuel_gallons = fuel_liters / 3.78541 if application_fuel_unit != "kWh" else 0

        else:
            # FALLBACK: Use estimated fuel consumption based on application method
            calculation_basis = "estimated_application_fuel"
            calculation_method_note = "Estimated based on application method and area"

            # UPDATED: Real-world agricultural fuel consumption rates based on equipment type
            # Source: Agricultural Engineering Standards, EPA Farm Equipment Data, USDA Energy Use Studies
            # NOTE 2026-04-11: removed stray `application_rate_per_hectare = volume_liters / area_hectares`
            # — the variable was never read downstream and crashed with ZeroDivisionError when
            # area_hectares was 0 (which the outer `area_hectares <= 0` guard at line 2079
            # should prevent, but belt-and-suspenders is cheap).

            # Estimate fuel consumption based on application method and equipment type
            # These values are based on real-world agricultural engineering data
            if application_method.lower() in ["broadcast", "spray"]:
                # Broadcast/spray methods CALIBRATED to research benchmarks:
                # - Boom sprayer (field crops): 1.5-2.5 L diesel/ha
                # - Airblast sprayer (orchards): 3.0-5.0 L diesel/ha
                # - Hand sprayer (small scale): 0.8-1.2 L diesel/ha
                # CALIBRATED: For pesticides/herbicides/fungicides - much lower fuel than fertilizers
                fuel_consumption_per_ha = 0.8  # L diesel/ha (CALIBRATED for chemical efficiency)
            elif application_method.lower() in ["airblast", "airblast_sprayer", "orchard_spray", "tree_spray"]:
                # Orchard airblast sprayers - high fuel consumption for air movement
                # Real-world range: 3.0-5.0 L diesel/ha depending on tree density
                fuel_consumption_per_ha = 4.0  # L diesel/ha (apple orchards typical)
            elif application_method.lower() in ["injection", "incorporation"]:
                # Soil injection requires more power for penetration
                # Real-world: 2.5-4.0 L diesel/ha for injection equipment
                fuel_consumption_per_ha = 3.0  # L diesel/ha (2x previous estimate)
            elif application_method.lower() in ["drip_irrigation", "drip", "micro_irrigation", "precision_irrigation"]:
                # Drip irrigation - pumping system energy use
                # Electric pumps common, but diesel backup: 0.5-1.0 L diesel/ha
                fuel_consumption_per_ha = 0.7  # L diesel/ha (pumping energy)
            elif application_method.lower() in ["foliar", "foliar_spray", "mist_blower"]:
                # Foliar application with mist blowers CALIBRATED
                # Real-world: 1.8-2.8 L diesel/ha for foliar equipment
                fuel_consumption_per_ha = 1.0  # L diesel/ha (CALIBRATED for chemical efficiency)
            elif application_method.lower() in ["aerial", "aircraft", "helicopter", "drone"]:
                # Aerial application - aircraft fuel consumption
                # Small aircraft: 8-12 L fuel/ha, helicopter: 15-20 L/ha
                fuel_consumption_per_ha = 10.0  # L fuel/ha (aircraft typical)
            elif application_method.lower() in ["hand", "backpack", "manual"]:
                # Manual/backpack sprayers - minimal fuel (small engines)
                # Real-world: 0.5-1.0 L fuel/ha for powered backpack sprayers
                fuel_consumption_per_ha = 0.8  # L fuel/ha
            else:
                # Default for unknown methods - use field crop boom sprayer average
                fuel_consumption_per_ha = 2.0  # L diesel/ha (realistic default)

            total_fuel_liters = area_hectares * fuel_consumption_per_ha
            total_fuel_gallons = total_fuel_liters / 3.78541  # Convert to gallons

            application_emissions = total_fuel_gallons * fuel_factor.value
            fuel_factors_used.append(fuel_factor)
            # Estimated fallback uses the default diesel fuel_factor — already
            # initialized above, no override needed.

        # Total emissions
        total_co2e = manufacturing_emissions + application_emissions

        # Build breakdown based on chemical type
        breakdown = {
            "chemical_type": chemical_type,
            "volume_applied_liters": volume_liters,
            "area_treated_hectares": area_hectares,
            "chemical_mass_kg": total_fertilizer_kg,
            # Only report density when it was actually used (volume→mass conversion).
            # When chemical_mass_kg was provided directly, density is not applicable.
            "formulation_density_kg_per_l": (round(density_applied, 3) if density_applied is not None else None),
            # Historically this was purely manufacturing. Since 2026-07-31 the organic
            # fertiliser branch also folds in post-application field N2O, so the honest
            # label for the aggregate is "product" emissions (everything except the
            # application fuel below). The organic breakdown splits it into
            # processing_emissions_kg_co2e + field_n2o_emissions_kg_co2e; the key below is
            # retained under its old name for backward compatibility with existing readers.
            "manufacturing_emissions_kg_co2e": round(manufacturing_emissions, 3),
            "product_emissions_kg_co2e": round(manufacturing_emissions, 3),
            "application_fuel_liters": total_fuel_liters,
            "application_fuel_gallons": round(total_fuel_gallons, 3),
            "application_fuel_type": application_fuel_type or "diesel",  # Include fuel type for transparency
            "application_emissions_kg_co2e": round(application_emissions, 3),
            "application_method": application_method,
            # Legacy key (backward compatible): now holds the ACTUAL factor applied
            # to the selected fuel type (gasoline, biodiesel, propane, electric kWh, etc.),
            # not the default diesel factor. Frontend displays this as "kg CO₂e/gal (EPA factor)".
            "epa_diesel_factor_kg_co2_per_gallon": round(used_fuel_factor_value, 3),
            # Generic successor key + unit for future frontend use.
            "epa_fuel_factor_kg_co2_per_unit": round(used_fuel_factor_value, 3),
            "epa_fuel_factor_unit": used_fuel_factor_unit,
            "confidence_level": fuel_factor.confidence_level,
        }

        # Add chemical-specific breakdown data including explicit subtype info
        # FIX 2025-12-24: Use actual calculated values instead of hardcoded defaults
        breakdown["chemical_subtype_used"] = chemical_subtype if chemical_subtype else "auto-detected"

        # F03-consistent fix (2026-06): surface when AI manufacturing was omitted because
        # the farmer didn't enter a concentration (no fabricated %AI). Application fuel
        # emissions are unaffected. Lets the UI/audit show "enter concentration for an
        # accurate manufacturing estimate" instead of a silently-invented number.
        breakdown["active_ingredient_concentration_provided"] = not ai_concentration_missing
        if ai_concentration_missing:
            breakdown["manufacturing_emissions_omitted"] = True
            breakdown["manufacturing_omitted_reason"] = (
                "Active-ingredient concentration not provided — manufacturing emissions omitted "
                "rather than assuming a default %AI. Enter the product concentration for an "
                "accurate estimate."
            )

        # Track if user provided concentration vs using default
        concentration_source = "user_provided" if user_concentration else "default"

        if chemical_type.lower() in ["pesticide", "pe"]:
            if is_organic_pesticide:
                organic_pesticide_factor = cls.EPA_CHEMICAL_FACTORS["organic_pesticide_manufacturing"]
                breakdown.update(
                    {
                        # FIX: Use actual calculated values
                        "active_ingredient_percentage": round(active_ingredient_percentage * 100, 1),
                        "active_ingredient_kg": round(active_ingredient_kg, 3),
                        "concentration_source": concentration_source,
                        "emission_factor_kg_co2_per_kg": organic_pesticide_factor.value,
                        "pesticide_subtype": "organic",
                        "note": "Organic pesticide (neem, pyrethrin) uses lower emission factor than synthetic pesticides",
                        "note_code": "organic_pesticide",
                        "confidence_level": min(
                            organic_pesticide_factor.confidence_level, fuel_factor.confidence_level
                        ),
                    }
                )
            elif is_biological_pesticide:
                biological_pesticide_factor = cls.EPA_CHEMICAL_FACTORS["biological_pesticide_manufacturing"]
                breakdown.update(
                    {
                        # FIX: Use actual calculated values
                        "active_ingredient_percentage": round(active_ingredient_percentage * 100, 1),
                        "active_ingredient_kg": round(active_ingredient_kg, 3),
                        "concentration_source": concentration_source,
                        "emission_factor_kg_co2_per_kg": biological_pesticide_factor.value,
                        "pesticide_subtype": "biological",
                        "note": "Biological pesticide (Bt, Spinosad) uses lower emission factor due to fermentation-based production",
                        "note_code": "biological_pesticide",
                        "confidence_level": min(
                            biological_pesticide_factor.confidence_level, fuel_factor.confidence_level
                        ),
                    }
                )
            else:
                pesticide_factor = cls.EPA_CHEMICAL_FACTORS["pesticide_manufacturing"]
                breakdown.update(
                    {
                        # FIX: Use actual calculated values
                        "active_ingredient_percentage": round(active_ingredient_percentage * 100, 1),
                        "active_ingredient_kg": round(active_ingredient_kg, 3),
                        "concentration_source": concentration_source,
                        "epa_pesticide_factor_kg_co2_per_kg": pesticide_factor.value,
                        "pesticide_subtype": "synthetic",
                        "confidence_level": min(pesticide_factor.confidence_level, fuel_factor.confidence_level),
                    }
                )
        elif chemical_type.lower() in ["herbicide", "he"]:
            if is_organic_herbicide:
                organic_herbicide_factor = cls.EPA_CHEMICAL_FACTORS["organic_herbicide_manufacturing"]
                breakdown.update(
                    {
                        # FIX 2025-12-24: Use actual calculated values
                        "active_ingredient_percentage": round(active_ingredient_percentage * 100, 1),
                        "active_ingredient_kg": round(active_ingredient_kg, 3),
                        "concentration_source": concentration_source,
                        "emission_factor_kg_co2_per_kg": organic_herbicide_factor.value,
                        "herbicide_subtype": "organic",
                        "note": "Organic herbicide (acetic acid/vinegar) uses lower emission factor than synthetic herbicides",
                        "note_code": "organic_herbicide",
                        "confidence_level": min(
                            organic_herbicide_factor.confidence_level, fuel_factor.confidence_level
                        ),
                    }
                )
            else:
                herbicide_factor = cls.EPA_CHEMICAL_FACTORS["herbicide_manufacturing"]
                breakdown.update(
                    {
                        # FIX 2025-12-24: Use actual calculated values
                        "active_ingredient_percentage": round(active_ingredient_percentage * 100, 1),
                        "active_ingredient_kg": round(active_ingredient_kg, 3),
                        "concentration_source": concentration_source,
                        "emission_factor_kg_co2_per_kg": herbicide_factor.value,
                        "herbicide_subtype": "synthetic",
                        "confidence_level": min(herbicide_factor.confidence_level, fuel_factor.confidence_level),
                    }
                )
        elif chemical_type.lower() in ["fungicide", "fu"]:
            if is_copper_fungicide:
                copper_fungicide_factor = cls.EPA_CHEMICAL_FACTORS["copper_fungicide_manufacturing"]
                breakdown.update(
                    {
                        # FIX 2025-12-24: Use actual calculated values
                        "active_ingredient_percentage": round(active_ingredient_percentage * 100, 1),
                        "active_ingredient_kg": round(active_ingredient_kg, 3),
                        "concentration_source": concentration_source,
                        "emission_factor_kg_co2_per_kg": copper_fungicide_factor.value,
                        "fungicide_subtype": "copper",
                        "note": "Copper-based fungicide uses higher emission factor due to copper mining/refining energy intensity",
                        "note_code": "copper_fungicide",
                        "confidence_level": min(copper_fungicide_factor.confidence_level, fuel_factor.confidence_level),
                    }
                )
            elif is_sulfur_fungicide:
                sulfur_fungicide_factor = cls.EPA_CHEMICAL_FACTORS["sulfur_fungicide_manufacturing"]
                breakdown.update(
                    {
                        # FIX 2025-12-24: Use actual calculated values
                        "active_ingredient_percentage": round(active_ingredient_percentage * 100, 1),
                        "active_ingredient_kg": round(active_ingredient_kg, 3),
                        "concentration_source": concentration_source,
                        "emission_factor_kg_co2_per_kg": sulfur_fungicide_factor.value,
                        "fungicide_subtype": "sulfur",
                        "note": "Sulfur-based fungicide uses lower emission factor as sulfur is often a byproduct of oil/gas refining",
                        "note_code": "sulfur_fungicide",
                        "confidence_level": min(sulfur_fungicide_factor.confidence_level, fuel_factor.confidence_level),
                    }
                )
            elif is_biological_fungicide:
                biological_fungicide_factor = cls.EPA_CHEMICAL_FACTORS["biological_fungicide_manufacturing"]
                breakdown.update(
                    {
                        # FIX 2025-12-24: Use actual calculated values
                        "active_ingredient_percentage": round(active_ingredient_percentage * 100, 1),
                        "active_ingredient_kg": round(active_ingredient_kg, 3),
                        "concentration_source": concentration_source,
                        "emission_factor_kg_co2_per_kg": biological_fungicide_factor.value,
                        "fungicide_subtype": "biological",
                        "note": "Biological fungicide (Bacillus, Trichoderma) uses lower emission factor due to fermentation-based production",
                        "note_code": "biological_fungicide",
                        "confidence_level": min(
                            biological_fungicide_factor.confidence_level, fuel_factor.confidence_level
                        ),
                    }
                )
            elif is_organic_fungicide:
                organic_fungicide_factor = cls.EPA_CHEMICAL_FACTORS["organic_fungicide_manufacturing"]
                breakdown.update(
                    {
                        "active_ingredient_percentage": round(active_ingredient_percentage * 100, 1),
                        "active_ingredient_kg": round(active_ingredient_kg, 3),
                        "concentration_source": concentration_source,
                        "emission_factor_kg_co2_per_kg": organic_fungicide_factor.value,
                        "fungicide_subtype": "organic",
                        "note": "Organic fungicide (neem oil, potassium bicarbonate) uses lower emission factor due to natural extraction",
                        "note_code": "organic_fungicide",
                        "confidence_level": min(
                            organic_fungicide_factor.confidence_level, fuel_factor.confidence_level
                        ),
                    }
                )
            else:
                fungicide_factor = cls.EPA_CHEMICAL_FACTORS["fungicide_manufacturing"]
                breakdown.update(
                    {
                        # FIX 2025-12-24: Use actual calculated values
                        "active_ingredient_percentage": round(active_ingredient_percentage * 100, 1),
                        "active_ingredient_kg": round(active_ingredient_kg, 3),
                        "concentration_source": concentration_source,
                        "emission_factor_kg_co2_per_kg": fungicide_factor.value,
                        "fungicide_subtype": "synthetic",
                        "confidence_level": min(fungicide_factor.confidence_level, fuel_factor.confidence_level),
                    }
                )
        else:
            # Fertilizer breakdown
            n_kg = total_fertilizer_kg * n_percentage
            p_kg = total_fertilizer_kg * p_percentage
            k_kg = total_fertilizer_kg * k_percentage

            if is_organic_fertilizer:
                organic_fertilizer_factor = cls.EPA_CHEMICAL_FACTORS["organic_fertilizer_manufacturing"]
                field_n2o_factor = cls.EPA_CHEMICAL_FACTORS["nitrogen_field_n2o"]
                breakdown.update(
                    {
                        "fertilizer_subtype": "organic",
                        "emission_factor_kg_co2_per_kg": organic_fertilizer_factor.value,
                        # Show the nitrogen basis. Previously the organic branch reported only a
                        # per-kg-of-PRODUCT rate, so a dilute liquid was charged for its water
                        # and the applied N was invisible in the audit trail.
                        "nitrogen_kg": round(n_kg, 3),
                        "processing_emissions_kg_co2e": round(total_fertilizer_kg * organic_fertilizer_factor.value, 3),
                        "field_n2o_factor_kg_co2e_per_kg_n": field_n2o_factor.value,
                        "field_n2o_emissions_kg_co2e": round(n_kg * field_n2o_factor.value, 3),
                        "note": (
                            "Organic fertilizer: minimal manufacturing/processing emissions, plus "
                            "post-application field N2O on the nitrogen applied (IPCC 2019 "
                            "Refinement direct + indirect). Field N2O depends on the nitrogen, "
                            "not on how it was made."
                        ),
                        "note_code": "organic_fertilizer",
                        "confidence_level": min(
                            organic_fertilizer_factor.confidence_level,
                            field_n2o_factor.confidence_level,
                            fuel_factor.confidence_level,
                        ),
                    }
                )
            elif is_slow_release_fertilizer:
                breakdown.update(
                    {
                        "npk_content": npk_content,
                        "nitrogen_kg": n_kg,
                        "phosphorus_kg": p_kg,
                        "potassium_kg": k_kg,
                        "fertilizer_subtype": "slow_release",
                        "epa_nitrogen_factor_kg_co2_per_kg_n": nitrogen_factor.value,
                        "epa_phosphorus_factor_kg_co2_per_kg_p": phosphorus_factor.value,
                        "epa_potassium_factor_kg_co2_per_kg_k": potassium_factor.value,
                        "coating_premium_percent": 10,
                        # "has better efficiency" was an unsourced benefit claim; the factual part is the premium.
                        "note": "Slow-release fertilizer: the factor includes a 10% premium for the coating.",
                        "note_code": "slow_release_fertilizer",
                        "confidence_level": min(
                            nitrogen_factor.confidence_level,
                            phosphorus_factor.confidence_level,
                            potassium_factor.confidence_level,
                            fuel_factor.confidence_level,
                        ),
                    }
                )
            else:
                breakdown.update(
                    {
                        "npk_content": npk_content,
                        "nitrogen_kg": n_kg,
                        "phosphorus_kg": p_kg,
                        "potassium_kg": k_kg,
                        "fertilizer_subtype": "synthetic",
                        "epa_nitrogen_factor_kg_co2_per_kg_n": nitrogen_factor.value,
                        "epa_phosphorus_factor_kg_co2_per_kg_p": phosphorus_factor.value,
                        "epa_potassium_factor_kg_co2_per_kg_k": potassium_factor.value,
                        "confidence_level": min(
                            nitrogen_factor.confidence_level,
                            phosphorus_factor.confidence_level,
                            potassium_factor.confidence_level,
                            fuel_factor.confidence_level,
                        ),
                    }
                )

        return {
            "co2e_kg": round(total_co2e, 3),
            "calculation_method": "verified_epa_usda_factors",
            "breakdown": breakdown,
            "data_sources": list(dict.fromkeys(f.source for f in manufacturing_factors + fuel_factors_used)),
            # One provenance per applied factor class: "published", "internal_estimate", ...
            "factor_provenance": sorted({f.provenance for f in manufacturing_factors + fuel_factors_used}),
            "limitations": (
                "Each input uses the factor named for it in data_sources; application estimates vary "
                "with equipment and conditions"
            ),
        }

    @classmethod
    def _is_organic_herbicide(cls, product_name: str) -> bool:
        """
        Detect if a herbicide is organic/vinegar-based (acetic acid).

        BLACK-BOX VALIDATED (2025-01-21):
        Acetic acid production emits only 0.64-1.2 kg CO2e/kg (ScienceDirect LCA studies)
        vs 5.5 kg CO2e/kg for synthetic herbicides like glyphosate.

        Returns True if the product appears to be organic/vinegar-based.
        """
        organic_keywords = [
            "vinegar",
            "acetic",
            "organic",
            "natural",
            "eco-friendly",
            "biodegradable",
            "citrus",
            "clove oil",
            "citric acid",
            "d-limonene",
            "eugenol",
            "fatty acid",
            "pelargonic",
            "ammonium nonanoate",
            "herbicidal soap",
        ]
        product_lower = product_name.lower()
        return any(keyword in product_lower for keyword in organic_keywords)

    @classmethod
    def _is_copper_fungicide(cls, product_name: str) -> bool:
        """
        Detect if a fungicide is copper-based.

        BLACK-BOX VALIDATED (2025-01-21):
        Copper-based fungicides have higher emissions (5-6 kg CO2e/kg AI)
        due to copper mining and refining energy intensity.
        Source: International Copper Association - Copper Production LCA

        Returns True if the product appears to be copper-based.
        """
        copper_keywords = [
            "copper",
            "cupric",
            "copper sulfate",
            "copper hydroxide",
            "copper oxychloride",
            "bordeaux",
            "kocide",
            "champion",
            "cuprofix",
            "nordox",
            "champ",
            "basicop",
            "cu-based",
        ]
        product_lower = product_name.lower()
        return any(keyword in product_lower for keyword in copper_keywords)

    @classmethod
    def _get_fertilizer_density(cls, npk_content: dict, application_method: str = "broadcast") -> float:
        """
        Get accurate fertilizer density based on NPK content and application method.

        CRITICAL FIX: Anhydrous ammonia (82-0-0) has density ~0.68 kg/L,
        not the generic 1.0 kg/L average. This significantly impacts carbon calculations.

        Source: USDA Agricultural Research Service Fertilizer Density Tables
        """
        n_percentage = npk_content.get("N", 0)
        p_percentage = npk_content.get("P", 0)
        k_percentage = npk_content.get("K", 0)

        # Log density calculation for troubleshooting (minimal logging)
        import logging

        logger = logging.getLogger(__name__)

        method = application_method.lower()

        # Special case: Anhydrous ammonia (82-0-0 or similar high N, no P/K)
        if n_percentage >= 80 and p_percentage == 0 and k_percentage == 0:
            return 0.68  # kg/L

        # High nitrogen liquid fertilizers (UAN solutions) - ENHANCED
        elif n_percentage >= 25 and any(term in method for term in ["injection", "spray", "drip", "fertigation"]):
            return 1.30  # kg/L

        # Specific high-precision injection methods - Always high N density
        elif any(term in method for term in ["injection", "trunk_injection"]):
            return 1.30  # kg/L

        # Fertigation and irrigation-based liquid methods
        elif any(term in method for term in ["fertigation", "irrigation"]):
            return 1.25  # kg/L

        # Standard liquid fertilizers - ENHANCED
        elif any(term in method for term in ["spray", "drip", "foliar", "drench", "liquid"]):
            return 1.25  # kg/L

        # Granular/dry fertilizers - ENHANCED to support all frontend methods
        elif any(
            term in method
            for term in [
                "broadcast",
                "incorporation",
                "incorporated",
                "band",
                "surface",
                "granular",
                "spreader",
                "side_dress",
            ]
        ):
            return 0.80  # kg/L

        # Default for unknown cases (conservative estimate)
        else:
            logger.warning(f"Unknown application method '{application_method}', using default 1.0 kg/L density")
            return 1.0  # kg/L

    @classmethod
    def _get_chemical_density(
        cls,
        chemical_type: str,
        chemical_subtype: str = "",
        product_name: str = "",
        organic_approved: str = "",
    ) -> float:
        """
        Get accurate density (kg/L) for pesticide / herbicide / fungicide
        formulations. Distinct from `_get_fertilizer_density()`, which returns
        NPK-weighted values tuned for fertilizer manufacturing.

        Formulated agrichemicals are mostly water-based suspensions/solutions
        around 1.0 kg/L, with notable exceptions for oil-based organics
        (d-limonene, neem, citrus → ~0.85-0.92) and metal-heavy suspensions
        (copper fungicides → ~1.20-1.25).

        Precedence order (highest to lowest):
          1. Explicit chemical_subtype from the UI dropdown — user's choice
             always wins over free-text product name.
          2. Product-name keyword detection — covers products where subtype
             was not selected (voice input, template fill, legacy data).
          3. Subtype-driven organic defaults — when no keyword matched but
             the subtype or organic_approved flag indicates organic status.
          4. Synthetic EC/SC default (1.05 kg/L).

        Matches the chemical_type / chemical_subtype precedence used by the
        manufacturing emission factor selection block above (~line 2128).

        Density sources:
          - EPA Pesticide Product Label System
          - USDA ARS Pesticide Formulation Guidelines
          - Knowles, D. "Chemistry and Technology of Agrochemical Formulations"
            (Springer 1998) — formulation density tables
          - International Copper Association — Copper Bordeaux product data
        """
        subtype_lower = (chemical_subtype or "").lower()
        product_lower = (product_name or "").lower()
        type_lower = (chemical_type or "").lower()
        organic_lower = (organic_approved or "").lower()

        is_certified_organic = organic_lower in [
            "omri_listed",
            "organic_equivalent",
            "organic_certified",
            "organic",
            "usda_organic",
            "certified_organic",
        ]

        # ---- TIER 1: Explicit subtype checks (user's UI choice, highest priority) ----
        # Copper-based fungicides — heavy metal suspensions (1.20-1.30 kg/L).
        # Explicit subtype wins even if the product name also mentions oil/neem.
        if subtype_lower in ["copper_fungicide", "copper"]:
            return 1.25  # kg/L
        # Sulfur fungicides — elemental sulfur suspensions (1.05-1.15 kg/L)
        if subtype_lower in ["sulfur_fungicide", "sulfur"]:
            return 1.10  # kg/L
        # Biological agents (Bt, Spinosad, Trichoderma) — aqueous suspensions
        if subtype_lower in ["biological_pesticide", "biological_fungicide", "biological"]:
            return 1.00  # kg/L

        # ---- TIER 2: Product-name keyword detection ----
        # Oil-based organic formulations (d-limonene, neem, citrus, clove).
        # Density: 0.85-0.92 kg/L. Use 0.88 as representative mid-range.
        oil_based_keywords = [
            "d-limonene",
            "limonene",
            "citrus",
            "neem",
            "clove oil",
            "eugenol",
            "essential oil",
            "fatty acid",
            "herbicidal soap",
        ]
        if any(kw in product_lower for kw in oil_based_keywords):
            return 0.88  # kg/L

        # Copper fungicide by product name (when subtype not explicitly set)
        if cls._is_copper_fungicide(product_lower):
            return 1.25  # kg/L

        # Sulfur fungicide by product name
        if "sulfur" in product_lower:
            return 1.10  # kg/L

        # Acetic-acid / vinegar / citric-acid herbicides — aqueous organic acids.
        # Density close to water (1.02-1.05 kg/L).
        if any(kw in product_lower for kw in ["vinegar", "acetic", "citric"]):
            return 1.03  # kg/L

        # ---- TIER 3: Organic subtype defaults (no product match) ----
        # Matches the manufacturing factor selection rules:
        #   - organic_herbicide accepts "organic" as shorthand
        #   - organic_pesticide accepts "organic" as shorthand
        #   - organic_fungicide does NOT accept "organic" (specific code only)
        if subtype_lower in ["organic_herbicide", "organic"] and type_lower in ["herbicide", "he"]:
            return 0.88  # kg/L
        if is_certified_organic and type_lower in ["herbicide", "he"]:
            return 0.88  # kg/L
        if subtype_lower in ["organic_pesticide", "organic"] and type_lower in ["pesticide", "pe"]:
            return 0.92  # kg/L
        if is_certified_organic and type_lower in ["pesticide", "pe"]:
            return 0.92  # kg/L
        if subtype_lower == "organic_fungicide" or (is_certified_organic and type_lower in ["fungicide", "fu"]):
            return 0.95  # kg/L

        # ---- TIER 4: Synthetic default (EC/SC formulations) ----
        # Slightly heavier than water due to adjuvants and solvent carriers.
        # 1.05 kg/L is the industry median for emulsifiable concentrates.
        return 1.05  # kg/L

    @classmethod
    def _validate_production_emissions(
        cls, co2e_kg: float, area_covered_acres: float, operation_type: str, breakdown: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate production emissions for realistic values and detect calculation errors.

        CRITICAL: Prevents 26x overestimation issues by catching unit conversion errors
        and unrealistic emission values.
        """
        warnings = []
        limitations = []

        # Convert area to hectares for validation
        area_hectares = area_covered_acres * 0.404686

        # If area is 0 and emissions are 0, no validation needed
        if area_hectares <= 0 and co2e_kg <= 0:
            return {"co2e_kg": 0.0, "breakdown": breakdown, "warnings": [], "limitations": []}

        # Define realistic emission ranges per hectare for different operations
        realistic_ranges = {
            "harvesting": {"min": 8.0, "max": 50.0},  # 8-50 kg CO₂e per hectare
            "planting": {"min": 5.0, "max": 35.0},  # 5-35 kg CO₂e per hectare
            "general_crop_production": {"min": 6.0, "max": 40.0},  # 6-40 kg CO₂e per hectare
            "soil_cultivation": {"min": 10.0, "max": 60.0},  # 10-60 kg CO₂e per hectare
            "fertilization": {"min": 3.0, "max": 25.0},  # 3-25 kg CO₂e per hectare
            "weeding": {"min": 2.0, "max": 15.0},  # 2-15 kg CO₂e per hectare
            "mulching": {"min": 5.0, "max": 30.0},  # 5-30 kg CO₂e per hectare
            "pruning": {"min": 0.5, "max": 8.0},  # 0.5-8 kg CO₂e per hectare
            "thinning": {"min": 0.75, "max": 8.0},  # 0.75-8 kg CO₂e per hectare
        }

        # Get range for this operation type
        operation_range = realistic_ranges.get(operation_type, {"min": 5.0, "max": 50.0})

        # Calculate emissions per hectare
        emissions_per_hectare = co2e_kg / area_hectares if area_hectares > 0 else co2e_kg

        # Check for unrealistic values
        if emissions_per_hectare > operation_range["max"]:
            overestimation_factor = emissions_per_hectare / operation_range["max"]
            warnings.append(f"CRITICAL: Emissions {overestimation_factor:.1f}x higher than realistic range")
            warnings.append(
                f"Result: {emissions_per_hectare:.1f} kg CO₂e/ha, expected: {operation_range['min']}-{operation_range['max']} kg CO₂e/ha"
            )

            # Cap the result at maximum realistic value
            corrected_co2e = area_hectares * operation_range["max"]
            warnings.append(f"Auto-corrected from {co2e_kg:.1f} to {corrected_co2e:.1f} kg CO₂e")

            # Update breakdown with correction info
            breakdown["validation_applied"] = True
            breakdown["original_result_kg"] = co2e_kg
            breakdown["corrected_result_kg"] = corrected_co2e
            breakdown["correction_reason"] = f"Exceeded realistic {operation_type} emissions range"
            breakdown["emissions_per_hectare"] = emissions_per_hectare
            breakdown["realistic_range_kg_per_hectare"] = operation_range

            limitations.append(f"Result capped at realistic maximum for {operation_type} operations")

            return {"co2e_kg": corrected_co2e, "breakdown": breakdown, "warnings": warnings, "limitations": limitations}

        elif emissions_per_hectare < operation_range["min"]:
            # Special case: zero emissions from renewable energy sources
            if emissions_per_hectare == 0:
                warnings.append("Zero emissions from renewable energy source (solar/wind)")
                breakdown["emissions_per_hectare"] = 0
                breakdown["realistic_range_kg_per_hectare"] = operation_range
                breakdown["renewable_energy_credit"] = True
            else:
                underestimation_factor = operation_range["min"] / emissions_per_hectare
                warnings.append(f"Low emissions: {underestimation_factor:.1f}x lower than typical range")
                warnings.append(
                    f"Result: {emissions_per_hectare:.1f} kg CO₂e/ha, typical: {operation_range['min']}-{operation_range['max']} kg CO₂e/ha"
                )

                # Don't correct low values, just warn
                breakdown["emissions_per_hectare"] = emissions_per_hectare
                breakdown["realistic_range_kg_per_hectare"] = operation_range

        else:
            # Result is within realistic range
            breakdown["emissions_per_hectare"] = emissions_per_hectare
            breakdown["realistic_range_kg_per_hectare"] = operation_range
            breakdown["validation_status"] = "within_realistic_range"

        return {"co2e_kg": co2e_kg, "breakdown": breakdown, "warnings": warnings, "limitations": limitations}
