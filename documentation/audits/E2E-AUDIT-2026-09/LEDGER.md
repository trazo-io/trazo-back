# E2E Audit 2026-09 — Progress Ledger

Companion to `PLAN.md`. One row per finding; one entry per slice. Update at every completed slice.
Status: `open` · `in progress` · `done` · `blocked` · `deferred` · `rejected`. Decisions are D1–D11 in PLAN.md §5/§11.

## Findings

| ID | Title | Status | Decision refs | Slices | Changed files | Validation | Remaining risk | Next action |
|---|---|---|---|---|---|---|---|---|
| T01 | Public disclosure vs free text | **done (A1a)** | D1 | A1a ✅, A1b (next) | `history/serializers.py`, `history/services/privacy.py`, `history/views.py`, `trazo-app` consumer + i18n, landing privacy/FAQ | 23 schema tests + 196 privacy/claim tests + live payload | supplier match is exact-only, stated in the copy; `private_note` field still to come (A1b) | A1b after Oscar commits staged set |
| T02 | Demo shows USDA "Verified" | **done** | D2 | A2 ✅ | `consumer_claim_validator.py`, `certifications/serializers.py`, `claim_resolver.py`, 2 fixtures, 3 badge components | 11 specimen tests + live page shows "Specimen record, not checked against any registry" | "Certified Organic" pillar still renders for a specimen, qualified by the DEMO FARM chip and the specimen disclaimer — noted, not in T02's scope | — |
| T03 | Allocation & remainder | blocked | D10 (held) | B2 | — | — | model revision required (processing batch) | D10 rev. |
| T04 | Review link "no longer available" | **done (A3)** | — | A3 ✅ | `certifications/views.py`, `backend/settings/{base,dev}.py`, `utils/reviewLinkFailure.ts`, both review pages, both link cards, `config/environment.ts` | 13 backend + 21 frontend + live lifecycle probe (200 → cross-audience 404 → revoked 404) | root cause of the original observation still unestablished; browser lifecycle spec SKIPS on the E2E farm (readiness blocker) | — |
| T05 | Daily forms | **partly done (C1)** | — | C1 ✅ (gating), C2 (core/more split) | `ChemicalTab-ENHANCED.jsx`, `ProductionTab.jsx`, `config/harvestMaturity.ts`, `StandardFinishProductionForm.tsx` | 3 + 13 + 4 tests, all mutation-verified; season-close stuck state reproduced in a browser then fixed | the "More details" collapse and repeat/recent affordances are C2, not done | C2 |
| T06 | "On file" vs attached | blocked | B3 (held) | B3 | — | — | versioning design required | B3 rev. |
| T07 | Purchase counted twice | open | — | B-design, B1 | — | — | — | B-design |
| T08 | Dates | **partly done (A4-interim)**; rest blocked | D4, D11 (held) | A4-interim ✅ | `eventDescriptions.ts`, link cards (in A3) | 9 + 5 tests across 3 timezones | consumer-day rendering still waits on D11; **one claimed defect RETRACTED** (see below) | D11 |
| T09 | OSP completion conflation | open | — | D1-OSP | — | — | — | order 6 |
| T10 | Consumer prose | open | — | E1 | — | — | — | order 6 |
| T11 | Carbon boundary copy | open | — | E2 | — | — | wording is E2's, not A5's | order 6 |
| T12 | Export scope | copy done, data open | — | A5 ✅, B4 | `gating.py`, `pricing/page.tsx`, `contact-client.tsx`, `cog-pro-migration/page.tsx` | build + tsc clean; no stale claim left on the site | ZIP still omits sales↔harvest M2M, amendments, OSP tables (B4) | B4, order 5 |
| T13 | Density / i18n | open (tour keys done in staged work) | D6 | C3 | — | — | — | order 6 |
| T14 | Production count | done | — | A5 ✅ | `company/models.py`, `subscriptions/serializers.py`, `test_creation_limits.py` | 29 subscriptions tests; mutation-verified (old query fails 4 of 5) | none | — |
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
- Raw run logs (`baseline/*.log`) and the render screenshots (`screenshots/*.png`) are kept
  LOCAL and deliberately not committed: ~5 MB of point-in-time binaries that git would carry
  in every clone forever, stale on the next commit, and unreadable in a review. Every number
  they establish is transcribed inline below, which is what a later reader actually needs.

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

