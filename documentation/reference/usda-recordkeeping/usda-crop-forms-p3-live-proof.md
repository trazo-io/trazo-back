# P3 — Live Rendered Proof

**Method.** Generated a real certifier packet and read the paper, rather than reasoning about the
code. `AuditExportService(History.objects.get(id=580), certification_type="organic").generate_pdf()`
→ 46,701 bytes, **15 pages**, extracted with `pdftotext -layout`.

**Fixture.** `History id=580 — "Walnut Season 2026"`, parcel 284, lot `PCR-26-NB-01`, finish
2026-08-08, 1 chemical event, 1 production event, 1 `SalesRecord`. CA walnut — on-ICP.

⚠️ The fixture named in prior notes (`5ba2194a…`, Solana Verde avocado) **does not exist in this
database.** Do not cite it as the canonical fixture without checking first.

---

## 🔴 P3 overturned P2's headline finding

P2 called "no storage mass balance" the highest-value gap in the audit, on the strength of a grep
for `inventory_balance` / `quantity_in` / `quantity_out` / `on_hand` returning nothing.

The rendered packet contains, on page 12:

```
Mass-Balance Audit Summary (§ 205.103(b)(2) / § 205.2)
  Harvest Yield:                          5,200 lb (2.6 short tons)
  Quantity Sold:                          1,200 lb
  Sales Records on File (§ 205.307(a)):   1
  Organic Identified on Invoice:          Yes
  Balance (Yield − Sold, same unit):      4,000 lb (2.0 short tons)
```

plus `Itemized Sales Records (7 CFR 205.307(a))` and `Per-Shipment Transport (7 CFR 205.272 /
205.103(b)(2))` tables carrying BOL #, carrier, vehicle, destination, and clean-transport method.

It also catches integrity errors the crosswalk never asked for:

> `[REVIEW] 7 CFR 205.103(b)(2): 1 sale(s) are dated BEFORE the harvest date (2026-08-09) — product
> cannot be sold before it is harvested. Correct the sale dates.`

**Form #20 re-scored GAP → PARTIAL. Baseline B(b)(2)'s reasoning rewritten.** The audit trail turns
out to be the best-covered block in the set, not the worst — the exact opposite of the P1 hypothesis.

**Method lesson, second occurrence.** P2 also under-called `LandownerAffidavit` the same way. Both
misses came from grepping for the name *I* would have given the feature instead of the name it has.
`inventory_balance` → the feature is called **Mass-Balance / Output Reconciliation**. Grep the
regulatory concept and the CFR cite (`205.103(b)(2)`), not the imagined identifier — and when the
question is "does the artifact show X," render the artifact.

---

## 🐛 Confirmed defect: the packet contradicts itself on sales documentation

**Page 1, compliance snapshot:**
```
Sales documentation (§ 205.103)        REVIEW      Add buyer + organic-on-invoice flag
```
**Page 12, same PDF:**
```
Sold To: Smoke Buyer Co
Sale Date: 2026-08-01
Organic Identified on Invoice: Yes
```

**Root cause.** `history/services/audit_export_service.py:2283`:

```python
# Sales record
if p.sold_to:
    snapshot_rows.append(("Sales documentation (§ 205.103)", "PASS", f"Sold to: …"))
else:
    snapshot_rows.append(("Sales documentation (§ 205.103)", "REVIEW", "Add buyer + organic-on-invoice flag"))
```

The snapshot branches on `History.sold_to` only. The packet body does it correctly — the comment at
`audit_export_service.py:7642-7644` states the rule explicitly: *"dedicated SalesRecord rows exist,
aggregate them for the output side and [use the History] fields only when no SalesRecord rows are on
file."* The snapshot never got that fallback.

On the fixture: `History.sold_to = None`, `History.organic_on_invoice = False`, while
`SalesRecord(buyer_name="Smoke Buyer Co", organic_on_invoice=True, invoice_number="INV-SMOKE-1",
bill_of_lading="BOL-SMOKE-9")` exists.

**Why it matters beyond cosmetics.** The compliance snapshot is page 1 — the summary a certifier
reads first. It under-reports the operation's own compliance, and it disagrees with page 12 of the
document it is summarizing. A certifier who spots the contradiction has reason to distrust every
other row on that page.

**Fix.** Give the snapshot the same `SalesRecord`-first / `History`-fallback precedence the body
already uses. Not applied here — P3 is a verification phase, and editing the service would
invalidate the artifact this document cites. It is item 1 on the P5 ship list.

**Third occurrence of one root cause.** `osp-parity-qa-2026-08-09` named "two writers, disjoint key
vocabularies → silent data loss" as a recurring failure. This is the same shape, now in the
certifier packet. Worth a targeted sweep for other readers of `History.sold_to` /
`History.organic_on_invoice` that predate `SalesRecord`.

---

## Verified on paper

