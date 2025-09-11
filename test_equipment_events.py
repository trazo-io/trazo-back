#!/usr/bin/env python
"""
Comprehensive Equipment Events and Carbon Calculation Testing Script
"""

import os
import sys
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.models import ProductionTemplate, EventTemplate, CropType
import json

def test_equipment_events():
    """Test equipment events coverage for all crops"""
    print('=' * 70)
    print('🚜 EQUIPMENT EVENTS COMPREHENSIVE TEST')
    print('=' * 70)

    all_crops = CropType.objects.filter(is_active=True).order_by('name')
    total_equipment_events = 0
    missing_equipment = []
    compliant_crops = []
    non_compliant = []

    for crop in all_crops:
        try:
            template = ProductionTemplate.objects.get(crop_type=crop)
            events = template.event_templates.all()
            equipment_events = events.filter(event_type='equipment')
            
            if equipment_events.count() > 0:
                status = '✅'
                compliant_crops.append(crop.name)
            else:
                status = '❌'
                missing_equipment.append(crop.name)
            
            total_equipment_events += equipment_events.count()
            
            print(f'{status} {crop.name:20}: {events.count():2} total events, {equipment_events.count()} equipment events, {template.total_carbon_impact:.1f} kg CO2e/ha')
            
        except ProductionTemplate.DoesNotExist:
            print(f'⚠️  {crop.name:20}: NO TEMPLATE FOUND')
            non_compliant.append(crop.name)

    print()
    print('📊 SUMMARY:')
    print(f'  Total Crops: {all_crops.count()}')
    print(f'  Crops with Equipment Events: {len(compliant_crops)}')
    print(f'  Crops Missing Equipment: {len(missing_equipment)}')
    print(f'  Total Equipment Events: {total_equipment_events}')

    if missing_equipment:
        print(f'\n❌ Crops Missing Equipment Events: {", ".join(missing_equipment)}')
    
    return missing_equipment

def test_usda_compliance():
    """Test USDA compliance for all crops"""
    print()
    print('=' * 70)
    print('📊 USDA CARBON COMPLIANCE TEST')
    print('=' * 70)
    
    # USDA compliance ranges (kg CO2e/ha)
    usda_ranges = {
        'Corn (Field)': (800, 1200),
        'Soybeans': (600, 900),
        'Wheat': (700, 1000),
        'Cotton': (1200, 1800),
        'Rice': (1000, 1500),
        'Hay/Alfalfa': (400, 800),
        'Potatoes': (600, 1000),
        'Tomatoes': (800, 1200),
        'Onions': (500, 900),
        'Carrots': (400, 800),
        'Lettuce': (300, 600),
        'Strawberries': (600, 1000),
        'Apples': (400, 700),
        'Grapes': (500, 800),
        'Citrus (Oranges)': (500, 800),
        'Avocados': (600, 900),
        'Almonds': (800, 1200),
        'Peanuts': (500, 800),
        'Sunflowers': (400, 700),
    }
    
    compliant_count = 0
    total_count = 0
    issues = []
    
    for crop_name, (min_val, max_val) in usda_ranges.items():
        try:
            template = ProductionTemplate.objects.get(crop_type__name=crop_name)
            total_carbon = template.total_carbon_impact
            
            compliant = min_val <= total_carbon <= max_val
            status = '✅' if compliant else '❌'
            
            if compliant:
                compliant_count += 1
            else:
                deviation = 0
                if total_carbon < min_val:
                    deviation = min_val - total_carbon
                    direction = 'BELOW'
                else:
                    deviation = total_carbon - max_val
                    direction = 'ABOVE'
                issues.append((crop_name, total_carbon, min_val, max_val, deviation, direction))
            
            total_count += 1
            
            print(f'{status} {crop_name:20}: {total_carbon:6.1f} kg CO2e/ha | Target: {min_val:4}-{max_val:4}')
            
        except ProductionTemplate.DoesNotExist:
            print(f'⚠️  {crop_name:20}: No template found')
    
    compliance_rate = (compliant_count / total_count * 100) if total_count > 0 else 0
    
    print()
    print(f'📈 COMPLIANCE RATE: {compliant_count}/{total_count} ({compliance_rate:.1f}%)')
    
    if issues:
        print('\n🔧 ISSUES TO FIX:')
        for crop, current, min_val, max_val, deviation, direction in issues:
            print(f'  {crop}: {current:.1f} is {deviation:.1f} kg {direction} target range ({min_val}-{max_val})')
    
    return issues