**Frontend baseline:** vitest **2127 passed / 8 skipped**, **5 files failed to run**. ⚠️ **CORRECTED 2026-09-08:** I first attributed these to an RTK Query `AbortSignal` harness error visible in the log. That was wrong. The five were the **Playwright specs under `e2e/`**, which vitest was collecting and which throw "Playwright Test did not expect test() to be called here". They were never product failures, and the `AbortSignal` line is unrelated noise. `vitest.config.ts` now excludes `e2e/**`, and the suite reports **205 files passed, 0 failed**. A gate whose headline number is phantom failures is one people learn to read past. Typecheck **815 total (baseline 1040), 8 NEW over baseline in 5 files**. Lint **1099 total (baseline 3753), 8 NEW in 5 files**. None of the new typecheck/lint errors is in a file this slice touches; all are pre-existing in already-committed or staged work and are not fixed here.


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


### A3 — Review-link lifecycle (2026-09-08)

**The finding was never reproduced, and the fix does not depend on reproducing it.** The audit
watched a link fail minutes after creation while its own card showed it active. What was
provable is that the page *could not tell a dead link from a transport failure*: a 404, a 429, a
502 and a blocked CORS preflight all rendered as "This link is no longer available … It may have
expired or been withdrawn." The page was asserting a fact about the grower's intent from an
unclassified error. Three contributing causes were found and closed.

**What changed**

- **Only a 404 may say the link is gone.** New `utils/reviewLinkFailure.ts` classifies a failure
  as `gone` (404 only) or `temporary` (everything else, including a rejection with no status).
  Both review pages branch on it, with new copy in both locales. The server's deliberate
  404-for-expired-and-revoked contract is unchanged — an anonymous caller still cannot probe
  which.
- **The review pages left the shared anonymous throttle bucket.** They were on the default
  `anon` scope at 50/hour, and one page load costs TWO requests (metadata + readiness) — 25
  loads an hour for everyone behind one NAT, which is what a certifier's office is. New
  `certifier_review` scope at 240/hour in `base.py`, 10000/hour in `dev.py` (which redefines the
  whole rates dict rather than extending base — a scope added to base alone breaks dev).
  ⚠️ Throttling is inert in production today (`DummyCache` without `REDIS_URL`); this is what
  makes the pages survive Redis being switched on, and the 429 handling above is what stops
  that day being reported as revoked links.
- **A refusal now leaves a trace.** `_resolve_link_or_404` logs a WARNING naming the audience
  and the reason (`expired` / `revoked` / no match), with a **SHA-256 fingerprint, never the
  token** — a log line carrying the token is a second copy of the credential.
- **`API_ROOT_URL` honours `VITE_APP_BACKEND_URL`.** It hardcoded `http://localhost:8000` in
  development while `getApiBaseUrl()` honoured the env var, so anyone running the backend
  elsewhere (a LAN address for phone testing, a tunnel) had the review pages *alone* fail their
  preflight — and render that as a revoked link.
- **Two date defects on the link cards.** `periodDates()` built its bounds via
  `new Date(y, 0, 1).toISOString()`, so east of Greenwich the review window was sent to the
  certifier starting **31 December of the previous year** (measured in Europe/Madrid:
  `2025-12-31 → 2026-12-30`). And `expires_at` / `last_accessed_at` are DateTimeFields being
  formatted with `formatDateOnly`, whose `YYYY-MM-DD` pattern does not match an ISO datetime, so
  they fell through to local-zone rendering: an expiry of `2026-12-31T00:00:00Z` showed as
  "Dec 30" for every US grower. Both fixed; `formatDateFromTimestamp` is the correct helper and
  now used.
- **`?audience=` filter** on the management list, fail-open on an unknown value. **The cards
  were deliberately NOT rewired to use it**: both render from one shared cache entry and split
  client-side, the split is not a security boundary (cross-audience is a server-side 404), and
  filtering per card would double the requests for no gain. The parameter is tested and stays
  for future consumers.

**Validation**

| Check | Result |
|---|---|
| `test_review_link_diagnostics` (new) | 13 OK — throttle scope, rates in both settings modules, endpoint enumeration, log reason/fingerprint, audience filter |
| `test_certifier_access_links` + `test_buyer_review_links` + anonymous inventory + door inventory | 69 OK |
| `reviewLinkFailure` + `reviewLinkFailureStates` (new) | 21 OK — both pages × 404 / 429 / 5xx / network / healthy |
| `reviewPeriodDates` (new, run under `TZ=Europe/Madrid`) | 5 OK |
| Frontend affected suites | 748 OK across 55 files |
| Typecheck / lint gates | new-error lists byte-identical to baseline |
| `format.sh` | PASSED |

