# Run 8b residuals: corrective plan (2026-10-15)

Scope: the five live observations from Astra's 2026-10-14/15 confirmation, the blocked Starter fixture, and the
evidence gaps. Code read at back 317a714, app 9f56650, landing f497725. Nothing implemented, nothing run on
production. Run 8b stays open.

## 1. Verdicts

| # | Observation | Verdict | Evidence |
|---|---|---|---|
| 1a | "Or sign up with" in Spanish sign-up | Confirmed | Hard-coded literal `AppSignUp.tsx:1255`; same literal `SetupPassword.tsx:1011` (pilot invitation page). Sign-in already uses `auth.signin.orContinueWith`. Consumer sign-in/up hard-code "Or continue with" (`ConsumerSignIn.tsx:547`, `ConsumerSignUp.tsx:748`). No guard: key guards cannot see literals. |
| 1b | "Qué hizo, cuándo y quién lo hizo" | Confirmed | `events.wizard.step.basicHint` (`es-419.json:5288`), rendered `NewEvent.jsx:237`. `spanishRegister.test.ts` checks past tense only by a closed phrase list; bare "hizo" is also valid third person (7 legitimate uses in `events.*`), so a narrow `qué hizo(?=[,?])` phrase is the safe guard. |
| 1c | Same journeys, quick scan | Found more | Sign-up "Check your email" success state and join-code strings hard-coded English (`AppSignUp.tsx:642,720,746,1471-1530`); sign-in toasts (`AppSignIn.tsx:150-283`); `app.errorLoadingEvent` missing in both locales (`NewEvent.jsx:3403`, shows the raw key). Hard-coded English tip in the notes section, "Why This Matters to Consumers ... sustainable, transparent farming practices" (`ProductionTab.jsx:5650-5657`): untranslated and a general-benefit virtue sentence. |
| 2 | Notes heading on certifier-only records | Confirmed | `events.section.fieldNotes` rendered unconditionally (`ProductionTab.jsx:5668`). `noteIsCertifierOnly` (`:1093`, from `isEventOnBuyerPage`, `consumerDisplay.ts:131`) already switches badge, label, helper and placeholder, not the heading. Voice and paste use the same helper (`NewEvent.jsx:3814`); `VoiceEventCapture.tsx:829-846` deliberately keeps buyer wording when the parser hears a published activity. Other tabs (Chemical, Pest, Soil, General, Business, Weather) only log public records, so their heading is accurate. |
| 3 | "What shows this input is allowed for organic use?" | Confirmed | `events.chemical.form.organicBasis` (`ChemicalTab-ENHANCED.jsx:1869`); stale `defaultMessage` "How is this input verified for organic use?". Soil and pest labels already read "Organic basis". Soil select hard-codes 5 English option texts (~`SoilManagementTab.jsx:1565-1579`). `certifier_approved` ("Reviewed and approved by my certifier") is operator-recorded and stays. Quick-add option list still offers retired values; it is unmounted UI but voice/templates import it. No test pins the chemical label. |
| 4 | Template switches fields, not activity | Reproduced in code (not in a browser) | `handleTemplateSelect` (`NewEvent.jsx:2241-2246`) merges `type: tpl.subtype` but never sets `pickedVerbKey` (heading stays) and clears nothing (cleanout preset `equipment_operation_type: 'CL'` and typed cleaning fields are submitted with an HA record; `cleanEventData` passes them through). Name freeze is the language switch: `autoNames` (`ProductionTab.jsx:1161-1165`) holds labels in the current locale only, so the English auto-name counts as operator-typed after switching to Spanish; in English it would regenerate. Saved record: HA, name "Equipment cleanout", leftover cleanout fields. Privacy: notes typed under the "certifier-only" promise on EM become a public HA note with no confirmation. Picker filters by event type only (`templatesForEventType`, `templateAccelerators.ts:113`). Same for chemical (a pest-control answer can become fertilization) and plan items (`_fulfil_plan_item` closes without checking subtype). Separate bug: "Equipment maintenance" template writes `equipment_operation_type: 'routine_maintenance'`, not a valid code (valid: FC/MN/RE/CA/BD/EI/CL). Voice/paste do not have the mismatch: they offer "Switch to X" and `handleVoiceSwitchType` clears and re-titles. |
| 5 | "7 CFR § nonsyn" | Confirmed | Spinosad's row has `cfr_section="nonsyn"` since migration 0040 (eCFR check: nonsynthetic, not a National List entry). Calapooia's events link it by name; the signal stamps `legacy_unverified`. `claim_resolver.py:375-391` emits `national_list_link` with raw `cfr_section` without checking `is_national_list_entry` (the confirmed path in `claim_authority.py:276-281` does check). `ConsumerEventCard.tsx:1288-1312` formats "7 CFR § {cfr}" and calls it "A National List entry", both false for a nonsynthetic row. Latent: `serializers.py:5191-5195` ships raw `national_list_cfr_section` on the anonymous payload (no reader today). Every other surface (audit PDF, OSP materials, workbooks, OMRI verifier, producer helpers) is guarded or prints prohibited rows only. Tests lock the defect in: `test_buyer_page_states_the_record.py:89-100` asserts raw pass-through; `inputBasisNamesItsSource.test.tsx:129-131` uses Spinosad with `205.601`; `national_list_basis.py:13` cites a guard test that does not exist. |
| F | Starter fixture blocked | Confirmed (expected) | The account stopped at company setup, so readiness has nothing to evaluate. Minimal state found (below). |

