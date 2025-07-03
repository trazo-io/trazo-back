"""
Quick fix for carbon data to create proper breakdown with correct field names
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from carbon.models import CarbonEntry, CarbonSource, CarbonOffsetProject, CarbonOffsetPurchase
from company.models import Establishment
from decimal import Decimal
import json
import random

User = get_user_model()

class Command(BaseCommand):
    help = 'Quick fix for carbon breakdown with correct model fields'

    def handle(self, *args, **options):
        self.stdout.write('⚡ Quick fixing carbon breakdown...')
        
        try:
            user = User.objects.get(email='demo@trazo.io')
            
            # 1. Update existing sources with better categories
            self.update_source_categories()
            
            # 2. Create diverse carbon entries with correct fields
            self.create_quick_carbon_entries(user)
            
            # 3. Fix offset purchases
            self.create_quick_offsets(user)
            
            # 4. Verify results
            self.verify_quick_results()
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error: {e}'))
            import traceback
            self.stdout.write(traceback.format_exc())

    def update_source_categories(self):
        """Update existing source categories for better breakdown"""
        self.stdout.write('🔄 Updating source categories...')
        
        # Update existing sources
        try:
            fuel_source = CarbonSource.objects.get(name='Demo Fuel Source')
            fuel_source.category = 'fuel'
            fuel_source.save()
            
            equipment_source = CarbonSource.objects.get(name='Equipment Operation')
            equipment_source.category = 'equipment'
            equipment_source.save()
            
            production_source = CarbonSource.objects.get(name='Production Activity')
            production_source.category = 'processing'
            production_source.save()
            
            weather_source = CarbonSource.objects.get(name='Weather Response')
            weather_source.category = 'irrigation'
            weather_source.save()
            
            general_source = CarbonSource.objects.get(name='General Activity')
            general_source.category = 'transport'
            general_source.save()
            
            self.stdout.write('   ✅ Updated existing source categories')
            
        except Exception as e:
            self.stdout.write(f'   ⚠️  Error updating sources: {e}')

    def create_quick_carbon_entries(self, user):
        """Create diverse carbon entries using correct field names"""
        self.stdout.write('📊 Creating diverse carbon entries...')
        
        # Create additional sources first
        new_sources = [
            ('Fertilizer Application', 'fertilizer', 'kg', 8.5),
            ('Electricity Consumption', 'electricity', 'kWh', 0.35),
            ('Product Transport', 'transport', 'km', 0.12),
            ('Packaging Materials', 'materials', 'kg', 1.8),
            ('Cover Crop Carbon', 'sequestration', 'hectare', -2.5),
            ('Solar Energy Credits', 'renewable_energy', 'kWh', -0.35),
        ]
        
        sources_created = 0
        for name, category, unit, factor in new_sources:
            source, created = CarbonSource.objects.get_or_create(
                name=name,
                defaults={
                    'category': category,
                    'unit': unit,
                    'default_emission_factor': factor,
                    'description': f'{category.title()} carbon impact',
                    'usda_verified': True,
                    'usda_factors_based': factor > 0
                }
            )
            if created:
                sources_created += 1
        
        self.stdout.write(f'   ✅ Created {sources_created} new sources')
        
        # Create entries for each establishment
        establishments = Establishment.objects.all()
        entries_created = 0
        
        for establishment in establishments:
            # Fertilizer entries
            fertilizer_source = CarbonSource.objects.get(name='Fertilizer Application')
            for month in [3, 6, 9]:  # Seasonal applications
                for year in [2024, 2025]:
                    entry = CarbonEntry.objects.create(
                        establishment=establishment,
                        created_by=user,
                        type='emission',
                        source=fertilizer_source,
                        amount=random.uniform(300, 800),
                        co2e_amount=random.uniform(2500, 6800),
                        year=year,
                        timestamp=timezone.datetime(year, month, 15).date(),
                        description=f'Seasonal fertilizer application - {year}-{month:02d}',
                        usda_verified=True,
                        usda_factors_based=True,
                        verification_status='verified',
                        data_source='USDA Agricultural Research Service',
                        verification_level='certified_project',
                        trust_score=0.95,
                        effective_amount=random.uniform(2375, 6460),
                        additionality_verified=True,
                        permanence_plan='Standard agricultural practices',
                        baseline_data=json.dumps({'type': 'fertilizer'}),
                        audit_status='passed',
                        methodology_template='USDA_FERTILIZER',
                        evidence_requirements_met=True,
                        documentation_complete=True,
                        additionality_evidence='USDA-verified fertilizer application',
                        evidence_photos=json.dumps([]),
                        evidence_documents=json.dumps([]),
                        registry_verification_id=f'FERT-{establishment.id}-{year}-{month}',
                        third_party_verification_url='https://usda.gov/verify'
                    )
                    entries_created += 1
            
            # Electricity entries (monthly)
            electricity_source = CarbonSource.objects.get(name='Electricity Consumption')
            for month in range(1, 13):
                for year in [2024, 2025]:
                    entry = CarbonEntry.objects.create(
                        establishment=establishment,
                        created_by=user,
                        type='emission',
                        source=electricity_source,
                        amount=random.uniform(2000, 5000),
                        co2e_amount=random.uniform(700, 1750),
                        year=year,
                        timestamp=timezone.datetime(year, month, 1).date(),
                        description=f'Monthly electricity consumption - {year}-{month:02d}',
                        usda_verified=False,
                        usda_factors_based=False,
                        verification_status='utility_verified',
                        data_source='Utility Company Records',
                        verification_level='utility_verified',
                        trust_score=0.90,
                        effective_amount=random.uniform(665, 1663),
                        additionality_verified=True,
                        permanence_plan='Standard utility consumption',
                        baseline_data=json.dumps({'type': 'electricity'}),
                        audit_status='passed',
                        methodology_template='UTILITY_CONSUMPTION',
                        evidence_requirements_met=True,
                        documentation_complete=True,
                        additionality_evidence='Utility billing records',
                        evidence_photos=json.dumps([]),
                        evidence_documents=json.dumps([]),
                        registry_verification_id=f'ELEC-{establishment.id}-{year}-{month}',
                        third_party_verification_url='https://utility.example.com/verify'
                    )
                    entries_created += 1
            
            # Transportation entries
            transport_source = CarbonSource.objects.get(name='Product Transport')
            for quarter in range(1, 5):
                for year in [2024, 2025]:
                    month = quarter * 3
                    entry = CarbonEntry.objects.create(
                        establishment=establishment,
                        created_by=user,
                        type='emission',
                        source=transport_source,
                        amount=random.uniform(800, 2000),
                        co2e_amount=random.uniform(96, 240),
                        year=year,
                        timestamp=timezone.datetime(year, month, 15).date(),
                        description=f'Quarterly product transportation - Q{quarter} {year}',
                        usda_verified=False,
                        usda_factors_based=False,
                        verification_status='gps_verified',
                        data_source='GPS Fleet Tracking',
                        verification_level='automated_monitoring',
                        trust_score=0.85,
                        effective_amount=random.uniform(91, 228),
                        additionality_verified=True,
                        permanence_plan='Transportation tracking',
                        baseline_data=json.dumps({'type': 'transport'}),
                        audit_status='passed',
                        methodology_template='TRANSPORT_TRACKING',
                        evidence_requirements_met=True,
                        documentation_complete=True,
                        additionality_evidence='GPS tracking records',
                        evidence_photos=json.dumps([]),
                        evidence_documents=json.dumps([]),
                        registry_verification_id=f'TRAN-{establishment.id}-{year}-Q{quarter}',
                        third_party_verification_url='https://fleet.example.com/verify'
                    )
                    entries_created += 1
            
            # Sequestration entries (offsets)
            sequestration_source = CarbonSource.objects.get(name='Cover Crop Carbon')
            for year in [2024, 2025]:
                entry = CarbonEntry.objects.create(
                    establishment=establishment,
                    created_by=user,
                    type='sequestration',
                    source=sequestration_source,
                    amount=random.uniform(10, 30),
                    co2e_amount=random.uniform(-25, -75),  # Negative for sequestration
                    year=year,
                    timestamp=timezone.datetime(year, 6, 1).date(),
                    description=f'Annual cover crop carbon sequestration - {year}',
                    usda_verified=True,
                    usda_factors_based=True,
                    verification_status='verified',
                    data_source='USDA Soil Carbon Assessment',
                    verification_level='certified_project',
                    trust_score=0.88,
                    effective_amount=random.uniform(22, 66),
                    additionality_verified=True,
                    permanence_plan='Long-term soil carbon management',
                    baseline_data=json.dumps({'type': 'sequestration', 'hectares': random.uniform(10, 30)}),
                    audit_status='passed',
                    methodology_template='USDA_SOIL_CARBON',
                    evidence_requirements_met=True,
                    documentation_complete=True,
                    additionality_evidence='USDA soil carbon measurements',
                    evidence_photos=json.dumps([]),
                    evidence_documents=json.dumps([]),
                    registry_verification_id=f'SEQE-{establishment.id}-{year}',
                    third_party_verification_url='https://usda.gov/soil-carbon'
                )
                entries_created += 1
            
            # Renewable energy entries (offsets)
            renewable_source = CarbonSource.objects.get(name='Solar Energy Credits')
            for month in range(4, 11):  # Solar season
                for year in [2024, 2025]:
                    entry = CarbonEntry.objects.create(
                        establishment=establishment,
                        created_by=user,
                        type='offset',
                        source=renewable_source,
                        amount=random.uniform(1500, 4000),
                        co2e_amount=random.uniform(-525, -1400),  # Negative for offset
                        year=year,
                        timestamp=timezone.datetime(year, month, 1).date(),
                        description=f'Monthly solar energy generation - {year}-{month:02d}',
                        usda_verified=False,
                        usda_factors_based=False,
                        verification_status='meter_verified',
                        data_source='Solar Energy Meters',
                        verification_level='automated_monitoring',
                        trust_score=0.92,
                        effective_amount=random.uniform(497, 1323),
                        additionality_verified=True,
                        permanence_plan='On-farm renewable energy generation',
                        baseline_data=json.dumps({'type': 'solar', 'kwh': random.uniform(1500, 4000)}),
                        audit_status='passed',
                        methodology_template='SOLAR_GENERATION',
                        evidence_requirements_met=True,
                        documentation_complete=True,
                        additionality_evidence='Solar meter readings',
                        evidence_photos=json.dumps([]),
                        evidence_documents=json.dumps([]),
                        registry_verification_id=f'SOLR-{establishment.id}-{year}-{month}',
                        third_party_verification_url='https://solar.example.com/verify'
                    )
                    entries_created += 1
        
        self.stdout.write(f'   ✅ Created {entries_created} diverse carbon entries')

    def create_quick_offsets(self, user):
        """Create offset purchases quickly"""
        self.stdout.write('💰 Creating offset purchases...')
        
        # Clean existing
        CarbonOffsetPurchase.objects.all().delete()
        
        # Create a simple offset project
        project, created = CarbonOffsetProject.objects.get_or_create(
            name='California Reforestation Project',
            defaults={
                'description': 'Forest conservation and reforestation initiative',
                'project_type': 'Forest Conservation',
                'certification_standard': 'VCS',
                'location': 'Northern California',
                'price_per_ton': Decimal('22.50'),
                'available_capacity': Decimal('5000.00')
            }
        )
        
        # Create offset source
        offset_source, created = CarbonSource.objects.get_or_create(
            name='Purchased Carbon Offsets',
            defaults={
                'category': 'purchased_offsets',
                'unit': 'tons_co2e',
                'default_emission_factor': -1.0,
                'description': 'Purchased carbon offset credits',
                'usda_verified': False,
                'usda_factors_based': False
            }
        )
        
        # Create purchases for each establishment
        establishments = Establishment.objects.all()
        purchases_created = 0
        
        for establishment in establishments:
            for year in [2024, 2025]:
                amount = Decimal(str(random.uniform(20, 60)))
                purchase = CarbonOffsetPurchase.objects.create(
                    project=project,
                    user=user,
                    amount=amount,
                    price_per_ton=project.price_per_ton,
                    total_price=amount * project.price_per_ton,
                    status='completed',
                    is_verified=True
                )
                
                # Create corresponding carbon entry
                entry = CarbonEntry.objects.create(
                    establishment=establishment,
                    created_by=user,
                    type='offset',
                    source=offset_source,
                    amount=float(amount),
                    co2e_amount=-float(amount),  # Negative for offset
                    year=year,
                    timestamp=timezone.datetime(year, 12, 1).date(),
                    description=f'Carbon offset purchase - {amount} tons CO2e',
                    usda_verified=False,
                    usda_factors_based=False,
                    verification_status='third_party_verified',
                    data_source='Carbon Offset Registry',
                    verification_level='certified_project',
                    trust_score=0.93,
                    effective_amount=float(amount),
                    additionality_verified=True,
                    permanence_plan='Forest conservation permanence guarantee',
                    baseline_data=json.dumps({'project': project.name, 'amount': float(amount)}),
                    audit_status='third_party_verified',
                    methodology_template='VCS_FOREST_CONSERVATION',
                    evidence_requirements_met=True,
                    documentation_complete=True,
                    additionality_evidence='Third-party verified forest conservation',
                    evidence_photos=json.dumps([]),
                    evidence_documents=json.dumps([]),
                    registry_verification_id=f'OFFS-{establishment.id}-{year}',
                    third_party_verification_url='https://registry.verra.org'
                )
                purchases_created += 1
        
        self.stdout.write(f'   ✅ Created {purchases_created} offset purchases')

    def verify_quick_results(self):
        """Verify the quick fix results"""
        self.stdout.write('🔍 Verifying results...')
        
        # Entry types
        types = CarbonEntry.objects.values('type').distinct()
        self.stdout.write('   📊 Entry Types:')
        for t in types:
            count = CarbonEntry.objects.filter(type=t['type']).count()
            total = sum([e.co2e_amount or 0 for e in CarbonEntry.objects.filter(type=t['type'])])
            self.stdout.write(f'     - {t["type"]}: {count} entries, {total:.2f} kg CO2e')
        
        # Categories
        categories = CarbonSource.objects.values('category').distinct()
        self.stdout.write('   📋 Categories:')
        for c in categories:
            count = CarbonEntry.objects.filter(source__category=c['category']).count()
            total = sum([e.co2e_amount or 0 for e in CarbonEntry.objects.filter(source__category=c['category'])])
            self.stdout.write(f'     - {c["category"]}: {count} entries, {total:.2f} kg CO2e')
        
        # Establishments
        establishments = Establishment.objects.all()
        self.stdout.write('   🏢 Establishments:')
        for est in establishments:
            total_entries = CarbonEntry.objects.filter(establishment=est).count()
            emissions = sum([e.co2e_amount for e in CarbonEntry.objects.filter(establishment=est, type='emission')])
            offsets = sum([abs(e.co2e_amount) for e in CarbonEntry.objects.filter(establishment=est, type__in=['offset', 'sequestration'])])
            net = emissions - offsets
            
            self.stdout.write(f'     {est.name}:')
            self.stdout.write(f'       - Total entries: {total_entries}')
            self.stdout.write(f'       - Emissions: {emissions:.2f} kg CO2e')
            self.stdout.write(f'       - Offsets: {offsets:.2f} kg CO2e')
            self.stdout.write(f'       - Net: {net:.2f} kg CO2e')
        
        # Offset purchases
        offset_count = CarbonOffsetPurchase.objects.count()
        self.stdout.write(f'   💰 Offset purchases: {offset_count}')
        
        self.stdout.write(self.style.SUCCESS('✅ Quick carbon fix complete'))