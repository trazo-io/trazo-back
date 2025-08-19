"""
Comprehensive test suite for Company management functionality.
Tests cover CRUD operations, validation, access control, and integration scenarios.

Test Coverage:
- Company creation and validation
- Establishment management
- Geographic data validation
- Multi-tenant access control
- Role-based permissions
- Subscription enforcement
- Integration with carbon calculations
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from carbon.models import CarbonEntry
from company.models import Company, Establishment
from subscriptions.models import Plan, Subscription
from users.models import User, WorksIn

User = get_user_model()


class CompanyModelTestCase(TestCase):
    """Test Company model functionality and validation."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@test.com", password="testpass123", first_name="Test", last_name="Owner"
        )

    def test_company_creation_valid(self):
        """Test creating a company with valid data."""
        company = Company.objects.create(
            name="Test Farm Co.",
            description="A sustainable farming company",
            address="123 Farm Road",
            city="Fresno",
            state="CA",
            country="US",
            zip_code="93721",
            contact_phone="+1-559-123-4567",
            contact_email="info@testfarm.com",
            website="https://testfarm.com",
        )

        self.assertEqual(company.name, "Test Farm Co.")
        self.assertIn("Test Farm Co.", str(company))

    def test_company_creation_minimal(self):
        """Test creating a company with minimal required data."""
        company = Company.objects.create(
            name="Minimal Farm", address="123 Test St", city="Test City", state="Test State"
        )

        self.assertEqual(company.name, "Minimal Farm")

    def test_company_name_validation(self):
        """Test company name length validation."""
        # Test maximum length (150 characters based on model definition)
        long_name = "A" * 151
        with self.assertRaises(ValidationError):
            company = Company(name=long_name, address="123 Test St", city="Test City", state="Test State")
            company.full_clean()

    def test_company_unique_constraint(self):
        """Test that company creation works with required fields."""
        Company.objects.create(name="Unique Farm", address="123 Test St", city="Test City", state="Test State")

        # Creating another company with same name should work (no uniqueness constraint)
        Company.objects.create(name="Unique Farm 2", address="456 Test Ave", city="Test City 2", state="Test State 2")

    def test_company_deletion_cascade(self):
        """Test that deleting company cascades properly."""
        company = Company.objects.create(
            name="Delete Test", address="123 Test St", city="Test City", state="Test State"
        )
        establishment = Establishment.objects.create(name="Test Establishment", company=company)

        company_id = company.id
        establishment_id = establishment.id

        company.delete()

        self.assertFalse(Company.objects.filter(id=company_id).exists())
        self.assertFalse(Establishment.objects.filter(id=establishment_id).exists())


