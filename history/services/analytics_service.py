"""
Privacy-Safe Analytics Service (2025 Standards)
Provides aggregated insights for the Commercial dashboard without exposing individual data
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from django.core.cache import cache
from django.db.models import Avg, Count, F, Q
from django.db.models.functions import Length
from django.utils import timezone


class AnalyticsService:
    """Privacy-compliant analytics following 2025 data protection standards"""

    @staticmethod
    def get_establishment_insights(establishment_id: int, days: int = 30) -> Dict:
        """
        Generate privacy-safe analytics for an establishment

        Args:
            establishment_id: The establishment to analyze
            days: Number of days to analyze (max 365)

        Returns:
            Dictionary with aggregated insights
        """
        from ..models import HistoryScan

        # Cache key for performance
        cache_key = f"analytics_insights:{establishment_id}:{days}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result

        start_date = timezone.now() - timedelta(days=days)

        # Base queryset - only high-quality scans
        base_scans = HistoryScan.objects.filter(
            history__parcel__establishment_id=establishment_id,
            date__gte=start_date,
            is_duplicate=False,  # Exclude duplicates
            bot_score__lt=0.5,  # Exclude likely bots
        ).select_related("history__product", "history__parcel")

        # Generate comprehensive insights
        insights = {
            **AnalyticsService._get_traffic_insights(base_scans),
            **AnalyticsService._get_engagement_insights(base_scans),
            **AnalyticsService._get_geographic_insights(base_scans),
            **AnalyticsService._get_product_insights(base_scans),
            **AnalyticsService._get_quality_insights(base_scans),
            **AnalyticsService._get_temporal_insights(base_scans, days),
            **AnalyticsService._get_feedback_insights(base_scans),
            **AnalyticsService._get_referrer_insights(base_scans),
            "period_days": days,
            "generated_at": timezone.now().isoformat(),
        }

        # Cache for 15 minutes
        cache.set(cache_key, insights, 900)

        return insights

    @staticmethod
    def _get_traffic_insights(scans) -> Dict:
        """
        Get traffic and visitor insights
        """
        total_scans = scans.count()

        if total_scans == 0:
            return {
                "traffic": {
                    "total_scans": 0,
                    "unique_sessions": 0,
                    "estimated_visitors": 0,
                    "scan_rate": 0,
                }
            }

        # Unique sessions (privacy-safe visitor estimation)
        unique_sessions = scans.values("session_hash").distinct().count()

        # Estimate unique visitors (sessions might span multiple days)
        # Conservative estimate: sessions / 1.2 (accounting for multi-day visitors)
        estimated_visitors = max(1, int(unique_sessions / 1.2))

        # Scan rate (scans per unique session)
        scan_rate = round(total_scans / max(unique_sessions, 1), 2)

        return {
            "traffic": {
                "total_scans": total_scans,
                "unique_sessions": unique_sessions,
                "estimated_visitors": estimated_visitors,
                "scan_rate": scan_rate,
            }
        }

    @staticmethod
    def _get_engagement_insights(scans) -> Dict:
        """
        Get engagement quality insights
        """
        total_scans = scans.count()

        if total_scans == 0:
            return {"engagement": {"avg_score": 0, "high_engagement_rate": 0}}

        # Average engagement score
        avg_engagement = scans.aggregate(avg_score=Avg("engagement_score"))["avg_score"] or 0

        # High engagement rate (score > 0.5)
        high_engagement_count = scans.filter(engagement_score__gt=0.5).count()
        high_engagement_rate = (high_engagement_count / total_scans) * 100

        # Engagement distribution
        engagement_buckets = {
            "low": scans.filter(engagement_score__lt=0.3).count(),
            "medium": scans.filter(engagement_score__gte=0.3, engagement_score__lt=0.7).count(),
            "high": scans.filter(engagement_score__gte=0.7).count(),
        }

        return {
            "engagement": {
                "avg_score": round(avg_engagement, 3),
                "high_engagement_rate": round(high_engagement_rate, 2),
                "distribution": engagement_buckets,
            }
        }

    @staticmethod
    def _get_geographic_insights(scans) -> Dict:
        """
        Get privacy-safe geographic insights (region/country level only)
        """
        # Top regions (limit to protect privacy)
        top_regions = list(
            scans.filter(region__isnull=False)
            .exclude(region="")
            .values("region", "country_code")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )

        # Country distribution
        country_distribution = list(
            scans.filter(country_code__isnull=False)
            .exclude(country_code="")
            .values("country_code")
            .annotate(count=Count("id"))
            .order_by("-count")[:15]
        )

        return {
            "geography": {
                "top_regions": top_regions,
                "country_distribution": country_distribution,
            }
        }

    @staticmethod
    def _get_product_insights(scans) -> Dict:
        """
        Get product-specific insights
        """
        # Top products by scan volume
        top_products = list(
            scans.filter(history__product__isnull=False)
            .values("history__product__name", "history__product_id")
            .annotate(count=Count("id"), avg_engagement=Avg("engagement_score"))
            .order_by("-count")[:10]
        )

        # Product engagement comparison
        for product in top_products:
            product["avg_engagement"] = round(product["avg_engagement"] or 0, 3)

        return {
            "products": {
                "top_by_scans": top_products,
            }
        }

    @staticmethod
    def _get_quality_insights(scans) -> Dict:
        """
        Get data quality insights
        """
        total_scans = scans.count()

        if total_scans == 0:
            return {"quality": {"human_rate": 0, "avg_bot_score": 0}}

        # Human verification rate
        human_verified = scans.filter(is_verified_human=True).count()
        human_rate = (human_verified / total_scans) * 100

        # Average bot score
        avg_bot_score = scans.aggregate(avg_score=Avg("bot_score"))["avg_score"] or 0

        # Quality distribution
        quality_buckets = {
            "high_quality": scans.filter(bot_score__lt=0.2, engagement_score__gt=0.3).count(),
            "medium_quality": scans.filter(bot_score__lt=0.5, engagement_score__gt=0.1).count(),
            "low_quality": scans.filter(Q(bot_score__gte=0.5) | Q(engagement_score__lte=0.1)).count(),
        }

        return {
            "quality": {
                "human_rate": round(human_rate, 2),
                "avg_bot_score": round(avg_bot_score, 3),
                "distribution": quality_buckets,
            }
        }

    @staticmethod
    def _get_temporal_insights(scans, days: int) -> Dict:
        """
        Get time-based insights
        """
        # Daily scan counts for trend analysis
        daily_scans = []
        for i in range(min(days, 30)):  # Limit to 30 days for performance
            date = timezone.now().date() - timedelta(days=i)
            day_scans = scans.filter(date__date=date).count()

            daily_scans.append({"date": date.isoformat(), "scans": day_scans})

        daily_scans.reverse()  # Chronological order

        # Peak hours analysis (if we have time data)
        # This would require frontend to send hour information

        return {
            "temporal": {
                "daily_scans": daily_scans,
            }
        }

    @staticmethod
    def _get_feedback_insights(scans) -> Dict:
        """
        Get feedback and comment insights
        """
        # Scans with comments
        with_comments = scans.exclude(comment__isnull=True).exclude(comment="")
        comment_count = with_comments.count()

        total_scans = scans.count()
        feedback_rate = (comment_count / total_scans * 100) if total_scans > 0 else 0

        # Scan type distribution
        scan_type_distribution = list(scans.values("scan_type").annotate(count=Count("id")).order_by("-count"))

        # Average comment length (privacy-safe metric)
        avg_comment_length = with_comments.aggregate(avg_length=Avg(Length("comment")))["avg_length"] or 0

        return {
            "feedback": {
                "total_comments": comment_count,
                "feedback_rate": round(feedback_rate, 2),
                "scan_type_distribution": scan_type_distribution,
                "avg_comment_length": round(avg_comment_length, 1),
            }
        }

    @staticmethod
    def _get_referrer_insights(scans) -> Dict:
        """
        Get referrer source insights
        """
        # Referrer type distribution
        referrer_distribution = list(scans.values("referrer_type").annotate(count=Count("id")).order_by("-count"))

        return {
            "referrers": {
                "source_distribution": referrer_distribution,
            }
        }

    @staticmethod
    def get_comparative_insights(establishment_id: int, days: int = 30) -> Dict:
        """
        Get comparative insights (this establishment vs averages)
        """
        from ..models import HistoryScan

        # Cache key
        cache_key = f"comparative_insights:{establishment_id}:{days}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result

        start_date = timezone.now() - timedelta(days=days)

        # This establishment's data
        establishment_scans = HistoryScan.objects.filter(
            history__parcel__establishment_id=establishment_id,
            date__gte=start_date,
            is_duplicate=False,
            bot_score__lt=0.5,
        )

        # Industry averages (all establishments)
        all_scans = HistoryScan.objects.filter(
            date__gte=start_date,
            is_duplicate=False,
            bot_score__lt=0.5,
        )

        # Calculate metrics for comparison
        establishment_engagement = establishment_scans.aggregate(avg=Avg("engagement_score"))["avg"] or 0

        industry_engagement = all_scans.aggregate(avg=Avg("engagement_score"))["avg"] or 0

        # Feedback rate comparison
        establishment_feedback_rate = (
            establishment_scans.exclude(comment__isnull=True).exclude(comment="").count()
            / max(establishment_scans.count(), 1)
            * 100
        )

        industry_feedback_rate = (
            all_scans.exclude(comment__isnull=True).exclude(comment="").count() / max(all_scans.count(), 1) * 100
        )

        insights = {
            "comparison": {
                "engagement": {
                    "establishment": round(establishment_engagement, 3),
                    "industry_avg": round(industry_engagement, 3),
                    "performance": "above" if establishment_engagement > industry_engagement else "below",
                },
                "feedback_rate": {
                    "establishment": round(establishment_feedback_rate, 2),
                    "industry_avg": round(industry_feedback_rate, 2),
                    "performance": "above" if establishment_feedback_rate > industry_feedback_rate else "below",
                },
            }
        }

        # Cache for 1 hour
        cache.set(cache_key, insights, 3600)

        return insights

    @staticmethod
    def get_scan_trends(establishment_id: int, days: int = 90) -> Dict:
        """
        Get trend analysis for the establishment
        """
        from ..models import HistoryScan

        # Weekly aggregation for trend analysis
        weeks = []
        for week in range(min(days // 7, 12)):  # Max 12 weeks
            week_start = timezone.now() - timedelta(weeks=week + 1)
            week_end = timezone.now() - timedelta(weeks=week)

            week_scans = HistoryScan.objects.filter(
                history__parcel__establishment_id=establishment_id,
                date__gte=week_start,
                date__lt=week_end,
                is_duplicate=False,
                bot_score__lt=0.5,
            )

            weeks.append(
                {
                    "week_start": week_start.date().isoformat(),
                    "total_scans": week_scans.count(),
                    "unique_sessions": week_scans.values("session_hash").distinct().count(),
                    "avg_engagement": week_scans.aggregate(avg=Avg("engagement_score"))["avg"] or 0,
                    "feedback_count": week_scans.exclude(comment__isnull=True).exclude(comment="").count(),
                }
            )

        weeks.reverse()  # Chronological order

        return {
            "trends": {
                "weekly_data": weeks,
                "trend_direction": AnalyticsService._calculate_trend_direction(weeks),
            }
        }

    @staticmethod
    def _calculate_trend_direction(weekly_data: List[Dict]) -> str:
        """
        Calculate overall trend direction
        """
        if len(weekly_data) < 2:
            return "stable"

        # Compare first half vs second half
        mid_point = len(weekly_data) // 2
        first_half_avg = sum(w["total_scans"] for w in weekly_data[:mid_point]) / mid_point
        second_half_avg = sum(w["total_scans"] for w in weekly_data[mid_point:]) / (len(weekly_data) - mid_point)

        if second_half_avg > first_half_avg * 1.1:  # 10% increase
            return "increasing"
        elif second_half_avg < first_half_avg * 0.9:  # 10% decrease
            return "decreasing"
        else:
            return "stable"
