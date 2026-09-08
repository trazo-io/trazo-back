# P4 — Buyer-Surface Labeling Audit

**Authority:** 7 CFR §§ 205.300, .303, .307, .310, .311 (from
`cfr/title-7-part-205_2026-08-05.txt`) + FTC 16 CFR 260 + EU ECGT 2024/825 (live **2026-09-27**).
**Not** the recordkeeping page — this is a separate legal instrument from P1–P3 and was audited
independently.

**Method:** real anonymous response bytes, per the standing rule that demo/fallback data is not a
defence on a public endpoint. Two productions fetched unauthenticated from a running dev server, one
per claim branch:

| Fixture | Branch | Bytes |
|---|---|---|
| `8f8a3b82…` Walnut Season 2026 | uncertified / self-reported | 7,382 |
| `7668ade3…` 2025 Chandler Walnut Block 4 (est 148, OID-matched CCOF cert) | certified | 22,070 |

Endpoint: `GET /api/transparency/{public_id}/` → 200 anonymous.

---

## Scope correction: "the buyer page" is not a public page

`trazo-app/src/views/Dashboard/Buyer/index.tsx` is **producer-side and authenticated**
(`/admin/dashboard/farm/:farmId/buyer`). Its own docstring: *"Aggregation only, no new consumer-side
build… The consumer ProductDetail page itself stays exactly as shipped (claim-safe)."*

So the buyer-facing labeling surfaces are:
1. the **public production page** (what the QR resolves to), and
2. the **printed lot tag** — `history/views.py:1563`, a physical nonretail-container label and
   therefore squarely § 205.307.

The lot tag is the surface no previous consumer audit covered, and it is where both high-severity
findings live.

---

## What holds up (verified on the wire, both branches)

- **`organic_claim` gating is exemplary.** Uncertified: `can_display_organic: false`, label
  *"Organic practices (farmer-reported)"*, disclaimer *"Farmer-reported organic practices. Not
  independently verified. Not USDA Certified Organic."* Certified: `can_display_organic: true`,
  *"USDA Certified Organic"*, evidence `{tier: certified, source: USDA Organic Integrity Database,
  scope: production_lot}`. § 205.300(a) and § 205.311 both satisfied.
- **Lot-level gate runs and reports.** `lot_eligibility: {eligible: true, detail: "Certificate valid
  at harvest, crop scope covered, no prohibited inputs on this lot."}`
- **Blockchain withdrawal holds on the wire.** `blockchain_verification: {verified: false,
  transaction_hash: ""}`, `timeline[].blockchain_verified: false`.
- **No `transparency_score` field** in either payload. The ECGT demotion was really done — as far as
  fields go. See F1.
- **§ 205.310 (exempt operations)** — no explicit exempt-operation model exists anywhere in the
  codebase, but the claim gate keys on the *presence of a verified certificate*, so an exempt
  operation falls through to `self_reported` and is never represented as certified. Effectively
  compliant. Recorded as a note, not a defect.

---

## Findings

### F1 · HIGH — the transparency score is withheld as a field but fully derivable

Both payloads publish, under `standard_view.transparency_details`:

```json
{"actual_events": 12, "expected_events": 13, "farming_approach": "organic"}
```

12 ÷ 13 = 92%. The uncertified fixture publishes `{"actual_events": 2, "expected_events": 13}` = 15%.

Beneath it, `category_breakdown` exposes the entire scoring engine per category — `actual_count`,
`expected_count`, `photo_verified_count`, `photo_verification_rate`, `requires_photos`,
`anti_gaming_applied`, and a `photo_tier_summary` split into essential/recommended totals.

ECGT 2024/825 bans **self-created sustainability labels lacking third-party verification**. The
score was removed as a named field, but publishing the numerator, the denominator, and the weighting
inputs publishes the label — any client can reconstruct it, and the per-category breakdown makes the
reconstruction faithful rather than approximate. Removing the field while shipping its complete
basis is a rename, not a demotion.

This is the same defect class as the six prior consumer leaks: the guard was applied to the *name*
of the claim rather than to its *shape*.

**Recommendation:** decide what the consumer surface genuinely needs. Factual evidence counts
("12 practices documented") are the sanctioned framing and do not require `expected_events` to be
present at all. `expected_events` exists only to be a denominator.