## 2. Slices

All from origin/main in pair worktrees, CI-green PRs, review bot read, never merged by me.

**R1 app: Spanish remnants** (small)
- `auth.signup.orSignUpWith` in both locales; use in AppSignUp and SetupPassword. Consumer sign-in/up use `auth.signin.orContinueWith`.
- `basicHint` es-419 -> "Qué hiciste, cuándo y quién lo hizo".
- Same two journeys only: sign-up success state, join-code strings, sign-in toasts to keys; add `app.errorLoadingEvent`.
- Tests: `spanishRegister.test.ts` gains `qué hizo(?=[,?])` plus a guard-the-guard case; an es-419 render of AppSignUp asserting "O regístrate con" and no "Or sign up with".
- Not in scope: Soil/Pest option lists, the 11 help lines, backend OSP Spanish.

**R2 app: notes heading follows visibility** (small)
- New `events.section.fieldNotesCertifierOnly` ("Field notes for your certifier" / "Notas de campo para tu certificadora"), used when `noteIsCertifierOnly` in ProductionTab. Public subtypes keep `events.section.fieldNotes`.
- Remove the hard-coded "Why This Matters to Consumers" tip (virtue claim, untranslated) or move it to keys with neutral wording; decide in the PR (recommend remove: the badge and helper already say who sees the note).
- Voice: keep the existing documented rule (parser-detected published activity keeps buyer wording); no change.
- Tests: `certifierOnlyNoteAudience.test.tsx` locates the section by either heading, asserts the certifier heading for BU/SS/EM/TP and no "Consumer Transparency"/"transparencia para el consumidor" in that section, EN and ES; HA keeps the public heading.

**R3 app: organic basis label** (small)
- `events.chemical.form.organicBasis` -> "Organic basis" / "Base orgánica"; the question moves into `organicBasisHelp`; placeholder "Select the organic basis..."; stale defaultMessage removed.
- Soil select uses the existing `events.organicApproved.*` keys (fixes 5 English options in Spanish).
- Keep `certifier_approved`; no automatic approval anywhere.
- Tests: every grower organic-basis label equals "Organic basis"/"Base orgánica"; `certifier_approved` offered in chemical and soil; no literal `<option>` text in the soil organic select.
- Deferred, named: pest yes/no/unknown wording; quick-add option list alignment (voice reads it, separate slice).

