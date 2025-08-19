"""
Tests for API Key Rotation Service
Comprehensive testing of automated API key rotation functionality
"""

from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from carbon.services.api_key_rotation import (
    APIKeyRotationService,
    KeyValidationError,
    check_rotation_status,
    emergency_rotate_all_keys,
    rotate_usda_keys,
)


class APIKeyRotationServiceTest(TestCase):
    """Test API key rotation service functionality"""

    def setUp(self):
        """Set up test environment"""
        cache.clear()
        self.service = APIKeyRotationService()

        # Mock API keys for testing
        self.test_keys = {
            "usda_nass": "test_nass_key_12345",
            "usda_ers": "test_ers_key_67890",
            "usda_fooddata": "test_fooddata_key_abcdef",
            "stripe": "sk_test_12345abcdef",
        }

    def tearDown(self):
        """Clean up after tests"""
        cache.clear()

    def test_service_initialization(self):
        """Test service initializes with correct configuration"""
        self.assertEqual(self.service.rotation_interval_days, 90)
        self.assertEqual(self.service.validation_timeout, 30)
        self.assertEqual(self.service.max_retry_attempts, 3)

        # Check service configurations are loaded
        self.assertIn("usda_nass", self.service.service_configs)
        self.assertIn("usda_ers", self.service.service_configs)
        self.assertIn("usda_fooddata", self.service.service_configs)
        self.assertIn("stripe", self.service.service_configs)

        # Verify critical services are marked as such
        for service_name, config in self.service.service_configs.items():
            self.assertTrue(config["critical"])

    def test_check_rotation_needed_no_history(self):
        """Test rotation check when no rotation history exists"""
        result = self.service.check_rotation_needed("usda_nass")
        self.assertTrue(result)

    def test_check_rotation_needed_recent_rotation(self):
        """Test rotation check with recent rotation"""
        # Set recent rotation timestamp
        cache.set("api_key_last_rotation_usda_nass", timezone.now().isoformat(), 86400)

        result = self.service.check_rotation_needed("usda_nass")
        self.assertFalse(result)

    def test_check_rotation_needed_old_rotation(self):
        """Test rotation check with old rotation"""
        # Set old rotation timestamp (100 days ago)
        old_date = timezone.now() - timedelta(days=100)
        cache.set("api_key_last_rotation_usda_nass", old_date.isoformat(), 86400)

        result = self.service.check_rotation_needed("usda_nass")
        self.assertTrue(result)

    def test_check_rotation_needed_invalid_service(self):
        """Test rotation check with invalid service name"""
        result = self.service.check_rotation_needed("invalid_service")
        self.assertFalse(result)

    @patch("carbon.services.api_key_rotation.requests.get")
    def test_validate_usda_nass_key_success(self, mock_get):
        """Test successful USDA NASS API key validation"""
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"some": "data"}]}
        mock_get.return_value = mock_response

        result = self.service.validate_api_key("usda_nass", self.test_keys["usda_nass"])
        self.assertTrue(result)

        # Verify correct API call was made
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertIn("quickstats.nass.usda.gov", call_args[0][0])
        self.assertEqual(call_args[1]["params"]["key"], self.test_keys["usda_nass"])

    @patch("carbon.services.api_key_rotation.requests.get")
    def test_validate_usda_nass_key_failure(self, mock_get):
        """Test failed USDA NASS API key validation"""
        # Mock failed API response
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        result = self.service.validate_api_key("usda_nass", "invalid_key")
        self.assertFalse(result)

    @patch("carbon.services.api_key_rotation.requests.get")
    def test_validate_fooddata_key_success(self, mock_get):
        """Test successful FoodData Central API key validation"""
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"foods": [{"description": "corn"}]}
        mock_get.return_value = mock_response

        result = self.service.validate_api_key("usda_fooddata", self.test_keys["usda_fooddata"])
        self.assertTrue(result)

        # Verify correct API call was made
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertIn("api.nal.usda.gov", call_args[0][0])
        self.assertEqual(call_args[1]["params"]["api_key"], self.test_keys["usda_fooddata"])

    @patch("carbon.services.api_key_rotation.stripe")
    def test_validate_stripe_key_success(self, mock_stripe):
        """Test successful Stripe API key validation"""
        # Mock successful Stripe API call
        mock_stripe.Account.retrieve.return_value = {"id": "test_account"}

        result = self.service.validate_api_key("stripe", self.test_keys["stripe"])
        self.assertTrue(result)

        # Verify Stripe API key was set and call was made
        self.assertEqual(mock_stripe.api_key, self.test_keys["stripe"])
        mock_stripe.Account.retrieve.assert_called_once()

    @patch("carbon.services.api_key_rotation.stripe")
    def test_validate_stripe_key_failure(self, mock_stripe):
        """Test failed Stripe API key validation"""
        # Mock failed Stripe API call
        mock_stripe.Account.retrieve.side_effect = Exception("Invalid API key")

        result = self.service.validate_api_key("stripe", "invalid_stripe_key")
        self.assertFalse(result)

    def test_validate_invalid_service(self):
        """Test validation with invalid service name"""
        with self.assertRaises(KeyValidationError):
            self.service.validate_api_key("invalid_service", "any_key")

    def test_generate_new_api_key_usda(self):
        """Test API key generation for USDA services (should return None)"""
        result = self.service.generate_new_api_key("usda_nass")
        self.assertIsNone(result)

        result = self.service.generate_new_api_key("usda_ers")
        self.assertIsNone(result)

        result = self.service.generate_new_api_key("usda_fooddata")
        self.assertIsNone(result)

    def test_generate_new_api_key_stripe(self):
        """Test API key generation for Stripe (should return None)"""
        result = self.service.generate_new_api_key("stripe")
        self.assertIsNone(result)

    @patch("carbon.services.api_key_rotation.secrets_manager")
    @patch.object(APIKeyRotationService, "validate_api_key")
    @patch.object(APIKeyRotationService, "_test_key_in_context")
    def test_rotate_api_key_success(self, mock_test_context, mock_validate, mock_secrets):
        """Test successful API key rotation"""
        # Setup mocks
        mock_secrets.get_secret.return_value = "old_key"
        mock_secrets.store_secret.return_value = True
        mock_validate.return_value = True
        mock_test_context.return_value = True

        new_key = "new_test_key_12345"
        result = self.service.rotate_api_key("usda_nass", new_key)

        self.assertTrue(result)

        # Verify validation was called
        mock_validate.assert_called_with("usda_nass", new_key)

        # Verify context test was called
        mock_test_context.assert_called_with("usda_nass", new_key)

        # Verify backup and new key storage
        self.assertEqual(mock_secrets.store_secret.call_count, 2)  # Backup + new key

        # Verify rotation timestamp was set
        rotation_key = "api_key_last_rotation_usda_nass"
        self.assertIsNotNone(cache.get(rotation_key))

    @patch("carbon.services.api_key_rotation.secrets_manager")
    @patch.object(APIKeyRotationService, "validate_api_key")
    def test_rotate_api_key_validation_failure(self, mock_validate, mock_secrets):
        """Test API key rotation with validation failure"""
        # Setup mocks
        mock_secrets.get_secret.return_value = "old_key"
        mock_validate.return_value = False

        new_key = "invalid_test_key"
        result = self.service.rotate_api_key("usda_nass", new_key)

        self.assertFalse(result)

        # Verify validation was called but storage was not
        mock_validate.assert_called_with("usda_nass", new_key)
        mock_secrets.store_secret.assert_not_called()

    @patch("carbon.services.api_key_rotation.secrets_manager")
    @patch.object(APIKeyRotationService, "validate_api_key")
    @patch.object(APIKeyRotationService, "_test_key_in_context")
    def test_rotate_api_key_context_test_failure(self, mock_test_context, mock_validate, mock_secrets):
        """Test API key rotation with context test failure"""
        # Setup mocks
        mock_secrets.get_secret.return_value = "old_key"
        mock_secrets.store_secret.return_value = True
        mock_validate.return_value = True
        mock_test_context.return_value = False

        new_key = "new_test_key_12345"
        result = self.service.rotate_api_key("usda_nass", new_key)

        self.assertFalse(result)

        # Verify rollback occurred (store_secret called twice: new key + rollback)
        self.assertEqual(mock_secrets.store_secret.call_count, 3)  # Backup + new key + rollback

    def test_rotate_api_key_invalid_service(self):
        """Test rotation with invalid service name"""
        result = self.service.rotate_api_key("invalid_service", "any_key")
        self.assertFalse(result)

    def test_rotate_api_key_no_new_key(self):
        """Test rotation without providing new key"""
        result = self.service.rotate_api_key("usda_nass")
        self.assertFalse(result)

    @patch("carbon.services.api_key_rotation.secrets_manager")
    def test_check_all_services(self, mock_secrets):
        """Test checking all services rotation status"""
        # Mock secrets manager responses
        mock_secrets.get_secret.side_effect = lambda name, required=True: {
            "usda_nass_api_key": "nass_key",
            "usda_ers_api_key": "ers_key",
            "usda_fooddata_api_key": "fooddata_key",
            "stripe_api_key": "stripe_key",
        }.get(name)

        # Set some rotation timestamps
        cache.set("api_key_last_rotation_usda_nass", timezone.now().isoformat(), 86400)
        old_date = timezone.now() - timedelta(days=100)
        cache.set("api_key_last_rotation_usda_ers", old_date.isoformat(), 86400)

        results = self.service.check_all_services()

        # Verify all services are checked
        self.assertEqual(len(results), 4)
        self.assertIn("usda_nass", results)
        self.assertIn("usda_ers", results)
        self.assertIn("usda_fooddata", results)
        self.assertIn("stripe", results)

        # Verify status information
        for service_name, status in results.items():
            self.assertIn("needs_rotation", status)
            self.assertIn("has_key", status)
            self.assertIn("critical", status)
            self.assertTrue(status["critical"])  # All our test services are critical

        # NASS should not need rotation (recent), ERS should need rotation (old)
        self.assertFalse(results["usda_nass"]["needs_rotation"])
        self.assertTrue(results["usda_ers"]["needs_rotation"])

    def test_emergency_rotate_all(self):
        """Test emergency rotation of all keys"""
        results = self.service.emergency_rotate_all()

        # All services should return False (manual key generation required)
        for service_name, success in results.items():
            self.assertFalse(success)

        # All configured services should be included
        self.assertEqual(len(results), 4)


