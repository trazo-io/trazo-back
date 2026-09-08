# Carbon surface audit — 2026-09-07

**Question asked:** after the transparency pivot, carbon is a background KPI rather than the
product. How much of the `carbon` app is still load-bearing, what is dead, and which tests are
stale?

**Method.** Nothing here is inferred from the dev database (that is not evidence). Every claim is
either a file:line, a count over the tree, or a route resolved through Django's own URLconf:

* backend routes: `django.urls.get_resolver()` walked and filtered to `api/carbon/*`
  (script kept in the session scratchpad, `dump_urls.py`);
* frontend calls: every `carbon/…` string literal in `trazo-app/src`, **all extensions**
  (`.ts`, `.tsx`, `.js`, `.jsx` — the app is mixed, a tsx-only filter fabricates findings);
* each frontend call resolved back through `django.urls.resolve()` with `${…}` substituted,
  so a "404" below means the URLconf genuinely does not route it;
* reachability: RTK hook → importing component → *its* importer, transitively, to a route in
  `App.tsx`. A hook that only its own api module mentions is dead however good it looks.

---

## 1. What is actually live (keep, do not touch)

| Surface | Route | Consumer |
|---|---|---|
| Carbon write path | signals, no HTTP | `history/signals.py` → `carbon/services/event_carbon_calculator.py` (4,926 LOC) + `verified_emission_factors.py` (4,071) |
| Event preview in the wizard | `POST api/carbon/calculate-event-carbon/` | `NewEvent.jsx:756` (`useCalculateEventCarbonImpactMutation`) |
| Season carbon summary | `api/carbon/public/productions/<id>/complete/` | `ProfileProduction.tsx:147` (`useGetCompleteSummaryQuery`) |
| Farm summary card | `api/carbon/establishments/<id>/summary/` | `CarbonSummaryCard.jsx:65`, mounted in `Dashboard/index.tsx:64` as `TransparencySummaryCard` |
| Crop templates | `api/carbon/crop-templates/`, `…/<id>/`, `api/carbon/crop-types/dropdown/` | `QuickStartProduction.tsx` (routed in `App.tsx:465`) |
| Voice capture | `voice-config/`, `deepgram-token/`, `process-voice-event/` | `VoiceEventCapture.tsx`, used by `NewEvent.jsx:109` |
| Consumer carbon explainer | reads the QR payload, no carbon route | `CarbonImpactExplainer` lazy-loaded in `ProductDetail.tsx:118`, guarded by `views/Scan/__tests__/noScoreOnConsumer.test.ts` |

**The consumer QR page calls no `carbonApi` endpoint at all.** It reads carbon through
`history` (`transparency_views.py`, `views_consumer.py`). `ProductDetail.tsx:322` still carries
the comment recording the removal of its duplicate `useGetCompleteSummaryQuery`. So the pivot
already landed on the consumer side; what is left over is producer-side and backend-side.

`history/transparency_views.py` (1,398 LOC) serves `api/histories/transparency/<uuid>/` and
`…/verify-blockchain/`, both `AllowAny`. **Both are written down with reasons in
`history/tests/test_anonymous_endpoint_inventory.py:54,63`** — reviewed, not a leak.

---

## 2. Broken frontend → backend calls

Five calls do not resolve. All five belong to hooks with **zero** component consumers, so
they are dead code rather than live 404s — but they are dead code that *looks* wired.

| Call site | URL | Backend reality |
|---|---|---|
| `carbonApi.ts:868` | `carbon/public/productions/${id}/summary/` | only `…/complete/` exists |
| `carbonApi.ts:877` | `carbon/productions/${id}/timeline/` | only `…/summary/` exists |
| `carbonApi.ts:1145` | `carbon/education/regional-farming-practices/${state}/${crop}/` | route is `education/regional-practices/<state>/<crop_type>/` |
| `carbonApi.ts:1206` | `carbon/usda/real-factors/` | route is `usda/regional-factors/<state>/` |
| `companyApi.ts:217` | `carbon/establishments/${farmId}/footprint/` | only `…/summary/` and `…/entries/paginated/` |

Two more resolve, but not to what the caller means — worse than a 404, because nothing errors:

* **`companyApi.ts:299` `carbon/reports/generate/`** resolves to `carbonreport-**detail**` with
  `pk="generate"`. `CarbonReportViewSet` is a `ReadOnlyModelViewSet`, so the POST is a 405 on a
  detail route, not a report generation. Its only caller, `CarbonReportTab.jsx`, is itself
  unmounted (§3), so nothing is broken in the running app today.
