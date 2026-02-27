"""
Fix event template backend_event_type values.

The event type constants were incorrectly swapped in the original seed command:
- PRODUCTION was using 2 (should be 1)
- CHEMICAL was using 1 (should be 2)

Correct constants from history/constants.py:
    WEATHER_EVENT_TYPE = 0
    PRODUCTION_EVENT_TYPE = 1
    CHEMICAL_EVENT_TYPE = 2
    GENERAL_EVENT_TYPE = 3
    EQUIPMENT_EVENT_TYPE = 4
    SOIL_MANAGEMENT_EVENT_TYPE = 5
    PEST_MANAGEMENT_EVENT_TYPE = 6
    BUSINESS_EVENT_TYPE = 7

Usage:
    python manage.py fix_event_template_types --dry-run  # Preview changes
    python manage.py fix_event_template_types            # Apply fixes
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from carbon.models import EventTemplate


class Command(BaseCommand):
    help = "Fix event template backend_event_type values (swap PRODUCTION=1 and CHEMICAL=2)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without applying them",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        self.stdout.write(
            self.style.NOTICE("Scanning EventTemplate records for incorrect backend_event_type values...")
        )
        self.stdout.write("")

        # Find templates that need fixing
        # Templates with backend_event_type=1 that should be CHEMICAL (based on event_type field)
        # Templates with backend_event_type=2 that should be PRODUCTION (based on event_type field)

        chemical_event_types = ["fertilization", "pesticide", "herbicide", "fungicide", "chemical"]
        production_event_types = [
            "pruning",
            "irrigation",
            "harvest",
            "planting",
            "production",
            "transplanting",
            "cultivation",
            "thinning",
        ]

        templates_to_fix = []

        for template in EventTemplate.objects.all():
            event_type_lower = template.event_type.lower() if template.event_type else ""
            current_backend_type = template.backend_event_type
            correct_backend_type = None

            # Determine what the correct backend_event_type should be
            if any(t in event_type_lower for t in chemical_event_types):
                correct_backend_type = 2  # CHEMICAL_EVENT_TYPE
            elif any(t in event_type_lower for t in production_event_types):
                correct_backend_type = 1  # PRODUCTION_EVENT_TYPE
            # Leave other types (soil=5, pest=6, etc.) unchanged

            if correct_backend_type is not None and current_backend_type != correct_backend_type:
                templates_to_fix.append(
                    {
                        "template": template,
                        "current": current_backend_type,
                        "correct": correct_backend_type,
                    }
                )

        if not templates_to_fix:
            self.stdout.write(
                self.style.SUCCESS("No templates need fixing. All backend_event_type values are correct.")
            )
            return

        self.stdout.write(f"Found {len(templates_to_fix)} templates that need fixing:")
        self.stdout.write("")

        for item in templates_to_fix:
            template = item["template"]
            self.stdout.write(
                f"  - {template.name} (ID: {template.id}): "
                f"event_type='{template.event_type}', "
                f"backend_event_type: {item['current']} → {item['correct']}"
            )

        self.stdout.write("")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes applied. Run without --dry-run to apply fixes."))
            return

        # Apply fixes
        with transaction.atomic():
            for item in templates_to_fix:
                template = item["template"]
                template.backend_event_type = item["correct"]
                template.save(update_fields=["backend_event_type"])

        self.stdout.write(self.style.SUCCESS(f"Successfully fixed {len(templates_to_fix)} templates."))
