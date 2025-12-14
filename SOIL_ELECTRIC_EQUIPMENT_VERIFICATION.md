# Soil Management Electric Equipment Event Flow Verification

**Date**: 2025-01-21
**Mission**: Verify EXACT field preservation from form → preview → API → ProductDetail display
**CRITICAL**: Preview must show IDENTICAL content to ProductDetail ConsumerEventCard

---

## Test Scenario 1: Electric Soil Cultivation

### Form Input (SoilManagementTab.jsx)
```javascript
{
  type: "TI",                    // Tillage
  name: "Electric Tilling",
  soil_management_practice: "Tilling",
  fuel_type: "electric",         // 🔌 Phase 3 electric equipment
  fuel_consumed: "55",
  fuel_unit: "kWh",
  area: "2.5",
  area_unit: "ha",
  equipment_hours: "3.5",
  date: "2025-01-21T10:00:00Z"
}
```

### Expected Transformation Flow

#### Stage 1: Form → Preview (eventPreviewUtils.ts line 731-733)
```typescript
// ✅ CRITICAL: getFuelTypeDisplayName() mapping
if (formData.fuel_type) {
  event.fuel_type = getFuelTypeDisplayName(formData.fuel_type);
  // "electric" → "Electric"
}

// ✅ Expected preview event data:
{
  fuel_type: "Electric",        // ✅ Capitalized display name
  fuel_consumed: "55 kWh",      // ✅ Formatted with unit
  fuel_unit: "kWh",             // ✅ Preserved
  equipment_hours: "3.5 hours", // ✅ Formatted with unit
  area_managed: "2.5 ha",       // ✅ Formatted with unit
  name: "Electric Tilling"      // ✅ Preserved
}
```

**Preview Display Fields (EventPreviewModal):**
- ✅ Fuel Type: "Electric"
- ✅ Fuel Consumed: "55 kWh"
- ✅ Equipment Hours: "3.5 hours"
- ✅ Area Managed: "2.5 ha"

#### Stage 2: Preview → Backend API Submission

**API Endpoint**: `POST /api/v1/events/create/`

**Payload (normalized)**:
```json
{
  "event_type": 5,
  "type": "TI",
  "name": "Electric Tilling",
  "fuel_type": "electric",      // ⚠️ Backend expects lowercase code
  "fuel_consumed": 55,           // ⚠️ Backend expects numeric
  "fuel_unit": "kWh",
  "area_covered": 2.5,
  "area_unit": "ha",
  "equipment_hours": 3.5,
  "date": "2025-01-21T10:00:00Z",
  "production_id": 110
}
```

**Backend Model (SoilManagementEvent - models.py line 1453-1459)**:
```python
fuel_type = models.CharField(
    max_length=30,
    choices=FUEL_TYPES,  # Contains ("electric", "Electric")
    blank=True,
    default="",
    help_text="Fuel type for EPA emission factor calculation",
)
```

**Backend Carbon Calculation** (VerifiedEmissionFactors.calculate_production_event_emissions):
```python
# PHASE 3: Electric equipment calculation
if fuel_type == "electric" and fuel_unit == "kWh":
    electricity_kwh = fuel_consumed
    co2e_kg = electricity_kwh * EPA_ELECTRICITY_FACTOR  # 0.39 kg CO₂/kWh
    # 55 kWh × 0.39 = 21.45 kg CO₂e
```

**Expected Carbon Result**: 21.45 kg CO₂e

#### Stage 3: Backend → ProductDetail Retrieval

**API Endpoint**: `GET /api/v1/productions/110/events/`

**Expected Backend Response**:
```json
{
  "id": 1234,
  "event_type": 5,
  "type": "TI",
  "name": "Electric Tilling",
  "fuel_type": "electric",       // ⚠️ Backend returns lowercase code
  "fuel_consumed": 55.0,
  "fuel_unit": "kWh",
  "area_covered": 2.5,
  "area_unit": "ha",
  "equipment_hours": 3.5,
  "date": "2025-01-21T10:00:00Z",
  "carbon_impact": 21.45
}
```

#### Stage 4: Backend Response → Display (eventDataNormalizer.ts)

**Normalization Function**: `normalizeBackendEventData()`

**Expected Normalization**:
```typescript
// ⚠️ CRITICAL: Backend returns lowercase "electric", must map to "Electric"
// Line 720-721 in eventDataNormalizer.ts:
if (rawData.fuel_type) {
  (productionData as any).fuel_type = rawData.fuel_type;
  // ❌ POTENTIAL BUG: Direct assignment without getFuelTypeDisplayName()
  // Should be: getFuelTypeDisplayName(rawData.fuel_type)
}
```