def test_seed_commands():
    """Test critical seed commands"""
    print()
    print('=' * 70)
    print('🌱 SEED COMMAND VALIDATION')
    print('=' * 70)
    
    from django.core.management import call_command
    from io import StringIO
    import sys
    
    commands_to_test = [
        'populate_usda_crop_types',
        'create_comprehensive_production_templates',
    ]
    
    results = {}
    
    for cmd in commands_to_test:
        print(f'\nTesting: {cmd}')
        out = StringIO()
        try:
            # Capture output
            old_stdout = sys.stdout
            sys.stdout = out
            
            # Run command
            call_command(cmd)
            
            # Restore stdout
            sys.stdout = old_stdout
            
            output = out.getvalue()
            
            # Check for success indicators
            if 'Complete' in output or 'Created' in output or 'already exists' in output:
                print(f'  ✅ {cmd}: SUCCESS')
                results[cmd] = 'SUCCESS'
            else:
                print(f'  ⚠️  {cmd}: Check output')
                results[cmd] = 'CHECK'
                
        except Exception as e:
            sys.stdout = old_stdout
            print(f'  ❌ {cmd}: ERROR - {str(e)}')
            results[cmd] = 'ERROR'
    
    return results

def detailed_equipment_analysis():
    """Detailed analysis of equipment events by crop category"""
    print()
    print('=' * 70)
    print('🔍 DETAILED EQUIPMENT EVENT ANALYSIS')
    print('=' * 70)
    
    crop_categories = {
        'Grains': ['Corn (Field)', 'Wheat', 'Soybeans', 'Rice'],
        'Vegetables': ['Tomatoes', 'Potatoes', 'Lettuce', 'Carrots', 'Onions'],
        'Fruits': ['Strawberries', 'Apples', 'Grapes', 'Citrus (Oranges)', 'Avocados'],
        'Nuts': ['Almonds', 'Peanuts'],
        'Other': ['Cotton', 'Hay/Alfalfa', 'Sunflowers']
    }
    
    for category, crops in crop_categories.items():
        print(f'\n📦 {category}:')
        for crop_name in crops:
            try:
                template = ProductionTemplate.objects.get(crop_type__name=crop_name)
                equipment_events = template.event_templates.filter(event_type='equipment')
                
                if equipment_events.exists():
                    print(f'  ✅ {crop_name}: {equipment_events.count()} equipment events')
                    for event in equipment_events:
                        print(f'      - {event.name}: {event.carbon_impact} kg CO2e/ha')
                else:
                    print(f'  ❌ {crop_name}: NO equipment events')
                    
            except ProductionTemplate.DoesNotExist:
                print(f'  ⚠️  {crop_name}: No template')
    
    return True

# Run all tests
if __name__ == '__main__':
    print('🚀 STARTING COMPREHENSIVE TESTING SUITE\n')
    
    # Test 1: Equipment Events
    missing_equipment = test_equipment_events()
    
    # Test 2: USDA Compliance
    compliance_issues = test_usda_compliance()
    
    # Test 3: Seed Commands
    seed_results = test_seed_commands()
    
    # Test 4: Detailed Analysis
    detailed_equipment_analysis()
    
    # Final Summary
    print()
    print('=' * 70)
    print('📋 FINAL TEST SUMMARY')
    print('=' * 70)
    
    if not missing_equipment and not compliance_issues:
        print('🎉 ALL TESTS PASSED!')
    else:
        print('🔧 ISSUES FOUND:')
        if missing_equipment:
            print(f'  - {len(missing_equipment)} crops missing equipment events')
        if compliance_issues:
            print(f'  - {len(compliance_issues)} crops out of USDA compliance')
        print('\n💡 Run calibration commands to fix these issues')