### F2 · HIGH — lot tag prints `—` as the lot number

`history/views.py`: `lot = history.lot_id or "—"`, drawn as
`c.drawString(text_x, cursor, f"LOT {lot}"[:30])`. The tag therefore prints, literally:

```
LOT —
```

§ 205.307(a)(2) requires nonretail containers to display *"the production lot number, shipping
identification, or other unique information that links the container to audit trail documentation."*
An em-dash is none of the three. The tag is a physical label on a shipping container; printing a
placeholder produces a **non-compliant nonretail container** with no indication to the producer that
anything is wrong.

**This is not an edge case.** Measured on the live database: **72 of 115 published productions (63%)
have a null or blank `lot_id`**, and 67 of the 110 that have actually finished. The majority of tags
generated today would print `LOT —`.

*(An earlier draft said "3 of the 5 most recent published productions." That was a hand count off a
5-row sample and understated the problem; the figure above is a database-wide count.)*

**Recommendation:** refuse to generate the tag without a lot ID, and say why. A blocked download is
recoverable; a printed non-compliant label on shipped product is not.

### ~~F3 · MEDIUM-HIGH — the QR destination does not echo the lot ID~~ — **RETRACTED**

**This finding was wrong and is withdrawn.** The anonymous payload *does* carry the lot, on both
branches, at `harvestDetails.lot_number`:

| Fixture | `harvestDetails.lot_number` |
|---|---|
| `7668ade3…` certified | `DCG-B4-2025-001` |
| `8f8a3b82…` uncertified | `PCR-26-NB-01` |

§ 205.307(a)(2)'s container→audit-trail linkage resolves correctly: the tag prints the lot, the QR
resolves to a page carrying the same lot, and a buyer can confirm the container in hand matches the
record.

**How the error happened — third occurrence of one method fault.** The original check tested whether
the strings `"lot_id"`, `"lot"`, or `"lotId"` appeared in the JSON. The actual key is `lot_number`.
Searching for the *lot value* (`DCG-B4-2025-001`) found it immediately. This is the same fault that
produced the P2 mass-balance miss (`inventory_balance` vs the real `Mass-Balance Audit Summary`) and
the `LandownerAffidavit` miss: **searching for the identifier I would have chosen instead of the one
that exists.** The standing correction — search for the *value* or the *regulatory concept*, never
only the imagined field name — now has three data points behind it.

### F4 · MEDIUM — the tag silently omits the organic identification when the gate fails

```python
except Exception:
    logger.warning("Lot-tag organic gate failed; omitting organic line", exc_info=True)
```

Failing closed on a claim is the right instinct and matches the claim-authority discipline. But
§ 205.307(a)(1) is a **positive requirement**: nonretail containers used to ship or store certified
organic product *must* display identification of the product as organic. For a genuinely certified
operation, a tag with no organic line is itself non-compliant — and the only signal is a server-side
log line the producer never sees.

**Recommendation:** when the gate declines for a farm holding a verified certificate, surface it in
the response ("organic identification omitted — resolve X before shipping"). Silence is the wrong
output either way: either the claim is safe and should print, or it is not and the producer needs to
know before the pallet moves.

### F5 · MEDIUM — `photo_verified_count` / `photo_verification_rate` misuse "verified" publicly

These keys are on the anonymous payload and describe **farmer-uploaded photographs**. The project's
own rule reserves "verified" for a USDA Organic Integrity Database match; `claim_authority.py`
enforces exactly this for certifier names and input listings, and never returns a bare "Verified".

The photo fields predate that authority and were never routed through it. A photo the farmer
uploaded is *documented*, not verified.

**Recommendation:** rename to `photo_documented_count` / `photo_documentation_rate` on the public
serializer. Interior naming can stay if churn is a concern — the wire is what matters.

### F6 · MEDIUM — `all_inputs_organic: true` / `organic_input_percentage: 100` on an uncertified farm

The self-reported fixture publishes:

```json
{"is_organic_farm": true, "claim_status": "self_reported", "certification_verified": false,
 "total_chemical_inputs": 1, "organic_approved_inputs": 1,
 "all_inputs_organic": true, "organic_input_percentage": 100}
```

