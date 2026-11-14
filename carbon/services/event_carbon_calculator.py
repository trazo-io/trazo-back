import logging
import re
import time
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.utils import timezone

from common.us_states import normalize_state, resolve_establishment_state, resolve_event_state

from ..models import CarbonEntry, CarbonSource, USDACalculationAudit, USDAComplianceRecord
from .emission_factors import emission_factors
from .enhanced_emission_factors import EnhancedEmissionFactors
from .enhanced_usda_factors import EnhancedUSDAFactors
from .verified_emission_factors import VERIFICATION_STATUS_ESTIMATE, figure_basis, verification_status_for

logger = logging.getLogger(__name__)


def count_amount_result(count, unit, chemical_type=None) -> Dict[str, Any]:
    """The carbon result for an amount recorded as a COUNT (pheromone dispensers).

    A count has no product mass or volume, so there is nothing to multiply an emission factor by.
    Shared by the stored-record calculator and the form preview, so both say the same thing:
    nothing calculated, why, and never "verified".
    """
    try:
        shown = f"{float(count):g} {unit}"
    except (TypeError, ValueError):
        shown = f"{count} {unit}".strip() if count not in (None, "") else str(unit)
    return {
        "co2e": 0.0,
        "calculation_method": "amount_is_count_not_converted",
        "verification_status": "insufficient_data",
        "breakdown": {
            "amount_is_count": True,
            "amount_count": count,
            "amount_unit": unit,
            "chemical_type": chemical_type,
        },
        "data_sources": [],
        "limitations": (
            f"The amount is recorded as a count ({shown}), not a weight or volume. No emissions "
            "are calculated from a count; application fuel on this record is not included either."
        ),
    }


# Soil subtypes that record a sample being taken: soil test (ST) and lab analysis (LA). The
# sample is taken by hand and the lab work is upstream, so with no fuel recorded there is no
# direct emission to count (`soil_test` factor, 0 kg CO2e per hectare).
SAMPLING_SUBTYPES = frozenset({"ST", "LA"})

# How the carbonate-lime component is computed: IPCC 2006 Vol 4 Ch 11 Eq. 11.12 on the applied
# mass, with the whole release assigned to the year of application. Served beside the figure so
# no surface reads it as a release measured on the application date (Astra follow-up B1).
LIME_CALCULATION_BASIS = "IPCC 2006 Tier 1, assigned to application year"

# Soil area factors that stand in for the operation's equipment fuel, per their own notes in
# EmissionFactorsRegistry.SOIL_MANAGEMENT_FACTORS: tillage 1.2 kg/ha ("base equipment fuel
# emissions only") and ph_adjustment 0.3 kg/ha ("base application emissions"). When the record
# carries the fuel, the default is replaced by it, not added to it: adding both counted the same
# diesel twice. The other soil factors are not fuel proxies (sequestration credits for cover crops,
# compost and organic matter; compaction for grazing; zero for sampling and habitat) and stay
# additive.
FUEL_PROXY_SOIL_FACTORS = frozenset({"tillage", "ph_adjustment"})


