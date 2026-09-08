# P2 — Crosswalk: USDA Crop Documentation Forms → Trazo

**Inputs:** `usda-crop-forms-inventory.md` (25 forms, ~198 fields) × Trazo models, introspected live
via `django.apps` against `backend.settings.dev` on 2026-08-10 — not read off `models.py`, so the
field lists are what the ORM actually has.

**Code joined:** `history/services/record_completeness.py`,
`history/services/audit_export_service.py` (`compliance_snapshot_rows`, line 1598),
`certifications/services/common_osp_records.py`, `certifications/services/osp_prefill.py`,
`product/services/buffer_zones.py`, and the `history` / `product` / `certifications` model sets.

**Verdicts are desk verdicts.** Every `MET` here is a claim that a field exists and is populated by
the right flow — it is **not** proof the value reaches a certifier-facing artifact. P3 renders the
packet on the real fixture and demotes anything that cannot be shown on paper.

---

## Score

> ⚠️ **Superseded in part by P3.** This document's original headline — "no storage mass balance,
> the highest-value gap" — was **wrong**, and form #20 has been re-scored GAP → PARTIAL. The packet
> renders a `Mass-Balance Audit Summary (§ 205.103(b)(2) / § 205.2)` with yield, quantity sold, and a
> computed balance. The P2 grep searched for `inventory_balance` / `quantity_in` / `quantity_out` and
> found nothing because the feature is named *Mass-Balance* / *Output Reconciliation*. See
> `usda-crop-forms-p3-live-proof.md`. Verdicts below are corrected; the lesson is recorded there.

| Verdict | Count | Forms |
|---|---|---|
| **MET** | 6 | 3, 4, 6, 7, 14, 21 |
| **PARTIAL** | 14 | 1, 2, 5, 8, 9, 11, 12, 18, 19, 20, 22, 23, 24, 25 |
| **GAP** | 2 | 10, 13 |
| **N/A-scope** | 3 | 15, 16, 17 |

**Denominator after scope exclusion: 22 forms** (25 minus the three direct-market forms).

- Fully MET: **6 / 22 = 27%**
- MET or PARTIAL: **20 / 22 = 91%**

⚠️ **The Sep 15 gate was written as "≥90% MET." On that reading we are at 27%, not 86%.** Most
PARTIALs are one or two missing columns on a form whose spine already exists, so the distance is
smaller than 32% suggests — but the gate must be restated against a defined metric before it can be
passed. Recommend restating it as **"≥90% of in-scope forms at MET, with PARTIAL allowed only where
the missing columns are documented as out of regulatory scope."** Do not quietly redefine the gate
to whichever number the audit produced.

---

## Baseline B — § 205.103 as amended (88 FR 3621), scored independently of any form

These are product-level rows. No 2011 form has a column for them; they cannot be inherited from
Baseline A.

| Clause | Verdict | Evidence |
|---|---|---|
| **(b)(1)** adapted to the business | MET | Per-crop event templates + OSP module set |
| **(b)(2)** span purchase → production → sale/transport, traceable to last certified operation | **PARTIAL** | *Corrected by P3.* The chain **is** reconciled: the packet's `Mass-Balance Audit Summary` prints Harvest Yield, Quantity Sold, and Balance, and even catches temporal integrity errors ("1 sale(s) are dated BEFORE the harvest date"). It remains PARTIAL for the **input side** — the same section reports "Mass balance cannot be reconciled. No purchase quantity is recorded on any chemical event," because `quantity_purchased` is optional. Output side works; input side depends on data the UI does not compel |
| **(b)(3)** products identified by organic label category | **GAP** | `History.organic_on_invoice` and `SalesRecord.organic_on_invoice` are booleans. The regulation asks *which* category — "100 percent organic" vs "organic" vs "made with organic" (§ 205.303, § 205.301); a boolean cannot express that. **`LabelImage.label_type` does not carry it either** — its choices are `['nonretail', 'retail', 'unpackaged']`, i.e. packaging format, a different axis entirely. Confirmed missing, not pending |
| **(b)(4)** retained ≥ 5 years | **MET** | `history/models.py:754` sets `retention_until = finish_dt + timedelta(days=5*365)`; deletion is blocked at `models.py:336-340` with the retention date in the error. Enforced, not advisory |
| **(b)(5)** sufficient to demonstrate compliance | PARTIAL | `compliance_snapshot_rows()` runs **at least 14** distinct CFR-cited check rows (extracted by literal match — treat as a floor). `record_completeness.py`'s docstring says 16; the discrepancy is unresolved, so do not cite either number as exact in anything certifier-facing. Coverage gaps are the GAP rows below |
| **(c)** available to Secretary / State official / certifying agent | MET | `CertifierAccessLink` + `CertifierAccessLog` (tokened, expiring, revocable, access-logged) |
| SOE addition — fraud prevention | PARTIAL | `OFPP (§ 205.201(a)(3))` check exists and fails loudly when absent: *"No Organic Fraud Prevention Plan on file — required under SOE 2024"* |

