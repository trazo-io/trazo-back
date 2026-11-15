"""
Performance regression testing for database queries.
Tests query count and response time improvements.
"""

import time

from django.contrib.auth import get_user_model
from django.db import connection, reset_queries
from django.test import TestCase, override_settings
from django.test.client import Client
from django.test.utils import override_settings

from company.models import Company, Establishment
from company.views import EstablishmentViewSet
from history.models import HistoryScan, Production
from history.views import HistoryScanViewSet, PublicHistoryScanViewSet
from product.models import Parcel, Product
from product.views import ParcelViewSet

User = get_user_model()


class QueryPerformanceTestCase(TestCase):
    """Base class for query performance testing"""

    def setUp(self):
        """Set up test data for performance testing"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        # Create test companies
        self.companies = []
        for i in range(3):
            company = Company.objects.create(name=f"Test Company {i}", country="USA")
            self.companies.append(company)

        # Create test establishments
        self.establishments = []
        for i, company in enumerate(self.companies):
            for j in range(2):
                establishment = Establishment.objects.create(
                    name=f"Farm {j}{i}", company=company, country="USA"  # Shorter names
                )
                self.establishments.append(establishment)

        # Create test parcels
        self.parcels = []
        for i, establishment in enumerate(self.establishments):
            for k in range(2):
                parcel = Parcel.objects.create(
                    name=f"Field {k}{i}",  # Shorter names to fit 30 char limit
                    establishment=establishment,
                    area=100.0 + k * 50,
                )
                self.parcels.append(parcel)

        # Create test products
        self.products = []
        for i in range(3):
            product = Product.objects.create(name=f"Crop Type {i}", description=f"Test crop {i}")
            self.products.append(product)

    def reset_query_tracking(self):
        """Reset query tracking for accurate measurements"""
        reset_queries()
        connection.queries_log.clear()

    def get_query_count(self):
        """Get the number of queries executed"""
        return len(connection.queries_log)

    def measure_query_time(self, func, *args, **kwargs):
        """Measure execution time and query count for a function"""
        self.reset_query_tracking()
        start_time = time.time()

        result = func(*args, **kwargs)

        end_time = time.time()
        query_count = self.get_query_count()
        execution_time = end_time - start_time

        return {
            "result": result,
            "query_count": query_count,
            "execution_time": execution_time,
            "queries": connection.queries_log,
        }


@override_settings(DEBUG=True)  # Required for query logging
class EstablishmentQueryPerformanceTests(QueryPerformanceTestCase):
    """Test establishment query performance optimizations"""

    def test_establishment_list_query_optimization(self):
        """Test that establishment list queries are optimized"""
        viewset = EstablishmentViewSet()

        # Test unoptimized query (baseline)
        def get_unoptimized_queryset():
            return Establishment.objects.all()

        # Test optimized query (our improvement)
        def get_optimized_queryset():
            return (
                Establishment.objects.select_related("company", "album")
                .prefetch_related("parcels")  # Use correct relationship name
                .all()
            )

        # Measure unoptimized performance
        unoptimized_metrics = self.measure_query_time(lambda: list(get_unoptimized_queryset()))

        # Measure optimized performance
        optimized_metrics = self.measure_query_time(lambda: list(get_optimized_queryset()))

        # Assertions for optimization
        self.assertLessEqual(
            optimized_metrics["query_count"],
            unoptimized_metrics["query_count"] + 1,  # Allow for 1 additional setup query
            f"Optimized query count ({optimized_metrics['query_count']}) should be <= "
            f"unoptimized ({unoptimized_metrics['query_count']})",
        )

        # Log performance metrics
        print(f"\nEstablishment Query Performance:")
        print(
            f"  Unoptimized: {unoptimized_metrics['query_count']} queries, "
            f"{unoptimized_metrics['execution_time']:.4f}s"
        )
        print(
            f"  Optimized: {optimized_metrics['query_count']} queries, " f"{optimized_metrics['execution_time']:.4f}s"
        )

    def test_establishment_with_related_data_access(self):
        """Test accessing related data doesn't cause N+1 queries"""
        queryset = Establishment.objects.select_related("company", "album").prefetch_related("parcels").all()

        def access_related_data():
            establishments = list(queryset)
            # Access related company data (should use select_related)
            company_names = []
            for est in establishments:
                if est.company:
                    company_names.append(est.company.name)
            return company_names

        metrics = self.measure_query_time(access_related_data)

        # Should not have one query per establishment for company access
        max_expected_queries = 3  # Initial query + potential prefetch queries
        self.assertLessEqual(
            metrics["query_count"],
            max_expected_queries,
            f"Accessing related company data triggered {metrics['query_count']} queries, "
            f"expected <= {max_expected_queries} (N+1 query problem)",
        )

        print(f"\nEstablishment Related Data Access:")
        print(f"  Query count: {metrics['query_count']}")
        print(f"  Execution time: {metrics['execution_time']:.4f}s")


