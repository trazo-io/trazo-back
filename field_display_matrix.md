# Comprehensive Field-by-Field Display Matrix
## Complete Transparency Data Display Specification for Consumer QR Pages

**Purpose:** Ensure ALL collected transparency data is displayed to consumers in meaningful ways, not just stored in the database.

**Display Priority Levels:**
- 🔴 **IMMEDIATE** - Show in main event card (0-1s load)
- 🟡 **SECONDARY** - Show in expanded view (1-3s load)
- 🟢 **DETAILS** - Show in "Learn More" section (on-demand)

---

## 🌤️ WEATHER EVENTS (Type 0)
### All Weather Subtypes & Their Fields

| Subtype | Field | Display Priority | Consumer Display Format | Example |
|---------|-------|-----------------|------------------------|---------|
| **Frost (FR)** | | | | |
| | `lower_temperature` | 🔴 IMMEDIATE | "Protected from {value}°C/{F} frost" | "Protected from -2°C/28°F frost" |
| | `way_of_protection` | 🔴 IMMEDIATE | "{value} deployed" | "Frost protection heaters deployed" |
| | `duration` | 🟡 SECONDARY | "Protection lasted {value} hours" | "Protection lasted 6 hours" |
| | `start_date` | 🟡 SECONDARY | "Frost event: {date}" | "Frost event: Jan 15, 2024" |
| | `end_date` | 🟡 SECONDARY | "Until: {date}" | "Until: Jan 16, 2024" |
| | `damage_assessment` | 🔴 IMMEDIATE | "Outcome: {value}" | "Outcome: Crops successfully protected" |
| | `observation` | 🟡 SECONDARY | "Farmer notes: {value}" | "Farmer notes: Early warning system worked perfectly" |
| **Drought (DR)** | | | | |
| | `water_deficit` | 🔴 IMMEDIATE | "Managing {value}mm water shortage" | "Managing 150mm water shortage" |
| | `duration` | 🔴 IMMEDIATE | "Drought lasted {value} days" | "Drought lasted 45 days" |
| | `crop_impact` | 🔴 IMMEDIATE | "Crop status: {value}" | "Crop status: Adapted with drip irrigation" |
| | `protection_measures` | 🔴 IMMEDIATE | "Response: {value}" | "Response: Water-saving irrigation activated" |
| | `start_date`/`end_date` | 🟡 SECONDARY | "Period: {start} to {end}" | "Period: June 1 to July 15" |
| | `observation` | 🟡 SECONDARY | "Management notes: {value}" | "Management notes: Maintained quality despite drought" |
| **Hailstorm (HL)** | | | | |
| | `weight` | 🔴 IMMEDIATE | "Hail size: {value}g stones" | "Hail size: 15g stones" |
| | `diameter` | 🔴 IMMEDIATE | "Hail diameter: {value}cm" | "Hail diameter: 2cm" |
| | `damage_assessment` | 🔴 IMMEDIATE | "Damage level: {value}" | "Damage level: Minor, netting protected 95%" |
| | `protection_measures` | 🔴 IMMEDIATE | "Protection: {value}" | "Protection: Hail netting deployed" |
| | `duration` | 🟡 SECONDARY | "Storm duration: {value} minutes" | "Storm duration: 15 minutes" |
| | `observation` | 🟡 SECONDARY | "Impact notes: {value}" | "Impact notes: Investment in netting paid off" |
| **High Temperature (HT)** | | | | |
| | `highest_temperature` | 🔴 IMMEDIATE | "Peak temperature: {value}°C/{F}" | "Peak temperature: 42°C/108°F" |
| | `protection_measures` | 🔴 IMMEDIATE | "Heat protection: {value}" | "Heat protection: Shade cloth and misting" |
| | `duration` | 🔴 IMMEDIATE | "Heat wave: {value} days" | "Heat wave: 3 days" |
| | `start_date`/`end_date` | 🟡 SECONDARY | "{start} to {end}" | "July 10-12, 2024" |
| | `crop_impact` | 🔴 IMMEDIATE | "Crop response: {value}" | "Crop response: Minimal stress, well managed" |
| | `observation` | 🟡 SECONDARY | "Management: {value}" | "Management: Early morning irrigation helped" |
| **Tropical Storm (TS)** | | | | |
| | `wind_speed` | 🔴 IMMEDIATE | "Wind speeds: {value} mph" | "Wind speeds: 65 mph" |
| | `precipitation_amount` | 🔴 IMMEDIATE | "Rainfall: {value}mm" | "Rainfall: 125mm" |
| | `duration` | 🔴 IMMEDIATE | "Storm duration: {value} hours" | "Storm duration: 8 hours" |
| | `damage_assessment` | 🔴 IMMEDIATE | "Storm impact: {value}" | "Storm impact: Minimal, windbreaks effective" |
| | `protection_measures` | 🟡 SECONDARY | "Preparations: {value}" | "Preparations: Secured equipment, reinforced supports" |
| **High Winds (HW)** | | | | |
| | `wind_speed` | 🔴 IMMEDIATE | "Wind gusts up to {value} mph" | "Wind gusts up to 45 mph" |
| | `protection_measures` | 🔴 IMMEDIATE | "Wind protection: {value}" | "Wind protection: Windbreaks and staking" |
| | `damage_assessment` | 🔴 IMMEDIATE | "Wind damage: {value}" | "Wind damage: None, protection effective" |
| | `duration` | 🟡 SECONDARY | "Wind event: {value} hours" | "Wind event: 4 hours" |
| **Humidity Events (HH/LH)** | | | | |
| | `humidity_level` | 🔴 IMMEDIATE | "Humidity: {value}%" | "Humidity: 85%" |
| | `crop_impact` | 🔴 IMMEDIATE | "Impact: {value}" | "Impact: Increased disease monitoring" |
| | `protection_measures` | 🟡 SECONDARY | "Management: {value}" | "Management: Enhanced air circulation" |

