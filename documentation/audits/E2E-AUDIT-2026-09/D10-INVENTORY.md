# D10 — Inventory model (rev. 2)

Status: ✅ **SIGNED 2026-09-08 (Oscar) — and DELIBERATELY NOT BUILT.**

⛔ **Signing is not a build order.** Trazo has zero users, pre-revenue, and the outreach window
opens in six days. Building the purchase/inventory/evidence spine now would be architecture for a
scale that does not exist — the same mistake this document's own §0 corrections came from. What the
signature buys is that the reasoning, and the four corrections forced into rev. 2, survive until a
pilot farm actually closes a season and a mass balance has to reconcile.

**Build trigger:** the first pilot lot where harvest, sales and a handler have to agree.
**Then, and only then:** `history/services/inventory_model.py` as pure functions over dataclasses,
with every number in §8 reproduced in `Decimal` by `test_inventory_model_examples.py`, before any
migration is written.

Rev. 1 was rejected on three points, all addressed here:

| Objection | Where |
|---|---|
| Processing must be a **batch with input/output quantities and product condition**, not a unit-change trigger | §3 `processing_batch` |
| The walnut example must assert closing inventory at **both** locations, including the wet input | §8 example 2 |
| A missing conversion or an over-allocation ⇒ status **"not reconciled"**, never a warning beside a definitive balance | §5 |

## 0. Two corrections to rev. 1 — it assumed fields that do not exist

Rev. 1 was written from the audit's prose. Checked against the code on 2026-09-08:

- ⛔ **`is_summary`, `yield_total` and `yield_total_unit` are NOT columns.** They are
  `extra_data` JSON keys, lifted by `UpdateProductionEventSerializer`, under a comment that
  says so outright: *"Extract summary-only fields (NOT model fields) sent at top level"*
  (`history/serializers.py:2169-2179`). So the summary/individual double-count rule reads JSON,
  where a mistyped key is indistinguishable from an absent one. Rev. 1 treated them as columns.
- ⛔ **`box_weight_lb` is on `History` (the season), not on the harvest event** — nullable, and
  `audit_export_service` already falls back to `CROP_DEFAULT_BOX_WEIGHTS` when it is null
  (`history/models.py:364-373`). Rev. 1 assumed a per-record factor and assumed absence meant
  "not reconciled". A **documented** factor and an **industry default** are different evidence
  and §5 now separates them.

Everything else below names a field that exists today, or says explicitly that it needs one.

## 1. Boundary

Inventory of one **crop-season lot** that the operation **owns**, tracked at two locations:
`on_farm` and `at_handler`.

- Ownership ends at a sale/shipment or an out-disposition.
- Buyer-side stock and handler-**owned** stock are out of scope. Stock at a handler that the
  operation still owns is `at_handler`, not out of scope — that distinction is the whole reason
  two locations exist.
- A season opens at **zero**. Carried-over stock enters as an explicit `opening_transfer`
  movement naming its source lot, never as an implicit starting balance.

## 2. What exists today

| Fact | Field | Type |
|---|---|---|
| Harvest yield | `ProductionEvent.yield_quantity` / `yield_unit` | Decimal / Char |
| Sent to handler | `quantity_sent_to_handler`, `handler_quantity_unit`, `sent_to_handler_date` | Decimal / Char / Date |
| Returned from handler | `quantity_returned_from_handler`, `handler_return_unit` | Decimal / Char |
| Handler paperwork | `handler_document_reference` | Char |
| Sale | `SalesRecord.quantity` / `quantity_unit` | Decimal / Char |
| Sale ↔ harvest link | `SalesRecord.harvest_events` | plain M2M, **no through model, no per-pick quantity** |
| Void | `voided_at`, `void_reason`, `voided_by` | shipped 0234 |
| Box factor | `History.box_weight_lb` | Decimal, nullable, season-level |
| Summary harvest | `extra_data.is_summary` / `yield_total` / `yield_total_unit` | **JSON**, not columns |
| Buffer / purge quantity | `buffer_disposition_quantity`, `purge_quantity` | ⚠️ **CharField — free text** |

**Needs schema (B2, after signature):** a through model carrying per-pick quantity;
`HarvestDisposition`; `InventoryCount`; `SalesRecord.ship_from`; and the processing batch of §3.
Handler movements are **derived from the existing columns above** — no new handler columns.

## 3. Movements

A movement is `(kind, location(s), quantity, unit, date, source_record)`. Quantities are read
**live** from their source record, so a correction to the record corrects the movement; there is
no second copy to drift.

| Kind | Effect | Source |
|---|---|---|
| `harvest_in` | → `on_farm` | HA `yield_quantity` |
| `opening_transfer` | → `on_farm` | carried-over stock, names its source lot |
| `transfer_to_handler` | `on_farm` → `at_handler` | `quantity_sent_to_handler` |
| `handler_return` | `at_handler` → `on_farm` | `quantity_returned_from_handler`, in `handler_return_unit` |
| `processing_batch` | consumes at `at_handler`, produces at `at_handler` | §3.1 |
| `sale_shipment` | `on_farm` **or** `at_handler` → outside | live `SalesRecord.quantity` + new `ship_from` |
| `out_disposition` | → outside | `HarvestDisposition`: loss / cull / donation / feed / seed / sample / other |

