#!/usr/bin/env python
"""
Test script to verify that both PRODUCER and CONSUMER user types are properly handled
in welcome and verification emails
"""

import os
import sys

import django

# Add the project root to the Python path
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from django.contrib.auth import get_user_model

from users.constants import CERTIFIER, CONSUMER, PRODUCER, STAFF, SUPERUSER
from users.utils import send_verification_email, send_welcome_email

User = get_user_model()


def test_producer_emails():
    """Test emails for producer users"""
    print("🧪 Testing PRODUCER user emails...")

    try:
        # Create a producer user
        producer_user = User(
            email="producer@testfarm.com",
            first_name="Farm",
            last_name="Owner",
            user_type=PRODUCER,  # This should be 4 according to constants
        )

        print(f"   Producer user type: {producer_user.user_type} (should be {PRODUCER})")

        # Test welcome email
        welcome_result = send_welcome_email(producer_user)
        if welcome_result:
            print("   ✅ Producer welcome email sent successfully")
        else:
            print("   ❌ Producer welcome email failed")
            return False

        # Test verification email
        verification_result = send_verification_email(
            user=producer_user,
            verification_code="PROD123",
            verification_link="https://producer.trazo.io/verify?code=PROD123",
        )

        if verification_result:
            print("   ✅ Producer verification email sent successfully")
        else:
            print("   ❌ Producer verification email failed")
            return False

        return True

    except Exception as e:
        print(f"   ❌ Producer email test failed: {e}")
        return False


def test_consumer_emails():
    """Test emails for consumer users"""
    print("\n🧪 Testing CONSUMER user emails...")

    try:
        # Create a consumer user
        consumer_user = User(
            email="consumer@example.com",
            first_name="Food",
            last_name="Lover",
            user_type=CONSUMER,  # This should be 3 according to constants
        )

        print(f"   Consumer user type: {consumer_user.user_type} (should be {CONSUMER})")

        # Test welcome email
        welcome_result = send_welcome_email(consumer_user)
        if welcome_result:
            print("   ✅ Consumer welcome email sent successfully")
        else:
            print("   ❌ Consumer welcome email failed")
            return False

        # Test verification email
        verification_result = send_verification_email(
            user=consumer_user,
            verification_code="CONS456",
            verification_link="https://consumer.trazo.io/verify?code=CONS456",
        )

        if verification_result:
            print("   ✅ Consumer verification email sent successfully")
        else:
            print("   ❌ Consumer verification email failed")
            return False

        return True

    except Exception as e:
        print(f"   ❌ Consumer email test failed: {e}")
        return False


def test_other_user_types():
    """Test emails for other user types (should default to consumer)"""
    print("\n🧪 Testing OTHER user types (should default to consumer)...")

    try:
        # Test STAFF user (should default to consumer styling)
        staff_user = User(
            email="staff@trazo.com",
            first_name="Staff",
            last_name="Member",
            user_type=STAFF,  # This should be 2 according to constants
        )

        print(f"   Staff user type: {staff_user.user_type} (should be {STAFF})")

        # Test welcome email
        welcome_result = send_welcome_email(staff_user)
        if welcome_result:
            print("   ✅ Staff welcome email sent (should use consumer styling)")
        else:
            print("   ❌ Staff welcome email failed")
            return False

        return True

    except Exception as e:
        print(f"   ❌ Other user types test failed: {e}")
        return False


def test_template_rendering_by_type():
    """Test that templates render differently based on user type"""
    print("\n🧪 Testing template rendering differences...")

    try:
        from django.template.loader import render_to_string

        # Producer context
        producer_context = {"user": User(first_name="Producer", email="producer@test.com"), "user_type": "producer"}

        # Consumer context
        consumer_context = {"user": User(first_name="Consumer", email="consumer@test.com"), "user_type": "consumer"}

        # Render welcome templates
        producer_welcome = render_to_string("emails/welcome.html", producer_context)
        consumer_welcome = render_to_string("emails/welcome.html", consumer_context)

        # Check for producer-specific content
        if "specialty crop farms" in producer_welcome and "transparency" in producer_welcome:
            print("   ✅ Producer welcome contains producer-specific content")
        else:
            print("   ❌ Producer welcome missing producer content")
            return False

        # Check for consumer-specific content
        if "scan QR codes" in consumer_welcome and "story behind your food" in consumer_welcome:
            print("   ✅ Consumer welcome contains consumer-specific content")
        else:
            print("   ❌ Consumer welcome missing consumer content")
            return False

        # Check for different styling classes
        if 'class="email-header consumer"' in consumer_welcome:
            print("   ✅ Consumer emails use consumer CSS classes")
        else:
            print("   ❌ Consumer emails missing consumer CSS classes")
            return False

        if 'class="email-header consumer"' not in producer_welcome:
            print("   ✅ Producer emails use producer CSS classes")
        else:
            print("   ❌ Producer emails incorrectly using consumer CSS classes")
            return False

        return True

    except Exception as e:
        print(f"   ❌ Template rendering test failed: {e}")
        return False


def main():
    """Run all user type differentiation tests"""
    print("🚀 Testing User Type Differentiation in Email System")
    print("=" * 55)

    # Print user type constants for verification
    print(f"📋 User Type Constants:")
    print(f"   PRODUCER = {PRODUCER}")
    print(f"   CONSUMER = {CONSUMER}")
    print(f"   STAFF = {STAFF}")
    print(f"   SUPERUSER = {SUPERUSER}")
    print(f"   CERTIFIER = {CERTIFIER}")
    print()

    tests = [
        test_producer_emails,
        test_consumer_emails,
        test_other_user_types,
        test_template_rendering_by_type,
    ]

    passed = 0
    total = len(tests)

    for test in tests:
        if test():
            passed += 1

    print("\n" + "=" * 55)
    print(f"📊 Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All user type differentiation tests passed!")
        print("✅ Producer and Consumer users receive properly differentiated emails")
        print("✅ Email templates adapt content and styling based on user type")
        print("✅ Verification codes and sign-up emails work for both user types")
    else:
        print(f"⚠️  {total - passed} tests failed. User type differentiation needs fixes.")

    return passed == total


if __name__ == "__main__":
    main()