---

## 🧪 CHEMICAL EVENTS (Type 1)
### All Chemical Types & Their Fields

| Chemical Type | Field | Display Priority | Consumer Display Format | Example |
|--------------|-------|-----------------|------------------------|---------|
| **All Types** | | | | |
| | `commercial_name` | 🔴 IMMEDIATE | "{value}" | "SafeGrow Organic Fertilizer" |
| | `type` | 🔴 IMMEDIATE | "Type: {label}" | "Type: Organic Fertilizer" |
| | `target_pest_disease` | 🔴 IMMEDIATE | "Purpose: {value}" | "Purpose: Aphid prevention" |
| | `application_method` | 🔴 IMMEDIATE | "Method: {value}" | "Method: Precision drip application" |
| | `area_treated` + `area_unit` | 🔴 IMMEDIATE | "Applied to {value} {unit}" | "Applied to 5.2 hectares" |
| | `date` | 🔴 IMMEDIATE | "Applied: {date}" | "Applied: 3 days ago" |
| **Fertilizer (FE)** | | | | |
| | `nitrogenPercentage` | 🔴 IMMEDIATE | "N: {value}%" | "N: 10%" |
| | `phosphorusPercentage` | 🔴 IMMEDIATE | "P: {value}%" | "P: 10%" |
| | `potassiumPercentage` | 🔴 IMMEDIATE | "K: {value}%" | "K: 10%" |
| | `concentration` | 🟡 SECONDARY | "NPK Formula: {value}" | "NPK Formula: 10-10-10 balanced" |
| | `volume_applied` + `volume_unit` | 🟡 SECONDARY | "Amount: {value} {unit}" | "Amount: 50 liters" |
| | `active_ingredient` | 🟡 SECONDARY | "Active: {value}" | "Active: Organic nitrogen compounds" |
| | `weather_conditions` | 🔴 IMMEDIATE | "Weather: {value}" | "Weather: Calm conditions, no wind" |
| | `application_timing` | 🔴 IMMEDIATE | "Timing: {value}" | "Timing: Pre-flower stage" |
| | `observation` | 🟡 SECONDARY | "Notes: {value}" | "Notes: Soil test guided application" |
| **Pesticide (PE)** | | | | |
| | `active_ingredient` | 🔴 IMMEDIATE | "Active: {value}" | "Active: Neem oil (organic)" |
| | `concentration` | 🟡 SECONDARY | "Concentration: {value}" | "Concentration: 0.5% solution" |
| | `volume_applied` + `volume_unit` | 🟡 SECONDARY | "Applied: {value} {unit}" | "Applied: 20 liters" |
| | `weather_conditions` | 🔴 IMMEDIATE | "Conditions: {value}" | "Conditions: Early morning, no wind" |
| | `application_timing` | 🔴 IMMEDIATE | "Stage: {value}" | "Stage: After pest threshold reached" |
| | `pre_harvest_interval` | 🔴 IMMEDIATE | "Safe to harvest in: {value} days" | "Safe to harvest in: 7 days" |
| **Fungicide (FU)** | | | | |
| | `active_ingredient` | 🔴 IMMEDIATE | "Treatment: {value}" | "Treatment: Copper sulfate (approved)" |
| | `target_pest_disease` | 🔴 IMMEDIATE | "Preventing: {value}" | "Preventing: Powdery mildew" |
| | `weather_conditions` | 🔴 IMMEDIATE | "Applied in: {value}" | "Applied in: Dry conditions" |
| | `application_timing` | 🟡 SECONDARY | "Timing: {value}" | "Timing: Preventive application" |
| **Herbicide (HE)** | | | | |
| | `active_ingredient` | 🟡 SECONDARY | "Weed control: {value}" | "Weed control: Organic mulch" |
| | `application_method` | 🔴 IMMEDIATE | "Method: {value}" | "Method: Targeted spot treatment" |
| | `target_pest_disease` | 🔴 IMMEDIATE | "Target weeds: {value}" | "Target weeds: Annual grasses" |
| | `weather_conditions` | 🟡 SECONDARY | "Conditions: {value}" | "Conditions: Before rain forecast" |

