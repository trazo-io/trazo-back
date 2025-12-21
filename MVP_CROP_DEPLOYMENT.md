# Trazo MVP Crop Types & Templates Deployment Guide

## Overview

This document provides the complete deployment checklist for seeding USDA-verified crop types and production templates in the Trazo production environment.

**Single Command**: All crop data (types + templates + events) is seeded by ONE command:
```bash
poetry run python manage.py populate_usda_crop_types
```

---

## Pre-Deployment Checklist

### 1. Database Access
- [ ] Verify production database connection
- [ ] Ensure migrations are up to date
- [ ] Have database backup ready (recommended)

### 2. Environment Setup
```bash
# SSH to production server or connect to ECS task
cd /app  # or wherever Django project is located

# Verify Django settings
echo $DJANGO_SETTINGS_MODULE  # Should be appropriate for production
```

---

## Deployment Steps

### Step 1: Run Migrations (if needed)
```bash
poetry run python manage.py migrate
```

### Step 2: Preview Changes (Dry-Run)
```bash
poetry run python manage.py populate_usda_crop_types --dry-run
```

Expected output:
```
DRY RUN MODE - No changes will be made
============================================================
TRAZO MVP - USDA Crop Data Seeding
============================================================

19 crop types would be created/updated
19 production templates would be created
~120 event templates would be created

✅ After running, production dropdown will show 19 USDA-verified crop types!
```

### Step 3: Execute Seeding
```bash
poetry run python manage.py populate_usda_crop_types
```

Expected output:
```
============================================================
TRAZO MVP - USDA Crop Data Seeding
============================================================

📦 Step 1: Seeding USDA Crop Types...
   ✅ Created: Corn (Field)
   ✅ Created: Wheat
   ... (19 total)

📋 Step 2: Seeding Production Templates...
   ✅ Created template: Corn (Field)
   ✅ Created template: Wheat
   ... (19 total)

============================================================
SEEDING COMPLETE
============================================================

📊 SUMMARY:
   Crop Types Created:    19
   Templates Created:     19
   Events Created:        ~120

📈 DATABASE TOTALS:
   Active Crop Types:     19
   Active Templates:      19
   Active Events:         ~120

✅ Production dropdown will show 19 USDA-verified crop types!
```

### Step 4: Verify Deployment
```bash
# Check crop types
poetry run python manage.py shell -c "from carbon.models import CropType; print(f'Crop types: {CropType.objects.filter(is_active=True).count()}')"

# Check templates
poetry run python manage.py shell -c "from carbon.models import ProductionTemplate; print(f'Templates: {ProductionTemplate.objects.filter(is_active=True).count()}')"

# Check events
poetry run python manage.py shell -c "from carbon.models import EventTemplate; print(f'Events: {EventTemplate.objects.filter(is_active=True).count()}')"
```

Expected results:
- Crop types: 19
- Templates: 19
- Events: ~120 (varies by complexity per crop)

---

## Command Options

### Full Seeding (Default)
```bash
poetry run python manage.py populate_usda_crop_types
```
Seeds both crop types AND production templates with events.

### Crops Only
```bash
poetry run python manage.py populate_usda_crop_types --crops-only
```
Only seeds the 19 CropType records (no templates).

### Templates Only
```bash
poetry run python manage.py populate_usda_crop_types --templates-only
```
Only seeds ProductionTemplate + EventTemplate records.
**Note**: Requires crop types to already exist.

### Dry Run (Preview)
```bash
poetry run python manage.py populate_usda_crop_types --dry-run
```
Shows what would be created without making changes.

### Verbose Mode
```bash
poetry run python manage.py populate_usda_crop_types -v 2
```
Shows detailed output including skipped items.

---

## Crop Types Included (19 Total)

### Grains (4)
| Crop | Slug | US Acreage |
|------|------|------------|
| Corn (Field) | `corn_field` | 90M acres |
| Wheat | `wheat` | 47M acres |
| Rice | `rice` | 2.9M acres |
| Soybeans | `soybeans` | 87M acres |