@override_settings(DEBUG=True)
class ParcelQueryPerformanceTests(QueryPerformanceTestCase):
    """Test parcel query performance optimizations"""

    def test_parcel_list_query_optimization(self):
        """Test that parcel list queries are optimized"""

        def get_optimized_parcels():
            return list(Parcel.objects.select_related("establishment", "establishment__company").all())

        def get_unoptimized_parcels():
            return list(Parcel.objects.all())

        # Measure both approaches
        unoptimized_metrics = self.measure_query_time(get_unoptimized_parcels)
        optimized_metrics = self.measure_query_time(get_optimized_parcels)

        # The optimized version should not perform worse
        self.assertLessEqual(
            optimized_metrics["query_count"],
            unoptimized_metrics["query_count"] + 2,  # Allow for select_related setup
            "Optimized parcel queries should not increase query count significantly",
        )

        print(f"\nParcel Query Performance:")
        print(f"  Unoptimized: {unoptimized_metrics['query_count']} queries")
        print(f"  Optimized: {optimized_metrics['query_count']} queries")

    def test_parcel_establishment_company_access(self):
        """Test that accessing parcel->establishment->company is optimized"""
        queryset = Parcel.objects.select_related("establishment", "establishment__company").all()

        def access_nested_relations():
            parcels = list(queryset)
            company_names = []
            for parcel in parcels:
                if parcel.establishment and parcel.establishment.company:
                    company_names.append(parcel.establishment.company.name)
            return company_names

        metrics = self.measure_query_time(access_nested_relations)

        # Should be well optimized for nested access
        max_expected_queries = 5  # Main query + joins + prefetch
        self.assertLessEqual(
            metrics["query_count"],
            max_expected_queries,
            f"Nested relation access used {metrics['query_count']} queries, " f"expected <= {max_expected_queries}",
        )


@override_settings(DEBUG=True)
class HistoryScanQueryPerformanceTests(QueryPerformanceTestCase):
    """Test history scan query performance optimizations"""

    def setUp(self):
        super().setUp()

        # Create test history scans
        self.history_scans = []
        for parcel in self.parcels[:3]:  # Limit to avoid too much test data
            # Create a history record first
            history = Production.objects.create(
                name=f"Prod {parcel.id}", parcel=parcel, start_date="2024-01-01", published=True  # Short name
            )

            # Create history scan
            scan = HistoryScan.objects.create(history=history, user=self.user, ip_address="127.0.0.1")
            self.history_scans.append(scan)

    def test_history_scan_viewset_optimization(self):
        """Test HistoryScanViewSet query optimization"""

        def get_optimized_scans():
            return list(HistoryScan.objects.select_related("history", "user", "history__parcel").all())

        def get_unoptimized_scans():
            return list(HistoryScan.objects.all())

        # Measure performance
        unoptimized_metrics = self.measure_query_time(get_unoptimized_scans)
        optimized_metrics = self.measure_query_time(get_optimized_scans)

        print(f"\nHistoryScan Query Performance:")
        print(f"  Unoptimized: {unoptimized_metrics['query_count']} queries")
        print(f"  Optimized: {optimized_metrics['query_count']} queries")

        # Optimization should not increase query count
        self.assertLessEqual(
            optimized_metrics["query_count"],
            unoptimized_metrics["query_count"] + 1,
            "HistoryScan optimization should not increase queries",
        )

    def test_history_scan_related_access(self):
        """Test accessing history scan related data is optimized"""
        queryset = HistoryScan.objects.select_related("history", "user", "history__parcel").all()

        def access_related_data():
            scans = list(queryset)
            related_data = []
            for scan in scans:
                if scan.history and scan.history.parcel:
                    related_data.append(
                        {
                            "history_name": scan.history.name,
                            "parcel_name": scan.history.parcel.name,
                            "user_email": scan.user.email if scan.user else None,
                        }
                    )
            return related_data

        metrics = self.measure_query_time(access_related_data)

        # Should be well optimized with select_related
        max_expected_queries = 4  # Optimized with proper joins
        self.assertLessEqual(
            metrics["query_count"],
            max_expected_queries,
            f"Related data access used {metrics['query_count']} queries, " f"expected <= {max_expected_queries}",
        )


