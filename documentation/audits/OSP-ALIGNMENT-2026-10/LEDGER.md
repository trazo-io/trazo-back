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
| T18 | HIGH | ok | exact-name matching only (`common_osp_workbooks.py:364`) | Neptune 2-4-1 vs 2-3-1, Tsunami vs SaniDate in demo data | blank use/comment cells by design (`:785-808`) | an unresolved product identity is never flagged | code-defect (matching), specimen-gap | 5 | **closed on mapping, specimen, rendering and disclosure** (runs 6 and 6b, 2026-10-03, packet-observed: unresolved names marked, decided identities joined with their basis, approval findings retained, transcribed restriction disclosed, classification rendering per event). Schema not independently exercised by the reviewer. R6b-01 (Feather Meal suggestion) confirmed fixed by run 6c, which also packet-observed undo and withdraw (back #108): an undone decision or withdrawn statement leaves the packet reading as before it was made. R6c-01 (withdrawn decisions shown on the materials application page) confirmed by run 6e (`RUN6E-CONFIRMATION.md`); its three test-only cases stay test-only. History: Phase 5 slice 1 (code and tests, not yet packet-observed): partial-name National List matches are suggestions, never classifications or citations; stored classifications keep their value and are marked `legacy_unverified` (20 in production, all on the demo farm, counted before migrating); the drift detector clears a finding on exact catalog names only and notes partial hits. Identity decisions, review suggestions and restriction statements are slices 2 and 3. Phase 5 slice 2 (code and tests, not yet packet-observed): append-only operator identity decisions, per logged name, covering only the events reviewed and bound to their identity-relevant content; a formulation difference needs an acknowledgment; a National List substance is never a target; a decision answers the drift "not matched" finding only, and the identified product keeps its own approval and CDFA findings; the materials workbook joins an identified name to its plan row with the basis and marks the rest "identity not confirmed". Phase 5 slice 2b (code and tests, not yet packet-observed): append-only restriction statements, one per material, plan version and identified restriction, several per material; the restriction is either regulation wording Trazo holds (a § 205.602 condition of use, with citation, effective date and read date, and "whether it applies to this material and use is not established by Trazo") or wording the operator transcribed (source type, identifier, page or section, optional attachment from this operation), printed as "transcribed by the operator; not independently verified by Trazo"; "how it is met" prints as the operator's dated statement, not a compliance finding; a material with no restriction on record reads "restriction not documented"; a change of plan, material or held wording marks a statement for review; a statement changes no finding and no approval. Phase 5 slice 3 (code and tests, not yet packet-observed): review suggestions computed on read and never stored, shown in the identity panel only for names with no decision: a logged name and a plan product starting with the same distinctive word (a generic first word such as "Organic" pairs nothing; different numbers are reported), a catalog product named in a plan handling or sanitation answer other than the sanitizer logged (with the catalog subtype when it is a substance the plan approves), and a partial-name National List suggestion pointing at an approved substance; a suggestion records no decision, clears no finding and changes no workbook row or event. Remaining for T18: packet observation in run 6. |
| T19 | HIGH | equipment-cleaning questions exist (`stubs.py:413-672`); no brand-owner question (G7.0 C2) | G6.0 C2 honestly `not_covered` | cleaning questions unanswered in demo | **uploaded label files never reach the packet** (G7.0 A1/B1 P1) | a required label attachment that is absent is not named per question | render-gap, disclosure-gap, specimen-gap | 1 (disclosure), 3+ (attachments) | partly resolved (disclosure), merged in back #64. Missing label files named per question. Phase 3 S3, back #81 and app #58 (rendering and disclosure): a file uploaded for the label question rides in the packet under labels/ and is named on the G7.0 page; one that could not be read or did not fit is named and does not answer. Phase 3 S6 (specimen): Calapooia ships a label file against the G7.0 requirement and the G7.0 page names its ZIP path. Open: equipment-cleaning answers and the brand-owner question (unchanged) |
| T20 | HIGH | `OSPAnnualUpdate` exists | OTCO OSP-Update and WSDA 2516 map to `packet_documents` 02 + 03 | v4 has no filing | 02 prints "No § 205.406(a) annual update is on file…" (`osp_module_pdf.py:1494`) | 04 lists both forms as generated whether or not anything is filed (`packet_coverage.py:275`); and even when filed, 02 is not the agent's form | disclosure-gap, code-defect | 1 (disclosure), 3 (renewal) | partly resolved (disclosure), merged in back #64. Update forms listed as filed with the agent, filed or not. Phase 3 S1, back #79 and app #57 (schema; disclosure of revision and legacy state): a filing is a chain of signed revisions; (a)(3) and (a)(4) are captured; 02 is the filed bytes and 02s carries later status. Phase 3 S2, back #80 (mapping and disclosure of each agent's renewal forms): CCOF's renewal contract and NOPB88 and WSDA's AGR 2521 are registered, and 02s routes each agent's operation to its own renewal forms with a crosswalk. Phase 3 S6 (specimen, rendering end to end): Calapooia's August 2026 filing is revision 1, legacy and disclosed as such; revision 2 corrects it with (a)(3) and (a)(4), is signed, filed and frozen, and the packet ships its bytes unchanged; a v4 draft and a 2027 draft update leave both 2026 revisions untouched. **Implementation complete** on all five axes, shown by tests and the seeded demo. Not verified: the independent review of the regenerated packets, and any live filing with a certifier. **Run 3 (2026-10-02) reopens mapping, specimen and disclosure**: R3-01 (coming-year answers describe past changes), R3-02 (OTCO Step 5-4 mapped to a different promise; Step 6 locator stale), R3-03 (WSDA subtotal presented as the fee figure), R3-07 (revision 2 contradicts G6.0), R3-08 (cover says every document is live). Packet-observed by run 3: frozen bytes identical in all 11 copies, legacy revision 1 honestly disclosed, v4 draft labelled. Schema and workflow stay developer-tested, not shown by PDFs (R3-09). See "Run 3 review". |
| T21 | HIGH | declaration `dlpm_none_within_tenure` exists | Parcel B partly (ERRATA) | declaration unanswered | "Eligible" printed | Eligibility is "by absence of contrary evidence" (`product/services/transition_status_service.py:214-220`, verdict `:288`); the declaration never gates it. The 5/5 application count checks no address (`parcel_application_status.py:55-100`). | code-defect | 1 | partly resolved, merged in back #65 and app #53. No "Eligible"; declaration printed in its own states. Phase 3 S4, back #83 and app #60 (rendering and disclosure of land history): the clock reads soil amendments and beneficial releases too; an input of unknown status starts no clock and blocks a clean statement, named; the 36-month accounting counts the operator's period only with a declaration, never a logged season. Phase 3 S6 (specimen): every Calapooia parcel states it is certified, declines the no-inputs statement and prints its dated inputs per year; no "Eligible" anywhere. No prohibited or unknown input was added to the demo: on a farm certified since 2006 that would be a new contradiction (the T28 class). T21-F1 addressed (back and app PRs pending): a certified parcel follows its agent's own route. Still partly resolved: the answers-axis land-history check is agent-neutral (three years of rows or an affidavit) and is unchanged. Run 3: no packet page awards eligibility; dated inputs and the no-inputs No print. Not closed: R3-04, R3-05, R3-06 (see T21-F1). |
| T22 | HIGH | ok | n/a | destination "WVF Salem, IQF" vs handler narrative = demo data | The exhibit states the harvest-to-pack-out difference **is** "the handler's culls and shrink" (`osp_module_pdf.py:1760-1768`, from `audit_trail_exhibit.py:242-294`) with no cull record behind it. Invoice/BOL numbers print as text; nothing attached. | no statement that sources are not embedded | code-defect, render-gap | 1 (label), 3+ (attachments) | partly resolved (label), merged in back #65. No cause named for the difference. Phase 3 S3, back #81 and app #58 (rendering and disclosure): a sale's invoice, bill of lading or pack-out file rides in the packet under audit-trail/sale-<id>/ and the exhibit names it; a sale with only typed numbers says they are recorded as text, no source attached. Phase 3 S6 (specimen): the exhibit's lot shows one sale with its invoice attached and named, beside one recorded as text. **Partly resolved**: source attachments and their rendering are complete. Still open, not demonstrated: per-pick quantity allocation, dated loss evidence (the harvest-to-pack-out difference is stated, never evidenced) and custody or title reconstruction through the handlers (AUDIT §5; same open items as T03). |
| T23 | HIGH | n/a | fallback resolves to the CCOF register (`packet_coverage.py:195-200`) | n/a | For OCI, MOSA or any unregistered agent: "only the numbering differs" (`osp_module_pdf.py:2142-2154`), "file CCOF's own form where it applies" (`:2178`), and `ccof/scope.yaml` reasons "with CCOF directly" print verbatim | misroutes the operator | code-defect | 1 | partly resolved, merged in back #64. Fallback packets borrow no agent numbering; mapping OCI/MOSA forms stays out of scope |
| T24 | MED | ok | n/a | n/a | Module headings and filenames come from `module.code` for every agent (`osp_module_pdf.py:988-989`, `:2342`); `CCOF_MAP_ELEMENTS` hard-coded. Only 04 and the workbook filter vary by agent. | reviewer must use 04 as a crosswalk | render-gap | 5 | **closed on mapping, specimen, rendering and disclosure** (runs 6 and 6b, 2026-10-03, packet-observed: 2,751 cited pages resolved, conditional parcel states, order source, fallback page). Schema not independently exercised by the reviewer. History: Phase 5 slice 4 (code and tests, not yet packet-observed): new packet document 06-question-index.pdf, built last. For the packet's agent: forms in the agent's published order (`published_inventory.yaml`), rows in register order, each row with every answered location (file, page, section, question label; per parcel) and every open part with its reason, together; cited headings in generated and filed documents found by reading their bytes back, filed ones marked "located in the filed document"; attachments by ZIP path; rows with no location show the register's text labelled as not checked. Pages come from the question label recording the page it is drawn on, kept with its first answer line. Fallback agents get a one-page index with no rows. No entry states a question is met. Module files and headings keep Trazo's codes. Remaining: run-6 reviewer confirmation that the pages can be opened and found. |
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

