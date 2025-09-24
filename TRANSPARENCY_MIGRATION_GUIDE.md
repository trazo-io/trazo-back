# Trazo Transparency-First Migration Guide

## Overview

This migration transforms Trazo from competitive carbon scoring to transparency-first approach, solving farmer incentive problems by eliminating gaming opportunities.

## 🎯 Key Changes

### Before (Competitive)
- Carbon scores 0-100 with "better than X% of farms"
- Encouraged farmers to game the system
- Created competitive pressure vs. authentic reporting

### After (Transparency-First)
- Transparency percentage (0-100%) based on record completeness
- Carbon impact shown as secondary metric (kg CO₂ per kg)
- Rewards honest, complete reporting

## 🔧 Backend Changes

### 1. New Transparency API (`/history/transparency/`)

**Key Files:**
- `history/transparency_views.py` - New transparency-focused endpoints
- `carbon/services/calculator_service.py` - Carbon calculation service

**Progressive Loading Structure:**
```python
# Quick View (2s) - Essential consumer info
{
  "farm_name": "Green Valley Farm",
  "product_name": "Organic Avocados", 
  "transparency_score": {
    "percentage": 85,
    "message": "Comprehensive farm record",
    "status": "good"
  },
  "carbon_score": {
    "kg_per_kg": 1.2,
    "unit": "kg CO₂"
  }
}

# Standard View (10s) - Core details
{
  "transparency_details": {
    "actual_events": 42,
    "expected_events": 50,
    "farming_approach": "organic",
    "category_breakdown": {...}
  },
  "carbon_details": {...},
  "farm_details": {...}
}

# Detailed View (30s+) - Deep insights
{
  "transparency_insights": {...},
  "benchmark_comparison": {...},
  "verification_status": {...}
}
```

### 2. Updated Carbon API (`/carbon/public/productions/{id}/qr-summary/`)

**Changed Response Format:**
```python
# OLD - Competitive
{
  "carbonScore": 85,
  "industryPercentile": 75,  # REMOVED
  "relatableFootprint": "like driving 1 mile"  # REMOVED
}

# NEW - Transparency-First  
{
  "transparency": {
    "completeness_percentage": 85,
    "data_quality": "good", 
    "verification_status": "verified"
  },
  "carbon_impact": {
    "kg_per_kg": 1.2,
    "total_emissions": 2400,
    "unit": "kg CO₂ per kg product"
  }
}
```

## 🎨 Frontend Changes

### 1. New Transparency API (`transparencyQrApi.ts`)

**Key Hooks:**
```typescript
import { 
  useGetTransparencySummaryQuery,
  useGetTransparencyDetailsQuery,
  useRecordTransparencyScanMutation
} from 'store/api/transparencyQrApi';
```

### 2. Updated QR Components

**TransparencyHeroSection.tsx** - Main QR display component:
- Primary: Transparency percentage with green circle animation
- Secondary: Carbon impact as supporting metric  
- Progressive disclosure: Quick → Standard → Detailed views

**ProductDetail.tsx** - Hybrid approach:
```typescript
// Uses both APIs for backward compatibility
const { data: transparencySummary } = useGetTransparencySummaryQuery(productionId);
const { data: completeData } = useGetCompleteSummaryQuery(productionId);

// Merges transparency data with existing complete data
const mergedData = React.useMemo(() => {
  const merged = { ...completeData };
  if (transparencySummary) {
    merged.transparency_percentage = transparencySummary.transparency?.percentage || 75;
    merged.transparency_message = transparencySummary.transparency?.message || 'Good transparency';
  }
  return merged;
}, [completeData, transparencySummary]);
```

### 3. Design System Integration

**New Component Export:**
```typescript
// components/Design/index.tsx
export { TransparencyIndicator } from './TransparencyIndicator';
```

**Transparency Display Utilities:**
```typescript
// Trazo-branded colors following design system
export const getTransparencyBadgeColor = (percentage: number): string => {
  if (percentage >= 90) return 'green.500';   // Excellent
  if (percentage >= 70) return 'green.400';   // Good
  if (percentage >= 50) return 'yellow.500';  // Basic
  return 'gray.500';                          // Limited
};

// Consumer-friendly messages
export const getTransparencyMessage = (percentage: number): string => {
  if (percentage >= 95) return 'Complete farm transparency ✨';
  if (percentage >= 85) return 'Comprehensive farm record 🌟';
  if (percentage >= 70) return 'Good record keeping 📋';
  return 'Basic farm information 📝';
};
```