**Mutation verification.** Reverting the classifier to "every failure is gone" (the old
behaviour) fails **15** tests. Restoring the `toISOString()` implementation of `periodDates`
fails **2** under `TZ=Europe/Madrid` and **0** under `America/Los_Angeles` — which is exactly why
it survived: the ICP is American.

**Live lifecycle, exercised against the dev server** (probe link created and deleted afterwards):
active link → **200** carrying exactly the eight allowed metadata keys and the right operation;
the same token on the buyer route → **404**; after `revoke()` → **404**.

**Untested / limitations**
- The **browser** lifecycle spec (`e2e/05-review-link-lifecycle.spec.ts`) **skips** on the E2E
  farm: minting is disabled there by an open readiness blocker, which is correct product
  behaviour (`perform_create` refuses to mint over one). Its sibling test — an unknown token is
  refused and never reported as transient — **passes**. The lifecycle itself was proven
  server-side instead, as above.
- Playwright still runs locally only; no CI wiring.
- Production behaviour unverified (no prod access). The throttle scope only takes effect once
  `REDIS_URL` is set.


### A4-interim + C1 — dates and form scoping (2026-09-08)

**A defect I claimed does not exist, and I retracted it rather than "fixing" it.** The plan
asserted that the edit path re-dates records, because `NewEvent.jsx` seeds its `datetime-local`
input with `new Date(existingEvent.date).toISOString().slice(0, 16)`. Measured in
America/Los_Angeles, Europe/Madrid and Pacific/Auckland: **the round trip is stable**. Trazo
stores a datetime as the grower's WALL CLOCK labelled UTC, so the UTC wall clock IS what the
farmer typed and IS what the input should show. `nowLocalDateTimeInput()`'s docstring warns
against that expression for seeding **"now" on a CREATE** — a different case, already fixed —
and applying it to the READ path would have introduced exactly the offset shift it describes.
Now PINNED by `eventDateRoundTrip.test.ts` (save-with-no-change, a deliberate time change, a
midnight boundary, and the seconds the input type drops) so the change is not made later by
someone reading that docstring. I nearly made it myself.

**What was genuinely wrong and is fixed**
- `formatEventDate` used `Math.abs` on the difference, so a FUTURE-dated event read "3 days
  ago" — and Trazo accepts future dates (a planned application, a post-harvest record dated
  after the season closed). Its ≥365-day fallback also called `toLocaleDateString()` with
  neither locale nor time zone, rendering a stored UTC wall clock in the viewer's zone.
- **The season-close stuck state, REPRODUCED and closed.** The audit left it open: "Test form
  values entered; Continue remained disabled; session reset before cause resolved." Reproduced
  in a browser: `finish_date` is a `datetime-local`, and a browser reports an **empty value
  until both halves are complete**, so a farmer who types the date and tabs away sees
  "09/08/2026" sitting in the field while `value === ''`. Every field looks filled, Continue
  stays disabled, nothing says which one. The form now names what is still needed — measured
  before/after: `Still needed: Production amount, Lot Number, Finish date` → after typing the
  date half only, `Still needed: Finish date` → none once complete. ⛔ The input TYPE is
  deliberately unchanged: that would alter what `History.finish_date` stores and belongs to D11.
- **The California DPR permit block is state-gated.** It was keyword-only, on a ten-word list
  containing `sulfur`, `spinosad`, `entrust` and three coppers — ordinary organic inputs — so an
  Oregon grower was shown a California county Restricted Materials Permit section asking for a
  permit number, county and expiry that cannot apply to them. Now `farmState === 'CA'` AND the
  keyword, matching how the sibling PUR identity block has always been gated. Fails closed on an
  unknown state.
- **Harvest maturity fields are crop-scoped.** New `config/harvestMaturity.ts`: grain moisture,
  Brix and dry matter now render only for crops that have them, reusing the existing
  `CROP_GRADE_FAMILY` groups and naming avocado explicitly (it sits in the `none` GRADE family
  because it has no USDA grade standard, while dry matter is precisely its maturity test — so
  deriving from grade family alone would have dropped the crop the audit named). **Unmapped
  crops keep all three**: hiding a measure on a crop the table has not heard of would silently
  drop a measurement the grower needs, and the audit's complaint is about crops we DO know.

**Validation**

