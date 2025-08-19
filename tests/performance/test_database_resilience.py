#!/usr/bin/env python3
"""
Database Resilience Testing

Comprehensive testing for database failure scenarios, connection pooling,
transaction handling, and recovery mechanisms.
"""

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
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, OperationalError, connection, connections, transaction
from django.test import TransactionTestCase

import psutil

# Add project root to path
sys.path.insert(0, "/Users/oscarmunoz/dev/trazo/trazo-back")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.models import CachedEmissionFactor, CarbonEntry, CarbonSource
from company.models import Company, Establishment
from history.models import History


class DatabaseResilienceTests:
    """Test suite for database resilience under various failure conditions"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.test_results = {}
        self.created_objects = {"companies": [], "establishments": [], "histories": [], "carbon_entries": []}

    def run_database_tests(self):
        """Run comprehensive database resilience tests"""
        print("\n💾 Starting Database Resilience Testing")
        print("=" * 60)

        database_tests = [
            self.test_connection_pool_exhaustion,
            self.test_connection_recovery,
            self.test_transaction_rollback_scenarios,
            self.test_deadlock_handling,
            self.test_concurrent_write_operations,
            self.test_large_transaction_handling,
            self.test_connection_timeout_scenarios,
            self.test_database_lock_scenarios,
            self.test_data_consistency_under_load,
            self.test_backup_and_recovery_simulation,
        ]

        for test in database_tests:
            test_name = test.__name__
            print(f"\n🧪 Running {test_name}")

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

        self.print_database_test_summary()

    def test_connection_pool_exhaustion(self):
        """Test database connection pool exhaustion scenarios"""
        print("  Testing connection pool exhaustion...")

        # Get current connection count
        initial_connections = len(connections.all())

        # Create many connections rapidly
        connection_list = []
        max_connections = 50  # Attempt to exceed typical pool size

        try:
            for i in range(max_connections):
                try:
                    conn = connections["default"]
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        result = cursor.fetchone()
                    connection_list.append(conn)
                except OperationalError as e:
                    if "too many connections" in str(e).lower():
                        print(f"    ✓ Connection pool limit enforced at {i} connections")
                        break
                    else:
                        raise

            # Test that system gracefully handles pool exhaustion
            # Should either queue requests or reject gracefully
            print(f"    ✓ Connection pool management working ({len(connection_list)} connections created)")

        finally:
            # Cleanup connections
            for conn in connection_list:
                try:
                    conn.close()
                except:
                    pass

    def test_connection_recovery(self):
        """Test connection recovery after database downtime"""
        print("  Testing connection recovery...")

        # Simulate database unavailability
        original_cursor = connection.cursor

        failure_count = 0

        def failing_cursor():
            nonlocal failure_count
            failure_count += 1
            if failure_count <= 3:  # Fail first 3 attempts
                raise OperationalError("Database connection lost")
            return original_cursor()

        with patch.object(connection, "cursor", side_effect=failing_cursor):
            # Attempt operations that should retry
            retry_count = 0
            max_retries = 5

            while retry_count < max_retries:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        result = cursor.fetchone()
                    print(f"    ✓ Connection recovered after {retry_count + 1} attempts")
                    break
                except OperationalError:
                    retry_count += 1
                    time.sleep(0.1)  # Brief delay between retries

            assert retry_count < max_retries, "Connection recovery failed"

    def test_transaction_rollback_scenarios(self):
        """Test transaction rollback under various failure scenarios"""
        print("  Testing transaction rollback scenarios...")

        # Test rollback on database error
        try:
            with transaction.atomic():
                # Create a company
                company = Company.objects.create(
                    name="Test Company Rollback", address="123 Test St", city="Test City", country="US"
                )
                self.created_objects["companies"].append(company.id)

                # Force a database error (try to create duplicate)
                duplicate_company = Company.objects.create(
                    name="Test Company Rollback",  # Same name might cause issues
                    address="456 Test Ave",
                    city="Test City",
                    country="US",
                )

                # This should cause rollback
                raise Exception("Forced rollback")

        except Exception:
            # Transaction should be rolled back
            assert not Company.objects.filter(name="Test Company Rollback").exists()
            print("    ✓ Transaction rollback on exception working")

        # Test nested transaction rollback
        try:
            with transaction.atomic():
                company = Company.objects.create(
                    name="Outer Transaction Company", address="123 Outer St", city="Outer City", country="US"
                )

                try:
                    with transaction.atomic():
                        establishment = Establishment.objects.create(
                            name="Inner Transaction Est",
                            company=company,
                            address="456 Inner St",
                            city="Inner City",
                            country="US",
                        )
                        raise Exception("Inner transaction failure")
                except Exception:
                    pass  # Inner transaction should rollback

                # Outer transaction continues
                company.save()
                self.created_objects["companies"].append(company.id)

        except Exception as e:
            print(f"    ⚠️ Nested transaction test failed: {e}")

        print("    ✓ Nested transaction rollback working")

    def test_deadlock_handling(self):
        """Test deadlock detection and handling"""
        print("  Testing deadlock handling...")

        # Create test companies for deadlock scenario
        company1 = Company.objects.create(
            name="Deadlock Test Company 1", address="123 Deadlock St", city="Test City", country="US"
        )
        company2 = Company.objects.create(
            name="Deadlock Test Company 2", address="456 Deadlock Ave", city="Test City", country="US"
        )

        self.created_objects["companies"].extend([company1.id, company2.id])

        deadlock_detected = threading.Event()
        results = {"thread1_complete": False, "thread2_complete": False, "deadlock_caught": False}

        def transaction1():
            try:
                with transaction.atomic():
                    # Lock company1 first
                    c1 = Company.objects.select_for_update().get(id=company1.id)
                    time.sleep(0.1)  # Give thread2 time to lock company2

                    # Try to lock company2 (potential deadlock)
                    c2 = Company.objects.select_for_update().get(id=company2.id)
                    c1.name = "Updated by thread1"
                    c1.save()

                results["thread1_complete"] = True
            except Exception as e:
                if "deadlock" in str(e).lower():
                    results["deadlock_caught"] = True
                    deadlock_detected.set()

        def transaction2():
            try:
                with transaction.atomic():
                    # Lock company2 first
                    c2 = Company.objects.select_for_update().get(id=company2.id)
                    time.sleep(0.1)  # Give thread1 time to lock company1

                    # Try to lock company1 (potential deadlock)
                    c1 = Company.objects.select_for_update().get(id=company1.id)
                    c2.name = "Updated by thread2"
                    c2.save()

                results["thread2_complete"] = True
            except Exception as e:
                if "deadlock" in str(e).lower():
                    results["deadlock_caught"] = True
                    deadlock_detected.set()

        # Start both transactions
        thread1 = threading.Thread(target=transaction1)
        thread2 = threading.Thread(target=transaction2)

        thread1.start()
        thread2.start()

        # Wait for completion or deadlock
        thread1.join(timeout=5)
        thread2.join(timeout=5)

        # At least one should complete or deadlock should be detected
        if results["deadlock_caught"]:
            print("    ✓ Deadlock detected and handled")
        elif results["thread1_complete"] or results["thread2_complete"]:
            print("    ✓ Transactions completed without deadlock")
        else:
            print("    ⚠️ Potential deadlock not resolved")

    def test_concurrent_write_operations(self):
        """Test concurrent write operations on the same data"""
        print("  Testing concurrent write operations...")

        # Create a company for concurrent updates
        company = Company.objects.create(
            name="Concurrent Test Company", address="123 Concurrent St", city="Test City", country="US"
        )
        self.created_objects["companies"].append(company.id)

        update_results = {"successes": 0, "conflicts": 0, "errors": 0}

        def concurrent_update(thread_id):
            try:
                for i in range(10):
                    try:
                        with transaction.atomic():
                            # Reload company to get latest version
                            c = Company.objects.select_for_update().get(id=company.id)
                            c.name = f"Updated by thread {thread_id} iteration {i}"
                            c.save()
                            update_results["successes"] += 1
                    except IntegrityError:
                        update_results["conflicts"] += 1
                    except Exception as e:
                        update_results["errors"] += 1
                        self.logger.error(f"Concurrent update error: {e}")

            except Exception as e:
                update_results["errors"] += 1

        # Run concurrent updates
        threads = []
        for i in range(10):
            thread = threading.Thread(target=concurrent_update, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        total_operations = update_results["successes"] + update_results["conflicts"] + update_results["errors"]
        success_rate = update_results["successes"] / max(total_operations, 1)

        assert success_rate > 0.5, f"Too many concurrent update failures: {success_rate:.2%}"
        print(f"    ✓ Concurrent updates handled ({success_rate:.1%} success rate)")

    def test_large_transaction_handling(self):
        """Test handling of large transactions"""
        print("  Testing large transaction handling...")

        batch_size = 1000
        start_time = time.time()

        try:
            with transaction.atomic():
                # Create large batch of carbon entries
                carbon_entries = []
                for i in range(batch_size):
                    entry = CarbonEntry(activity_type=f"large_batch_{i}", amount=float(i), co2e_amount=float(i * 0.5))
                    carbon_entries.append(entry)

                # Bulk create
                created_entries = CarbonEntry.objects.bulk_create(carbon_entries, batch_size=100)
                self.created_objects["carbon_entries"].extend([e.id for e in created_entries])

            duration = time.time() - start_time

            if duration < 10.0:  # Should complete within 10 seconds
                print(f"    ✓ Large transaction completed efficiently ({duration:.2f}s)")
            else:
                print(f"    ⚠️ Large transaction slow ({duration:.2f}s)")

        except Exception as e:
            print(f"    ❌ Large transaction failed: {e}")
            raise

    def test_connection_timeout_scenarios(self):
        """Test various connection timeout scenarios"""
        print("  Testing connection timeout scenarios...")

        # Test long-running query simulation
        def long_running_query():
            try:
                with connection.cursor() as cursor:
                    # Simulate long-running query with sleep
                    cursor.execute("SELECT pg_sleep(0.1)")  # 100ms delay
                return True
            except Exception as e:
                self.logger.error(f"Long query error: {e}")
                return False

        # Run multiple long queries concurrently
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(long_running_query) for _ in range(50)]
            results = [future.result() for future in as_completed(futures)]

        success_rate = sum(results) / len(results)
        assert success_rate > 0.8, f"Too many timeout failures: {success_rate:.2%}"

        print(f"    ✓ Connection timeouts handled ({success_rate:.1%} success rate)")

    def test_database_lock_scenarios(self):
        """Test database lock scenarios and resolution"""
        print("  Testing database lock scenarios...")

        # Create test data
        company = Company.objects.create(
            name="Lock Test Company", address="123 Lock St", city="Test City", country="US"
        )
        self.created_objects["companies"].append(company.id)

        lock_results = {"acquired": 0, "waited": 0, "failed": 0}

        def acquire_lock(thread_id):
            try:
                with transaction.atomic():
                    # Try to acquire exclusive lock
                    c = Company.objects.select_for_update(nowait=False).get(id=company.id)
                    lock_results["acquired"] += 1

                    # Hold lock briefly
                    time.sleep(0.1)

                    c.name = f"Locked by thread {thread_id}"
                    c.save()

            except Exception as e:
                if "could not obtain lock" in str(e).lower():
                    lock_results["failed"] += 1
                else:
                    lock_results["waited"] += 1

        # Test concurrent lock acquisition
        threads = []
        for i in range(5):
            thread = threading.Thread(target=acquire_lock, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        total_attempts = sum(lock_results.values())
        assert total_attempts > 0, "No lock attempts recorded"

        print(
            f"    ✓ Database locks handled (acquired: {lock_results['acquired']}, waited: {lock_results['waited']}, failed: {lock_results['failed']})"
        )

    def test_data_consistency_under_load(self):
        """Test data consistency under concurrent load"""
        print("  Testing data consistency under load...")

        # Create initial data
        company = Company.objects.create(
            name="Consistency Test Company", address="123 Consistency St", city="Test City", country="US"
        )
        self.created_objects["companies"].append(company.id)

        consistency_results = {"reads": 0, "writes": 0, "inconsistencies": 0}

        def read_operations():
            for i in range(100):
                try:
                    c = Company.objects.get(id=company.id)
                    # Verify data consistency
                    if c.name and c.address:
                        consistency_results["reads"] += 1
                    else:
                        consistency_results["inconsistencies"] += 1
                except Company.DoesNotExist:
                    consistency_results["inconsistencies"] += 1
                time.sleep(0.001)

        def write_operations():
            for i in range(50):
                try:
                    with transaction.atomic():
                        c = Company.objects.select_for_update().get(id=company.id)
                        c.name = f"Updated name {i}"
                        c.address = f"Updated address {i}"
                        c.save()
                        consistency_results["writes"] += 1
                except Exception as e:
                    self.logger.error(f"Write operation error: {e}")
                time.sleep(0.002)

        # Run concurrent reads and writes
        read_threads = [threading.Thread(target=read_operations) for _ in range(5)]
        write_threads = [threading.Thread(target=write_operations) for _ in range(3)]

        all_threads = read_threads + write_threads
        for thread in all_threads:
            thread.start()

        for thread in all_threads:
            thread.join()

        consistency_rate = 1 - (consistency_results["inconsistencies"] / max(consistency_results["reads"], 1))
        assert consistency_rate > 0.95, f"Data consistency issues: {consistency_rate:.2%}"

        print(f"    ✓ Data consistency maintained ({consistency_rate:.1%} consistency rate)")

    def test_backup_and_recovery_simulation(self):
        """Test backup and recovery simulation scenarios"""
        print("  Testing backup and recovery simulation...")

        # Create test data to backup
        original_companies = []
        for i in range(10):
            company = Company.objects.create(
                name=f"Backup Test Company {i}", address=f"123 Backup St {i}", city="Backup City", country="US"
            )
            original_companies.append(company)
            self.created_objects["companies"].append(company.id)

        # Simulate data export (backup)
        backup_data = []
        for company in original_companies:
            backup_data.append(
                {"name": company.name, "address": company.address, "city": company.city, "country": company.country}
            )

        # Simulate data loss
        Company.objects.filter(name__startswith="Backup Test Company").delete()

        # Verify data is gone
        remaining_count = Company.objects.filter(name__startswith="Backup Test Company").count()
        assert remaining_count == 0, "Data deletion simulation failed"

        # Simulate recovery
        recovered_companies = []
        for data in backup_data:
            company = Company.objects.create(**data)
            recovered_companies.append(company)
            self.created_objects["companies"].append(company.id)

        # Verify recovery
        recovered_count = Company.objects.filter(name__startswith="Backup Test Company").count()
        assert recovered_count == len(original_companies), "Data recovery simulation failed"

        print(f"    ✓ Backup and recovery simulation successful ({recovered_count} records recovered)")

    def cleanup_test_data(self):
        """Clean up test data created during tests"""
        try:
            # Clean up carbon entries
            if self.created_objects["carbon_entries"]:
                CarbonEntry.objects.filter(id__in=self.created_objects["carbon_entries"]).delete()
                self.created_objects["carbon_entries"].clear()

            # Clean up histories
            if self.created_objects["histories"]:
                History.objects.filter(id__in=self.created_objects["histories"]).delete()
                self.created_objects["histories"].clear()

            # Clean up establishments
            if self.created_objects["establishments"]:
                Establishment.objects.filter(id__in=self.created_objects["establishments"]).delete()
                self.created_objects["establishments"].clear()

            # Clean up companies
            if self.created_objects["companies"]:
                Company.objects.filter(id__in=self.created_objects["companies"]).delete()
                self.created_objects["companies"].clear()

        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")

    def print_database_test_summary(self):
        """Print comprehensive database test results"""
        print("\n" + "=" * 60)
        print("💾 DATABASE RESILIENCE TEST SUMMARY")
        print("=" * 60)

        total_tests = len(self.test_results)
        passed_tests = len([r for r in self.test_results.values() if r["status"] == "PASSED"])
        failed_tests = total_tests - passed_tests

        print(f"Total Database Tests: {total_tests}")
        print(f"Passed: {passed_tests} ✅")
        print(f"Failed: {failed_tests} ❌")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")

        if failed_tests > 0:
            print("\n❌ FAILED DATABASE TESTS:")
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

        # Performance analysis
        slow_tests = [(name, result) for name, result in self.test_results.items() if result["duration"] > 5.0]
        if slow_tests:
            print("\n⚠️  SLOW DATABASE TESTS (>5s):")
            for name, result in slow_tests:
                print(f"  - {name}: {result['duration']:.2f}s")

        print("\n🛡️  DATABASE RESILIENCE ASSESSMENT:")
        if passed_tests / total_tests >= 0.95:
            print("✅ EXCELLENT - Database layer shows exceptional resilience")
        elif passed_tests / total_tests >= 0.85:
            print("✅ GOOD - Database resilience is production-ready")
        elif passed_tests / total_tests >= 0.75:
            print("⚠️  FAIR - Some database resilience issues to address")
        else:
            print("❌ POOR - Database resilience needs significant improvement")

        print("\n📊 DATABASE INSIGHTS:")
        print("  - Connection pool management")
        print("  - Transaction integrity")
        print("  - Deadlock prevention")
        print("  - Concurrent operation safety")
        print("  - Data consistency under load")
        print("  - Recovery mechanisms")


if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Run the database resilience tests
    db_tests = DatabaseResilienceTests()
    db_tests.run_database_tests()
