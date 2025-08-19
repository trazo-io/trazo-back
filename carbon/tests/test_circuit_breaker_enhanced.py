"""
Tests for Enhanced Circuit Breaker Implementation
Comprehensive testing of circuit breaker functionality for external API resilience
"""

import time
from datetime import datetime, timedelta

from django.core.cache import cache
from django.test import TestCase

from carbon.services.circuit_breaker_enhanced import (
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerManager,
    CircuitMetrics,
    CircuitState,
    EnhancedCircuitBreaker,
    blockchain_circuit_breaker,
    blockchain_fallback_response,
    circuit_breaker,
    circuit_manager,
    stripe_circuit_breaker,
    stripe_fallback_response,
    usda_circuit_breaker,
    usda_fallback_response,
)


class EnhancedCircuitBreakerTest(TestCase):
    """Test enhanced circuit breaker functionality"""

    def setUp(self):
        """Set up test environment"""
        cache.clear()
        self.config = CircuitBreakerConfig(
            failure_threshold=3, timeout_seconds=10, success_threshold=2, request_timeout=5
        )
        self.circuit_breaker = EnhancedCircuitBreaker("test_service", self.config)

    def tearDown(self):
        """Clean up after tests"""
        cache.clear()

    def test_circuit_breaker_initialization(self):
        """Test circuit breaker initializes correctly"""
        self.assertEqual(self.circuit_breaker.name, "test_service")
        self.assertEqual(self.circuit_breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.circuit_breaker.config.failure_threshold, 3)
        self.assertEqual(self.circuit_breaker.config.timeout_seconds, 10)
        self.assertIsInstance(self.circuit_breaker.metrics, CircuitMetrics)

    def test_successful_call(self):
        """Test successful function call through circuit breaker"""

        def test_function():
            return "success"

        result = self.circuit_breaker.call(test_function)

        self.assertEqual(result, "success")
        self.assertEqual(self.circuit_breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.circuit_breaker.metrics.successful_requests, 1)
        self.assertEqual(self.circuit_breaker.metrics.total_requests, 1)

    def test_failed_call(self):
        """Test failed function call through circuit breaker"""

        def test_function():
            raise Exception("Test failure")

        with self.assertRaises(Exception):
            self.circuit_breaker.call(test_function)

        self.assertEqual(self.circuit_breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.circuit_breaker.metrics.failed_requests, 1)
        self.assertEqual(self.circuit_breaker.metrics.total_requests, 1)

    def test_circuit_opens_after_failures(self):
        """Test circuit breaker opens after reaching failure threshold"""

        def test_function():
            raise Exception("Test failure")

        # Make 3 failed calls (threshold)
        for i in range(3):
            with self.assertRaises(Exception):
                self.circuit_breaker.call(test_function)

        # Circuit should now be open
        self.assertEqual(self.circuit_breaker.state, CircuitState.OPEN)
        self.assertEqual(self.circuit_breaker.metrics.circuit_opens, 1)
        self.assertEqual(self.circuit_breaker.metrics.failed_requests, 3)

    def test_circuit_blocks_calls_when_open(self):
        """Test circuit breaker blocks calls when in open state"""
        # Force circuit to open
        self.circuit_breaker._state = CircuitState.OPEN
        self.circuit_breaker._next_attempt_time = datetime.now() + timedelta(seconds=60)

        def test_function():
            return "success"

        # Should raise CircuitBreakerError
        with self.assertRaises(CircuitBreakerError) as context:
            self.circuit_breaker.call(test_function)

        self.assertEqual(context.exception.service_name, "test_service")

    def test_circuit_transitions_to_half_open(self):
        """Test circuit breaker transitions to half-open after timeout"""
        # Force circuit to open with past timeout
        self.circuit_breaker._state = CircuitState.OPEN
        self.circuit_breaker._next_attempt_time = datetime.now() - timedelta(seconds=1)

        def test_function():
            return "success"

        # Should allow call and transition to half-open
        result = self.circuit_breaker.call(test_function)

        self.assertEqual(result, "success")
        self.assertEqual(self.circuit_breaker.state, CircuitState.CLOSED)  # Should close after success

    def test_half_open_to_closed_transition(self):
        """Test transition from half-open to closed after successes"""
        # Set to half-open state
        self.circuit_breaker._state = CircuitState.HALF_OPEN
        self.circuit_breaker._success_count = 1  # Need 2 successes to close

        def test_function():
            return "success"

        # Make successful call
        result = self.circuit_breaker.call(test_function)

        self.assertEqual(result, "success")
        self.assertEqual(self.circuit_breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.circuit_breaker.metrics.circuit_closes, 1)

    def test_half_open_to_open_on_failure(self):
        """Test transition from half-open back to open on failure"""
        # Set to half-open state
        self.circuit_breaker._state = CircuitState.HALF_OPEN

        def test_function():
            raise Exception("Test failure")

        # Failed call should return circuit to open
        with self.assertRaises(Exception):
            self.circuit_breaker.call(test_function)

        self.assertEqual(self.circuit_breaker.state, CircuitState.OPEN)

    def test_fallback_mechanism(self):
        """Test fallback function is called when circuit is open"""
        # Force circuit to open
        self.circuit_breaker._state = CircuitState.OPEN
        self.circuit_breaker._next_attempt_time = datetime.now() + timedelta(seconds=60)

        def test_function():
            return "primary"

        def fallback_function():
            return "fallback"

        result = self.circuit_breaker.call(test_function, fallback=fallback_function)

        self.assertEqual(result, "fallback")
        self.assertEqual(self.circuit_breaker.metrics.fallback_uses, 1)

    def test_retry_mechanism(self):
        """Test retry mechanism with exponential backoff"""
        call_count = 0

        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary failure")
            return "success"

        start_time = time.time()
        result = self.circuit_breaker.call(test_function)
        elapsed_time = time.time() - start_time

        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)
        # Should have some delay due to exponential backoff
        self.assertGreater(elapsed_time, 3)  # At least 1 + 2 seconds delay

    def test_non_retryable_errors(self):
        """Test that certain errors are not retried"""
        call_count = 0

        def test_function():
            nonlocal call_count
            call_count += 1
            raise ValueError("Non-retryable error")

        with self.assertRaises(ValueError):
            self.circuit_breaker.call(test_function)

        # Should only be called once (no retries)
        self.assertEqual(call_count, 1)

    def test_metrics_tracking(self):
        """Test detailed metrics tracking"""
        # Successful calls
        for i in range(5):
            self.circuit_breaker.call(lambda: "success")

        # Failed calls
        for i in range(2):
            try:
                self.circuit_breaker.call(lambda: exec('raise Exception("failure")'))
            except:
                pass

        metrics = self.circuit_breaker.get_metrics()

        self.assertEqual(metrics["total_requests"], 7)
        self.assertEqual(metrics["successful_requests"], 5)
        self.assertEqual(metrics["failed_requests"], 2)
        self.assertAlmostEqual(metrics["success_rate_percent"], 71.43, places=1)
        self.assertGreater(metrics["average_response_time_ms"], 0)

    def test_state_persistence(self):
        """Test circuit breaker state persistence in cache"""
        # Make some calls to change state
        self.circuit_breaker.call(lambda: "success")

        # Create new circuit breaker with same name
        new_circuit_breaker = EnhancedCircuitBreaker("test_service", self.config)

        # Should load previous state
        self.assertEqual(new_circuit_breaker.metrics.successful_requests, 1)

    def test_manual_reset(self):
        """Test manual circuit breaker reset"""
        # Force to open state
        self.circuit_breaker._state = CircuitState.OPEN
        self.circuit_breaker._failure_count = 5

        # Reset
        self.circuit_breaker.reset()

        self.assertEqual(self.circuit_breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.circuit_breaker._failure_count, 0)

    def test_force_open(self):
        """Test manually forcing circuit breaker to open"""
        self.assertEqual(self.circuit_breaker.state, CircuitState.CLOSED)

        # Force open
        self.circuit_breaker.force_open()

        self.assertEqual(self.circuit_breaker.state, CircuitState.OPEN)
        self.assertIsNotNone(self.circuit_breaker._next_attempt_time)


