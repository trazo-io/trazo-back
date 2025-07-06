from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    # Notification management
    path('', views.NotificationListView.as_view(), name='notification-list'),
    path('count/', views.notification_count, name='notification-count'),
    path('stats/', views.notification_stats, name='notification-stats'),
    path('mark-as-read/', views.mark_notification_as_read, name='mark-as-read'),
    path('mark-all-as-read/', views.mark_all_as_read, name='mark-all-as-read'),
    path('<int:notification_id>/delete/', views.delete_notification, name='delete-notification'),
    path('test/', views.test_notification, name='test-notification'),
    
    # Notification preferences
    path('preferences/', views.NotificationPreferenceView.as_view(), name='notification-preferences'),
    
    # Active channels (for monitoring)
    path('channels/', views.NotificationChannelListView.as_view(), name='notification-channels'),
    
    # Admin endpoints
    path('create/', views.create_notification, name='create-notification'),
    path('templates/', views.NotificationTemplateListCreateView.as_view(), name='notification-templates'),
    path('templates/<int:pk>/', views.NotificationTemplateDetailView.as_view(), name='notification-template-detail'),
]