# Complete Verified Emission Factors Reference

**Last Comprehensive Audit: 2025-12-03 · Electricity + fertilizer citation review: 2026-09-07**

All emission factors are stored in `trazo-back/carbon/services/verified_emission_factors.py`.

> **CRITICAL UPDATE 2025-12-03**: Electricity factor was corrected from 0.821 to 0.39 kg CO2/kWh after discovering the previous value was 2.1x too high based on EPA eGRID 2023 data.

> **CRITICAL UPDATE 2026-09-07 — electricity 0.39 -> 0.365 kg CO2e/kWh.** 0.39 did not follow
> from the source cited for it. 0.39 is EPA's **Equivalencies Calculator** figure (823.1 lb
> CO2/MWh, **eGRID2022** data, 5.12% T&D losses) — a real EPA number, but from a different
> publication and an older data year than the eGRID2023 Summary Tables this file named. Deriving
> the factor from the source actually cited gives 0.365, and eGRID's published U.S. grid gross
> loss is **4.2%**, not 5.12%. The old line below even showed the gap ("0.366 -> 0.39") without
> explaining it.

> **DECIDED 2026-09-07 — P2O5 and K2O are Trazo conservative estimates, not agency figures.**
> Both were attributed to the *EPA GHG Emission Factors Hub (40 CFR Part 98)*. That publication
> contains **no fertilizer manufacturing factors at all** (checked against the 2025 Hub). The
> attribution is withdrawn and the values are held where they are, deliberately:
>
> * Walling & Vaneeckhaute 2020 put phosphorus production at **1.0-1.5** kg CO2e/kg P2O5. Ours,
>   1.19, sits inside that range and toward its upper half.
> * Brentrup et al. 2018 (via the 4C emission-factor list) implies **~0.52**/kg P2O5 for triple
>   superphosphate and **~0.42**/kg K2O for muriate of potash — but that is *European* production.
>   US phosphate is largely domestic (FL/LA) and US potash largely Canadian, so adopting those
>   figures would swap an unsourced number for a mis-scoped one **and move the estimate down**.
> * For a transparency product, overstating our own footprint is the safe direction and
>   understating it is the greenwashing direction. So the numbers stay at the conservative end
>   while they are imprecise, and they are labelled `internal_estimate` — our judgement within a
>   cited range, not an agency's figure. Nothing on any surface may present them as sourced.

## Official Data Sources

| Source | Description | URL |
|--------|-------------|-----|
| EPA GHG Emission Factors Hub | 40 CFR Part 98 fuel combustion factors | https://www.epa.gov/climateleadership/ghg-emission-factors-hub |
| EPA eGRID2023 Summary Tables rev.2 | US grid rates (U.S. CO2 767.2, CO2e 770.9 lb/MWh; grid gross loss 4.2%) | https://www.epa.gov/egrid/summary-data |
| EIA 2023 | Electricity validation (0.81 lbs/kWh = 0.367 kg) | https://www.eia.gov/tools/faqs/faq.php?id=74&t=11 |
| IPCC 2006/2019 | N2O emission factors (EF1=1%, GWP=265) | https://www.ipcc-nggip.iges.or.jp/ |
| Lal 2004 / Audsley et al. | Pesticide manufacturing LCA | ResearchGate/ScienceDirect |
| USDA NRCS NEH Chapter 8 | Irrigation pumping energy guidelines | https://www.wcc.nrcs.usda.gov/ |

## Fuel Emission Factors (EPA 40 CFR Part 98)

| Fuel Type | Factor | Unit | Confidence | Verification |
|-----------|--------|------|------------|--------------|
| Diesel (Mobile Equipment) | 10.21 | kg CO2/gallon | 95% | EPA 40 CFR Part 98 Table C-1 |
| Diesel (Stationary) | 10.18 | kg CO2/gallon | 95% | EPA 40 CFR Part 98 Table C-1 |

## Electricity Emission Factors (EPA eGRID2023)

| Region | Factor | Unit | Confidence | Verification |
|--------|--------|------|------------|--------------|
| US Average (Delivered) | **0.365** | kg CO2e/kWh | 95% | eGRID2023 Summary Tables rev.2: U.S. 770.9 lb CO2e/MWh, 4.2% grid gross loss |
| ~~2025-12 to 2026-09~~ | ~~0.39~~ | ~~kg CO2/kWh~~ | - | ~~Equivalencies Calculator (eGRID2022), miscited as eGRID2023~~ |
| ~~Before 2025-12~~ | ~~0.821~~ | ~~kg CO2/kWh~~ | - | ~~Was 2.1x too high~~ |

**Derivation** (eGRID2023 Summary Tables rev.2, released 2025-06-12, U.S. row — CO2 767.2 lb/MWh,
CO2e 770.9 lb/MWh, grid gross loss 4.2%):