The disclaimer is correct and sits in `organic_claim`. But `all_inputs_organic` and
`organic_input_percentage` are in a *different object*, and a boolean/number travels without its
qualifier the moment any client renders one without the other. This is the precise shape of the
2026-07-31 incident where `Boolean('not_organic')` produced *"All Inputs Organic-Approved"*.

The values are computed from `organic_approved`, a farmer-set field, on a farm with
`certification_verified: false`. Under § 205.300(a) and FTC 16 CFR 260.6 the safe form is a count
with its basis attached, not a percentage.

**Recommendation:** either carry the tier inside the same object (`{value: 100, basis:
"farmer-classified", certified: false}`) or drop the percentage and keep the counts.

### F7 · LOW — § 205.307(b) "last certified operation" may be the wrong operation

§ 205.307(b): *"Audit trail documentation for nonretail containers must identify the last certified
operation that handled the agricultural product."* The lot tag prints `establishment.name`.

`History.post_harvest_facility` (FK to `certifications.PostHarvestFacility`) exists, so Trazo already
models the case where a packer handled the product after the farm. When it is set, the last certified
operation is plausibly the facility, not the farm — and the tag would name the wrong one.

Low severity because the ICP ships from the farm, but it needs a deliberate scope call rather than
an accident.

---

## Summary

| # | Severity | Finding | Surface |
|---|---|---|---|
| F1 | HIGH | Transparency score derivable from `actual_events`/`expected_events` + full category breakdown | Public payload |
| F2 | HIGH | Lot tag prints `LOT —` when `lot_id` is null — **63% of published productions** (§ 205.307(a)(2)) | Printed label |
| ~~F3~~ | — | **RETRACTED** — the lot *is* published, at `harvestDetails.lot_number` | — |
| F4 | MED | Organic identification silently omitted from tag on gate failure (§ 205.307(a)(1)) | Printed label |
| F5 | MED | `photo_verified_*` says "verified" of farmer-uploaded photos | Public payload |
| F6 | MED | `all_inputs_organic` / `organic_input_percentage` separated from their tier | Public payload |
| F7 | LOW | Tag may name the farm where § 205.307(b) wants the last certified operation | Printed label |

**Six live findings: 2 HIGH, 3 MEDIUM, 1 LOW.**

**No findings against §§ 205.300, .303, .310, .311** — each checked, not assumed:

- **§ 205.300(a)** — "organic" is used only where the gate permits it; the uncertified branch says
  *"Not USDA Certified Organic"* explicitly.
- **§ 205.303** — governs *packaged retail products* under § 205.301(a)/(b). Trazo's product is raw
  single-ingredient produce, so (b)(1)'s ingredient-statement rules do not apply. (a)(5) *permits*
  the certifying agent's seal or logo provided it is no more prominent than the USDA seal; the
  project standard is stricter still (USDA seal only, other certifiers text-only), so the permission
  is left unused. Conservative and compliant.
- **§ 205.310** — no exempt-operation model exists in the codebase (verified by a word-boundary grep
  for `exempt`: every hit is unrelated, mostly compost/manure interval exemptions). But the claim
  gate keys on a *verified certificate*, so an exempt operation falls through to `self_reported` and
  is never represented as certified. Effectively compliant by construction rather than by design —
  worth knowing, since the property depends on the gate and not on an explicit rule.
- **§ 205.311** — `showUsdaSeal = Boolean(oidMatchedCert)` (`TrustSummaryHeader.tsx:179`), which
  cites the section directly.

**Pattern worth naming.** Every finding above is on a surface the claim-authority chokepoint does not
cover: the printed lot tag (F2, F3, F4, F7) and payload fields that predate the authority (F1, F5,
F6). `claim_authority.py` works — its blast radius is the problem. The lot tag is a *labeling*
surface under a *different* CFR subpart, and nothing routes it through a gate.

**Recommended structural fix:** extend the authority to answer "may this container be labeled
organic, and with what identification" (§ 205.307), not only "may this page say verified"
(§ 205.311 / FTC / ECGT). One gate, two subparts.

---

## Feeds P5

Ranked into the ship list ahead of the smaller record-field additions — F1 and F2 are both
externally visible, and F1's deadline is **ECGT go-live 2026-09-27**, which lands before the
October target.
