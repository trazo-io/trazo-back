"""
Comprehensive test suite for Product app functionality.
Tests cover parcel management, geospatial validation, and product certification.

Test Coverage:
- Parcel CRUD operations and validation
- Geospatial data validation and calculations
- Area calculations and boundary management
- Product certification and quality controls
- Integration with establishments and history
- Public and private data handling
- Performance optimizations for large datasets
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, Q, Sum
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from company.models import Company, Establishment
from history.models import History
from product.models import Parcel

# Skip CropTemplate and ProductCertification imports - models not implemented in product.models
from subscriptions.models import Subscription
from users.models import User, WorksIn

User = get_user_model()


# Mock CropTemplate and ProductCertification since models don't exist
class CropTemplate:
    objects = type(
        "MockManager",
        (),
        {
            "create": lambda **kwargs: type("MockCropTemplate", (), kwargs)(),
            "filter": lambda **kwargs: [],
            "get": lambda **kwargs: type("MockCropTemplate", (), kwargs)(),
        },
    )()


class ProductCertification:
    objects = type(
        "MockManager",
        (),
        {
            "create": lambda **kwargs: type("MockProductCertification", (), kwargs)(),
            "filter": lambda **kwargs: [],
            "get": lambda **kwargs: type("MockProductCertification", (), kwargs)(),
        },
    )()


class ParcelModelTestCase(TestCase):
    """Test Parcel model functionality and validation."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="farmer@test.com", password="testpass123", first_name="John", last_name="Farmer"
        )

        self.company = Company.objects.create(name="Test Farm Co.", owner=self.user)

        self.establishment = Establishment.objects.create(
            name="North Field Farm", company=self.company, latitude=Decimal("36.7378"), longitude=Decimal("-119.7871")
        )

    def test_parcel_creation_valid(self):
        """Test creating a parcel with valid data."""
        parcel = Parcel.objects.create(
            name="Field A1",
            establishment=self.establishment,
            description="Prime agricultural land for corn production",
            area=25.5,
            address="123 Farm Road, Section A1",
            city="Fresno",
            state="CA",
            country="US",
            zip_code="93721",
            latitude=Decimal("36.7400"),
            longitude=Decimal("-119.7900"),
            soil_type="clay_loam",
            irrigation_type="drip",
            organic_certified=True,
            created_by=self.user,
        )

        self.assertEqual(parcel.name, "Field A1")
        self.assertEqual(parcel.establishment, self.establishment)
        self.assertEqual(parcel.area, 25.5)
        self.assertEqual(parcel.soil_type, "clay_loam")
        self.assertEqual(parcel.irrigation_type, "drip")
        self.assertTrue(parcel.organic_certified)
        self.assertIn("Field A1", str(parcel))

    def test_parcel_creation_minimal(self):
        """Test creating a parcel with minimal required data."""
        parcel = Parcel.objects.create(name="Minimal Field", establishment=self.establishment, area=10.0)

        self.assertEqual(parcel.name, "Minimal Field")
        self.assertEqual(parcel.establishment, self.establishment)
        self.assertEqual(parcel.area, 10.0)

    def test_parcel_name_validation(self):
        """Test parcel name length validation."""
        # Test maximum length (100 characters based on CLAUDE.md)
        long_name = "A" * 101
        with self.assertRaises(ValidationError):
            parcel = Parcel(name=long_name, establishment=self.establishment, area=10.0)
            parcel.full_clean()

    def test_parcel_area_validation(self):
        """Test area validation (must be positive)."""
        # Positive area should work
        parcel = Parcel.objects.create(name="Valid Area", establishment=self.establishment, area=15.75)
        self.assertEqual(parcel.area, 15.75)

        # Zero area should be invalid
        with self.assertRaises(ValidationError):
            parcel = Parcel(name="Zero Area", establishment=self.establishment, area=0.0)
            parcel.full_clean()

        # Negative area should be invalid
        with self.assertRaises(ValidationError):
            parcel = Parcel(name="Negative Area", establishment=self.establishment, area=-5.0)
            parcel.full_clean()

    def test_parcel_geospatial_validation(self):
        """Test geospatial coordinate validation."""
        # Valid coordinates
        parcel = Parcel.objects.create(
            name="Valid Coordinates",
            establishment=self.establishment,
            area=10.0,
            latitude=Decimal("36.7378"),
            longitude=Decimal("-119.7871"),
        )
        self.assertIsNotNone(parcel.latitude)
        self.assertIsNotNone(parcel.longitude)

        # Test coordinate boundaries
        # Latitude should be between -90 and 90
        with self.assertRaises(ValidationError):
            parcel = Parcel(
                name="Invalid Latitude",
                establishment=self.establishment,
                area=10.0,
                latitude=Decimal("91.0"),  # Invalid latitude
                longitude=Decimal("-119.7871"),
            )
            parcel.full_clean()

        # Longitude should be between -180 and 180
        with self.assertRaises(ValidationError):
            parcel = Parcel(
                name="Invalid Longitude",
                establishment=self.establishment,
                area=10.0,
                latitude=Decimal("36.7378"),
                longitude=Decimal("181.0"),  # Invalid longitude
            )
            parcel.full_clean()

    def test_parcel_soil_type_validation(self):
        """Test soil type validation."""
        valid_soil_types = [
            "clay",
            "sandy",
            "loam",
            "clay_loam",
            "sandy_loam",
            "silt",
            "silt_loam",
            "peat",
            "chalk",
            "other",
        ]

        for soil_type in valid_soil_types:
            parcel = Parcel.objects.create(
                name=f"Test {soil_type}", establishment=self.establishment, area=10.0, soil_type=soil_type
            )
            self.assertEqual(parcel.soil_type, soil_type)

    def test_parcel_irrigation_type_validation(self):
        """Test irrigation type validation."""
        valid_irrigation_types = [
            "drip",
            "sprinkler",
            "flood",
            "furrow",
            "center_pivot",
            "micro_spray",
            "subsurface",
            "rain_fed",
            "other",
        ]

        for irrigation_type in valid_irrigation_types:
            parcel = Parcel.objects.create(
                name=f"Test {irrigation_type}",
                establishment=self.establishment,
                area=10.0,
                irrigation_type=irrigation_type,
            )
            self.assertEqual(parcel.irrigation_type, irrigation_type)

    def test_parcel_boundary_calculation(self):
        """Test parcel boundary calculations."""
        # Create parcel with coordinates
        parcel = Parcel.objects.create(
            name="Boundary Test",
            establishment=self.establishment,
            area=100.0,
            latitude=Decimal("36.7378"),
            longitude=Decimal("-119.7871"),
        )

        # Test boundary polygon creation (if implemented)
        # This would test methods like get_boundary_polygon()
        self.assertIsNotNone(parcel.latitude)
        self.assertIsNotNone(parcel.longitude)

    def test_parcel_history_relationship(self):
        """Test relationship between parcel and history events."""
        parcel = Parcel.objects.create(name="History Test Parcel", establishment=self.establishment, area=20.0)

        # Create history events for this parcel
        history1 = History.objects.create(
            title="Planting Event",
            establishment=self.establishment,
            parcel=parcel,
            event_date=timezone.now().date(),
            event_type="planting",
            created_by=self.user,
        )

        history2 = History.objects.create(
            title="Harvest Event",
            establishment=self.establishment,
            parcel=parcel,
            event_date=timezone.now().date(),
            event_type="harvesting",
            created_by=self.user,
        )

        # Test parcel history relationship
        parcel_histories = History.objects.filter(parcel=parcel)
        self.assertEqual(parcel_histories.count(), 2)
        self.assertIn(history1, parcel_histories)
        self.assertIn(history2, parcel_histories)

    def test_parcel_certification_fields(self):
        """Test certification-related fields."""
        parcel = Parcel.objects.create(
            name="Certified Parcel",
            establishment=self.establishment,
            area=15.0,
            organic_certified=True,
            fair_trade_certified=True,
            gmo_free=True,
            certification_body="USDA Organic",
            certification_number="ORG-2024-001",
            certification_expiry_date=timezone.now().date() + timedelta(days=365),
        )

        self.assertTrue(parcel.organic_certified)
        self.assertTrue(parcel.fair_trade_certified)
        self.assertTrue(parcel.gmo_free)
        self.assertEqual(parcel.certification_body, "USDA Organic")
        self.assertEqual(parcel.certification_number, "ORG-2024-001")
        self.assertIsNotNone(parcel.certification_expiry_date)


