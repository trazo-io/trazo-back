# P5 — Ship List: USDA Alignment, October 2026

Consolidates P1–P4. Every item traces to a CFR citation or a rendered artifact; nothing here is
"would be nice."

**Sources:** `usda-crop-forms-inventory.md` (P1) · `usda-crop-forms-crosswalk.md` (P2) ·
`usda-crop-forms-p3-live-proof.md` (P3) · `usda-buyer-surface-p4-labeling.md` (P4). Corpus and the
two standing caveats: `MANIFEST.md`.

---

## Status board — verified 2026-08-11, not asserted

Each ✅ was confirmed against code or a rendered artifact on the date shown, not from memory.

| # | Item | Status |
|---|---|---|
| 1 | Stop publishing the score's basis (ECGT) | ✅ shipped — `expected_events` + machinery dropped, shape gate added |
| 2 | Lot tag must not print `LOT —` | ✅ shipped — HTTP 400 `lot_id_required` |
| 3 | Sales snapshot reads the wrong source | ✅ shipped — `resolve_sales_disclosure()`, 5 read sites |
| 4 | Organic label category | ✅ shipped — migration 0195. **⚠️ CORRECTED 2026-08-13: this was marked shipped while having NO frontend writer at all.** Model + serializer + packet existed; zero occurrences in `trazo-app/src`, so the packet printed a § 205.301 row no grower could answer. Select added to `SalesRecordsSection`, disabled until organic-on-invoice is ticked (mirrors `SalesRecord.clean()`) |
| 5 | OSP asserts storage records | ⏸️ **blocked on certifier Q1** — severity downgraded to product gap |
| 5b | OSP claim-vs-evidence sweep | ✅ shipped — `osp_evidence_map.py` + standing gate |
| 6 | `retention_until` off-by-1–2 days | ✅ shipped — `compute_retention_until()` |
| 7 | Lot tag drops organic line silently | ✅ shipped — `X-Trazo-Label-Warning` |
| 8 | Storage in/out ledger | ⏸️ **blocked on certifier Q1** |
| 9 | Input-side mass balance | ✅ shipped — conditional `quantity_purchased` |
| 10 | `photo_verified_*` misuses "verified" | ✅ shipped — renamed to `photo_documented_*` on the anon payload; 0 occurrences on the wire |
| 11 | `all_inputs_organic` split from its tier | ✅ shipped — `organic_input_basis` + `organic_input_evidence` ship in the same object |
| 12 | Claim authority → container labeling | ✅ shipped — `may_label_container()` |
| 13 | `LandownerAffidavit` unexercised | ❌ **open** — 2 rows, 0 with populated `yearly_history` |
| Tier 3 | 10 small field additions | ✅ **10 of 10 COMPLETE** — #22 clean transport + #25 adjoining land · #1 field history + #2 land use verification · #8 compost batch identity · #7 input purpose · #12 seed-treatment allowability (2026-08-11) · #11 seed nonavailability ground · #23 buffer crop disposition · **#9 manure COMPLETE** (2026-08-12) |

**11 shipped · 2 blocked on the certifier (5, 8) · 1 still OPEN (13) · Tier 3 COMPLETE (10 of 10).**

⚠️ The previous wording — "11 of 13 shipped · 2 blocked" — accounted for 13 of the 14 rows and
quietly dropped item 13. A status board that does not add up is worse than no status board.

Every live claim-safety finding from P4 is now closed. What remains is item 5 and item 8 — both
waiting on the certifier's answer to Q1, and both the wrong thing to guess at — plus Tier 3's ten
field additions, which are PARTIAL rows where the spine already exists.

**Item 11 turned out sharper than P4 recorded it.** The finding was written as "the percentage
travels without its disclaimer". The real defect was that `ORGANIC_APPROVED_OK_VALUES` includes
`omri_listed` — the grower's *dropdown pick*, not a catalog match — so the aggregate counted a
self-report identically to a verified OMRI row. `may_claim_input_listing()` already tiers exactly
this per input, after the 2026-08-09 leak where an anonymous payload said "OMRI Listed" for an
input with no OMRI record. That fix landed on the per-input chip and never on the aggregate: the
**seventh** instance of "fixed on the audited surface, alive on its sibling".

