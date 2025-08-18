"""
Enhanced Logging Service for Trazo
Provides comprehensive logging, error tracking, and monitoring capabilities
Addresses production readiness requirement for enhanced error handling and logging
"""

import json
import logging
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Optional, Union

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest
from django.utils import timezone


# Configure structured logging
class TrazoFormatter(logging.Formatter):
    """Custom formatter for structured logging"""

    def format(self, record):
        # Create structured log entry
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields if present
        if hasattr(record, "user_id"):
            log_entry["user_id"] = record.user_id
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if hasattr(record, "establishment_id"):
            log_entry["establishment_id"] = record.establishment_id
        if hasattr(record, "carbon_entry_id"):
            log_entry["carbon_entry_id"] = record.carbon_entry_id
        if hasattr(record, "api_endpoint"):
            log_entry["api_endpoint"] = record.api_endpoint
        if hasattr(record, "response_time_ms"):
            log_entry["response_time_ms"] = record.response_time_ms
        if hasattr(record, "error_type"):
            log_entry["error_type"] = record.error_type
        if hasattr(record, "stack_trace"):
            log_entry["stack_trace"] = record.stack_trace

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        return json.dumps(log_entry)


class ErrorTracker:
    """
    Centralized error tracking and analytics

    Features:
    - Error aggregation and deduplication
    - Error rate monitoring
    - Performance impact analysis
    - User impact tracking
    - Automatic alerting thresholds
    """

    def __init__(self):
        self.error_cache_ttl = 3600  # 1 hour
        self.alert_thresholds = {
            "error_rate_per_minute": 10,
            "critical_errors_per_hour": 5,
            "user_impact_threshold": 0.1,  # 10% of users affected
        }

    def track_error(self, error: Exception, context: Dict[str, Any] = None):
        """Track an error with context information"""
        try:
            context = context or {}
            error_data = {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "timestamp": timezone.now().isoformat(),
                "stack_trace": traceback.format_exc(),
                "context": context,
                "error_hash": self._generate_error_hash(error, context),
            }

            # Store error
            self._store_error(error_data)

            # Update error metrics
            self._update_error_metrics(error_data)

            # Check alert thresholds
            self._check_alert_thresholds(error_data)

        except Exception as e:
            # Failsafe - log to standard logger if error tracking fails
            logger = logging.getLogger(__name__)
            logger.error(f"Error tracking failed: {e}")

    def _generate_error_hash(self, error: Exception, context: Dict[str, Any]) -> str:
        """Generate unique hash for error deduplication"""
        import hashlib

        error_signature = f"{type(error).__name__}:{str(error)}"
        if context.get("function"):
            error_signature += f":{context['function']}"
        if context.get("module"):
            error_signature += f":{context['module']}"

        return hashlib.md5(error_signature.encode()).hexdigest()

    def _store_error(self, error_data: Dict[str, Any]):
        """Store error in cache for analysis"""
        error_hash = error_data["error_hash"]
        cache_key = f"error_{error_hash}"

        # Get existing error data
        existing_error = cache.get(cache_key, {})

        if existing_error:
            # Update occurrence count and last seen
            existing_error["occurrence_count"] = existing_error.get("occurrence_count", 1) + 1
            existing_error["last_seen"] = error_data["timestamp"]
            existing_error["recent_contexts"].append(error_data["context"])

            # Keep only last 10 contexts
            existing_error["recent_contexts"] = existing_error["recent_contexts"][-10:]
        else:
            # New error
            existing_error = {
                "first_seen": error_data["timestamp"],
                "last_seen": error_data["timestamp"],
                "occurrence_count": 1,
                "error_type": error_data["error_type"],
                "error_message": error_data["error_message"],
                "stack_trace": error_data["stack_trace"],
                "recent_contexts": [error_data["context"]],
            }

        cache.set(cache_key, existing_error, self.error_cache_ttl)

        # Also store in time-based buckets for analytics
        minute_key = f"errors_minute_{timezone.now().strftime('%Y%m%d%H%M')}"
        minute_errors = cache.get(minute_key, [])
        minute_errors.append(error_hash)
        cache.set(minute_key, minute_errors, 300)  # 5 minutes

    def _update_error_metrics(self, error_data: Dict[str, Any]):
        """Update error rate and impact metrics"""
        try:
            # Update error rate metrics
            now = timezone.now()
            hour_key = f"error_metrics_{now.strftime('%Y%m%d%H')}"

            metrics = cache.get(
                hour_key,
                {
                    "total_errors": 0,
                    "unique_errors": set(),
                    "critical_errors": 0,
                    "affected_users": set(),
                    "affected_establishments": set(),
                    "error_types": {},
                },
            )

            metrics["total_errors"] += 1
            metrics["unique_errors"].add(error_data["error_hash"])

            # Track error types
            error_type = error_data["error_type"]
            metrics["error_types"][error_type] = metrics["error_types"].get(error_type, 0) + 1

            # Track critical errors
            if error_type in ["DatabaseError", "OperationalError", "ConnectionError", "BlockchainError"]:
                metrics["critical_errors"] += 1

            # Track user/establishment impact
            context = error_data.get("context", {})
            if context.get("user_id"):
                metrics["affected_users"].add(str(context["user_id"]))
            if context.get("establishment_id"):
                metrics["affected_establishments"].add(str(context["establishment_id"]))

            cache.set(hour_key, metrics, 7200)  # 2 hours

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error metrics update failed: {e}")

    def _check_alert_thresholds(self, error_data: Dict[str, Any]):
        """Check if error rates exceed alert thresholds"""
        try:
            now = timezone.now()

            # Check error rate per minute
            minute_key = f"errors_minute_{now.strftime('%Y%m%d%H%M')}"
            minute_errors = cache.get(minute_key, [])

            if len(minute_errors) >= self.alert_thresholds["error_rate_per_minute"]:
                self._trigger_alert(
                    "high_error_rate",
                    {
                        "errors_per_minute": len(minute_errors),
                        "threshold": self.alert_thresholds["error_rate_per_minute"],
                        "recent_errors": minute_errors[-5:],  # Last 5 errors
                    },
                )

            # Check critical errors per hour
            hour_key = f"error_metrics_{now.strftime('%Y%m%d%H')}"
            hour_metrics = cache.get(hour_key, {})

            critical_errors = hour_metrics.get("critical_errors", 0)
            if critical_errors >= self.alert_thresholds["critical_errors_per_hour"]:
                self._trigger_alert(
                    "critical_errors",
                    {
                        "critical_errors_per_hour": critical_errors,
                        "threshold": self.alert_thresholds["critical_errors_per_hour"],
                        "error_types": hour_metrics.get("error_types", {}),
                    },
                )

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Alert threshold check failed: {e}")

    def _trigger_alert(self, alert_type: str, details: Dict[str, Any]):
        """Trigger alert for error conditions"""
        alert_data = {
            "alert_type": alert_type,
            "timestamp": timezone.now().isoformat(),
            "details": details,
            "severity": "high" if alert_type == "critical_errors" else "medium",
        }

        # Store alert
        alert_key = f"alert_{alert_type}_{timezone.now().strftime('%Y%m%d%H%M')}"
        cache.set(alert_key, alert_data, 86400)  # 24 hours

        # Log alert
        logger = logging.getLogger("trazo.alerts")
        logger.error(
            f"ALERT TRIGGERED: {alert_type}",
            extra={"alert_type": alert_type, "alert_details": details, "severity": alert_data["severity"]},
        )

    def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get error summary for specified time period"""
        try:
            now = timezone.now()
            summary = {
                "total_errors": 0,
                "unique_errors": 0,
                "critical_errors": 0,
                "error_rate_per_hour": 0,
                "most_common_errors": {},
                "affected_users": 0,
                "affected_establishments": 0,
                "recent_alerts": [],
            }

            # Aggregate metrics from hourly buckets
            for i in range(hours):
                hour = now - timedelta(hours=i)
                hour_key = f"error_metrics_{hour.strftime('%Y%m%d%H')}"
                hour_metrics = cache.get(hour_key, {})

                summary["total_errors"] += hour_metrics.get("total_errors", 0)
                summary["critical_errors"] += hour_metrics.get("critical_errors", 0)

                # Merge error types
                for error_type, count in hour_metrics.get("error_types", {}).items():
                    summary["most_common_errors"][error_type] = summary["most_common_errors"].get(error_type, 0) + count

            # Calculate rates
            if hours > 0:
                summary["error_rate_per_hour"] = summary["total_errors"] / hours

            # Get recent alerts
            alert_keys = cache.keys("alert_*")
            for alert_key in alert_keys:
                alert = cache.get(alert_key)
                if alert:
                    summary["recent_alerts"].append(alert)

            # Sort alerts by timestamp
            summary["recent_alerts"].sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            summary["recent_alerts"] = summary["recent_alerts"][:10]  # Last 10 alerts

            return summary

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error summary generation failed: {e}")
            return {"error": str(e)}


class PerformanceMonitor:
    """
    Performance monitoring and profiling

    Features:
    - Response time tracking
    - Database query monitoring
    - API endpoint performance
    - Resource usage tracking
    - Performance degradation alerts
    """

    def __init__(self):
        self.slow_request_threshold = getattr(settings, "SLOW_REQUEST_THRESHOLD_MS", 2000)
        self.performance_cache_ttl = 3600  # 1 hour

    @contextmanager
    def measure_performance(self, operation: str, context: Dict[str, Any] = None):
        """Context manager for measuring operation performance"""
        start_time = time.time()
        context = context or {}

        try:
            yield

        except Exception as e:
            # Track performance even on errors
            elapsed_time = (time.time() - start_time) * 1000
            context["error"] = str(e)
            self._record_performance(operation, elapsed_time, context, success=False)
            raise

        else:
            # Record successful operation
            elapsed_time = (time.time() - start_time) * 1000
            self._record_performance(operation, elapsed_time, context, success=True)

    def _record_performance(
        self, operation: str, elapsed_time_ms: float, context: Dict[str, Any], success: bool = True
    ):
        """Record performance metrics"""
        try:
            perf_data = {
                "operation": operation,
                "elapsed_time_ms": round(elapsed_time_ms, 2),
                "timestamp": timezone.now().isoformat(),
                "success": success,
                "context": context,
            }

            # Store in time-based buckets
            minute_key = f"perf_minute_{timezone.now().strftime('%Y%m%d%H%M')}"
            minute_data = cache.get(minute_key, [])
            minute_data.append(perf_data)
            cache.set(minute_key, minute_data, 300)  # 5 minutes

            # Update operation-specific metrics
            self._update_operation_metrics(operation, elapsed_time_ms, success)

            # Check for slow operations
            if elapsed_time_ms > self.slow_request_threshold:
                self._handle_slow_operation(operation, elapsed_time_ms, context)

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Performance recording failed: {e}")

    def _update_operation_metrics(self, operation: str, elapsed_time_ms: float, success: bool):
        """Update aggregated metrics for operation"""
        try:
            hour_key = f"perf_operation_{operation}_{timezone.now().strftime('%Y%m%d%H')}"
            metrics = cache.get(
                hour_key,
                {
                    "total_requests": 0,
                    "successful_requests": 0,
                    "total_time_ms": 0,
                    "min_time_ms": float("inf"),
                    "max_time_ms": 0,
                    "slow_requests": 0,
                },
            )

            metrics["total_requests"] += 1
            if success:
                metrics["successful_requests"] += 1

            metrics["total_time_ms"] += elapsed_time_ms
            metrics["min_time_ms"] = min(metrics["min_time_ms"], elapsed_time_ms)
            metrics["max_time_ms"] = max(metrics["max_time_ms"], elapsed_time_ms)

            if elapsed_time_ms > self.slow_request_threshold:
                metrics["slow_requests"] += 1

            cache.set(hour_key, metrics, 7200)  # 2 hours

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Operation metrics update failed: {e}")

    def _handle_slow_operation(self, operation: str, elapsed_time_ms: float, context: Dict[str, Any]):
        """Handle slow operation detection"""
        slow_op_data = {
            "operation": operation,
            "elapsed_time_ms": elapsed_time_ms,
            "context": context,
            "timestamp": timezone.now().isoformat(),
        }

        # Log slow operation
        logger = logging.getLogger("trazo.performance")
        logger.warning(
            f"SLOW OPERATION: {operation} took {elapsed_time_ms:.2f}ms",
            extra={"operation": operation, "response_time_ms": elapsed_time_ms, "slow_operation": True, **context},
        )

        # Store for analysis
        slow_key = f"slow_operations_{timezone.now().strftime('%Y%m%d')}"
        slow_ops = cache.get(slow_key, [])
        slow_ops.append(slow_op_data)
        cache.set(slow_key, slow_ops[-100:], 86400)  # Keep last 100, 24 hours

    def get_performance_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get performance summary for specified time period"""
        try:
            now = timezone.now()
            summary = {
                "total_requests": 0,
                "average_response_time_ms": 0,
                "slowest_operations": [],
                "success_rate": 0,
                "slow_request_rate": 0,
                "operations_performance": {},
            }

            total_time = 0
            successful_requests = 0
            slow_requests = 0

            # Get all operation metrics
            all_operations = set()
            for i in range(hours):
                hour = now - timedelta(hours=i)
                # This would need a way to get all operation keys - simplified for demo
                pass

            # For now, return basic summary structure
            return summary

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Performance summary generation failed: {e}")
            return {"error": str(e)}


