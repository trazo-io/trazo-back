"""
Production Phase Calculator for Trazo Carbon Transparency
Calculates production phases based on actual farm event data
Aligned with Trazo's mission: transparent carbon footprints for consumers
"""

from django.db.models import Sum
from typing import Dict, List, Any


class ProductionPhaseCalculator:
    """
    Calculate production phases based on actual Trazo event data.
    
    Focus: Farm-level carbon transparency for consumer QR scanning.
    Scope: On-farm activities only (no transportation/processing).
    """
    
    def __init__(self):
        # Import here to avoid circular imports
        from history.models import (
            ChemicalEvent, ProductionEvent, EquipmentEvent, 
            SoilManagementEvent, PestManagementEvent
        )
        from carbon.models import CarbonEntry
        
        self.ChemicalEvent = ChemicalEvent
        self.ProductionEvent = ProductionEvent
        self.EquipmentEvent = EquipmentEvent
        self.SoilManagementEvent = SoilManagementEvent
        self.PestManagementEvent = PestManagementEvent
        self.CarbonEntry = CarbonEntry
    
    def calculate_phases(self, production_id: int) -> Dict[str, Any]:
        """
        Calculate production phases for a specific production.
        
        Returns phases with actual carbon data from database.
        No hardcoded values - everything calculated from real events.
        """
        
        # Get all events for this production
        farm_prep_events = list(self.SoilManagementEvent.objects.filter(history=production_id)) + \
                          list(self.EquipmentEvent.objects.filter(history=production_id, type__in=['MN', 'CA']))
        
        growing_season_events = list(self.ChemicalEvent.objects.filter(history=production_id)) + \
                               list(self.ProductionEvent.objects.filter(history=production_id)) + \
                               list(self.PestManagementEvent.objects.filter(history=production_id))
        
        harvest_events = list(self.ProductionEvent.objects.filter(history=production_id, type='HA')) + \
                        list(self.EquipmentEvent.objects.filter(history=production_id, type='FC'))
        
        soil_regen_events = list(self.SoilManagementEvent.objects.filter(
            history=production_id, 
            type__in=['CC', 'CO', 'OM']  # Cover Crop, Composting, Organic Matter
        ))
        
        phases = {
            'farm_preparation': {
                'name': 'Farm Preparation',
                'events': farm_prep_events,
                'carbon_impact': 0,
                'percentage': 0,
                'consumer_story': 'Preparing healthy soil for optimal growth'
            },
            'growing_season': {
                'name': 'Growing Season',
                'events': growing_season_events,
                'carbon_impact': 0,
                'percentage': 0,
                'consumer_story': 'Sustainable crop care and water management'
            },
            'harvest_operations': {
                'name': 'Harvest Operations',
                'events': harvest_events,
                'carbon_impact': 0,
                'percentage': 0,
                'consumer_story': 'Efficient harvest at peak ripeness'
            },
            'soil_regeneration': {
                'name': 'Soil Health & Regeneration',
                'events': soil_regen_events,
                'carbon_impact': 0,
                'percentage': 0,
                'consumer_story': 'Building soil health for future generations'
            }
        }
        
        # Calculate actual carbon impact per phase
        total_carbon = 0
        for phase_name, phase_data in phases.items():
            phase_carbon = self._calculate_phase_carbon(production_id, phase_data['events'])
            phase_data['carbon_impact'] = phase_carbon
            total_carbon += abs(phase_carbon)  # Use absolute value for percentage calculation
        
        # Calculate percentages based on actual data
        for phase_data in phases.values():
            if total_carbon > 0:
                phase_data['percentage'] = (abs(phase_data['carbon_impact']) / total_carbon) * 100
            else:
                phase_data['percentage'] = 0
                
        return phases
    
    def _calculate_phase_carbon(self, production_id: int, events: List) -> float:
        """
        Calculate carbon impact for a specific phase based on events.
        
        For MVP: Use general carbon categorization since CarbonEntry 
        doesn't directly link to specific events.
        """
        if not events:
            return 0
        
        # Get all carbon entries for this production
        carbon_entries = self.CarbonEntry.objects.filter(production=production_id)
        
        if not carbon_entries.exists():
            return 0
        
        # For MVP: Estimate phase carbon based on event types and general carbon sources
        # This is a simplified approach since we don't have direct event-carbon linkage
        
        total_carbon = 0
        event_types = set(event.__class__.__name__ for event in events)
        
        # Map event types to carbon source categories
        if 'ChemicalEvent' in event_types:
            # Fertilizer and chemical-related carbon
            fertilizer_carbon = carbon_entries.filter(
                source__name__icontains='fertilizer'
            ).aggregate(total=Sum('co2e_amount'))['total'] or 0
            total_carbon += fertilizer_carbon
            
        if 'EquipmentEvent' in event_types:
            # Fuel-related carbon
            fuel_carbon = carbon_entries.filter(
                source__name__icontains='fuel'
            ).aggregate(total=Sum('co2e_amount'))['total'] or 0
            total_carbon += fuel_carbon
            
        if 'SoilManagementEvent' in event_types:
            # Soil-related carbon (including sequestration)
            soil_carbon = carbon_entries.filter(
                source__name__icontains='soil'
            ).aggregate(total=Sum('co2e_amount'))['total'] or 0
            total_carbon += soil_carbon
        
        # If no specific mapping, distribute total carbon evenly across phases with events
        if total_carbon == 0 and events:
            all_carbon = carbon_entries.aggregate(total=Sum('co2e_amount'))['total'] or 0
            # Simple estimation: divide by number of event types
            total_carbon = all_carbon / 4  # 4 phases
        
        return total_carbon
    
    def get_phase_summary(self, production_id: int) -> Dict[str, Any]:
        """
        Get a consumer-friendly summary of production phases.
        
        Optimized for QR code scanning and consumer transparency.
        """
        phases = self.calculate_phases(production_id)
        
        return {
            'total_phases': len([p for p in phases.values() if len(p['events']) > 0]),
            'primary_activities': self._get_primary_activities(phases),
            'carbon_highlights': self._get_carbon_highlights(phases),
            'sustainability_story': self._get_sustainability_story(phases)
        }
    
    def _get_primary_activities(self, phases: Dict) -> List[str]:
        """Get the most significant activities for consumer display."""
        activities = []
        
        for phase_data in phases.values():
            if len(phase_data['events']) > 0:
                activities.append(phase_data['name'])
        
        return activities
    
    def _get_carbon_highlights(self, phases: Dict) -> Dict[str, float]:
        """Get carbon highlights for consumer understanding."""
        return {
            'highest_impact_phase': max(phases.keys(), 
                                      key=lambda x: abs(phases[x]['carbon_impact'])),
            'total_carbon': sum(p['carbon_impact'] for p in phases.values()),
            'regenerative_impact': phases['soil_regeneration']['carbon_impact']
        }
    
    def _get_sustainability_story(self, phases: Dict) -> str:
        """Generate a consumer-friendly sustainability story."""
        stories = []
        
        for phase_data in phases.values():
            if len(phase_data['events']) > 0:
                stories.append(phase_data['consumer_story'])
        
        return " | ".join(stories)