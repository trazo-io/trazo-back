#!/usr/bin/env python
"""
Test script to verify MailDev email configuration
"""

import os
import sys
import django
from django.conf import settings

# Add the project root to the Python path
sys.path.append('/Users/oscarmunoz/dev/trazo/trazo-back')

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from django.core.mail import send_mail
from users.utils import send_welcome_email, send_verification_email
from users.constants import PRODUCER, CONSUMER
from django.contrib.auth import get_user_model

User = get_user_model()

def test_maildev_connection():
    """Test basic MailDev connection"""
    print("🧪 Testing MailDev Connection...")
    print(f"📧 Email Backend: {settings.EMAIL_BACKEND}")
    print(f"📧 Email Host: {settings.EMAIL_HOST}")
    print(f"📧 Email Port: {settings.EMAIL_PORT}")
    print(f"📧 Email TLS: {settings.EMAIL_USE_TLS}")
    print(f"📧 Default From: {settings.DEFAULT_FROM_EMAIL}")
    
    try:
        result = send_mail(
            subject='MailDev Test Email',
            message='This is a test email to verify MailDev configuration is working.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=['test@example.com'],
            fail_silently=False,
        )
        
        if result:
            print("✅ Test email sent successfully to MailDev!")
            print("🌐 Check MailDev at: http://localhost:3025")
            return True
        else:
            print("❌ Test email failed to send")
            return False
            
    except Exception as e:
        print(f"❌ Email sending failed: {e}")
        return False

def test_producer_welcome_email():
    """Test producer welcome email"""
    print("\n🧪 Testing Producer Welcome Email...")
    
    producer_user = User(
        email='producer@testfarm.com',
        first_name='Test',
        last_name='Producer',
        user_type=PRODUCER
    )
    
    try:
        result = send_welcome_email(producer_user)
        if result:
            print("✅ Producer welcome email sent to MailDev!")
            return True
        else:
            print("❌ Producer welcome email failed")
            return False
    except Exception as e:
        print(f"❌ Producer welcome email error: {e}")
        return False

def test_consumer_verification_email():
    """Test consumer verification email"""
    print("\n🧪 Testing Consumer Verification Email...")
    
    consumer_user = User(
        email='consumer@example.com',
        first_name='Test',
        last_name='Consumer',
        user_type=CONSUMER
    )
    
    try:
        result = send_verification_email(
            user=consumer_user,
            verification_code='TEST123',
            verification_link='https://consumer.trazo.io/verify?code=TEST123'
        )
        if result:
            print("✅ Consumer verification email sent to MailDev!")
            return True
        else:
            print("❌ Consumer verification email failed")
            return False
    except Exception as e:
        print(f"❌ Consumer verification email error: {e}")
        return False

def main():
    """Run MailDev tests"""
    print("🚀 Testing Email Configuration with MailDev")
    print("=" * 50)
    
    tests = [
        test_maildev_connection,
        test_producer_welcome_email,
        test_consumer_verification_email,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
    
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All emails should now appear in MailDev!")
        print("🌐 Open MailDev at: http://localhost:3025")
        print("📧 Check your inbox for the test emails")
    else:
        print(f"⚠️  {total - passed} tests failed. Check MailDev configuration.")
    
    return passed == total

if __name__ == '__main__':
    main()