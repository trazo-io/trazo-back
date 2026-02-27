"""
Simple command to create basic carbon entries for demo productions
"""

import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from carbon.models import CarbonEntry, CarbonSource
from company.models import Company
from history.models import History

User = get_user_model()


class Command(BaseCommand):
    help = "Create simple carbon entries for published productions"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("🌱 Creating simple carbon entries..."))

        # Get demo entities
        try:
            user = User.objects.get(email="demo@trazo.io")
            company = Company.objects.get(name="GreenHarvest Agricultural Enterprises")
            published_productions = History.objects.filter(published=True, parcel__establishment__company=company)

            self.stdout.write(f"Found {published_productions.count()} published productions")

        except (User.DoesNotExist, Company.DoesNotExist):
            self.stdout.write(self.style.ERROR("❌ Demo data not found."))
            return

        # Create simple carbon sources first
        self.create_basic_carbon_sources()

        # Create carbon entries with minimal required fields
        entries_created = 0
        for production in published_productions:
            try:
                # Create emission entry
                emission_source = CarbonSource.objects.filter(category="fuel").first()
                if emission_source:
                    amount = production.parcel.area * 50  # 50 kg per hectare
                    co2e_amount = amount * emission_source.default_emission_factor

                    # Provide all required fields with defaults
                    CarbonEntry.objects.create(
                        establishment=production.parcel.establishment,
                        production=production,
                        created_by=user,
                        type="emission",
                        source=emission_source,
                        amount=amount,
                        co2e_amount=co2e_amount,
                        year=production.start_date.year,
                        description=f"Fuel emissions for {production.name}",
                        usda_verified=True,
                        usda_factors_based=True,
                        verification_status="usda_verified",
                        data_source="USDA Agricultural Research Service",
                        verification_level="certified_project",
                        trust_score=0.9,
                        effective_amount=co2e_amount * 0.9,
                        additionality_verified=True,
                        permanence_plan="Long-term agricultural management plan",
                        baseline_data={"year": production.start_date.year, "baseline_emissions": amount * 1.2},
                        audit_status="passed",
                        evidence_requirements_met=True,
                        documentation_complete=True,
                        additionality_evidence="USDA certified practices documentation",
                        evidence_photos=[],
                        evidence_documents=[],
                        external_verification_id=f"USDA-{production.id}-{random.randint(10000, 99999)}",
                    )
                    entries_created += 1

                # Create offset entry
                offset_source = CarbonSource.objects.filter(category="sequestration").first()
                if offset_source:
                    amount = production.parcel.area * 2  # 2 tons sequestered per hectare
                    co2e_amount = amount * offset_source.default_emission_factor  # Negative value

                    CarbonEntry.objects.create(
                        establishment=production.parcel.establishment,
                        production=production,
                        created_by=user,
                        type="offset",
                        source=offset_source,
                        amount=amount,
                        co2e_amount=co2e_amount,
                        year=production.start_date.year,
                        description=f"Soil carbon sequestration for {production.name}",
                        usda_verified=True,
                        usda_factors_based=True,
                        verification_status="usda_verified",
                        data_source="USDA Agricultural Research Service",
                        verification_level="certified_project",
                        trust_score=0.9,
                        effective_amount=co2e_amount * 0.9,
                        additionality_verified=True,
                        permanence_plan="Long-term soil management plan",
                        baseline_data={"year": production.start_date.year, "baseline_sequestration": 0},
                        audit_status="passed",
                        evidence_requirements_met=True,
                        documentation_complete=True,
                        additionality_evidence="Cover crop and no-till documentation",
                        evidence_photos=[],
                        evidence_documents=[],
                        external_verification_id=f"USDA-SEQ-{production.id}-{random.randint(10000, 99999)}",
                    )
                    entries_created += 1

            except Exception as e:
                self.stdout.write(self.style.WARNING(f"⚠️  Could not create entries for {production.name}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"✅ Created {entries_created} carbon entries"))

    def create_basic_carbon_sources(self):
        """Create basic carbon sources if they don't exist"""
        sources_data = [
            {
                "name": "Diesel Fuel",
                "category": "fuel",
                "unit": "liters",
                "default_emission_factor": 2.70,
                "description": "Diesel fuel for agricultural equipment",
                "usda_verified": True,
                "usda_factors_based": True,
            },
            {
                "name": "Soil Carbon Sequestration",
                "category": "sequestration",
                "unit": "hectares",
                "default_emission_factor": -2.5,  # Negative for sequestration
                "description": "Carbon sequestration through soil management",
                "usda_verified": True,
                "usda_factors_based": True,
            },
        ]

        sources_created = 0
        for source_data in sources_data:
            source, created = CarbonSource.objects.get_or_create(name=source_data["name"], defaults=source_data)
            if created:
                sources_created += 1

        if sources_created > 0:
            self.stdout.write(f"✅ Created {sources_created} carbon sources")
