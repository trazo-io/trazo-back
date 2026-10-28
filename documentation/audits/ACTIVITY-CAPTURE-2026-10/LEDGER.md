# Activity-capture audit (Astra, 2026-10-26): ledger

Source: `Trazo-Activity-Capture-Audit-2026-10-26.md` in this folder, kept byte for byte
(sha256 `754469c9a2df3c725a9b0b543ee3509ae77b481958147eceef87afc8813bb971`). Fixture: company 17,
farm 20, South Block, Gala 2026 (ASTRA TEST), 60 fictional records, unpublished. Left in place for
the focused confirmation run.

Triage rule (October scope): would a prospect, a certifier or a pilot's inspector read a false or
overstated statement in the output today? Every finding in this round passed that test or was
cheap enough to fix with it, so nothing is deferred.

| ID | Finding | Cause found in code | Fix | PR |
|---|---|---|---|---|
| AC-01 | Hail 7 minutes shown as 7 hours | One `duration` key, two units (hail form asks minutes); registry formatter always appended "hours" | Two declarations with disjoint subtypes; resolver picks the owning one | app #209 |
| AC-02 | Certification in progress read as third-party; certificate number promised | Fixed sentence per subtype in `getConsumerEventDescription` | Attributed to the farm; number line only with `certificate_number`; status suffix removed (field is owner-only) | app #208 |
| AC-03 | Compost process read as spreading; pH "what and how much" with neither | Same | Gated on `amendment_amount_numeric` / `amendment_type`; partial-record fallbacks deny only the missing field | app #208 |
| AC-04 | Manual weeding read as mowing; weather damage asserted; emergency "cleanup and repair" | Same | Gated on `floor_management_type`, `damage_assessment`/`crop_impact`; neutral emergency line | app #208 |
| AC-05 | Canopy tying, habitat, nest box, pollination, grazing (+ extras: irrigation source, tillage, fungicide target, pest ID, inspection) | Same | Field-driven or neutral; guard `consumerNarrativeIsFieldBacked.test.ts` | app #208 |
| AC-06 | Planting offered "Búsqueda de semilla orgánica" template | A PL template named after the certifier-only seed-search activity, duplicating `planting` | Template removed; containment guard against certifier-only labels | app #211 |
| AC-07 | "Did not spray today, too windy" shown as mixed | `voice_negation` splits on commas and counted the reason clause as an action | Un-negated clause is affirmed only with an action word or a number | back #239 |
| AC-08 | Water lab analysis forced an area > 0 | Frontend schema required area for every soil subtype but NS/HD; backend never did | Area optional for LA and ST | app #211 |
| AC-09 | English in the Spanish UI | Producer surfaces never localized registry values; timeline de-camelCased label keys; 193 hardcoded soil/pest options | Localized values and labels; options through intl | app #209, app #212 |
| AC-10 | Weather values with no unit | Four fields had no formatter | mm, km/h, % formatters | app #209 |
| AC-11 | Amarre as "Tucking", PA as "Soil Amendment", generic "Producción", seed-search result missing | Bare string field; stale label map; no subtype row; formatter dropped `result` | Enum source, label fixes, `production_type` row, result appended | app #209 |
| AC-12 | Document picker could not tell same-day records apart | Passed an i18n key where a subtype code belongs | `subtypeOf(ev)`, plus time and product | app #211 |
| AC-13 | Certification status defaulted into a blocked state; English error; "passed" activity names | Default `pending` vs a rule refusing it; module-scope zod message | `in_progress` default for verification; `buildBusinessSchema(intl)`; neutral labels | app #211 |
| AC-14 | "No emissions estimated" beside "0 kg CO₂e / Mínima"; "from recorded inputs" on area-only soil figures | Modal fabricated `co2e: 0` for types 0/3/7; soil path never marked `area_estimate`; LA fell through to the "general" factor | No fabricated zero; soil area estimates labelled as such; LA maps to `soil_test` | app #210, back #238 |
| AC-15 | "This record appears on your buyer page" on an unpublished season | Hint ignored publish state | `isSeasonPublished` prop; conditional wording otherwise | app #210 |

## Where Astra's reading and the code differ

- AC-12: Astra described ambiguous chemical rows. Chemical rows already showed "Input
  application" whatever their subtype; the wrong argument showed most on unnamed production rows
  (a harvest read "Field work"). Both are fixed by the same change.
- AC-07 (review on back #239): the first fix recognised ACTIONS and misread crop nouns and
  elliptical clauses; it now recognises REASONS (weather, ground) and leaves anything else MIXED.
- AC-14: the backend stores no carbon for weather, general or business records. The only zero
  was the one the frontend filled in.

## Open after this round

- Stored soil CarbonEntry rows keep their old label until each event is re-saved;
  `recompute_unreported_carbon` covers ProductionEvent only. Not run against prod.
- Methodology call: tillage soil-CO2 flux and lime dissolution are counted but not listed under
  "Included" in `carbon-methodology.md`; a tillage record with fuel keeps the recorded-inputs
  label even when the flux dominates.
  Follow-up 2026-10-28 (B1): the tillage flux term is REMOVED (tillage counts recorded fuel, or
  the 1.2 kg/ha operation default when no fuel is recorded, never both); lime counts only for a named carbonate (limestone,
  dolomite) with an applied quantity, never quicklime or hydrated lime. Guard:
  `carbon/tests/test_soil_carbon_boundary.py`. `carbon-methodology.md` still has to list lime.
- `enums.identified_by.agronomist` reads "Licensed Agronomist" on readback, a credential the
  record does not establish.
  Follow-up 2026-10-28 (B2): backend labels are farm-reported roles with no credential, and
  `identified_by` is producer/certifier only. Guard:
  `history/tests/test_pest_identifier_is_farm_reported.py`.
- `formatSeedSearchAttempts` wraps the supplier list in English (formatters get no `intl`).
- Not tested by Astra and still owed: 375 px layout, live microphone, WhatsApp receipt.

Next step (Astra's recommendation, adopted): a focused confirmation on these named records plus a
real 375 px session, not another full-app audit.
