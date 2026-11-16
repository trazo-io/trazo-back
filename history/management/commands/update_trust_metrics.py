"""Backfill `History.confidence_score` for existing productions.

NOTE: it used to backfill `transparency_score` too. That 0-100 self-grade was retired as a
concept (`transparency-first.md`) and left every payload on 2026-09-30, so there is nothing
to backfill: no surface reads it. `confidence_score` is not a sustainability grade (it reports
how complete the inputs to a carbon calculation are) and is rendered only in the Django admin.
"""

import logging

from django.core.management.base import BaseCommand

from history.models import Production

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Recalculate confidence_score for all productions"

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

        self.stdout.write("🔍 Starting confidence score update...")

        # Get productions to update
        if production_id:
            productions = Production.objects.filter(id=production_id)
            if not productions.exists():
                self.stderr.write(f"❌ Production with ID {production_id} not found")
                return
        else:
            productions = Production.objects.all()

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
                    old_confidence = production.confidence_score
                    new_confidence = production.calculate_confidence_score()
                    farm_history = production.get_farm_history_years()

                    if dry_run:
                        self.stdout.write(
                            f"  📋 Production {production.id} ({production.name or 'Unnamed'}):\n"
                            f"      Confidence: {old_confidence:.1f} → {new_confidence:.1f}\n"
                            f"      Farm History: {farm_history} years"
                        )
                    else:
                        production.confidence_score = new_confidence
                        production.save(update_fields=["confidence_score"])

                        self.stdout.write(f"  ✅ Updated Production {production.id}: Confidence {new_confidence:.1f}%")

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
            self.stdout.write(f"\n✅ CONFIDENCE SCORE UPDATE COMPLETE:")
            self.stdout.write(f"   Successfully updated: {updated_count} productions")
            self.stdout.write(f"   Errors: {error_count}")

        if error_count > 0:
            self.stdout.write(f"\n⚠️  Check logs for error details")
