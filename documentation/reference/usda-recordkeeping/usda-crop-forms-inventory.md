# P1 — Field Inventory: USDA Documentation Forms for Organic Crop Producers

**Source:** `pdf/NOP-CropDocumentationForms.pdf` (March 2011), extracted to
`txt/NOP-CropDocumentationForms.txt`. Provenance, hashes, and the two standing caveats are in
`MANIFEST.md` — read them first. In particular: these forms are **optional and pre-SOE**, so this
inventory is **Baseline A** only. Baseline B (§ 205.103 as amended, 88 FR 3621) is scored separately.

**Scope:** 25 crop forms, PDF pages C1–C25. **~198 distinct capture fields.**

**Counting rules** (so the denominator is auditable): a repeating table column counts once, not once
per row. A checkbox group (e.g. "Swept / Vacuum / Air blown / Washed / Other") counts as one field.
Header fields (Farm Name, Year) count. Signature and Date on an attestation count as fields, because
a record that cannot be signed cannot satisfy the form.

**Verdict column** is deliberately absent. This phase inventories only; the join against Trazo's
models and the MET/PARTIAL/GAP calls are P2.

---

## Land Use Records — *§ 205.202*

### 1. Field History / Previous Land Use Record — C1, txt:2
Establishes the date of last prohibited-material application over **36 months** to determine
eligibility. "Complete one form for each location."

| Field | Notes |
|---|---|
| Field, Pasture, or Location ID | header |
| Year | rows are pre-labeled *This year / Last year / Two years ago / Three years ago* — a fixed 4-year lookback |
| Crop or Land Use | |
| Material / Product Brand Name | "Include all fertilizer and pest-management materials applied" |
| Manufacturer | |
| Application Date(s) | |
| Signature | attestation: "complete and accurate to the best of my knowledge" |
| Date | |

### 2. Land Use History Verification — C2, txt:46
**Third-party attestation.** Signed by the *prior* manager of the land, not the applicant.

| Field | Notes |
|---|---|
| Organic Producer Name | |
| Crop Production Year | |
| Affirming party name | free text in the affidavit sentence |
| Dates of management/control | from–to |
| Land parcel description | "assessor's parcel number, county, township/section/range, or other regulatory description" |
| Number of acres in parcel(s) | |
| ☐ No materials applied | negative-declaration checkbox |
| Parcel / Field Location & Crop | table col |
| Material / Manufacturer | table col |
| Date Applied | table col |
| Date of submission | |
| Signature | |
| Name (printed) | |

---

## Activity Records — *§ 205.2 (Records, Crop Rotation); § 205.103; § 205.201*

### 3. Activity Log — C3, txt:76
| Field | Notes |
|---|---|
| Farm/Location | header |
| Year | header |
| Date | |
| Activities | free text. Scope per the form: "planting, input applications, mowing, irrigation, pest monitoring, weather" |

Note: "Records may be kept in any type of notebook or format" — USDA does not prescribe structure here.

### 4. Activity Calendar — C4, txt:90
Same data as #3 in month-grid form. Alternative, not additional.

| Field | Notes |
|---|---|
| Month/Year | header |
| Farm/Location | header |
| Day cell 1–31 | free-text activity note per day |

---

## Planting / Harvest / Crop Rotation — *§ 205.2 (Crop Rotation); § 205.205*

### 5. Planting and Harvest Record — C5, txt:125
| Field | Notes |
|---|---|
| Location | with acreage in the example ("Field A, 1 ac.") |
| Crop Variety / Source or Lot# | |
| Transplant / Seeding or Wet Date (if irrigated) | "wet date" is the irrigation-start date used for annual-crop timing |
| Harvest Date(s) | |
| Harvest Quantity / Yield | |
| Buyer / Price | ← sales data appearing on a *production* form |

### 6. Crop Rotation Record — C6, txt:140
| Field | Notes |
|---|---|
| Farm | header |
| Location | footnoted: "Farm, ranch, field, pasture, parcel, plot, or bed" |
| Year/Season & Crop(s) Planted | **4 repeating columns** — a multi-season history in one row |

Explicitly includes cover crops, green manures, and grazed pasture/forage — not just saleable crops.

---

## Input Material Records — *§ 205.2 (Agricultural Input, Compost); § 205.203; § 205.205; § 205.601; § 205.602*

### 7. Input Material Application Record — C7, txt:163
The single highest-traffic form, and the closest analogue to Trazo's ChemicalEvent.

