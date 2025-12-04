"""
Security Monitoring and Alerting System for Trazo
Real-time security event detection and notification system
"""

import json
import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.utils import timezone

import requests

logger = logging.getLogger(__name__)


class SecurityEventDetector:
    """
    Real-time security event detection and analysis
    """

    def __init__(self):
        self.cache_prefix = "security_events"
        self.alert_cooldown = 300  # 5 minutes between similar alerts

    def detect_attack_patterns(self) -> List[Dict]:
        """
        Detect ongoing security attacks based on patterns
        """
        events = []

        # 1. Detect coordinated attacks (multiple IPs with similar patterns)
        coordinated_attack = self._detect_coordinated_attack()
        if coordinated_attack:
            events.append(
                {
                    "type": "coordinated_attack",
                    "severity": "critical",
                    "description": f"Coordinated attack detected from {len(coordinated_attack['ips'])} IPs",
                    "details": coordinated_attack,
                    "timestamp": timezone.now().isoformat(),
                }
            )

        # 2. Detect credential stuffing attacks
        credential_stuffing = self._detect_credential_stuffing()
        if credential_stuffing:
            events.append(
                {
                    "type": "credential_stuffing",
                    "severity": "high",
                    "description": f"Credential stuffing attack: {credential_stuffing['attempts']} attempts",
                    "details": credential_stuffing,
                    "timestamp": timezone.now().isoformat(),
                }
            )

        # 3. Detect API abuse patterns
        api_abuse = self._detect_api_abuse()
        if api_abuse:
            events.append(
                {
                    "type": "api_abuse",
                    "severity": "medium",
                    "description": f"API abuse detected: {api_abuse['requests_per_minute']}/min",
                    "details": api_abuse,
                    "timestamp": timezone.now().isoformat(),
                }
            )

        # 4. Detect data exfiltration attempts
        data_exfiltration = self._detect_data_exfiltration()
        if data_exfiltration:
            events.append(
                {
                    "type": "data_exfiltration",
                    "severity": "critical",
                    "description": f"Potential data exfiltration: {data_exfiltration['data_accessed']} records",
                    "details": data_exfiltration,
                    "timestamp": timezone.now().isoformat(),
                }
            )

        return events

    def _detect_coordinated_attack(self) -> Optional[Dict]:
        """Detect coordinated attacks from multiple IPs"""
        # Get recent blocked IPs
        blacklist = cache.get("ddos_advanced_blacklist", set())
        if len(blacklist) < 5:  # Need at least 5 IPs for coordination
            return None

        # Check if these IPs were blocked around the same time
        recent_blocks = cache.get("recent_blocks", {})
        now = time.time()

        # Group by time windows (5-minute windows)
        time_windows = defaultdict(list)
        for ip in blacklist:
            block_time = recent_blocks.get(ip, 0)
            if now - block_time < 3600:  # Last hour
                window = int(block_time // 300) * 300  # 5-minute window
                time_windows[window].append(ip)

        # Find windows with multiple IPs (coordination indicator)
        for window, ips in time_windows.items():
            if len(ips) >= 5:
                return {
                    "ips": ips,
                    "time_window": window,
                    "coordination_score": len(ips),
                }

        return None

    def _detect_credential_stuffing(self) -> Optional[Dict]:
        """Detect credential stuffing attacks"""
        auth_failures = cache.get("auth_failures_summary", {})
        now = time.time()

        # Count recent auth failures
        recent_failures = 0
        unique_ips = set()
        unique_usernames = set()

        for key, data in auth_failures.items():
            if now - data.get("timestamp", 0) < 300:  # Last 5 minutes
                recent_failures += data.get("count", 0)
                unique_ips.add(data.get("ip", ""))
                unique_usernames.add(data.get("username", ""))

        # Criteria for credential stuffing:
        # - High volume of failures (>50 in 5 minutes)
        # - Multiple IPs
        # - Multiple usernames
        if recent_failures > 50 and len(unique_ips) > 10 and len(unique_usernames) > 20:

            return {
                "attempts": recent_failures,
                "unique_ips": len(unique_ips),
                "unique_usernames": len(unique_usernames),
                "time_window": 300,
            }

        return None

    def _detect_api_abuse(self) -> Optional[Dict]:
        """Detect API abuse patterns"""
        api_requests = cache.get("api_requests_summary", {})
        now = time.time()

        total_requests = 0
        unique_endpoints = set()

        for endpoint, data in api_requests.items():
            if now - data.get("last_request", 0) < 60:  # Last minute
                total_requests += data.get("count", 0)
                unique_endpoints.add(endpoint)

        requests_per_minute = total_requests

        # Criteria for API abuse:
        # - Very high request volume (>1000/min)
        # - Hitting many different endpoints (>50)
        if requests_per_minute > 1000 and len(unique_endpoints) > 50:
            return {
                "requests_per_minute": requests_per_minute,
                "unique_endpoints": len(unique_endpoints),
                "time_window": 60,
            }

        return None

    def _detect_data_exfiltration(self) -> Optional[Dict]:
        """Detect potential data exfiltration"""
        # This would typically analyze access patterns to sensitive data
        # For now, we'll check for unusual data access patterns

        carbon_data_access = cache.get("carbon_data_access", {})
        now = time.time()

        total_records = 0
        unique_ips = set()

        for ip, data in carbon_data_access.items():
            if now - data.get("timestamp", 0) < 300:  # Last 5 minutes
                total_records += data.get("records_accessed", 0)
                unique_ips.add(ip)

        # Criteria for potential exfiltration:
        # - Large volume of data accessed (>1000 records in 5 minutes)
        # - From few IPs (concentrated access)
        if total_records > 1000 and len(unique_ips) < 3:
            return {
                "data_accessed": total_records,
                "unique_ips": len(unique_ips),
                "time_window": 300,
            }

        return None


class SecurityAlertManager:
    """
    Manages security alerts and notifications
    """

    def __init__(self):
        self.webhook_url = getattr(settings, "SECURITY_ALERT_WEBHOOK_URL", "")
        self.alert_cache = "security_alerts_sent"

    def should_send_alert(self, event: Dict) -> bool:
        """Check if alert should be sent (avoid spam)"""
        event_key = f"{event['type']}_{event['severity']}"
        last_sent = cache.get(f"{self.alert_cache}_{event_key}", 0)

        # Don't send same type of alert more than once every 5 minutes
        if time.time() - last_sent < 300:
            return False

        cache.set(f"{self.alert_cache}_{event_key}", time.time(), 3600)
        return True

    def send_alert(self, event: Dict):
        """Send security alert via webhook"""
        if not self.should_send_alert(event):
            return

        if not self.webhook_url:
            logger.warning("Security alert webhook URL not configured")
            return

        # Format alert message
        color = {
            "critical": "#ff0000",  # Red
            "high": "#ff8c00",  # Orange
            "medium": "#ffff00",  # Yellow
            "low": "#00ff00",  # Green
        }.get(event.get("severity", "medium"), "#ffff00")

        payload = {
            "text": f"🚨 Security Alert: {event['description']}",
            "attachments": [
                {
                    "color": color,
                    "fields": [
                        {"title": "Event Type", "value": event["type"], "short": True},
                        {"title": "Severity", "value": event["severity"].upper(), "short": True},
                        {"title": "Time", "value": event["timestamp"], "short": True},
                        {"title": "Details", "value": json.dumps(event["details"], indent=2), "short": False},
                    ],
                }
            ],
        }

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info(f"Security alert sent successfully: {event['type']}")
            else:
                logger.error(f"Failed to send security alert: HTTP {response.status_code}")
        except requests.RequestException as e:
            logger.error(f"Error sending security alert: {e}")

    def generate_security_report(self) -> Dict:
        """Generate summary security report"""
        now = time.time()
        last_24h = now - 86400

        # Get various security metrics
        report = {
            "timestamp": timezone.now().isoformat(),
            "period": "24_hours",
            "metrics": {
                "blocked_ips": len(cache.get("ddos_advanced_blacklist", set())),
                "rate_limit_violations": self._count_rate_limit_violations(last_24h),
                "auth_failures": self._count_auth_failures(last_24h),
                "suspicious_requests": self._count_suspicious_requests(last_24h),
                "circuit_breaker_trips": self._count_circuit_breaker_trips(last_24h),
            },
            "top_threats": self._get_top_threats(last_24h),
            "recommendations": self._generate_recommendations(),
        }

        return report

    def _count_rate_limit_violations(self, since: float) -> int:
        """Count rate limit violations since timestamp"""
        # This would query logs or cache for rate limit violations
        return cache.get("rate_limit_violations_24h", 0)

    def _count_auth_failures(self, since: float) -> int:
        """Count authentication failures since timestamp"""
        auth_failures = cache.get("auth_failures_summary", {})
        count = 0
        for data in auth_failures.values():
            if data.get("timestamp", 0) > since:
                count += data.get("count", 0)
        return count

    def _count_suspicious_requests(self, since: float) -> int:
        """Count suspicious requests since timestamp"""
        return cache.get("suspicious_requests_24h", 0)

    def _count_circuit_breaker_trips(self, since: float) -> int:
        """Count circuit breaker trips since timestamp"""
        return cache.get("circuit_breaker_trips_24h", 0)

    def _get_top_threats(self, since: float) -> List[Dict]:
        """Get top security threats"""
        threats = []

        # Top blocked IPs
        blacklist = cache.get("ddos_advanced_blacklist", set())
        for ip in list(blacklist)[:5]:  # Top 5
            threats.append(
                {
                    "type": "blocked_ip",
                    "value": ip,
                    "threat_score": 80,  # Would calculate actual score
                }
            )

        return threats

    def _generate_recommendations(self) -> List[str]:
        """Generate security recommendations"""
        recommendations = []

        blocked_ips = len(cache.get("ddos_advanced_blacklist", set()))
        if blocked_ips > 100:
            recommendations.append("Consider implementing geographic IP filtering")

        auth_failures = self._count_auth_failures(time.time() - 86400)
        if auth_failures > 1000:
            recommendations.append("Enable additional authentication factors (2FA)")

        if not recommendations:
            recommendations.append("Security posture is currently stable")

        return recommendations


class SecurityMonitoringCommand(BaseCommand):
    """
    Django management command for security monitoring
    Usage: python manage.py monitor_security
    """

    help = "Monitor security events and send alerts"

    def __init__(self):
        super().__init__()
        self.detector = SecurityEventDetector()
        self.alert_manager = SecurityAlertManager()

    def handle(self, *args, **options):
        """Run security monitoring cycle"""
        self.stdout.write("Starting security monitoring...")

        try:
            # Detect security events
            events = self.detector.detect_attack_patterns()

            # Send alerts for critical events
            for event in events:
                if event["severity"] in ["critical", "high"]:
                    self.alert_manager.send_alert(event)
                    self.stdout.write(self.style.WARNING(f"Alert sent: {event['type']} - {event['description']}"))

            # Generate and log security report
            if len(events) > 0:
                report = self.alert_manager.generate_security_report()
                logger.info(f"Security report: {json.dumps(report, indent=2)}")

            self.stdout.write(self.style.SUCCESS(f"Security monitoring completed. {len(events)} events detected."))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Security monitoring error: {e}"))
            logger.error(f"Security monitoring error: {e}")


# Utility functions for integration with middleware
def record_security_event(event_type: str, ip: str, details: Dict):
    """Record a security event for monitoring"""
    event_key = f"security_event_{event_type}_{ip}"
    cache.set(
        event_key,
        {
            "timestamp": time.time(),
            "ip": ip,
            "details": details,
        },
        3600,
    )  # Store for 1 hour


def record_auth_failure(ip: str, username: str, endpoint: str):
    """Record authentication failure for monitoring"""
    failures = cache.get("auth_failures_summary", {})
    key = f"{ip}_{username}_{endpoint}"

    if key in failures:
        failures[key]["count"] += 1
        failures[key]["last_attempt"] = time.time()
    else:
        failures[key] = {
            "ip": ip,
            "username": username,
            "endpoint": endpoint,
            "count": 1,
            "timestamp": time.time(),
            "last_attempt": time.time(),
        }

    cache.set("auth_failures_summary", failures, 3600)


def record_api_request(endpoint: str, ip: str, status_code: int):
    """Record API request for monitoring"""
    requests_data = cache.get("api_requests_summary", {})

    if endpoint in requests_data:
        requests_data[endpoint]["count"] += 1
        requests_data[endpoint]["last_request"] = time.time()
        if status_code >= 400:
            requests_data[endpoint]["errors"] += 1
    else:
        requests_data[endpoint] = {
            "count": 1,
            "errors": 1 if status_code >= 400 else 0,
            "last_request": time.time(),
            "first_request": time.time(),
        }

    cache.set("api_requests_summary", requests_data, 3600)


def record_carbon_data_access(ip: str, records_count: int):
    """Record carbon data access for exfiltration detection"""
    access_data = cache.get("carbon_data_access", {})

    if ip in access_data:
        access_data[ip]["records_accessed"] += records_count
        access_data[ip]["last_access"] = time.time()
    else:
        access_data[ip] = {
            "records_accessed": records_count,
            "timestamp": time.time(),
            "last_access": time.time(),
        }

    cache.set("carbon_data_access", access_data, 600)  # 10 minutes