* **`carbonApi.ts:1117` `carbon/education/carbon-examples/?value=…`** resolves to the
  `education/<str:topic>/` catch-all. That view *does* handle `topic == "carbon-examples"`
  (`carbon/views.py:6799`), so the response is real — but it reads `level`, `context`, `source`
  and **ignores `value`, `unit`, `max_examples`**. The value-aware endpoint,
  `education/carbon-examples/<carbon_value>/` → `get_carbon_impact_examples`, has no caller at all.

---

## 3. Dead frontend surface

`carbonApi.ts` exports **41 hooks. 10 have a consumer. 31 have none.**

Dead hooks (0 references outside `carbonApi.ts`): farm/production carbon summary, benchmarks,
public carbon summary, production timeline, create offset, all five weather hooks, company crop
options, USDA methodology / regional benchmark / USDA credibility / regional practices, USDA
emission factors, validate USDA compliance, USDA benchmark comparison, AI event suggestions,
paginated farm entries, both security hooks, all three photo-evidence hooks, both gas hooks,
advanced analytics, dashboard comprehensive, carbon scope breakdown.

`companyApi.ts`: of 15 carbon hooks, **11 have no consumer** — emission sources, offset actions,
farm footprints, add/update/delete footprint, all four certification hooks, carbon entries,
crop types (non-dropdown), certified projects, create offset.

Dead components (nothing imports them, or only a barrel does):

| Component | Status |
|---|---|
| `views/Scan/ProductDetail/components/ModernSidebar.tsx` | only its own barrel `components/index.ts:1` references it — **unmounted**, and it is the only importer of `CarbonImpactVisualizer` |
| `components/Education/CarbonImpactVisualizer.tsx` | reachable only through `ModernSidebar` |
| `components/Education/TrustComparisonWidget.tsx` | only `components/Education/index.ts:2` |
| `components/Education/EducationModal.tsx` | imported only by the two dead components above |
| `components/Education/EducationalTooltip.tsx` | referenced only in a comment inside `src/__tests__/hooksBeforeReturns.test.ts` |
| `views/Dashboard/Dashboard/components/forms/CarbonReportTab.jsx` | no importer |

`CarbonImpactExplainer.tsx` is the one live file in `components/Education/` — keep it.

---

## 4. Dead backend surface

Models whose only references are `carbon/models.py`, `carbon/serializers.py`, `carbon/views.py`,
demo seeders and their own tests — no production reader, no frontend consumer:

`SustainabilityBadge`, `GreenPoints`, `MicroOffset`, `CarbonOffsetProject`,
`CarbonOffsetPurchase`, `CarbonOffsetCertificate`, `IoTDevice`, `IoTDataPoint`,
`AutomationRule`, `ConsumerTrustMetric`, `CarbonIntelligence`.

Their routes are all registered and all `IsAuthenticated` or stricter — `badges`,
`green-points`, `micro-offsets`, `offset-projects`, `offset-purchases`, `offset-certificates`,
`iot-devices` (registered **twice**, once on the router and again as seven explicit paths),
`automation-rules`, plus the John Deere OAuth trio and two webhooks.

**No carbon route is anonymous.** `DEFAULT_PERMISSION_CLASSES` is `IsAuthenticated`
(`backend/settings/base.py:144`), and the seven `@api_view` functions without an explicit
`@permission_classes` (the education/USDA-credibility group, `carbon/views.py:6601`–`6764`)
inherit it. Two of them describe themselves as "consumer-facing" in their docstrings while being
auth-gated, which is the tell that they were written before the pivot and never removed.

⚠️ **`SustainabilityBadge` is the self-assigned sustainability-label class** that
`transparency-first.md` and ECGT 2024/825 (live 2026-09-27) rule out on a consumer surface. It is
not rendered anywhere today. It should not be left lying around to be rediscovered.

### Blockchain

`BLOCKCHAIN_ENABLED` defaults `False` in `base.py:860`, and `base.py:857` records the decision to
keep the code rather than delete it. That is a deliberate dormancy, so this audit does **not**
recommend deleting it. It does flag the shape: **seven overlapping implementations, 5,016 LOC** —
`blockchain.py`, `blockchain_with_circuit_breaker.py`, `enhanced_multisig_blockchain_service.py`,
`gas_optimized_blockchain.py`, `multisig_blockchain_enhanced.py`, `multisig_blockchain_service.py`,
`production_blockchain.py` — plus `polygon_security_manager.py` (708). Dormant code is cheap;
seven dormant copies of the same thing are not.