---

## 🌾 PRODUCTION EVENTS (Type 2)
### All Production Activities & Their Fields

| Activity Type | Field | Display Priority | Consumer Display Format | Example |
|--------------|-------|-----------------|------------------------|---------|
| **Planting** | | | | |
| | `area` | 🔴 IMMEDIATE | "Planted: {value} hectares" | "Planted: 10 hectares" |
| | `planting_density` | 🟡 SECONDARY | "Density: {value} plants/ha" | "Density: 250 plants/ha" |
| | `seed_variety` | 🔴 IMMEDIATE | "Variety: {value}" | "Variety: Hass Avocado" |
| | `observation` | 🟡 SECONDARY | "Planting notes: {value}" | "Planting notes: Optimal soil conditions" |
| **Harvesting** | | | | |
| | `quantityHarvested` | 🔴 IMMEDIATE | "Harvest: {value} tons" | "Harvest: 2.5 tons" |
| | `area` | 🔴 IMMEDIATE | "From: {value} hectares" | "From: 1 hectare" |
| | `yield_per_area` | 🔴 IMMEDIATE | "Yield: {calc} tons/ha" | "Yield: 2.5 tons/ha" |
| | `quality_grade` | 🔴 IMMEDIATE | "Quality: {value}" | "Quality: Premium grade" |
| | `harvest_method` | 🟡 SECONDARY | "Method: {value}" | "Method: Hand-picked at peak ripeness" |
| | `observation` | 🟡 SECONDARY | "Harvest notes: {value}" | "Harvest notes: Perfect maturity achieved" |
| **Irrigation** | | | | |
| | `waterAmount` | 🔴 IMMEDIATE | "Water used: {value} liters" | "Water used: 5000 liters" |
| | `area` | 🔴 IMMEDIATE | "Irrigated: {value} hectares" | "Irrigated: 2 hectares" |
| | `irrigation_method` | 🔴 IMMEDIATE | "Method: {value}" | "Method: Drip irrigation" |
| | `water_efficiency` | 🔴 IMMEDIATE | "Efficiency: {calc} L/ha" | "Efficiency: 2500 L/ha (30% below average)" |
| | `soil_moisture` | 🟡 SECONDARY | "Soil moisture: {value}%" | "Soil moisture: Optimal 65%" |
| | `observation` | 🟡 SECONDARY | "Water notes: {value}" | "Water notes: Sensor-guided irrigation" |
| **Pruning** | | | | |
| | `area` | 🔴 IMMEDIATE | "Pruned: {value} hectares" | "Pruned: 3 hectares" |
| | `pruning_type` | 🔴 IMMEDIATE | "Type: {value}" | "Type: Canopy shaping" |
| | `trees_pruned` | 🟡 SECONDARY | "Trees: {value}" | "Trees: 750" |
| | `observation` | 🟡 SECONDARY | "Purpose: {value}" | "Purpose: Improving light penetration" |
| **Grain Drying** | | | | |
| | `moisture_before` | 🔴 IMMEDIATE | "Initial moisture: {value}%" | "Initial moisture: 25%" |
| | `moisture_after` | 🔴 IMMEDIATE | "Final moisture: {value}%" | "Final moisture: 14%" |
| | `energy_used` | 🟡 SECONDARY | "Energy: {value} kWh" | "Energy: 150 kWh" |
| | `drying_method` | 🟡 SECONDARY | "Method: {value}" | "Method: Solar drying" |
| **Storage** | | | | |
| | `storage_facility` | 🔴 IMMEDIATE | "Stored in: {value}" | "Stored in: Climate-controlled facility" |
| | `temperature` | 🔴 IMMEDIATE | "Temperature: {value}°C" | "Temperature: 12°C" |
| | `humidity` | 🟡 SECONDARY | "Humidity: {value}%" | "Humidity: 60%" |
| | `duration` | 🟡 SECONDARY | "Storage period: {value} days" | "Storage period: 14 days" |

