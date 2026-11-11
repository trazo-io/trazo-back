import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .emission_factors import emission_factors

logger = logging.getLogger(__name__)


class CarbonFootprintCalculator:
    """Service for calculating carbon footprints based on various inputs"""

    def __init__(self):
        # Emission factors from the centralized registry; provenance is per factor there
        self.usda_factors = {
            "fertilizer": {
                "nitrogen": emission_factors.get_fertilizer_factor("nitrogen")["value"],
                "phosphorus": emission_factors.get_fertilizer_factor("phosphorus")["value"],
                "potassium": emission_factors.get_fertilizer_factor("potassium")["value"],
            },
            "fuel": {
                "diesel": emission_factors.get_fuel_factor("diesel")["value"],
                "gasoline": emission_factors.get_fuel_factor("gasoline")["value"],
                "propane": emission_factors.get_fuel_factor("propane")["value"],
            },
            "electricity": {
                "grid": emission_factors.get_electricity_factor("grid")["value"],
                "solar": emission_factors.get_electricity_factor("solar")["value"],
                "wind": emission_factors.get_electricity_factor("wind")["value"],
            },
            "water": {
                "irrigation": emission_factors.get_water_factor("irrigation")["value"],
                "pumping": emission_factors.get_water_factor("pumping")["value"],
            },
        }

        # Log the standardization for audit purposes
        logger.debug(f"CarbonFootprintCalculator initialized with centralized factors v{emission_factors.VERSION}")
        logger.debug(f"Nitrogen factor: {self.usda_factors['fertilizer']['nitrogen']} kg CO2e per kg N")

    def calculate_farm_footprint(
        self, inputs: Dict[str, Any], crop_type: str, area: float, region: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculate total carbon footprint for a farm based on inputs

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
                "usda_factors_used": True,
            }

        except Exception as e:
            logger.error(f"Error calculating farm footprint: {str(e)}")
            raise

    def _calculate_fertilizer_emissions(self, fertilizer_data: Dict[str, Any]) -> float:
        """Calculate emissions from fertilizer use"""
        total_emissions = 0

        for nutrient, amount in fertilizer_data.items():
            if nutrient in self.usda_factors["fertilizer"]:
                total_emissions += amount * self.usda_factors["fertilizer"][nutrient]

        return total_emissions

    def _calculate_fuel_emissions(self, fuel_data: Dict[str, Any]) -> float:
        """Calculate emissions from fuel use"""
        total_emissions = 0

        for fuel_type, amount in fuel_data.items():
            if fuel_type in self.usda_factors["fuel"]:
                total_emissions += amount * self.usda_factors["fuel"][fuel_type]

        return total_emissions

    def _calculate_electricity_emissions(self, electricity_data: Dict[str, Any]) -> float:
        """Calculate emissions from electricity use"""
        total_emissions = 0

        for source, amount in electricity_data.items():
            if source in self.usda_factors["electricity"]:
                total_emissions += amount * self.usda_factors["electricity"][source]

        return total_emissions

    def _calculate_water_emissions(self, water_data: Dict[str, Any]) -> float:
        """Calculate emissions from water use"""
        total_emissions = 0

        for use_type, amount in water_data.items():
            if use_type in self.usda_factors["water"]:
                total_emissions += amount * self.usda_factors["water"][use_type]

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


class CarbonOffsetCalculator:
    """Service for calculating carbon offsets and related metrics."""

    def calculate_offset(self, amount: Decimal, price_per_ton: Decimal) -> Dict[str, Any]:
        """
        Calculate carbon offset details for a given amount and price.

        Args:
            amount: Amount of carbon to offset in tons
            price_per_ton: Price per ton of carbon offset

        Returns:
            dict: Calculation results including total cost and environmental impact
        """
        total_cost = amount * price_per_ton

        # Calculate environmental impact metrics
        impact_metrics = {
            "trees_equivalent": float(amount * Decimal("0.5")),  # Assuming 0.5 tons per tree per year
            "cars_equivalent": float(amount * Decimal("0.4")),  # Assuming 0.4 tons per car per year
            "homes_equivalent": float(amount * Decimal("0.3")),  # Assuming 0.3 tons per home per year
        }

        return {
            "amount": float(amount),
            "price_per_ton": float(price_per_ton),
            "total_cost": float(total_cost),
            "impact_metrics": impact_metrics,
        }

    def calculate_project_capacity(self, total_capacity: Decimal, available_capacity: Decimal) -> Dict[str, Any]:
        """
        Calculate project capacity metrics.

        Args:
            total_capacity: Total capacity of the project in tons
            available_capacity: Available capacity in tons

        Returns:
            dict: Capacity metrics including utilization percentage
        """
        utilized_capacity = total_capacity - available_capacity
        utilization_percentage = (utilized_capacity / total_capacity) * 100 if total_capacity > 0 else 0

        return {
            "total_capacity": float(total_capacity),
            "available_capacity": float(available_capacity),
            "utilized_capacity": float(utilized_capacity),
            "utilization_percentage": float(utilization_percentage),
        }

    def get_recommendations(self, carbon_footprint: Decimal) -> List[Dict[str, Any]]:
        """
        Get recommendations for carbon offset projects based on carbon footprint.

        Args:
            carbon_footprint: Total carbon footprint in tons

        Returns:
            list: List of recommended projects with details
        """
        recommendations = []

        # Example recommendation logic
        if carbon_footprint > Decimal("100"):
            recommendations.append(
                {
                    "type": "reforestation",
                    "priority": "high",
                    "description": "Consider investing in large-scale reforestation projects",
                    "estimated_impact": float(carbon_footprint * Decimal("0.7")),
                }
            )

        if carbon_footprint > Decimal("50"):
            recommendations.append(
                {
                    "type": "renewable_energy",
                    "priority": "medium",
                    "description": "Support renewable energy projects",
                    "estimated_impact": float(carbon_footprint * Decimal("0.5")),
                }
            )

        recommendations.append(
            {
                "type": "conservation",
                "priority": "low",
                "description": "Contribute to conservation efforts",
                "estimated_impact": float(carbon_footprint * Decimal("0.3")),
            }
        )

        return recommendations


# Create singleton instance
calculator = CarbonOffsetCalculator()
