"""
Session Deduplication Service (2025 Standards)
Prevents duplicate scan tracking using privacy-safe browser fingerprinting
"""

from datetime import timedelta
from typing import TYPE_CHECKING, Optional, Tuple

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

if TYPE_CHECKING:
    from history.models import HistoryScan


class DeduplicationService:
    """Prevent duplicate scan tracking using modern techniques"""

    # Default deduplication timeframe (configurable)
    DEFAULT_TIMEFRAME_MINUTES = 15

    @staticmethod
    def check_duplicate_scan(
        session_hash: str, history_id: int, timeframe_minutes: Optional[int] = None
    ) -> Tuple[bool, Optional["HistoryScan"]]:
        """
        Check if this is a duplicate scan within the specified timeframe

        Args:
            session_hash: Privacy-safe browser fingerprint
            history_id: Production/history ID being scanned
            timeframe_minutes: Deduplication window (default: 15 minutes)

        Returns:
            Tuple of (is_duplicate: bool, original_scan: HistoryScan or None)
        """
        from ..models import HistoryScan

        if not session_hash or not history_id:
            return False, None

        timeframe = timeframe_minutes or DeduplicationService.DEFAULT_TIMEFRAME_MINUTES
        cutoff_time = timezone.now() - timedelta(minutes=timeframe)

        # Check for existing scan from same session within timeframe
        existing_scan = (
            HistoryScan.objects.filter(
                session_hash=session_hash,
                history_id=history_id,
                date__gte=cutoff_time,
                is_duplicate=False,  # Only consider original scans
            )
            .order_by("-date")
            .first()
        )

        is_duplicate = existing_scan is not None

        return is_duplicate, existing_scan

    @staticmethod
    def check_duplicate_by_ip_hash(
        ip_hash: str, history_id: int, timeframe_minutes: Optional[int] = None
    ) -> Tuple[bool, Optional["HistoryScan"]]:
        """
        Fallback deduplication check using IP hash (when session fingerprinting fails)

        Args:
            ip_hash: Hashed IP address
            history_id: Production/history ID being scanned
            timeframe_minutes: Deduplication window (default: 15 minutes)

        Returns:
            Tuple of (is_duplicate: bool, original_scan: HistoryScan or None)
        """
        from ..models import HistoryScan

        if not ip_hash or not history_id:
            return False, None

        timeframe = timeframe_minutes or DeduplicationService.DEFAULT_TIMEFRAME_MINUTES
        cutoff_time = timezone.now() - timedelta(minutes=timeframe)

        # Check for existing scan from same IP within timeframe
        existing_scan = (
            HistoryScan.objects.filter(
                ip_hash=ip_hash, history_id=history_id, date__gte=cutoff_time, is_duplicate=False
            )
            .order_by("-date")
            .first()
        )

        is_duplicate = existing_scan is not None

        return is_duplicate, existing_scan

    @staticmethod
    def mark_as_duplicate(original_scan: "HistoryScan", duplicate_scan: "HistoryScan") -> bool:
        """
        Mark scan as duplicate and link to original

        Args:
            original_scan: The original scan found within timeframe
            duplicate_scan: The new scan to mark as duplicate

        Returns:
            True if successfully marked as duplicate
        """
        try:
            duplicate_scan.is_duplicate = True
            duplicate_scan.original_scan = original_scan
            duplicate_scan.save(update_fields=["is_duplicate", "original_scan"])

            # Update cache with duplicate info
            DeduplicationService._cache_duplicate_info(duplicate_scan)

            return True
        except Exception:
            return False

    @staticmethod
    def get_deduplication_strategy(session_hash: str, ip_hash: str) -> str:
        """
        Determine the best deduplication strategy based on available data

        Returns:
            'session' | 'ip' | 'none'
        """
        if session_hash:
            return "session"
        elif ip_hash:
            return "ip"
        else:
            return "none"

    @staticmethod
    def check_comprehensive_duplicate(
        session_hash: str, ip_hash: str, history_id: int, timeframe_minutes: Optional[int] = None
    ) -> Tuple[bool, Optional["HistoryScan"], str]:
        """
        Comprehensive duplicate check using multiple strategies

        Args:
            session_hash: Privacy-safe browser fingerprint
            ip_hash: Hashed IP address
            history_id: Production/history ID being scanned
            timeframe_minutes: Deduplication window

        Returns:
            Tuple of (is_duplicate: bool, original_scan: HistoryScan or None, method: str)
        """
        # Try session-based deduplication first (most accurate)
        if session_hash:
            is_duplicate, original_scan = DeduplicationService.check_duplicate_scan(
                session_hash, history_id, timeframe_minutes
            )
            if is_duplicate:
                return True, original_scan, "session"

        # Fallback to IP-based deduplication
        if ip_hash:
            is_duplicate, original_scan = DeduplicationService.check_duplicate_by_ip_hash(
                ip_hash, history_id, timeframe_minutes
            )
            if is_duplicate:
                return True, original_scan, "ip"

        # No duplicates found
        return False, None, "none"

    @staticmethod
    def _cache_duplicate_info(scan: "HistoryScan") -> None:
        """
        Cache duplicate scan information for analytics
        """
        cache_key = f"duplicate_scan:{scan.id}"
        cache_data = {
            "is_duplicate": scan.is_duplicate,
            "original_scan_id": scan.original_scan.id if scan.original_scan else None,
            "timestamp": scan.date.isoformat(),
        }
        # Cache for 1 hour
        cache.set(cache_key, cache_data, 3600)

    @staticmethod
    def get_duplicate_stats(history_id: int, days: int = 7) -> dict:
        """
        Get duplicate scan statistics for analytics

        Args:
            history_id: Production/history ID
            days: Number of days to analyze

        Returns:
            Dictionary with duplicate statistics
        """
        from ..models import HistoryScan

        start_date = timezone.now() - timedelta(days=days)

        scans = HistoryScan.objects.filter(history_id=history_id, date__gte=start_date)

        total_scans = scans.count()
        duplicate_scans = scans.filter(is_duplicate=True).count()
        unique_scans = total_scans - duplicate_scans

        # Calculate duplicate rate
        duplicate_rate = (duplicate_scans / total_scans * 100) if total_scans > 0 else 0

        return {
            "total_scans": total_scans,
            "unique_scans": unique_scans,
            "duplicate_scans": duplicate_scans,
            "duplicate_rate": round(duplicate_rate, 2),
            "period_days": days,
        }

    @staticmethod
    def cleanup_old_duplicates(days_old: int = 30) -> int:
        """
        Clean up very old duplicate scans to save storage

        Args:
            days_old: Delete duplicates older than this many days

        Returns:
            Number of duplicates deleted
        """
        from ..models import HistoryScan

        cutoff_date = timezone.now() - timedelta(days=days_old)

        old_duplicates = HistoryScan.objects.filter(is_duplicate=True, date__lt=cutoff_date)

        count = old_duplicates.count()
        old_duplicates.delete()

        return count


