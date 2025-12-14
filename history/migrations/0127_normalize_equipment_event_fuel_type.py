# Data migration to normalize existing EquipmentEvent fuel_type values to standardized choices
# Handles variant spellings and capitalization from user input

from django.db import migrations


def normalize_fuel_types(apps, schema_editor):
    """Normalize fuel_type values to standardized choices"""
    EquipmentEvent = apps.get_model('history', 'EquipmentEvent')

    # Mapping of old values to new standardized values
    normalizations = {
        'renewable_diesel': 'biodiesel',    # Handle variant name
        'bio-diesel': 'biodiesel',          # Handle hyphenated variant
        'Bio-diesel': 'biodiesel',          # Handle capitalized variant
        'Ultra-Low Sulfur Diesel': 'diesel', # Handle ultra-low sulfur variant
        'DIESEL': 'diesel',                 # Handle uppercase variant
        'Diesel': 'diesel',                 # Handle capitalized variant
        'GASOLINE': 'gasoline',             # Handle uppercase variant
        'Gasoline': 'gasoline',             # Handle capitalized variant
        'ELECTRIC': 'electric',             # Handle uppercase variant
        'Electric': 'electric',             # Handle capitalized variant
        'PROPANE': 'propane',               # Handle uppercase variant
        'Propane': 'propane',               # Handle capitalized variant
        'NATURAL_GAS': 'natural_gas',       # Handle underscore variant
        'BIODIESEL': 'biodiesel',           # Handle uppercase variant
        'Biodiesel': 'biodiesel',           # Handle capitalized variant
    }

    # Apply normalizations
    for old_value, new_value in normalizations.items():
        EquipmentEvent.objects.filter(fuel_type=old_value).update(fuel_type=new_value)

    # Empty strings are left as-is (they're the default)
    # Null values are left as-is (blank=True allows null)


def reverse_fuel_type_normalization(apps, schema_editor):
    """Reverse normalization - not typically needed but provided for completeness"""
    # We can't reliably reverse this since multiple old values map to one new value
    # (e.g., 'renewable_diesel' and 'bio-diesel' both map to 'biodiesel')
    # So we just pass and document that reversal requires a backup
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0126_standardize_fuel_type_choices"),
    ]

    operations = [
        migrations.RunPython(normalize_fuel_types, reverse_fuel_type_normalization),
    ]
