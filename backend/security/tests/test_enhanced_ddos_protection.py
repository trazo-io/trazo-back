"""
Tests for Enhanced DDoS Protection and Rate Limiting
"""

import json
import time
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from backend.security.enhanced_ddos_protection import (
    AdvancedDDoSProtection,
    EnhancedRateLimitMiddleware,
    CircuitBreakerMiddleware,
)

User = get_user_model()


class AdvancedDDoSProtectionTests(TestCase):
    """Test Advanced DDoS Protection functionality"""

    def setUp(self):
        self.factory = RequestFactory()
        self.protection = AdvancedDDoSProtection()
        cache.clear()

    def test_get_client_ip_with_x_forwarded_for(self):
        """Test IP extraction with X-Forwarded-For header"""
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "192.168.1.100, 10.0.0.1"
        
        ip = self.protection.get_client_ip(request)
        self.assertEqual(ip, "192.168.1.100")

    def test_get_client_ip_direct_connection(self):
        """Test IP extraction for direct connections"""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "203.0.113.1"
        
        ip = self.protection.get_client_ip(request)
        self.assertEqual(ip, "203.0.113.1")

    def test_behavioral_pattern_analysis_clean_request(self):
        """Test behavioral analysis for clean requests"""
        request = self.factory.get("/api/carbon/")
        request.META["HTTP_USER_AGENT"] = "Mozilla/5.0 (legitimate browser)"
        request.META["REMOTE_ADDR"] = "203.0.113.1"
        
        threat_score, indicators = self.protection.analyze_behavioral_patterns(request)
        
        self.assertLess(threat_score, 30)
        self.assertEqual(len(indicators), 0)

    def test_behavioral_pattern_analysis_suspicious_user_agent(self):
        """Test detection of suspicious user agents"""
        request = self.factory.get("/api/carbon/")
        request.META["HTTP_USER_AGENT"] = "sqlmap/1.0"
        request.META["REMOTE_ADDR"] = "203.0.113.1"
        
        threat_score, indicators = self.protection.analyze_behavioral_patterns(request)
        
        self.assertGreater(threat_score, 10)
        self.assertTrue(any("suspicious_user_agent" in indicator for indicator in indicators))

    def test_behavioral_pattern_analysis_high_frequency(self):
        """Test detection of high frequency requests"""
        request = self.factory.get("/api/carbon/")
        request.META["HTTP_USER_AGENT"] = "Mozilla/5.0"
        request.META["REMOTE_ADDR"] = "203.0.113.1"
        
        # Simulate high frequency by pre-populating request history
        ip_hash = "203.0.113.1"
        history_key = f"ddos_advanced_history_{ip_hash}"
        now = time.time()
        
        # Create 150 requests in the last 5 minutes (high frequency)
        request_times = [now - i for i in range(150)]
        history = {
            "requests": request_times,
            "endpoints": {"/api/carbon/": 150},
            "user_agents": ["Mozilla/5.0"],
            "referrers": [""],
            "countries": ["US"],
            "first_seen": now - 300,
        }
        cache.set(history_key, history, 600)
        
        threat_score, indicators = self.protection.analyze_behavioral_patterns(request)
        
        self.assertGreater(threat_score, 25)
        self.assertTrue(any("high_request_rate" in indicator for indicator in indicators))

    def test_whitelist_functionality(self):
        """Test IP whitelisting"""
        # Test private IP range whitelisting
        self.assertTrue(self.protection.is_ip_whitelisted("192.168.1.1"))
        self.assertTrue(self.protection.is_ip_whitelisted("10.0.0.1"))
        self.assertTrue(self.protection.is_ip_whitelisted("172.16.0.1"))
        self.assertTrue(self.protection.is_ip_whitelisted("127.0.0.1"))
        
        # Test public IP not whitelisted
        self.assertFalse(self.protection.is_ip_whitelisted("203.0.113.1"))

    def test_blacklist_functionality(self):
        """Test IP blacklisting"""
        ip = "203.0.113.1"
        
        # IP should not be blacklisted initially
        self.assertFalse(self.protection.is_ip_blacklisted(ip))
        
        # Add to blacklist
        self.protection.add_to_blacklist(ip, 300, "Test blacklisting")
        
        # IP should now be blacklisted
        self.assertTrue(self.protection.is_ip_blacklisted(ip))

    def test_should_block_request_clean(self):
        """Test request blocking for clean requests"""
        request = self.factory.get("/api/carbon/")
        request.META["HTTP_USER_AGENT"] = "Mozilla/5.0"
        request.META["REMOTE_ADDR"] = "192.168.1.1"  # Whitelisted IP
        
        should_block, reason, threat_score = self.protection.should_block_request(request)
        
        self.assertFalse(should_block)
        self.assertEqual(reason, "whitelisted")
        self.assertEqual(threat_score, 0)

    def test_should_block_request_blacklisted(self):
        """Test request blocking for blacklisted IPs"""
        ip = "203.0.113.1"
        self.protection.add_to_blacklist(ip, 300, "Test")
        
        request = self.factory.get("/api/carbon/")
        request.META["REMOTE_ADDR"] = ip
        
        should_block, reason, threat_score = self.protection.should_block_request(request)
        
        self.assertTrue(should_block)
        self.assertEqual(reason, "blacklisted")
        self.assertEqual(threat_score, 100)