---

## 5. Loose scripts at the backend repo root — the biggest single hazard

`trazo-back/` has **157 loose `.py` files at its root**. **101 of them match `test*.py`** — which
is Django's *default* test-discovery pattern, with the top level defaulting to the working
directory. `pytest` reaches them too: `pyproject.toml:108` sets `testpaths = [".", …]` with
`python_files = ["test_*.py", …]` and `DJANGO_SETTINGS_MODULE = "backend.settings.dev"`.

They are not tests. They are one-off debugging scripts:

* **77** call `django.setup()` at import;
* **81** execute code at module level beyond that (measured with `ast`, counting top-level
  `Expr(Call)` nodes) — `test_carbon_calculations.py` has 120 top-level calls;
* another 35 non-`test*` root scripts (`comprehensive_carbon_audit.py`,
  `refresh_frontend_data.py`, `deep_compliance_check.py`, …) do the same.

So a bare `poetry run python manage.py test` imports ~101 modules that run agricultural
calculations, HTTP calls and ORM writes at import time against **`backend.settings.dev`**. This is
the mechanism behind the note in `.github/workflows/ci.yml` — "never by adding the whole codebase
in one process (that fabricates hundreds of phantom errors)" — and the reason CI has to enumerate
suites by hand.

Deleting these is the highest-value, lowest-risk cleanup in the whole repo.

`carbon/management/commands/` holds **57 commands**, of which the documented seed path uses two
(`populate_usda_crop_types`, `create_comprehensive_production_templates_v2`). The rest include six
`seed_comprehensive_demo*` variants and eleven one-shot `fix_*` / `quick_*` / `final_*` repair
commands whose migrations have long since run.

---

## 6. Test suite

`carbon` has **49 test modules, ~730 test methods**, and **not one of them runs in CI** —
`.github/workflows/ci.yml`'s "Claim-safety and compliance suites" step lists `history`,
`certifications` and `subscriptions` modules only.

Two modules are duplicated by name, which is its own trap:
`carbon/test_carbon_calculations.py` (15 methods, app root) vs
`carbon/tests/test_carbon_calculations.py` (45), and `carbon/tests_emission_factors.py` (25, app
root) vs `carbon/tests/test_emission_factors.py` (15).

Blocks that test subsystems §4 shows have no consumer:

| Block | Methods |
|---|---|
| blockchain (`test_blockchain`, `test_blockchain_production`, `…_simple`, `test_multisig_blockchain`) | 70 |
| circuit breaker (`test_circuit_breaker_enhanced`, `…_stress`) | 56 |
| AI suggestions (4 modules) | 37 |
| weather integration | 25 |
| IoT + John Deere (3 modules) | 27 |

### Baseline run — 2026-09-07

`DATABASE_NAME=trazo_isoC poetry run python manage.py test carbon --noinput` (isolated database;
another session was running tests at the time):

```
Ran 694 tests in 331.664s
FAILED (failures=35, errors=110, skipped=2)
```

**145 broken, 21% of the suite.** By module:

| Module | Broken |
|---|---|
| `tests/test_carbon_calculations` | 29 |
| `tests/test_models` | 26 |
| `tests/test_blockchain` | 15 |
| `tests/test_calculations` | 14 |
| `tests/test_carbon_api` | 10 |
| `tests/test_multisig_blockchain` | 9 |
| `tests/test_centralized_factors_integration` | 9 |
| `test_carbon_calculations` (app root) | 9 |
| `tests/test_weather_integration` | 5 |
| eleven others | ≤3 each |

`carbon/tests/test_integrated_iot_workflow.py` does not even import:
`ImportError: cannot import name 'calculate_data_point_confidence' from 'carbon.tasks'`.

**These are stale tests, not product defects.** The top causes are constructors and methods that
no longer exist:

| Cause | Count |
|---|---|
| `Establishment() got unexpected keyword arguments: 'created_by'` | 24 |
| `Company() got unexpected keyword arguments: 'created_by'` | 13 |
| `Parcel() got unexpected keyword arguments: 'organic_certified'` | 8 |
| `Company() got … 'legal_entity_name', 'owner'` | 7 |
| `'EventCarbonCalculator' object has no attribute 'calculate_event_carbon'` | 7 |
| `'CarbonFootprintCalculator' object has no attribute 'calculate_fertilizer_emissions'` | 6 |

