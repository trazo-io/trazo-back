# Transparency Scoring System & 3-Tier Photo Verification

**Date**: February 2026
**Status**: Active
**Location**: `history/services/transparency_calculator.py`

---

## Overview

Trazo's transparency score measures how thoroughly a farmer documents their agricultural practices. The system uses **weighted category scoring** with a **3-tier photo verification penalty** that applies different photo requirements based on event subtype, not blanket category rules.

### Design Principles

1. **More logging = higher score** (fixes the perverse incentive where carbon-first penalized thorough farmers)
2. **Photo penalties are proportional** to how important visual evidence is for each event type
3. **No dead weight** from categories with zero events in modern productions

---

## Category Weights

7 categories, totaling 100%:

| Category | Weight | Key Subtypes | Rationale |
|----------|--------|--------------|-----------|
| **Production** | 30% | PL, HA, IR, PR, TR, CU, EM, TH | Core farming activities; highest consumer interest |
| **Chemical** | 20% | FE, PE, FU, HE | Highest consumer sensitivity; treatment transparency |
| **Soil** | 18% | ST, OM, CO, PA, TI, CC | Sustainability practices; growing consumer awareness |
| **Pest** | 12% | BR, PI, SC, TM, IP, TA | IPM practices; organic farming indicator |
| **Business** | 10% | Certifications, inspections | Third-party trust signals valuable for consumers |
| **Weather** | 5% | All weather events | Environmental context; low farmer control |
| **General** | 5% | Miscellaneous observations | Supplementary documentation |

### Why Equipment Was Removed

The standalone `EquipmentEvent` model was merged into `ProductionEvent` (subtype `"EM"`) in Sprint 2 Epic 2.1. The old model had 42 legacy records but the frontend no longer creates `EquipmentEvent` instances. Keeping "equipment" as a category with 15% weight meant every new production permanently lost 15% of its potential score from a category that would always have 0 events.

**Weight redistribution**: Production absorbed 5% (25->30%), Soil gained 3% (15->18%), Pest gained 2% (10->12%), Business gained 5% (5->10%).

---

## 3-Tier Photo Verification System

### The Problem with Uniform Photo Penalties

The previous system penalized all events in "critical categories" equally: 50% score reduction if photos were missing. But:

- **Irrigation events** are impractical to photograph (turning on a valve)
- **Weather observations** have no meaningful photo evidence
- **Chemical application labels** are essential for consumer trust
- **Harvest photos** directly build purchase confidence

No major certification program (USDA Organic, GlobalGAP, Rainforest Alliance) requires universal photo evidence across all event types.

### Tier Definitions

#### Tier 1: ESSENTIAL (50% penalty without photos)

Events where photos are critical for consumer trust, prevent gaming, and provide irreplaceable verification.

```
Subtypes: PL, HA, FE, PE, FU, HE, CC, BR, PI
```

| Subtype | Event | Why Essential |
|---------|-------|---------------|
| PL | Planting | Consumers want to see crops being planted |
| HA | Harvesting | Harvest quality directly affects purchase decisions |
| FE | Fertilizer Application | Chemical label photos prove what was applied |
| PE | Pesticide Application | Critical for organic/conventional trust |
| FU | Fungicide Application | Treatment transparency |
| HE | Herbicide Application | Treatment transparency |
| CC | Cover Crop | Sustainability practice verification |
| BR | Beneficial Release | IPM practice proof (releasing beneficial insects) |
| PI | Pest Identification | Visual evidence of pest management decisions |

**Penalty**: Score multiplied by `0.5 + 0.5 * verification_rate`
- 0% photos verified -> 50% of base score
- 50% photos verified -> 75% of base score
- 100% photos verified -> 100% of base score

#### Tier 2: RECOMMENDED (25% penalty without photos)

Events where photos add value but their absence is understandable due to practical constraints.

```
Subtypes: PR, TR, CU, ST, OM, CO, SC, TM, IP
```

| Subtype | Event | Why Recommended |
|---------|-------|-----------------|
| PR | Pruning | Adds visual context but routine activity |
| TR | Transplanting | Useful but logistically hard to capture |
| CU | Cultivation | Soil work documentation |
| ST | Soil Test | Lab results more useful than photo of soil |
| OM | Organic Matter | Composting/amendment documentation |
| CO | Composting | Process documentation |
| SC | Scouting | Field observation records |
| TM | Trap Monitoring | Pest monitoring evidence |
| IP | IPM (Integrated Pest Management) | Practice documentation |

**Penalty**: Score multiplied by `0.75 + 0.25 * verification_rate`
- 0% photos verified -> 75% of base score
- 50% photos verified -> 87.5% of base score
- 100% photos verified -> 100% of base score

