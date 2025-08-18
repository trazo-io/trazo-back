"""
Django management command for system health monitoring
Usage: python manage.py system_health [--errors] [--performance] [--alerts] [--json]
"""

import json

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from common.services.database_optimizer import get_performance_report
from common.services.enhanced_logging import get_error_summary, get_performance_summary


class Command(BaseCommand):
    help = "Monitor system health, errors, and performance"

    def add_arguments(self, parser):
        parser.add_argument("--errors", action="store_true", help="Show error summary and analysis")

        parser.add_argument("--performance", action="store_true", help="Show performance metrics and analysis")

        parser.add_argument("--alerts", action="store_true", help="Show active alerts and warnings")

        parser.add_argument("--database", action="store_true", help="Show database health and performance")

        parser.add_argument("--hours", type=int, default=24, help="Time period in hours for analysis (default: 24)")

        parser.add_argument("--json", action="store_true", help="Output results in JSON format")

        parser.add_argument("--watch", action="store_true", help="Watch mode - continuously monitor health")

    def handle(self, *args, **options):
        try:
            errors = options.get("errors")
            performance = options.get("performance")
            alerts = options.get("alerts")
            database = options.get("database")
            hours = options.get("hours", 24)
            json_output = options.get("json")
            watch_mode = options.get("watch")

            if watch_mode:
                self.watch_system_health(hours, json_output)
                return

            # If no specific option is selected, show overall health
            if not any([errors, performance, alerts, database]):
                self.show_overall_health(hours, json_output)
            else:
                if errors:
                    self.show_error_analysis(hours, json_output)
                if performance:
                    self.show_performance_analysis(hours, json_output)
                if alerts:
                    self.show_alerts(json_output)
                if database:
                    self.show_database_health(json_output)

        except Exception as e:
            raise CommandError(f"System health check failed: {e}")

    def show_overall_health(self, hours: int, json_output: bool = False):
        """Show comprehensive system health overview"""
        if not json_output:
            self.stdout.write(self.style.HTTP_INFO("🏥 System Health Overview\n"))

        try:
            # Gather all health data
            error_summary = get_error_summary(hours)
            performance_summary = get_performance_summary(hours)
            database_report = get_performance_report()
            alerts = self._get_active_alerts()

            health_data = {
                "timestamp": timezone.now().isoformat(),
                "period_hours": hours,
                "overall_status": self._calculate_overall_status(
                    error_summary, performance_summary, database_report, alerts
                ),
                "error_summary": error_summary,
                "performance_summary": performance_summary,
                "database_health": database_report.get("database_health", {}),
                "active_alerts": alerts,
                "system_metrics": self._get_system_metrics(),
            }

            if json_output:
                self.stdout.write(json.dumps(health_data, indent=2))
                return

            # Console output
            self._display_health_overview(health_data)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Health check failed: {e}"))

    def show_error_analysis(self, hours: int, json_output: bool = False):
        """Show detailed error analysis"""
        if not json_output:
            self.stdout.write(self.style.HTTP_INFO(f"🔍 Error Analysis (Last {hours} hours)\n"))

        try:
            error_summary = get_error_summary(hours)

            if json_output:
                self.stdout.write(json.dumps(error_summary, indent=2))
                return

            # Console output
            self._display_error_analysis(error_summary)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error analysis failed: {e}"))

    def show_performance_analysis(self, hours: int, json_output: bool = False):
        """Show detailed performance analysis"""
        if not json_output:
            self.stdout.write(self.style.HTTP_INFO(f"⚡ Performance Analysis (Last {hours} hours)\n"))

        try:
            performance_summary = get_performance_summary(hours)

            if json_output:
                self.stdout.write(json.dumps(performance_summary, indent=2))
                return

            # Console output
            self._display_performance_analysis(performance_summary)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Performance analysis failed: {e}"))

    def show_alerts(self, json_output: bool = False):
        """Show active alerts and warnings"""
        if not json_output:
            self.stdout.write(self.style.HTTP_INFO("🚨 Active Alerts\n"))

        try:
            alerts = self._get_active_alerts()

            if json_output:
                self.stdout.write(json.dumps({"alerts": alerts}, indent=2))
                return

            # Console output
            self._display_alerts(alerts)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Alert retrieval failed: {e}"))

    def show_database_health(self, json_output: bool = False):
        """Show database health status"""
        if not json_output:
            self.stdout.write(self.style.HTTP_INFO("🗄️  Database Health\n"))

        try:
            database_report = get_performance_report()

            if json_output:
                self.stdout.write(json.dumps(database_report, indent=2))
                return

            # Console output
            self._display_database_health(database_report)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Database health check failed: {e}"))

    def watch_system_health(self, hours: int, json_output: bool):
        """Watch mode - continuously monitor system health"""
        import time

        if not json_output:
            self.stdout.write(self.style.HTTP_INFO("👁️  Watching system health (Ctrl+C to stop)...\n"))

        try:
            while True:
                if not json_output:
                    # Clear screen (simple version)
                    self.stdout.write("\033[2J\033[H")

                    # Show timestamp
                    now = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.stdout.write(f"Last Update: {now}\n")

                # Show health overview
                self.show_overall_health(hours, json_output)

                if not json_output:
                    self.stdout.write("\n" + "=" * 60)

                # Wait before next update
                time.sleep(30)  # Update every 30 seconds

        except KeyboardInterrupt:
            if not json_output:
                self.stdout.write("\n👋 Health monitoring stopped")

    def _calculate_overall_status(
        self, error_summary: dict, performance_summary: dict, database_report: dict, alerts: list
    ) -> str:
        """Calculate overall system health status"""
        try:
            # Check for critical issues
            critical_errors = error_summary.get("critical_errors", 0)
            error_rate = error_summary.get("error_rate_per_hour", 0)

            # Critical alerts
            critical_alerts = len([a for a in alerts if a.get("severity") == "high"])

            # Database health
            db_health = database_report.get("database_health", {}).get("overall_status", "unknown")

            if critical_errors > 0 or critical_alerts > 0 or db_health == "critical":
                return "critical"
            elif error_rate > 50 or db_health == "degraded":
                return "degraded"
            elif error_rate > 10:
                return "warning"
            else:
                return "healthy"

        except Exception:
            return "unknown"

    def _get_active_alerts(self) -> list:
        """Get active alerts from cache"""
        try:
            alerts = []

            # Get alert keys from cache
            alert_keys = []
            try:
                # This would need a proper way to get cache keys - simplified for demo
                # In production, you'd use Redis KEYS command or maintain an alert index
                for i in range(24):  # Check last 24 hours
                    hour = timezone.now() - timezone.timedelta(hours=i)
                    hour_key = f"alert_*_{hour.strftime('%Y%m%d%H')}*"
                    # alert_keys.extend(cache.keys(hour_key))
            except:
                pass

            # For demo, return sample alerts structure
            return alerts

        except Exception:
            return []

    def _get_system_metrics(self) -> dict:
        """Get basic system metrics"""
        try:
            import psutil

            return {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage("/").percent,
                "load_average": psutil.getloadavg() if hasattr(psutil, "getloadavg") else None,
            }
        except ImportError:
            return {"note": "psutil not available - system metrics unavailable"}
        except Exception:
            return {"error": "Could not retrieve system metrics"}

    def _display_health_overview(self, health_data: dict):
        """Display health overview in console"""
        status = health_data["overall_status"]

        # Overall status
        self.stdout.write(f"Overall Status: {self._colorize_status(status)}")
        self.stdout.write(f"Analysis Period: {health_data['period_hours']} hours")
        self.stdout.write(f"Last Updated: {health_data['timestamp'][:19]}")

        # Error summary
        error_summary = health_data.get("error_summary", {})
        self.stdout.write(f"\n📊 Error Summary:")
        self.stdout.write(f"  Total Errors: {error_summary.get('total_errors', 0)}")
        self.stdout.write(f"  Critical Errors: {error_summary.get('critical_errors', 0)}")
        self.stdout.write(f"  Error Rate/Hour: {error_summary.get('error_rate_per_hour', 0):.1f}")
        self.stdout.write(f"  Affected Users: {error_summary.get('affected_users', 0)}")

        # Performance summary
        perf_summary = health_data.get("performance_summary", {})
        self.stdout.write(f"\n⚡ Performance Summary:")
        self.stdout.write(f"  Total Requests: {perf_summary.get('total_requests', 0)}")
        self.stdout.write(f"  Avg Response Time: {perf_summary.get('average_response_time_ms', 0):.1f}ms")
        self.stdout.write(f"  Success Rate: {perf_summary.get('success_rate', 0):.1f}%")
        self.stdout.write(f"  Slow Requests: {perf_summary.get('slow_request_rate', 0):.1f}%")

        # Database health
        db_health = health_data.get("database_health", {})
        db_status = db_health.get("overall_status", "unknown")
        self.stdout.write(f"\n🗄️  Database Health: {self._colorize_status(db_status)}")
        self.stdout.write(f"  Models Analyzed: {db_health.get('models_analyzed', 0)}")
        self.stdout.write(f"  Performance Issues: {db_health.get('total_issues', 0)}")

        # Active alerts
        alerts = health_data.get("active_alerts", [])
        alert_count = len(alerts)
        if alert_count > 0:
            self.stdout.write(f"\n🚨 Active Alerts: {alert_count}")
            for alert in alerts[:3]:  # Show first 3
                severity = alert.get("severity", "unknown")
                alert_type = alert.get("alert_type", "unknown")
                self.stdout.write(f"  [{severity.upper()}] {alert_type}")
        else:
            self.stdout.write(f"\n✅ No Active Alerts")

        # System metrics
        sys_metrics = health_data.get("system_metrics", {})
        if "cpu_percent" in sys_metrics:
            self.stdout.write(f"\n💻 System Resources:")
            self.stdout.write(f"  CPU Usage: {sys_metrics.get('cpu_percent', 0):.1f}%")
            self.stdout.write(f"  Memory Usage: {sys_metrics.get('memory_percent', 0):.1f}%")
            self.stdout.write(f"  Disk Usage: {sys_metrics.get('disk_percent', 0):.1f}%")

    def _display_error_analysis(self, error_summary: dict):
        """Display detailed error analysis"""
        total_errors = error_summary.get("total_errors", 0)

        if total_errors == 0:
            self.stdout.write("✅ No errors found in the specified time period")
            return

        self.stdout.write(f"📈 Error Statistics:")
        self.stdout.write(f"  Total Errors: {total_errors}")
        self.stdout.write(f"  Unique Errors: {error_summary.get('unique_errors', 0)}")
        self.stdout.write(f"  Critical Errors: {error_summary.get('critical_errors', 0)}")
        self.stdout.write(f"  Error Rate/Hour: {error_summary.get('error_rate_per_hour', 0):.2f}")
        self.stdout.write(f"  Affected Users: {error_summary.get('affected_users', 0)}")
        self.stdout.write(f"  Affected Establishments: {error_summary.get('affected_establishments', 0)}")

        # Most common errors
        common_errors = error_summary.get("most_common_errors", {})
        if common_errors:
            self.stdout.write(f"\n🔍 Most Common Errors:")
            for error_type, count in sorted(common_errors.items(), key=lambda x: x[1], reverse=True)[:5]:
                self.stdout.write(f"  {error_type}: {count} occurrences")

        # Recent alerts
        recent_alerts = error_summary.get("recent_alerts", [])
        if recent_alerts:
            self.stdout.write(f"\n🚨 Recent Alerts:")
            for alert in recent_alerts[:5]:
                alert_type = alert.get("alert_type", "unknown")
                timestamp = alert.get("timestamp", "")[:19]
                severity = alert.get("severity", "unknown")
                self.stdout.write(f"  [{severity.upper()}] {alert_type} at {timestamp}")

    def _display_performance_analysis(self, perf_summary: dict):
        """Display detailed performance analysis"""
        total_requests = perf_summary.get("total_requests", 0)

        if total_requests == 0:
            self.stdout.write("📊 No performance data available for the specified time period")
            return

        self.stdout.write(f"📊 Performance Statistics:")
        self.stdout.write(f"  Total Requests: {total_requests}")
        self.stdout.write(f"  Average Response Time: {perf_summary.get('average_response_time_ms', 0):.2f}ms")
        self.stdout.write(f"  Success Rate: {perf_summary.get('success_rate', 0):.2f}%")
        self.stdout.write(f"  Slow Request Rate: {perf_summary.get('slow_request_rate', 0):.2f}%")

        # Slowest operations
        slowest_ops = perf_summary.get("slowest_operations", [])
        if slowest_ops:
            self.stdout.write(f"\n🐌 Slowest Operations:")
            for operation in slowest_ops[:5]:
                op_name = operation.get("operation", "unknown")
                avg_time = operation.get("average_time_ms", 0)
                self.stdout.write(f"  {op_name}: {avg_time:.2f}ms average")

        # Operations performance
        ops_perf = perf_summary.get("operations_performance", {})
        if ops_perf:
            self.stdout.write(f"\n⚡ Operations Performance:")
            for operation, metrics in list(ops_perf.items())[:5]:
                success_rate = metrics.get("success_rate", 0)
                avg_time = metrics.get("average_time_ms", 0)
                self.stdout.write(f"  {operation}: {avg_time:.1f}ms, {success_rate:.1f}% success")

    def _display_alerts(self, alerts: list):
        """Display active alerts"""
        if not alerts:
            self.stdout.write("✅ No active alerts")
            return

        # Group alerts by severity
        critical_alerts = [a for a in alerts if a.get("severity") == "high"]
        warning_alerts = [a for a in alerts if a.get("severity") == "medium"]
        info_alerts = [a for a in alerts if a.get("severity") == "low"]

        if critical_alerts:
            self.stdout.write(self.style.ERROR(f"🚨 CRITICAL ALERTS ({len(critical_alerts)}):"))
            for alert in critical_alerts:
                alert_type = alert.get("alert_type", "unknown")
                timestamp = alert.get("timestamp", "")[:19]
                self.stdout.write(f"  {alert_type} at {timestamp}")

        if warning_alerts:
            self.stdout.write(self.style.WARNING(f"\n⚠️  WARNING ALERTS ({len(warning_alerts)}):"))
            for alert in warning_alerts:
                alert_type = alert.get("alert_type", "unknown")
                timestamp = alert.get("timestamp", "")[:19]
                self.stdout.write(f"  {alert_type} at {timestamp}")

        if info_alerts:
            self.stdout.write(self.style.NOTICE(f"\n💡 INFO ALERTS ({len(info_alerts)}):"))
            for alert in info_alerts:
                alert_type = alert.get("alert_type", "unknown")
                timestamp = alert.get("timestamp", "")[:19]
                self.stdout.write(f"  {alert_type} at {timestamp}")

    def _display_database_health(self, db_report: dict):
        """Display database health status"""
        db_health = db_report.get("database_health", {})

        status = db_health.get("overall_status", "unknown")
        self.stdout.write(f"Overall Status: {self._colorize_status(status)}")
        self.stdout.write(f"Models Analyzed: {db_health.get('models_analyzed', 0)}")
        self.stdout.write(f"Total Issues: {db_health.get('total_issues', 0)}")

        # Performance summary
        perf_summary = db_report.get("performance_summary", {})
        self.stdout.write(f"\n📊 Database Performance:")
        self.stdout.write(f"  Total Records: {perf_summary.get('total_records', 0):,}")
        self.stdout.write(f"  Total Size: {perf_summary.get('total_size_mb', 0):.2f} MB")
        self.stdout.write(f"  Large Tables: {perf_summary.get('large_tables_count', 0)}")

        # Critical issues
        critical_issues = db_report.get("critical_issues", [])
        if critical_issues:
            self.stdout.write(f"\n🚨 Critical Database Issues:")
            for issue in critical_issues[:5]:
                issue_type = issue.get("type", "unknown")
                description = issue.get("description", "No description")
                self.stdout.write(f"  {issue_type}: {description}")

        # Index optimization
        index_opt = db_report.get("index_optimization", {})
        if index_opt:
            self.stdout.write(f"\n🔧 Index Optimization:")
            self.stdout.write(f"  Total Recommendations: {index_opt.get('total_recommendations', 0)}")
            self.stdout.write(f"  High Priority: {index_opt.get('high_priority', 0)}")

    def _colorize_status(self, status: str) -> str:
        """Apply color to status"""
        if status == "healthy":
            return self.style.SUCCESS(status.upper())
        elif status in ["warning", "degraded"]:
            return self.style.WARNING(status.upper())
        elif status == "critical":
            return self.style.ERROR(status.upper())
        else:
            return self.style.NOTICE(status.upper())
