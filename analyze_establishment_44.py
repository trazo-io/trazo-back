#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings.dev')
django.setup()

from history.models import History
from company.models import Establishment

def analyze_establishment_44():
    print("=== Analyzing Establishment 44 Transparency Score ===\n")
    
    try:
        # Get establishment 44
        establishment = Establishment.objects.get(id=44)
        print(f"Establishment: {establishment.name}")
        
        # Get productions for establishment 44
        productions = History.objects.filter(parcel__establishment=establishment)
        print(f"Number of productions: {productions.count()}\n")
        
        total_transparency = 0
        total_productions = 0
        
        # Analyze each production
        for i, production in enumerate(productions, 1):
            print(f"--- Production {i} (ID: {production.id}) ---")
            print(f"Name: {production.name}")
            print(f"Published: {production.published}")
            print(f"Stored Transparency Score: {production.transparency_score}")
            
            # Count events for each production
            production_events = production.history_productionevent_events.count()
            chemical_events = production.history_chemicalevent_events.count()
            weather_events = production.history_weatherevent_events.count()
            general_events = production.history_generalevent_events.count()
            equipment_events = production.history_equipmentevent_events.count()
            soil_events = production.history_soilmanagementevent_events.count()
            pest_events = production.history_pestmanagementevent_events.count()
            business_events = production.history_businessevent_events.count()
            
            total_events = (production_events + chemical_events + weather_events + 
                          general_events + equipment_events + soil_events + 
                          pest_events + business_events)
            
            print(f"Events breakdown:")
            print(f"  - Production: {production_events}")
            print(f"  - Chemical: {chemical_events}")
            print(f"  - Weather: {weather_events}")
            print(f"  - General: {general_events}")
            print(f"  - Equipment: {equipment_events}")
            print(f"  - Soil: {soil_events}")
            print(f"  - Pest: {pest_events}")
            print(f"  - Business: {business_events}")
            print(f"  - TOTAL: {total_events}")
            
            # Count photos (if album exists)
            photo_count = 0
            if production.album:
                photo_count = production.album.images.count()
            print(f"Photos: {photo_count}")
            
            # Calculate transparency score using the model method
            try:
                calculated_score = production.calculate_transparency_score()
                print(f"Calculated Transparency Score: {calculated_score}")
            except Exception as e:
                print(f"Error calculating transparency score: {e}")
                calculated_score = 0
            
            # Manual calculation based on CarbonSummaryCard logic
            # Base score: (events / 10) * 60, max 60
            base_score = min(60, (total_events / 10) * 60)
            # Photo bonus: (photos / 5) * 20, max 20  
            photo_bonus = min(20, (photo_count / 5) * 20)
            # Production bonus: not used in establishment average
            
            manual_score = base_score + photo_bonus
            print(f"Manual calculation: base({base_score:.1f}) + photo({photo_bonus:.1f}) = {manual_score:.1f}")
            
            if production.published:
                total_transparency += calculated_score or manual_score
                total_productions += 1
            
            print()
        
        # Calculate establishment average
        if total_productions > 0:
            establishment_avg = total_transparency / total_productions
            print(f"=== ESTABLISHMENT AVERAGE ===")
            print(f"Total transparency score: {total_transparency:.1f}")
            print(f"Published productions: {total_productions}")
            print(f"Average transparency: {establishment_avg:.1f}%")
            
            # Check with production bonus calculation (as in CarbonSummaryCard)
            production_bonus = min(20, (total_productions / 3) * 20)
            establishment_with_bonus = establishment_avg + production_bonus
            print(f"With production bonus (+{production_bonus:.1f}): {establishment_with_bonus:.1f}%")
        else:
            print("No published productions found")
    
    except Establishment.DoesNotExist:
        print("Establishment 44 not found")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_establishment_44()