---

## 🔧 EQUIPMENT EVENTS (Type 4)
### All Equipment Activities & Their Fields

| Activity Type | Field | Display Priority | Consumer Display Format | Example |
|--------------|-------|-----------------|------------------------|---------|
| **Fuel Consumption (FC)** | | | | |
| | `equipment_type` | 🔴 IMMEDIATE | "Equipment: {value}" | "Equipment: Precision tractor" |
| | `fuel_consumed` + `fuel_unit` | 🔴 IMMEDIATE | "Fuel used: {value} {unit}" | "Fuel used: 45 liters" |
| | `fuel_type` | 🔴 IMMEDIATE | "Fuel type: {value}" | "Fuel type: Biodiesel B20" |
| | `hours_operated` | 🔴 IMMEDIATE | "Operating time: {value} hours" | "Operating time: 6 hours" |
| | `area_worked` + `area_unit` | 🔴 IMMEDIATE | "Area covered: {value} {unit}" | "Area covered: 15 hectares" |
| | `fuel_efficiency` | 🔴 IMMEDIATE | "Efficiency: {calc} L/ha" | "Efficiency: 3 L/ha" |
| | `operation_efficiency` | 🟡 SECONDARY | "Performance: {value}" | "Performance: Excellent" |
| | `observation` | 🟡 SECONDARY | "Notes: {value}" | "Notes: GPS guidance reduced overlap" |
| **Maintenance (MA)** | | | | |
| | `equipment_type` | 🔴 IMMEDIATE | "Maintained: {value}" | "Maintained: Harvester" |
| | `maintenance_type` | 🔴 IMMEDIATE | "Service: {value}" | "Service: Annual preventive maintenance" |
| | `cost` | 🟢 DETAILS | "Investment: ${value}" | "Investment: $1,200" |
| | `next_service` | 🟡 SECONDARY | "Next service: {value}" | "Next service: In 250 hours" |
| **Transportation (TR)** | | | | |
| | `distance` | 🔴 IMMEDIATE | "Distance: {value} km" | "Distance: 45 km" |
| | `fuel_consumed` | 🟡 SECONDARY | "Transport fuel: {value} L" | "Transport fuel: 15 L" |
| | `cargo` | 🔴 IMMEDIATE | "Transported: {value}" | "Transported: Fresh harvest" |

