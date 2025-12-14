# ⚡ ELECTRIC EQUIPMENT TESTING - QUICK REFERENCE

**EPA Electricity Factor:** 0.39 kg CO₂/kWh
**Formula:** Carbon = Energy (kWh) × 0.39

---

## 10 Test Scenarios - Copy & Paste Form Values

### 1️⃣ Electric Irrigation Pump
**Type:** Production → Irrigation
**Copy:**
```
Name: Electric Irrigation - Center Pivot
Area: 10.0 acres
Fuel Type: electric
Energy: 86.5 kWh
Expected: 33.7 kg CO₂e ✅
```

---

### 2️⃣ Greenhouse Climate Control
**Type:** Equipment
**Copy:**
```
Name: Greenhouse Climate Control
Scope: 1000 sq ft
Fuel Type: electric
Energy: 95.0 kWh
Expected: 37.1 kg CO₂e ✅
```

---

### 3️⃣ Electric Tractor Planting
**Type:** Production → Planting
**Copy:**
```
Name: Electric Tractor Planting
Area: 25.0 acres
Fuel Type: electric
Energy: 60.0 kWh
Expected: 23.4 kg CO₂e ✅
```

---

### 4️⃣ Electric Harvester
**Type:** Production → Harvesting
**Copy:**
```
Name: Electric Harvester - Vegetables
Area: 15.0 acres
Fuel Type: electric
Energy: 42.0 kWh
Expected: 16.4 kg CO₂e ✅
```

---

### 5️⃣ Cold Storage System
**Type:** Equipment
**Copy:**
```
Name: Electric Walk-In Cooler
Capacity: 500 cu ft
Fuel Type: electric
Energy: 68.0 kWh
Expected: 26.5 kg CO₂e ✅
```

---

### 6️⃣ Electric Pesticide Sprayer
**Type:** Chemical → Pesticide
**Copy:**
```
Product: Neem Oil Insecticide
Volume: 25.0 L
Area: 5.0 ha
App Fuel Type: electric
App Energy: 8.0 kWh
Expected: 3.1 kg CO₂e ✅
```

---

### 7️⃣ Soil Tilling Equipment
**Type:** Soil Management → Tilling
**Copy:**
```
Name: Electric Tiller
Area: 2.5 acres
Fuel Type: electric
Energy: 35.0 kWh
Expected: 13.7 kg CO₂e ✅
```

---

### 8️⃣ Fertilizer Spreader
**Type:** Chemical → Fertilizer
**Copy:**
```
Product: NPK 15-15-15 Blend
Amount: 150.0 kg
Area: 3.0 ha
App Fuel Type: electric
App Energy: 12.0 kWh
Expected: 4.7 kg CO₂e ✅
```

---

### 9️⃣ Electric Transplanter
**Type:** Production → Transplanting
**Copy:**
```
Name: Electric Transplanter
Area: 1.0 ha
Fuel Type: electric
Energy: 18.0 kWh
Expected: 7.0 kg CO₂e ✅
```

---

### 🔟 Soil Sampling Kit
**Type:** Equipment
**Copy:**
```
Name: Portable Electric Soil Kit
Area: 10.0 acres
Fuel Type: electric
Energy: 2.5 kWh
Expected: 1.0 kg CO₂e ✅
```

---

## Results Tracking Template

```
Test Results - Date: ___________

Scenario #1: _____ kg CO₂e (Expected: 33.7) Status: ✅/❌
Scenario #2: _____ kg CO₂e (Expected: 37.1) Status: ✅/❌
Scenario #3: _____ kg CO₂e (Expected: 23.4) Status: ✅/❌
Scenario #4: _____ kg CO₂e (Expected: 16.4) Status: ✅/❌
Scenario #5: _____ kg CO₂e (Expected: 26.5) Status: ✅/❌
Scenario #6: _____ kg CO₂e (Expected: 3.1) Status: ✅/❌
Scenario #7: _____ kg CO₂e (Expected: 13.7) Status: ✅/❌
Scenario #8: _____ kg CO₂e (Expected: 4.7) Status: ✅/❌
Scenario #9: _____ kg CO₂e (Expected: 7.0) Status: ✅/❌
Scenario #10: _____ kg CO₂e (Expected: 1.0) Status: ✅/❌

TOTAL: _____ kg CO₂e (Expected: 167.0)
Pass Rate: _____% (Target: 100%)
```

---

## Quick Validation Checklist

✅ EPA factor is 0.39 kg CO₂/kWh (not 0.821)
✅ All results within ±5% of expected values
✅ Fuel type successfully set to "electric"
✅ kWh unit accepted in fuel_unit field
✅ Preview shows correct carbon value
✅ ProductDetail matches preview value
✅ No "N/A" or placeholder text
✅ All 10 scenarios passing
✅ Backwards compatibility maintained (test diesel event)
✅ Ready for production deployment

---

## Success Criteria

🎯 **PASS** if: 9-10/10 scenarios within tolerance (167.0 ± 8.35 kg CO₂e total)
🟡 **REVIEW** if: 7-8/10 scenarios pass
❌ **INVESTIGATE** if: <7/10 scenarios pass

**Tolerance:** ±5% per scenario (±0.2-1.9 kg CO₂e depending on magnitude)

---

For detailed information and data sources, see: **ELECTRIC_EQUIPMENT_TESTING_GUIDE.md**