### Other Crops (2)
| Crop | Slug | US Acreage |
|------|------|------------|
| Cotton | `cotton` | 12M acres |
| Sunflowers | `sunflowers` | 1.6M acres |

### Tree Fruits (4)
| Crop | Slug | Value |
|------|------|-------|
| Citrus (Oranges) | `citrus_oranges` | $3.4B |
| Apples | `apples` | $4B+ |
| Grapes | `grapes` | $6B+ |
| Avocados | `avocados` | $500M+ |

### Tree Nuts (1)
| Crop | Slug | Value |
|------|------|-------|
| Almonds | `almonds` | $5.6B |

### Vegetables (5)
| Crop | Slug | Value |
|------|------|-------|
| Tomatoes | `tomatoes` | $2B |
| Potatoes | `potatoes` | $4B+ |
| Lettuce | `lettuce` | $2.9B |
| Carrots | `carrots` | $700M |
| Onions | `onions` | $1B |

### Berries (1)
| Crop | Slug | Value |
|------|------|-------|
| Strawberries | `strawberries` | $3B+ |

### Legumes (1)
| Crop | Slug | Value |
|------|------|-------|
| Peanuts | `peanuts` | $2B |

### Forage (1)
| Crop | Slug | US Acreage |
|------|------|------------|
| Hay/Alfalfa | `hay_alfalfa` | 56M acres |

---

## Regional Coverage

### California (Primary Target Market)
**7 crops optimized for California specialty agriculture:**
- Avocados (highest transparency demand)
- Grapes (6B+ value, wine industry)
- Citrus (Oranges)
- Almonds (California 99%+)
- Lettuce (California 90%+)
- Strawberries (highest value/acre)
- Tomatoes

### Midwest (Secondary Target Market)
**5 crops for large-scale commodity agriculture:**
- Corn (Field)
- Soybeans
- Wheat
- Potatoes
- Sunflowers

### Southeast (Expansion Market)
**3 crops for regional specialization:**
- Cotton
- Rice
- Peanuts

---

## Idempotent Design

The command is **safe to run multiple times**:

1. **Crop Types**: Uses `update_or_create()` - existing crops are updated, not duplicated
2. **Templates**: Checks for existing templates before creating
3. **Events**: Created fresh only when template is new

**Re-running the command** after initial deployment will:
- Update any changed crop data (fields, descriptions, etc.)
- Skip existing templates (shows "⏭️ Template exists")
- Not create duplicate events

---

## Troubleshooting

### "Crop 'X' not found" Error
If running with `--templates-only` and crops don't exist:
```bash
# Run full command instead
poetry run python manage.py populate_usda_crop_types
```

### Template Not Appearing
Check if template is active:
```bash
poetry run python manage.py shell -c "from carbon.models import ProductionTemplate; print(ProductionTemplate.objects.filter(slug__contains='corn').values('slug', 'is_active'))"
```

### Verify API Endpoint
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" https://api.trazo.app/carbon/crop-types/dropdown/
```
Should return 19 crop types.

---

## Post-Deployment

### Frontend Verification
1. Log into Trazo dashboard
2. Navigate to Production > New Production
3. Click Crop Type dropdown
4. Verify all 19 crops are visible

### Consumer QR Verification
1. Create a test production with new crop (e.g., Avocados)
2. Add sample events
3. Generate QR code
4. Scan and verify transparency display

---

## Files Reference

**Single Source of Truth:**
```
trazo-back/carbon/management/commands/populate_usda_crop_types.py
```

This file contains:
- 19 USDA-verified crop type definitions
- 19 production template configurations
- ~120 event template definitions
- Complete MVP deployment checklist (in docstring)

**Deprecated (DELETED):**
- ~~`seed_tier1_crop_templates.py`~~ - Merged into main command
- ~~`seed_crop_templates.py`~~ - Old 6-crop version (still exists but superseded)

---

## Support

For issues with crop data seeding, contact the development team or check:
- GitHub Issues: https://github.com/trazo/trazo-back/issues
- Slack: #trazo-dev

---

*Last Updated: December 2024*
*Document Version: 1.0*
