#!/usr/bin/env python
"""
Simplified Integration Test for Trazo Backend
==========================================

Tests critical integration points without complex authentication flows.
"""

import os
import sys

import django

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

# Import models
from users.models import User


class SimpleIntegrationTest:
    """Simple integration test for core functionality"""

    def __init__(self):
        self.results = []

    def run_tests(self):
        """Run all integration tests"""
        print("🔧 Simple Integration Test - Verifying Core Systems")
        print("=" * 60)

        self.test_middleware_loading()
        self.test_database_connectivity()
        self.test_model_functionality()
        self.test_service_imports()
        self.test_settings_configuration()

        self._print_results()

    def test_middleware_loading(self):
        """Test that all middleware loads without errors"""
        try:
            from backend.security_middleware import CSRFSecurityMiddleware, SecurityLoggingMiddleware
            from carbon.middleware.security_middleware import CarbonSecurityMiddleware

            self._log_success("MIDDLEWARE", "All security middleware classes imported successfully")
        except Exception as e:
            self._log_failure("MIDDLEWARE", f"Middleware import failed: {str(e)}")

    def test_database_connectivity(self):
        """Test basic database operations"""
        try:
            # Test basic queries
            user_count = User.objects.count()
            company_count = Company.objects.count()
            establishment_count = Establishment.objects.count()
            carbon_count = CarbonEntry.objects.count()

            self._log_success(
                "DATABASE",
                f"Database connectivity working - Users: {user_count}, Companies: {company_count}, Establishments: {establishment_count}, Carbon: {carbon_count}",
            )

            # Test that we can create a simple record
            test_user = User.objects.create_user(email="test.simple@trazo.com", password="TestPass123!")
            test_user.delete()  # Clean up immediately

            self._log_success("DATABASE", "Database write operations working")

        except Exception as e:
            self._log_failure("DATABASE", f"Database test failed: {str(e)}")

    def test_model_functionality(self):
        """Test that models work correctly"""
        try:
            # Test model relationships still work
            from carbon.models import CarbonEntry, CarbonSource
            from company.models import Company, Establishment
            from users.models import User

            # Check model meta options
            self._log_success("MODELS", "All model classes imported successfully")

            # Test basic model instantiation (without saving)
            user = User(email="test@example.com")
            company = Company(name="Test Company")
            establishment = Establishment(name="Test Farm")

            self._log_success("MODELS", "Model instantiation working")

        except Exception as e:
            self._log_failure("MODELS", f"Model test failed: {str(e)}")

    def test_service_imports(self):
        """Test that key services can be imported"""
        try:
            # Test carbon services
            from carbon.services import calculator
            from carbon.services.circuit_breaker_enhanced import CircuitBreakerManager
            self._log_success("SERVICES", "Carbon services imported successfully")

            # Test other services
            from backend.services.secrets_manager import SecretsManager

            self._log_success("SERVICES", "Security services imported successfully")

        except Exception as e:
            self._log_failure("SERVICES", f"Service import failed: {str(e)}")

    def test_settings_configuration(self):
        """Test that settings are properly configured"""
        try:
            # Test critical settings
            required_settings = ["SECRET_KEY", "DATABASES", "INSTALLED_APPS", "MIDDLEWARE", "REST_FRAMEWORK"]

            for setting in required_settings:
                if hasattr(settings, setting):
                    self._log_success("SETTINGS", f"{setting} configured")
                else:
                    self._log_failure("SETTINGS", f"{setting} missing")

            # Test middleware order
            middleware = settings.MIDDLEWARE
            security_middleware = [m for m in middleware if "security" in m.lower()]
            if security_middleware:
                self._log_success("SETTINGS", f"Security middleware configured: {len(security_middleware)} found")
            else:
                self._log_failure("SETTINGS", "No security middleware found")

        except Exception as e:
            self._log_failure("SETTINGS", f"Settings test failed: {str(e)}")

    def _log_success(self, category: str, message: str):
        """Log a successful test"""
        self.results.append({"status": "PASS", "category": category, "message": message})
        print(f"✅ {category}: {message}")

    def _log_failure(self, category: str, message: str):
        """Log a failed test"""
        self.results.append({"status": "FAIL", "category": category, "message": message})
        print(f"❌ {category}: {message}")

    def _print_results(self):
        """Print test summary"""
        passed = len([r for r in self.results if r["status"] == "PASS"])
        failed = len([r for r in self.results if r["status"] == "FAIL"])

        print(f"\n📊 Test Results: {passed} passed, {failed} failed")

        if failed == 0:
            print("✅ Core integration working correctly")
        else:
            print("❌ Critical integration issues found")


def main():
    """Run the simple integration test"""
    test = SimpleIntegrationTest()
    test.run_tests()


if __name__ == "__main__":
    main()