```
770.9 lb/MWh x 0.45359237 kg/lb / 1000 kWh/MWh = 0.34967 kg CO2e/kWh at the generator
0.34967 / (1 - 0.042)                          = 0.365   kg CO2e/kWh delivered
```

CO2e rather than CO2-only, because every downstream label in the product says CO2e.
**Re-check when eGRID2024 lands** — EPA's page still listed eGRID2023 rev.2 as current on
2026-09-07, with eGRID2024 "next planned".

## Fertilizer Manufacturing Emissions

| Nutrient | Factor | Unit | Source | Notes |
|----------|--------|------|--------|-------|
| Nitrogen (N) | 10.5 | kg CO2/kg N | EPA + IPCC | Manufacturing (2.6 kg) + N2O field (4.2 kg) + indirect (3.7 kg). High-end of 4-12 kg literature range |
| Phosphorus (P2O5) | 1.19 | kg CO2/kg P2O5 | **Trazo conservative estimate** — upper half of Walling & Vaneeckhaute 2020 (1.0-1.5) | Manufacturing only. Not an agency figure; never present it as sourced |
| Potassium (K2O) | 0.65 | kg CO2/kg K2O | **Trazo conservative estimate** — above Brentrup et al. 2018 (~0.42), literature sparse | Manufacturing only. Not an agency figure; never present it as sourced |
| Organic Fertilizer | 0.5 | kg CO2/kg | USDA Composting LCA | Minimal manufacturing, primarily processing |

## Chemical Manufacturing Emissions (Lal 2004 / Audsley)

| Chemical Type | Factor | Unit | Literature Range | Source |
|--------------|--------|------|------------------|--------|
| Synthetic Pesticide | 8.8 | kg CO2/kg AI | 5.1-19 kg (Lal: 5.1+/-3.0) | Midpoint for insecticides |
| Synthetic Herbicide | 5.5 | kg CO2/kg AI | 6.3-27 kg (Lal: 6.3+/-2.7) | Conservative estimate |
| Glyphosate (specific) | 31.3 | kg CO2/kg AI | - | High due to synthesis process |
| Organic Herbicide | 1.2 | kg CO2/kg | 0.64-1.2 kg | Acetic acid/vinegar-based |
| Fungicide (Synthetic) | 4.5 | kg CO2/kg AI | 3.9+/-2.2 kg (Lal) | Generic synthetic |
| Copper Fungicide | 5.5 | kg CO2/kg AI | 3-5 kg Cu mining + processing | Higher due to copper refining |
| Sulfur Fungicide | 1.8 | kg CO2/kg | - | Byproduct of oil/gas refining |
| Organic Pesticide | 3.5 | kg CO2/kg | - | Neem, pyrethrin extraction |

## Irrigation & Equipment Factors

| Factor | Value | Unit | Notes |
|--------|-------|------|-------|
| Irrigation Pump (Deep Well 200+ ft) | 3.5 | kWh/1000 gal | Literature: 3-5 kWh for deep wells |
| Irrigation Pump (Standard 50-100 ft) | 0.85 | kWh/1000 gal | Literature: 0.5-2.5 kWh typical |
| Planting Diesel | 1.8 | gal/hectare | USDA ARS |
| Harvesting Diesel | 0.7 | gal/hectare | USDA ARS (modern efficient equipment) |
| Transplanting Diesel | 2.4 | gal/hectare | Higher due to careful handling |
| Crop Production Diesel | 2.5 | gal/hectare | Average operations |

## Calculation Examples

**Irrigation Event:**
```
Water Applied: 2471 gallons
kWh = (2471 / 1000) x 3.5 = 8.65 kWh
CO2e = 8.65 x 0.365 = 3.16 kg CO2e
```

**Chemical Application:**
```
Pesticide Applied: 5 kg active ingredient
Manufacturing: 5 kg x 8.8 kg CO2/kg = 44 kg CO2e
Application Fuel: 0.5 gal x 10.21 kg CO2/gal = 5.1 kg CO2e
Total: 49.1 kg CO2e
```

**Fertilizer Application (NPK 10-10-10):**
```
Applied: 100 kg fertilizer
Nitrogen: 10 kg x 10.5 = 105 kg CO2e
Phosphorus: 10 kg x 1.19 = 11.9 kg CO2e
Potassium: 10 kg x 0.65 = 6.5 kg CO2e
Total: 123.4 kg CO2e
```

**Carbon Values Comparison:**
```
Full LCA Approach:
- Planting Event: 195.4 kg CO2e (includes supply chain)
- Result: Farmers discouraged from logging activities

Trazo Direct Approach:
- Planting Event: 76.9 kg CO2e (direct fuel only)
- Result: Farmers encouraged to document everything
```