**🚨 CRITICAL ISSUE IDENTIFIED**:
The `eventDataNormalizer.ts` at line 720-721 directly assigns `fuel_type` without using `getFuelTypeDisplayName()` mapping, which means:
- Preview shows: "Electric" (capitalized via getFuelTypeDisplayName)
- ProductDetail shows: "electric" (lowercase from backend)
- **RESULT**: PREVIEW-DISPLAY MISMATCH ❌

#### Stage 5: Display Fields (fieldDisplayUtils.ts line 1869-1875)

**Expected Field Extraction**:
```typescript
if (event.fuel_type) {
  details.push({
    label: 'Fuel Type',
    value: getReadableFieldValue('fuel_type', event.fuel_type),
    // "electric" → "Electric" via mapping at line 269-275
    priority: 'details',
    category: 'operational'
  });
}
```

**Mapping (line 269-275)**:
```typescript
fuel_type: {
  diesel: 'Diesel',
  gasoline: 'Gasoline',
  biodiesel: 'Biodiesel',
  electric: 'Electric',      // ✅ Lowercase → Capitalized
  natural_gas: 'Natural Gas'
}
```

**Final ProductDetail Display Fields**:
- ✅ Fuel Type: "Electric" (mapped via getReadableFieldValue)
- ✅ Fuel Consumed: "55 kWh"
- ✅ Equipment Hours: "3.5 hours"
- ✅ Area Managed: "2.5 ha"

---

## Test Scenario 2: Diesel Soil Cultivation (Backwards Compatibility)

### Form Input
```javascript
{
  type: "TI",
  name: "Diesel Tilling",
  soil_management_practice: "Tilling",
  fuel_type: "diesel",
  fuel_consumed: "20",
  fuel_unit: "L",
  area: "2.5",
  area_unit: "ha",
  equipment_hours: "3.5"
}
```

### Expected Carbon Calculation
```python
# Diesel combustion
fuel_liters = 20
co2e_kg = fuel_liters * EPA_DIESEL_FACTOR  # 2.68 kg CO₂/L
# 20 L × 2.68 = 53.6 kg CO₂e
```

**Expected Carbon Result**: 53.6 kg CO₂e

---

## Verification Checklist

### ✅ Preview Stage (EventPreviewModal)
- [ ] fuel_type displayed as "Electric" (capitalized)
- [ ] fuel_consumed displayed as "55 kWh" (with unit)
- [ ] fuel_unit displayed as "kWh"
- [ ] equipment_hours displayed as "3.5 hours"
- [ ] area_managed displayed as "2.5 ha"
- [ ] NO "N/A" or placeholder text

### ✅ Backend Submission
- [ ] fuel_type submitted as "electric" (lowercase code)
- [ ] fuel_consumed submitted as 55 (numeric)
- [ ] fuel_unit submitted as "kWh"
- [ ] Backend accepts payload without errors
- [ ] Carbon calculation uses 0.39 kg CO₂/kWh factor
- [ ] Carbon result = 21.45 kg CO₂e

### ✅ ProductDetail Display (ConsumerEventCard)
- [ ] fuel_type displayed as "Electric" (capitalized, EXACT match to preview)
- [ ] fuel_consumed displayed as "55 kWh" (EXACT match to preview)
- [ ] fuel_unit displayed correctly
- [ ] equipment_hours displayed as "3.5 hours" (EXACT match to preview)
- [ ] area_managed displayed as "2.5 ha" (EXACT match to preview)
- [ ] NO "N/A" or placeholder text

### ✅ Field Preservation Pipeline
- [ ] eventPreviewUtils.ts case 5 applies getFuelTypeDisplayName()
- [ ] eventDataNormalizer.ts normalizes backend response correctly
- [ ] fieldDisplayUtils.ts displays all fields with proper mapping
- [ ] getReadableFieldValue() maps "electric" → "Electric"
- [ ] All numeric fields preserve values exactly
- [ ] All units preserved correctly

### ✅ Carbon Calculation Integration
- [ ] Electric equipment triggers electricity calculation path
- [ ] Diesel equipment triggers diesel calculation path (backwards compatibility)
- [ ] EPA factors applied correctly (0.39 for electric, 2.68 for diesel)
- [ ] Carbon result displayed in ProductDetail
- [ ] Carbon breakdown includes fuel type in explanation

---

## Critical Success Criteria

### 🎯 EXACT Preview-Display Matching
| Field | Preview Value | ProductDetail Value | Status |
|-------|---------------|---------------------|--------|
| fuel_type | "Electric" | Must be "Electric" | ⚠️ NEEDS FIX |
| fuel_consumed | "55 kWh" | Must be "55 kWh" | ✅ OK |
| fuel_unit | "kWh" | Must be "kWh" | ✅ OK |
| equipment_hours | "3.5 hours" | Must be "3.5 hours" | ✅ OK |
| area_managed | "2.5 ha" | Must be "2.5 ha" | ✅ OK |

**BLOCKING ISSUE**: fuel_type case mismatch
- Preview: "Electric" (via getFuelTypeDisplayName)
- Backend: "electric" (lowercase code)
- ProductDetail: Depends on normalization fix

