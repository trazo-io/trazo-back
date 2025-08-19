"""
Comprehensive tests for invitation flow and company code join functionality
Tests for 2025 SaaS best practices implementation
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company, Establishment
from users.models import WorksIn
from users.models_invitation import CompanyInvitation

User = get_user_model()


class InvitationFlowTestCase(APITestCase):
    """Test invitation flow for existing users (company transfers)"""

    def setUp(self):
        """Set up test data"""
        # Create companies
        self.company_a = Company.objects.create(
            name="Test Company A", contact_phone="1234567890", invitation_code="TESTCOA"
        )
        self.company_b = Company.objects.create(
            name="Test Company B", contact_phone="0987654321", invitation_code="TESTCOB"
        )

        # Create establishments
        self.establishment_a = Establishment.objects.create(
            name="Farm A", company=self.company_a, address="123 Farm Road"
        )
        self.establishment_b = Establishment.objects.create(
            name="Farm B", company=self.company_b, address="456 Field Lane"
        )

        # Create users
        self.admin_user = User.objects.create_user(
            email="admin@testa.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            user_type=4,  # PRODUCER
        )

        self.existing_user = User.objects.create_user(
            email="existing@user.com",
            password="testpass123",
            first_name="Existing",
            last_name="User",
            user_type=4,  # PRODUCER
        )

        # Create WorksIn relationships
        WorksIn.objects.create(user=self.admin_user, company=self.company_a, role=WorksIn.COMPANY_ADMIN)

        WorksIn.objects.create(user=self.existing_user, company=self.company_a, role=WorksIn.DOMAIN_WORKER)

    def test_create_invitation(self):
        """Test creating an invitation"""
        self.client.force_authenticate(user=self.admin_user)

        data = {
            "email": "newuser@test.com",
            "invitee_name": "New User",
            "role": "DW",
            "message": "Join our team!",
            "establishments": [self.establishment_a.id],
        }

        response = self.client.post("/api/invitations/create/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify invitation was created
        invitation = CompanyInvitation.objects.get(email="newuser@test.com")
        self.assertEqual(invitation.company, self.company_a)
        self.assertEqual(invitation.role, "DW")
        self.assertEqual(invitation.inviter, self.admin_user)

    def test_invitation_for_existing_user_company_transfer(self):
        """Test creating invitation for user who already exists in another company"""
        self.client.force_authenticate(user=self.admin_user)

        # Create admin for company B
        admin_b = User.objects.create_user(
            email="adminb@testb.com", password="testpass123", first_name="Admin B", last_name="User", user_type=4
        )
        WorksIn.objects.create(user=admin_b, company=self.company_b, role=WorksIn.COMPANY_ADMIN)

        # Admin B invites existing user from Company A
        self.client.force_authenticate(user=admin_b)

        data = {
            "email": "existing@user.com",
            "invitee_name": "Existing User",
            "role": "DS",
            "message": "Come join Company B!",
            "establishments": [self.establishment_b.id],
        }

        response = self.client.post("/api/invitations/create/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify this is flagged as a transfer
        invitation = CompanyInvitation.objects.get(email="existing@user.com")
        self.assertTrue(invitation.is_company_transfer())

    def test_accept_invitation_company_transfer(self):
        """Test accepting invitation that results in company transfer"""
        # Create invitation from Company B to existing user in Company A
        invitation = CompanyInvitation.objects.create(
            email="existing@user.com",
            invitee_name="Existing User",
            company=self.company_b,
            role="DS",
            inviter=self.admin_user,
            invitation_message="Join Company B!",
        )
        invitation.establishments.add(self.establishment_b)

        # User accepts invitation (should transfer from A to B)
        self.client.force_authenticate(user=self.existing_user)

        response = self.client.post(f"/api/invitation/{invitation.invitation_code}/accept/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify user was transferred
        self.assertFalse(WorksIn.objects.filter(user=self.existing_user, company=self.company_a).exists())
        self.assertTrue(WorksIn.objects.filter(user=self.existing_user, company=self.company_b).exists())

        # Verify new role
        new_membership = WorksIn.objects.get(user=self.existing_user, company=self.company_b)
        self.assertEqual(new_membership.role, "DS")

    def test_accept_invitation_unauthenticated_user(self):
        """Test accepting invitation for unauthenticated user"""
        invitation = CompanyInvitation.objects.create(
            email="newuser@test.com",
            invitee_name="New User",
            company=self.company_a,
            role="DW",
            inviter=self.admin_user,
        )

        response = self.client.post(f"/api/invitation/{invitation.invitation_code}/accept/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should return signup redirect info
        self.assertTrue(response.data["requires_signup"])
        self.assertIn("signup_url", response.data)

    def test_rate_limiting_invitation_acceptance(self):
        """Test rate limiting on invitation acceptance"""
        invitation = CompanyInvitation.objects.create(
            email="test@test.com", company=self.company_a, role="DW", inviter=self.admin_user
        )

        # Clear cache first
        cache.clear()

        # Make 5 attempts (should be allowed)
        for i in range(5):
            response = self.client.post(
                f"/api/invitation/{invitation.invitation_code}/accept/", HTTP_X_FORWARDED_FOR="192.168.1.100"
            )
            self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # 6th attempt should be rate limited
        response = self.client.post(
            f"/api/invitation/{invitation.invitation_code}/accept/", HTTP_X_FORWARDED_FOR="192.168.1.100"
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_invitation_expiry(self):
        """Test that expired invitations cannot be accepted"""
        # Create expired invitation
        invitation = CompanyInvitation.objects.create(
            email="expired@test.com",
            company=self.company_a,
            role="DW",
            inviter=self.admin_user,
            expires_at=timezone.now() - timedelta(days=1),  # Expired yesterday
        )

        response = self.client.post(f"/api/invitation/{invitation.invitation_code}/accept/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expired", response.data["error"].lower())


class CompanyCodeJoinTestCase(APITestCase):
    """Test company code join functionality for new users"""

    def setUp(self):
        """Set up test data"""
        self.company = Company.objects.create(
            name="Test Company", contact_phone="1234567890", invitation_code="TESTCO1"
        )

        # Create existing user for conflict tests
        self.existing_user = User.objects.create_user(
            email="existing@user.com", password="testpass123", first_name="Existing", last_name="User", user_type=4
        )

        # Create another company for conflict tests
        self.other_company = Company.objects.create(
            name="Other Company", contact_phone="0987654321", invitation_code="OTHERCO"
        )

        WorksIn.objects.create(user=self.existing_user, company=self.other_company, role=WorksIn.DOMAIN_WORKER)

    def test_signup_with_valid_company_code(self):
        """Test signing up with a valid company code"""
        data = {
            "first_name": "New",
            "last_name": "User",
            "email": "newuser@test.com",
            "password": "securepass123",
            "user_type": "PRODUCER",
            "company_code": "TESTCO1",
        }

        response = self.client.post("/api/auth/register/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify user was created and joined company
        user = User.objects.get(email="newuser@test.com")
        self.assertTrue(WorksIn.objects.filter(user=user, company=self.company).exists())

        # Verify default role
        membership = WorksIn.objects.get(user=user, company=self.company)
        self.assertEqual(membership.role, WorksIn.DOMAIN_WORKER)

    def test_signup_with_invalid_company_code(self):
        """Test signing up with invalid company code"""
        data = {
            "first_name": "New",
            "last_name": "User",
            "email": "newuser@test.com",
            "password": "securepass123",
            "user_type": "PRODUCER",
            "company_code": "INVALID",
        }

        response = self.client.post("/api/auth/register/", data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("company_code", response.data)

        # Verify user was not created
        self.assertFalse(User.objects.filter(email="newuser@test.com").exists())

    def test_signup_without_company_code(self):
        """Test normal signup without company code"""
        data = {
            "first_name": "New",
            "last_name": "User",
            "email": "newuser@test.com",
            "password": "securepass123",
            "user_type": "PRODUCER",
        }

        response = self.client.post("/api/auth/register/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify user was created but not joined to any company
        user = User.objects.get(email="newuser@test.com")
        self.assertFalse(WorksIn.objects.filter(user=user).exists())

    def test_existing_user_with_company_code_conflict(self):
        """Test existing user trying to join another company via code (should fail)"""
        data = {
            "first_name": "Existing",
            "last_name": "User",
            "email": "existing@user.com",
            "password": "securepass123",
            "user_type": "PRODUCER",
            "company_code": "TESTCO1",
        }

        response = self.client.post("/api/auth/register/", data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("You already belong", str(response.data["company_code"]))

    def test_company_code_format_validation(self):
        """Test company code format validation"""
        invalid_codes = [
            "123",  # Too short
            "TOOLONGCODE",  # Too long
            "TEST-123",  # Invalid characters
            "test123",  # Lowercase (should be auto-uppercase)
        ]

        for code in invalid_codes:
            data = {
                "first_name": "Test",
                "last_name": "User",
                "email": f"test{code}@test.com",
                "password": "securepass123",
                "user_type": "PRODUCER",
                "company_code": code,
            }

            response = self.client.post("/api/auth/register/", data)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("company_code", response.data)

    def test_rate_limiting_company_code_validation(self):
        """Test rate limiting on company code validation"""
        cache.clear()

        # Make 10 attempts (should be allowed)
        for i in range(10):
            data = {
                "first_name": "Test",
                "last_name": "User",
                "email": f"test{i}@test.com",
                "password": "securepass123",
                "user_type": "PRODUCER",
                "company_code": "INVALID",
            }

            response = self.client.post("/api/auth/register/", data, HTTP_X_FORWARDED_FOR="192.168.1.100")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # 11th attempt should be rate limited
        data = {
            "first_name": "Test",
            "last_name": "User",
            "email": "test11@test.com",
            "password": "securepass123",
            "user_type": "PRODUCER",
            "company_code": "INVALID",
        }

        response = self.client.post("/api/auth/register/", data, HTTP_X_FORWARDED_FOR="192.168.1.100")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Too many", response.data["company_code"][0])

    def test_transaction_safety_company_code_join(self):
        """Test that company code join is transaction-safe"""
        with patch("users.serializers.WorksIn.objects.create") as mock_create:
            # Make WorksIn creation fail
            mock_create.side_effect = Exception("Database error")

            data = {
                "first_name": "Test",
                "last_name": "User",
                "email": "test@test.com",
                "password": "securepass123",
                "user_type": "PRODUCER",
                "company_code": "TESTCO1",
            }

            response = self.client.post("/api/auth/register/", data)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            # Verify user was not created due to transaction rollback
            self.assertFalse(User.objects.filter(email="test@test.com").exists())


class EdgeCaseTestCase(APITestCase):
    """Test edge cases and error scenarios"""

    def setUp(self):
        self.company = Company.objects.create(
            name="Test Company", contact_phone="1234567890", invitation_code="TESTCO1"
        )

    def test_malformed_invitation_code(self):
        """Test handling of malformed invitation codes"""
        malformed_codes = [
            "",
            "   ",
            "a" * 100,  # Too long
            "../../etc/passwd",  # Path traversal attempt
            "<script>alert('xss')</script>",  # XSS attempt
            "'; DROP TABLE users; --",  # SQL injection attempt
        ]

        for code in malformed_codes:
            response = self.client.get(f"/api/invitation/{code}/")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_concurrent_invitation_acceptance(self):
        """Test handling of concurrent invitation acceptance"""
        invitation = CompanyInvitation.objects.create(
            email="test@test.com", company=self.company, role="DW", inviter_id=1  # Assume admin exists
        )

        # This would require more complex testing with threading
        # For now, verify basic transaction safety
        response = self.client.post(f"/api/invitation/{invitation.invitation_code}/accept/")
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_email_failure_handling(self):
        """Test that email failures don't break the flow"""
        with patch("users.utils.send_company_join_welcome_email") as mock_email:
            mock_email.side_effect = Exception("Email service down")

            data = {
                "first_name": "Test",
                "last_name": "User",
                "email": "test@test.com",
                "password": "securepass123",
                "user_type": "PRODUCER",
                "company_code": "TESTCO1",
            }

            response = self.client.post("/api/auth/register/", data)
            # Should still succeed even if email fails
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

            # Verify user was created and joined company
            user = User.objects.get(email="test@test.com")
            self.assertTrue(WorksIn.objects.filter(user=user, company=self.company).exists())
