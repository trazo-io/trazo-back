"""
Test command to create minimal carbon entry and identify exact constraint
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from carbon.models import CarbonEntry, CarbonSource
from history.models import History

User = get_user_model()


class Command(BaseCommand):
    help = "Test minimal carbon entry creation"

    def handle(self, *args, **options):
        self.stdout.write("Testing minimal carbon entry creation...")

        try:
            user = User.objects.get(email="demo@trazo.io")
            production = History.objects.filter(published=True).first()
            source = CarbonSource.objects.first()

            # Try creating with absolutely minimal required fields
            entry = CarbonEntry(type="emission", amount=100.0, co2e_amount=268.0, year=2024)

            # Save and see what happens
            entry.save()
            self.stdout.write(self.style.SUCCESS("✅ Created minimal carbon entry"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error: {e}"))

            # Try with more fields
            try:
                entry = CarbonEntry(
                    establishment=production.parcel.establishment,
                    production=production,
                    created_by=user,
                    type="emission",
                    source=source,
                    amount=100.0,
                    co2e_amount=268.0,
                    year=2024,
                    description="Test entry",
                )
                entry.save()
                self.stdout.write(self.style.SUCCESS("✅ Created carbon entry with basic fields"))

            except Exception as e2:
                self.stdout.write(self.style.ERROR(f"❌ Still failed: {e2}"))
