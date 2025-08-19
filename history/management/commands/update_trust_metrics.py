"""
Management command to update trust metrics for all existing productions.
Run this after adding the new trust metric fields to populate them with calculated values.
"""

import logging

from django.core.management.base import BaseCommand

from history.models import History

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Update trust metrics (confidence_score, transparency_score) for all productions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size", type=int, default=100, help="Number of productions to process in each batch (default: 100)"
        )
        parser.add_argument("--production-id", type=int, help="Update trust metrics for a specific production ID only")
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be updated without actually updating"
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        production_id = options.get("production_id")
        dry_run = options["dry_run"]

        self.stdout.write("🔍 Starting trust metrics update...")

        # Get productions to update
        if production_id:
            productions = History.objects.filter(id=production_id)
            if not productions.exists():
                self.stderr.write(f"❌ Production with ID {production_id} not found")
                return
        else:
            productions = History.objects.all()

        total_count = productions.count()
        self.stdout.write(f"📊 Found {total_count} productions to process")

        if dry_run:
            self.stdout.write("🧪 DRY RUN MODE - No changes will be made")

        updated_count = 0
        error_count = 0

        # Process in batches
        for i in range(0, total_count, batch_size):
            batch = productions[i : i + batch_size]
            self.stdout.write(f"📦 Processing batch {i//batch_size + 1} ({i+1}-{min(i+batch_size, total_count)})...")

            for production in batch:
                try:
                    # Calculate new trust metrics
                    old_confidence = production.confidence_score
                    old_transparency = production.transparency_score

                    new_confidence = production.calculate_confidence_score()
                    new_transparency = production.calculate_transparency_score()
                    farm_history = production.get_farm_history_years()

                    if dry_run:
                        self.stdout.write(
                            f"  📋 Production {production.id} ({production.name or 'Unnamed'}):\n"
                            f"      Confidence: {old_confidence:.1f} → {new_confidence:.1f}\n"
                            f"      Transparency: {old_transparency:.1f} → {new_transparency:.1f}\n"
                            f"      Farm History: {farm_history} years"
                        )
                    else:
                        # Update the metrics
                        production.confidence_score = new_confidence
                        production.transparency_score = new_transparency
                        production.save(update_fields=["confidence_score", "transparency_score"])

                        self.stdout.write(
                            f"  ✅ Updated Production {production.id}: "
                            f"Confidence {new_confidence:.1f}%, Transparency {new_transparency:.1f}%"
                        )

                    updated_count += 1

                except Exception as e:
                    error_count += 1
                    logger.error(f"Error updating production {production.id}: {str(e)}")
                    self.stderr.write(f"  ❌ Error updating Production {production.id}: {str(e)}")

        # Summary
        if dry_run:
            self.stdout.write(f"\n🧪 DRY RUN COMPLETE:")
            self.stdout.write(f"   Would update: {updated_count} productions")
            self.stdout.write(f"   Errors found: {error_count}")
        else:
            self.stdout.write(f"\n✅ TRUST METRICS UPDATE COMPLETE:")
            self.stdout.write(f"   Successfully updated: {updated_count} productions")
            self.stdout.write(f"   Errors: {error_count}")

        if error_count > 0:
            self.stdout.write(f"\n⚠️  Check logs for error details")
