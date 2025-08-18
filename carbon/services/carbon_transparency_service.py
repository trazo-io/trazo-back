"""
Carbon Transparency Service - Trazo 2025 Enhancement
Enhanced carbon transparency calculations with A-F grading, industry comparisons, and consumer-friendly metrics.
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Sum, Avg, Count, Q
from django.core.cache import cache

from ..models import (
    CarbonEntry, CarbonBenchmark, CarbonReport, 
    ConsumerTrustMetric, CarbonIntelligence
)
from history.models import History
from company.models import Establishment

logger = logging.getLogger(__name__)


class CarbonTransparencyService:
    """Enhanced carbon transparency calculations and grading service."""
    
    # Carbon grade thresholds (based on percentile performance)
    GRADE_THRESHOLDS = {
        'A+': 95,  # Top 5%
        'A': 90,   # Top 10%
        'A-': 85,  # Top 15%
        'B+': 75,  # Top 25%
        'B': 65,   # Top 35%
        'B-': 50,  # Average (50th percentile)
        'C+': 35,  # Below average
        'C': 25,   # Bottom 25%
        'C-': 15,  # Bottom 15%
        'D+': 10,  # Bottom 10%
        'D': 5,    # Bottom 5%
        'F': 0     # Bottom performers
    }
    
    def __init__(self):
        self.cache_timeout = 1800  # 30 minutes cache
    
    def calculate_carbon_grade(self, production: History) -> str:
        """
        Calculate A-F carbon grade based on industry comparison and performance.
        
        Args:
            production: History object representing the production
            
        Returns:
            str: Carbon grade (A+ to F)
        """
        try:
            cache_key = f"carbon_grade_{production.id}"
            cached_grade = cache.get(cache_key)
            if cached_grade:
                return cached_grade
            
            # Get carbon data for this production
            carbon_data = self._get_production_carbon_data(production)
            if not carbon_data:
                return 'C'  # Default grade for no data
            
            # Calculate performance percentile
            percentile = self._calculate_industry_percentile(production, carbon_data)
            
            # Convert percentile to grade
            grade = self._percentile_to_grade(percentile)
            
            # Cache the result
            cache.set(cache_key, grade, self.cache_timeout)
            
            return grade
            
        except Exception as e:
            logger.error(f"Error calculating carbon grade for production {production.id}: {str(e)}")
            return 'C'  # Default grade on error
    
    def calculate_industry_comparison(self, production: History) -> Dict[str, Any]:
        """
        Calculate detailed industry comparison metrics.
        
        Args:
            production: History object
            
        Returns:
            Dict containing industry comparison data
        """
        try:
            cache_key = f"industry_comparison_{production.id}"
            cached_comparison = cache.get(cache_key)
            if cached_comparison:
                return cached_comparison
            
            carbon_data = self._get_production_carbon_data(production)
            if not carbon_data:
                return {}
            
            # Get crop type for benchmarking
            crop_type = getattr(production.crop_type, 'name', 'Unknown') if production.crop_type else 'Unknown'
            
            # Find relevant benchmarks
            benchmark = self._get_industry_benchmark(crop_type, carbon_data.get('region', 'US'))
            
            if not benchmark:
                return self._create_fallback_comparison(carbon_data)
            
            # Calculate comparison metrics
            comparison = {
                'industry_average': float(benchmark.average_emissions),
                'industry_best': float(benchmark.min_emissions),
                'industry_worst': float(benchmark.max_emissions),
                'your_emissions': carbon_data['net_emissions'],
                'percentile': self._calculate_industry_percentile(production, carbon_data),
                'better_than_percent': 0,  # Calculated below
                'crop_type': crop_type,
                'region': carbon_data.get('region', 'US'),
                'sample_size': benchmark.company_count,
                'last_updated': benchmark.last_updated.isoformat() if benchmark.last_updated else None,
                'context_message': '',  # Calculated below
                'improvement_potential': 0,  # Calculated below
            }
            
            # Calculate better than percentage
            if comparison['your_emissions'] <= comparison['industry_best']:
                comparison['better_than_percent'] = 95
            elif comparison['your_emissions'] <= comparison['industry_average']:
                ratio = (comparison['industry_average'] - comparison['your_emissions']) / (comparison['industry_average'] - comparison['industry_best'])
                comparison['better_than_percent'] = 50 + (ratio * 45)
            else:
                if comparison['your_emissions'] <= comparison['industry_worst']:
                    ratio = (comparison['your_emissions'] - comparison['industry_average']) / (comparison['industry_worst'] - comparison['industry_average'])
                    comparison['better_than_percent'] = 50 - (ratio * 45)
                else:
                    comparison['better_than_percent'] = 5
            
            comparison['better_than_percent'] = max(5, min(95, round(comparison['better_than_percent'], 1)))
            
            # Generate context message
            comparison['context_message'] = self._generate_context_message(comparison)
            
            # Calculate improvement potential
            comparison['improvement_potential'] = max(0, comparison['your_emissions'] - comparison['industry_best'])
            
            # Cache the result
            cache.set(cache_key, comparison, self.cache_timeout)
            
            return comparison
            
        except Exception as e:
            logger.error(f"Error calculating industry comparison for production {production.id}: {str(e)}")
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
            
            net_emissions = carbon_data.get('net_emissions', 0)
            
            # Calculate various equivalencies
            equivalencies = {
                # Transportation equivalencies
                'miles_driven': {
                    'value': round(abs(net_emissions) / 0.404, 1),  # kg CO2 per mile (average car)
                    'unit': 'miles',
                    'description': 'Miles driven in an average car',
                    'icon': 'car',
                    'category': 'transportation'
                },
                'flights_domestic': {
                    'value': round(abs(net_emissions) / 180, 2),  # kg CO2 per domestic flight
                    'unit': 'flights',
                    'description': 'Domestic flights (round trip)',
                    'icon': 'plane',
                    'category': 'transportation'
                },
                
                # Environmental equivalencies
                'trees_planted': {
                    'value': round(abs(net_emissions) / 22, 1),  # kg CO2 per tree per year
                    'unit': 'trees',
                    'description': 'Trees planted and grown for 1 year',
                    'icon': 'tree',
                    'category': 'environmental'
                },
                'forest_preserved': {
                    'value': round(abs(net_emissions) / 1000, 2),  # kg CO2 per acre of forest per year
                    'unit': 'acres',
                    'description': 'Acres of forest preserved',
                    'icon': 'forest',
                    'category': 'environmental'
                },
                
                # Energy equivalencies
                'electricity_saved': {
                    'value': round(abs(net_emissions) / 0.5, 1),  # kg CO2 per kWh (US average)
                    'unit': 'kWh',
                    'description': 'Electricity saved from renewable sources',
                    'icon': 'lightning',
                    'category': 'energy'
                },
                'solar_panels': {
                    'value': round(abs(net_emissions) / 1500, 2),  # kg CO2 saved per solar panel per year
                    'unit': 'panels',
                    'description': 'Solar panels operating for 1 year',
                    'icon': 'sun',
                    'category': 'energy'
                },
                
                # Daily life equivalencies
                'smartphones_charged': {
                    'value': round(abs(net_emissions) / 0.008, 0),  # kg CO2 per smartphone charge
                    'unit': 'charges',
                    'description': 'Smartphone charges',
                    'icon': 'phone',
                    'category': 'daily_life'
                },
                'recycling_impact': {
                    'value': round(abs(net_emissions) / 0.2, 1),  # kg CO2 saved per kg recycled
                    'unit': 'kg',
                    'description': 'Materials recycled instead of landfilled',
                    'icon': 'recycle',
                    'category': 'daily_life'
                }
            }
            
            # Add context for positive vs negative emissions
            context = {
                'is_carbon_positive': net_emissions > 0,
                'is_carbon_neutral': abs(net_emissions) < 0.1,
                'is_carbon_negative': net_emissions < -0.1,
                'net_emissions': net_emissions,
                'interpretation': self._get_emissions_interpretation(net_emissions)
            }
            
            metrics = {
                'equivalencies': equivalencies,
                'context': context,
                'primary_metric': self._select_primary_equivalency(equivalencies, net_emissions),
                'secondary_metrics': self._select_secondary_equivalencies(equivalencies, net_emissions)
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
                    'overall_trust_score': 0.0,
                    'data_completeness_score': 0.0,
                    'verification_score': 0.0,
                    'transparency_score': 0.0,
                    'consistency_score': 0.0,
                }
            )
            
            if created or self._should_recalculate_trust(trust_metric):
                self._calculate_trust_scores(trust_metric, production)
            
            # Build trust indicators response
            indicators = {
                'overall_score': trust_metric.overall_trust_score,
                'grade': self._score_to_grade(trust_metric.overall_trust_score),
                'scores': {
                    'data_completeness': trust_metric.data_completeness_score,
                    'verification': trust_metric.verification_score,
                    'transparency': trust_metric.transparency_score,
                    'consistency': trust_metric.consistency_score,
                },
                'badges': self._generate_trust_badges(trust_metric),
                'indicators': {
                    'verified_data': trust_metric.verification_score >= 70,
                    'complete_documentation': trust_metric.data_completeness_score >= 80,
                    'transparent_process': trust_metric.transparency_score >= 75,
                    'consistent_reporting': trust_metric.consistency_score >= 70,
                },
                'improvement_areas': trust_metric.improvement_areas,
                'trust_factors': trust_metric.trust_factors,
                'last_updated': trust_metric.last_calculated.isoformat()
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
            carbon_grade = self.calculate_carbon_grade(production)
            industry_comparison = self.calculate_industry_comparison(production)
            equivalency_metrics = self.calculate_equivalency_metrics(production)
            trust_indicators = self.calculate_trust_indicators(production)
            
            # Update production fields
            production.carbon_grade = carbon_grade
            production.industry_comparison = industry_comparison
            production.equivalency_metrics = equivalency_metrics
            production.trust_indicators = trust_indicators
            
            # Generate improvement recommendations
            recommendations = self._generate_improvement_recommendations(production, industry_comparison)
            production.improvement_recommendations = recommendations
            
            # Generate consumer insights
            consumer_insights = self._generate_consumer_insights(production, equivalency_metrics, trust_indicators)
            production.consumer_insights = consumer_insights
            
            # Save the production
            production.save(update_fields=[
                'carbon_grade', 'industry_comparison', 'equivalency_metrics', 
                'trust_indicators', 'improvement_recommendations', 'consumer_insights'
            ])
            
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
            
            total_emissions = carbon_entries.filter(type='emission').aggregate(
                Sum('amount')
            )['amount__sum'] or 0
            
            total_offsets = carbon_entries.filter(type='offset').aggregate(
                Sum('effective_amount')
            )['effective_amount__sum'] or 0
            
            net_emissions = total_emissions - total_offsets
            
            # Get region from establishment
            region = 'US'  # Default
            if production.parcel and production.parcel.establishment:
                # Could extract region from establishment location
                pass
            
            return {
                'total_emissions': float(total_emissions),
                'total_offsets': float(total_offsets),
                'net_emissions': float(net_emissions),
                'entry_count': carbon_entries.count(),
                'region': region,
                'last_updated': carbon_entries.latest('updated_at').updated_at if carbon_entries.exists() else None
            }
            
        except Exception as e:
            logger.error(f"Error getting carbon data for production {production.id}: {str(e)}")
            return None
    
    def _calculate_industry_percentile(self, production: History, carbon_data: Dict) -> float:
        """Calculate industry percentile for this production."""
        try:
            crop_type = getattr(production.crop_type, 'name', 'Unknown') if production.crop_type else 'Unknown'
            benchmark = self._get_industry_benchmark(crop_type, carbon_data.get('region', 'US'))
            
            if not benchmark:
                return 50.0  # Default to average
            
            net_emissions = carbon_data['net_emissions']
            
            # Calculate percentile based on normal distribution assumption
            if net_emissions <= benchmark.min_emissions:
                return 95.0
            elif net_emissions <= benchmark.average_emissions:
                # Scale from 50-95 based on position between average and best
                ratio = (benchmark.average_emissions - net_emissions) / (benchmark.average_emissions - benchmark.min_emissions)
                return 50 + (ratio * 45)
            else:
                if net_emissions <= benchmark.max_emissions:
                    # Scale from 5-50 based on position between average and worst
                    ratio = (net_emissions - benchmark.average_emissions) / (benchmark.max_emissions - benchmark.average_emissions)
                    return 50 - (ratio * 45)
                else:
                    return 5.0
                    
        except Exception as e:
            logger.error(f"Error calculating industry percentile: {str(e)}")
            return 50.0
    
    def _percentile_to_grade(self, percentile: float) -> str:
        """Convert percentile to letter grade."""
        for grade, threshold in self.GRADE_THRESHOLDS.items():
            if percentile >= threshold:
                return grade
        return 'F'
    
    def _score_to_grade(self, score: float) -> str:
        """Convert numeric score to letter grade."""
        return self._percentile_to_grade(score)
    
    def _get_industry_benchmark(self, crop_type: str, region: str) -> Optional[CarbonBenchmark]:
        """Get industry benchmark for crop type and region."""
        try:
            current_year = timezone.now().year
            
            # Try to find exact match
            benchmark = CarbonBenchmark.objects.filter(
                crop_type__iexact=crop_type,
                region=region,
                year__gte=current_year - 2  # Within last 2 years
            ).order_by('-year').first()
            
            if benchmark:
                return benchmark
            
            # Fallback to general industry benchmark
            benchmark = CarbonBenchmark.objects.filter(
                industry__icontains=crop_type.split()[0],  # First word of crop type
                year__gte=current_year - 3  # Within last 3 years
            ).order_by('-year').first()
            
            return benchmark
            
        except Exception as e:
            logger.error(f"Error getting industry benchmark: {str(e)}")
            return None
    
    def _create_fallback_comparison(self, carbon_data: Dict) -> Dict[str, Any]:
        """Create fallback comparison when no benchmark is available."""
        net_emissions = carbon_data['net_emissions']
        
        # Use rough industry estimates
        estimated_average = 1000  # kg CO2e - rough estimate
        estimated_best = 200
        estimated_worst = 3000
        
        return {
            'industry_average': estimated_average,
            'industry_best': estimated_best,
            'industry_worst': estimated_worst,
            'your_emissions': net_emissions,
            'percentile': 50,  # Default to average
            'better_than_percent': 50,
            'crop_type': 'General Agriculture',
            'region': 'Estimated',
            'sample_size': 0,
            'last_updated': None,
            'context_message': 'Based on industry estimates - specific benchmarks not available',
            'improvement_potential': max(0, net_emissions - estimated_best),
            'estimated': True
        }
    
    def _generate_context_message(self, comparison: Dict) -> str:
        """Generate context message for industry comparison."""
        better_than = comparison['better_than_percent']
        
        if better_than >= 90:
            return f"Exceptional performance - better than {better_than:.0f}% of {comparison['crop_type'].lower()} producers"
        elif better_than >= 75:
            return f"Excellent performance - better than {better_than:.0f}% of similar operations"
        elif better_than >= 50:
            return f"Above average performance - better than {better_than:.0f}% of producers"
        elif better_than >= 25:
            return f"Below average performance - {100-better_than:.0f}% of producers perform better"
        else:
            return f"Significant room for improvement - only better than {better_than:.0f}% of producers"
    
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
            return equivalencies['smartphones_charged']
        elif abs(net_emissions) < 100:
            return equivalencies['miles_driven']
        elif abs(net_emissions) < 1000:
            return equivalencies['trees_planted']
        else:
            return equivalencies['forest_preserved']
    
    def _select_secondary_equivalencies(self, equivalencies: Dict, net_emissions: float) -> List[Dict]:
        """Select 2-3 secondary equivalency metrics."""
        primary_key = self._select_primary_equivalency(equivalencies, net_emissions)
        
        secondary = []
        for key, metric in equivalencies.items():
            if metric != primary_key and len(secondary) < 3:
                if key in ['trees_planted', 'miles_driven', 'electricity_saved']:
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
                trust_metric.data_completeness_score * 0.25 +
                trust_metric.verification_score * 0.30 +
                trust_metric.transparency_score * 0.25 +
                trust_metric.consistency_score * 0.20
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
        required_fields = ['name', 'start_date', 'production_amount', 'parcel', 'product', 'crop_type']
        completed = sum(1 for field in required_fields if getattr(production, field))
        score += (completed / len(required_fields)) * 40
        
        # Carbon data (30 points)
        carbon_entries = CarbonEntry.objects.filter(production=production)
        if carbon_entries.exists():
            score += 20
            if carbon_entries.filter(usda_verified=True).exists():
                score += 10
        
        # Event documentation (20 points)
        total_events = (
            production.history_productionevent_events.count() +
            production.history_chemicalevent_events.count() +
            production.history_equipmentevent_events.count()
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
        if carbon_entries.filter(usda_verified=True).exists():
            score += 40
        
        # Blockchain verification (30 points)
        # Note: This would check actual blockchain verification status
        score += 30  # Placeholder - assumes blockchain verification exists
        
        # Third-party certifications (20 points)
        if hasattr(production, 'carbon_certifications') and production.carbon_certifications.exists():
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
            total_emissions = carbon_entries.filter(type='emission').aggregate(Sum('amount'))['amount__sum'] or 0
            if total_emissions > 0 and total_emissions < 10000:  # Reasonable range
                score += 15
            
            # Check for recent updates
            recent_updates = carbon_entries.filter(
                updated_at__gte=timezone.now() - timedelta(days=30)
            ).exists()
            if recent_updates:
                score += 15
        
        return min(100, score)
    
    def _generate_trust_factors(self, trust_metric: ConsumerTrustMetric, production: History) -> Dict:
        """Generate factors contributing to trust score."""
        factors = {
            'strengths': [],
            'concerns': [],
            'neutral': []
        }
        
        # Data completeness factors
        if trust_metric.data_completeness_score >= 80:
            factors['strengths'].append("Complete production documentation")
        elif trust_metric.data_completeness_score < 60:
            factors['concerns'].append("Missing key production data")
        
        # Verification factors
        if trust_metric.verification_score >= 80:
            factors['strengths'].append("Strong third-party verification")
        elif trust_metric.verification_score < 60:
            factors['concerns'].append("Limited verification of claims")
        
        # Transparency factors
        if trust_metric.transparency_score >= 80:
            factors['strengths'].append("High transparency standards")
        elif trust_metric.transparency_score < 60:
            factors['concerns'].append("Limited transparency in reporting")
        
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
            badges.append({
                'id': 'verified_transparent',
                'name': 'Verified & Transparent',
                'description': 'Highest standards of verification and transparency',
                'icon': 'shield-check',
                'color': 'green'
            })
        elif trust_metric.overall_trust_score >= 70:
            badges.append({
                'id': 'trusted_producer',
                'name': 'Trusted Producer',
                'description': 'Reliable carbon reporting with verification',
                'icon': 'shield',
                'color': 'blue'
            })
        
        if trust_metric.verification_score >= 80:
            badges.append({
                'id': 'third_party_verified',
                'name': 'Third-Party Verified',
                'description': 'Carbon claims verified by independent third parties',
                'icon': 'check-circle',
                'color': 'green'
            })
        
        return badges
    
    def _generate_improvement_recommendations(self, production: History, industry_comparison: Dict) -> List[Dict]:
        """Generate AI-powered improvement recommendations."""
        recommendations = []
        
        if not industry_comparison:
            return recommendations
        
        # Performance-based recommendations
        if industry_comparison.get('better_than_percent', 50) < 50:
            recommendations.append({
                'category': 'Performance',
                'priority': 'High',
                'title': 'Reduce Carbon Footprint',
                'description': 'Your emissions are above industry average. Focus on high-impact reduction strategies.',
                'potential_impact': 'High',
                'difficulty': 'Medium',
                'estimated_savings': industry_comparison.get('improvement_potential', 0)
            })
        
        # Add more specific recommendations based on carbon data
        carbon_data = self._get_production_carbon_data(production)
        if carbon_data:
            if carbon_data['total_emissions'] > carbon_data['total_offsets'] * 2:
                recommendations.append({
                    'category': 'Offsetting',
                    'priority': 'Medium',
                    'title': 'Increase Carbon Offsets',
                    'description': 'Consider additional carbon offset projects to balance emissions.',
                    'potential_impact': 'Medium',
                    'difficulty': 'Low',
                    'estimated_savings': carbon_data['total_emissions'] - carbon_data['total_offsets']
                })
        
        return recommendations
    
    def _generate_consumer_insights(self, production: History, equivalency_metrics: Dict, trust_indicators: Dict) -> Dict:
        """Generate consumer-focused insights and explanations."""
        insights = {
            'key_message': '',
            'sustainability_story': '',
            'trust_summary': '',
            'action_items': [],
            'comparisons': {},
            'explanations': {}
        }
        
        # Generate key message
        grade = production.carbon_grade
        if grade in ['A+', 'A', 'A-']:
            insights['key_message'] = f"Exceptional sustainability with {grade} grade carbon performance"
        elif grade in ['B+', 'B', 'B-']:
            insights['key_message'] = f"Good sustainability practices with {grade} grade performance"
        else:
            insights['key_message'] = f"Working toward better sustainability - current grade: {grade}"
        
        # Generate sustainability story
        if equivalency_metrics and equivalency_metrics.get('context'):
            context = equivalency_metrics['context']
            if context['is_carbon_negative']:
                insights['sustainability_story'] = "This production actually removes more CO₂ from the atmosphere than it produces, helping fight climate change."
            elif context['is_carbon_neutral']:
                insights['sustainability_story'] = "This production achieves carbon neutrality, balancing emissions with effective offsets."
            else:
                insights['sustainability_story'] = "This production is working to reduce its environmental impact through sustainable farming practices."
        
        # Generate trust summary
        trust_score = trust_indicators.get('overall_score', 0)
        if trust_score >= 80:
            insights['trust_summary'] = "High trust with verified data and transparent reporting"
        elif trust_score >= 60:
            insights['trust_summary'] = "Good transparency with reliable data sources"
        else:
            insights['trust_summary'] = "Basic transparency - room for improvement in verification"
        
        return insights
    
    def _clear_production_caches(self, production_id: int):
        """Clear all caches related to a production."""
        cache_keys = [
            f"carbon_grade_{production_id}",
            f"industry_comparison_{production_id}",
            f"equivalency_metrics_{production_id}",
            f"trust_indicators_{production_id}",
            f"qr_summary_{production_id}_v2",
            f"qr_summary_{production_id}_v2_quick"
        ]
        
        for key in cache_keys:
            cache.delete(key)


# Global service instance
transparency_service = CarbonTransparencyService()