"""Pest management activities."""

from django.core.exceptions import ValidationError
from django.db import models

from carbon.choices import FUEL_TYPES
from common.field_registry import PRODUCTION_EFFICIENCY, UNIT_AREA, UNIT_FUEL

from .common_event import CommonEvent


class PestManagementEvent(CommonEvent):
    """Events related to pest monitoring, beneficial insect releases, and IPM practices"""

    # Pest management event types
    SCOUTING = "SC"
    BENEFICIAL_RELEASE = "BR"
    TRAP_MONITORING = "TM"
    PEST_IDENTIFICATION = "PI"
    THRESHOLD_ASSESSMENT = "TA"
    IPM_IMPLEMENTATION = "IP"
    # §E-4 — Cultural / sanitation control. 7 CFR 205.206(a) requires PREVENTIVE practices first,
    # and § 205.206(e) allows a substance only after those practices prove insufficient. Winter
    # sanitation is the preventive practice for navel orangeworm in a California orchard — and it
    # had no home in the model, so the single most common non-spray control an organic grower
    # performs was invisible to both the certifier and the consumer. UC Davis 2024 organic-almond
    # study: December mummy shake, blow and shred, custom-hired except the shredding.
    CULTURAL_CONTROL = "CU"

    PEST_TYPE_CHOICES = [
        (SCOUTING, "Scouting"),
        (BENEFICIAL_RELEASE, "Beneficial Release"),
        (TRAP_MONITORING, "Trap Monitoring"),
        (PEST_IDENTIFICATION, "Pest Identification"),
        (THRESHOLD_ASSESSMENT, "Threshold Assessment"),
        (IPM_IMPLEMENTATION, "IPM Implementation"),
        (CULTURAL_CONTROL, "Cultural / Sanitation Control"),
    ]

    CULTURAL_PRACTICE_CHOICES = [
        ("mummy_removal", "Mummy nut removal (hand poling)"),
        ("sanitation_shake", "Sanitation shake"),
        ("brush_shred", "Brush / mummy shredding"),
        ("pruning_removal", "Pruning removal and destruction"),
        ("field_sanitation", "Field sanitation / debris removal"),
        ("trap_crop", "Trap crop"),
    ]

    type = models.CharField(max_length=2, choices=PEST_TYPE_CHOICES, default=SCOUTING)
    cultural_practice = models.CharField(
        max_length=30,
        choices=CULTURAL_PRACTICE_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Preventive cultural practice performed (CU subtype). Evidence for § 205.206(a); "
            "documenting it is what lets § 205.206(e) justify any later substance application."
        ),
    )
    pest_species = models.CharField(max_length=200, blank=True)
    pest_pressure_level = models.CharField(max_length=50, blank=True)  # Low, Medium, High
    # F44 (2026-06): quantitative UC-IPM monitoring count — the actual data behind a scouting/trap
    # decision (e.g. "5 mites/leaf", "12% fruit infested", "8 moths/trap"). pest_pressure_level is
    # the qualitative summary; this is the measured number a certifier/PCA expects.
    monitoring_count = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Measured monitoring count (e.g. 5 mites per leaf) — SC/TM/PI",
    )
    monitoring_unit = models.CharField(
        max_length=20,
        choices=[
            ("per_leaf", "per leaf"),
            ("per_trap", "per trap"),
            ("per_tree", "per tree"),
            ("per_100_fruit", "per 100 fruit"),
            ("percent_infested", "% infested"),
            ("per_sample", "per sample"),
        ],
        blank=True,
        null=True,
        help_text="Unit for monitoring_count (UC IPM monitoring form vocabulary)",
    )
    beneficial_species = models.CharField(max_length=200, blank=True)
    release_quantity = models.CharField(max_length=100, blank=True)
    trap_count = models.IntegerField(null=True, blank=True)
    damage_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    # F17 fix (2026-06): nullable so "not assessed" (None) is distinct from "below threshold" (False).
    # An unanswered NOP 205.206(e) threshold question must NOT be fabricated into a definitive
    # "below threshold" record on the audit export.
    action_threshold_met = models.BooleanField(null=True, blank=True, default=None)
    ipm_strategy = models.TextField(blank=True)
    # The farmer's own words, kept apart from `description` — see the matching note on
    # SoilManagementEvent. Without this column a grower's trap-monitoring or beneficial-release
    # note had nowhere to live and never reached the consumer card.
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    beneficial_insects_used = models.CharField(
        max_length=20,
        choices=[
            ("yes", "Yes - Using Beneficial Insects"),
            ("no", "No"),
            ("planning", "Planning to Implement"),
        ],
        blank=True,
        null=True,
        help_text="Whether beneficial insects are used for pest control",
    )

    # Beneficial-release traceability (BR subtype) — NOP 7 CFR 205.206 requires the SOURCE of any
    # introduced biological control to be documented; reusing beneficial_species/release_quantity
    # above, these add supplier + lot + organic status so a certifier can trace the release.
    beneficial_supplier = models.CharField(
        max_length=200, blank=True, null=True, help_text="Insectary/supplier the beneficials came from (BR)"
    )
    beneficial_lot_number = models.CharField(
        max_length=100, blank=True, null=True, help_text="Supplier lot / batch number for the release (BR)"
    )
    beneficial_organic_approved = models.CharField(
        max_length=10,
        choices=[("yes", "Yes"), ("no", "No"), ("unknown", "Unknown")],
        blank=True,
        null=True,
        help_text="Whether the operator recorded an organic basis for the beneficial organism (BR)",
    )

    # Trap monitoring (TM subtype) — trap_count above is the NUMBER OF TRAPS; these capture the
    # trap kind and the actual catch so an auditor sees real IPM pressure data.
    trap_type = models.CharField(
        max_length=20,
        choices=[
            ("sticky", "Sticky card"),
            ("pheromone", "Pheromone lure"),
            ("delta", "Delta trap"),
            ("bucket_funnel", "Bucket / funnel"),
            # Vertebrate trapping (§E-7, 2026-07). The option list was insect-only, but the
            # UC Davis 2024 organic-almond cost study budgets gopher traps twice a year and
            # ground-squirrel traps six times (March-October) — routine orchard work with
            # nowhere to be recorded. Vertebrate control is also the practice most likely to
            # be questioned at inspection, since the alternative is a rodenticide.
            ("gopher_trap", "Gopher trap"),
            ("ground_squirrel_trap", "Ground squirrel trap"),
            ("other", "Other"),
        ],
        blank=True,
        null=True,
        help_text="Kind of trap deployed (TM)",
    )
    pest_catch_count = models.PositiveIntegerField(
        null=True, blank=True, help_text="Insects caught across the traps this monitoring (TM) — not the # of traps"
    )

    chemical_free_period_days = models.PositiveIntegerField(
        blank=True, null=True, help_text="Days since last synthetic chemical application"
    )

    # Sprint 3 Epic 3.1: Fuel/Equipment fields for carbon calculations (matching SoilManagementEvent)
    area_covered = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Area covered during pest management activity",
    )
    area_unit = models.CharField(
        max_length=10,
        choices=UNIT_AREA,
        default="acres",
        blank=True,
        help_text="Area unit",
    )
    fuel_consumed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed during pest management activity",
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
        blank=True,
        help_text="Fuel unit",
    )
    fuel_type = models.CharField(
        max_length=30,
        choices=FUEL_TYPES,
        blank=True,
        default="",
        help_text="Fuel type for EPA emission factor calculation",
    )
    equipment_hours = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Equipment operating hours"
    )
    production_efficiency = models.CharField(
        max_length=10,
        choices=PRODUCTION_EFFICIENCY,
        default="normal",
        blank=True,
        help_text="Equipment efficiency level for carbon calculations",
    )

    # Who identified the pest, as the farm reports it (7 CFR 205.206). Labels name a ROLE, never
    # a credential: "Licensed Agronomist" asserted a licence the record does not establish, and
    # WA/OR/CA licences and the ASA CCA are distinct things a role name cannot stand for (Astra
    # follow-up 2026-10-28, B2). Stored values are unchanged. Producer/certifier only: the field
    # is in PublicHistorySerializer._CERTIFIER_ONLY_EVENT_FIELDS.
    IDENTIFIED_BY_CHOICES = [
        ("farmer", "Farmer or farm staff"),
        ("agronomist", "Agronomist"),
        ("entomologist", "Entomologist"),
        ("extension_service", "Extension adviser"),
        ("crop_consultant", "Crop advisor"),
        ("lab", "Laboratory report"),
    ]
    identified_by = models.CharField(
        max_length=30,
        choices=IDENTIFIED_BY_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Who identified the pest, as the farm reports it (7 CFR 205.206). This is the farm's "
            "statement; Trazo does not verify the person's credentials."
        ),
    )
    identification_method = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Method used for pest identification (e.g., field guide, lab analysis, visual inspection)",
    )

    # NOP Compliance: Action Threshold Rationale (7 CFR 205.206(e))
    threshold_rationale = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "Justification for why action threshold was/wasn't met "
            "(e.g., '5 trap catches/week per UC Davis IPM guidelines'). "
            "Required per 7 CFR 205.206(e) before applying any pest control material."
        ),
    )

    def clean(self):
        """§E-4 — a cultural-control event must name the practice it performed.

        § 205.206(a) is satisfied by the SPECIFIC preventive practice, not by the category. "We
        did cultural control" supports nothing at inspection; "December mummy shake" is the
        record that later justifies, under § 205.206(e), applying a substance when it proved
        insufficient. Anything else about the event (area, crew, fuel) is optional as before.
        """
        from django.core.exceptions import ValidationError

        if self.type == self.CULTURAL_CONTROL and not self.cultural_practice:
            raise ValidationError(
                {
                    "cultural_practice": (
                        "Select the preventive practice performed (mummy removal, sanitation "
                        "shake, shredding, pruning removal, field sanitation or trap crop). "
                        "§ 205.206(a) is documented by the specific practice, not the category."
                    )
                }
            )

    class Meta:
        verbose_name = "Pest Management Event"
        verbose_name_plural = "Pest Management Events"
