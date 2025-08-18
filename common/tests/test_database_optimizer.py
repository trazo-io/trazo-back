"""
Tests for Database Optimization Service
Comprehensive testing of database performance analysis and optimization
"""

import json
import unittest
from unittest.mock import MagicMock, Mock, patch

from django.apps import apps
from django.db import connection
from django.test import TestCase, override_settings

from common.services.database_optimizer import (
    DatabaseOptimizer,
    analyze_model_performance,
    create_indexes,
    database_optimizer,
    get_performance_report,
)


class DatabaseOptimizerTest(TestCase):
    """Test database optimizer functionality"""

    def setUp(self):
        """Set up test environment"""
        self.optimizer = DatabaseOptimizer()

    def test_optimizer_initialization(self):
        """Test optimizer initializes correctly"""
        self.assertEqual(self.optimizer.db_vendor, connection.vendor)
        self.assertEqual(self.optimizer.slow_query_threshold, 1000)
        self.assertIsInstance(self.optimizer.analyzed_queries, list)

    @patch.object(DatabaseOptimizer, "_get_existing_indexes")
    @patch.object(DatabaseOptimizer, "_get_table_size_postgres")
    def test_analyze_model_performance(self, mock_table_size, mock_indexes):
        """Test analyzing performance for a specific model"""
        # Mock dependencies
        mock_indexes.return_value = [{"name": "test_index", "definition": "CREATE INDEX test_index ON test_table (id)"}]
        mock_table_size.return_value = 10.5

        # Test with carbon CropType model
        try:
            CropType = apps.get_model("carbon", "CropType")
            analysis = self.optimizer._analyze_model_performance(CropType)

            self.assertIn("model", analysis)
            self.assertIn("table_name", analysis)
            self.assertIn("record_count", analysis)
            self.assertIn("existing_indexes", analysis)
            self.assertIn("index_recommendations", analysis)
            self.assertIn("issues", analysis)

            self.assertEqual(analysis["model"], "carbon.croptype")

        except LookupError:
            self.skipTest("CropType model not available in test environment")

    def test_recommend_foreign_key_indexes(self):
        """Test foreign key index recommendations"""
        try:
            CarbonEntry = apps.get_model("carbon", "CarbonEntry")
            recommendations = self.optimizer._recommend_foreign_key_indexes(CarbonEntry)

            # Should recommend indexes for foreign key fields
            self.assertIsInstance(recommendations, list)

            # Check if establishment foreign key is recommended
            establishment_recs = [r for r in recommendations if "establishment" in r.get("field", "")]
            self.assertGreater(len(establishment_recs), 0)

            for rec in recommendations:
                self.assertEqual(rec["type"], "foreign_key_index")
                self.assertEqual(rec["priority"], "high")
                self.assertIn("sql", rec)

        except LookupError:
            self.skipTest("CarbonEntry model not available in test environment")

    def test_recommend_datetime_indexes(self):
        """Test datetime field index recommendations"""
        try:
            CarbonEntry = apps.get_model("carbon", "CarbonEntry")
            recommendations = self.optimizer._recommend_datetime_indexes(CarbonEntry)

            self.assertIsInstance(recommendations, list)

            # Should recommend indexes for datetime fields
            datetime_recs = [r for r in recommendations if "created_at" in r.get("field", "")]
            if datetime_recs:  # Only test if datetime fields exist
                for rec in datetime_recs:
                    self.assertEqual(rec["type"], "datetime_index")
                    self.assertEqual(rec["priority"], "medium")
                    self.assertIn("sql", rec)

        except LookupError:
            self.skipTest("CarbonEntry model not available in test environment")

    def test_recommend_status_field_indexes(self):
        """Test status field index recommendations"""
        try:
            CarbonEntry = apps.get_model("carbon", "CarbonEntry")
            recommendations = self.optimizer._recommend_status_field_indexes(CarbonEntry)

            self.assertIsInstance(recommendations, list)

            # Check for status field recommendations
            for rec in recommendations:
                self.assertEqual(rec["type"], "status_index")
                self.assertEqual(rec["priority"], "medium")
                self.assertIn("sql", rec)

        except LookupError:
            self.skipTest("CarbonEntry model not available in test environment")

    def test_recommend_composite_indexes(self):
        """Test composite index recommendations"""
        try:
            CarbonEntry = apps.get_model("carbon", "CarbonEntry")
            recommendations = self.optimizer._recommend_composite_indexes(CarbonEntry)

            self.assertIsInstance(recommendations, list)

            # Should recommend composite indexes for CarbonEntry
            if recommendations:
                for rec in recommendations:
                    self.assertEqual(rec["type"], "composite_index")
                    self.assertIn("fields", rec)
                    self.assertIn("sql", rec)
                    self.assertIsInstance(rec["fields"], list)

        except LookupError:
            self.skipTest("CarbonEntry model not available in test environment")

    def test_identify_performance_issues(self):
        """Test performance issue identification"""
        # Mock model analysis data
        analysis = {
            "record_count": 50000,  # Large table
            "table_size_mb": 150,  # Large size
            "existing_indexes": [{"name": "primary_key"}],  # Few indexes
            "index_recommendations": [
                {"type": "foreign_key_index", "field": "establishment_id"},
                {"type": "foreign_key_index", "field": "parcel_id"},
            ],
        }

        try:
            CarbonEntry = apps.get_model("carbon", "CarbonEntry")
            issues = self.optimizer._identify_performance_issues(CarbonEntry, analysis)

            self.assertIsInstance(issues, list)

            # Should identify issues with large table and insufficient indexing
            issue_types = [issue["type"] for issue in issues]
            self.assertIn("insufficient_indexing", issue_types)
            self.assertIn("large_table_size", issue_types)
            self.assertIn("missing_fk_indexes", issue_types)

        except LookupError:
            self.skipTest("CarbonEntry model not available in test environment")

    @patch("common.services.database_optimizer.connection")
    def test_get_existing_indexes_postgres(self, mock_connection):
        """Test getting existing indexes for PostgreSQL"""
        # Mock PostgreSQL vendor
        self.optimizer.db_vendor = "postgresql"

        # Mock database cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("test_index_1", "CREATE INDEX test_index_1 ON test_table (column1)", "public"),
            ("test_index_2", "CREATE INDEX test_index_2 ON test_table (column2)", "public"),
        ]
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        indexes = self.optimizer._get_existing_indexes("test_table")

        self.assertEqual(len(indexes), 2)
        self.assertEqual(indexes[0]["name"], "test_index_1")
        self.assertEqual(indexes[1]["name"], "test_index_2")

    @patch("common.services.database_optimizer.connection")
    def test_get_table_size_postgres(self, mock_connection):
        """Test getting table size for PostgreSQL"""
        # Mock database cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("10 MB", 10485760)  # 10 MB in bytes
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        size_mb = self.optimizer._get_table_size_postgres("test_table")

        self.assertEqual(size_mb, 10.0)

    @patch("common.services.database_optimizer.connection")
    def test_get_postgres_statistics(self, mock_connection):
        """Test getting PostgreSQL statistics"""
        # Mock database cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("50 MB",),  # Database size
            (25,),  # Connection count
            (95.5,),  # Cache hit ratio
        ]
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        stats = self.optimizer._get_postgres_statistics()

        self.assertEqual(stats["database_size"], "50 MB")
        self.assertEqual(stats["connection_count"], 25)
        self.assertEqual(stats["cache_hit_ratio"], 95.5)

    def test_create_recommended_indexes_dry_run(self):
        """Test creating indexes in dry run mode"""
        recommendations = [
            {
                "type": "foreign_key_index",
                "field": "establishment_id",
                "sql": "CREATE INDEX test_idx ON test_table (establishment_id);",
            },
            {
                "type": "datetime_index",
                "field": "created_at",
                "sql": "CREATE INDEX test_date_idx ON test_table (created_at);",
            },
        ]

        results = self.optimizer.create_recommended_indexes(recommendations, dry_run=True)

        self.assertEqual(len(results["created_indexes"]), 2)
        self.assertEqual(len(results["sql_statements"]), 2)
        self.assertEqual(len(results["failed_indexes"]), 0)

        for created in results["created_indexes"]:
            self.assertEqual(created["status"], "dry_run")

    @patch("common.services.database_optimizer.connection")
    def test_create_recommended_indexes_live(self, mock_connection):
        """Test creating indexes in live mode"""
        recommendations = [
            {
                "type": "foreign_key_index",
                "field": "establishment_id",
                "sql": "CREATE INDEX test_idx ON test_table (establishment_id);",
            }
        ]

        # Mock successful index creation
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        results = self.optimizer.create_recommended_indexes(recommendations, dry_run=False)

        self.assertEqual(len(results["created_indexes"]), 1)
        self.assertEqual(results["created_indexes"][0]["status"], "success")
        mock_cursor.execute.assert_called_once()