---

## 🌱 SOIL MANAGEMENT EVENTS (Type 5)
### All Soil Activities & Their Fields

| Activity Type | Field | Display Priority | Consumer Display Format | Example |
|--------------|-------|-----------------|------------------------|---------|
| **Soil Test** | | | | |
| | `ph_value` | 🔴 IMMEDIATE | "Soil pH: {value}" | "Soil pH: 6.5 (optimal)" |
| | `organic_matter` | 🔴 IMMEDIATE | "Organic matter: {value}%" | "Organic matter: 4.2% (excellent)" |
| | `nitrogen_level` | 🟡 SECONDARY | "Nitrogen: {value} ppm" | "Nitrogen: 35 ppm (good)" |
| | `phosphorus_level` | 🟡 SECONDARY | "Phosphorus: {value} ppm" | "Phosphorus: 25 ppm" |
| | `potassium_level` | 🟡 SECONDARY | "Potassium: {value} ppm" | "Potassium: 150 ppm" |
| | `test_laboratory` | 🟡 SECONDARY | "Lab: {value}" | "Lab: Certified Soil Testing Inc." |
| | `recommendations` | 🔴 IMMEDIATE | "Action: {value}" | "Action: No amendments needed" |
| **pH Adjustment/Lime** | | | | |
| | `lime_type` | 🔴 IMMEDIATE | "Applied: {value}" | "Applied: Agricultural limestone" |
| | `application_rate` | 🔴 IMMEDIATE | "Rate: {value} tons/ha" | "Rate: 2 tons/ha" |
| | `target_ph` | 🔴 IMMEDIATE | "Target pH: {value}" | "Target pH: 6.5" |
| | `area_treated` | 🟡 SECONDARY | "Treated: {value} ha" | "Treated: 10 ha" |
| **Organic Matter Addition** | | | | |
| | `material_type` | 🔴 IMMEDIATE | "Added: {value}" | "Added: Aged compost" |
| | `application_rate` | 🔴 IMMEDIATE | "Rate: {value} tons/ha" | "Rate: 5 tons/ha" |
| | `organic_content` | 🔴 IMMEDIATE | "Organic boost: {value}%" | "Organic boost: +0.5%" |
| | `carbon_sequestered` | 🔴 IMMEDIATE | "Carbon stored: {value} tons" | "Carbon stored: 2.5 tons" |
| | `observation` | 🟡 SECONDARY | "Benefits: {value}" | "Benefits: Improved water retention" |
| **Compost Application** | | | | |
| | `compost_source` | 🔴 IMMEDIATE | "Compost: {value}" | "Compost: On-farm plant waste" |
| | `maturity_level` | 🟡 SECONDARY | "Maturity: {value}" | "Maturity: Fully composted" |
| | `nutrients_added` | 🔴 IMMEDIATE | "Nutrients: {value}" | "Nutrients: N-P-K 2-1-2" |
| **Biochar Application** | | | | |
| | `biochar_source` | 🔴 IMMEDIATE | "Biochar from: {value}" | "Biochar from: Agricultural waste" |
| | `carbon_content` | 🔴 IMMEDIATE | "Carbon stored: {value}%" | "Carbon stored: 85%" |
| | `application_rate` | 🟡 SECONDARY | "Applied: {value} tons/ha" | "Applied: 1 ton/ha" |
| | `longevity` | 🔴 IMMEDIATE | "Permanence: {value} years" | "Permanence: 100+ years" |

