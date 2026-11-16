"""
Management command to update production reputation values based on reviews.

Usage:
    poetry run python manage.py update_production_reputations
    poetry run python manage.py update_production_reputations --production-id 247
"""

from django.core.management.base import BaseCommand
from django.db.models import Avg

from history.models import Production
from reviews.models import Review


class Command(BaseCommand):
    help = "Update production reputation values based on review ratings"

    def add_arguments(self, parser):
        parser.add_argument(
            "--production-id",
            type=int,
            help="Update reputation for a specific production ID",
        )

    def handle(self, *args, **options):
        production_id = options.get("production_id")

        if production_id:
            # Update specific production
            try:
                production = Production.objects.get(id=production_id)
                old_reputation = production.reputation
                production.update_reputation()
                production.refresh_from_db()

                self.stdout.write(
                    self.style.SUCCESS(f"Production {production_id}: " f"{old_reputation} → {production.reputation}")
                )
            except Production.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Production {production_id} not found"))
        else:
            # Update all productions with reviews
            productions_with_reviews = Production.objects.filter(reviews__isnull=False).distinct()

            total = productions_with_reviews.count()
            updated = 0

            self.stdout.write(f"Found {total} productions with reviews\n")

            for production in productions_with_reviews:
                # Calculate expected reputation
                avg_rating = Review.objects.filter(production=production).aggregate(Avg("rating"))["rating__avg"]
                expected_reputation = round(avg_rating, 2) if avg_rating else 0.00

                if abs(production.reputation - expected_reputation) > 0.01:
                    old_reputation = production.reputation
                    production.update_reputation()
                    production.refresh_from_db()
                    updated += 1

                    self.stdout.write(f"  Production {production.id}: " f"{old_reputation} → {production.reputation}")

            if updated > 0:
                self.stdout.write(self.style.SUCCESS(f"\n✅ Updated {updated} production(s)"))
            else:
                self.stdout.write(self.style.SUCCESS("\n✅ All reputations are already correct"))
