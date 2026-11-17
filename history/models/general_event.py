"""General activities."""

from django.db import models

from .common_event import CommonEvent


class GeneralEvent(CommonEvent):
    name = models.CharField(max_length=150, help_text="Event name")
    observation = models.TextField(blank=True, null=True)

    # Activity details for comprehensive farm transparency
    activity_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Type of activity performed (e.g., Farm Maintenance, Equipment Setup)",
    )
    activity_name = models.CharField(
        max_length=200, blank=True, null=True, help_text="Specific name or description of the activity"
    )
    duration = models.CharField(
        max_length=50, blank=True, null=True, help_text="Duration of the activity (e.g., '2 hours', '1 day')"
    )
    people_involved = models.PositiveIntegerField(
        blank=True, null=True, help_text="Number of people involved in the activity"
    )

    # Contamination incident reporting — § 205.400(f)(1) + § 205.272.
    #
    # 🔴 Corrected 2026-08-15. This cited § 205.201(b), which is the clause permitting a
    # producer to SUBSTITUTE another government programme's plan for the OSP — nothing to do
    # with contamination. The notification duty is § 205.400(f)(1) ("immediately notify the
    # certifying agent concerning any... application, including drift, of a prohibited
    # substance"); the prevention standard is § 205.272. The certifier packet already uses
    # both correctly; the model and the registry never followed.
    CONTAMINATION_SOURCE_CHOICES = [
        ("spray_drift", "Spray Drift from Adjacent Land"),
        ("equipment", "Equipment Contamination"),
        ("storage", "Storage Commingling"),
        ("water", "Water Contamination"),
        ("soil", "Soil Contamination"),
        ("other", "Other"),
    ]
    is_contamination_incident = models.BooleanField(
        default=False,
        help_text="Whether this event documents a contamination incident (7 CFR 205.400(f)(1) / § 205.272)",
    )
    contamination_source = models.CharField(
        max_length=30,
        choices=CONTAMINATION_SOURCE_CHOICES,
        blank=True,
        null=True,
        help_text="Source of contamination (spray drift, equipment, storage, etc.)",
    )
    contamination_affected_area = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Area affected by contamination in acres",
    )
    corrective_action_taken = models.TextField(
        blank=True,
        null=True,
        help_text="Corrective actions taken in response to contamination incident",
    )
    corrective_action_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date corrective action was completed",
    )
    certifier_notified = models.BooleanField(
        default=False,
        help_text="Whether the certifying agent was notified of the contamination incident",
    )
    certifier_notification_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date certifier was notified of contamination incident",
    )

    extra_data = models.JSONField(blank=True, null=True)