---

## 🐛 PEST MANAGEMENT EVENTS (Type 7)
### All IPM Activities & Their Fields

| Activity Type | Field | Display Priority | Consumer Display Format | Example |
|--------------|-------|-----------------|------------------------|---------|
| **Scouting** | | | | |
| | `pests_found` | 🔴 IMMEDIATE | "Monitoring: {value}" | "Monitoring: Below threshold" |
| | `pest_count` | 🟡 SECONDARY | "Count: {value} per plant" | "Count: 2 per plant" |
| | `threshold_level` | 🔴 IMMEDIATE | "Action threshold: {value}" | "Action threshold: 5 per plant" |
| | `action_taken` | 🔴 IMMEDIATE | "Decision: {value}" | "Decision: No treatment needed" |
| | `observation` | 🟡 SECONDARY | "Notes: {value}" | "Notes: Natural predators present" |
| **Beneficial Release** | | | | |
| | `beneficial_species` | 🔴 IMMEDIATE | "Released: {value}" | "Released: Ladybugs (500)" |
| | `target_pest` | 🔴 IMMEDIATE | "Controls: {value}" | "Controls: Aphids naturally" |
| | `release_rate` | 🟡 SECONDARY | "Density: {value} per ha" | "Density: 5000 per ha" |
| | `effectiveness` | 🔴 IMMEDIATE | "Result: {value}" | "Result: 85% pest reduction" |
| | `observation` | 🟡 SECONDARY | "Success: {value}" | "Success: Established population" |
| **Trap Monitoring** | | | | |
| | `trap_type` | 🔴 IMMEDIATE | "Trap type: {value}" | "Trap type: Pheromone trap" |
| | `pest_count` | 🔴 IMMEDIATE | "Captured: {value}" | "Captured: 12 moths/week" |
| | `threshold` | 🔴 IMMEDIATE | "Alert level: {value}" | "Alert level: 20 moths/week" |
| | `action` | 🔴 IMMEDIATE | "Status: {value}" | "Status: Monitoring continues" |
| **Biological Control** | | | | |
| | `control_agent` | 🔴 IMMEDIATE | "Biocontrol: {value}" | "Biocontrol: Bacillus thuringiensis" |
| | `target_pest` | 🔴 IMMEDIATE | "Targets: {value}" | "Targets: Caterpillars" |
| | `application_method` | 🟡 SECONDARY | "Method: {value}" | "Method: Foliar spray" |
| | `effectiveness` | 🔴 IMMEDIATE | "Result: {value}" | "Result: 90% control achieved" |

---

## 💼 BUSINESS EVENTS (Type 6)
### All Business Activities & Their Fields

| Activity Type | Field | Display Priority | Consumer Display Format | Example |
|--------------|-------|-----------------|------------------------|---------|
| **Certification** | | | | |
| | `certification_type` | 🔴 IMMEDIATE | "Certified: {value}" | "Certified: USDA Organic" |
| | `certifying_body` | 🔴 IMMEDIATE | "By: {value}" | "By: Oregon Tilth" |
| | `expiry_date` | 🟡 SECONDARY | "Valid until: {value}" | "Valid until: Dec 2025" |
| | `certificate_number` | 🟢 DETAILS | "Certificate: {value}" | "Certificate: #ORG-2024-123" |
| **Audit/Inspection** | | | | |
| | `audit_type` | 🔴 IMMEDIATE | "Audit: {value}" | "Audit: Food Safety" |
| | `auditor` | 🟡 SECONDARY | "Auditor: {value}" | "Auditor: GlobalGAP" |
| | `result` | 🔴 IMMEDIATE | "Result: {value}" | "Result: Passed with excellence" |
| | `recommendations` | 🟡 SECONDARY | "Feedback: {value}" | "Feedback: Best practices observed" |
| **Training/Education** | | | | |
| | `training_topic` | 🔴 IMMEDIATE | "Training: {value}" | "Training: Sustainable farming" |
| | `provider` | 🟡 SECONDARY | "Provider: {value}" | "Provider: Agricultural Extension" |
| | `participants` | 🟡 SECONDARY | "Attendees: {value}" | "Attendees: 5 staff members" |
| | `skills_gained` | 🔴 IMMEDIATE | "New skills: {value}" | "New skills: Precision agriculture" |

