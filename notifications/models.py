from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

User = get_user_model()


class NotificationType(models.TextChoices):
    PRODUCT_SCAN = 'product_scan', 'Product Scan'
    PRODUCT_REVIEW = 'product_review', 'Product Review'
    CARBON_VERIFICATION = 'carbon_verification', 'Carbon Verification'
    SYSTEM_ALERT = 'system_alert', 'System Alert'


class NotificationPriority(models.TextChoices):
    LOW = 'low', 'Low'
    MEDIUM = 'medium', 'Medium'
    HIGH = 'high', 'High'
    URGENT = 'urgent', 'Urgent'


class Notification(models.Model):
    """
    Core notification model for real-time notifications
    """
    # Who receives the notification
    recipient = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='notifications'
    )
    
    # Who triggered the notification (can be null for system notifications)
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='triggered_notifications'
    )
    
    # What type of notification
    type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
        default=NotificationType.SYSTEM_ALERT
    )
    
    # Priority level
    priority = models.CharField(
        max_length=10,
        choices=NotificationPriority.choices,
        default=NotificationPriority.MEDIUM
    )
    
    # Message content
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Generic foreign key for linking to any model
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Additional data as JSON
    extra_data = models.JSONField(default=dict, blank=True)
    
    # Status tracking
    read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'read']),
            models.Index(fields=['type', 'created_at']),
            models.Index(fields=['priority', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.recipient.email}"
    
    def mark_as_read(self):
        """Mark notification as read"""
        if not self.read:
            self.read = True
            self.read_at = timezone.now()
            self.save(update_fields=['read', 'read_at'])
    
    def mark_as_delivered(self):
        """Mark notification as delivered"""
        if not self.delivered:
            self.delivered = True
            self.delivered_at = timezone.now()
            self.save(update_fields=['delivered', 'delivered_at'])


class NotificationPreference(models.Model):
    """
    User preferences for different types of notifications
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    
    # Notification type preferences
    product_scan_enabled = models.BooleanField(default=True)
    product_review_enabled = models.BooleanField(default=True)
    carbon_verification_enabled = models.BooleanField(default=True)
    system_alert_enabled = models.BooleanField(default=True)
    
    # Delivery preferences
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    realtime_notifications = models.BooleanField(default=True)
    
    # Timing preferences
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Preferences for {self.user.email}"


class NotificationChannel(models.Model):
    """
    WebSocket channel tracking for real-time notifications
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notification_channels'
    )
    
    channel_name = models.CharField(max_length=100, unique=True)
    
    # Connection metadata
    connected_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    
    # Client information
    user_agent = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'last_activity']),
        ]
    
    def __str__(self):
        return f"{self.user.email} - {self.channel_name}"


class NotificationTemplate(models.Model):
    """
    Templates for different notification types
    """
    type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
        unique=True
    )
    
    title_template = models.CharField(max_length=200)
    message_template = models.TextField()
    
    # Template variables documentation
    variables = models.JSONField(
        default=dict,
        help_text="JSON object describing available template variables"
    )
    
    active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Template for {self.get_type_display()}"
    
    def render(self, context):
        """Render template with context variables"""
        title = self.title_template.format(**context)
        message = self.message_template.format(**context)
        return title, message