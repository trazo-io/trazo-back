from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    Notification, 
    NotificationPreference, 
    NotificationChannel,
    NotificationTemplate
)

User = get_user_model()


class UserBasicSerializer(serializers.ModelSerializer):
    """Basic user information for notifications"""
    
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name']


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for notifications"""
    
    actor = UserBasicSerializer(read_only=True)
    time_since = serializers.SerializerMethodField()
    
    class Meta:
        model = Notification
        fields = [
            'id', 'title', 'message', 'type', 'priority',
            'read', 'read_at', 'delivered', 'delivered_at',
            'created_at', 'updated_at', 'actor', 'extra_data',
            'time_since'
        ]
        read_only_fields = [
            'id', 'delivered', 'delivered_at', 'created_at', 
            'updated_at', 'actor', 'extra_data'
        ]
    
    def get_time_since(self, obj):
        """Get human-readable time since notification was created"""
        from django.utils.timesince import timesince
        return timesince(obj.created_at)


class NotificationMarkAsReadSerializer(serializers.Serializer):
    """Serializer for marking notifications as read"""
    
    notification_id = serializers.IntegerField()


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    """Serializer for notification preferences"""
    
    class Meta:
        model = NotificationPreference
        fields = [
            'product_scan_enabled', 'product_review_enabled',
            'carbon_verification_enabled', 'system_alert_enabled',
            'email_notifications', 'push_notifications', 
            'realtime_notifications', 'quiet_hours_start', 
            'quiet_hours_end'
        ]
    
    def update(self, instance, validated_data):
        """Update notification preferences"""
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class NotificationChannelSerializer(serializers.ModelSerializer):
    """Serializer for notification channels"""
    
    user = UserBasicSerializer(read_only=True)
    is_active = serializers.SerializerMethodField()
    
    class Meta:
        model = NotificationChannel
        fields = [
            'id', 'user', 'channel_name', 'connected_at',
            'last_activity', 'user_agent', 'ip_address',
            'is_active'
        ]
        read_only_fields = [
            'id', 'user', 'channel_name', 'connected_at',
            'last_activity', 'user_agent', 'ip_address'
        ]
    
    def get_is_active(self, obj):
        """Check if channel is still active"""
        from django.utils import timezone
        from datetime import timedelta
        
        threshold = timezone.now() - timedelta(minutes=5)
        return obj.last_activity > threshold


class NotificationStatsSerializer(serializers.Serializer):
    """Serializer for notification statistics"""
    
    total_count = serializers.IntegerField()
    unread_count = serializers.IntegerField()
    read_count = serializers.IntegerField()
    today_count = serializers.IntegerField()
    this_week_count = serializers.IntegerField()
    by_type = serializers.DictField()
    by_priority = serializers.DictField()


class CreateNotificationSerializer(serializers.Serializer):
    """Serializer for creating notifications (admin use)"""
    
    recipient_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=[
        ('product_scan', 'Product Scan'),
        ('product_review', 'Product Review'),
        ('carbon_verification', 'Carbon Verification'),
        ('system_alert', 'System Alert')
    ])
    priority = serializers.ChoiceField(
        choices=[
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
            ('urgent', 'Urgent')
        ],
        default='medium'
    )
    title = serializers.CharField(max_length=200)
    message = serializers.CharField()
    extra_data = serializers.JSONField(required=False, default=dict)
    
    def validate_recipient_id(self, value):
        """Validate that recipient exists"""
        try:
            User.objects.get(id=value)
            return value
        except User.DoesNotExist:
            raise serializers.ValidationError("Recipient does not exist")


class NotificationTemplateSerializer(serializers.ModelSerializer):
    """Serializer for notification templates"""
    
    class Meta:
        model = NotificationTemplate
        fields = [
            'id', 'type', 'title_template', 'message_template',
            'variables', 'active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']