| Field | Notes |
|---|---|
| Farm or Ranch Location/Crop | header |
| Year | header |
| Date Applied | |
| Location and Crop | "farm, field, parcel, or bed, and crop (including cover crops, green manures, pasture)" |
| Material / Product Name | footnote 3: "**and formulation, if applicable**" |
| Source / Manufacturer | footnote 4 is emphatic — **manufacturer, explicitly distinct from distributor**, because allowability is verified against the formulator |
| Purpose / Reason for Use | footnote 5: "Some materials are allowed for pest management but not as a soil amendment" |
| Organic Status Verification | footnote 6 enumerates exactly four acceptable bases: **OMRI or WSDA List, NOP Seal on label, or certifier review and approval** |
| Application Method and Rate / Amount | one combined column |

**Supporting documents named on the form:** receipts for purchased inputs; labels for materials not
on an approved list; receiving/source records for free inputs; **county Pesticide Use Reports**.

### 8. Compost Production Record — C8, txt:202
| Field | Notes |
|---|---|
| Farm Name | |
| Production Year | |
| Compost System | ☐ Windrow ☐ Static ☐ Aerated Pile ☐ In-Vessel ☐ Other |
| Compost Pile, Windrow or Unit ID | |
| Location/Method of Temperature Reading | |
| Feedstocks / Materials Used (and quantity) | |
| Estimated C/N Ratio of mixture | example "30:1" |
| Date | temp-log col |
| Temperature | temp-log col |
| Turned? | temp-log col |
| Initials of Responsible Party | temp-log col |
| Notes | |

⚠️ **The form cites "NOP § 203(c)(2)" — a malformed citation** (no such part; it means
**§ 205.203(c)(2)**). Use the correct cite downstream.

This form's fields map 1:1 onto § 205.203(c)(2)'s numeric thresholds, verified against
`cfr/title-7-part-205_2026-08-05.txt`: initial C:N **between 25:1 and 40:1**; **131–170 °F** for
**3 days** in-vessel/static-aerated, **or 15 days** windrow with **≥ 5 turnings**. That makes compost
the most mechanically checkable record in the entire set — a strong candidate for an automated
readiness check rather than a free-text field.

### 9. Manure Application / Food Crop Harvest Interval Record — C9, txt:231
| Field | Notes |
|---|---|
| Farm | header |
| Year | header |
| Location and Crop | |
| Date / Rate of Manure Application | one combined column |
| Date of Harvest — Estimated | |
| Date of Harvest — Actual | **both** estimated and actual are captured |
| How Applied / Incorporated | example: "Manure spreader disk in" |
| Manure Type, Form and Source | example: "Chicken, dry, on farm" |
| Documentation of EU Compliance | form says this column is **optional**; "disregard that column if it's not applicable" |

⚠️ **The form cites "§ 205.2: Manure, and § 205.203 (b)".** The 90/120-day interval actually lives at
**§ 205.203(c)(1)(ii)–(iii)** — (ii) 120 days where the edible portion contacts soil, (iii) 90 days
where it does not. § 205.203(b) is the general crop-nutrient clause. Verified against the corpus.
**Cite (c)(1) downstream, not (b).**

---

## Seed and Planting Stock Records — *§ 205.204; § 205.2 (Commercially Available)*

Parts A/B/C are one linked set: A is the supplier reference list, B references A by abbreviation.

### 10. Seed Records Part A: Suppliers of Seed or Planting Stock — C10, txt:254
| Field |
|---|
| Company or Seed Source |
| Contact Information |
| Abbreviation |

The **Abbreviation** column exists solely as a join key into Part B. A product implementing this
needs a persistent supplier entity, not a free-text supplier string per row.

### 11. Seed Records Part B: Nonorganic Seed or Planting Stock — C11, txt:275
| Field | Notes |
|---|---|
| Nonorganic Seed or Planting Stock Type and Variety | |
| Supplier / Quantity Used | |
| Reason for Commercial Nonavailability | qualified as **form, quality, quantity** — the three statutory axes |
| Suppliers Contacted | "list numbers or abbreviations from list of seed suppliers" → FK to Part A |
| Documentation of Allowed Status | three-part: **a) allowed list, b) no prohibited treatments, c) non-GMO** |

**Supporting documents named:** purchase receipts; order forms and special requests; **current
organic certificates for all annual seedlings or transplants**.

### 12. Seed Records Part C: Documentation of Allowability of Seed Treatments, Coatings, or Inoculants — C12, txt:300
| Field |
|---|
| Date |
| Location |
| Crop / Variety |
| Inoculant or Seed Coating |
| Documentation of Allowed Status |

### 13. Seed-saving and Planting-stock Propagation Record — C13, txt:312
| Field |
|---|
| Harvest Date |
| Crop / Variety |
| Field / Location of Harvest or Propagation |
| Quantity / Storage Location |

---

## Harvest, Inventory/Storage, Sales, and Transaction Records — *§ 205.103; § 205.201*

