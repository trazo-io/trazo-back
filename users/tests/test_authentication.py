"""
Test Suite for User Authentication and Authorization
Ensures secure and reliable user management
"""

import json
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import authenticate, get_user_model
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from company.models import Company, Establishment
from users.models import VerificationCode, WorksIn

User = get_user_model()


class TestUserModel(TransactionTestCase):
    """Test custom User model functionality"""

    def test_user_creation(self):
        """Test user creation with email as username"""
        user = User.objects.create_user(
            email="test@example.com", password="Str0ng!Passw0rd", first_name="Test", last_name="User"
        )

        self.assertEqual(user.email, "test@example.com")
        self.assertIsNone(user.username)  # Username field is disabled, email is the unique identifier
        self.assertTrue(user.check_password("Str0ng!Passw0rd"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_active)  # Default is False, user must verify email first

    def test_user_creation_duplicate_email(self):
        """Test that duplicate emails are not allowed"""
        User.objects.create_user(email="test@example.com", password="Str0ng!Passw0rd")

        with self.assertRaises(Exception):
            User.objects.create_user(email="test@example.com", password="testpass456")  # Duplicate email

    def test_superuser_creation(self):
        """Test superuser creation"""
        superuser = User.objects.create_superuser(email="admin@example.com", password="adminpass123")

        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)
        self.assertTrue(superuser.is_active)

    def test_user_string_representation(self):
        """Test user string representation"""
        user = User.objects.create_user(email="test@example.com", first_name="Test", last_name="User")

        expected = "Test User"
        self.assertEqual(str(user), expected)

        # Test with only email
        user_no_name = User.objects.create_user(email="noname@example.com")
        self.assertEqual(str(user_no_name), "noname@example.com")


