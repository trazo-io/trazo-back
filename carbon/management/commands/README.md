# Carbon Management Commands - Deployment Guide

This guide provides the exact process for setting up the complete carbon calculation system in staging and production environments.

## 🚀 Fresh Environment Setup (No Existing Data)

Use this process when deploying to a clean environment with no crops, production templates, or event templates.

### Prerequisites

- Django environment properly configured
- Poetry installed and virtual environment activated
- Database migrations applied
- USDA API keys configured in environment variables:
  - `USDA_NASS_API_KEY`
  - `USDA_ERS_API_KEY` 
  - `USDA_FOODDATA_API_KEY`

### Step-by-Step Deployment Process

#### Step 1: Create Crop Types (Required First)
```bash
poetry run python manage.py populate_usda_crop_types
```
**What it does:**
- Creates 19 crop types covering 312.5M acres (91.8% of US agriculture)
- Includes major crops: Corn, Soybeans, Wheat, Rice, Cotton, Hay/Alfalfa
- Includes vegetables: Tomatoes, Potatoes, Lettuce, Carrots, Onions
- Includes fruits/nuts: Strawberries, Apples, Grapes, Citrus, Avocados, Almonds
- Includes strategic additions: Peanuts, Sunflowers

**Expected output:**
```
✅ Created 19 crop types successfully
📊 Coverage: 312.5M acres (91.8% of US agriculture)
```

#### Step 2: Create Base Production Templates
```bash
poetry run python manage.py create_comprehensive_production_templates
```
**What it does:**
- Creates 19 production templates (one for each crop type)
- Creates ~114 base event templates (6 events per crop average)
- Covers all essential farming operations: land prep, fertilizer, planting, pest control, irrigation, harvest

**Expected output:**
```
✅ Created 19 production templates
✅ Created 114 event templates
📋 All crops now have basic operational templates
```

#### Step 3: Add Equipment Events (Critical for Carbon Accuracy)
```bash
poetry run python manage.py enhance_production_templates_with_equipment
```
**What it does:**
- Adds 70+ equipment-specific events to existing templates
- Includes tractors, combines, sprayers, tillage equipment
- Provides equipment-level carbon tracking (addresses 20-40% carbon undercount)
- Maintains existing event templates while adding equipment operations

**Expected output:**
```
🚜 EQUIPMENT EVENTS ENHANCEMENT COMPLETE
✅ Enhanced 19 production templates with equipment events
✅ Added 76 equipment-specific events
📊 Major crops now include: Fall Tillage, Spring Prep, Precision Planting, Cultivation, Harvest Equipment
```

#### Step 4: Calibrate Carbon Footprints to USDA Standards
```bash
# First, validate current compliance (optional but recommended)
poetry run python manage.py calibrate_carbon_to_usda_standards --validate-only

# Then apply calibrations
poetry run python manage.py calibrate_carbon_to_usda_standards
```
**What it does:**
- Adjusts fertilizer and equipment carbon impacts to USDA research standards
- Ensures carbon footprints match Agricultural Research Service data
- Targets: Corn (800-1200 kg CO2e/ha), Soybeans (600-900 kg CO2e/ha), etc.
- Validates compliance across all crops

**Expected output:**
```
📊 CALIBRATING TEMPLATES TO USDA STANDARDS
✅ Corn (Field):    590.0 → 1015.0 kg CO2e/ha (Target: 800-1200)
✅ Soybeans:        590.0 →  845.0 kg CO2e/ha (Target: 600-900)
✅ Wheat:           590.0 →  920.0 kg CO2e/ha (Target: 700-1000)
🎉 Calibration Complete! Updated 19 crop templates
📈 COMPLIANCE SUMMARY: 19/19 crops compliant (100%)
🏆 EXCELLENT: High USDA compliance achieved!
```

### Final Verification

After completing all steps, verify the setup:

```bash
# Check crop types
poetry run python manage.py shell -c "
from carbon.models import CropType
print(f'Crop Types: {CropType.objects.filter(is_active=True).count()}')
"

# Check production templates  
poetry run python manage.py shell -c "
from carbon.models import ProductionTemplate
print(f'Production Templates: {ProductionTemplate.objects.count()}')
"

# Check event templates
poetry run python manage.py shell -c "
from carbon.models import EventTemplate  
print(f'Event Templates: {EventTemplate.objects.count()}')
"

# Check carbon compliance
poetry run python manage.py calibrate_carbon_to_usda_standards --validate-only
```

**Expected final state:**
- ✅ 19 active crop types
- ✅ 19 production templates  
- ✅ 180+ total event templates (base + equipment)
- ✅ 100% USDA compliance for carbon calculations

## 🔄 Existing Environment Updates

If you already have crops and templates but want to add enhancements:

### Option A: Add Only Equipment Events
```bash
# Safe - won't overwrite existing templates
poetry run python manage.py enhance_production_templates_with_equipment
```

### Option B: Add Only USDA Calibration  
```bash
# Safe - only adjusts carbon_impact values
poetry run python manage.py calibrate_carbon_to_usda_standards
```

### Option C: Add New Crop Types Only
```bash
# Safe - won't duplicate existing crops
poetry run python manage.py populate_usda_crop_types
```

## ⚠️ Important Notes

### Database Backup (CRITICAL)
Always backup your database before running commands in production:
```bash
# For PostgreSQL
pg_dump trazo_production > backup_$(date +%Y%m%d_%H%M%S).sql
```

### Environment Variables Required
Ensure these USDA API keys are configured:
```bash
# Check if keys are loaded
poetry run python manage.py shell -c "
import os
keys = ['USDA_NASS_API_KEY', 'USDA_ERS_API_KEY', 'USDA_FOODDATA_API_KEY']
for key in keys:
    status = '✅' if os.getenv(key) else '❌'
    print(f'{status} {key}: {\"Configured\" if os.getenv(key) else \"Missing\"}')
"
```

### Safe Command Execution
All commands are designed to be:
- ✅ **Idempotent**: Can be run multiple times safely
- ✅ **Non-destructive**: Won't delete existing data
- ✅ **Additive**: Only adds or updates, never removes
- ✅ **Atomic**: Use database transactions for consistency

### Performance Considerations
- Each command processes 19 crop types
- Total execution time: ~2-3 minutes for all commands
- Safe to run during low-traffic periods
- No downtime required

## 🆘 Troubleshooting

### "No module named 'carbon'" Error
```bash
# Ensure you're in the correct directory
cd /path/to/trazo-back
poetry shell
```

### "CropType matching query does not exist" Error
```bash  
# Run populate_usda_crop_types first
poetry run python manage.py populate_usda_crop_types
```

### "USDA API key not configured" Error
```bash
# Check environment variables
echo $USDA_NASS_API_KEY
echo $USDA_ERS_API_KEY  
echo $USDA_FOODDATA_API_KEY
```

### Carbon Calculations Still Inaccurate
```bash
# Force recalibration
poetry run python manage.py calibrate_carbon_to_usda_standards
```

## 📊 Expected Results

After successful deployment:
- **Farmers**: Can create productions for any major US crop
- **Carbon Tracking**: Equipment-level accuracy (±10% of USDA standards)
- **Market Coverage**: 312.5M acres (91.8% of US agriculture)  
- **Event Templates**: 180+ comprehensive farming operations
- **Compliance**: 100% USDA Agricultural Research Service standards

---

**Last Updated**: 2025-01-09  
**Commands Version**: v2.0 (Enhanced with Equipment Events)  
**Compatibility**: Django 4.2+, PostgreSQL 13+