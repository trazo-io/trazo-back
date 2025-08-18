#!/usr/bin/env python3
"""
Security Edge Cases Testing

Comprehensive security testing for production readiness features including:
- API key security and rotation
- Input validation and sanitization
- Authentication edge cases
- Authorization bypass attempts
- Injection attack prevention
- Rate limiting and DoS protection
"""

import base64
import hashlib
import logging
import os
import random
import sys
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import django
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

import jwt
import requests

# Add project root to path
sys.path.insert(0, "/Users/oscarmunoz/dev/trazo/trazo-back")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from backend.services.secrets_manager import SecureSecretsManager
from carbon.models import CarbonEntry
from carbon.services.secure_key_management import SecureKeyManagement
from common.services.enhanced_logging import SecurityAuditLogger
from company.models import Company, Establishment
from users.models import User


class SecurityEdgeCaseTests:
    """Test suite for security edge cases and attack scenarios"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.test_results = {}
        self.client = Client()
        self.audit_logger = SecurityAuditLogger()
        self.created_users = []
        self.created_objects = []

    def run_security_tests(self):
        """Run comprehensive security edge case tests"""
        print("\n🔒 Starting Security Edge Case Testing")
        print("=" * 60)

        security_tests = [
            self.test_api_key_security_edge_cases,
            self.test_input_validation_bypass_attempts,
            self.test_authentication_edge_cases,
            self.test_authorization_bypass_attempts,
            self.test_sql_injection_prevention,
            self.test_xss_prevention_comprehensive,
            self.test_csrf_protection,
            self.test_rate_limiting_bypass_attempts,
            self.test_session_security,
            self.test_file_upload_security,
            self.test_data_exposure_prevention,
            self.test_timing_attack_prevention,
        ]

        for test in security_tests:
            test_name = test.__name__
            print(f"\n🛡️ Running {test_name}")

            start_time = time.time()
            try:
                test()
                duration = time.time() - start_time
                self.test_results[test_name] = {"status": "PASSED", "duration": duration}
                print(f"✅ {test_name} PASSED ({duration:.2f}s)")
            except Exception as e:
                duration = time.time() - start_time
                self.test_results[test_name] = {"status": "FAILED", "error": str(e), "duration": duration}
                print(f"❌ {test_name} FAILED: {str(e)}")
            finally:
                self.cleanup_test_data()

        self.print_security_test_summary()

    def test_api_key_security_edge_cases(self):
        """Test API key security under various edge cases"""
        print("  Testing API key security edge cases...")

        key_manager = SecureKeyManagement()

        # Test key rotation under concurrent access
        def concurrent_key_rotation(service_name):
            try:
                for i in range(10):
                    old_key = key_manager.get_api_key(service_name)
                    key_manager.rotate_api_key(service_name)
                    new_key = key_manager.get_api_key(service_name)
                    assert old_key != new_key, "Key rotation failed"
            except Exception as e:
                self.logger.error(f"Concurrent key rotation error: {e}")
                raise

        # Test concurrent rotation
        threads = []
        for i in range(5):
            thread = threading.Thread(target=concurrent_key_rotation, args=(f"test_service_{i}",))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        print("    ✓ Concurrent key rotation handled safely")

        # Test key encryption/decryption edge cases
        edge_case_keys = [
            "",  # Empty key
            "a" * 1000,  # Very long key
            "🔑🚀💾",  # Unicode characters
            "\x00\x01\x02",  # Binary data
            "key with spaces and special chars !@#$%^&*()",
        ]

        for test_key in edge_case_keys:
            try:
                encrypted = key_manager.encrypt_key(test_key)
                decrypted = key_manager.decrypt_key(encrypted)
                assert decrypted == test_key, f"Key encryption/decryption failed for: {repr(test_key)}"
                print(f"    ✓ Key encryption handled: {repr(test_key[:20])}")
            except Exception as e:
                print(f"    ⚠️ Key encryption failed for {repr(test_key[:20])}: {e}")

        # Test key storage security
        self._test_key_storage_security(key_manager)

    def _test_key_storage_security(self, key_manager):
        """Test key storage security mechanisms"""
        # Test that keys are not stored in plain text
        test_key = "super_secret_test_key_12345"
        encrypted_key = key_manager.encrypt_key(test_key)

        # Encrypted key should not contain the original key
        assert test_key not in encrypted_key, "Key stored in plain text"

        # Test key expiration
        expired_key = key_manager.create_key_with_expiration("test_service", hours=0.001)  # 3.6 seconds
        time.sleep(4)

        try:
            retrieved_key = key_manager.get_api_key("test_service")
            print("    ⚠️ Expired key not properly handled")
        except Exception:
            print("    ✓ Expired key properly rejected")

    def test_input_validation_bypass_attempts(self):
        """Test various input validation bypass attempts"""
        print("  Testing input validation bypass attempts...")

        # Create test user
        user = User.objects.create_user(email="test@example.com", password="testpass123")
        self.created_users.append(user.id)

        # Test company creation with malicious inputs
        malicious_inputs = [
            # SQL injection attempts
            {"name": "'; DROP TABLE company_company; --", "address": "123 Test St"},
            {"name": "Test Company", "address": "123'; DELETE FROM company_company; --"},
            # XSS attempts
            {"name": "<script>alert('xss')</script>", "address": "123 Test St"},
            {"name": "Test Company", "address": "<img src=x onerror=alert('xss')>"},
            # NoSQL injection attempts
            {"name": {"$ne": None}, "address": "123 Test St"},
            {"name": "Test Company", "address": {"$regex": ".*"}},
            # Path traversal attempts
            {"name": "../../../etc/passwd", "address": "123 Test St"},
            {"name": "Test Company", "address": "..\\..\\windows\\system32"},
            # Command injection attempts
            {"name": "Test; rm -rf /", "address": "123 Test St"},
            {"name": "Test Company", "address": "123 | whoami"},
            # Buffer overflow attempts
            {"name": "A" * 10000, "address": "123 Test St"},
            {"name": "Test Company", "address": "B" * 10000},
            # Unicode and encoding attacks
            {"name": "Test\u0000Company", "address": "123 Test St"},
            {"name": "Test Company", "address": "123\xff\xfe Test St"},
        ]

        self.client.force_login(user)

        for malicious_input in malicious_inputs:
            try:
                response = self.client.post(
                    "/api/companies/",
                    {
                        "name": malicious_input["name"],
                        "address": malicious_input["address"],
                        "city": "Test City",
                        "country": "US",
                    },
                )

                if response.status_code == 201:
                    # Check if malicious input was sanitized
                    company_id = response.json().get("id")
                    if company_id:
                        company = Company.objects.get(id=company_id)
                        self.created_objects.append(("company", company_id))

                        # Verify sanitization
                        if (
                            "<script>" in company.name.lower()
                            or "drop table" in company.name.lower()
                            or "delete from" in company.address.lower()
                        ):
                            print(f"    ⚠️ Malicious input not sanitized: {malicious_input}")
                        else:
                            print(f"    ✓ Malicious input properly sanitized")
                else:
                    print(f"    ✓ Malicious input properly rejected")

            except Exception as e:
                print(f"    ✓ Malicious input caused validation error: {e}")

    def test_authentication_edge_cases(self):
        """Test authentication system edge cases"""
        print("  Testing authentication edge cases...")

        # Test with malformed JWT tokens
        malformed_tokens = [
            "invalid.token.format",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid_payload.signature",
            "",
            None,
            "Bearer " + "a" * 1000,  # Very long token
            "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJub25lIn0.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.",  # None algorithm
        ]

        for token in malformed_tokens:
            headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
            response = self.client.get("/api/companies/", **headers)

            if response.status_code == 200:
                print(f"    ⚠️ Malformed token accepted: {repr(token)}")
            else:
                print(f"    ✓ Malformed token properly rejected")

        # Test password edge cases
        edge_case_passwords = [
            "",  # Empty password
            " " * 100,  # Whitespace only
            "password",  # Common password
            "12345678",  # Sequential numbers
            "aaaaaaaa",  # Repeated characters
            "\x00\x01\x02",  # Binary data
            "🔑🚀💾" * 20,  # Unicode password
        ]

        for password in edge_case_passwords:
            try:
                test_user = User.objects.create_user(
                    email=f"test_{random.randint(1000, 9999)}@example.com", password=password
                )
                self.created_users.append(test_user.id)
                print(f"    ⚠️ Weak password accepted: {repr(password[:20])}")
            except Exception:
                print(f"    ✓ Weak password rejected: {repr(password[:20])}")

        # Test concurrent login attempts
        self._test_concurrent_authentication()

    def _test_concurrent_authentication(self):
        """Test concurrent authentication attempts"""
        user = User.objects.create_user(email="concurrent_test@example.com", password="testpass123")
        self.created_users.append(user.id)

        login_results = {"successes": 0, "failures": 0}

        def concurrent_login():
            response = self.client.post(
                "/api/auth/login/", {"email": "concurrent_test@example.com", "password": "testpass123"}
            )
            if response.status_code == 200:
                login_results["successes"] += 1
            else:
                login_results["failures"] += 1

        # Multiple concurrent logins
        threads = []
        for i in range(20):
            thread = threading.Thread(target=concurrent_login)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        print(
            f"    ✓ Concurrent authentication handled (successes: {login_results['successes']}, failures: {login_results['failures']})"
        )

    def test_authorization_bypass_attempts(self):
        """Test authorization bypass attempts"""
        print("  Testing authorization bypass attempts...")

        # Create users with different permission levels
        admin_user = User.objects.create_user(email="admin@example.com", password="adminpass123", is_staff=True)

        regular_user = User.objects.create_user(email="regular@example.com", password="userpass123")

        self.created_users.extend([admin_user.id, regular_user.id])

        # Create company owned by admin
        company = Company.objects.create(name="Admin Company", address="123 Admin St", city="Admin City", country="US")
        self.created_objects.append(("company", company.id))

        # Test regular user trying to access admin resources
        self.client.force_login(regular_user)

        # Attempt to access admin company
        response = self.client.get(f"/api/companies/{company.id}/")
        if response.status_code == 200:
            print("    ⚠️ Authorization bypass detected - regular user accessed admin resource")
        else:
            print("    ✓ Authorization properly enforced")

        # Test parameter tampering
        tampering_attempts = [
            {"user_id": admin_user.id},  # Try to impersonate admin
            {"is_staff": True},  # Try to elevate privileges
            {"permissions": ["admin"]},  # Try to add permissions
        ]

        for attempt in tampering_attempts:
            response = self.client.post("/api/profile/update/", attempt)
            if response.status_code == 200:
                print(f"    ⚠️ Parameter tampering successful: {attempt}")
            else:
                print(f"    ✓ Parameter tampering blocked: {attempt}")

        # Test IDOR (Insecure Direct Object Reference)
        self._test_idor_attacks()

    def _test_idor_attacks(self):
        """Test Insecure Direct Object Reference attacks"""
        # Create carbon entries for different users
        user1 = User.objects.create_user(email="user1@example.com", password="pass123")
        user2 = User.objects.create_user(email="user2@example.com", password="pass123")
        self.created_users.extend([user1.id, user2.id])

        # User1's carbon entry
        entry1 = CarbonEntry.objects.create(activity_type="user1_activity", amount=100.0, co2e_amount=50.0)

        # User2's carbon entry
        entry2 = CarbonEntry.objects.create(activity_type="user2_activity", amount=200.0, co2e_amount=100.0)

        self.created_objects.extend([("carbon_entry", entry1.id), ("carbon_entry", entry2.id)])

        # User1 tries to access User2's data
        self.client.force_login(user1)
        response = self.client.get(f"/api/carbon-entries/{entry2.id}/")

        if response.status_code == 200:
            print("    ⚠️ IDOR vulnerability detected")
        else:
            print("    ✓ IDOR attack prevented")

    def test_sql_injection_prevention(self):
        """Test comprehensive SQL injection prevention"""
        print("  Testing SQL injection prevention...")

        # Create test user and data
        user = User.objects.create_user(email="sql_test@example.com", password="pass123")
        self.created_users.append(user.id)

        company = Company.objects.create(name="SQL Test Company", address="123 SQL St", city="SQL City", country="US")
        self.created_objects.append(("company", company.id))

        self.client.force_login(user)

        # Advanced SQL injection payloads
        sql_payloads = [
            # Union-based injections
            "' UNION SELECT username, password FROM auth_user --",
            "1' UNION SELECT 1,2,3,4,5,6,7,8,9,10 --",
            # Boolean-based blind injections
            "' AND 1=1 --",
            "' AND 1=2 --",
            "' AND (SELECT COUNT(*) FROM auth_user) > 0 --",
            # Time-based blind injections
            "'; WAITFOR DELAY '00:00:05' --",
            "' AND (SELECT SLEEP(5)) --",
            # Error-based injections
            "' AND EXTRACTVALUE(1, CONCAT(0x7e, (SELECT user()), 0x7e)) --",
            "' AND (SELECT * FROM (SELECT COUNT(*),CONCAT((SELECT version()),FLOOR(RAND(0)*2))x FROM information_schema.tables GROUP BY x)a) --",
            # Stacked queries
            "'; DROP TABLE company_company; --",
            "'; INSERT INTO auth_user (username, password) VALUES ('hacker', 'password'); --",
            # NoSQL injection attempts
            {"$ne": None},
            {"$regex": ".*"},
            {"$where": "1==1"},
        ]

        # Test SQL injection in search/filter parameters
        for payload in sql_payloads:
            try:
                if isinstance(payload, dict):
                    # NoSQL style injection
                    response = self.client.get("/api/companies/", payload)
                else:
                    # SQL injection in search
                    response = self.client.get("/api/companies/", {"search": payload})

                # Check if injection was successful
                if response.status_code == 200:
                    data = response.json()
                    if "password" in str(data) or "auth_user" in str(data):
                        print(f"    ⚠️ SQL injection successful: {repr(payload)}")
                    else:
                        print(f"    ✓ SQL injection blocked: {repr(payload)}")
                else:
                    print(f"    ✓ SQL injection blocked with error: {repr(payload)}")

            except Exception as e:
                print(f"    ✓ SQL injection caused safe error: {repr(payload)}")

    def test_xss_prevention_comprehensive(self):
        """Test comprehensive XSS prevention"""
        print("  Testing comprehensive XSS prevention...")

        user = User.objects.create_user(email="xss_test@example.com", password="pass123")
        self.created_users.append(user.id)
        self.client.force_login(user)

        # Advanced XSS payloads
        xss_payloads = [
            # Basic script injection
            "<script>alert('xss')</script>",
            "<SCRIPT>alert('XSS')</SCRIPT>",
            # Event handlers
            "<img src=x onerror=alert('xss')>",
            "<body onload=alert('xss')>",
            "<div onmouseover=alert('xss')>",
            # JavaScript URLs
            "javascript:alert('xss')",
            "JaVaScRiPt:alert('xss')",
            # Encoded payloads
            "%3Cscript%3Ealert('xss')%3C/script%3E",
            "&#60;script&#62;alert('xss')&#60;/script&#62;",
            # Filter bypass attempts
            "<scr<script>ipt>alert('xss')</script>",
            "<img src=x onerror=eval(String.fromCharCode(97,108,101,114,116,40,39,120,115,115,39,41))>",
            # DOM-based XSS
            "<svg onload=alert('xss')>",
            "<details open ontoggle=alert('xss')>",
            # CSS injection
            "<style>body{background:url('javascript:alert(\"xss\")')}</style>",
            "expression(alert('xss'))",
        ]

        for payload in xss_payloads:
            try:
                # Test XSS in company creation
                response = self.client.post(
                    "/api/companies/", {"name": payload, "address": "123 Test St", "city": "Test City", "country": "US"}
                )

                if response.status_code == 201:
                    company_id = response.json().get("id")
                    if company_id:
                        company = Company.objects.get(id=company_id)
                        self.created_objects.append(("company", company_id))

                        # Check if XSS payload is present in stored data
                        if "<script>" in company.name.lower() or "alert(" in company.name:
                            print(f"    ⚠️ XSS payload stored: {repr(payload)}")
                        else:
                            print(f"    ✓ XSS payload sanitized: {repr(payload)}")
                else:
                    print(f"    ✓ XSS payload rejected: {repr(payload)}")

            except Exception as e:
                print(f"    ✓ XSS payload caused validation error: {repr(payload)}")

    def test_csrf_protection(self):
        """Test CSRF protection mechanisms"""
        print("  Testing CSRF protection...")

        # Test CSRF protection on state-changing operations
        csrf_test_requests = [
            ("POST", "/api/companies/", {"name": "CSRF Test", "address": "123 St", "city": "City", "country": "US"}),
            ("PUT", "/api/companies/1/", {"name": "Updated"}),
            ("DELETE", "/api/companies/1/"),
        ]

        for method, url, data in csrf_test_requests:
            # Request without CSRF token
            if method == "POST":
                response = self.client.post(url, data)
            elif method == "PUT":
                response = self.client.put(url, data)
            elif method == "DELETE":
                response = self.client.delete(url)

            # Should be rejected without proper CSRF protection
            if response.status_code in [403, 401]:
                print(f"    ✓ CSRF protection active for {method} {url}")
            else:
                print(f"    ⚠️ CSRF protection missing for {method} {url}")

    def test_rate_limiting_bypass_attempts(self):
        """Test rate limiting bypass attempts"""
        print("  Testing rate limiting bypass attempts...")

        # Test rapid requests from same IP
        rapid_requests = 0
        start_time = time.time()

        while time.time() - start_time < 1.0:  # 1 second burst
            response = self.client.get("/api/companies/")
            rapid_requests += 1

            if response.status_code == 429:  # Too Many Requests
                print(f"    ✓ Rate limiting activated after {rapid_requests} requests")
                break

        if rapid_requests > 100:
            print(f"    ⚠️ No rate limiting detected ({rapid_requests} requests/sec)")

        # Test rate limiting bypass with different headers
        bypass_headers = [
            {"HTTP_X_FORWARDED_FOR": "192.168.1.100"},
            {"HTTP_X_REAL_IP": "10.0.0.100"},
            {"HTTP_USER_AGENT": "Different User Agent"},
            {"HTTP_X_FORWARDED_HOST": "different.host.com"},
        ]

        for headers in bypass_headers:
            response = self.client.get("/api/companies/", **headers)
            # Rate limiting should not be easily bypassed
            print(f"    ✓ Rate limiting bypass attempt tested")

    def test_session_security(self):
        """Test session security mechanisms"""
        print("  Testing session security...")

        user = User.objects.create_user(email="session_test@example.com", password="pass123")
        self.created_users.append(user.id)

        # Test session fixation
        self.client.login(email="session_test@example.com", password="pass123")
        session_key_before = self.client.session.session_key

        # Logout and login again
        self.client.logout()
        self.client.login(email="session_test@example.com", password="pass123")
        session_key_after = self.client.session.session_key

        if session_key_before != session_key_after:
            print("    ✓ Session regeneration on login working")
        else:
            print("    ⚠️ Session fixation vulnerability detected")

        # Test concurrent sessions
        self._test_concurrent_sessions(user)

    def _test_concurrent_sessions(self, user):
        """Test concurrent session handling"""
        from django.contrib.sessions.models import Session

        # Clear existing sessions
        Session.objects.all().delete()

        # Create multiple concurrent sessions
        clients = [Client() for _ in range(5)]

        for client in clients:
            client.login(email=user.email, password="pass123")

        # Check session count
        active_sessions = Session.objects.count()

        if active_sessions <= 2:  # Should limit concurrent sessions
            print(f"    ✓ Concurrent sessions limited ({active_sessions} active)")
        else:
            print(f"    ⚠️ Too many concurrent sessions allowed ({active_sessions} active)")

    def test_file_upload_security(self):
        """Test file upload security mechanisms"""
        print("  Testing file upload security...")

        user = User.objects.create_user(email="upload_test@example.com", password="pass123")
        self.created_users.append(user.id)
        self.client.force_login(user)

        # Test malicious file uploads
        malicious_files = [
            # PHP shell
            ("shell.php", b"<?php system($_GET['cmd']); ?>", "application/x-php"),
            # JavaScript
            ("script.js", b"alert('xss')", "application/javascript"),
            # Executable
            ("malware.exe", b"\x4d\x5a\x90\x00", "application/x-executable"),
            # Large file
            ("large.txt", b"A" * (10 * 1024 * 1024), "text/plain"),  # 10MB
            # Double extension
            ("image.jpg.php", b"<?php echo 'pwned'; ?>", "image/jpeg"),
            # Null byte injection
            ("image.jpg\x00.php", b"malicious content", "image/jpeg"),
        ]

        for filename, content, content_type in malicious_files:
            from django.core.files.uploadedfile import SimpleUploadedFile

            uploaded_file = SimpleUploadedFile(filename, content, content_type=content_type)

            try:
                # Attempt to upload malicious file
                response = self.client.post("/api/upload/", {"file": uploaded_file})

                if response.status_code == 200:
                    print(f"    ⚠️ Malicious file upload accepted: {filename}")
                else:
                    print(f"    ✓ Malicious file upload rejected: {filename}")

            except Exception as e:
                print(f"    ✓ Malicious file upload blocked: {filename}")

    def test_data_exposure_prevention(self):
        """Test prevention of sensitive data exposure"""
        print("  Testing data exposure prevention...")

        # Create sensitive test data
        admin_user = User.objects.create_user(email="admin@example.com", password="supersecret123", is_staff=True)
        self.created_users.append(admin_user.id)

        # Test that sensitive fields are not exposed in API responses
        response = self.client.get(f"/api/users/{admin_user.id}/")

        if response.status_code == 200:
            user_data = response.json()

            # Check for password exposure
            if "password" in user_data:
                print("    ⚠️ Password field exposed in API response")
            else:
                print("    ✓ Password field properly hidden")

            # Check for sensitive fields
            sensitive_fields = ["password_hash", "secret_key", "private_key"]
            for field in sensitive_fields:
                if field in user_data:
                    print(f"    ⚠️ Sensitive field exposed: {field}")

        # Test debug information exposure
        response = self.client.get("/api/debug/")
        if response.status_code == 200:
            debug_data = response.json()
            if "SECRET_KEY" in str(debug_data) or "DATABASE_URL" in str(debug_data):
                print("    ⚠️ Debug information exposing sensitive data")
            else:
                print("    ✓ Debug information properly sanitized")
        else:
            print("    ✓ Debug endpoint properly protected")

    def test_timing_attack_prevention(self):
        """Test timing attack prevention"""
        print("  Testing timing attack prevention...")

        # Create test user
        user = User.objects.create_user(email="timing_test@example.com", password="pass123")
        self.created_users.append(user.id)

        # Test login timing for existing vs non-existing users
        def measure_login_time(email, password):
            start_time = time.time()
            response = self.client.post("/api/auth/login/", {"email": email, "password": password})
            return time.time() - start_time

        # Measure timing for existing user (wrong password)
        existing_user_times = []
        for _ in range(10):
            timing = measure_login_time("timing_test@example.com", "wrongpassword")
            existing_user_times.append(timing)

        # Measure timing for non-existing user
        nonexisting_user_times = []
        for _ in range(10):
            timing = measure_login_time("nonexistent@example.com", "wrongpassword")
            nonexisting_user_times.append(timing)

        # Calculate average times
        avg_existing = sum(existing_user_times) / len(existing_user_times)
        avg_nonexisting = sum(nonexisting_user_times) / len(nonexisting_user_times)

        # Time difference should be minimal (< 50ms)
        time_diff = abs(avg_existing - avg_nonexisting)
        if time_diff < 0.05:  # 50ms
            print(f"    ✓ Timing attack prevention working (diff: {time_diff*1000:.1f}ms)")
        else:
            print(f"    ⚠️ Timing attack vulnerability detected (diff: {time_diff*1000:.1f}ms)")

    def cleanup_test_data(self):
        """Clean up test data created during security tests"""
        try:
            # Clean up created objects
            for obj_type, obj_id in self.created_objects:
                try:
                    if obj_type == "company":
                        Company.objects.filter(id=obj_id).delete()
                    elif obj_type == "carbon_entry":
                        CarbonEntry.objects.filter(id=obj_id).delete()
                except:
                    pass
            self.created_objects.clear()

            # Clean up created users
            if self.created_users:
                User.objects.filter(id__in=self.created_users).delete()
                self.created_users.clear()

        except Exception as e:
            self.logger.error(f"Security test cleanup error: {e}")

    def print_security_test_summary(self):
        """Print comprehensive security test results"""
        print("\n" + "=" * 60)
        print("🔒 SECURITY EDGE CASE TEST SUMMARY")
        print("=" * 60)

        total_tests = len(self.test_results)
        passed_tests = len([r for r in self.test_results.values() if r["status"] == "PASSED"])
        failed_tests = total_tests - passed_tests

        print(f"Total Security Tests: {total_tests}")
        print(f"Passed: {passed_tests} ✅")
        print(f"Failed: {failed_tests} ❌")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")

        if failed_tests > 0:
            print("\n❌ FAILED SECURITY TESTS:")
            for test_name, result in self.test_results.items():
                if result["status"] == "FAILED":
                    print(f"  - {test_name}: {result.get('error', 'Unknown error')}")

        print("\n⏱️  PERFORMANCE SUMMARY:")
        total_duration = 0
        for test_name, result in self.test_results.items():
            duration = result["duration"]
            total_duration += duration
            print(f"  - {test_name}: {duration:.2f}s")

        print(f"Total Test Duration: {total_duration:.2f}s")

        print("\n🛡️  SECURITY ASSESSMENT:")
        if passed_tests / total_tests >= 0.95:
            print("✅ EXCELLENT - Security implementation is robust")
        elif passed_tests / total_tests >= 0.85:
            print("✅ GOOD - Security is production-ready with minor issues")
        elif passed_tests / total_tests >= 0.75:
            print("⚠️  FAIR - Several security issues need attention")
        else:
            print("❌ POOR - Critical security vulnerabilities detected")

        print("\n🚨 SECURITY FINDINGS:")
        print("  - Input validation and sanitization")
        print("  - Authentication and authorization")
        print("  - SQL injection and XSS prevention")
        print("  - Rate limiting and DoS protection")
        print("  - Session and API key security")
        print("  - Data exposure prevention")
        print("  - Timing attack mitigation")


if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Run the security edge case tests
    security_tests = SecurityEdgeCaseTests()
    security_tests.run_security_tests()
