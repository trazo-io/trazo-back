"""
Carbon Transparency Service - Trazo Transparency-First Platform
Enhanced carbon transparency calculations supporting documentation completeness and verification standards.
Eliminates competitive rankings to focus on transparency achievements and scientific validation.
"""

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

from history.models import History

from ..models import CarbonBenchmark, CarbonEntry, ConsumerTrustMetric

logger = logging.getLogger(__name__)


class CarbonTransparencyService:
    """Enhanced carbon transparency calculations supporting verification and documentation standards."""

    # Transparency verification thresholds (absolute standards, not competitive)
    VERIFICATION_THRESHOLDS = {
        "Complete": 95,  # Complete documentation and verification
        "Comprehensive": 85,  # Strong documentation with verification
        "Good": 75,  # Good documentation practices
        "Standard": 60,  # Meets basic standards
        "Basic": 40,  # Basic documentation only
        "Limited": 0,  # Limited documentation
    }

    def __init__(self):
        self.cache_timeout = 1800  # 30 minutes cache

    def calculate_verification_level(self, production: History) -> str:
        """
        Calculate transparency verification level based on documentation completeness and validation.

        Args:
            production: History object representing the production

        Returns:
            str: Verification level (Complete, Comprehensive, Good, Standard, Basic, Limited)
        """
        try:
            cache_key = f"verification_level_{production.id}"
            cached_level = cache.get(cache_key)
            if cached_level:
                return cached_level

            # Get carbon data for this production
            carbon_data = self._get_production_carbon_data(production)
            if not carbon_data:
                return "Limited"  # Default level for no data

            # Calculate transparency score using TransparencyCalculator
            from history.services.transparency_calculator import TransparencyCalculator

            transparency_calc = TransparencyCalculator()
            transparency_data = transparency_calc.calculate_transparency_score(production)
            transparency_score = transparency_data.get("transparency_percentage", 0)

            # Convert transparency score to verification level
            level = self._score_to_verification_level(transparency_score)

            # Cache the result
            cache.set(cache_key, level, self.cache_timeout)

            return level

        except Exception as e:
            logger.error(f"Error calculating verification level for production {production.id}: {str(e)}")
            return "Limited"  # Default level on error

    def calculate_verification_standards(self, production: History) -> Dict[str, Any]:
        """
        Calculate verification against absolute transparency standards (non-competitive).

        Args:
            production: History object

        Returns:
            Dict containing verification standards assessment
        """
        try:
            cache_key = f"verification_standards_{production.id}"
            cached_standards = cache.get(cache_key)
            if cached_standards:
                return cached_standards

            carbon_data = self._get_production_carbon_data(production)
            if not carbon_data:
                return {}

            # Get transparency data
            from history.services.transparency_calculator import TransparencyCalculator

            transparency_calc = TransparencyCalculator()
            transparency_data = transparency_calc.calculate_transparency_score(production)

            # Calculate verification against standards
            verification = {
                "transparency_percentage": transparency_data.get("transparency_percentage", 0),
                "verification_level": self._score_to_verification_level(
                    transparency_data.get("transparency_percentage", 0)
                ),
                "carbon_data_verified": carbon_data["entry_count"] > 0,
                "usda_factors_used": self._check_usda_verification(production),
                "blockchain_verified": self._check_blockchain_verification(production),
                "documentation_completeness": transparency_data.get("completeness_score", 0),
                "category_breakdown": transparency_data.get("category_breakdown", {}),
                "context_message": self._generate_verification_message(transparency_data),
                "next_standards": self._get_next_verification_standards(
                    transparency_data.get("transparency_percentage", 0)
                ),
                "achievements": self._generate_transparency_achievements(transparency_data),
            }

            # Cache the result
            cache.set(cache_key, verification, self.cache_timeout)

            return verification

        except Exception as e:
            logger.error(f"Error calculating verification standards for production {production.id}: {str(e)}")
            return {}

    def calculate_equivalency_metrics(self, production: History) -> Dict[str, Any]:
        """
        Calculate consumer-friendly equivalency metrics.

        Args:
            production: History object

        Returns:
            Dict containing equivalency metrics
        """
        try:
            cache_key = f"equivalency_metrics_{production.id}"
            cached_metrics = cache.get(cache_key)
            if cached_metrics:
                return cached_metrics

            carbon_data = self._get_production_carbon_data(production)
            if not carbon_data:
                return {}

            net_emissions = carbon_data.get("net_emissions", 0)

            # Calculate various equivalencies
            equivalencies = {
                # Transportation equivalencies
                "miles_driven": {
                    "value": round(abs(net_emissions) / 0.404, 1),  # kg CO2 per mile (average car)
                    "unit": "miles",
                    "description": "Miles driven in an average car",
                    "icon": "car",
                    "category": "transportation",
                },
                "flights_domestic": {
                    "value": round(abs(net_emissions) / 180, 2),  # kg CO2 per domestic flight
                    "unit": "flights",
                    "description": "Domestic flights (round trip)",
                    "icon": "plane",
                    "category": "transportation",
                },
                # Environmental equivalencies
                "trees_planted": {
                    "value": round(abs(net_emissions) / 22, 1),  # kg CO2 per tree per year
                    "unit": "trees",
                    "description": "Trees planted and grown for 1 year",
                    "icon": "tree",
                    "category": "environmental",
                },
                "forest_preserved": {
                    "value": round(abs(net_emissions) / 1000, 2),  # kg CO2 per acre of forest per year
                    "unit": "acres",
                    "description": "Acres of forest preserved",
                    "icon": "forest",
                    "category": "environmental",
                },
                # Energy equivalencies
                "electricity_saved": {
                    "value": round(abs(net_emissions) / 0.5, 1),  # kg CO2 per kWh (US average)
                    "unit": "kWh",
                    "description": "Electricity saved from renewable sources",
                    "icon": "lightning",
                    "category": "energy",
                },
                "solar_panels": {
                    "value": round(abs(net_emissions) / 1500, 2),  # kg CO2 saved per solar panel per year
                    "unit": "panels",
                    "description": "Solar panels operating for 1 year",
                    "icon": "sun",
                    "category": "energy",
                },
                # Daily life equivalencies
                "smartphones_charged": {
                    "value": round(abs(net_emissions) / 0.008, 0),  # kg CO2 per smartphone charge
                    "unit": "charges",
                    "description": "Smartphone charges",
                    "icon": "phone",
                    "category": "daily_life",
                },
                "recycling_impact": {
                    "value": round(abs(net_emissions) / 0.2, 1),  # kg CO2 saved per kg recycled
                    "unit": "kg",
                    "description": "Materials recycled instead of landfilled",
                    "icon": "recycle",
                    "category": "daily_life",
                },
            }

            # Add context for positive vs negative emissions
            context = {
                "is_carbon_positive": net_emissions > 0,
                "is_carbon_neutral": abs(net_emissions) < 0.1,
                "is_carbon_negative": net_emissions < -0.1,
                "net_emissions": net_emissions,
                "interpretation": self._get_emissions_interpretation(net_emissions),
            }

            metrics = {
                "equivalencies": equivalencies,
                "context": context,
                "primary_metric": self._select_primary_equivalency(equivalencies, net_emissions),
                "secondary_metrics": self._select_secondary_equivalencies(equivalencies, net_emissions),
            }

            # Cache the result
            cache.set(cache_key, metrics, self.cache_timeout)

            return metrics

        except Exception as e:
            logger.error(f"Error calculating equivalency metrics for production {production.id}: {str(e)}")
            return {}

    def calculate_trust_indicators(self, production: History) -> Dict[str, Any]:
        """
        Calculate trust indicators for consumer confidence.

        Args:
            production: History object

        Returns:
            Dict containing trust indicators
        """
        try:
            cache_key = f"trust_indicators_{production.id}"
            cached_indicators = cache.get(cache_key)
            if cached_indicators:
                return cached_indicators

            # Get or create consumer trust metric
            trust_metric, created = ConsumerTrustMetric.objects.get_or_create(
                production=production,
                defaults={
                    "overall_trust_score": 0.0,
                    "data_completeness_score": 0.0,
                    "verification_score": 0.0,
                    "transparency_score": 0.0,
                    "consistency_score": 0.0,
                },
            )

            if created or self._should_recalculate_trust(trust_metric):
                self._calculate_trust_scores(trust_metric, production)

            # Build trust indicators response
            indicators = {
                "overall_score": trust_metric.overall_trust_score,
                "grade": self._score_to_grade(trust_metric.overall_trust_score),
                "scores": {
                    "data_completeness": trust_metric.data_completeness_score,
                    "verification": trust_metric.verification_score,
                    "transparency": trust_metric.transparency_score,
                    "consistency": trust_metric.consistency_score,
                },
                "badges": self._generate_trust_badges(trust_metric),
                "indicators": {
                    "verified_data": trust_metric.verification_score >= 70,
                    "complete_documentation": trust_metric.data_completeness_score >= 80,
                    "transparent_process": trust_metric.transparency_score >= 75,
                    "consistent_reporting": trust_metric.consistency_score >= 70,
                },
                "improvement_areas": trust_metric.improvement_areas,
                "trust_factors": trust_metric.trust_factors,
                "last_updated": trust_metric.last_calculated.isoformat(),
            }

            # Cache the result
            cache.set(cache_key, indicators, self.cache_timeout)

            return indicators

        except Exception as e:
            logger.error(f"Error calculating trust indicators for production {production.id}: {str(e)}")
            return {}

    def update_production_transparency_data(self, production: History) -> bool:
        """
        Update all transparency data for a production.

        Args:
            production: History object

        Returns:
            bool: Success status
        """
        try:
            # Calculate all transparency metrics
            verification_level = self.calculate_verification_level(production)
            verification_standards = self.calculate_verification_standards(production)
            equivalency_metrics = self.calculate_equivalency_metrics(production)
            trust_indicators = self.calculate_trust_indicators(production)

            # Update production fields with transparency-focused data
            production.verification_level = verification_level
            production.verification_standards = verification_standards
            production.equivalency_metrics = equivalency_metrics
            production.trust_indicators = trust_indicators

            # Generate transparency improvement recommendations
            recommendations = self._generate_transparency_recommendations(production, verification_standards)
            production.improvement_recommendations = recommendations

            # Generate consumer insights focused on transparency
            consumer_insights = self._generate_transparency_consumer_insights(
                production, equivalency_metrics, trust_indicators
            )
            production.consumer_insights = consumer_insights

            # Save the production
            production.save(
                update_fields=[
                    "verification_level",
                    "verification_standards",
                    "equivalency_metrics",
                    "trust_indicators",
                    "improvement_recommendations",
                    "consumer_insights",
                ]
            )

            # Clear related caches
            self._clear_production_caches(production.id)

            return True

        except Exception as e:
            logger.error(f"Error updating transparency data for production {production.id}: {str(e)}")
            return False

    # Private helper methods

    def _get_production_carbon_data(self, production: History) -> Optional[Dict[str, Any]]:
        """Get carbon data summary for a production."""
        try:
            carbon_entries = CarbonEntry.objects.filter(production=production)

            if not carbon_entries.exists():
                return None

            total_emissions = carbon_entries.filter(type="emission").aggregate(Sum("amount"))["amount__sum"] or 0

            total_offsets = (
                carbon_entries.filter(type="offset").aggregate(Sum("effective_amount"))["effective_amount__sum"] or 0
            )

            net_emissions = total_emissions - total_offsets

            # Get region from establishment
            region = "US"  # Default
            if production.parcel and production.parcel.establishment:
                # Could extract region from establishment location
                pass

            return {
                "total_emissions": float(total_emissions),
                "total_offsets": float(total_offsets),
                "net_emissions": float(net_emissions),
                "entry_count": carbon_entries.count(),
                "region": region,
                "last_updated": carbon_entries.latest("updated_at").updated_at if carbon_entries.exists() else None,
            }

        except Exception as e:
            logger.error(f"Error getting carbon data for production {production.id}: {str(e)}")
            return None

    def _calculate_industry_percentile(self, production: History, carbon_data: Dict) -> float:
        """Calculate industry percentile for this production."""
        try:
            crop_type = getattr(production.crop_type, "name", "Unknown") if production.crop_type else "Unknown"
            benchmark = self._get_industry_benchmark(crop_type, carbon_data.get("region", "US"))

            if not benchmark:
                return 50.0  # Default to average

            net_emissions = carbon_data["net_emissions"]

            # Calculate percentile based on normal distribution assumption
            if net_emissions <= benchmark.min_emissions:
                return 95.0
            elif net_emissions <= benchmark.average_emissions:
                # Scale from 50-95 based on position between average and best
                ratio = (benchmark.average_emissions - net_emissions) / (
                    benchmark.average_emissions - benchmark.min_emissions
                )
                return 50 + (ratio * 45)
            else:
                if net_emissions <= benchmark.max_emissions:
                    # Scale from 5-50 based on position between average and worst
                    ratio = (net_emissions - benchmark.average_emissions) / (
                        benchmark.max_emissions - benchmark.average_emissions
                    )
                    return 50 - (ratio * 45)
                else:
                    return 5.0

        except Exception as e:
            logger.error(f"Error calculating industry percentile: {str(e)}")
            return 50.0

    def _score_to_verification_level(self, score: float) -> str:
        """Convert transparency score to verification level."""
        for level, threshold in self.VERIFICATION_THRESHOLDS.items():
            if score >= threshold:
                return level
        return "Limited"

    def _check_usda_verification(self, production: History) -> bool:
        """
        Check if production has USDA verified carbon data.

        PHASE 1 FIX (2025-12-12): This now checks if USDA factors were used in the
        carbon calculation (via USDAComplianceRecord.is_usda_verified property).

        Returns True if at least one CarbonEntry exists with usda_factors_based=True,
        which indicates USDA factors were applied to the carbon calculation.
        """
        from ..models import CarbonEntry

        return CarbonEntry.objects.filter(production=production, usda_factors_based=True).exists()

    def _check_blockchain_verification(self, production: History) -> bool:
        """Check if production has blockchain verified carbon data."""
        from ..models import CarbonEntry

        return CarbonEntry.objects.filter(
            production=production, blockchain_verified=True, blockchain_transaction_hash__isnull=False
        ).exists()

    def _generate_verification_message(self, transparency_data: Dict) -> str:
        """Generate verification message based on transparency data."""
        transparency_percentage = transparency_data.get("transparency_percentage", 0)

        if transparency_percentage >= 95:
            return "Complete transparency with comprehensive documentation"
        elif transparency_percentage >= 85:
            return f"{transparency_percentage:.0f}% transparency - comprehensive farm record"
        elif transparency_percentage >= 75:
            return f"{transparency_percentage:.0f}% transparency - good documentation practices"
        elif transparency_percentage >= 60:
            return f"{transparency_percentage:.0f}% transparency - meets transparency standards"
        elif transparency_percentage >= 40:
            return f"{transparency_percentage:.0f}% transparency - basic documentation available"
        else:
            return f"{transparency_percentage:.0f}% transparency - limited documentation"

    def _get_next_verification_standards(self, current_score: float) -> Dict:
        """Get next transparency verification standard to achieve."""
        for level, threshold in self.VERIFICATION_THRESHOLDS.items():
            if current_score < threshold:
                return {
                    "target_score": threshold,
                    "target_level": level,
                    "points_needed": threshold - current_score,
                    "description": f"Achieve {level} verification level",
                }

        return {
            "target_score": 100,
            "target_level": "Perfect",
            "points_needed": 100 - current_score,
            "description": "Perfect transparency documentation",
        }

    def _generate_transparency_achievements(self, transparency_data: Dict) -> List[Dict]:
        """Generate transparency achievements based on documentation."""
        achievements = []
        transparency_percentage = transparency_data.get("transparency_percentage", 0)
        category_breakdown = transparency_data.get("category_breakdown", {})

        # Overall transparency achievements
        if transparency_percentage >= 95:
            achievements.append(
                {
                    "title": "Complete Transparency",
                    "description": "Comprehensive farm documentation",
                    "icon": "shield-check",
                    "level": "gold",
                }
            )
        elif transparency_percentage >= 85:
            achievements.append(
                {
                    "title": "High Transparency",
                    "description": "Strong documentation practices",
                    "icon": "shield",
                    "level": "silver",
                }
            )
        elif transparency_percentage >= 75:
            achievements.append(
                {
                    "title": "Good Transparency",
                    "description": "Solid documentation foundation",
                    "icon": "check-circle",
                    "level": "bronze",
                }
            )

        # Category-specific achievements
        for category, data in category_breakdown.items():
            if data.get("completeness_percentage", 0) >= 90:
                achievements.append(
                    {
                        "title": f'Excellent {category.replace("_", " ").title()} Documentation',
                        "description": f"Complete {category} event recording",
                        "icon": "file-check",
                        "level": "category",
                    }
                )

        return achievements

    def _generate_transparency_recommendations(self, production: History, verification_standards: Dict) -> List[Dict]:
        """Generate transparency improvement recommendations (non-competitive)."""
        recommendations = []

        transparency_percentage = verification_standards.get("transparency_percentage", 0)
        category_breakdown = verification_standards.get("category_breakdown", {})

        # Documentation improvement recommendations
        if transparency_percentage < 85:
            recommendations.append(
                {
                    "category": "Documentation",
                    "priority": "High",
                    "title": "Improve Farm Documentation",
                    "description": "Add more detailed event documentation to increase transparency",
                    "action_items": [
                        "Document routine farming activities",
                        "Record equipment maintenance events",
                        "Add soil management practices",
                    ],
                    "potential_improvement": f"+{85 - transparency_percentage:.0f} transparency points",
                }
            )

        # Category-specific recommendations
        for category, data in category_breakdown.items():
            if data.get("completeness_percentage", 0) < 70:
                recommendations.append(
                    {
                        "category": "Category Improvement",
                        "priority": "Medium",
                        "title": f'Improve {category.replace("_", " ").title()} Documentation',
                        "description": f"Add more {category} events to strengthen transparency",
                        "action_items": [f"Document {category} activities regularly"],
                        "potential_improvement": f"Strengthen {category} transparency",
                    }
                )

        # Verification recommendations
        if not verification_standards.get("usda_factors_used", False):
            recommendations.append(
                {
                    "category": "Verification",
                    "priority": "Medium",
                    "title": "Add USDA Verification",
                    "description": "Verify carbon calculations with USDA standards",
                    "action_items": ["Submit carbon data for USDA verification"],
                    "potential_improvement": "Enhanced credibility",
                }
            )

        if not verification_standards.get("blockchain_verified", False):
            recommendations.append(
                {
                    "category": "Verification",
                    "priority": "Low",
                    "title": "Add Blockchain Verification",
                    "description": "Secure carbon data with blockchain verification",
                    "action_items": ["Enable blockchain verification for carbon records"],
                    "potential_improvement": "Immutable verification",
                }
            )

        return recommendations

    def _generate_transparency_consumer_insights(
        self, production: History, equivalency_metrics: Dict, trust_indicators: Dict
    ) -> Dict:
        """Generate consumer-focused transparency insights."""
        insights = {
            "transparency_story": "",
            "verification_summary": "",
            "trust_summary": "",
            "carbon_context": "",
            "achievements": [],
        }

        # Get verification level
        verification_level = getattr(production, "verification_level", "Limited")

        # Generate transparency story
        if verification_level == "Complete":
            insights["transparency_story"] = (
                "This farm maintains complete transparency with comprehensive documentation of all farming activities"
            )
        elif verification_level == "Comprehensive":
            insights["transparency_story"] = (
                "This farm demonstrates strong transparency practices with detailed documentation"
            )
        elif verification_level == "Good":
            insights["transparency_story"] = "This farm follows good transparency practices with solid documentation"
        else:
            insights["transparency_story"] = "This farm is working to improve transparency through better documentation"

        # Generate verification summary
        verification_points = []
        if self._check_usda_verification(production):
            verification_points.append("USDA verified carbon data")
        if self._check_blockchain_verification(production):
            verification_points.append("Blockchain secured records")

        if verification_points:
            insights["verification_summary"] = f"Verified through: {', '.join(verification_points)}"
        else:
            insights["verification_summary"] = "Working toward third-party verification"

        # Generate trust summary from trust indicators
        trust_score = trust_indicators.get("overall_score", 0)
        if trust_score >= 80:
            insights["trust_summary"] = "High trust through verified transparency and documentation"
        elif trust_score >= 60:
            insights["trust_summary"] = "Good transparency with reliable documentation"
        else:
            insights["trust_summary"] = "Building trust through improved transparency"

        # Generate carbon context (supporting role)
        if equivalency_metrics and equivalency_metrics.get("context"):
            context = equivalency_metrics["context"]
            if context.get("is_carbon_negative", False):
                insights["carbon_context"] = "Carbon negative production - removes CO₂ from atmosphere"
            elif context.get("is_carbon_neutral", False):
                insights["carbon_context"] = "Carbon neutral production - balanced emissions"
            else:
                insights["carbon_context"] = "Working to reduce environmental impact"

        return insights

    def _get_industry_benchmark(self, crop_type: str, region: str) -> Optional[CarbonBenchmark]:
        """Get industry benchmark for crop type and region."""
        try:
            current_year = timezone.now().year

            # Try to find exact match
            benchmark = (
                CarbonBenchmark.objects.filter(
                    crop_type__iexact=crop_type, region=region, year__gte=current_year - 2  # Within last 2 years
                )
                .order_by("-year")
                .first()
            )

            if benchmark:
                return benchmark

            # Fallback to general industry benchmark
            benchmark = (
                CarbonBenchmark.objects.filter(
                    industry__icontains=crop_type.split()[0],  # First word of crop type
                    year__gte=current_year - 3,  # Within last 3 years
                )
                .order_by("-year")
                .first()
            )

            return benchmark

        except Exception as e:
            logger.error(f"Error getting industry benchmark: {str(e)}")
            return None

    def _create_fallback_comparison(self, carbon_data: Dict) -> Dict[str, Any]:
        """Create fallback comparison when no benchmark is available."""
        net_emissions = carbon_data["net_emissions"]

        # Use rough industry estimates
        estimated_average = 1000  # kg CO2e - rough estimate
        estimated_best = 200
        estimated_worst = 3000

        return {
            "industry_average": estimated_average,
            "industry_best": estimated_best,
            "industry_worst": estimated_worst,
            "your_emissions": net_emissions,
            "percentile": 50,  # Default to average
            "better_than_percent": 50,
            "crop_type": "General Agriculture",
            "region": "Estimated",
            "sample_size": 0,
            "last_updated": None,
            "context_message": "Based on industry estimates - specific benchmarks not available",
            "improvement_potential": max(0, net_emissions - estimated_best),
            "estimated": True,
        }

    def _get_emissions_interpretation(self, net_emissions: float) -> str:
        """Get interpretation of emissions level."""
        if net_emissions < -10:
            return "Highly carbon negative - this production removes significant CO₂ from the atmosphere"
        elif net_emissions < -1:
            return "Carbon negative - this production removes more CO₂ than it emits"
        elif abs(net_emissions) <= 1:
            return "Nearly carbon neutral - emissions and offsets are balanced"
        elif net_emissions <= 100:
            return "Low carbon footprint - below typical levels for agricultural production"
        elif net_emissions <= 500:
            return "Moderate carbon footprint - within normal range for this type of production"
        elif net_emissions <= 1000:
            return "Above average carbon footprint - opportunities for reduction exist"
        else:
            return "High carbon footprint - significant opportunities for improvement"

    def _select_primary_equivalency(self, equivalencies: Dict, net_emissions: float) -> Dict:
        """Select the most relevant primary equivalency metric."""
        if abs(net_emissions) < 10:
            return equivalencies["smartphones_charged"]
        elif abs(net_emissions) < 100:
            return equivalencies["miles_driven"]
        elif abs(net_emissions) < 1000:
            return equivalencies["trees_planted"]
        else:
            return equivalencies["forest_preserved"]

    def _select_secondary_equivalencies(self, equivalencies: Dict, net_emissions: float) -> List[Dict]:
        """Select 2-3 secondary equivalency metrics."""
        primary_key = self._select_primary_equivalency(equivalencies, net_emissions)

        secondary = []
        for key, metric in equivalencies.items():
            if metric != primary_key and len(secondary) < 3:
                if key in ["trees_planted", "miles_driven", "electricity_saved"]:
                    secondary.append(metric)

        return secondary

    def _should_recalculate_trust(self, trust_metric: ConsumerTrustMetric) -> bool:
        """Check if trust metrics should be recalculated."""
        # Recalculate if older than 24 hours
        return timezone.now() - trust_metric.last_calculated > timedelta(hours=24)

    def _calculate_trust_scores(self, trust_metric: ConsumerTrustMetric, production: History):
        """Calculate all trust scores for a production."""
        try:
            # Data completeness score
            trust_metric.data_completeness_score = self._calculate_data_completeness_score(production)

            # Verification score
            trust_metric.verification_score = self._calculate_verification_score(production)

            # Transparency score (reuse existing method)
            trust_metric.transparency_score = production.calculate_transparency_score()

            # Consistency score
            trust_metric.consistency_score = self._calculate_consistency_score(production)

            # Overall trust score (weighted average)
            trust_metric.overall_trust_score = (
                trust_metric.data_completeness_score * 0.25
                + trust_metric.verification_score * 0.30
                + trust_metric.transparency_score * 0.25
                + trust_metric.consistency_score * 0.20
            )

            # Update metadata
            trust_metric.trust_factors = self._generate_trust_factors(trust_metric, production)
            trust_metric.improvement_areas = self._generate_improvement_areas(trust_metric)

            trust_metric.save()

        except Exception as e:
            logger.error(f"Error calculating trust scores: {str(e)}")

    def _calculate_data_completeness_score(self, production: History) -> float:
        """Calculate data completeness score."""
        score = 0
        max_score = 100

        # Required production data (40 points)
        required_fields = ["name", "start_date", "production_amount", "parcel", "product", "crop_type"]
        completed = sum(1 for field in required_fields if getattr(production, field))
        score += (completed / len(required_fields)) * 40

        # Carbon data (30 points)
        carbon_entries = CarbonEntry.objects.filter(production=production)
        if carbon_entries.exists():
            score += 20
            if carbon_entries.filter(usda_factors_based=True).exists():
                score += 10

        # Event documentation (20 points)
        total_events = (
            production.history_productionevent_events.count()
            + production.history_chemicalevent_events.count()
            + production.history_equipmentevent_events.count()
        )
        score += min(20, total_events * 2)

        # Images and documentation (10 points)
        if production.album and production.album.images.exists():
            score += 10

        return min(max_score, score)

    def _calculate_verification_score(self, production: History) -> float:
        """Calculate third-party verification score."""
        score = 0

        # USDA verification (40 points)
        carbon_entries = CarbonEntry.objects.filter(production=production)
        if carbon_entries.filter(usda_factors_based=True).exists():
            score += 40

        # Blockchain verification (30 points)
        # Check for actual blockchain verification records
        blockchain_verified_entries = carbon_entries.filter(
            blockchain_verified=True, blockchain_transaction_hash__isnull=False
        ).exists()
        if blockchain_verified_entries:
            score += 30
        else:
            logger.info("No blockchain verified entries found for production")
            # Give partial score for having carbon entries (better than no data)
            if carbon_entries.exists():
                score += 10  # Partial score for having some data

        # Third-party certifications (20 points)
        if hasattr(production, "carbon_certifications") and production.carbon_certifications.exists():
            score += 20

        # Audit trail completeness (10 points)
        if carbon_entries.exists():
            score += 10

        return score

    def _calculate_consistency_score(self, production: History) -> float:
        """Calculate data consistency score over time."""
        # This is a simplified version - could be enhanced with historical data analysis
        score = 70  # Base score

        # Check for data inconsistencies
        carbon_entries = CarbonEntry.objects.filter(production=production)

        if carbon_entries.exists():
            # Check for reasonable carbon values
            total_emissions = carbon_entries.filter(type="emission").aggregate(Sum("amount"))["amount__sum"] or 0
            if total_emissions > 0 and total_emissions < 10000:  # Reasonable range
                score += 15

            # Check for recent updates
            recent_updates = carbon_entries.filter(updated_at__gte=timezone.now() - timedelta(days=30)).exists()
            if recent_updates:
                score += 15

        return min(100, score)

    def _generate_trust_factors(self, trust_metric: ConsumerTrustMetric, production: History) -> Dict:
        """Generate factors contributing to trust score."""
        factors = {"strengths": [], "concerns": [], "neutral": []}

        # Data completeness factors
        if trust_metric.data_completeness_score >= 80:
            factors["strengths"].append("Complete production documentation")
        elif trust_metric.data_completeness_score < 60:
            factors["concerns"].append("Missing key production data")

        # Verification factors
        if trust_metric.verification_score >= 80:
            factors["strengths"].append("Strong third-party verification")
        elif trust_metric.verification_score < 60:
            factors["concerns"].append("Limited verification of claims")

        # Transparency factors
        if trust_metric.transparency_score >= 80:
            factors["strengths"].append("High transparency standards")
        elif trust_metric.transparency_score < 60:
            factors["concerns"].append("Limited transparency in reporting")

        return factors

    def _generate_improvement_areas(self, trust_metric: ConsumerTrustMetric) -> List[str]:
        """Generate areas where trust can be improved."""
        areas = []

        if trust_metric.data_completeness_score < 80:
            areas.append("Complete missing production documentation")

        if trust_metric.verification_score < 80:
            areas.append("Obtain third-party verification of carbon claims")

        if trust_metric.transparency_score < 80:
            areas.append("Increase transparency in reporting and documentation")

        if trust_metric.consistency_score < 80:
            areas.append("Improve consistency in data collection and reporting")

        return areas

    def _generate_trust_badges(self, trust_metric: ConsumerTrustMetric) -> List[Dict]:
        """Generate trust badges based on trust metrics."""
        badges = []

        if trust_metric.overall_trust_score >= 90:
            badges.append(
                {
                    "id": "verified_transparent",
                    "name": "Verified & Transparent",
                    "description": "Highest standards of verification and transparency",
                    "icon": "shield-check",
                    "color": "green",
                }
            )
        elif trust_metric.overall_trust_score >= 70:
            badges.append(
                {
                    "id": "trusted_producer",
                    "name": "Trusted Producer",
                    "description": "Reliable carbon reporting with verification",
                    "icon": "shield",
                    "color": "blue",
                }
            )

        if trust_metric.verification_score >= 80:
            badges.append(
                {
                    "id": "third_party_verified",
                    "name": "Third-Party Verified",
                    "description": "Carbon claims verified by independent third parties",
                    "icon": "check-circle",
                    "color": "green",
                }
            )

        return badges

    def _clear_production_caches(self, production_id: int):
        """Clear all caches related to a production."""
        cache_keys = [
            f"verification_level_{production_id}",
            f"verification_standards_{production_id}",
            f"equivalency_metrics_{production_id}",
            f"trust_indicators_{production_id}",
            f"qr_summary_{production_id}_v2",
            f"qr_summary_{production_id}_v2_quick",
        ]

        for key in cache_keys:
            cache.delete(key)


# Global service instance
transparency_service = CarbonTransparencyService()
