from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .models import Notification, NotificationChannel, NotificationPreference, NotificationTemplate
from .serializers import (
    CreateNotificationSerializer,
    NotificationChannelSerializer,
    NotificationMarkAsReadSerializer,
    NotificationPreferenceSerializer,
    NotificationSerializer,
    NotificationStatsSerializer,
    NotificationTemplateSerializer,
)
from .services import notification_service

User = get_user_model()


class NotificationPagination(PageNumberPagination):
    """Custom pagination for notifications"""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class NotificationListView(generics.ListAPIView):
    """List notifications for the authenticated user"""

    serializer_class = NotificationSerializer
    pagination_class = NotificationPagination
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = (
            Notification.objects.filter(recipient=user).select_related("actor", "content_type").order_by("-created_at")
        )

        # Filter by read status
        unread_only = self.request.query_params.get("unread_only", "false").lower() == "true"
        if unread_only:
            queryset = queryset.filter(read=False)

        # Filter by type
        notification_type = self.request.query_params.get("type")
        if notification_type:
            queryset = queryset.filter(type=notification_type)

        # Filter by priority
        priority = self.request.query_params.get("priority")
        if priority:
            queryset = queryset.filter(priority=priority)

        return queryset


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def mark_notification_as_read(request):
    """Mark a specific notification as read"""
    serializer = NotificationMarkAsReadSerializer(data=request.data)

    if serializer.is_valid():
        notification_id = serializer.validated_data["notification_id"]
        success = notification_service.mark_notification_as_read(notification_id, request.user)

        if success:
            return Response({"success": True, "message": "Notification marked as read"})
        else:
            return Response({"success": False, "message": "Notification not found"}, status=status.HTTP_404_NOT_FOUND)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def mark_all_as_read(request):
    """Mark all notifications as read for the authenticated user"""
    try:
        unread_notifications = Notification.objects.filter(recipient=request.user, read=False)

        count = 0
        for notification in unread_notifications:
            notification.mark_as_read()
            count += 1

        return Response({"success": True, "message": f"{count} notifications marked as read", "count": count})
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def notification_count(request):
    """Get notification counts for the authenticated user"""
    user = request.user

    total_count = Notification.objects.filter(recipient=user).count()
    unread_count = Notification.objects.filter(recipient=user, read=False).count()
    read_count = total_count - unread_count

    # Today's notifications
    today = timezone.now().date()
    today_count = Notification.objects.filter(recipient=user, created_at__date=today).count()

    # This week's notifications
    week_ago = timezone.now() - timedelta(days=7)
    this_week_count = Notification.objects.filter(recipient=user, created_at__gte=week_ago).count()

    return Response(
        {
            "total_count": total_count,
            "unread_count": unread_count,
            "read_count": read_count,
            "today_count": today_count,
            "this_week_count": this_week_count,
        }
    )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def notification_stats(request):
    """Get detailed notification statistics"""
    user = request.user

    # Basic counts
    total_count = Notification.objects.filter(recipient=user).count()
    unread_count = Notification.objects.filter(recipient=user, read=False).count()
    read_count = total_count - unread_count

    # Time-based counts
    today = timezone.now().date()
    week_ago = timezone.now() - timedelta(days=7)

    today_count = Notification.objects.filter(recipient=user, created_at__date=today).count()

    this_week_count = Notification.objects.filter(recipient=user, created_at__gte=week_ago).count()

    # Count by type
    by_type = dict(Notification.objects.filter(recipient=user).values_list("type").annotate(count=Count("type")))

    # Count by priority
    by_priority = dict(
        Notification.objects.filter(recipient=user).values_list("priority").annotate(count=Count("priority"))
    )

    stats_data = {
        "total_count": total_count,
        "unread_count": unread_count,
        "read_count": read_count,
        "today_count": today_count,
        "this_week_count": this_week_count,
        "by_type": by_type,
        "by_priority": by_priority,
    }

    serializer = NotificationStatsSerializer(stats_data)
    return Response(serializer.data)


class NotificationPreferenceView(generics.RetrieveUpdateAPIView):
    """Get and update notification preferences"""

    serializer_class = NotificationPreferenceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        preferences, created = NotificationPreference.objects.get_or_create(
            user=self.request.user,
            defaults={
                "product_scan_enabled": True,
                "product_review_enabled": True,
                "carbon_verification_enabled": True,
                "system_alert_enabled": True,
                "email_notifications": True,
                "push_notifications": True,
                "realtime_notifications": True,
            },
        )
        return preferences


class NotificationChannelListView(generics.ListAPIView):
    """List active notification channels for admin"""

    serializer_class = NotificationChannelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Only show user's own channels, or all if admin
        if self.request.user.is_staff:
            return NotificationChannel.objects.select_related("user").order_by("-last_activity")
        else:
            return NotificationChannel.objects.filter(user=self.request.user).order_by("-last_activity")


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def create_notification(request):
    """Create a notification (admin only)"""
    serializer = CreateNotificationSerializer(data=request.data)

    if serializer.is_valid():
        data = serializer.validated_data

        try:
            recipient = User.objects.get(id=data["recipient_id"])

            notification = notification_service.create_notification(
                recipient=recipient,
                notification_type=data["type"],
                title=data["title"],
                message=data["message"],
                priority=data["priority"],
                extra_data=data.get("extra_data", {}),
            )

            if notification:
                return Response(
                    {
                        "success": True,
                        "message": "Notification created successfully",
                        "notification_id": notification.id,
                    }
                )
            else:
                return Response(
                    {"success": False, "message": "Failed to create notification"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        except User.DoesNotExist:
            return Response({"success": False, "message": "Recipient not found"}, status=status.HTTP_404_NOT_FOUND)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NotificationTemplateListCreateView(generics.ListCreateAPIView):
    """List and create notification templates (admin only)"""

    serializer_class = NotificationTemplateSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = NotificationTemplate.objects.all()


class NotificationTemplateDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, delete notification templates (admin only)"""

    serializer_class = NotificationTemplateSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = NotificationTemplate.objects.all()


@api_view(["DELETE"])
@permission_classes([permissions.IsAuthenticated])
def delete_notification(request, notification_id):
    """Delete a specific notification"""
    try:
        notification = Notification.objects.get(id=notification_id, recipient=request.user)
        notification.delete()

        return Response({"success": True, "message": "Notification deleted successfully"})
    except Notification.DoesNotExist:
        return Response({"success": False, "message": "Notification not found"}, status=status.HTTP_404_NOT_FOUND)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def test_notification(request):
    """Create a test notification for the authenticated user"""
    notification = notification_service.create_notification(
        recipient=request.user,
        notification_type="system_alert",
        title="Test Notification",
        message="This is a test notification to verify the system is working correctly.",
        priority="medium",
        extra_data={"test": True},
    )

    if notification:
        return Response(
            {"success": True, "message": "Test notification sent successfully", "notification_id": notification.id}
        )
    else:
        return Response(
            {"success": False, "message": "Failed to create test notification"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