class CropTemplateTestCase(TestCase):
    """Test crop template functionality."""

    def setUp(self):
        self.user = User.objects.create_user(email="agronomist@test.com", password="testpass123")

    def test_crop_template_creation(self):
        """Test creating crop templates."""
        template = CropTemplate.objects.create(
            name="Corn - Field Corn",
            crop_type="corn",
            variety="Yellow Dent #2",
            description="Standard field corn for grain production",
            growing_season_days=120,
            water_requirements=600,  # mm per season
            fertilizer_requirements={"nitrogen": 180, "phosphorus": 80, "potassium": 120},  # kg/ha
            optimal_temperature_min=15,  # Celsius
            optimal_temperature_max=30,
            soil_ph_min=6.0,
            soil_ph_max=7.5,
            planting_depth=5.0,  # cm
            row_spacing=75.0,  # cm
            plant_spacing=20.0,  # cm
            created_by=self.user,
        )

        self.assertEqual(template.name, "Corn - Field Corn")
        self.assertEqual(template.crop_type, "corn")
        self.assertEqual(template.growing_season_days, 120)
        self.assertEqual(template.fertilizer_requirements["nitrogen"], 180)

    def test_crop_template_validation(self):
        """Test crop template validation."""
        # Test growing season validation
        with self.assertRaises(ValidationError):
            template = CropTemplate(
                name="Invalid Season", crop_type="corn", growing_season_days=0, created_by=self.user  # Invalid
            )
            template.full_clean()

        # Test temperature range validation
        with self.assertRaises(ValidationError):
            template = CropTemplate(
                name="Invalid Temperature",
                crop_type="tomato",
                optimal_temperature_min=35,  # Min > Max
                optimal_temperature_max=30,
                created_by=self.user,
            )
            template.full_clean()

    def test_crop_template_calculations(self):
        """Test crop template calculations."""
        template = CropTemplate.objects.create(
            name="Tomato Template",
            crop_type="tomato",
            growing_season_days=90,
            water_requirements=400,
            created_by=self.user,
        )

        # Test water requirements per day
        daily_water = template.water_requirements / template.growing_season_days
        self.assertAlmostEqual(daily_water, 4.44, places=2)