| Check | Result |
|---|---|
| `harvestMaturity` (new) | 13 OK — carrots get none, avocado gets dry matter only, unknown crops keep all three |
| `caPermitIsStateGated` (new) | 3 OK — CA sees it, Oregon does not, unknown state does not |
| `finishFormNamesMissingFields` (new) | 4 OK |
| `eventDateRoundTrip` (new, × 3 timezones) | 9 OK each |
| `formRenderConformance` | 50 OK (unmapped crop keeps all three fields, so the field-coverage guard is unaffected) |
| **Whole frontend suite** | **205 files, 2216 tests, 0 failures** |
| Typecheck / lint gates | new-error lists byte-identical to baseline; lint total **1097**, below the 1098 it started at |

**Mutation verification.** Removing the CA state gate fails 2 of 3. Restoring `Math.abs` fails 1.
(The A3 mutations — classifier and `periodDates` — are recorded in the A3 entry.)

**Not done in C1, deliberately:** the "More details" collapse for the FSMA review block, the
irrigation lab-test trio and `*_efficiency` is the core/more-details split, which is C2's scope
and a larger UI change. `*_efficiency` still needs E2's finding on whether the carbon calculator
reads it before it is moved or removed.


### Order-3 close-out (2026-09-08)

**Final backend regression:** `certifications` + `history` + `subscriptions` — **3111 tests, 10
red**, all the pre-existing stale `test_enhanced_scans` module. Zero regressions across A3,
A4-interim and C1. `format.sh` PASSED.

**⚠️ The tree was NOT hermetic for that run.** Another session was editing this working copy at
the same time: `carbon/views.py` (14:06), `carbon/services/blockchain.py` (14:13),
`.github/workflows/ci.yml` (14:14), six deleted blockchain service modules and their tests, and
`trazo-app/src/store/api/carbonApi.ts` — none of them mine, none touched by me. My run started
14:38, so it included their in-flight work. The suites I ran are largely independent of
`carbon`, and the only reds are the known stale module, but a passing run is only evidence about
the tree it ran against. Their files are listed here so the two changesets can be separated
before either is committed.

**Frontend gate correction, worth carrying forward:** `vitest.config.ts` now excludes `e2e/**`.
The suite had been collecting the Playwright specs and counting each as a failed suite, which is
where the "5 files failed" in the S0 baseline came from — never product code. The frontend suite
now reports **205 files passed, 0 failed, 2216 tests**.

**Still open in order 3:** A5 (landing export FAQ + stale gating comments + the T14 production
meter) was not started. C1's "More details" collapse belongs to C2.


### Fresh-eyes review of the order-3 work (2026-09-08)

Nine findings in my own A3 / A4-interim / C1 code. Two were substantive.

**1. I quietly quadrupled the rate ceiling on the most expensive route in the product.** Moving
the review endpoints onto the new `certifier_review` scope (240/hour) swept
`certifier_review_dossier` along with them. That endpoint streams a PDF that takes ~a minute to
build on a 12-production farm and pins a gthread worker while it does — the scope existed
because cheap LANDING pages cost two requests each, and applying it there was a side effect, not
a decision. Reverted to the tighter shared default, with a test pinning that the expensive route
stays off the landing scope. Both directions mutation-verified.

**2. An unsourced agronomy claim in a gating table.** `harvestMaturity.ts` narrowed EVERY mapped
grade family and asserted `olives: { dryMatter: true }` on no evidence whatsoever. Narrowing an
`olive`, `date` or `fig` grower's form is hiding a field on a guess — the same failure the change
exists to remove, pointed at a different farmer. Now only families whose profile is settled are
narrowed (the sugar-measured fruits, grain, tree nuts, and the root/leafy families the audit
itself names); everything else keeps all three measures. The invented olive claim is gone.

**3. A data-loss risk I verified instead of assuming — and my first check was wrong.** Both C1
gates hide inputs, so if react-hook-form dropped unmounted fields from the payload, opening an
existing record and saving it would erase a Brix reading or a permit number. My first probe
asserted synchronously after clicking submit, while `handleSubmit` is async: it reported every
field as `undefined` and read exactly like the data loss I was looking for. Corrected with
`waitFor`: RHF 7.43.5 with `shouldUnregister` at its default keeps unmounted values, for both
`Controller` and `register`. Pinned by `hidingAFieldKeepsItsValue.test.tsx`, because the
invariant is a property of the FORM CONFIG — setting `shouldUnregister: true` later would turn a
cosmetic improvement into silent data loss with nothing else failing.

