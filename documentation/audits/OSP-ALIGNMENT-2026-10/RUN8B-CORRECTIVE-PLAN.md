# Run 8b corrective plan, revision 3 (approved for S1-S6 implementation 2026-10-13)

Verified 2026-10-13 against origin/main: trazo-back `a59e899`, trazo-app `6d5c4d0`, trazo-landing
`1c675bd` (read-only detached worktrees `~/dev/trazo-wt/run8b/`). Revision 2 applies Astra's six
review points and its answers to D1-D3. Code and tests establish their own evidence axis only;
nothing here closes a live observation.

**Merging deploys** (DO and Netlify autodeploy `main`). Each merge is Oscar's decision. A date
target in this plan never authorises a merge.

## Scope for October

| In this round | Why now |
|---|---|
| 8b-01, 8b-02 | First screens a pilot or a prospect's new account sees. |
| 8b-05, 8b-07, landing parts of 8b-06 and 8b-08 | The Oregon Tilth send (Oct 20-24) links to these pages. Target: ready for Oscar's merge decision before Oct 20. |
| 8b-04 (D1 legacy equipment stays open) | False privacy statement on crew forms. |
| 8b-06 app wording | A buyer-page sentence states approval from a guess. |
| 8b-03, crew logging journey (partial) | Sign-up, harvest, cleanout, template picker. Does NOT close 8b-03. |

| Deferred, recorded as a limitation (8b-03 stays open) | Reason |
|---|---|
| Backend OSP module Spanish (252 of 1,000 es strings in usted) | Size, CONTENT_VERSION bump, needs a back-side register guard. Limitation: a Spanish-reading manager meets usted in the OSP questions. Not an assumption that managers read English. |
| Soil and Pest tab option lists (~210 strings) | Crew workflows; named open under 8b-03, next Spanish slice. |
| Bilingual crop, template, plan and add-on names | Backend single-language fields: data-model decision. |
| Self-serve importer, billing, subscription behaviour, gates | Out of bounds for this round. |

## A. Verification table