class EnhancedRateLimitMiddlewareTests(TestCase):
    """Test Enhanced Rate Limit Middleware"""

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = EnhancedRateLimitMiddleware(lambda request: Mock(status_code=200))
        cache.clear()

    def test_get_endpoint_category_auth(self):
        """Test endpoint categorization for auth endpoints"""
        category = self.middleware.get_endpoint_category("/api/auth/login/")
        self.assertEqual(category, "auth")
        
        category = self.middleware.get_endpoint_category("/signup/")
        self.assertEqual(category, "auth")

    def test_get_endpoint_category_carbon(self):
        """Test endpoint categorization for carbon endpoints"""
        category = self.middleware.get_endpoint_category("/api/carbon/calculate/")
        self.assertEqual(category, "carbon")

    def test_get_endpoint_category_consumer(self):
        """Test endpoint categorization for consumer endpoints"""
        category = self.middleware.get_endpoint_category("/qr/scan/")
        self.assertEqual(category, "consumer")

    def test_rate_limit_within_limits(self):
        """Test rate limiting when within limits"""
        request = self.factory.get("/api/carbon/")
        request.META["REMOTE_ADDR"] = "203.0.113.1"
        
        is_allowed, limit_info = self.middleware.check_rate_limit(request)
        
        self.assertTrue(is_allowed)
        self.assertGreater(limit_info["remaining"], 0)
        self.assertEqual(limit_info["category"], "carbon")

    def test_rate_limit_authenticated_user_higher_limits(self):
        """Test that authenticated users get higher rate limits"""
        user = User.objects.create_user(username="testuser", email="test@example.com")
        
        request = self.factory.get("/api/carbon/")
        request.META["REMOTE_ADDR"] = "203.0.113.1"
        request.user = user
        
        is_allowed, limit_info = self.middleware.check_rate_limit(request)
        
        self.assertTrue(is_allowed)
        # Should have higher limits than base (1.5x multiplier)
        base_limits = self.middleware.rate_limits["carbon"]["max_requests"]
        expected_limit = int(base_limits * 1.5)
        self.assertEqual(limit_info["limit"], expected_limit)

    def test_rate_limit_threat_score_adjustment(self):
        """Test rate limit adjustment based on threat score"""
        request = self.factory.get("/api/carbon/")
        request.META["REMOTE_ADDR"] = "203.0.113.1"
        
        # High threat score should reduce limits
        threat_score = 60
        is_allowed, limit_info = self.middleware.check_rate_limit(request, threat_score)
        
        self.assertTrue(is_allowed)
        # Limits should be reduced due to high threat score
        base_limit = self.middleware.rate_limits["carbon"]["max_requests"]
        self.assertLess(limit_info["limit"], base_limit)

    def test_process_request_allowed(self):
        """Test middleware process_request for allowed requests"""
        request = self.factory.get("/api/carbon/")
        request.META["REMOTE_ADDR"] = "192.168.1.1"  # Whitelisted
        request.META["HTTP_USER_AGENT"] = "Mozilla/5.0"
        
        response = self.middleware.process_request(request)
        
        self.assertIsNone(response)  # Should not block
        self.assertTrue(hasattr(request, "_rate_limit_info"))

    @patch('backend.security.enhanced_ddos_protection.logger')
    def test_process_request_blocked_ddos(self, mock_logger):
        """Test middleware process_request for DDoS blocked requests"""
        # Create a request that will trigger DDoS protection
        request = self.factory.get("/api/carbon/")
        request.META["REMOTE_ADDR"] = "203.0.113.1"
        request.META["HTTP_USER_AGENT"] = "sqlmap/1.0"  # Suspicious user agent
        
        # Mock the DDoS protection to return block decision
        with patch.object(self.middleware.ddos_protection, 'should_block_request') as mock_should_block:
            mock_should_block.return_value = (True, "high_threat_score_80", 80)
            
            response = self.middleware.process_request(request)
            
            self.assertIsNotNone(response)
            self.assertEqual(response.status_code, 429)
            mock_logger.warning.assert_called()

    def test_process_response_adds_headers(self):
        """Test that response processing adds rate limit headers"""
        request = self.factory.get("/api/carbon/")
        request.META["REMOTE_ADDR"] = "203.0.113.1"
        request._rate_limit_info = {
            "limit": 20,
            "remaining": 15,
            "reset": int(time.time()) + 60,
            "window": 60,
            "category": "carbon",
        }
        
        response = Mock()
        response.__setitem__ = Mock()
        
        result = self.middleware.process_response(request, response)
        
        # Verify headers were added
        response.__setitem__.assert_any_call("X-RateLimit-Limit", "20")
        response.__setitem__.assert_any_call("X-RateLimit-Remaining", "15")
        response.__setitem__.assert_any_call("X-RateLimit-Category", "carbon")