class SessionAnalyticsService:
    """Advanced session analytics for scan insights"""

    @staticmethod
    def get_session_engagement_score(
        session_hash: str,
        time_on_page: Optional[float] = None,
        interactions: Optional[int] = None,
        feedback_given: bool = False,
    ) -> float:
        """
        Calculate engagement score for a session (0.0 to 1.0)

        Args:
            session_hash: Session identifier
            time_on_page: Seconds spent on page
            interactions: Number of interactions (clicks, scrolls, etc.)
            feedback_given: Whether user left feedback/comment

        Returns:
            Engagement score between 0.0 and 1.0
        """
        score = 0.0

        # Time on page scoring (30% of total score)
        if time_on_page:
            if time_on_page >= 60:  # 1+ minutes = full points
                score += 0.3
            elif time_on_page >= 30:  # 30+ seconds = partial points
                score += 0.2
            elif time_on_page >= 10:  # 10+ seconds = minimal points
                score += 0.1

        # Interaction scoring (40% of total score)
        if interactions:
            if interactions >= 10:  # High interaction
                score += 0.4
            elif interactions >= 5:  # Medium interaction
                score += 0.3
            elif interactions >= 2:  # Some interaction
                score += 0.2
            elif interactions >= 1:  # Minimal interaction
                score += 0.1

        # Feedback bonus (30% of total score)
        if feedback_given:
            score += 0.3

        return min(score, 1.0)

    @staticmethod
    def detect_bounce(
        session_hash: str, time_on_page: Optional[float] = None, interactions: Optional[int] = None
    ) -> bool:
        """
        Detect if this is a bounce (low engagement) session
        """
        # Bounce criteria: less than 10 seconds and no interactions
        is_quick_exit = time_on_page and time_on_page < 10
        has_no_interactions = not interactions or interactions == 0

        return is_quick_exit and has_no_interactions

    @staticmethod
    def get_session_insights(history_id: int, days: int = 30) -> dict:
        """
        Get comprehensive session insights for a production
        """
        from ..models import HistoryScan

        start_date = timezone.now() - timedelta(days=days)

        scans = HistoryScan.objects.filter(
            history_id=history_id, date__gte=start_date, is_duplicate=False  # Only count unique sessions
        )

        total_sessions = scans.count()

        if total_sessions == 0:
            return {"total_sessions": 0, "avg_engagement": 0, "bounce_rate": 0, "feedback_rate": 0}

        # Calculate averages
        total_engagement = sum(scan.engagement_score for scan in scans)
        avg_engagement = total_engagement / total_sessions

        # Count feedback sessions
        feedback_sessions = scans.exclude(comment__isnull=True).exclude(comment="").count()
        feedback_rate = (feedback_sessions / total_sessions) * 100

        # Estimate bounce rate (sessions with very low engagement)
        low_engagement_sessions = scans.filter(engagement_score__lt=0.1).count()
        bounce_rate = (low_engagement_sessions / total_sessions) * 100

        return {
            "total_sessions": total_sessions,
            "avg_engagement": round(avg_engagement, 3),
            "bounce_rate": round(bounce_rate, 2),
            "feedback_rate": round(feedback_rate, 2),
            "period_days": days,
        }
