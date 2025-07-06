import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import NotificationChannel, Notification, NotificationPreference

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time notifications
    """
    
    async def connect(self):
        """Handle WebSocket connection"""
        self.user = self.scope["user"]
        
        # Reject anonymous users
        from django.contrib.auth.models import AnonymousUser
        if isinstance(self.user, AnonymousUser):
            await self.close()
            return
        
        # Create user-specific group
        self.user_group_name = f"user_{self.user.id}"
        
        # Accept connection
        await self.accept()
        
        # Join user group
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )
        
        # Store channel information in database
        await self.save_channel_info()
        
        # Send initial notification count
        await self.send_notification_count()
        
        logger.info(f"User {self.user.email} connected to notifications WebSocket")
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        if hasattr(self, 'user_group_name'):
            # Leave user group
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name
            )
            
            # Remove channel from database
            await self.remove_channel_info()
            
            logger.info(f"User {self.user.email} disconnected from notifications WebSocket")
    
    async def receive(self, text_data):
        """Handle messages from WebSocket"""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')
            
            if message_type == 'mark_as_read':
                notification_id = text_data_json.get('notification_id')
                await self.mark_notification_as_read(notification_id)
            
            elif message_type == 'mark_all_as_read':
                await self.mark_all_notifications_as_read()
            
            elif message_type == 'get_notifications':
                limit = text_data_json.get('limit', 20)
                await self.send_recent_notifications(limit)
            
            elif message_type == 'ping':
                # Update last activity
                await self.update_channel_activity()
                await self.send(text_data=json.dumps({
                    'type': 'pong'
                }))
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON received in WebSocket message")
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {str(e)}")
    
    async def notification_message(self, event):
        """Send notification to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'notification': event['notification']
        }))
    
    async def notification_count(self, event):
        """Send notification count to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'notification_count',
            'count': event['count']
        }))
    
    @database_sync_to_async
    def save_channel_info(self):
        """Save channel information to database"""
        try:
            # Get client information from headers
            headers = dict(self.scope["headers"])
            user_agent = headers.get(b"user-agent", b"").decode()
            
            # Get IP address
            ip_address = None
            if "client" in self.scope:
                ip_address = self.scope["client"][0] if self.scope["client"] else None
            
            # Create or update channel record
            NotificationChannel.objects.update_or_create(
                user=self.user,
                channel_name=self.channel_name,
                defaults={
                    'user_agent': user_agent,
                    'ip_address': ip_address,
                    'last_activity': timezone.now()
                }
            )
        except Exception as e:
            logger.error(f"Error saving channel info: {str(e)}")
    
    @database_sync_to_async
    def remove_channel_info(self):
        """Remove channel information from database"""
        try:
            NotificationChannel.objects.filter(
                user=self.user,
                channel_name=self.channel_name
            ).delete()
        except Exception as e:
            logger.error(f"Error removing channel info: {str(e)}")
    
    @database_sync_to_async
    def update_channel_activity(self):
        """Update channel last activity"""
        try:
            NotificationChannel.objects.filter(
                user=self.user,
                channel_name=self.channel_name
            ).update(last_activity=timezone.now())
        except Exception as e:
            logger.error(f"Error updating channel activity: {str(e)}")
    
    @database_sync_to_async
    def mark_notification_as_read(self, notification_id):
        """Mark a specific notification as read"""
        try:
            notification = Notification.objects.get(
                id=notification_id,
                recipient=self.user
            )
            notification.mark_as_read()
            return True
        except Notification.DoesNotExist:
            logger.warning(f"Notification {notification_id} not found for user {self.user.email}")
            return False
        except Exception as e:
            logger.error(f"Error marking notification as read: {str(e)}")
            return False
    
    @database_sync_to_async
    def mark_all_notifications_as_read(self):
        """Mark all notifications as read for the user"""
        try:
            unread_notifications = Notification.objects.filter(
                recipient=self.user,
                read=False
            )
            for notification in unread_notifications:
                notification.mark_as_read()
            return unread_notifications.count()
        except Exception as e:
            logger.error(f"Error marking all notifications as read: {str(e)}")
            return 0
    
    @database_sync_to_async
    def get_unread_count(self):
        """Get unread notification count"""
        try:
            return Notification.objects.filter(
                recipient=self.user,
                read=False
            ).count()
        except Exception as e:
            logger.error(f"Error getting unread count: {str(e)}")
            return 0
    
    @database_sync_to_async
    def get_recent_notifications(self, limit=20):
        """Get recent notifications for the user"""
        try:
            notifications = Notification.objects.filter(
                recipient=self.user
            ).select_related('actor', 'content_type').order_by('-created_at')[:limit]
            
            result = []
            for notification in notifications:
                result.append({
                    'id': notification.id,
                    'title': notification.title,
                    'message': notification.message,
                    'type': notification.type,
                    'priority': notification.priority,
                    'read': notification.read,
                    'created_at': notification.created_at.isoformat(),
                    'actor': {
                        'id': notification.actor.id,
                        'email': notification.actor.email,
                        'first_name': notification.actor.first_name,
                        'last_name': notification.actor.last_name,
                    } if notification.actor else None,
                    'extra_data': notification.extra_data
                })
            return result
        except Exception as e:
            logger.error(f"Error getting recent notifications: {str(e)}")
            return []
    
    async def send_notification_count(self):
        """Send current notification count to client"""
        count = await self.get_unread_count()
        await self.send(text_data=json.dumps({
            'type': 'notification_count',
            'count': count
        }))
    
    async def send_recent_notifications(self, limit=20):
        """Send recent notifications to client"""
        notifications = await self.get_recent_notifications(limit)
        await self.send(text_data=json.dumps({
            'type': 'notifications_list',
            'notifications': notifications
        }))


# Utility functions for sending notifications
async def send_notification_to_user(user_id, notification_data):
    """Send a notification to a specific user via WebSocket"""
    from channels.layers import get_channel_layer
    
    channel_layer = get_channel_layer()
    user_group_name = f"user_{user_id}"
    
    await channel_layer.group_send(
        user_group_name,
        {
            'type': 'notification_message',
            'notification': notification_data
        }
    )


async def send_notification_count_to_user(user_id, count):
    """Send notification count update to a specific user"""
    from channels.layers import get_channel_layer
    
    channel_layer = get_channel_layer()
    user_group_name = f"user_{user_id}"
    
    await channel_layer.group_send(
        user_group_name,
        {
            'type': 'notification_count',
            'count': count
        }
    )