### 3.1 `processing_batch` — a batch, not a unit change

**Rejected in rev. 1:** treating a differing handler unit as a signal to "convert". That made
the model infer processing from a unit mismatch, so a data-entry slip became a physical event.

A processing batch is its own record, and it is the handler's report, not our inference:

```
processing_batch:
  input_quantity, input_unit, input_condition      # 50,000 lb, "wet in-shell, field run"
  output_quantity, output_unit, output_condition    # 22,000 lb, "dry in-shell"
  byproduct_quantity, byproduct_unit, byproduct_kind   # optional: hulls, shells, culls
  documented_loss_quantity, documented_loss_unit       # optional: only if the handler reports it
  document_reference                                # the handler's settlement sheet
```

Rules:

1. **The input is consumed and the output is created.** Both are movements at `at_handler`.
   Closing inventory there reflects the output, and the input is *gone* — not silently retitled.
2. `input_quantity − output_quantity − byproduct − documented_loss` is the **unexplained
   remainder**. It is reported as such, in the input's unit. ⛔ It is **never** booked as loss.
   Drying weight-loss and a handler losing your nuts look identical in arithmetic and are not
   the same fact.
3. **Condition is required on both sides** and printed verbatim. "50,000 lb → 22,000 lb" is
   nonsense without "wet → dry", and a reader who cannot see the condition will read a 56%
   shrink as theft.
4. Outturn % is a **printed ratio** (`output / input`), never a stored conversion factor. It
   describes one batch and must not be reused to convert anything else.
5. ⛔ **A batch is never inferred.** No batch record ⇒ no batch. If in and out units differ with
   no batch on file, the lot is **not reconciled** (§5), which is the honest state: something
   physically happened that nobody wrote down.

## 4. Counts and the equation

A count is a dated snapshot, not a movement: `inventory_count(location, date, quantity, unit)`.

Per location:

```
computed_closing = 0 + Σ inflows − Σ outflows
variance         = computed_closing − latest_count      # only when a count exists
```

A count only settles the lot if it is dated **on or after the last movement**; an earlier count
is printed as historical, not as the closing figure.

## 5. Reconciliation is a STATUS, not a warning beside a number

**This is the rev. 1 rejection.** Printing a definitive balance with a caution next to it means
the number gets read and the caution does not. Every lot-location carries exactly one status,
and an unreconciled lot **does not print a closing figure at all**:

| Status | When | What prints |
|---|---|---|
| `reconciled` | count on/after last movement, variance = 0 | closing quantity + "counted" |
| `variance` | count present, variance ≠ 0 | both figures **and** the difference |
| `not_counted` | no count | "computed on hand — not counted" + computed figure |
| **`not_reconciled`** | a term could not be evaluated | ⛔ **no closing figure** — the unusable terms, named |

`not_reconciled` is entered by, and only by:

- units in different families with no documented factor and no processing batch;
- an over-allocation (Σ allocations > the pick's yield, or > the sale's quantity);
- a summary harvest record **and** individual records in the same lot (§6);
- a differing in/out unit at the handler with no `processing_batch` on file.

**A documented factor and an industry default are different evidence.** `History.box_weight_lb`
set by the operator is a documented factor: converting with it yields `reconciled`.
`CROP_DEFAULT_BOX_WEIGHTS` is an assumption we supplied: it can never produce `reconciled`,
because our own default must not substantiate someone else's mass balance. Rev. 1 collapsed the two.

⚠️ **AMENDED at signature.** Rev. 2 first specified a bare `not_reconciled` here, which is
needlessly bleak: this is the one unreconciled cause with a ten-second fix. The status stays
`not_reconciled`, but the line must NAME THE REMEDY — *"harvest in boxes, sales in lb — enter this
season's carton weight to reconcile"* — rather than only stating the refusal. Same strictness, and
it turns a dead end into one field.

## 6. Summary vs individual harvest — mutually exclusive inputs

A summary HA record (`extra_data.is_summary` with `yield_total`) and individual HA records in the
same lot are mutually exclusive.

- Both present ⇒ use the **individual** records, set `not_reconciled`, and print *"a summary
  harvest record is also on file for this lot — reconcile before filing"*. ⛔ Never sum both.
- ⚠️ Because these are JSON keys, a mistyped `is_summary` is invisible: the record silently
  becomes an ordinary HA with no yield. The model must therefore also flag an HA record with a
  `yield_total` key but no `is_summary` as `not_reconciled`, rather than ignoring it.

## 7. Voids, corrections, allocations, units

- **Voided sales are not movements.** They are excluded from every term and listed separately.
- **Amendments change live values**, so a corrected quantity flows through with no recomputation
  step to forget.
- **An allocation is an attribution, not a movement.** It ties part of a sale to a specific pick.
  Σ allocations per pick ≤ that pick's yield; Σ allocations per sale ≤ that sale's quantity;
  either breach ⇒ `not_reconciled`. A sale's unallocated remainder is printed as unallocated —
  which is a legitimate state, not an error.