🐛 **Defect found while verifying (b)(4).** `timedelta(days=5 * 365)` = 1825 days; five calendar
years spans 1826 or 1827. Computed, not assumed — a production finishing 2026-08-10 gets
`retention_until` = **2031-08-09, one day short**; finishing 2027-08-10 is **two days short** (window
catches two leap days). Every finish date tested is short by 1–2 days. Fix:
`relativedelta(years=5)`, or `finish_dt.replace(year=finish_dt.year + 5)`. Low severity, trivially
correct, and exactly the kind of thing a certifier's counsel would find.

---

## Per-form verdicts

### MET (7)

| # | Form | Trazo home | Note |
|---|---|---|---|
| 3 | Activity Log | `GeneralEvent` | `activity_type`, `activity_name`, `duration`, `people_involved`, `observation` + `CommonEvent.date` |
| 4 | Activity Calendar | — | Alternative presentation of #3's data, not additional data. MET by way of #3 |
| 6 | Crop Rotation Record | `product.ParcelCropHistory` | `parcel`, `year`, `crop_grown`, `cover_crop`, `block_id`, `production_method`. Multi-season per location, and cover crops are first-class — matches the form's explicit inclusion of green manures and forage |
| 7 | Input Material Application Record | `ChemicalEvent` | The strongest match in the set. `commercial_name`, `manufacturer` **and** `supplier_name` as separate fields (the form's footnote-4 distinction is honored), `way_of_application`, `volume_numeric`/`volume_unit`, `area_numeric`/`area_unit`, `target_pest_disease`, `organic_approved`, `omri_product`, `national_list_substance` FK, `purchase_invoice`, `quantity_purchased`, `chemical_lot_number`. Backed by `record_completeness.py`'s 4 required fields and the `Input traceability (§ 205.103)` snapshot check |
| 14 | Harvest Record | `ProductionEvent` + `History` | `yield_quantity`/`yield_unit`, `harvest_quality_grade`, `storage_location`, `harvest_destination`, `harvest_date_end`; `History.lot_id`, `production_amount`, `finish_date`, `parcel` |
| 21 | Equipment Cleaning Log | `ProductionEvent` | `cleaning_date`, `cleaning_method`, `cleaning_asset_class`, `cleaning_materials_used`, `cleaned_by`, `shared_with_conventional`, `cleaning_protocol_reference`, `equipment_cleaning_event` FK. Snapshot check fires on shared equipment with no cleaning events on file |

**Caveat on #7.** "Purpose / Reason for Use" maps to `target_pest_disease`, which
`record_completeness.py` deliberately restricts to `{PE, FU, HE}` — fertilizer (`FE`) has no target
pest, and correctly so. But the USDA column is *purpose*, not *target*, and the form's own footnote
says purposes include "soil fertility." **A fertilizer application therefore has no purpose field.**
Narrow, real, and cheap to close.

### PARTIAL (12)

| # | Form | Have | Missing |
|---|---|---|---|
| 1 | Field History / Previous Land Use | `ParcelCropHistory.year/crop_grown/cover_crop/substances_applied/last_prohibited_substance/date_last_prohibited`; `Parcel.date_began_managing` | `substances_applied` is a **TextField** — help text calls it a "Summary of all substances applied during this year." So the form's per-row **Material / Manufacturer / Application Date(s)** columns collapse into one prose blob: no manufacturer field, no individual application dates, nothing queryable. Also no applicant signature block |
| 2 | Land Use History Verification | `certifications.LandownerAffidavit` — `previous_manager_*`, `landowner_*`, `last_prohibited_date`, `attestation_text`, two signed-date fields, `signed_document` FileField | `yearly_history` JSON is documented as `{year, land_use, inputs, applied_by}` dicts. The form's table needs **Material / Manufacturer** and **Date Applied** per row — `applied_by` is the applicator, not the manufacturer, and there is no per-application date. Also: the "☐ No materials applied" negative declaration has no representation (an empty `inputs` is ambiguous between "none applied" and "not yet filled in"), and the parcel's regulatory description lives on `Parcel.apn`/`section_township_range`, not on the affidavit |
| 5 | Planting and Harvest Record | `ProductionEvent.area_covered/yield_quantity/harvest_date_end`, `CommonEvent.variety`, `seed_lot_number`, `History.start_date/expected_harvest/finish_date/sold_to` | **Price.** `SalesRecord` has no price or revenue field anywhere |
| 8 | Compost Production Record | `SoilManagementEvent.compost_method/compost_initial_cn_ratio/compost_peak_temp_f/compost_duration_days_at_temp/compost_turning_count/compost_feedstock`; snapshot check enforces the 25:1–40:1 floor by name | **Pile / windrow / unit ID**; **location & method of temperature reading**. `compost_temperature_log` is a **TextField**, not structured rows — the form's Date / Temperature / Turned? / Initials table is free prose, so per-reading responsible-party initials are uncheckable and the snapshot check must be reading the scalar `compost_peak_temp_f` / `compost_duration_days_at_temp` / `compost_turning_count` fields instead. The scalars satisfy § 205.203(c)(2); the *log* does not stand as an auditable record |
| 9 | Manure Application / Harvest Interval | `manure_application_date`, `manure_harvest_interval`, `manure_treatment`, `processed_manure_temp_f`, `processed_manure_attestation`; `§ 205.203(c)(1) interval` check | **Estimated vs actual harvest date as two fields** (interval is stored as a computed number, so a changed harvest date cannot be audited against the original plan); **how applied / incorporated**; **manure type, form and source** |
| 11 | Seed Records Part B | `seeds_source`, `seed_certification_status`, `seed_search_attempts` (JSON), `seed_supplier_name`, `seed_purchase_invoice`, `seed_treatment`, `seed_lot_number` | Whether the JSON carries the **three statutory nonavailability axes (form / quality / quantity)** and the **a/b/c allowed-status triple** is unverified — schema check is a P3 item |
| 12 | Seed Records Part C | Date, location, crop/variety come free from `CommonEvent`; `seed_treatment` names the treatment | **Documentation of allowed status** for the treatment/coating/inoculant. A named treatment with no allowability basis is the same failure mode `record_completeness.py` was built to catch |
| 18 | Harvest Instructions / Record | `CommonEvent.performed_by`, `reviewed`, `reviewer_name`, `review_date`, `description` | No pairing of an *instruction* with a *per-row completion initial*. Arguably N/A for mechanical wholesale harvest — **make the scope call explicitly** |
| 20 | Storage Inventory Record | The packet's `Mass-Balance Audit Summary` computes **Harvest Yield − Quantity Sold = Balance** in a common unit, backed by `Itemized Sales Records (§ 205.307(a))` and a per-shipment transport table. The regulatory purpose of the form — auditable reconciliation — is served | The form's own artifact is a **dated in/out ledger per storage location with a running balance**; Trazo computes a single production-level figure instead. `ProductionEvent.storage_location` is a `CharField` and was **empty on the live fixture**. Movement between storage locations, partial withdrawals, and shrink are not recordable |
| 19 | Total Farm Sales Record | `SalesRecord.sale_date/buyer_name/quantity/quantity_unit/invoice_number/destination`; `History.sold_to/sale_date/quantity_sold` | Total receipts $, expenses, net. **These are almost certainly out of regulatory scope** — § 205.103 wants volume reconciliation, not a P&L. Against Baseline B this row is effectively MET; against Baseline A it is PARTIAL. Record the distinction rather than picking the flattering one |
| 22 | Clean Transport Affidavit | `History.transport_method/transport_vehicle_id/transport_affidavit_on_file/transport_affidavit_document` (FileField); `SalesRecord.carrier_name/vehicle_id/clean_transport_method/bill_of_lading` | The affidavit's **content** is not modeled — transport type, arranged-by, **what was carried prior to organic**, inspection findings, cleaning method. Trazo stores the document but cannot query it. The `LandownerAffidavit` pattern is the obvious template and is not reused here |
| 23 | Buffer Crop Disposition | `ProductionEvent.buffer_disposition`; `Parcel.buffer_zones` JSON | **Quantity** of buffer crop, sales/revenue if sold as conventional, documentation-location pointer, marking method, map reference. The form warns commercial quantities need formal proof the crop was never represented as organic — Trazo records the disposition word, not the proof |
| 24 | Sample Neighbor Notification Letter | `buffer_zones[].neighbor_notified`, `neighbor_notification_date` | The **letter itself**. The fact of notification is recorded; no outbound artifact is generated or stored |
| 25 | Adjoining Land Use Verification | `buffer_zones[].adjoining_land_use`, `adjacent_is_organic`, `prohibited_use_last_date`; `Parcel.treated_lumber_present`/`treated_lumber_description` matches the form's treated-wood checkbox | **Neighbor's countersignature.** `LandownerAffidavit` covers the prior *manager*; nothing covers the *neighbor*. Also missing: distance-in-feet, materials checklist as structured data |

### GAP (3)

| # | Form | Why |
|---|---|---|
| 10 | Seed Records Part A: Suppliers | `ProductionEvent.seed_supplier_name` is a per-event free-text string. The form is a persistent supplier reference list whose **Abbreviation** column exists purely as a join key into Part B. A string per event cannot be referenced, deduplicated, or contacted again next season. Structural: needs a supplier entity |
| 13 | Seed-saving and Planting-stock Propagation | No fields for saved-seed harvest date, propagation location, or seed storage location. **Likely `N/A-scope`** — tree nuts and orchard crops are propagated from nursery stock, not saved seed. Left as GAP pending an explicit ICP scope call rather than assumed away |

### N/A-scope (3)

| # | Form | Basis |
|---|---|---|
| 15 | Farmers Market Load List / Farm Stand Sales | Direct-market. ICP is wholesale tree nut and orchard |
| 16 | Harvest Plan and Record "Pick List" | Direct-market, market-garden shaped (crops × market stalls) |
| 17 | CSA Weekly Harvest and Cost Summary | CSA share economics |

Excluding these moves the denominator from 25 to 22. **That raises the score, so the basis is stated
here in full and the excluded forms are named** — the same discipline `MANIFEST.md` applies to the
livestock PDFs. If Trazo ever targets a direct-market segment, all three return to scope.

---

## The P1 audit-trail hypothesis — resolved

P1 predicted the harvest → storage → sales block would be the thinnest coverage. **P3 killed that
hypothesis.** Forms 14, 19 and 20's regulatory purpose are all served, forms 15–17 are scope-excluded,
and the packet carries a dedicated `Mass-Balance Audit Summary` with output reconciliation, itemized
sales, and per-shipment transport. The audit trail is the *best*-covered block in the set, not the
worst.

What survives is narrow and specific: no dated in/out storage ledger (#20), and input-side
reconciliation that silently degrades when `quantity_purchased` is left blank.

Second-order note: `SalesRecord.bill_of_lading` is a `CharField` — a reference number, not the
document. Nine forms name attachments (bills of lading, organic certificates, delivery/receiving
tags, invoices, dated photographs, farm maps). Trazo has FileFields in some places
(`transport_affidavit_document`, `signed_document`, `cert_document`, `supporting_document`) but the
sales/transport path stores pointers to paper that lives elsewhere. Whether that satisfies a
certifier is a question for the certifier, and a good thing to ask one before building.

---

## Ranked for P5

1. **Sales-documentation snapshot row reads the wrong source** — `audit_export_service.py:2283`
   branches on `History.sold_to` with no `SalesRecord` fallback, so a production with a complete
   sales record prints `REVIEW — Add buyer + organic-on-invoice flag` on page 1 while page 12 of the
   *same PDF* prints `Sold To: Smoke Buyer Co / Organic Identified on Invoice: Yes`. Confirmed on a
   rendered packet. See `usda-crop-forms-p3-live-proof.md`
2. **Organic label category** (Baseline B(b)(3)) — confirmed GAP, not a pending question. A boolean
   cannot express "100 percent organic" vs "organic" vs "made with organic", and `LabelImage.label_type`
   is a different axis (packaging format). Cheap to fix, and directly § 205.303
3. **Neighbor countersignature** (#25) + **transport affidavit fields** (#22) — reuse the
   `LandownerAffidavit` pattern twice; one pattern, two forms
4. **Seed supplier entity** (#10) unlocking Part B's join (#11)
5. **Small field additions** — manufacturer + all application dates on `ParcelCropHistory` (#1);
   purpose-for-use on fertilizer (#7); compost unit ID and reading method (#8); estimated-vs-actual
   harvest date and application method on manure (#9); allowed-status for seed treatments (#12);
   buffer crop quantity and disposition proof (#23)
6. **`retention_until` leap-day bug** — one line

---

## P3 must verify (desk verdicts that could not be settled from schema alone)

- `seed_search_attempts` JSON shape — the form/quality/quantity axes and the a/b/c allowed-status
  triple (#11)
- Whether `LandownerAffidavit`'s rendered output prints the `Parcel.apn` / `section_township_range`
  regulatory description (#2)
- Every `MET` above, on the real fixture packet — render it and read the cell, per
  `frontend-typecheck-gate-dead` and the pricing-restructure live-page lesson

**Settled during P2's own review, no longer open:** `compost_temperature_log` is a `TextField` (not
structured rows) and `LabelImage.label_type` is packaging format (`nonretail`/`retail`/`unpackaged`),
not a § 205.303 label category. Both were written as P3 questions in the first draft; introspecting
the field types answered them and moved (b)(3) from PARTIAL to GAP.