class CircuitBreakerMiddlewareTests(TestCase):
    """Test Circuit Breaker Middleware"""

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CircuitBreakerMiddleware(lambda request: Mock(status_code=200))
        cache.clear()

    def test_circuit_breaker_closed_state(self):
        """Test circuit breaker in closed state"""
        status = self.middleware.get_circuit_status()
        self.assertEqual(status["state"], "closed")
        self.assertEqual(status["failure_count"], 0)

    def test_record_success_resets_failures(self):
        """Test that successful requests reset failure count"""
        # Set some failures first
        status = self.middleware.get_circuit_status()
        status["failure_count"] = 10
        self.middleware.update_circuit_status(status)
        
        # Record success should reset if in half_open state
        status["state"] = "half_open"
        self.middleware.update_circuit_status(status)
        
        self.middleware.record_success()
        
        updated_status = self.middleware.get_circuit_status()
        self.assertEqual(updated_status["state"], "closed")
        self.assertEqual(updated_status["failure_count"], 0)

    def test_record_failure_trips_circuit(self):
        """Test that enough failures trip the circuit breaker"""
        # Record failures to trip the circuit
        for _ in range(self.middleware.failure_threshold):
            self.middleware.record_failure()
        
        status = self.middleware.get_circuit_status()
        self.assertEqual(status["state"], "open")
        self.assertIsNotNone(status["next_attempt_time"])

    def test_process_request_open_circuit(self):
        """Test request processing with open circuit"""
        # Trip the circuit breaker
        status = self.middleware.get_circuit_status()
        status.update({
            "state": "open",
            "failure_count": 60,
            "next_attempt_time": time.time() + 3600,  # 1 hour in future
        })
        self.middleware.update_circuit_status(status)
        
        request = self.factory.get("/api/carbon/")
        response = self.middleware.process_request(request)
        
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 503)

    def test_process_request_transition_to_half_open(self):
        """Test transition from open to half-open state"""
        # Set circuit to open with expired timeout
        status = self.middleware.get_circuit_status()
        status.update({
            "state": "open",
            "failure_count": 60,
            "next_attempt_time": time.time() - 1,  # Past time
        })
        self.middleware.update_circuit_status(status)
        
        request = self.factory.get("/api/carbon/")
        response = self.middleware.process_request(request)
        
        # Should transition to half-open and allow request
        self.assertIsNone(response)
        updated_status = self.middleware.get_circuit_status()
        self.assertEqual(updated_status["state"], "half_open")

    def test_process_response_records_failures(self):
        """Test that failed responses are recorded"""
        request = self.factory.get("/api/carbon/")
        response = Mock()
        response.status_code = 500
        
        initial_status = self.middleware.get_circuit_status()
        initial_failures = initial_status["failure_count"]
        
        self.middleware.process_response(request, response)
        
        updated_status = self.middleware.get_circuit_status()
        self.assertEqual(updated_status["failure_count"], initial_failures + 1)

    def test_process_response_records_success(self):
        """Test that successful responses are recorded"""
        # Set to half-open state first
        status = self.middleware.get_circuit_status()
        status["state"] = "half_open"
        self.middleware.update_circuit_status(status)
        
        request = self.factory.get("/api/carbon/")
        response = Mock()
        response.status_code = 200
        
        self.middleware.process_response(request, response)
        
        updated_status = self.middleware.get_circuit_status()
        self.assertEqual(updated_status["state"], "closed")


