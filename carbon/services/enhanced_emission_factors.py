"""
Per-activity defaults for general events (a visit, a training day, an hour of paperwork).

Every value here is a Trazo estimate: no agency publishes these numbers, and each `source` says so.
Until 2026-11-22 the sources read like citations ("USDA Farm Visit Transportation Survey (2024)",
"EPA Training Program Carbon Assessment (2024)", "EPA Digital Work Carbon Assessment (2024)") that
no one could follow to a document. While the calculator wrote "USDA Agricultural Research Service"
over every figure, they never printed; once each figure kept its own source, they would have
(review of back #516, OV-FJ-C17). Six further tables of the same kind (pesticide, fungicide,
herbicide, soil, pest, business) and their four calculators had no caller and were deleted with
their invented citations.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

# The EPA 40 CFR Part 98 Table C-1 diesel factor (kg CO2 per gallon), the one published factor a
# general event can apply; `VerifiedEmissionFactors.EPA_DIESEL_FACTORS` holds its citation.
DIESEL_KG_CO2_PER_GALLON = 10.21
LITERS_PER_GALLON = 3.785


@dataclass
class EnhancedEmissionFactor:
    """A per-activity default and what it rests on."""

    value: float
    unit: str
    source: str
    confidence_level: float
    last_updated: str
    compound_specific: bool = False
    notes: Optional[str] = None


class EnhancedEmissionFactors:
    """Trazo estimates for general events. None is a published factor."""

    GENERAL_FACTORS = {
        "farm_visit": EnhancedEmissionFactor(
            value=2.5,  # L fuel per visit (average round trip)
            unit="L_fuel_per_visit",
            source="Trazo estimate of fuel per farm visit (2.5 L round trip), priced with the EPA diesel factor",
            confidence_level=0.70,
            last_updated="2024-08-01",
            notes="Average transportation fuel for farm visits and consultations",
        ),
        "training_session": EnhancedEmissionFactor(
            value=8.5,  # kg CO2e per participant per day
            unit="kg_CO2e_per_participant_day",
            source="Trazo estimate of emissions per training participant-day",
            confidence_level=0.73,
            last_updated="2024-07-15",
            notes="Includes travel, facilities, materials, and catering emissions",
        ),
        "documentation": EnhancedEmissionFactor(
            value=0.25,  # kg CO2e per hour of documentation work
            unit="kg_CO2e_per_hour",
            source="Trazo estimate of emissions per hour of documentation work",
            confidence_level=0.80,
            last_updated="2024-09-10",
            notes="Computer use, cloud storage, and digital infrastructure",
        ),
    }

    @classmethod
    def calculate_general_event_emissions(
        cls, event_type: str, duration_hours: float = 1.0, participants: int = 1
    ) -> Dict[str, Any]:
        """Calculate general event emissions"""

        factor_key = event_type.lower().replace(" ", "_")
        if factor_key not in cls.GENERAL_FACTORS:
            factor_key = "documentation"  # Default

        emission_factor = cls.GENERAL_FACTORS[factor_key]

        if emission_factor.unit == "kg_CO2e_per_participant_day":
            co2e_kg = participants * (duration_hours / 8.0) * emission_factor.value
        elif emission_factor.unit == "L_fuel_per_visit":
            co2e_kg = (emission_factor.value / LITERS_PER_GALLON) * DIESEL_KG_CO2_PER_GALLON
        else:
            co2e_kg = duration_hours * emission_factor.value

        return {
            "co2e_kg": co2e_kg,
            "calculation_method": "general_event_specific",
            "emission_factor": emission_factor.value,
            "source": emission_factor.source,
            "confidence_level": emission_factor.confidence_level,
        }
