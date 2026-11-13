"""
URL patterns for security endpoints
"""

from django.urls import path

from . import views

urlpatterns = [
    path("verify-qr/", views.verify_qr_code, name="verify_qr_code"),
]
