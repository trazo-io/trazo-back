"""
Simple command to add missing demo data components without complex model constraints
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import datetime, timedelta
import random

from carbon.models import CarbonOffsetProject, CarbonOffsetPurchase, IoTDevice, IoTDataPoint
from history.models import History, HistoryScan
from reviews.models import Review
from company.models import Company, Establishment
from users.constants import CONSUMER

User = get_user_model()

class Command(BaseCommand):
    help = 'Add missing demo data components (IoT, Reviews, Scans, Offsets)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🔧 Adding missing demo data components...'))
        
        # Get demo entities
        try:
            user = User.objects.get(email='demo@trazo.io')
            company = Company.objects.get(name='GreenHarvest Agricultural Enterprises')
            establishments = list(Establishment.objects.filter(company=company))
            published_productions = list(History.objects.filter(published=True, parcel__establishment__company=company))
            
            self.stdout.write(f'Found company with {len(establishments)} establishments and {len(published_productions)} published productions')
            
        except (User.DoesNotExist, Company.DoesNotExist):
            self.stdout.write(self.style.ERROR('❌ Demo data not found. Run seed_comprehensive_demo first.'))
            return

        # Add missing components one by one
        self.create_carbon_offset_data(company, user)
        self.create_iot_infrastructure(establishments, user)
        self.create_consumer_engagement_data(published_productions)
        
        self.stdout.write(self.style.SUCCESS('✅ Missing demo data components added!'))

    def create_carbon_offset_data(self, company, user):
        """Create carbon offset projects and purchases"""
        self.stdout.write(self.style.SUCCESS('🌳 Creating carbon offset data...'))
        
        # Create offset projects with correct field names
        projects_data = [
            {
                'name': 'California Central Valley Reforestation',
                'description': 'Large-scale reforestation project focusing on native oak restoration.',
                'project_type': 'reforestation',
                'location': 'Central Valley, California',
                'available_capacity': 50000,
                'price_per_ton': 25.50,
                'certification_standard': 'Verified Carbon Standard (VCS)'
            },
            {
                'name': 'Sustainable Agriculture Soil Carbon',
                'description': 'Soil carbon sequestration through regenerative agriculture practices.',
                'project_type': 'soil_sequestration',
                'location': 'Salinas Valley, California',
                'available_capacity': 25000,
                'price_per_ton': 32.75,
                'certification_standard': 'Climate Action Reserve (CAR)'
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
        
        # Create offset purchases with correct field names
        purchases_created = 0
        for project in CarbonOffsetProject.objects.all()[:2]:  # Limit to avoid overwhelming
            amount = random.randint(100, 500)
            price_per_ton = float(project.price_per_ton)
            total_price = amount * price_per_ton
            
            purchase, created = CarbonOffsetPurchase.objects.get_or_create(
                user=user,
                project=project,
                defaults={
                    'amount': amount,
                    'price_per_ton': price_per_ton,
                    'total_price': total_price,
                    'status': 'completed',
                    'is_verified': True
                }
            )
            if created:
                purchases_created += 1
        
        self.stdout.write(f'✅ Created {projects_created} offset projects and {purchases_created} purchases')

    def create_iot_infrastructure(self, establishments, user):
        """Create IoT devices and data points"""
        self.stdout.write(self.style.SUCCESS('📱 Creating IoT infrastructure...'))
        
        devices_created = 0
        data_points_created = 0
        
        for establishment in establishments:
            # Create 2 devices per establishment (using valid device_type choices)
            device_types = [
                {
                    'name': f'{establishment.name} - Soil Sensors',
                    'device_type': 'soil_moisture',
                    'manufacturer': 'AgriSense Pro',
                    'model': 'SoilMaster 3000'
                },
                {
                    'name': f'{establishment.name} - Weather Station',
                    'device_type': 'weather_station', 
                    'manufacturer': 'WeatherTech Agriculture',
                    'model': 'ClimateGuard Pro'
                }
            ]
            
            for device_data in device_types:
                device_id = f'{device_data["device_type"].upper()}-{random.randint(100000, 999999)}'
                device, created = IoTDevice.objects.get_or_create(
                    device_id=device_id,
                    establishment=establishment,
                    defaults={
                        'name': device_data['name'],
                        'device_type': device_data['device_type'],
                        'manufacturer': device_data['manufacturer'],
                        'model': device_data['model'],
                        'status': 'online',
                        'last_seen': timezone.now() - timedelta(hours=random.randint(1, 6)),
                        'battery_level': random.randint(75, 100),
                        'signal_strength': f'{random.randint(85, 100)}%',
                        'latitude': 36.7 + random.uniform(-0.5, 0.5),
                        'longitude': -119.8 + random.uniform(-0.5, 0.5),
                        'configuration': {
                            'sampling_interval': '15min',
                            'data_retention': '30days',
                            'alerts_enabled': True
                        }
                    }
                )
                if created:
                    devices_created += 1
                    
                    # Create 10 recent data points per device
                    for days_ago in range(10, 0, -1):
                        timestamp = timezone.now() - timedelta(days=days_ago, hours=random.randint(8, 18))
                        
                        # Create realistic sensor data
                        if device_data['device_type'] == 'soil_moisture':
                            data = {
                                'soil_moisture': random.uniform(25, 45),
                                'soil_temperature': random.uniform(15, 25),
                                'unit': '%',
                                'sensor_type': 'soil_moisture'
                            }
                        else:  # weather_station
                            data = {
                                'temperature': random.uniform(15, 30),
                                'humidity': random.uniform(40, 80),
                                'wind_speed': random.uniform(0, 15),
                                'unit': '°C',
                                'sensor_type': 'weather_station'
                            }
                        
                        IoTDataPoint.objects.create(
                            device=device,
                            timestamp=timestamp,
                            data=data,
                            quality_score=random.uniform(0.85, 1.0)
                        )
                        data_points_created += 1
        
        self.stdout.write(f'✅ Created {devices_created} IoT devices and {data_points_created} data points')

    def create_consumer_engagement_data(self, productions):
        """Create QR code scans and product reviews"""
        self.stdout.write(self.style.SUCCESS('👥 Creating consumer engagement data...'))
        
        # Create consumer users
        consumer_users_data = [
            ('Emily', 'Chen', 'emily.chen@email.com'),
            ('Michael', 'Rodriguez', 'mike.rodriguez@email.com'),
            ('Sarah', 'Johnson', 'sarah.j@email.com'),
            ('David', 'Kim', 'david.kim@email.com'),
            ('Lisa', 'Thompson', 'lisa.t@email.com')
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
        
        # Create QR code scans (recent 2 weeks)
        scans_created = 0
        for production in productions[:10]:  # Limit to avoid overwhelming
            num_scans = random.randint(10, 25)  # Realistic engagement
            
            for _ in range(num_scans):
                scan_date = timezone.now() - timedelta(
                    days=random.randint(1, 14),
                    hours=random.randint(8, 22),
                    minutes=random.randint(0, 59)
                )
                
                scanner = random.choice(consumer_users) if random.random() < 0.7 else None
                
                HistoryScan.objects.create(
                    history=production,
                    user=scanner,
                    ip_address=f'192.168.{random.randint(1,255)}.{random.randint(1,255)}',
                    city=random.choice(['Fresno', 'Salinas', 'San Francisco', 'Los Angeles', 'Sacramento']),
                    country='United States',
                    comment=f'QR scan via {random.choice(["mobile app", "web browser", "in-store kiosk"])}'
                )
                scans_created += 1
        
        # Create product reviews
        reviews_created = 0
        review_templates = [
            ("Exceptional quality and transparency!", 5, "Love being able to see the carbon footprint and growing process."),
            ("Great sustainable practices", 5, "Impressed by the commitment to carbon-neutral farming."),
            ("Fresh and responsibly grown", 4, "Product quality is excellent with detailed sustainability info."),
            ("Transparency is amazing", 5, "Finally, a company that shows exactly how their produce is grown."),
            ("Premium quality produce", 4, "Outstanding quality with complete traceability.")
        ]
        
        for production in productions[:8]:  # Focus on subset
            if random.random() < 0.6:  # 60% chance of reviews
                num_reviews = random.randint(2, 5)
                
                for _ in range(num_reviews):
                    reviewer = random.choice(consumer_users)
                    title, rating, content = random.choice(review_templates)
                    
                    review_date = timezone.now() - timedelta(
                        days=random.randint(1, 30),
                        hours=random.randint(9, 21)
                    )
                    
                    Review.objects.create(
                        production=production,
                        user=reviewer,
                        headline=title,
                        written_review=content,
                        rating=rating
                    )
                    reviews_created += 1
        
        self.stdout.write(f'✅ Created {consumers_created} consumers, {scans_created} QR scans, and {reviews_created} reviews')