The 35 assertion failures were checked individually rather than assumed stale, because some of
them sit on the live path. They are stale too, and two of them matter:

* **The emission-factor guards are red against the CORRECT values.**
  `test_emission_factors.py:36,44,70` demand phosphorus `1.25`, potassium `0.60`, electricity
  `0.40`. The registry returns `1.19`, `0.65`, `0.39` — which is exactly what
  `documentation/reference/emission-factors.md:41,42` and the 2025-12-03 electricity correction
  (0.821 → 0.39, EPA eGRID2023) say it should return. The code is right; the tests were never
  updated after the correction. So the factor guards — the tests whose whole job is to catch a
  drifting EPA/USDA number, the numbers we make public claims about — have been permanently red
  and therefore unread. That is the failure mode worth fixing first: not a wrong factor, a
  guard that cannot warn.
* **`test_pump_test_renders_in_the_carbon_appendix`** asserts `"72.5%"` while the appendix now
  renders `"72.50%"`. Cosmetic. The appendix text itself is compliance-correct
  ("EPA/USDA-sourced factors", "informational; not a USDA NOP requirement", lifecycle excluded).

---

## 7. Proposed cleanup, in order

0. **Repair the emission-factor guards** (`test_emission_factors.py`,
   `test_hardcoded_factors_audit.py`, `carbon/test_carbon_calculations.py`) to the documented
   post-correction values. Small, and it is the only red test on this list that guards a public
   claim. Everything else can wait behind it.
1. **Delete the 157 loose root scripts** (keep `manage.py`). Nothing imports them — verified by
   grepping every package for `import <name>` / `from <name> import`, zero hits. They are
   discovered as tests by both runners and execute against the dev database. One commit, and
   `manage.py test` becomes a usable command again.
2. **Delete the dead frontend surface** — `ModernSidebar`, `CarbonImpactVisualizer`,
   `TrustComparisonWidget`, `EducationModal`, `EducationalTooltip`, `CarbonReportTab`, and the
   31 + 11 unused RTK endpoints. Keep `CarbonImpactExplainer`.
3. **Fix or delete the seven broken calls in §2** — deletion is right for six of them; the
   `carbon-examples` value path is the one worth deciding on deliberately.
4. **Retire the offsets / badges / green-points / IoT / John Deere surface**: unregister the
   routes first (a route is the thing that can be rediscovered), then decide separately whether
   to drop the tables. `SustainabilityBadge` should go furthest — it is a compliance liability
   with no product behind it.
5. **Consolidate the seven blockchain services** into one dormant implementation behind
   `BLOCKCHAIN_ENABLED`, rather than deleting a documented keep.
6. **Prune the 57 management commands** to the seed path plus the recalculation commands.
7. **Swap the 17 `print()` calls in `history/signals.py` for `logger.debug`** — they are the
   CI noise that started this audit, and they run in production too.
8. **Add the surviving carbon tests to CI** once the dead blocks are gone. A suite that never
   runs is not a suite.

---

## 8. Work done 2026-09-07 (steps 0 and 1)

### Root scripts removed

154 of the 157 loose `.py` files at `trazo-back/` root deleted. Kept: `manage.py`,
**`setup_billing.py`** (referenced by `deploy_billing.sh` and `documentation/BILLING_SETUP.md` —
the "nothing references them" check in §5 covered Python imports only, and this one is reached
from a shell script) and `setup_blockchain.py`. A tarball of all 154 is in the session scratchpad
as `root-scripts-archive-2026-09-07.tar.gz`; they are also recoverable from git history.

### Electricity factor: 0.39 → 0.365 kg CO2e/kWh

Verifying the guard's expectation against the source, rather than against the code, showed the
code was wrong too — in a different way from the test.

**0.39 never followed from the source cited for it.** The registry said
`EPA eGRID2023 Summary Tables (767.2 lbs/MWh) + 5.12% T&D losses`. That arithmetic gives 0.366,
and `documentation/reference/emission-factors.md` even printed the gap as "0.366 -> 0.39" without
explaining it. 0.39 is real, but it is EPA's **Greenhouse Gas Equivalencies Calculator** figure —
823.1 lb CO2/MWh, **eGRID2022** data, 5.12% T&D — a different publication and an older data year.

