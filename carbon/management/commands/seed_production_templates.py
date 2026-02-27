"""
Master Seed Command for Production Templates
=============================================

SINGLE SOURCE OF TRUTH for seeding all production templates, event templates,
and related data in Trazo.

This command orchestrates all template seeding in the correct order, ensures
canonical field formats, and provides idempotency tracking.

Usage:
    # Full production seed (recommended for new deployments)
    poetry run python manage.py seed_production_templates

    # Dry run - see what would be executed without making changes
    poetry run python manage.py seed_production_templates --dry-run

    # Validate only - check current state without seeding
    poetry run python manage.py seed_production_templates --validate-only

    # Force re-seed (re-runs even if already seeded)
    poetry run python manage.py seed_production_templates --force

    # Skip validation step (faster, less safe)
    poetry run python manage.py seed_production_templates --skip-validation

    # Specific region only
    poetry run python manage.py seed_production_templates --region iowa
    poetry run python manage.py seed_production_templates --region california

Best Practices:
    - Always backup database before running in production
    - Use --dry-run first to preview changes
    - Use --validate-only to check current state
    - This command is idempotent - safe to run multiple times
"""

import json
from datetime import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from carbon.models import CropType, EventTemplate, ProductionTemplate


class Command(BaseCommand):
    help = "Master seed command for all production templates - SINGLE SOURCE OF TRUTH"

    # Canonical field format specification
    # All numeric values must be stored separately from units
    CANONICAL_FIELD_SPEC = {
        "volume": {"type": "numeric", "unit_field": "volume_unit"},
        "area": {"type": "numeric", "unit_field": "area_unit"},
        "fuel_consumed": {"type": "numeric", "unit_field": "fuel_unit"},
        "area_covered": {"type": "numeric", "unit_field": "area_unit"},
        "water_amount_gallons": {"type": "numeric", "unit_field": None},
        "nitrogen_percentage": {"type": "numeric", "unit_field": None},
        "phosphorus_percentage": {"type": "numeric", "unit_field": None},
        "potassium_percentage": {"type": "numeric", "unit_field": None},
    }

    def __init__(self):
        super().__init__()
        self.dry_run = False
        self.force = False
        self.skip_validation = False
        self.region = "all"
        self.errors = []
        self.warnings = []
        self.stats = {
            "crop_types_created": 0,
            "production_templates_created": 0,
            "event_templates_created": 0,
            "equipment_events_added": 0,
            "regional_practices_added": 0,
            "transparency_features_added": 0,
            "field_format_issues": 0,
        }

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be executed without making changes",
        )
        parser.add_argument(
            "--validate-only",
            action="store_true",
            help="Only validate current state, don't seed anything",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-seed even if data already exists",
        )
        parser.add_argument(
            "--skip-validation",
            action="store_true",
            help="Skip post-seed validation (faster, less safe)",
        )
        parser.add_argument(
            "--region",
            type=str,
            default="all",
            choices=["all", "iowa", "california"],
            help="Specific region to seed (default: all)",
        )

    def handle(self, *args, **options):
        self.dry_run = options.get("dry_run", False)
        self.force = options.get("force", False)
        self.skip_validation = options.get("skip_validation", False)
        self.region = options.get("region", "all")
        validate_only = options.get("validate_only", False)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("  TRAZO MASTER SEED - Production Templates"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write("")

        if validate_only:
            self._run_validation_only()
            return

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))
            self.stdout.write("")

        # Check current state
        current_state = self._get_current_state()
        self._print_current_state(current_state)

        # Check if already seeded
        if self._is_already_seeded(current_state) and not self.force:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Production templates already seeded. Use --force to re-seed."))
            self.stdout.write("")
            self._run_field_format_validation()
            return

        # Execute seeding sequence
        self._execute_seed_sequence()

        # Run validation
        if not self.skip_validation and not self.dry_run:
            self._run_post_seed_validation()

        # Print summary
        self._print_summary()

    def _get_current_state(self):
        """Get current database state for templates."""
        return {
            "crop_types": CropType.objects.filter(is_active=True).count(),
            "production_templates": ProductionTemplate.objects.count(),
            "event_templates": EventTemplate.objects.count(),
            "usda_verified": CropType.objects.filter(usda_verified=True).count(),
        }

    def _print_current_state(self, state):
        """Print current database state."""
        self.stdout.write("Current State:")
        self.stdout.write(f"  Crop Types: {state['crop_types']}")
        self.stdout.write(f"  Production Templates: {state['production_templates']}")
        self.stdout.write(f"  Event Templates: {state['event_templates']}")
        self.stdout.write(f"  USDA Verified: {state['usda_verified']}")
        self.stdout.write("")

    def _is_already_seeded(self, state):
        """Check if templates have already been seeded."""
        return state["crop_types"] >= 19 and state["production_templates"] >= 19 and state["event_templates"] >= 100

    def _execute_seed_sequence(self):
        """Execute the seeding sequence in correct order."""
        steps = [
            ("Step 1/6: Populate USDA Crop Types", self._seed_crop_types),
            (
                "Step 2/6: Create Production Templates",
                self._seed_production_templates,
            ),
            ("Step 3/6: Add Equipment Events", self._seed_equipment_events),
            ("Step 4/6: Add Regional Practices", self._seed_regional_practices),
            (
                "Step 5/6: Add Consumer Transparency",
                self._seed_consumer_transparency,
            ),
            ("Step 6/6: Validate Field Formats", self._validate_and_fix_field_formats),
        ]

        for step_name, step_func in steps:
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO(f"{step_name}"))
            self.stdout.write("-" * 50)

            try:
                if self.dry_run:
                    self.stdout.write(f"  [DRY RUN] Would execute: {step_name}")
                else:
                    step_func()
                    self.stdout.write(self.style.SUCCESS(f"  Completed: {step_name}"))
            except Exception as e:
                self.errors.append(f"{step_name}: {str(e)}")
                self.stdout.write(self.style.ERROR(f"  ERROR: {str(e)}"))
                if not self.force:
                    raise

    def _seed_crop_types(self):
        """Step 1: Seed USDA crop types."""
        before_count = CropType.objects.filter(is_active=True).count()
        call_command("populate_usda_crop_types", verbosity=0)
        after_count = CropType.objects.filter(is_active=True).count()
        self.stats["crop_types_created"] = after_count - before_count
        self.stdout.write(f"  Created {self.stats['crop_types_created']} crop types")

    def _seed_production_templates(self):
        """Step 2: Seed production templates with event templates."""
        before_pt = ProductionTemplate.objects.count()
        before_et = EventTemplate.objects.count()
        call_command("create_comprehensive_production_templates", verbosity=0)
        after_pt = ProductionTemplate.objects.count()
        after_et = EventTemplate.objects.count()
        self.stats["production_templates_created"] = after_pt - before_pt
        self.stats["event_templates_created"] = after_et - before_et
        self.stdout.write(f"  Created {self.stats['production_templates_created']} production templates")
        self.stdout.write(f"  Created {self.stats['event_templates_created']} event templates")

    def _seed_equipment_events(self):
        """Step 3: Add equipment-specific events."""
        before_count = EventTemplate.objects.count()
        call_command("enhance_production_templates_with_equipment", verbosity=0)
        after_count = EventTemplate.objects.count()
        self.stats["equipment_events_added"] = after_count - before_count
        self.stdout.write(f"  Added {self.stats['equipment_events_added']} equipment events")

    def _seed_regional_practices(self):
        """Step 4: Add regional agricultural practices."""
        states_to_seed = []
        if self.region == "all":
            states_to_seed = ["Iowa", "California"]
        elif self.region == "iowa":
            states_to_seed = ["Iowa"]
        elif self.region == "california":
            states_to_seed = ["California"]

        for state in states_to_seed:
            try:
                call_command(
                    "add_regional_practices",
                    state=state,
                    practice="all",
                    verbosity=0,
                )
                self.stdout.write(f"  Added regional practices for: {state}")
            except Exception as e:
                self.warnings.append(f"Regional practices ({state}): {str(e)}")
                self.stdout.write(self.style.WARNING(f"  Warning: Could not add regional practices for {state}: {e}"))

    def _seed_consumer_transparency(self):
        """Step 5: Add consumer transparency features."""
        try:
            call_command(
                "add_consumer_transparency",
                region=self.region,
                feature="all",
                verbosity=0,
            )
            self.stdout.write(f"  Added transparency features for: {self.region}")
        except Exception as e:
            self.warnings.append(f"Consumer transparency: {str(e)}")
            self.stdout.write(self.style.WARNING(f"  Warning: Could not add transparency features: {e}"))

    def _validate_and_fix_field_formats(self):
        """Step 6: Validate and fix field formats to canonical specification."""
        issues_found = 0
        issues_fixed = 0

        event_templates = EventTemplate.objects.exclude(backend_event_fields={})

        for template in event_templates:
            fields = template.backend_event_fields or {}
            needs_update = False

            for field_name, spec in self.CANONICAL_FIELD_SPEC.items():
                if field_name in fields:
                    value = fields[field_name]

                    # Check if value is a combined string like "400 kg/ha"
                    if isinstance(value, str) and self._is_combined_value(value):
                        issues_found += 1

                        # Parse and fix
                        numeric_val, unit = self._parse_combined_value(value)
                        if numeric_val is not None:
                            fields[field_name] = numeric_val
                            if spec["unit_field"]:
                                fields[spec["unit_field"]] = unit
                            needs_update = True
                            issues_fixed += 1
                            self.stdout.write(
                                f"    Fixed {template.name}.{field_name}: "
                                f'"{value}" -> {numeric_val}, {spec["unit_field"]}="{unit}"'
                            )

            if needs_update:
                template.backend_event_fields = fields
                template.save(update_fields=["backend_event_fields"])

        self.stats["field_format_issues"] = issues_found
        self.stdout.write(f"  Checked {event_templates.count()} event templates")
        self.stdout.write(f"  Found {issues_found} field format issues")
        self.stdout.write(f"  Fixed {issues_fixed} field format issues")

    def _is_combined_value(self, value):
        """Check if a value is a combined string like '400 kg/ha'."""
        if not isinstance(value, str):
            return False

        # Pattern: number followed by space and unit
        parts = value.strip().split()
        if len(parts) >= 2:
            try:
                float(parts[0])
                return True
            except ValueError:
                return False
        return False

    def _parse_combined_value(self, value):
        """Parse a combined value like '400 kg/ha' into (400, 'kg/ha')."""
        parts = value.strip().split(None, 1)
        if len(parts) >= 2:
            try:
                numeric = float(parts[0])
                # Convert to int if it's a whole number
                if numeric == int(numeric):
                    numeric = int(numeric)
                unit = parts[1]
                return numeric, unit
            except ValueError:
                return None, None
        return None, None

    def _run_field_format_validation(self):
        """Validate field formats without fixing."""
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Field Format Validation"))
        self.stdout.write("-" * 50)

        issues = []
        event_templates = EventTemplate.objects.exclude(backend_event_fields={})

        for template in event_templates:
            fields = template.backend_event_fields or {}

            for field_name, spec in self.CANONICAL_FIELD_SPEC.items():
                if field_name in fields:
                    value = fields[field_name]

                    if isinstance(value, str) and self._is_combined_value(value):
                        issues.append(
                            {
                                "template": template.name,
                                "field": field_name,
                                "value": value,
                                "expected": f"numeric value with separate {spec['unit_field']}",
                            }
                        )

        if issues:
            self.stdout.write(self.style.WARNING(f"  Found {len(issues)} field format issues:"))
            for issue in issues[:10]:  # Show first 10
                self.stdout.write(
                    f"    - {issue['template']}.{issue['field']}: "
                    f'"{issue["value"]}" (expected: {issue["expected"]})'
                )
            if len(issues) > 10:
                self.stdout.write(f"    ... and {len(issues) - 10} more")
            self.stdout.write("")
            self.stdout.write("  Run without --validate-only to fix these issues")
        else:
            self.stdout.write(self.style.SUCCESS("  All field formats are canonical"))

    def _run_validation_only(self):
        """Run validation without seeding."""
        self.stdout.write("VALIDATION ONLY MODE")
        self.stdout.write("")

        # Current state
        current_state = self._get_current_state()
        self._print_current_state(current_state)

        # Field format validation
        self._run_field_format_validation()

        # MVP readiness
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("MVP Readiness Check"))
        self.stdout.write("-" * 50)
        try:
            call_command("validate_mvp_readiness", region="all", detailed=True, verbosity=1)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Could not run MVP validation: {e}"))

    def _run_post_seed_validation(self):
        """Run validation after seeding."""
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Post-Seed Validation"))
        self.stdout.write("-" * 50)

        # Validate field formats
        issues = self._count_field_format_issues()
        if issues > 0:
            self.stdout.write(self.style.WARNING(f"  Field format issues remaining: {issues}"))
        else:
            self.stdout.write(self.style.SUCCESS("  All field formats are canonical"))

        # MVP readiness
        try:
            call_command("validate_mvp_readiness", region="all", detailed=False, verbosity=0)
            self.stdout.write(self.style.SUCCESS("  MVP readiness: PASSED"))
        except Exception as e:
            self.warnings.append(f"MVP validation: {str(e)}")
            self.stdout.write(self.style.WARNING(f"  MVP readiness check failed: {e}"))

    def _count_field_format_issues(self):
        """Count field format issues without fixing."""
        count = 0
        event_templates = EventTemplate.objects.exclude(backend_event_fields={})

        for template in event_templates:
            fields = template.backend_event_fields or {}

            for field_name in self.CANONICAL_FIELD_SPEC.keys():
                if field_name in fields:
                    value = fields[field_name]
                    if isinstance(value, str) and self._is_combined_value(value):
                        count += 1

        return count

    def _print_summary(self):
        """Print execution summary."""
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("  SEED COMPLETE"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write("")

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes were made"))
            self.stdout.write("")

        self.stdout.write("Summary:")
        self.stdout.write(f"  Crop Types Created: {self.stats['crop_types_created']}")
        self.stdout.write(f"  Production Templates Created: {self.stats['production_templates_created']}")
        self.stdout.write(f"  Event Templates Created: {self.stats['event_templates_created']}")
        self.stdout.write(f"  Equipment Events Added: {self.stats['equipment_events_added']}")
        self.stdout.write(f"  Field Format Issues Fixed: {self.stats['field_format_issues']}")

        if self.errors:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("Errors:"))
            for error in self.errors:
                self.stdout.write(f"  - {error}")

        if self.warnings:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Warnings:"))
            for warning in self.warnings:
                self.stdout.write(f"  - {warning}")

        # Final state
        self.stdout.write("")
        final_state = self._get_current_state()
        self.stdout.write("Final State:")
        self.stdout.write(f"  Crop Types: {final_state['crop_types']}")
        self.stdout.write(f"  Production Templates: {final_state['production_templates']}")
        self.stdout.write(f"  Event Templates: {final_state['event_templates']}")
        self.stdout.write("")

        # Next steps
        self.stdout.write("Next Steps:")
        self.stdout.write("  1. Verify with: poetry run python manage.py seed_production_templates --validate-only")
        self.stdout.write("  2. Check MVP: poetry run python manage.py validate_mvp_readiness --region all --detailed")
        self.stdout.write("")