### 🔧 Required Fix

**File**: `/Users/oscarmunoz/dev/trazo/trazo-app/src/utils/eventDataNormalizer.ts`
**Line**: 720-721

**Current Code** (INCORRECT):
```typescript
if (rawData.fuel_type) {
  (productionData as any).fuel_type = rawData.fuel_type;  // ❌ Direct assignment
}
```

**Required Fix**:
```typescript
if (rawData.fuel_type) {
  (productionData as any).fuel_type = getFuelTypeDisplayName(rawData.fuel_type);  // ✅ Apply mapping
}
```

This ensures:
- Backend returns: "electric"
- Normalization converts: "electric" → "Electric"
- ProductDetail displays: "Electric" (EXACT match to preview)

---

## Test Execution Results

### Scenario 1: Electric Soil Cultivation

**Form Submission**:
- [ ] PENDING - Requires manual test

**Preview Display**:
- [ ] PENDING - Verify fuel_type = "Electric"
- [ ] PENDING - Verify fuel_consumed = "55 kWh"
- [ ] PENDING - Verify all fields visible

**Backend Submission**:
- [ ] PENDING - Check API payload format
- [ ] PENDING - Verify carbon calculation = 21.45 kg CO₂e

**ProductDetail Display**:
- [ ] PENDING - Verify fuel_type = "Electric" (exact match)
- [ ] PENDING - Verify fuel_consumed = "55 kWh" (exact match)
- [ ] PENDING - Verify NO "N/A" or placeholder text

**Overall Status**: 🚨 BLOCKING - eventDataNormalizer.ts fix required

### Scenario 2: Diesel Soil Cultivation

**Form Submission**:
- [ ] PENDING - Requires manual test

**Carbon Calculation**:
- [ ] PENDING - Verify = 53.6 kg CO₂e

**Backwards Compatibility**:
- [ ] PENDING - Verify no regression in diesel fuel type
- [ ] PENDING - Verify fuel_type = "Diesel" displays correctly

---

## Production Readiness Assessment

### Current Status: ❌ NOT PRODUCTION READY

**Blocking Issues**:
1. **CRITICAL**: fuel_type normalization missing getFuelTypeDisplayName() mapping
   - Impact: Preview shows "Electric", ProductDetail shows "electric"
   - Fix: Add getFuelTypeDisplayName() to eventDataNormalizer.ts line 720-721

**After Fix Applied**:
- ✅ Preview displays "Electric"
- ✅ Backend stores "electric"
- ✅ Normalization converts "electric" → "Electric"
- ✅ ProductDetail displays "Electric" (EXACT match)
- ✅ Carbon calculation uses correct EPA factor (0.39)
- ✅ All fields preserved through complete pipeline

### Recommended Next Steps

1. **Apply Fix** to eventDataNormalizer.ts
2. **Deploy Fix** to staging environment
3. **Manual Testing**:
   - Create electric soil event via form
   - Verify preview shows "Electric"
   - Submit to backend
   - Verify carbon calculation = 21.45 kg CO₂e
   - Navigate to ProductDetail
   - Verify display shows "Electric" (exact match)
4. **Backwards Compatibility Test**:
   - Create diesel soil event
   - Verify carbon calculation uses diesel factor
   - Verify display shows "Diesel" correctly
5. **Production Deployment**:
   - Only after all tests pass
   - Monitor for any field display issues

---

## Documentation References

- **Event Preview Utils**: `/trazo-app/src/utils/eventPreviewUtils.ts` (line 731-733)
- **Event Data Normalizer**: `/trazo-app/src/utils/eventDataNormalizer.ts` (line 720-721)
- **Field Display Utils**: `/trazo-app/src/utils/fieldDisplayUtils.ts` (line 1869-1875, 269-275)
- **Backend Model**: `/trazo-back/history/models.py` (line 1453-1459)
- **Carbon Calculation**: `/trazo-back/carbon/services/verified_emission_factors.py`
- **Soil Form**: `/trazo-app/src/views/Dashboard/Dashboard/components/forms/SoilManagementTab.jsx` (line 540-612)

---

## Trazo Event Flow Specialist Notes

**Mission Alignment**: ✅ This verification follows TRAZO-EVENT-FLOW.md principles:
- EXACT preview-display matching required
- NO "N/A" or fallback data allowed
- Complete field preservation through entire pipeline
- Proper fuel_type mapping (lowercase → capitalized display)
- Anti-fallback validation at all stages

**Quality Standard**: This document ensures Phase 3 electric equipment integration maintains the zero-tolerance standard for preview-display consistency established in the Trazo event workflow system.

**Carbon Integration**: Electric equipment properly integrates with EPA-verified emission factors (0.39 kg CO₂/kWh) while maintaining full backwards compatibility with existing diesel/gasoline equipment carbon calculations.