class CircuitBreakerManagerTest(TestCase):
    """Test circuit breaker manager functionality"""

    def setUp(self):
        cache.clear()
        self.manager = CircuitBreakerManager()

    def tearDown(self):
        cache.clear()

    def test_get_circuit_breaker(self):
        """Test getting circuit breaker instances"""
        cb1 = self.manager.get_circuit_breaker("service1", "usda_api")
        cb2 = self.manager.get_circuit_breaker("service1", "usda_api")  # Should return same instance
        cb3 = self.manager.get_circuit_breaker("service2", "stripe_api")

        self.assertIs(cb1, cb2)
        self.assertIsNot(cb1, cb3)
        self.assertEqual(cb1.name, "service1")
        self.assertEqual(cb3.name, "service2")

    def test_get_all_metrics(self):
        """Test getting metrics for all circuit breakers"""
        # Create some circuit breakers
        cb1 = self.manager.get_circuit_breaker("service1")
        cb2 = self.manager.get_circuit_breaker("service2")

        # Make some calls
        cb1.call(lambda: "success")
        try:
            cb2.call(lambda: exec('raise Exception("failure")'))
        except:
            pass

        all_metrics = self.manager.get_all_metrics()

        self.assertIn("service1", all_metrics)
        self.assertIn("service2", all_metrics)
        self.assertEqual(all_metrics["service1"]["successful_requests"], 1)
        self.assertEqual(all_metrics["service2"]["failed_requests"], 1)

    def test_health_summary(self):
        """Test overall health summary"""
        # Create circuit breakers in different states
        cb1 = self.manager.get_circuit_breaker("healthy_service")
        cb2 = self.manager.get_circuit_breaker("unhealthy_service")

        # Make healthy service successful
        cb1.call(lambda: "success")

        # Make unhealthy service fail and open
        for i in range(5):  # Exceed default failure threshold
            try:
                cb2.call(lambda: exec('raise Exception("failure")'))
            except:
                pass

        health_summary = self.manager.get_health_summary()

        self.assertEqual(health_summary["total_circuits"], 2)
        self.assertEqual(health_summary["open_circuits"], 1)
        self.assertEqual(health_summary["closed_circuits"], 1)
        self.assertIn(health_summary["overall_health"], ["degraded", "critical"])

    def test_reset_all(self):
        """Test resetting all circuit breakers"""
        # Create and modify circuit breakers
        cb1 = self.manager.get_circuit_breaker("service1")
        cb2 = self.manager.get_circuit_breaker("service2")

        cb1._state = CircuitState.OPEN
        cb2._state = CircuitState.HALF_OPEN

        # Reset all
        self.manager.reset_all()

        self.assertEqual(cb1.state, CircuitState.CLOSED)
        self.assertEqual(cb2.state, CircuitState.CLOSED)