---

## 📋 GENERAL EVENTS (Type 3)
### All General Activities & Their Fields

| Activity Type | Field | Display Priority | Consumer Display Format | Example |
|--------------|-------|-----------------|------------------------|---------|
| **Tillage** | | | | |
| | `tillageMethod` | 🔴 IMMEDIATE | "Method: {value}" | "Method: No-till conservation" |
| | `areaTreated` | 🔴 IMMEDIATE | "Area: {value} ha" | "Area: 15 ha" |
| | `equipmentName` | 🟡 SECONDARY | "Equipment: {value}" | "Equipment: No-till seeder" |
| | `fuelAmount` | 🟡 SECONDARY | "Fuel saved: {value} L" | "Fuel saved: 30 L vs conventional" |
| | `soil_health_impact` | 🔴 IMMEDIATE | "Soil benefit: {value}" | "Soil benefit: Preserved structure" |
| **Cover Crop** | | | | |
| | `coverCropSpecies` | 🔴 IMMEDIATE | "Cover crop: {value}" | "Cover crop: Winter rye & vetch" |
| | `coverCropActivity` | 🔴 IMMEDIATE | "Activity: {value}" | "Activity: Planting for soil health" |
| | `areaTreated` | 🔴 IMMEDIATE | "Coverage: {value} ha" | "Coverage: 20 ha" |
| | `seedingRate` | 🟡 SECONDARY | "Seeding: {value} kg/ha" | "Seeding: 100 kg/ha" |
| | `benefits` | 🔴 IMMEDIATE | "Benefits: {value}" | "Benefits: Nitrogen fixation, erosion control" |
| | `termination_method` | 🟡 SECONDARY | "Termination: {value}" | "Termination: Roller crimper" |
| **Energy** | | | | |
| | `energyType` | 🔴 IMMEDIATE | "Energy: {value}" | "Energy: Solar power" |
| | `energyAmount` | 🔴 IMMEDIATE | "Used: {value} kWh" | "Used: 500 kWh" |
| | `facilityName` | 🟡 SECONDARY | "Location: {value}" | "Location: Packing house" |
| | `energyCost` | 🟢 DETAILS | "Cost: ${value}" | "Cost: $0 (solar)" |
| | `carbon_saved` | 🔴 IMMEDIATE | "CO2 saved: {value} kg" | "CO2 saved: 250 kg" |
| **Conservation Practice** | | | | |
| | `practiceType` | 🔴 IMMEDIATE | "Practice: {value}" | "Practice: Riparian buffer" |
| | `areaTreated` | 🔴 IMMEDIATE | "Area: {value} ha" | "Area: 2 ha" |
| | `establishmentCost` | 🟢 DETAILS | "Investment: ${value}" | "Investment: $5,000" |
| | `expectedLifespan` | 🟡 SECONDARY | "Duration: {value} years" | "Duration: 20 years" |
| | `environmental_benefit` | 🔴 IMMEDIATE | "Impact: {value}" | "Impact: Filters runoff, wildlife habitat" |
| **Verification** | | | | |
| | `verificationType` | 🔴 IMMEDIATE | "Verified: {value}" | "Verified: Residue testing" |
| | `verificationProtocol` | 🟡 SECONDARY | "Standard: {value}" | "Standard: EPA Method 1699" |
| | `sampleCount` | 🟡 SECONDARY | "Samples: {value}" | "Samples: 10" |
| | `verifierName` | 🔴 IMMEDIATE | "Lab: {value}" | "Lab: Certified Testing Lab" |
| | `result` | 🔴 IMMEDIATE | "Result: {value}" | "Result: No residues detected" |