Fetched EPA's own eGRID2023 Summary Tables rev.2 (released 2025-06-12) and read the U.S. row:

```
U.S.   CO2 767.2   CH4 0.057   N2O 0.008   CO2e 770.9  (lb/MWh)   grid gross loss 4.2%

770.9 x 0.45359237 / 1000 = 0.34967 kg CO2e/kWh at the generator
0.34967 / (1 - 0.042)     = 0.365   kg CO2e/kWh delivered
```

eGRID's published U.S. grid gross loss is **4.2%**, not the 5.12% the code claimed. eGRID2023
rev.2 was still the current edition on EPA's site on 2026-09-07 (eGRID2024 listed as "next
planned"), so this is also the up-to-date edition.

The factor was declared in **four** places, not one — `verified_emission_factors.py` (×3, including
the `US` country entry and `irrigation_pump`), `carbon/choices.py`, `carbon/services/emission_factors.py`,
and a bare `ELECTRICITY_FACTOR = 0.39` in `carbon/views.py`. All four corrected, plus the metadata
strings the API returns (`data_sources`, `transparency_note`, `critical_updates`).

Downstream copies corrected too: `.claude/rules/carbon-methodology.md`,
`documentation/reference/emission-factors.md`, eight frontend sites (both locale files, in parity),
and **the public landing methodology page**, which stated "0.39 kg CO2/kWh ... including 5.12%
transmission & distribution losses" under an eGRID2023 heading.

Unit label left as `kg_CO2_per_kWh` rather than renamed to `kg_CO2e_per_kWh`: the eight
country factors in the same dict use the CO2 label, and asserting CO2e for grids that have not
been re-checked would be worse than a loose label on one entry. The CO2e basis is stated in the
factor's `notes` and `source`.

### ⚠️ P2O5 and K2O: citation withdrawn, values NOT changed

`phosphorus_fertilizer` (1.19) and `potassium_fertilizer` (0.65) were both attributed to the
*EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98)*. **That publication contains no
fertilizer manufacturing factors at all** — checked against the 2025 Hub (January 2025). The
attribution is fabricated, and it was reaching the public: the landing methodology page printed
"EPA 40 CFR Part 98" in the Source column for both rows.

Published values also sit below ours:

| Source | P2O5 | K2O |
|---|---|---|
| Brentrup et al. 2018, via the 4C emission-factor list | TSP 0.25 kg CO2e/kg product ≈ **0.52**/kg P2O5 | MOP 0.25 kg CO2e/kg product ≈ **0.42**/kg K2O |
| Walling & Vaneeckhaute 2020 (review) | "generally **1–1.5**" kg CO2-eq/kg P2O5 | "knowledge … greatly lacking" |
| Wood & Cowie 2004 (IEA Bioenergy Task 38), Table 7 | SSP 0.095–1.05, TSP 0.35–1.08 kg CO2-e/kg P2O5 | not covered |

1.19 is inside the review's range; 0.65 is above every published figure found. **Neither value
was changed** — picking a number is a methodology decision, not a cleanup, and it would silently
move every fertilizer event's emissions. What was changed is the claim: the false attribution is
gone from the registry docs, the reference doc, the guard tests and the public page, replaced with
"under re-verification".

**Open decision for the owner:** adopt Brentrup et al. 2018 (EU production mix, per-product,
convertible to per-nutrient) or a US-specific LCA, and recalculate, or keep the values with an
honest "literature midpoint, range X–Y" citation.

### Guards repaired

`test_emission_factors.py`, `test_hardcoded_factors_audit.py`, `test_calculations.py`,
`test_factor_provenance.py`, `test_electric_equipment_emissions.py`, `test_carbon_calculations.py`
and `tests_emission_factors.py` updated to the corrected values. The electricity guard now carries
the full derivation and the eGRID URL in its docstring, plus a note saying why it is written as a
literal rather than read from the registry — a guard that asks the code what it thinks passes
forever.

Result on the factor suites: **73 tests, 1 failure**, and that one is pre-existing:
`test_urea_application_benchmark` — 100 kg urea at 46% N through `EventCarbonCalculator` returns
**0.0 kg CO2e**. `"FE"` is a live chemical-type code in the calculator, so this is a candidate
real defect rather than an obviously stale fixture, and it is on the fertilizer path. **Not
investigated — flagged.**

Frontend: `formRenderConformance.test.tsx` 50/50 and the i18n suite 29/29 pass with the new
strings, in both locales.

### Suite movement