| Finding | Verdict | Code evidence | Affected surfaces | Proposed change |
|---|---|---|---|---|
| 8b-01 New-account warnings | **Confirmed, two corrections.** Badge reads "Blocks certifier sharing" / "Bloquea el envío a la certificadora", not "submission"; nothing blocks OSP submission (`OSPViewSet.submit` checks narratives only). On Starter the certifier link is refused by the plan gate first (`require_compliance_exports`, `certifications/views.py:2728`), so a document warning carries an access reason. | `history/services/operation_readiness_service.py:248-320`: `ofpp.missing` is a blocker when no G2.0 module and no upload. `applicable` (`:215-227`) is true for any OSP, organic certificate or farming method "Organic", so a new organic farm gets 3 blockers (ofpp, osp, records; pinned `test_certifier_access_links.py:556-584`). `readinessItem.ofpp.missing.detail` (:7323) "prohibits certification without a valid OFPP" sits under the card's own disclaimer (:2163) "documentation checks … not a compliance decision". `osp.none` / `records.none` state facts about the operation, not about Trazo; `osp.not_submitted` was already reworded that way 2026-08-19 (service :400-413). No setup-help action; the `records` row links to the page it is on. | `CertifierReadinessCard.tsx` (badge :500-504, routes :183-192), preshare `OperationReadinessPanel.tsx` (`readiness.blockedIntro`), tour `tour.welcomeFresh.step2`, packet/dossier English from the service. | Two separate things on the card. **Access notice** (plan): Starter "Certifier review links are part of Compliance". **Documentation findings** (records): "not on file in Trazo", next actions, no regulatory conclusion. Pilot/Compliance gate wording: "Trazo requires these records before creating a review link". Codes, severities and gates unchanged. |
| 8b-02 Pilot setup path | **Confirmed.** One self-serve list, no plan awareness: `add-parcel → start-production → document-event → finish-production → share-qr`, plus `file-osp`, `upload-ofpp` (`hooks/useOnboardingChecklist.ts:40-48`). | Widget `components/Tour/OnboardingChecklist.tsx`; strings `tour.checklist.*`; dismissal browser-local (`tourStore.ts:109`). **Activation path checked:** `provision_pilot` assigns `Plan.slug == "pilot"` (`subscriptions/management/commands/provision_pilot.py:127,206`) and refuses to run without it; the company payload carries `subscription` (`company/serializers.py:562`); the app already detects `plan.slug === 'pilot' \|\| features.is_pilot` (Dashboard `index.tsx:218`). A pilot comped any other way (admin, Compliance plan) would NOT get the pilot view, which is correct: `provision_pilot` is the only supported path (its docstring explains why). | Checklist on every admin page; dashboard. | Pilot accounts get a renewal-preparation checklist (section B, S2); season-closing and QR move to an optional group; informational rows are not steps. |
| 8b-03 Spanish consistency | **Partly confirmed.** 0 missing es keys (parity guard); OSP/farm/parcel/chemical chrome routed through intl. Still: ~80 journey strings in usted; 3 voseo past the guard ("Comparalo", "Contanos", "definilo"); hardcoded English in ProductionTab (~40 options, ~30 placeholders), sign-up/verify toasts (17), QuickStart method labels (7); Soil/Pest tabs (~210); Settings hardcodes "Granja Familiar" in both locales. | `spanishRegister.test.ts` skips su/sus, mid-sentence imperatives, usted present tense, unaccented voseo-with-pronoun. Backend OSP module es text 252/1,000 usted, no back-side guard. Ledger "Open" list (Run 8 375 px pass) names the same wizard leftovers. | Event tabs, sign-up, template picker, OSP module text, pricing keys, Settings. | S6 (partial). Operator-entered and historical text never rewritten. |
| 8b-04 Cleanout disclosure | **Confirmed: the certifier-only notice is true; the note helper is false.** | EM (and BU, SS, TP) withheld whole from public serializers (`history/services/claim_authority.py:447-468`, `history/serializers.py:4963-4982`). Form: notice `events.certifierOnly.*` (`ProductionTab.jsx:1903-1918`) correct; the Field-notes section (:5411-5432) renders for every subtype with badge `certifierRecordAndBuyer`, label "Public note", helper `observationAudience` ("shown on your buyer page") and an English consumer placeholder. | Production forms for EM, BU, SS, TP. | Certifier-only variant of badge, label, helper and placeholder for withheld subtypes. No exposure change. |
| 8b-04 legacy (D1) | **Audience checked: public by design today.** | Legacy `EquipmentEvent` (family 4) has types maintenance, repair, calibration, fuel, breakdown, inspection; no cleaning type (`history/models.py:3343-3357`). Served on the public payload with no subtype gate (`serializers.py:4984`); that serving is pinned on purpose by `test_consumer_qr_privacy_regression.py:1676-1740` (`equipment` key must carry the machine name) and app `equipmentKeyTitleGate.test.ts`. Free text goes through `public_free_text`. The UI no longer creates family-4 rows. | Buyer page for pre-merge or seeded rows only. | See D1: the risk is free-text cleanout narrative in a legacy maintenance note, not the row. Recommendation revised below. |
| 8b-05 Current-season promise | **Confirmed.** | `hero.tsx:63` "assembles … the annual update"; `for-farmers/page.tsx:96-98` "the annual update itself assemble[s]"; `how-it-works.tsx:30,32,76` "Renewal Ready", "back every answer"; `common-osp/page.tsx:130` "nothing is missing"; `methodology/page.tsx:9,36` "certifier-ready records"; `layout.tsx:40,63,122`, `page.tsx:30`; `lib/blog-data.ts:543`. Backend prints "The packet cannot stand in for the filing" when no filing exists (`osp_module_pdf.py:1703`). `check-copy.mjs` has no rule for these. | Landing. | Name the outputs (records section, change-summary draft, acreage workbooks, inspection packet), the grower's review and signature, "your certifier's other requirements are yours to supply"; keep the next-cycle value. |
| 8b-06 Input approval language | **Partly confirmed.** Buyer-page chips already state a basis. Not these: | `utils/eventDescriptions.ts:1597-1599` (+es :379-382) "A pest treatment approved for organic growing was applied", chosen from subtype text or a name containing "neem", even when the grower recorded `not_organic`. `inputVerify.reminder` (:5594) "Your certifier adds approved inputs to the OSP" (the operator adds them, `certifications/views.py:858`). `app.exportInfoOrganic` (:759) "approved inputs" / "insumos aprobados" can describe a DRAFT list (`audit_export_service.py:15403`). Producer labels "Organic Approved" / "Aprobado orgánico" on the grower's own dropdown (app keys :1086, :7029-7038, :4658; backend `common/field_registry.py:528,556`, help_text `certifications/models.py:1075-1105`). Landing `organic-features.tsx:32`, `dual-output.tsx:244,263`, `plan-review.tsx:32`. | Buyer event cards, input lookup, export modal, producer forms, landing. | Neutral event description. Where a basis is shown: the recorded basis, attributed ("Recorded by the farm as: OMRI Listed"), plus its limit (a listing match does not show that this application was approved or met the listing's restrictions). Neither a listing match nor the server tier is presented as permission. |
| 8b-07 Migration contact handoff | **Confirmed.** | `cog-pro-migration/page.tsx:333` → `/contact?topic=cog-pro-migration`; `topic` never read; form (`contact-client.tsx:52-58`) has no file field; nothing says to email the CSVs or that a dry run comes first; `blog-data.ts:454` reads self-serve. Backend `import_cogpro` is a dry run unless `--commit`. | Migration page, contact page, blog. | Instructions (D2 addresses) on the migration page and on `/contact` for that topic; blog fixed. No upload feature. |
| 8b-08 Methodology consistency | **(a) partly, (b) partly, (c) stale copy, code stricter.** | (a) `methodology/page.tsx:389` "All emission factors are sourced from government publications and peer-reviewed literature" and :917 contradict the page's table and `carbon/services/verified_emission_factors.py:427-460` (P/K internal estimate). Separate: `carbon/services/emission_factors.py:50-71` labels P/K "EPA 40 CFR Part 98", confidence high, docstring "All factors are USDA-verified"; whether that reaches an output is not yet traced. (b) :64-65 "not a consumer-facing claim" vs public, collapsed-by-default buyer section (`ProductDetail.tsx:2117-2128`, `CarbonImpactExplainer.tsx:54`). (c) §7.2 (:762-779) describes threshold token/brand matching; code counts only exact normalized catalog matches or curated aliases (`drift_detector.py:816-818, 1081-1090`) across OMRI, WSDA, National List and the plan list; partial hits are "possible match". | Methodology page; possibly backend metadata. | Copy matches behaviour, version bump. Backend metadata: trace first (S7). |