## 📊 Dashboard Changes

**Updated Dashboard Metrics API:**
```typescript
// OLD - Competitive metrics
interface EstablishmentDashboardMetrics {
  industry_percentile: number;  // REMOVED
  carbon_score: number;         // CHANGED to transparency_score
}

// NEW - Transparency-first metrics  
interface EstablishmentDashboardMetrics {
  transparency_score: number;      // PRIMARY metric
  carbon_intensity: number;        // Secondary metric
  carbon_reduction_trend: number;  // Improvement tracking
}
```

## 🔄 Migration Steps

### For Backend Developers

1. **Update API responses** to use transparency format:
   ```python
   # Replace competitive carbon scoring
   response_data = {
       "transparency": {
           "completeness_percentage": transparency_percentage,
           "verification_status": "verified"
       },
       "carbon_impact": {
           "kg_per_kg": carbon_kg_per_kg
       }
   }
   ```

2. **Implement transparency calculation** based on event completeness:
   ```python
   transparency_percentage = (actual_events / expected_events) * 100
   ```

### For Frontend Developers

1. **Use transparency API** for new QR components:
   ```typescript
   const { data } = useGetTransparencyDetailsQuery(productionId);
   ```

2. **Update existing components** to show transparency as primary metric:
   ```jsx
   <Text>Farm Transparency: {data.transparency_score.percentage}%</Text>
   <Text>Carbon Impact: {data.carbon_score.kg_per_kg} kg CO₂</Text>
   ```

3. **Follow progressive loading pattern**:
   - 2s: Essential transparency + carbon data
   - 10s: Detailed breakdown + farm info  
   - 30s+: Insights + recommendations

## ✅ Verification Checklist

- [ ] Backend transparency API returns proper data structure
- [ ] Frontend QR scanning uses transparency-first display
- [ ] Carbon impact shown as secondary metric
- [ ] No competitive language ("better than X%", "ranking", etc.)
- [ ] Progressive loading working (2s → 10s → 30s+)
- [ ] Design system colors and patterns followed
- [ ] Dashboard metrics updated to transparency-first
- [ ] Mobile performance maintained (<3s load times)

## 🚨 Breaking Changes

### API Response Changes
- `carbonScore` → `transparency.completeness_percentage` 
- `industryPercentile` → REMOVED
- `relatableFootprint` → REMOVED

### Component Props
- QR components now expect transparency data structure
- Dashboard metrics use different field names

### Design Language
- "Carbon score" → "Transparency percentage"
- "Better than X%" → "Complete record" 
- Competitive messaging → Trust messaging

## 📱 Testing

### QR Scanning Flow
1. Scan QR code → Transparency percentage displays first
2. Wait 2s → Basic carbon impact appears
3. Wait 10s → Full farm details load
4. Check: No competitive language visible
5. Verify: Mobile performance <3s total load

### Dashboard Integration  
1. Open establishment dashboard
2. Verify transparency score displayed prominently
3. Check carbon metrics shown as secondary
4. Confirm no industry percentile references

## 🔗 Related Files

**Backend:**
- `history/transparency_views.py`
- `carbon/views.py` (qr_summary method)
- `carbon/services/calculator_service.py`

**Frontend:**
- `store/api/transparencyQrApi.ts`
- `components/QR/TransparencyHeroSection.tsx`
- `views/Scan/ProductDetail/ProductDetail.tsx`
- `store/api/dashboardMetricsApi.ts`
- `components/Design/index.tsx`

## 💡 Best Practices

1. **Always show transparency as primary metric** in consumer-facing displays
2. **Use carbon impact as supporting information** (kg CO₂ per kg)
3. **Follow Trazo design system** for colors and messaging
4. **Implement progressive loading** for mobile performance
5. **Maintain backward compatibility** during transition period
6. **Test on real mobile devices** to verify performance targets

## 🎉 Benefits

- **Eliminates farmer gaming incentives**
- **Builds authentic consumer trust**
- **Improves mobile performance**
- **Aligns with sustainability mission**
- **Creates differentiated value proposition**

---

**Migration completed**: January 2025
**Next review**: Q2 2025 (evaluate farmer adoption and consumer response)