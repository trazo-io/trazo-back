"""
Shared choices constants for carbon app models.
Centralizes choice definitions to maintain DRY principle across event types.

Source: EPA 40 CFR Part 98, EPA eGRID 2023
Last Updated: 2025-12-11
"""

# EPA-verified fuel type choices
# Used across ProductionEvent, EquipmentEvent, SoilManagementEvent, ChemicalEvent
FUEL_TYPES = [
    ("diesel", "Diesel"),
    ("gasoline", "Gasoline"),
    ("electric", "Electric"),
    ("propane", "Propane"),
    ("natural_gas", "Natural Gas"),
    ("biodiesel", "Biodiesel"),
    ("none", "No Fuel / Manual"),
]

# Fuel type factors (kg CO₂e per unit) - Reference data for documentation
FUEL_TYPE_FACTORS = {
    "diesel": {"value": 10.21, "unit": "kg CO₂e/gallon", "source": "EPA 40 CFR Part 98"},
    "gasoline": {"value": 8.89, "unit": "kg CO₂e/gallon", "source": "EPA 40 CFR Part 98"},
    "electric": {"value": 0.39, "unit": "kg CO₂e/kWh", "source": "EPA eGRID 2023"},
    "propane": {"value": 5.74, "unit": "kg CO₂e/gallon", "source": "EPA 40 CFR Part 98"},
    "natural_gas": {"value": 0.0531, "unit": "kg CO₂e/cubic foot", "source": "EPA 40 CFR Part 98"},
    "biodiesel": {"value": 8.76, "unit": "kg CO₂e/gallon", "source": "EPA 40 CFR Part 98"},
    "none": {"value": 0.0, "unit": "kg CO₂e", "source": "Manual/no fuel"},
}