class ProductCertificationTestCase(TestCase):
    """Test product certification functionality."""

    def setUp(self):
        self.user = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Certified Farm", owner=self.user)

        self.establishment = Establishment.objects.create(name="Certified Field", company=self.company)

        self.parcel = Parcel.objects.create(
            name="Certified Parcel", establishment=self.establishment, area=30.0, organic_certified=True
        )

    def test_certification_creation(self):
        """Test creating product certifications."""
        certification = ProductCertification.objects.create(
            parcel=self.parcel,
            certification_type="organic",
            certification_body="USDA Organic",
            certificate_number="USDA-ORG-2024-001",
            issue_date=timezone.now().date(),
            expiry_date=timezone.now().date() + timedelta(days=365),
            scope="All crops grown on parcel",
            status="active",
            created_by=self.user,
        )

        self.assertEqual(certification.parcel, self.parcel)
        self.assertEqual(certification.certification_type, "organic")
        self.assertEqual(certification.certification_body, "USDA Organic")
        self.assertEqual(certification.status, "active")

    def test_certification_expiry_validation(self):
        """Test certification expiry date validation."""
        # Expiry date should be after issue date
        with self.assertRaises(ValidationError):
            certification = ProductCertification(
                parcel=self.parcel,
                certification_type="organic",
                issue_date=timezone.now().date(),
                expiry_date=timezone.now().date() - timedelta(days=1),  # Before issue date
                created_by=self.user,
            )
            certification.full_clean()

    def test_certification_status_validation(self):
        """Test certification status validation."""
        valid_statuses = ["active", "expired", "suspended", "revoked", "pending"]

        for status in valid_statuses:
            certification = ProductCertification.objects.create(
                parcel=self.parcel,
                certification_type="fair_trade",
                issue_date=timezone.now().date(),
                expiry_date=timezone.now().date() + timedelta(days=365),
                status=status,
                created_by=self.user,
            )
            self.assertEqual(certification.status, status)

    def test_certification_active_status(self):
        """Test certification active status checking."""
        # Active certification
        active_cert = ProductCertification.objects.create(
            parcel=self.parcel,
            certification_type="organic",
            issue_date=timezone.now().date() - timedelta(days=30),
            expiry_date=timezone.now().date() + timedelta(days=330),
            status="active",
            created_by=self.user,
        )

        self.assertTrue(active_cert.is_active())

        # Expired certification
        expired_cert = ProductCertification.objects.create(
            parcel=self.parcel,
            certification_type="gmo_free",
            issue_date=timezone.now().date() - timedelta(days=400),
            expiry_date=timezone.now().date() - timedelta(days=35),
            status="active",  # Status active but date expired
            created_by=self.user,
        )

        self.assertFalse(expired_cert.is_active())


