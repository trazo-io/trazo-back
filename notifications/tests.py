import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from company.models import Company
from history.models import Production
from product.models import Parcel
from reviews.models import Review

from .models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
    NotificationPriority,
    NotificationTemplate,
    NotificationType,
)
from .services import NotificationService

User = get_user_model()


class NotificationModelTests(TestCase):
    """Test notification models"""

    def setUp(self):
        self.user1 = User.objects.create_user(
            email="user1@example.com", password="testpass123", first_name="John", last_name="Doe"
        )
        self.user2 = User.objects.create_user(
            email="user2@example.com", password="testpass123", first_name="Jane", last_name="Smith"
        )

    def test_notification_creation(self):
        """Test creating a notification"""
        notification = Notification.objects.create(
            recipient=self.user1,
            actor=self.user2,
            type=NotificationType.PRODUCT_SCAN,
            priority=NotificationPriority.MEDIUM,
            title="Test Notification",
            message="This is a test message",
            extra_data={"test": True},
        )

        self.assertEqual(notification.recipient, self.user1)
        self.assertEqual(notification.actor, self.user2)
        self.assertEqual(notification.type, NotificationType.PRODUCT_SCAN)
        self.assertEqual(notification.priority, NotificationPriority.MEDIUM)
        self.assertEqual(notification.title, "Test Notification")
        self.assertEqual(notification.message, "This is a test message")
        self.assertFalse(notification.read)
        self.assertFalse(notification.delivered)
        self.assertEqual(notification.extra_data, {"test": True})

    def test_notification_mark_as_read(self):
        """Test marking notification as read"""
        notification = Notification.objects.create(
            recipient=self.user1, type=NotificationType.SYSTEM_ALERT, title="Test", message="Test message"
        )

        self.assertFalse(notification.read)
        self.assertIsNone(notification.read_at)

        notification.mark_as_read()

        self.assertTrue(notification.read)
        self.assertIsNotNone(notification.read_at)

    def test_notification_mark_as_delivered(self):
        """Test marking notification as delivered"""
        notification = Notification.objects.create(
            recipient=self.user1, type=NotificationType.SYSTEM_ALERT, title="Test", message="Test message"
        )

        self.assertFalse(notification.delivered)
        self.assertIsNone(notification.delivered_at)

        notification.mark_as_delivered()

        self.assertTrue(notification.delivered)
        self.assertIsNotNone(notification.delivered_at)

    def test_notification_preferences_creation(self):
        """Test creating notification preferences"""
        preferences = NotificationPreference.objects.create(
            user=self.user1, product_scan_enabled=True, product_review_enabled=False, realtime_notifications=True
        )

        self.assertEqual(preferences.user, self.user1)
        self.assertTrue(preferences.product_scan_enabled)
        self.assertFalse(preferences.product_review_enabled)
        self.assertTrue(preferences.realtime_notifications)

    def test_notification_channel_creation(self):
        """Test creating notification channel"""
        channel = NotificationChannel.objects.create(
            user=self.user1, channel_name="test_channel_123", user_agent="Mozilla/5.0", ip_address="192.168.1.1"
        )

        self.assertEqual(channel.user, self.user1)
        self.assertEqual(channel.channel_name, "test_channel_123")
        self.assertEqual(channel.user_agent, "Mozilla/5.0")
        self.assertEqual(channel.ip_address, "192.168.1.1")

    def test_notification_template_render(self):
        """Test notification template rendering"""
        template = NotificationTemplate.objects.create(
            type=NotificationType.PRODUCT_SCAN,
            title_template="Product Scanned: {product_name}",
            message_template="{scanner_name} scanned your product {product_name} from {location}",
            variables={"product_name": "string", "scanner_name": "string", "location": "string"},
        )

        context = {"product_name": "Organic Apples", "scanner_name": "John Doe", "location": "New York"}

        title, message = template.render(context)

        self.assertEqual(title, "Product Scanned: Organic Apples")
        self.assertEqual(message, "John Doe scanned your product Organic Apples from New York")


