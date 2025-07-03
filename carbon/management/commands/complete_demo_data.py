"""
Management command to complete missing demo data components:
- Carbon Entries
- Carbon Offset Purchases  
- IoT Devices and Data Points
- History Scans (QR code scans)
- Product Reviews
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import datetime, timedelta
import random

from carbon.models import (
    CarbonEntry, CarbonSource, CarbonOffsetProject, CarbonOffsetPurchase,
    IoTDevice, IoTDataPoint
)
from history.models import History, HistoryScan
from reviews.models import Review
from company.models import Company, Establishment
from product.models import Parcel
from users.constants import CONSUMER

User = get_user_model()

class Command(BaseCommand):
    help = 'Complete all missing demo data components for comprehensive Trazo showcase'

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('🔧 Completing comprehensive Trazo demo data...')
        )
        
        # Get demo entities
        try:
            user = User.objects.get(email='demo@trazo.io')
            company = Company.objects.get(name='GreenHarvest Agricultural Enterprises')
            establishments = Establishment.objects.filter(company=company)
            parcels = Parcel.objects.filter(establishment__company=company)
            published_productions = History.objects.filter(published=True, parcel__establishment__company=company)
            
            self.stdout.write(f'Found {parcels.count()} parcels and {published_productions.count()} published productions')
            
        except (User.DoesNotExist, Company.DoesNotExist):
            self.stdout.write(self.style.ERROR('❌ Demo data not found. Run seed_comprehensive_demo first.'))
            return

        # Create missing components
        self.create_carbon_sources()
        self.create_carbon_entries(published_productions, user)
        self.create_carbon_offset_data(company, user)
        self.create_iot_infrastructure(establishments, user)
        self.create_consumer_engagement_data(published_productions)
        
        self.stdout.write(self.style.SUCCESS('✅ Demo data completion finished!'))

    def create_carbon_sources(self):
        """Create comprehensive carbon sources for calculations"""
        self.stdout.write(self.style.SUCCESS('🌱 Creating carbon sources...'))
        
        sources_data = [
            # Emission sources
            ('Organic Fertilizer', 'fertilizer', 'kg', 0.45, 'USDA verified organic fertilizer emissions'),
            ('Renewable Diesel', 'fuel', 'liter', 2.1, 'B20 biodiesel blend emissions'),
            ('Grid Electricity', 'energy', 'kWh', 0.35, 'Grid electricity with renewable offset'),
            ('Product Transport', 'transport', 'km', 0.12, 'Product transportation emissions'),
            ('Packaging Materials', 'materials', 'kg', 1.8, 'Sustainable packaging materials'),
            ('Equipment Operation', 'equipment', 'hour', 8.5, 'Agricultural equipment operation'),
            ('Irrigation Systems', 'water', 'gallon', 0.002, 'Water pumping and distribution'),
            ('Post-Harvest Processing', 'processing', 'kg', 0.25, 'Post-harvest processing emissions'),
            
            # Sequestration sources (negative emissions)
            ('Cover Crop Sequestration', 'sequestration', 'hectare', -2.5, 'Cover crop carbon sequestration'),
            ('Compost Application', 'sequestration', 'hectare', -1.8, 'Compost soil carbon increase'),
            ('Precision Agriculture', 'efficiency', 'hectare', -0.5, 'Precision agriculture efficiency gains'),
            ('Renewable Energy Offset', 'renewable', 'kWh', -0.8, 'On-site renewable energy offset'),
            ('No-Till Practices', 'sequestration', 'hectare', -3.2, 'No-till soil carbon sequestration'),
            ('Integrated Pest Management', 'efficiency', 'hectare', -0.3, 'IPM chemical reduction benefits')
        ]
        
        created_count = 0
        for name, category, unit, factor, description in sources_data:
            source, created = CarbonSource.objects.get_or_create(
                name=name,
                defaults={
                    'category': category,
                    'unit': unit,
                    'default_emission_factor': factor,
                    'description': description,
                    'usda_verified': True,
                    'usda_factors_based': True
                }
            )
            if created:
                created_count += 1
        
        self.stdout.write(f'✅ Created {created_count} carbon sources')

    def create_carbon_entries(self, productions, user):
        """Create comprehensive carbon entries for all published productions"""
        self.stdout.write(self.style.SUCCESS('📊 Creating carbon entries...'))
        
        # Clear existing entries for clean data
        CarbonEntry.objects.filter(production__in=productions).delete()
        
        sources = {source.name: source for source in CarbonSource.objects.all()}
        
        total_entries = 0
        for production in productions:
            parcel_area = production.parcel.area
            
            # Base emissions per production
            emission_data = [
                ('Organic Fertilizer', parcel_area * 45, parcel_area * 35),
                ('Renewable Diesel', parcel_area * 35, parcel_area * 28),
                ('Grid Electricity', parcel_area * 150, parcel_area * 95),
                ('Product Transport', parcel_area * 25, parcel_area * 18),
                ('Packaging Materials', parcel_area * 12, parcel_area * 8),
                ('Equipment Operation', parcel_area * 25, parcel_area * 45),
                ('Irrigation Systems', parcel_area * 8500, parcel_area * 12),
                ('Post-Harvest Processing', parcel_area * 180, parcel_area * 25)
            ]
            
            # Sequestration activities
            sequestration_data = [
                ('Cover Crop Sequestration', parcel_area * 0.8, parcel_area * 1.2),
                ('Compost Application', parcel_area * 2.5, parcel_area * 2.8),
                ('Precision Agriculture', parcel_area, parcel_area * 0.8),
                ('Renewable Energy Offset', parcel_area * 100, parcel_area * 65),
                ('No-Till Practices', parcel_area * 0.6, parcel_area * 1.5),
                ('Integrated Pest Management', parcel_area * 0.4, parcel_area * 0.2)
            ]
            
            # Create emission entries
            for source_name, amount, cost in emission_data:
                if source_name in sources:
                    source = sources[source_name]
                    co2e_amount = amount * source.default_emission_factor
                    
                    CarbonEntry.objects.create(
                        establishment=production.parcel.establishment,
                        production=production,
                        created_by=user,
                        type='emission',
                        source=source,
                        amount=amount,
                        co2e_amount=co2e_amount,
                        year=production.start_date.year,
                        description=f'{source_name} for {production.name}',
                        usda_verified=True,
                        usda_factors_based=True,
                        verification_status='usda_verified',
                        data_source='USDA Agricultural Research Service',
                        timestamp=production.start_date + timedelta(days=random.randint(30, 300))
                    )
                    total_entries += 1
            
            # Create sequestration entries
            for source_name, amount, cost in sequestration_data:
                if source_name in sources:
                    source = sources[source_name]
                    co2e_amount = amount * source.default_emission_factor  # Negative value
                    
                    CarbonEntry.objects.create(
                        establishment=production.parcel.establishment,
                        production=production,
                        created_by=user,
                        type='offset',
                        source=source,
                        amount=amount,
                        co2e_amount=co2e_amount,
                        year=production.start_date.year,
                        description=f'{source_name} for {production.name}',
                        usda_verified=True,
                        usda_factors_based=True,
                        verification_status='usda_verified',
                        data_source='USDA Agricultural Research Service',
                        timestamp=production.start_date + timedelta(days=random.randint(30, 300))
                    )
                    total_entries += 1
        
        self.stdout.write(f'✅ Created {total_entries} carbon entries')

    def create_carbon_offset_data(self, company, user):
        """Create carbon offset projects and purchases"""
        self.stdout.write(self.style.SUCCESS('🌳 Creating carbon offset data...'))
        
        # Create offset projects
        projects_data = [
            {
                'name': 'California Central Valley Reforestation Initiative',
                'description': 'Large-scale reforestation project in the Central Valley focusing on native oak and riparian species restoration.',
                'project_type': 'reforestation',
                'location': 'Central Valley, California',
                'total_credits_available': 50000,
                'price_per_credit': 25.50,
                'verification_standard': 'Verified Carbon Standard (VCS)',
                'certification_body': 'Verra',
                'start_date': timezone.now().date() - timedelta(days=365),
                'end_date': timezone.now().date() + timedelta(days=2555),  # ~7 years
                'usda_verified': True
            },
            {
                'name': 'Sustainable Agriculture Carbon Sequestration Program',
                'description': 'Soil carbon sequestration through regenerative agriculture practices across 10,000 acres of farmland.',
                'project_type': 'soil_sequestration',
                'location': 'Salinas Valley, California',
                'total_credits_available': 25000,
                'price_per_credit': 32.75,
                'verification_standard': 'Climate Action Reserve (CAR)',
                'certification_body': 'Climate Action Reserve',
                'start_date': timezone.now().date() - timedelta(days=180),
                'end_date': timezone.now().date() + timedelta(days=1825),  # 5 years
                'usda_verified': True
            },
            {
                'name': 'California Renewable Energy Cooperative',
                'description': 'Community solar and wind energy project providing renewable electricity to agricultural operations.',
                'project_type': 'renewable_energy',
                'location': 'Fresno County, California',
                'total_credits_available': 75000,
                'price_per_credit': 18.25,
                'verification_standard': 'Gold Standard',
                'certification_body': 'Gold Standard Foundation',
                'start_date': timezone.now().date() - timedelta(days=90),
                'end_date': timezone.now().date() + timedelta(days=3650),  # 10 years
                'usda_verified': False
            }
        ]
        
        projects_created = 0
        for project_data in projects_data:
            project, created = CarbonOffsetProject.objects.get_or_create(
                name=project_data['name'],
                defaults=project_data
            )
            if created:
                projects_created += 1
        
        # Create offset purchases for the company
        purchases_created = 0
        for project in CarbonOffsetProject.objects.all():
            # Purchase different amounts from each project
            credits_purchased = random.randint(100, 500)
            total_cost = credits_purchased * float(project.price_per_credit)
            
            purchase, created = CarbonOffsetPurchase.objects.get_or_create(
                company=company,
                project=project,
                defaults={
                    'purchased_by': user,
                    'credits_purchased': credits_purchased,
                    'total_cost': total_cost,
                    'purchase_date': timezone.now().date() - timedelta(days=random.randint(7, 90)),
                    'retirement_date': timezone.now().date() + timedelta(days=random.randint(30, 180)),
                    'certificate_number': f'OFFSET-{company.id}-{project.id}-{random.randint(10000, 99999)}',
                    'notes': f'Carbon offset purchase to achieve net-zero goals for {company.name} agricultural operations.'
                }
            )
            if created:
                purchases_created += 1
        
        self.stdout.write(f'✅ Created {projects_created} offset projects and {purchases_created} purchases')

    def create_iot_infrastructure(self, establishments, user):
        """Create IoT devices and data points for precision agriculture"""
        self.stdout.write(self.style.SUCCESS('📱 Creating IoT infrastructure...'))
        
        devices_created = 0
        data_points_created = 0
        
        for establishment in establishments:
            # Create different types of IoT devices per establishment
            device_types = [
                {
                    'name': f'{establishment.name} - Soil Moisture Network',
                    'device_type': 'soil_sensor',
                    'description': 'Network of wireless soil moisture and temperature sensors across all parcels',
                    'manufacturer': 'AgriSense Pro',
                    'model': 'SoilMaster 3000',
                    'metrics': ['soil_moisture', 'soil_temperature', 'soil_ph', 'electrical_conductivity']
                },
                {
                    'name': f'{establishment.name} - Weather Station',
                    'device_type': 'weather_station',
                    'description': 'Advanced weather monitoring station with climate tracking capabilities',
                    'manufacturer': 'WeatherTech Agriculture',
                    'model': 'ClimateGuard Pro',
                    'metrics': ['temperature', 'humidity', 'wind_speed', 'rainfall', 'solar_radiation', 'barometric_pressure']
                },
                {
                    'name': f'{establishment.name} - Irrigation Controller',
                    'device_type': 'irrigation_control',
                    'description': 'Smart irrigation system with automated water management and efficiency tracking',
                    'manufacturer': 'HydroSmart Systems',
                    'model': 'AquaFlow 2024',
                    'metrics': ['water_flow_rate', 'water_pressure', 'irrigation_duration', 'water_usage_total']
                },
                {
                    'name': f'{establishment.name} - Carbon Monitoring System',
                    'device_type': 'carbon_monitor',
                    'description': 'Real-time carbon flux monitoring and soil CO2 measurement system',
                    'manufacturer': 'CarbonTrack Solutions',
                    'model': 'EcoMonitor X1',
                    'metrics': ['soil_co2_flux', 'carbon_sequestration_rate', 'organic_matter_content']
                }
            ]
            
            for device_data in device_types:
                device, created = IoTDevice.objects.get_or_create(
                    name=device_data['name'],
                    establishment=establishment,
                    defaults={
                        'device_type': device_data['device_type'],
                        'description': device_data['description'],
                        'manufacturer': device_data['manufacturer'],
                        'model': device_data['model'],
                        'serial_number': f'{device_data["device_type"].upper()}-{random.randint(100000, 999999)}',
                        'installation_date': timezone.now().date() - timedelta(days=random.randint(30, 365)),
                        'last_maintenance': timezone.now().date() - timedelta(days=random.randint(7, 90)),
                        'is_active': True,
                        'battery_level': random.randint(75, 100),
                        'signal_strength': random.randint(85, 100),
                        'firmware_version': f'v{random.randint(1,3)}.{random.randint(0,9)}.{random.randint(0,9)}',
                        'created_by': user
                    }
                )
                if created:
                    devices_created += 1
                    
                    # Create historical data points for each device
                    for days_ago in range(30, 0, -1):  # Last 30 days
                        timestamp = timezone.now() - timedelta(days=days_ago, hours=random.randint(8, 18))
                        
                        for metric in device_data['metrics']:
                            # Generate realistic values based on metric type
                            value = self.generate_realistic_iot_value(metric, timestamp)
                            
                            IoTDataPoint.objects.create(
                                device=device,
                                metric_name=metric,
                                value=value,
                                timestamp=timestamp,
                                unit=self.get_metric_unit(metric),
                                quality_score=random.uniform(0.85, 1.0)
                            )
                            data_points_created += 1
        
        self.stdout.write(f'✅ Created {devices_created} IoT devices and {data_points_created} data points')

    def generate_realistic_iot_value(self, metric, timestamp):
        """Generate realistic IoT sensor values based on metric type and seasonality"""
        base_values = {
            'soil_moisture': random.uniform(25, 45),  # Percentage
            'soil_temperature': random.uniform(15, 25),  # Celsius
            'soil_ph': random.uniform(6.2, 7.5),
            'electrical_conductivity': random.uniform(0.5, 2.5),  # mS/cm
            'temperature': random.uniform(10, 30),  # Celsius
            'humidity': random.uniform(40, 80),  # Percentage
            'wind_speed': random.uniform(0, 15),  # km/h
            'rainfall': random.uniform(0, 5) if random.random() < 0.3 else 0,  # mm
            'solar_radiation': random.uniform(200, 800),  # W/m²
            'barometric_pressure': random.uniform(1010, 1030),  # hPa
            'water_flow_rate': random.uniform(10, 50),  # L/min
            'water_pressure': random.uniform(2.0, 4.5),  # bar
            'irrigation_duration': random.randint(30, 180),  # minutes
            'water_usage_total': random.uniform(100, 500),  # liters
            'soil_co2_flux': random.uniform(-2.5, 5.0),  # µmol CO2 m⁻² s⁻¹
            'carbon_sequestration_rate': random.uniform(0.1, 2.0),  # tCO2/ha/year
            'organic_matter_content': random.uniform(2.5, 8.0)  # Percentage
        }
        
        return base_values.get(metric, random.uniform(0, 100))

    def get_metric_unit(self, metric):
        """Get the appropriate unit for each metric"""
        units = {
            'soil_moisture': '%',
            'soil_temperature': '°C',
            'soil_ph': 'pH',
            'electrical_conductivity': 'mS/cm',
            'temperature': '°C',
            'humidity': '%',
            'wind_speed': 'km/h',
            'rainfall': 'mm',
            'solar_radiation': 'W/m²',
            'barometric_pressure': 'hPa',
            'water_flow_rate': 'L/min',
            'water_pressure': 'bar',
            'irrigation_duration': 'minutes',
            'water_usage_total': 'liters',
            'soil_co2_flux': 'µmol CO2 m⁻² s⁻¹',
            'carbon_sequestration_rate': 'tCO2/ha/year',
            'organic_matter_content': '%'
        }
        return units.get(metric, 'units')

    def create_consumer_engagement_data(self, productions):
        """Create QR code scans and product reviews from consumers"""
        self.stdout.write(self.style.SUCCESS('👥 Creating consumer engagement data...'))
        
        # Create consumer users
        consumer_users_data = [
            ('Emily', 'Chen', 'emily.chen@email.com'),
            ('Michael', 'Rodriguez', 'mike.rodriguez@email.com'),
            ('Sarah', 'Johnson', 'sarah.j@email.com'),
            ('David', 'Kim', 'david.kim@email.com'),
            ('Lisa', 'Thompson', 'lisa.t@email.com'),
            ('James', 'Wilson', 'james.w@email.com'),
            ('Maria', 'Garcia', 'maria.garcia@email.com'),
            ('Robert', 'Brown', 'robert.brown@email.com'),
            ('Jennifer', 'Davis', 'jennifer.davis@email.com'),
            ('Christopher', 'Miller', 'chris.miller@email.com')
        ]
        
        consumer_users = []
        consumers_created = 0
        for first, last, email in consumer_users_data:
            consumer, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'is_active': True,
                    'user_type': CONSUMER
                }
            )
            if created:
                consumer.set_password('consumer123')
                consumer.save()
                consumers_created += 1
            consumer_users.append(consumer)
        
        # Create QR code scans for recent weeks (last 14 days)
        scans_created = 0
        for production in productions:
            # Generate random number of scans per production (realistic engagement)
            num_scans = random.randint(15, 45)  # High engagement for demo
            
            for _ in range(num_scans):
                scan_date = timezone.now() - timedelta(
                    days=random.randint(1, 14),
                    hours=random.randint(8, 22),
                    minutes=random.randint(0, 59)
                )
                
                scanner = random.choice(consumer_users) if random.random() < 0.7 else None  # 70% logged in users
                
                HistoryScan.objects.create(
                    history=production,
                    user=scanner,  # Can be None for anonymous scans
                    scan_timestamp=scan_date,
                    location_lat=random.uniform(36.0, 37.5),  # California Central Valley
                    location_lon=random.uniform(-121.0, -119.0),
                    device_info=random.choice([
                        'iPhone 15 Pro - iOS 17.2',
                        'Samsung Galaxy S24 - Android 14',
                        'iPhone 14 - iOS 17.1',
                        'Google Pixel 8 - Android 14',
                        'iPhone 13 - iOS 17.0'
                    ]),
                    ip_address=f'192.168.{random.randint(1,255)}.{random.randint(1,255)}',
                    user_agent='TrazoMobile/2.1.0'
                )
                scans_created += 1
        
        # Create product reviews for finished productions
        reviews_created = 0
        review_templates = [
            ("Exceptional quality and transparency!", 5, "Love being able to see the entire growing process and carbon footprint. The {product} was fresh and delicious!"),
            ("Great sustainable practices", 5, "Impressed by the commitment to carbon-neutral farming. Will definitely purchase again."),
            ("Fresh and responsibly grown", 4, "Product quality is excellent. Appreciate the detailed sustainability information."),
            ("Transparency is amazing", 5, "Finally, a company that shows exactly how their {product} is grown. Carbon tracking is the future!"),
            ("Premium quality produce", 4, "Outstanding {product} with complete traceability. Worth the premium price."),
            ("Sustainable agriculture done right", 5, "This is how all farming should be done. Transparent, sustainable, and high quality."),
            ("Excellent carbon tracking", 5, "Being able to see the carbon footprint gives me confidence in my purchase decisions."),
            ("Farm-to-table transparency", 4, "Love the detailed production information. Fresh and sustainably grown {product}."),
            ("Outstanding quality", 4, "Premium {product} with full sustainability credentials. Highly recommend!"),
            ("Carbon-conscious choice", 5, "Perfect for environmentally conscious consumers. Great quality and full transparency.")
        ]
        
        for production in productions.filter(published=True):
            # 60% chance of having reviews
            if random.random() < 0.6:
                num_reviews = random.randint(2, 8)
                
                for _ in range(num_reviews):
                    reviewer = random.choice(consumer_users)
                    title, rating, content_template = random.choice(review_templates)
                    
                    # Get product name for content personalization
                    product_name = production.parcel.product.name if production.parcel.product else "produce"
                    content = content_template.format(product=product_name.lower())
                    
                    review_date = timezone.now() - timedelta(
                        days=random.randint(1, 30),
                        hours=random.randint(9, 21)
                    )
                    
                    Review.objects.create(
                        production=production,
                        reviewer=reviewer,
                        title=title,
                        content=content,
                        rating=rating,
                        created_at=review_date,
                        verified_purchase=random.choice([True, True, False])  # 67% verified
                    )
                    reviews_created += 1
        
        self.stdout.write(f'✅ Created {consumers_created} consumers, {scans_created} QR scans, and {reviews_created} reviews')