#### Tier 3: NO PENALTY (implicit)

Events where photo evidence is impractical, unnecessary, or where the logged data itself is sufficient.

```
Subtypes: IR, EM, TH (Production); PA, TI (Soil); TA (Pest);
          All weather, business, and general events
```

| Subtype | Event | Why No Penalty |
|---------|-------|----------------|
| IR | Irrigation | Turning on a valve; sensor data more useful |
| EM | Equipment Maintenance | Routine; receipt/log more useful than photo |
| TH | Thinning | Routine pruning-adjacent activity |
| PA | pH Adjustment | Lab results matter, not a photo of lime |
| TI | Tillage | Standard field operation |
| TA | Trap Application | Setup is routine |
| All weather | Weather events | Nature photos don't verify weather data |
| All business | Certifications | Certificate documents, not photos |
| All general | General notes | Observations by definition |

**Penalty**: None. Score = base completeness score.

### Blended Multiplier Calculation

When a category contains events from multiple tiers, the penalty is blended by event count:

```python
# Example: Production category with 2 events
# - 1 Planting (PL) = Tier 1, no photo -> multiplier = 0.5
# - 1 Irrigation (IR) = Tier 3, no penalty

tier1_mult = 0.5 + 0.5 * (0/1)  = 0.5   # 0 of 1 PL verified
tier2_mult = not applicable                # no tier 2 events
# Only tier 1 events count for blending
blended = 0.5

# But if the production also had 1 Pruning (PR) = Tier 2:
tier1_mult = 0.5                           # PL unverified
tier2_mult = 0.75                          # PR unverified
blended = (0.5 * 1 + 0.75 * 1) / 2 = 0.625
```

If a category has **no tier 1 or tier 2 events** (e.g., Weather with only tier 3 events), the multiplier is 1.0 (no penalty).

---

## Minimum Image Requirements

Chemical subtypes (FE, PE, FU, HE) require **2+ verified images** (label photo + application evidence). All other subtypes require only **1 verified image**.

### Image Verification Layers

Each image passes through 5 anti-gaming checks:

1. **File size**: 10KB minimum, 50MB maximum
2. **Format validation**: JPEG, PNG, WebP, TIFF magic number check
3. **Content analysis**: Rejects solid-color/blank images (variance < 100), extreme aspect ratios (> 10:1), tiny dimensions (< 100x100px)
4. **Hash comparison**: Known dummy/placeholder image detection
5. **Timestamp correlation**: Photo must be within 7 days of event date

---

## Score Calculation Flow

```
For each production:
  1. Determine expected event count (crop type + farming approach + duration)
  2. For each of 7 categories:
     a. Count actual events
     b. Classify each event into tier 1, 2, or 3
     c. Check photo verification for each event
     d. Calculate base completeness = min(actual/expected, 100%)
     e. Calculate blended photo multiplier from tier rates
     f. Final category score = base * blended_multiplier
  3. Weighted sum: sum(category_score * category_weight) / sum(weights)
  4. Result: 0-100 transparency percentage
```

---

## API Response: `photo_tier_summary`

Each category in the breakdown now includes tier-level photo data:

```json
{
  "production": {
    "actual_count": 4,
    "photo_verified_count": 1,
    "completeness_percentage": 75.2,
    "photo_tier_summary": {
      "essential": { "total": 2, "verified": 1 },
      "recommended": { "total": 1, "verified": 0 }
    }
  }
}
```

The frontend uses this to show differentiated messaging:
- Essential events missing photos: **"X events require photos for full score"**
- Only recommended events missing: **"Photos recommended for X events"**
- No tier 1/2 events in category: no photo messaging shown

---

## Files

| File | Role |
|------|------|
| `history/services/transparency_calculator.py` | Core calculation engine |
| `trazo-app/src/views/Dashboard/Dashboard/Establishment/TransparencyDashboard.tsx` | Farmer-facing dashboard |
| `history/management/commands/update_trust_metrics.py` | Batch recalculation command |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-23 | Removed dead "equipment" category (0 events for new productions, 15% permanent drag). Redistributed weight to production, soil, pest, business. |
| 2026-02-23 | Implemented 3-tier photo system replacing uniform 50% penalty. Essential (50%), Recommended (25%), No penalty tiers based on event subtype. |
| 2026-02-23 | Simplified min-image requirement: only chemical subtypes need 2+ photos. |
| 2026-02-23 | Added `photo_tier_summary` to API response for frontend tier-aware messaging. |

---

*Last Updated: 2026-02-23*