> This is the audit-trail block — **7 of the 25 forms.** The Harvest Record and Storage Inventory
> Record both state the governing principle verbatim: *"The audit trail is complete when the producer
> releases control of the product."*

### 14. Harvest Record — C14, txt:322
| Field | Notes |
|---|---|
| Farm Name | header |
| Crop Year/Season | header |
| Harvest Date | |
| Location (Field or Parcel ID) | |
| Crop | |
| Quantity | |
| Where Stored or Sold | ← the link from production to disposition |

**Supporting documents named:** receipts and organic certificates for purchased product; transport
records (**delivery tags, receiving tags, bills of lading, clean transport records**); sales records
(**purchase orders, invoices**).

### 15. Farmers Market Load List or Farm Stand Sales Record — C15, txt:341 · *direct-market*
| Field |
|---|
| Farm Name · Location · Date(s) |
| Crop or Product |
| Unit of Measure (bunches, baskets, boxes, lb.) |
| Quantity — To Market |
| Quantity — Remaining |
| Sold — Quantity |
| Sold — Price |
| Sold — Revenue |
| Expenses: stall fee · mileage · staff wages · misc · total |

### 16. Harvest Plan and Record "Pick List" — C16, txt:365 · *direct-market*
Matrix form: crops down, markets across.
| Field |
|---|
| Date · Farm or Location |
| Crops (row axis) |
| Markets (column axis) |
| Harvest Location (specific) |
| Quantity per crop × market cell |

### 17. Community Supported Agriculture (CSA) Weekly Harvest And Cost Summary — C17, txt:383 · *direct-market*
| Field | Notes |
|---|---|
| Week of · Weekly Share Price for Full Share | |
| Produce · Crop / Variety | |
| Source (farm or purchased product) | footnote 7: purchased product **must also be disclosed to shareholders** in writing so anyone can tell where each product came from and whether it is certified organic |
| Quantity of Product · Value of Product | |
| Quantity (number of shares) · Total Value or Revenue | |
| LABOR: Worker · Rate · Hours · Total | |
| DELIVERY: Route · Miles · Rate · Total | |
| Other CSA-Related Travel or Expenses | |

### 18. Harvest Instructions / Record — C18, txt:424
| Field | Notes |
|---|---|
| Date · Market (or CSA Distribution) | header |
| Location · Crop · Variety · Quantity | |
| Comments | "quantity, special harvest instructions, post-harvest handling, storage" |
| Initial When Complete | **per-row sign-off by the worker who did it** |

### 19. Total Farm Sales Record — C19, txt:443
| Field |
|---|
| Farm Name · Crop Year |
| Date of Sale or Delivery |
| Market or Buyer |
| Record and Location |
| Total Sales Receipts $ |
| Expenses |
| Net for Market |

"Record and Location" is a **pointer to where the underlying document is filed** — a record-of-records
column. Same supporting-document list as #14.

### 20. Storage Inventory Record — C20, txt:462
| Field |
|---|
| Crop or Product Stored |
| Storage Location and Type |
| Quantity / Date In |
| Quantity / Date Out |
| Inventory Balance |

**Supporting documents named:** grower statements, invoices, delivery/receipting tags, other
audit-trail documents. This is the mass-balance record — in / out / running balance.

---

## Prevention of Commingling and Contamination — *§ 205.201(a)(5),(6); § 205.103; § 205.272*

### 21. Equipment Cleaning Log — C21, txt:478
| Field |
|---|
| Date |
| Equipment or Surface |
| Cleaning Methods and Materials |
| Responsible Party |

Applies to equipment "not dedicated to organic operations" — i.e. split-operation shared equipment.

### 22. Clean Transport Affidavit — C22, txt:493 · **attestation**
| Field | Notes |
|---|---|
| Producer/Business Name | |
| Date Transport Unit Loaded | |
| Type of transport | ☐ farm wagons ☐ farm truck ☐ bulk semi trailer ☐ common carrier ☐ tanker ☐ other |
| Transportation arranged by | ☐ grower ☐ buyer ☐ other |
| Only used for organic products? | ☐ yes ☐ no → if no, **state products transported prior to organic** |
| Inspected and found free of | ☐ foreign odors ☐ residues ☐ conventional products ☐ other |
| Transport Unit / Vehicle Identification | table col |
| Organic Crop and **Lot #** | table col — lot-level traceability |
| ☐ Inspected prior to loading | table col |
| Cleaning method | ☐ Swept ☐ Vacuum ☐ Air blown ☐ Washed ☐ Other |
| Signature · Date | certification statement |