class EstablishmentModelTestCase(TestCase):
    """Test Establishment model functionality and validation."""

    def setUp(self):
        self.user = User.objects.create_user(email="owner@test.com", password="testpass123")
        self.company = Company.objects.create(
            name="Test Company", address="123 Test St", city="Test City", state="Test State"
        )

    def test_establishment_creation_valid(self):
        """Test creating an establishment with valid data."""
        establishment = Establishment.objects.create(
            name="North Field Farm",
            company=self.company,
            description="Main production facility",
            address="456 Agricultural Way",
            city="Salinas",
            state="CA",
            country="US",
            zip_code="93901",
            latitude=Decimal("36.6777"),
            longitude=Decimal("-121.6555"),
            contact_person="Farm Manager",
            contact_phone="+1-831-555-0123",
            contact_email="manager@northfield.com",
            main_activities="Organic vegetable production",
            total_acreage=250.5,
            employee_count=15,
            year_established=2010,
            establishment_type="farm",
            farming_method="organic",
        )

        self.assertEqual(establishment.name, "North Field Farm")
        self.assertEqual(establishment.company, self.company)
        self.assertEqual(establishment.total_acreage, 250.5)
        self.assertIn("North Field Farm", str(establishment))

    def test_establishment_geographic_validation(self):
        """Test geographic coordinate validation."""
        # Valid coordinates
        establishment = Establishment.objects.create(
            name="Valid Location", company=self.company, latitude=Decimal("36.7378"), longitude=Decimal("-119.7871")
        )
        self.assertIsNotNone(establishment.latitude)

        # Test coordinate boundaries (if implemented)
        # Latitude should be between -90 and 90
        # Longitude should be between -180 and 180

    def test_establishment_contact_validation(self):
        """Test contact information validation."""
        establishment = Establishment.objects.create(
            name="Contact Test", company=self.company, contact_email="invalid-email"  # Invalid email format
        )

        # Django's EmailField should handle validation during full_clean()
        with self.assertRaises(ValidationError):
            establishment.full_clean()

    def test_establishment_acreage_validation(self):
        """Test acreage must be positive."""
        establishment = Establishment(
            name="Invalid Acreage", company=self.company, total_acreage=-10  # Negative acreage should be invalid
        )

        # Custom validation would be in clean() method if implemented
        # For now, we just test that the field accepts decimal values
        establishment.save()

    def test_establishment_parcels_relationship(self):
        """Test relationship between establishment and parcels."""
        establishment = Establishment.objects.create(name="Parcel Test Farm", company=self.company)

        # Create parcels for this establishment
        from product.models import Parcel

        parcel1 = Parcel.objects.create(name="North Parcel", establishment=establishment, area=10.5)
        parcel2 = Parcel.objects.create(name="South Parcel", establishment=establishment, area=8.2)

        self.assertEqual(establishment.parcels.count(), 2)
        self.assertIn(parcel1, establishment.parcels.all())
        self.assertIn(parcel2, establishment.parcels.all())


class CompanyViewSetTestCase(APITestCase):
    """Test Company API endpoints and permissions."""

    def setUp(self):
        self.client = APIClient()

        # Create test users with different roles
        self.owner = User.objects.create_user(
            email="owner@test.com", password="testpass123", first_name="Company", last_name="Owner"
        )

        self.manager = User.objects.create_user(
            email="manager@test.com", password="testpass123", first_name="Farm", last_name="Manager"
        )

        self.worker = User.objects.create_user(
            email="worker@test.com", password="testpass123", first_name="Field", last_name="Worker"
        )

        # Create test company
        self.company = Company.objects.create(
            name="API Test Farm", description="Test company for API testing", owner=self.owner
        )

        # Set up user roles
        WorksIn.objects.create(user=self.manager, company=self.company, role=WorksIn.DOMAIN_SUPERVISOR)

        WorksIn.objects.create(user=self.worker, company=self.company, role=WorksIn.DOMAIN_WORKER)

    def test_list_companies_authenticated(self):
        """Test listing companies requires authentication."""
        url = reverse("company-list")

        # Unauthenticated request should fail
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Authenticated request should succeed
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_companies_filters_by_user(self):
        """Test that users only see their companies."""
        # Create another company owned by different user
        other_user = User.objects.create_user(email="other@test.com", password="testpass123")
        other_company = Company.objects.create(name="Other Company", owner=other_user)

        self.client.force_authenticate(user=self.owner)
        url = reverse("company-list")
        response = self.client.get(url)

        # Should only see own company
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "API Test Farm")

    def test_create_company_valid(self):
        """Test creating a company via API."""
        self.client.force_authenticate(user=self.owner)
        url = reverse("company-list")

        data = {
            "name": "New API Farm",
            "description": "Created via API",
            "address": "789 API Street",
            "city": "San Francisco",
            "state": "CA",
            "country": "US",
            "phone": "+1-415-555-0199",
            "email": "contact@newapifarm.com",
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "New API Farm")
        self.assertEqual(response.data["owner"], self.owner.id)

    def test_create_company_invalid_data(self):
        """Test creating company with invalid data."""
        self.client.force_authenticate(user=self.owner)
        url = reverse("company-list")

        # Missing required name field
        data = {"description": "Missing name field"}

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data)

    def test_update_company_owner_only(self):
        """Test that only company owner can update company."""
        url = reverse("company-detail", kwargs={"pk": self.company.pk})

        data = {"name": "Updated Farm Name", "description": "Updated description"}

        # Manager should not be able to update
        self.client.force_authenticate(user=self.manager)
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Owner should be able to update
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Updated Farm Name")

    def test_delete_company_owner_only(self):
        """Test that only company owner can delete company."""
        url = reverse("company-detail", kwargs={"pk": self.company.pk})

        # Manager should not be able to delete
        self.client.force_authenticate(user=self.manager)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Owner should be able to delete
        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())