**Also fixed**
- My dossier-throttle guard failed on its **own explanatory comment**, because it asserted the
  class name was absent from the whole decorator BLOCK. Second time this session: a guard that
  forbids naming the thing it excludes makes the exclusion undocumentable. It now reads the
  `@throttle_classes([...])` decorator, not the prose around it.
- That same guard sliced a fixed character window before the `def`, which reaches back into the
  PREVIOUS endpoint's decorators — it would have reported a neighbour's scope as this one's and
  passed for the wrong reason. Now sliced from the nearest `@api_view`.
- The refusal logger did `import logging` inside the function and built its own logger, while
  `certifications/views.py` has had a module-level `logger` since line 60. Reuses it; `hashlib`
  hoisted to the imports.
- `e2e/05-review-link-lifecycle.spec.ts` littered: a failure between minting and revoking left a
  LIVE dossier link on the dev farm. Now wrapped in try/finally with an idempotent revoke
  through the authenticated API, so cleanup works even when the UI is what broke.
- The `{/* Step Navigation */}` comment in the finish form was orphaned from the code it labels
  by my hint block; `formatEventDate` carried a pointless `diffTime = signedMs` alias and a
  duplicated date-options object.

**Validation after the review fixes**
- Backend: review-link suites + anonymous-endpoint inventory + door inventory — **83 OK**;
  `certifications` + `history` full run below. `format.sh` PASSED.
- Frontend: **206 files, 2220 tests, 0 failures**. Typecheck and lint new-error lists
  byte-identical to baseline; lint total **1097**.
- Date tests re-run under America/Los_Angeles, Europe/Madrid and Pacific/Auckland: 27 OK each.
- Every i18n key added this slice is present, non-empty and genuinely translated in both
  locales; `spanishRegister` passes (my Spanish is usted, matching the neighbouring copy, and
  the guard is scoped to voseo markers).


### 🔴 OPEN FINDING — the specimen safeguard has a data gap (2026-09-08)

Found while widening the verification from one farm to all of them. **Not a code defect: the
code does exactly what it should for anything flagged.** The gap is that everything I built for
T02 keys on `Establishment.is_demo`, and the flag is opt-IN by design (marking a REAL operation's
packet "SPECIMEN" would invite a certifier to reject a legitimate filing — `common/specimen.py`
argues that at length, and it is right). Nothing audits whether fabricated operations actually
carry it.

**Measured on the local dev database:**

| | count | note |
|---|---|---|
| demo farms, flagged, published | 9 seasons / 5 operations | all clean: specimen marked, no `verified_via_database`, no grade key, no supplier keys |
| real operations with a verified badge | 2 | correctly keep it — `oid_matched: true`, `specimen: false` |
| **unflagged + published + serving a registry-verified badge** | **2** | `Dry Creek Home Ranch` (est 148), `Loewen Family Farm` (est 117) |
| unflagged + published, names containing test/demo/sample/example | 18 more | ~60 published seasons; no verified badge, so lower risk, but fabricated records on public pages with no specimen mark |

`_loewen_base.py` sets `is_demo = True` today, so est 117 predates the flag (added 2026-08-21)
and was never backfilled. Both operations currently serve
"Verified via USDA Organic Integrity Database" on an anonymous page from invented records — the
exact T02 shape, surviving as data rather than code.

**Deliberately NOT fixed here.** Which operations are real is a judgment call, not a heuristic:
flipping `is_demo` on a row that turns out to belong to a genuine prospect would stamp SPECIMEN
across their certifier packet. Two things are needed and both are Oscar's:
1. a decision on the local rows (and a re-seed or a targeted flag update); and
2. **the same census run against production**, which I have no access to. If the gap exists
   there, it is live on real consumer pages.

A read-only `audit_specimen_flags` management command — listing operations whose records look
seeded but are not flagged, writing nothing — is the proportionate guard. Not built without a
decision, because its heuristic would need to be reviewed before anyone acts on its output.

**Regression after the review fixes:** `certifications` + `history` — **2871 tests, 10 red**, all
the pre-existing stale `test_enhanced_scans` module. Zero regressions.


### A5 — meter/gate agreement and the export claim (2026-09-08)

**T14 — two numbers under one label.** `Company.can_create_production` counts `created_at` and
documents at length why `start_date` cannot gate billing (farmer-editable; NULL escapes
`start_date__gte`). The usage meter on the subscription payload ran its OWN query, on
`start_date__gte` — the very field that comment rules out. A season dated to last December, or
carrying no start date, was invisible to the meter and counted by the gate: the farmer reads
"1 of 2 used", creates one more, and is refused. `productions_created_this_year()` is now the one
authority and the meter delegates; the rationale moved with the query.

