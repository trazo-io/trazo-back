# OSP alignment audit 2026-10: ledger

Companion to `AUDIT.md` (Astra's report, unedited), `ERRATA.md` (where we read it differently) and
`IMPLEMENTATION-PROMPT.md` (Astra's suggested sequence, kept as input; the sequence below replaces
it). Earlier findings T01–T14 stay in `../E2E-AUDIT-2026-09/LEDGER.md`; AUDIT.md §10 re-scores them
and that is not repeated here.

## Evidence pins

| Repo | Commit | Why this one |
|---|---|---|
| trazo-back | `4959284` | The five packets were generated here (2026-09-29, local demo DB, OSP id 66 v4 draft). `certifications/`, `product/`, `history/services/` and `documentation/compliance/` are byte-identical at `7e0673e`. |
| trazo-back | `7e0673e` | Field notes only (T29): `fieldnotes/services/retention.py` changed after `4959284`. |
| trazo-landing | `f3bb9fb` | Public copy (T30). |
| trazo-app | `bf08370` | T29 only (`src/views/Dashboard/FieldNotes/CrewRoster.tsx`). |

Every file:line below is at the pinned commit. Re-read with
`git show <commit>:<path> | sed -n '<a>,<b>p'`.

## How a finding is scored

One collapsed verdict hides where the fault is. Each finding is judged on five separate axes:

| Axis | Question |
|---|---|
| **Schema** | Can Trazo capture the answer at all (a module question or model field exists)? |
| **Mapping** | Does the register row cite the Trazo question that actually answers the official question? |
| **Specimen** | Did the Calapooia Bend demo populate it? |
| **Rendering** | Does a populated answer reach the packet file a reviewer reads? |
| **Disclosure** | When it is unanswered or unsupported, does the packet say so specifically? |

Status tags: `code-defect` · `mapping-defect` · `specimen-gap` · `render-gap` · `disclosure-gap` ·
`open-question` · `refuted`. A finding can carry several. "ok" means we found no fault on that axis.

Two rules that follow from the scoring:
- **Mapped is not answered, and answered is not adequate.** `register_status: complete` says the
  transcription exercise is finished. It is never a packet-completeness signal.
- **A Trazo annual update is supporting material, not the agent's renewal form.** Even a filed
  `OSPAnnualUpdate` does not complete OTCO's OSP Update Application & Agreement, WSDA AGR 2516 /
  2521, or CCOF's annual renewal. Those are the agent's own forms, signed and filed with it.

## Findings

| ID | Sev. | Schema | Mapping | Specimen | Rendering | Disclosure | Tags | Phase | Status |
|---|---|---|---|---|---|---|---|---|---|
| T15 | HIGH | ok | ok per row | n/a | n/a | Page 04 heads the list "Forms generated in this packet" (`osp_module_pdf.py:2130`). `_classify` (`packet_coverage.py:252-288`) lists a form once any module or packet document maps to it and never reads row verdicts or answers. Only mitigation: the separate "Sections of this plan still to finish" list (`outstanding_modules`, `packet_coverage.py:420`). | disclosure-gap, code-defect | 1 | partly resolved (disclosure), merged in back #64. Page 04 reads answers per register row; no form is listed as answered unless every in-scope row is closed |
| T16 | HIGH | 3-question stub `CERTIFICATION_CONTRACT` (`osp_modules/stubs.py:1158`) vs NOPB06 sections A–H | `ccof/forms/Certification-Contract.yaml` maps NOPB06 to the stub: 24 rows, 2 covered | n/a | prints as the contract | 04 lists "CCOF Certification Contract (NOPB06): modules/certification_contract.pdf" as generated | code-defect, disclosure-gap | 1 | partly resolved (disclosure), merged in back #64. Listed as filed with the agent; module renamed Operation profile. Capturing NOPB06 A–H stays Phase 2 |
| T17 | HIGH | per item (ERRATA) | 1 wrong (Contract D2 indirect export), 2 partly (WSDA 2264 Q13, Parcel B), stray wash-water citations on G6.4 B1 / 2121-L 5, 5a; 4 disputed | several "no answer" = demo unanswered | n/a | n/a | mapping-defect, specimen-gap, open-question | 2 | mapping corrected, follow-ups open (back #72). Contract D2 now offers indirect and planned export, with the old answer retired and read as unconfirmed; 2264 13 no longer cites the prohibited-material declaration; Parcel B is an instruction, not a covered question; the wash-water citations are off G6.4 B1 and 2121-L 5, 5a. The four disputed items were re-read against the PDFs: three refuted, G8.0 A1 downgraded to partial (ERRATA). Open: T17-F1, T17-F2 |
| T18 | HIGH | ok | exact-name matching only (`common_osp_workbooks.py:364`) | Neptune 2-4-1 vs 2-3-1, Tsunami vs SaniDate in demo data | blank use/comment cells by design (`:785-808`) | an unresolved product identity is never flagged | code-defect (matching), specimen-gap | 5 | open Phase 5 slice 1 (code and tests, not yet packet-observed): partial-name National List matches are suggestions, never classifications or citations; stored classifications keep their value and are marked `legacy_unverified` (20 in production, all on the demo farm, counted before migrating); the drift detector clears a finding on exact catalog names only and notes partial hits. Identity decisions, review suggestions and restriction statements are slices 2 and 3. |
| T19 | HIGH | equipment-cleaning questions exist (`stubs.py:413-672`); no brand-owner question (G7.0 C2) | G6.0 C2 honestly `not_covered` | cleaning questions unanswered in demo | **uploaded label files never reach the packet** (G7.0 A1/B1 P1) | a required label attachment that is absent is not named per question | render-gap, disclosure-gap, specimen-gap | 1 (disclosure), 3+ (attachments) | partly resolved (disclosure), merged in back #64. Missing label files named per question. Phase 3 S3, back #81 and app #58 (rendering and disclosure): a file uploaded for the label question rides in the packet under labels/ and is named on the G7.0 page; one that could not be read or did not fit is named and does not answer. Phase 3 S6 (specimen): Calapooia ships a label file against the G7.0 requirement and the G7.0 page names its ZIP path. Open: equipment-cleaning answers and the brand-owner question (unchanged) |
| T20 | HIGH | `OSPAnnualUpdate` exists | OTCO OSP-Update and WSDA 2516 map to `packet_documents` 02 + 03 | v4 has no filing | 02 prints "No § 205.406(a) annual update is on file…" (`osp_module_pdf.py:1494`) | 04 lists both forms as generated whether or not anything is filed (`packet_coverage.py:275`); and even when filed, 02 is not the agent's form | disclosure-gap, code-defect | 1 (disclosure), 3 (renewal) | partly resolved (disclosure), merged in back #64. Update forms listed as filed with the agent, filed or not. Phase 3 S1, back #79 and app #57 (schema; disclosure of revision and legacy state): a filing is a chain of signed revisions; (a)(3) and (a)(4) are captured; 02 is the filed bytes and 02s carries later status. Phase 3 S2, back #80 (mapping and disclosure of each agent's renewal forms): CCOF's renewal contract and NOPB88 and WSDA's AGR 2521 are registered, and 02s routes each agent's operation to its own renewal forms with a crosswalk. Phase 3 S6 (specimen, rendering end to end): Calapooia's August 2026 filing is revision 1, legacy and disclosed as such; revision 2 corrects it with (a)(3) and (a)(4), is signed, filed and frozen, and the packet ships its bytes unchanged; a v4 draft and a 2027 draft update leave both 2026 revisions untouched. **Implementation complete** on all five axes, shown by tests and the seeded demo. Not verified: the independent review of the regenerated packets, and any live filing with a certifier. **Run 3 (2026-10-02) reopens mapping, specimen and disclosure**: R3-01 (coming-year answers describe past changes), R3-02 (OTCO Step 5-4 mapped to a different promise; Step 6 locator stale), R3-03 (WSDA subtotal presented as the fee figure), R3-07 (revision 2 contradicts G6.0), R3-08 (cover says every document is live). Packet-observed by run 3: frozen bytes identical in all 11 copies, legacy revision 1 honestly disclosed, v4 draft labelled. Schema and workflow stay developer-tested, not shown by PDFs (R3-09). See "Run 3 review". |
| T21 | HIGH | declaration `dlpm_none_within_tenure` exists | Parcel B partly (ERRATA) | declaration unanswered | "Eligible" printed | Eligibility is "by absence of contrary evidence" (`product/services/transition_status_service.py:214-220`, verdict `:288`); the declaration never gates it. The 5/5 application count checks no address (`parcel_application_status.py:55-100`). | code-defect | 1 | partly resolved, merged in back #65 and app #53. No "Eligible"; declaration printed in its own states. Phase 3 S4, back #83 and app #60 (rendering and disclosure of land history): the clock reads soil amendments and beneficial releases too; an input of unknown status starts no clock and blocks a clean statement, named; the 36-month accounting counts the operator's period only with a declaration, never a logged season. Phase 3 S6 (specimen): every Calapooia parcel states it is certified, declines the no-inputs statement and prints its dated inputs per year; no "Eligible" anywhere. No prohibited or unknown input was added to the demo: on a farm certified since 2006 that would be a new contradiction (the T28 class). T21-F1 addressed (back and app PRs pending): a certified parcel follows its agent's own route. Still partly resolved: the answers-axis land-history check is agent-neutral (three years of rows or an affidavit) and is unchanged. Run 3: no packet page awards eligibility; dated inputs and the no-inputs No print. Not closed: R3-04, R3-05, R3-06 (see T21-F1). |
| T22 | HIGH | ok | n/a | destination "WVF Salem, IQF" vs handler narrative = demo data | The exhibit states the harvest-to-pack-out difference **is** "the handler's culls and shrink" (`osp_module_pdf.py:1760-1768`, from `audit_trail_exhibit.py:242-294`) with no cull record behind it. Invoice/BOL numbers print as text; nothing attached. | no statement that sources are not embedded | code-defect, render-gap | 1 (label), 3+ (attachments) | partly resolved (label), merged in back #65. No cause named for the difference. Phase 3 S3, back #81 and app #58 (rendering and disclosure): a sale's invoice, bill of lading or pack-out file rides in the packet under audit-trail/sale-<id>/ and the exhibit names it; a sale with only typed numbers says they are recorded as text, no source attached. Phase 3 S6 (specimen): the exhibit's lot shows one sale with its invoice attached and named, beside one recorded as text. **Partly resolved**: source attachments and their rendering are complete. Still open, not demonstrated: per-pick quantity allocation, dated loss evidence (the harvest-to-pack-out difference is stated, never evidenced) and custody or title reconstruction through the handlers (AUDIT §5; same open items as T03). |
| T23 | HIGH | n/a | fallback resolves to the CCOF register (`packet_coverage.py:195-200`) | n/a | For OCI, MOSA or any unregistered agent: "only the numbering differs" (`osp_module_pdf.py:2142-2154`), "file CCOF's own form where it applies" (`:2178`), and `ccof/scope.yaml` reasons "with CCOF directly" print verbatim | misroutes the operator | code-defect | 1 | partly resolved, merged in back #64. Fallback packets borrow no agent numbering; mapping OCI/MOSA forms stays out of scope |
| T24 | MED | ok | n/a | n/a | Module headings and filenames come from `module.code` for every agent (`osp_module_pdf.py:988-989`, `:2342`); `CCOF_MAP_ELEMENTS` hard-coded. Only 04 and the workbook filter vary by agent. | reviewer must use 04 as a crosswalk | render-gap | 5 | open |
| T25 | MED | n/a | n/a | v4 is a draft | 01 is titled "Organic System Plan: Submission Snapshot" regardless of status (`osp_pdf_snapshot.py:198`); the cover says draft | contradictory state | code-defect | 1 | merged in back #65 |
| T26 | MED | n/a | Grouped rows (G6.4 B1 a/b, G8.0 A1, Contract G, OTCO O1 D-2–6); CCOF Contract I/J absent while `register_status: complete` (unverified: the audit also calls NOPB06 sections A–H, see ERRATA); WSDA 2121-R ends at 7, both "7a" folded. Stale docstring `packet_coverage.py:377` ("20 of WSDA's 24 forms are drafts"). | n/a | n/a | n/a | mapping-defect | 2 | done (back #72, #75, #77): every registered form (55) carries `source_sha256`, and its rows match an inventory derived from the agent's own file, one to one and in order (`test_form_inventory`; `verify_form_inventory` re-derives all of them). Rows split where the form numbers or letters separately, refs follow the form, row kinds, `scope_basis` and optional flags added Run 3: the 58 form files and their inventories agree internally (907 rows: 857 questions, 46 instructions, 4 interpretations); 7 official sources re-downloaded and hash-matched by the reviewer. Extraction of all 58 originals was not independently re-run. |
| T27 | HIGH | n/a | **O1 transcribed from rev. 2025/08/27; live is rev. 2026/03/25** (widened section D, 3 new checkboxes). 13 other OTCO forms match. | n/a | n/a | n/a | mapping-defect | 2 | source verified and mapping corrected (back #72): O1 transcribed from rev. 2026/03/25, its rows checked one to one against an inventory derived from the live file (sha256 recorded). Open: T27-F1 (capture of the certification history D asks) |
| T28 | MED | n/a | n/a | Demo text contradicts itself: "no conventional production anywhere" vs buffer rows sold conventional; "onion sets" as annual seedlings | n/a | n/a | specimen-gap | Fixture | **done**, Phase 3 S6, on the two named contradictions only: narratives now say the shed and lugs are organic-only and the buffer fruit is sold as conventional process fruit (G6.0), and the onion material is called what the farm's own planting records show, cell-tray transplants. Guards in `test_calapooia_fixture_integrity`. v1 still answers "split operation: No"; that is the superseded plan as filed, corrected by v2. Run 3, R3-07: **not closed for the current packet**. Revision 2 (frozen, current) still says no split or parallel production while G6.0 answers Yes; the Home Field East buffer is called both unharvested and harvested; 02 says the Grandevo notice was acknowledged while 03 says it is not. The onion and shed/lug fixes print and stand. |
| T29 | HIGH if compliance claimed | `FieldNote` keeps sender, sender_phone, received_at, confirmed_by and the event it became (`fieldnotes/models.py:231-341` @`7e0673e`) | n/a | untested live | The event and every export carry only the confirming user; nothing in event serializers, audit export or OSP PDF reads `FieldNote` (`history/views.py:4093-4142` @`7e0673e`) | the record does not say it came from a crew note | code-defect, open-question | 4 | **partly resolved**, Phase 4 (back #88, app #63 and #64), on tested provenance and export only: each confirmation keeps an append-only history row (message as received, machine proposal and what was applied, values as first saved; voided, never cleared, on delete); the dossier, CSV and records export print sender, performer as entered and confirmer apart, with stated occurrence, receipt and confirmation times and record-specific § 112.161(a)(2), (a)(4) and (b) facts; the buyer page carries none of it; confirmation is atomic (a second save is 409); an application may come from a message only with input details typed by the confirmer (server-enforced by record type); a message that negates all or part of what it describes is manual review. Open: specimen (no crew notes in the demo, none invented), live capture (untested live), any attestation workflow Trazo does not support. |
| T30 | MED | n/a | n/a | n/a | Landing: 205.103(b)(3) cited for 5-year retention, correct is (b)(4) (`components/organic-features.tsx:79`, `app/cog-pro-migration/page.tsx:129`, `lib/blog-data.ts:367,388,568`); "The score measures how many events were documented" (`app/methodology/page.tsx:841-842`) on a page that says there is never a score; "The full regulated record" (`components/dual-output.tsx:209`); "complete records" (`app/demo/page.tsx:81`, demo video captions); "Every lot reconciles…" (`components/organic-features.tsx:45-47`) | claims exceed what the packet substantiates | code-defect (copy), open-question (fuzzy "Verified", ERRATA) | 1 | done: app #53, back #65 and landing #18 merged. Demo video captions still say "complete records" (needs a re-cut) Run 3: not demonstrated by the packets (landing copy was not in the bundle); "done" covers the landing and app copy only, the video captions are the named exception. |

### Follow-ups opened in Phase 2 (each closes only on the evidence named)

| ID | From | What is still open | Closes when |
|---|---|---|---|
| T17-F1 | T17, G8.0 A1 | Trazo's records attestation covers "the record types confirmed above", gated only on a non-empty list; CCOF A1 asks for ALL records the plan's activities need | the attestation is scoped to CCOF's wording, or the packet names the activity-implied record types left unconfirmed; a test fails when one is missing | **Phase 3 S5, back #84 and app #61 (gate and rendering): the statement covers every record the plan's own answers require (seven triggers, each one answer); Yes is refused while any is not confirmed, "not kept" included; the G8.0 page names each missing one by state. Open: triggers for storage, sales and transport records (A1 stays partial). Phase 3 S6 (specimen): Calapooia confirms the record types its answers and records support and leaves compost records unconfirmed; G8.0 names it and marks the earlier Yes [REVIEW].**
| T17-F2 | T17, WSDA 2264 13 | no question records "no input materials of any kind"; application dates are free text | a per-parcel no-inputs statement exists apart from the prohibited-material declaration, and dated input events print beside the typed history | **Phase 3 S4, back #83 (schema, rendering): `no_inputs_within_tenure` per parcel, asked of every parcel; dated input events print per year beside the typed history. Typed application dates stay free text (row 13 partial). Phase 3 S6 (specimen): each Calapooia parcel answers the no-inputs statement No and prints its dated inputs.**
| T21-F1 | T21, Phase 3 S6 specimen | a parcel the operation states is currently certified, with no lapse attested, prints "the operation's own period ... is not covered: the operator has made no declaration", while the same page says the declaration is not asked of a certified parcel. The page asks for a statement the form never offers. | the 36-month accounting for a currently certified parcel says what covers it (or what the certifier holds instead), and a test fails when the page asks for a statement the form hides | **Addressed 2026-10-01** (`certified_parcel_branch`): CCOF F2 to G asks (1) a certificate copy listing the parcel and (2) no-lapse verification, each attached, referenced separately or missing, the checkbox never filling (2); WSDA 2264 only for new sites and transfers (existing site renews on 2516; transfer asks the previous grower's certificate and a signed AGR 2262); OTCO C2 not refiled for an existing site, 2.4/2.5 still asked for a parcel from another operation; any other agent: its own form decides, nothing claimed. Conflicting records print as review items. UI and PDF render one assessment. **Run 3 (2026-10-02): source readings supported; not closed.** CCOF F2 to G, WSDA 2264 for new sites and transfers, and OTCO C2 for new applications and added acreage were read against the downloaded originals and hold, subject to applicability first (NOPB49 is for new parcels; existing parcels change on the Crop Update). Three renderers disagreed with the route: R3-04 page 04, R3-05 the parcel summary, R3-06 the fallback paragraph. Slice 1 of `R3-CORRECTIVE-PLAN.md` fixes all three (see "Run 3 review"). |
| T27-F1 | T27, O1 D-1 to D-7; CCOF Contract D5, D6 | no question captures certification history (suspension, revocation, surrender, denial, withdrawal) for the operation or its responsibly connected persons | a certification-history page exists, one answer per responsibly connected person, and the rows move off `not_covered` |
| T26-F1 | T26 | closed (back #77): the 13 OTCO crop forms are inventoried. Extraction learned Word's `startOverride` list restarts (C9 9.3/9.4), forms with no subsection number (C6, refs `1`..`8`), "Section N"/"Step N" forms and revision stamps split across runs | the list is empty: done |


### Run 3 review (2026-10-02): what each kind of evidence shows

`RUN3-REVIEW.md` (Astra) against the 2026-10-01 handoff (back `75226a4`, app `4c86274`); plan in
`R3-CORRECTIVE-PLAN.md`. Three kinds of evidence, never merged into one verdict:
**packet-observed** is what a reviewer reads in generated files; **code/test-verified** is what a
test in CI proves, mutation-checked; **untested** is everything neither covers.

| R3 | Finding | Packet-observed | Code/test-verified | Untested | Slice |
|---|---|---|---|---|---|
| R3-01 | (a)(2) coming-year heading carries changes already made | revision 2 p1 (run 3) | slice 3: revision 3 moves the three changes already made to (a)(1) and states no 2027 intention (the fixture holds none); the (a)(2) headings name the coming year (`test_calapooia_renewal_specimen.Run3SpecimenTests`) | whether the operator intends any change for 2027 is not in the fixture and is not invented | 3 (back #92, app #66) |
| R3-02 | OTCO Step 5-4 mapped to the 205.400(f) notify line; Step 6 locator stale | 02s p2, register row 5-4 (run 3) | slice 2: row 5-4 is answered on OTCO's form (`not_covered`, no packet locator); Step 6 points at the subtotal 02 prints (the scope gap was stated only on a non-frozen 02; run 4, R4-04, moves it to 02s) (`test_renewal_routing.Run3RenewalMeaningTests`); CONFORMANCE.md regenerated | run-4 review of the regenerated packets (bundle built 2026-10-02, not yet reviewed); OTCO's own reading of 5-4 | 2 (back #91) |
| R3-03 | WSDA invoiced-sales subtotal presented as the AGR 2521 income figure | 02 p2 (run 3) | slice 2: 02 prints "Sales records subtotal, <year> (not reconciled)", says it is not any agent's fee figure and names each agent's basis (`test_packet_second_wsda_read`); routing heading says "forms to file" | run-4 review of the regenerated packets (bundle built 2026-10-02, not yet reviewed); payment-date and service-income capture (AGR 2521 row 1 stays partial) | 2 (back #91) |
| R3-04 | Page 04 lists rows the parcel's route skips as still open | OTCO 04 p1, WSDA 04 p2 (run 3) | slice 1: page 04 reads each parcel's route under the packet's plan; skipped rows listed apart with the reason, an unresolved route open with its reason (`test_certified_parcel_branch` (the run-3 classes were folded into it so CI runs them; there is no `test_r3_route_applicability` module)) | run-4 review of the regenerated packets (bundle built 2026-10-02, not yet reviewed) | 1 (back #90 merged, app #65) |
| R3-05 | CCOF active summary counts 1 missing item, its detail names 3; draft prints internal keys | v3/v4 CCOF parcel p1 (run 3); cause read in code: the summary used the newest plan | slice 1: one `assess_for_plan` for every renderer; summary count equals the route's missing items, in words; active, draft and an unsaved agent choice tested | run-4 review of the regenerated packets (bundle built 2026-10-02, not yet reviewed) | 1 (back #90 merged, app #65) |
| R3-06 | OCI/MOSA page defers to the agent, then claims its form does not ask for the 36-month accounting | v3/v4 OCI and MOSA parcel pages (run 3) | slice 1: fallback says no agent-specific exemption is determined and prints the accounting; OCI and MOSA both tested | run-4 review of the regenerated packets (bundle built 2026-10-02, not yet reviewed) | 1 (back #90 merged, app #65) |
| R3-07 | Current specimen contradictions (split/parallel, buffer, Grandevo acknowledgment) | 02 p1, G6_0 p1, Home Field East p1, 03 p1 (run 3) | slice 3: revision 3 agrees with G6.0 on split and parallel production; the buffer rows are no longer "unharvested"; the Grandevo acknowledgment is the operation's account, and 03 says "no acknowledgment recorded in Trazo" (no acknowledgment record created); revision 2 keeps its pinned bytes (e20e0567...) and signed hash | run-4 review of the regenerated packets (bundle built 2026-10-02, not yet reviewed); the April 2026 certificate event still states 54.2 organic acres beside 86.9 certified (not in the review, not changed) | 3 (back #92, app #66) |
| R3-08 | Cover says every document is live; counts "None" as a deletion | 00-cover p1-2 (run 3) | slice 2 (02s "forms to file") and slice 3: the cover names frozen and reconstructed documents and counts (a)(2) entries | run-4 review of the regenerated packets (bundle built 2026-10-02, not yet reviewed) | 2, 3 (back #91, #92) |
| R3-09 | Freeze evidence is a log, not a reproducible test | `frozen/evidence.json` (run 3) | slice 4: `manage.py osp_freeze_evidence` writes the canonical signed payload and hash method, each edit with record id and before/after values, the API refusal (status and body) and the packet copy before and after, all in a rolled-back transaction (`test_annual_update_revisions.FreezeEvidenceCommandTests`) | run-4 review of `evidence/freeze-2026-revision-{2,3}.json` (not yet reviewed) | 4 (back #93) |

Slice 1 also changes the route rule itself (Oscar, 2026-10-02): "currently certified" is existing
acreage under the selected agent only when the agent named for the parcel IS that agent. Another
known agent makes it new acreage (`ccof_g`, `wsda_new_site`, `otco_new_acreage`); no name, or one
Trazo does not recognise, is `unresolved`, never skipped. The demo farm names a fictional certifier,
so its packets will show `unresolved` on every routed agent; the other routes are shown by tests.

### Run 4 review (2026-10-02)

`RUN4-REVIEW.md` (Astra) against the run-4 bundle (back `743c3bf`). Verdict: most run-3 corrections
are demonstrated in the packets; four follow-ups. Packet-observed by run 4, and so no longer pending:
the routed existing-acreage routes and their page 04 (R3-04 for resolved routes); OTCO Step 5-4 and
the Step 6 locator (R3-02, locator part); the non-fee labelling in every packet and the agent-specific
wording in the draft packets (R3-03); revision 3's stated corrections with no invented intention or
acknowledgment (R3-07, R3-01 misplacement part); the cover (R3-08); frozen bytes and recomputable
signed hashes for revisions 2 and 3 (R3-09, hash part). Still open as specimen facts: no 2027
intention is stated (R3-01 completeness).

| R4 | Finding | Cause read in code | Fix and test | Untested |
|---|---|---|---|---|
| R4-01 | Unresolved and fallback evidence items read "Not asked on this branch"; summary silent on an unresolved route | `lines()` gave every non-asked item the resolved-route prefix | items on an undetermined route read "whether this is asked is not determined"; the parcel summary says the evidence set is not determined; app card likewise (`test_certified_parcel_branch`, all three routed agents unresolved, OCI and MOSA) | **closed by run 5** (`RUN5-CONFIRMATION.md`): demonstrated in the packets and evidence; runtime and CI not exercised by the reviewer |
| R4-02 | Revision 1 "replaced 2026-10-02" beside revision 2 filed 2026-10-01 | `file_filing` stamped the replaced revision with the time of recording (`now`), not its successor's filing date; the run-3 seed happened to run on Oct 1 | replaced on the successor's filing date, never before the replaced revision's own (`ReplacementHistoryTests`, three revisions) | **closed by run 5** (`RUN5-CONFIRMATION.md`): demonstrated in the packets and evidence; runtime and CI not exercised by the reviewer |
| R4-03 | Freeze evidence: two different "before" digests for the plan's sections | the edit's digest was taken after the packet build recompiled the narratives inside the transaction; the baseline before the command | every digest named by stage with one stated method; canonical before/after section data and the created notification's values included (`FreezeEvidenceCommitsNothingTests` reconciles the stages) | **closed by run 5** (`RUN5-CONFIRMATION.md`): demonstrated in the packets and evidence; runtime and CI not exercised by the reviewer |
| R4-04 | Active OTCO 02s did not carry OTCO's Step 6 scope; the frozen 02 is neutral | the agent's basis lived only in 02's template | 02s prints the packet's own agent's fee basis (OTCO now names the written-petition exclusion); 02 stays as filed (`test_a_neutral_frozen_filing_exported_for_otco_gets_otcos_caveat_on_02s`) | **closed by run 5** (`RUN5-CONFIRMATION.md`): demonstrated in the packets and evidence; runtime and CI not exercised by the reviewer |

### T29: three roles, kept apart

| Role | Who | Where it lives today | On the record? |
|---|---|---|---|
| **Sender** | the crew number that sent the note | `FieldNote.sender`, `sender_phone`, `sender_display_name`, `received_at` | no |
| **Performer** | who did the work | deliberately never inferred from the sender (`fieldnotes/models.py:118-121`, trazo-app `src/views/Dashboard/FieldNotes/CrewRoster.tsx:11` @`bf08370`); only set if the grower enters it | only if typed |
| **Confirmer / author** | the grower who applied the offer | `FieldNote.confirmed_by`; the event's `created_by` | yes, as the only person |

Open question for Phase 4: for records in FSMA Produce Safety scope, 21 CFR 112.161(a)(4) wants the
performer's or observer's signature or initials, created at the time. A later Apply by a
supervisor does not supply that. Decide which record types may come through the channel at all
before claiming anything about them.

## Phases (each one a separate session, plan mode first)

**Phase 1: stop overstating.** T15, T16, T20 (disclosure), T21, T22 (label), T23, T25, T30, and
T19's per-question disclosure of missing label attachments. Acceptance is behavioural. Each item
gets a test that fails on the current code and passes after the change, and the old behaviour is
re-applied once to prove the test catches it. Tests that lock in the old wording
(`test_an_unrecognised_agent_is_told_which_numbering_it_is_reading`,
`test_each_update_form_points_at_the_update_pages`) are rewritten, not deleted.

**Phase 2: register truth.** T17 fixes (Contract D2 option, 2264 Q13 and Parcel B citations,
stray G6.4/L5 citations), T26 atomic rows and Contract I/J, T27 O1 edition, the ZIP-only OTCO
forms against `scope.yaml`, and a re-read of the four disputed T17 items against the official PDFs.

**Phase 3: renewal.** Evidence-based land history for the parcel transition card (moved from T21). A filed-renewal fixture (prior-year baseline, changes made, planned changes,
unchanged sections, signature and filing state per 7 CFR 205.406(a)(1)–(4)); per-agent routing to
the agent's own renewal form; year and snapshot identity so a new draft never erases a filed
update. Label and source attachments in the packet (T19, T22).

**Phase 4: crew-note provenance.** Sender, performer and confirmer carried onto the event, the
audit export and the PDFs (T29); record-type rules for what the channel may create.

**Phase 5: navigation and materials.** An agent-ordered question index with exact answer
locations (T24); material identity reconciliation and near-duplicate flags (T18).

**Reviewer-fixture task (before any packet goes to a certifier).** Resolve T28 and the specimen
gaps in `_calapooia_bend_data.json`, or build a separate reviewer fixture, so the specimen answers
every question it can.

## Not tested (no pass is claimed for any of these)

- WhatsApp field notes live: all eight failure cases in AUDIT.md §8. Whether the Twilio sandbox is
  connected in production is unconfirmed.
- Consumer QR page runtime, redaction and badges.
- Phone widths and offline recovery.
- Certifier review link after the T04 fix.
- Cross-tenant fix (back #52/#53): no two-tenant regression was run by the auditor.

## Questions for a real reviewer (AUDIT.md §12, kept as the exit test)

1. Would you use this packet for your intake? Mark the exact questions still needed and the agent
   forms that must be signed or filed separately.
2. Is this completed annual-update example sufficient for an existing crop client?
3. Can you reconstruct this one sale and this one input application from the included sources?
   Mark the first broken link.
4. For this crew-note example, whose signature or initials and what retained source would you expect?

## Log

- **2026-09-30.** Report and prompt filed unedited. Findings re-scored against code at the pins
  above. Register count reconciled: 755 rows, the audit was right and our first count (571) was
  wrong. OTCO originals retrieved (`sources/otco/MANIFEST.md`); O1 edition drift found. No product
  code changed.

- **2026-09-30, Phase 1 opened** (plan corrections from Oscar applied: trigger evidence, three-state
  declarations, separate filing/signature/format metadata, requirement-matched attachments,
  evidence-based submission and loss wording). PRs: trazo-back #64 (page 04 answer states, T15,
  T16, T19, T20, T23), trazo-back #65 (T21, T22, T25, retention cite), trazo-app #53 (T21 badge,
  retention cite, retired-score wording sweep), trazo-landing #18 (T30, first CI copy check). Every
  new guard was run against the old behaviour and went red. Findings made on the way:
  - Retention is 205.103(b)(4) since the SOE rule (88 FR 3621). A review bot and an August test
    both used the pre-2023 (b)(3); both answered and corrected.
  - No registered form is fully `covered` today, so page 04 lists no form as answered. That is the
    honest state, not a defect of Phase 1.
  - Navbar search prints a `carbon_score` as "kg CO₂": `parcel_count * 25.5` for farms, a real
    footprint for parcels, under one label (`common/views.py` global_search). Open, awaiting a slice.
  - Pre-existing failures on main outside CI's list: `test_osp_module_pdf` parcel status line,
    `test_parcel_map_in_packet` uploaded map, `test_parcel_application` x2,
    `test_schoolsite_roundtrip`, `test_packet_section_vocabulary`.

- **2026-10-01.** Phase 1 merged: trazo-back #64, #65, #67, #68 and trazo-app #53, #54. Landing
  #18 (T30 site copy and the copy-check CI) is still open. After the #65 deploy the education seed
  has to be re-run in production WITH `--refresh` (`python manage.py seed_education_content
  --refresh`): deploys run only `migrate`, and the seed is create-only without that flag, so the
  COG Pro FAQ would keep the pre-2023 retention cite.

- **2026-09-30, Phase 2 opened** (plan corrections from Oscar: a legacy "Neither" answer is never read as
  the new indirect-export statement; the register is checked against a question inventory derived from
  each source file and tied to its hash; instruction, interpretation, optional and conditional rows
  cannot hide a requirement or make a form read as complete; ledger rows close only on what was
  demonstrated). PRs: trazo-back #72 (register truth), trazo-app #56 (the retired option in the
  wizard). Found on the way:
  - Every out-of-scope row needed a reason from a closed set. 45 of the 71 were conditional
    requirements (mushrooms, livestock, direct marketing, LPO, handling) or questions answered on
    another form, not out of scope. They are now open, or conditional on `contract_scopes` with the
    trigger answer as evidence.
  - Register size after Phase 2: 852 rows, of which 826 are official questions (CCOF 257, OTCO 291,
    WSDA 278) and 26 are instructions that ask nothing. The rise from 755 is the splits and the rows
    added for items that had none, not new forms. Statuses over the 826 questions: 134 covered,
    418 partial, 237 not covered, 37 out of scope.
  - WSDA AGR 2264 9 (possible export to Canada via a buyer) is now answered in part by the
    indirect-export option.
  - The first mutation harness run reported every guard red because the shell could not start the
    test runner at all; re-run with the interpreter named directly before any result was used.

- **2026-10-01, Phase 2 follow-up (back #75).** Every CCOF and WSDA form now has a source
  inventory, and its rows match it one to one. Main changes: G3.1 expanded to the form's 31 items;
  G5.0's three matrix rows folded back into A (the form does not number its practices); the
  Materials Application re-cut, with the citation banner and section B's opening sentence as
  instructions, its column rows folded into their lettered sections, and three Trazo
  interpretations (listing evidence, authority) marked as such, their gaps carried by the official
  row they read; AGR 2196's table columns kept as rows (the form numbers nothing), its WSDA List
  cross-reference an interpretation; section-level "Not Applicable" checkboxes have their own rows on
  WSDA A, B, C, M, R and S; WSDA prints "7a" twice on R, now two described rows; the Canada
  variances on 2121-Q keep the printed numbers with a description. OTCO's crop forms are a separate
  pass (T26-F1).

- **2026-10-01, Phase 2 OTCO pass (back #77).** OTCO's 13 crop forms re-read from the docx files
  and their registers re-cut to the printed numbering: the earlier files numbered items by order of
  appearance, gave table columns rows of their own and folded subsection "Not applicable" lines into
  question 1. Notable corrections: C8's export section is 8.4, not 8.5, and the Product Formulation
  Sheet is 8.3-5; C6 prints no subsection number, so its refs are `1`..`8` (no "6.1"); C7 7.6 prints
  2) and 3) with no 1); C12 12.4's question is 12.4-1 with a) and b); C9's numbering restarts, which
  the extractor now reads. Merged rows carry the merged rows' gaps, marked with the old ref, and the
  worse status; three covered rows became partial on that rule (C9 9.2-1b, C9 9.4-1, C5 5.2-1).
  Every registered form now has a source inventory (T26 done).
- **2026-10-01, Phase 3 opened** (renewal; plan corrections from Oscar: a filing is a chain of
  revisions, a signature covers all content, legacy rows are disclosed and never back-filled, the
  original stays as filed with status in a separate supplement, unknown input status is neither
  prohibited nor allowed, a logged season is not coverage, "not kept" is no way out of a required
  record, only an attachment actually read into the ZIP answers its question). Six slices, S1 to
  S6, the fixture last.
- **Phase 3 S1, revisions and signed content** (trazo-back #79, trazo-app #57).
  - `OSPAnnualUpdate` gains `revision_number` and `corrects`, `establishment`, the (a)(3) changes
    text, (a)(4) text with a three-state "nothing further", a server-written signature with a
    hash over every signed field, write-once filing date and method, and the frozen document
    (`filed_pdf`, `filed_sha256`, held in the row, not the public media bucket).
  - Edits after signing return 409; deleting a signed or filed revision returns 423; a
    correction is revision N+1, and filing it marks N superseded. One current filing per
    establishment and year, across plan versions (it was one per plan version).
  - 02 is the filed bytes. Every revision ships under `annual-update/`, and a new
    `02s-renewal-status-and-routing.pdf` reports acknowledgement, corrections, withdrawals and
    the legacy state.
  - Migration 0044 marks already-filed rows `legacy_none` with no signer and no frozen copy,
    and refuses (naming the rows) when one establishment holds two updates for one year. The
    local dev DB has none; production has to be checked before merge.
  - Two choices outside the plan's wording: `new_osp` and `filing_method` are not in the signed
    hash. `new_osp` is the backlink a later fork writes (once, never re-pointed), and the method
    is recorded at filing, after signing; both are write-once instead.
  - Mutation check: 11 backend and 2 frontend re-applied defects, each red with an
    AssertionError. Tests that pinned the old tiers were rewritten, not deleted
    (`test_annual_update_lock`, `annualUpdateHistory`, four packet tests).
- **Phase 3 S2, renewal routing** (trazo-back #80).
  - Registered the three agent renewal forms the register lacked, each against an inventory
    derived from its source and tied to a sha256: CCOF Annual Renewal Contract (a web form,
    captured; `capture_web_form` drops the per-request nonces so two captures hash the same, and
    the capture date stands in for the revision the form does not print), CCOF Crop Update
    NOPB88 (was a `scope.yaml` gap), and WSDA AGR 2521 Renewal Fee Form (R 05/26; the audit read
    R 01/24, see ERRATA). WSDA's renewal application is not published as a blank form, so it is a
    `scope.yaml` decision, quoting WSDA's own "renew your application by March 1 each year".
  - `renewal_role` (annual_renewal, site_update, crop_update, fee) on forms and scope entries; a
    form with a role must be filed with the agent. OTCO's OSP Update Form and WSDA AGR 2516 carry
    it too.
  - The 02s supplement lists the operation's own agent's renewal forms, with each official
    question's standing ("in this packet", "in part", "not in this packet; answer it on the
    form", or the operation's own election) and where to copy it from. A fallback agent gets no
    borrowed form. Listing a form never makes it read as answered on page 04.
  - Mutation check: 7 re-applied defects, each red with an AssertionError.
  - Register after S2: 58 forms, 857 questions.
- **Phase 3 S3, attachments** (trazo-back #81, trazo-app #58).
  - One manifest decides every operator file before any page is written: attached (bytes in the
    ZIP), held outside the packet (past `PACKET_ATTACHMENT_BUDGET_BYTES`, 150 MB) or unreadable.
    Maps, affidavits and receipts moved onto it; their loops used to skip a failed read silently
    while page 04 counted the upload.
  - `GeneratedDocument.requirement` (a validated `module.question` upload key), `sales_record`
    (resolved against the URL's establishment) and `source_kind`. Only a file linked to the
    requirement AND written into the ZIP answers; a section-only upload still reads "not
    identified".
  - New folders: labels/ (label files), labels/lot-tags/, labels/photos/, attachments/<module>/<question>/,
    audit-trail/sale-<id>/. Module pages and the exhibit name each file or say why it is not there.
  - Register: 27 rows that said uploads never reach the packet now say what ships and what is
    still missing. No status changed.
  - Mutation check: 9 backend and 2 frontend re-applied defects, each red with an assertion.
- **Phase 3 S4, land history from evidence** (trazo-back #83, trazo-app #60).
  - `product/services/input_evidence.py`: every dated input (chemical, soil amendment, beneficial
    release) is prohibited, allowed or unknown. Unknown starts no clock and is never read as
    allowed: inside the window it blocks the clean statement and is named in the verdict. With a
    prohibited input on record the clock runs from it "at the earliest". An elapsed clock plus an
    unknown input used to read "In transition, 0 days remaining".
  - `coverage()` counts the operator's own period only when the operator declared it (no
    prohibited material, or no inputs at all). It counted tenure alone before. Seasons print
    beside it with their exact span and never close a gap; a season with no inputs says that is
    not a statement that none was applied. Typed land-history years have no explicit "none"
    answer, so they add dated findings but no coverage.
  - T17-F2: `no_inputs_within_tenure`, three states, flagged when a dated input inside the tenure
    disagrees; dated inputs print per year marked (dated record), typed ones (typed).
  - Card: "In transition" only while a clock runs; the unknown-only case reads "Not established".
  - Mutation check: 10 backend and 1 frontend re-applied defects, each red with an assertion.
- **Phase 3 S5, required records** (trazo-back #84, trazo-app #61).
  - `certifications/services/required_records.py`: a record type is required when one answer in
    the plan says its activity happens (materials used, pest inputs applied, who harvests,
    compost made, storage shared with non-organic, supplier verification, a documented seed
    search). A trigger hidden by an answered condition requires nothing; an unanswered one leaves
    the requirement unresolved. States: confirmed, not confirmed, not kept (new, with a reason;
    never a way out), unresolved.
  - The statement reads "all the records your plan's activities require". The gate refuses Yes
    while any required record is not confirmed. A Yes stored before this stays as given, prints a
    [REVIEW] naming what is missing and counts as unconfirmed on page 04.
  - The § 11 panel marks required rows with the reason and offers "we don't keep this" with a
    required reason.
  - Mutation check: 7 backend and 1 frontend re-applied defects, each red with an assertion.
- **Phase 3 S6, filed-renewal fixture and T28** (trazo-back PR pending).
  - `seed_calapooia_bend` drives the product's own services: it marks the August 2026 filing
    legacy, corrects it (`correct_filing`), signs and files the correction (`sign_filing`,
    `file_filing`, which renders the frozen copy), forks v4 (`fork_plan`, moved out of the
    viewset so the seed and the button run one path) and opens a 2027 draft update.
  - Record types confirmed on v3 except compost; `no_materials_used` answered No; each parcel
    certified with no lapse and the no-inputs statement declined; a specimen label file and one
    specimen invoice, generated from the fixture's own rows and stamped SPECIMEN.
  - `_teardown` deletes revisions newest first (`corrects` is PROTECT) and says it is a demo
    reset. The re-seed test asserts determinism only, never that a filing survives it.
  - T28: four narratives narrowed to what G6.0 supports; "onion sets" renamed to the cell-tray
    transplants the planting records describe.
  - Found by the specimen, not fixed here: T21-F1.
  - Mutation check: 10 re-applied defects, each red with an assertion.
- **2026-10-01, Phase 3 accepted as an implementation milestone** (Oscar). Independent review of the
  regenerated packets is pending; nothing here is marked verified because CI passed.
  - Ledger corrected: T22 is partly resolved (attachments and rendering only; allocation, loss and
    custody open), and T20 is "implementation complete", not done.
- **T21-F1, certified parcels follow their agent's route** (trazo-back and trazo-app PRs pending).
  - `certifications/services/certified_parcel_branch.py` decides the route per agent and branch
    (existing site of this operation, or a parcel from another operation, read from the question
    "operation name on that certificate (if not this operation)") and reports each item as attached,
    referenced separately, missing or not asked. Availability only; never "verified" or "eligible".
  - The declaration the form skips is printed as not asked; the 36-month accounting prints only where
    the route asks for it (WSDA and OTCO transfers), worded so it never demands that declaration.
  - Per-parcel certificate and continuity uploads ship under parcels/certificates/ and
    parcels/continuity/; a signed Affidavit of Land History counts as continuity evidence (CCOF G(2)).
  - Register: CCOF G (currently certified) covered; WSDA 2264 6a and OTCO C2 2.4 cite the new questions
    and stay partial on their other gaps.
  - Mutation check: 11 backend and 2 frontend re-applied defects, each red on an assertion.
- **Phase 4, crew-note provenance (T29)** (trazo-back #88, trazo-app #63, follow-up #64). Oscar's boundary and
  corrections (2026-10-01): option 1 (applications route to the application form, the note waits until
  it saves); record-specific attestation facts, never a blanket disclaimer; mixed negation is manual
  review; append-only confirmation history; application mode by record type; atomic linking.
  - `fieldnotes.FieldNoteConfirmation` (note RESTRICT, append-only, voided on delete).
    `EventViewSet.perform_create` locks the note and writes record, link and history in one transaction.
  - `history/services/crew_note_provenance.py` (outside the fieldnotes app, whose guard forbids naming an
    event model): the dossier section "Records Confirmed From Crew Messages", a CSV section (formula
    cells neutralised), the records export (no full phone, no media reference), and a private
    `events/<id>/crew-note/` endpoint for the dashboard.
  - The dossier column "Recorded By" printed `performed_by`; it is now "Performed By" beside a real
    "Recorded By" (the saving account).
  - `carbon/services/voice_negation.py`: none / all / mixed, language-aware (Portuguese "no" is "in the").
  - Mutation check: 12 backend defects re-applied, each red on an assertion.
  - Review of #88 (6 findings, all fixed): typographic apostrophe in negation, "porém" split, negated
    message keeps no description or type, every crew CSV cell quoted, bulk writes refused on the
    history, and the server keeps its own reading of a crew note (`FieldNoteExtraction`) so the
    dossier states the server's match apart from the app's report. Review of #63 and #64 (4 findings,
    all fixed in #64): unit and amount withheld together, offer filtered where it is built,
    manual-review headline, one rule for build and apply.

- **2026-10-02, run 3 review filed** (`RUN3-REVIEW.md`, Astra; plan `R3-CORRECTIVE-PLAN.md`).
  Seven of nine findings spot-checked against the packets before planning, all confirmed. T20
  reopened on mapping, specimen and disclosure; T21-F1, T28, T26 and T30 qualified as the review
  lists. Slice 1 (one applicability decision) in progress.
  - Slice 1 merged (back #90 with one review fix: a WSDA new site from another operation keeps its AGR 2262 item; app #65). Slice 2: R3-02 and R3-03, with part of R3-08 (02s "forms to file").
  - Slice 3: revision 3 corrects revision 2 with a printed `correction_note` (new field, signed only when set, so earlier hashes do not move); the demo seeder restores revision 2's filed bytes instead of re-rendering them.
  - Slice 3 merged (back #92; app #66 lets the operator write the correction note). Slice 4: replayable freeze evidence.
  - Slice 4 merged (back #93, with two review fixes: the before-edit packet is built inside the
    rolled-back transaction, and the evidence re-reads the records it edits). App #66 merged.
    Revision 3's filed bytes are pinned like revision 2's (`4cd62bbf...`), the bytes sent for run 4.
  - Run-4 bundle built from a fresh seed at back `743c3bf`: 11 packets (as-seeded, and a rolled-back
    "routed" set showing the existing-acreage routes), both frozen revisions, freeze evidence for each
    (every check true). **Not reviewed yet**: no R3 finding is closed on the packet-observed axis
    until run 4 reads it.
- **2026-10-02, run 4 review filed** (`RUN4-REVIEW.md`). Most run-3 corrections demonstrated in the
  packets; four follow-ups (R4-01 to R4-04) fixed in one backend PR and one app PR. Ledger cells
  corrected where run 4 found them stronger than the evidence (the folded test module name; the
  Step 6 scope gap).
- **2026-10-02, run 5 confirmation filed** (`RUN5-CONFIRMATION.md`, bundle from back `e7044eb`). R4-01 to
  R4-04 pass on every packet axis the bundle can show; no regression against run 4; revision 3
  reproduced byte for byte from its pin on a fresh seed. The corrective rounds end here. Next: Phase 5
  (T24, T18). Still open, unchanged: T22 allocation/loss/custody, T27-F1, T15/T16 contract capture, T17
  follow-ups, T29 live capture, T23 OCI/MOSA mapping (out of scope), T30 video captions, the
  reviewer-fixture task, and the demo's unstated 2027 intention (by design).
- **2026-10-02, Phase 5 opened** (plan approved with Oscar's six corrections). Slice 1, no claim from a
  guess: partial-name National List matches become suggestions; existing classifications are kept and
  marked legacy-unverified (production count before migrating: 20, all Calapooia Bend); drift warnings
  clear on exact catalog names only. Mutation check: 9 re-applied defects, 8 red on an AssertionError,
  the ninth an equivalent mutant whose redundant guard was removed.
