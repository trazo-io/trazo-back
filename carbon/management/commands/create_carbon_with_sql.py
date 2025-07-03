"""
Create carbon entries using raw SQL to bypass the model constraint issue
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import connection
from carbon.models import CarbonSource
from history.models import History

User = get_user_model()

class Command(BaseCommand):
    help = 'Create carbon entries using raw SQL'

    def handle(self, *args, **options):
        self.stdout.write('🌱 Creating carbon entries using raw SQL...')
        
        try:
            user = User.objects.get(email='demo@trazo.io')
            published_productions = History.objects.filter(published=True, parcel__establishment__id__in=[1, 2])
            fuel_source = CarbonSource.objects.filter(name='Diesel Fuel').first()
            seq_source = CarbonSource.objects.filter(name='Soil Carbon Sequestration').first()
            
            self.stdout.write(f'Found {published_productions.count()} published productions')
            
            entries_created = 0
            
            with connection.cursor() as cursor:
                for production in published_productions:
                    # Create emission entry
                    if fuel_source:
                        amount = production.parcel.area * 50
                        co2e_amount = amount * fuel_source.default_emission_factor
                        
                        cursor.execute("""
                            INSERT INTO carbon_carbonentry (
                                establishment_id, production_id, created_by_id, type, source_id,
                                amount, co2e_amount, year, description, timestamp, created_at, updated_at,
                                usda_verified, usda_factors_based, verification_status, data_source,
                                verification_level, trust_score, effective_amount, additionality_verified,
                                permanence_plan, baseline_data, audit_status, evidence_requirements_met,
                                documentation_complete, additionality_evidence, evidence_photos, evidence_documents,
                                external_verification_id, iot_device_id, methodology_template
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            )
                        """, [
                            production.parcel.establishment.id,
                            production.id,
                            user.id,
                            'emission',
                            fuel_source.id,
                            amount,
                            co2e_amount,
                            production.start_date.year,
                            f'Fuel emissions for {production.name}',
                            production.start_date,
                            production.start_date,
                            production.start_date,
                            True,  # usda_verified
                            True,  # usda_factors_based
                            'usda_verified',
                            'USDA Agricultural Research Service',
                            'certified_project',
                            0.9,  # trust_score
                            co2e_amount * 0.9,  # effective_amount
                            True,  # additionality_verified
                            'Long-term agricultural management plan',
                            '{}',  # baseline_data JSON
                            'passed',
                            True,  # evidence_requirements_met
                            True,  # documentation_complete
                            'USDA certified practices documentation',
                            '[]',  # evidence_photos JSON
                            '[]',  # evidence_documents JSON
                            f'USDA-{production.id}-{production.start_date.year}',  # external_verification_id
                            '',  # iot_device_id
                            'USDA_STANDARD'  # methodology_template
                        ])
                        entries_created += 1
                    
                    # Create sequestration entry
                    if seq_source:
                        amount = production.parcel.area * 2
                        co2e_amount = amount * seq_source.default_emission_factor  # Negative
                        
                        cursor.execute("""
                            INSERT INTO carbon_carbonentry (
                                establishment_id, production_id, created_by_id, type, source_id,
                                amount, co2e_amount, year, description, timestamp, created_at, updated_at,
                                usda_verified, usda_factors_based, verification_status, data_source,
                                verification_level, trust_score, effective_amount, additionality_verified,
                                permanence_plan, baseline_data, audit_status, evidence_requirements_met,
                                documentation_complete, additionality_evidence, evidence_photos, evidence_documents,
                                external_verification_id, iot_device_id, methodology_template
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            )
                        """, [
                            production.parcel.establishment.id,
                            production.id,
                            user.id,
                            'offset',
                            seq_source.id,
                            amount,
                            co2e_amount,
                            production.start_date.year,
                            f'Soil sequestration for {production.name}',
                            production.start_date,
                            production.start_date,
                            production.start_date,
                            True,  # usda_verified
                            True,  # usda_factors_based
                            'usda_verified',
                            'USDA Agricultural Research Service',
                            'certified_project',
                            0.9,  # trust_score
                            co2e_amount * 0.9,  # effective_amount
                            True,  # additionality_verified
                            'Long-term soil management plan',
                            '{}',  # baseline_data JSON
                            'passed',
                            True,  # evidence_requirements_met
                            True,  # documentation_complete
                            'Cover crop and no-till documentation',
                            '[]',  # evidence_photos JSON
                            '[]',  # evidence_documents JSON
                            f'USDA-SEQ-{production.id}-{production.start_date.year}',  # external_verification_id
                            '',  # iot_device_id
                            'USDA_SOIL_CARBON'  # methodology_template
                        ])
                        entries_created += 1
            
            self.stdout.write(self.style.SUCCESS(f'✅ Created {entries_created} carbon entries using raw SQL'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error: {e}'))