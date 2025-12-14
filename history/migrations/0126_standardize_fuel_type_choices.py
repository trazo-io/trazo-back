# Generated migration for standardizing fuel_type across event models
# Adds fuel_type with standardized EPA-verified choices to EquipmentEvent and SoilManagementEvent
# Also adds kWh to fuel_unit choices for both models

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0125_alter_productionevent_fuel_unit"),
    ]

    operations = [
        # EquipmentEvent: Change fuel_type from unconstrained CharField to standardized choices
        # Note: max_length=30 to accommodate existing values like "Ultra-Low Sulfur Diesel" (23 chars)
        migrations.AlterField(
            model_name="equipmentevent",
            name="fuel_type",
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
                help_text="Fuel type for EPA emission factor calculation",
            ),
        ),
        # EquipmentEvent: Add kWh to fuel_unit choices
        migrations.AlterField(
            model_name="equipmentevent",
            name="fuel_unit",
            field=models.CharField(
                max_length=10,
                choices=[
                    ("L", "Liters"),
                    ("gal", "Gallons"),
                    ("kg", "Kilograms"),
                    ("kWh", "Kilowatt-hours"),
                ],
                default="L",
                blank=True,
                help_text="Fuel unit",
            ),
        ),
        # SoilManagementEvent: Add kWh to fuel_unit choices
        migrations.AlterField(
            model_name="soilmanagementevent",
            name="fuel_unit",
            field=models.CharField(
                max_length=10,
                choices=[
                    ("L", "Liters"),
                    ("gal", "Gallons"),
                    ("kg", "Kilograms"),
                    ("kWh", "Kilowatt-hours"),
                ],
                default="L",
                blank=True,
                help_text="Fuel unit",
            ),
        ),
        # SoilManagementEvent: Add fuel_type field
        migrations.AddField(
            model_name="soilmanagementevent",
            name="fuel_type",
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
                help_text="Fuel type for EPA emission factor calculation",
            ),
        ),
    ]
