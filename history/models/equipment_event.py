"""Equipment activities (read-only rows; new ones are refused)."""

from django.core.exceptions import ValidationError
from django.db import models

from carbon.choices import FUEL_TYPES
from common.field_registry import PRODUCTION_EFFICIENCY, UNIT_AREA, UNIT_FUEL

from .common_event import CommonEvent


class EquipmentEvent(CommonEvent):
    """Events related to equipment maintenance, repairs, and fuel consumption"""

    # Equipment event types
    MAINTENANCE = "MN"
    REPAIR = "RE"
    CALIBRATION = "CA"
    FUEL_CONSUMPTION = "FC"
    BREAKDOWN = "BD"
    INSPECTION = "EI"

    EQUIPMENT_TYPE_CHOICES = [
        (MAINTENANCE, "Maintenance"),
        (REPAIR, "Repair"),
        (CALIBRATION, "Calibration"),
        (FUEL_CONSUMPTION, "Fuel Consumption"),
        (BREAKDOWN, "Breakdown"),
        (INSPECTION, "Inspection"),
    ]

    type = models.CharField(max_length=2, choices=EQUIPMENT_TYPE_CHOICES, default=MAINTENANCE)
    equipment_name = models.CharField(max_length=100, blank=True)
    fuel_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fuel_type = models.CharField(
        max_length=30,
        choices=FUEL_TYPES,
        blank=True,
        default="",
        help_text="Fuel type for EPA emission factor calculation",
    )
    maintenance_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hours_used = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    area_covered = models.CharField(max_length=100, blank=True)
    extra_data = models.JSONField(blank=True, null=True)

    # New structured fields for better carbon calculations
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Event name")
    equipment_type_structured = models.CharField(
        max_length=30,
        choices=[
            ("tractor_small", "Small Tractor (<75 HP)"),
            ("tractor_medium", "Medium Tractor (75-150 HP)"),
            ("tractor_large", "Large Tractor (>150 HP)"),
            ("irrigation_pump", "Irrigation Pump"),
            ("harvester", "Combine Harvester"),
            ("sprayer", "Field Sprayer"),
            ("cultivator", "Cultivator/Plow"),
            ("transport", "Transport Vehicle"),
        ],
        null=True,
        blank=True,
        help_text="Structured equipment type for carbon calculations",
    )
    fuel_consumed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed (renamed from fuel_amount for clarity)",
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
        blank=True,
        help_text="Fuel unit",
    )
    hours_operated = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Hours operated (renamed from hours_used for clarity)",
    )
    area_worked = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Area worked in numeric format"
    )
    area_unit = models.CharField(
        max_length=10,
        choices=UNIT_AREA,
        default="acres",
        blank=True,
        help_text="Area unit",
    )
    operation_efficiency = models.CharField(
        max_length=10,
        choices=PRODUCTION_EFFICIENCY,
        default="normal",
        blank=True,
        help_text="Operation efficiency rating for carbon scoring",
    )
    observation = models.TextField(blank=True, null=True, help_text="Equipment event observations")

    def clean(self):
        """Model-level validation for equipment event values and business logic"""
        from django.core.exceptions import ValidationError

        errors = {}

        # Validate fuel_consumed is non-negative
        if self.fuel_consumed is not None and self.fuel_consumed < 0:
            errors["fuel_consumed"] = "Fuel consumed cannot be negative"

        # Validate hours_operated is non-negative
        if self.hours_operated is not None and self.hours_operated < 0:
            errors["hours_operated"] = "Hours operated cannot be negative"

        # Validate maintenance_cost is non-negative
        if self.maintenance_cost is not None and self.maintenance_cost < 0:
            errors["maintenance_cost"] = "Maintenance cost cannot be negative"

        # Validate area_worked is non-negative
        if self.area_worked is not None and self.area_worked < 0:
            errors["area_worked"] = "Area worked cannot be negative"

        # Business logic validations

        # If fuel consumption is provided, hours operated should also be provided for accuracy
        if self.fuel_consumed and self.fuel_consumed > 0 and not self.hours_operated:
            if "hours_operated" not in errors:
                errors["hours_operated"] = "Hours operated should be provided when fuel consumption is recorded"

        # Validate reasonable fuel efficiency (basic sanity check)
        if self.fuel_consumed and self.fuel_consumed > 0 and self.hours_operated and self.hours_operated > 0:
            fuel_per_hour = float(self.fuel_consumed) / float(self.hours_operated)

            # Reasonable fuel consumption: 0.5L/hr to 50L/hr (covers small pumps to large tractors)
            if fuel_per_hour > 50:
                errors["fuel_consumed"] = (
                    f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unreasonably high. Check values."
                )
            elif fuel_per_hour < 0.5:
                errors["fuel_consumed"] = (
                    f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unreasonably low. Check values."
                )

        # Validate reasonable operating hours (max 1000 hours for multi-day operations)
        if self.hours_operated and self.hours_operated > 1000:
            errors["hours_operated"] = "Hours operated cannot exceed 1000 hours per event"

        if errors:
            raise ValidationError(errors)

        super().clean()

    class Meta:
        verbose_name = "Equipment Event"
        verbose_name_plural = "Equipment Events"