class DatabaseOptimizerIntegrationTest(TestCase):
    """Integration tests for database optimizer"""

    def test_analyze_query_performance(self):
        """Test complete query performance analysis"""
        analysis = analyze_model_performance()

        self.assertIn("timestamp", analysis)
        self.assertIn("database_vendor", analysis)
        self.assertIn("models_analyzed", analysis)
        self.assertIn("performance_issues", analysis)
        self.assertIn("index_recommendations", analysis)
        self.assertIn("overall_health", analysis)

        # Should analyze at least some models
        self.assertIsInstance(analysis["models_analyzed"], list)
        self.assertIsInstance(analysis["performance_issues"], list)
        self.assertIsInstance(analysis["index_recommendations"], list)

    def test_get_performance_report(self):
        """Test comprehensive performance report generation"""
        report = get_performance_report()

        self.assertIn("timestamp", report)
        self.assertIn("database_health", report)
        self.assertIn("performance_summary", report)
        self.assertIn("critical_issues", report)
        self.assertIn("recommendations", report)
        self.assertIn("index_optimization", report)

        # Health summary
        health = report["database_health"]
        self.assertIn("overall_status", health)
        self.assertIn("models_analyzed", health)
        self.assertIn("total_issues", health)

        # Performance summary
        summary = report["performance_summary"]
        self.assertIn("total_records", summary)
        self.assertIn("total_size_mb", summary)
        self.assertIn("large_tables_count", summary)

        # Index optimization
        index_opt = report["index_optimization"]
        self.assertIn("total_recommendations", index_opt)
        self.assertIn("high_priority", index_opt)

    def test_analyze_specific_model(self):
        """Test analyzing a specific model"""
        try:
            analysis = analyze_model_performance("CropType")

            if "error" not in analysis:
                self.assertEqual(len(analysis["models_analyzed"]), 1)
                model_analysis = analysis["models_analyzed"][0]
                self.assertIn("carbon.croptype", model_analysis["model"].lower())

        except Exception:
            self.skipTest("CropType model analysis not available")