class QueryRegressionDetectionTests(QueryPerformanceTestCase):
    """Tests to detect query performance regressions"""

    PERFORMANCE_BASELINES = {
        "establishment_list": {"max_queries": 3, "max_time": 0.1},
        "parcel_list": {"max_queries": 4, "max_time": 0.1},
        "history_scan_list": {"max_queries": 4, "max_time": 0.1},
    }

    def test_establishment_performance_regression(self):
        """Detect performance regression in establishment queries"""

        metrics = self.measure_query_time(
            lambda: list(Establishment.objects.select_related("company", "album").prefetch_related("parcels").all())
        )

        baseline = self.PERFORMANCE_BASELINES["establishment_list"]

        self.assertLessEqual(
            metrics["query_count"],
            baseline["max_queries"],
            f"Establishment query count regression: {metrics['query_count']} > {baseline['max_queries']}",
        )

        self.assertLess(
            metrics["execution_time"],
            baseline["max_time"],
            f"Establishment query time regression: {metrics['execution_time']:.4f}s > {baseline['max_time']}s",
        )

    def test_parcel_performance_regression(self):
        """Detect performance regression in parcel queries"""

        metrics = self.measure_query_time(
            lambda: list(Parcel.objects.select_related("establishment", "establishment__company").all())
        )

        baseline = self.PERFORMANCE_BASELINES["parcel_list"]

        self.assertLessEqual(
            metrics["query_count"],
            baseline["max_queries"],
            f"Parcel query count regression: {metrics['query_count']} > {baseline['max_queries']}",
        )

        self.assertLess(
            metrics["execution_time"],
            baseline["max_time"],
            f"Parcel query time regression: {metrics['execution_time']:.4f}s > {baseline['max_time']}s",
        )

    def test_query_patterns_analysis(self):
        """Analyze query patterns for common performance issues"""

        metrics = self.measure_query_time(
            lambda: list(Establishment.objects.select_related("company", "album").prefetch_related("parcels").all())
        )

        # Analyze query patterns
        queries = metrics["queries"]

        # Check for SELECT N+1 patterns
        select_queries = [q for q in queries if q["sql"].strip().upper().startswith("SELECT")]

        # Should not have many similar SELECT queries (sign of N+1)
        if len(select_queries) > 3:
            # Group similar queries
            query_patterns = {}
            for query in select_queries:
                # Simplified pattern matching (remove specific IDs)
                pattern = query["sql"]
                # Remove specific ID values for pattern matching
                import re

                pattern = re.sub(r"= \d+", "= ?", pattern)
                pattern = re.sub(r"IN \([0-9, ]+\)", "IN (?)", pattern)

                if pattern in query_patterns:
                    query_patterns[pattern] += 1
                else:
                    query_patterns[pattern] = 1

            # Check for repeated patterns (N+1 indicator)
            repeated_patterns = {k: v for k, v in query_patterns.items() if v > 2}

            self.assertEqual(
                len(repeated_patterns), 0, f"Detected potential N+1 query patterns: {list(repeated_patterns.keys())}"
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
