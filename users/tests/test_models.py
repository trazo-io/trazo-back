"""
Comprehensive Test Suite for Users App
Tests user models, API endpoints, permissions, and authentication flows
"""

import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from company.models import Company, Establishment
from subscriptions.models import Subscription
from users.constants import CONSUMER, PRODUCER, USER_TYPE_CHOICES
from users.managers import UserManager
from users.models import VerificationCode, WorksIn

User = get_user_model()


class TestUserManager(TestCase):
    """Test custom UserManager functionality"""

    def test_create_user_with_email(self):
        """Test creating user with email as username"""
        user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.assertEqual(user.email, "test@example.com")
        self.assertEqual(user.username, "test@example.com")
        self.assertTrue(user.check_password("testpass123"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_user_without_email(self):
        """Test creating user without email raises error"""
        with self.assertRaises(ValueError):
            User.objects.create_user(email=None, password="testpass123")

    def test_create_superuser(self):
        """Test creating superuser"""
        superuser = User.objects.create_superuser(email="admin@example.com", password="adminpass123")

        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)
        self.assertTrue(superuser.is_active)

    def test_create_superuser_validation(self):
        """Test superuser creation validation"""
        with self.assertRaises(ValueError):
            User.objects.create_superuser(email="admin@example.com", password="adminpass123", is_staff=False)

        with self.assertRaises(ValueError):
            User.objects.create_superuser(email="admin@example.com", password="adminpass123", is_superuser=False)


class TestUserModel(TransactionTestCase):
    """Test User model functionality"""

    def setUp(self):
        """Set up test data"""
        self.user_data = {
            "email": "test@example.com",
            "password": "testpass123",
            "first_name": "Test",
            "last_name": "User",
        }

    def test_user_creation_basic(self):
        """Test basic user creation"""
        user = User.objects.create_user(**self.user_data)

        self.assertEqual(user.email, "test@example.com")
        self.assertEqual(user.first_name, "Test")
        self.assertEqual(user.last_name, "User")
        self.assertEqual(user.user_type, CONSUMER)  # Default type
        self.assertFalse(user.is_verified)
        self.assertFalse(user.is_active)  # Default to False for email verification

    def test_user_email_uniqueness(self):
        """Test email uniqueness constraint"""
        User.objects.create_user(**self.user_data)

        with self.assertRaises(IntegrityError):
            User.objects.create_user(**self.user_data)

    def test_user_string_representation(self):
        """Test user string representation"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(str(user), "Test User")

        # Test with empty names
        user_no_name = User.objects.create_user(email="noname@example.com", password="testpass123")
        self.assertEqual(str(user_no_name), " ")

    def test_get_full_name_method(self):
        """Test get_full_name method"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(user.get_full_name(), "Test User")

    def test_user_types(self):
        """Test different user types"""
        # Consumer user
        consumer = User.objects.create_user(email="consumer@example.com", password="testpass123", user_type=CONSUMER)
        self.assertEqual(consumer.user_type, CONSUMER)

        # Producer user
        producer = User.objects.create_user(email="producer@example.com", password="testpass123", user_type=PRODUCER)
        self.assertEqual(producer.user_type, PRODUCER)

    def test_social_auth_fields(self):
        """Test social authentication fields"""
        user = User.objects.create_user(
            email="social@example.com",
            password="testpass123",
            social_auth_provider="google",
            social_auth_id="google_123456",
        )

        self.assertEqual(user.social_auth_provider, "google")
        self.assertEqual(user.social_auth_id, "google_123456")

    def test_user_image_field(self):
        """Test user image field"""
        user = User.objects.create_user(**self.user_data)
        self.assertIsNone(user.image.name)  # Should be empty initially

    def test_phone_field(self):
        """Test phone field"""
        user = User.objects.create_user(**self.user_data, phone="+1234567890")
        self.assertEqual(user.phone, "+1234567890")


class TestCompanyRelationships(TransactionTestCase):
    """Test user-company relationships"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.user)

        self.establishment = Establishment.objects.create(
            company=self.company, name="Test Farm", address="123 Farm Road", country="USA", created_by=self.user
        )

    def test_get_active_company(self):
        """Test get_active_company method"""
        # No subscription - should return None
        self.assertIsNone(self.user.get_active_company())

        # Create active subscription
        subscription = Subscription.objects.create(
            company=self.company,
            plan_type="professional",
            status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        # Add user to company
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)

        active_company = self.user.get_active_company()
        self.assertEqual(active_company, self.company)

    def test_get_trial_company(self):
        """Test get_trial_company method"""
        # No trial - should return None
        self.assertIsNone(self.user.get_trial_company())

        # Create trial subscription
        trial_subscription = Subscription.objects.create(
            company=self.company,
            plan_type="professional",
            status="trialing",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=14),
        )

        # Add user to company
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)

        trial_company = self.user.get_trial_company()
        self.assertEqual(trial_company, self.company)

    def test_multiple_companies(self):
        """Test user with multiple companies"""
        # Create second company
        company2 = Company.objects.create(name="Second Company", country="USA", created_by=self.user)

        # Add user to both companies
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)

        WorksIn.objects.create(user=self.user, company=company2, role=WorksIn.DOMAIN_SUPERVISOR)

        # Check user is associated with both
        self.assertEqual(self.user.companies.count(), 2)
        self.assertIn(self.company, self.user.companies.all())
        self.assertIn(company2, self.user.companies.all())


class TestWorksInModel(TransactionTestCase):
    """Test WorksIn relationship model"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.user)

        self.establishment = Establishment.objects.create(
            company=self.company, name="Test Farm", address="123 Farm Road", country="USA", created_by=self.user
        )

    def test_works_in_creation(self):
        """Test WorksIn relationship creation"""
        works_in = WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)

        self.assertEqual(works_in.user, self.user)
        self.assertEqual(works_in.company, self.company)
        self.assertEqual(works_in.role, WorksIn.COMPANY_ADMIN)

    def test_role_choices(self):
        """Test different role choices"""
        roles = [WorksIn.COMPANY_ADMIN, WorksIn.DOMAIN_SUPERVISOR, WorksIn.DOMAIN_WORKER, WorksIn.DEALER]

        for role in roles:
            works_in = WorksIn.objects.create(user=self.user, company=self.company, role=role)
            self.assertEqual(works_in.role, role)
            works_in.delete()  # Clean up for next iteration

    def test_establishments_in_charge(self):
        """Test establishments_in_charge relationship"""
        # Create manager role
        works_in = WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.DOMAIN_SUPERVISOR)

        # Assign establishment
        works_in.establishments_in_charge.add(self.establishment)

        self.assertEqual(works_in.establishments_in_charge.count(), 1)
        self.assertIn(self.establishment, works_in.establishments_in_charge.all())

    def test_multiple_establishments(self):
        """Test manager with multiple establishments"""
        # Create additional establishment
        establishment2 = Establishment.objects.create(
            company=self.company, name="Second Farm", address="456 Farm Road", country="USA", created_by=self.user
        )

        works_in = WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.DOMAIN_SUPERVISOR)

        # Assign both establishments
        works_in.establishments_in_charge.add(self.establishment, establishment2)

        self.assertEqual(works_in.establishments_in_charge.count(), 2)