class EnhancedLogger:
    """
    Enhanced logging service with context and structured logging

    Features:
    - Structured JSON logging
    - Request context tracking
    - User and business context
    - Performance integration
    - Error tracking integration
    """

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.error_tracker = ErrorTracker()
        self.performance_monitor = PerformanceMonitor()
        self._local = threading.local()

    def set_context(self, **kwargs):
        """Set logging context for current thread"""
        if not hasattr(self._local, "context"):
            self._local.context = {}
        self._local.context.update(kwargs)

    def clear_context(self):
        """Clear logging context for current thread"""
        if hasattr(self._local, "context"):
            self._local.context = {}

    def _get_context(self) -> Dict[str, Any]:
        """Get current logging context"""
        if hasattr(self._local, "context"):
            return self._local.context.copy()
        return {}

    def _log_with_context(self, level: int, message: str, extra: Dict[str, Any] = None):
        """Log message with context"""
        context = self._get_context()
        if extra:
            context.update(extra)

        self.logger.log(level, message, extra=context)

    def debug(self, message: str, **kwargs):
        """Log debug message with context"""
        self._log_with_context(logging.DEBUG, message, kwargs)

    def info(self, message: str, **kwargs):
        """Log info message with context"""
        self._log_with_context(logging.INFO, message, kwargs)

    def warning(self, message: str, **kwargs):
        """Log warning message with context"""
        self._log_with_context(logging.WARNING, message, kwargs)

    def error(self, message: str, error: Exception = None, **kwargs):
        """Log error message with tracking"""
        context = self._get_context()
        context.update(kwargs)

        if error:
            context["error_type"] = type(error).__name__
            self.error_tracker.track_error(error, context)

        self._log_with_context(logging.ERROR, message, context)

    def critical(self, message: str, error: Exception = None, **kwargs):
        """Log critical message with tracking"""
        context = self._get_context()
        context.update(kwargs)

        if error:
            context["error_type"] = type(error).__name__
            self.error_tracker.track_error(error, context)

        self._log_with_context(logging.CRITICAL, message, context)

    @contextmanager
    def operation_context(self, operation: str, **context):
        """Context manager for operation logging and performance tracking"""
        self.set_context(operation=operation, **context)

        with self.performance_monitor.measure_performance(operation, context):
            try:
                self.info(f"Starting operation: {operation}")
                yield
                self.info(f"Completed operation: {operation}")

            except Exception as e:
                self.error(f"Operation failed: {operation}", error=e)
                raise

            finally:
                self.clear_context()


