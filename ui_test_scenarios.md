# Pest Management UI Testing Scenarios

## 🌱 Frontend Testing Guide

Now that the backend pest management carbon calculations are fixed, here are realistic scenarios to test through the UI to verify the complete end-to-end flow.

---

## Setup Instructions

1. **Start the backend server:**
   ```bash
   cd trazo-back && poetry run python manage.py runserver
   ```

2. **Start the frontend development server:**
   ```bash
   cd trazo-app && npm run start
   ```

3. **Navigate to the New Event form:**
   - Go to `http://localhost:3000/dashboard`
   - Click "New Event" or navigate to the events section
   - Select "Pest Management" from the event type dropdown

---

## Test Scenario 1: Aphid Scouting 🐛

**Expected CO2e Result: 0.2 kg**

### Form Fields:
- **Event Type:** Pest Management
- **Pest Management Type:** SC (Scouting)
- **Event Name:** "Morning Aphid Check"
- **Pest Species:** "aphids"
- **Pest Pressure Level:** "medium"
- **Field Area (hectares):** 2.5
- **Travel Distance (km):** 5.0
- **Time Spent (hours):** 2.0
- **Crop Growth Stage:** "flowering"
- **Weather Conditions:** "dry"
- **Economic Threshold Met:** No
- **Action Recommended:** "continue_monitoring"

### What to Verify:
- ✅ Carbon calculation appears in real-time (no infinite loop)
- ✅ CO2e value shows **0.2 kg** (not 0.0)
- ✅ Efficiency score displays (~75.0)
- ✅ Method shows "integrated_pest_management_estimation"
- ✅ No error messages in console
- ✅ Form remains responsive

---

## Test Scenario 2: Trap Monitoring 🪤

**Expected CO2e Result: 0.1 kg**

### Form Fields:
- **Event Type:** Pest Management
- **Pest Management Type:** TM (Trap Monitoring)
- **Event Name:** "Weekly Trap Check"
- **Pest Species:** "thrips"
- **Trap Count:** 25
- **Field Area (hectares):** 3.0
- **Travel Distance (km):** 6.0
- **Time Spent (hours):** 1.5
- **Pest Pressure Level:** "low"
- **Crop Growth Stage:** "flowering"
- **Weather Conditions:** "dry"

### What to Verify:
- ✅ Carbon calculation updates immediately
- ✅ CO2e value shows **0.1 kg** 
- ✅ Lower emission value reflects minimal monitoring impact
- ✅ Form performance remains smooth

---

## Test Scenario 3: IPM Implementation 🌿

**Expected CO2e Result: -1.0 kg (Carbon Negative!)**

### Form Fields:
- **Event Type:** Pest Management  
- **Pest Management Type:** IP (IPM Implementation)
- **Event Name:** "Citrus Mite IPM Strategy"
- **Pest Species:** "citrus_mites"
- **Pest Pressure Level:** "medium"
- **IPM Strategy:** "biological_control"
- **Field Area (hectares):** 10.0
- **Travel Distance (km):** 12.0
- **Time Spent (hours):** 6.0
- **Crop Growth Stage:** "vegetative"
- **Weather Conditions:** "humid"
- **Economic Threshold Met:** Yes

### What to Verify:
- ✅ Carbon calculation shows **-1.0 kg** (negative value)
- ✅ Negative value indicates environmental benefit
- ✅ Higher efficiency score reflects sustainable practice
- ✅ UI handles negative values properly

---

## Test Scenario 4: Beneficial Release 🐞

**Expected CO2e Result: -0.5 kg (Carbon Negative!)**

### Form Fields:
- **Event Type:** Pest Management
- **Pest Management Type:** BR (Beneficial Release)
- **Event Name:** "Predatory Mite Release"
- **Pest Species:** "spider_mites"
- **Beneficial Species:** "predatory_mites"
- **Release Quantity:** 1000
- **Field Area (hectares):** 15.0
- **Travel Distance (km):** 8.0
- **Time Spent (hours):** 4.0
- **Pest Pressure Level:** "high"
- **Crop Growth Stage:** "fruit_development"
- **Weather Conditions:** "moderate"

### What to Verify:
- ✅ Carbon calculation shows **-0.5 kg** (negative value)
- ✅ Beneficial insects create environmental credit
- ✅ Form handles beneficial species dropdown
- ✅ Release quantity field works properly

---

## UI Performance Tests

### Real-Time Calculation Testing:
1. **Start with empty form**
2. **Fill fields one by one** - verify calculation updates smoothly
3. **Change pest management type** - verify different CO2e values
4. **Clear and refill** - verify no stale values or errors

### Expected Behavior:
- ✅ **No infinite API calls** (check browser Network tab)
- ✅ **Smooth debounced updates** (~500ms delay)
- ✅ **Correct calculations** for each pest type
- ✅ **Consistent UI responsiveness**

---

## Browser Developer Tools Verification

### Network Tab:
- Should see occasional POST requests to `/api/carbon/calculate-event-carbon/`
- **No continuous requests** (infinite loop was fixed)
- Response should show non-zero CO2e values

### Console:
- Should see form validation logs
- **No error messages** about attribute errors
- Carbon calculation debug logs should show success

---

## Troubleshooting

### If you see 0.0 kg CO2e:
1. Check browser console for JavaScript errors
2. Verify backend server is running
3. Check Network tab for failed API calls
4. Restart both frontend and backend

### If you see infinite API calls:
1. The frontend infinite loop fix should prevent this
2. If it occurs, check console for React re-render warnings
3. Verify the debounce logic is working

### If form is unresponsive:
1. Check for JavaScript errors in console
2. Verify all required form fields are filled
3. Test with simpler field values first

---

## Success Criteria ✅

**The UI test is successful when:**
1. All 4 pest management types return correct CO2e values
2. Real-time calculations work without infinite loops
3. Form remains responsive during data entry
4. Negative values display properly for beneficial practices
5. No console errors during normal usage

**Expected Results Summary:**
- **Scouting (SC):** 0.2 kg CO2e
- **Trap Monitoring (TM):** 0.1 kg CO2e  
- **IPM Implementation (IP):** -1.0 kg CO2e
- **Beneficial Release (BR):** -0.5 kg CO2e

The carbon calculations now properly reflect the environmental impact of different pest management practices, supporting Trazo's transparency-first approach to agricultural sustainability.