**R4 app: templates cannot change the activity** (medium; needs decision D1)
- Recommended option A: offer only templates whose subtype equals the current `eventFormData.type`; `templatePrefillValues` no longer writes `type` (assert instead). Hide the button when none match (existing behaviour). Changing activity stays where it already works properly: "Not X? Choose a different activity" and the voice "Switch to X".
- Fix the "Equipment maintenance" template to a valid code (MN) and verify the § 205.272 section logic.
- Fix the auto-name freeze: `autoNames` includes the labels in both locales, so a language switch never turns an auto-name into an operator name; operator-typed names stay untouched.
- Tests: picker under each verb offers only same-subtype templates (cleanout offers no harvest); applying a template never changes `type`; a cleanout record cannot be submitted with HA after a template; auto-name regenerates after a locale switch; operator-typed name survives; `omriAttachIsExplicit` merge count still holds.

**R5 back + app: National List citation from provenance** (medium; back first)
- Back: `claim_resolver` emits `national_list_link` only when `substance.is_national_list_entry`; the link carries the model's `citation` (`§ 205.601(e)` form) instead of raw `cfr_section`. For a nonsynthetic row no link is emitted, so the existing grower-reported text ("No OMRI, WSDA or National List entry is linked") is the true statement. `serializers.py:5191` sends `citation` or nothing, never a raw code. Route the audit export formatter (`:6456`, `:14498`) and `omri_verifier.py:551` through `.citation` for one shape.
- App: `ConsumerEventCard` prints the server citation only when it matches `^§ 205\.60[1-6](\([a-z]\))?$`; otherwise the no-reference wording. No citation is built from a substance name.
- Tests: replace the raw pass-through assertion; add the missing `test_national_list_basis`; legacy link to a nonsynthetic row yields no citation and no "National List entry" sentence (anonymous and signed-in payloads); confirmed link to a real entry prints `§ 205.601(e)`; fix the Spinosad/205.601 fixture in `inputBasisNamesItsSource.test.tsx`; frontend refuses a non-section value. Each red on main.
- Not in scope: reclassifying Calapooia's links (data), the broader classification project.

**R6 back: Starter review fixture command** (small; production run is a separate approval)
- `subscriptions/management/commands/provision_starter_review_fixture.py`, modelled on `provision_pilot`: dry run unless `--commit`; `--remove`.
- Refuses unless the email matches `^oscar\+astra[a-z0-9]*@trazo\.io$`, the user passes the login gates and has no company, Starter exists and lacks `compliance_exports`.
- Writes in one transaction: Company "ASTRA TEST Starter Review"; Starter subscription (active, as the sign-up view creates it); WorksIn as Company Admin; Establishment "ASTRA TEST Organic Farm" with `farming_method="organic"`, `is_demo=True`, WA, in the farms in charge; one `DataOperationLog` row. No parcel, production, certificate, OSP, plan file, invitation, alert email, Stripe call, review link, publication or document.
- Side effects found: one `SubscriptionEvent` (MRR 0) from the subscription signal; one auditlog entry on the Establishment. Both removed by the cascade on `--remove`.
- Post-check prints PASS/FAIL: plan starter, no `compliance_exports`, active company is this one, readiness `applicable` with exactly `ofpp.missing`, `osp.none`, `records.none`.
- `--remove` refuses if any member, non-demo farm, parcel, history, certificate, OSP, document or review link was added.
- Tests (isolated DB, no keepdb): dry run writes nothing; commit writes exactly these rows; `mail.outbox` empty with `SIGNUP_ALERT_EMAILS` set; Stripe patched and not called; no Notification/review link/OSP/Certification/document rows; readiness codes; each refusal with a can-fail mutant; rerun is a no-op; remove and its refusals.
- Production action (for separate approval, after merge and deploy):
  ```
  doctl apps console 0a91c6a9-5d56-4f7d-9bb9-042bdcd67174 trazo-back
  python manage.py provision_starter_review_fixture --email oscar+astrastarter@trazo.io
  python manage.py provision_starter_review_fixture --email oscar+astrastarter@trazo.io --commit
  ```
  Effects on production: 1 company, 1 subscription (Starter, $0), 1 membership, 1 demo farm, 1 subscription event, 1 audit log entry, 1 data-operation log. Removal: same command with `--remove --commit`.

