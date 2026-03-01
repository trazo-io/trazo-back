#!/usr/bin/env python
"""
Integration Testing Script for Trazo Backend
=====================================

This script verifies that all integration points between new production features
and existing functionality work correctly.

Test Coverage:
1. API endpoints - middleware compatibility
2. Authentication flow - JWT and session auth
3. Database queries - index compatibility
4. Frontend API compatibility
5. Third-party integrations
6. Serializer compatibility
7. Permission systems
8. Celery tasks
9. File uploads and static serving
"""

import json
import os
import sys
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

import django

import requests

# Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from carbon.models import CarbonEntry, CarbonSource
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel

# Import models
from users.models import User


class IntegrationTestRunner:
    """
    Comprehensive integration test runner that verifies all system components
    work together correctly after new production features implementation.
    """

    def __init__(self):
        self.client = APIClient()
        self.results = {"passed": 0, "failed": 0, "warnings": 0, "details": []}
        self.test_user = None
        self.test_company = None
        self.test_establishment = None

    def run_all_tests(self):
        """Run all integration tests"""
        print("🚀 Starting Trazo Backend Integration Verification")
        print("=" * 60)

        try:
            # Setup test data
            self._setup_test_data()

            # Run all test suites
            self._test_middleware_compatibility()
            self._test_authentication_flow()
            self._test_database_queries()
            self._test_api_response_format()
            self._test_third_party_integrations()
            self._test_serializer_compatibility()
            self._test_permission_systems()
            self._test_celery_tasks()
            self._test_file_operations()

        except Exception as e:
            self._log_failure("CRITICAL", f"Test setup failed: {str(e)}")

        finally:
            # Cleanup
            self._cleanup_test_data()

        # Print results
        self._print_results()

        return self.results["failed"] == 0

    def _setup_test_data(self):
        """Create test data for integration tests"""
        try:
            # Create test user
            self.test_user = User.objects.create_user(
                email="integration.test@trazo.com",
                password="TestPassword123!",
                first_name="Integration",
                last_name="Test",
            )

            # Create test company
            self.test_company = Company.objects.create(
                name="Test Integration Company",
                contact_email="test@trazo.com",
                city="Test City",
                state="Test State",
                address="123 Test Street",
            )

            # Create test establishment
            self.test_establishment = Establishment.objects.create(
                name="Test Integration Farm",
                company=self.test_company,
                city="Test City",
                state="Test State",
                address="123 Farm Street",
            )

            self._log_success("TEST_SETUP", "Test data created successfully")

        except Exception as e:
            self._log_failure("TEST_SETUP", f"Failed to create test data: {str(e)}")
            raise

    def _test_middleware_compatibility(self):
        """Test that new middleware doesn't break API responses"""
        try:
            # Test without authentication (should work for public endpoints)
            response = self.client.get("/api/carbon/entries/")
            if response.status_code in [200, 401]:  # 401 is expected for protected endpoints
                self._log_success("MIDDLEWARE", "Middleware allows requests to pass through")
            else:
                self._log_failure("MIDDLEWARE", f"Unexpected response: {response.status_code}")

            # Test security headers are added
            response = self.client.get("/api/carbon/entries/")
            security_headers = ["X-Content-Type-Options", "X-Frame-Options", "X-XSS-Protection", "Referrer-Policy"]

            missing_headers = []
            for header in security_headers:
                if header not in response:
                    missing_headers.append(header)

            if missing_headers:
                self._log_warning("MIDDLEWARE", f"Missing security headers: {missing_headers}")
            else:
                self._log_success("MIDDLEWARE", "All security headers present")

        except Exception as e:
            self._log_failure("MIDDLEWARE", f"Middleware test failed: {str(e)}")

    def _test_authentication_flow(self):
        """Test JWT and session authentication with new security features"""
        try:
            # Test login endpoint
            login_data = {"email": "integration.test@trazo.com", "password": "TestPassword123!"}

            response = self.client.post("/api/auth/login/", login_data, format="json")

            if response.status_code == 200:
                self._log_success("AUTH", "Login endpoint working")

                # Extract token
                response_data = response.json()
                if "access" in response_data:
                    token = response_data["access"]

                    # Test authenticated request
                    self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
                    auth_response = self.client.get("/api/users/profile/")

                    if auth_response.status_code == 200:
                        self._log_success("AUTH", "JWT authentication working")
                    else:
                        self._log_failure("AUTH", f"JWT auth failed: {auth_response.status_code}")
                else:
                    self._log_failure("AUTH", "No access token in login response")
            else:
                self._log_failure("AUTH", f"Login failed: {response.status_code}")

        except Exception as e:
            self._log_failure("AUTH", f"Authentication test failed: {str(e)}")

    def _test_database_queries(self):
        """Test that new indexes don't conflict with existing queries"""
        try:
            # Test basic model queries

            # Test User queries
            users = User.objects.all()[:10]
            self._log_success("DATABASE", f"User queries working - {len(users)} users found")

            # Test Company queries
            companies = Company.objects.all()[:10]
            self._log_success("DATABASE", f"Company queries working - {len(companies)} companies found")

            # Test Establishment queries
            establishments = Establishment.objects.all()[:10]
            self._log_success("DATABASE", f"Establishment queries working - {len(establishments)} establishments found")

            # Test Carbon queries
            carbon_entries = CarbonEntry.objects.all()[:10]
            self._log_success("DATABASE", f"Carbon queries working - {len(carbon_entries)} entries found")

            # Test complex queries with joins
            complex_query = Establishment.objects.select_related("company").prefetch_related("carbonfootprint_set")[:5]
            result = list(complex_query)
            self._log_success("DATABASE", f"Complex queries working - {len(result)} results")

        except Exception as e:
            self._log_failure("DATABASE", f"Database query test failed: {str(e)}")

    def _test_api_response_format(self):
        """Test that API responses match expected frontend format"""
        try:
            # Authenticate first
            self._authenticate_client()

            # Test carbon endpoints
            endpoints_to_test = [
                ("/api/carbon/entries/", "Carbon entries"),
                ("/api/carbon/sources/", "Carbon sources"),
                ("/api/company/companies/", "Companies"),
                ("/api/company/establishments/", "Establishments"),
            ]

            for endpoint, description in endpoints_to_test:
                try:
                    response = self.client.get(endpoint)
                    if response.status_code == 200:
                        data = response.json()

                        # Check basic structure
                        if isinstance(data, dict) and "results" in data:
                            self._log_success("API_FORMAT", f"{description} - paginated response format correct")
                        elif isinstance(data, list):
                            self._log_success("API_FORMAT", f"{description} - list response format correct")
                        else:
                            self._log_warning("API_FORMAT", f"{description} - unexpected response format")
                    else:
                        self._log_warning("API_FORMAT", f"{description} - status {response.status_code}")

                except Exception as e:
                    self._log_warning("API_FORMAT", f"{description} - error: {str(e)}")

        except Exception as e:
            self._log_failure("API_FORMAT", f"API format test failed: {str(e)}")

    def _test_third_party_integrations(self):
        """Test USDA API, Stripe, and blockchain services"""
        try:
            # USDA API integration removed for MVP — using hardcoded factors
            self._log_success("USDA", "USDA API removed for MVP (hardcoded EPA/USDA factors)")
            else:
                self._log_warning("USDA", "USDA API key not configured - skipping test")

            # Test blockchain service initialization
            try:
                from carbon.services.blockchain import BlockchainService

                blockchain_service = BlockchainService()
                self._log_success("BLOCKCHAIN", "Blockchain service initialized")
            except Exception as e:
                self._log_warning("BLOCKCHAIN", f"Blockchain service issue: {str(e)}")

            # Test Stripe configuration (if configured)
            if hasattr(settings, "STRIPE_SECRET_KEY") and settings.STRIPE_SECRET_KEY:
                self._log_success("STRIPE", "Stripe configuration present")
            else:
                self._log_warning("STRIPE", "Stripe not configured - skipping test")

        except Exception as e:
            self._log_failure("THIRD_PARTY", f"Third-party integration test failed: {str(e)}")

    def _test_serializer_compatibility(self):
        """Test that JSON responses match expected schemas"""
        try:
            self._authenticate_client()

            # Test carbon entry serializer
            response = self.client.get("/api/carbon/entries/")
            if response.status_code == 200:
                data = response.json()

                # Check expected fields in carbon entries
                if "results" in data and len(data["results"]) > 0:
                    entry = data["results"][0]
                    expected_fields = ["id", "carbon_source", "co2e_amount", "created_at"]

                    missing_fields = [field for field in expected_fields if field not in entry]
                    if missing_fields:
                        self._log_warning("SERIALIZER", f"Missing fields in carbon entry: {missing_fields}")
                    else:
                        self._log_success("SERIALIZER", "Carbon entry serializer working correctly")
                else:
                    self._log_warning("SERIALIZER", "No carbon entries to test serializer")

            # Test company serializer
            response = self.client.get("/api/company/companies/")
            if response.status_code == 200:
                data = response.json()
                if "results" in data and len(data["results"]) > 0:
                    company = data["results"][0]
                    if "name" in company and "id" in company:
                        self._log_success("SERIALIZER", "Company serializer working correctly")
                    else:
                        self._log_warning("SERIALIZER", "Company serializer missing basic fields")

        except Exception as e:
            self._log_failure("SERIALIZER", f"Serializer test failed: {str(e)}")

    def _test_permission_systems(self):
        """Test role-based access control with new middleware"""
        try:
            # Test unauthenticated access (should be blocked)
            self.client.credentials()  # Clear auth
            response = self.client.post("/api/carbon/entries/", {})

            if response.status_code == 401:
                self._log_success("PERMISSIONS", "Unauthenticated requests properly blocked")
            else:
                self._log_failure("PERMISSIONS", f"Unauthenticated request not blocked: {response.status_code}")

            # Test authenticated access
            self._authenticate_client()
            response = self.client.get("/api/users/profile/")

            if response.status_code == 200:
                self._log_success("PERMISSIONS", "Authenticated requests working")
            else:
                self._log_failure("PERMISSIONS", f"Authenticated request failed: {response.status_code}")

        except Exception as e:
            self._log_failure("PERMISSIONS", f"Permission test failed: {str(e)}")

    def _test_celery_tasks(self):
        """Test that background tasks work with new logging/monitoring"""
        try:
            # Test that Celery tasks can be imported
            from carbon.tasks import generate_nightly_reports

            self._log_success("CELERY", "Celery tasks can be imported")

            # Test task definition (don't actually run to avoid side effects)
            if hasattr(generate_nightly_reports, "delay"):
                self._log_success("CELERY", "Celery task decorator working")
            else:
                self._log_warning("CELERY", "Celery task decorator not found")

        except Exception as e:
            self._log_warning("CELERY", f"Celery test failed (expected if Redis not running): {str(e)}")

    def _test_file_operations(self):
        """Test file uploads and static serving with new middleware"""
        try:
            # Test that static files configuration is working
            if hasattr(settings, "STATIC_URL"):
                self._log_success("FILES", "Static files configuration present")

            # Test media configuration
            if hasattr(settings, "MEDIA_URL") and hasattr(settings, "MEDIA_ROOT"):
                self._log_success("FILES", "Media files configuration present")

            # Test that file upload endpoints exist
            self._authenticate_client()
            # Just check that the endpoint exists (don't actually upload)
            response = self.client.options("/api/common/gallery/")
            if response.status_code in [200, 405]:  # 405 is OK, means endpoint exists
                self._log_success("FILES", "File upload endpoints accessible")
            else:
                self._log_warning("FILES", f"File upload endpoint issue: {response.status_code}")

        except Exception as e:
            self._log_failure("FILES", f"File operations test failed: {str(e)}")

    def _authenticate_client(self):
        """Helper to authenticate the test client"""
        if self.test_user:
            token = AccessToken.for_user(self.test_user)
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _cleanup_test_data(self):
        """Clean up test data"""
        try:
            if self.test_establishment:
                self.test_establishment.delete()
            if self.test_company:
                self.test_company.delete()
            if self.test_user:
                self.test_user.delete()
            self._log_success("CLEANUP", "Test data cleaned up")
        except Exception as e:
            self._log_warning("CLEANUP", f"Cleanup failed: {str(e)}")

    def _log_success(self, category: str, message: str):
        """Log a successful test"""
        self.results["passed"] += 1
        self.results["details"].append({"status": "PASS", "category": category, "message": message})
        print(f"✅ {category}: {message}")

    def _log_failure(self, category: str, message: str):
        """Log a failed test"""
        self.results["failed"] += 1
        self.results["details"].append({"status": "FAIL", "category": category, "message": message})
        print(f"❌ {category}: {message}")

    def _log_warning(self, category: str, message: str):
        """Log a warning"""
        self.results["warnings"] += 1
        self.results["details"].append({"status": "WARN", "category": category, "message": message})
        print(f"⚠️  {category}: {message}")

    def _print_results(self):
        """Print final test results"""
        print("\n" + "=" * 60)
        print("🔍 INTEGRATION TEST RESULTS")
        print("=" * 60)
        print(f"✅ Passed: {self.results['passed']}")
        print(f"❌ Failed: {self.results['failed']}")
        print(f"⚠️  Warnings: {self.results['warnings']}")

        if self.results["failed"] == 0:
            print("\n🎉 ALL CRITICAL INTEGRATION TESTS PASSED!")
            print("✅ New production features integrate correctly with existing functionality")
        else:
            print(f"\n⚠️  {self.results['failed']} CRITICAL ISSUES FOUND")
            print("🔧 Review failed tests before deploying to production")

        # Print detailed breakdown by category
        categories = {}
        for detail in self.results["details"]:
            cat = detail["category"]
            if cat not in categories:
                categories[cat] = {"PASS": 0, "FAIL": 0, "WARN": 0}
            categories[cat][detail["status"]] += 1

        print(f"\n📊 Results by Category:")
        for category, counts in categories.items():
            status = "✅" if counts["FAIL"] == 0 else "❌"
            print(f"{status} {category}: {counts['PASS']} pass, {counts['FAIL']} fail, {counts['WARN']} warn")


def main():
    """Run the integration tests"""
    runner = IntegrationTestRunner()
    success = runner.run_all_tests()

    if success:
        print("\n🚀 READY FOR PRODUCTION DEPLOYMENT")
        return 0
    else:
        print("\n🛑 DEPLOYMENT BLOCKED - FIX CRITICAL ISSUES")
        return 1


if __name__ == "__main__":
    exit(main())
