# E2E Audit 2026-09 — Progress Ledger

Companion to `PLAN.md`. One row per finding; one entry per slice. Update at every completed slice.
Status: `open` · `in progress` · `done` · `blocked` · `deferred` · `rejected`. Decisions are D1–D11 in PLAN.md §5/§11.

## Findings

| ID | Title | Status | Decision refs | Slices | Changed files | Validation | Remaining risk | Next action |
|---|---|---|---|---|---|---|---|---|
| T01 | Public disclosure vs free text | **done (A1a)** | D1 | A1a ✅, A1b (next) | `history/serializers.py`, `history/services/privacy.py`, `history/views.py`, `trazo-app` consumer + i18n, landing privacy/FAQ | 23 schema tests + 196 privacy/claim tests + live payload | supplier match is exact-only, stated in the copy; `private_note` field still to come (A1b) | A1b after Oscar commits staged set |
| T02 | Demo shows USDA "Verified" | **done** | D2 | A2 ✅ | `consumer_claim_validator.py`, `certifications/serializers.py`, `claim_resolver.py`, 2 fixtures, 3 badge components | 11 specimen tests + live page shows "Specimen record, not checked against any registry" | "Certified Organic" pillar still renders for a specimen, qualified by the DEMO FARM chip and the specimen disclaimer — noted, not in T02's scope | — |
| T03 | Allocation & remainder | blocked | D10 (held) | B2 | — | — | model revision required (processing batch) | D10 rev. |
| T04 | Review link "no longer available" | open | — | A3 | — | — | root cause unestablished | A3 |
| T05 | Daily forms | open | — | C1, C2 | — | — | — | C1 |
| T06 | "On file" vs attached | blocked | B3 (held) | B3 | — | — | versioning design required | B3 rev. |
| T07 | Purchase counted twice | open | — | B-design, B1 | — | — | — | B-design |
| T08 | Dates | blocked | D4, D11 (held) | A4-interim | — | — | timezone inventory required | A4-interim |
| T09 | OSP completion conflation | open | — | D1-OSP | — | — | — | order 6 |
| T10 | Consumer prose | open | — | E1 | — | — | — | order 6 |
| T11 | Carbon boundary copy | open | — | A5, E2 | — | — | — | order 3 |
| T12 | Export scope | open | — | A5, B4 | — | — | — | order 3 |
| T13 | Density / i18n | open (tour keys done in staged work) | D6 | C3 | — | — | — | order 6 |
| T14 | Production count | open | — | A5 | — | — | — | order 3 |
| §6 retention cite / wording | blocked | D9 (needs Oscar) | — | — | — | legal page | D9 |
| §9 grade/method public | **done** | D5 | A1a ✅ | `transparency_views.py`, `HarvestInfoCard.tsx` | live page: "US Fancy", "Quality", "Harvest Method" all absent | — | — |
| §4 amend GET permission parity | **done** | — | A1a ✅ | `history/views.py` | 4 tests (admin 200 / viewer 403 read + write / anon) | — | — |
| §16 late entry | open | — | D3 | — | — | migration | order 6 |

## Untested / blocked environments
- Production payloads and prod review-link behaviour: not checked (no prod access by design). Oscar runs one check after deploy.
- Real phone devices, offline: not tested; Playwright viewports only.
- Playwright: local runs only until CI wiring (cross-repo token) — **release condition**: a passing local run against the exact release revision.

## Slice log

### S0 — Baseline (2026-09-08)
- Started. Staged-work boundary: `trazo-back` 87 staged files on `chore/remove-dead-ec2-deploy`; `trazo-app` 37 staged files on `chore/producer-analytics-posture`; `trazo-landing` clean. Oscar commits the staged sets; no migration is numbered before that.
- Another session was running `manage.py test certifications` at start; all runs here use `DATABASE_NAME=trazo_e2e_a|b`.
- Logs: `baseline/*.log`.

**Backend baseline (current tree, staged work applied, isolated DBs):**

| Suite | Result |
|---|---|
| CI scoped claim-safety/compliance list | Ran 590 — **OK** |
| `certifications` | Ran 1132 — **OK** (8 skipped) |
| `subscriptions` | Ran 241 — **OK** |
| `product` | Ran 165 — **OK** |
| `company` | Ran 84 — **12 errors** |
| `history` | Ran 1674 — **11 red** (4 failures, 7 errors) |