class TestEmailVerification(TransactionTestCase):
    """Test email verification functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            email="test@example.com", password="Str0ng!Passw0rd", first_name="Test", last_name="User"
        )

    def test_verification_code_creation(self):
        """Test verification code creation"""
        code = VerificationCode.objects.create(user=self.user, purpose="email_verification")

        self.assertEqual(code.user, self.user)
        self.assertEqual(code.purpose, "email_verification")
        self.assertIsNotNone(code.code)
        self.assertEqual(len(code.code), 6)  # Should be 6-digit code
        self.assertFalse(code.is_verified)

    def test_verification_code_expiry(self):
        """Test verification code expiry"""
        # Create expired code
        expired_code = VerificationCode.objects.create(user=self.user, purpose="email_verification")
        # Manually set to expired
        expired_code.created_at = timezone.now() - timedelta(hours=25)
        expired_code.save()

        self.assertTrue(expired_code.is_expired())

        # Create fresh code
        fresh_code = VerificationCode.objects.create(user=self.user, purpose="email_verification")

        self.assertFalse(fresh_code.is_expired())

    def test_verification_code_usage(self):
        """Test verification code can only be used once"""
        code = VerificationCode.objects.create(user=self.user, purpose="email_verification")

        # First use should succeed
        result = code.verify()
        self.assertTrue(result)
        self.assertTrue(code.is_verified)

        # Second use should fail
        result = code.verify()
        self.assertFalse(result)

    def test_multiple_verification_codes(self):
        """Test multiple verification codes per user"""
        # Create first code
        code1 = VerificationCode.objects.create(user=self.user, purpose="email_verification")

        # Create second code (should invalidate first)
        code2 = VerificationCode.objects.create(user=self.user, purpose="email_verification")

        # Refresh first code from database
        code1.refresh_from_db()

        # Only latest code should be valid
        self.assertFalse(code1.verify())
        self.assertTrue(code2.verify())


class TestAuthentication(TestCase):
    """Test authentication functionality"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com", password="Str0ng!Passw0rd", first_name="Test", last_name="User"
        )

    def test_email_authentication(self):
        """Test authentication with email"""
        user = authenticate(username="test@example.com", password="Str0ng!Passw0rd")

        self.assertIsNotNone(user)
        self.assertEqual(user.email, "test@example.com")

    def test_authentication_failure(self):
        """Test authentication failure"""
        # Wrong password
        user = authenticate(username="test@example.com", password="wrongpassword")
        self.assertIsNone(user)

        # Wrong email
        user = authenticate(username="wrong@example.com", password="Str0ng!Passw0rd")
        self.assertIsNone(user)

    @patch("users.views.send_verification_email")
    def test_login_api_endpoint(self, mock_send_email):
        """Test login API endpoint"""
        url = reverse("users:login")

        # Valid login
        response = self.client.post(url, {"email": "test@example.com", "password": "Str0ng!Passw0rd"})

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        self.assertIn("user", data)

        # Invalid login
        response = self.client.post(url, {"email": "test@example.com", "password": "wrongpassword"})

        self.assertEqual(response.status_code, 400)

    @patch("users.views.send_verification_email")
    def test_signup_api_endpoint(self, mock_send_email):
        """Test signup API endpoint"""
        url = reverse("users:signup")

        # Valid signup
        response = self.client.post(
            url,
            {"email": "newuser@example.com", "password": "newpassword123", "first_name": "New", "last_name": "User"},
        )

        self.assertEqual(response.status_code, 201)
        data = json.loads(response.content)
        self.assertIn("user", data)
        self.assertEqual(data["user"]["email"], "newuser@example.com")

        # Verify user was created
        user = User.objects.get(email="newuser@example.com")
        self.assertIsNotNone(user)

        # Verify verification email was sent
        mock_send_email.assert_called_once()

    def test_password_validation(self):
        """Test password validation"""
        url = reverse("users:signup")

        # Weak password
        response = self.client.post(
            url,
            {"email": "weak@example.com", "password": "123", "first_name": "Weak", "last_name": "Password"},  # Too weak
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn("password", data)


class TestAuthorization(TransactionTestCase):
    """Test authorization and role-based access control"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()

        # Create users
        self.admin_user = User.objects.create_user(email="admin@example.com", password="Str0ng!Passw0rd")

        self.manager_user = User.objects.create_user(email="manager@example.com", password="Str0ng!Passw0rd")

        self.viewer_user = User.objects.create_user(email="viewer@example.com", password="Str0ng!Passw0rd")

        # Create company and establishment
        self.company = Company.objects.create(name="Test Company", country="USA")

        self.establishment = Establishment.objects.create(
            company=self.company, name="Test Farm", address="123 Farm Road", country="USA"
        )

        # Create role assignments
        WorksIn.objects.create(user=self.admin_user, company=self.company, role="company_admin")

        WorksIn.objects.create(
            user=self.manager_user,
            company=self.company,
            role="farm_manager",
            establishments_in_charge=[self.establishment.id],
        )

        WorksIn.objects.create(user=self.viewer_user, company=self.company, role="viewer")

    def test_company_admin_permissions(self):
        """Test company admin has full access"""
        self.client.force_login(self.admin_user)

        # Should be able to access company management
        url = reverse("company:detail", kwargs={"pk": self.company.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Should be able to create establishments
        url = reverse("company:establishment-create")
        response = self.client.post(
            url, {"name": "New Farm", "address": "456 New Road", "country": "USA", "company": self.company.id}
        )
        self.assertIn(response.status_code, [200, 201, 302])  # Success or redirect

    def test_farm_manager_permissions(self):
        """Test farm manager has limited access"""
        self.client.force_login(self.manager_user)

        # Should be able to access assigned establishment
        url = reverse("company:establishment-detail", kwargs={"pk": self.establishment.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Should NOT be able to delete company
        url = reverse("company:delete", kwargs={"pk": self.company.id})
        response = self.client.delete(url)
        self.assertIn(response.status_code, [403, 404, 405])  # Forbidden or not allowed

    def test_viewer_permissions(self):
        """Test viewer has read-only access"""
        self.client.force_login(self.viewer_user)

        # Should be able to view company
        url = reverse("company:detail", kwargs={"pk": self.company.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Should NOT be able to modify anything
        url = reverse("company:establishment-create")
        response = self.client.post(
            url,
            {
                "name": "Unauthorized Farm",
                "address": "789 Unauthorized Road",
                "country": "USA",
                "company": self.company.id,
            },
        )
        self.assertIn(response.status_code, [403, 405])  # Forbidden

    def test_unauthorized_access(self):
        """Test unauthorized users cannot access protected resources"""
        # Not logged in
        url = reverse("company:detail", kwargs={"pk": self.company.id})
        response = self.client.get(url)
        self.assertIn(response.status_code, [401, 302, 403])  # Unauthorized or redirect

        # Create user not associated with company
        unauthorized_user = User.objects.create_user(email="unauthorized@example.com", password="Str0ng!Passw0rd")
        self.client.force_login(unauthorized_user)

        response = self.client.get(url)
        self.assertIn(response.status_code, [403, 404])  # Forbidden or not found


class TestJWTAuthentication(TestCase):
    """Test JWT token authentication"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="Str0ng!Passw0rd")
        self.client = Client()

    @patch("users.views.send_verification_email")
    def test_token_generation(self, mock_send_email):
        """Test JWT token generation on login"""
        url = reverse("users:login")

        response = self.client.post(url, {"email": "test@example.com", "password": "Str0ng!Passw0rd"})

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        self.assertIsInstance(data["access_token"], str)
        self.assertIsInstance(data["refresh_token"], str)

    def test_token_refresh(self):
        """Test JWT token refresh"""
        # Get initial tokens
        login_url = reverse("users:login")
        response = self.client.post(login_url, {"email": "test@example.com", "password": "Str0ng!Passw0rd"})

        data = json.loads(response.content)
        refresh_token = data["refresh_token"]

        # Use refresh token to get new access token
        refresh_url = reverse("users:token-refresh")
        response = self.client.post(refresh_url, {"refresh": refresh_token})

        self.assertEqual(response.status_code, 200)
        refresh_data = json.loads(response.content)
        self.assertIn("access", refresh_data)

    def test_protected_endpoint_access(self):
        """Test accessing protected endpoints with JWT"""
        # Get token
        login_url = reverse("users:login")
        response = self.client.post(login_url, {"email": "test@example.com", "password": "Str0ng!Passw0rd"})

        data = json.loads(response.content)
        access_token = data["access_token"]

        # Access protected endpoint
        protected_url = reverse("users:profile")

        # Without token - should fail
        response = self.client.get(protected_url)
        self.assertIn(response.status_code, [401, 403])

        # With token - should succeed
        response = self.client.get(protected_url, HTTP_AUTHORIZATION=f"Bearer {access_token}")
        self.assertEqual(response.status_code, 200)

    def test_token_expiration(self):
        """Test JWT token expiration handling"""
        from datetime import timedelta

        from django.conf import settings

        # Mock short token expiration
        with patch.object(
            settings,
            "SIMPLE_JWT",
            {**getattr(settings, "SIMPLE_JWT", {}), "ACCESS_TOKEN_LIFETIME": timedelta(seconds=1)},
        ):
            # Get token
            login_url = reverse("users:login")
            response = self.client.post(login_url, {"email": "test@example.com", "password": "Str0ng!Passw0rd"})

            data = json.loads(response.content)
            access_token = data["access_token"]

            # Wait for expiration
            import time

            time.sleep(2)

            # Try to use expired token
            protected_url = reverse("users:profile")
            response = self.client.get(protected_url, HTTP_AUTHORIZATION=f"Bearer {access_token}")

            self.assertIn(response.status_code, [401, 403])


class TestSocialAuthentication(TestCase):
    """Test social authentication integration"""

    @patch("allauth.socialaccount.models.SocialApp.objects.get")
    def test_google_oauth_configuration(self, mock_get_app):
        """Test Google OAuth configuration"""
        from allauth.socialaccount.models import SocialApp

        # Mock social app
        mock_app = MagicMock()
        mock_app.client_id = "test_google_client_id"
        mock_app.secret = "test_google_secret"
        mock_get_app.return_value = mock_app

        # Test configuration
        app = SocialApp.objects.get(provider="google")
        self.assertEqual(app.client_id, "test_google_client_id")

    def test_social_account_creation(self):
        """Test social account user creation"""
        from allauth.socialaccount.models import SocialAccount

        # Create social account
        social_account = SocialAccount.objects.create(
            user=self.user,
            provider="google",
            uid="google_user_123",
            extra_data={"email": "test@example.com", "name": "Test User"},
        )

        self.assertEqual(social_account.user, self.user)
        self.assertEqual(social_account.provider, "google")
        self.assertEqual(social_account.uid, "google_user_123")


class TestSecurityFeatures(TestCase):
    """Test security features and protections"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="Str0ng!Passw0rd")
        self.client = Client()

    def test_rate_limiting(self):
        """Test login rate limiting"""
        url = reverse("users:login")

        # Make multiple failed login attempts
        for i in range(6):  # Exceed rate limit
            response = self.client.post(url, {"email": "test@example.com", "password": "wrongpassword"})

        # Should be rate limited
        self.assertIn(response.status_code, [429, 400])

    def test_password_security(self):
        """Test password security requirements"""
        # Test password strength validation
        weak_passwords = [
            "123",
            "password",
            "abc",
            "12345678",
        ]

        for weak_password in weak_passwords:
            with self.assertRaises(Exception):
                User.objects.create_user(email=f"test{weak_password}@example.com", password=weak_password)

    def test_session_security(self):
        """Test session security settings"""
        from django.conf import settings

        # Check secure session settings
        self.assertTrue(getattr(settings, "SESSION_COOKIE_HTTPONLY", False))
        self.assertEqual(getattr(settings, "SESSION_COOKIE_SAMESITE", None), "Lax")

    def test_csrf_protection(self):
        """Test CSRF protection"""
        from django.middleware.csrf import get_token

        # Get CSRF token
        request = self.client.get("/").wsgi_request
        csrf_token = get_token(request)

        self.assertIsNotNone(csrf_token)
        self.assertTrue(len(csrf_token) > 10)

    @patch("users.utils.send_verification_email")
    def test_resend_verification_email(self, mock_send_email):
        """Test resend verification email endpoint"""

        # Create an unverified user
        user = User.objects.create_user(
            email="unverified@example.com",
            password="Str0ng!Passw0rd",
            first_name="Test",
            last_name="User",
            is_verified=False,
        )

        # Mock successful email sending
        mock_send_email.return_value = True

        # Test resend verification email
        url = "/api/users/resend_verification_email/"
        response = self.client.post(url, {"email": "unverified@example.com"}, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["message"], "Verification email sent successfully")

        # Verify that a new verification code was created
        verification_code = VerificationCode.objects.filter(user=user).last()
        self.assertIsNotNone(verification_code)

        # Verify email function was called
        mock_send_email.assert_called_once()

    def test_resend_verification_email_already_verified(self):
        """Test resend verification email for already verified user"""
        # Create a verified user
        user = User.objects.create_user(
            email="verified@example.com",
            password="Str0ng!Passw0rd",
            first_name="Test",
            last_name="User",
            is_verified=True,
        )

        # Test resend verification email for verified user
        url = "/api/users/resend_verification_email/"
        response = self.client.post(url, {"email": "verified@example.com"}, content_type="application/json")

        # 🔴 2026-09-07 — this asserted 400 "User is already verified". That answer tells an
        # unauthenticated caller which addresses are registered AND which are already verified,
        # which is account enumeration. `users/views.py resend_verification_email` deliberately
        # returns the same generic 200 for every address, and its comment says so. The test was
        # demanding the insecure behaviour: obeying it would have reopened the hole.
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["message"], "If an account exists, a verification email has been sent")

    def test_resend_verification_email_nonexistent_user(self):
        """Test resend verification email for non-existent user"""
        url = "/api/users/resend_verification_email/"
        response = self.client.post(url, {"email": "nonexistent@example.com"}, content_type="application/json")

        # Same enumeration rule as the already-verified case above: an unknown address must be
        # indistinguishable from a known one. 404 "User with this email does not exist" is a
        # membership oracle.
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["message"], "If an account exists, a verification email has been sent")

    def test_resend_verification_email_missing_email(self):
        """Test resend verification email with missing email"""
        url = "/api/users/resend_verification_email/"
        response = self.client.post(url, {}, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertEqual(data["error"], "Email is required")


if __name__ == "__main__":
    unittest.main()