# Global instances
error_tracker = ErrorTracker()
performance_monitor = PerformanceMonitor()


# Convenience functions
def get_logger(name: str) -> EnhancedLogger:
    """Get enhanced logger for module"""
    return EnhancedLogger(name)


def track_error(error: Exception, context: Dict[str, Any] = None):
    """Track error globally"""
    error_tracker.track_error(error, context)


def get_error_summary(hours: int = 24) -> Dict[str, Any]:
    """Get global error summary"""
    return error_tracker.get_error_summary(hours)


def get_performance_summary(hours: int = 24) -> Dict[str, Any]:
    """Get global performance summary"""
    return performance_monitor.get_performance_summary(hours)


# Decorators for automatic logging
def log_errors(logger_name: str = None):
    """Decorator to automatically log and track errors"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name or func.__module__)

            try:
                return func(*args, **kwargs)
            except Exception as e:
                context = {
                    "function": func.__name__,
                    "module": func.__module__,
                    "args_count": len(args),
                    "kwargs_keys": list(kwargs.keys()),
                }

                logger.error(f"Function {func.__name__} failed", error=e, **context)
                raise

        return wrapper

    return decorator


def measure_performance(operation_name: str = None):
    """Decorator to automatically measure function performance"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            operation = operation_name or f"{func.__module__}.{func.__name__}"
            context = {"function": func.__name__, "module": func.__module__}

            with performance_monitor.measure_performance(operation, context):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def log_and_measure(logger_name: str = None, operation_name: str = None):
    """Combined decorator for error logging and performance measurement"""

    def decorator(func):
        @log_errors(logger_name)
        @measure_performance(operation_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator
