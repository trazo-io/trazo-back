# UI-COMPLIANT DATABASE EVENT TESTING RESULTS

**Date:** 2025-10-11 21:10:57
**Events Created:** 9
**High Priority Issues:** 0

## Critical Issues Requiring Immediate Fixes

- **Chemical - fertilizer - Anhydrous Ammonia (82-0-0)**
  - Issue: Calculated 2423.3 kg CO2e outside expected range 2800.0-3200.0
  - Deviation: 19.2%

- **Chemical - pesticide - Chlorpyrifos 48EC**
  - Issue: Calculated 1415.3 kg CO2e outside expected range 180.0-220.0
  - Deviation: 607.6%

- **Chemical - herbicide - Roundup PowerMAX**
  - Issue: Calculated 1582.6 kg CO2e outside expected range 155.0-195.0
  - Deviation: 804.4%

- **Chemical - fungicide - Copper Sulfate Basic**
  - Issue: Calculated 749.8 kg CO2e outside expected range 95.0-125.0
  - Deviation: 581.7%

## UI-Model Mapping Gaps

- **weather - frost** (medium priority)
  - Issue: Django model constant may not exist
  - Django: FR

- **weather - drought** (medium priority)
  - Issue: Django model constant may not exist
  - Django: DR

- **weather - heavy_rain** (medium priority)
  - Issue: Django model constant may not exist
  - Django: TS

- **weather - high_winds** (medium priority)
  - Issue: Django model constant may not exist
  - Django: HW

- **weather - hail** (medium priority)
  - Issue: Django model constant may not exist
  - Django: HL

- **weather - heat_stress** (medium priority)
  - Issue: Django model constant may not exist
  - Django: HT

- **chemical - fertilizer** (medium priority)
  - Issue: Django model constant may not exist
  - Django: FE

- **chemical - pesticide** (medium priority)
  - Issue: Django model constant may not exist
  - Django: PE

- **chemical - herbicide** (medium priority)
  - Issue: Django model constant may not exist
  - Django: HE

- **chemical - fungicide** (medium priority)
  - Issue: Django model constant may not exist
  - Django: FU

- **chemical - growth_regulator** (medium priority)
  - Issue: Django model constant may not exist
  - Django: PE

- **production - planting** (medium priority)
  - Issue: Django model constant may not exist
  - Django: PL

- **production - harvesting** (medium priority)
  - Issue: Django model constant may not exist
  - Django: HA

- **production - irrigation** (medium priority)
  - Issue: Django model constant may not exist
  - Django: IR

- **production - pruning** (medium priority)
  - Issue: Django model constant may not exist
  - Django: PR

- **production - grain_drying** (medium priority)
  - Issue: Django model constant may not exist
  - Django: GRAIN_DRYING

- **production - storage** (medium priority)
  - Issue: Django model constant may not exist
  - Django: STORAGE

- **equipment - field_operations** (medium priority)
  - Issue: Django model constant may not exist
  - Django: FIELD_OPERATIONS

- **equipment - fuel_consumption** (medium priority)
  - Issue: Django model constant may not exist
  - Django: FC

- **equipment - maintenance** (medium priority)
  - Issue: Django model constant may not exist
  - Django: MN

- **equipment - repair** (medium priority)
  - Issue: Django model constant may not exist
  - Django: RE

- **equipment - transport** (medium priority)
  - Issue: Django model constant may not exist
  - Django: TRANSPORT

- **soil - soil_test** (medium priority)
  - Issue: Django model constant may not exist
  - Django: ST

- **soil - ph_adjustment** (medium priority)
  - Issue: Django model constant may not exist
  - Django: PA

- **soil - organic_matter** (medium priority)
  - Issue: Django model constant may not exist
  - Django: OM

- **soil - compost** (medium priority)
  - Issue: Django model constant may not exist
  - Django: CO

- **soil - biochar** (medium priority)
  - Issue: Django model constant may not exist
  - Django: BIOCHAR

- **soil - manure** (medium priority)
  - Issue: Django model constant may not exist
  - Django: MANURE

- **pest - scouting** (medium priority)
  - Issue: Django model constant may not exist
  - Django: SC

- **pest - beneficial_release** (medium priority)
  - Issue: Django model constant may not exist
  - Django: BR

- **pest - trap_monitoring** (medium priority)
  - Issue: Django model constant may not exist
  - Django: TM

- **pest - biological_control** (medium priority)
  - Issue: Django model constant may not exist
  - Django: BIOLOGICAL_CONTROL

- **business - certification** (medium priority)
  - Issue: Django model constant may not exist
  - Django: CE

- **business - audit** (medium priority)
  - Issue: Django model constant may not exist
  - Django: AUDIT

- **business - planning** (medium priority)
  - Issue: Django model constant may not exist
  - Django: PLANNING

- **business - training** (medium priority)
  - Issue: Django model constant may not exist
  - Django: TRAINING

- **business - documentation** (medium priority)
  - Issue: Django model constant may not exist
  - Django: DOCUMENTATION

- **general - tillage** (medium priority)
  - Issue: Django model constant may not exist
  - Django: TILLAGE

- **general - cover_crops** (medium priority)
  - Issue: Django model constant may not exist
  - Django: COVER_CROPS

- **general - conservation** (medium priority)
  - Issue: Django model constant may not exist
  - Django: CONSERVATION

- **general - energy** (medium priority)
  - Issue: Django model constant may not exist
  - Django: ENERGY

- **general - verification** (medium priority)
  - Issue: Django model constant may not exist
  - Django: VERIFICATION

- **general - other** (medium priority)
  - Issue: Django model constant may not exist
  - Django: OTHER

## Recommendations

1. **[CRITICAL] Carbon Calculation Fix**
   - Issue: 4 chemical calculation failures
   - Recommendation: Fix chemical calculation service to handle UI form data correctly
   - Impact: Chemical applications show incorrect or zero carbon emissions