**R7 CI allowlist (Oscar, web edit)**
CI-safe modules with no cross-repo lookups that cover these gaps and never run today: `users.tests.test_signup_alerts_and_terms`, `history.tests.test_consumer_production_subtypes`, `history.tests.test_private_note`, `history.tests.test_readiness_codes`, `history.tests.test_wsda_listing_attachment`, `carbon.tests.test_voice_known_activity`, plus R6's module. Check line-continuation backslashes.

Order: R1, R2, R3 independent (one app PR each, merge R2 before R3 if both touch ProductionTab/locale lines). R5 back before R5 app. R4 after D1. R6 any time; its production run after R6 deploys and your approval. R7 after R6 merges.

## 3. Evidence gaps (code/test evidence, not live)

| Gap | Existing tests | In CI? | Missing |
|---|---|---|---|
| Catalog-match badge | app `inputBasisNamesItsSource.test.tsx` (catalog match attributed to Trazo with its limit, EN/ES; exact OMRI match never renders approval), `growerChipStatesTheRecord`, `serverStatusIsTranslated`; back `test_cross_surface_claim_safety`, `test_buyer_page_states_the_record` | app yes; back partly (`test_wsda_listing_attachment`, `test_input_status_preview`, `test_nonsynthetic_catalogue` not in CI) | A contract test feeding a real server `input_status` to the card. No public prod lot has a matched input (Duke: 11 inputs, all farm-recorded), so live confirmation needs a lot with a catalog match. |
| No documentation percentage | `test_anonymous_payload_carries_counts_never_a_rate` + `test_rate_guard_can_fail` | yes | Prod Duke lot has `organic_summary` null while the fixture populates it; add a case with the null branch. |
| Terms version on sign-up | `users/tests/test_signup_alerts_and_terms.py` (email, invitation, Google, first acceptance kept) | no (`users` not in CI) | CI (R7); a test pinning the literal to the published "Last updated" date is cross-repo, so keep it manual. |
| Voice end to end and saved privacy | app `VoiceEventCapture.notesAudience`, `certifierOnlyNoteAudience`, `buyerPageVisibility`, `voiceWizardMerge`, `voiceRenderGate`; back `test_voice_*` (CI), `test_crew_note_provenance`, `fieldnotes.tests.test_voice_notes` | saved-output privacy tests (`test_consumer_production_subtypes`, `test_private_note`) not in CI | Backend: transcript-shaped EM create through the API, then the anonymous and signed-in non-owner payloads exclude the note (one test). Live transcription stays mocked. |

## 4. Live recheck checklist

Fixture state: Calapooia as is; ASTRA Test Pilot empty; Starter fixture provisioned (R6, after approval).

1. `/auth/signup` in Spanish: "O regístrate con"; success state in Spanish. Pilot invitation page the same.
2. Calapooia, Home Field East, Log activity, any activity, step 1 in Spanish: "Qué hiciste, cuándo y quién lo hizo".
3. Log activity, Equipment cleanout / Transport / Buffer use / Seed search, step 2: section heading "Field notes for your certifier" (EN) / "Notas de campo para tu certificadora" (ES); Harvest keeps the buyer-page heading.
4. Log activity, Input application, step 2: "Organic basis" / "Base orgánica"; Soil amendment options in Spanish.
5. Log activity, Equipment cleanout, step 2, Use a template: no Harvest template offered; heading, name and fields stay cleanout. Switch language mid-form: auto-name follows the language.
6. `consumer.trazo.io/production/72248e35-5b5b-4410-b9d5-5f44b001a551?view=proof`, Entrust SC card: no "§ nonsyn" and no "National List entry" for spinosad. Counts still match the page (do not hard-code).
7. Starter fixture login, EN and ES: Compliance access notice separate from findings; three findings worded "not on file in Trazo"; fraud prevention plan row offers upload, G2.0 and oscar@trazo.io help. Do not press upload.
8. Regression spot checks from the confirmed list: pilot checklist labels and completion text, certifier-only alerts, methodology 2.2, Terms dated October 14, 2026, no Carbon Neutral option.