class APIKeyRotationUtilityTest(TestCase):
    """Test utility functions for API key rotation"""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch("carbon.services.api_key_rotation.api_key_rotation_service")
    def test_rotate_usda_keys(self, mock_service):
        """Test USDA keys rotation utility function"""
        mock_service.rotate_api_key.return_value = True

        test_keys = {"nass_key": "new_nass_key", "ers_key": "new_ers_key", "fooddata_key": "new_fooddata_key"}

        results = rotate_usda_keys(**test_keys)

        # Verify all keys were rotated
        self.assertEqual(len(results), 3)
        self.assertTrue(all(results.values()))

        # Verify correct service calls
        mock_service.rotate_api_key.assert_any_call("usda_nass", test_keys["nass_key"])
        mock_service.rotate_api_key.assert_any_call("usda_ers", test_keys["ers_key"])
        mock_service.rotate_api_key.assert_any_call("usda_fooddata", test_keys["fooddata_key"])

    @patch("carbon.services.api_key_rotation.api_key_rotation_service")
    def test_check_rotation_status(self, mock_service):
        """Test rotation status check utility function"""
        mock_status = {
            "usda_nass": {"needs_rotation": False, "has_key": True},
            "usda_ers": {"needs_rotation": True, "has_key": True},
        }
        mock_service.check_all_services.return_value = mock_status

        result = check_rotation_status()

        self.assertEqual(result, mock_status)
        mock_service.check_all_services.assert_called_once()

    @patch("carbon.services.api_key_rotation.api_key_rotation_service")
    def test_emergency_rotate_all_keys(self, mock_service):
        """Test emergency rotation utility function"""
        mock_results = {"usda_nass": False, "stripe": False}
        mock_service.emergency_rotate_all.return_value = mock_results

        result = emergency_rotate_all_keys()

        self.assertEqual(result, mock_results)
        mock_service.emergency_rotate_all.assert_called_once()