Classification of every red:
- `company.tests.test_models` (12) — **stale fixture**, all in one module, matches the 2026-09-07 per-app baseline note. Not touched by this slice.
- `history.tests.test_enhanced_scans` (10) — **stale fixture**, one module (bot detection / dedup / GDPR anonymisation thresholds). Not touched by this slice.
- `history.tests.test_claim_authority_certification_types.test_carbon_neutral_is_withheld` (1) — **caused by staged work and demanding the wrong rule**: the committed assertion pinned `260.6` while the staged sweep correctly moved general-environmental-benefit citations to **260.4** (260.6 governs certifications and seals). This one sits inside the claim-safety area A1a/A2 change, where a red guard would mask a real regression, so it was corrected as part of S0 — assertion now requires `260.4` and forbids `260.6`. Verified: 10 tests OK.

**Frontend baseline:** vitest **2127 passed / 8 skipped**, **5 files failed to run** (RTK Query harness: `TypeError: RequestInit: Expected signal ("AbortSignal {}") to be an instance of AbortSignal` — a jsdom/undici mismatch in the test environment, not product code). Typecheck **815 total (baseline 1040), 8 NEW over baseline in 5 files**. Lint **1099 total (baseline 3753), 8 NEW in 5 files**. None of the new typecheck/lint errors is in a file this slice touches; all are pre-existing in already-committed or staged work and are not fixed here.


### A1a + A2 — public trust contract (2026-09-08)

**What changed**

*Backend*
- `history/serializers.py` — new `_public_event_label(event, family_default)`: the public event `description` is now a controlled subtype label (`get_type_display()`), never stored prose. The KEY is kept for older deployed SPA builds. All 8 families swapped.
- Same file — the 10 remaining raw prose keys (`name` ×4 bare + 2 variants, `activity_type`, `activity_name`) now route through `_public_event_text`, i.e. vendor redaction. They previously bypassed it entirely: the sibling-surface class.
- `_OWNER_ONLY_FIELDS` += `description` (the season note). `ALLOWED_EXTRA_DATA_KEYS` − `seed_lot_number`; `EXTRA_DATA_SENSITIVE_SUBSTRINGS` += `lot_number`. Write-side `extra_data_only_fields` untouched, so the field still round-trips to the certifier.
- `history/services/privacy.py` — `redact_own_vendor_names(text, event, extra_names=())` now also reads `EXTRA_DATA_VENDOR_KEYS` and an establishment-wide supplier registry (`establishment_supplier_names`, 4 `values_list` reads, stamped once per payload by `get_events`).
- `history/transparency_views.py` — `harvestDetails` drops `quality_grade` and `harvest_method` (D5).
- `history/views.py` — `_require_amend_permission` extracted and applied to BOTH methods of `EventViewSet.amend`.
- `certifications/services/consumer_claim_validator.py` — `ConsumerClaimResult.specimen`, `DISCLAIMER_SPECIMEN`, `oid_matched` forced False for a specimen, new `consumer_certification_status()` chokepoint.
- `certifications/serializers.py` — `ConsumerCertificationSerializer.status` now goes through that chokepoint; adds `specimen`.
- `history/services/claim_resolver.py` — claim `source` names the demonstration data instead of a registry or a certificate.
- Fixtures `_calapooia_bend_data.json`, `_loewen_base.py` — stop stamping the OID verification source.

*Frontend*
- `eventDescriptions.ts` — tolerates an absent seed; the weather branch is entered by subtype CODE, not by keyword (a `DR`/`HW` record with empty temperature fields used to fall out of the branch entirely).
- `HarvestInfoCard.tsx` — grade and method render branches removed.
- `CertificationBadge.tsx` (4 label sites), `FarmModal.tsx` — a specimen reads "Specimen record, not checked against any registry", never green, never "Reported by Producer".
- `observation` relabelled **Public note** across all 8 tabs + finish form, both locales; finish-form notes labelled "for your certifier and your team. Not shown on your buyer page."
- New `utils/supplierNameNudge.ts` + a write-time hint in the chemical form.

*Landing* — privacy policy and FAQ describe supplier withholding as fields-plus-an-exact-match safeguard, with a new paragraph on the public/private note split. No guarantee language.

**Validation**

| Check | Result |
|---|---|
| CI scoped list + new guards | **514 tests OK** |
| `certifications` (full) | **1132 OK**, 8 skipped |
| `history` (full) | **1715 tests, 10 red — all the pre-existing stale `test_enhanced_scans` module.** Baseline was 1674 tests / 11 red; the count rose by exactly the 41 tests added here and the 11th red (the stale `260.6` citation) was fixed in S0. **Zero new failures.** |
| New `test_public_response_schema` | 23 OK (3 audience contracts) |
| New `test_specimen_claim_neutralised` | 11 OK |
| New `test_seeders_never_stamp_oid` | 3 OK |
| New `test_event_amend_permissions` | 4 OK |
| Existing privacy/claim suites | 196 OK |
| Frontend vitest (consumer scope) | 725 OK across 57 files |
| New vitest: subtype seed / specimen badge / nudge | 18 + 4 + 9 OK |
| `formRenderConformance` (forms still mount) | 65 OK |
| Typecheck gate | **815 total, new-error list byte-identical to baseline** |
| Backend `format.sh` | Black + isort + flake8 PASSED |
| Live anonymous payload, unreseeded DB | see below |
| Consumer page 375/1440 × en-US/es-419 | 0 banned strings, 0 page errors, no horizontal scroll |

**Live verification — the audit's own season, on the UNRESEEDED database.**
`GET /api/transparency/d5988069-.../` (Liberty 2026 — River Block, Calapooia Bend Farm, 57 events, HTTP 200):
- forbidden keys (supplier/invoice/`_lot_number`/purchase order/BOL): **none**
- `verified_via_database` anywhere in the payload: **absent** — and the database still holds that
  certificate with `verification_status=verified`, `verification_source=usda_organic_integrity_db`,
  `consumer_display_status=verified_via_database`. This is the runtime safeguard working on legacy
  data with no re-seed, which is what the fixture correction alone could not do.
- `organic_claim.specimen=True`, `oid_matched=False`; both certs `self_reported` + `specimen=True`
- `harvestDetails` keys: `amount`, `lot_number`, `unit` only
- season note (`description`) absent from `/public_history/`; event titles are clean subtype labels
  ("Frost", "Drought", "Fertilizer", "Harvesting", "Irrigation", "Mowing / Orchard-Floor", …)
- rendered page carries "Specimen record, not checked against any registry" and the DEMO FARM chip;
  "Verified via", "US Fancy", "Quality", "Harvest Method" all absent
- performance: 30 queries, 0.08 s for the whole payload; the supplier registry is 4 of those

**Known limitations / not verified**
- Production payloads and prod review-link behaviour: not checked (no prod access). Oscar's call after deploy.
- Real devices and offline: not tested; Playwright viewports only.
- Playwright: local only, no CI wiring yet (needs a cross-repo checkout token).
- The consumer trust pillar still renders "Certified Organic" for a specimen operation, qualified by
  the page-level DEMO FARM chip and the specimen disclaimer. Suppressing the label itself is a
  separate product decision, not part of T02's "Verified" finding.
- The page-foot disclosure still reads "Certifications are labeled separately as Verified or
  Self-Reported"; there is now a third label. One-line copy follow-up.
- `A1b` (`CommonEvent.private_note`, one additive migration) is deliberately NOT in this slice: it
  must be numbered after the staged migration 0234, which Oscar commits.

**Migrations:** none in A1a or A2.


### Fresh-eyes review of the A1a/A2 change itself (2026-09-08)

Re-read every line written or modified in the slice. **Six defects found in my own work, all fixed**, plus two pre-existing ones confirmed as not-mine and left alone.

**1. Prose aliases shipped raw beside the key they alias.** `name` was routed through vendor redaction on all eight families, and three siblings carrying the identical value were missed: `operation_name` (equipment, "Frontend compatibility alias"), `soil_management_name` (soil, "Compatibility with TimelineService"), and the weather family's `name`, which is read from `extra_data` and so did not match the pattern the other seven were fixed by. **This is the exact sibling-surface class the slice exists to close, reproduced inside the fix for it.** Guard: `ProseAliasKeysAreRedactedTests`, mutation-verified.