### 23. Buffer Crop Disposition Records — C23, txt:533
| Field | Notes |
|---|---|
| Location | example is orchard-shaped: "North side of Parcel 1, one row of apple trees (25 trees)" |
| Buffer Crop | |
| Map | narrative describing neighbor position, slope, cardinal direction, **prevailing winds** |
| Marking | how buffer plants are physically flagged pre-harvest — example uses red ribbon plus a **dated photograph** matched to the day before harvest |
| Date · Crop / Variety · Location | table cols |
| Disposition | sold as nonorganic, home use, donated, disked under |
| Quantity | |
| Sales (gross revenue in dollars) | |
| Documentation (type and location) | again a record-of-records pointer |

Form warns: commercial quantities need **formal** documentation (delivery tags + nonorganic sales
records) proving the buffer crop was never represented as organic; and *"Always check with your
certifier… before harvest season arrives."*

### 24. Sample Neighbor Notification Letter — C24, txt:562 · **outbound correspondence**
Template letter, not a table.
| Field |
|---|
| Date · Neighbor name and address |
| Name of certifying agent |
| Direction of bordering field (E/W/N/S) |
| Adjoining field # |
| Signature of organic farmer |
| Enclosures: Verification of Adjoining Land Use letter · Farm map |

### 25. Adjoining Land Use Verification — C25, txt:610 · **third-party attestation**
Completed and signed **by the neighbor**.
| Field |
|---|
| Location (of the organic farm) |
| Neighbor name · bordering side(s) N/E/S/W |
| ☐ I am an organic farmer, certified by ____ (or exempt due to sales) |
| Materials routinely used: ☐ synthetic fertilizers ☐ herbicides ☐ insecticides ☐ fungicides ☐ treated wood ☐ other ☐ none of the above |
| ☐ I use the materials above, but not on the fields adjoining my neighbor |
| Distance from use to organic property (feet) |
| ☐ I agree to notify my organic neighbor before use |
| Signature of neighbor · Date |
| Farm Name · Address · Phone number |

---

## Cross-cutting observations for P2

**1. Four forms cannot be completed by the farmer alone.** #2 (prior land manager), #22 (transport
operator), #24 (outbound letter), #25 (neighbor). These need a *request → collect → store
countersigned artifact* workflow, which is a different product shape from event logging. Flag as a
distinct gap class, not as four missing forms.

> **Corrected in P2:** an earlier draft of this note asserted Trazo "has no such flow today." That
> is wrong. `certifications.LandownerAffidavit` is exactly this shape — `previous_manager_*`,
> `landowner_*`, `attestation_text`, two signed-date fields, and a `signed_document` FileField — and
> it covers form #2. The gap is narrower than stated: the pattern exists but is **not reused** for
> #22 or #25. See `usda-crop-forms-crosswalk.md`.

**2. Signature / attestation appears on 5 forms** (#1, #2, #22, #24, #25) and per-row initials on 2
(#8 compost, #18 harvest instructions). A typed field is not a signature; P2 must decide whether
Trazo's records carry an attestation artifact at all.

**3. Nine forms point at documents rather than capture data.** Recurring named attachment types:
receipts, invoices, purchase orders, product labels, **current organic certificates**, delivery
tags, receiving tags, **bills of lading**, clean transport records, grower statements, county
Pesticide Use Reports, dated photographs, farm maps. § 205.103(b)(2)'s audit trail is satisfied by
*attachments plus fields*, not fields alone. Two forms (#19, #23) even have an explicit "where is
this filed" column.

**4. Lot number appears exactly once** (#22 Clean Transport, "Organic Crop and Lot #"). Everything
else keys on field/parcel + date + crop. Worth checking whether Trazo needs lot identity or whether
parcel+date is sufficient for the ICP.

**5. Scope calls to make explicitly in P2, not silently.** #15, #16, #17 are direct-market shaped
(farmers market, pick list, CSA) and likely `N/A-scope` for a wholesale tree-nut ICP. #18 is
market-garden flavored but its structure (crew instructions + per-row completion initials) is
general. If #15–17 are excluded, the live audit-trail requirement narrows to **#14, #18, #19, #20**
— and the denominator drops from 25 to 22. **Write the exclusion down; do not let the score improve
by quietly shrinking the set** (same failure the corpus-scoping section of `MANIFEST.md` guards
against).

**6. Two citation errors in USDA's own forms**, both verified against
`cfr/title-7-part-205_2026-08-05.txt`: compost cites "NOP § 203(c)(2)" (should be § 205.203(c)(2));
manure cites "§ 205.203 (b)" for the 90/120-day interval (it is § 205.203(c)(1)(ii)–(iii)). Trazo
must cite the correct sections — an inherited wrong citation in a certifier-facing PDF is worse than
no citation.

**7. Fixed 36-month / 4-year lookback** on #1 is a hard structural requirement, not a preference. Any
Trazo land-history feature must produce exactly that window.