# NOTHING IS PATCHED FOR DELIVERY, BECAUSE THERE IS NO DELIVERY.
#
# Five tests here patched `notifications.services.send_notification_to_user` and asserted
# `mock_send.called`. That function does not exist and `NotificationService` has no websocket,
# email or push path at all: `create_notification` writes a row and returns it. The frontend
# POLLS `/api/notifications/`. So the assertion was testing a real-time mechanism the product
# does not have, and `mock.patch` raised on the missing attribute before any test body ran.
#
# What IS worth asserting is that a notification comes back at all: `create_notification`
# swallows every exception and returns None, so `assertIsNotNone` is the only thing standing
# between a silent write failure and a green suite.
class NotificationServiceTests(TestCase):
    """Test notification service"""

    def setUp(self):
        self.user1 = User.objects.create_user(
            email="user1@example.com", password="testpass123", first_name="John", last_name="Doe"
        )
        self.user2 = User.objects.create_user(
            email="user2@example.com", password="testpass123", first_name="Jane", last_name="Smith"
        )
        self.service = NotificationService()

    def test_create_notification(self):
        """Test creating a notification via service"""
        notification = self.service.create_notification(
            recipient=self.user1,
            notification_type=NotificationType.PRODUCT_SCAN,
            title="Test Notification",
            message="Test message",
            actor=self.user2,
            priority=NotificationPriority.HIGH,
        )

        self.assertIsNotNone(notification)
        self.assertEqual(notification.recipient, self.user1)
        self.assertEqual(notification.actor, self.user2)
        self.assertEqual(notification.type, NotificationType.PRODUCT_SCAN)
        self.assertEqual(notification.priority, NotificationPriority.HIGH)

    def test_create_product_scan_notification(self):
        """Test creating product scan notification"""
        notification = self.service.create_product_scan_notification(
            product_owner=self.user1, scanner=self.user2, product_name="Organic Apples", scan_location="New York, USA"
        )

        self.assertIsNotNone(notification)
        self.assertEqual(notification.type, NotificationType.PRODUCT_SCAN)
        self.assertEqual(notification.recipient, self.user1)
        self.assertEqual(notification.actor, self.user2)
        self.assertIn("Organic Apples", notification.title)
        self.assertIn("Jane Smith", notification.message)
        self.assertIn("New York, USA", notification.message)

    def test_create_product_review_notification(self):
        """Test creating product review notification"""
        notification = self.service.create_product_review_notification(
            product_owner=self.user1,
            reviewer=self.user2,
            product_name="Organic Apples",
            rating=5,
            review_text="Great product!",
        )

        self.assertIsNotNone(notification)
        self.assertEqual(notification.type, NotificationType.PRODUCT_REVIEW)
        self.assertEqual(notification.recipient, self.user1)
        self.assertEqual(notification.actor, self.user2)
        self.assertEqual(notification.priority, NotificationPriority.HIGH)
        self.assertIn("Organic Apples", notification.title)
        self.assertIn("Jane Smith", notification.message)
        self.assertEqual(notification.extra_data["rating"], 5)
        self.assertEqual(notification.extra_data["review_text"], "Great product!")

    def test_notification_blocked_by_preferences(self):
        """Test notification is not sent when blocked by user preferences"""
        # Create preferences that disable product scan notifications
        NotificationPreference.objects.create(user=self.user1, product_scan_enabled=False)

        notification = self.service.create_product_scan_notification(
            product_owner=self.user1, scanner=self.user2, product_name="Organic Apples"
        )

        # Should return None when notification is blocked
        self.assertIsNone(notification)

    def test_get_user_notifications(self):
        """Test getting user notifications"""
        # Create test notifications
        n1 = Notification.objects.create(
            recipient=self.user1, type=NotificationType.PRODUCT_SCAN, title="Notification 1", message="Message 1"
        )
        n2 = Notification.objects.create(
            recipient=self.user1,
            type=NotificationType.PRODUCT_REVIEW,
            title="Notification 2",
            message="Message 2",
            read=True,
        )
        # Different user's notification
        Notification.objects.create(
            recipient=self.user2,
            type=NotificationType.SYSTEM_ALERT,
            title="Other notification",
            message="Other message",
        )

        # Get all notifications for user1
        notifications = self.service.get_user_notifications(self.user1)
        self.assertEqual(len(notifications), 2)

        # Get only unread notifications
        unread_notifications = self.service.get_user_notifications(self.user1, unread_only=True)
        self.assertEqual(len(unread_notifications), 1)
        self.assertEqual(unread_notifications[0].id, n1.id)

    def test_get_unread_count(self):
        """Test getting unread notification count"""
        # Create test notifications
        Notification.objects.create(
            recipient=self.user1, type=NotificationType.PRODUCT_SCAN, title="Notification 1", message="Message 1"
        )
        Notification.objects.create(
            recipient=self.user1,
            type=NotificationType.PRODUCT_REVIEW,
            title="Notification 2",
            message="Message 2",
            read=True,
        )

        count = self.service.get_unread_count(self.user1)
        self.assertEqual(count, 1)