**2. `extra_data` string VALUES were never vendor-redacted.** The allow-list and substring guard both gate KEY NAMES. Caught by the new test as two adjacent values on one weather record:
```
"name":                  "Frost watch called by [supplier withheld]"
"extra_data.event_name": "Frost watch called by Hydra-Gardens Inc."
```
Fixed in `_sanitize_extra_data_for_public`'s `scrub_nested`, length-gated (>3 chars) so it stays cheap. Measured after: 27 queries, 0.047 s for the 57-event season.

**3. Redaction was non-deterministic and leaked a supplier's address.** Substitution ran inside the per-name loop, so the result depended on the order names arrived in — and the operation-wide registry is a `frozenset`, whose iteration order varies with `PYTHONHASHSEED` between processes. Reproduced across five seeds: the same note rendered as `"[supplier withheld] this year."` on some workers and `"[supplier withheld], Wolcott VT this year."` on others, stranding the supplier's city and state on a public page. Now one pooled, longest-first pass. Guard: `RedactionIsDeterministicTests` (asserts every permutation yields one output).

**4. A privacy fix for anonymous readers degraded the producer's own view.** `_public_event_label` replaced the title for *everyone*, and `ProfileProduction` — the grower's own season page — reads the same `/public_history/` endpoint. Now viewer-aware: the owner keeps the stored text, non-owners (including `force_public_view` previews) get the label. Two guards pin both directions.

**5. A live establishment-profile leak, found while verifying.** Event prose was redacted correctly while the farm's own profile published `farmer.soil_types: [... "Purchased OMRI compost (Rexius)" ...]` — a real supplier on the same page. `soil_types`, `water_sources` and `irrigation_methods` reached the wire with **no scrubber at all**; `about`/`main_activities`/`location_highlights`/`custom_message` went through `public_free_text`, which polices claims and has never known a vendor name. Fixed with a shared `_redact_names` core + `redact_supplier_names`, wired into all seven fields. The practice statement survives, only the name goes: `"Purchased OMRI compost ([supplier withheld])"`. Guard: `EstablishmentFreeTextIsVendorRedactedTests`.

**6. A lookbehind regex that would crash the form on Safari < 16.4.** `supplierNameNudge.ts` built `(?<!\w)` at runtime; `vite.config.ts` targets `safari13.1`, and a RegExp built from a string is never transpiled, so it would throw a `SyntaxError` inside the component's render. It was the only lookbehind in `src/`. Replaced with the portable `(^|\W)` + lookahead. Guard asserts the source contains no `(?<`.

**Also corrected in my own work:** a comment claiming a weather-branch defect that never existed (`hasSpecificWeatherType` already covered it) — the redundant guard was removed rather than shipped with a false rationale; a false measured figure in a memoisation comment (said "12 queries where 4 will do"; the 12 was my own miscount of event SELECTs that merely list supplier columns); the `never` type trick on `HarvestDetails` replaced with honest removal, plus two orphaned icon imports and a dead `humanize` helper; a misplaced JSX comment; and `manufacturer` dropped from the supplier nudge, because `privacy.py` deliberately excludes it as legitimate public product information — warning about it would have told farmers to remove something Trazo publishes on purpose. The nudge also moved into its own `useWatch` component: a top-level `methods.watch` re-rendered the ~5,600-line chemical form on every keystroke.

**Confirmed pre-existing, left alone:** `Card`/`CardBody` unused imports in `HarvestInfoCard` (in its lint baseline) and an unused `User` import in `_loewen_base.py` (present in the committed version).

**Mutation verification.** Disabling the specimen check → 4 failures. Un-redacting the `soil_management_name` alias → 4 failures. Re-adding `seed_lot_number` to the allow-list alone → still green, because the `lot_number` substring guard independently blocks it; disabling **both** controls → 4 failures. Defence in depth confirmed working rather than a toothless test.

**Post-review validation (final clean run against the reviewed tree):** `history` + `certifications` **2857 tests, 10 red** — all the pre-existing stale `test_enhanced_scans` module, zero regressions. Frontend 1284 tests across 105 files, all green. Typecheck and lint new-error lists byte-identical to baseline. `format.sh` clean. Live payload re-verified: no forbidden keys, no supplier names, no `verified_via_database`.
