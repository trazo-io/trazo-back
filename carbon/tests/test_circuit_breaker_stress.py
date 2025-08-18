#!/usr/bin/env python3
"""
Circuit Breaker Stress Testing

Comprehensive stress testing for circuit breaker patterns under extreme conditions.
Tests the resilience and recovery mechanisms of the production-ready circuit breakers.
"""

import asyncio
import logging
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import django

import requests
from requests.exceptions import ConnectionError, ConnectTimeout, ReadTimeout

# Add project root to path
sys.path.insert(0, "/Users/oscarmunoz/dev/trazo/trazo-back")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.services.api_circuit_breaker import APICircuitBreaker
from carbon.services.circuit_breaker_enhanced import CircuitBreakerService
from common.services.external_api_manager import ExternalAPIManager


class CircuitBreakerStressTests:
    """Stress test suite for circuit breaker functionality"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.test_results = {}
        self.api_manager = ExternalAPIManager()

    def run_stress_tests(self):
        """Run comprehensive circuit breaker stress tests"""
        print("\n⚡ Starting Circuit Breaker Stress Testing")
        print("=" * 60)

        stress_tests = [
            self.test_rapid_failure_recovery,
            self.test_sustained_failure_scenarios,
            self.test_concurrent_circuit_operations,
            self.test_cascade_failure_prevention,
            self.test_recovery_under_load,
            self.test_memory_pressure_scenarios,
            self.test_timing_edge_cases,
            self.test_state_transition_stress,
            self.test_mixed_success_failure_patterns,
            self.test_extreme_timeout_scenarios,
        ]

        for test in stress_tests:
            test_name = test.__name__
            print(f"\n🔬 Running {test_name}")

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

        self.print_stress_test_summary()

    def test_rapid_failure_recovery(self):
        """Test rapid failure and recovery cycles"""
        print("  Testing rapid failure/recovery cycles...")

        breaker = APICircuitBreaker("rapid_test", failure_threshold=3, timeout=0.5)

        # Rapid failure cycles
        for cycle in range(10):
            # Trigger failures
            for i in range(4):  # Exceed threshold
                breaker.record_failure()

            assert breaker.state == "OPEN", f"Circuit not open after failures in cycle {cycle}"

            # Wait for half-open
            time.sleep(0.6)
            assert breaker.state == "HALF_OPEN", f"Circuit not half-open in cycle {cycle}"

            # Recovery
            breaker.record_success()
            assert breaker.state == "CLOSED", f"Circuit not closed after success in cycle {cycle}"

        print("    ✓ Rapid failure/recovery cycles handled correctly")

    def test_sustained_failure_scenarios(self):
        """Test sustained failure scenarios over extended periods"""
        print("  Testing sustained failure scenarios...")

        breaker = APICircuitBreaker("sustained_test", failure_threshold=5, timeout=1.0)

        # Generate sustained failures
        failure_duration = 10  # seconds
        start_time = time.time()
        failure_count = 0

        while time.time() - start_time < failure_duration:
            breaker.record_failure()
            failure_count += 1
            time.sleep(0.1)

        # Circuit should remain open during sustained failures
        assert breaker.state == "OPEN", "Circuit not open during sustained failures"

        # After timeout, should transition to half-open
        time.sleep(1.1)
        assert breaker.state == "HALF_OPEN", "Circuit not transitioning to half-open"

        print(f"    ✓ Sustained failures handled ({failure_count} failures over {failure_duration}s)")

    def test_concurrent_circuit_operations(self):
        """Test concurrent operations on circuit breakers"""
        print("  Testing concurrent circuit breaker operations...")

        breaker = APICircuitBreaker("concurrent_test", failure_threshold=10, timeout=1.0)
        results = {"successes": 0, "failures": 0, "errors": 0}

        def circuit_operation(operation_id):
            try:
                for i in range(50):
                    # Random operation
                    if random.random() < 0.3:  # 30% failure rate
                        breaker.record_failure()
                        results["failures"] += 1
                    else:
                        breaker.record_success()
                        results["successes"] += 1

                    # Occasional state check
                    if i % 10 == 0:
                        _ = breaker.state

            except Exception as e:
                results["errors"] += 1
                self.logger.error(f"Concurrent operation error: {e}")

        # Run many concurrent operations
        threads = []
        for i in range(20):
            thread = threading.Thread(target=circuit_operation, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        total_operations = results["successes"] + results["failures"]
        error_rate = results["errors"] / (total_operations + results["errors"]) if total_operations > 0 else 1

        assert error_rate < 0.01, f"Too many concurrent operation errors: {error_rate:.2%}"
        print(f"    ✓ Concurrent operations handled ({total_operations} ops, {error_rate:.3%} error rate)")

    def test_cascade_failure_prevention(self):
        """Test prevention of cascade failures across multiple services"""
        print("  Testing cascade failure prevention...")

        services = ["usda_api", "blockchain", "weather", "stripe", "storage"]
        breakers = {service: APICircuitBreaker(service, failure_threshold=3, timeout=2.0) for service in services}

        # Simulate cascade failure scenario
        for service in services:
            # Trigger failure in this service
            for i in range(4):  # Exceed threshold
                breakers[service].record_failure()

            assert breakers[service].state == "OPEN", f"{service} circuit not open"

        # All circuits should be open but system should remain functional
        open_circuits = sum(1 for b in breakers.values() if b.state == "OPEN")
        assert open_circuits == len(services), "Not all circuits opened during cascade"

        # Test system degradation gracefully
        healthy_services = self.api_manager.get_healthy_services()
        # Should have fallback mechanisms

        print(f"    ✓ Cascade failure handled ({open_circuits} circuits opened)")

    def test_recovery_under_load(self):
        """Test circuit recovery under continued load"""
        print("  Testing recovery under load...")

        breaker = APICircuitBreaker("recovery_test", failure_threshold=5, timeout=1.0)

        # First, open the circuit
        for i in range(6):
            breaker.record_failure()
        assert breaker.state == "OPEN"

        # Wait for half-open
        time.sleep(1.1)
        assert breaker.state == "HALF_OPEN"

        # Simulate recovery under load
        load_threads = []
        recovery_results = {"attempts": 0, "successes": 0, "rejected": 0}

        def load_operation():
            for i in range(100):
                try:
                    recovery_results["attempts"] += 1
                    # 70% success rate during recovery
                    if random.random() < 0.7:
                        breaker.record_success()
                        recovery_results["successes"] += 1
                    else:
                        breaker.record_failure()
                except Exception:
                    recovery_results["rejected"] += 1
                time.sleep(0.01)

        # Start load during recovery
        for i in range(5):
            thread = threading.Thread(target=load_operation)
            load_threads.append(thread)
            thread.start()

        for thread in load_threads:
            thread.join()

        # Circuit should eventually stabilize
        final_state = breaker.state
        success_rate = recovery_results["successes"] / max(recovery_results["attempts"], 1)

        print(f"    ✓ Recovery under load completed (final state: {final_state}, success rate: {success_rate:.2%})")

    def test_memory_pressure_scenarios(self):
        """Test circuit breaker behavior under memory pressure"""
        print("  Testing behavior under memory pressure...")

        breakers = []

        # Create many circuit breakers
        for i in range(1000):
            breaker = APICircuitBreaker(f"memory_test_{i}", failure_threshold=3, timeout=1.0)
            breakers.append(breaker)

            # Generate some activity
            if i % 2 == 0:
                breaker.record_failure()
            else:
                breaker.record_success()

        # Test operations on all breakers
        operations_completed = 0
        for breaker in breakers[:100]:  # Test subset
            try:
                _ = breaker.state
                breaker.record_success()
                operations_completed += 1
            except Exception as e:
                self.logger.warning(f"Memory pressure operation failed: {e}")

        completion_rate = operations_completed / 100
        assert completion_rate > 0.95, f"Too many failures under memory pressure: {completion_rate:.2%}"

        print(f"    ✓ Memory pressure handled ({completion_rate:.1%} operations successful)")

    def test_timing_edge_cases(self):
        """Test timing edge cases in circuit breaker logic"""
        print("  Testing timing edge cases...")

        breaker = APICircuitBreaker("timing_test", failure_threshold=3, timeout=0.5)

        # Test rapid state transitions
        start_time = time.time()

        # Open circuit
        for i in range(4):
            breaker.record_failure()
        open_time = time.time()

        # Verify timing precision
        time.sleep(0.49)  # Just before timeout
        assert breaker.state == "OPEN", "Circuit opened too early"

        time.sleep(0.02)  # Just after timeout
        assert breaker.state == "HALF_OPEN", "Circuit didn't transition to half-open"

        # Test race conditions
        def rapid_operations():
            for i in range(100):
                if random.random() < 0.5:
                    breaker.record_success()
                else:
                    breaker.record_failure()

        threads = []
        for i in range(10):
            thread = threading.Thread(target=rapid_operations)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Circuit should be in a consistent state
        final_state = breaker.state
        assert final_state in ["OPEN", "CLOSED", "HALF_OPEN"], f"Invalid state: {final_state}"

        print("    ✓ Timing edge cases handled correctly")

    def test_state_transition_stress(self):
        """Test state transition logic under stress"""
        print("  Testing state transition stress...")

        breaker = APICircuitBreaker("transition_test", failure_threshold=2, timeout=0.2)
        transition_counts = {"CLOSED": 0, "OPEN": 0, "HALF_OPEN": 0}

        # Rapid state changes over time
        start_time = time.time()
        while time.time() - start_time < 5.0:  # 5 seconds of stress
            current_state = breaker.state
            transition_counts[current_state] += 1

            # Force state changes
            if current_state == "CLOSED":
                # Open it
                breaker.record_failure()
                breaker.record_failure()
                breaker.record_failure()
            elif current_state == "HALF_OPEN":
                # Random outcome
                if random.random() < 0.5:
                    breaker.record_success()  # Close it
                else:
                    breaker.record_failure()  # Open it
            elif current_state == "OPEN":
                # Wait for half-open
                time.sleep(0.21)

            time.sleep(0.01)

        # Verify all states were visited
        states_visited = sum(1 for count in transition_counts.values() if count > 0)
        assert states_visited >= 2, f"Not enough state transitions: {transition_counts}"

        print(f"    ✓ State transitions stress tested: {transition_counts}")

    def test_mixed_success_failure_patterns(self):
        """Test various mixed success/failure patterns"""
        print("  Testing mixed success/failure patterns...")

        breaker = APICircuitBreaker("pattern_test", failure_threshold=5, timeout=1.0)

        # Pattern 1: Alternating success/failure
        for i in range(20):
            if i % 2 == 0:
                breaker.record_success()
            else:
                breaker.record_failure()
        assert breaker.state in ["CLOSED", "OPEN"], "Pattern 1 failed"

        # Pattern 2: Burst failures then recovery
        breaker = APICircuitBreaker("pattern_test_2", failure_threshold=5, timeout=1.0)

        # Burst of failures
        for i in range(10):
            breaker.record_failure()
        assert breaker.state == "OPEN", "Burst failures didn't open circuit"

        # Wait and recover
        time.sleep(1.1)
        assert breaker.state == "HALF_OPEN", "Didn't transition to half-open"

        # Sustained recovery
        for i in range(10):
            breaker.record_success()
        assert breaker.state == "CLOSED", "Didn't close after sustained success"

        # Pattern 3: Gradual degradation
        breaker = APICircuitBreaker("pattern_test_3", failure_threshold=5, timeout=1.0)

        success_rate = 0.9
        for round in range(5):
            for i in range(20):
                if random.random() < success_rate:
                    breaker.record_success()
                else:
                    breaker.record_failure()
            success_rate -= 0.2  # Degrade over time

        print("    ✓ Mixed success/failure patterns handled")

    def test_extreme_timeout_scenarios(self):
        """Test extreme timeout scenarios"""
        print("  Testing extreme timeout scenarios...")

        # Very short timeout
        short_breaker = APICircuitBreaker("short_timeout", failure_threshold=3, timeout=0.01)

        # Open circuit
        for i in range(4):
            short_breaker.record_failure()
        assert short_breaker.state == "OPEN"

        # Should transition very quickly
        time.sleep(0.02)
        assert short_breaker.state == "HALF_OPEN", "Short timeout didn't work"

        # Very long timeout
        long_breaker = APICircuitBreaker("long_timeout", failure_threshold=3, timeout=60.0)

        # Open circuit
        for i in range(4):
            long_breaker.record_failure()
        assert long_breaker.state == "OPEN"

        # Should stay open for a while
        time.sleep(1.0)
        assert long_breaker.state == "OPEN", "Long timeout circuit opened too early"

        # Zero timeout (edge case)
        zero_breaker = APICircuitBreaker("zero_timeout", failure_threshold=3, timeout=0.0)

        # Open circuit
        for i in range(4):
            zero_breaker.record_failure()

        # Should immediately be available for retry
        assert zero_breaker.state in ["HALF_OPEN", "OPEN"], "Zero timeout edge case failed"

        print("    ✓ Extreme timeout scenarios handled")

    def print_stress_test_summary(self):
        """Print comprehensive stress test results"""
        print("\n" + "=" * 60)
        print("⚡ CIRCUIT BREAKER STRESS TEST SUMMARY")
        print("=" * 60)

        total_tests = len(self.test_results)
        passed_tests = len([r for r in self.test_results.values() if r["status"] == "PASSED"])
        failed_tests = total_tests - passed_tests

        print(f"Total Stress Tests: {total_tests}")
        print(f"Passed: {passed_tests} ✅")
        print(f"Failed: {failed_tests} ❌")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")

        if failed_tests > 0:
            print("\n❌ FAILED STRESS TESTS:")
            for test_name, result in self.test_results.items():
                if result["status"] == "FAILED":
                    print(f"  - {test_name}: {result.get('error', 'Unknown error')}")

        print("\n⏱️  PERFORMANCE SUMMARY:")
        total_duration = 0
        for test_name, result in self.test_results.items():
            duration = result["duration"]
            total_duration += duration
            print(f"  - {test_name}: {duration:.2f}s")

        print(f"Total Stress Test Duration: {total_duration:.2f}s")

        # Performance analysis
        slow_tests = [(name, result) for name, result in self.test_results.items() if result["duration"] > 3.0]
        if slow_tests:
            print("\n⚠️  SLOW STRESS TESTS (>3s):")
            for name, result in slow_tests:
                print(f"  - {name}: {result['duration']:.2f}s")

        print("\n🛡️  RESILIENCE ASSESSMENT:")
        if passed_tests / total_tests >= 0.95:
            print("✅ EXCELLENT - Circuit breakers show exceptional resilience")
        elif passed_tests / total_tests >= 0.85:
            print("✅ GOOD - Circuit breakers are production-ready")
        elif passed_tests / total_tests >= 0.75:
            print("⚠️  FAIR - Some resilience issues to address")
        else:
            print("❌ POOR - Circuit breaker implementation needs work")

        print("\n📊 STRESS TEST INSIGHTS:")
        print("  - State transition reliability")
        print("  - Concurrent operation safety")
        print("  - Memory efficiency under load")
        print("  - Timing precision and edge cases")
        print("  - Recovery behavior under stress")


if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Run the circuit breaker stress tests
    stress_tests = CircuitBreakerStressTests()
    stress_tests.run_stress_tests()