| | Errors | Failures | Total broken |
|---|---|---|---|
| Baseline (before any change) | 110 | 35 | **145** |
| After the electricity pass | 110 | 29 | **139** |
| After the three follow-up fixes | 110 | 26 | **136** (derived; the three verify green in isolation, 60 tests OK) |

The 110 errors are untouched on purpose: they are the removed-model-kwarg class
(`Establishment(created_by=…)` and friends), which belongs to the dead-surface removal in step 4,
not to the factor guards.

Three follow-ups after the first re-run:

* `tests_emission_factors.py` `test_phosphorus_factor_consistency` / `..._potassium_...` asserted
  1.25 / 0.60 across four "copies" of the fertilizer factor. Worth checking rather than assuming:
  `EventCarbonCalculator.USDA_FERTILIZER_FACTORS`, `EnhancedUSDAFactors.base_usda_factors` and
  `CoolFarmService` all **delegate to `emission_factors.get_fertilizer_factor()`** — they are views
  on one registry, not divergent copies. The test was only holding a stale literal.
* `test_pump_test_renders_in_the_carbon_appendix` — the appendix renders `72.50%`, the guard
  demanded `72.5%`. Assertion moved to the rendered precision.
* `EmissionFactorRegistry.get_factor_change_audit()` listed **v3.0.0 (nitrogen 11.0, phosphorus
  1.25, potassium 0.60) as "current"** while the registry returns 10.5 / 1.19 / 0.65. Corrected,
  with a v3.1.0 entry that also records the withdrawn P/K attribution. Only a test calls this
  method, so nothing was serving the wrong numbers to users.

---

## 9. What was done next, and why that and not something else

The instruction was "no backfill, and then do what an expert would do given the pivot". With zero
real users a recalculation would rewrite dev rows and prove nothing, so the question is what
carbon is FOR now. Under the pivot it is not a product: it is an informational appendix in a
certifier packet and an expandable section on a buyer page. Its job is to be **defensible and
small**. That ranks the work:

1. a claim that cannot be traced is the thing that can actually hurt Trazo — fix the class, not
   the instance;
2. a guard nobody runs is the thing that let it happen — wire it to CI;
3. every dead endpoint is claim surface with no product behind it — remove the ones that assert
   something.

Being 6% off on a carbon number is, next to those, not very interesting.

### 9.1 The class: a source must be a document someone opened

`carbon/tests/test_factor_sources_are_citable.py`. Every `EmissionFactor` reachable from the
registry is walked **by reflection** — a factor added to a new dict is covered the moment it
exists, not when someone remembers to extend a list. A factor may claim `PROVENANCE_PUBLISHED`
only if its `source` is an **exact** member of `CITABLE_SOURCES`, an allowlist where each entry
carries the URL that was opened and the date it was checked. A reworded citation is a new claim
and comes back through review. There is also a specific rule for the specific fabrication: a
fertilizer factor may not cite 40 CFR Part 98 or the Emission Factors Hub, which are fuel
combustion.

**Why an allowlist and not the check that already existed.** `test_factor_provenance.py` (written
2026-08-20, good work) held `CITATION_MARKERS` — substrings a published source had to contain:
`"40 CFR"`, `"eGRID"`, `"IPCC"`, `"et al."` … The fertilizer source read
`"EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98)"`. It contains `"40 CFR"`. **It
passed.** The check proved the string was citation-*shaped*, which is exactly what a fabricated
attribution is good at being. `CITATION_MARKERS` has been deleted and that test now delegates to
the allowlist — one rule, one answer, because two readings of one rule is how you end up trusting
the weaker one.

A third provenance state was added, `PROVENANCE_UNVERIFIED`, and P2O5/K2O moved to it.
`INTERNAL_ESTIMATE` would have been a lie of a different kind — an internal estimate is a number
we derived and can explain; these are numbers of unknown origin that were dressed as an agency's.
Anything unverified must be named in `UNVERIFIED_REGISTER` with a reason, and can never report
`is_published`.

**Mutation-tested rather than assumed** — a guard that has never failed is a guard nobody has
tested:

| Mutation | Guard failures |
|---|---|
| baseline | 0 |
| new factor, PUBLISHED, source `"USDA Definitive Fertilizer Study 2026"` | 1 |
| the original bug: fertilizer factor citing the EPA Hub | 2 |
| one of the three grid-factor copies drifts back to 0.39 | 2 |
| restored | 0 |

### 9.2 The mechanism: guards that actually run

Nine carbon modules added to the CI claim-safety step, including both new guards. This is the
loop that was open: the factor guards were red for nine months **and no carbon test ran in CI at
all**, so there was nothing to go red in front of anyone.

The rest of the carbon suite is deliberately still out — 135 of 694 are red against removed model
kwargs, and a red-by-default job is one nobody reads. Widen as §7 step 4 lands.

### 9.3 The surface: seven claim-bearing routes unregistered

`badges`, `green-points`, `micro-offsets`, `offset-projects`, `offset-purchases`,
`offset-certificates`, `offsets`. Not because they were unused — that is why they were easy — but because of
what they assert. `SustainabilityBadge` is a grade the product awards itself, the class **EU ECGT
2024/825 bans outright, live 2026-09-27, twenty days out**. The widgets were pulled in 2026-08;
the API outlived them and still served badge rows to any authenticated caller.
`offset-certificates` is the sharpest unearned word in the codebase.

Models kept. Dropping tables is a separate decision with a migration behind it, and the table is
not the part that leaks — **the route is the part that gets rediscovered**. Six months on, the
model, serializer and viewset are all still there; someone wiring a dashboard finds
`SustainabilityBadgeViewSet` and re-registers it in four characters.
**The seventh was found by asking what the other six left behind.** Retiring the offset CRUD
routes and stopping would have been the "fixed on the audited surface, alive on its sibling"
failure this project's own audits keep re-finding. `carbon/offsets/` survived the first pass
because it is a different viewset — until you read it: `CarbonOffsetViewSet` has exactly one
action, `certified_projects`, which returns `CarbonOffsetProject.objects.all()` — the same
marketplace model — and decorates every row with a hardcoded
`verification_badges = {"text": "VCS Verified"}`. A third-party verification claim, written by us,
attached to our own rows, served to any authenticated caller. `compliance.md` puts "verified" in
the UNSAFE column for everything except a USDA Organic Integrity Database match. Retired, and
listed in the guard with that reason.

`carbon/tests/test_retired_claim_routes_stay_retired.py` makes that a decision instead of a
keystroke: it checks both doors (path `resolve()` and name `reverse()`), demands a written reason
per entry, and — because a negative assertion has to prove it read something — resolves a route
that IS live, so it cannot pass against a URLconf that failed to load.

### 9.4 Deliberately not done

* **No recalculation, no backfill, no data migration.** Instructed, and correct: zero real users.
  Existing rows keep the 0.39 basis; new events use 0.365.
* **P2O5/K2O values unchanged.** Sourcing them is a methodology decision, not cleanup.
* **The urea zero not chased** — `EventCarbonCalculator` returns 0.0 kg CO2e for 100 kg urea at
  46% N. Still the best candidate for a real defect on the live path.
* **The 110 stale-fixture errors, the dead frontend surface, and the IoT/John Deere routes** —
  §7 steps 2 and 4, a bigger and much less urgent tranche.

---

## 10. The three open items, decided

### 10.1 P2O5 / K2O — keep the values, label them ours

**Decision: hold 1.19 and 0.65, reclassify to `PROVENANCE_INTERNAL_ESTIMATE`, publish the
reasoning.** Not "re-source to Brentrup", and not "leave them UNVERIFIED".

The tempting move was to adopt Brentrup et al. 2018 — a real, citable, peer-reviewed source
implying ~0.52/kg P2O5 and ~0.42/kg K2O. It is the wrong move twice over:

* **Scope.** Brentrup is European production. US phosphate is largely domestic (Florida and
  Louisiana) and US potash largely Canadian. Adopting EU figures for US farms swaps an unsourced
  number for a mis-scoped one, which is not an improvement — it is the same defect wearing a
  citation.
* **Direction.** It moves both estimates *down*. For a product whose whole proposition is
  transparency, overstating our own footprint is the safe error and understating it is the
  greenwashing error. Walling & Vaneeckhaute 2020 put phosphorus production at 1.0–1.5 kg
  CO2e/kg P2O5, so 1.19 sits inside the published range, toward its upper half. 0.65 sits above
  every published K2O figure found, in an area the same review calls "greatly lacking" in
  knowledge — and K2O is the smallest of the three NPK terms in any realistic application, so
  erring high there costs a farmer nothing they would notice.

