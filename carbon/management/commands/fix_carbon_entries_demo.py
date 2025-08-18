"""
Command to fix carbon entries creation for the demo data
This addresses the database schema constraints that prevent carbon entries from being created
"""

import datetime
import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from carbon.models import CarbonSource
from history.models import History

User = get_user_model()


class Command(BaseCommand):
    help = "Fix carbon entries creation for demo data with proper database constraints"

    def handle(self, *args, **options):
        self.stdout.write("🔧 Fixing carbon entries for demo data...")

        try:
            user = User.objects.get(email="demo@trazo.io")
            published_productions = History.objects.filter(
                published=True, parcel__establishment__id__in=[1, 2]
            ).order_by("start_date")

            self.stdout.write(f"Found {published_productions.count()} published productions")

            # Get or create carbon sources
            fuel_source = self.get_or_create_carbon_source(
                "Diesel Fuel", "fuel", "liters", 2.68, "USDA verified diesel fuel emissions"
            )
            fertilizer_source = self.get_or_create_carbon_source(
                "Organic Fertilizer", "fertilizer", "kg", 0.45, "USDA verified organic fertilizer"
            )
            sequestration_source = self.get_or_create_carbon_source(
                "Soil Carbon Sequestration", "sequestration", "hectares", -2.5, "Soil carbon sequestration"
            )

            entries_created = 0

            # Use direct SQL with ALL required fields
            with connection.cursor() as cursor:
                for production in published_productions:
                    parcel_area = production.parcel.area
                    year = production.start_date.year

                    # Create fuel emission entry
                    fuel_amount = parcel_area * 50  # 50 liters per hectare
                    fuel_co2e = fuel_amount * fuel_source.default_emission_factor

                    self.create_carbon_entry_sql(
                        cursor,
                        {
                            "establishment_id": production.parcel.establishment.id,
                            "production_id": production.id,
                            "created_by_id": user.id,
                            "type": "emission",
                            "source_id": fuel_source.id,
                            "amount": fuel_amount,
                            "co2e_amount": fuel_co2e,
                            "year": year,
                            "description": f"Fuel emissions for {production.name}",
                            "external_verification_id": f"USDA-FUEL-{production.id}-{year}",
                            "methodology_template": "USDA_STANDARD",
                            "registry_verification_id": f"REG-{production.id}-{year}-FUEL",
                            "baseline_scenario": "Conventional agricultural practices",
                            "methodology_id": "USDA_AG_001",
                            "monitoring_plan": "Annual fuel consumption monitoring",
                            "registry_name": "USDA Carbon Registry",
                            "registry_submission_id": f"SUB-{production.id}-{year}",
                            "verification_notes": "USDA verified fuel consumption data",
                            "verification_report_url": f"https://usda.gov/verify/{production.id}",
                            "gps_coordinates": f"{36.7 + random.uniform(-0.1, 0.1)}, {-119.8 + random.uniform(-0.1, 0.1)}",
                            "financial_analysis": "Cost-effective emission reduction strategy",
                            "detected_patterns": "Seasonal fuel usage patterns detected",
                        },
                    )
                    entries_created += 1

                    # Create fertilizer emission entry
                    fert_amount = parcel_area * 20  # 20 kg per hectare
                    fert_co2e = fert_amount * fertilizer_source.default_emission_factor

                    self.create_carbon_entry_sql(
                        cursor,
                        {
                            "establishment_id": production.parcel.establishment.id,
                            "production_id": production.id,
                            "created_by_id": user.id,
                            "type": "emission",
                            "source_id": fertilizer_source.id,
                            "amount": fert_amount,
                            "co2e_amount": fert_co2e,
                            "year": year,
                            "description": f"Fertilizer emissions for {production.name}",
                            "external_verification_id": f"USDA-FERT-{production.id}-{year}",
                            "methodology_template": "USDA_FERTILIZER",
                            "registry_verification_id": f"REG-{production.id}-{year}-FERT",
                            "baseline_scenario": "Conventional fertilizer application",
                            "methodology_id": "USDA_AG_002",
                            "monitoring_plan": "Quarterly fertilizer application tracking",
                            "registry_name": "USDA Carbon Registry",
                            "registry_submission_id": f"SUB-FERT-{production.id}-{year}",
                            "verification_notes": "USDA verified organic fertilizer usage",
                            "verification_report_url": f"https://usda.gov/verify/fert/{production.id}",
                            "gps_coordinates": f"{36.7 + random.uniform(-0.1, 0.1)}, {-119.8 + random.uniform(-0.1, 0.1)}",
                            "financial_analysis": "Organic fertilizer premium justified by carbon benefits",
                            "detected_patterns": "Optimal fertilizer timing for crop stages",
                        },
                    )
                    entries_created += 1

                    # Create sequestration offset entry
                    seq_amount = parcel_area * 1.5  # 1.5 hectares of sequestration practices
                    seq_co2e = seq_amount * sequestration_source.default_emission_factor  # Negative

                    self.create_carbon_entry_sql(
                        cursor,
                        {
                            "establishment_id": production.parcel.establishment.id,
                            "production_id": production.id,
                            "created_by_id": user.id,
                            "type": "offset",
                            "source_id": sequestration_source.id,
                            "amount": seq_amount,
                            "co2e_amount": seq_co2e,
                            "year": year,
                            "description": f"Soil carbon sequestration for {production.name}",
                            "external_verification_id": f"USDA-SEQ-{production.id}-{year}",
                            "methodology_template": "USDA_SOIL_CARBON",
                            "registry_verification_id": f"REG-{production.id}-{year}-SEQ",
                            "baseline_scenario": "Conventional tillage practices",
                            "methodology_id": "USDA_SOIL_001",
                            "monitoring_plan": "Annual soil carbon measurement",
                            "registry_name": "USDA Soil Carbon Registry",
                            "registry_submission_id": f"SUB-SEQ-{production.id}-{year}",
                            "verification_notes": "USDA verified soil carbon sequestration",
                            "verification_report_url": f"https://usda.gov/verify/soil/{production.id}",
                            "gps_coordinates": f"{36.7 + random.uniform(-0.1, 0.1)}, {-119.8 + random.uniform(-0.1, 0.1)}",
                            "financial_analysis": "Carbon credit revenue from soil sequestration",
                            "detected_patterns": "Improved soil organic matter over time",
                        },
                    )
                    entries_created += 1

            self.stdout.write(
                self.style.SUCCESS(f"✅ Created {entries_created} carbon entries with all required fields")
            )

            # Verify the entries were created
            from carbon.models import CarbonEntry

            final_count = CarbonEntry.objects.count()
            est_2_count = CarbonEntry.objects.filter(establishment_id=2).count()
            year_2025_count = CarbonEntry.objects.filter(year=2025).count()

            self.stdout.write(f"📊 Verification:")
            self.stdout.write(f"   Total carbon entries: {final_count}")
            self.stdout.write(f"   Entries for establishment 2: {est_2_count}")
            self.stdout.write(f"   Entries for year 2025: {year_2025_count}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error: {e}"))
            import traceback

            self.stdout.write(traceback.format_exc())

    def get_or_create_carbon_source(self, name, category, unit, factor, description):
        """Get or create a carbon source with proper fields"""
        source, created = CarbonSource.objects.get_or_create(
            name=name,
            defaults={
                "category": category,
                "unit": unit,
                "default_emission_factor": factor,
                "description": description,
                "usda_verified": True,
                "usda_factors_based": True,
            },
        )
        return source

    def create_carbon_entry_sql(self, cursor, data):
        """Create carbon entry using raw SQL with all required fields"""
        now = timezone.now()

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
                data["establishment_id"],
                data["production_id"],
                data["created_by_id"],
                data["type"],
                data["source_id"],
                data["amount"],
                data["co2e_amount"],
                data["year"],
                data["description"],
                now,  # timestamp
                now,  # created_at
                now,  # updated_at
                True,  # usda_verified
                True,  # usda_factors_based
                "usda_verified",  # verification_status
                "USDA Agricultural Research Service",  # data_source
                "certified_project",  # verification_level
                0.95,  # trust_score
                data["co2e_amount"] * 0.95,  # effective_amount
                True,  # additionality_verified
                "Long-term sustainable agricultural practices",  # permanence_plan
                '{"baseline_year": 2020, "baseline_emissions": 100}',  # baseline_data (JSON)
                "passed",  # audit_status
                True,  # evidence_requirements_met
                True,  # documentation_complete
                "USDA verification documentation and field measurements",  # additionality_evidence
                "[]",  # evidence_photos (JSON)
                "[]",  # evidence_documents (JSON)
                data["external_verification_id"],
                "",  # iot_device_id
                data["methodology_template"],
                data["registry_verification_id"],
                data["baseline_scenario"],
                data["methodology_id"],
                data["monitoring_plan"],
                data["registry_name"],
                data["registry_submission_id"],
                data["verification_notes"],
                data["verification_report_url"],
                data["gps_coordinates"],
                data["financial_analysis"],
                data["detected_patterns"],
                "",  # third_party_verification_url
            ],
        )