class TestVerificationCodeModel(TransactionTestCase):
    """Test VerificationCode model functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

    def test_verification_code_creation(self):
        """Test verification code creation"""
        code = VerificationCode.objects.create(user=self.user, code="123456")

        self.assertEqual(code.user, self.user)
        self.assertEqual(code.code, "123456")
        self.assertIsNotNone(code.created_at)

    def test_verification_code_string_representation(self):
        """Test verification code string representation"""
        code = VerificationCode.objects.create(user=self.user, code="123456")

        expected = f"{self.user.email} - 123456"
        self.assertEqual(str(code), expected)

    def test_verification_code_uniqueness(self):
        """Test user-code uniqueness constraint"""
        VerificationCode.objects.create(user=self.user, code="123456")

        # Same user, same code should fail
        with self.assertRaises(IntegrityError):
            VerificationCode.objects.create(user=self.user, code="123456")

    def test_multiple_codes_per_user(self):
        """Test multiple different codes per user"""
        code1 = VerificationCode.objects.create(user=self.user, code="123456")

        code2 = VerificationCode.objects.create(user=self.user, code="654321")

        self.assertEqual(self.user.verification_code.count(), 2)
        self.assertIn(code1, self.user.verification_code.all())
        self.assertIn(code2, self.user.verification_code.all())


class TestUserAPIEndpoints(TestCase):
    """Test User API endpoints"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com", password="testpass123", first_name="Test", last_name="User", is_active=True
        )

    @patch("users.views.send_verification_email")
    def test_user_registration_endpoint(self, mock_send_email):
        """Test user registration API endpoint"""
        url = reverse("users:signup")

        data = {
            "email": "newuser@example.com",
            "password": "newpassword123",
            "first_name": "New",
            "last_name": "User",
            "user_type": PRODUCER,
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 201)

        # Verify user was created
        user = User.objects.get(email="newuser@example.com")
        self.assertEqual(user.first_name, "New")
        self.assertEqual(user.user_type, PRODUCER)
        self.assertFalse(user.is_active)  # Should require verification

    def test_user_login_endpoint(self):
        """Test user login API endpoint"""
        url = reverse("users:login")

        response = self.client.post(url, {"email": "test@example.com", "password": "testpass123"})

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)

    def test_user_profile_endpoint(self):
        """Test user profile API endpoint"""
        # Login to get token
        login_url = reverse("users:login")
        login_response = self.client.post(login_url, {"email": "test@example.com", "password": "testpass123"})

        token_data = json.loads(login_response.content)
        access_token = token_data["access_token"]

        # Get profile
        profile_url = reverse("users:profile")
        response = self.client.get(profile_url, HTTP_AUTHORIZATION=f"Bearer {access_token}")

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["email"], "test@example.com")

    def test_user_profile_update(self):
        """Test user profile update"""
        # Login to get token
        login_url = reverse("users:login")
        login_response = self.client.post(login_url, {"email": "test@example.com", "password": "testpass123"})

        token_data = json.loads(login_response.content)
        access_token = token_data["access_token"]

        # Update profile
        profile_url = reverse("users:profile")
        update_data = {"first_name": "Updated", "last_name": "Name", "phone": "+1234567890"}

        response = self.client.patch(
            profile_url,
            json.dumps(update_data),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

        self.assertEqual(response.status_code, 200)

        # Verify update
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")
        self.assertEqual(self.user.phone, "+1234567890")


class TestUserPermissions(TransactionTestCase):
    """Test user permissions and access control"""

    def setUp(self):
        """Set up test data"""
        self.admin_user = User.objects.create_user(email="admin@example.com", password="testpass123", is_active=True)

        self.regular_user = User.objects.create_user(email="user@example.com", password="testpass123", is_active=True)

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.admin_user)

        # Make admin user company admin
        WorksIn.objects.create(user=self.admin_user, company=self.company, role=WorksIn.COMPANY_ADMIN)

        self.client = Client()

    def test_company_admin_permissions(self):
        """Test company admin permissions"""
        self.client.force_login(self.admin_user)

        # Should be able to access company details
        url = reverse("company:detail", kwargs={"pk": self.company.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_unauthorized_access(self):
        """Test unauthorized user access"""
        self.client.force_login(self.regular_user)

        # Should not be able to access company not associated with
        url = reverse("company:detail", kwargs={"pk": self.company.id})
        response = self.client.get(url)
        self.assertIn(response.status_code, [403, 404])


class TestUserSecurity(TestCase):
    """Test user security features"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()

    def test_password_validation(self):
        """Test password validation rules"""
        url = reverse("users:signup")

        weak_passwords = ["123", "password", "abc", "12345678"]

        for weak_password in weak_passwords:
            response = self.client.post(
                url,
                {
                    "email": f"test{weak_password}@example.com",
                    "password": weak_password,
                    "first_name": "Test",
                    "last_name": "User",
                },
            )

            self.assertEqual(response.status_code, 400)

    def test_email_verification_requirement(self):
        """Test email verification requirement"""
        # Create unverified user
        user = User.objects.create_user(
            email="unverified@example.com", password="testpass123", is_active=False, is_verified=False
        )

        # Try to login - should fail for unverified user
        login_url = reverse("users:login")
        response = self.client.post(login_url, {"email": "unverified@example.com", "password": "testpass123"})

        self.assertNotEqual(response.status_code, 200)


class TestUserIntegrations(TransactionTestCase):
    """Test user integrations with other apps"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123", is_active=True)

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.user)

    def test_user_subscription_integration(self):
        """Test user subscription integration"""
        # Create subscription
        subscription = Subscription.objects.create(
            company=self.company,
            plan_type="professional",
            status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        # Add user to company
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)

        # Test active company method
        active_company = self.user.get_active_company()
        self.assertEqual(active_company, self.company)

    def test_user_company_cascade_behavior(self):
        """Test cascade behavior when company is deleted"""
        # Add user to company
        works_in = WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)

        company_id = self.company.id

        # Delete company
        self.company.delete()

        # WorksIn should be deleted too
        self.assertFalse(WorksIn.objects.filter(company_id=company_id).exists())

        # User should still exist
        self.assertTrue(User.objects.filter(id=self.user.id).exists())


if __name__ == "__main__":
    unittest.main()