class SecurityIntegrationTests(TestCase):
    """Integration tests for security components"""

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def test_full_middleware_stack_normal_request(self):
        """Test normal request through full middleware stack"""
        # Create middleware instances
        circuit_breaker = CircuitBreakerMiddleware(lambda req: Mock(status_code=200))
        rate_limiter = EnhancedRateLimitMiddleware(lambda req: Mock(status_code=200))
        
        request = self.factory.get("/api/carbon/")
        request.META["REMOTE_ADDR"] = "192.168.1.1"  # Whitelisted
        request.META["HTTP_USER_AGENT"] = "Mozilla/5.0"
        
        # Process through middleware stack
        cb_response = circuit_breaker.process_request(request)
        self.assertIsNone(cb_response)
        
        rl_response = rate_limiter.process_request(request)
        self.assertIsNone(rl_response)
        
        # Both should allow the request
        self.assertTrue(hasattr(request, "_rate_limit_info"))

    def test_full_middleware_stack_blocked_request(self):
        """Test blocked request through full middleware stack"""
        circuit_breaker = CircuitBreakerMiddleware(lambda req: Mock(status_code=200))
        rate_limiter = EnhancedRateLimitMiddleware(lambda req: Mock(status_code=200))
        
        request = self.factory.get("/api/carbon/")
        request.META["REMOTE_ADDR"] = "203.0.113.1"
        request.META["HTTP_USER_AGENT"] = "sqlmap/1.0"  # Suspicious
        
        # Circuit breaker should pass
        cb_response = circuit_breaker.process_request(request)
        self.assertIsNone(cb_response)
        
        # Rate limiter should block due to suspicious user agent
        with patch.object(rate_limiter.ddos_protection, 'should_block_request') as mock_should_block:
            mock_should_block.return_value = (True, "high_threat_score_80", 80)
            
            rl_response = rate_limiter.process_request(request)
            self.assertIsNotNone(rl_response)
            self.assertEqual(rl_response.status_code, 429)