class EventCarbonCalculator:
    """
    Service for calculating carbon impact from agricultural events.
    Implements USDA emission factors and industry best practices.
    Enhanced with regional USDA factors, real-time API integration, and compliance validation.
    """

    # USDA Emission Factors (kg CO2e per unit) - Now sourced from centralized registry
    @property
    def USDA_FERTILIZER_FACTORS(self):
        """Get USDA fertilizer factors from centralized registry (legacy compatibility)"""
        return {
            "nitrogen": emission_factors.get_fertilizer_factor("nitrogen")["value"],
            "phosphorus": emission_factors.get_fertilizer_factor("phosphorus")["value"],
            "potassium": emission_factors.get_fertilizer_factor("potassium")["value"],
        }

    def _get_climate_aware_fertilizer_factors(self, event, application_method: str = "broadcast") -> Dict[str, float]:
        """
        Get climate-aware fertilizer factors based on farm location and application method.
        Uses the new corrected USDA values with climate and application adjustments.
        """
        try:
            # Get farm location
            latitude, longitude, state = self._get_farm_coordinates(event)

            # Get enhanced factors with climate and application method adjustments
            enhanced_factors = emission_factors.get_enhanced_fertilizer_factors(
                nutrients=["nitrogen", "phosphorus", "potassium"],
                latitude=latitude,
                longitude=longitude,
                state=state,
                application_methods={
                    "nitrogen": application_method,
                    "phosphorus": application_method,
                    "potassium": application_method,
                },
            )

            # Extract values for calculation
            return {
                "nitrogen": enhanced_factors["nitrogen"]["value"],
                "phosphorus": enhanced_factors["phosphorus"]["value"],
                "potassium": enhanced_factors["potassium"]["value"],
                "metadata": {
                    "climate_zone": enhanced_factors["nitrogen"]["climate_zone"],
                    "precipitation": enhanced_factors["nitrogen"]["annual_precipitation"],
                    "application_method": application_method,
                    "adjustments_applied": enhanced_factors["nitrogen"]["adjustments_applied"],
                    "version": enhanced_factors["nitrogen"]["version"],
                },
            }

        except Exception as e:
            logger.error(f"Error getting climate-aware fertilizer factors: {e}")
            # Fallback to base factors
            return {
                "nitrogen": emission_factors.get_fertilizer_factor("nitrogen")["value"],
                "phosphorus": emission_factors.get_fertilizer_factor("phosphorus")["value"],
                "potassium": emission_factors.get_fertilizer_factor("potassium")["value"],
                "metadata": {
                    "climate_zone": "unknown",
                    "application_method": application_method,
                    "fallback_used": True,
                    "error": str(e),
                },
            }

    @property
    def FUEL_EMISSION_FACTORS(self):
        """Get fuel emission factors from centralized registry (choices.py).

        F08 fix (2026-06): the static choices.py `electric` value is the US grid
        (0.365). Override it with the operating country's grid factor so equipment
        and other electric calc paths don't leak US emissions for a UY deployment.
        """
        from carbon.choices import FUEL_TYPE_FACTORS

        from .verified_emission_factors import VerifiedEmissionFactors

        factors = {fuel: data["value"] for fuel, data in FUEL_TYPE_FACTORS.items()}
        factors["electric"] = VerifiedEmissionFactors.get_country_electricity_factor().value
        return factors

    @property
    def APPLICATION_EFFICIENCY(self):
        """Get application efficiency factors from centralized registry (legacy compatibility)"""
        return {method: data["value"] for method, data in emission_factors.APPLICATION_EFFICIENCY_FACTORS.items()}

    @property
    def CROP_SPECIFIC_FACTORS(self):
        """Get crop-specific factors from centralized registry (legacy compatibility)"""
        return {crop: data["value"] for crop, data in emission_factors.CROP_SPECIFIC_FACTORS.items()}

    @property
    def CROP_FERTILIZER_EFFICIENCY(self):
        """Get crop fertilizer efficiency factors from centralized registry (legacy compatibility)"""
        return {category: data["value"] for category, data in emission_factors.CROP_FERTILIZER_EFFICIENCY.items()}

    def __init__(self):
        self.current_year = timezone.now().year
        self.enhanced_usda = EnhancedUSDAFactors()

        # Log initialization with centralized factors
        logger.info(f"EventCarbonCalculator initialized with centralized emission factors v{emission_factors.VERSION}")
        logger.info(f"Nitrogen factor: {self.USDA_FERTILIZER_FACTORS['nitrogen']} kg CO2e per kg N (USDA-verified)")
        logger.info(f"Loaded {len(emission_factors.CROP_SPECIFIC_FACTORS)} centralized crop factors")

    def _get_usda_emission_factors(self) -> Dict[str, float]:
        """Get base USDA emission factors for compatibility"""
        # Use centralized factors to ensure consistency
        factors = emission_factors.get_all_factors_simple()
        return {
            "nitrogen": factors["nitrogen"],
            "phosphorus": factors["phosphorus"],
            "potassium": factors["potassium"],
            "diesel": factors["diesel"],
            "gasoline": factors["gasoline"],
            "natural_gas": factors["natural_gas"],
        }

    def _get_establishment_location(self, event) -> tuple:
        """Return (state_code_or_None, county).

        County is always None: `Establishment` has no `county` field, so the
        previous `getattr(establishment, "county", None)` could never return a
        value. It is kept in the tuple because four call sites unpack it.
        """
        return resolve_event_state(event), None

    def _get_farm_coordinates(self, event) -> tuple:
        """
        Extract farm coordinates and location information from event.
        Returns (latitude, longitude, state)
        """
        try:
            # Try to get coordinates from establishment
            if (
                hasattr(event, "history")
                and event.history
                and hasattr(event.history, "parcel")
                and event.history.parcel
                and hasattr(event.history.parcel, "establishment")
                and event.history.parcel.establishment
            ):
                establishment = event.history.parcel.establishment

                # Get coordinates if available
                latitude = getattr(establishment, "latitude", None)
                longitude = getattr(establishment, "longitude", None)
                # None when the farm's state is missing or not a US state. Callers
                # must fall back to national factors rather than assuming a state —
                # this used to default to "CA", which costed a Florida farm as
                # Californian and still recorded regional_adjustments_applied=True.
                state = resolve_establishment_state(establishment)

                # If coordinates are available, use them
                if latitude is not None and longitude is not None:
                    return float(latitude), float(longitude), state

                # If no coordinates, use state for regional estimates
                return None, None, state

        except Exception as e:
            logger.error(f"Error getting farm coordinates: {e}")

        return None, None, None

    def _get_real_time_usda_factors(self, crop_type: str, state: str) -> Dict[str, float]:
        """Get USDA emission factors using hardcoded EPA/USDA regional factors."""
        return self.enhanced_usda.get_regional_factors(crop_type, state)

    def _calculate_confidence_score(self, event, calculation_data: Dict) -> float:
        """NEW METHOD: Calculate confidence score for carbon calculation"""
        try:
            confidence_factors = []

            # Factor 1: Data completeness (0.0 - 0.3)
            required_fields = ["crop_type", "area", "amount"]
            present_fields = sum(1 for field in required_fields if calculation_data.get(field))
            completeness_score = (present_fields / len(required_fields)) * 0.3
            confidence_factors.append(completeness_score)

            # Factor 2: USDA factor usage (0.0 - 0.4)
            usda_factor_score = 0.4 if calculation_data.get("usda_factors_based", False) else 0.1
            confidence_factors.append(usda_factor_score)

            # Factor 3: Regional specificity (0.0 - 0.2)
            state, county = self._get_establishment_location(event)
            regional_score = 0.2 if state != "Unknown" else 0.0
            if county:
                regional_score += 0.05  # Bonus for county-level data
            confidence_factors.append(min(regional_score, 0.2))

            # Factor 4: Method precision (0.0 - 0.1)
            method_score = 0.1 if calculation_data.get("method") == "detailed" else 0.05
            confidence_factors.append(method_score)

            total_confidence = sum(confidence_factors)
            return min(total_confidence, 1.0)

        except Exception as e:
            logger.error(f"Error calculating confidence score: {e}")
            return 0.5  # Default medium confidence

    # ==========================================================================================
    # Sprint 5: Aggregate Event Support - Calculate carbon for multiple events logged as one summary
    # ==========================================================================================

    def _is_aggregate_event(self, event) -> bool:
        """
        Check if this is an aggregate/summary event (multiple events logged as one).
        Sprint 5: Aggregate Event Logging feature.
        """
        try:
            extra_data = getattr(event, "extra_data", None) or {}
            return extra_data.get("is_summary", False) is True
        except Exception:
            return False

    def _get_aggregate_extra_data(self, event) -> Dict[str, Any]:
        """Extract extra_data from an aggregate event, safely handling None values."""
        try:
            return getattr(event, "extra_data", None) or {}
        except Exception:
            return {}

    def _calculate_aggregate_fuel_emissions(self, fuel_total: float, fuel_type: str, fuel_unit: str) -> float:
        """
        Calculate fuel emissions for aggregate events using the correct fuel type factor.
        Supports diesel, gasoline, propane, biodiesel, electric, natural_gas, and 'none'.
        Returns emissions in kg CO2e.
        """
        if fuel_total <= 0:
            return 0.0

        from .verified_emission_factors import VerifiedEmissionFactors

        fuel_type_lower = (fuel_type or "diesel").lower()

        # Handle electric equipment
        if fuel_type_lower == "electric":
            # fuel_total is in kWh when unit is kWh, convert if needed
            kwh = fuel_total
            if fuel_unit == "L" or fuel_unit == "gal":
                # Nonsensical combination, but treat as kWh anyway
                kwh = fuel_total
            electricity_factor = VerifiedEmissionFactors.get_country_electricity_factor()
            return kwh * electricity_factor.value

        # Handle manual/no fuel
        if fuel_type_lower == "none":
            return 0.0

        # Gaseous fuels are billed per standard cubic foot, not per gallon — hand the raw
        # quantity and its own unit to fuel_co2e rather than pretending litres of gas
        # convert to gallons of gas. A summary/aggregate event (e.g. a season of dryer
        # runs) was under-reporting by ~2 orders of magnitude here, same as the seven
        # per-event paths.
        if fuel_type_lower == "natural_gas":
            co2e, _factor, _err = VerifiedEmissionFactors.fuel_co2e(fuel_total, fuel_type_lower, fuel_unit)
            return co2e

        # Convert to gallons for liquid fuels
        if fuel_unit == "gal":
            fuel_gallons = fuel_total
        else:
            # Default assumes liters
            fuel_gallons = fuel_total / 3.78541

        co2e, _factor, _err = VerifiedEmissionFactors.fuel_co2e(fuel_gallons, fuel_type_lower, "gal")
        return co2e

    @staticmethod
    def _aggregate_basis(product_factors, fuel_total: float, fuel_type: str, omitted_code=None) -> Dict[str, Any]:
        """Status, sources and basis of a summary record, from the factors it applied (2026-11-13).

        Summaries were stored "epa_usda_verified_aggregate" whatever they rested on, citing
        "USDA ARS (fertilizer manufacturing)" for factors that are EPA + IPCC (nitrogen) or Trazo
        estimates (P2O5, K2O, copper, sulfur, organic products). Same rule as a single record: a
        Trazo estimate factor, a fuel costed as diesel, or a part left out makes it an estimate.
        A summary has no area estimate: with no fuel total its application pass is not counted.
        """
        from .verified_emission_factors import VerifiedEmissionFactors

        factors = list(product_factors)
        reasons = [omitted_code] if omitted_code else []
        fuel_type_lower = (fuel_type or "diesel").lower()
        if fuel_type_lower == "none":
            pass  # manual application: no fuel burned, nothing left out
        elif fuel_total > 0:
            if fuel_type_lower == "electric":
                factors.append(VerifiedEmissionFactors.get_country_electricity_factor())
            else:
                if fuel_type_lower not in VerifiedEmissionFactors.EPA_FUEL_FACTORS:
                    reasons.append("fuel_costed_as_diesel")
                factors.append(VerifiedEmissionFactors._get_fuel_factor_for_type(fuel_type_lower)[0])
        else:
            reasons.append("application_not_estimated")
        basis = figure_basis(factors, reasons)
        return {
            **basis,
            "verification_status": verification_status_for(basis, "epa_usda_verified_aggregate"),
            "data_sources": list(dict.fromkeys(f.source for f in factors)),
            "factor_provenance": sorted({f.provenance for f in factors}),
        }

    def _calculate_aggregate_fertilizer_impact(self, event, extra_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate carbon impact for aggregate fertilizer events (multiple applications as one summary).
        Uses pre-calculated NPK totals instead of individual event calculations.

        Sprint 5: Aggregate Chemical Support - Fertilizer
        """
        try:
            from .verified_emission_factors import VerifiedEmissionFactors

            # Extract aggregate totals from extra_data
            n_total_kg = float(extra_data.get("n_total_kg", 0) or 0)
            p_total_kg = float(extra_data.get("p_total_kg", 0) or 0)
            k_total_kg = float(extra_data.get("k_total_kg", 0) or 0)
            event_count = int(extra_data.get("event_count", 1) or 1)
            date_start = extra_data.get("date_start", "")
            date_end = extra_data.get("date_end", "")

            # Get fuel consumption if provided
            fuel_total = float(extra_data.get("fuel_consumption_total", 0) or 0)
            fuel_type = extra_data.get("fuel_type", "diesel") or "diesel"
            fuel_unit = extra_data.get("fuel_unit", "gal") or "gal"

            # Manufacturing from the registry's factors, each with its own provenance: nitrogen is
            # published (EPA + IPCC), P2O5 and K2O are Trazo estimates (carbon-methodology.md).
            # The values were inlined here (10.5, 1.19, 0.65) and the result cited "USDA ARS".
            factors = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS
            n_factor = factors["nitrogen_fertilizer"]
            p_factor = factors["phosphorus_fertilizer"]
            k_factor = factors["potassium_fertilizer"]
            n_emissions = n_total_kg * n_factor.value
            p_emissions = p_total_kg * p_factor.value
            k_emissions = k_total_kg * k_factor.value
            manufacturing_emissions = n_emissions + p_emissions + k_emissions

            # Calculate application fuel emissions using correct fuel type
            application_emissions = self._calculate_aggregate_fuel_emissions(fuel_total, fuel_type, fuel_unit)

            total_emissions = manufacturing_emissions + application_emissions
            basis = self._aggregate_basis(
                [f for f, kg in ((n_factor, n_total_kg), (p_factor, p_total_kg), (k_factor, k_total_kg)) if kg],
                fuel_total,
                fuel_type,
                omitted_code=None if (n_total_kg or p_total_kg or k_total_kg) else "npk_not_recorded",
            )

            breakdown = {
                "is_aggregate": True,
                "event_count": event_count,
                "date_range": f"{date_start} to {date_end}" if date_start and date_end else "Multiple dates",
                "nitrogen_total_kg": n_total_kg,
                "nitrogen_emissions_kg_co2e": round(n_emissions, 3),
                "phosphorus_total_kg": p_total_kg,
                "phosphorus_emissions_kg_co2e": round(p_emissions, 3),
                "potassium_total_kg": k_total_kg,
                "potassium_emissions_kg_co2e": round(k_emissions, 3),
                "manufacturing_emissions_kg_co2e": round(manufacturing_emissions, 3),
                "application_fuel_total": fuel_total,
                "application_fuel_type": fuel_type,
                "application_fuel_unit": fuel_unit,
                "application_emissions_kg_co2e": round(application_emissions, 3),
                "confidence_level": 0.92,
                "figure_basis": basis["figure_basis"],
                "estimate_reasons": basis["estimate_reasons"],
            }

            return {
                "co2e": round(total_emissions, 3),
                "calculation_method": "aggregate_fertilizer_epa_usda",
                **basis,
                "breakdown": breakdown,
                "limitations": f"Aggregate calculation for {event_count} fertilizer applications",
                "recommendations": [
                    {
                        "type": "aggregate_transparency",
                        "message": f"This represents {event_count} fertilizer applications logged as one summary",
                        "impact": "Transparency",
                        "source": "Trazo Aggregate Logging",
                    }
                ],
                "confidence_level": 0.92,
            }

        except Exception as e:
            logger.error(f"Aggregate fertilizer calculation failed: {e}")
            return {
                "co2e": 0.0,
                "verification_status": "aggregate_calculation_error",
                "error": str(e),
            }

    def _calculate_aggregate_fungicide_impact(self, event, extra_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate carbon impact for aggregate fungicide events (multiple applications as one summary).
        Uses pre-calculated active ingredient total.

        ENHANCED 2025-12-24: Support organic/biological fungicide variants with accurate emission factors.
        Uses chemical_subtype from extra_data to select correct emission factor.

        Sprint 5: Aggregate Chemical Support - Fungicide
        """
        try:
            from .verified_emission_factors import VerifiedEmissionFactors

            # Extract aggregate totals from extra_data
            active_ingredient_kg = float(extra_data.get("active_ingredient_total_kg", 0) or 0)
            event_count = int(extra_data.get("event_count", 1) or 1)
            date_start = extra_data.get("date_start", "")
            date_end = extra_data.get("date_end", "")

            # ENHANCED 2025-12-24: Extract chemical_subtype for accurate emission factor
            # FIX: Check extra_data first, then fall back to model field
            chemical_subtype = (
                extra_data.get("chemical_subtype", "") or getattr(event, "chemical_subtype", "") or ""
            ).lower()

            # Get fuel consumption if provided
            fuel_total = float(extra_data.get("fuel_consumption_total", 0) or 0)
            fuel_type = extra_data.get("fuel_type", "diesel") or "diesel"
            fuel_unit = extra_data.get("fuel_unit", "gal") or "gal"

            # ENHANCED 2025-12-24: Select emission factor based on chemical_subtype
            # Default to synthetic fungicide if subtype not specified. The factor object is kept
            # (not only its value) so the result states its source and provenance (2026-11-13).
            chemical_factors = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS
            product_factor = chemical_factors["fungicide_manufacturing"]  # 4.5, synthetic
            emission_factor_label = "synthetic fungicide"

            if chemical_subtype in ["copper_fungicide", "copper"]:
                # Copper-based fungicides (higher due to copper mining/refining)
                product_factor = chemical_factors["copper_fungicide_manufacturing"]
                emission_factor_label = "copper fungicide"
            elif chemical_subtype in ["sulfur_fungicide", "sulfur"]:
                # Sulfur-based fungicides (lower as sulfur is often a byproduct)
                product_factor = chemical_factors["sulfur_fungicide_manufacturing"]
                emission_factor_label = "sulfur fungicide"
            elif chemical_subtype in ["biological_fungicide", "biological"]:
                # Biological fungicides (fermentation-based production)
                product_factor = chemical_factors["biological_fungicide_manufacturing"]
                emission_factor_label = "biological fungicide"
            elif chemical_subtype == "organic_fungicide":
                # Organic fungicides (neem oil, potassium bicarbonate, essential oils)
                product_factor = chemical_factors["organic_fungicide_manufacturing"]
                emission_factor_label = "organic fungicide"
            emission_factor = product_factor.value

            # Calculate manufacturing emissions using selected emission factor
            manufacturing_emissions = active_ingredient_kg * emission_factor

            # Calculate application fuel emissions using correct fuel type
            application_emissions = self._calculate_aggregate_fuel_emissions(fuel_total, fuel_type, fuel_unit)

            total_emissions = manufacturing_emissions + application_emissions
            basis = self._aggregate_basis(
                [product_factor] if active_ingredient_kg else [],
                fuel_total,
                fuel_type,
                omitted_code=None if active_ingredient_kg else "amount_not_recorded",
            )

            breakdown = {
                "is_aggregate": True,
                "event_count": event_count,
                "date_range": f"{date_start} to {date_end}" if date_start and date_end else "Multiple dates",
                "active_ingredient_total_kg": active_ingredient_kg,
                "chemical_subtype": chemical_subtype or "synthetic (default)",
                "manufacturing_emissions_kg_co2e": round(manufacturing_emissions, 3),
                "application_fuel_total": fuel_total,
                "application_fuel_type": fuel_type,
                "application_fuel_unit": fuel_unit,
                "application_emissions_kg_co2e": round(application_emissions, 3),
                "emission_factor_used": f"{emission_factor} kg CO2/kg AI ({emission_factor_label})",
                "confidence_level": 0.90,
                "figure_basis": basis["figure_basis"],
                "estimate_reasons": basis["estimate_reasons"],
            }

            return {
                "co2e": round(total_emissions, 3),
                "calculation_method": "aggregate_fungicide_epa_usda",
                **basis,
                "breakdown": breakdown,
                "limitations": f"Aggregate calculation for {event_count} fungicide applications",
                "recommendations": [
                    {
                        "type": "aggregate_transparency",
                        "message": f"This represents {event_count} fungicide applications logged as one summary",
                        "impact": "Transparency",
                        "source": "Trazo Aggregate Logging",
                    }
                ],
                "confidence_level": 0.90,
            }

        except Exception as e:
            logger.error(f"Aggregate fungicide calculation failed: {e}")
            return {
                "co2e": 0.0,
                "verification_status": "aggregate_calculation_error",
                "error": str(e),
            }

    def _calculate_aggregate_herbicide_impact(self, event, extra_data: Dict[str, Any]) -> Dict[str, Any]:
        """Carbon impact for an aggregate herbicide event (several applications logged as one).

        A6 fix (2026-07). Summary herbicide events had no handler, so the dispatcher's `else`
        branch sent them to `_calculate_aggregate_fertilizer_impact` — which reads
        nitrogen/phosphorus/potassium totals and multiplies by fertilizer manufacturing
        factors. A herbicide summary carries `active_ingredient_total_kg` and no NPK at all,
        so the fertilizer path found zeros and returned a near-zero figure while logging only
        a warning. A grower spraying herbicide across a season saw no emissions from it.

        Mirrors _calculate_aggregate_pesticide_impact, with the herbicide manufacturing
        factors (synthetic 6.3 kg CO2/kg AI, organic 1.2).
        """
        try:
            from .verified_emission_factors import VerifiedEmissionFactors

            active_ingredient_kg = float(extra_data.get("active_ingredient_total_kg", 0) or 0)
            event_count = int(extra_data.get("event_count", 1) or 1)
            date_start = extra_data.get("date_start", "")
            date_end = extra_data.get("date_end", "")

            chemical_subtype = (
                extra_data.get("chemical_subtype", "") or getattr(event, "chemical_subtype", "") or ""
            ).lower()

            fuel_total = float(extra_data.get("fuel_consumption_total", 0) or 0)
            fuel_type = extra_data.get("fuel_type", "diesel") or "diesel"
            fuel_unit = extra_data.get("fuel_unit", "gal") or "gal"

            if chemical_subtype in ["organic_herbicide", "organic"]:
                factor = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["organic_herbicide_manufacturing"]
                emission_factor_label = "organic herbicide"
            else:
                factor = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["herbicide_manufacturing"]
                emission_factor_label = "synthetic herbicide"
            emission_factor = factor.value

            manufacturing_emissions = active_ingredient_kg * emission_factor
            application_emissions = self._calculate_aggregate_fuel_emissions(fuel_total, fuel_type, fuel_unit)
            total_emissions = manufacturing_emissions + application_emissions
            basis = self._aggregate_basis(
                [factor] if active_ingredient_kg else [],
                fuel_total,
                fuel_type,
                omitted_code=None if active_ingredient_kg else "amount_not_recorded",
            )

            breakdown = {
                "is_aggregate": True,
                "event_count": event_count,
                "date_range": f"{date_start} to {date_end}" if date_start and date_end else "Multiple dates",
                "active_ingredient_total_kg": active_ingredient_kg,
                "chemical_subtype": chemical_subtype or "synthetic (default)",
                "manufacturing_emissions_kg_co2e": round(manufacturing_emissions, 3),
                "application_fuel_total": fuel_total,
                "application_fuel_type": fuel_type,
                "application_fuel_unit": fuel_unit,
                "application_emissions_kg_co2e": round(application_emissions, 3),
                "emission_factor_used": f"{emission_factor} kg CO2/kg AI ({emission_factor_label})",
                "confidence_level": 0.90,
                "figure_basis": basis["figure_basis"],
                "estimate_reasons": basis["estimate_reasons"],
            }

            return {
                "co2e": round(total_emissions, 3),
                "calculation_method": "aggregate_herbicide_epa_usda",
                **basis,
                "breakdown": breakdown,
                "limitations": f"Aggregate calculation for {event_count} herbicide applications",
                "recommendations": [],
                "confidence_level": 0.90,
            }

        except Exception as e:
            logger.error(f"Aggregate herbicide calculation failed: {e}")
            return {
                "co2e": 0.0,
                "verification_status": "aggregate_calculation_error",
                "error": str(e),
            }

    def _calculate_aggregate_pesticide_impact(self, event, extra_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate carbon impact for aggregate pesticide events (multiple applications as one summary).
        Uses pre-calculated active ingredient total.

        ENHANCED 2025-12-24: Support organic/biological pesticide variants with accurate emission factors.
        Uses chemical_subtype from extra_data to select correct emission factor.

        Sprint 5: Aggregate Chemical Support - Pesticide
        """
        try:
            from .verified_emission_factors import VerifiedEmissionFactors

            # Extract aggregate totals from extra_data
            active_ingredient_kg = float(extra_data.get("active_ingredient_total_kg", 0) or 0)
            event_count = int(extra_data.get("event_count", 1) or 1)
            date_start = extra_data.get("date_start", "")
            date_end = extra_data.get("date_end", "")

            # ENHANCED 2025-12-24: Extract chemical_subtype for accurate emission factor
            # FIX: Check extra_data first, then fall back to model field
            chemical_subtype = (
                extra_data.get("chemical_subtype", "") or getattr(event, "chemical_subtype", "") or ""
            ).lower()

            # Get fuel consumption if provided
            fuel_total = float(extra_data.get("fuel_consumption_total", 0) or 0)
            fuel_type = extra_data.get("fuel_type", "diesel") or "diesel"
            fuel_unit = extra_data.get("fuel_unit", "gal") or "gal"

            # ENHANCED 2025-12-24: Select emission factor based on chemical_subtype
            # Default to synthetic pesticide if subtype not specified. The factor object is kept
            # (not only its value) so the result states its source and provenance (2026-11-13).
            chemical_factors = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS
            product_factor = chemical_factors["pesticide_manufacturing"]  # 8.8, synthetic
            emission_factor_label = "synthetic pesticide"

            if chemical_subtype in ["organic_pesticide", "organic"]:
                # Organic pesticides (neem, pyrethrin) - naturally-derived
                product_factor = chemical_factors["organic_pesticide_manufacturing"]
                emission_factor_label = "organic pesticide"
            elif chemical_subtype in ["biological_pesticide", "biological"]:
                # Biological pesticides (Bt, Spinosad) - microbial-based
                product_factor = chemical_factors["biological_pesticide_manufacturing"]
                emission_factor_label = "biological pesticide"
            emission_factor = product_factor.value

            # Calculate manufacturing emissions using selected emission factor
            manufacturing_emissions = active_ingredient_kg * emission_factor

            # Calculate application fuel emissions using correct fuel type
            application_emissions = self._calculate_aggregate_fuel_emissions(fuel_total, fuel_type, fuel_unit)

            total_emissions = manufacturing_emissions + application_emissions
            basis = self._aggregate_basis(
                [product_factor] if active_ingredient_kg else [],
                fuel_total,
                fuel_type,
                omitted_code=None if active_ingredient_kg else "amount_not_recorded",
            )

            breakdown = {
                "is_aggregate": True,
                "event_count": event_count,
                "date_range": f"{date_start} to {date_end}" if date_start and date_end else "Multiple dates",
                "active_ingredient_total_kg": active_ingredient_kg,
                "chemical_subtype": chemical_subtype or "synthetic (default)",
                "manufacturing_emissions_kg_co2e": round(manufacturing_emissions, 3),
                "application_fuel_total": fuel_total,
                "application_fuel_type": fuel_type,
                "application_fuel_unit": fuel_unit,
                "application_emissions_kg_co2e": round(application_emissions, 3),
                "emission_factor_used": f"{emission_factor} kg CO2/kg AI ({emission_factor_label})",
                "confidence_level": 0.90,
                "figure_basis": basis["figure_basis"],
                "estimate_reasons": basis["estimate_reasons"],
            }

            return {
                "co2e": round(total_emissions, 3),
                "calculation_method": "aggregate_pesticide_epa_usda",
                **basis,
                "breakdown": breakdown,
                "limitations": f"Aggregate calculation for {event_count} pesticide applications",
                "recommendations": [
                    {
                        "type": "aggregate_transparency",
                        "message": f"This represents {event_count} pesticide applications logged as one summary",
                        "impact": "Transparency",
                        "source": "Trazo Aggregate Logging",
                    }
                ],
                "confidence_level": 0.90,
            }

        except Exception as e:
            logger.error(f"Aggregate pesticide calculation failed: {e}")
            return {
                "co2e": 0.0,
                "verification_status": "aggregate_calculation_error",
                "error": str(e),
            }

    # ==========================================================================================
    # End of Sprint 5: Aggregate Event Support
    # ==========================================================================================

    def _create_usda_compliance_record(
        self, carbon_entry: CarbonEntry, event, calculation_data: Dict, confidence_score: float
    ) -> None:
        """NEW METHOD: Create USDA compliance record"""
        try:
            state, county = self._get_establishment_location(event)

            # Extract crop type properly from event's history relationship
            crop_type = "unknown"
            if hasattr(event, "history") and event.history:
                if hasattr(event.history, "crop_type") and event.history.crop_type:
                    # First try: get from history.crop_type.name (new model structure)
                    crop_type = event.history.crop_type.name
                elif hasattr(event.history, "product") and event.history.product:
                    # Fallback: get from history.product.name (legacy structure)
                    crop_type = event.history.product.name
                elif "crop_name" in calculation_data:
                    # Fallback: get from calculation_data if available
                    crop_type = calculation_data["crop_name"]

            # Log for debugging
            logger.info(f"🌾 USDA Compliance - Crop type extracted: '{crop_type}' for event {event.id}")

            # Canonicalize to a 2-letter code, or None. Deliberately NOT defaulting
            # to "CA": an unknown state must fall through to national factors, not
            # be silently recorded as a California operation.
            state = normalize_state(state)

            # Extract proper area from event
            area_hectares = 1  # Default fallback
            if hasattr(event, "area") and event.area and event.area != "None":
                area_hectares = self._convert_area_to_hectares(event.area, event, crop_type)
            elif (
                hasattr(event, "history")
                and event.history
                and hasattr(event.history, "parcel")
                and event.history.parcel
            ):
                area_hectares = self._convert_area_to_hectares(event.history.parcel.area, event, crop_type)

            # Validate against USDA standards
            validation_result = self.enhanced_usda.validate_against_usda_standards(
                {
                    "crop_type": crop_type,
                    "state": state,
                    "co2e": calculation_data.get("co2e", 0),
                    "area_hectares": area_hectares,
                    "usda_factors_based": calculation_data.get("usda_factors_based", False),
                    "method": calculation_data.get("method", "standard"),
                }
            )

            # Create compliance record
            USDAComplianceRecord.objects.create(
                carbon_entry=carbon_entry,
                establishment=getattr(event, "history", None)
                and getattr(event.history, "parcel", None)
                and getattr(event.history.parcel, "establishment", None),
                production=getattr(event, "history", None),
                compliance_status="compliant" if validation_result.is_compliant else "non_compliant",
                confidence_score=validation_result.confidence_score,
                validation_method="local_validation",
                validation_details=validation_result.validation_details,
                recommendations=validation_result.recommendations,
                usda_api_used=False,
                crop_type=crop_type,
                # `USDAComplianceRecord.state` is CharField(max_length=2) with no
                # null=True, so an unknown state must be stored as "" and never None:
                # the IntegrityError would be swallowed by the except below but would
                # poison the enclosing atomic block, failing every later query in it.
                state=state or "",
                regional_factors_used=state in self.enhanced_usda.regional_adjustments,
                validated_by=getattr(event, "created_by", None),
            )

            logger.info(f"Created USDA compliance record for carbon entry {carbon_entry.id}")

        except Exception as e:
            logger.error(f"Error creating USDA compliance record: {e}")

    def _create_calculation_audit(
        self, event, carbon_entry: CarbonEntry, calculation_data: Dict, calculation_time_ms: int
    ) -> None:
        """NEW METHOD: Create calculation audit record"""
        try:
            event_type_mapping = {
                "ChemicalEvent": "chemical_event",
                "ProductionEvent": "production_event",
                "EquipmentEvent": "equipment_event",
                "SoilManagementEvent": "soil_management",
                "WeatherEvent": "weather_event",
                "PestManagementEvent": "pest_management",
                "GeneralEvent": "business_event",
            }

            event_type = event_type_mapping.get(event.__class__.__name__, "business_event")
            state, county = self._get_establishment_location(event)

            USDACalculationAudit.objects.create(
                event_type=event_type,
                event_id=event.id,
                carbon_entry=carbon_entry,
                input_data=calculation_data.get("input_data", {}),
                regional_factors_used=calculation_data.get("regional_factors", {}),
                calculation_method=calculation_data.get("method", "standard"),
                usda_factors_applied=calculation_data.get("usda_factors_based", False),
                regional_adjustments_applied=state in self.enhanced_usda.regional_adjustments,
                api_data_used=False,
                calculated_co2e=calculation_data.get("co2e", 0),
                confidence_score=calculation_data.get("confidence_score", 0.5),
                benchmark_comparison=calculation_data.get("usda_benchmark", {}),
                calculation_time_ms=calculation_time_ms,
                processor_version="2.0_enhanced",
                calculated_by=getattr(event, "created_by", None),
            )

        except Exception as e:
            logger.error(f"Error creating calculation audit: {e}")

    def _add_enhanced_usda_metadata(self, result: Dict[str, Any], event, crop_name: str = "default") -> Dict[str, Any]:
        """Add enhanced USDA metadata to calculation results"""
        start_time = time.time()
        country = getattr(settings, "TRAZO_OPERATING_COUNTRY", "US")

        try:
            if country != "US":
                # Non-US: skip NASS and USDA metadata entirely
                result["nass_adjustment"] = {"applied": False, "reason": f"Not applicable for {country}"}
                result["regional_factors"] = {}
                result["usda_factors_based"] = False
                result["verification_status"] = "factors_verified"
                result["confidence_score"] = self._calculate_confidence_score(event, result)
                result["calculation_time_ms"] = int((time.time() - start_time) * 1000)
                return result

            state, county = self._get_establishment_location(event)

            # Get enhanced metadata
            metadata = self.enhanced_usda.get_enhanced_calculation_metadata(crop_name, state)

            # Calculate confidence score
            confidence_score = self._calculate_confidence_score(event, result)
            result["confidence_score"] = confidence_score

            # Add to result
            result.update(
                {
                    "usda_factors_based": True,
                    "verification_status": "factors_verified",
                    "data_source": metadata["data_source"],
                    "methodology": metadata["methodology"],
                    "regional_specificity": metadata["regional_specificity"],
                    "confidence_level": metadata["confidence_level"],
                    "usda_compliance": metadata["usda_compliance"],
                    "regional_optimization": metadata.get("regional_optimization", False),
                    "real_time_data": metadata.get("real_time_data", False),
                    "api_integration": metadata.get("api_enabled", False),
                }
            )

            # Add benchmark comparison if possible
            if "co2e" in result and result["co2e"] > 0:
                # Calculate carbon intensity (simplified)
                # Pass event so area_unit is honored (prevents acres being treated as hectares)
                area_hectares = self._convert_area_to_hectares(getattr(event, "area", "1"), event=event)
                if area_hectares > 0:
                    carbon_intensity = result["co2e"] / area_hectares
                    benchmark = self.enhanced_usda.get_usda_benchmark_comparison(carbon_intensity, crop_name, state)
                    result["usda_benchmark"] = benchmark

            # Store calculation metadata for audit
            result["input_data"] = {
                "event_type": event.__class__.__name__,
                "event_id": event.id,
                "crop_type": crop_name,
                "state": state,
                "county": county,
            }

            # Get regional factors and apply NASS yield-based efficiency adjustment
            regional_factors = self._get_real_time_usda_factors(crop_name, state)
            result["regional_factors"] = regional_factors

            original_co2e = result.get("co2e", 0)
            if regional_factors.get("real_time") and regional_factors.get("benchmark_yield") and original_co2e > 0:
                benchmark_yield = regional_factors["benchmark_yield"]
                efficiency_factor = min(benchmark_yield / 150, 1.2) if benchmark_yield > 0 else 1.0
                result["co2e"] = round(original_co2e / efficiency_factor, 3)
                result["nass_adjustment"] = {
                    "applied": True,
                    "co2e_original": original_co2e,
                    "co2e_adjusted": result["co2e"],
                    "efficiency_factor": round(efficiency_factor, 4),
                    "benchmark_yield": benchmark_yield,
                }
            else:
                result["nass_adjustment"] = {"applied": False, "reason": "No real-time NASS data available"}

            calculation_time = int((time.time() - start_time) * 1000)  # Convert to milliseconds
            result["calculation_time_ms"] = calculation_time

            return result

        except Exception as e:
            logger.error(f"Error adding enhanced USDA metadata: {e}")
            # Fallback to basic metadata
            result.update(
                {
                    "usda_factors_based": True,
                    "verification_status": "factors_verified",
                    "data_source": "USDA Agricultural Research Service",
                    "confidence_level": "medium",
                    "confidence_score": 0.5,
                }
            )
            return result

    @staticmethod
    def _state_chemical_basis(result: Dict[str, Any], status: str, data_sources) -> Dict[str, Any]:
        """Put back what an input figure rests on after `_add_enhanced_usda_metadata` (2026-11-13).

        That step stamps every US result `factors_verified`, `usda_factors_based: True` and a
        blanket "USDA Agricultural Research Service" source. For a chemical figure the status
        follows its basis: an estimate in any part keeps `estimate` and never carries the flag the
        app badges "From recorded inputs"; the source column names the factors actually applied.
        """
        result["verification_status"] = status
        if status == VERIFICATION_STATUS_ESTIMATE:
            result["usda_factors_based"] = False
        result["data_source"] = ("; ".join(data_sources or []) or "No factor applied")[:200]
        # Same step, same blanket: "USDA emission factors with regional adjustments" and a
        # `usda_compliance: True` that nothing reads, on a figure built from EPA, IPCC, academic
        # and Trazo factors.
        result["methodology"] = "Each input priced with the factor named for it in data_sources"
        result.pop("usda_compliance", None)
        return result

    def _get_crop_category(self, crop_name: str) -> str:
        """Determine crop category from crop name for efficiency calculations"""
        crop_lower = crop_name.lower()

        fruit_keywords = ["orange", "apple", "grape", "lemon", "lime", "strawberry", "blueberry", "avocado"]
        vegetable_keywords = ["tomato", "lettuce", "carrot", "broccoli", "spinach", "cucumber", "pepper", "onion"]
        grain_keywords = ["corn", "wheat", "rice", "barley", "oats"]
        herb_keywords = ["basil", "oregano", "thyme", "rosemary", "mint"]
        legume_keywords = ["soybean", "bean", "chickpea", "lentil", "pea"]
        nut_keywords = ["almond", "walnut", "pecan", "hazelnut"]

        for keyword in fruit_keywords:
            if keyword in crop_lower:
                return "fruits"
        for keyword in vegetable_keywords:
            if keyword in crop_lower:
                return "vegetables"
        for keyword in grain_keywords:
            if keyword in crop_lower:
                return "grains"
        for keyword in herb_keywords:
            if keyword in crop_lower:
                return "herbs"
        for keyword in legume_keywords:
            if keyword in crop_lower:
                return "legumes"
        for keyword in nut_keywords:
            if keyword in crop_lower:
                return "nuts"

        return "default"

    def _get_crop_specific_factor(self, crop_name: str) -> float:
        """Get crop-specific emission factor"""
        crop_key = crop_name.lower().replace(" ", "_")
        return self.CROP_SPECIFIC_FACTORS.get(crop_key, self.CROP_SPECIFIC_FACTORS["default"])

    def calculate_chemical_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of chemical application events, each input with its own factor.
        Includes both manufacturing and application emissions.

        Sprint 5: Added support for aggregate events (multiple applications logged as one summary).

        2026-11-13: `verification_status` follows the basis: "factors_verified" (published factors
        on recorded quantities, nothing left out) or "estimate" (any part estimated or left out),
        on single records and summaries alike.
        """
        try:
            from .verified_emission_factors import VerifiedEmissionFactors

            # Sprint 5: Check for aggregate events first
            # Aggregate events have pre-calculated totals in extra_data
            if self._is_aggregate_event(event):
                extra_data = self._get_aggregate_extra_data(event)
                chemical_type = getattr(event, "type", None) or extra_data.get("chemical_type", "FE")

                # Route to appropriate aggregate calculator based on chemical type
                if chemical_type == "FE":  # Fertilizer
                    logger.info(f"Processing aggregate fertilizer event {event.id}")
                    return self._calculate_aggregate_fertilizer_impact(event, extra_data)
                elif chemical_type == "FU":  # Fungicide
                    logger.info(f"Processing aggregate fungicide event {event.id}")
                    return self._calculate_aggregate_fungicide_impact(event, extra_data)
                elif chemical_type == "PE":  # Pesticide
                    logger.info(f"Processing aggregate pesticide event {event.id}")
                    return self._calculate_aggregate_pesticide_impact(event, extra_data)
                elif chemical_type == "HE":  # Herbicide
                    logger.info(f"Processing aggregate herbicide event {event.id}")
                    return self._calculate_aggregate_herbicide_impact(event, extra_data)
                else:
                    # A6: do NOT silently fall back to the fertilizer calculator. It reads NPK
                    # totals, so for any non-fertilizer chemical it finds zeros and returns a
                    # confident-looking near-zero figure. Returning 0 with an explicit
                    # limitation is honest; quietly applying the wrong model is not.
                    logger.error(
                        "Aggregate chemical type %r has no handler; refusing to guess (event %s)",
                        chemical_type,
                        event.id,
                    )
                    return {
                        "co2e": 0.0,
                        "calculation_method": "aggregate_unsupported_chemical_type",
                        "verification_status": "insufficient_data",
                        "breakdown": {"is_aggregate": True, "chemical_type": chemical_type},
                        "limitations": (
                            f"No aggregate emission model for chemical type {chemical_type!r}; "
                            "log the applications individually for a calculated figure."
                        ),
                    }

            # Extract chemical data from event
            chemical_data = self._extract_chemical_event_data(event)

            # An amount recorded as a COUNT (pheromone dispensers) has no product mass or volume,
            # so there is nothing to multiply an emission factor by. Say so on the result rather
            # than return the "invalid inputs" zero, or worse, read the count as litres.
            if chemical_data.get("amount_is_count"):
                return count_amount_result(
                    chemical_data.get("amount_count"),
                    chemical_data.get("amount_unit"),
                    chemical_data.get("chemical_type"),
                )

            # Get chemical parameters for EPA calculation
            chemical_type = chemical_data.get("chemical_type", "FE")
            volume_liters = chemical_data.get("volume_liters", 0.0)
            area_hectares = chemical_data.get("area_hectares", 0.0)
            npk_content = chemical_data.get("npk_content", {"N": 0, "P": 0, "K": 0})
            application_method = chemical_data.get("application_method", "broadcast")
            product_name = chemical_data.get("product_name", "")
            chemical_subtype = chemical_data.get("chemical_subtype", "")

            # Extract application fuel parameters (ADDED 2025-12-11)
            application_fuel_type = chemical_data.get("application_fuel_type", "")
            application_fuel_consumed = chemical_data.get("application_fuel_consumed", None)
            application_fuel_unit = chemical_data.get("application_fuel_unit", "L")

            # Extract concentration for pesticides/herbicides/fungicides (ADDED 2025-12-24)
            # FIX: Without concentration, the calculation assumes 100% active ingredient
            # which vastly overestimates manufacturing emissions (e.g., 109 kg vs 10.9 kg)
            concentration = chemical_data.get("concentration")

            # Use EPA/USDA verified emission factors for chemical calculations
            # ENHANCED 2025-01-21: Pass chemical_subtype for explicit emission factor selection.
            # Takes precedence over keyword detection from product_name.
            # Supports: organic_herbicide, organic_fungicide, copper_fungicide, sulfur_fungicide,
            #           biological_fungicide, organic_pesticide, biological_pesticide,
            #           organic_fertilizer, slow_release_fertilizer
            # ENHANCED 2025-12-11: Pass application fuel parameters for accurate fuel emission tracking.
            # Enables tracking of actual fuel consumed by application equipment (electric, diesel, etc.)
            # ENHANCED 2025-12-24: Pass concentration for accurate active ingredient calculation.
            # Ensures preview and dashboard show consistent manufacturing emissions.
            # Item #14: Pass fertigation flag to skip double-counting application fuel
            is_fertigation = bool(getattr(event, "is_fertigation", False))
            # Auto-detect fertigation if application method indicates it
            if not is_fertigation and chemical_type == "FE":
                app_method = getattr(event, "way_of_application", "") or ""
                if "fertigation" in app_method.lower():
                    is_fertigation = True

            chemical_mass_kg = chemical_data.get("chemical_mass_kg")

            # Tank mix (OV-RK-C04): one pass, several product records. Only the record of the
            # tank's lowest-numbered line on this target carries the pass's application emissions;
            # the others keep their own manufacturing (history/services/tank_mix.py). A preview's
            # unsaved stand-in event has no tank and always carries its own pass.
            from history.services.tank_mix import pass_counted_on_line

            application_pass_counted_on_line = pass_counted_on_line(event)

            calculation_result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
                chemical_type=chemical_type,
                volume_liters=volume_liters,
                area_hectares=area_hectares,
                npk_content=npk_content,
                application_method=application_method,
                product_name=product_name,
                chemical_subtype=chemical_subtype,
                application_fuel_type=application_fuel_type,
                application_fuel_consumed=application_fuel_consumed,
                application_fuel_unit=application_fuel_unit,
                concentration=concentration,
                is_fertigation=is_fertigation,
                chemical_mass_kg=chemical_mass_kg,
                application_pass_counted_on_line=application_pass_counted_on_line,
            )

            base_emissions = calculation_result["co2e_kg"]
            breakdown = calculation_result["breakdown"]
            data_sources = calculation_result["data_sources"]
            limitations = calculation_result.get("limitations", "")
            calculation_method = calculation_result["calculation_method"]

            confidence_level = breakdown.get("confidence_level", 0.90)

            # Generate EPA-based recommendations
            recommendations = self._generate_epa_chemical_recommendations(event, base_emissions, breakdown)

            # The status follows the basis the calculation used (2026-11-13). It was
            # "epa_usda_verified" for every chemical figure, and the metadata step below then
            # stamped "factors_verified" and the EPA/USDA flag on it, so an application pass
            # estimated from the area (or a figure with manufacturing left out) was stored and
            # badged as resting on published factors.
            basis = {
                "figure_basis": calculation_result.get("figure_basis"),
                "estimate_reasons": calculation_result.get("estimate_reasons") or [],
            }
            status = verification_status_for(basis, "factors_verified")

            result = {
                "co2e": round(base_emissions, 3),
                "calculation_method": calculation_method,
                "verification_status": status,
                "data_sources": data_sources,
                "factor_provenance": calculation_result.get("factor_provenance"),
                "figure_basis": basis["figure_basis"],
                "estimate_reasons": basis["estimate_reasons"],
                "breakdown": breakdown,
                "limitations": limitations,
                "recommendations": recommendations,
                "confidence_level": confidence_level,
            }

            enriched = self._add_enhanced_usda_metadata(result, event, chemical_data.get("crop_name", "unknown"))
            return self._state_chemical_basis(enriched, status, data_sources)

        except Exception as e:
            # Return minimal safe calculation on error
            logger.error(f"Chemical event calculation failed: {e}")
            logger.error(
                f"Event data: type={getattr(event, 'type', 'unknown')}, volume={getattr(event, 'volume', 'unknown')}, area={getattr(event, 'area', 'unknown')}"
            )
            return {
                "co2e": 0.0,
                "verification_status": "calculation_error",
                "error": str(e),
                "calculation_method": "epa_fallback",
            }

    def _extract_chemical_event_data(self, event) -> Dict[str, Any]:
        """Extract chemical event data for EPA/USDA calculations"""
        try:
            # Get crop information
            crop_name = "unknown"
            # `hasattr(history, "product")` is ALWAYS True for a model FK — the attribute exists,
            # it is simply None when unset. Checking it therefore guarded nothing, and
            # `event.history.product.name` raised AttributeError on every production without a
            # crop, which the caller swallowed into "zero defaults": silent zero carbon.
            if event.history is not None and event.history.product is not None:
                crop_name = event.history.product.name

            # Extract chemical type - handle None values properly
            chemical_type = getattr(event, "type", None)
            if chemical_type is None or chemical_type == "":
                chemical_type = "FE"  # Default to fertilizer
            elif chemical_type == "":
                chemical_type = "FE"  # Default to fertilizer for empty strings

            # Extract volume and determine if mass or volume unit
            # Priority: (1) volume_numeric + volume_unit model fields
            #           (2) legacy string field volume="3320" + extra_data.volume_unit
            #           (3) separate volume_applied + volume_unit fields from frontend
            # When none of them holds an amount, the record holds none and nothing is assumed in
            # its place: the calculator then omits manufacturing and says why. Until 2026-11-12 a
            # blank amount read as 50 units, so a spray whose source record gives no amount was
            # priced on 50 units nobody recorded (tank-mix review).
            from carbon.utils.unit_converter import UnitConverter

            volume_numeric = getattr(event, "volume_numeric", None)
            chemical_mass_kg = None
            volume_liters = 0.0

            if volume_numeric is not None:
                raw_volume_unit = getattr(event, "volume_unit", "gal") or "gal"
                volume_value = float(volume_numeric)
            else:
                volume_str_raw = getattr(event, "volume", None)
                if volume_str_raw:
                    try:
                        volume_value = float(str(volume_str_raw).strip())
                    except (ValueError, TypeError):
                        # Legacy format with embedded unit like "3320 Kilograms"
                        volume_liters = self._convert_volume_to_liters(str(volume_str_raw), event, crop_name)
                        volume_value = None
                        raw_volume_unit = None
                    else:
                        # Numeric-only volume: check extra_data for unit
                        extra = getattr(event, "extra_data", None) or {}
                        raw_volume_unit = extra.get("volume_unit", "L")
                else:
                    volume_applied = getattr(event, "volume_applied", None)
                    raw_volume_unit = getattr(event, "volume_unit", "L") or "L"
                    try:
                        volume_value = float(volume_applied)
                    except (ValueError, TypeError):
                        volume_value = None

            # Route mass vs volume units through UnitConverter
            amount_is_count = False
            if volume_value is not None and raw_volume_unit is not None:
                unit_normalized = UnitConverter.normalize_unit_name(raw_volume_unit)
                if UnitConverter.is_count_unit(raw_volume_unit):
                    # A count of dispensers is not a mass or a volume, and no factor turns one
                    # into the other. Never let it reach the "assume liters" branch below.
                    amount_is_count = True
                    chemical_mass_kg = None
                    volume_liters = 0.0
                elif UnitConverter.is_mass_unit(raw_volume_unit):
                    try:
                        chemical_mass_kg, _ = UnitConverter.convert_mass(
                            volume_value, unit_normalized, to_unit="kilograms"
                        )
                    except Exception:
                        chemical_mass_kg = volume_value  # Fallback: assume kg
                    volume_liters = 0.0
                elif UnitConverter.is_volume_unit(raw_volume_unit):
                    try:
                        volume_liters, _ = UnitConverter.convert_volume(volume_value, unit_normalized, to_unit="liters")
                    except Exception:
                        volume_liters = volume_value  # Fallback: assume liters
                else:
                    volume_liters = volume_value  # Unknown unit: assume liters

            # The COLUMN decides, whichever branch parsed the amount. A legacy free-text volume
            # ("approx 1200") skips the routing above with no unit at all and falls to a parser
            # that assumes litres, so a dispenser count was still read as 1200 L on that path
            # (review on back#192).
            column_unit = getattr(event, "volume_unit", None)
            if UnitConverter.is_count_unit(column_unit):
                amount_is_count = True
                chemical_mass_kg = None
                volume_liters = 0.0
                if volume_value is None:
                    volume_value = getattr(event, "volume", None)
                raw_volume_unit = column_unit

            # Extract area (convert to hectares)
            # Priority: (1) area_numeric + area_unit model fields (Item #8 clean numeric fields)
            #           (2) legacy string field area="16.2 Hectares"
            #           (3) separate area_treated + area_unit fields from frontend
            area_numeric = getattr(event, "area_numeric", None)
            if area_numeric is not None:
                # Item #8: Use clean numeric field
                raw_area_unit = getattr(event, "area_unit", "acres") or "acres"
                area_unit_map = {
                    "ha": "Hectares",
                    "acres": "Acres",
                    "m2": "Square Meters",
                }
                normalized_area_unit = area_unit_map.get(raw_area_unit, raw_area_unit)
                area_str = f"{area_numeric} {normalized_area_unit}"
            else:
                area_str = getattr(event, "area", None)
                if not area_str:
                    # New frontend format: separate area_treated and area_unit fields
                    area_treated = getattr(event, "area_treated", None)
                    if area_treated not in (None, ""):
                        area_unit = getattr(event, "area_unit", "ha") or "ha"

                        # Map common unit variations
                        area_unit_map = {"ha": "Hectares", "hectares": "Hectares", "acres": "Acres", "ac": "Acres"}

                        normalized_area_unit = area_unit_map.get(area_unit.lower(), area_unit)
                        area_str = f"{area_treated} {normalized_area_unit}"
                else:
                    # Plain numeric area (e.g. "25") - append area_unit from model
                    try:
                        float(str(area_str).strip())
                        model_area_unit = getattr(event, "area_unit", None)
                        if model_area_unit:
                            area_unit_map = {
                                "ha": "Hectares",
                                "hectares": "Hectares",
                                "acres": "Acres",
                                "ac": "Acres",
                                "m2": "m2",
                            }
                            normalized = area_unit_map.get(model_area_unit.lower(), model_area_unit)
                            area_str = f"{area_str} {normalized}"
                    except (ValueError, TypeError):
                        pass  # area_str already has unit suffix (e.g. "16.2 Hectares")

            # No area on the record is no area. The shared converter answers a blank or "unknown"
            # with a per-crop default (1 ha and up), and this path read a missing area_treated as
            # "1.0": a per-hectare pass estimate was then charged on land the record never names.
            if area_str is None or not any(ch.isdigit() for ch in str(area_str)):
                area_hectares = 0.0
            else:
                area_hectares = self._convert_area_to_hectares(area_str, event, crop_name)

            # Extract NPK content
            npk_content = self._get_structured_npk_content(event, crop_name)

            # Extract application method
            application_method = self._get_structured_application_method(event, crop_name)

            # Extract product/commercial name for specific chemical type detection
            # (e.g., organic herbicides, copper fungicides)
            product_name = getattr(event, "commercial_name", "") or ""

            # Extract explicit chemical_subtype for accurate emission factor selection
            # This takes precedence over keyword detection from product_name
            # Values: organic_herbicide, organic_fungicide, copper_fungicide, sulfur_fungicide,
            #         biological_fungicide, organic_pesticide, biological_pesticide,
            #         organic_fertilizer, slow_release_fertilizer
            chemical_subtype = getattr(event, "chemical_subtype", "") or ""

            # Extract application fuel fields (ADDED 2025-12-11)
            # Enables tracking of actual fuel consumed by application equipment
            # Supports electric equipment with kWh units and alternative fuels
            application_fuel_type = getattr(event, "application_fuel_type", "") or ""
            application_fuel_consumed = getattr(event, "application_fuel_consumed", None)
            application_fuel_unit = getattr(event, "application_fuel_unit", "L") or "L"

            # FIX (2025-12-24): Extract concentration for pesticides/herbicides/fungicides
            # Without this, the calculation assumes 100% active ingredient which vastly overestimates emissions
            # Concentration is stored as a string percentage (e.g., "2.5" for 2.5%)
            concentration_raw = getattr(event, "concentration", None)
            concentration = None
            if concentration_raw and chemical_type != "FE":  # Only for non-fertilizers
                try:
                    # Handle both "2.5" and "2.5%" formats
                    conc_str = str(concentration_raw).replace("%", "").strip()
                    if conc_str and "-" not in conc_str:  # Skip NPK format like "10-10-10"
                        concentration = float(conc_str)
                except (ValueError, TypeError):
                    concentration = None

            # Inform when concentration is missing for non-fertilizer chemicals.
            # F03-consistent (2026-06): the calculator now OMITS active-ingredient
            # manufacturing emissions when concentration is absent (no fabricated %AI
            # default) — application-fuel emissions still count. Encourage data entry.
            if concentration is None and chemical_type in ["PE", "FU", "HE"]:
                logger.info(
                    "Chemical event %s: no concentration for %s — active-ingredient "
                    "manufacturing emissions omitted (no phantom %%AI default). Enter "
                    "concentration for an accurate manufacturing estimate.",
                    getattr(event, "id", "unknown"),
                    chemical_type,
                )

            return {
                "chemical_type": chemical_type,
                "crop_name": crop_name,
                "volume_liters": volume_liters,
                "chemical_mass_kg": chemical_mass_kg,
                "amount_is_count": amount_is_count,
                "amount_count": volume_value if amount_is_count else None,
                "amount_unit": raw_volume_unit if amount_is_count else None,
                "area_hectares": area_hectares,
                "npk_content": npk_content,
                "application_method": application_method,
                "product_name": product_name,
                "chemical_subtype": chemical_subtype,
                "application_fuel_type": application_fuel_type,
                "application_fuel_consumed": application_fuel_consumed,
                "application_fuel_unit": application_fuel_unit,
                "concentration": concentration,  # FIX: Add concentration for accurate AI calculation
            }

        except Exception as e:
            logger.warning(f"Error extracting chemical data, using zero defaults: {e}")
            return {
                "chemical_type": "FE",
                "crop_name": "unknown",
                "volume_liters": 0.0,
                "area_hectares": 0.0,
                "npk_content": {"N": 0, "P": 0, "K": 0},
                "application_method": "broadcast",
                "product_name": "",
                "chemical_subtype": "",
            }

    def _generate_epa_chemical_recommendations(self, event, emissions: float, breakdown: dict) -> list:
        """Generate recommendations for chemical events.

        NOTE: the items carry no "source". They named agency "guidelines" that are not citable
        documents, and the wizard printed them as the source of the advice (2026-11-05). The
        factor sources are named per input by the calculation itself.
        """
        recommendations = []

        try:
            manufacturing_emissions = breakdown.get("manufacturing_emissions_kg_co2e", 0.0)
            application_emissions = breakdown.get("application_emissions_kg_co2e", 0.0)

            # High manufacturing emissions recommendations
            if manufacturing_emissions > application_emissions * 2:
                recommendations.append(
                    {
                        "type": "input_optimization",
                        "message": "Consider slow-release fertilizers to reduce total application frequency",
                        "impact": "High",
                    }
                )

            # High total emissions recommendations
            if emissions > 50:
                recommendations.append(
                    {
                        "type": "precision_agriculture",
                        "message": "Use soil testing to apply only needed nutrients",
                        "impact": "High",
                    }
                )

            # Application efficiency recommendations
            if breakdown.get("application_method", "").lower() == "broadcast":
                recommendations.append(
                    {
                        "type": "application_efficiency",
                        "message": "Consider precision injection to reduce fertilizer waste",
                        "impact": "Medium",
                    }
                )

            # EPA verification transparency
            recommendations.append(
                {
                    "type": "data_transparency",
                    "message": "Factor source named per input; see the carbon methodology. An estimate, not a verified figure.",
                    "impact": "Transparency",
                }
            )

            return recommendations

        except Exception as e:
            logger.warning(f"Error generating EPA chemical recommendations: {e}")
            return []

    def calculate_production_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate production event impact using EPA/USDA verified emission factors.
        ENHANCED: Uses only credible, government-sourced data for transparency.
        """
        try:
            from .verified_emission_factors import VerifiedEmissionFactors

            # Debug logging
            logger.info(
                f"Production calculation: type={getattr(event, 'type', 'unknown')}, fuel_consumed={getattr(event, 'fuel_consumed', 'unknown')}, area_covered={getattr(event, 'area_covered', 'unknown')}"
            )

            # Extract production data from event
            production_data = self._extract_production_event_data(event)
            logger.info(f"Extracted production data: {production_data}")

            # Determine production type for EPA/USDA calculation
            production_type = production_data.get("production_type", "")
            area_covered = production_data.get("area_covered", 0.0)
            fuel_consumed = production_data.get("fuel_consumed")
            equipment_hours = production_data.get("equipment_hours")
            method = production_data.get("method")  # Farmer-documented method (enables manual-operation routing)

            if event.type == "IR":  # Irrigation
                # Use EPA electricity factors for irrigation pumps
                water_volume_gallons = None

                # Sprint 4: Check for aggregate irrigation water_volume_total first
                # This enables accurate carbon calculation for irrigation summaries
                # (e.g., "12 irrigations in May totaling 50,000 gallons")
                # Check both model attribute and extra_data (aggregate events store in extra_data)
                extra_data = getattr(event, "extra_data", None) or {}
                raw_water_total = getattr(event, "water_volume_total", None) or extra_data.get("water_volume_total")
                if raw_water_total:
                    water_volume_total = float(raw_water_total)
                    water_unit = getattr(event, "water_volume_unit", None) or extra_data.get(
                        "water_volume_unit", "gallons"
                    )

                    # Convert to gallons based on unit
                    if water_unit == "gallons":
                        water_volume_gallons = water_volume_total
                    elif water_unit == "liters":
                        water_volume_gallons = water_volume_total * 0.264172  # L to gal
                    elif water_unit == "acre_feet":
                        water_volume_gallons = water_volume_total * 325851  # acre-ft to gal
                    elif water_unit == "cubic_meters":
                        water_volume_gallons = water_volume_total * 264.172  # m³ to gal
                    else:
                        water_volume_gallons = water_volume_total  # Assume gallons

                    logger.info(
                        f"Using aggregate water_volume_total: {water_volume_total} {water_unit} "
                        f"= {water_volume_gallons:.0f} gallons"
                    )

                # Fall back to production_data or estimation
                if not water_volume_gallons:
                    water_volume_gallons = production_data.get("water_volume_gallons")

                if not water_volume_gallons:
                    # ENHANCED: USDA-sourced irrigation water estimates
                    # USDA NASS 2023: Average 1.5 acre-feet/acre/season = ~489,000 gal/acre/season
                    # Single irrigation event: ~30,000-50,000 gallons/acre typical
                    # Sources: ERS.USDA.gov, NASS Irrigation & Water Management Survey 2023
                    water_volume_gallons = self._estimate_irrigation_water_volume(event, area_covered)

                # Extract water_source for pump factor selection
                water_source = getattr(event, "water_source", None) or extra_data.get("water_source")

                # Item #13: pump_depth_ft overrides water_source-based pump factor.
                # Standard pump curve: kWh/1000gal = depth_ft * 0.0175  (USDA NRCS pump efficiency)
                # Check model field first, then extra_data (well_depth_ft or pump_depth_ft)
                pump_depth_ft = (
                    getattr(event, "pump_depth_ft", None)
                    or extra_data.get("pump_depth_ft")
                    or extra_data.get("well_depth_ft")
                )

                # Item #13: electricity_source overrides the default 0.39 kg CO2/kWh grid factor.
                electricity_source = getattr(event, "electricity_source", None) or extra_data.get("electricity_source")

                # F06 fix (2026-06): route the SAVED IR path through the SAME entry
                # point the live preview uses (calculate_production_event_emissions),
                # so diesel-pump fuel and AUXILIARY diesel (service vehicle/standby
                # pump) are included identically. The previous call to the bare
                # calculate_drought_irrigation_emissions had no fuel parameter and
                # silently dropped auxiliary diesel the preview showed (e.g. 5 gal =
                # 51 kg). water_volume_gallons is already resolved above, so the
                # function uses it directly; fuel_type/electricity_source select
                # diesel-pump vs auxiliary-diesel vs electric exactly as in preview.
                fuel_type = getattr(event, "fuel_type", None) or extra_data.get("fuel_type")
                energy_source = getattr(event, "energy_source", None) or extra_data.get("energy_source") or "grid"
                calculation_result = VerifiedEmissionFactors.calculate_production_event_emissions(
                    production_type="IR",
                    area_covered=area_covered,
                    fuel_consumed=fuel_consumed,
                    equipment_hours=equipment_hours,
                    fuel_type=fuel_type,
                    energy_source=energy_source,
                    electricity_source=electricity_source,
                    water_volume_gallons=water_volume_gallons,
                    water_source=water_source,
                    pump_depth_ft=float(pump_depth_ft) if pump_depth_ft is not None else None,
                    # A drip line and a sprinkler do different amounts of work per gallon;
                    # the method sets the pressure component of total dynamic head.
                    irrigation_method=(
                        getattr(event, "irrigation_method", None) or extra_data.get("irrigation_method")
                    ),
                    # §E-6: a measured pumping plant overrides the 70% / method-derived
                    # defaults. Pump tests are annual and parcel-level, so they live on the
                    # Parcel rather than being re-entered on every irrigation event.
                    **self._parcel_pump_attributes(event),
                )

                base_emissions = calculation_result["co2e_kg"]
                data_sources = calculation_result["data_sources"]
                calculation_method = calculation_result["calculation_method"]
                breakdown = calculation_result["breakdown"]
                limitations = calculation_result.get("limitations", "")

            elif event.type == "PO":  # Pollination - biological service, zero direct emissions
                base_emissions = 0.0
                data_sources = ["Trazo Methodology - Biological pollination services produce zero direct emissions"]
                calculation_method = "zero_emission_biological_service"
                breakdown = {
                    "production_type": "PO",
                    "carbon_impact": "zero",
                    "carbon_notes": (
                        "Pollination is a biological service performed by bees or other pollinators. "
                        "No direct fuel combustion or chemical inputs are involved."
                    ),
                    "confidence_level": 1.0,
                }
                limitations = "Excludes indirect transportation emissions for hive delivery/pickup"

            elif event.type == "PH":  # Post-Harvest Processing
                result = self._calculate_postharvest_emissions(event, production_data)
                return self._add_enhanced_usda_metadata(result, event, production_data.get("crop_name", "unknown"))

            elif event.type == "CM":  # Canopy Management - same fuel-based calc as other production events
                fuel_type = getattr(event, "fuel_type", "diesel")
                energy_source = getattr(event, "energy_source", "grid")
                # Pass raw "CM" code so manual-method short-circuit works for hand canopy work
                # (leaf pulling, hedging, shoot positioning often done by hand with shears)
                calculation_result = VerifiedEmissionFactors.calculate_production_event_emissions(
                    production_type="CM",
                    area_covered=area_covered,
                    fuel_consumed=fuel_consumed,
                    equipment_hours=equipment_hours,
                    fuel_type=fuel_type,
                    energy_source=energy_source,
                    method=method,
                )
                base_emissions = calculation_result["co2e_kg"]
                data_sources = calculation_result["data_sources"]
                calculation_method = calculation_result["calculation_method"]
                breakdown = calculation_result["breakdown"]
                limitations = calculation_result.get("limitations", "")

            elif event.type in [
                "HA",
                "PL",
                "PR",
                "EM",
                "TH",
                "TR",
                "CU",
                # Batch 3 (2026-06): frost protection (wind machines/heaters) and
                # orchard-floor mowing are fuel-driven Production ops — route through
                # the same fuel pipeline so reported diesel/propane is counted.
                "FP",
                "MO",
            ]:  # Harvesting, Planting, Pruning, Equipment Maint., Thinning, Transplanting, Cultivation, Frost, Mowing
                # Use EPA/USDA production emission factors.
                # Pass the raw 2-letter code so PRODUCTION_TYPE_MAPPING in VerifiedEmissionFactors
                # routes to the correct per-type calculator (e.g. TH -> _calculate_thinning_emissions
                # with 0.75 gal/ha, not the 2.5 gal/ha general-production fallback).
                # Sprint 5: Check for aggregate harvest data
                if event.type == "HA":
                    extra_data = getattr(event, "extra_data", None) or {}
                    is_summary = extra_data.get("is_summary", False)
                    if is_summary:
                        # For harvest summaries, carbon comes from total fuel consumed
                        # which is already in the main fuel_consumed field.
                        # The yield_total is for transparency, not carbon calculation.
                        logger.info(
                            f"Harvest summary event: {extra_data.get('event_count', 'N/A')} harvests, "
                            f"yield: {extra_data.get('yield_total', 'N/A')} {extra_data.get('yield_total_unit', '')}"
                        )

                # Extract fuel_type and energy_source from event object for electric equipment support
                fuel_type = getattr(event, "fuel_type", "diesel")  # Default to diesel if not specified
                energy_source = getattr(event, "energy_source", "grid")  # Default to grid if not specified

                calculation_result = VerifiedEmissionFactors.calculate_production_event_emissions(
                    production_type=event.type,
                    area_covered=area_covered,
                    fuel_consumed=fuel_consumed,
                    equipment_hours=equipment_hours,
                    fuel_type=fuel_type,
                    energy_source=energy_source,
                    method=method,
                )

                base_emissions = calculation_result["co2e_kg"]
                data_sources = calculation_result["data_sources"]
                calculation_method = calculation_result["calculation_method"]
                breakdown = calculation_result["breakdown"]
                limitations = calculation_result.get("limitations", "")

            else:
                # Any subtype without a branch above.
                #
                # ⛔ This used to pass the LITERAL string "general production", which threw the
                # farmer's actual subtype away before PRODUCTION_TYPE_MAPPING ever saw it. That
                # map is the single place that knows which operations are area-driven, so
                # overwriting the code here made every entry added to it unreachable from the
                # SAVED path — the map only ever got "GENERAL PRODUCTION", an unknown code, and
                # fell through to the 2.5 gal diesel/hectare field estimate every time.
                #
                # It cost exactly the three subtypes the 2026-08-20 fix was written for. TP, BU
                # and SS were mapped to `_calculate_reported_fuel_only_emissions` in that pass,
                # and all three kept computing the area estimate on save while the live preview
                # (which passes the real code) showed 0. A seed search — three phone calls and a
                # catalogue — was charged 169 kg CO2e on a 16.4-acre block, because the fallback
                # reads the PARCEL's acreage when the event has no `area_covered` of its own.
                # PO escaped only because it also has an explicit `elif` above.
                #
                # Passing `event.type` restores the map as the authority. An unrecognised code
                # still lands on general production — via the map's own documented fallback,
                # which logs a warning naming the code, instead of silently laundering it into
                # a string that is itself unrecognised.
                fuel_type = getattr(event, "fuel_type", "diesel")  # Default to diesel if not specified
                energy_source = getattr(event, "energy_source", "grid")  # Default to grid if not specified

                calculation_result = VerifiedEmissionFactors.calculate_production_event_emissions(
                    production_type=event.type or "general production",
                    area_covered=area_covered,
                    fuel_consumed=fuel_consumed,
                    equipment_hours=equipment_hours,
                    fuel_type=fuel_type,
                    energy_source=energy_source,
                    method=method,
                )

                base_emissions = calculation_result["co2e_kg"]
                data_sources = calculation_result["data_sources"]
                calculation_method = calculation_result["calculation_method"]
                breakdown = calculation_result["breakdown"]
                limitations = calculation_result.get("limitations", "")

            # NOTE: Crop-specific modifiers REMOVED (2025-12-21)
            # Research showed arbitrary modifiers (1.3x avocado, 0.8x lettuce) lacked scientific basis.
            # Actual crop differences are already captured through measured fuel/fertilizer/energy usage.
            # See: PMC 2024 Avocado LCA, California Almond/Walnut LCA studies.
            # Trazo's "Direct Operational Emissions" philosophy: measure actual inputs, don't apply arbitrary multipliers.

            # A4 (2026-07): add farm-to-first-receiver hauling. `transportation_distance` was
            # collected, validated and displayed but fed into no formula, so a recorded 40-mile
            # run to the huller contributed nothing. Added on top of the operation's own
            # emissions rather than replacing them — the haul is extra work, not a substitute.
            # Read from the event itself: _extract_production_event_data nests the structured
            # fields under "structured_data" rather than promoting them, so a top-level lookup
            # here silently found nothing.
            structured = production_data.get("structured_data") or {}
            transport_distance = (
                getattr(event, "transportation_distance", None) or structured.get("transportation_distance") or 0.0
            )
            if transport_distance and float(transport_distance) > 0:
                transport_result = VerifiedEmissionFactors.calculate_transport_emissions(
                    distance=transport_distance,
                    distance_unit=(
                        getattr(event, "transportation_unit", None) or structured.get("transportation_unit") or "miles"
                    ),
                )
                base_emissions += transport_result["co2e_kg"]
                breakdown.update(transport_result["breakdown"])
                data_sources = list(data_sources) + transport_result.get("data_sources", [])
                if calculation_method == "not_estimated":
                    # The operation itself had nothing to count, but the recorded haul does.
                    calculation_method = "transport_distance_only"
                    breakdown["calculation_basis"] = "transport_distance_only"

            # Generate EPA-based recommendations
            recommendations = self._generate_epa_production_recommendations(event, base_emissions, calculation_method)

            result = {
                "co2e": round(base_emissions, 3),
                "calculation_method": calculation_method,
                "verification_status": (
                    "epa_factors_based" if calculation_method == "verified_usda_factors" else "standard"
                ),
                "data_sources": data_sources,
                "breakdown": breakdown,
                "limitations": limitations,
                "recommendations": recommendations,
                "confidence_level": breakdown.get("confidence_level", 0.80),
            }

            enriched = self._add_enhanced_usda_metadata(result, event, production_data.get("crop_name", "unknown"))

            # ⚖️ Do not claim EPA/USDA sourcing for a figure no factor produced.
            #
            # `_add_enhanced_usda_metadata` sets `usda_factors_based: True` for every US event
            # unconditionally, and the detail modal renders that as an "EPA/USDA-sourced"
            # badge beside the number. That is right whenever a factor WAS applied — including
            # a TP haul whose reported diesel is multiplied by the EPA factor.
            #
            # It is NOT right for the reported-fuel-only path when nothing was reported: that
            # 0 comes from the absence of an input, not from any agency's factor, and
            # `_calculate_reported_fuel_only_emissions` says so itself by returning
            # "Trazo Methodology - non-area-driven activity, reported fuel only" as its only
            # data source. Badging that 0 as EPA/USDA-sourced lends agency provenance to an
            # absence — the failure `carbon-panel-provenance` exists to prevent, where the
            # citable half of a calculation vouches for the uncited half.
            #
            # Narrow on purpose: only when the route was reported_fuel_only AND nothing was
            # counted. Every other path keeps the badge it earns.
            if calculation_method == "reported_fuel_only" and not base_emissions:
                enriched["usda_factors_based"] = False
                enriched["verification_status"] = "no_factor_applied"

            # Run 8 (R8-04): nothing recorded to count from. Marked so the signal stores no entry
            # and the event carries an explicit not_estimated status instead of a number.
            if calculation_method == "not_estimated":
                enriched["not_estimated"] = True
                enriched["usda_factors_based"] = False
                enriched["verification_status"] = "not_estimated"
            # A per-hectare figure is an estimate from the recorded area, never a reported-fuel
            # number: no EPA/USDA badge.
            elif breakdown.get("calculation_basis") == "usda_standard_per_hectare":
                enriched["usda_factors_based"] = False
                enriched["verification_status"] = "area_estimate"

            return enriched

        except Exception as e:
            logger.error(f"Production event calculation error: {e}")
            return {
                "co2e": 0.0,
                "calculation_method": "calculation_error",
                "verification_status": "error",
                "error": str(e),
                "data_sources": [],
                "breakdown": {},
                "limitations": "Calculation failed, using fallback values",
                "recommendations": [],
            }

    def _calculate_postharvest_emissions(self, event, production_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate carbon emissions for Post-Harvest Processing events (PH subtype).

        Post-harvest operations (hulling, shelling, washing, sorting, packing) generate
        emissions primarily from:
        - Equipment fuel combustion (hullers, shellers, washers, sorters, packers)
        - Electricity for processing facility operations

        Uses the same EPA fuel factor pattern as other production events.
        """
        try:
            from .verified_emission_factors import VerifiedEmissionFactors

            extra_data = getattr(event, "extra_data", None) or {}
            area_covered = production_data.get("area_covered", 0.0)
            fuel_consumed = production_data.get("fuel_consumed")
            equipment_hours = production_data.get("equipment_hours")
            fuel_type = getattr(event, "fuel_type", "diesel")
            energy_source = getattr(event, "energy_source", "grid")

            # A7 fix (2026-07): this passed production_type="general production", which routed
            # PH to the generic per-hectare FIELD estimate (~2.5 gal diesel/ha). Post-harvest
            # work happens in a huller or drying shed — ProductionEvent.clean() even allows
            # area_covered = 0 for PH for that reason — so any area on the event describes the
            # block the crop came FROM, and multiplying it by a field-fuel rate invented diesel
            # nobody burned. Passing "PH" routes to _calculate_postharvest_emissions, which
            # prefers the measured facility energy the form already collects.
            calculation_result = VerifiedEmissionFactors.calculate_production_event_emissions(
                production_type="PH",
                area_covered=area_covered,
                fuel_consumed=fuel_consumed,
                equipment_hours=equipment_hours,
                fuel_type=fuel_type,
                # DOUBLE-CONVERSION FIX (2026-07-31): `production_data["fuel_consumed"]`
                # comes from _extract_production_event_data, which ALREADY converted the
                # farmer's litres/kg to gallons but left event.fuel_unit reading "L".
                # Forwarding that stale unit made calculate_production_event_emissions
                # divide by 3.78541 a second time, under-reporting post-harvest fuel by
                # 3.79x (a 310 L dryer run was billed as 21.6 gal, not 81.9 gal).
                # The quantity handed over here is gallons, so say so.
                # Gases are exempt: the extractor leaves them in their own unit.
                fuel_unit=(
                    (getattr(event, "fuel_unit", None) or extra_data.get("fuel_unit"))
                    if str(fuel_type).lower() == "natural_gas"
                    else "gal"
                ),
                energy_source=energy_source,
                # Collected by the PH form section and read by nothing until now.
                processing_energy_kwh=extra_data.get("processing_energy_kwh"),
                processing_type=extra_data.get("processing_type"),
            )

            base_emissions = calculation_result["co2e_kg"]
            breakdown = calculation_result["breakdown"]
            breakdown["production_type"] = "PH"
            data_sources = calculation_result["data_sources"]
            calculation_method = calculation_result["calculation_method"]
            base_limitations = calculation_result.get("limitations", "")
            if isinstance(base_limitations, list):
                base_limitations = "; ".join(base_limitations)
            limitations = (
                "Excludes refrigeration/cold-storage electricity unless reported as "
                "processing_energy_kwh. " + base_limitations
            )

            recommendations = self._generate_epa_production_recommendations(event, base_emissions, calculation_method)

            return {
                "co2e": round(base_emissions, 3),
                "calculation_method": calculation_method,
                # Run 8 (R8-04): no energy recorded for post-harvest work is not an EPA figure.
                "verification_status": "not_estimated" if calculation_method == "not_estimated" else "epa_usda_sourced",
                "not_estimated": calculation_method == "not_estimated",
                "data_sources": data_sources,
                "breakdown": breakdown,
                "limitations": limitations,
                "recommendations": recommendations,
                "confidence_level": breakdown.get("confidence_level", 0.80),
            }

        except Exception as e:
            logger.error(f"Post-harvest processing calculation error: {e}")
            return {
                "co2e": 0.0,
                "calculation_method": "calculation_error",
                "verification_status": "error",
                "error": str(e),
                "data_sources": [],
                "breakdown": {},
                "limitations": "Calculation failed, using fallback values",
                "recommendations": [],
            }

    # NOTE: a _parcel_area_hectares() helper briefly lived here, to give the high-temperature
    # branch an area to work with. It was removed the same day: substituting the whole
    # orchard's area for an area the farmer never reported is what turned one heat event into
    # 12,974 kg CO2e. If an event has no area, that is information, not a gap to fill.

    @staticmethod
    def _parcel_pump_attributes(event):
        """Measured pumping-plant attributes from the parcel, as calculator kwargs.

        Returns only the keys that are actually recorded, so an unset attribute falls through
        to the calculator's default instead of overriding it with None.
        """
        try:
            parcel = event.history.parcel
        except AttributeError:
            return {}

        attributes = {}
        efficiency_pct = getattr(parcel, "pump_efficiency_pct", None)
        if efficiency_pct:
            # Stored as a percentage for the farmer; the calculator wants a fraction.
            attributes["pump_efficiency"] = float(efficiency_pct) / 100.0
        pressure_psi = getattr(parcel, "system_pressure_psi", None)
        if pressure_psi:
            attributes["system_pressure_psi"] = float(pressure_psi)
        return attributes

    def calculate_weather_event_impact(self, event) -> Dict[str, Any]:
        """A weather record carries no emissions.

        It documents conditions: a frost night, a hailstorm, a heat wave. The work done in
        response (frost protection, irrigation, cleanup) is logged as its own activity, with its
        own fuel, and that record carries the emissions. Until 2026-10 this method inferred a
        figure from the weather record itself (heaters assumed from the protection measures
        named, pumping assumed from a water deficit) with no fuel the grower had entered:
        a number the operation never measured, and one that double-counted any response work
        logged properly. The weather form never offered a fuel input, and its own code says
        weather is not a source of carbon emissions. Owner decision 2026-10-21.

        Existing weather carbon entries are removed when the event is saved
        (`history.signals`) and in bulk by `manage.py remove_weather_carbon_entries`.
        """
        note = (
            "A weather record documents conditions and carries no emissions. Log the work done in "
            "response (frost protection, irrigation, cleanup) as its own activity."
        )
        # The keys the old result carried stay, so a caller reading them finds an honest empty
        # value rather than a missing key. No efficiency score: there is nothing to grade.
        return {
            "co2e": 0.0,
            "calculation_method": "weather_not_estimated",
            "data_source": None,
            "data_sources": [],
            "usda_factors_based": False,
            "confidence_score": None,
            "verification_status": "not_applicable",
            "limitations": [note],
            "last_updated": None,
            "breakdown": {"weather_type": getattr(event, "type", None)},
            "recommendations": [],
            "transparency_note": note,
        }

    def calculate_equipment_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of equipment events (maintenance, fuel consumption, etc.)
        Enhanced with structured fields for better accuracy.
        """
        try:
            # Get crop information from the production
            crop_name = "default"
            # `hasattr(history, "product")` is ALWAYS True for a model FK — the attribute exists,
            # it is simply None when unset. Checking it therefore guarded nothing, and
            # `event.history.product.name` raised AttributeError on every production without a
            # crop, which the caller swallowed into "zero defaults": silent zero carbon.
            if event.history is not None and event.history.product is not None:
                crop_name = event.history.product.name

            # ENHANCED: Use structured equipment data
            equipment_data = self._get_structured_equipment_data(event, crop_name)

            base_emissions = 0.0
            cost_estimate = 0.0

            if event.type == "FC":  # Fuel Consumption
                # `fuel_amount` is normalized to **liters** (or kWh for electric) by
                # _get_structured_equipment_data. `FUEL_EMISSION_FACTORS` are all
                # per-gallon except electricity (per-kWh) and natural_gas (per-cubic-foot).
                # FIX 2026-04-11: convert liters → gallons before applying per-gallon
                # factors. Previously, this line multiplied liters by a per-gallon
                # factor, producing a ~3.785x overestimate for every liquid fuel.
                fuel_amount = equipment_data["fuel_amount"]
                fuel_type = equipment_data["fuel_type"].lower()

                emission_factor = self.FUEL_EMISSION_FACTORS.get(fuel_type, self.FUEL_EMISSION_FACTORS["diesel"])

                if fuel_type == "electric":
                    # fuel_amount is kWh, factor is per-kWh
                    base_emissions = fuel_amount * emission_factor
                elif fuel_type == "natural_gas":
                    # Factor is per cubic foot. Approximate 1 L natural gas ≈ 0.035 cf.
                    base_emissions = (fuel_amount * 0.035) * emission_factor
                else:
                    # Liquid fuels (diesel / gasoline / propane / biodiesel / none):
                    # fuel_amount is in liters, factor is per gallon → convert first.
                    fuel_gallons = fuel_amount / 3.78541
                    base_emissions = fuel_gallons * emission_factor

                # A5 (2026-07): the self-assessed efficiency rating NO LONGER scales
                # emissions. It is a free choice the farmer makes in a dropdown ("high" /
                # "normal" / "low"), and selecting "high" used to cut reported fuel
                # emissions by 15% — a self-declared discount on a measured quantity.
                # `carbon-methodology.md` lists anti-gaming protections precisely to stop
                # that; a rating that lowers your own footprint is the clearest example.
                # The fuel actually burned is already the measurement; efficiency is at most
                # context for the farmer, so it stays in the breakdown and out of the maths.
                efficiency_modifier = 1.0
                cost_estimate = fuel_amount * 1.2  # Approximate fuel cost per liter

                # Equipment type specific adjustments
                equipment_type = equipment_data["equipment_type"]
                if "large" in str(equipment_type).lower():
                    base_emissions *= 1.3  # Large equipment uses more fuel
                elif "small" in str(equipment_type).lower():
                    base_emissions *= 0.8  # Small equipment is more efficient

            elif event.type in ["MN", "RE"]:  # Maintenance, Repair
                # Use equipment type and hours for better estimation
                hours = equipment_data["hours_operated"]
                equipment_type = equipment_data["equipment_type"]

                # Base emissions per hour by equipment type
                base_rate = 2.0  # Default kg CO2e per hour
                if "tractor" in str(equipment_type).lower():
                    if "large" in str(equipment_type).lower():
                        base_rate = 5.0
                    elif "medium" in str(equipment_type).lower():
                        base_rate = 3.5
                    else:
                        base_rate = 2.5
                elif "pump" in str(equipment_type).lower():
                    base_rate = 1.5
                elif "harvester" in str(equipment_type).lower():
                    base_rate = 8.0

                base_emissions = hours * base_rate if hours > 0 else 0.0
                cost_estimate = float(event.maintenance_cost or (hours * 50 if hours > 0 else 0))

            elif event.type == "CA":  # Calibration
                base_emissions = 0.0  # No direct emissions from calibration
                cost_estimate = 50.0

            elif event.type == "BD":  # Breakdown
                # Use actual fuel/repair data if available, otherwise 0
                # Reference VerifiedEmissionFactors as the single source of truth for emission factors
                # (avoids factor drift when EPA/USDA updates are applied).
                repair_fuel = self._extract_numeric_value(getattr(event, "fuel_consumed", "0"), default=0.0)
                if repair_fuel > 0:
                    from .verified_emission_factors import VerifiedEmissionFactors

                    fuel_unit = getattr(event, "fuel_unit", "L") or "L"
                    # Convert to gallons for EPA diesel factor (10.21 kg CO2/gal)
                    repair_fuel_gallons = repair_fuel / 3.78541 if fuel_unit == "L" else repair_fuel
                    diesel_factor = VerifiedEmissionFactors.EPA_DIESEL_FACTORS["agricultural_equipment"]
                    base_emissions = repair_fuel_gallons * diesel_factor.value
                else:
                    base_emissions = 0.0
                cost_estimate = float(event.maintenance_cost or 0)

            elif event.type == "EI":  # Inspection
                base_emissions = 0.0  # No direct emissions from inspection
                cost_estimate = 25.0

            recommendations = self._generate_equipment_recommendations(
                event, base_emissions, cost_estimate, equipment_data
            )

            result = {
                "co2e": round(base_emissions, 3),
                "calculation_method": (
                    "usda_fuel_factors_enhanced" if event.type == "FC" else "equipment_estimation_enhanced"
                ),
                "data_source": "USDA Agricultural Research Service" if event.type == "FC" else "Industry Standards",
                "verification_status": "factors_verified" if event.type == "FC" else "estimated",
                "breakdown": {
                    "fuel_amount": equipment_data["fuel_amount"],
                    "fuel_type": equipment_data["fuel_type"],
                    "equipment_type": equipment_data["equipment_type"],
                    "area_worked": equipment_data["area_worked"],
                    "hours_operated": equipment_data["hours_operated"],
                    "operation_efficiency": equipment_data["efficiency"],
                    "data_source": equipment_data["data_source"],
                },
                "cost_analysis": {
                    "estimated_cost": cost_estimate,
                    "cost_per_co2e": cost_estimate / max(base_emissions, 0.1),
                    "cost_per_hectare": (
                        cost_estimate / max(equipment_data["area_worked"], 0.1)
                        if equipment_data["area_worked"] > 0
                        else 0
                    ),
                },
                "recommendations": recommendations,
            }

            return self._add_enhanced_usda_metadata(result, event)

        except Exception as e:
            return {"co2e": 0.0, "usda_factors_based": False, "error": str(e)}

    def calculate_soil_management_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of soil management events using USDA area-scaled emission factors
        Enhanced with standardized fuel consumption data for 90% accuracy
        """
        try:
            from .emission_factors import EmissionFactorsRegistry
            from .verified_emission_factors import VerifiedEmissionFactors

            base_emissions = 0.0
            fuel_emissions = 0.0
            area_hectares = 0.0
            confidence_score = 65.0
            data_completeness_factors = []

            # Get area managed - critical for proper scaling
            # CRITICAL: pass event so area_unit is read correctly (acres vs hectares).
            # Without event, _convert_area_to_hectares defaults to 'ha' and treats 85 acres as 85 ha.
            # `a or b` treats a legitimate 0 as absent (Decimal("0") is falsy), so a zero
            # area fell through to the "0" string and then to the 1-hectare default.
            # Only None means the field was not supplied.
            _area_raw = getattr(event, "area_covered", None)
            if _area_raw is None:
                _area_raw = getattr(event, "area", None)
            area_hectares = self._convert_area_to_hectares(_area_raw, event=event)

            # ENHANCED: Calculate fuel consumption emissions (standardized across event types)
            fuel_consumed_raw = getattr(event, "fuel_consumed", None)
            equipment_hours_raw = getattr(event, "equipment_hours", None)

            # Convert string values to float for calculations
            fuel_consumed = None
            if fuel_consumed_raw:
                try:
                    fuel_consumed = float(fuel_consumed_raw)
                except (ValueError, TypeError):
                    fuel_consumed = None

            equipment_hours = None
            if equipment_hours_raw:
                try:
                    equipment_hours = float(equipment_hours_raw)
                except (ValueError, TypeError):
                    equipment_hours = None

            if fuel_consumed and fuel_consumed > 0:
                # Use verified EPA emission factors for direct fuel combustion
                fuel_unit = getattr(event, "fuel_unit", "L")
                fuel_type = getattr(event, "fuel_type", "diesel") or "diesel"

                # Reference VerifiedEmissionFactors as single source of truth (prevents drift)
                from .verified_emission_factors import VerifiedEmissionFactors

                if fuel_type == "electric":
                    # Electric equipment: use kWh directly with country-specific grid factor
                    electricity_factor = VerifiedEmissionFactors.get_country_electricity_factor().value
                    fuel_emissions = float(fuel_consumed) * electricity_factor
                    fuel_gallons = 0  # No gallons involved for electric
                else:
                    # Convert to gallons for EPA calculation
                    if fuel_unit == "L":
                        fuel_gallons = float(fuel_consumed) / 3.78541
                    elif fuel_unit in ("gal", "gallons"):
                        fuel_gallons = float(fuel_consumed)
                    else:
                        # Unknown unit — log warning and assume gallons
                        logger.warning(f"Soil Management: unexpected fuel_unit={fuel_unit!r}, assuming gallons")
                        fuel_gallons = float(fuel_consumed)

                    # Use VerifiedEmissionFactors EPA_FUEL_FACTORS for the actual fuel type
                    fuel_factor = VerifiedEmissionFactors.EPA_FUEL_FACTORS.get(
                        fuel_type, VerifiedEmissionFactors.EPA_FUEL_FACTORS.get("diesel")
                    )
                    fuel_emissions = fuel_gallons * fuel_factor.value
                confidence_score = 90.0  # High confidence with fuel data
                data_completeness_factors.extend(["fuel_consumption_documented", "epa_factors_applied"])

                # Log fuel calculation details
                logger.info(
                    f"Soil Management fuel calculation: {fuel_consumed} {fuel_unit} = {fuel_gallons:.2f} gal = {fuel_emissions:.2f} kg CO2e"
                )

            # Map event types to emission factor keys
            event_type_mapping = {
                "OM": "organic_matter",  # Organic Matter Addition
                "CC": "cover_crops",  # Cover Crop
                "CO": "composting",  # Composting
                "TI": "tillage",  # Tillage
                "ST": "soil_test",  # Soil Test
                "PA": "ph_adjustment",  # pH Adjustment
                "GR": "grazing",  # Grazing Management
                "HD": "habitat",  # Habitat Development (hedgerows / insectary) — zero direct emissions
                "NS": "nesting",  # Nesting / Shelter Structures (nest boxes) — zero direct emissions
                # Lab analysis is a sampling record, like a soil test: the sample is taken by hand
                # and the lab work is upstream (excluded by the methodology). It fell through to
                # "general" (1.0 kg CO2e per hectare), so a water analysis on one acre read
                # 0.41 kg "from recorded inputs" (AC-14, 2026-10-26). Any fuel burned getting to
                # the block is still counted from `fuel_consumed`.
                "LA": "soil_test",
            }

            # Get the appropriate emission factor for area-based calculation
            factor_key = event_type_mapping.get(event.type, "general")
            factor_data = EmissionFactorsRegistry.get_soil_management_factor(factor_key)

            # Review on landing #35 (2026-10-28): the soil table's tillage (1.2 kg/ha) and pH
            # adjustment (0.3 kg/ha) defaults cite "USDA-ARS Soil Carbon Research 2025" with a
            # soil-carbon reference, and 1.2 kg/ha is about 25x below the cultivation factor the
            # methodology page already publishes for the same kind of pass. A tillage pass with no
            # fuel now uses that same per-hectare diesel estimate as production cultivation (a Trazo
            # estimate, published), and a pH adjustment with no fuel and no lime gets no default:
            # the record holds nothing to estimate from, so it is not estimated.
            if factor_key == "tillage":
                from .verified_emission_factors import VerifiedEmissionFactors as _VEF

                cultivation = _VEF.PRODUCTION_FACTORS["cultivation_diesel"]
                diesel = _VEF.EPA_FUEL_FACTORS["diesel"]
                factor_data = {
                    **factor_data,
                    "value": cultivation.value * diesel.value,
                    "unit": "kg CO2e per hectare",
                    "source": f"{cultivation.source} ({cultivation.value} gal diesel/ha), {diesel.source}",
                    "reference": "Trazo estimate: the production cultivation diesel factor",
                    "provenance": cultivation.provenance,
                }
            elif factor_key == "ph_adjustment":
                factor_data = {**factor_data, "value": 0.0}
            emission_factor = factor_data["value"]  # kg CO2e per hectare

            # Area-based emissions calculation
            area_emissions = 0.0
            if area_hectares > 0:
                area_emissions = area_hectares * emission_factor
                data_completeness_factors.append("area_documented")
            else:
                # No area provided - return 0 emissions (no phantom defaults)
                area_emissions = 0.0
                data_completeness_factors.append("area_assumed")

            # Recorded fuel replaces a per-hectare default that is itself an estimate of that fuel.
            fuel_replaces_area_default = bool(fuel_emissions) and factor_key in FUEL_PROXY_SOIL_FACTORS
            if fuel_replaces_area_default:
                area_emissions = 0.0
                data_completeness_factors.append("operation_default_replaced_by_recorded_fuel")

            # ============================================================================
            # IPCC 2006 carbonate-lime CO2 (PA events)
            # IPCC 2006 Vol 4, Ch 11, section 11.3, Eq. 11.12: Tier 1 factors on the annual
            # applied mass, limestone 0.12 and dolomite 0.13 t C/t (x 44/12 = 0.44 / 0.477).
            # Counted ONLY when the record names a carbonate material AND carries the applied
            # quantity (Astra follow-up 2026-10-28, B1). A pH adjustment with no material, or
            # with quicklime / hydrated lime (not carbonates), adds no lime term.
            # ============================================================================
            lime_dissolution_emissions = 0.0
            lime_kg_applied = 0.0
            lime_type_used = None
            lime_factor_data = None

            amendment_numeric = getattr(event, "amendment_amount_numeric", None)
            amendment_text = getattr(event, "amendment_amount", None)
            if event.type == "PA" and (amendment_numeric is not None or amendment_text):
                # None unless a carbonate material is named on the record
                lime_type_used = self._detect_lime_type(event)

                if lime_type_used is not None:
                    # Prefer structured numeric field over legacy string parsing
                    amendment_unit = getattr(event, "amendment_amount_unit", "kg")
                    if amendment_numeric is not None:
                        lime_kg_applied = float(amendment_numeric)
                        if amendment_unit == "tons":
                            lime_kg_applied *= 1000.0
                        elif amendment_unit == "lbs":
                            lime_kg_applied *= 0.453592
                    else:
                        lime_kg_applied = self._parse_lime_amount(amendment_text)

                    if lime_kg_applied > 0:
                        # Get IPCC-verified lime dissolution factor
                        lime_factor_data = EmissionFactorsRegistry.get_lime_dissolution_factor(lime_type_used)
                        lime_emission_factor = lime_factor_data["value"]  # kg CO₂ per kg lime

                        # Calculate lime dissolution emissions
                        lime_dissolution_emissions = lime_kg_applied * lime_emission_factor
                        data_completeness_factors.append("ipcc_lime_dissolution_calculated")
                        data_completeness_factors.append(f"lime_type_{lime_type_used}")

                        logger.info(
                            f"IPCC Lime Dissolution: {lime_kg_applied:.1f} kg {lime_type_used} × "
                            f"{lime_emission_factor} kg CO₂/kg = {lime_dissolution_emissions:.2f} kg CO₂"
                        )
                else:
                    data_completeness_factors.append("no_carbonate_material_named")
                    logger.info("Skipped IPCC lime CO2: no carbonate material named on the record")

            # NEVER: a per-pass tillage soil CO2 flux term (removed 2026-10-28, Astra follow-up B1).
            # It charged 50/150/300 kg CO2e/ha by depth, and a missing depth read as 150. The
            # cited sources do not support per-pass factors: Reicosky, Dugas & Torbert 1997 is a
            # 24-hour post-tillage pulse on one Texas vertisol; West & Post 2002 and IPCC 2019
            # Vol 4 Ch 5 are multi-year soil stock change (20-year default); Lal 2004 is
            # farm-operation energy, which the recorded fuel already counts. Tillage counts the
            # recorded fuel, or the per-hectare operation default above when no fuel is recorded.
            # Soil stock accounting, if it ever comes, needs its own baseline, interval and
            # overlap rules.

            # ============================================================================
            # Field N2O from nitrogen applied in the amendment (2026-07-31)
            # ============================================================================
            # Post-application N2O depends on the NITROGEN, not on what carried it.
            # ChemicalEvent fertilisers were charged for it; soil amendments were not — so
            # on an organic orchard, where compost is normally the largest N source, the
            # biggest contributor to field N2O was silently counted as zero. Same factor
            # and same IPCC derivation as the fertiliser path, so the two cannot diverge.
            amendment_n_kg = 0.0
            amendment_n2o_emissions = 0.0
            n_pct = getattr(event, "amendment_nitrogen_percentage", None)
            amendment_numeric = getattr(event, "amendment_amount_numeric", None)
            if n_pct and amendment_numeric:
                amendment_kg = float(amendment_numeric)
                unit = getattr(event, "amendment_amount_unit", "kg")
                if unit == "tons":
                    amendment_kg *= 1000.0  # metric tons, per the form's own label
                elif unit == "lbs":
                    amendment_kg *= 0.453592
                amendment_n_kg = amendment_kg * (float(n_pct) / 100.0)
                field_n2o_factor = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["nitrogen_field_n2o"]
                amendment_n2o_emissions = amendment_n_kg * field_n2o_factor.value
                logger.info(
                    f"Amendment field N2O: {amendment_kg:.1f} kg x {n_pct}% N = "
                    f"{amendment_n_kg:.1f} kg N x {field_n2o_factor.value} = "
                    f"{amendment_n2o_emissions:.2f} kg CO2e"
                )

            # ============================================================================
            # Combine all emission components
            # ============================================================================
            base_emissions = fuel_emissions + area_emissions + lime_dissolution_emissions + amendment_n2o_emissions

            # Adjust confidence score based on data availability
            if fuel_consumed and fuel_consumed > 0:
                confidence_score = 90.0  # High confidence with fuel data
            elif event.type in SAMPLING_SUBTYPES and area_hectares > 0:
                # Soil testing with no fuel = 0 emissions is scientifically correct
                # (manual tools, no combustion) — high confidence in that result
                confidence_score = 90.0
            elif area_hectares > 0:
                confidence_score = 75.0  # Good confidence with area data only
            else:
                confidence_score = 60.0  # Lower confidence with minimal data

            # Additional confidence factors based on available data
            if hasattr(event, "soil_ph") and event.soil_ph:
                confidence_score += 5.0
                data_completeness_factors.append("soil_ph_available")

            if hasattr(event, "organic_matter_percentage") and event.organic_matter_percentage:
                confidence_score += 5.0
                data_completeness_factors.append("organic_matter_data")

            if hasattr(event, "amendment_amount") and event.amendment_amount:
                if lime_kg_applied > 0:
                    confidence_score += 15.0  # Higher confidence with lime quantity used
                else:
                    confidence_score += 10.0
                data_completeness_factors.append("amendment_quantity")

            if hasattr(event, "test_results") and event.test_results:
                confidence_score += 10.0
                data_completeness_factors.append("detailed_test_results")

            # Boost confidence if the IPCC lime factor was applied
            if lime_dissolution_emissions > 0:
                confidence_score += 5.0
                data_completeness_factors.append("enhanced_scientific_factors_applied")

            # Cap confidence at 95%
            confidence_score = min(confidence_score, 95.0)

            recommendations = self._generate_soil_recommendations(event, base_emissions)

            # Determine calculation method based on data availability
            if event.type in SAMPLING_SUBTYPES and (not fuel_consumed or fuel_consumed == 0):
                calculation_method = "zero_direct_emissions_manual_sampling"
            elif event.type in SAMPLING_SUBTYPES and fuel_consumed and fuel_consumed > 0:
                calculation_method = "fuel_based_soil_sampling"
            else:
                calculation_method = "usda_area_scaled_soil_factors"
            if fuel_consumed and fuel_consumed > 0 and event.type not in SAMPLING_SUBTYPES:
                calculation_method = (
                    "fuel_based_soil_operation" if fuel_replaces_area_default else "enhanced_fuel_plus_area_factors"
                )
            if lime_dissolution_emissions > 0:
                calculation_method = "ipcc_lime_dissolution_enhanced"
            if lime_dissolution_emissions > 0 and fuel_consumed and fuel_consumed > 0:
                calculation_method = "comprehensive_lime_fuel_enhanced"

            # Build enhanced calculation string
            calc_parts = []
            if fuel_emissions > 0:
                calc_parts.append(f"Fuel: {round(fuel_emissions, 3)} kg CO₂e")
            if area_emissions != 0:
                calc_parts.append(f"Area: {area_hectares} ha × {emission_factor} = {round(area_emissions, 3)} kg CO₂e")
            if lime_dissolution_emissions > 0:
                calc_parts.append(
                    f"Lime Dissolution (IPCC): {lime_kg_applied:.1f} kg × "
                    f"{lime_factor_data['value']} = {round(lime_dissolution_emissions, 3)} kg CO₂"
                )
            calculation_string = " + ".join(calc_parts) + f" = {round(base_emissions, 3)} kg CO₂e"

            # Build data sources list
            data_sources = [factor_data["source"]]
            if lime_factor_data:
                data_sources.append(lime_factor_data["source"])

            # Map raw subtype code to human-readable label
            soil_type_labels = {
                "ST": "soil_testing",
                "PA": "ph_adjustment",
                "OM": "organic_matter",
                "CC": "cover_crop",
                "TI": "tillage",
                "CO": "composting",
                "GR": "grazing",
                "HD": "habitat_development",
                "NS": "nesting_shelter",
                "LA": "lab_analysis",
            }
            soil_label = soil_type_labels.get(event.type, event.type)

            result = {
                "co2e": round(base_emissions, 3),
                "calculation_method": calculation_method,
                "data_source": " | ".join(data_sources),
                "verification_status": "usda_ipcc_factors_verified",
                "emission_factor_used": {
                    "factor_type": factor_key,
                    "factor_value": emission_factor,
                    "unit": factor_data["unit"],
                    "impact_type": factor_data.get("impact_type", "unknown"),
                    "reference": factor_data["reference"],
                },
                "calculation_details": {
                    "area_hectares": area_hectares,
                    "area_emissions": round(area_emissions, 3),
                    "fuel_emissions": round(fuel_emissions, 3),
                    "lime_dissolution_emissions": round(lime_dissolution_emissions, 3),
                    "amendment_nitrogen_kg": round(amendment_n_kg, 3),
                    "amendment_field_n2o_emissions": round(amendment_n2o_emissions, 3),
                    "total_emissions": round(base_emissions, 3),
                    "emission_factor": emission_factor,
                    "calculation": calculation_string,
                    "confidence_score": confidence_score,
                    "data_completeness": data_completeness_factors,
                },
                "breakdown": {
                    "soil_activity": soil_label,
                    "area_managed": area_hectares,
                    # Backend always converts to hectares; preview label must match to avoid
                    # "85 acres × -1 kg/acre = -85" display that doesn't match the stored total.
                    "area_unit": "ha",
                    "fuel_consumed": fuel_consumed or 0,
                    "fuel_unit": getattr(event, "fuel_unit", "L"),
                    "equipment_hours": equipment_hours or 0,
                    "area_emissions": round(area_emissions, 3),
                    "fuel_emissions": round(fuel_emissions, 3),
                    "lime_dissolution_emissions": round(lime_dissolution_emissions, 3),
                    "amendment_nitrogen_kg": round(amendment_n_kg, 3),
                    "amendment_field_n2o_emissions": round(amendment_n2o_emissions, 3),
                    "emission_factor": emission_factor,
                    "total_impact": base_emissions,
                },
                "recommendations": recommendations,
            }

            # Add lime-specific data if applicable
            if lime_dissolution_emissions > 0 and lime_factor_data:
                result["breakdown"]["lime_calculation_basis"] = LIME_CALCULATION_BASIS
                result["lime_dissolution_details"] = {
                    "lime_amount_kg": round(lime_kg_applied, 2),
                    "lime_type": lime_type_used,
                    "emission_factor": lime_factor_data["value"],
                    "emission_factor_unit": lime_factor_data["unit"],
                    "emissions_kg_co2": round(lime_dissolution_emissions, 3),
                    "source": lime_factor_data["source"],
                    "reference": lime_factor_data["reference"],
                    "methodology": "IPCC 2006 Tier 1",
                    "calculation_basis": LIME_CALCULATION_BASIS,
                    "note": (
                        "Estimated CO2 from a recorded carbonate-lime application, using IPCC Tier 1 "
                        "factors and assigning the emissions to the application year; this is not a "
                        "measured release on the application date."
                    ),
                }

            enriched = self._add_enhanced_usda_metadata(result, event)

            # Do not label an area estimate as computed from recorded inputs (AC-14, 2026-10-26).
            #
            # `_add_enhanced_usda_metadata` sets `usda_factors_based: True` for every US event,
            # and the cards render that as "From recorded inputs". The production path takes it
            # back for its per-hectare estimates; this path never did. So a pH adjustment with no
            # material (0.3 kg/ha x 1 acre = 0.12 kg), a tillage with no fuel (then 1.2 kg/ha plus
            # a soil-flux term since removed, x 1 acre = 61 kg) and a lab analysis
            # (1.0 kg/ha "general" x 1 acre = 0.41 kg) were all badged as recorded-input figures.
            #
            # Recorded inputs here are the fuel, the lime and the amendment nitrogen: a quantity
            # on the record times a published factor. The area factor is a per-hectare default.
            # A figure built only from it is `area_estimate`, the
            # status the production path, the serializer, the exports and the consumer total
            # (RECORDED_BASIS_STATUSES) already read as "estimated from the area, no fuel
            # recorded". The sentinel also stops `create_carbon_entry_from_event` flipping the
            # stored flag back to True.
            #
            # A figure that mixes both keeps its factor-based label: fuel was recorded, which is
            # what the `area_estimate` wording says was not.
            recorded_component = fuel_emissions or lime_dissolution_emissions or amendment_n2o_emissions
            area_component = area_emissions
            if area_component and not recorded_component:
                enriched["usda_factors_based"] = False
                enriched["verification_status"] = "area_estimate"
                enriched["breakdown"]["calculation_basis"] = "usda_standard_per_hectare"
            elif not recorded_component and not area_component:
                # Nothing counted: the 0 is the absence of an input, not an agency factor
                # (same rule as the pest and reported-fuel-only production paths).
                enriched["usda_factors_based"] = False
                enriched["verification_status"] = "no_factor_applied"

            return enriched

        except Exception as e:
            return {
                "co2e": 0.0,  # No phantom emissions on error
                "usda_factors_based": False,
                "verification_status": "calculation_error",
                "error": str(e),
                "fallback_used": "general_soil_management_estimate",
            }

    def calculate_business_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of business events.

        Business events (certifications, audits, compliance) have negligible
        direct operational emissions. Per Trazo's Direct Operational Emissions
        methodology, lifecycle/indirect benefits are not quantified as CO2e.
        """
        try:
            crop_name = "default"
            # `hasattr(history, "product")` is ALWAYS True for a model FK — the attribute exists,
            # it is simply None when unset. Checking it therefore guarded nothing, and
            # `event.history.product.name` raised AttributeError on every production without a
            # crop, which the caller swallowed into "zero defaults": silent zero carbon.
            if event.history is not None and event.history.product is not None:
                crop_name = event.history.product.name

            business_data = self._get_structured_business_data(event, crop_name)
            recommendations = self._generate_business_recommendations(event, 0.0, business_data)

            result = {
                "co2e": 0.0,
                "calculation_method": "direct_operational_emissions",
                "data_source": "Trazo Direct Emissions Methodology",
                "methodology_note": (
                    "Business events (certifications, audits, compliance) have negligible "
                    "direct operational emissions, so none is counted as CO2e."
                ),
                "verification_status": business_data["verification_status"],
                "breakdown": {
                    "business_type": business_data["business_type"],
                    "certification_type": business_data["certification_type"],
                    "carbon_credits_earned": business_data["carbon_credits_earned"],
                    "carbon_credits_unit": business_data["carbon_credits_unit"],
                    "sustainability_practice": business_data["sustainability_practice"],
                    "verification_status": business_data["verification_status"],
                    "data_source": business_data["data_source"],
                    "direct_emissions_kg": 0.0,
                },
                "transparency_metrics": {
                    "consumer_value": "high",
                    "verification_level": business_data["verification_status"],
                    "carbon_impact": "neutral",
                },
                "recommendations": recommendations,
            }

            return self._add_enhanced_usda_metadata(result, event)

        except Exception as e:
            return {
                "co2e": 0.0,
                "usda_factors_based": False,
                "verification_status": "calculation_error",
                "error": str(e),
            }

    def calculate_pest_management_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of pest management events (IPM practices)

        Sprint 3 Epic 3.1: Enhanced to use fuel/equipment fields for accurate carbon calculations.

        A scouting SUMMARY (a season of passes logged as one record) runs this same calculation.
        It used to take a separate aggregate path that returned a hardcoded 0 and never read
        fuel, so a summary with its season fuel total filled in reported no emissions. Removed
        2026-09-10, when a stored 0 started rendering as "No direct emissions" in the modal.
        """
        try:
            # Sprint 3 Epic 3.1: Enhanced fuel/equipment calculation
            fuel_emissions = 0.0
            base_emissions = 0.0
            calculation_method = "integrated_pest_management_estimation"
            data_source = "Industry Standards"
            verification_status = "estimated"

            # Extract fuel/equipment fields (Sprint 3 Epic 3.1)
            # Scouting summary mode collects its fuel as `fuel_consumed_total`, an extra_data-only
            # key (history/serializers.py). Read it when the per-event column is empty, without
            # gating on `is_summary`: the form holds that flag as a string and it can be stored as
            # True or "true", so a type-sensitive check would drop the fuel for one of them.
            fuel_consumed_raw = getattr(event, "fuel_consumed", None) or (
                (getattr(event, "extra_data", None) or {}).get("fuel_consumed_total")
            )
            fuel_type = getattr(event, "fuel_type", "diesel") or "diesel"
            fuel_unit = getattr(event, "fuel_unit", "L") or "L"
            equipment_hours_raw = getattr(event, "equipment_hours", None)
            production_efficiency = getattr(event, "production_efficiency", "normal") or "normal"
            area_covered_raw = getattr(event, "area_covered", None)
            area_unit = getattr(event, "area_unit", "ha") or "ha"

            # Convert string values to float for calculations
            fuel_consumed = None
            if fuel_consumed_raw:
                try:
                    fuel_consumed = float(fuel_consumed_raw)
                except (ValueError, TypeError):
                    fuel_consumed = None

            equipment_hours = None
            if equipment_hours_raw:
                try:
                    equipment_hours = float(equipment_hours_raw)
                except (ValueError, TypeError):
                    equipment_hours = None

            area_covered = None
            if area_covered_raw:
                try:
                    area_covered = float(area_covered_raw)
                except (ValueError, TypeError):
                    area_covered = None

            # Calculate fuel emissions if fuel data provided
            if fuel_consumed and fuel_consumed > 0:
                # Reference VerifiedEmissionFactors as single source of truth (prevents drift)
                from .verified_emission_factors import VerifiedEmissionFactors

                if fuel_type == "electric":
                    # Country-specific electricity factor (US: EPA eGRID2023, see VerifiedEmissionFactors)
                    electricity_factor = VerifiedEmissionFactors.get_country_electricity_factor().value
                    fuel_emissions = fuel_consumed * electricity_factor
                    calculation_method = "epa_egrid_electricity"
                    data_source = "EPA eGRID 2023"
                    logger.info(
                        f"Pest Management electric: {fuel_consumed} {fuel_unit} × {electricity_factor} = {fuel_emissions:.2f} kg CO2e"
                    )
                else:
                    # Convert to gallons for EPA calculation
                    if fuel_unit == "L":
                        fuel_gallons = float(fuel_consumed) / 3.78541
                    elif fuel_unit in ("gal", "gallons"):
                        fuel_gallons = float(fuel_consumed)
                    else:
                        logger.warning(f"Pest Management: unexpected fuel_unit={fuel_unit!r}, assuming gallons")
                        fuel_gallons = float(fuel_consumed)

                    # Use VerifiedEmissionFactors for fuel factor (single source of truth)
                    fuel_factor = VerifiedEmissionFactors.EPA_FUEL_FACTORS.get(
                        fuel_type, VerifiedEmissionFactors.EPA_FUEL_FACTORS.get("diesel")
                    )
                    fuel_emissions = fuel_gallons * fuel_factor.value

                    calculation_method = "epa_fuel_combustion"
                    data_source = "EPA GHG Emission Factors Hub (40 CFR Part 98)"
                    logger.info(
                        f"Pest Management fuel: {fuel_consumed} {fuel_unit} = {fuel_gallons:.2f} gal × {fuel_factor.value} = {fuel_emissions:.2f} kg CO2e"
                    )

                verification_status = "epa_verified"

            # Pest management type context - only add base emissions when fuel data proves activity
            if event.type == "BR":  # Beneficial Release
                # Beneficial insect releases have no direct emissions without fuel data
                pass  # base_emissions stays 0.0

            elif event.type == "SC":  # Scouting
                # Only count if fuel was consumed (driving to scout)
                pass  # Fuel emissions already captured above

            elif event.type == "TM":  # Trap Monitoring
                # Only count if fuel was consumed
                pass  # Fuel emissions already captured above

            elif event.type == "IP":  # IPM Implementation
                # IPM has no direct emissions
                pass  # base_emissions stays 0.0

            # Total emissions = base + fuel
            total_emissions = base_emissions + fuel_emissions

            # A5 (2026-07): self-assessed efficiency no longer scales emissions — see the
            # equivalent note in the equipment calculator. Retained in the breakdown as
            # farmer-supplied context, with no effect on the figure.
            efficiency_modifier = 1.0

            recommendations = self._generate_pest_recommendations(event, total_emissions)

            # Map raw subtype code to human-readable label
            pest_type_labels = {
                "SC": "scouting",
                "BR": "beneficial_release",
                "TM": "trap_monitoring",
                "PI": "pest_identification",
                "TA": "threshold_assessment",
                "IP": "ipm_implementation",
                "CU": "cultural_control",
            }
            pest_label = pest_type_labels.get(event.type, event.type)

            result = {
                "co2e": round(total_emissions, 3),
                "calculation_method": calculation_method,
                "data_source": data_source,
                "verification_status": verification_status,
                "breakdown": {
                    "pest_activity": pest_label,
                    "pest_management_type": pest_label,
                    "base_emissions": round(base_emissions, 3),
                    "fuel_emissions": round(fuel_emissions, 3),
                    "fuel_consumed": fuel_consumed,
                    "fuel_unit": fuel_unit,
                    "fuel_type": fuel_type,
                    "equipment_hours": equipment_hours,
                    "area_covered": area_covered,
                    "area_unit": area_unit,
                    "production_efficiency": production_efficiency,
                    "efficiency_modifier": efficiency_modifier,
                },
                "recommendations": recommendations,
            }

            enriched = self._add_enhanced_usda_metadata(result, event)

            # ⚖️ Do not claim EPA/USDA sourcing for a figure no factor produced — the same rule
            # as the reported-fuel-only Production path (see the note there). Every pest subtype
            # counts reported fuel and nothing else, so with no fuel entered the 0 is the absence
            # of an input. `_add_enhanced_usda_metadata` flags every US event
            # `usda_factors_based: True`, which the detail modal renders as an "EPA/USDA-sourced"
            # badge beside the number. The sentinel also stops `create_carbon_entry_from_event`
            # upgrading the stored flag back to True.
            if not fuel_emissions and not base_emissions:
                enriched["usda_factors_based"] = False
                enriched["verification_status"] = "no_factor_applied"

            return enriched

        except Exception as e:
            logger.error(f"Error calculating pest management impact: {e}")
            return {
                "co2e": 0.0,
                "usda_factors_based": False,
                "verification_status": "calculation_error",
                "error": str(e),
            }

    def calculate_general_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of general events using enhanced emission factors.
        Replaces hardcoded 0.5 kg CO2e with context-aware calculations.
        Option A: Empty events return 0.0 kg CO2e instead of 0.25 kg CO2e.
        """
        try:
            # Get event details for calculation
            event_description = (
                getattr(event, "description", "") or getattr(event, "name", "") or getattr(event, "observation", "")
            )
            event_type = getattr(event, "type", "")

            # Option A: Check for empty/minimal event data
            # If no meaningful content is provided, return 0.0 kg CO2e
            if not event_description or event_description.strip() == "":
                return {
                    "co2e": 0.0,
                    "calculation_method": "empty_general_event",
                    "data_source": "No Activity Specified",
                    "verification_status": "no_activity",
                    "breakdown": {
                        "general_event_type": "empty",
                        "duration_hours": 0.0,
                        "participants": 0,
                        "emission_factor": 0.0,
                        "confidence_level": "high",
                    },
                    "recommendations": ["Add event description to calculate carbon impact"],
                    "transparency_note": "No emissions calculated - no activity specified",
                }

            # Default parameters for general events
            duration_hours = 1.0
            participants = 1

            # Try to extract duration from event data if available
            if hasattr(event, "extra_data") and event.extra_data:
                duration_hours = float(event.extra_data.get("duration_hours", 1.0))
                participants = int(event.extra_data.get("participants", 1))

            # Determine the appropriate general event type based on description
            general_event_type = self._classify_general_event_type(event_description, event_type)

            # Calculate using enhanced emission factors
            calculation_result = EnhancedEmissionFactors.calculate_general_event_emissions(
                event_type=general_event_type, duration_hours=duration_hours, participants=participants
            )

            base_emissions = calculation_result["co2e_kg"]

            # Generate recommendations
            recommendations = self._generate_general_recommendations(event, base_emissions, general_event_type)

            result = {
                "co2e": round(base_emissions, 3),
                "calculation_method": calculation_result["calculation_method"],
                "data_source": calculation_result["source"],
                "verification_status": "enhanced_factors",
                "breakdown": {
                    "general_event_type": general_event_type,
                    "duration_hours": duration_hours,
                    "participants": participants,
                    "emission_factor": calculation_result["emission_factor"],
                    "confidence_level": calculation_result["confidence_level"],
                },
                "recommendations": recommendations,
                "transparency_note": f"Calculated using EPA-verified factors for {general_event_type} activities",
            }

            return self._add_enhanced_usda_metadata(result, event)

        except Exception as e:
            logger.warning(f"Error calculating general event impact: {e}")
            # Fallback to reasonable default instead of hardcoded 0.5
            return {
                "co2e": 0.1,  # Reduced from 0.5 to more appropriate default
                "calculation_method": "general_event_fallback",
                "data_source": "Default Estimation",
                "verification_status": "estimated",
                "breakdown": {"general_event_type": "documentation", "fallback_reason": str(e)},
                "recommendations": [],
                "error": str(e),
            }

    @staticmethod
    def record_carbon_status(event, calculation_result: Optional[Dict[str, Any]]) -> None:
        """Store (or clear) an explicit `not_estimated` carbon status on the event (run 8, R8-04).

        A null estimate with its basis and reason, kept in `extra_data["carbon_calculation"]`,
        which the event serializer already reads when no CarbonEntry exists. Written with a
        queryset update so it does not re-fire the save signal. `None` clears a stale status once
        the record has something to count from.
        """
        extra = dict(getattr(event, "extra_data", None) or {})
        current = extra.get("carbon_calculation")
        if calculation_result is None:
            if not (isinstance(current, dict) and current.get("calculation_method") == "not_estimated"):
                return
            extra.pop("carbon_calculation", None)
        else:
            breakdown = calculation_result.get("breakdown") or {}
            extra["carbon_calculation"] = {
                "co2e": None,
                "calculation_method": "not_estimated",
                "calculation_basis": "not_estimated",
                "verification_status": "not_estimated",
                "usda_factors_based": False,
                "reason": calculation_result.get("limitations") or breakdown.get("carbon_notes") or "",
            }
        type(event).objects.filter(pk=event.pk).update(extra_data=extra)
        event.extra_data = extra

    def create_carbon_entry_from_event(self, event, calculation_result: Dict[str, Any]) -> Optional["CarbonEntry"]:
        """
        Create a CarbonEntry from an event and its carbon calculation result.
        Enhanced with USDA compliance tracking and audit logging.
        """
        try:
            from ..models import CarbonEntry

            # Get or create carbon source
            carbon_source = self._get_or_create_carbon_source(event)

            # Get establishment_id through the parcel relationship
            establishment_id = None
            if hasattr(event, "history") and event.history:
                if hasattr(event.history, "parcel") and event.history.parcel:
                    establishment_id = event.history.parcel.establishment.id

            # Create carbon entry
            carbon_entry = CarbonEntry.objects.create(
                establishment_id=establishment_id,
                production_id=getattr(event.history, "id", None) if hasattr(event, "history") else None,
                # The link; the description and registry id below stay for display and export.
                activity_id=getattr(event, "activity_id", None),
                # Only a NEGATIVE result is an offset. A zero is an answer that the activity emitted
                # nothing (carbon-methodology.md), and was stored as "offset" until 2026-11-05, so
                # every summary counted it as one.
                type="offset" if calculation_result.get("co2e", 0) < 0 else "emission",
                source=carbon_source,
                amount=abs(calculation_result.get("co2e", 0)),
                year=(
                    getattr(event.date, "year", timezone.now().year)
                    if hasattr(event, "date") and event.date
                    else timezone.now().year
                ),
                description=f"Auto-calculated from {event.__class__.__name__}(ID={event.id}) event: {calculation_result.get('calculation_method', 'unknown')}",
                # `explanation_text`, `methodology_template` and `permanence_plan` are no longer
                # written. Nothing reads them, and they shipped to the farmer's records export as
                # blanket claims ("using USDA emission factors", "USDA_<CLASS>", "verified farm
                # event data") that compliance.md forbids: provenance is per input class, and is
                # carried by `data_source` and `verification_status`.
                usda_factors_based=calculation_result.get("usda_factors_based", False),
                verification_status=calculation_result.get("verification_status", "estimated"),
                data_source=calculation_result.get("data_source", "Unknown"),
                created_by=getattr(event, "created_by", None) if hasattr(event, "created_by") else None,
                registry_verification_id=f"REG-{event.__class__.__name__}-{event.id}",
                baseline_data=calculation_result.get("breakdown", {}),
                co2e_amount=calculation_result.get("co2e", 0),
                timestamp=event.date if hasattr(event, "date") else timezone.now(),
                # `external_verification_id` ("EXT-<Class>-<id>") was written here until 2026-11-06;
                # nothing read it, and migration 0048 retired it (carbon/retired_columns.py).
            )

            # Create USDA compliance record
            confidence_score = calculation_result.get("confidence_score", 0.5)
            self._create_usda_compliance_record(carbon_entry, event, calculation_result, confidence_score)

            # Update carbon entry EPA/USDA factors status based on compliance record
            from ..models import USDAComplianceRecord

            compliance_record = USDAComplianceRecord.objects.filter(carbon_entry=carbon_entry).first()

            # ⚖️ This upgrade is ONE-WAY: it can set the flag True, never False. That is fine
            # while `is_epa_factors_based` is a decent proxy — but read its docstring: it
            # returns True whenever validation RAN with a known crop. It reports that the
            # validation pipeline worked, not that any factor was applied to THIS number.
            #
            # So a calculation that deliberately applied no factor had its own answer
            # overwritten here, and the modal showed an "EPA/USDA-sourced" badge beside a 0
            # produced by the absence of an input. `verification_status` survived the
            # overwrite while `usda_factors_based` did not, which is what made the mismatch
            # visible: one field said `no_factor_applied`, the other said True.
            #
            # Gated on the explicit sentinel rather than on the flag itself, so paths that
            # simply never set `usda_factors_based` keep the upgrade they rely on.
            # An area estimate keeps its own status; the validation upgrade below must not badge it.
            # Nor an input figure that is an estimate in any part (2026-11-13).
            no_factor_applied = calculation_result.get("verification_status") in (
                "no_factor_applied",
                "area_estimate",
                VERIFICATION_STATUS_ESTIMATE,
            )
            if compliance_record and compliance_record.is_epa_factors_based and not no_factor_applied:
                carbon_entry.usda_factors_based = True
                carbon_entry.save(update_fields=["usda_factors_based"])
                logger.info(
                    f"✅ Updated carbon entry {carbon_entry.id} to usda_factors_based=True based on compliance record"
                )

            # Create calculation audit record
            calculation_time_ms = calculation_result.get("calculation_time_ms", 0)
            self._create_calculation_audit(event, carbon_entry, calculation_result, calculation_time_ms)

            logger.info(f"Created carbon entry {carbon_entry.id} with USDA compliance tracking")
            return carbon_entry

        except Exception as e:
            logger.error(f"Error creating carbon entry from event: {e}")
            return None

    # ENHANCED Helper methods for structured fields
    def _get_structured_npk_content(self, event, crop_name: str = "default") -> Dict[str, float]:
        """
        Get NPK content from structured fields (nitrogen_percentage, phosphorus_percentage, potassium_percentage)
        or fallback to parsing concentration string.
        CRITICAL FIX: Only fertilizers (FE) have NPK content. Pesticides (PE), Fungicides (FU), Herbicides (HE) have ZERO NPK.
        """
        try:
            # CRITICAL: Check chemical type first - only fertilizers have NPK
            chemical_type = getattr(event, "type", "FE")
            if chemical_type in ["PE", "FU", "HE"]:  # Pesticides, Fungicides, Herbicides
                return {"N": 0.0, "P": 0.0, "K": 0.0}  # NO NPK content

            # Only for fertilizers (FE): Check if structured NPK fields are available and populated
            if (
                hasattr(event, "nitrogen_percentage")
                and event.nitrogen_percentage is not None
                and hasattr(event, "phosphorus_percentage")
                and event.phosphorus_percentage is not None
                and hasattr(event, "potassium_percentage")
                and event.potassium_percentage is not None
            ):

                return {
                    "N": float(event.nitrogen_percentage),
                    "P": float(event.phosphorus_percentage),
                    "K": float(event.potassium_percentage),
                }

            # Fallback to parsing the FARMER-ENTERED concentration string (FE only).
            # F03 fix (2026-06): do NOT inject a phantom "10-10-10"/crop default when
            # the farmer left concentration blank. Fabricating an NPK composition
            # manufactures nitrogen-manufacturing + N2O emissions from data the farmer
            # never provided, contradicting the no-phantom policy used for soil and
            # irrigation. Absent/unknown composition -> 0 NPK (no emissions), and the
            # event is surfaced as composition-not-provided rather than silently
            # invented.
            return self._npk_from_raw_concentration(event, chemical_type)

        except Exception as e:
            logger.warning(f"Error getting structured NPK content, using fallback: {e}")
            chemical_type = getattr(event, "type", "FE")
            if chemical_type in ["PE", "FU", "HE"]:
                return {"N": 0.0, "P": 0.0, "K": 0.0}  # NO NPK for non-fertilizers
            return self._npk_from_raw_concentration(event, chemical_type)

    def _npk_from_raw_concentration(self, event, chemical_type: str) -> Dict[str, float]:
        """Parse NPK from the farmer-entered concentration only — no phantom default.

        Returns zeros (and logs a completeness note) when the concentration is
        blank/unknown, so missing fertilizer composition contributes 0 emissions
        instead of a fabricated 10-10-10. See F03 (2026-06).
        """
        raw_conc = getattr(event, "concentration", None)
        if not raw_conc or str(raw_conc).strip().lower() in ("", "unknown", "n/a", "na", "none", "null"):
            logger.info(
                "FE event %s has no NPK/concentration — NPK treated as 0 (no phantom default, F03)",
                getattr(event, "id", "?"),
            )
            return {"N": 0.0, "P": 0.0, "K": 0.0}
        return self._parse_npk_content(str(raw_conc), chemical_type)

    def _get_structured_application_method(self, event, crop_name: str = "default") -> str:
        """
        Get application method from structured field (application_method_structured)
        or fallback to way_of_application or application_method
        """
        try:
            # Check if structured application method field is available
            if hasattr(event, "application_method_structured") and event.application_method_structured:
                return event.application_method_structured

            # Check for frontend application_method field
            if hasattr(event, "application_method") and event.application_method:
                return self._get_intelligent_application_method(event.application_method, event, crop_name)

            # Fallback to legacy field
            if hasattr(event, "way_of_application") and event.way_of_application:
                return self._get_intelligent_application_method(event.way_of_application, event, crop_name)

            # Default if no application method found
            return "broadcast"

        except Exception as e:
            logger.warning(f"Error getting structured application method, using fallback: {e}")
            return "broadcast"

    def _get_structured_equipment_data(self, event, crop_name: str = "default") -> Dict[str, Any]:
        """
        Get equipment data from structured fields or fallback to legacy fields
        """
        try:
            # Check for structured fields first
            if hasattr(event, "fuel_consumed") and event.fuel_consumed is not None:
                fuel_amount = float(event.fuel_consumed)
                fuel_unit = getattr(event, "fuel_unit", "L")
                fuel_type_for_density = (getattr(event, "fuel_type", None) or "diesel").lower()

                # Convert to liters if needed (electric stays in kWh)
                if fuel_type_for_density == "electric":
                    pass  # leave fuel_amount as kWh — downstream handles per-kWh factor
                elif fuel_unit == "gal":
                    fuel_amount *= 3.78541  # gallons to liters
                elif fuel_unit == "kg":
                    # Convert kg → L using fuel-specific density (L/kg = 1 / kg-per-L).
                    # Agent finding #2: treating all fuels as diesel density (1.2 L/kg)
                    # mis-converted propane by ~2.4x. Sources: EPA 40 CFR Part 98 densities.
                    kg_to_l = {
                        "diesel": 1.18,  # 0.85 kg/L
                        "gasoline": 1.34,  # 0.745 kg/L
                        "propane": 2.03,  # 0.493 kg/L
                        "biodiesel": 1.15,  # 0.87 kg/L
                    }.get(fuel_type_for_density, 1.18)
                    fuel_amount *= kg_to_l

                return {
                    "fuel_amount": fuel_amount,
                    "fuel_type": event.fuel_type or "diesel",
                    "equipment_type": getattr(event, "equipment_type_structured", None) or event.equipment_name,
                    "area_worked": float(getattr(event, "area_worked", 0) or 0),
                    "area_unit": getattr(event, "area_unit", "ha"),
                    "hours_operated": float(getattr(event, "hours_operated", 0) or 0),
                    "efficiency": getattr(event, "operation_efficiency", "normal"),
                    "data_source": "structured_fields",
                }

            # Fallback to legacy EquipmentEvent fields (fuel_amount, hours_used, area_covered as string).
            # EquipmentEvent (type 4) is LEGACY — merged into Production for users but model still exists.
            # These fields are kept for backward compatibility with existing data.
            return {
                "fuel_amount": float(getattr(event, "fuel_amount", 0) or 0),
                "fuel_type": event.fuel_type or "diesel",
                "equipment_type": event.equipment_name or "general",
                "area_worked": self._extract_numeric_value(event.area_covered or "", default=1.0),
                "area_unit": "ha",
                "hours_operated": float(getattr(event, "hours_used", 0) or 0),
                "efficiency": "normal",
                "data_source": "legacy_fields",
            }

        except Exception as e:
            logger.warning(f"Error getting structured equipment data, using zero defaults: {e}")
            return {
                "fuel_amount": 0.0,
                "fuel_type": "diesel",
                "equipment_type": "general",
                "area_worked": 0.0,
                "area_unit": "ha",
                "hours_operated": 0.0,
                "efficiency": "normal",
                "data_source": "defaults",
            }

    def _get_structured_production_data(self, event, crop_name: str = "default") -> Dict[str, Any]:
        """
        Get production data from structured fields or fallback to legacy fields
        """

        # F07 fix (2026-06): preserve None for unreported fuel. Coercing None->0.0
        # made calculate_production_event_emissions treat it as an explicit "0 fuel"
        # (manual routing -> 0 kg) instead of "no fuel reported" (USDA area estimate),
        # so saved HA/PL/TR/CU/TH with empty fuel computed 0 while the preview showed
        # the area-based estimate. None flows through to the area-estimate fallback,
        # matching the preview path. Explicit farmer-entered 0 is still respected.
        def _fuel_or_none():
            raw = getattr(event, "fuel_consumed", None)
            if raw is None or raw == "":
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        try:
            # Check for structured fields first
            if hasattr(event, "area_covered") and event.area_covered is not None:
                area = float(event.area_covered)
                area_unit = getattr(event, "area_unit", "ha")

                # Convert to hectares if needed
                if area_unit == "acres":
                    area *= 0.404686  # acres to hectares
                elif area_unit == "m2":
                    area /= 10000  # m2 to hectares
                elif area_unit == "km2":
                    area *= 100  # km2 to hectares

                return {
                    "area_hectares": area,
                    "yield_quantity": float(getattr(event, "yield_quantity", 0) or 0),
                    "yield_unit": getattr(event, "yield_unit", "kg"),
                    "fuel_consumed": _fuel_or_none(),
                    "fuel_unit": getattr(event, "fuel_unit", "L"),
                    # A8 fix (2026-07): _extract_production_event_data reads
                    # structured_data["fuel_type"] with a "diesel" fallback, but this dict
                    # never carried the key — so the kg->gallons conversion always used the
                    # diesel density (0.832 kg/L) regardless of what the farmer selected.
                    # Wrong for gasoline (0.745) and badly wrong for the propane used in
                    # flame weeding, now an offered floor-management operation.
                    "fuel_type": getattr(event, "fuel_type", None) or "diesel",
                    "equipment_hours": float(getattr(event, "equipment_hours", 0) or 0),
                    "transportation_distance": float(getattr(event, "transportation_distance", 0) or 0),
                    "transportation_unit": getattr(event, "transportation_unit", "km"),
                    "efficiency": getattr(event, "production_efficiency", "normal"),
                    "data_source": "structured_fields",
                }

            # Fallback to legacy fields and history data
            # FIX (2026-04-12): Read actual model values for fuel/equipment even when
            # area_covered is NULL. EM (Equipment Maintenance) events legitimately have
            # no area_covered but DO have fuel_consumed and equipment_hours. Previously
            # these were hardcoded to 0.0, causing carbon=0 and "No CO₂ data" on timeline.
            # Run 8 (R8-04): no area recorded on the event means no area. This used to borrow the
            # PARCEL's area (or 1.0), and a per-hectare diesel estimate was then charged on land
            # the record never said was worked: a cleanout with no fuel saved as 129 kg CO2e.
            # Same reasoning as the removed _parcel_area_hectares() note further up.
            area = 0.0

            return {
                "area_hectares": area,
                "yield_quantity": float(getattr(event, "yield_quantity", 0) or 0),
                "yield_unit": getattr(event, "yield_unit", "kg"),
                "fuel_consumed": _fuel_or_none(),
                "fuel_unit": getattr(event, "fuel_unit", "L"),
                "fuel_type": getattr(event, "fuel_type", None) or "diesel",  # see the A8 note above
                "equipment_hours": float(getattr(event, "equipment_hours", 0) or 0),
                "transportation_distance": float(getattr(event, "transportation_distance", 0) or 0),
                "transportation_unit": getattr(event, "transportation_unit", "km"),
                "efficiency": getattr(event, "production_efficiency", "normal"),
                "data_source": "legacy_fields",
            }

        except Exception as e:
            logger.warning(f"Error getting structured production data, using defaults: {e}")
            defaults = self._get_intelligent_defaults(event, crop_name)
            return {
                "area_hectares": defaults.get("area", 1.0),
                "yield_quantity": 0.0,
                "yield_unit": "kg",
                "fuel_consumed": 0.0,
                "fuel_unit": "L",
                "equipment_hours": 0.0,
                "transportation_distance": 0.0,
                "transportation_unit": "km",
                "efficiency": "normal",
                "data_source": "defaults",
            }

    def _get_structured_business_data(self, event, crop_name: str = "default") -> Dict[str, Any]:
        """
        Get business event data from structured fields
        """
        try:
            return {
                "business_type": getattr(event, "business_type", "certification"),
                "certification_type": getattr(event, "certification_type", None),
                "carbon_credits_earned": float(getattr(event, "carbon_credits_earned", 0) or 0),
                "carbon_credits_unit": getattr(event, "carbon_credits_unit", "tCO2e"),
                "verification_status": getattr(event, "verification_status", "pending"),
                "sustainability_practice": getattr(event, "sustainability_practice", None),
                "data_source": "structured_fields" if hasattr(event, "business_type") else "legacy_fields",
            }
        except Exception as e:
            logger.warning(f"Error getting structured business data, using defaults: {e}")
            return {
                "business_type": "certification",
                "certification_type": None,
                "carbon_credits_earned": 0.0,
                "carbon_credits_unit": "tCO2e",
                "verification_status": "pending",
                "sustainability_practice": None,
                "data_source": "defaults",
            }

    def _extract_production_event_data(self, event) -> Dict[str, Any]:
        """Extract production event data for EPA/USDA calculations"""
        try:
            # Get crop information from the production
            crop_name = "unknown"
            # `hasattr(history, "product")` is ALWAYS True for a model FK — the attribute exists,
            # it is simply None when unset. Checking it therefore guarded nothing, and
            # `event.history.product.name` raised AttributeError on every production without a
            # crop, which the caller swallowed into "zero defaults": silent zero carbon.
            if event.history is not None and event.history.product is not None:
                crop_name = event.history.product.name
            elif hasattr(event, "history") and event.history and hasattr(event.history, "crop_type"):
                crop_name = event.history.crop_type.name if event.history.crop_type else "unknown"

            # Get structured production data
            structured_data = self._get_structured_production_data(event, crop_name)

            # Determine production type based on event type
            production_type = self._get_production_type_name(event.type, crop_name)

            # Extract specific production values
            area_covered = structured_data["area_hectares"] * 2.47105  # Convert to acres for EPA calculations
            fuel_consumed = structured_data["fuel_consumed"]
            equipment_hours = structured_data["equipment_hours"]

            # Convert fuel to gallons if needed.
            # NOTE (2026-07-31): gaseous fuels are deliberately NOT normalised here.
            # The EPA factor for natural gas is per STANDARD CUBIC FOOT, not per gallon,
            # so "litres of natural gas" is not a quantity that converts to anything
            # meaningful. Downstream (calculate_production_event_emissions) resolves gas
            # quantities against the factor's own basis and refuses nonsensical
            # liquid-volume units rather than silently emitting a near-zero figure.
            fuel_unit = structured_data["fuel_unit"]
            if str(structured_data.get("fuel_type", "")).lower() == "natural_gas":
                pass
            elif fuel_consumed and fuel_unit == "L":
                fuel_consumed = fuel_consumed / 3.78541  # Convert liters to gallons
            elif fuel_consumed and fuel_unit == "kg":
                # Convert kg to gallons via fuel density (diesel default: 0.832 kg/L)
                fuel_type = structured_data.get("fuel_type", "diesel")
                density = 0.832 if fuel_type == "diesel" else 0.745  # gasoline fallback
                fuel_consumed = (fuel_consumed / density) / 3.78541

            # Estimate water volume for irrigation
            water_volume_gallons = None
            if event.type == "IR":  # Irrigation
                # Preferred: farmer-reported irrigation_depth × area (USDA standard:
                # 27,154 gal/inch/acre). This is the accurate path and matches the
                # live carbon preview. Must be checked before legacy fallbacks.
                irrigation_depth_raw = getattr(event, "irrigation_depth", None)
                irrigation_depth_unit = getattr(event, "irrigation_depth_unit", "inches") or "inches"
                if irrigation_depth_raw and area_covered:
                    try:
                        depth_inches = float(irrigation_depth_raw)
                        if irrigation_depth_unit == "cm":
                            depth_inches = depth_inches * 0.3937
                        water_volume_gallons = area_covered * depth_inches * 27154.0
                    except (TypeError, ValueError):
                        water_volume_gallons = None
                if not water_volume_gallons:
                    if hasattr(event, "volume") and event.volume:
                        water_volume_gallons = self._convert_volume_to_gallons(event.volume, event, crop_name)
                    else:
                        # Estimate based on area (1000 gallons per acre is conservative)
                        water_volume_gallons = area_covered * 1000

            # Extract farmer-documented method for manual-operation detection
            # (e.g. "Hand thinning with pruning shears" should not apply USDA mechanical averages).
            # Priority order:
            #   1. extra_data.method          — free-text `production_method` bridged by frontend
            #   2. extra_data.production_method — legacy alias
            #   3. extra_data.harvest_method  — structured HA dropdown (hand_picking, mechanical, ...)
            # Including harvest_method ensures the structured HA dropdown choice alone is
            # sufficient to route manual harvests through _is_manual_method() — the farmer
            # shouldn't also have to type "Hand thinning" into production_method to get
            # accurate manual-operation carbon. Note: History.production_method is a
            # different field (organic/conventional) and must NOT be used here.
            extra_data = getattr(event, "extra_data", None) or {}
            # `getattr(event, "harvest_method", None)` is a defensive fallback for any
            # future serializer that writes the dropdown top-level on ProductionEvent.
            # Currently it resolves to None (ProductionEvent has no such attr) — safe.
            method = (
                extra_data.get("method")
                or extra_data.get("production_method")
                or extra_data.get("harvest_method")
                or getattr(event, "harvest_method", None)
            )

            return {
                "production_type": production_type,
                "crop_name": crop_name,
                "area_covered": area_covered,
                "fuel_consumed": fuel_consumed,
                "equipment_hours": equipment_hours,
                "water_volume_gallons": water_volume_gallons,
                "method": method,
                "structured_data": structured_data,
            }

        except Exception as e:
            # ⛔ This used to `return` zero defaults and let the caller carry on, which turned
            # ANY extraction error into a confident-looking carbon figure computed from
            # nothing: area 0, fuel None, water None. The number still rendered in the
            # activity wizard and printed into the certifier packet, indistinguishable from a
            # real calculation — there was no field anywhere in the result saying "this came
            # from a failure". That is the fabricated-number class this codebase already
            # removed from the wizard's API-failure fallback.
            #
            # It also actively hid bugs: the IR preview/saved parity suite read 34.32 instead
            # of 85.37 for two months and looked like a dropped-auxiliary-diesel defect in the
            # calculator, when the real cause was an AttributeError swallowed right here.
            #
            # Re-raised so the caller's own handler decides. `calculate_production_event_impact`
            # already wraps this call in a try/except that returns an explicit error result.
            logger.error(
                "Failed to extract production data for event %s (type=%s): %s",
                getattr(event, "id", "unsaved"),
                getattr(event, "type", "unknown"),
                e,
                exc_info=True,
            )
            raise

    def _get_production_type_name(self, event_type: str, crop_name: str) -> str:
        """Get descriptive production type name for EPA calculations - handles ALL frontend types"""
        type_mapping = {
            "HA": f"harvesting {crop_name}",
            "PL": f"planting {crop_name}",
            "IR": f"irrigating {crop_name}",
            "PR": f"pruning {crop_name}",
            "EM": "EM",
            "cultivation": f"cultivating {crop_name}",
            "fertilization": f"fertilizing {crop_name}",
            "weeding": f"weeding {crop_name}",
            "mulching": f"mulching {crop_name}",
            "transplanting": f"transplanting {crop_name}",
            "GE": f"general production {crop_name}",
        }
        return type_mapping.get(event_type, f"general production {crop_name}")

    def _convert_volume_to_gallons(self, volume_str: str, event, crop_name: str) -> float:
        """Convert volume string to gallons for EPA irrigation calculations.

        Uses UnitConverter as single source of truth for conversion factors.
        """
        from carbon.utils.unit_converter import UnitConverter

        try:
            volume_str_lower = str(volume_str).lower() if volume_str else ""
            volume_value = self._extract_numeric_value(volume_str_lower, default=0)
            if volume_value == 0:
                return 1000  # Default fallback

            # Detect unit from string
            if "gal" in volume_str_lower:
                return volume_value  # Already in gallons
            elif "m3" in volume_str_lower or "m³" in volume_str_lower or "cubic" in volume_str_lower:
                gallons, _ = UnitConverter.convert_volume(volume_value, "m3", "gallons")
                return gallons
            elif "ml" in volume_str_lower:
                gallons, _ = UnitConverter.convert_volume(volume_value, "ml", "gallons")
                return gallons
            elif "l" in volume_str_lower or "liter" in volume_str_lower:
                gallons, _ = UnitConverter.convert_volume(volume_value, "liters", "gallons")
                return gallons
            else:
                # No unit detected — check extra_data for water_volume_unit
                extra = getattr(event, "extra_data", None) or {}
                water_unit = extra.get("water_volume_unit", "").lower()
                if "gal" in water_unit:
                    return volume_value
                # Default: assume gallons (most common for US irrigation)
                return volume_value

        except Exception as e:
            logger.warning(f"Error converting volume to gallons: {e}")
            return 1000

    # NOTE: _get_crop_area_modifier REMOVED (2025-12-21)
    # Research showed arbitrary crop modifiers (1.3x avocado, 0.8x lettuce) lacked scientific basis.
    # Peer-reviewed LCA studies show avocado (0.38-0.91 kg CO₂e/kg) is similar to lettuce (0.46 kg).
    # Almond vs walnut only differs by ~5%, not 30%. Trazo's "Direct Operational Emissions" philosophy:
    # actual crop differences are captured through measured fuel/fertilizer/energy usage, not arbitrary multipliers.

    def _generate_epa_production_recommendations(self, event, emissions: float, calculation_method: str) -> list:
        """Generate EPA-based recommendations for production events"""
        recommendations = []

        try:
            # High emissions threshold (above 50 kg CO2e)
            if emissions > 50:
                recommendations.append(
                    {
                        "type": "efficiency_improvement",
                        "message": "Consider upgrading to more fuel-efficient equipment",
                        "impact": "High",
                    }
                )

            if emissions > 25:
                recommendations.append(
                    {
                        "type": "operational_optimization",
                        "message": "Optimize field operations timing to reduce multiple passes",
                        "impact": "Medium",
                    }
                )

            # Always include verification recommendation
            if calculation_method == "verified_usda_factors":
                recommendations.append(
                    {
                        "type": "data_quality",
                        "message": "Factor source named per input; see the carbon methodology. An estimate, not a verified figure.",
                        "impact": "Transparency",
                    }
                )

            return recommendations

        except Exception as e:
            logger.warning(f"Error generating EPA recommendations: {e}")
            return []

    # Helper methods
    def _parse_npk_content(self, concentration_str: str, chemical_type: str = "FE") -> Dict[str, float]:
        """
        Parse NPK values from concentration string like '10-10-10' or '20-5-10'
        CRITICAL FIX: Only fertilizers (FE) have NPK. Other chemicals return 0-0-0.
        """
        try:
            # CRITICAL: Only fertilizers have NPK content
            if chemical_type in ["PE", "FU", "HE"]:  # Pesticides, Fungicides, Herbicides
                return {"N": 0.0, "P": 0.0, "K": 0.0}

            # For fertilizers (FE): Try to parse NPK format (N-P-K)
            if "-" in concentration_str:
                parts = concentration_str.split("-")
                if len(parts) >= 3:
                    return {"N": float(parts[0]), "P": float(parts[1]), "K": float(parts[2])}

            # Try to extract percentage from text
            import re

            numbers = re.findall(r"\d+(?:\.\d+)?", concentration_str)
            if len(numbers) >= 3:
                return {"N": float(numbers[0]), "P": float(numbers[1]), "K": float(numbers[2])}

            # No three numbers, no analysis: zeros, and the calculator states the N-P-K is missing.
            # A fertilizer whose text held no analysis ("compost", "approx") was priced as
            # 10-10-10 here until 2026-11-13, the F03 phantom the blank-text path had already lost.
            return {"N": 0.0, "P": 0.0, "K": 0.0}

        except (TypeError, ValueError):
            return {"N": 0.0, "P": 0.0, "K": 0.0}

    def _extract_numeric_value(self, text, default: float = 0.0) -> float:
        """Extract the first numeric value from a string, or pass a real number through.

        2026-07: this used to go straight to `text.lower()`. Passing an int or a float raised
        AttributeError, the bare `except:` swallowed it, and the function returned `default`.
        Since `extra_data` is a JSONField, `{"duration": 8}` round-trips as a real int — so
        EVERY numeric extra_data value that happened to be stored as a JSON number rather
        than a quoted string was silently read as 0.

        That was the actual cause of the weather calculators returning 0 for documented heat
        and hail events: the branches were reading the right keys, and then this discarded the
        values. The blast radius is wider than weather — this helper is used across the
        chemical, production and soil paths, so any of them fed a JSON number lost it too.
        A leading minus sign was also dropped, which matters for sub-zero frost temperatures.
        """
        import re
        from decimal import Decimal

        if text is None:
            return default
        # Real numbers (including JSON ints/floats and model Decimals) need no parsing.
        if isinstance(text, bool):
            return default
        if isinstance(text, (int, float, Decimal)):
            try:
                return float(text)
            except (TypeError, ValueError):
                return default

        try:
            as_text = str(text).strip()
            if as_text.lower() in ["unknown", "n/a", "na", "", "none", "null"]:
                return default

            # Keep the sign: a frost event's "-2 C" must not become 2.
            numbers = re.findall(r"-?\d+(?:\.\d+)?", as_text)
            return float(numbers[0]) if numbers else default
        except (TypeError, ValueError):
            return default

    def _get_intelligent_defaults(self, event, crop_name: str = "default") -> Dict[str, Any]:
        """
        Get intelligent default values for events with missing data based on crop type and event type.
        This prevents zero emissions when users enter "Unknown" values.

        It carries no amount applied. The volume defaults that stood here (10 to 500 L) were read
        only by `_convert_volume_to_liters`, which no longer assumes an amount (2026-11-12).
        """
        # No N-P-K here: a default analysis is an invented input (2026-11-13). The crop blends that
        # stood beside each area (12-6-6 citrus, 46-0-0 corn, 15-15-15 nuts, 20-20-20 vegetables,
        # 16-16-16 otherwise) were read only by `_get_intelligent_concentration`, removed with them.
        defaults = {
            "area": 1.0,  # hectares
            "application_method": "broadcast",
        }

        # Crop-specific defaults
        crop_lower = crop_name.lower()

        # Event type specific defaults
        if hasattr(event, "type"):
            if event.type == "FE":  # Fertilizer
                if "citrus" in crop_lower or "orange" in crop_lower:
                    defaults.update({"area": 2.0})  # Typical citrus grove size
                elif "corn" in crop_lower:
                    defaults.update({"area": 1.5})  # Typical corn field
                elif any(nut in crop_lower for nut in ["almond", "walnut", "pecan"]):
                    defaults.update({"area": 3.0})  # Larger orchard areas
                elif any(veg in crop_lower for veg in ["tomato", "lettuce", "pepper"]):
                    defaults.update({"area": 0.5})  # Smaller vegetable plots
                else:
                    defaults.update({"area": 1.5})

            elif event.type in ["PE", "HE", "FU"]:  # Pesticides, Herbicides, Fungicides
                if "citrus" in crop_lower:
                    defaults.update({"area": 2.0, "application_method": "spray"})  # Citrus pest control
                elif any(veg in crop_lower for veg in ["tomato", "pepper", "cucumber"]):
                    defaults.update({"area": 0.5, "application_method": "foliar"})
                else:
                    defaults.update({"area": 1.0, "application_method": "spray"})

        # Production event defaults
        elif hasattr(event, "type") and event.type == "IR":  # Irrigation
            if any(nut in crop_lower for nut in ["almond", "walnut"]):
                defaults.update(
                    {
                        "area": 3.0,
                    }
                )
            elif "citrus" in crop_lower:
                defaults.update(
                    {
                        "area": 2.0,
                    }
                )
            else:
                defaults.update(
                    {
                        "area": 1.5,
                    }
                )

        return defaults

    def _convert_volume_to_liters(self, volume_str: str, event=None, crop_name: str = "default") -> float:
        """Convert a free-text volume ("3320 Kilograms", "12 gal") to liters.

        A text that holds no amount ("Unknown", "approx", "0", blank) converts to 0.0, never to a
        default: the chemical calculator then omits what needs an amount and says so. Until
        2026-11-12 it returned a per-crop default of 10 to 75 L, an amount nobody recorded.
        """
        if not volume_str or str(volume_str).strip().lower() in ["unknown", "n/a", "na", "none", "null"]:
            return 0.0

        volume_str = str(volume_str).lower()
        number = self._extract_numeric_value(volume_str)
        if number <= 0:
            return 0.0

        if "gal" in volume_str:
            return number * 3.78541  # gallons to liters
        elif "kg" in volume_str or "kilogram" in volume_str:
            # Convert kg to liters using density (check before 'l' to avoid false matches)
            return self._convert_kg_to_liters(number, event)
        elif "ml" in volume_str:
            return number / 1000
        elif "l" in volume_str or "liter" in volume_str:
            return number
        else:
            return number  # Assume liters if no unit

    def _convert_kg_to_liters(self, kg_amount: float, event=None) -> float:
        """
        Convert kilograms to liters using chemical-specific density.

        Common agricultural chemical densities (kg/L):
        - Anhydrous ammonia (82-0-0): ~0.68 kg/L
        - Liquid fertilizers: ~1.2-1.4 kg/L
        - Water-based solutions: ~1.0 kg/L
        - Herbicides/Pesticides: ~0.9-1.2 kg/L
        """
        try:
            # Get NPK content to identify chemical type
            if event and hasattr(event, "concentration"):
                concentration = getattr(event, "concentration", "")
                if "82-0-0" in concentration or "anhydrous" in concentration.lower():
                    # Anhydrous ammonia density
                    density = 0.68  # kg/L
                    return kg_amount / density

            # Check if it's a high-nitrogen fertilizer (likely anhydrous ammonia)
            if event and hasattr(event, "type") and getattr(event, "type") == "FE":
                npk_content = self._get_structured_npk_content(event, "default")
                nitrogen_percent = npk_content.get("N", 0)

                if nitrogen_percent >= 80:  # High nitrogen content (anhydrous ammonia)
                    density = 0.68  # kg/L for anhydrous ammonia
                    return kg_amount / density
                elif nitrogen_percent >= 20:  # Liquid fertilizer
                    density = 1.3  # kg/L for typical liquid fertilizers
                    return kg_amount / density

            # Default density for general agricultural chemicals
            density = 1.0  # kg/L (water-based solutions)
            return kg_amount / density

        except Exception as e:
            logger.warning(f"Error converting kg to liters: {e}")
            # Fallback: assume water density
            return kg_amount / 1.0

    def _convert_area_to_hectares(self, area_str: str, event=None, crop_name: str = "default") -> float:
        """Convert area string to hectares with intelligent defaults for missing data"""
        try:
            # SPRINT 6 FIX (2025-12-26): Handle numeric types (Decimal, int, float) directly
            # SoilManagementEvent stores area_covered as Decimal, not string
            from decimal import Decimal

            if isinstance(area_str, (int, float, Decimal)):
                # Direct numeric value — check area_unit on the event
                # `if area_str else 1.0` treated an EXPLICIT ZERO as missing, because
                # Decimal("0"), 0 and 0.0 are all falsy. SoilManagementEvent stores
                # area_covered as a Decimal, so a zero area became 1 acre and a tillage
                # record with no area reported 151.2 kg CO2e invented out of nothing.
                # Zero is a value the operator can enter; only None means "not told".
                area_value = 1.0 if area_str is None else float(area_str)
                area_unit = getattr(event, "area_unit", "ha") if event else "ha"
                if area_unit and area_unit.lower() in ["acre", "acres", "ac"]:
                    return area_value * 0.404686  # acres to hectares
                elif area_unit and area_unit.lower() in ["m²", "m2", "sqm", "square_meters"]:
                    return area_value / 10000  # m² to hectares
                return area_value  # Default: assume hectares

            # Check if area is missing or "Unknown"
            if not area_str or str(area_str).lower() in ["unknown", "n/a", "na", "none", "null"]:
                if event:
                    defaults = self._get_intelligent_defaults(event, crop_name)
                    return defaults["area"]
                return 1.0  # Fallback default

            area_str = str(area_str).lower()
            number = self._extract_numeric_value(area_str)

            # If extraction failed, use intelligent defaults.
            # `number == 0.0` cannot distinguish "no digits in the string" from the string
            # "0", so an explicit zero area was routed to the intelligent default (1 ha) and
            # came back as a full hectare of emissions. Check that the string actually
            # contained a digit before deciding extraction failed.
            has_digit = any(ch.isdigit() for ch in area_str)
            if number == 0.0 and not has_digit and event:
                defaults = self._get_intelligent_defaults(event, crop_name)
                return defaults["area"]

            if "acre" in area_str:
                return number * 0.404686  # acres to hectares
            elif "ha" in area_str or "hectare" in area_str:
                return number
            elif "m²" in area_str or "m2" in area_str:
                return number / 10000

            # No unit suffix in the string — fall back to event.area_unit
            # CRITICAL: the preview path (carbon/views.py MockSoilEvent) sends area_covered as a
            # plain number string like "85" with area_unit set separately. Without this fallback,
            # acres get treated as hectares (85 → 85 instead of 34.4).
            event_area_unit = getattr(event, "area_unit", None) if event else None
            if event_area_unit and str(event_area_unit).lower() in ["acre", "acres", "ac"]:
                return number * 0.404686
            if event_area_unit and str(event_area_unit).lower() in [
                "m²",
                "m2",
                "sqm",
                "square_meters",
            ]:
                return number / 10000
            return number  # Assume hectares if no unit info available

        except:
            if event:
                defaults = self._get_intelligent_defaults(event, crop_name)
                return defaults["area"]
            return 1.0  # Fallback default

    # ============================================================================
    # Lime helper methods (IPCC 2006)
    # ============================================================================

    def _parse_lime_amount(self, amendment_amount: str) -> float:
        """
        Parse amendment_amount string to extract lime quantity in kilograms.

        Supports various formats:
        - "2000 kg" or "2000kg"
        - "2 tons" or "2 tonnes"
        - "4000 lbs" or "4000 pounds"
        - "2 t/ha" (tons per hectare)
        - Just numeric value (assumes kg)

        Returns:
            float: Lime amount in kilograms (0.0 if parsing fails)
        """
        if not amendment_amount:
            return 0.0

        try:
            amount_str = str(amendment_amount).lower().strip()

            # Extract numeric value using regex
            import re

            # Match numbers including decimals and thousands separators
            numeric_match = re.search(r"[\d,]+\.?\d*", amount_str.replace(",", ""))
            if not numeric_match:
                return 0.0

            numeric_value = float(numeric_match.group())

            # Convert to kg based on unit
            if "ton" in amount_str or "tonne" in amount_str or amount_str.endswith("t"):
                # Metric tons to kg
                return numeric_value * 1000.0
            elif "lb" in amount_str or "pound" in amount_str:
                # Pounds to kg
                return numeric_value * 0.453592
            elif "kg" in amount_str or not any(unit in amount_str for unit in ["ton", "lb", "pound", "t/ha"]):
                # Already in kg or no unit specified (assume kg)
                return numeric_value
            else:
                # Default: assume kg
                return numeric_value

        except Exception as e:
            logger.warning(f"Failed to parse lime amount '{amendment_amount}': {e}")
            return 0.0

    # Not carbonates, so no IPCC carbonate factor. Quicklime (CaO) and hydrated lime (Ca(OH)2)
    # are burnt or slaked lime: IPCC 2006 Vol 4 Ch 11 section 11.3 gives factors for limestone
    # and dolomite only. Checked FIRST so "dolomitic hydrated lime" is not read as dolomite.
    # The others never had carbonate to release (gypsum is CaSO4, sulfur lowers pH).
    _NON_CARBONATE_AMENDMENTS = (
        "calcium_oxide",
        "calcium oxide",
        "calcium_hydroxide",
        "calcium hydroxide",
        "quicklime",
        "quick lime",
        "burnt lime",
        "burned lime",
        "hydrated lime",
        "slaked lime",
        "caustic lime",
        "cao",
        "ca(oh)2",
        "gypsum",
        "caso4",
        "calcium sulfate",
        "sulfur",
        "sulphur",
        "wood ash",
        "iron sulfate",
        "aluminum sulfate",
        "ammonium sulfate",
    )
    _DOLOMITE_NAMES = ("dolomite", "dolomitic", "mag lime", "magnesium lime", "camg", "calcium magnesium")
    _LIMESTONE_NAMES = (
        "limestone",
        "calcitic",
        "calcite",
        "ag lime",
        "aglime",
        "agricultural lime",
        "caco3",
        "calcium carbonate",
    )

    def _detect_lime_type(self, event):
        """The carbonate named on the record: 'limestone', 'dolomite', or None.

        Reads the material identity fields only: `amendment_type` (the form's enum) and
        `amendment_product_name`. None when no carbonate is named, which includes a blank
        material, compost or "other", quicklime and hydrated lime. There is no default: a pH
        adjustment with no named material is not evidence of limestone (Astra follow-up
        2026-10-28, B1).
        """
        names = [
            str(value).lower()
            for value in (getattr(event, "amendment_type", None), getattr(event, "amendment_product_name", None))
            if value
        ]
        if not names:
            return None
        text = " ".join(names)

        def named(candidates):
            return next((c for c in candidates if re.search(rf"(?<![a-z]){re.escape(c)}(?![a-z])", text)), None)

        hit = named(self._NON_CARBONATE_AMENDMENTS)
        if hit:
            logger.info(f"No carbonate factor: non-carbonate amendment '{hit}'")
            return None
        if named(self._DOLOMITE_NAMES):
            return "dolomite"
        if named(self._LIMESTONE_NAMES):
            return "limestone"
        return None

    # Regional default irrigation application depth (inches per single event).
    # Source: USDA NASS 2023 Irrigation Survey + USDA ERS Regional Water Use data.
    # Arid-region crops routinely require 2-3x the water per event compared to
    # humid-region crops at the same growth stage. Using the national 1-inch default
    # in states like AZ or NV underestimates a typical application by 2-2.5x.
    # Added 2026-03-21.
    REGIONAL_IRRIGATION_DEFAULTS = {
        # Arid West — high evapotranspiration, deep percolation to root zone
        "AZ": 2.5,
        "NM": 2.5,
        "NV": 2.5,
        "UT": 2.0,
        "CA": 2.0,
        "CO": 1.5,
        "TX": 1.5,
        # Semi-arid Great Plains
        "OK": 1.25,
        "KS": 1.25,
        "NE": 1.25,
        # Humid East — the 1-inch national default is appropriate
        "default": 1.0,
    }

    def _estimate_irrigation_water_volume(self, event, area_acres: float) -> float:
        """
        Estimate irrigation water volume when not explicitly provided.

        Uses USDA NASS 2023 Irrigation and Water Management Survey data:
        - Average seasonal application: 1.5 acre-feet per acre (~489,000 gallons/acre/season)
        - Typical single irrigation: 0.5-1.5 inches per event (national), higher in arid west
        - 1 inch of water per acre = 27,154 gallons

        Regional adjustment (added 2026-03-21):
        REGIONAL_IRRIGATION_DEFAULTS is consulted when the farm's state is available
        from the event. Arid-region states (AZ, NM, NV, etc.) require significantly
        more water per irrigation event than the humid-east default of 1 inch.

        Sources:
        - USDA ERS Irrigation & Water Use (ers.usda.gov)
        - USDA NASS 2023 Irrigation Survey

        Returns:
            float: Estimated water volume in gallons
        """
        # Return 0 gallons if no area specified - no phantom defaults
        if not area_acres or area_acres <= 0:
            return 0.0

        # Base estimation: moderate irrigation event (1 inch of water)
        # 1 inch water per acre = 27,154 gallons
        GALLONS_PER_INCH_PER_ACRE = 27154.0

        # Determine regional default from farm state if available
        # Canonical code, or None. Reading the raw field here used to miss on every
        # farm that stored "California" rather than "CA" — silently applying the
        # 1.0" humid-East default to a state whose real figure is 2.0".
        state = resolve_event_state(event)

        regional_default = self.REGIONAL_IRRIGATION_DEFAULTS.get(
            state or "", self.REGIONAL_IRRIGATION_DEFAULTS["default"]
        )

        # Start from regional default; override with text-based intensity signals below
        irrigation_inches = regional_default

        # Detect irrigation intensity from event data
        fields_to_check = []
        if hasattr(event, "description") and event.description:
            fields_to_check.append(str(event.description).lower())
        if hasattr(event, "notes") and event.notes:
            fields_to_check.append(str(event.notes).lower())
        if hasattr(event, "irrigation_type") and event.irrigation_type:
            fields_to_check.append(str(event.irrigation_type).lower())

        combined_text = " ".join(fields_to_check)

        # Heavy irrigation indicators — override regional default with a high value.
        # 1.75 inches is the heavy midpoint (range 1.5-2 inches).
        heavy_indicators = [
            "heavy",
            "deep",
            "flood",
            "furrow flood",
            "border flood",
            "saturate",
            "soak",
            "drought recovery",
        ]

        # Light irrigation indicators — override regional default with a low value.
        # 0.5 inches is used for supplemental/drip events.
        light_indicators = [
            "light",
            "supplement",
            "drip",
            "trickle",
            "micro",
            "deficit",
            "maintenance",
            "germination",
        ]

        # Text-based intensity signals override the regional default.
        for indicator in heavy_indicators:
            if indicator in combined_text:
                irrigation_inches = 1.75  # Heavy: 1.5-2 inches average
                logger.info(f"Detected heavy irrigation from indicator: '{indicator}'")
                break
        else:
            # Check for light irrigation
            for indicator in light_indicators:
                if indicator in combined_text:
                    irrigation_inches = 0.5  # Light: 0.5 inches
                    logger.info(f"Detected light irrigation from indicator: '{indicator}'")
                    break
            # No intensity signal — regional_default already set above

        # Calculate total water volume
        water_volume_gallons = area_acres * irrigation_inches * GALLONS_PER_INCH_PER_ACRE

        logger.info(
            f"USDA-based irrigation estimate: {area_acres} acres × {irrigation_inches} inches "
            f"(state={state or 'unknown'}, regional_default={regional_default}) × "
            f"{GALLONS_PER_INCH_PER_ACRE} gal/in/acre = {water_volume_gallons:.0f} gallons"
        )

        return water_volume_gallons

    def _get_intelligent_application_method(self, method_str: str, event=None, crop_name: str = "default") -> str:
        """Get intelligent application method defaults for missing data"""
        if not method_str or method_str.lower() in ["unknown", "n/a", "na", "none", "null"]:
            if event:
                defaults = self._get_intelligent_defaults(event, crop_name)
                return defaults["application_method"]
            return "broadcast"  # Fallback default
        return method_str

    def _normalize_application_method(self, method: str) -> str:
        """Normalize application method to standard terms (legacy)"""
        method = method.lower()
        if any(word in method for word in ["drip", "irrigation", "micro"]):
            return "drip_irrigation"
        elif any(word in method for word in ["broadcast", "spread"]):
            return "broadcast"
        elif any(word in method for word in ["foliar", "spray", "leaf"]):
            return "foliar"
        elif any(word in method for word in ["band", "strip"]):
            return "banded"
        elif any(word in method for word in ["inject", "subsurface"]):
            return "injection"
        else:
            return "broadcast"  # Default

    def _normalize_application_method_for_factors(self, method: str) -> str:
        """Normalize application method for emission factor adjustments"""
        method = method.lower()

        # Map to emission factor adjustment categories
        if any(word in method for word in ["inject", "subsurface", "deep"]):
            return "injected"
        elif any(word in method for word in ["incorporate", "till", "mix"]):
            return "incorporated"
        elif any(word in method for word in ["slow", "controlled", "coated", "release"]):
            return "slow_release"
        elif any(word in method for word in ["precision", "variable", "gps", "rate"]):
            return "precision"
        elif any(word in method for word in ["split", "multiple", "sidedress"]):
            return "split_application"
        else:
            return "broadcast"  # Default baseline method

    def _estimate_chemical_cost(self, event, volume_liters: float) -> float:
        """Estimate cost of chemical application"""
        # Rough cost estimates per liter
        cost_per_liter = {
            "FE": 2.50,  # Fertilizer
            "PE": 15.00,  # Pesticide
            "HE": 8.00,  # Herbicide
            "FU": 12.00,  # Fungicide
        }

        base_cost = cost_per_liter.get(event.type, 5.0) * volume_liters
        return round(base_cost, 2)

    def _generate_chemical_recommendations(
        self,
        event,
        efficiency: float,
        emissions: float,
        cost: float,
        crop_name: str = "default",
        crop_category: str = "default",
    ) -> List[Dict[str, Any]]:
        """Generate cost-saving and efficiency recommendations with crop-specific advice"""
        recommendations = []

        if efficiency < 0.8:
            recommendations.append(
                {
                    "type": "efficiency",
                    "title": "Improve Application Efficiency",
                    "description": f"Consider drip irrigation or injection methods for {round((0.9 - efficiency) * 100, 1)}% efficiency gain",
                    "potential_savings": round(cost * (0.9 - efficiency), 2),
                    "carbon_reduction": round(emissions * (0.9 - efficiency), 2),
                }
            )

        if event.type == "FE" and emissions > 50:  # High fertilizer emissions
            recommendations.append(
                {
                    "type": "optimization",
                    "title": "Consider Slow-Release Fertilizer",
                    "description": "Slow-release fertilizers can reduce N2O emissions by 20-30%",
                    "potential_savings": round(cost * 0.15, 2),
                    "carbon_reduction": round(emissions * 0.25, 2),
                }
            )

        # Crop-specific recommendations
        if crop_category == "legumes" and event.type == "FE":
            recommendations.append(
                {
                    "type": "crop_specific",
                    "title": "Reduce Nitrogen for Legumes",
                    "description": f"{crop_name} can fix nitrogen naturally. Consider reducing N fertilizer by 30-50%.",
                    "potential_savings": round(cost * 0.4, 2),
                    "carbon_reduction": round(emissions * 0.4, 2),
                }
            )

        if crop_category == "herbs" and event.type in ["PE", "HE", "FU"]:
            recommendations.append(
                {
                    "type": "crop_specific",
                    "title": "Consider Organic Pest Control",
                    "description": f"{crop_name} responds well to companion planting and beneficial insects.",
                    "potential_savings": round(cost * 0.3, 2),
                    "carbon_reduction": round(emissions * 0.3, 2),
                }
            )

        if crop_category == "nuts" and emissions > 30:
            recommendations.append(
                {
                    "type": "crop_specific",
                    "title": "Tree Crop Efficiency",
                    "description": f"{crop_name} trees benefit from precise nutrient timing. Consider soil testing.",
                    "potential_savings": round(cost * 0.2, 2),
                    "carbon_reduction": round(emissions * 0.2, 2),
                }
            )

        return recommendations

    def _generate_production_recommendations(
        self, event, emissions: float, crop_name: str = "default", crop_category: str = "default"
    ) -> List[Dict[str, Any]]:
        """Generate recommendations for production events with crop-specific advice"""
        recommendations = []

        if event.type == "IR":  # Irrigation
            recommendations.append(
                {
                    "type": "water_efficiency",
                    "title": "Optimize Irrigation Timing",
                    "description": "Early morning irrigation reduces evaporation losses by 20-30%",
                    "potential_savings": 50.0,
                    "carbon_reduction": round(emissions * 0.25, 2),
                }
            )

            # Crop-specific irrigation recommendations
            if crop_category == "nuts":
                recommendations.append(
                    {
                        "type": "crop_specific",
                        "title": "Deficit Irrigation for Nuts",
                        "description": f"{crop_name} can tolerate controlled water stress, reducing water use by 15-25%.",
                        "potential_savings": 100.0,
                        "carbon_reduction": round(emissions * 0.2, 2),
                    }
                )
            elif crop_category == "vegetables":
                recommendations.append(
                    {
                        "type": "crop_specific",
                        "title": "Mulching for Vegetables",
                        "description": f"{crop_name} benefits from mulching to retain soil moisture.",
                        "potential_savings": 75.0,
                        "carbon_reduction": round(emissions * 0.15, 2),
                    }
                )

        if event.type in ["HA", "PL"]:  # Harvesting, Planting
            recommendations.append(
                {
                    "type": "equipment",
                    "title": "Equipment Efficiency",
                    "description": "Regular equipment maintenance can improve fuel efficiency by 10-15%",
                    "potential_savings": 200.0,
                    "carbon_reduction": round(emissions * 0.12, 2),
                }
            )

            # Crop-specific equipment recommendations
            if crop_category == "grains":
                recommendations.append(
                    {
                        "type": "crop_specific",
                        "title": "Combine Harvester Optimization",
                        "description": f"{crop_name} harvesting can be optimized with proper combine settings.",
                        "potential_savings": 150.0,
                        "carbon_reduction": round(emissions * 0.1, 2),
                    }
                )

        return recommendations

    def _generate_weather_recommendations(self, event) -> List[Dict[str, Any]]:
        """Generate recommendations for weather events with enhanced suggestions"""
        recommendations = []

        if event.type == "FR":  # Frost
            recommendations.append(
                {
                    "type": "protection",
                    "title": "Consider Passive Frost Protection",
                    "description": "Row covers or thermal mass can reduce energy needs by 40%",
                    "potential_savings": 300.0,
                    "carbon_reduction": 6.0,
                }
            )
            if hasattr(event, "lower_temperature"):
                temp_c = self._extract_numeric_value(event.lower_temperature, default=0)
                temp = temp_c * 9 / 5 + 32  # Convert °C to °F
                if temp < 28:  # Severe frost (28°F = -2.2°C)
                    recommendations.append(
                        {
                            "type": "monitoring",
                            "title": "Install Temperature Monitoring System",
                            "description": "Early warning systems can optimize protection timing",
                            "potential_savings": 200.0,
                            "carbon_reduction": 4.0,
                        }
                    )

        elif event.type == "DR":  # Drought
            recommendations.append(
                {
                    "type": "resilience",
                    "title": "Install Drip Irrigation",
                    "description": "Reduce water usage by 50% during drought conditions",
                    "potential_savings": 500.0,
                    "carbon_reduction": 10.0,
                }
            )

        elif event.type == "HL":  # Hailstorm
            recommendations.append(
                {
                    "type": "protection",
                    "title": "Install Hail Netting",
                    "description": "Reduce crop damage by 80-90% in future hail events",
                    "potential_savings": 2000.0,
                    "carbon_reduction": 50.0,
                }
            )
            if hasattr(event, "diameter"):
                diameter = self._extract_numeric_value(event.diameter, default=1.0)
                if diameter > 20:  # Large hail
                    recommendations.append(
                        {
                            "type": "insurance",
                            "title": "Review Crop Insurance Coverage",
                            "description": "Large hail events suggest need for comprehensive coverage",
                            "potential_savings": 5000.0,
                            "carbon_reduction": 0.0,
                        }
                    )

        elif event.type == "HT":  # High temperatures
            recommendations.append(
                {
                    "type": "cooling",
                    "title": "Implement Shade Netting",
                    "description": "Reduce heat stress and water evaporation by 30%",
                    "potential_savings": 400.0,
                    "carbon_reduction": 8.0,
                }
            )

        elif event.type in ["TS", "HW"]:  # Tropical storm, High winds
            recommendations.append(
                {
                    "type": "structural",
                    "title": "Install Windbreaks",
                    "description": "Reduce wind damage and soil erosion",
                    "potential_savings": 800.0,
                    "carbon_reduction": 15.0,
                }
            )

        elif event.type in ["HH", "LH"]:  # Humidity issues
            recommendations.append(
                {
                    "type": "environmental",
                    "title": "Optimize Microclimate Management",
                    "description": "Proper spacing and airflow can reduce humidity-related issues",
                    "potential_savings": 300.0,
                    "carbon_reduction": 5.0,
                }
            )

        return recommendations

    def _generate_equipment_recommendations(
        self, event, emissions: float, cost: float, equipment_data: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """Generate recommendations for equipment events"""
        recommendations = []

        if event.type == "FC" and float(event.fuel_amount or 0) > 20:  # High fuel consumption
            recommendations.append(
                {
                    "type": "fuel_efficiency",
                    "title": "Consider Precision Agriculture",
                    "description": "GPS guidance can reduce fuel consumption by 10-15%",
                    "potential_savings": cost * 0.12,
                    "carbon_reduction": emissions * 0.12,
                }
            )

        if event.type in ["MA", "RE"]:
            recommendations.append(
                {
                    "type": "maintenance",
                    "title": "Preventive Maintenance Schedule",
                    "description": "Regular maintenance reduces breakdowns and improves efficiency",
                    "potential_savings": cost * 0.2,
                    "carbon_reduction": 2.0,
                }
            )

        return recommendations

    def _generate_soil_recommendations(self, event, emissions: float) -> List[Dict[str, Any]]:
        """Generate recommendations for soil management events"""
        recommendations = []

        if event.type == "TI":  # Tillage
            recommendations.append(
                {
                    "type": "conservation",
                    "title": "Consider No-Till Practices",
                    "description": "No-till farming can sequester 0.5-1.5 tons CO2e per hectare per year",
                    "potential_savings": 0.0,
                    "carbon_reduction": 10.0,
                }
            )

        if event.type == "ST" and float(event.soil_ph or 0) < 6.0:
            recommendations.append(
                {
                    "type": "soil_health",
                    "title": "pH Adjustment Needed",
                    "description": "Optimal pH improves nutrient efficiency and reduces fertilizer needs",
                    "potential_savings": 200.0,
                    "carbon_reduction": 5.0,
                }
            )

        return recommendations

    def _generate_business_recommendations(
        self, event, emissions: float, business_data: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """Generate recommendations for business events"""
        recommendations = []

        if event.type == "HS":
            recommendations.append(
                {
                    "type": "logistics",
                    "title": "Optimize Transportation",
                    "description": "Consolidate shipments to reduce transportation emissions",
                    "potential_savings": 100.0,
                    "carbon_reduction": emissions * 0.3,
                }
            )

        if event.type == "CE":
            recommendations.append(
                {
                    "type": "certification",
                    "title": "Expand Carbon Credit Programs",
                    "description": "Additional sustainable practices can generate more carbon credits",
                    "potential_savings": 1000.0,
                    "carbon_reduction": 20.0,
                }
            )

        return recommendations

    def _generate_pest_recommendations(self, event, emissions: float) -> List[Dict[str, Any]]:
        """Generate recommendations for pest management events"""
        recommendations = []

        if event.type == "SC" and event.pest_pressure_level == "High":
            recommendations.append(
                {
                    "type": "ipm",
                    "title": "Implement Biological Control",
                    "description": "Beneficial insects can reduce pesticide use by 30-50%",
                    "potential_savings": 300.0,
                    "carbon_reduction": 5.0,
                }
            )

        if event.type == "IP":
            recommendations.append(
                {
                    "type": "monitoring",
                    "title": "Expand IPM Monitoring",
                    "description": "Regular monitoring can prevent pest outbreaks and reduce treatments",
                    "potential_savings": 500.0,
                    "carbon_reduction": 8.0,
                }
            )

        return recommendations

    def _get_or_create_carbon_source(self, event) -> "CarbonSource":
        """
        Get or create a CarbonSource for the given event type.
        """
        # Named by (kind, code), not by code alone: event codes repeat across tables. Until
        # 2026-11-05 the map was keyed by code, so a pest beneficial release ("BR") was filed under
        # "Equipment Breakdown" (whose code is "BD"), and equipment maintenance ("MN") fell through
        # to "MN Activity". Known names are kept so existing sources keep their buckets; any other
        # code is named by the model's own label for it.
        from history.taxonomy import kind_of

        from ..models import CarbonSource

        kind = kind_of(event).slug
        code = getattr(event, "type", None)
        source_mapping = {
            ("chemical", "FE"): "Fertilizer Application",
            ("chemical", "PE"): "Pesticide Application",
            ("chemical", "HE"): "Herbicide Application",
            ("chemical", "FU"): "Fungicide Application",
            ("production", "IR"): "Irrigation",
            ("production", "HA"): "Harvesting",
            ("production", "PL"): "Planting",
            ("production", "PR"): "Pruning",
            ("equipment", "FC"): "Fuel Consumption",
            ("equipment", "MN"): "Equipment Maintenance",
            ("equipment", "RE"): "Equipment Repair",
            ("equipment", "CA"): "Equipment Calibration",
            ("equipment", "BD"): "Equipment Breakdown",
        }
        label = event.get_type_display() if code and hasattr(event, "get_type_display") else kind.title()
        source_name = source_mapping.get((kind, code), str(label))

        source, created = CarbonSource.objects.get_or_create(
            name=source_name,
            defaults={
                "category": "agricultural_activity",
                "description": f"Carbon emissions from {source_name.lower()}",
                "usda_factors_based": True,
                "verification_status": "factors_verified",
            },
        )

        return source

    def _classify_general_event_type(self, event_description: str, event_type: str) -> str:
        """
        Classify general event type based on description and type for appropriate emission factor selection.
        """
        description_lower = event_description.lower()
        type_lower = event_type.lower() if event_type else ""

        # Check for specific activity patterns in description
        if any(keyword in description_lower for keyword in ["visit", "inspection", "consultation", "meeting"]):
            return "farm_visit"
        elif any(keyword in description_lower for keyword in ["training", "workshop", "education", "learning"]):
            return "training_session"
        elif any(keyword in description_lower for keyword in ["document", "record", "note", "observation", "report"]):
            return "documentation"
        elif any(keyword in description_lower for keyword in ["scout", "monitor", "check", "survey", "assess"]):
            # Note: These should ideally be pest management events, but if they're general events, treat as documentation
            return "documentation"
        else:
            # Default to documentation for unknown general events
            return "documentation"

    def _generate_general_recommendations(
        self, event, base_emissions: float, general_event_type: str
    ) -> List[Dict[str, Any]]:
        """
        Generate recommendations for general events based on event type and emissions.
        """
        recommendations = []

        if general_event_type == "farm_visit" and base_emissions > 5.0:
            recommendations.append(
                {
                    "type": "efficiency",
                    "title": "Combine Farm Visits",
                    "description": "Schedule multiple activities in single visits to reduce transportation emissions",
                    "potential_savings": 50.0,
                    "carbon_reduction": 2.0,
                }
            )
        elif general_event_type == "training_session":
            recommendations.append(
                {
                    "type": "digitization",
                    "title": "Virtual Training Options",
                    "description": "Consider virtual training sessions to reduce travel-related emissions",
                    "potential_savings": 100.0,
                    "carbon_reduction": 5.0,
                }
            )
        elif general_event_type == "documentation" and base_emissions > 1.0:
            recommendations.append(
                {
                    "type": "efficiency",
                    "title": "Digital Documentation",
                    "description": "Use mobile apps and cloud storage to reduce paper usage and streamline record keeping",
                    "potential_savings": 25.0,
                    "carbon_reduction": 0.5,
                }
            )

        return recommendations