class APIKeyRotationIntegrationTest(TestCase):
    """Integration tests for API key rotation with real components"""

    @patch("carbon.services.api_key_rotation.requests.get")
    @patch("carbon.services.api_key_rotation.secrets_manager")
    def test_full_rotation_workflow(self, mock_secrets, mock_requests):
        """Test complete key rotation workflow"""
        # Setup mocks for successful rotation
        mock_secrets.get_secret.return_value = "old_key"
        mock_secrets.store_secret.return_value = True

        # Mock successful API validation
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"test": "data"}]}
        mock_requests.return_value = mock_response

        service = APIKeyRotationService()
        new_key = "new_validated_key"

        # Perform rotation
        result = service.rotate_api_key("usda_nass", new_key)

        # Verify success
        self.assertTrue(result)

        # Verify API validation was called
        mock_requests.assert_called()

        # Verify secrets were stored (backup + new key)
        self.assertEqual(mock_secrets.store_secret.call_count, 2)

        # Verify rotation timestamp was recorded
        rotation_key = "api_key_last_rotation_usda_nass"
        self.assertIsNotNone(cache.get(rotation_key))

    def test_audit_logging(self):
        """Test that rotation operations are properly audited"""
        service = APIKeyRotationService()

        # Test audit log method
        service._audit_log_rotation("usda_nass", success=True)

        # Check audit log was created in cache
        audit_key = f"audit_key_rotation_{timezone.now().strftime('%Y%m%d')}"
        audit_logs = cache.get(audit_key, [])

        self.assertEqual(len(audit_logs), 1)
        self.assertEqual(audit_logs[0]["service"], "usda_nass")
        self.assertTrue(audit_logs[0]["success"])
        self.assertEqual(audit_logs[0]["event"], "api_key_rotation")


