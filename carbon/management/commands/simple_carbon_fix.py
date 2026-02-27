"""
Simple command to create carbon entries with minimal required fields
"""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from carbon.models import CarbonSource
from history.models import History

User = get_user_model()


class Command(BaseCommand):
    help = "Create carbon entries with minimal required fields"

    def handle(self, *args, **options):
        self.stdout.write("🌱 Creating carbon entries with minimal required fields...")

        try:
            user = User.objects.get(email="demo@trazo.io")

            # Get a few productions for testing, including establishment 2 and year 2025
            productions = History.objects.filter(published=True, parcel__establishment__id__in=[1, 2])

            # Get or create simple carbon sources
            fuel_source, _ = CarbonSource.objects.get_or_create(
                name="Demo Fuel",
                defaults={
                    "category": "fuel",
                    "unit": "liters",
                    "default_emission_factor": 2.70,
                    "description": "Demo fuel emissions",
                    "usda_verified": True,
                    "usda_factors_based": True,
                },
            )

            entries_created = 0

            with connection.cursor() as cursor:
                for production in productions:
                    year = production.start_date.year

                    # For testing, let's create one entry for year 2025 specifically
                    if production.parcel.establishment.id == 2:
                        test_year = 2025  # Force year 2025 for establishment 2
                    else:
                        test_year = year

                    amount = production.parcel.area * 50
                    co2e_amount = amount * fuel_source.default_emission_factor
                    now = timezone.now()

                    # Use a very simple insert with minimal fields and proper JSON
                    cursor.execute(
                        """
                        INSERT INTO carbon_carbonentry (
                            establishment_id, production_id, created_by_id, type, source_id,
                            amount, co2e_amount, year, description, timestamp, created_at, updated_at,
                            usda_verified, usda_factors_based, verification_status, data_source,
                            verification_level, trust_score, effective_amount, additionality_verified,
                            permanence_plan, baseline_data, audit_status, evidence_requirements_met,
                            documentation_complete, additionality_evidence, evidence_photos, evidence_documents,
                            external_verification_id, iot_device_id, methodology_template, registry_verification_id,
                            baseline_scenario, methodology_id, monitoring_plan, registry_name, registry_submission_id,
                            verification_notes, verification_report_url, gps_coordinates, financial_analysis,
                            detected_patterns, third_party_verification_url
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                    """,
                        [
                            production.parcel.establishment.id,  # establishment_id
                            production.id,  # production_id
                            user.id,  # created_by_id
                            "emission",  # type
                            fuel_source.id,  # source_id
                            amount,  # amount
                            co2e_amount,  # co2e_amount
                            test_year,  # year - using test_year for establishment 2
                            f"Demo fuel emissions for {production.name}",  # description
                            now,  # timestamp
                            now,  # created_at
                            now,  # updated_at
                            True,  # usda_verified
                            True,  # usda_factors_based
                            "verified",  # verification_status
                            "USDA",  # data_source
                            "basic",  # verification_level
                            0.9,  # trust_score
                            co2e_amount * 0.9,  # effective_amount
                            True,  # additionality_verified
                            "Standard plan",  # permanence_plan
                            json.dumps({"baseline": "standard"}),  # baseline_data (proper JSON)
                            "pending",  # audit_status
                            True,  # evidence_requirements_met
                            True,  # documentation_complete
                            "Standard evidence",  # additionality_evidence
                            json.dumps([]),  # evidence_photos (proper JSON)
                            json.dumps([]),  # evidence_documents (proper JSON)
                            f"EXT-{production.id}-{test_year}",  # external_verification_id
                            "",  # iot_device_id
                            "STANDARD",  # methodology_template
                            f"REG-{production.id}-{test_year}",  # registry_verification_id
                            "Standard baseline",  # baseline_scenario
                            "METHOD-001",  # methodology_id
                            "Standard monitoring",  # monitoring_plan
                            "USDA Registry",  # registry_name
                            f"SUB-{production.id}",  # registry_submission_id
                            "Standard notes",  # verification_notes
                            "",  # verification_report_url
                            "36.7,-119.8",  # gps_coordinates
                            "Standard analysis",  # financial_analysis
                            "Standard patterns",  # detected_patterns
                            "",  # third_party_verification_url
                        ],
                    )
                    entries_created += 1

                    # Only create a few entries for testing
                    if entries_created >= 5:
                        break

            self.stdout.write(self.style.SUCCESS(f"✅ Created {entries_created} carbon entries"))

            # Verify the results
            from carbon.models import CarbonEntry

            total = CarbonEntry.objects.count()
            est_2 = CarbonEntry.objects.filter(establishment_id=2).count()
            year_2025 = CarbonEntry.objects.filter(year=2025).count()

            self.stdout.write(f"📊 Results:")
            self.stdout.write(f"   Total entries: {total}")
            self.stdout.write(f"   Establishment 2: {est_2}")
            self.stdout.write(f"   Year 2025: {year_2025}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error: {e}"))
            import traceback

            self.stdout.write(traceback.format_exc())
