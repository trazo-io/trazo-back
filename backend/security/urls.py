"""
URL patterns for security endpoints
"""

from django.urls import path
from . import views

urlpatterns = [
    path('verify-qr/', views.verify_qr_code, name='verify_qr_code'),
    path('qr-info/', views.qr_security_info, name='qr_security_info'),
    path('health/', views.QRSecurityHealthCheck.as_view(), name='qr_security_health'),
    path('validate-production/', views.validate_production_access, name='validate_production_access'),
    path('metrics/', views.security_metrics, name='security_metrics'),
]