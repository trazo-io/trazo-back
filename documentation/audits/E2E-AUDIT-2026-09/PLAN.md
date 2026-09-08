# Trazo End-to-End Audit (2026-09-06/07) — Verified Disposition & Implementation Plan (rev. 2)

## 0. What changed in rev. 2 (Oscar's review, 2026-09-08)

| Review point | Where addressed |
|---|---|
| 1 Inventory model before B2 | §5 **D10** (boundary, movements, counts, summary rule, voids/allocations) + three worked examples; B2 blocked until D10 signed |
| 2 Reject UTC "business date" | §5 **D4 rewritten**: three date classes, operation timezone = **D11**; only the edit round-trip and pure timestamp bugs ship before D11; Continue-disabled reproduced before any input change |
| 3 Purchase identity / evidence integrity | §6 **B1** (surrogate line id, duplicate *warning* not uniqueness, multi-lot allocations with product quantity, PROTECT on delete); **B3** (document pin, reviewer/at, same-operation checks on every write, **no mirroring**) |
| 4 Public/private contract | §5 **D1** three-tier contract + explicit public response schema tested across anonymous / buyer-token / certifier-link payloads |
| 5 Migration assurances | §7 rewritten: rehearsal on a seeded copy, old/new compatibility, data-preserving rollback, recovery; "no migration" contradiction fixed (A1a/A2 none; A1b one) |
| 6 Release gates | §7.1: blocking backend list additions, blocking frontend named-subset step, Playwright lifecycle (local now, CI wiring needs a cross-repo token), export **reconstruction** test |
| 7 Late-entry workflow | §6 **D3 rewritten** as a user journey (missed record on a closed season with reason; originals untouched) |
| 8 Delivery order | §6 reordered to the six-step sequence; retention/deletion copy split into **D9** (legal page, separate approval) |

## 1. Context

`~/dev/trazo/Trazo-End-to-End-Audit.md` (637 lines) is a browser-level product/business/evidence audit of the authenticated app, public QR pages, marketing site and downloaded exports, run against the fabricated **Calapooia Bend Farm** fixture on 2026-09-06/07. It ranks 14 findings (T01–T14) and adds ~40 recommendations.

Goal: verified code changes + coherent UX fixes + a manageable release sequence, inside *organic specialty-crop recordkeeping and inspection preparation, with optional buyer/consumer transparency from the same records*. The audit is evidence + hypotheses; every finding was checked against current code (three read-only exploration passes over all 8 relationship chains, load-bearing claims re-verified directly). Several items were already fixed in **uncommitted staged work dated 2026-09-07** (§3).

## 2. Repository / architecture map and access gaps

| Repo | Path | Branch | State | Deploy |
|---|---|---|---|---|
| Backend — Django 5.2.17 / DRF / Postgres, py3.12, Poetry | `trazo-back/` | `chore/remove-dead-ec2-deploy` | **87 staged files, +14,763 lines, uncommitted** | DO App Platform behind Cloudflare; **no Redis ⇒ `DummyCache` ⇒ DRF throttles + DDoS middleware are no-ops in prod** |
| Producer + consumer SPA — React/Vite, Chakra, RTK Query, mixed `.jsx/.tsx` | `trazo-app/` | `chore/producer-analytics-posture` | **37 staged files, uncommitted** | Netlify (`app.`/`consumer.trazo.io`) |
| Landing — Next.js 16 / Tailwind v4 | `trazo-landing/` | `chore/renovate-dependency-channel` | clean | Vercel |
| OG-tag worker (Cloudflare) | `trazo-worker/` | not a git repo | — | routes disabled |
| Root `~/dev/trazo` | — | **not a git repo** | root `documentation/`, `.claude/`, the audit: tracked by nothing | — |

