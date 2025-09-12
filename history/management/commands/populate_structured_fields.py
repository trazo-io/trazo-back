"""
Management command to populate structured fields from legacy text data
Usage: python manage.py populate_structured_fields [--dry-run] [--event-type chemical|equipment|production|all]
"""

import re
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from history.models import ChemicalEvent, EquipmentEvent, ProductionEvent


class Command(BaseCommand):
    help = 'Populate structured fields from legacy text data in event models'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes'
        )
        parser.add_argument(
            '--event-type',
            type=str,
            choices=['chemical', 'equipment', 'production', 'all'],
            default='all',
            help='Type of events to process (default: all)'
        )

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        event_type = options['event_type']
        
        if self.dry_run:
            self.stdout.write(
                self.style.WARNING('🔍 DRY RUN MODE - No changes will be made')
            )
        
        with transaction.atomic():
            if event_type in ['chemical', 'all']:
                self.process_chemical_events()
            
            if event_type in ['equipment', 'all']:
                self.process_equipment_events()
            
            if event_type in ['production', 'all']:
                self.process_production_events()
            
            if self.dry_run:
                # Rollback transaction in dry-run mode
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.SUCCESS('✅ Dry run complete - no changes made')
                )

    def parse_npk_content(self, concentration_str):
        """Parse NPK values from concentration string like '10-10-10' or '20-5-10'"""
        if not concentration_str:
            return None, None, None
        
        try:
            concentration_str = str(concentration_str).strip().lower()
            
            # Skip if it's clearly not NPK data
            skip_terms = ['unknown', 'n/a', 'na', 'none', 'null', 'organic', 'liquid', 'granular']
            if any(term in concentration_str for term in skip_terms):
                return None, None, None
            
            # Try to parse NPK format (N-P-K)
            if "-" in concentration_str:
                parts = concentration_str.split("-")
                if len(parts) >= 3:
                    try:
                        return float(parts[0]), float(parts[1]), float(parts[2])
                    except ValueError:
                        pass

            # Try to extract percentage from text
            numbers = re.findall(r"\d+(?:\.\d+)?", concentration_str)
            if len(numbers) >= 3:
                try:
                    return float(numbers[0]), float(numbers[1]), float(numbers[2])
                except ValueError:
                    pass

            # Single number case - assume balanced fertilizer
            if len(numbers) == 1:
                try:
                    n = float(numbers[0])
                    return n, n/2, n/2  # Common ratio approximation
                except ValueError:
                    pass
                    
        except Exception as e:
            self.stderr.write(f"Error parsing NPK content '{concentration_str}': {e}")
        
        return None, None, None

    def normalize_application_method(self, way_of_application):
        """Normalize application method to structured choices"""
        if not way_of_application:
            return None
        
        method = str(way_of_application).strip().lower()
        
        # Mapping legacy text to structured choices
        if any(term in method for term in ['broadcast', 'spread', 'scatter']):
            return 'broadcast'
        elif any(term in method for term in ['inject', 'band', 'side-dress', 'sidedress']):
            return 'injection'
        elif any(term in method for term in ['foliar', 'spray', 'leaf']):
            return 'foliar' 
        elif any(term in method for term in ['drip', 'fertigation', 'irrigate']):
            return 'drip'
        elif any(term in method for term in ['band', 'banding', 'placement']):
            return 'banding'
        
        return None

    def extract_numeric_value(self, text, default=None):
        """Extract first numeric value from text"""
        if not text:
            return default
        
        try:
            text = str(text).strip().lower()
            
            # Handle "unknown" values
            if text in ["unknown", "n/a", "na", "", "none", "null"]:
                return default
                
            numbers = re.findall(r"\d+(?:\.\d+)?", text)
            return float(numbers[0]) if numbers else default
        except:
            return default

    def process_chemical_events(self):
        """Process ChemicalEvent records"""
        self.stdout.write('🧪 Processing ChemicalEvent records...')
        
        events = ChemicalEvent.objects.all()
        total_count = events.count()
        updated_count = 0
        
        for event in events:
            updated = False
            changes = []
            
            # Parse NPK from concentration
            if event.concentration and not any([event.nitrogen_percentage, event.phosphorus_percentage, event.potassium_percentage]):
                n, p, k = self.parse_npk_content(event.concentration)
                if n is not None and p is not None and k is not None:
                    if not self.dry_run:
                        event.nitrogen_percentage = n
                        event.phosphorus_percentage = p
                        event.potassium_percentage = k
                    updated = True
                    changes.append(f"NPK: N={n}, P={p}, K={k}")
            
            # Normalize application method
            if event.way_of_application and not event.application_method_structured:
                method = self.normalize_application_method(event.way_of_application)
                if method:
                    if not self.dry_run:
                        event.application_method_structured = method
                    updated = True
                    changes.append(f"Method: {method}")
            
            if updated:
                if not self.dry_run:
                    event.save()
                updated_count += 1
                
                if self.dry_run:
                    self.stdout.write(f"  Would update event {event.id}: {', '.join(changes)}")
        
        self.stdout.write(
            self.style.SUCCESS(f"✅ {'Would update' if self.dry_run else 'Updated'} {updated_count}/{total_count} ChemicalEvent records")
        )

    def process_equipment_events(self):
        """Process EquipmentEvent records"""
        self.stdout.write('🚜 Processing EquipmentEvent records...')
        
        events = EquipmentEvent.objects.all()
        total_count = events.count()
        updated_count = 0
        
        for event in events:
            updated = False
            changes = []
            
            # Copy fuel_amount to fuel_consumed
            if hasattr(event, 'fuel_amount') and event.fuel_amount and not event.fuel_consumed:
                try:
                    fuel_value = float(event.fuel_amount)
                    if not self.dry_run:
                        event.fuel_consumed = fuel_value
                        event.fuel_unit = 'L'
                    updated = True
                    changes.append(f"Fuel: {fuel_value}L")
                except (ValueError, TypeError):
                    pass
            
            # Copy hours_used to hours_operated
            if hasattr(event, 'hours_used') and event.hours_used and not event.hours_operated:
                try:
                    hours_value = float(event.hours_used)
                    if not self.dry_run:
                        event.hours_operated = hours_value
                    updated = True
                    changes.append(f"Hours: {hours_value}")
                except (ValueError, TypeError):
                    pass
            
            # Set default efficiency
            if not event.operation_efficiency:
                if not self.dry_run:
                    event.operation_efficiency = 'normal'
                updated = True
                changes.append("Efficiency: normal")
            
            if updated:
                if not self.dry_run:
                    event.save()
                updated_count += 1
                
                if self.dry_run:
                    self.stdout.write(f"  Would update event {event.id}: {', '.join(changes)}")
        
        self.stdout.write(
            self.style.SUCCESS(f"✅ {'Would update' if self.dry_run else 'Updated'} {updated_count}/{total_count} EquipmentEvent records")
        )

    def process_production_events(self):
        """Process ProductionEvent records"""
        self.stdout.write('🌱 Processing ProductionEvent records...')
        
        events = ProductionEvent.objects.all()
        total_count = events.count()
        updated_count = 0
        
        for event in events:
            updated = False
            changes = []
            
            # Try to extract area from history.parcel
            if not event.area_covered and event.history and hasattr(event.history, 'parcel') and event.history.parcel:
                try:
                    if hasattr(event.history.parcel, 'area'):
                        area_value = self.extract_numeric_value(event.history.parcel.area)
                        if area_value:
                            if not self.dry_run:
                                event.area_covered = area_value
                                event.area_unit = 'ha'
                            updated = True
                            changes.append(f"Area: {area_value} ha")
                except (AttributeError, ValueError):
                    pass
            
            # Set default efficiency and units
            defaults = [
                ('production_efficiency', 'normal'),
                ('fuel_unit', 'L'),
                ('transportation_unit', 'km'),
                ('yield_unit', 'kg'),
            ]
            
            for field, default_value in defaults:
                if not getattr(event, field):
                    if not self.dry_run:
                        setattr(event, field, default_value)
                    updated = True
                    changes.append(f"{field}: {default_value}")
            
            if updated:
                if not self.dry_run:
                    event.save()
                updated_count += 1
                
                if self.dry_run:
                    self.stdout.write(f"  Would update event {event.id}: {', '.join(changes)}")
        
        self.stdout.write(
            self.style.SUCCESS(f"✅ {'Would update' if self.dry_run else 'Updated'} {updated_count}/{total_count} ProductionEvent records")
        )