Precision is not what is at stake. This is an informational appendix line, not a regulated
disclosure; no decision a farmer or certifier makes turns on 1.19 versus 0.52. What is at stake
is whether the number is honest about what it is. `internal_estimate` says: our judgement, within
a range we cite, chosen conservatively. That is true, it is defensible to a certifier, and it
requires no recalculation of anything.

`UNVERIFIED_REGISTER` is now empty, which is the state it should normally be in — `UNVERIFIED` is
where a factor lands while a decision is pending, not where one lives.

### 10.2 The urea zero — not a defect, three layers of test artefact

`EventCarbonCalculator` returned 0.0 kg CO2e for 100 kg of urea at 46% N. It was worth chasing
precisely because it was not obviously stale. It was:

1. The fixture was a `SimpleNamespace` with no `.history`. `_extract_chemical_data` reads that
   attribute, raised, and the calculator's broad `except` returned its zero defaults.
2. The assertion read `result.get("co2e", 0)` — the default masking the failure a second time.
   A benchmark that cannot tell "we calculated zero" from "we could not read the event" is not a
   benchmark.
3. With a real `ChemicalEvent`, it still priced at 0.873 kg CO2e — because NPK was put in
   `extra_data`, and the calculator reads the farmer-entered `concentration` field. Returning
   zero there is **correct and deliberate**: the F03 no-phantom rule (2026-06) refuses to invent
   a 10-10-10 composition, because fabricating NPK manufactures nitrogen emissions the farmer
   never reported.

Rewritten against a real event with `concentration="46-0-0"`. It now prices within 0.5×–2× of
46 kg N × the registry nitrogen factor, and the failure message says what a zero would mean. The
product was right on all three counts; the test was wrong on all three.

Worth noting for later, not acted on: that broad `except` returns 0.0 CO2e on any extraction
error and logs at WARNING. On the live path `.history` always exists, but "extraction failed"
and "genuinely zero" are indistinguishable downstream — the *zero ≠ missing* class this codebase
already has a test named after.

### 10.3 The next tranche — sequenced, not started

One deletion made: `carbon/tests/test_integrated_iot_workflow.py`, which could not import at all
(`calculate_data_point_confidence` no longer exists in `carbon.tasks`). A module that cannot be
imported provides no coverage; its subject has no consumer.

The rest is written down rather than done, deliberately. 135 red tests cost nothing externally:
they are invisible, in a suite that does not run in CI, on a subsystem that is not the product.
Cutting ~250 tests at the end of a long session, without room to verify each call, is not
expertise. **The judgement is the deliverable here; the execution is a session of its own.**

Cut by SUBJECT, not by redness:

| Subject | Modules | Tests | Call |
|---|---|---|---|
| Blockchain | `test_blockchain`, `test_blockchain_production*`, `test_multisig_blockchain` | ~70 | **Delete.** `BLOCKCHAIN_ENABLED=False` is a documented keep for the *service* code (`base.py:857`), not for 70 tests of seven overlapping implementations. Consolidate the services first (§7 step 5); the tests follow that decision, they do not precede it. |
| IoT / John Deere | `test_iot_automation_frontend`, `test_john_deere_integration` | ~21 | **Delete** with the routes, as one change. No consumer, no product intent. |
| Weather integration | `test_weather_integration` | 25 | **Delete.** All five weather RTK hooks have zero call sites. |
| AI suggestions | `test_ai_suggestions*` (4 modules) | ~37 | **Delete three, keep one.** `ai-event-suggestions` has no consumer today, but voice/AI prefill is live product. Keep the module that covers the prefill path. |
| Live calculator | `test_calculations`, `test_carbon_calculations`, `test_carbon_calculator_gaps`, `test_centralized_factors_integration` | ~100 | **Repair.** This is the write path every event goes through. The errors are almost all `Establishment(created_by=…)`-class removed kwargs — mechanical, and worth doing because this is the code that produces the numbers in the packet. |
| `carbon/test_carbon_calculations.py` (app root) | — | 15 | **Read then split.** Same basename as `carbon/tests/test_carbon_calculations.py`, and an app-root test module is the discovery hazard just cleaned at repo root. It also holds pre-pivot `test_carbon_neutral_score` / `test_carbon_negative_score` — "carbon neutral" is on the UNSAFE list in `compliance.md`. Move the live parts into `tests/`, delete the scoring ones. |

Order: routes and their tests together (IoT, John Deere, weather), then blockchain service
consolidation with its tests, then repair the calculator suite, then widen CI. The dead frontend
surface (§3) is independent and can go at any point.
