import logging
from typing import Any, Dict, Optional

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .models import Notification, NotificationPreference, NotificationPriority, NotificationTemplate, NotificationType

User = get_user_model()
logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service for creating and managing notifications
    """

    def __init__(self):
        pass

    def create_notification(
        self,
        recipient: User,
        notification_type: str,
        title: str,
        message: str,
        actor: Optional[User] = None,
        related_object: Optional[Any] = None,
        priority: str = NotificationPriority.MEDIUM,
        extra_data: Optional[Dict] = None,
    ) -> Notification:
        """
        Create a new notification
        """
        try:
            # Check user preferences
            if not self._should_send_notification(recipient, notification_type):
                logger.info(f"Notification {notification_type} skipped for user {recipient.email} due to preferences")
                return None

            # Create notification
            notification = Notification.objects.create(
                recipient=recipient,
                actor=actor,
                type=notification_type,
                priority=priority,
                title=title,
                message=message,
                content_object=related_object,
                extra_data=extra_data or {},
            )

            logger.info(f"Notification created: {notification.title} for {recipient.email}")
            return notification

        except Exception as e:
            logger.error(f"Error creating notification: {str(e)}")
            return None

    def create_product_scan_notification(
        self,
        product_owner: User,
        scanner: Optional[User],
        product_name: str,
        scan_location: Optional[str] = None,
        production_id: Optional[int] = None,
        establishment_id: Optional[int] = None,
        product_id: Optional[int] = None,
        parcel_id: Optional[int] = None,
    ) -> Optional[Notification]:
        """
        Create a notification when someone scans a product
        """
        title = f"Product Scanned: {product_name}"

        if scanner:
            if scanner.first_name and scanner.last_name:
                actor_name = f"{scanner.first_name} {scanner.last_name}"
            else:
                actor_name = scanner.email
            scanner_email = scanner.email
        else:
            actor_name = "Someone"
            scanner_email = None

        message = f"{actor_name} scanned your product {product_name}"
        if scan_location:
            message += f" from {scan_location}"

        extra_data = {
            "product_name": product_name,
            "scanner_email": scanner_email,
            "scan_location": scan_location,
            "scan_time": timezone.now().isoformat(),
            "production_id": production_id,
            "establishment_id": establishment_id,
            "product_id": product_id,
            "parcel_id": parcel_id,
        }

        return self.create_notification(
            recipient=product_owner,
            notification_type=NotificationType.PRODUCT_SCAN,
            title=title,
            message=message,
            actor=scanner,
            priority=NotificationPriority.MEDIUM,
            extra_data=extra_data,
        )

    def create_product_review_notification(
        self,
        product_owner: User,
        reviewer: Optional[User],
        product_name: str,
        rating: Optional[int] = None,
        review_text: Optional[str] = None,
        production_id: Optional[int] = None,
        establishment_id: Optional[int] = None,
        product_id: Optional[int] = None,
        parcel_id: Optional[int] = None,
    ) -> Optional[Notification]:
        """
        Create a notification when someone leaves a review
        """
        title = f"New Review: {product_name}"

        if reviewer:
            if reviewer.first_name and reviewer.last_name:
                reviewer_name = f"{reviewer.first_name} {reviewer.last_name}"
            else:
                reviewer_name = reviewer.email
            reviewer_email = reviewer.email
        else:
            reviewer_name = "Someone"
            reviewer_email = None

        message = f"{reviewer_name} left a review for your product {product_name}"
        if rating:
            message += f" (Rating: {rating}/5)"

        extra_data = {
            "product_name": product_name,
            "reviewer_email": reviewer_email,
            "rating": rating,
            "review_text": review_text,
            "review_time": timezone.now().isoformat(),
            "production_id": production_id,
            "establishment_id": establishment_id,
            "product_id": product_id,
            "parcel_id": parcel_id,
        }

        return self.create_notification(
            recipient=product_owner,
            notification_type=NotificationType.PRODUCT_REVIEW,
            title=title,
            message=message,
            actor=reviewer,
            priority=NotificationPriority.HIGH,
            extra_data=extra_data,
        )

    def create_carbon_verification_notification(
        self, recipient: User, verification_status: str, product_name: str, carbon_score: Optional[float] = None
    ) -> Optional[Notification]:
        """
        Create a notification for carbon verification updates
        """
        if verification_status == "verified":
            title = f"Carbon Verification Complete: {product_name}"
            message = f"Your product '{product_name}' has been successfully verified"
            priority = NotificationPriority.HIGH
        else:
            title = f"Carbon Verification Failed: {product_name}"
            message = f"Carbon verification failed for '{product_name}'. Please review the data."
            priority = NotificationPriority.URGENT

        extra_data = {
            "product_name": product_name,
            "verification_status": verification_status,
            "carbon_score": carbon_score,
            "verification_time": timezone.now().isoformat(),
        }

        return self.create_notification(
            recipient=recipient,
            notification_type=NotificationType.CARBON_VERIFICATION,
            title=title,
            message=message,
            priority=priority,
            extra_data=extra_data,
        )

    def mark_notification_as_read(self, notification_id: int, user: User) -> bool:
        """
        Mark a notification as read
        """
        try:
            notification = Notification.objects.get(id=notification_id, recipient=user)
            notification.mark_as_read()

            return True
        except Notification.DoesNotExist:
            logger.warning(f"Notification {notification_id} not found for user {user.email}")
            return False
        except Exception as e:
            logger.error(f"Error marking notification as read: {str(e)}")
            return False

    def get_user_notifications(self, user: User, limit: int = 20, unread_only: bool = False) -> list:
        """
        Get notifications for a user
        """
        try:
            queryset = Notification.objects.filter(recipient=user)

            if unread_only:
                queryset = queryset.filter(read=False)

            notifications = queryset.select_related("actor", "content_type").order_by("-created_at")[:limit]

            return list(notifications)
        except Exception as e:
            logger.error(f"Error getting user notifications: {str(e)}")
            return []

    def get_unread_count(self, user: User) -> int:
        """
        Get unread notification count for a user
        """
        try:
            return Notification.objects.filter(recipient=user, read=False).count()
        except Exception as e:
            logger.error(f"Error getting unread count: {str(e)}")
            return 0

    def _should_send_notification(self, user: User, notification_type: str) -> bool:
        """
        Check if user wants to receive this type of notification
        """
        try:
            preferences, created = NotificationPreference.objects.get_or_create(
                user=user,
                defaults={
                    "product_scan_enabled": True,
                    "product_review_enabled": True,
                    "carbon_verification_enabled": True,
                    "system_alert_enabled": True,
                    "realtime_notifications": True,
                },
            )

            # Check if realtime notifications are disabled
            if not preferences.realtime_notifications:
                return False

            # Check specific notification type preferences
            if notification_type == NotificationType.PRODUCT_SCAN:
                return preferences.product_scan_enabled
            elif notification_type == NotificationType.PRODUCT_REVIEW:
                return preferences.product_review_enabled
            elif notification_type == NotificationType.CARBON_VERIFICATION:
                return preferences.carbon_verification_enabled
            elif notification_type == NotificationType.SYSTEM_ALERT:
                return preferences.system_alert_enabled

            return True
        except Exception as e:
            logger.error(f"Error checking notification preferences: {str(e)}")
            return True  # Default to sending notification


# Global service instance
notification_service = NotificationService()