---

## 📊 DISPLAY IMPLEMENTATION GUIDELINES

### Progressive Disclosure Rules

```javascript
const displayRules = {
  // IMMEDIATE fields load with event card
  immediate: {
    loadTime: "0-1s",
    fields: "Trust indicators, safety context, key outcomes",
    example: "Commercial name, application purpose, weather protection"
  },
  
  // SECONDARY fields in expandable section
  secondary: {
    loadTime: "1-3s",
    fields: "Technical details, additional context, measurements",
    example: "Exact concentrations, durations, equipment details"
  },
  
  // DETAILS in "Learn More" section
  details: {
    loadTime: "On-demand",
    fields: "Full specifications, costs, regulatory data",
    example: "Certificate numbers, investment amounts, lab protocols"
  }
};
```

### Consumer-Friendly Transformations

```javascript
const transformations = {
  technical_to_simple: {
    "10-10-10": "Balanced nutrition (equal N-P-K)",
    "2.5 L/ha": "Precisely measured application",
    "pH 6.5": "Optimal soil balance",
    "< threshold": "No treatment needed - natural balance maintained"
  },
  
  numbers_to_context: {
    "42°C": "42°C/108°F extreme heat",
    "500 ladybugs": "Natural pest control army deployed",
    "4.2% OM": "4.2% organic matter (excellent soil health)",
    "3 L/ha fuel": "3 L/ha (40% below conventional methods)"
  },
  
  timing_to_story: {
    "pre-emergence": "Preventive treatment before weeds emerge",
    "7 days PHI": "Safe to harvest in 7 days",
    "peak ripeness": "Harvested at perfect maturity",
    "calm morning": "Applied in ideal conditions for safety"
  }
};
```

### Trust Building Elements

```javascript
const trustIndicators = {
  verification: {
    "✓ Lab tested": "Third-party verification",
    "✓ Certified organic": "Official certification",
    "✓ Below threshold": "Science-based decision",
    "✓ Weather optimal": "Responsible application"
  },
  
  safety: {
    "✓ Licensed applicator": "Professional expertise",
    "✓ PPE used": "Worker safety priority",
    "✓ Buffer zones": "Environmental protection",
    "✓ Drift prevention": "Neighbor consideration"
  },
  
  sustainability: {
    "✓ Water saved": "Resource conservation",
    "✓ Carbon stored": "Climate positive",
    "✓ Biodiversity": "Ecosystem support",
    "✓ Soil health": "Long-term thinking"
  }
};
```

---

## 🎯 IMPLEMENTATION CHECKLIST

### For Each Event Type:
- [ ] Display ALL collected fields (not just summaries)
- [ ] Apply progressive disclosure (Immediate → Secondary → Details)
- [ ] Transform technical language to consumer-friendly
- [ ] Add trust indicators and verification badges
- [ ] Include educational context where helpful
- [ ] Calculate derived values (efficiency, yield/area, etc.)
- [ ] Show environmental benefits prominently
- [ ] Highlight safety and responsible practices

### Priority Implementation:
1. **Chemical Events** - All NPK values, weather conditions, timing
2. **Weather Events** - Start/end dates, duration calculations, all measurements
3. **Production Events** - Yield calculations, quality indicators
4. **Soil Management** - Test results with interpretation
5. **Pest Management** - Natural control emphasis
6. **Equipment Events** - Efficiency calculations
7. **Business Events** - Certifications and audits
8. **General Events** - Conservation practices and benefits

---

## 📱 MOBILE OPTIMIZATION NOTES

- **IMMEDIATE fields** must load in <500ms
- **SECONDARY fields** lazy load on expansion
- **DETAILS** only load when specifically requested
- Use icons and badges for quick visual understanding
- Maintain 44px minimum touch targets
- Progressive images for photo verification
- Cache calculations and transformations

This matrix ensures **100% of collected transparency data** is displayed to consumers in meaningful, trust-building ways.