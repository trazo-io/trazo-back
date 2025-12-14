# Migration to add application fuel tracking fields to ChemicalEvent
# Enables tracking of fuel consumed by application equipment (sprayers, spreaders, etc.)
# Critical for accurate carbon calculations: application fuel often equals/exceeds manufacturing emissions

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0127_normalize_equipment_event_fuel_type"),
    ]

    operations = [
        # ChemicalEvent: Add application_fuel_type field for EPA emission factor selection
        migrations.AddField(
            model_name="chemicalevent",
            name="application_fuel_type",
            field=models.CharField(
                max_length=30,
                choices=[
                    ("diesel", "Diesel"),
                    ("gasoline", "Gasoline"),
                    ("electric", "Electric"),
                    ("propane", "Propane"),
                    ("natural_gas", "Natural Gas"),
                    ("biodiesel", "Biodiesel"),
                    ("none", "No Fuel / Manual"),
                ],
                blank=True,
                default="",
                help_text="Fuel type for application equipment (EPA emission factor selection)",
            ),
        ),
        # ChemicalEvent: Add application_fuel_consumed field
        migrations.AddField(
            model_name="chemicalevent",
            name="application_fuel_consumed",
            field=models.DecimalField(
                decimal_places=2,
                max_digits=10,
                blank=True,
                null=True,
                help_text="Fuel consumed by application equipment (sprayer, spreader, etc.)",
            ),
        ),
        # ChemicalEvent: Add application_fuel_unit field
        migrations.AddField(
            model_name="chemicalevent",
            name="application_fuel_unit",
            field=models.CharField(
                max_length=10,
                choices=[
                    ("L", "Liters"),
                    ("gal", "Gallons"),
                    ("kg", "Kilograms"),
                    ("kWh", "Kilowatt-hours"),
                ],
                blank=True,
                default="L",
                help_text="Fuel unit for application equipment",
            ),
        ),
    ]