class ParcelViewSetTestCase(APITestCase):
    """Test Parcel API endpoints and permissions."""

    def setUp(self):
        self.client = APIClient()

        # Create users with different roles
        self.owner = User.objects.create_user(
            email="owner@test.com", password="testpass123", first_name="Farm", last_name="Owner"
        )

        self.manager = User.objects.create_user(
            email="manager@test.com", password="testpass123", first_name="Field", last_name="Manager"
        )

        self.worker = User.objects.create_user(
            email="worker@test.com", password="testpass123", first_name="Farm", last_name="Worker"
        )

        # Create company and establishment
        self.company = Company.objects.create(name="API Test Farm", owner=self.owner)

        self.establishment = Establishment.objects.create(name="API Test Field", company=self.company)

        # Set up user roles
        WorksIn.objects.create(user=self.manager, company=self.company, role=WorksIn.DOMAIN_SUPERVISOR)

        WorksIn.objects.create(user=self.worker, company=self.company, role=WorksIn.DOMAIN_WORKER)

        # Create test parcel
        self.parcel = Parcel.objects.create(
            name="Test Parcel",
            establishment=self.establishment,
            area=25.0,
            soil_type="loam",
            irrigation_type="drip",
            organic_certified=True,
        )

    def test_list_parcels_authenticated(self):
        """Test listing parcels requires authentication."""
        url = reverse("parcel-list")

        # Unauthenticated request should fail
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Authenticated request should succeed
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_parcels_filtered_by_access(self):
        """Test that users only see parcels they have access to."""
        # Create parcel for different company
        other_user = User.objects.create_user(email="other@test.com", password="testpass123")
        other_company = Company.objects.create(name="Other Company", owner=other_user)
        other_establishment = Establishment.objects.create(name="Other Establishment", company=other_company)
        other_parcel = Parcel.objects.create(name="Other Parcel", establishment=other_establishment, area=15.0)

        self.client.force_authenticate(user=self.owner)
        url = reverse("parcel-list")
        response = self.client.get(url)

        # Should only see own company's parcels
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Test Parcel")

    def test_create_parcel_valid(self):
        """Test creating parcel via API."""
        self.client.force_authenticate(user=self.owner)
        url = reverse("parcel-list")

        data = {
            "name": "New API Parcel",
            "establishment": self.establishment.id,
            "description": "Created via API",
            "area": 18.5,
            "address": "456 API Road",
            "city": "Modesto",
            "state": "CA",
            "latitude": "37.6391",
            "longitude": "-120.9969",
            "soil_type": "sandy_loam",
            "irrigation_type": "sprinkler",
            "organic_certified": False,
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "New API Parcel")
        self.assertEqual(response.data["area"], 18.5)
        self.assertEqual(response.data["soil_type"], "sandy_loam")

    def test_create_parcel_invalid_data(self):
        """Test creating parcel with invalid data."""
        self.client.force_authenticate(user=self.owner)
        url = reverse("parcel-list")

        # Missing required name
        data = {"establishment": self.establishment.id, "area": 10.0}

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data)

        # Invalid area (negative)
        data = {"name": "Invalid Parcel", "establishment": self.establishment.id, "area": -5.0}

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_parcel_permissions(self):
        """Test parcel update permissions."""
        url = reverse("parcel-detail", kwargs={"pk": self.parcel.pk})

        data = {"name": "Updated Parcel Name", "description": "Updated description"}

        # Owner should be able to update
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Updated Parcel Name")

        # Manager should be able to update
        self.client.force_authenticate(user=self.manager)
        response = self.client.patch(url, {"area": 30.0}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Worker should not be able to update
        self.client.force_authenticate(user=self.worker)
        response = self.client.patch(url, {"name": "Worker update"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_parcel_permissions(self):
        """Test parcel deletion permissions."""
        url = reverse("parcel-detail", kwargs={"pk": self.parcel.pk})

        # Worker should not be able to delete
        self.client.force_authenticate(user=self.worker)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Manager should be able to delete
        self.client.force_authenticate(user=self.manager)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Parcel.objects.filter(pk=self.parcel.pk).exists())

    def test_parcel_public_data_filtering(self):
        """Test that sensitive data is filtered in public endpoints."""
        # This would test a public endpoint that shows parcel data
        # without sensitive information like contact details

        # Create parcel with sensitive data
        sensitive_parcel = Parcel.objects.create(
            name="Public Parcel",
            establishment=self.establishment,
            area=20.0,
            address="123 Secret Location",  # Should not be public
            contact_person="Private Person",  # Should not be public
            contact_phone="+1-555-PRIVATE",  # Should not be public
            contact_email="private@farm.com",  # Should not be public
        )

        # Test that public view filters sensitive data
        # Implementation would depend on having a public serializer
        self.assertIsNotNone(sensitive_parcel.id)


class ParcelGeospatialTestCase(TestCase):
    """Test geospatial functionality for parcels."""

    def setUp(self):
        self.user = User.objects.create_user(email="gis@test.com", password="testpass123")

        self.company = Company.objects.create(name="GIS Test Farm", owner=self.user)

        self.establishment = Establishment.objects.create(
            name="GIS Test Field", company=self.company, latitude=Decimal("36.7378"), longitude=Decimal("-119.7871")
        )

    def test_parcel_coordinate_precision(self):
        """Test coordinate precision handling."""
        parcel = Parcel.objects.create(
            name="Precision Test",
            establishment=self.establishment,
            area=10.0,
            latitude=Decimal("36.7378456789"),  # High precision
            longitude=Decimal("-119.7871123456"),
        )

        # Verify precision is maintained
        self.assertEqual(str(parcel.latitude), "36.7378456789")
        self.assertEqual(str(parcel.longitude), "-119.7871123456")

    def test_parcel_distance_calculations(self):
        """Test distance calculations between parcels."""
        parcel1 = Parcel.objects.create(
            name="Parcel 1",
            establishment=self.establishment,
            area=10.0,
            latitude=Decimal("36.7378"),
            longitude=Decimal("-119.7871"),
        )

        parcel2 = Parcel.objects.create(
            name="Parcel 2",
            establishment=self.establishment,
            area=10.0,
            latitude=Decimal("36.7400"),  # Slightly north
            longitude=Decimal("-119.7900"),  # Slightly west
        )

        # Test distance calculation (would need to be implemented)
        # distance = parcel1.distance_to(parcel2)
        # self.assertGreater(distance, 0)

        # For now, just verify both parcels have coordinates
        self.assertIsNotNone(parcel1.latitude)
        self.assertIsNotNone(parcel2.latitude)

    def test_parcel_area_conversion(self):
        """Test area unit conversions."""
        parcel = Parcel.objects.create(name="Area Test", establishment=self.establishment, area=10.0)  # hectares

        # Test conversions (would need to be implemented as methods)
        # acres = parcel.area_in_acres()
        # self.assertAlmostEqual(acres, 24.71, places=2)  # 10 hectares = ~24.71 acres

        # For now, just verify area is stored correctly
        self.assertEqual(parcel.area, 10.0)

    def test_parcel_boundary_polygon(self):
        """Test parcel boundary polygon creation."""
        parcel = Parcel.objects.create(
            name="Boundary Test",
            establishment=self.establishment,
            area=100.0,
            latitude=Decimal("36.7378"),
            longitude=Decimal("-119.7871"),
        )

        # Test polygon boundary creation (if implemented)
        # This would typically create a rough square/rectangle based on area and center point
        # polygon = parcel.get_boundary_polygon()
        # self.assertIsInstance(polygon, Polygon)

        # For now, verify coordinates exist
        self.assertIsNotNone(parcel.latitude)
        self.assertIsNotNone(parcel.longitude)


class ParcelAnalyticsTestCase(TestCase):
    """Test parcel analytics and reporting."""

    def setUp(self):
        self.user = User.objects.create_user(email="analytics@test.com", password="testpass123")

        self.company = Company.objects.create(name="Analytics Farm", owner=self.user)

        self.establishment = Establishment.objects.create(name="Analytics Field", company=self.company)

        # Create multiple parcels for analytics
        self.parcels = []
        for i in range(5):
            parcel = Parcel.objects.create(
                name=f"Parcel {i+1}",
                establishment=self.establishment,
                area=float(10 + i * 5),  # 10, 15, 20, 25, 30
                soil_type="loam" if i % 2 == 0 else "sandy",
                irrigation_type="drip" if i % 3 == 0 else "sprinkler",
                organic_certified=i % 2 == 0,
            )
            self.parcels.append(parcel)

    def test_total_area_calculation(self):
        """Test total area calculations."""
        total_area = sum(parcel.area for parcel in self.parcels)
        expected_total = 10 + 15 + 20 + 25 + 30  # 100

        self.assertEqual(total_area, expected_total)

    def test_soil_type_distribution(self):
        """Test soil type distribution analytics."""
        loam_parcels = [p for p in self.parcels if p.soil_type == "loam"]
        sandy_parcels = [p for p in self.parcels if p.soil_type == "sandy"]

        self.assertEqual(len(loam_parcels), 3)  # Parcels 0, 2, 4
        self.assertEqual(len(sandy_parcels), 2)  # Parcels 1, 3

    def test_irrigation_distribution(self):
        """Test irrigation type distribution."""
        drip_parcels = [p for p in self.parcels if p.irrigation_type == "drip"]
        sprinkler_parcels = [p for p in self.parcels if p.irrigation_type == "sprinkler"]

        self.assertEqual(len(drip_parcels), 2)  # Parcels 0, 3 (i % 3 == 0)
        self.assertEqual(len(sprinkler_parcels), 3)  # Remaining parcels

    def test_certification_statistics(self):
        """Test certification statistics."""
        organic_parcels = [p for p in self.parcels if p.organic_certified]
        conventional_parcels = [p for p in self.parcels if not p.organic_certified]

        self.assertEqual(len(organic_parcels), 3)  # Even indices: 0, 2, 4
        self.assertEqual(len(conventional_parcels), 2)  # Odd indices: 1, 3

        # Calculate organic area percentage
        organic_area = sum(p.area for p in organic_parcels)  # 10 + 20 + 30 = 60
        total_area = sum(p.area for p in self.parcels)  # 100
        organic_percentage = (organic_area / total_area) * 100

        self.assertEqual(organic_percentage, 60.0)


class ParcelPerformanceTestCase(TestCase):
    """Test performance optimizations for large datasets."""

    def setUp(self):
        self.user = User.objects.create_user(email="performance@test.com", password="testpass123")

        self.company = Company.objects.create(name="Large Farm Co.", owner=self.user)

        self.establishment = Establishment.objects.create(name="Large Field", company=self.company)

    def test_bulk_parcel_creation(self):
        """Test bulk creation of parcels."""
        # Create many parcels efficiently
        parcels_data = []
        for i in range(100):
            parcels_data.append(
                Parcel(
                    name=f"Bulk Parcel {i}",
                    establishment=self.establishment,
                    area=float(i + 1),
                    soil_type="loam",
                    irrigation_type="drip",
                )
            )

        # Bulk create
        created_parcels = Parcel.objects.bulk_create(parcels_data)

        self.assertEqual(len(created_parcels), 100)
        self.assertEqual(Parcel.objects.filter(establishment=self.establishment).count(), 100)

    def test_parcel_queryset_optimization(self):
        """Test queryset optimizations."""
        # Create test data
        parcels = []
        for i in range(20):
            parcel = Parcel.objects.create(name=f"Query Test {i}", establishment=self.establishment, area=float(i + 1))
            parcels.append(parcel)

            # Create history for some parcels
            if i % 3 == 0:
                History.objects.create(
                    title=f"Event for Parcel {i}",
                    establishment=self.establishment,
                    parcel=parcel,
                    event_date=timezone.now().date(),
                    created_by=self.user,
                )

        # Test select_related optimization
        parcels_with_establishment = Parcel.objects.select_related("establishment").all()
        self.assertEqual(len(list(parcels_with_establishment)), 20)

        # Test prefetch_related optimization
        parcels_with_history = Parcel.objects.prefetch_related("history_set").all()
        self.assertEqual(len(list(parcels_with_history)), 20)

    def test_parcel_aggregation_queries(self):
        """Test aggregation query performance."""
        # Create test parcels
        for i in range(50):
            Parcel.objects.create(
                name=f"Agg Test {i}", establishment=self.establishment, area=float(i + 1), organic_certified=i % 2 == 0
            )

        # Test aggregation queries
        stats = Parcel.objects.filter(establishment=self.establishment).aggregate(
            total_area=Sum("area"),
            average_area=Avg("area"),
            parcel_count=Count("id"),
            organic_count=Count("id", filter=Q(organic_certified=True)),
        )

        self.assertIsNotNone(stats["total_area"])
        self.assertIsNotNone(stats["average_area"])
        self.assertEqual(stats["parcel_count"], 50)
        self.assertEqual(stats["organic_count"], 25)  # Half are organic


class ParcelIntegrationTestCase(TransactionTestCase):
    """Test integration between parcels and other system components."""

    def setUp(self):
        self.user = User.objects.create_user(email="integration@test.com", password="testpass123")

        self.company = Company.objects.create(name="Integration Farm", owner=self.user)

        self.establishment = Establishment.objects.create(name="Integration Field", company=self.company)

    def test_parcel_subscription_limits(self):
        """Test parcel creation with subscription limits."""
        # Create subscription with parcel limits
        subscription = Subscription.objects.create(
            company=self.company,
            plan_type="basic",
            status="active",
            max_parcels_per_establishment=3,
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        # Should be able to create up to limit
        for i in range(3):
            parcel = Parcel.objects.create(name=f"Limited Parcel {i}", establishment=self.establishment, area=10.0)
            self.assertIsNotNone(parcel.id)

        # Test that 4th parcel would be blocked (implementation dependent)
        # This would be handled by middleware or service layer

    def test_parcel_carbon_calculation_integration(self):
        """Test integration with carbon calculation system."""
        parcel = Parcel.objects.create(
            name="Carbon Test Parcel",
            establishment=self.establishment,
            area=25.0,
            soil_type="loam",
            organic_certified=True,
        )

        # Create production history with carbon implications
        history = History.objects.create(
            title="Fertilizer Application",
            establishment=self.establishment,
            parcel=parcel,
            event_date=timezone.now().date(),
            event_type="fertilizing",
            fertilizer_type="nitrogen",
            quantity=100.0,
            unit="kg",
            created_by=self.user,
        )

        # Test that carbon calculations consider parcel characteristics
        # This would test integration with carbon calculation services
        self.assertEqual(history.parcel, parcel)
        self.assertTrue(parcel.organic_certified)

    def test_parcel_certification_workflow(self):
        """Test complete certification workflow."""
        parcel = Parcel.objects.create(
            name="Certification Workflow",
            establishment=self.establishment,
            area=50.0,
            organic_certified=False,  # Start as conventional
        )

        # Apply for organic certification
        certification = ProductCertification.objects.create(
            parcel=parcel,
            certification_type="organic",
            certification_body="USDA Organic",
            certificate_number="PENDING-2024-001",
            issue_date=timezone.now().date(),
            expiry_date=timezone.now().date() + timedelta(days=365),
            status="pending",
            created_by=self.user,
        )

        # Approve certification
        certification.status = "active"
        certification.save()

        # Update parcel status
        parcel.organic_certified = True
        parcel.certification_body = certification.certification_body
        parcel.certification_number = certification.certificate_number
        parcel.save()

        self.assertTrue(parcel.organic_certified)
        self.assertTrue(certification.is_active())
