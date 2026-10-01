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
| T18 | HIGH | ok | exact-name matching only (`common_osp_workbooks.py:364`) | Neptune 2-4-1 vs 2-3-1, Tsunami vs SaniDate in demo data | blank use/comment cells by design (`:785-808`) | an unresolved product identity is never flagged | code-defect (matching), specimen-gap | 5 | open |
| T19 | HIGH | equipment-cleaning questions exist (`stubs.py:413-672`); no brand-owner question (G7.0 C2) | G6.0 C2 honestly `not_covered` | cleaning questions unanswered in demo | **uploaded label files never reach the packet** (G7.0 A1/B1 P1) | a required label attachment that is absent is not named per question | render-gap, disclosure-gap, specimen-gap | 1 (disclosure), 3+ (attachments) | partly resolved (disclosure), merged in back #64. Missing label files named per question. Phase 3 S3, back #81 and app #58 (rendering and disclosure): a file uploaded for the label question rides in the packet under labels/ and is named on the G7.0 page; one that could not be read or did not fit is named and does not answer. Open: specimen (S6) |
| T20 | HIGH | `OSPAnnualUpdate` exists | OTCO OSP-Update and WSDA 2516 map to `packet_documents` 02 + 03 | v4 has no filing | 02 prints "No § 205.406(a) annual update is on file…" (`osp_module_pdf.py:1494`) | 04 lists both forms as generated whether or not anything is filed (`packet_coverage.py:275`); and even when filed, 02 is not the agent's form | disclosure-gap, code-defect | 1 (disclosure), 3 (renewal) | partly resolved (disclosure), merged in back #64. Update forms listed as filed with the agent, filed or not; the renewal fixture stays Phase 3 |
| T22 | HIGH | ok | n/a | destination "WVF Salem, IQF" vs handler narrative = demo data | The exhibit states the harvest-to-pack-out difference **is** "the handler's culls and shrink" (`osp_module_pdf.py:1760-1768`, from `audit_trail_exhibit.py:242-294`) with no cull record behind it. Invoice/BOL numbers print as text; nothing attached. | no statement that sources are not embedded | code-defect, render-gap | 1 (label), 3+ (attachments) | partly resolved (label), merged in back #65. No cause named for the difference. Phase 3 S3, back #81 and app #58 (rendering and disclosure): a sale's invoice, bill of lading or pack-out file rides in the packet under audit-trail/sale-<id>/ and the exhibit names it; a sale with only typed numbers says they are recorded as text, no source attached. Open: specimen (S6) |
| T21 | HIGH | declaration `dlpm_none_within_tenure` exists | Parcel B partly (ERRATA) | declaration unanswered | "Eligible" printed | Eligibility is "by absence of contrary evidence" (`product/services/transition_status_service.py:214-220`, verdict `:288`); the declaration never gates it. The 5/5 application count checks no address (`parcel_application_status.py:55-100`). | code-defect | 1 | partly resolved, merged in back #65 and app #53. No "Eligible"; declaration printed in its own states. Phase 3 S4, back #83 and app #60 (rendering and disclosure of land history): the clock reads soil amendments and beneficial releases too; an input of unknown status starts no clock and blocks a clean statement, named; the 36-month accounting counts the operator's period only with a declaration, never a logged season. Open: specimen (S6) |
| T22 | HIGH | ok | n/a | destination "WVF Salem, IQF" vs handler narrative = demo data | The exhibit states the harvest-to-pack-out difference **is** "the handler's culls and shrink" (`osp_module_pdf.py:1760-1768`, from `audit_trail_exhibit.py:242-294`) with no cull record behind it. Invoice/BOL numbers print as text; nothing attached. | no statement that sources are not embedded | code-defect, render-gap | 1 (label), 3+ (attachments) | partly resolved (label), merged in back #65. No cause named for the difference; source attachments stay Phase 3 |
| T23 | HIGH | n/a | fallback resolves to the CCOF register (`packet_coverage.py:195-200`) | n/a | For OCI, MOSA or any unregistered agent: "only the numbering differs" (`osp_module_pdf.py:2142-2154`), "file CCOF's own form where it applies" (`:2178`), and `ccof/scope.yaml` reasons "with CCOF directly" print verbatim | misroutes the operator | code-defect | 1 | partly resolved, merged in back #64. Fallback packets borrow no agent numbering; mapping OCI/MOSA forms stays out of scope |
| T24 | MED | ok | n/a | n/a | Module headings and filenames come from `module.code` for every agent (`osp_module_pdf.py:988-989`, `:2342`); `CCOF_MAP_ELEMENTS` hard-coded. Only 04 and the workbook filter vary by agent. | reviewer must use 04 as a crosswalk | render-gap | 5 | open |
| T25 | MED | n/a | n/a | v4 is a draft | 01 is titled "Organic System Plan: Submission Snapshot" regardless of status (`osp_pdf_snapshot.py:198`); the cover says draft | contradictory state | code-defect | 1 | merged in back #65 |
| T26 | MED | n/a | Grouped rows (G6.4 B1 a/b, G8.0 A1, Contract G, OTCO O1 D-2–6); CCOF Contract I/J absent while `register_status: complete` (unverified: the audit also calls NOPB06 sections A–H, see ERRATA); WSDA 2121-R ends at 7, both "7a" folded. Stale docstring `packet_coverage.py:377` ("20 of WSDA's 24 forms are drafts"). | n/a | n/a | n/a | mapping-defect | 2 | done (back #72, #75, #77): every registered form (55) carries `source_sha256`, and its rows match an inventory derived from the agent's own file, one to one and in order (`test_form_inventory`; `verify_form_inventory` re-derives all of them). Rows split where the form numbers or letters separately, refs follow the form, row kinds, `scope_basis` and optional flags added |
| T27 | HIGH | n/a | **O1 transcribed from rev. 2025/08/27; live is rev. 2026/03/25** (widened section D, 3 new checkboxes). 13 other OTCO forms match. | n/a | n/a | n/a | mapping-defect | 2 | source verified and mapping corrected (back #72): O1 transcribed from rev. 2026/03/25, its rows checked one to one against an inventory derived from the live file (sha256 recorded). Open: T27-F1 (capture of the certification history D asks) |
| T28 | MED | n/a | n/a | Demo text contradicts itself: "no conventional production anywhere" vs buffer rows sold conventional; "onion sets" as annual seedlings | n/a | n/a | specimen-gap | Fixture | **open**: a packet shown to a reviewer must not contradict itself |
| T29 | HIGH if compliance claimed | `FieldNote` keeps sender, sender_phone, received_at, confirmed_by and the event it became (`fieldnotes/models.py:231-341` @`7e0673e`) | n/a | untested live | The event and every export carry only the confirming user; nothing in event serializers, audit export or OSP PDF reads `FieldNote` (`history/views.py:4093-4142` @`7e0673e`) | the record does not say it came from a crew note | code-defect, open-question | 4 | open |
| T30 | MED | n/a | n/a | n/a | Landing: 205.103(b)(3) cited for 5-year retention, correct is (b)(4) (`components/organic-features.tsx:79`, `app/cog-pro-migration/page.tsx:129`, `lib/blog-data.ts:367,388,568`); "The score measures how many events were documented" (`app/methodology/page.tsx:841-842`) on a page that says there is never a score; "The full regulated record" (`components/dual-output.tsx:209`); "complete records" (`app/demo/page.tsx:81`, demo video captions); "Every lot reconciles…" (`components/organic-features.tsx:45-47`) | claims exceed what the packet substantiates | code-defect (copy), open-question (fuzzy "Verified", ERRATA) | 1 | done: app #53, back #65 and landing #18 merged. Demo video captions still say "complete records" (needs a re-cut) |

### Follow-ups opened in Phase 2 (each closes only on the evidence named)

| ID | From | What is still open | Closes when |
|---|---|---|---|
| T17-F1 | T17, G8.0 A1 | Trazo's records attestation covers "the record types confirmed above", gated only on a non-empty list; CCOF A1 asks for ALL records the plan's activities need | the attestation is scoped to CCOF's wording, or the packet names the activity-implied record types left unconfirmed; a test fails when one is missing | **Phase 3 S5 (gate and rendering): the statement covers every record the plan's own answers require (seven triggers, each one answer); Yes is refused while any is not confirmed, "not kept" included; the G8.0 page names each missing one by state. Open: triggers for storage, sales and transport records (A1 stays partial).**
| T17-F2 | T17, WSDA 2264 13 | no question records "no input materials of any kind"; application dates are free text | a per-parcel no-inputs statement exists apart from the prohibited-material declaration, and dated input events print beside the typed history | **Phase 3 S4, back #83 (schema, rendering): `no_inputs_within_tenure` per parcel, asked of every parcel; dated input events print per year beside the typed history. Typed application dates stay free text (row 13 partial).**
| T17-F1 | T17, G8.0 A1 | Trazo's records attestation covers "the record types confirmed above", gated only on a non-empty list; CCOF A1 asks for ALL records the plan's activities need | the attestation is scoped to CCOF's wording, or the packet names the activity-implied record types left unconfirmed; a test fails when one is missing | **Phase 3 S5, back #84 and app #61 (gate and rendering): the statement covers every record the plan's own answers require (seven triggers, each one answer); Yes is refused while any is not confirmed, "not kept" included; the G8.0 page names each missing one by state. Open: triggers for storage, sales and transport records (A1 stays partial).**
| T17-F2 | T17, WSDA 2264 13 | no question records "no input materials of any kind"; application dates are free text | a per-parcel no-inputs statement exists apart from the prohibited-material declaration, and dated input events print beside the typed history |
| T27-F1 | T27, O1 D-1 to D-7; CCOF Contract D5, D6 | no question captures certification history (suspension, revocation, surrender, denial, withdrawal) for the operation or its responsibly connected persons | a certification-history page exists, one answer per responsibly connected person, and the rows move off `not_covered` |
| T26-F1 | T26 | closed (back #77): the 13 OTCO crop forms are inventoried. Extraction learned Word's `startOverride` list restarts (C9 9.3/9.4), forms with no subsection number (C6, refs `1`..`8`), "Section N"/"Step N" forms and revision stamps split across runs | the list is empty: done |


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
- **Phase 3 S5, required records** (trazo-back PR pending, trazo-app PR pending).
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
