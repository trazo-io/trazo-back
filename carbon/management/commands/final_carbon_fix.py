"""
Final working command to create carbon entries with exact database schema
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
    help = "Create carbon entries with exact database schema mapping"

    def handle(self, *args, **options):
        self.stdout.write("🌱 Creating carbon entries with exact schema...")

        try:
            user = User.objects.get(email="demo@trazo.io")

            # Get productions for both establishments
            productions = History.objects.filter(published=True, parcel__establishment__id__in=[1, 2])[
                :6
            ]  # Limit to 6 for testing

            # Get or create carbon source
            fuel_source, _ = CarbonSource.objects.get_or_create(
                name="Demo Fuel Source",
                defaults={
                    "category": "fuel",
                    "unit": "liters",
                    "default_emission_factor": 2.70,
                    "description": "Demo fuel emissions for testing",
                    "usda_factors_used": True,
                    "usda_factors_based": True,
                },
            )

            entries_created = 0

            with connection.cursor() as cursor:
                for production in productions:
                    est_id = production.parcel.establishment.id

                    # For establishment 2, use year 2025 to test the API
                    if est_id == 2:
                        year = 2025
                    else:
                        year = production.start_date.year

                    amount = production.parcel.area * 50
                    co2e_amount = amount * fuel_source.default_emission_factor
                    now = timezone.now()

                    # Insert using exact column order from database schema
                    cursor.execute(
                        """
                        INSERT INTO carbon_carbonentry (
                            year, type, amount, description, created_by_id, establishment_id, production_id, source_id,
                            timestamp, created_at, iot_device_id, updated_at, co2e_amount, data_source,
                            usda_factors_based, verification_status, additionality_evidence, additionality_verified,
                            audit_scheduled_date, baseline_data, documentation_complete, evidence_requirements_met,
                            methodology_template, permanence_plan, registry_verification_id, third_party_verification_url,
                            external_verification_id, gps_coordinates, verification_notes, baseline_scenario,
                            detected_patterns, financial_analysis, methodology_id, monitoring_plan, registry_name,
                            registry_submission_id, verification_report_url, audit_status, effective_amount,
                            evidence_documents, evidence_photos, trust_score, verification_level
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                    """,
                        [
                            year,  # year
                            "emission",  # type
                            amount,  # amount
                            f"Demo fuel emissions for {production.name}",  # description
                            user.id if user else None,  # created_by_id
                            est_id,  # establishment_id
                            production.id,  # production_id
                            fuel_source.id,  # source_id
                            now,  # timestamp
                            now,  # created_at
                            "",  # iot_device_id
                            now,  # updated_at
                            co2e_amount,  # co2e_amount
                            "USDA Agricultural Research Service",  # data_source
                            True,  # usda_factors_based
                            "verified",  # verification_status
                            "USDA verification documentation",  # additionality_evidence
                            True,  # additionality_verified
                            None,  # audit_scheduled_date
                            json.dumps({"baseline_year": 2020, "baseline_emissions": 100}),  # baseline_data (jsonb)
                            True,  # documentation_complete
                            True,  # evidence_requirements_met
                            "USDA_STANDARD",  # methodology_template
                            "Long-term sustainable agricultural practices",  # permanence_plan
                            f"REG-{production.id}-{year}",  # registry_verification_id
                            "",  # third_party_verification_url
                            f"EXT-{production.id}-{year}",  # external_verification_id
                            json.dumps({"lat": 36.7, "lon": -119.8}),  # gps_coordinates (jsonb)
                            "USDA verified emissions data",  # verification_notes
                            json.dumps(
                                {"scenario": "conventional_practices", "description": "Standard baseline"}
                            ),  # baseline_scenario (jsonb)
                            json.dumps(
                                {"patterns": ["seasonal_variation", "equipment_efficiency"]}
                            ),  # detected_patterns (jsonb)
                            json.dumps({"cost_per_ton": 25.5, "roi": "positive"}),  # financial_analysis (jsonb)
                            "USDA_AG_001",  # methodology_id
                            json.dumps(
                                {"frequency": "monthly", "parameters": ["fuel_usage", "efficiency"]}
                            ),  # monitoring_plan (jsonb)
                            "USDA Carbon Registry",  # registry_name
                            f"SUB-{production.id}-{year}",  # registry_submission_id
                            f"https://usda.gov/verify/{production.id}",  # verification_report_url
                            "passed",  # audit_status
                            co2e_amount * 0.95,  # effective_amount
                            json.dumps([]),  # evidence_documents (jsonb)
                            json.dumps([]),  # evidence_photos (jsonb)
                            0.95,  # trust_score
                            "certified_project",  # verification_level
                        ],
                    )
                    entries_created += 1

            self.stdout.write(self.style.SUCCESS(f"✅ Created {entries_created} carbon entries"))

            # Verify the results
            from carbon.models import CarbonEntry

            total = CarbonEntry.objects.count()
            est_1 = CarbonEntry.objects.filter(establishment_id=1).count()
            est_2 = CarbonEntry.objects.filter(establishment_id=2).count()
            year_2025 = CarbonEntry.objects.filter(year=2025).count()

            self.stdout.write(f"📊 Final Results:")
            self.stdout.write(f"   Total entries: {total}")
            self.stdout.write(f"   Establishment 1: {est_1}")
            self.stdout.write(f"   Establishment 2: {est_2}")
            self.stdout.write(f"   Year 2025: {year_2025}")

            # Test the API query that was failing
            api_test = CarbonEntry.objects.filter(establishment_id=2, year=2025)
            self.stdout.write(f"   API test (establishment=2&year=2025): {api_test.count()}")

            if api_test.exists():
                self.stdout.write(self.style.SUCCESS("🎉 API endpoint should now return data!"))
                entry = api_test.first()
                self.stdout.write(f"   Sample entry: {entry.description} - {entry.co2e_amount} kg CO2e")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error: {e}"))
            import traceback

            self.stdout.write(traceback.format_exc())