- **Chains, where they live**: Company→Establishment→Parcel→History(season)→8 `CommonEvent` subclasses (`history/models.py`); catalogs (`certifications/models.py`: `OMRIProduct`, `WSDAMaterial`, `NationalListSubstance`, `PlanMaterialEntry`, `OrganicSystemPlan.approved_*`); harvest = `ProductionEvent(type="HA")`; `SalesRecord.harvest_events` M2M; corrections = `EventAmendment` + django-auditlog; public = `history/transparency_views.py` + `PublicHistorySerializer` + `claim_authority.py`/`privacy.py`; consumer UI `src/views/Scan/ProductDetail/**`; review link = `CertifierAccessLink` + `/api/certifier-review/<token>/*` + `src/views/CertifierReview`; OSP = `OrganicSystemPlan`/`OSPAnnualUpdate` + `osp_module_pdf.generate_osp_packet`; export = `history/services/records_export.py`.
- **Test infra**: backend CI runs a scoped claim-safety list (~416 tests, settings `dev`, Postgres+Redis) + black/isort + requirements sync — blocking. Full suite: per-app serial, `--noinput`, isolated `DATABASE_NAME`; `subscriptions` never `--keepdb`. **Another session is currently running `manage.py test certifications`** (seen 2026-09-08) — every run here uses its own `DATABASE_NAME`. Frontend: vitest (895, 33 known red), Playwright `e2e/` (5 specs, not in CI, needs 4 hand-started processes), typecheck/lint per-file gates — all non-blocking.
- **Access gaps**: no production DB/credentials/deploys (T04 prod check after deploy is Oscar's). No physical phone (Playwright viewports only, recorded). Stripe test keys. Ledger in git-tracked `trazo-back/documentation/audits/E2E-AUDIT-2026-09/`.
- Foot-guns: stray `trazo-back/trazo-back/`, `trazo-back/trazo-app/` (absolute paths only); `PlanUsage/` empty dir; `farm.meta.acres` untranslated.

## 3. In-flight staged work — PRESERVE, build on top

Backend: migration **0233** §205.601(j)(6)→(j)(7); **0234** `SalesRecord.voided_at/void_reason/voided_by` + `.live()/.voided()`; `retention.assert_child_record_deletable`; `operation_certificate.py`; `binding_clauses` subpart E; register/published-inventory guards; FTC 260.6→260.4; Voided Sales table. Frontend: `SalesRecordsSection` void UI, `TourProvider` raw-key fix, OSP export-gate tests, i18n.
**Rule**: never revert/re-stage; new work = separate commits after Oscar commits the staged set (he runs git). Any migration in this plan is numbered after 0234, so **Oscar commits first**. Slices name the staged files they touch.

## 4. Verified finding matrix

Legend: ✅ confirmed · 🟡 partial/narrower · ✔︎ already fixed · ✖ not reproduced · ❓ decision · ⏸ deferred/rejected.

### T01 — Public disclosure vs free text — 🟡 narrower, three real leaks
- Promise (`trazo-landing/app/privacy-policy/page.tsx:517-533`, `faq-section.tsx:45`): supplier/purchase records never publish, "supplier names also removed from free-text notes".
- Held: top-level supplier/invoice/purchase fields omitted (`serializers.py:4935-4942`, `:5220-5238`); `_CERTIFIER_ONLY_EVENT_FIELDS` (32 keys) stripped twice; `extra_data` allow-listed (~450 keys) minus sensitive substrings; BU/SS/EM/TP withheld; establishment prose via `public_free_text`; anonymous + unpublished ⇒ 404 (`transparency_views.py:156`). The audit's "authenticated carrot preview exposes supplier/invoice/lot" = the owner-only unstripped `/histories/<pk>/public_history/` (`views.py:1029`, no `force_public_view`); the consumer route uses `/api/transparency/<uuid>/`, which serves owners the same stripped payload (`:323-325`). ✖ as "publicly exposed".
- **Leak 1** ✅ `"seed_lot_number"` in `ALLOWED_EXTRA_DATA_KEYS` (`serializers.py:1940`, `:2462`), no substring catches it, demo data writes it; test walks only the top level (`test_public_serializer_leakage.py:471-482`).
- **Leak 2** ✅ `redact_own_vendor_names` reads only 4 model fields (`privacy.py:121-126`, `:202`); an extra_data-only vendor is not redacted from prose.
- **Leak 3** ✅ `History.description` published raw (`serializers.py:3633`), no scrub (not rendered on the consumer page today).
- Existing public-note model: `observation` on all 8 tabs, labelled "Your buyer page shows this in your own words" (`events.common.help.observationAudience`); `description` is **machine-authored** (serializer default `"{label}: {name}"`, `serializers.py:176-178`; `voiceDataMapper.ts:1259-1264` refuses farmer words in it); the consumer generator only keyword-matches it. → **D1, slice A1a/A1b**.

### T02 — Fabricated demo shows USDA "Verified" — ✅ root cause
- Gate correct (`certifications/models.py:172-193`; `consumer_claim_validator.py:226`). **Fixtures stamp the OID source on invented certificates**: `_calapooia_bend_data.json:301-303` (fake `nopid`), `_loewen_base.py:196-209` (`is_demo=True` at :186). `seed_showcase_walnut_farm.py:703-719` does it right. `backfill_demo_claim_safety.py` covers Solana Verde/Coastal Valleys only.
- Specimen mark exists at page level (`transparency_views.py:634`, hero chip, banner) — **not at the claim point** (`filter_certifications_for_consumer` never consults `is_specimen`; `CertificationBadge.tsx:53-99`, `TrustSummaryHeader.tsx:181`, `FarmModal.tsx:657`).
- Second half (public "OMRI listed" while OSP has findings) 🟡 → D3-vocabulary (§5). → **A2**.

### T03 — Harvest→sale allocation & remainder — ✅ structural
- Plain M2M, no through model, no per-pick quantity (`history/models.py:4863`; checkboxes `SalesRecordsSection.tsx:723-767`). Balance = `harvest − sold` (`audit_export_service.py:11175-11183`); no inventory/loss/return fields; buffer/purge quantities free text by design; `quantity_returned_from_handler` outside the balance; summary `yield_total` never summed (`:10858`); unit mismatch silently drops the line; `lb`≠`lbs` between two helpers. → **D10 then B2**.

### T04 — Review link "no longer available" — 🟡 not reproduced; every remaining path identified
- Lifecycle sound and tested (`CertifierAccessLink`, `views.py:2149-2164` 404-for-unknown/expired/revoked by design, 30+ tests). **UI collapses every failure into "no longer available"** (`CertifierReview.tsx:120-146`, `BuyerReview.tsx:80-113`); no frontend test mounts either page.
- Ranked causes: dev-only hardcoded `API_ROOT_URL` + CORS list (`environment.ts:105`, `dev.py:169-181`); audience mismatch (`get_queryset` returns both, `views.py:2477`); copied-token trailing char; prod 429s (inert without Redis; live once `REDIS_URL` set). Ruled out: CSRF, cookies, plan gate, IP logging, `expires_at` parsing. Adjacent: `periodDates()` TZ bug, `expires_at` via `formatDateOnly`. → **A3**.

### T05 — Daily forms — ✅ with precise gates
- `required` on 3 of ~400 registry fields; requiredness in two zod schemas. Irrigation/harvest require `type` only. PUR identity block state-gated; **CA DPR permit block keyed on a product keyword list** (`ChemicalTab-ENHANCED.jsx:4932-4944`); grain/Brix/dry-matter **no crop gate** (`productionEvent.ts:696-766`); FSMA review on every subtype; `*_efficiency` self-assessed. One repeat affordance (`EventDetailsModal.tsx:884-903`), no recent list. Season close: `finish_date` is `datetime-local` (`StandardFinishProductionForm.tsx:563`), `isStep0Valid` needs it non-empty — **plausible** cause of the audit's disabled Continue, **unverified; reproduce first (C1)**. → **C1, C2**.

### T06 — "On file" vs attached — ✅ narrower
- Receipt files linked for Chemical/Soil (`receipt_document`, packed in packet, `[receipt on file]`). Not for seed, beneficials, scale tickets, sale invoices/BOL, handler certificates, letters. `GeneratedDocument` has `history`/`parcel` FKs only; no generic FK; ~15 boolean/text "on file" fields with no file. → **B3**.

### T07 — Purchase counted twice — ✅ structural
- No purchase model; purchase facts re-typed per application; `total_purchased_by_unit[unit]` (`audit_export_service.py:10996-11040`) has no dedupe key; CSV twin drops soil. `volume_numeric` help text is "Volume applied" (product vs mixture undefined; `_amount_reconciles_with_rate` exists because carrier volume gets typed as product). → **B1**.

### T08 — Dates — ✅ live; two producer-side defects
- `CommonEvent.date`, `History.start/finish_date` are `DateTimeField`; `TIME_ZONE="UTC"`; **no operation timezone exists**. Backend renders the UTC day everywhere; consumer surfaces render the viewer's local day (`consumerDisplay.ts:315`, `:248`). **Edit path re-dates records** (`NewEvent.jsx:1028-1031`: UTC wall clock into `datetime-local`). `formatEventDate` `Math.abs` + locale-less fallback. `expires_at` misformatted. Public harvest date already reads the last HA record ✔︎. → **D4/D11**, interim **A4**.

### T09 — OSP completion conflation — ✅
- Four surfaces, four counts; three definitions of "section complete" (`models.py:1108` vs `views.py:472` vs `OSPView.tsx`); packet never completeness-blocked ✔︎; "filed" = checkbox at `now()`; `certifier_acknowledged_at` written by nothing. → **D1-OSP slice**.

### T10 — Consumer prose — ✅
- `getConsumerEventDescription` picks prose by subtype only; irrigation "recorded water source"/"trees" (`eventDescriptions.ts:723`, `:1078-1081`), mowing "fruit picked up off the floor"/"orchard floor" (`:1123-1141`, `:922-941`), harvest "fruit", pruning, post-harvest — all unconditional; only `flame_weed` checks a field. → **E1**.

### T11 — Carbon boundary — ✅
- In-app: "direct on-farm emissions only … based on EPA/USDA factors" (`CarbonImpactExplainer.tsx:102-109`); calculator includes fertilizer + crop-protection **manufacturing** (`verified_emission_factors.py:418-570`, P/K are `PROVENANCE_INTERNAL_ESTIMATE`); landing table already admits manufacturing while its paragraph denies it. → **E2**.

### T12 — Export scope — ✅
- `pricing/page.tsx:295-302` "not built yet" vs `faq-section.tsx:53-56` "yes, every plan"; stale comments `pricing/page.tsx:296-300`, `gating.py:57-63`. ZIP (12 CSV) omits sales↔harvest M2M, `EventAmendment`, auditlog, documents/bytes, all OSP tables, `EquipmentEvent`, facilities, `LabelImage`, `ProductionPlanItem`. → **A5 copy, B4 data**.

### T13 — Density / i18n — 🟡
- Raw tour keys ✔︎ fixed (staged); `farm.meta.acres` untranslated; no compact-row card variant. → **C3**.

### T14 — Production count — ✅ narrow
- Gate counts `created_at`, meter counts `start_date`, both calendar-year (`company/models.py:237-275`, `subscriptions/serializers.py:113-127`). → **A5**.

### Additional rows
| Row | Disposition |
|---|---|
| §6 retention cite (b)(3)→(b)(4) | ✅ landing ×6 + backend ×4 cite (b)(3); `test_seed_education_content.py:69-71` pins (b)(3). Privacy page "5 years" vs "7 years". → **D9** (legal copy, separate approval) |
| §6 (j)(7) | ✔︎ staged 0233 |
| §9 quality/method "Not shown to consumers" vs published | ✅ → D5 decided: withhold (A1a) |
| §9 withheld categories unnamed on the page | 🟡 → E1 policy line |
| §9 retention/cancellation terms | → D9 |
| §7 reviews flow | 🟡 dormant backend; no UI; E1 drops zero-count `reviews` from payload |
| §15 efficiency adjustment | ✅ → C1/E2 |
| §6 handler blanket rule | ✖ copy already qualified |
| §5 water-source model | ⏸ backlog |
| §12 vocabulary | D6 decided: bounded label rename (C3) |
| §12 nav rewrite | ⏸ |
| §16 late entry | ✅ no `created_at`, no reason path; server refuses records dated ≤ `finish_date` (`views.py:3747-3760`) → **D3 journey** |
| §16 packet front summary | → D2 |
| §4 amend GET permission parity | ✅ found → A1a |
| §5 mobile/offline | ⏸ viewport pass only (C4) |
| §14 #10–12 | ⏸ later experiments |
| §10/§11/§19–22 positioning, WTP, interviews | ⏸ not engineering-provable; D8 decided: facts only |

## 5. Decisions

- **D1 — DECIDED: explicit public/private notes; contract in three tiers.**
  1. **Structured private fields never enter public responses** — enforced by the serializer allow-lists and pinned by an **explicit public response schema**: a declared set of top-level keys and per-event keys for (a) `/api/transparency/<uuid>/`, (b) `/histories/<uuid>/public_history/` non-owner view, (c) buyer-token view of an unpublished season, (d) certifier-link metadata/readiness payloads. Any new key fails the test; a recursive walk asserts no `description`, `seed_lot_number`, `*_lot_number`, supplier/invoice/purchase keys anywhere.
  2. **Public notes are deliberately published text**: `observation` relabelled "Public note — shown on your buyer page" on all 8 tabs + edit modal + finish form; it is the only farmer prose that publishes. New `CommonEvent.private_note` ("Private note — certifier and your team only"; A1b, one additive migration).
  3. **Supplier-name detection is an additional safeguard, not the boundary**: `redact_own_vendor_names` also reads allow-listed extra_data vendor keys and the establishment's supplier registry; write-time nudge in the wizard. Wording nowhere promises that every supplier reference is removed.
  `description` (machine-authored) and `History.description` are withheld from public payloads. Legacy: nothing destroyed; existing `observation` text stays public (it was written into a box labelled public); existing `description`/season notes stop publishing. Privacy policy/FAQ/in-app help: "Only the box labelled *Public note* appears on your buyer page. Supplier and purchase details entered in their own fields never publish; if one of those supplier names also appears in your public note it is removed there too. Everything else you write is for your certifier and your team."
- **D2** specimen at the claim point: do it (A2).
- **D3-vocabulary** input states (exact product identified / public listing matched / operation approval documented / use conditions reviewed / unresolved) on producer surfaces only; consumer chip stays factual. Later phase.
- **D4 — REVISED. No UTC "business date" convention.** Three classes: (i) **business dates** — `DateField`s (purchase date, sale date, `retention_until`, review period): rendered with `formatDateOnly`, never through `new Date(iso)`; (ii) **timestamps** — created/amended/accessed/expires: rendered as instants with a zone label; (iii) **timed activities** — `CommonEvent.date`, `History.start/finish_date`: an instant whose *intended local day* must be preserved, which requires an operation timezone (**D11**). Until D11 ships: no rendering change to activity days on any surface; fix only the edit round-trip (`NewEvent.jsx:1028` must write back the same instant it read), `formatEventDate` `Math.abs`/fallback, `periodDates()`, `expires_at` formatting. Tests use *intended farm date* examples (Oregon 20:00 PDT logged → prints that Oregon day on QR, packet and CSV once D11 lands; a Madrid viewer sees the same day), not "PDF equals consumer". Season close: reproduce the disabled Continue in the browser before changing the input; if confirmed, making `finish_date` a business date is a model change inside D11.
- **D5 — DECIDED** withhold `quality_grade`/`harvest_method` from public (A1a).
- **D6 — DECIDED** bounded label rename (C3).
- **D7** ledger at `trazo-back/documentation/audits/E2E-AUDIT-2026-09/{PLAN.md,LEDGER.md}` + root pointer.
- **D8 — DECIDED** landing facts only; headline/CTA alternatives go in the ledger.
- **D9 ⚠︎ Retention / deletion copy (legal page; needs Oscar's approval of wording).** Enforced behaviour today: seasons carry `retention_until = finish_date + 5 y` (`history/models.py:894`); events, sales and containers inside that window refuse deletion (423/409); **no account-deletion endpoint exists** (`users/views.py` has none) — deletion is a request handled by hand; no 7-year rule exists anywhere; cite is 7 CFR 205.103(b)(4). Proposed copy states exactly that (5 years after the season closes; export anytime; account deletion on request, records inside the retention window are exported to you before removal). Not bundled with A5 copy cleanup.
- **D10 ⚠︎ Inventory model (must be signed before B2 schema).**
  - **Boundary**: inventory the operation *owns* for one crop-season lot, tracked at two locations, `on_farm` and `at_handler`. Ownership ends at a sale/shipment or an out-disposition. Buyer-side and handler-owned stock are out of scope.
  - **Movements** (quantity, unit, date, source record; live values, so a correction changes the movement): `harvest_in` (→ on_farm; from HA `yield_quantity`), `transfer_to_handler` (on_farm → at_handler; from `quantity_sent_to_handler`), `handler_return` (at_handler → on_farm, in `handler_return_unit`), `processing_outturn` (at_handler, in-unit → out-unit, when the handler reports a different unit; the difference is printed as outturn %, **never** booked as loss unless the handler reports one), `sale_shipment` (on_farm **or** at_handler → outside; from live `SalesRecord.quantity`; new `ship_from` on the sale, default on_farm), `out_disposition` (loss / cull / donation / feed / seed / sample / other; from `HarvestDisposition`).
  - **Counts** are dated snapshots, not movements: `inventory_count(location, date, quantity, unit)`.
  - **Equation per location**: `computed_closing = 0 + Σ inflows − Σ outflows` (crop seasons open at zero; carried-over stock is a `harvest_in`-class movement of kind `opening_transfer` with a source lot). `variance = computed_closing − latest count` when a count exists on/after the last movement; otherwise the line prints "computed on hand, not counted". "Unexplained" is the variance, never the computed closing.
  - **Summary harvest rule**: a summary HA record (`is_summary`, `yield_total`) and individual HA records in the same lot are mutually exclusive inputs. Both present ⇒ use individual records, print "summary record also on file — double-count risk, reconcile", never sum both.
  - **Voids / corrections / allocations**: voided sales are not movements; amendments change live values; per-pick allocations are an *attribution* of a sale movement to picks, not a movement; Σ allocations per pick ≤ pick yield else "over-allocated" flag; Σ allocations per sale ≤ sale quantity else flag; unallocated remainder of a sale printed as such.
  - **Units**: movements keep their recorded unit; arithmetic only within one unit family after `_canonical_unit`; cross-unit conversion only with a documented factor on the record (box weight); a mismatch prints a review line and excludes the term, never drops the section.
  - **Worked examples (expected outputs a test must reproduce before any schema ships)**
    1. *Blueberries, River Block*: HA records Σ 114,240 lb; sales 89,562 + 21,140 lb from on_farm; no counts, no dispositions → on_farm computed 3,538 lb, line "computed on hand 3,538 lb — not counted or explained". Operator adds cull 2,900 lb (reason "soft fruit, dumped") and a count of 600 lb dated after the last sale → computed 638, count 600, **variance 38 lb** flagged. Allocation: fresh sale allocated 60,000 to pick A (yield 60,000) and 29,562 to pick B (yield 54,240) → pick B remaining attribution 24,678; processing sale allocated 21,140 to pick B → pick B over-allocation none (24,678 ≥ 21,140).
    2. *Walnuts via huller*: HA 50,000 lb field weight; `transfer_to_handler` 50,000 lb; `handler_return` 22,000 lb dry in-shell → at_handler shows processing outturn 44% (in 50,000 lb wet, out 22,000 lb dry), on_farm 22,000 lb; sale 21,500 lb → on_farm 500; count 500 → variance 0.
    3. *Summary + individual*: summary HA `yield_total` 10,000 lb and two HA records 4,800 + 5,100 → uses 9,900, prints the double-count warning; sale 9,900 → computed 0.
    4. *Unit mismatch*: HA 1,200 boxes, sale 30,000 lb, `box_weight_lb` 25 → converted line "1,200 boxes × 25 lb = 30,000 lb (documented factor)", computed 0; without a box weight → "harvest in boxes, sales in lb, no documented factor — not reconciled".
  - Oscar signs D10 (or amends it) → B2 schema designed from it.
- **D11 ⚠︎ Operation timezone.** Add `Establishment.timezone` (IANA), defaulted at migration from `state` (US state → zone map; multi-zone states pick the majority zone and flag for confirmation), editable in farm profile; every timed-activity rendering (producer, consumer, packet, CSV "local date" column) and every "day" comparison (post-harvest continuation, retention floor, cert expiry) uses it. Stored instants unchanged (the wall-clock-as-UTC convention is *reinterpreted*, not migrated: a stored `14:30Z` from an Oregon farm is displayed as 14:30 Oregon — today's readers already do this via `timeZone:'UTC'`; D11 makes that explicit per farm and lets the consumer page use the same day). Needs Oscar's sign-off on the default rule and on the migration that stamps existing farms.

## 6. Delivery order and slices (Oscar's sequence)

| Order | Scope | Slices |
|---|---|---|
| 1 | Reviewed baseline: staged work + current test failures | **S0** |
| 2 | Public-data + specimen-claim fixes | **A1a, A2** (A1b after staged commit) |
| 3 | Review-link behaviour; date interim fixes; straightforward form gating | **A3, A4-interim, C1** (+ **A5** copy/metric, minus retention) |
| 4 | Validate purchase / inventory / evidence models with worked examples | **D10, D11 sign-off; B-design doc with the four examples as executable tests against a pure-Python model before schema** |
| 5 | One complete journey purchase → application → harvest → sale → evidence → export | **B1 → B2 → B3 → B4** on one seeded farm, end-to-end Playwright |
| 6 | Expand coverage; OSP review, public presentation, marketing | **C2–C4, D1-OSP, D2, D3, E1–E3** |

### S0 — Baseline (no code changes)
Record in the ledger: `git status` summary of both repos (staged file lists), backend per-app test results on the current tree for `history`, `certifications`, `subscriptions`, `company`, `product` (isolated `DATABASE_NAME=trazo_e2e_<n>`, `--noinput`, logged to files, never piped to `tail`), the CI scoped list result, vitest full-run counts, typecheck/lint gate diffs. Any red test is classified: *stale fixture* / *real* / *caused by staged work*. Oscar commits the staged set; migrations in later slices number after 0234.

### A1a — Public payload contract (no migration)
- Withhold `description` from the 8 public event dicts and `History.description` + `quality_grade`/`harvest_method` from the public payload (non-owner view: add to `_OWNER_ONLY_FIELDS`; `harvestDetails` in `transparency_views.py:596-602`); consumer title/prose derive from subtype (`getConsumerEventDescription` accepts an empty seed; weather keyword branch reads `type`).
- `ALLOWED_EXTRA_DATA_KEYS` minus `seed_lot_number` (both lists); `EXTRA_DATA_SENSITIVE_SUBSTRINGS` += `lot_number` (`lot_id`, `harvest_lot_code` stay).
- `redact_own_vendor_names`: candidates from model fields + allow-listed extra_data vendor keys + establishment supplier registry (distinct values of the 4 supplier columns across the farm; per-request cache).
- `GET /events/<id>/amend/` CA/FM parity with `/histories/<pk>/amend/`.
- Relabel `observation` → public note (8 tabs, edit modal, finish form; both locales); write-time nudge when the public note contains a supplier name from the same form; landing privacy/FAQ + in-app help per D1.
- **Public response schema test** (new `history/tests/test_public_response_schema.py`): declared key sets for the four payload kinds in D1; recursive denylist walk; fails on new keys. Extend `test_public_serializer_leakage` to walk `extra_data`. Vitest: consumer card title with no `description` for all 8 families; nudge util; i18n parity.
- Acceptance: anonymous River Block + carrot payloads contain no `description`, `seed_lot_number`, supplier strings from any purchase field, season note, grade/method; consumer cards still titled; landing/in-app text matches behaviour.

### A2 — Specimen at the claim point
- `consumer_claim_validator.filter_certifications_for_consumer` + `build_organic_claim_evidence`: on `is_specimen(establishment)` never emit `verified_via_database`; downgrade to `self_reported`, add `specimen: true` per cert and to `organic_claim`; source/disclaimer = specimen text. `claim_resolver.py:253-258` follows.
- Fixtures: `_calapooia_bend_data.json`, `_loewen_base.py` → `self_reported`, empty source/URL; `backfill_demo_claim_safety.FIXTURES` += both.
- Frontend: `CertificationBadge`, `TrustSummaryHeader`, `FarmModal`, `ProductDetail` hero → grey "Specimen — not checked against any registry" when `specimen`; never green.
- Tests: specimen establishment → no `verified_via_database` anywhere in the three anonymous payloads; real operation unchanged; static guard that no seeder/fixture writes `verification_source="usda_organic_integrity_db"`; vitest badge. Local re-seed documented.

### A1b — Private note (one additive migration, after Oscar's commit)
`CommonEvent.private_note = TextField(blank=True, default="")` over the 8 tables; serializer read/write on all 8 families (round-trip test — the 2026-09-07 `extra_data_only_fields` class); `_CERTIFIER_ONLY_EVENT_FIELDS` + `consumerDisplay.ts` mirror; box on 8 tabs + edit modal; packet prints it; ZIP gets it (concrete field). Rehearsal per §7.

### A3 — Review-link lifecycle
Frontend distinguishes 404 ("no longer available") from 429/5xx/network ("temporarily unavailable — try again"); `API_ROOT_URL` honours `VITE_APP_BACKEND_URL`; own DRF scope `certifier_review` (base + dev; documented that prod throttling is inert without Redis); WARNING log on resolve failure (reason + token hash); `?audience=` filter + cards pass it; `periodDates()` and `expires_at` fixes. Tests: vitest both pages (404 vs 429 vs network); backend scope + log; **Playwright `05-review-link-lifecycle.spec.ts`** create → open anon → revoke → open ⇒ unavailable; expired via factory. Prod check after deploy = Oscar.

### A4-interim — Date defects that are not the D4 decision
Edit round-trip writes back the instant it read (new `instantToLocalInputPreservingUtcWallClock` helper reused from `dateOnly.ts` semantics); `formatEventDate` drops `Math.abs`, adds locale + explicit zone; `expires_at` via `formatDateFromTimestamp`; `periodDates()` builds ISO dates without `toISOString()`. Test: editing an event twice leaves `date` byte-identical; future events never read "ago". No consumer-day rendering change (waits for D11).

### A5 — Copy + metric alignment (no legal pages)
Landing export FAQ + pricing bullet rewritten to the real ZIP scope; stale comments removed (`gating.py`, `pricing/page.tsx`); in-app `app.carbonExplainer.scopeBoundary` loses "on-farm only / EPA/USDA factors" (E2 owns the full wording); T14 meter counts `created_at`, label "Productions created in {year}", test meter == gate. Retention cites/wording → **D9**, separately.

### C1 — Straightforward form gating
CA DPR permit block gated on `farmState==='CA'` AND keyword; crop-family gate for grain/Brix/dry-matter via `crop_type.slug` (one config); FSMA review + lab-test trio + `*_efficiency` behind "More details" (E2 confirms whether the calculator reads efficiency; if not, remove). **Reproduce the disabled Continue** on season close in Playwright first; fix `isStep0Valid` vs zod (`> 0`); input-type change only under D4/D11.

### B-design (order 4) — executable model before schema
`history/services/inventory_model.py` as pure functions over dataclasses (movements, counts, allocations) implementing D10; `history/tests/test_inventory_model_examples.py` reproduces the four worked examples exactly (Decimal arithmetic). Purchase-line identity and allocation rules from B1 modelled the same way (`purchase_model.py`) with examples: one invoice with two identical lines; one application from two lots; product vs mixture. No migration until both pass and Oscar signs D10/D11.

### B1 — Purchases
`InputPurchaseLine` (establishment, `document_ref` = supplier + invoice + date, `line_no`, product identity = name + optional catalog FKs, supplier lot, `product_quantity` Decimal(14,3) + unit, `receipt_document` FK, created_by/at). **Identity = surrogate pk; duplicate detection = a warning list** on (supplier, invoice, product, lot) matches at save time, not a DB constraint. `ApplicationPurchaseAllocation` (event family+id, line FK, `product_quantity` in the line's unit) — an application may draw from several lots. Application keeps `volume_numeric` documented as "amount applied as entered (may be mixture)"; allocation quantity is **product**; cross-check against `application_rate × area` reuses `_amount_reconciles_with_rate`. Deleting a line with allocations → PROTECT (409); "void" path keeps the row. Reconciliation groups by line: purchased / allocated / remaining; never across products; legacy events with typed purchase fields and no allocation listed as "typed on the application — not reconciled"; `link_legacy_purchases --dry-run` proposes, `--apply` links. ZIP: `input_purchase_lines.csv`, `application_purchase_allocations.csv`.

### B2 — Movements, allocations, dispositions (after D10 signed)
Schema from the executable model: `SalesRecordHarvestAllocation` (through; `quantity` nullable = "linked, unallocated" for migrated rows; `SeparateDatabaseAndState` reuse of the existing M2M table), `HarvestDisposition`, `InventoryCount`, `SalesRecord.ship_from`; handler movements derived from existing HA fields (no new columns). Season header: harvest / at handler / allocated / dispositions / computed on hand / count / variance / unresolved items. Balance page rewritten from the model. ZIP: allocations, dispositions, counts.

### B3 — Evidence links (no mirroring)
`documents.EvidenceLink` (document FK PROTECT, `document_sha256` + `size_bytes` pinned at link time so a replaced file is visible, `role`, exactly-one target CheckConstraint over event family+id / sales record / harvest event / plan material entry / facility / purchase line, `note`, `created_by/at`, `reviewed_by/at`). Every write validates `document.establishment == target establishment` and the caller's `WorksIn` on that company. Receipts stay on the existing FK; the evidence index unions both; a later decision may migrate receipts into links. Deleting a linked document → 409; "replace file" keeps the row id and updates the pin, printing "replaced on <date>" in the index. Documents page: reference entered / file attached / reviewed (by, at); "needed evidence" list next to generated outputs. ZIP: `documents.csv`, `evidence_links.csv`, `documents/` bytes (uploads only, 200 MB cap + manifest line).

### B4 — Export completeness + reconstruction test
CSV set from B1–B3 plus `event_amendments.csv`, `equipment_events.csv`, `post_harvest_facilities.csv`, `establishment.csv`, OSP set (`osp_plans`, `osp_plan_materials`, `osp_approved_inputs`, `osp_change_log`, `osp_annual_updates`, `osp_change_notifications`, `certifications`). README = exact contents + declared exclusions. **Reconstruction test**: a loader reads the ZIP into an empty test DB (id-mapped) and asserts the relationship graph and values — sale→allocation→pick quantities, application→purchase line quantities, event→amendment original/corrected, event→evidence pin, plan→materials — equal the source. Manifest test remains as the cheap gate.

### C2–C4, D1-OSP, D2, D3, E1–E3 (order 6)
- **C2** core/more-details split via `PriorityTier`; "Save and log another"; "Recent on this parcel" chips; irrigation summary default.
- **C3** D6 labels (key list in ledger); `farm.meta.acres`; compact-row card; `aria-label` sweep.
- **C4** Playwright 375/390/768/1440 EN+ES; states screenshotted; device/offline recorded as untested.
- **D1-OSP** five independent counters (`answers`, `operator_reviewed`, `evidence_linked`, `quantities_reconciled`, `filing`) + merged "Unresolved work" list with deep links; one "section complete" helper; optional `certifier_acknowledged_at` picker.
- **D2** packet front summary: operation + period, coverage counts, missing items, quantity exceptions, document index.
- **D3 — Late entry as a journey.** "Add a missed record" on a closed season: activity date ≤ `finish_date` allowed **only with a reason**; stored as a normal event plus `CommonEvent.created_at` (auto) and `late_entry_reason` (two nullable columns × 8 tables, one migration; historical rows NULL = "not recorded"); author from `created_by`; the packet's corrections section gains a "Late entries" table (activity date, entered on, by, reason); the producer timeline marks "entered later"; originals untouched; the existing post-harvest continuation path (dated after close) stays reason-free. Amendments unchanged.
- **E1** product-first QR page (identity → origin → grown highlights → claims in four dimensions → full record + withheld-categories line → optional environmental estimate → next action); compact no-photo hero; `eventDescriptions.ts` field-presence guards + crop-aware tables + literal fallback; "field named ⇒ field present" test; zero-count `reviews` dropped.
- **E2** carbon boundary copy + provenance line (EPA fuel/electricity; USDA/ARS + literature N; Trazo estimates P, K; Audsley/Lal crop protection); landing paragraph aligned to its table; rules file corrected; no factor changes.
- **E3** landing facts (deadline duplication, "who this is for", FAQ/export/carbon); headline/CTA alternatives in ledger only.

## 7. Migrations, compatibility, rollback, gates

- **Which slices migrate**: A1a, A2, A3, A4-interim, A5, C1 — none. A1b — one (`private_note`). B1/B2/B3/D3/D11 — one each, additive, nullable/defaulted, numbered after 0234 (staged commit first).
- **Rehearsal** before each: `pg_dump` the local seeded DB → `trazo_rehearsal_<slice>`, apply the migration, run the slice's tests + the CI scoped list against it, run the seeders' idempotent re-run, `makemigrations --check`, `migrate <app> <previous>` to prove reversibility on an empty-data column, then re-apply.
- **Old/new compatibility during deploy** (DO rolls one container; Netlify deploys the SPA separately): serializers treat every new field as optional on write and absent-tolerant on read; the SPA renders without new keys (feature flags per slice: `VITE_FEATURE_ALLOCATIONS` etc. default off until the backend is live); API generated types regenerated (`npm run typegen`).
- **Rollback that preserves data**: never drop a column that has user data. B2 rollback = disable the UI flag + leave tables; B3 same; A1b same. Down-migrations exist for empty columns only; the ledger records the "point of no drop" per slice. Recovery: before any down-migration, `records-export` ZIP + `pg_dump` of the affected tables to the DMS `exports/` folder.
- **Relationship preservation**: B2's M2M→through uses `SeparateDatabaseAndState` on the existing join table (no row copy); a guard test counts links before/after on the rehearsal DB.

### 7.1 Release gates (blocking)
- **Backend CI scoped list +=** `test_public_response_schema`, extended `test_public_serializer_leakage`, specimen-claim tests, seeder-source guard, review-link scope/log tests, event-amend permission test, date round-trip tests (as they land), `test_inventory_model_examples`, `test_purchase_model_examples`, allocation/disposition/reconstruction tests. The list stays scoped; each slice adds its guards.
- **Frontend CI**: new **blocking** step `npx vitest run --config vitest.config.ts $(cat scripts/ci-blocking-tests.txt)` — a named subset (consumer card/title, badge specimen, review pages, date helpers, i18n parity, mutation payload guards) that must be green; typecheck/lint stay per-file non-blocking with the documented baseline; touched files must not appear in the "new over baseline" diff.
- **Playwright lifecycle spec**: runs locally per slice and is recorded in the ledger; CI wiring needs a second checkout of `trazo-back` (cross-repo token) — task for Oscar; until wired, the ledger states "Playwright: local only".
- **Export**: manifest test (cheap) + reconstruction test (B4) both blocking.
- **Baseline honesty**: the 33 known-red vitest files and stale backend fixture suites are listed in the ledger with classification; not fixed here unless touched.

## 8. First implementation slice for approval — S0 + A1a + A2

- **S0**: baseline as above (read + test runs only; isolated DB; logs to files under the ledger's `baseline/`).
- **A1a + A2** exact files: `trazo-back/history/serializers.py` (public dicts ×8, `PublicHistorySerializer` owner-only set, allow-lists, sensitive substrings), `history/transparency_views.py:596-602`, `history/services/privacy.py`, `history/views.py` (amend GET), `certifications/services/consumer_claim_validator.py`, `history/services/claim_resolver.py`, fixtures `_calapooia_bend_data.json` / `_loewen_base.py` / `backfill_demo_claim_safety.py`, new tests `test_public_response_schema.py`, `test_seeders_never_stamp_oid.py`, `test_event_amend_permissions.py`, extended `test_public_serializer_leakage.py`, `test_public_claim_fabrication.py`; `trazo-app`: `eventDescriptions.ts`, `ConsumerEventCard.tsx:550`, `HarvestInfoCard`, `CertificationBadge.tsx`, `TrustSummaryHeader.tsx`, `FarmModal.tsx`, `ProductDetail.tsx` hero, `NewEvent.jsx` + `utils/supplierNameNudge.ts`, both locale files, vitest files; `trazo-landing`: `privacy-policy/page.tsx:517-533`, `faq-section.tsx:45`.
- **Validation**: backend touched suites + CI scoped list (isolated DB, logged); vitest touched + parity; local re-seed; curl the anonymous transparency and public_history payloads for River Block + carrot and assert the denylist; Playwright screenshots 375/1440 EN+ES of the River Block page showing the grey Specimen certification; landing diff reviewed. Ledger updated with results + the untested list (prod payload, real device).
- Touches staged files: `history/serializers.py`, `history/views.py`, `history/tests/test_public_serializer_leakage.py` — so **Oscar commits the staged set before A1a lands** (or A1a is committed on top and the staged diff is reviewed together).

## 9. Tracking files (created on approval)
`trazo-back/documentation/audits/E2E-AUDIT-2026-09/PLAN.md` (this document), `LEDGER.md` (per finding: status, decision refs, slices, files, validation results, remaining risks, next action; per slice: date, commit subject, evidence under `screenshots/`, `baseline/` logs), root pointer `~/dev/trazo/documentation/audits/E2E_AUDIT_2026-09-07.md`.

## 10. Deferred / rejected
Offline/sync, extraction, integrations, multi-grower (§14 #9–12); nav rewrite (§12); `WaterSource`; consumer reviews UI; real-device/offline tests; DB renames; positioning/WTP/interview claims — all recorded in the ledger as backlog or "customer evidence needed".

## 11. Approval record and held decisions (Oscar, 2026-09-08, second review)

**Approved to implement now:** S0 (baseline), then A1a and A2, with these first-slice corrections:
- **Separate audience contracts.** Three schemas, three permission tests: (1) anonymous — `/api/transparency/<uuid>/` and non-owner `/histories/<uuid>/public_history/`; (2) buyer-token view of an unpublished season; (3) certifier-link metadata/readiness. An authorised certifier may legitimately receive fields the public page must not; no single universal denylist.
- **No false-positive privacy tests.** Payload assertions run against a **published** fixture that returns 200; unpublished-anonymous ⇒ 404 is a separate access test and proves nothing about field filtering.
- **Privacy wording matches the safeguard.** Supplier-name detection is described as exact-match, supplemental, and explicitly not exhaustive; the copy never says supplier names "are removed" from notes unconditionally.
- **Interim date fix (A4) stays narrow** and is not in this slice: when it lands, tests must cover save-without-change and deliberate time change, including seconds where applicable; a helper's name is not evidence.
- **Playwright local-only is a release condition**: a passing local run against the exact release revision is required until CI wiring exists.

**Held pending targeted revision (do not implement):**
- **D11 (operation timezone)** — the draft contradicted itself ("stored instants unchanged" while reinterpreting `14:30Z` as 14:30 local). Required before any proposal: an inventory of every date-writing path (forms, edit path, voice, templates, COG Pro import, seeders, API) with representative stored values; separate treatment of confirmed-UTC instants vs confirmed legacy wall-clock-labelled-UTC values; explicit "intended time unknown" for historical rows that cannot be classified; per-farm timezone confirmation (multi-zone states, non-US farms); calendar-only dates (certificate expiry, purchase date, sale date) handled separately. **No blanket reinterpretation of historical timestamps.**
- **D10 (inventory model)** — processing must be a **batch with input and output quantities and product condition** (e.g. 50,000 lb wet in → 22,000 lb dry out + documented loss/byproduct/unresolved difference), not a unit-change trigger; the walnut example must assert closing inventory at **both** locations including what happened to the wet input; any missing conversion or over-allocation makes the status **"not reconciled"**, never a warning beside a definitive-looking balance.
- **B3 (evidence links)** — replacing a file must create a **new document version**; existing links and review decisions keep their original version; linking/reviewing the replacement is a separate attributable action; the original file stays retrievable. A hash detects difference; it does not recover an overwritten file.