class APIKeyRotationCeleryTaskTest(TestCase):
    """Test Celery tasks for API key rotation"""

    def setUp(self):
        cache.clear()

    @patch("carbon.services.api_key_rotation.CELERY_AVAILABLE", True)
    def test_celery_tasks_available(self):
        """Test that Celery tasks are defined when Celery is available"""
        from carbon.tasks.key_rotation_tasks import (
            check_api_key_rotation_status,
            cleanup_old_key_backups,
            validate_all_api_keys,
        )

        # Verify tasks are callable
        self.assertTrue(callable(check_api_key_rotation_status))
        self.assertTrue(callable(validate_all_api_keys))
        self.assertTrue(callable(cleanup_old_key_backups))


@override_settings(API_KEY_ROTATION_DAYS=30, API_KEY_VALIDATION_TIMEOUT=15, API_KEY_ROTATION_RETRIES=2)
class APIKeyRotationConfigurationTest(TestCase):
    """Test API key rotation with different configurations"""

    def test_custom_configuration(self):
        """Test service respects custom configuration"""
        service = APIKeyRotationService()

        self.assertEqual(service.rotation_interval_days, 30)
        self.assertEqual(service.validation_timeout, 15)
        self.assertEqual(service.max_retry_attempts, 2)

    def test_rotation_threshold_configuration(self):
        """Test rotation needed calculation with custom threshold"""
        service = APIKeyRotationService()

        # Set rotation timestamp 31 days ago (should need rotation with 30-day threshold)
        old_date = timezone.now() - timedelta(days=31)
        cache.set("api_key_last_rotation_usda_nass", old_date.isoformat(), 86400)

        result = service.check_rotation_needed("usda_nass")
        self.assertTrue(result)

        # Set rotation timestamp 29 days ago (should not need rotation)
        recent_date = timezone.now() - timedelta(days=29)
        cache.set("api_key_last_rotation_usda_nass", recent_date.isoformat(), 86400)

        result = service.check_rotation_needed("usda_nass")
        self.assertFalse(result)