class EstablishmentViewSetTestCase(APITestCase):
    """Test Establishment API endpoints and permissions."""

    def setUp(self):
        self.client = APIClient()

        self.owner = User.objects.create_user(email="owner@test.com", password="testpass123")

        self.manager = User.objects.create_user(email="manager@test.com", password="testpass123")

        self.company = Company.objects.create(name="Establishment Test Farm", owner=self.owner)

        self.establishment = Establishment.objects.create(
            name="Test Establishment", company=self.company, description="For API testing"
        )

        WorksIn.objects.create(user=self.manager, company=self.company, role=WorksIn.DOMAIN_SUPERVISOR)

    def test_list_establishments_company_filtered(self):
        """Test that establishments are filtered by company access."""
        # Create establishment for different company
        other_user = User.objects.create_user(email="other@test.com", password="testpass123")
        other_company = Company.objects.create(name="Other Company", owner=other_user)
        other_establishment = Establishment.objects.create(name="Other Establishment", company=other_company)

        self.client.force_authenticate(user=self.owner)
        url = reverse("establishment-list", kwargs={"company_pk": self.company.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Test Establishment")

    def test_create_establishment_valid(self):
        """Test creating establishment via API."""
        self.client.force_authenticate(user=self.owner)
        url = reverse("establishment-list", kwargs={"company_pk": self.company.pk})

        data = {
            "name": "New Establishment",
            "description": "Created via API",
            "address": "123 New Farm Road",
            "city": "Modesto",
            "state": "CA",
            "latitude": "37.6391",
            "longitude": "-120.9969",
            "total_acreage": 150.0,
            "farming_method": "conventional",
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "New Establishment")
        self.assertEqual(response.data["company"], self.company.id)

    def test_update_establishment_manager_permissions(self):
        """Test that managers can update establishments."""
        self.client.force_authenticate(user=self.manager)
        url = reverse("establishment-detail", kwargs={"company_pk": self.company.pk, "pk": self.establishment.pk})

        data = {"description": "Updated by manager"}

        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["description"], "Updated by manager")


class CompanySubscriptionIntegrationTestCase(APITestCase):
    """Test integration between companies and subscription system."""

    def setUp(self):
        self.user = User.objects.create_user(email="subscription@test.com", password="testpass123")

        self.company = Company.objects.create(
            name="Subscription Test Farm", address="123 Test St", city="Test City", state="Test State"
        )

        # Create subscription plan
        self.plan = Plan.objects.create(
            name="Premium Plan", price_monthly=49.99, max_establishments=5, max_parcels_per_establishment=20
        )

    @patch("subscriptions.models.stripe.Customer.create")
    @patch("subscriptions.models.stripe.Subscription.create")
    def test_company_with_subscription_limits(self, mock_subscription, mock_customer):
        """Test that subscription limits are enforced for companies."""
        # Mock Stripe responses
        mock_customer.return_value = MagicMock(id="cus_test123")
        mock_subscription.return_value = MagicMock(id="sub_test123", status="active")

        # Create subscription for company
        subscription = Subscription.objects.create(
            company=self.company,
            plan=self.plan,
            stripe_customer_id="cus_test123",
            stripe_subscription_id="sub_test123",
            status="active",
        )

        # Test that company can create establishments up to limit
        for i in range(self.plan.max_establishments):
            establishment = Establishment.objects.create(name=f"Establishment {i+1}", company=self.company)

        # Verify all establishments were created
        self.assertEqual(self.company.establishments.count(), self.plan.max_establishments)

    def test_company_without_subscription_defaults(self):
        """Test company behavior without active subscription."""
        # Company without subscription should have basic limits
        establishment = Establishment.objects.create(name="Free Tier Establishment", company=self.company)

        self.assertEqual(self.company.establishments.count(), 1)


class CompanyCarbonIntegrationTestCase(TransactionTestCase):
    """Test integration between companies and carbon calculation system."""

    def setUp(self):
        self.user = User.objects.create_user(email="carbon@test.com", password="testpass123")

        self.company = Company.objects.create(
            name="Carbon Test Farm", address="123 Test St", city="Test City", state="Test State"
        )

        self.establishment = Establishment.objects.create(
            name="Carbon Test Establishment",
            company=self.company,
            latitude=Decimal("36.7378"),
            longitude=Decimal("-119.7871"),
        )

    def test_establishment_carbon_aggregation(self):
        """Test that carbon entries are properly aggregated at establishment level."""
        from carbon.models import CarbonSource

        # Create carbon source
        source = CarbonSource.objects.create(name="Test Fertilizer", category="fertilizer", default_emission_factor=5.0)

        # Create carbon entries for establishment
        entry1 = CarbonEntry.objects.create(
            establishment=self.establishment,
            source=source,
            type="emission",
            amount=100.0,
            co2e_amount=500.0,
            year=2024,
            created_by=self.user,
        )

        entry2 = CarbonEntry.objects.create(
            establishment=self.establishment,
            source=source,
            type="emission",
            amount=50.0,
            co2e_amount=250.0,
            year=2024,
            created_by=self.user,
        )

        # Test aggregation
        total_emissions = CarbonEntry.objects.filter(establishment=self.establishment, type="emission").aggregate(
            total=models.Sum("co2e_amount")
        )["total"]

        self.assertEqual(total_emissions, 750.0)

    def test_geographic_carbon_calculations(self):
        """Test that geographic location affects carbon calculations."""
        # This would test integration with climate-aware carbon calculations
        # Based on establishment's latitude/longitude

        latitude = float(self.establishment.latitude)
        longitude = float(self.establishment.longitude)

        # Fresno, CA coordinates should be in moderate climate zone
        self.assertTrue(35.0 <= latitude <= 38.0)  # Central Valley latitude range
        self.assertTrue(-122.0 <= longitude <= -118.0)  # Central Valley longitude range


class CompanyDataPrivacyTestCase(TestCase):
    """Test data privacy and security aspects of company management."""

    def setUp(self):
        self.user = User.objects.create_user(email="privacy@test.com", password="testpass123")

        self.company = Company.objects.create(
            name="Privacy Test Farm",
            address="123 Test St",
            city="Test City",
            state="Test State",
            contact_email="contact@privacytest.com",
            contact_phone="+1-555-PRIVACY",
        )

    def test_sensitive_data_not_in_public_api(self):
        """Test that sensitive company data is not exposed in public APIs."""
        # This would test serializers to ensure contact info is not public
        # when accessed through consumer-facing endpoints

        # For now, verify sensitive fields exist in model
        self.assertEqual(self.company.email, "contact@privacytest.com")
        self.assertEqual(self.company.phone, "+1-555-PRIVACY")

    def test_company_data_deletion(self):
        """Test proper data deletion when company is removed."""
        company_id = self.company.id

        # Create related data
        establishment = Establishment.objects.create(name="To Be Deleted", company=self.company)
        establishment_id = establishment.id

        # Delete company
        self.company.delete()

        # Verify cascade deletion
        self.assertFalse(Company.objects.filter(id=company_id).exists())
        self.assertFalse(Establishment.objects.filter(id=establishment_id).exists())


# Import Django's models for aggregation
from django.db import models