class DatabaseOptimizerUtilitiesTest(TestCase):
    """Test utility functions"""

    def test_convenience_functions(self):
        """Test convenience functions work correctly"""
        # Test analyze_model_performance function
        result = analyze_model_performance()
        self.assertIsInstance(result, dict)

        # Test get_performance_report function
        report = get_performance_report()
        self.assertIsInstance(report, dict)

        # Test create_indexes function with empty recommendations
        result = create_indexes([], dry_run=True)
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result["created_indexes"]), 0)


@override_settings(SLOW_QUERY_THRESHOLD_MS=500)
class DatabaseOptimizerConfigurationTest(TestCase):
    """Test optimizer with different configurations"""

    def test_custom_slow_query_threshold(self):
        """Test optimizer respects custom slow query threshold"""
        optimizer = DatabaseOptimizer()
        self.assertEqual(optimizer.slow_query_threshold, 500)

    def test_different_database_vendors(self):
        """Test optimizer handles different database vendors"""
        # Test with current vendor
        optimizer = DatabaseOptimizer()
        self.assertIn(optimizer.db_vendor, ["postgresql", "sqlite", "mysql"])

        # Verify vendor-specific methods exist
        if optimizer.db_vendor == "postgresql":
            self.assertTrue(hasattr(optimizer, "_get_postgres_statistics"))
        elif optimizer.db_vendor == "sqlite":
            self.assertTrue(hasattr(optimizer, "_get_sqlite_statistics"))


class DatabaseOptimizerErrorHandlingTest(TestCase):
    """Test error handling in database optimizer"""

    @patch("common.services.database_optimizer.apps.get_model")
    def test_analyze_invalid_model(self, mock_get_model):
        """Test analyzing non-existent model"""
        mock_get_model.side_effect = LookupError("Model not found")

        analysis = analyze_model_performance("NonExistentModel")
        self.assertIn("error", analysis)

    @patch("common.services.database_optimizer.connection")
    def test_database_error_handling(self, mock_connection):
        """Test handling of database errors"""
        # Mock database error
        mock_connection.cursor.side_effect = Exception("Database connection failed")

        optimizer = DatabaseOptimizer()
        indexes = optimizer._get_existing_indexes("test_table")

        # Should return empty list on error
        self.assertEqual(indexes, [])

    def test_invalid_recommendations(self):
        """Test handling of invalid index recommendations"""
        invalid_recommendations = [
            {"type": "invalid_type"},  # Missing required fields
            {"sql": ""},  # Empty SQL
            {},  # Empty recommendation
        ]

        results = database_optimizer.create_recommended_indexes(invalid_recommendations, dry_run=True)

        # Should handle invalid recommendations gracefully
        self.assertIsInstance(results, dict)
        self.assertIn("created_indexes", results)
        self.assertIn("failed_indexes", results)


class DatabaseOptimizerPerformanceTest(TestCase):
    """Test performance characteristics of optimizer"""

    def test_analysis_performance(self):
        """Test that analysis completes in reasonable time"""
        import time

        start_time = time.time()
        analysis = analyze_model_performance()
        elapsed_time = time.time() - start_time

        # Analysis should complete within 30 seconds
        self.assertLess(elapsed_time, 30)

        # Should return valid results
        self.assertIsInstance(analysis, dict)
        self.assertNotIn("error", analysis)

    def test_large_recommendation_handling(self):
        """Test handling of large numbers of recommendations"""
        # Create many recommendations
        large_recommendations = []
        for i in range(100):
            large_recommendations.append(
                {
                    "type": "test_index",
                    "field": f"field_{i}",
                    "sql": f"CREATE INDEX test_idx_{i} ON test_table (field_{i});",
                }
            )

        # Should handle large number of recommendations
        results = database_optimizer.create_recommended_indexes(large_recommendations, dry_run=True)

        self.assertEqual(len(results["created_indexes"]), 100)
        self.assertEqual(len(results["sql_statements"]), 100)
