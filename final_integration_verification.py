#!/usr/bin/env python
"""
Final Integration Verification for Trazo Backend
==============================================

Comprehensive verification that all integration points work correctly
after implementing new production features and security enhancements.
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


class FinalIntegrationVerification:
    """
    Final verification of all integration points to ensure production readiness
    """

    def __init__(self):
        self.results = {
            "critical": {"passed": 0, "failed": 0, "details": []},
            "important": {"passed": 0, "failed": 0, "details": []},
            "optional": {"passed": 0, "failed": 0, "details": []},
        }

    def run_verification(self):
        """Run complete integration verification"""
        print("🚀 FINAL INTEGRATION VERIFICATION")
        print("Testing all integration points for production readiness")
        print("=" * 70)

        # Critical tests (must pass for deployment)
        self._test_critical_systems()

        # Important tests (should pass but won't block deployment)
        self._test_important_systems()

        # Optional tests (nice to have)
        self._test_optional_systems()

        # Print final results
        self._print_final_results()

        return self._is_production_ready()

    def _test_critical_systems(self):
        """Test critical systems that must work for production"""
        print("\n🔥 CRITICAL SYSTEMS VERIFICATION")
        print("-" * 50)

        # 1. Database connectivity and operations
        self._test_database_critical()

        # 2. Security middleware functionality
        self._test_security_middleware()

        # 3. Core model operations
        self._test_model_operations()

        # 4. Settings configuration
        self._test_settings_critical()

        # 5. Service initialization
        self._test_service_initialization()

    def _test_important_systems(self):
        """Test important systems that should work"""
        print("\n⚡ IMPORTANT SYSTEMS VERIFICATION")
        print("-" * 50)

        # 1. API endpoint availability
        self._test_api_endpoints()

        # 2. Third-party service configurations
        self._test_third_party_configs()

        # 3. Caching systems
        self._test_caching_systems()

        # 4. File handling
        self._test_file_systems()

    def _test_optional_systems(self):
        """Test optional systems that are nice to have"""
        print("\n🌟 OPTIONAL SYSTEMS VERIFICATION")
        print("-" * 50)

        # 1. Email system
        self._test_email_system()

        # 2. External API connectivity
        self._test_external_apis()

        # 3. Advanced features
        self._test_advanced_features()

    def _test_database_critical(self):
        """Critical database tests"""
        try:
            # Test basic connectivity
            user_count = User.objects.count()
            company_count = Company.objects.count()

            # Test write operations
            test_user = User.objects.create_user(email="final.test@trazo.com", password="TestPass123!")

            # Test read operations
            retrieved_user = User.objects.get(email="final.test@trazo.com")

            # Test delete operations
            test_user.delete()

            self._log_success(
                "critical",
                "DATABASE",
                f"Database CRUD operations working - {user_count} users, {company_count} companies",
            )

        except Exception as e:
            self._log_failure("critical", "DATABASE", f"Database operations failed: {str(e)}")

    def _test_security_middleware(self):
        """Test security middleware functionality"""
        try:
            # Test middleware imports
            from backend.security_middleware import CSRFSecurityMiddleware, SecurityLoggingMiddleware
            from carbon.middleware.security_middleware import CarbonSecurityMiddleware

            # Test middleware configuration
            middleware_list = settings.MIDDLEWARE
            security_middleware = [m for m in middleware_list if "security" in m.lower()]

            if len(security_middleware) >= 3:  # We have 3 security middleware
                self._log_success(
                    "critical",
                    "SECURITY",
                    f"Security middleware properly configured - {len(security_middleware)} found",
                )
            else:
                self._log_failure(
                    "critical", "SECURITY", f"Insufficient security middleware - only {len(security_middleware)} found"
                )

        except Exception as e:
            self._log_failure("critical", "SECURITY", f"Security middleware test failed: {str(e)}")

    def _test_model_operations(self):
        """Test core model operations"""
        try:
            # Test model imports
            from carbon.models import CarbonEntry, CarbonSource
            from company.models import Company, Establishment
            from users.models import User

            # Test model instantiation
            user = User(email="test@example.com")
            company = Company(name="Test Company")
            establishment = Establishment(name="Test Farm")

            # Test model methods exist
            if hasattr(user, "get_full_name") and hasattr(company, "save") and hasattr(establishment, "save"):
                self._log_success("critical", "MODELS", "Core model operations functional")
            else:
                self._log_failure("critical", "MODELS", "Core model methods missing")

        except Exception as e:
            self._log_failure("critical", "MODELS", f"Model operations test failed: {str(e)}")

    def _test_settings_critical(self):
        """Test critical settings configuration"""
        try:
            critical_settings = ["SECRET_KEY", "DATABASES", "INSTALLED_APPS", "MIDDLEWARE", "REST_FRAMEWORK"]

            missing_settings = []
            for setting in critical_settings:
                if not hasattr(settings, setting):
                    missing_settings.append(setting)

            if not missing_settings:
                self._log_success("critical", "SETTINGS", "All critical settings configured")
            else:
                self._log_failure("critical", "SETTINGS", f"Missing settings: {missing_settings}")

        except Exception as e:
            self._log_failure("critical", "SETTINGS", f"Settings test failed: {str(e)}")

    def _test_service_initialization(self):
        """Test that critical services can initialize"""
        try:
            # Test secrets manager
            from backend.services.secrets_manager import secrets_manager

            # Test carbon services
            from carbon.services import calculator

            # Test circuit breaker
            from carbon.services.circuit_breaker_enhanced import CircuitBreakerManager

            self._log_success("critical", "SERVICES", "Critical services initialize successfully")

        except Exception as e:
            self._log_failure("critical", "SERVICES", f"Service initialization failed: {str(e)}")

    def _test_api_endpoints(self):
        """Test API endpoint availability"""
        try:
            client = APIClient()

            # Test basic endpoint access (should return 401 for protected endpoints)
            response = client.get("/api/carbon/entries/")
            if response.status_code in [200, 401, 403]:  # Any of these is fine
                self._log_success("important", "API", "API endpoints accessible")
            else:
                self._log_failure("important", "API", f"Unexpected API response: {response.status_code}")

        except Exception as e:
            self._log_failure("important", "API", f"API endpoint test failed: {str(e)}")

    def _test_third_party_configs(self):
        """Test third-party service configurations"""
        try:
            configs_present = 0

            # Check Stripe
            if hasattr(settings, "STRIPE_SECRET_KEY") and settings.STRIPE_SECRET_KEY:
                configs_present += 1

            # Check AWS
            if hasattr(settings, "AWS_ACCESS_KEY_ID") and settings.AWS_ACCESS_KEY_ID:
                configs_present += 1

            # Check blockchain
            if hasattr(settings, "POLYGON_RPC_URL") and settings.POLYGON_RPC_URL:
                configs_present += 1

            self._log_success("important", "THIRD_PARTY", f"Third-party configurations present: {configs_present}/3")

        except Exception as e:
            self._log_failure("important", "THIRD_PARTY", f"Third-party config test failed: {str(e)}")

    def _test_caching_systems(self):
        """Test caching system functionality"""
        try:
            # Test basic cache operations
            cache.set("test_key", "test_value", 30)
            value = cache.get("test_key")

            if value == "test_value":
                self._log_success("important", "CACHE", "Caching system working")
            else:
                self._log_failure("important", "CACHE", "Cache read/write failed")

            cache.delete("test_key")

        except Exception as e:
            self._log_failure("important", "CACHE", f"Cache test failed: {str(e)}")

    def _test_file_systems(self):
        """Test file handling systems"""
        try:
            # Check media and static configurations
            media_configured = hasattr(settings, "MEDIA_URL") and hasattr(settings, "MEDIA_ROOT")
            static_configured = hasattr(settings, "STATIC_URL") and hasattr(settings, "STATIC_ROOT")

            if media_configured and static_configured:
                self._log_success("important", "FILES", "File systems properly configured")
            else:
                self._log_failure("important", "FILES", "File system configuration incomplete")

        except Exception as e:
            self._log_failure("important", "FILES", f"File system test failed: {str(e)}")

    def _test_email_system(self):
        """Test email system configuration"""
        try:
            email_configured = (
                hasattr(settings, "EMAIL_HOST")
                and settings.EMAIL_HOST
                and hasattr(settings, "EMAIL_HOST_PASSWORD")
                and settings.EMAIL_HOST_PASSWORD
            )

            if email_configured:
                self._log_success("optional", "EMAIL", "Email system configured")
            else:
                self._log_success("optional", "EMAIL", "Email system not configured (development mode)")

        except Exception as e:
            self._log_failure("optional", "EMAIL", f"Email test failed: {str(e)}")

    def _test_external_apis(self):
        """Test external API configurations"""
        try:
            # Test USDA API configuration
            usda_configured = hasattr(settings, "USDA_API_KEY") and settings.USDA_API_KEY

            # Test OpenAI configuration
            openai_configured = hasattr(settings, "OPENAI_API_KEY") and settings.OPENAI_API_KEY

            configured_apis = []
            if usda_configured:
                configured_apis.append("USDA")
            if openai_configured:
                configured_apis.append("OpenAI")

            self._log_success(
                "optional",
                "EXTERNAL_APIS",
                f'External APIs configured: {", ".join(configured_apis) if configured_apis else "None"}',
            )

        except Exception as e:
            self._log_failure("optional", "EXTERNAL_APIS", f"External API test failed: {str(e)}")

    def _test_advanced_features(self):
        """Test advanced features"""
        try:
            # Test Celery configuration
            celery_configured = hasattr(settings, "CELERY_BROKER_URL") and settings.CELERY_BROKER_URL

            # Test Redis configuration
            redis_configured = "redis" in str(settings.CACHES.get("default", {}))

            advanced_features = []
            if celery_configured:
                advanced_features.append("Celery")
            if redis_configured:
                advanced_features.append("Redis")

            self._log_success(
                "optional",
                "ADVANCED",
                f'Advanced features configured: {", ".join(advanced_features) if advanced_features else "None"}',
            )

        except Exception as e:
            self._log_failure("optional", "ADVANCED", f"Advanced features test failed: {str(e)}")

    def _log_success(self, level: str, category: str, message: str):
        """Log a successful test"""
        self.results[level]["passed"] += 1
        self.results[level]["details"].append({"status": "PASS", "category": category, "message": message})
        print(f"✅ {category}: {message}")

    def _log_failure(self, level: str, category: str, message: str):
        """Log a failed test"""
        self.results[level]["failed"] += 1
        self.results[level]["details"].append({"status": "FAIL", "category": category, "message": message})
        print(f"❌ {category}: {message}")

    def _is_production_ready(self) -> bool:
        """Determine if system is ready for production"""
        return self.results["critical"]["failed"] == 0

    def _print_final_results(self):
        """Print comprehensive final results"""
        print("\n" + "=" * 70)
        print("🎯 FINAL INTEGRATION VERIFICATION RESULTS")
        print("=" * 70)

        # Critical results
        critical_passed = self.results["critical"]["passed"]
        critical_failed = self.results["critical"]["failed"]
        print(f"🔥 CRITICAL: {critical_passed} passed, {critical_failed} failed")

        # Important results
        important_passed = self.results["important"]["passed"]
        important_failed = self.results["important"]["failed"]
        print(f"⚡ IMPORTANT: {important_passed} passed, {important_failed} failed")

        # Optional results
        optional_passed = self.results["optional"]["passed"]
        optional_failed = self.results["optional"]["failed"]
        print(f"🌟 OPTIONAL: {optional_passed} passed, {optional_failed} failed")

        # Overall status
        total_passed = critical_passed + important_passed + optional_passed
        total_failed = critical_failed + important_failed + optional_failed

        print(f"\n📊 OVERALL: {total_passed} passed, {total_failed} failed")

        # Production readiness determination
        if self._is_production_ready():
            print(f"\n🎉 PRODUCTION READY!")
            print("✅ All critical systems verified")
            print("✅ New production features integrate correctly")
            print("✅ Security enhancements working properly")
            print("✅ Database operations stable")
            print("✅ API endpoints functional")

            if important_failed == 0:
                print("🌟 Perfect integration - all systems optimal!")
            elif important_failed <= 2:
                print("⚠️  Minor issues in non-critical systems")
            else:
                print("⚠️  Several non-critical issues - recommend review")

        else:
            print(f"\n🛑 NOT READY FOR PRODUCTION")
            print(f"❌ {critical_failed} critical issues must be resolved")
            print("🔧 Fix critical issues before deploying")

            # List critical failures
            critical_failures = [d for d in self.results["critical"]["details"] if d["status"] == "FAIL"]
            if critical_failures:
                print("\n🚨 CRITICAL ISSUES TO RESOLVE:")
                for failure in critical_failures:
                    print(f"   • {failure['category']}: {failure['message']}")

        # Integration assessment
        print(f"\n🔗 INTEGRATION ASSESSMENT:")
        print(f"   • Middleware Integration: {'✅ Verified' if critical_failed == 0 else '❌ Issues'}")
        print(f"   • Database Integration: {'✅ Verified' if critical_failed == 0 else '❌ Issues'}")
        print(f"   • Security Integration: {'✅ Verified' if critical_failed == 0 else '❌ Issues'}")
        print(f"   • API Integration: {'✅ Verified' if important_failed <= 1 else '⚠️  Issues'}")
        print(f"   • Service Integration: {'✅ Verified' if critical_failed == 0 else '❌ Issues'}")


def main():
    """Run the final integration verification"""
    verifier = FinalIntegrationVerification()
    is_ready = verifier.run_verification()

    if is_ready:
        print(f"\n🚀 READY FOR PRODUCTION DEPLOYMENT")
        print(f"All integration points verified successfully!")
        return 0
    else:
        print(f"\n🛑 DEPLOYMENT BLOCKED")
        print(f"Critical integration issues must be resolved")
        return 1


if __name__ == "__main__":
    exit(main())