**Found while verifying (outside Astra's list):**
- **X1, security, landing:** `app/api/contact/route.ts:21-29` interpolates name, email, subject and message unescaped into the HTML email. Own commit in S3, mocked sender in the test, no real email.
- **X2, latent, app:** unreachable consumer carbon block in `EnhancedEventDetailModal.tsx` (would print "0 kg" for never-estimated events). Dead-code cleanup, last, never blocks pilot fixes.
- **X3, count drift:** `serializers_consumer.count_events_for_history` (:37-58) counts withheld EM events in the signed-in shopper scan count. No text leak. Fix in S4 if one line, else ledger.

## B. Slices, in order

Each slice: pair worktree from origin/main, isolated test DB, CI's own module list, review bot read, then Oscar's merge decision.

**S1 · access notice vs documentation findings (back + app) · 8b-01**
- Card renders two blocks: an access notice from the plan (Starter only, link to plan page) and the findings list. The findings block never mentions plans.
- Findings badge for pilot/Compliance: "Trazo requires these records before creating a review link" (true gate, stated as Trazo's).
- Rewrite `ofpp.missing`, `osp.none`, `records.none` (service English for packet/dossier, app EN/ES): "not on file in Trazo"; no "prohibits certification", no regulatory conclusion drawn from the gate. OFPP row: upload on profile, G2.0 module, setup help (D2 address). `records` row links to adding a season, not to itself.
- `readiness.blockedIntro` (preshare) in the same terms.
- Unchanged: codes, severities, the share gate, the plan gate, the dossier banner logic.

**S2 · pilot renewal-preparation checklist (app) · 8b-02**
- `isPilot` from `company.subscription` (same expression as Dashboard :218).
- Pilot checklist, required sequence only data-backed items relevant to renewal, each labelled by what its completion condition proves: "A parcel is on file" (`add-parcel`), "Season records are on file" (`document-event`), "An Organic System Plan is marked submitted in Trazo" (`file-osp`, whatever its completion rule actually reads; the label follows the code), "A fraud prevention plan is on file" (`upload-ofpp`). Grower review is never inferred from records being present or a plan existing; no item claims review, readiness or filing.
- Completion message for pilots: "These setup steps are complete", never "You're all set" or anything implying the renewal is ready to file.
- "How setup works" block above it, not counted as steps and never shown as incomplete: send existing records to Oscar (mailto, D2), Oscar enters them under his own login, you check them before anything is filed.
- `start-production`, `finish-production`, `share-qr` move to an "Optional" group for pilots; Starter checklist unchanged except one help line ("Have last season's records somewhere else? Get setup help", info@ per D2).

**S3 · landing truth (landing) · 8b-05, 8b-07, landing parts of 8b-06 and 8b-08, X1**
- Copy per table; methodology §7.2, factor sentence, carbon sentence, version bump.
- `/contact` reads `topic=cog-pro-migration` and shows where to send files and the dry-run step.
- check-copy rules, each narrow: `annual update (itself )?assembl`, `every answer in your`, `nothing is missing`, `renewal[- ]ready`, `certifier-ready`, `all emission factors (are|cite)`, `approved for organic growing`, `approved materials list`. No blanket "approved" ban.
- X1 escaping, own commit.

**S4 · cleanout note audience (app; back test) · 8b-04, X3 (D1 stays open)**
- ProductionTab certifier-only variant for withheld subtypes, EN/ES.

**S5 · approval wording (app + back) · 8b-06**
- `eventDescriptions` composition branch → neutral ("A pest treatment was applied"); no organic statement in the description.
- Where a basis appears (event card, preview), each statement names its actual source and keeps its limit: "Recorded by the farm as OMRI Listed" (operator's `organic_approved` value) is distinct from "Matched by Trazo to a catalog entry" (catalog FK / server tier). Neither establishes that this application was approved or met the listing's restrictions.
- `inputVerify.reminder` (operator adds, certifier reviews), `app.exportInfoOrganic` ("inputs on your plan's materials list"), producer labels → "Organic basis" / "Base orgánica"; backend `field_registry` labels and model help_text (help_text generates a no-op migration; included). The operator's own option "Reviewed and approved by my certifier" stays: it is an attributed operator statement.

**S6 · Spanish crew journey, partial (app) · 8b-03**
- ~80 journey usted strings → tuteo; 3 voseo fixed; ProductionTab harvest/cleanout options and placeholders, sign-up/verify toasts, QuickStart method labels through intl; Settings company-type labels through intl ("Finca familiar").
- Guard: su/sus and usted present tense in the journey prefixes (explicit third-person allowlist), mid-sentence imperatives, unaccented voseo-with-pronoun list.
- 8b-03 stays open: Soil/Pest option lists and OSP module Spanish named in the ledger.

**S7 · carbon metadata (back) · 8b-08 backend · after S1-S6**
- Trace first whether `emission_factors.py` P/K source/confidence reach any current output. If yes: defect fix with a test, labelled as such. If no: align metadata in a small commit or leave a ledger line; no expansion.
- X2 dead-code removal here, optional.

## C. Acceptance criteria and tests

Behaviour tests where state or the public boundary is at stake; static wording needs a test only where a guard already covers the pattern. Each new guard mutation-checked (old value re-applied once, red on an AssertionError).

- **S1**
  - Empty organic Starter farm: readiness still returns exactly the 3 blockers (existing test green: real gaps preserved); the card shows the access notice AND all three findings; the findings block contains no plan wording.
  - Pilot and Compliance farm without an OFPP: no access notice; findings badge "Trazo requires these records before creating a review link"; link minting still refused (existing test).
  - Catalogue test: no readiness title/detail/intro in either locale contains "prohibits certification" / "prohíbe la certificación" / "will not accept".
  - After G2.0 completion or an upload, the OFPP row disappears (existing completion rule, asserted on the card).
- **S2**
  - A company provisioned by `provision_pilot` serialises `subscription.plan.slug == "pilot"` (back test, if not already pinned).
  - Pilot company: required list = the four items; "How setup works" rows render, are never counted, never marked incomplete; QR/season-closing appear only under Optional.
  - Pilot company with records and an OSP but no grower review recorded: no item or message says the records or plan were reviewed; the completion message, when shown, is exactly "These setup steps are complete".
  - Starter company: checklist unchanged plus the help line; no pilot rows.
- **S3**
  - `pnpm check:copy` red on each new phrase (rule added, old string re-applied once).
  - `/contact?topic=cog-pro-migration` renders the instructions; plain `/contact` does not.
  - X1: message containing `<a href=…>` / `<script>` arrives escaped in the HTML body; sender mocked.
- **S4**
  - RTL: for EM, BU, SS, TP the form never renders `observationAudience` or `certifierRecordAndBuyer`; for harvest it still does.
  - Back: EM event with observation text absent from `/api/transparency/<uuid>/` for a non-owner (EM-specific case the suite lacks). Owner and certifier exports still include it (existing tests).
- **S5**
  - A chemical event recorded `not_organic`, or named "neem" with no basis, never produces a description containing "approved for organic" / "aprobado para".
  - Where a basis renders, it is attributed and carries the limit sentence; an exact listing match alone never renders "approved" (behaviour test on the card).
  - Key-list guard over Trazo-voiced keys only (event descriptions, export description, lookup reminder); attributed operator options exempt.
- **S6**
  - Extended `spanishRegister` red on one re-applied usted string, one mid-sentence imperative, "Comparalo"; parity and default-message guards green.
  - Sweep limited to catalogue and component literals; stored operator text untouched.
- **S7**
  - Only if metadata reaches an output: a test that the output names P/K as a Trazo estimate.

## D. Ledger (new "Run 8b" section in `OSP-ALIGNMENT-2026-10/LEDGER.md`)

Columns separate the old problem from the fix. "Pending" means pending, never inferred.

| 8b | Baseline observation (the problem) | Code/test evidence | Deployed commit | Live confirmation |
|---|---|---|---|---|
| 01 | Astra 8b, 2026-10-12, new Starter account (es-419) | verdict 2026-10-13; S1 tests when merged | pending | post-deployment confirmation pending |
| 02 | Astra 8b, checklist | S2 tests | pending | pending (needs a test pilot account; Oscar decides whether to provision one) |
| 03 | Astra 8b, forms, templates, OSP, pricing | partial (S6); Soil/Pest and OSP module Spanish OPEN | pending | pending |
| 04 | Astra 8b, cleanout form | backend withholding already tested; S4 form tests | pending | pending |
| 05 | Astra 8b, landing | S3 check-copy | pending | pending |
| 06 | Astra 8b, landing and export description | S3, S5 | pending | pending |
| 07 | Astra 8b, migration page | S3 | pending | pending (read only, no message sent) |
| 08 | Astra 8b, methodology | S3; S7 trace | pending | pending |
| X1-X3 | found in code 2026-10-13 | S3 / S7 / S4 | pending | X1 not live-testable without sending mail: code evidence only, said so |

**Outstanding Run 8 work, unchanged until demonstrated live:** buyer-page corrections, recipient review link, current packet contents, combined audit export, CSV contents (a download completed; contents unread), chemical lookup fixes, voice, phone width, offline (the 2026-10-06 pass was local, not production). Run 8 and 8b are not marked complete.

## Decisions (Astra's answers applied; revision 3 corrections from Astra's final review)

- **D1 legacy equipment: OPEN, unchanged this round.** The rows are public today and pinned by tests, but existing tests prove current behaviour, not that it is appropriate, and privacy is never classified from keywords. Resolve separately, from evidence about those records' intended audience. The confirmed EM/BU/SS/TP form-disclosure fix (S4) proceeds now.
- **D2 contact.** `oscar@trazo.io` for assisted pilot setup (app checklist, setup help, pilot letter); `info@trazo.io` for general enquiries and the landing contact form. The migration page says plainly: email the CSV files as attachments to oscar@trazo.io. Requires Oscar to monitor both.
- **D3 OFPP gate.** Preserved this round, worded as Trazo's requirement. This does not assert the gate is a certifier requirement.

## E. Live confirmation and production operations (separate lists)

### E1. Checks for the corrective changes (no production data operation needed)
1. New Starter account, organic: access notice separate from findings; findings say "not on file in Trazo" with upload, G2.0 and help.
2. Pilot view (only if Oscar provisions a test pilot): renewal items required, setup block not counted, QR optional.
3. Cleanout, Buffer, Seed Search, Transport forms (es-419): no buyer-page promise in the note field; harvest keeps it.
4. Landing pages in S3; migration page and `/contact?topic=cog-pro-migration` (read only).
5. Methodology: factor sentence, carbon sentence, §7.2, version.
6. Spanish crew journey (sign-up, harvest, cleanout, template picker).
7. Event card and preview: no "approved" from a guess; attributed basis with its limit.

### E2. Outstanding Run 8 checks (need the Calapooia specimen as it is, or after an approved operation)
Buyer page; recipient review link; packet contents; combined audit export; CSV contents; chemical lookup; voice; 375 px; offline; template guidance text (Run 8 finding 23: copper rate and blanket approval wording).

### E3. Production data operations (each separate, each its own approval; none is a prerequisite for E1)

| Operation | Purpose | Records affected | Dry-run evidence before approval | Needed for |
|---|---|---|---|---|
| `sync_template_guidance` | Template guidance text matches the I3 fix | Template guidance fields; historical plan items untouched | dry-run diff listing each template and field | template guidance checks in E2 |
| `reevaluate_certification_verification` | Re-plan rows stored `verified` after V1 | Certificate verification states | dry run; note: refuses while the Integrity Database is empty | demo certification card checks |
| `clear_developer_verification_note` | Remove the developer instruction from stored notes | Certificate verification notes | dry-run list, `--restore` report | same |
| Calapooia reseed | Rebuild the demo specimen after run 8 changes | Calapooia data incl. the ASTRA production, its four events, documents 24 and 25 | `--dry-run` deletion list; **ASTRA evidence preserved first** (export of the production, events, documents and screenshots filed in the audit folder) | buyer page / packet checks only if the current specimen cannot show them |

The ledger confirms only `recompute_unreported_carbon` has run. Every operation goes through `common/services/data_operations.py` (dry run, snapshot, audit row, restore).

Not done in any slice: deploys outside Oscar's merges, billing, publishing records, external review access, messages, signing, filing.
