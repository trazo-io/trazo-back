"""
Enhanced Carbon Calculator Service for Scope Breakdown
Provides detailed Scope 1, 2, 3 carbon analysis and consumer equivalencies
"""
import logging
from typing import Dict, List, Tuple
from django.utils import timezone
from django.db.models import Sum, Q

from ..models import CarbonEntry
from product.models import Establishment
from history.models import History

logger = logging.getLogger(__name__)


class EnhancedCarbonCalculator:
    """
    Enhanced carbon calculator providing detailed scope breakdown
    and consumer-friendly carbon equivalencies for transparency dashboard
    """
    
    # Emission factor mappings for scope categorization
    SCOPE_1_CATEGORIES = {
        'diesel_fuel', 'gasoline', 'propane', 'natural_gas', 'fertilizer_nitrogen',
        'fertilizer_phosphorus', 'fertilizer_potassium', 'pesticide', 'herbicide',
        'livestock_methane', 'manure_n2o', 'soil_n2o_direct'
    }
    
    SCOPE_2_CATEGORIES = {
        'electricity_grid', 'electricity_purchased', 'heating_purchased', 'cooling_purchased'
    }
    
    SCOPE_3_CATEGORIES = {
        'transportation_upstream', 'transportation_downstream', 'seed_production',
        'fertilizer_production', 'pesticide_production', 'packaging', 'waste_disposal',
        'water_supply', 'business_travel', 'employee_commuting'
    }
    
    # Consumer-friendly conversion factors
    CONSUMER_EQUIVALENCIES = {
        'trees_planted_kg_co2_per_year': 22.0,  # kg CO2 sequestered per tree per year
        'miles_driven_kg_co2_per_mile': 0.404,  # kg CO2 per mile average car
        'home_energy_kg_co2_per_day': 30.0,     # kg CO2 per day average home
        'smartphones_charged_kg_co2_per_charge': 0.008,  # kg CO2 per smartphone charge
        'plastic_bottles_kg_co2_per_bottle': 0.082,      # kg CO2 per plastic bottle
        'hamburgers_kg_co2_per_burger': 2.5              # kg CO2 per hamburger
    }
    
    # Regional carbon intensity factors (kg CO2/kWh)
    REGIONAL_GRID_FACTORS = {
        'California': 0.238,
        'Texas': 0.434,
        'Florida': 0.498,
        'Washington': 0.094,
        'default': 0.429  # US national average
    }

    def calculate_establishment_carbon_scopes(self, establishment: Establishment) -> Dict:
        """
        Calculate comprehensive carbon scope breakdown for establishment
        Returns detailed Scope 1, 2, 3 analysis with consumer equivalencies
        """
        try:
            # Get all carbon entries for the establishment
            carbon_entries = CarbonEntry.objects.filter(
                history__parcel__establishment=establishment
            ).select_related('history', 'history__parcel', 'history__product')
            
            if not carbon_entries.exists():
                return self._empty_carbon_response()
            
            # Calculate scope breakdown
            scope_breakdown = self._calculate_scope_breakdown(carbon_entries)
            
            # Calculate total emissions
            total_emissions = scope_breakdown['scope_1'] + scope_breakdown['scope_2'] + scope_breakdown['scope_3']
            
            # Calculate consumer equivalencies
            consumer_equivalencies = self._calculate_consumer_equivalencies(total_emissions)
            
            # Get USDA benchmarks
            usda_benchmarks = self._get_usda_benchmarks(establishment, total_emissions)
            
            # Identify reduction opportunities
            reduction_opportunities = self._identify_reduction_opportunities(scope_breakdown, carbon_entries)
            
            # Calculate data quality metrics
            data_quality = self._calculate_data_quality(carbon_entries)
            
            return {
                'establishment_id': establishment.id,
                'calculation_timestamp': timezone.now().isoformat(),
                'carbon_scope_breakdown': {
                    'scope_1_direct': {
                        'emissions_kg_co2e': scope_breakdown['scope_1'],
                        'percentage': (scope_breakdown['scope_1'] / total_emissions * 100) if total_emissions > 0 else 0,
                        'sources': scope_breakdown['scope_1_sources'],
                        'description': 'Direct emissions from farm operations (fuel, fertilizers, livestock)'
                    },
                    'scope_2_indirect_energy': {
                        'emissions_kg_co2e': scope_breakdown['scope_2'],
                        'percentage': (scope_breakdown['scope_2'] / total_emissions * 100) if total_emissions > 0 else 0,
                        'sources': scope_breakdown['scope_2_sources'],
                        'description': 'Indirect emissions from purchased electricity and heating'
                    },
                    'scope_3_value_chain': {
                        'emissions_kg_co2e': scope_breakdown['scope_3'],
                        'percentage': (scope_breakdown['scope_3'] / total_emissions * 100) if total_emissions > 0 else 0,
                        'sources': scope_breakdown['scope_3_sources'],
                        'description': 'Supply chain and transportation emissions'
                    }
                },
                'total_emissions': {
                    'kg_co2e': total_emissions,
                    'tons_co2e': total_emissions / 1000,
                    'per_hectare': (total_emissions / establishment.total_area_hectares) if establishment.total_area_hectares else 0,
                    'per_production': scope_breakdown.get('per_production', 0),
                    'calculation_date': timezone.now().isoformat(),
                    'methodology': 'USDA/EPA emission factors with GHG Protocol scope categorization'
                },
                'consumer_friendly_equivalencies': consumer_equivalencies,
                'usda_benchmarks': usda_benchmarks,
                'reduction_opportunities': reduction_opportunities,
                'data_quality_score': data_quality['overall_score'],
                'verified_percentage': data_quality['verified_percentage'],
                'completeness_score': data_quality['completeness_score'],
                'transparency_context': {
                    'data_sources': data_quality['data_sources'],
                    'calculation_confidence': data_quality['confidence_level'],
                    'last_updated': carbon_entries.latest('created').created.isoformat() if carbon_entries.exists() else None
                }
            }
            
        except Exception as e:
            logger.error(f"Enhanced carbon calculation failed for establishment {establishment.id}: {str(e)}")
            return self._error_carbon_response(str(e))

    def _calculate_scope_breakdown(self, carbon_entries) -> Dict:
        """Categorize carbon entries by GHG Protocol scopes"""
        scope_1 = 0
        scope_2 = 0  
        scope_3 = 0
        scope_1_sources = []
        scope_2_sources = []
        scope_3_sources = []
        total_productions = set()
        
        for entry in carbon_entries:
            emission_value = entry.emissions_kg_co2e or 0
            entry_type = entry.entry_type.lower() if entry.entry_type else 'unknown'
            source_name = entry.emission_factor_name or entry.entry_type or 'Unknown Source'
            
            # Track productions for per-production calculation
            if entry.history_id:
                total_productions.add(entry.history_id)
            
            # Categorize by scope
            if any(scope_1_cat in entry_type for scope_1_cat in self.SCOPE_1_CATEGORIES):
                scope_1 += emission_value
                if source_name not in scope_1_sources:
                    scope_1_sources.append(source_name)
                    
            elif any(scope_2_cat in entry_type for scope_2_cat in self.SCOPE_2_CATEGORIES):
                scope_2 += emission_value
                if source_name not in scope_2_sources:
                    scope_2_sources.append(source_name)
                    
            elif any(scope_3_cat in entry_type for scope_3_cat in self.SCOPE_3_CATEGORIES):
                scope_3 += emission_value
                if source_name not in scope_3_sources:
                    scope_3_sources.append(source_name)
                    
            else:
                # Default unclassified emissions to Scope 1 (most conservative)
                scope_1 += emission_value
                if f"{source_name} (unclassified)" not in scope_1_sources:
                    scope_1_sources.append(f"{source_name} (unclassified)")
        
        per_production = (scope_1 + scope_2 + scope_3) / len(total_productions) if total_productions else 0
        
        return {
            'scope_1': scope_1,
            'scope_2': scope_2, 
            'scope_3': scope_3,
            'scope_1_sources': scope_1_sources,
            'scope_2_sources': scope_2_sources,
            'scope_3_sources': scope_3_sources,
            'per_production': per_production,
            'total_productions_analyzed': len(total_productions)
        }

    def _calculate_consumer_equivalencies(self, total_emissions_kg: float) -> Dict:
        """Convert emissions to consumer-friendly equivalencies"""
        if total_emissions_kg <= 0:
            return {key.replace('_kg_co2_per_', '_equivalent'): 0 for key in self.CONSUMER_EQUIVALENCIES.keys()}
        
        return {
            'trees_to_offset': int(total_emissions_kg / self.CONSUMER_EQUIVALENCIES['trees_planted_kg_co2_per_year']),
            'miles_driven': int(total_emissions_kg / self.CONSUMER_EQUIVALENCIES['miles_driven_kg_co2_per_mile']),
            'homes_energy_days': int(total_emissions_kg / self.CONSUMER_EQUIVALENCIES['home_energy_kg_co2_per_day']),
            'smartphones_charged': int(total_emissions_kg / self.CONSUMER_EQUIVALENCIES['smartphones_charged_kg_co2_per_charge']),
            'plastic_bottles_avoided': int(total_emissions_kg / self.CONSUMER_EQUIVALENCIES['plastic_bottles_kg_co2_per_bottle']),
            'hamburgers_equivalent': int(total_emissions_kg / self.CONSUMER_EQUIVALENCIES['hamburgers_kg_co2_per_burger']),
            'explanation': f"This farm's {total_emissions_kg:.1f} kg CO2e footprint equals the carbon absorbed by {int(total_emissions_kg / 22)} trees in a year"
        }

    def _get_usda_benchmarks(self, establishment: Establishment, total_emissions: float) -> Dict:
        """Get USDA/industry benchmarks for comparison"""
        # These would be pulled from USDA databases in production
        # For now, providing representative benchmark ranges
        
        benchmarks = {
            'crop_specific_benchmark': {
                'avocado_kg_co2_per_kg': 0.8,  # USDA average for avocados
                'citrus_kg_co2_per_kg': 0.3,   # USDA average for citrus
                'berries_kg_co2_per_kg': 1.2,  # USDA average for berries
                'vegetables_kg_co2_per_kg': 0.4 # USDA average for vegetables
            },
            'regional_average': {
                'california_kg_co2_per_hectare': 3500,
                'florida_kg_co2_per_hectare': 4200,
                'texas_kg_co2_per_hectare': 3800,
                'national_average_kg_co2_per_hectare': 3600
            },
            'percentile_ranking': self._calculate_percentile_ranking(total_emissions, establishment),
            'improvement_potential': self._calculate_improvement_potential(total_emissions),
            'certification_thresholds': {
                'organic_benchmark_reduction': 0.85,  # 15% lower than conventional
                'carbon_neutral_threshold': 0.0,
                'low_carbon_certification': 0.7      # 30% below regional average
            }
        }
        
        return benchmarks

    def _identify_reduction_opportunities(self, scope_breakdown: Dict, carbon_entries) -> List[Dict]:
        """Identify specific carbon reduction opportunities"""
        opportunities = []
        total_emissions = scope_breakdown['scope_1'] + scope_breakdown['scope_2'] + scope_breakdown['scope_3']
        
        # Scope 1 opportunities (direct emissions)
        if scope_breakdown['scope_1'] > total_emissions * 0.6:  # If >60% of emissions
            opportunities.append({
                'category': 'Scope 1 - Direct Emissions',
                'current_emissions': scope_breakdown['scope_1'],
                'reduction_potential': scope_breakdown['scope_1'] * 0.25,  # 25% reduction potential
                'actions': [
                    'Implement precision agriculture to reduce fertilizer use',
                    'Switch to renewable fuel alternatives', 
                    'Optimize equipment efficiency',
                    'Consider cover crops for soil carbon sequestration'
                ],
                'priority': 'high',
                'estimated_cost': 'medium',
                'payback_period': '2-3 years'
            })
        
        # Scope 2 opportunities (electricity)
        if scope_breakdown['scope_2'] > total_emissions * 0.2:  # If >20% of emissions
            opportunities.append({
                'category': 'Scope 2 - Energy Use',
                'current_emissions': scope_breakdown['scope_2'],
                'reduction_potential': scope_breakdown['scope_2'] * 0.8,  # 80% reduction potential
                'actions': [
                    'Install on-farm solar panels',
                    'Switch to renewable energy supplier',
                    'Implement energy-efficient equipment',
                    'Add battery storage for peak load management'
                ],
                'priority': 'medium',
                'estimated_cost': 'high',
                'payback_period': '5-7 years'
            })
        
        # Scope 3 opportunities (supply chain)
        if scope_breakdown['scope_3'] > total_emissions * 0.15:  # If >15% of emissions
            opportunities.append({
                'category': 'Scope 3 - Supply Chain',
                'current_emissions': scope_breakdown['scope_3'],
                'reduction_potential': scope_breakdown['scope_3'] * 0.3,  # 30% reduction potential
                'actions': [
                    'Source inputs from local suppliers',
                    'Optimize transportation routes',
                    'Choose low-carbon packaging alternatives',
                    'Work with suppliers on their carbon reduction'
                ],
                'priority': 'low',
                'estimated_cost': 'low',
                'payback_period': '1-2 years'
            })
        
        return opportunities

    def _calculate_data_quality(self, carbon_entries) -> Dict:
        """Assess carbon data quality and completeness"""
        total_entries = carbon_entries.count()
        
        if total_entries == 0:
            return {
                'overall_score': 0,
                'verified_percentage': 0,
                'completeness_score': 0,
                'data_sources': [],
                'confidence_level': 'no_data'
            }
        
        # Count verified entries
        verified_entries = carbon_entries.filter(
            Q(verified=True) | Q(usda_verified=True)
        ).count()
        verified_percentage = (verified_entries / total_entries) * 100
        
        # Count entries with complete data
        complete_entries = carbon_entries.filter(
            emissions_kg_co2e__isnull=False,
            emission_factor_name__isnull=False
        ).count()
        completeness_score = (complete_entries / total_entries) * 100
        
        # Identify data sources
        data_sources = list(carbon_entries.exclude(
            emission_factor_source__isnull=True
        ).values_list('emission_factor_source', flat=True).distinct())
        
        # Calculate overall quality score
        overall_score = (verified_percentage * 0.4 + completeness_score * 0.6)
        
        # Determine confidence level
        if overall_score >= 80:
            confidence_level = 'high'
        elif overall_score >= 60:
            confidence_level = 'medium'
        elif overall_score >= 40:
            confidence_level = 'low'
        else:
            confidence_level = 'very_low'
        
        return {
            'overall_score': overall_score,
            'verified_percentage': verified_percentage,
            'completeness_score': completeness_score,
            'data_sources': data_sources or ['Unknown'],
            'confidence_level': confidence_level,
            'total_entries_analyzed': total_entries
        }

    def _calculate_percentile_ranking(self, total_emissions: float, establishment: Establishment) -> int:
        """Calculate percentile ranking against regional/industry benchmarks"""
        # This would use real benchmark data in production
        # For now, providing estimated ranking based on emission levels
        
        per_hectare = (total_emissions / establishment.total_area_hectares 
                      if establishment.total_area_hectares else total_emissions)
        
        # Rough percentile based on typical agricultural emissions
        if per_hectare < 2000:      # Very low emissions
            return 95
        elif per_hectare < 3000:    # Below average
            return 75
        elif per_hectare < 4000:    # Average
            return 50
        elif per_hectare < 5000:    # Above average
            return 25
        else:                       # High emissions
            return 10

    def _calculate_improvement_potential(self, total_emissions: float) -> Dict:
        """Calculate realistic improvement potential"""
        return {
            'short_term_reduction': total_emissions * 0.15,  # 15% in 1 year
            'medium_term_reduction': total_emissions * 0.35, # 35% in 3 years
            'long_term_reduction': total_emissions * 0.60,   # 60% in 5+ years
            'carbon_neutral_timeline': '5-10 years with aggressive measures',
            'sequestration_potential': total_emissions * 0.25 # 25% through carbon sequestration
        }

    def _empty_carbon_response(self) -> Dict:
        """Return empty response structure when no carbon data available"""
        return {
            'carbon_scope_breakdown': {
                'scope_1_direct': {'emissions_kg_co2e': 0, 'percentage': 0, 'sources': []},
                'scope_2_indirect_energy': {'emissions_kg_co2e': 0, 'percentage': 0, 'sources': []}, 
                'scope_3_value_chain': {'emissions_kg_co2e': 0, 'percentage': 0, 'sources': []}
            },
            'total_emissions': {'kg_co2e': 0, 'tons_co2e': 0, 'per_hectare': 0},
            'consumer_friendly_equivalencies': {},
            'usda_benchmarks': {},
            'reduction_opportunities': [],
            'data_quality_score': 0,
            'message': 'No carbon data available for this establishment'
        }

    def _error_carbon_response(self, error_message: str) -> Dict:
        """Return error response structure"""
        return {
            'error': True,
            'message': 'Carbon calculation temporarily unavailable',
            'details': error_message,
            'carbon_scope_breakdown': {'scope_1_direct': {'emissions_kg_co2e': 0}},
            'total_emissions': {'kg_co2e': 0}
        }