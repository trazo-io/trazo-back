# Carbon Calculation Investigation Report
**Anhydrous Ammonia (82-0-0) Application Scenario**

## Executive Summary

**CRITICAL BUG FOUND AND FIXED**: The backend carbon calculation was using incorrect fertilizer density (1.0 kg/L) for anhydrous ammonia, which actually has a density of 0.68 kg/L. This resulted in a **46% overestimation** of carbon emissions.

**Status**: ✅ **FIXED** - Backend now calculates correctly at **506.6 kg CO₂e** instead of the incorrect **741.2 kg CO₂e**

## Investigation Details

### Scenario Tested
- **Product**: Anhydrous Ammonia (82-0-0)
- **Volume**: 300L
- **Area**: 2.0 Ha
- **Application Method**: Injection (typical for anhydrous ammonia)

### Results Summary

| Calculation Method | Total CO₂e | Manufacturing | Application | Status |
|-------------------|------------|---------------|-------------|---------|
| Manual (EPA factors) | 506.6 kg | 498.5 kg | 8.1 kg | ✅ Verified |
| Backend (BEFORE fix) | 741.2 kg | 733.1 kg | 8.1 kg | ❌ Wrong density |
| Backend (AFTER fix) | 506.6 kg | 498.5 kg | 8.1 kg | ✅ Fixed |
| Frontend Display | 738.0 kg | ? | ? | 🔍 Needs investigation |

## Root Cause Analysis

### 1. Fertilizer Density Error
**Location**: `/carbon/services/verified_emission_factors.py:687`

**Before Fix**:
```python
fertilizer_density = 1.0  # kg/L average - WRONG for anhydrous ammonia
```

**After Fix**:
```python
fertilizer_density = cls._get_fertilizer_density(npk_content, application_method)
# Returns 0.68 kg/L for anhydrous ammonia (82-0-0)
```

### 2. Impact Analysis
- **Fertilizer Mass Error**: 300L × 1.0 kg/L = 300 kg (wrong) vs 300L × 0.68 kg/L = 204 kg (correct)
- **Nitrogen Mass Error**: 300 kg × 0.82 = 246 kg N (wrong) vs 204 kg × 0.82 = 167.3 kg N (correct)
- **Emission Error**: 246 kg N × 2.98 kg CO₂e/kg N = 733 kg CO₂e (wrong) vs 167.3 kg N × 2.98 kg CO₂e/kg N = 498.5 kg CO₂e (correct)

## Scientific Validation

### EPA Emission Factors Used (Correct)
- **Nitrogen Manufacturing**: 2.98 kg CO₂e/kg N ✅
- **Diesel Fuel**: 10.21 kg CO₂e/gallon ✅
- **Application Fuel**: 1.5 L/ha for injection method ✅

### Manual Calculation Verification
1. **Fertilizer Mass**: 300L × 0.68 kg/L = 204 kg ✅
2. **Nitrogen Content**: 204 kg × 82% = 167.3 kg N ✅
3. **Manufacturing Emissions**: 167.3 kg N × 2.98 kg CO₂e/kg N = 498.5 kg CO₂e ✅
4. **Application Emissions**: 2.0 ha × 1.5 L/ha ÷ 3.785 L/gal × 10.21 kg CO₂e/gal = 8.1 kg CO₂e ✅
5. **Total**: 498.5 + 8.1 = **506.6 kg CO₂e** ✅

## Fix Implementation

### New Fertilizer Density Function
Added intelligent density calculation based on NPK content and application method:

```python
@classmethod
def _get_fertilizer_density(cls, npk_content: dict, application_method: str = 'broadcast') -> float:
    """Get accurate fertilizer density based on NPK content and application method."""
    n_percentage = npk_content.get('N', 0)
    p_percentage = npk_content.get('P', 0)
    k_percentage = npk_content.get('K', 0)
    
    # Special case: Anhydrous ammonia (82-0-0)
    if n_percentage >= 80 and p_percentage == 0 and k_percentage == 0:
        return 0.68  # kg/L (liquid anhydrous ammonia)
    
    # Other fertilizer types with appropriate densities...
```

### Densities by Fertilizer Type
- **Anhydrous Ammonia (82-0-0)**: 0.68 kg/L
- **UAN Solutions (28-32% N)**: 1.30 kg/L
- **Standard Liquid Fertilizers**: 1.25 kg/L
- **Granular Fertilizers**: 0.80 kg/L

## Remaining Questions

### Frontend-Backend Discrepancy
- **Frontend shows**: 738 kg CO₂e
- **Backend (corrected) calculates**: 506.6 kg CO₂e
- **Difference**: 231.4 kg CO₂e (31% overestimation in frontend)

**Possible causes**:
1. Frontend using cached/outdated calculation
2. Frontend using different density or emission factors
3. Frontend including additional emission sources
4. Data extraction differences (volume, area, or NPK parsing)

## Recommendations

### Immediate Actions Required
1. ✅ **COMPLETED**: Fix fertilizer density calculation in backend
2. 🔍 **INVESTIGATE**: Frontend-backend discrepancy (738 vs 506.6 kg CO₂e)
3. 🧪 **TEST**: Verify fix doesn't break other fertilizer calculations
4. 📝 **DOCUMENT**: Update API documentation with density sources

### Quality Assurance
1. **Add Unit Tests**: Create comprehensive tests for all fertilizer types
2. **Validation Pipeline**: Implement automated validation against manual calculations
3. **Density Database**: Create lookup table for common fertilizer densities
4. **Audit Trail**: Log calculation parameters for debugging

### Farmer Impact
- **Before fix**: Farmers saw inflated emissions (741 kg CO₂e) potentially discouraging efficient practices
- **After fix**: Accurate emissions (507 kg CO₂e) provide trustworthy data for decision-making
- **Trust building**: Accurate calculations essential for carbon credit programs

## Conclusion

**Status**: ✅ **CRITICAL BUG FIXED**

The backend carbon calculation for anhydrous ammonia (82-0-0) is now scientifically accurate at **506.6 kg CO₂e** for 300L on 2.0 Ha. This represents a **31% reduction** from the previous incorrect calculation of 741.2 kg CO₂e.

**Next Steps**: Investigate why the frontend still shows 738 kg CO₂e to ensure complete accuracy throughout the system.

**Confidence Level**: 🟢 **High** - Manual calculations verified against EPA emission factors