- **Migrated rows:** the existing M2M rows become allocations with `quantity = NULL`, meaning
  "linked, unallocated". ⛔ NULL must never be read as zero.
- **Units:** arithmetic only within one unit family after `_canonical_unit`. ⚠️ `lb` vs `lbs`
  disagree between two existing helpers — the model normalises once, at the edge.
- ⚠️ `buffer_disposition_quantity` and `purge_quantity` are **CharFields**. They are printed
  verbatim as narrative and are **excluded from arithmetic**. Making them dispositions means
  typed columns, which is a B2 decision, not this one.

## 8. Worked examples — the expected outputs a test must reproduce first

### 1 · Blueberries, River Block (no handler, no counts)

HA records Σ **114,240 lb**; sales 89,562 + 21,140 lb from `on_farm`; no counts, no dispositions.

```
on_farm: computed 3,538 lb · status not_counted
         "computed on hand 3,538 lb — not counted or explained"
```

Operator then adds a cull disposition of 2,900 lb ("soft fruit, dumped") and a count of 600 lb
dated after the last sale:

```
on_farm: computed 638 lb · count 600 lb · variance 38 lb · status variance
```

Allocations: fresh sale 60,000 → pick A (yield 60,000) and 29,562 → pick B (yield 54,240);
processing sale 21,140 → pick B. Pick B attributed 50,702 of 54,240 ⇒ within yield, no breach.

### 2 · Walnuts through a huller — **both locations, and the wet input**

HA **50,000 lb** field run; `transfer_to_handler` 50,000 lb; handler reports a batch:
in 50,000 lb wet in-shell → out 22,000 lb dry in-shell, hulls 26,500 lb byproduct, no reported
loss. `handler_return` 22,000 lb dry. Sale 21,500 lb from `on_farm`. Count 500 lb.

```
at_handler:
  in   transfer_to_handler   50,000 lb  (wet in-shell, field run)
  out  processing_batch input 50,000 lb consumed
  in   processing_batch output 22,000 lb (dry in-shell)
       byproduct 26,500 lb (hulls)
       unexplained remainder 1,500 lb  ← NOT booked as loss
       outturn 44.0% (22,000 / 50,000)
  out  handler_return       22,000 lb
  computed closing at_handler: 0 lb · status not_counted

on_farm:
  in   handler_return  22,000 lb
  out  sale_shipment   21,500 lb
  computed 500 lb · count 500 lb · variance 0 · status reconciled
```

⚠️ Rev. 1 printed only `on_farm 22,000` and never showed the 50,000 lb wet input leaving. The
1,500 lb remainder is the number a grower would want to ask their huller about, and rev. 1 made
it disappear into a unit conversion.

### 3 · Summary and individual records in one lot

Summary `yield_total` 10,000 lb, plus HA records 4,800 + 5,100 lb.

```
uses individual records: 9,900 lb
status not_reconciled — "a summary harvest record is also on file for this lot"
no closing figure printed
```

Rev. 1 printed a 0 lb balance with a warning. That is the shape this decision rejects.

### 4 · Boxes against pounds — three distinct cases

HA 1,200 boxes; sale 30,000 lb.

```
a) History.box_weight_lb = 25 (operator-entered)
   "1,200 boxes × 25 lb = 30,000 lb (operation's documented carton weight)"
   computed 0 lb · status reconciled

b) box_weight_lb NULL, CROP_DEFAULT_BOX_WEIGHTS supplies 25
   "1,200 boxes × 25 lb = 30,000 lb (assumed carton weight, not the operation's own figure)"
   status not_reconciled, no closing figure
   "harvest in boxes, sales in lb — enter this season's carton weight to reconcile"

c) box_weight_lb NULL and no crop default
   status not_reconciled — "harvest in boxes, sales in lb, no documented factor"
   no closing figure printed
```

Case (b) is new in rev. 2 and is the one that matters: our own default must never let a mass
balance read as substantiated.

## 9. Signature record — 2026-09-08

All four questions answered by Oscar; one amended.

| # | Question | Decision |
|---|---|---|
| 1 | §3.1 batch shape; an unexplained remainder is never loss | ✅ signed as drafted |
| 2 | §5 four statuses; `not_reconciled` prints no closing figure | ✅ signed as drafted |
| 3 | Case 4(b) — an industry default can never yield `reconciled` | ✅ signed, **wording amended** to name the one-field remedy (§5) |
| 4 | §7 `buffer_disposition_quantity` / `purge_quantity` | ✅ stay NARRATIVE, excluded from arithmetic. Typing them is a data migration over free text nobody has validated |

**Accepted costs, recorded so nobody relitigates them later:**
- §5 will leave some lots with **no closing figure at all**. That reads as the product failing rather
  than the record being incomplete. Taken deliberately: a definitive number with a caution beside it
  gets read as definitive, which is the defect shape behind every claim failure found in this audit.
- Case 4(b) will mark currently-clean lots unreconciled wherever the operation has never entered its
  own carton weight. Mitigated by the amendment above, not by relaxing the rule.

**Not built. See the status note at the top for the build trigger.**