class NotificationAPITests(APITestCase):
    """Test notification API endpoints"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com", password="testpass123", first_name="Test", last_name="User"
        )
        self.admin_user = User.objects.create_user(
            email="admin@example.com", password="testpass123", is_staff=True, is_superuser=True
        )
        self.client = APIClient()

    def test_notification_list_authenticated(self):
        """Test listing notifications for authenticated user"""
        # Create test notifications
        Notification.objects.create(
            recipient=self.user, type=NotificationType.PRODUCT_SCAN, title="Test Notification", message="Test message"
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/notifications/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["title"], "Test Notification")

    def test_notification_list_unauthenticated(self):
        """Test listing notifications without authentication"""
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_mark_notification_as_read(self):
        """Test marking notification as read"""
        notification = Notification.objects.create(
            recipient=self.user, type=NotificationType.PRODUCT_SCAN, title="Test Notification", message="Test message"
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.post("/api/notifications/mark-as-read/", {"notification_id": notification.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        # Verify notification is marked as read
        notification.refresh_from_db()
        self.assertTrue(notification.read)

    def test_mark_all_as_read(self):
        """Test marking all notifications as read"""
        # Create test notifications
        n1 = Notification.objects.create(
            recipient=self.user, type=NotificationType.PRODUCT_SCAN, title="Notification 1", message="Message 1"
        )
        n2 = Notification.objects.create(
            recipient=self.user, type=NotificationType.PRODUCT_REVIEW, title="Notification 2", message="Message 2"
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.post("/api/notifications/mark-all-as-read/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["count"], 2)

        # Verify notifications are marked as read
        n1.refresh_from_db()
        n2.refresh_from_db()
        self.assertTrue(n1.read)
        self.assertTrue(n2.read)

    def test_notification_count(self):
        """Test getting notification count"""
        # Create test notifications
        Notification.objects.create(
            recipient=self.user, type=NotificationType.PRODUCT_SCAN, title="Notification 1", message="Message 1"
        )
        Notification.objects.create(
            recipient=self.user,
            type=NotificationType.PRODUCT_REVIEW,
            title="Notification 2",
            message="Message 2",
            read=True,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/notifications/count/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_count"], 2)
        self.assertEqual(response.data["unread_count"], 1)
        self.assertEqual(response.data["read_count"], 1)

    def test_notification_preferences(self):
        """Test getting and updating notification preferences"""
        self.client.force_authenticate(user=self.user)

        # Get preferences (should create default if not exists)
        response = self.client.get("/api/notifications/preferences/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["product_scan_enabled"])
        self.assertTrue(response.data["product_review_enabled"])

        # Update preferences
        response = self.client.patch(
            "/api/notifications/preferences/", {"product_scan_enabled": False, "realtime_notifications": False}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["product_scan_enabled"])
        self.assertFalse(response.data["realtime_notifications"])

    def test_create_notification_admin_only(self):
        """Test creating notification (admin only)"""
        # Test with non-admin user
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/notifications/create/",
            {
                "recipient_id": self.user.id,
                "type": "system_alert",
                "title": "Admin Notification",
                "message": "This is an admin message",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Test with admin user
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            "/api/notifications/create/",
            {
                "recipient_id": self.user.id,
                "type": "system_alert",
                "title": "Admin Notification",
                "message": "This is an admin message",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

    def test_test_notification(self):
        """Test creating a test notification"""
        self.client.force_authenticate(user=self.user)
        response = self.client.post("/api/notifications/test/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        # Verify notification was created
        notifications = Notification.objects.filter(recipient=self.user)
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().title, "Test Notification")


class NotificationIntegrationTests(TestCase):
    """Test notification integration with other apps"""

    def setUp(self):
        # Create test users
        self.product_owner = User.objects.create_user(
            email="owner@example.com", password="testpass123", first_name="Product", last_name="Owner"
        )
        self.consumer = User.objects.create_user(
            email="consumer@example.com", password="testpass123", first_name="Consumer", last_name="User"
        )

        # Create necessary objects for testing
        # `Company` HAS NO `user` FIELD. Membership is the M2M through `WorksIn`, and this line
        # was still passing `user=` from a model shape that no longer exists, so every test in
        # this class died in setUp with
        # "TypeError: Company() got unexpected keyword arguments: 'user'".
        self.company = Company.objects.create(name="Test Company")
        self.product_owner.companies.add(self.company)

    def test_product_scan_creates_notification(self):
        """Test that scanning a product creates a notification"""
        # This would typically be tested as part of the history app tests
        # but we're including it here to verify the integration
        from notifications.services import notification_service

        notification = notification_service.create_product_scan_notification(
            product_owner=self.product_owner,
            scanner=self.consumer,
            product_name="Test Product",
            scan_location="Test Location",
        )

        self.assertIsNotNone(notification)
        self.assertEqual(notification.type, NotificationType.PRODUCT_SCAN)
        self.assertEqual(notification.recipient, self.product_owner)
        self.assertEqual(notification.actor, self.consumer)

    def test_product_review_creates_notification(self):
        """Test that creating a review creates a notification"""
        from notifications.services import notification_service

        notification = notification_service.create_product_review_notification(
            product_owner=self.product_owner,
            reviewer=self.consumer,
            product_name="Test Product",
            rating=5,
            review_text="Great product!",
        )

        self.assertIsNotNone(notification)
        self.assertEqual(notification.type, NotificationType.PRODUCT_REVIEW)
        self.assertEqual(notification.recipient, self.product_owner)
        self.assertEqual(notification.actor, self.consumer)


# Note: WebSocket tests would require additional setup with Django Channels testing
# and are complex to implement. For now, we've focused on the core functionality tests.
