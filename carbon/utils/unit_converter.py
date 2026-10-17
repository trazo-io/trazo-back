"""
Unit Conversion Utility for Agricultural Carbon Calculations
===========================================================

CRITICAL: Ensures accurate carbon calculations by handling all unit conversions
used in agricultural production events.

Source Standards:
- EPA Greenhouse Gas Emission Factors (40 CFR Part 98)
- USDA Agricultural Research Service Standards
- International System of Units (SI)

Author: Claude Code
Last Updated: 2025-10-07
"""

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class UnitConversionError(Exception):
    """Raised when unit conversion fails"""

    pass


class UnitConverter:
    """
    Comprehensive unit conversion system for agricultural carbon calculations.

    DESIGN PRINCIPLES:
    1. Accuracy: Use precise conversion factors from official sources
    2. Transparency: Log all conversions for audit trail
    3. Validation: Validate inputs and detect invalid combinations
    4. Extensibility: Easy to add new units and conversion factors
    """

    # AREA CONVERSION FACTORS (to hectares as base unit)
    AREA_CONVERSIONS = {
        "hectares": 1.0,
        "ha": 1.0,
        "acres": 2.47105,  # 1 hectare = 2.47105 acres
        "ac": 2.47105,
        "square_meters": 10000.0,  # 1 hectare = 10,000 m²
        "sqm": 10000.0,
        "m2": 10000.0,
        "square_kilometers": 100.0,  # 1 hectare = 0.01 km²
        "sqkm": 100.0,
        "km2": 100.0,
    }

    # VOLUME CONVERSION FACTORS (to liters as base unit)
    VOLUME_CONVERSIONS = {
        "liters": 1.0,
        "l": 1.0,
        "gallons": 3.78541,  # 1 gallon = 3.78541 liters
        "gal": 3.78541,
        "us_gallons": 3.78541,
        "imperial_gallons": 4.54609,  # Imperial gallon
        "milliliters": 0.001,  # 1 liter = 1000 ml
        "ml": 0.001,
        # UNIT_VOLUME `fl_oz` (2026-10-17). Without it a fluid-ounce application fell through
        # to the "unknown unit, assuming liters" branch and 36 fl oz was read as 36 L.
        "fl_oz": 0.0295735295625,
        "cubic_meters": 1000.0,  # 1 m³ = 1000 liters
        "m3": 1000.0,
    }

    # MASS CONVERSION FACTORS (to kilograms as base unit)
    MASS_CONVERSIONS = {
        "kilograms": 1.0,
        "kg": 1.0,
        "tonnes": 1000.0,  # 1 tonne = 1000 kg
        "t": 1000.0,
        "metric_tons": 1000.0,
        "pounds": 0.453592,  # 1 pound = 0.453592 kg
        "lbs": 0.453592,
        "lb": 0.453592,
        "ounces": 0.0283495,  # 1 ounce = 0.0283495 kg
        "oz": 0.0283495,
        "oz_wt": 0.0283495,  # UNIT_VOLUME `oz_wt` (2026-10-17), the explicit weight ounce
        "grams": 0.001,  # 1 gram = 0.001 kg
        "g": 0.001,
    }

    # FUEL-SPECIFIC CONVERSIONS (considering density)
    FUEL_CONVERSIONS = {
        "diesel": {
            "density_kg_per_liter": 0.832,  # Average diesel density
            "energy_content_mj_per_kg": 43.1,  # MJ/kg for diesel
        },
        "gasoline": {
            "density_kg_per_liter": 0.745,  # Average gasoline density
            "energy_content_mj_per_kg": 44.3,  # MJ/kg for gasoline
        },
        "biodiesel": {
            "density_kg_per_liter": 0.88,  # Biodiesel density
            "energy_content_mj_per_kg": 37.8,  # MJ/kg for biodiesel
        },
    }

    @classmethod
    def convert_area(cls, value: float, from_unit: str, to_unit: str = "hectares") -> Tuple[float, str]:
        """
        Convert area between different units.

        Args:
            value: Numeric value to convert
            from_unit: Source unit (e.g., 'acres', 'hectares')
            to_unit: Target unit (default: 'hectares')

        Returns:
            Tuple of (converted_value, audit_message)

        Raises:
            UnitConversionError: If conversion is not possible
        """
        try:
            from_unit = from_unit.lower().strip()
            to_unit = to_unit.lower().strip()

            if from_unit not in cls.AREA_CONVERSIONS:
                raise UnitConversionError(f"Unsupported area unit: {from_unit}")
            if to_unit not in cls.AREA_CONVERSIONS:
                raise UnitConversionError(f"Unsupported target area unit: {to_unit}")

            # Convert to base unit (hectares) then to target unit
            value_in_hectares = value / cls.AREA_CONVERSIONS[from_unit]
            converted_value = value_in_hectares * cls.AREA_CONVERSIONS[to_unit]

            # Round to 6 decimal places for precision
            converted_value = float(Decimal(str(converted_value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))

            audit_msg = f"Area: {value} {from_unit} → {converted_value} {to_unit}"
            logger.info(f"Unit conversion: {audit_msg}")

            return converted_value, audit_msg

        except Exception as e:
            raise UnitConversionError(f"Area conversion failed: {e}")

    @classmethod
    def convert_volume(cls, value: float, from_unit: str, to_unit: str = "liters") -> Tuple[float, str]:
        """
        Convert volume between different units.

        Args:
            value: Numeric value to convert
            from_unit: Source unit (e.g., 'gallons', 'liters')
            to_unit: Target unit (default: 'liters')

        Returns:
            Tuple of (converted_value, audit_message)
        """
        try:
            from_unit = from_unit.lower().strip()
            to_unit = to_unit.lower().strip()

            if from_unit not in cls.VOLUME_CONVERSIONS:
                raise UnitConversionError(f"Unsupported volume unit: {from_unit}")
            if to_unit not in cls.VOLUME_CONVERSIONS:
                raise UnitConversionError(f"Unsupported target volume unit: {to_unit}")

            # Convert to base unit (liters) then to target unit
            value_in_liters = value * cls.VOLUME_CONVERSIONS[from_unit]
            converted_value = value_in_liters / cls.VOLUME_CONVERSIONS[to_unit]

            converted_value = float(Decimal(str(converted_value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))

            audit_msg = f"Volume: {value} {from_unit} → {converted_value} {to_unit}"
            logger.info(f"Unit conversion: {audit_msg}")

            return converted_value, audit_msg

        except Exception as e:
            raise UnitConversionError(f"Volume conversion failed: {e}")

    @classmethod
    def convert_mass(cls, value: float, from_unit: str, to_unit: str = "kilograms") -> Tuple[float, str]:
        """
        Convert mass between different units.

        Args:
            value: Numeric value to convert
            from_unit: Source unit (e.g., 'pounds', 'tonnes', 'kg')
            to_unit: Target unit (default: 'kilograms')

        Returns:
            Tuple of (converted_value, audit_message)
        """
        try:
            from_unit = from_unit.lower().strip()
            to_unit = to_unit.lower().strip()

            if from_unit not in cls.MASS_CONVERSIONS:
                raise UnitConversionError(f"Unsupported mass unit: {from_unit}")
            if to_unit not in cls.MASS_CONVERSIONS:
                raise UnitConversionError(f"Unsupported target mass unit: {to_unit}")

            # Convert to base unit (kg) then to target unit
            value_in_kg = value * cls.MASS_CONVERSIONS[from_unit]
            converted_value = value_in_kg / cls.MASS_CONVERSIONS[to_unit]

            converted_value = float(Decimal(str(converted_value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))

            audit_msg = f"Mass: {value} {from_unit} → {converted_value} {to_unit}"
            logger.info(f"Unit conversion: {audit_msg}")

            return converted_value, audit_msg

        except Exception as e:
            raise UnitConversionError(f"Mass conversion failed: {e}")

    @classmethod
    def convert_fuel_to_gallons(cls, value: float, from_unit: str, fuel_type: str = "diesel") -> Tuple[float, str]:
        """
        Convert fuel quantity to gallons for EPA emission factor calculations.

        CRITICAL: EPA emission factors are specified in kg_CO2_per_gallon,
        so all fuel must be converted to gallons for accurate calculations.

        Args:
            value: Numeric value to convert
            from_unit: Source unit ('liters', 'gallons', 'kg')
            fuel_type: Type of fuel for density calculations ('diesel', 'gasoline')

        Returns:
            Tuple of (gallons, audit_message)
        """
        try:
            from_unit = from_unit.lower().strip()
            fuel_type = fuel_type.lower().strip()

            if fuel_type not in cls.FUEL_CONVERSIONS:
                fuel_type = "diesel"  # Default to diesel

            fuel_props = cls.FUEL_CONVERSIONS[fuel_type]

            if from_unit in ["gallons", "gal", "us_gallons"]:
                converted_value = value
                audit_msg = f"Fuel: {value} {from_unit} (no conversion needed)"

            elif from_unit in ["liters", "l"]:
                # Convert liters to gallons
                converted_value = value / 3.78541
                audit_msg = f"Fuel: {value} L → {converted_value:.3f} gallons"

            elif from_unit in ["kilograms", "kg"]:
                # Convert kg to liters using fuel density, then to gallons
                liters = value / fuel_props["density_kg_per_liter"]
                converted_value = liters / 3.78541
                audit_msg = f"Fuel: {value} kg → {liters:.3f} L → {converted_value:.3f} gallons ({fuel_type})"

            else:
                raise UnitConversionError(f"Unsupported fuel unit: {from_unit}")

            converted_value = float(Decimal(str(converted_value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))

            logger.info(f"Fuel conversion: {audit_msg}")
            return converted_value, audit_msg

        except Exception as e:
            raise UnitConversionError(f"Fuel conversion failed: {e}")

    @classmethod
    def normalize_unit_name(cls, unit_string: str) -> str:
        """
        Normalize unit names to standard forms.

        Args:
            unit_string: Raw unit string from user input

        Returns:
            Standardized unit name
        """
        if not unit_string:
            return ""

        unit = unit_string.lower().strip()

        # Area units
        if unit in ["hectare", "hectares", "ha"]:
            return "hectares"
        elif unit in ["acre", "acres", "ac"]:
            return "acres"
        elif unit in ["square_meters", "sq_m", "m2", "sqm"]:
            return "square_meters"

        # Volume units
        elif unit in ["liter", "liters", "l"]:
            return "liters"
        elif unit in ["gallon", "gallons", "gal"]:
            return "gallons"

        # Mass units
        elif unit in ["kilogram", "kilograms", "kg"]:
            return "kilograms"
        elif unit in ["tonne", "tonnes", "t", "metric_ton"]:
            return "tonnes"
        elif unit in ["pound", "pounds", "lb", "lbs"]:
            return "pounds"
        elif unit in ["ounce", "ounces", "oz"]:
            return "ounces"
        elif unit in ["gram", "grams", "g"]:
            return "grams"

        # Volume units (additional)
        elif unit in ["milliliter", "milliliters", "ml"]:
            return "ml"

        return unit

    @classmethod
    def is_mass_unit(cls, unit: str) -> bool:
        """Check if a unit string represents a mass measurement."""
        normalized = cls.normalize_unit_name(unit.lower().strip()) if unit else ""
        return normalized in cls.MASS_CONVERSIONS

    @classmethod
    def is_volume_unit(cls, unit: str) -> bool:
        """Check if a unit string represents a volume measurement."""
        normalized = cls.normalize_unit_name(unit.lower().strip()) if unit else ""
        return normalized in cls.VOLUME_CONVERSIONS

    @classmethod
    def validate_unit_combination(cls, value: float, unit: str, measurement_type: str) -> bool:
        """
        Validate that a unit is appropriate for the measurement type.

        Args:
            value: The numeric value
            unit: The unit string
            measurement_type: 'area', 'volume', 'mass', or 'fuel'

        Returns:
            True if valid combination
        """
        normalized_unit = cls.normalize_unit_name(unit)

        if measurement_type == "area":
            return normalized_unit in cls.AREA_CONVERSIONS
        elif measurement_type == "volume":
            return normalized_unit in cls.VOLUME_CONVERSIONS
        elif measurement_type == "mass":
            return normalized_unit in cls.MASS_CONVERSIONS
        elif measurement_type == "fuel":
            return normalized_unit in ["liters", "gallons", "kilograms"]

        return False