### Run 7 review (2026-10-03): the audit dossier, read as an inspector

`RUN7-REVIEW.md` (Astra) against the run-7 bundle (back `95e52a6`): the operation dossier, 12
per-production exports, the raw records export and readiness data. Verdict: useful working papers,
not yet a dependable, self-contained dossier. Every finding was reproduced in code before planning.
Plan: correct what reads as false or overstated now; defer what only a real farm's records would
exercise, with an honest statement in the output meanwhile (Oscar, 2026-10-03: October scope).
Missing external evidence (receipts, labels, weigh tickets, handler certificates, receiving sheets)
stays open on the specimen axis whatever the wording.

| R7 | Finding | Cause read in code | Slice | Status |
|---|---|---|---|---|
| R7-01 | Handler certificate "DOCUMENTED ... on file and current" for a self-reported handler with no copy | decided on certificate dates only | 1 | code/test-verified: dates, copy and verification printed apart; no "documented", "on file" or "current" from dates |
| R7-02 | Plan "Active / Approved" with no approval date; narratives "verbatim filed"; footer "satisfies"; v1 change notification missed; annual update unnamed | model label; status-only lead-in; fixed footer; one-version lookup; newest-submitted selection | 1 (wording), 2 (notifications, annual update) | code/test-verified: wording (slice 1); change notices read across the version chain, one helper with packet 03; the annual update is the current revision (packet's own selection), summarised with revision, signer, signed hash, (a)(3), (a)(4) and the exact filed document by name and sha256, stated as not included in the dossier; superseded and withdrawn revisions listed (slice 2) |
| R7-03 | Drift reasons cut at 120 characters; "Verified" meant local lookup time; sanitizers absent from drift | explicit cell cap; column name; detector scope | 1 | code/test-verified: reasons whole, column "Looked up (local copy)", sanitizer gap stated. Sanitizers in the detector deferred |
| R7-04 | Soil "Yes - Organic Approved" unqualified; CSV dropped caveats; CSV "Inspector"/"Verified"; "no prohibited synthetic nitrogen" | legacy value outside the caveat set; CSV used raw labels; operator category read as a finding | 1 | code/test-verified |
| R7-05 | Blanket § 205.605(b) rinse rule; chlorine limit and PASS on peracetic acid; § 205.601 cited under § 205.605; blank dates | name-substring limit; fixed sentence; `cleaning_date` only | 1 | code/test-verified: no limit assessed, per-material wording, [REVIEW] on § 205.601, event date. Compound-aware limits deferred |
| R7-06 | One purchase counted on every application that carries it; application dates under "purchased" | summed per event | 3 | code/test-verified: grouped only when product, supplier, invoice, lot, purchase date, quantity and unit all match, labelled provisional (no purchase-line identifier); same product on a shared invoice or lot with other differences kept unresolved and reported beside the total; purchase date shown; units never summed; soil amendments in the CSV. T07 rendering corrected; receipts stay open (specimen) |
| R7-07 | "Uninvoiced remainder"; pick-1 lot not on its sale | label; fixture link | 1 (label), 3, 6 | label and [REVIEW] for a harvest lot on no sales record code/test-verified; fixture link open (slice 6) |
| R7-08 | Raw export cannot reconstruct relationships | concrete fields only | 5 (minimum) | code/test-verified: `sale_harvest_links.csv` (sale, harvest event, lot), the per-production CSV's drift and classification tables (full reasons, bases in words), and a README section naming each family the ZIP does not contain and where it lives. Full relational export deferred (T12 stays open) |
| R7-09 | C:N 18:1 "handle as raw manure", then interval "N/A" | raw-manure row reads manure fields only | 3 | code/test-verified: feedstock (manure / plant only / not stated / not recorded), C:N basis (initial only for an on-farm pile; a purchased compost's figure may be a finished-product analysis) and interval read apart; ambiguous cases print "manure interval assessment unresolved" naming what is missing; never N/A after the compost row raised it; soil compost table selects the snapshot's events; operation dossier prints each production's snapshot |
| R7-10 | Retention "five years from creation" over a finish-plus-five date | `compute_retention_until(finish)` | 4 | code/test-verified: stored date = later of finish + 5 years and newest covered record creation + 5 years (sales, amendments, events by audit-log creation or own date), moved forward (never back) when a record arrives after close, forward-only data migration 0242; open seasons show a calculated date and are stated as not deletion-protected; the dossier claims only the deletion refusal the code performs (the point-in-time-recovery claim removed). Open: whether open seasons' deletion should be refused (decision for Oscar) |
| R7-11 | Handler table: transport date under "Harvest Date"; "WVF" unrenamed | any event with handler fields; seeder list | 3, 6 | rendering code/test-verified: each row names its record's date and kind, never a transport date as harvest; fixture dates and WVF rename open (slice 6) |
| R7-12 | Eight specimen contradictions | fixture | 6 | specimen fixed (guards in `test_calapooia_fixture_integrity`): sale 97 names pick 1; sent dates follow transport records; every stored temperature carries its unit; drip fish is fertigation; feather-meal narrative lot matches the corrected lot; hive removal 13 May and the active plan says only Serenade (biological) goes on with hives in; Entrust 23 Jun, after the 22 Jun threshold; pick-1 culls buried (one disposition); certificate event 86.9 ac; compost record shows five turnings. Not fabricated: receipts, labels, weigh tickets, handler certificates, the conventional buffer sale (deferred with the conventional-sales split). Superseded plan versions v1 and v2 keep their text as filed |
| R7-13 | "30°C" frost, "101°C" heat for Fahrenheit readings | hardcoded °C; "C" default | 1, 6 | code/test-verified: no unit reads "unit not recorded"; fixture units open |
| R7-14 | Mature blueberry block: "no planting stock records ... standard inspection finding"; "3+" cited to § 205.204 | crop-name perennial test | 4 | code/test-verified: applicability from records: a planting event is assessed; with none, the parcel's crop history or an earlier production of the crop shows the stock predates the season; otherwise a [REVIEW] question, never a "standard inspection finding"; "3+" attributed to NOP 5029 guidance |
| also | Producer attestation called itself a "typed electronic attestation" with no signature | fixed string | 1 | code/test-verified: "Not signed in Trazo" |

**Run 7b (2026-10-04, `RUN7B-CONFIRMATION.md`):** packet-observed and closed on mapping, rendering and
disclosure within the October scope: R7-03, 04, 05, 06, 07, 08 (scoped), 11, 13, 14; R7-10 on rendering
and disclosure only (deletion refusal and recalculation are code/test-verified, not packet-observed).
Regression checks passed: frozen revisions 2 and 3 byte-identical, 95 warnings and 80 classification rows
unchanged (no legacy classification citable), harvest and sales totals unchanged, purchase totals reduced
only by provisional grouping. Partly open after run 7b, fixed in the follow-up PR and awaiting
confirmation: R7-01 (post-harvest footer said the certificate "is retained with the lot records"),
R7-02 ((a)(3) printed "-" while the filed revision attests no changes; the dossier now uses the packet's
own sentences), R7-09 (purchased compost's "No (C:N)" now "Not established (C:N basis)"), R7-12 (a
record still dated Entrust 19 June; Serenade "at dusk" against the before-7-a.m. account; Grandevo
"Entire planting" with the buffer skipped). Missing external documents stay open on the specimen axis.

Housekeeping (not a reviewer finding): workbook rows now follow record dates, so the same records
build the same workbook (run 6e saw row order move between builds).

### Run 8 review (2026-10-05): Trazo as its users meet it

`RUN8-REVIEW.md` (Astra) used the live app as the Calapooia owner, the buyer page and www.trazo.io.
28 findings; every one was reproduced in code on `origin/main` before planning (R8-11 only in part).
The code check found three problems the review only touched: fuzzy USDA matches and OMRI/National
List hits stored as `verified`, no farm timezone, and no stable template identity. Plan amended by
Oscar (2026-10-05) with ten conditions; the ones that change what counts as done:
- "Verified" only for a confirmed USDA Organic Integrity Database match.
- Unreported carbon is "not estimated" (null), never 0, never an area guess.
- Date versus timestamp semantics written down (ADR-011) before any formatter changed.
- Public free text loses invoice, order, receipt and account numbers; lot numbers stay.
- Templates versioned by stable key; historical plan items untouched.
- "N of 19 modules" is descriptive only.
- Every production data operation: dry run by default, snapshot, apply with an audit row,
  idempotent re-run, restore (`common/services/data_operations.py`, `common.DataOperationLog`).
- No ASTRA record is deleted until Oscar confirms the reseed's dry-run deletion list.

Evidence kinds: **Live** S = Astra screenshot, T = accessibility text only; **Code** = where the
cause was read; **Fixture** = the Calapooia demo data is involved; **Test** = the guard each slice
added (each mutation-checked, red on an AssertionError).

| R8 | Live | Code (cause) | Fixture | Test added | Slice | Status |
|---|---|---|---|---|---|---|
| 01 | S | methodology §7.2: unapproved input read as permitted after notification | no | landing `check-copy.mjs` | L1 | merged (landing #22) |
| 02 | S | methodology photo penalties, PASS/REVIEW/FAIL | no | copy guard | L1 | merged (landing #22) |
| 03 | S | `templateAccelerators.ts` prefilled quantities and energy | no | `templatePrefillIsNotAnAttestation` | I1 | merged (app #80) |
| 04 | S/T | parcel-area fallback charged per-hectare diesel on a cleanout | no | `Run8UnreportedIsNotEstimatedTests`, `carbonNotEstimated.test.ts` | I2 | merged (back #123, app #83) |
| 05 | T | renderers converted farm wall-clock time to the viewer zone | no | `farmRecordDatesIgnoreViewerZone`, `Run8DateSemanticsTests` | I1b | merged (back #121, app #81, workspace #15 ADR-011) |
| 06 | S | "Versións" concatenation; "POS"; usted in core strings | no | `ospRun8Wording`, `spanishRegister` usted guard | O1 | merged (app #84); full usted sweep deferred |
| 07 | T | chemical form length | no | none | deferred | needs observed growers |
| 08 | S/T | stale lookup result shown; no honest "unknown" basis | no | `inputLookupIsTiedToName`; `Run8UnknownOrganicBasisTests`, `unknownOrganicBasis.test.ts` | I1, I4 | merged (I1 app #80; I4 back #125, app #85) |
| 09 | T | event descriptions asserted outcomes | no (product copy) | `consumerDescriptionEvidence` outcome guard | P1 | merged (app #79) |
| 10 | S | OSP % bar, "Complete" per section | no | `ospRun8Wording` | O1 | merged (app #84) |
| 11 | S (part) | full new-entry form for a filed year | yes | `ospRun8Wording` render tests | O1 | merged (app #84) |
| 12 | T | app said "content is the same" for an agent with no register | no | `certifyingAgentPicker`, `ospCertifyingAgentCard` | O1 | merged (app #84) |
| 13 | S | certifier surfaces scattered | no | none | deferred (hub) | minimal links only |
| 14 | S | carbon expanded, before the story, car/phone equivalents | yes | `buyerPageRun8` | P1 | merged (app #79) |
| 15 | S | grower notice in the third-party chapter | yes | `buyerPageRun8` | P1 | merged (app #79) |
| 16 | S/T | "every step", "nobody can hide" | no | copy guards | P1, L1 | merged (landing #22, app #79) |
| 17 | S | farm intro before the lot story | yes | order test | P1 | merged (app #79) |
| 18 | T | invoice numbers in public free text | yes | `PublicFreeTextCommercialReferenceTests`, `Run8SpecimenPublicTextTests` | P2 | merged (back #120) |
| 19 | S | demo farm not labelled fictional | demo | copy guard | L1 | merged (landing #22) |
| 20 | S | hero lacked customer and price line | demo imagery | copy check | L1 | merged (landing #22); imagery deferred |
| 21 | S | "Document one season"; Extra Farm missing | no | copy guard | L1 | merged (landing #22) |
| 22 | S | applicator/coverage claims, Part 11, retention | no | copy guard | L1 | merged (landing #22) |
| 23 | T | "3 lb/acre/year" copper; blanket NOP approval claims | no | `Run8TemplateGuidanceClaimTests`, `Run8TemplateSyncTests` | I3 | merged (back #124) |
| 24 | T | voice disabled without a reason | no | `voiceSaysWhyItIsDisabled` | I1 | merged (app #80) |
| 25 | S | tours auto-started | no | `tourStartsOnRequest` | I1 | merged (app #80) |
| 26 | S/T | cleanout photo guidance about hour meters; "approved inputs" | no | `ospRun8Wording` | O1 | merged (app #84) |
| 27 | S | red FAIL badges; disclaimer last; English rows | no | `readinessIsNotAVerdict` | C1 | merged (back #122, app #82) |
| 28 | S | no PDF outline; Contents without page numbers | no | outline and Contents tests in `test_operation_audit_export` | C1 | merged (back #122) |
| V | none | fuzzy OID matches, OMRI/NL hits stored `verified` | no | `test_register_truth`, `verifiedRequiresOidMatch` | V1 | merged and deployed (back #119, app #78) |

**Deferred, each with its reason:** R8-07 shortening the chemical form (needs observed growers);
the full usted sweep (~374 strings) and enum and crop-name translation; R8-13 a single certifier
hub; finding-to-record deep links on the review page; certifier review row details still English;
server-side tour dismissal; hero imagery; a real farm-timezone field (ADR-011 records why none is
assumed); the dossier's two-pass build cost (about twice the layout time).

**Production steps (Oscar, each dry run first, snapshot before apply):** after V1
`reevaluate_certification_verification`; after I2 `recompute_unreported_carbon`; after I3
`sync_template_guidance`; then the Calapooia reseed, only after the `--dry-run` deletion list
(which includes the ASTRA production, its four events and documents 24 and 25) is confirmed.

**Manual 375 px Spanish pass (2026-10-06).** Local copy of `main` after every run 8 merge,
freshly seeded Calapooia, real headless Chrome at 375 x 812, es-419, network dropped with the
browser's offline switch at save time. (The Slow 3G profile was tried on the dev server first;
its unbundled modules made the load take 240 s and say nothing about the production bundle, so
poor signal was tested where a crew meets it: app loaded, signal gone at save.)

Worked:
- Unknown input: the lookup says there is no match and that this does not make the input
  allowed; renaming the input clears the old result.
- "Sin confirmar todavía" can be selected and saved. The save nudge names the missing organic
  basis in Spanish, and the record stores `unverified`.
- Offline save: nothing is lost (the form stays on step 3, draft saved). After reconnecting, one
  retry creates exactly one record.
- Harvest from a template: quantity, area, fuel and hours are blank.
- Cleanout with no fuel: the timeline row reads "Sin estimar"; the API serves a null figure
  with its reason. Photo guidance is about the cleaning.
- Voice: Spanish examples including harvest; "no words captured" explained.

Fixed from the pass:
- The "Sin estimar" sentence ran 120 px past the card at 375 px (its row kept `flexShrink={0}`).
  Fixed in app #86.
- About 120 event descriptions still stated outcomes or environmental benefits from the event
  type (R8-09 in other words, in both locales). Fixed in app #87, with a vocabulary guard.
- Voice offline did nothing and said nothing (autoStart even showed "Escuchando..."); an offline
  save read only "No se pudo crear el evento"; the reused-product chips read "Aprobado orgánico".
  Fixed in app #88 and re-checked live: voice is disabled offline with the reason, the save
  names the missing connection and the kept draft, the chip reads "Base orgánica registrada".

Open, each a decision or a later slice:
- English left in the Spanish wizard: "Required", "When did this activity occur and who
  performed it?", "Fungicide Concentration", "Fuel Consumed", "Auto-generated from production
  type...", "Essential for calculating carbon...", unit names, the activity-name prefill
  ("Harvesting", "Equipment Maintenance"), "Preview", the proof-view filter tabs, season-plan
  item names and windows, the purpose label "disease prevention", the modal value "Cleaning",
  and the not-estimated reason served by the API.
- Usted outside the guarded logging keys: wizard step 1 ("¿Qué hizo?", "Elija"), the photo step
  ("Agregue fotos de su finca", "Toque para capturar"), the production page ("Su página
  pública", "Siga registrando").
- "Eficiencia: normal" arrives preset on templates and the cleanout, a self-assessment saved
  unless changed.
- "(incl. 1 operativos)": plural with a count of one.
- One name variant left: "Plan Orgánico del Sistema".
- The event detail modal shows no carbon line at all (neither a figure nor "Sin estimar").
- Dev only, not confirmed in production: `/event/add` without `?production=` renders an empty
  page; after the throttled load the tab stayed blank through reloads until its local state was
  cleared.

### Recordkeeping review (2026-10-07): the two outputs, as their readers meet them

Source: `../RECORDKEEPING-REVIEW-2026-10/REVIEW.md` (back #128), run in a browser on the
Calapooia specimen against back `6b5ef1d` / app `fcea8c0`: warnings catalog (54 rows), the
renewal packet for a no-register agent and for OTCO, CCOF and WSDA, both dossiers, the records
ZIP, the buyer page in both locales, and the five journeys. 34 ranked findings (F-01 to F-34),
no blocker; what a certifier would send back is F-01 (brand-versus-listing counted as not on
the plan), F-03 (the dossier's false yield delta), F-06 (a packet download wrote the active
plan) and F-08 (an unconfirmed basis reported as missing).

Oscar's plan (2026-10-07), in order: S2, S1, S5, S3, S6, S4, then S7, S8, S9, S10 (REVIEW.md
§6), with these amendments: F-06 compiles the active plan's narratives in memory for the packet
and keeps the 2026-08-28 one-packet-one-answer fix; F-07 prints the continuation year and
rewords the model's help text; S4 keeps "not yet confirmed" as an open item worded "basis not
yet confirmed", never "Missing", and one unconfirmed input never unsets a certified parcel's
transition date; S1 deletes the "24-hour response" promise and rewrites the attestation as a
factual, unsigned retention statement; S5 shows the stored candidate and links to identity
confirmation; F-11 removes the public "Sustainability Commitment" block and the sign-up tiles
and keeps the stored field; F-02 excludes area estimates and no-factor rows from the buyer's
total and per-kg figure. The pending `recompute_unreported_carbon` production step has run
(dry run, apply, check = 0).

| slice | findings | status |
|---|---|---|
| S2 packet does not rewrite the on-file plan; continuation year; outlines on 01 and 06 | F-06, F-07, F-17 | back PR (this entry) |
| S1 dossier tells the truth | F-03, F-04, F-05 | open |
| S5 name the drift honestly, show the candidate, link to identity confirmation | F-01 | open |
| S3 public carbon payload and records ZIP columns | F-02, F-10 | open |
| S6 buyer chips, sustainability goals, template blurb, placeholders | F-09, F-11, F-12, F-25 | open |
| S4 unconfirmed is an answer; cleanout default name | F-08, F-13 | open |
| S7 annual update form | F-14, F-22, F-23 | open |
| S8 Spanish crew screens | F-18, F-24, F-28 | open |
| S9 certifier page rows and packet 04 route sentence | F-15, F-16 | open |
| S10 onboarding polish | F-19 to F-21, F-26, F-27, F-29 to F-31 | open |

Frozen filings and F-07: Calapooia's 2026 revisions 2 and 3 were filed under the `+ 1`
heading and print "(a)(2) Additions intended for the coming year (2027)" on a 2026
continuation. Their bytes are the documents as filed and stay as they are (pinned SHA-256);
every filing from this slice on prints the continuation year. A reader of the frozen 2026
revisions should read "(2027)" as "(2026)".

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
- **2026-10-02, Phase 5 slice 1 merged** (back #97; deployed, migration 0240 applied). **Slice 2**:
  material identity decisions (back and app PRs). Mutation check: 13 backend and 4 app defects, each
  red on an assertion.
- **2026-10-02, slice 2 review fixes** (back #98: malformed ids are a 400, the sanitizer filter applies
  on write, a merged name keeps its own listing note, the identity finding carries its verification
  dates; app #68: amber tokens, full form reset, safe error text). **Slice 2b**: restriction statements
  (Oscar's rules of 2026-10-02). Mutation check: 9 defects, each red on an assertion.
- **2026-10-02, slice 2 merged** (back #98, app #68; deployed). Slice 2b review fixes: statements
  belong to their plan version, other versions listed apart for review (back #99); needs-attention
  badges use the warning variant, including the identity panel's stale badge (app #69). **Slice 3**:
  review suggestions. Mutation check: 6 backend and 5 app defects, each red on an assertion.
- **2026-10-02, slice 3 merged** (back #100, app #70). **Slice 4**: the question index (T24). Per-question
  and per-parcel parts kept on `RowState` beside the unchanged folded state. Mutation check: 10 defects,
  each red on an assertion.
- **2026-10-03, run 6 reviewed** (`RUN6-REVIEW`, bundle at `3998a7f`): Phase 5 substantially
  demonstrated; 2,751 index page references independently resolved; decided identities, retained
  approval findings and transcribed restriction disclosure pass; no run-5 regression. Production
  `recompute_drift` after slice 1: 247 events, findings 23 before and 101 after, all on demo
  establishments (13: 81 unresolved and 14 `name_wsda_not_in_osp`, equal to a fresh seed of current
  code; 8 and 11: 6 unresolved). **Run-6 follow-ups** (one back PR, one app PR):
  - R6-01: the index keeps each parcel's "does not apply" part with the deciding answer in the reader's
    words; the register placeholder shows only when the packet gives nothing else for a row.
  - R6-02: suggestions read a plan product's name after a leading maker word (catalog manufacturer)
    or find the logged name's first two words together after a leading brand word; two products of
    one maker never pair on the maker.
  - R6-03: a test renders the audit dossier and checks the cell printed for legacy, suggested, exact
    and operator-set classifications; the run-6b bundle carries the same per event.
  - R6-04: an umbrella form precedes its sections; the index names the source and date of its form
    order; "Related packet document" where the document does not name the form.
  - Wording: a partly reviewed name says how many uses were identified, excluded, changed or not
    reviewed.
  Mutation check: 12 backend and 1 app defects, each red on an assertion.
- **2026-10-03, run 6b confirmed** (`RUN6B-CONFIRMATION`, bundle at `376a249`, freeze logs at the same
  commit): R6-01 to R6-04 and the Entrust wording demonstrated; no other regression. T18 and T24 closed
  on the demonstrated axes. **R6b-01** (low): the R6-02 rule lost the Feather Meal suggestion, because
  it set the maker aside on the plan name only. Fixed: when both names start with the plan product's
  maker, the maker is set aside on both and the next two-word phrase must appear in the plan name
  ("Feather Meal"); "Down To Earth Bone Meal" still does not pair. Also: identical "does not apply"
  lines on one row print once per parcel. Panel check on the specimen: every run-6 suggestion present,
  Feather Meal restored, no new pair. Mutation check: 3 defects, each red on an assertion.
- **2026-10-03, browser test of the Phase 5 flows** (real sign-in as the Calapooia owner, on a migrated
  copy of the dev database; no repo test added, by decision). Decide, exclude, restate, replace and
  download all worked end to end and the packet carried each result. Found and fixed (one back PR, one
  app PR): an identity decision took ~11 s because it recomputed drift for the whole farm, now only
  that name's uses, with each catalog name looked up once per recompute (whole farm 11 s to 2 s; one
  name under 1 s); suggestion text showed stored keys, now section and question labels; uses showed
  only a date, now parcel, amount and the product details as logged; no select all; an exclude box per
  ticked use; a mistyped restriction could not be corrected. Both panels redesigned as collapsed rows
  with a status (open work first, full names never cut), a one-tap suggestion, explicit Exclude, a
  hint for what is missing, and undo (decisions) and withdraw (statements) with a reason, kept in the
  history (migration 0050). Mutation check: 12 backend and 15 app defects, each red on an assertion.
- **2026-10-03, run 6c confirmed** (`RUN6C-CONFIRMATION`, bundle at `223b1ba`): R6b-01 restored (Feather
  Meal suggestion, 8 suggestions, no false pair); undo and withdraw demonstrated across the CCOF, OTCO
  and WSDA packets: Neptune and Serenade read exactly as seeded after the undo and the withdrawal,
  Entrust's partial decision and its 14 approval findings unchanged, the history keeps who, when and
  why, and no decision produces an approval claim. **R6c-01** (recommendation): the packet showed no
  trace of a withdrawn decision, so a reviewer could not tell "never decided" from "asserted, then
  withdrawn". Fixed: the materials application page lists every identity decision withdrawn on the
  operation and every restriction statement withdrawn on the plan version, with what it claimed, who,
  when and why, and says it no longer identifies or documents anything (or points at a later decision
  for the same name); with none, the page says none was withdrawn. A withdrawal still clears nothing.
  Review of the PR: the regulation and transcription qualifiers kept on a withdrawn statement, a
  withdrawn name now on the plan not called unidentified, and the section on the "none used" page too.
  Mutation check: 11 defects, each red on an assertion.
- **2026-10-03, run 6e confirmed and run 7 filed** (`RUN6E-CONFIRMATION.md`, `RUN7-REVIEW.md`). R6c-01
  closed. Run 7 read the audit dossier as an inspector: 14 findings, all reproduced in code; plan
  scoped to October (see "Run 7 review"). Slice 0+1 (this PR): filing, workbook order, and every
  wording correction above. Review of the PR: three facility tests outside the CI list updated, an unreadable submitted copy no longer reads as absent, stale handler dates no longer say "on file". Mutation check: 26 defects, each red on an assertion.
- **2026-10-04, run 7 slice 2** (back): change notices across plan versions (a v1 notice was "none
  on file" in a v3 dossier) and the current annual-update revision named exactly (R7-02). Mutation
  check: 8 defects, each red on an assertion. Review of the PR: a filed document is placed in the
  renewal packet only when the packet carries its year (one helper, `renewal_packet_filing`, for
  both); an unfiled draft reads as a draft with a REVIEW; a withdrawn-only year keeps its REVIEW and
  spanning-year lines. 4 more defects, each red.
- **2026-10-04, run 7 slice 3** (back): purchase grouping and unresolved lines (R7-06, T07), an
  unsold harvest lot named (R7-07b), compost assessed from feedstock, C:N basis and interval with
  six branches (R7-09), handler rows by record kind (R7-11), and the snapshot in the operation
  dossier. Mutation check: 15 defects, each red on an assertion. Review of the PR: invoice and lot
  compared without case or spacing differences; a proven duplicate stays one row when another line
  conflicts; feedstock naming both "plant only" and a manure ingredient is not established. 3 more
  defects, each red.
- **2026-10-04, run 7 slice 4** (back): retention floor stored, extended and described honestly
  (R7-10) and planting-stock applicability from records (R7-14). A stale in-memory date once let
  the hook overwrite a later stored date; the update is conditional on the stored value. Mutation
  check: 10 defects, each red on an assertion. Review of the PR: the planting check needs a perennial
  production and matches the crop as a whole word or by crop type, states the most recent earlier
  year; a void extends retention; a multi-season scope states the earliest date. 5 more defects,
  each red.
- **2026-10-04, run 7 slices 5 (minimum) and 6** (back): sale-to-harvest links and a "not in this
  export" README in the raw ZIP, drift and classification tables in the per-production CSV
  (R7-08); specimen contradictions reconciled in the fixture and the seeder (R7-12, fixture halves
  of R7-07b, R7-11, R7-13). Mutation check: 5 code defects, each red on an assertion; the
  pre-correction fixture fails all 10 specimen guards. The CSV classification table reads through
  `national_list_basis` (an existing guard caught a direct read): a legacy match or a suggestion is
  never printed as a citable classification.
- **2026-10-04, run 7b confirmed** (`RUN7B-CONFIRMATION.md`): ten R7 items closed on the demonstrated
  axes; R7-01, 02, 09 and 12 leftovers fixed in the follow-up PR. Mutation check: 3 code defects, each
  red on an assertion; the pre-correction fixture fails the 3 new specimen guards.
- **2026-10-04, browser pass on run 7** (real sign-in as the Calapooia owner on a freshly seeded copy,
  current main, desktop and 375 px; no repo browser test added, by decision). Worked end to end: the
  sanitation block in the activity wizard (English and Spanish), saving a cleanout event with a
  peracetic-acid residual, the per-production export (PDF and CSV), the operation dossier job (447
  pages, about 10 s), the records ZIP from Documents, and the certifier review page. Found and fixed:
  the review page's readiness row still read "Unapproved-input findings" (now "Inputs not matched to
  the plan's approved inputs"; this PR); the sanitation block still carried hardcoded English in the
  Spanish UI and a chlorine-only residual label and help (app PR). Noted, not changed: the
  "EPA/USDA-SOURCED" badge on carbon activity cards (a carbon-claim question outside run 7), and a
  wizard draft that dropped a typed date across a page reload.
- **2026-10-04, run 7c** (`RUN7C-CONFIRMATION.md`): R7-09 and the targeted R7-12 corrections passed
  and close on the demonstrated axes. R7-01 and R7-02 stay open until run 7d demonstrates the
  outputs below.
- **2026-10-04, run 7d corrections** (back): R7-01, the handling footer is an instruction ("Retain
  the handler's organic certificate with the lot records for inspection") and no longer says the
  operation keeps one. R7-02, cause found: the signed content holds two row ids (`prior_osp_id`,
  `corrects_id`). The committed frozen copies were signed with the plan at id 1 and the corrected
  revision at id 1 (revision 2) and 2 (revision 3); each re-seed signs again on new ids and then
  restores the frozen PDF, so the database hash (`ff48aeca...` for revision 3) differed from the one
  the frozen copy prints (`da2ebd6b...`) while every signed field was unchanged. Today's content
  with the original ids reproduces both printed hashes exactly. The seeder now restores the signed
  hash with the frozen bytes (pinned beside the PDF hash); the dossier prints the signed hash as
  recorded and, on its own row, the hash of the content this database holds, saying whether it
  matches and, when it does not, that the summary is read from the database and is not shown to be
  the signed content. The frozen PDFs are unchanged (pinned SHA-256). The specimen tests used to
  assert that the stored hash equalled a re-hash of the same database, which could never catch this;
  they now compare against the hash printed in the frozen copy.
- **2026-10-05, run 7d confirmed** (`RUN7D-CONFIRMATION.md`): R7-01 closes on rendering and
  disclosure; R7-02 closes on mapping, specimen, rendering and disclosure. The reviewer recomputed
  both signed hashes from the canonical content with the original ids. Not established by these
  files: schema correctness and live enforcement. Missing external certificates stay open on the
  specimen axis. **Run 7 is closed**; what stays open is the deferred list in the run 7 review
  section (sanitizers in the drift detector, compound-aware residual limits, the conventional-sales
  split and buffer sale, the full relational export, open-season deletion protection).
- **2026-10-05, run 8 review filed** (`RUN8-REVIEW.md`, unedited): 28 findings across the live app,
  the buyer page and the landing site, all reproduced in code. Corrective plan with Oscar's ten
  amendments; see "Run 8 review". Landing (#22) and the "verified" slice (back #119, app #78)
  merged and deployed. On 2026-10-06 P1, P2, I1, I1b, C1, I3 and O1 merged after their review
  findings were fixed and answered, then I2 (back #123, app #83) and I4 (back #125, app #85).
  Review findings fixed on the way, each with a test red on an assertion: lot numbers cut by a
  short invoice value and "Order 500 lb" redacted (#120); a zero computed from reported inputs
  dropped, and the applied report overwritten by the verification run so --restore restored
  nothing (#123; an applied report is now never overwritten and restore accepts only a report
  matching a logged apply); photos fetched separately per PDF pass (#122); blanket factor
  provenance in template notes (#124); "Not yet confirmed" earning the buyer-page chip, silent on
  soil records and counted as "checked" in the OSP section 11 evidence (#125, app #85); the QR
  loader's standalone "EPA/USDA-Sourced" and "Sustainable" chips (app #83); a withdrawn-only year
  reading as never filed (app #84). The gap-label parity test (not in CI, it reads trazo-app)
  caught the new completeness keys with no app label.
- **2026-10-06, manual 375 px Spanish pass** of the crew flows on a local copy of main: see "Run 8
  review". Defects fixed in app #86 (overflow), #87 (descriptions) and #88 (poor signal, chip);
  the open list is recorded there.
- **2026-10-07, recordkeeping review, slice S3** (back): the buyer's carbon figure counts only entries
  with a recorded basis. `CarbonCalculatorService` reports `recorded_emissions` and
  `recorded_co2_kg_per_kg` beside the farmer-dashboard totals, excluding `area_estimate` and
  `no_factor_applied` rows; the anonymous transparency payload reads the recorded figures (the
  specimen's Onions 2026 served 12,294 kg with 82 kg of per-hectare guesses inside). Gone from the
  payload: `calculation_method "USDA_EPA_factors"`, `isEpaFactorsBased`, the car-mile and
  phone-charge `comparisons` and `per_kg_*` fields; `methodology.carbon_scope` states the scope
  and the per-class factor sources instead of "Direct operational emissions only (EPA/USDA-sourced
  factors)". The records ZIP drops the retired carbon-credit columns (`trust_score`,
  `verification_level`, `additionality_verified`, `audit_status`, registry fields, the blanket
  `data_source`, `usda_factors_based`) and adds `factor_basis` per row; `productions.csv` drops
  `reputation` and `confidence_score`. Findings F-02 and F-10. Guard:
  `history.tests.test_public_carbon_counts_only_recorded_basis`, in CI, each test red on the old
  code. `blockchain_verified: false` stays on the wire by the 2026-08-03 decision (a hard False
  for older clients); not a claim.
- **2026-10-07, recordkeeping review, slice S5** (back + app): a drift finding names the listing the
  detector found and says what is not confirmed. The unresolved reason reads "'X' is not confirmed
  against the plan's inputs list. Closest listing, not confirmed as the same product: Y (OMRI)."
  (was "not matched to any approved OSP input. Possible match, not confirmed"); the readiness row is
  "Inputs not confirmed against the plan's inputs list" with its count served as data
  (`params.count`, new `row_key`), the dossier section is "Inputs Not Confirmed Against the Plan's
  Inputs List" and its intro explains identity confirmation before change notification; the packet
  materials note and the whole-operation fix line point at the plan's identity panel ("Logged names
  not on the plan"). In the app the banner prints the closest listing, drops "you must immediately
  notify your certifier" for a naming difference, and links to the materials module's identity panel
  (`#logged-names`); the farm card says the season row in the reader's language from `row_key` and
  `params`. Finding F-01 in `../RECORDKEEPING-REVIEW-2026-10/REVIEW.md`. Guards:
  `certifications.tests.test_drift_names_the_candidate` (in CI), app
  `driftBannerNamesTheCandidate.test.tsx` and `readinessFindingInTheReadersLanguage.test.tsx`, each
  red on the old code. The stored prose of findings written before this slice keeps the old sentence
  until the input is re-evaluated; every surface that reads `reason_code` + `reason_params` shows the
  new one.
- **2026-10-07, recordkeeping review, slice S1** (back): the per-production and operation dossiers
  state facts and counts. The pre-export yield check compares the header to the SUM of the harvest
  records' recorded quantities and falls back to the note parse only when no harvest record carries
  one (Duke 2026 had reported a 69.9% gap that page 49 of the same PDF disproved); the handler-chain
  check no longer names the certifying agent as an undeclared handler; "100% materially complete",
  "Section Completion … %" and "Complete — N characters" became counts ("6 of 6 sections above the
  narrative floor", "Written — N characters"); the unsigned "Producer attests … 24-hour response"
  paragraph became a factual, unsigned retention statement; the "value-add" sentence is gone.
  Findings F-03, F-04, F-05 in `../RECORDKEEPING-REVIEW-2026-10/REVIEW.md`. Guard:
  `history.tests.test_dossier_tells_the_truth`, in CI, each test red on the old code.
- **2026-10-07, recordkeeping review filed** (`../RECORDKEEPING-REVIEW-2026-10/REVIEW.md`, back
  #128): see "Recordkeeping review (2026-10-07)". S2 first: the packet compiles an active plan's
  narratives in memory and no longer writes the row (`updated_at` pinned across a download, the
  materials module and the (a)(2) narrative still agree); document 01 says when it is generated
  from current records; the annual update prints the continuation year as the year its additions
  are intended for (model help text reworded, migration 0052); outlines on 01 and 06. Guard:
  `test_packet_reads_the_active_plan_without_writing`, in CI.
- 2026-10-07 S4 (recordkeeping review F-08, F-13), back + app `fix/s4-unconfirmed-is-an-answer`. A basis the grower recorded as "Not yet confirmed" (R8-08, kept as an open item per Oscar) is its own class in `input_evidence` (`NOT_CONFIRMED`), never a blank: the transition clock lists it in a note and never dates, blocks or unsets the § 205.202(b) line (one such input on a certified parcel used to turn it into "Not established: input status not recorded"); the certified-parcel review emits `unconfirmed_input`; the dossier field-history row and the chemical record-completeness row say "organic basis not yet confirmed" as REVIEW, never "Missing"; the save nudge label matches. A cleanout (EM with operation Cleaning) is named by its verb in the wizard and prints "Equipment Maintenance — Cleaning" in every dossier table (`production_type_display`). Guards: `product/tests/test_unconfirmed_is_an_answer.py`, `unconfirmedIsAnAnswer.test.ts`.
- 2026-10-07 S10 (recordkeeping review F-19, F-20, F-21, F-26, F-27, F-29, F-30, F-31), back + app `fix/s10-onboarding-polish`. Back: an empty USDA Organic Integrity Database no longer writes "Run: python manage.py import_usda_organic_data" into the certificate's verification note (the instruction goes to the log; the note reads "Automatic check … is not available yet"); the welcome mail subject drops "Agricultural Transparency Platform". App: the Getting Started panel stays off the parcel and production pages it covered (dismissal is still browser-local; a server-side preference is its own slice); the sign-up terms links sit outside the checkbox label so a click on them no longer leaves the box unticked; a password with an open warning is never also "Strong"; a season created with nothing ticked on the template says so (inline notice and an info toast) and the "NT" initials avatar for no team is a plain line; the annual-update deadline row appears only for an operation with a certificate on file; the input form's "Consumer Trust Information" block and the unsourced "#1 non-conformance nationally" sentence are gone; the company-setup heading and the dossier modal button ("Download dossier") say what they are. Existing certificates that already hold the developer note are cleared by `clear_developer_verification_note` (dry run by default, `--apply`, `--restore <report>`; through `data_operations`; production: Oscar runs it). `reevaluate_certification_verification` cannot do it: it refuses to run while the Integrity Database is empty and only re-plans rows already verified (review of back #139). Guards: `certifications/tests/test_verification_note_is_for_the_grower.py`, `onboardingSaysWhatItHolds.test.ts`.