---

## Where the audit actually landed

| Measure | Result |
|---|---|
| USDA crop forms in scope | 22 of 25 (3 direct-market forms excluded, named) |
| Fully MET | **6 (27%)** |
| MET or PARTIAL | **20 (91%)** |
| Structural GAP | 2 — seed supplier entity (#10), seed-saving records (#13, likely N/A for orchards) |
| Baseline B (§ 205.103 as amended) | 3 MET, 3 PARTIAL, 1 GAP |
| Buyer-surface labeling findings | 6 live (2 HIGH, 3 MED, 1 LOW), 1 retracted |

**The honest headline:** Trazo's recordkeeping is substantially aligned — the audit trail, input
applications, compost/manure, equipment cleaning and certifier access are all genuinely covered, and
in several places exceed the USDA form. What is *not* true is "100% aligned," and the gap between
27% fully-MET and 91% at-least-partial is where the October work is.

### ⚠️ The Sep 15 gate must be restated before it can be passed

It was written as "≥90% MET." Read literally we are at 27%. Read as MET-or-PARTIAL we are at 91%.
Those are different claims and picking the flattering one after seeing the numbers is exactly the
move this audit exists to prevent.

**Recommended restatement:** *≥90% of in-scope forms at MET, where PARTIAL counts as MET only when
every missing column is documented as outside regulatory scope.* Under that definition, ~8 of the 14
PARTIALs (those missing only price, expense, or direct-market columns) would qualify today, putting
the real figure near **64%** — and making the remaining work legible instead of hidden behind a
percentage.

---

---

## False-gap sweep (run 2026-08-10, before scoping any build)

**Why.** Three verdicts in this audit were false gaps caused by one method fault — searching for the
identifier I would have chosen rather than the one that exists (`inventory_balance` vs the real
`Mass-Balance Audit Summary`; a missed `LandownerAffidavit`; `"lot_id"` vs `harvestDetails.lot_number`).
One of them was the headline finding. Since the ship list is built on verdicts produced by that
method, every remaining GAP and PARTIAL was re-tested by searching for **values, CFR cites, and
regulatory concepts** instead of field names.

**Result: all 16 remaining verdicts hold. Zero further false gaps.** The ship list is sound.

Confirmed by concept-search, not by field name:

| Item | Searched for | Outcome |
|---|---|---|
| B(b)(3) label category | `"100 percent organic"`, `"made with organic"`, `label_category` | GAP holds — single hit is a docstring |
| #10 seed supplier entity | `class .*Supplier`, `SeedSupplier` | GAP holds — form labels only, no entity |
| #13 seed-saving | `propagat`, `saved seed` | GAP holds — zero relevant hits |
| #5 sale price | `unit_price`, `sale_price` | PARTIAL holds — only carbon-credit `price_per_ton` |
| #20 storage ledger | `bin_card`, `pallet tag`, `shrink` | PARTIAL holds |
| #22 transport affidavit content | `swept`, `air blown`, `prior_product` | PARTIAL holds — prose in seed data only |
| #25 neighbor countersignature | `neighbor_signed`, `adjoining.*affidavit` | PARTIAL holds — zero hits |
| #23 buffer quantity/proof | `buffer_crop_quantity`, disposition values | ✅ **MET 2026-08-12** — quantity + documentation-pointer shipped; packet renders USDA's Buffer Crop Disposition Record |
| #24 letter generation | `notification.letter`, `letter_template` | PARTIAL holds — narrative strings only |
| #1 crop-history manufacturer | `substances_applied` | PARTIAL holds — `product/models.py:385` documents it as "a free-text summary of ALL substances that year" |
| #8 compost unit ID / reading method | `windrow_id`, `probe`, `temperature_method` | PARTIAL holds |
| #9 manure incorporation/type/source | `incorporat`, `manure_type`, `manure_source` | PARTIAL holds |
| #12 seed-treatment allowed status | `inoculant`, `treatment_status` | PARTIAL holds — `seed_treatment` cites § 205.204(a)(2) but carries no allowability basis |
| #11 nonavailability axes | `nonavailab`, `commercial_availability` | PARTIAL holds, **refined** — OSP `g3_0_seeds` section B asks *whether* searches are documented and section C covers excluded methods (GMO), so the a/b/c triple's non-GMO leg is addressed at OSP level. The per-record three-axis structure is still missing |

### The sweep changed two things

**A. Item 4 is cheaper than scoped.** `certifications/osp_modules/g7_0_labeling.py` already exists —
a § 205.303/§ 205.307 labeling module with `product_leaves_as`, `label_states_certifier`,
`label_has_usda_seal`, `invoices_identify_lot`, `container_markings_tie_to_lot`. The label-category
question has a home in section A; it is an addition to a live module, not a new surface.

Note `product_leaves_as` captures product *form* (consumer packaging / bulk bins / unlabeled bulk /
buyer label), cited to § 205.300 — **not** the § 205.303 category. The GAP is real; the fix is small.

**B. A new finding — and it is a pattern, not an instance.** See item 5b below.

Ordering is `externally visible × regulatory exposure × deadline`, not effort.

### Tier 0 — before ECGT go-live, **2026-09-27**

**1 · Stop publishing the transparency score's basis** *(P4 F1, HIGH)*
`standard_view.transparency_details` ships `actual_events` + `expected_events` (12/13 = 92%) plus a
per-category breakdown with photo rates and `anti_gaming_applied`. The score was removed as a field
while its complete computation basis stayed on the wire — a rename, not a demotion. ECGT 2024/825
bans self-created sustainability labels without third-party verification.
→ Drop `expected_events` and the category `expected_count`/`photo_verification_rate` fields from the
anonymous payload. `expected_events` exists only to be a denominator. Keep factual counts.
→ Add a claim-shape test asserting no anonymous payload carries a numerator/denominator pair.

**2 · Lot tags must not print `LOT —`** *(P4 F2, HIGH)*
`history/views.py`: `lot = history.lot_id or "—"`, drawn verbatim. **72 of 115 published productions
(63%) have a null lot_id** — the majority of tags generated today. § 205.307(a)(2) requires a lot
number, shipping ID, or other unique linking information on every nonretail container.
→ Refuse generation without a lot ID and return a reason. A blocked download is recoverable; a
printed non-compliant label on shipped product is not.

### Tier 1 — before certifier renewal packets go out (**CCOF Nov 3 → Jan 1**)

**3 · Sales-documentation snapshot row reads the wrong source** *(P3, confirmed on a rendered packet)*
`audit_export_service.py:2283` branches on `History.sold_to` with no `SalesRecord` fallback. Page 1
of the packet prints `REVIEW — Add buyer + organic-on-invoice flag` while page 12 of the same PDF
prints `Sold To: Smoke Buyer Co / Organic Identified on Invoice: Yes`. The body already has the
correct precedence (`audit_export_service.py:7642-7644`); the snapshot never got it.
→ Apply the same SalesRecord-first / History-fallback rule.
→ **Then sweep** for other readers of `History.sold_to` / `History.organic_on_invoice` — this is the
third occurrence of "two writers, disjoint key vocabularies."

**4 · Organic label category cannot be expressed** — ✅ **SHIPPED 2026-08-11**
`ORGANIC_LABEL_CATEGORY_CHOICES` (the three § 205.301 categories) added to `SalesRecord` and
`History` (migration `0195`), threaded through `resolve_sales_disclosure()` so the PDF and CSV
read one source, and rendered as `Labeling Category (§ 205.301)` in the mass-balance block.

Design notes worth keeping: the field is **operator-set, never inferred** — "100 percent organic"
is the right answer for most raw produce, and guessing it would put a fabricated labeling claim in
a certifier packet. Blank prints *"Not recorded — § 205.103(b)(3) requires…"* rather than nothing,
because silence in a packet reads as "nothing to report". A lot split across categories reports
**all** of them rather than collapsing to one. A category on a sale not marked organic-on-invoice
is refused at both the model and serializer layers (DRF does not call `Model.clean()`). Verified on
the rendered PDF (p. 675) and confirmed absent from the anonymous payload — it is a record field,
not a consumer claim. 6 tests.

<details><summary>Original finding</summary>

*(P2/P3 Baseline B(b)(3), GAP)*
§ 205.103(b)(3) requires records to identify products as "100 percent organic" / "organic" / "made
with organic". `organic_on_invoice` is a **boolean**; `LabelImage.label_type` is packaging format
(`nonretail`/`retail`/`unpackaged`), a different axis.
→ Add an enum on `SalesRecord` (and `History`) with the three § 205.303 categories. Small change,
directly cited, and it feeds the § 205.307(a)(1) tag line.

</details>

**5 · OSP narrative asserts storage records Trazo cannot produce** *(P3, severity corrected)*
The packet prints *"Lot identity maintained through storage (bin cards, pallet tags): Yes"* while
`ProductionEvent.storage_location` is empty and no storage record type exists.

⚠️ **Severity downgraded 2026-08-10.** P3 called this a claim-safety defect. Re-reading the rendered
packet, it is not: the document carries an explicit **Producer Attestation** (§ 205.401 /
§ 205.400(a)) — *"I, the undersigned, hereby certify under penalty of law…"* — so a grower
attesting that they keep bin cards in their own shed is a legitimate OSP answer, and Trazo is not
obliged to hold every artifact a farm maintains.

What survives is narrower: a certifier who asks "show me" gets nothing from Trazo, so the operation
falls back to paper for a record the platform could carry. **Product gap, not an overclaim** — which
moves it behind the storage ledger (item 8) rather than ahead of it.
→ No rewording needed. Close it by building item 8.

**5b · OSP claim-vs-evidence sweep — the pattern behind item 5** *(sweep finding, NEW)*
Item 5 is not a one-off. The false-gap sweep found a second instance immediately, and the two
together define a class:

| OSP compiles this statement | Record layer can evidence it? |
|---|---|
| *"Lot identity maintained through storage (bin cards, pallet tags): Yes"* | ❌ `storage_location` empty, no storage record type (P3) |
| `container_markings_tie_to_lot` — attested in `g7_0_labeling` | ❌ the lot-tag generator prints `LOT —` for **63%** of productions (P4 F2) |

The OSP is a **producer attestation under § 205.201(a)**, and it is the first document a certifier
reads. Every statement it compiles is a claim the operation makes about itself; where the record
layer cannot substantiate one, the packet contradicts itself in the certifier's hands — exactly the
failure P3 caught on page 1 vs page 12.

→ Sweep **every** `CompileRule` template across the 19 OSP modules and ask, per statement: can the
record layer produce evidence for this? Where it cannot, either build the record or reword the
question. This is cheap (the templates are declarative and enumerable), and it is the highest-value
thing found after the audit closed — because it is what a certifier notices first.

**6 · `retention_until` is 1–2 days short of the § 205.103(b)(4) floor** *(P2, confirmed on live data)*
`history/models.py:754` — `timedelta(days=5 * 365)` = 1825 days. Live row: finish 2026-08-08 →
`retention_until` 2031-08-07. Retention is otherwise properly enforced (delete guard at
`models.py:336-340`).
→ `relativedelta(years=5)`. One line.

**7 · Lot tag omits organic identification silently** *(P4 F4, MED)*
§ 205.307(a)(1) is a positive requirement: a certified operation's nonretail container *must* carry
organic identification. On gate failure the tag ships without it and the only signal is a server
log.
→ Surface the reason in the response when the farm holds a verified certificate.

### Tier 2 — October build, ahead of pilot inspections

**8 · Storage in/out ledger** *(P1 #20, PARTIAL)*
The `Mass-Balance Audit Summary` already reconciles Harvest Yield − Quantity Sold = Balance, so the
regulatory purpose of § 205.103(b)(2) is served. What is missing is the form's own artifact: dated
in/out movements per storage location with a running balance. Partial withdrawals, transfers between
locations, and shrink are unrecordable today.
→ Scope as a small ledger keyed on `History.lot_id`. **Not** the emergency P2 called it.

**9 · Input-side mass balance degrades silently** — ✅ **SHIPPED 2026-08-11**
`record_completeness.py` gained a **conditional** requirement: `quantity_purchased`, cited to
§ 205.103(b)(2), owed only once the operator has asserted a purchase (any of `supplier_name`,
`purchase_date`, `purchase_invoice`, `chemical_lot_number`). Required a new `applies_when`
predicate on `RequiredField` — the existing `applies_to` keys on subtype, which could not express
"required because of what was already recorded."

**Why conditional, not blanket.** Measured on live data: **289 of 289 chemical events have no
`quantity_purchased`**, so a flat requirement would have failed every record on every packet. But
not every application is a purchase — inputs carry over from last season, are produced on farm, or
arrive with a custom applicator. Demanding a quantity there would be Trazo inventing a requirement
the regulation does not make, which is the mistake `record_completeness.py`'s own docstring exists
to prevent. As shipped it fires on **23 of 289** and stays silent on 266.

Reaches the packet: `Record completeness — chemical (§ 205.103(b)(2)) — FAIL: 1/1 chemical records
missing required fields — quantity purchased (1)`. 7 tests, including one pinning that a recorded
**zero** is data rather than a blank (the falsy-vs-None conflation has already caused two bugs here).

<details><summary>Original finding</summary>

*(P3, Baseline B(b)(2))*
The packet says so itself: *"Mass balance cannot be reconciled. No purchase quantity is recorded on
any chemical event."* `quantity_purchased` is optional and unpopulated.
→ Make it required at the point where an input is recorded as purchased, or prompt for it in the
readiness card.

</details>

**10 · `photo_verified_*` misuses "verified" publicly** *(P4 F5, MED)*
Farmer-uploaded photos are *documented*, not verified. `claim_authority.py` enforces this everywhere
else; these fields predate it.
→ Rename on the public serializer to `photo_documented_count` / `photo_documentation_rate`.

**11 · `all_inputs_organic` / `organic_input_percentage` separated from their tier** *(P4 F6, MED)*
Published for a farm with `certification_verified: false`, in a different object from the
disclaimer. This is the shape of the 2026-07-31 incident.
→ Carry the basis inside the same object, or drop the percentage and keep counts.

**12 · Extend the claim authority to container labeling**
Every P4 finding sits on a surface `claim_authority.py` does not cover — the printed lot tag, and
payload fields predating the authority. The chokepoint works; its blast radius is the problem.
→ Add a § 205.307 decision ("may this container be labeled organic, and with what identification")
alongside the existing § 205.311 / FTC / ECGT decisions. One gate, two subparts.

**13 · `LandownerAffidavit` is a model nothing writes to** *(P3)*
One row in the entire database, `yearly_history = []`, `field_name = None`. It is what makes form #2
look covered.
→ Verify a working create/collect/sign path, or the coverage is nominal.

### Tier 3 — small field additions, post-October acceptable

| Form | Add |
|---|---|
| #1 Field History | ✅ **shipped 2026-08-12** — `substance_applications` JSON rows (material / manufacturer / application_dates) ALONGSIDE the `substances_applied` prose blob, which is **never parsed into them** (splitting prose means guessing a manufacturer, and the guess lands in an eligibility determination). `application_dates` is free text because USDA's column is plural and growers write "3/14 and 6/2". Mig product.0024; serializer, FieldHistorySection editor, en/es, PDF detail lines. 🐛 **Also fixed: `last_prohibited_substance` was capturable NOWHERE in the app** — the "Name and Application Date of Last Prohibited Input" USDA asks for on every field. Now has an input, and the packet prints name + date |
| #2 Land Use Verification | ✅ **shipped 2026-08-12** — `no_materials_applied` **tri-state** (declared-none / materials-listed / **unanswered**), `management_period_start`/`_end`, `parcel_legal_description`, plus `manufacturer` + `date_applied` on each `yearly_history` row. Mig certifications.0026; serializer, LandownerAffidavitSection editor (a SELECT not a checkbox — a checkbox cannot say "not answered"), en/es, packet columns. **The point of the tri-state**: an empty `yearly_history` used to be indistinguishable from a signed declaration that nothing was applied, which would manufacture the § 205.202(b) attestation eligibility rests on |
| #7 Input Material | ✅ **shipped 2026-08-11** — `application_purpose` 9-value enum aligned to how § 205.601 organises synthetics BY USE (mig 0198; owner serializers, registry via `enumSource`, form, en/es, packet `Target / Purpose` column). Not added to `record_completeness`: 143/143 FE events lack it and no CFR section enumerates purpose, so requiring it would be Trazo inventing a requirement |
| #8 Compost | ✅ **shipped 2026-08-11** — `compost_unit_id` + `compost_temp_reading_method` (migration 0197; model + both serializers + form + en/es i18n + packet log-table columns). Sibling `compost_feedstock`/`compost_temperature_log` labels moved off hardcoded English at the same time |
| #9 Manure | ✅ **COMPLETE 2026-08-12.** Planned harvest date (mig 0196, 08-11), then the last two USDA columns: **"How Applied / Incorporated"** (`manure_application_method`) and **"Manure Type, Form and Source"** — stored as three enums (`manure_animal_source` / `manure_form` / `manure_origin`) that rebuild USDA's single "Chicken, dry, on farm" column via `manure_type_form_source_display()`. Mig 0202; both owner serializers, registry, form, en/es (26 keys), PDF + CSV. **Splitting was safe here where it was not for buffer quantity**: animal/form/origin have closed vocabularies, a bin count does not. **GR gets only the animal** — grazed manure is not "applied", has no chosen form, and is on-farm by definition. Rendered as per-row detail LINES, not columns: the table is already 5.9in of ~6.4in, and adding columns would have shifted the warning overlay's hard-coded index 5. Not added to `record_completeness` — § 205.103 forms are optional and no CFR paragraph enumerates these facets |
| #11 Seed Part B | ✅ **shipped 2026-08-12** — `seed_nonavailability_reason` enum on the three § 205.2 statutory axes (form / quality / quantity) plus none-offered and other (mig 0200; owner serializers, registry, form inside the `needsSeedSearch` block, en/es, packet line above the supplier table). Prints the ask when unrecorded. Registry has no multi-select `valueType`, and § 205.2 is disjunctive, so a single primary ground is both faithful and native. ⏳ still open: the a/b/c allowed-status triple per supplier row |
| #12 Seed Part C | ✅ **shipped 2026-08-11** — `seed_treatment_allowed_basis` enum (mig 0199; owner serializers only, registry, form, en/es, packet column). ⚠️ deliberately NOT on `consumer_card`: one value is `omri_listed` and the field is a grower dropdown — the 2026-08-09 leak shape |
| #23 Buffer Crop | ✅ **shipped 2026-08-12** — `buffer_disposition_quantity` + `buffer_disposition_evidence` (mig 0201; owner serializers, registry, form, en/es, new packet **Buffer Crop Disposition Record** table). Quantity is free text on purpose — USDA's own example is "1 4x4 bin", buffer volumes are mass-balanced nowhere, and a forced unit would invite a fabricated conversion. Proof is demanded ONLY for the 4 dispositions that put the crop in someone else's hands (`BUFFER_DISPOSITIONS_ENTERING_COMMERCE`); a disked-under row renders "Not required". **Also fixed a claim leak found on the way**: the buffer section printed "crop in buffer (not sold as organic)" off a free-text parcel field — the packet asserting the exact fact § 205.202(c) asks the operator to PROVE |
| #25 Adjoining Land | ✅ **shipped 2026-08-12** — new `AdjoiningLandAffidavit` model + serializer + tenant-scoped viewset at `…/establishments/{id}/adjoining-land/` (mig certifications.0027), plus its own packet table. **A separate model, NOT more keys on `buffer_zones`**: buffer_zones is what the OPERATOR says about the boundary, this is what the NEIGHBOUR signs about their own practices, and folding them together would let an operator's entry render as third-party verification. Distance in **FEET** (USDA's unit; `buffer_width_m` is metres — mixing them turns a 25 ft buffer into a 25 m one). Tri-state on organic status, notify-agreement and 'none of the above'. Unsigned rows render as **UNSIGNED** and draw a REVIEW flag. **UI shipped 2026-08-13**: `adjoiningLandApi.ts` + `AdjoiningLandSection.tsx`, mounted in `ProfileParcel` beside the landowner affidavit. Every neighbour-answerable question is a TRI-STATE select, not a checkbox — a checkbox cannot say "not answered", and an unticked box rendering as a signed "no" is the fabrication this whole class of field exists to prevent. Verified through HTTP: GET 200 / POST 201 / unknown material code 400 / declared-none+materials 400 / cross-tenant parcel 400 / DELETE 204 |
| #22 Clean Transport | ✅ **shipped 2026-08-12** — `prior_products_transported`, `transport_cleaning_method` (USDA's Swept/Vacuum/Air-blown/Washed), `transport_inspected_free_of` (multi-valued list; **empty means no inspection recorded, never 'found clean'**). Mig history.0203; serializer, SalesRecordsSection editor, en/es, packet detail lines. Was storing only that a document EXISTED — a certifier learned a file was attached, not what it attested to. New REVIEW flag when a non-dedicated unit has no prior-load record: "swept" means little without knowing swept of what |

### Found while shipping #23 — packet robustness (2026-08-12)

Not a USDA-form gap; a defect the buffer work walked into and worth recording where the packet
work lives.

**Farmer free text crashed the certifier packet.** ReportLab `Paragraph` parses markup.
`_cell()` escaped `& < >`, so table cells were safe, but hand-built `Paragraph(f"...")` lines
were not:

| Input | Before |
|---|---|
| `Walnuts & almonds <north lot>` | renders as `Walnuts & almonds` — operator text silently deleted |
| `Bob & Sons <b>bold` | `ValueError` — **no packet generated at all** |

An ampersand in a farm name is not exotic. Fixed with `_esc()` at three sites: cover-page
title, `_label_value` (39 call sites — farm name, contacts, lot ID, seed source), and the
§ 205.307 lot-ID sentence. Guard: `history/tests/test_packet_markup_escaping.py`.

⚠️ **Reading the code found one of the three.** The other two came from setting hostile text on
every operator-controlled field and rendering. The guard does that in a single render and
asserts the text reaches the page, not merely that nothing threw. ~51 raw-Paragraph
interpolation sites remain (derived/enum values); re-fuzz whenever an operator free-text field
is added.

### Found while wiring #9 and #23 into the template flow (2026-08-12)

Adding the fields to the event forms turned out not to reach the path most growers use. Crop
templates do NOT go through the form or the serializers — they are built in
`history/views.py::_create_single_template_event`, one hand-written kwarg list per category.

**Two compounding defects, both invisible:**

| | Measured |
|---|---|
| Fields that existed on the model but could not be set from a template | **167** — production 51, soil 47, chemical 50, pest 19 |
| Seeded templates that created NO event at all, silently | **639 of 1029 (62%)** |

The second is the more serious. Every branch passes `backend_fields.get("x")`, so an omitted
key arrives as an explicit `None` — and an explicit `None` overrides a model default.
`transportation_unit` is `null=False, default="miles"`, so the insert failed the constraint,
and `_create_template_events` catches per-event exceptions and continues. The grower ticked
"Season Irrigation Program", saw no error, and got no event. 139 of 190 production templates
omit that key.

Fixed generically — `_template_extra_fields()` (concrete + editable + non-relation + not
already set + not denylisted, so a template can never repoint `history`/`created_by`) and
`_drop_nulls_over_model_defaults()`. After: **1029 of 1029 create**. Guard:
`history/tests/test_template_event_field_passthrough.py`. `ADDING_FIELDS.md` gained the Step 7
that was missing.

⛔ **No template pre-fills the new fields, deliberately.** A template setting
`manure_animal_source="poultry"` writes "Chicken" into the audit file of a grower who used
cattle. Templates suggest ACTIVITIES; they must not assert FACTS about an operation — the same
rule that forbids auto-populating `omri_product`, and the same shape as the Smart Setup
backdated-glyphosate incident.

### Orphan-field sweep (2026-08-13) — three fields the packet printed that nobody could answer

Prompted by the question "maybe we have the Django fields but not wired in the app". Three
confirmed, plus two adjacent shapes:

| Field | State before |
|---|---|
| `ParcelCropHistory.last_prohibited_substance` | printed, no writer — USDA needs it for EVERY field |
| `SalesRecord.organic_label_category` | printed, no writer — **ship list said "shipped"** |
| `ParcelCropHistory.block_id` | printed, no writer, AND the form's duplicate-year guard blocked the split field the column exists for |
| `LandownerAffidavit.landowner_*` | in the payload with no inputs — every create POSTed null |
| `LandownerAffidavit.parcel_legal_description` | captured, never rendered |

**Root cause:** every frontend guard runs registry-**outbound**. Nothing walks the Django models
or the audit export asking "who collects this?", and the three non-event models
(`ParcelCropHistory`, `LandownerAffidavit`, `AdjoiningLandAffidavit`) have no registry
representation at all — it is keyed by the eight event types.

All wired. New inbound guard: `history/tests/test_no_orphan_compliance_fields.py`.

### Explicitly not doing

- Forms #15, #16, #17 (farmers market, pick list, CSA) — direct-market, out of ICP scope
- Form #13 seed-saving — orchards propagate from nursery stock; **confirm with one grower before
  closing this out**
- Price, expense, and revenue columns on #5 and #19 — § 205.103 wants volume reconciliation, not a
  P&L
- Livestock and dry-matter-intake forms — 11 of the 15 AMS PDFs, excluded in `MANIFEST.md`

---

## Two things to fix in how this was claimed

**1. "100% aligned" is not available and should not be sought.** The USDA forms are **March 2011,
pre-SOE**, and every page says *"Optional form, not mandated by regulation."* Alignment to them is a
useful benchmark, not a compliance certificate. The defensible sentence is: *"Trazo's records are
modeled on USDA-published documentation forms and cite 7 CFR Part 205 directly."* Never
"USDA-approved records" or "the required USDA forms."

**2. Trazo's own forms inherit two wrong citations if copied.** USDA's compost form cites
"NOP § 203(c)(2)" (malformed — means § 205.203(c)(2)); the manure form cites "§ 205.203(b)" for the
90/120-day interval, which is actually § 205.203(c)(1)(ii)–(iii). Both verified against the corpus.
An inherited wrong citation in a certifier-facing PDF is worse than no citation.

---

## Verification plan

Each item ships with proof of the class its finding was caught by:

- **Items 1, 10, 11** — assert against **real anonymous response bytes**, not serializer unit tests.
  Demo data is not a defence on a public endpoint.
- **Items 2, 7** — generate the actual tag PDF and read the printed string.
- **Items 3, 4, 5** — regenerate the certifier packet on `History id=580` and diff page 1 against
  page 12. That contradiction is the regression test.
- **Item 6** — assert `retention_until == finish + relativedelta(years=5)` across a leap-year
  boundary specifically.
- **Items 8, 9, 13** — end-to-end on a populated fixture, not a schema check. A model nothing writes
  to is not coverage.

⚠️ Per-app serial test runs only. Never the whole codebase in one process, and read the
`Ran N / OK|FAILED` line rather than piping to `tail`.

---

## Deadlines

| Date | Gate |
|---|---|
| **2026-09-15** | Restated MET metric evaluated; cold outreach unfreezes |
| **2026-09-27** | **ECGT 2024/825 live** — item 1 must ship before this |
| **2026-11-03** | CCOF renewal window opens — Tier 1 complete |
| **2026-12-01** | Verdict gate (per `TRAZO-OCTOBER-2026-PLAN.md`) |
| **2026-12-31** | OCCSP due; COG Pro shutdown |
