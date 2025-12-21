"""
Management command to update EventTemplate records with display_priority,
template_category, and translation_key fields.

Usage:
    python manage.py update_event_template_fields
"""

from django.core.management.base import BaseCommand

from carbon.models import EventTemplate


class Command(BaseCommand):
    help = "Update EventTemplate records with display priority, category, and translation keys"

    # Mapping of event types to categories
    EVENT_TYPE_TO_CATEGORY = {
        "fertilization": "core",
        "irrigation": "core",
        "pest_control": "core",
        "pruning": "seasonal",
        "planting": "seasonal",
        "harvest": "seasonal",
        "soil_management": "core",
        "equipment": "maintenance",
        "weather_protection": "seasonal",
        "certification": "certification",
        "monitoring": "monitoring",
        "other": "documentation",
    }

    # Display priority based on event type (1=featured, 5=archive)
    EVENT_TYPE_TO_PRIORITY = {
        "fertilization": 1,  # Featured - core farming activity
        "irrigation": 1,  # Featured - essential
        "planting": 1,  # Featured - primary activity
        "harvest": 2,  # High - important milestone
        "pest_control": 2,  # High - important for crop health
        "pruning": 2,  # High - maintenance
        "soil_management": 2,  # High - foundation activity
        "equipment": 3,  # Normal - supporting activity
        "weather_protection": 3,  # Normal - situational
        "monitoring": 3,  # Normal - routine
        "certification": 4,  # Low - occasional
        "other": 4,  # Low - miscellaneous
    }

    # Translation key prefixes based on event type
    EVENT_TYPE_TO_TRANSLATION_PREFIX = {
        "fertilization": "quickAdd.template.fertilization",
        "irrigation": "quickAdd.template.irrigation",
        "pest_control": "quickAdd.template.pestControl",
        "pruning": "quickAdd.template.pruning",
        "planting": "quickAdd.template.planting",
        "harvest": "quickAdd.template.harvest",
        "soil_management": "quickAdd.template.soilManagement",
        "equipment": "quickAdd.template.equipment",
        "weather_protection": "quickAdd.template.weatherProtection",
        "certification": "quickAdd.template.certification",
        "monitoring": "quickAdd.template.monitoring",
        "other": "quickAdd.template.general",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        templates = EventTemplate.objects.all()
        total = templates.count()
        updated = 0

        self.stdout.write(f"Processing {total} event templates...")

        for template in templates:
            event_type = template.event_type.lower()

            # Determine new values
            new_category = self.EVENT_TYPE_TO_CATEGORY.get(event_type, "documentation")
            new_priority = self.EVENT_TYPE_TO_PRIORITY.get(event_type, 3)

            # Generate translation key based on event type and template name
            base_prefix = self.EVENT_TYPE_TO_TRANSLATION_PREFIX.get(event_type, "quickAdd.template.general")

            # Create a unique translation key using the template ID
            # This allows each template to have its own translation
            new_translation_key = f"{base_prefix}.db{template.id}"

            # Check if update is needed
            needs_update = (
                template.template_category != new_category
                or template.display_priority != new_priority
                or template.translation_key != new_translation_key
            )

            if needs_update:
                if dry_run:
                    self.stdout.write(
                        f"  Would update: {template.name}\n"
                        f"    category: {template.template_category} -> {new_category}\n"
                        f"    priority: {template.display_priority} -> {new_priority}\n"
                        f"    translation_key: '{template.translation_key}' -> '{new_translation_key}'"
                    )
                else:
                    template.template_category = new_category
                    template.display_priority = new_priority
                    template.translation_key = new_translation_key
                    template.save(update_fields=["template_category", "display_priority", "translation_key"])
                    self.stdout.write(f"  Updated: {template.name}")

                updated += 1

        if dry_run:
            self.stdout.write(self.style.WARNING(f"\nDry run complete. {updated} templates would be updated."))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nDone! Updated {updated} out of {total} templates."))
