#!/usr/bin/env python
"""
Test script for the new email implementation in Trazo
Tests welcome emails, verification emails, and invitation emails
"""

import os
import sys

import django
from django.conf import settings

# Add the project root to the Python path
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from django.contrib.auth import get_user_model
from django.core.mail import send_mail

from company.models import Company
from users.constants import CONSUMER, PRODUCER
from users.utils import send_invitation_email, send_verification_email, send_welcome_email

User = get_user_model()


def test_email_sending():
    """Test basic email sending functionality"""
    print("🧪 Testing basic email sending...")

    try:
        # Test basic Django email
        result = send_mail(
            subject="Test Email from Trazo",
            message="This is a test email to verify SMTP configuration.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=["test@example.com"],
            fail_silently=False,
        )
        print("✅ Basic email sending works")
        return True
    except Exception as e:
        print(f"❌ Basic email sending failed: {e}")
        return False


def test_welcome_email():
    """Test welcome email template"""
    print("\n🧪 Testing welcome email...")

    try:
        # Create a test user (don't save to avoid triggering signals)
        user = User(email="test@example.com", first_name="John", last_name="Doe", user_type=PRODUCER)

        # Test welcome email
        result = send_welcome_email(user)
        if result:
            print("✅ Welcome email sent successfully")
            return True
        else:
            print("❌ Welcome email failed to send")
            return False
    except Exception as e:
        print(f"❌ Welcome email test failed: {e}")
        return False


def test_verification_email():
    """Test verification email template"""
    print("\n🧪 Testing verification email...")

    try:
        # Create a test user
        user = User(email="test@example.com", first_name="Jane", last_name="Smith", user_type=CONSUMER)

        # Test verification email with code
        result = send_verification_email(
            user=user, verification_code="ABC123", verification_link="https://consumer.trazo.io/verify?code=ABC123"
        )

        if result:
            print("✅ Verification email sent successfully")
            return True
        else:
            print("❌ Verification email failed to send")
            return False
    except Exception as e:
        print(f"❌ Verification email test failed: {e}")
        return False


def test_invitation_email():
    """Test invitation email template"""
    print("\n🧪 Testing invitation email...")

    try:
        # Create test users and company (don't save)
        inviter = User(email="admin@testfarm.com", first_name="Farm", last_name="Admin", user_type=PRODUCER)

        company = Company(name="Test Farm LLC", address="123 Farm Road", city="Farmville", state="CA")

        # Test invitation email
        result = send_invitation_email(
            invitee_email="worker@example.com",
            invitee_name="Farm Worker",
            inviter=inviter,
            company=company,
            role="DW",
            invitation_link="https://producer.trazo.io/invitation/ABC123XYZ",
            invitation_message="Welcome to our farm team! We look forward to working with you.",
        )

        if result:
            print("✅ Invitation email sent successfully")
            return True
        else:
            print("❌ Invitation email failed to send")
            return False
    except Exception as e:
        print(f"❌ Invitation email test failed: {e}")
        return False


def test_template_rendering():
    """Test that templates render without errors"""
    print("\n🧪 Testing template rendering...")

    try:
        from django.template.loader import render_to_string

        # Test welcome template
        context = {"user": User(first_name="Test", email="test@example.com"), "user_type": "producer"}

        welcome_html = render_to_string("emails/welcome.html", context)
        welcome_txt = render_to_string("emails/welcome.txt", context)

        if len(welcome_html) > 0 and len(welcome_txt) > 0:
            print("✅ Welcome templates render correctly")
        else:
            print("❌ Welcome templates are empty")
            return False

        # Test verification template
        verification_context = {
            "user": User(first_name="Test", email="test@example.com"),
            "user_type": "consumer",
            "verification_code": "ABC123",
            "verification_link": "https://example.com/verify",
        }

        verification_html = render_to_string("emails/verification.html", verification_context)
        verification_txt = render_to_string("emails/verification.txt", verification_context)

        if len(verification_html) > 0 and len(verification_txt) > 0:
            print("✅ Verification templates render correctly")
        else:
            print("❌ Verification templates are empty")
            return False

        # Test invitation template
        invitation_context = {
            "invitee_name": "Test Invitee",
            "inviter": User(first_name="Test", last_name="Admin"),
            "company": Company(name="Test Company"),
            "role": "DW",
            "role_display": "Domain Worker",
            "invitation_link": "https://example.com/invitation/123",
            "invitation_message": "Welcome to our team!",
        }

        invitation_html = render_to_string("emails/invitation.html", invitation_context)
        invitation_txt = render_to_string("emails/invitation.txt", invitation_context)

        if len(invitation_html) > 0 and len(invitation_txt) > 0:
            print("✅ Invitation templates render correctly")
        else:
            print("❌ Invitation templates are empty")
            return False

        return True

    except Exception as e:
        print(f"❌ Template rendering test failed: {e}")
        return False


def main():
    """Run all email tests"""
    print("🚀 Starting Trazo Email Implementation Tests")
    print("=" * 50)

    tests = [
        test_template_rendering,
        test_email_sending,
        test_welcome_email,
        test_verification_email,
        test_invitation_email,
    ]

    passed = 0
    total = len(tests)

    for test in tests:
        if test():
            passed += 1

    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All email tests passed! Email implementation is working correctly.")
    else:
        print(f"⚠️  {total - passed} tests failed. Check the implementation.")

    # Check email backend configuration
    print(f"\n📧 Email Configuration:")
    print(f"   Backend: {settings.EMAIL_BACKEND}")
    print(f"   Host: {getattr(settings, 'EMAIL_HOST', 'Not configured')}")
    print(f"   From Email: {getattr(settings, 'DEFAULT_FROM_EMAIL', 'Not configured')}")

    return passed == total


if __name__ == "__main__":
    main()