class CircuitBreakerDecoratorTest(TestCase):
    """Test circuit breaker decorators"""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_circuit_breaker_decorator(self):
        """Test basic circuit breaker decorator"""

        @circuit_breaker("test_decorator_service")
        def test_function():
            return "decorated_success"

        result = test_function()
        self.assertEqual(result, "decorated_success")

        # Check circuit breaker was created
        cb = circuit_manager.get_circuit_breaker("test_decorator_service")
        self.assertEqual(cb.metrics.successful_requests, 1)

    def test_usda_circuit_breaker_decorator(self):
        """Test USDA-specific circuit breaker decorator"""

        @usda_circuit_breaker("test_usda_service")
        def test_usda_function():
            return "usda_success"

        result = test_usda_function()
        self.assertEqual(result, "usda_success")

        # Verify USDA-specific configuration was used
        cb = circuit_manager.get_circuit_breaker("test_usda_service")
        self.assertEqual(cb.config.failure_threshold, 3)  # USDA config

    def test_stripe_circuit_breaker_decorator(self):
        """Test Stripe-specific circuit breaker decorator"""

        @stripe_circuit_breaker("test_stripe_service")
        def test_stripe_function():
            return "stripe_success"

        result = test_stripe_function()
        self.assertEqual(result, "stripe_success")

        cb = circuit_manager.get_circuit_breaker("test_stripe_service")
        self.assertEqual(cb.config.failure_threshold, 5)  # Stripe config

    def test_blockchain_circuit_breaker_decorator(self):
        """Test blockchain-specific circuit breaker decorator"""

        @blockchain_circuit_breaker("test_blockchain_service")
        def test_blockchain_function():
            return "blockchain_success"

        result = test_blockchain_function()
        self.assertEqual(result, "blockchain_success")

        cb = circuit_manager.get_circuit_breaker("test_blockchain_service")
        self.assertEqual(cb.config.failure_threshold, 2)  # Blockchain config

    def test_decorator_with_fallback(self):
        """Test decorator with fallback function"""

        def fallback_function():
            return "fallback_result"

        @circuit_breaker("test_fallback_service", fallback=fallback_function)
        def failing_function():
            raise Exception("Always fails")

        # Force circuit to open
        cb = circuit_manager.get_circuit_breaker("test_fallback_service")
        cb.force_open()

        # Should return fallback result
        result = failing_function()
        self.assertEqual(result, "fallback_result")