| Claim | Evidence in `packet_580.txt` | Verdict |
|---|---|---|
| 16 snapshot check rows (not the 14 my P2 regex extracted) | `compliance_snapshot_rows()` returned 16 | ✅ `record_completeness.py`'s docstring was right; **my extraction was the wrong number**. Two rows are built differently and my literal-match regex missed them: `Raw manure interval (§ 205.203(c)(1)(iii))` and `Lot traceability (§ 205.307 / § 205.103(b)(2))` |
| Form #7 Input Material Application — MET | `Input Purchase Traceability (7 CFR 205.103)` table with Date · Product · Supplier · Purchase · Invoice # · Lot # · Qty · Applicator · Cert # · CA DPR Permit | ✅ **MET holds.** Exceeds the USDA form |
| Form #21 Equipment Cleaning — MET | `Equipment Cleaning Logs (7 CFR 205.272)` section present | ✅ MET holds |
| Form #14 Harvest Record — MET | `Harvest Records` + `Production Summary` sections; yield renders as 5,200 lb | ✅ MET holds |
| § 205.103(b)(4) retention off-by-one | `finish_date` 2026-08-08 → `retention_until` **2031-08-07**; delta **1825 days**, five calendar years is 1826 | ✅ **Bug confirmed on live data**, not just arithmetic |
| Form #11 `seed_search_attempts` shape | Real rows are `[{supplier_name, date_contacted, result, notes}]` | ✅ **PARTIAL holds, and sharpens.** The three statutory nonavailability axes (form / quality / quantity) are **not** structured — `result` is free text ("Available — certified organic Hass rootstock in stock"). The a/b/c allowed-status triple is absent entirely |
| Form #10 supplier entity — GAP | `supplier_name` is a string inside each attempt dict; no supplier table | ✅ GAP holds |
| `Input traceability (§ 205.103)` fires on empty data | Page 1: `GAP — 0/1 inputs have supplier — fill before audit` | ✅ The check works; the fixture data is thin. Schema MET, data incomplete — distinct problems |

**Status label mapping note:** `compliance_snapshot_rows()` returns `PASS`/`REVIEW`/`FAIL`; the PDF
renders these as `DOCUMENTED`/`REVIEW`/`GAP`. Not a defect — but anyone diffing code against paper
needs to know the words change.

---

## New findings P2 could not have seen

### 1. The OSP narrative asserts storage recordkeeping the record layer cannot evidence

Packet page 5–6, from the OSP modules:

- *"Lot identification in use: Yes — Trazo lot IDs (printed on lot tags and carried on harvest,
  **storage**, and sales records)."*
- *"Lot identity maintained through storage (bin cards, pallet tags): **Yes**."*
- *"harvests carry quantity, determination method, and destination; **storage carries lot identity**."*

Meanwhile `ProductionEvent.storage_location` is **empty on this production**, and there is no storage
record type at all. The narrative describes a practice; nothing in the record layer substantiates it.

This is a claim-shape problem, not merely a missing feature: the OSP is a **producer attestation**
under § 205.201(a), and the packet places an unevidenced storage-records claim next to a
mass-balance section that never mentions storage. If a certifier asks "show me the bin cards," there
is nothing to render. Route this through the same discipline as any other claim surface — the
narrative should describe what the records can show.

### 2. Vacuous PASS rows

Five of sixteen rows pass on absence: `Compost — No compost events to validate`, `Raw manure
interval — No raw manure events`, `IPM strategy — No pest events`, `Pest threshold rationale — No
pest events with action threshold met`, `Contamination prevention — No equipment shared`.

Each is individually correct and honest — the detail text says plainly why. But a packet reading
`DOCUMENTED ✓` five times for things that never happened invites a skim-reader to over-count
compliance. `Documentation depth — REVIEW: 2 events, 0 photos` is the counterweight and it works.
Worth considering a distinct visual treatment for "not applicable this season" versus "checked and
clean" — a presentation question for P5, not a correctness bug.

### 3. `LandownerAffidavit` exists but is unexercised

One row in the entire database, with `yearly_history = []` and `field_name = None`. The model that
made form #2 look strong in P2 is, in practice, empty. **P2's #2 verdict of PARTIAL stands on schema
grounds, but the flow that populates it needs its own check** — a model nothing writes to is not
coverage. Added to P5.

---

## Net effect on the score

| | P2 as written | After P3 |
|---|---|---|
| MET | 6 | 6 |
| PARTIAL | 13 | **14** (#20 promoted from GAP) |
| GAP | 3 | **2** (10, 13) |
| N/A-scope | 3 | 3 |
| **MET or PARTIAL** | 86% | **91%** (20/22) |

Fully-MET is unchanged at **27% (6/22)**, and that remains the number the Sep 15 gate must be
restated against. P3 improved the picture by removing a false gap, not by moving anything to MET.

### Known PDF/CSV structural divergence (recorded 2026-08-11)

The PDF's `Input Application Log` carries a `Target / Purpose` column; the CSV's event rows are a
generic flat format (date · category · subtype · description · product · amount · unit) with no
chemical-specific columns, so neither `target_pest_disease` nor `application_purpose` appears
there. This predates the 2026-08 work — it is a difference in export SHAPE, not a field someone
forgot to add — but it means the two exports of one production answer "why was this applied?"
differently. Worth closing when the CSV event schema is next revisited.