- Tests assert the two numbers AGAINST EACH OTHER, never a literal — a hardcoded "expect 2" passes
  equally on two independent queries that happen to agree on the fixture, which is how this
  survived: every pre-existing quota test exercises the gate alone.
- **Mutation-verified**: reintroducing the old query fails 4 of the 5 new tests.
- ⚠️ My first delegation guard asserted `"start_date" not in source` and failed on its own
  docstring. Now parses the AST and drops the docstring node. Second time this class has appeared
  in this audit — a guard that forbids NAMING what it removed makes the removal undocumentable.

**T12 (copy half) — a retraction that outlived its limitation.** `gating.py` justified its 403
wording with "Trazo has no plain data export at all". True when written; false from 2026-08-25,
when the free ungated `.../records-export/` shipped. That stale sentence was load-bearing: three
landing pages cited it in comments that FORBADE correcting them, and because those comments named
`hero.tsx` (which WAS corrected the same day) as the precedent, the omission read as deliberate.

The site therefore contradicted itself on its highest-intent page — `faq-section.tsx` "Yes, on
every plan including the free one" against `pricing/page.tsx` "a one-click export of your whole
account is not built yet".

- Fixed: `gating.py` 403 wording + comment, `/pricing`, `/contact`, `/cog-pro-migration`.
- ⛔ The conflation that must not return: "everything exports back out as CSV" covering the
  certifier ARTEFACTS. Raw records free; dossier / OSP packet / PUR export are Compliance. All
  four surfaces now state both halves, and the replacement comments say so instead of banning the
  topic.
- The `/cog-pro-migration` copy was the worst instance: a page written for growers who just lost a
  vendor was volunteering that their records could get stuck here.
- ⚠️ A recurring shape, third time in this audit: **fixed on the audited surface, alive on its
  siblings.** hero and FAQ were corrected; four siblings were not, and grep found the 3rd and 4th
  only after the first was fixed. Sweep the claim, never the file.

**Not in A5, deliberately:** T11's carbon boundary wording. The plan had A5 strip a phrase from
`app.carbonExplainer.scopeBoundary`, but E2 owns that copy end to end and a partial edit would
leave a half-stated boundary. Moved to order 6.

**Validation:** `subscriptions` all green (29 in `test_creation_limits`, 5 new); `./format.sh`
PASSED; landing `npm run build` + `tsc --noEmit` clean. ⚠️ `company.tests.test_models` reports 12
errors before AND after — proven by re-running it on `origin/main` with the changes stashed
(identical count), the stale suite `test_creation_limits`'s docstring already documents.

**PRs:** trazo-back#9, trazo-landing#4. **Order 3 is now closed.**

### Commit state — corrected 2026-09-08

Checked rather than assumed, and it had moved since the earlier note.

**Slice 1 (A1a + A2) is COMMITTED and MERGED.** `trazo-back f88c6f2` "fix(consumer,privacy): stop
a fabricated farm claiming USDA verification, and redact vendors written to extra_data" (PR #5)
and `trazo-app b22dbe8` "fix(consumer): name specimen records, and warn before a supplier name is
published" (PR #5). Verified in the committed trees: the vendor registry, `_public_event_label`
and the specimen validator markers are all present at HEAD. The 87 previously-staged files are
committed too — `git diff --cached` is now empty.

**⚠️ Order-3 work (A3, A4-interim, C1, the census command) is UNCOMMITTED AND ON THE WRONG
BRANCHES.** It sits in the working tree of two branches that belong to the other session's
blockchain cleanup:

| repo | branch | uncommitted paths |
|---|---|---|
| `trazo-back` | `chore/retire-blockchain-surface` | 7 |
| `trazo-app` | `chore/drop-dead-gas-hooks` | 23 |
| `trazo-landing` | `chore/renovate-dependency-channel` | 2 |

Nothing of mine is *inside* those commits — the files are modified/untracked, not staged — but
committing on those branches would put review-link throttling, form gating and a specimen census
into a PR about deleting Polygon code. The separation is now a branch problem rather than a
working-tree problem, and it is Oscar's to resolve (I do not run git).

The landing changes (privacy/FAQ wording from D1) have been uncommitted since slice 1 and are on
a Renovate branch, which is equally unrelated.