## 5. Decisions for Oscar

- **D1 template behaviour.** A (recommended): templates only fill fields for the chosen activity; changing activity happens only through "Not X?" or voice "Switch to X". B: picking a template switches the whole activity (heading, subtype, cleared fields, name, plan item handling, a confirmation when notes would become public). B is broader and re-adds a second place to answer the activity question that the 2026-08-22 change removed.
- **D2 "certificador" vs "certificadora"** in Spanish copy: badge says certificador, helper and alert say certificadora. Pick one for the new heading (recommend "certificadora", the agency).
- **D3 the "Why This Matters to Consumers" tip** in the notes section: remove (recommended) or rewrite.
- **D4 R6 production run**: approve separately after the command is merged and deployed.
- **R7**: the CI workflow edit is yours (web).

## 6. Revision 2 (Astra review, 2026-10-15): approved with corrections

Decisions: D1 = A, D2 = "certificadora", D3 = remove the tip, D4 = production fixture run approved separately.

1. **R4 matches the activity, not only the subtype.** Compatibility = the selected activity verb's subtype AND its
   discriminating preset (e.g. cleanout = EM + `equipment_operation_type: 'CL'`; maintenance = EM + MN). Enforced in
   the picker AND in `handleTemplateSelect` (an incompatible template is refused even if offered by another path).
   Test: notes typed while the form said certifier-only can never end up on a public subtype through a template.
2. **Name origin is tracked, not inferred from text.** The wizard records whether the operator edited the name
   (touched flag). Auto-name regenerates only while untouched; when origin is unknown (edit mode, drafts restored
   without the flag), the name is preserved. A name that happens to equal a default but was typed is kept.
3. **R5 keeps citation validity and match confirmation separate.** The citation is printed only from the model's
   `citation` for a real entry; the unconfirmed/legacy disclosure is independent and always shown for a
   non-confirmed basis. Frontend validation tests the formats the backend actually emits (from `.citation` and
   seed data, e.g. "§ 205.601(e)", "§ 205.601(e)(8)" if subsections nest, "§ 205.605(b)"), not a guessed regex.
   Spinosad gets no section: it is nonsynthetic, not a National List entry.
4. **Inference vs reproduction.** Observation 4 is a code-based inference until the payload test exercises the save
   path. The ledger says "reproduced" only after that test is red on main.
5. **Starter fixture scope.** It covers the readiness card only: access notice, the three "not on file in Trazo"
   findings and the fraud prevention plan row actions, in EN and ES. It does not cover a Starter event journey;
   that stays open. Readiness state is rendered and checked locally before any production request. The command
   distinguishes an identical rerun (no-op) from an account holding other company data (refuse).
6. **R7 is an ordinary PR.** Reason for the hand-off: the `gh` token lacks the `workflow` scope, and GitHub treats
   merging a PR that edits `.github/workflows/ci.yml` as a workflow update (`refusing to allow a Personal Access
   Token to create or update workflow ... without workflow scope`). Pushing over SSH works. So Claude opens the PR
   with the exact diff; Oscar merges it in the web UI or grants the scope (`gh auth refresh -s workflow`).
   Tests outside CI are never reported as CI-verified.

**Recheck limits:** sign-up success, invitation acceptance and real voice transcription cannot be confirmed under
the read-only, no-submission rules. They rest on automated evidence and are labelled "live: untested". No new lot is
published to demonstrate the catalog-match badge.

Implementation proceeds in small PRs. Deployment and the Starter production action remain separate approvals.
