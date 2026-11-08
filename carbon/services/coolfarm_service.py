import logging
from typing import Any, Dict, List, Optional

from .emission_factors import emission_factors

logger = logging.getLogger(__name__)


class CoolFarmService:
    """Service for calculating and managing farm carbon emissions."""

    def __init__(self):
        # Use centralized emission factors to ensure consistency
        self.emission_factors = {
            "fertilizer": {
                "nitrogen": emission_factors.get_fertilizer_factor("nitrogen")["value"],  # USDA-verified
                "phosphorus": emission_factors.get_fertilizer_factor("phosphorus")["value"],  # USDA-verified
                "potassium": emission_factors.get_fertilizer_factor("potassium")["value"],  # USDA-verified
            },
            "fuel": {
                "diesel": emission_factors.get_fuel_factor("diesel")["value"],  # EPA-verified
                "gasoline": emission_factors.get_fuel_factor("gasoline")["value"],  # EPA-verified
                "propane": 1.51,  # kg CO2e per liter (EPA 40 CFR Part 98: 5.72 kg/gal ÷ 3.785)
            },
            "electricity": {
                "grid": 0.4,  # kg CO2e per kWh (US average, EPA 2024)
                "solar": 0.0,  # kg CO2e per kWh
                "wind": 0.0,  # kg CO2e per kWh
            },
            "water": {
                "irrigation": 0.3,  # kg CO2e per m3 (research-based)
                "pumping": 0.2,  # kg CO2e per m3 (research-based)
            },
        }

        logger.info(
            f"CoolFarmService initialized with USDA-verified factors: N={self.emission_factors['fertilizer']['nitrogen']} kg CO2e/kg"
        )

    def calculate_farm_emissions(
        self, inputs: Dict[str, Any], crop_type: str, area: float, region: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculate total carbon emissions for a farm based on inputs.

        Args:
            inputs: Dictionary of input data (fertilizer, fuel, etc.)
            crop_type: Type of crop being grown
            area: Area in acres
            region: Optional region for more accurate calculations

        Returns:
            Dictionary containing total emissions and breakdown
        """
        try:
            total_emissions = 0
            breakdown = {}

            # Calculate fertilizer emissions
            if "fertilizer" in inputs:
                fertilizer_emissions = self._calculate_fertilizer_emissions(inputs["fertilizer"])
                total_emissions += fertilizer_emissions
                breakdown["fertilizer"] = fertilizer_emissions

            # Calculate fuel emissions
            if "fuel" in inputs:
                fuel_emissions = self._calculate_fuel_emissions(inputs["fuel"])
                total_emissions += fuel_emissions
                breakdown["fuel"] = fuel_emissions

            # Calculate electricity emissions
            if "electricity" in inputs:
                electricity_emissions = self._calculate_electricity_emissions(inputs["electricity"])
                total_emissions += electricity_emissions
                breakdown["electricity"] = electricity_emissions

            # Calculate water-related emissions
            if "water" in inputs:
                water_emissions = self._calculate_water_emissions(inputs["water"])
                total_emissions += water_emissions
                breakdown["water"] = water_emissions

            # Get industry benchmark if available
            benchmark = self._get_industry_benchmark(crop_type, region)

            # Generate recommendations
            recommendations = self._generate_recommendations(breakdown)

            return {
                "total_emissions": total_emissions,
                "emissions_per_acre": total_emissions / area,
                "breakdown": breakdown,
                "benchmark": benchmark,
                "recommendations": recommendations,
            }

        except Exception as e:
            logger.error(f"Error calculating farm emissions: {str(e)}")
            raise

    def _calculate_fertilizer_emissions(self, fertilizer_data: Dict[str, Any]) -> float:
        """Calculate emissions from fertilizer use"""
        total_emissions = 0

        for nutrient, amount in fertilizer_data.items():
            if nutrient in self.emission_factors["fertilizer"]:
                total_emissions += amount * self.emission_factors["fertilizer"][nutrient]

        return total_emissions

    def _calculate_fuel_emissions(self, fuel_data: Dict[str, Any]) -> float:
        """Calculate emissions from fuel use"""
        total_emissions = 0

        for fuel_type, amount in fuel_data.items():
            if fuel_type in self.emission_factors["fuel"]:
                total_emissions += amount * self.emission_factors["fuel"][fuel_type]

        return total_emissions

    def _calculate_electricity_emissions(self, electricity_data: Dict[str, Any]) -> float:
        """Calculate emissions from electricity use"""
        total_emissions = 0

        for source, amount in electricity_data.items():
            if source in self.emission_factors["electricity"]:
                total_emissions += amount * self.emission_factors["electricity"][source]

        return total_emissions

    def _calculate_water_emissions(self, water_data: Dict[str, Any]) -> float:
        """Calculate emissions from water use"""
        total_emissions = 0

        for use_type, amount in water_data.items():
            if use_type in self.emission_factors["water"]:
                total_emissions += amount * self.emission_factors["water"][use_type]

        return total_emissions

    def _get_industry_benchmark(self, crop_type: str, region: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get industry benchmark data for the crop type and region"""
        # NEVER: 2026-11-07 - CarbonBenchmark is retiring (it leaves the model in carbon migration
        # 0052): an industry average Trazo computed about itself, seeded with simulated company
        # counts sourced to USDA ARS. There is no benchmark to compare against.
        return None

    def _generate_recommendations(self, breakdown: Dict[str, float]) -> List[str]:
        """Recommendations from the emissions breakdown.

        NEVER: 2026-11-08 - the 0-100 efficiency score these were graded on was deleted with the
        rest of the retired score concept, and the "above the industry average" line with it.
        """
        recommendations = []

        # Specific recommendations based on emission sources
        if "fertilizer" in breakdown and breakdown["fertilizer"] > 0:
            recommendations.append("Consider using organic fertilizers or implementing precision agriculture")

        if "fuel" in breakdown and breakdown["fuel"] > 0:
            recommendations.append("Explore electric or hybrid equipment options")

        if "electricity" in breakdown and breakdown["electricity"] > 0:
            recommendations.append("Consider installing solar panels or switching to renewable energy")

        if "water" in breakdown and breakdown["water"] > 0:
            recommendations.append("Implement drip irrigation and water conservation practices")

        return recommendations


# Create singleton instance
coolfarm_service = CoolFarmService()