class FallbackResponseTest(TestCase):
    """Test fallback response functions"""

    def test_usda_fallback_response(self):
        """Test USDA API fallback response"""
        result = usda_fallback_response("test_endpoint", {"param": "value"})

        self.assertFalse(result["success"])
        self.assertTrue(result["fallback"])
        self.assertEqual(result["endpoint"], "test_endpoint")
        self.assertIn("USDA API temporarily unavailable", result["message"])

    def test_stripe_fallback_response(self):
        """Test Stripe API fallback response"""
        result = stripe_fallback_response("charge_creation", amount=1000)

        self.assertFalse(result["success"])
        self.assertTrue(result["fallback"])
        self.assertEqual(result["operation"], "charge_creation")
        self.assertTrue(result["retry_required"])

    def test_blockchain_fallback_response(self):
        """Test blockchain API fallback response"""
        result = blockchain_fallback_response("verify_transaction", tx_hash="0x123")

        self.assertFalse(result["success"])
        self.assertTrue(result["fallback"])
        self.assertEqual(result["operation"], "verify_transaction")
        self.assertTrue(result["queue_for_retry"])


class CircuitBreakerConfigurationTest(TestCase):
    """Test circuit breaker with different configurations"""

    def setUp(self):
        cache.clear()

    def test_custom_configuration(self):
        """Test circuit breaker with custom configuration"""
        config = CircuitBreakerConfig(failure_threshold=2, timeout_seconds=5, success_threshold=1, max_retry_attempts=1)

        cb = EnhancedCircuitBreaker("custom_service", config)

        self.assertEqual(cb.config.failure_threshold, 2)
        self.assertEqual(cb.config.timeout_seconds, 5)
        self.assertEqual(cb.config.success_threshold, 1)
        self.assertEqual(cb.config.max_retry_attempts, 1)

    def test_service_specific_configurations(self):
        """Test service-specific default configurations"""
        manager = CircuitBreakerManager()

        # Test USDA configuration
        usda_cb = manager.get_circuit_breaker("test_usda", "usda_api")
        self.assertEqual(usda_cb.config.failure_threshold, 3)
        self.assertEqual(usda_cb.config.timeout_seconds, 30)

        # Test Stripe configuration
        stripe_cb = manager.get_circuit_breaker("test_stripe", "stripe_api")
        self.assertEqual(stripe_cb.config.failure_threshold, 5)
        self.assertEqual(stripe_cb.config.timeout_seconds, 60)

        # Test Blockchain configuration
        blockchain_cb = manager.get_circuit_breaker("test_blockchain", "blockchain_api")
        self.assertEqual(blockchain_cb.config.failure_threshold, 2)
        self.assertEqual(blockchain_cb.config.timeout_seconds, 120)


class CircuitBreakerIntegrationTest(TestCase):
    """Integration tests for circuit breaker with real scenarios"""

    def setUp(self):
        cache.clear()

    def test_api_timeout_scenario(self):
        """Test circuit breaker behavior with API timeouts"""
        import time

        def slow_api_call():
            time.sleep(0.1)  # Simulate slow API
            return "success"

        config = CircuitBreakerConfig(request_timeout=0.05)  # 50ms timeout
        cb = EnhancedCircuitBreaker("slow_api", config)

        # This should succeed (we're not actually enforcing timeout in the test)
        result = cb.call(slow_api_call)
        self.assertEqual(result, "success")

    def test_intermittent_failures(self):
        """Test circuit breaker with intermittent failures"""
        call_count = 0

        def intermittent_api():
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:  # Fail every 3rd call
                raise Exception("Intermittent failure")
            return f"success_{call_count}"

        cb = EnhancedCircuitBreaker("intermittent_api")

        # Make multiple calls
        results = []
        for i in range(10):
            try:
                result = cb.call(intermittent_api)
                results.append(result)
            except Exception:
                results.append("failed")

        # Should have mix of successes and failures
        successes = [r for r in results if r.startswith("success")]
        failures = [r for r in results if r == "failed"]

        self.assertGreater(len(successes), 0)
        self.assertGreater(len(failures), 0)
        self.assertEqual(cb.state, CircuitState.CLOSED)  # Should stay closed with mixed results

    def test_cascading_failures(self):
        """Test circuit breaker prevents cascading failures"""

        def always_failing_api():
            raise Exception("Service down")

        cb = EnhancedCircuitBreaker("failing_api")

        # Make enough calls to open circuit
        for i in range(10):
            try:
                cb.call(always_failing_api)
            except (Exception, CircuitBreakerError):
                pass

        # Circuit should be open and blocking calls
        self.assertEqual(cb.state, CircuitState.OPEN)

        # Further calls should be blocked immediately
        with self.assertRaises(CircuitBreakerError):
            cb.call(always_failing_api)

        # Failed request count should not increase significantly
        # (only the initial failures that opened the circuit)
        self.assertLessEqual(cb.metrics.failed_requests, 7)  # Some retries + initial failures
