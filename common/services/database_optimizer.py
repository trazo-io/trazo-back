"""
Database Query Optimizer and Index Manager for Trazo
Analyzes query patterns and implements performance optimizations
Addresses production readiness requirement for database optimization
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import ForeignKey, Index, Model, Q
from django.db.models.fields import CharField, DateTimeField, FloatField, IntegerField
from django.utils import timezone

logger = logging.getLogger(__name__)


class DatabaseOptimizer:
    """
    Comprehensive database optimization service

    Features:
    - Query performance analysis
    - Automatic index creation and optimization
    - Slow query detection and reporting
    - Database statistics and health monitoring
    - Index usage analysis
    - Query plan optimization suggestions
    """

    def __init__(self):
        self.db_vendor = connection.vendor
        self.slow_query_threshold = getattr(settings, "SLOW_QUERY_THRESHOLD_MS", 1000)
        self.analyzed_queries = []

        logger.info(f"DatabaseOptimizer initialized for {self.db_vendor}")

    def analyze_query_performance(self, model_name: str = None) -> Dict[str, Any]:
        """
        Analyze query performance for specific model or all models

        Args:
            model_name: Optional specific model to analyze

        Returns:
            Analysis results with recommendations
        """
        try:
            analysis_results = {
                "timestamp": timezone.now().isoformat(),
                "database_vendor": self.db_vendor,
                "models_analyzed": [],
                "performance_issues": [],
                "index_recommendations": [],
                "query_statistics": {},
                "overall_health": "good",
            }

            # Get models to analyze
            models_to_analyze = []
            if model_name:
                try:
                    model = apps.get_model("carbon", model_name)
                    models_to_analyze = [model]
                except LookupError:
                    logger.warning(f"Model {model_name} not found")
                    return {"error": f"Model {model_name} not found"}
            else:
                # Analyze key Trazo models
                key_models = [
                    "carbon.CarbonEntry",
                    "carbon.CropType",
                    "carbon.ProductionTemplate",
                    "history.History",
                    "company.Company",
                    "company.Establishment",
                    "product.Parcel",
                    "users.User",
                    "subscriptions.Subscription",
                ]

                for model_path in key_models:
                    try:
                        app_label, model_name = model_path.split(".")
                        model = apps.get_model(app_label, model_name)
                        models_to_analyze.append(model)
                    except (LookupError, ValueError):
                        logger.warning(f"Could not load model: {model_path}")

            # Analyze each model
            for model in models_to_analyze:
                model_analysis = self._analyze_model_performance(model)
                analysis_results["models_analyzed"].append(model_analysis)

                # Collect performance issues
                if model_analysis.get("issues"):
                    analysis_results["performance_issues"].extend(model_analysis["issues"])

                # Collect index recommendations
                if model_analysis.get("index_recommendations"):
                    analysis_results["index_recommendations"].extend(model_analysis["index_recommendations"])

            # Analyze overall database statistics
            analysis_results["query_statistics"] = self._get_database_statistics()

            # Determine overall health
            critical_issues = len(
                [issue for issue in analysis_results["performance_issues"] if issue.get("severity") == "critical"]
            )
            if critical_issues > 0:
                analysis_results["overall_health"] = "critical"
            elif len(analysis_results["performance_issues"]) > 5:
                analysis_results["overall_health"] = "degraded"

            logger.info(
                f"Database analysis completed: {len(models_to_analyze)} models analyzed, "
                f"{len(analysis_results['performance_issues'])} issues found"
            )

            return analysis_results

        except Exception as e:
            logger.error(f"Database analysis failed: {e}")
            return {"error": str(e), "timestamp": timezone.now().isoformat()}

    def _analyze_model_performance(self, model: Model) -> Dict[str, Any]:
        """Analyze performance for a specific model"""
        try:
            model_name = f"{model._meta.app_label}.{model._meta.model_name}"
            table_name = model._meta.db_table

            model_analysis = {
                "model": model_name,
                "table_name": table_name,
                "record_count": 0,
                "table_size_mb": 0,
                "existing_indexes": [],
                "missing_indexes": [],
                "index_recommendations": [],
                "issues": [],
                "common_queries": [],
            }

            # Get record count
            try:
                model_analysis["record_count"] = model.objects.count()
            except Exception as e:
                logger.warning(f"Could not get count for {model_name}: {e}")

            # Get table size (PostgreSQL specific)
            if self.db_vendor == "postgresql":
                model_analysis["table_size_mb"] = self._get_table_size_postgres(table_name)

            # Analyze existing indexes
            model_analysis["existing_indexes"] = self._get_existing_indexes(table_name)

            # Analyze field usage patterns and recommend indexes
            index_recommendations = self._analyze_field_usage(model)
            model_analysis["index_recommendations"] = index_recommendations

            # Identify performance issues
            model_analysis["issues"] = self._identify_performance_issues(model, model_analysis)

            # Analyze common query patterns
            model_analysis["common_queries"] = self._analyze_common_queries(model)

            return model_analysis

        except Exception as e:
            logger.error(f"Model analysis failed for {model}: {e}")
            return {"model": str(model), "error": str(e)}

    def _get_existing_indexes(self, table_name: str) -> List[Dict[str, Any]]:
        """Get existing database indexes for a table"""
        try:
            indexes = []

            if self.db_vendor == "postgresql":
                query = """
                SELECT 
                    indexname,
                    indexdef,
                    schemaname
                FROM pg_indexes 
                WHERE tablename = %s AND schemaname = 'public'
                """

                with connection.cursor() as cursor:
                    cursor.execute(query, [table_name])
                    for row in cursor.fetchall():
                        indexes.append({"name": row[0], "definition": row[1], "schema": row[2]})

            elif self.db_vendor == "sqlite":
                query = f"PRAGMA index_list({table_name})"

                with connection.cursor() as cursor:
                    cursor.execute(query)
                    for row in cursor.fetchall():
                        indexes.append({"name": row[1], "unique": bool(row[2]), "origin": row[3]})

            return indexes

        except Exception as e:
            logger.error(f"Failed to get indexes for {table_name}: {e}")
            return []

    def _get_table_size_postgres(self, table_name: str) -> float:
        """Get table size in MB for PostgreSQL"""
        try:
            query = """
            SELECT pg_size_pretty(pg_total_relation_size(%s)) as size,
                   pg_total_relation_size(%s) as bytes
            """

            with connection.cursor() as cursor:
                cursor.execute(query, [table_name, table_name])
                result = cursor.fetchone()
                if result:
                    return round(result[1] / (1024 * 1024), 2)  # Convert to MB

            return 0.0

        except Exception as e:
            logger.warning(f"Could not get table size for {table_name}: {e}")
            return 0.0

    def _analyze_field_usage(self, model: Model) -> List[Dict[str, Any]]:
        """Analyze field usage patterns and recommend indexes"""
        recommendations = []

        try:
            # Common patterns that benefit from indexes
            recommendations.extend(self._recommend_foreign_key_indexes(model))
            recommendations.extend(self._recommend_datetime_indexes(model))
            recommendations.extend(self._recommend_status_field_indexes(model))
            recommendations.extend(self._recommend_search_indexes(model))
            recommendations.extend(self._recommend_composite_indexes(model))

        except Exception as e:
            logger.error(f"Field usage analysis failed for {model}: {e}")

        return recommendations

    def _recommend_foreign_key_indexes(self, model: Model) -> List[Dict[str, Any]]:
        """Recommend indexes for foreign key fields"""
        recommendations = []

        for field in model._meta.get_fields():
            if isinstance(field, ForeignKey):
                # Foreign keys usually benefit from indexes
                recommendations.append(
                    {
                        "type": "foreign_key_index",
                        "field": field.name,
                        "column": field.column,
                        "reason": "Foreign key lookups and joins",
                        "priority": "high",
                        "sql": f"CREATE INDEX idx_{model._meta.db_table}_{field.column} ON {model._meta.db_table} ({field.column});",
                    }
                )

        return recommendations

    def _recommend_datetime_indexes(self, model: Model) -> List[Dict[str, Any]]:
        """Recommend indexes for datetime fields"""
        recommendations = []

        datetime_fields = ["created_at", "updated_at", "date", "timestamp", "modified"]

        for field in model._meta.get_fields():
            if isinstance(field, DateTimeField) or field.name in datetime_fields:

                recommendations.append(
                    {
                        "type": "datetime_index",
                        "field": field.name,
                        "column": field.column if hasattr(field, "column") else field.name,
                        "reason": "Date range queries and temporal filtering",
                        "priority": "medium",
                        "sql": f"CREATE INDEX idx_{model._meta.db_table}_{field.name} ON {model._meta.db_table} ({field.name});",
                    }
                )

        return recommendations

    def _recommend_status_field_indexes(self, model: Model) -> List[Dict[str, Any]]:
        """Recommend indexes for status and enumeration fields"""
        recommendations = []

        status_fields = ["status", "state", "type", "category", "is_active", "published"]

        for field in model._meta.get_fields():
            if field.name in status_fields or (hasattr(field, "choices") and field.choices):

                recommendations.append(
                    {
                        "type": "status_index",
                        "field": field.name,
                        "column": field.column if hasattr(field, "column") else field.name,
                        "reason": "Status filtering and enumeration queries",
                        "priority": "medium",
                        "sql": f"CREATE INDEX idx_{model._meta.db_table}_{field.name} ON {model._meta.db_table} ({field.name});",
                    }
                )

        return recommendations

    def _recommend_search_indexes(self, model: Model) -> List[Dict[str, Any]]:
        """Recommend full-text search indexes"""
        recommendations = []

        # Fields that commonly benefit from text search
        text_fields = ["name", "title", "description", "slug", "email"]

        for field in model._meta.get_fields():
            if isinstance(field, CharField) and field.name in text_fields:

                if self.db_vendor == "postgresql":
                    # PostgreSQL GIN index for text search
                    recommendations.append(
                        {
                            "type": "text_search_index",
                            "field": field.name,
                            "column": field.name,
                            "reason": "Text search and LIKE queries",
                            "priority": "medium",
                            "sql": f"CREATE INDEX idx_{model._meta.db_table}_{field.name}_gin ON {model._meta.db_table} USING gin(to_tsvector('english', {field.name}));",
                        }
                    )
                else:
                    # Standard index for other databases
                    recommendations.append(
                        {
                            "type": "text_index",
                            "field": field.name,
                            "column": field.name,
                            "reason": "Text search and pattern matching",
                            "priority": "medium",
                            "sql": f"CREATE INDEX idx_{model._meta.db_table}_{field.name} ON {model._meta.db_table} ({field.name});",
                        }
                    )

        return recommendations

    def _recommend_composite_indexes(self, model: Model) -> List[Dict[str, Any]]:
        """Recommend composite indexes for common query patterns"""
        recommendations = []

        # Common composite index patterns for Trazo models
        model_name = model._meta.model_name.lower()

        if model_name == "carbonentry":
            # Carbon entries often filtered by establishment and date
            recommendations.append(
                {
                    "type": "composite_index",
                    "fields": ["establishment", "created_at"],
                    "reason": "Carbon entries by establishment and date range",
                    "priority": "high",
                    "sql": f"CREATE INDEX idx_{model._meta.db_table}_est_date ON {model._meta.db_table} (establishment_id, created_at);",
                }
            )

        elif model_name == "history":
            # History often filtered by parcel and date
            recommendations.append(
                {
                    "type": "composite_index",
                    "fields": ["parcel", "date"],
                    "reason": "Production history by parcel and date",
                    "priority": "high",
                    "sql": f"CREATE INDEX idx_{model._meta.db_table}_parcel_date ON {model._meta.db_table} (parcel_id, date);",
                }
            )

        elif model_name == "establishment":
            # Establishments often filtered by company and status
            recommendations.append(
                {
                    "type": "composite_index",
                    "fields": ["company", "is_active"],
                    "reason": "Active establishments by company",
                    "priority": "medium",
                    "sql": f"CREATE INDEX idx_{model._meta.db_table}_company_active ON {model._meta.db_table} (company_id, is_active);",
                }
            )

        return recommendations

    def _identify_performance_issues(self, model: Model, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Identify potential performance issues"""
        issues = []

        # Large tables without adequate indexing
        if analysis["record_count"] > 10000 and len(analysis["existing_indexes"]) < 3:
            issues.append(
                {
                    "type": "insufficient_indexing",
                    "severity": "high",
                    "description": f'Large table ({analysis["record_count"]} records) with insufficient indexing',
                    "recommendation": "Add indexes for commonly queried fields",
                }
            )

        # Very large tables
        if analysis["record_count"] > 100000:
            issues.append(
                {
                    "type": "large_table",
                    "severity": "medium",
                    "description": f'Very large table ({analysis["record_count"]} records)',
                    "recommendation": "Consider partitioning or archiving old data",
                }
            )

        # Tables growing rapidly (heuristic)
        if analysis["table_size_mb"] > 100:
            issues.append(
                {
                    "type": "large_table_size",
                    "severity": "medium",
                    "description": f'Table size is {analysis["table_size_mb"]} MB',
                    "recommendation": "Monitor growth and consider optimization",
                }
            )

        # Missing foreign key indexes
        foreign_key_recommendations = [r for r in analysis["index_recommendations"] if r["type"] == "foreign_key_index"]
        if foreign_key_recommendations:
            issues.append(
                {
                    "type": "missing_fk_indexes",
                    "severity": "high",
                    "description": f"Missing indexes on {len(foreign_key_recommendations)} foreign key fields",
                    "recommendation": "Add foreign key indexes to improve join performance",
                }
            )

        return issues

    def _analyze_common_queries(self, model: Model) -> List[Dict[str, Any]]:
        """Analyze common query patterns for the model"""
        queries = []

        try:
            # Sample common queries based on model type
            model_name = model._meta.model_name.lower()

            if model_name == "carbonentry":
                queries.extend(
                    [
                        {"pattern": "filter by establishment", "frequency": "high"},
                        {"pattern": "filter by date range", "frequency": "high"},
                        {"pattern": "order by created_at", "frequency": "medium"},
                        {"pattern": "aggregate by establishment", "frequency": "medium"},
                    ]
                )
            elif model_name == "history":
                queries.extend(
                    [
                        {"pattern": "filter by parcel", "frequency": "high"},
                        {"pattern": "filter by date", "frequency": "high"},
                        {"pattern": "filter by type", "frequency": "medium"},
                        {"pattern": "order by date desc", "frequency": "high"},
                    ]
                )
            elif model_name == "establishment":
                queries.extend(
                    [
                        {"pattern": "filter by company", "frequency": "high"},
                        {"pattern": "filter by is_active", "frequency": "medium"},
                        {"pattern": "search by name", "frequency": "medium"},
                    ]
                )

        except Exception as e:
            logger.error(f"Query pattern analysis failed: {e}")

        return queries

    def _get_database_statistics(self) -> Dict[str, Any]:
        """Get overall database statistics"""
        stats = {
            "vendor": self.db_vendor,
            "connection_count": 0,
            "database_size_mb": 0,
            "cache_hit_ratio": 0,
            "slow_queries_count": 0,
        }

        try:
            if self.db_vendor == "postgresql":
                stats.update(self._get_postgres_statistics())
            elif self.db_vendor == "sqlite":
                stats.update(self._get_sqlite_statistics())

        except Exception as e:
            logger.error(f"Failed to get database statistics: {e}")

        return stats

    def _get_postgres_statistics(self) -> Dict[str, Any]:
        """Get PostgreSQL-specific statistics"""
        stats = {}

        try:
            with connection.cursor() as cursor:
                # Database size
                cursor.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
                size_result = cursor.fetchone()
                if size_result:
                    stats["database_size"] = size_result[0]

                # Connection count
                cursor.execute("SELECT count(*) FROM pg_stat_activity")
                conn_result = cursor.fetchone()
                if conn_result:
                    stats["connection_count"] = conn_result[0]

                # Cache hit ratio
                cursor.execute(
                    """
                    SELECT 
                        round(
                            (sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read))) * 100, 2
                        ) as cache_hit_ratio
                    FROM pg_statio_user_tables
                """
                )
                cache_result = cursor.fetchone()
                if cache_result and cache_result[0]:
                    stats["cache_hit_ratio"] = float(cache_result[0])

        except Exception as e:
            logger.error(f"PostgreSQL statistics error: {e}")

        return stats

    def _get_sqlite_statistics(self) -> Dict[str, Any]:
        """Get SQLite-specific statistics"""
        stats = {}

        try:
            with connection.cursor() as cursor:
                # Database size (page count * page size)
                cursor.execute("PRAGMA page_count")
                page_count = cursor.fetchone()[0]

                cursor.execute("PRAGMA page_size")
                page_size = cursor.fetchone()[0]

                stats["database_size_mb"] = round((page_count * page_size) / (1024 * 1024), 2)

        except Exception as e:
            logger.error(f"SQLite statistics error: {e}")

        return stats

    def create_recommended_indexes(self, recommendations: List[Dict[str, Any]], dry_run: bool = True) -> Dict[str, Any]:
        """
        Create recommended indexes

        Args:
            recommendations: List of index recommendations
            dry_run: If True, only return SQL without executing

        Returns:
            Results of index creation
        """
        results = {"created_indexes": [], "failed_indexes": [], "skipped_indexes": [], "sql_statements": []}

        try:
            for recommendation in recommendations:
                sql = recommendation.get("sql")
                if not sql:
                    continue

                results["sql_statements"].append(sql)

                if dry_run:
                    results["created_indexes"].append({"sql": sql, "status": "dry_run"})
                    continue

                try:
                    with connection.cursor() as cursor:
                        cursor.execute(sql)

                    results["created_indexes"].append({"sql": sql, "status": "success"})

                    logger.info(f"Created index: {sql}")

                except Exception as e:
                    error_message = str(e)

                    # Skip if index already exists
                    if "already exists" in error_message.lower():
                        results["skipped_indexes"].append({"sql": sql, "reason": "Index already exists"})
                    else:
                        results["failed_indexes"].append({"sql": sql, "error": error_message})
                        logger.error(f"Failed to create index: {sql} - {error_message}")

            logger.info(
                f"Index creation completed: {len(results['created_indexes'])} created, "
                f"{len(results['failed_indexes'])} failed, "
                f"{len(results['skipped_indexes'])} skipped"
            )

        except Exception as e:
            logger.error(f"Index creation process failed: {e}")
            results["error"] = str(e)

        return results

    def get_query_performance_report(self) -> Dict[str, Any]:
        """Generate comprehensive query performance report"""
        report = {
            "timestamp": timezone.now().isoformat(),
            "database_health": {},
            "performance_summary": {},
            "critical_issues": [],
            "recommendations": [],
            "index_optimization": {},
        }

        try:
            # Analyze all models
            analysis = self.analyze_query_performance()

            # Health summary
            report["database_health"] = {
                "overall_status": analysis.get("overall_health", "unknown"),
                "models_analyzed": len(analysis.get("models_analyzed", [])),
                "total_issues": len(analysis.get("performance_issues", [])),
                "database_stats": analysis.get("query_statistics", {}),
            }

            # Performance summary
            total_records = sum(model.get("record_count", 0) for model in analysis.get("models_analyzed", []))
            total_size_mb = sum(model.get("table_size_mb", 0) for model in analysis.get("models_analyzed", []))

            report["performance_summary"] = {
                "total_records": total_records,
                "total_size_mb": round(total_size_mb, 2),
                "average_table_size_mb": round(total_size_mb / max(len(analysis.get("models_analyzed", [])), 1), 2),
                "large_tables_count": len(
                    [m for m in analysis.get("models_analyzed", []) if m.get("record_count", 0) > 10000]
                ),
            }

            # Critical issues
            report["critical_issues"] = [
                issue
                for issue in analysis.get("performance_issues", [])
                if issue.get("severity") == "critical" or issue.get("severity") == "high"
            ]

            # Top recommendations
            report["recommendations"] = analysis.get("index_recommendations", [])[:10]  # Top 10

            # Index optimization summary
            all_recommendations = analysis.get("index_recommendations", [])
            report["index_optimization"] = {
                "total_recommendations": len(all_recommendations),
                "high_priority": len([r for r in all_recommendations if r.get("priority") == "high"]),
                "foreign_key_indexes": len([r for r in all_recommendations if r.get("type") == "foreign_key_index"]),
                "composite_indexes": len([r for r in all_recommendations if r.get("type") == "composite_index"]),
                "text_search_indexes": len(
                    [r for r in all_recommendations if r.get("type") in ["text_search_index", "text_index"]]
                ),
            }

        except Exception as e:
            logger.error(f"Performance report generation failed: {e}")
            report["error"] = str(e)

        return report


# Global optimizer instance
database_optimizer = DatabaseOptimizer()


# Convenience functions
def analyze_model_performance(model_name: str = None) -> Dict[str, Any]:
    """Analyze performance for specific model or all models"""
    return database_optimizer.analyze_query_performance(model_name)


def get_performance_report() -> Dict[str, Any]:
    """Get comprehensive performance report"""
    return database_optimizer.get_query_performance_report()


def create_indexes(recommendations: List[Dict[str, Any]], dry_run: bool = True) -> Dict[str, Any]:
    """Create recommended indexes"""
    return database_optimizer.create_recommended_indexes(recommendations, dry_run)
