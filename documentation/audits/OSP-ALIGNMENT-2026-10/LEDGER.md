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
| T15 | HIGH | ok | ok per row | n/a | n/a | Page 04 heads the list "Forms generated in this packet" (`osp_module_pdf.py:2130`). `_classify` (`packet_coverage.py:252-288`) lists a form once any module or packet document maps to it and never reads row verdicts or answers. Only mitigation: the separate "Sections of this plan still to finish" list (`outstanding_modules`, `packet_coverage.py:420`). | disclosure-gap, code-defect | 1 | open |
| T16 | HIGH | 3-question stub `CERTIFICATION_CONTRACT` (`osp_modules/stubs.py:1158`) vs NOPB06 sections A–H | `ccof/forms/Certification-Contract.yaml` maps NOPB06 to the stub: 24 rows, 2 covered | n/a | prints as the contract | 04 lists "CCOF Certification Contract (NOPB06): modules/certification_contract.pdf" as generated | code-defect, disclosure-gap | 1 | open |
| T17 | HIGH | per item (ERRATA) | 1 wrong (Contract D2 indirect export), 2 partly (WSDA 2264 Q13, Parcel B), stray wash-water citations on G6.4 B1 / 2121-L 5, 5a; 4 disputed | several "no answer" = demo unanswered | n/a | n/a | mapping-defect, specimen-gap, open-question | 2 | open |
| T18 | HIGH | ok | exact-name matching only (`common_osp_workbooks.py:364`) | Neptune 2-4-1 vs 2-3-1, Tsunami vs SaniDate in demo data | blank use/comment cells by design (`:785-808`) | an unresolved product identity is never flagged | code-defect (matching), specimen-gap | 5 | open |
| T19 | HIGH | equipment-cleaning questions exist (`stubs.py:413-672`); no brand-owner question (G7.0 C2) | G6.0 C2 honestly `not_covered` | cleaning questions unanswered in demo | **uploaded label files never reach the packet** (G7.0 A1/B1 P1) | a required label attachment that is absent is not named per question | render-gap, disclosure-gap, specimen-gap | 1 (disclosure), 3+ (attachments) | open |
| T20 | HIGH | `OSPAnnualUpdate` exists | OTCO OSP-Update and WSDA 2516 map to `packet_documents` 02 + 03 | v4 has no filing | 02 prints "No § 205.406(a) annual update is on file…" (`osp_module_pdf.py:1494`) | 04 lists both forms as generated whether or not anything is filed (`packet_coverage.py:275`); and even when filed, 02 is not the agent's form | disclosure-gap, code-defect | 1 (disclosure), 3 (renewal) | open |
| T21 | HIGH | declaration `dlpm_none_within_tenure` exists | Parcel B partly (ERRATA) | declaration unanswered | "Eligible" printed | Eligibility is "by absence of contrary evidence" (`product/services/transition_status_service.py:214-220`, verdict `:288`); the declaration never gates it. The 5/5 application count checks no address (`parcel_application_status.py:55-100`). | code-defect | 1 | open |
| T22 | HIGH | ok | n/a | destination "WVF Salem, IQF" vs handler narrative = demo data | The exhibit states the harvest-to-pack-out difference **is** "the handler's culls and shrink" (`osp_module_pdf.py:1760-1768`, from `audit_trail_exhibit.py:242-294`) with no cull record behind it. Invoice/BOL numbers print as text; nothing attached. | no statement that sources are not embedded | code-defect, render-gap | 1 (label), 3+ (attachments) | open |
| T23 | HIGH | n/a | fallback resolves to the CCOF register (`packet_coverage.py:195-200`) | n/a | For OCI, MOSA or any unregistered agent: "only the numbering differs" (`osp_module_pdf.py:2142-2154`), "file CCOF's own form where it applies" (`:2178`), and `ccof/scope.yaml` reasons "with CCOF directly" print verbatim | misroutes the operator | code-defect | 1 | open |
| T24 | MED | ok | n/a | n/a | Module headings and filenames come from `module.code` for every agent (`osp_module_pdf.py:988-989`, `:2342`); `CCOF_MAP_ELEMENTS` hard-coded. Only 04 and the workbook filter vary by agent. | reviewer must use 04 as a crosswalk | render-gap | 5 | open |
| T25 | MED | n/a | n/a | v4 is a draft | 01 is titled "Organic System Plan: Submission Snapshot" regardless of status (`osp_pdf_snapshot.py:198`); the cover says draft | contradictory state | code-defect | 1 | open |
| T26 | MED | n/a | Grouped rows (G6.4 B1 a/b, G8.0 A1, Contract G, OTCO O1 D-2–6); CCOF Contract I/J absent while `register_status: complete` (unverified: the audit also calls NOPB06 sections A–H, see ERRATA); WSDA 2121-R ends at 7, both "7a" folded. Stale docstring `packet_coverage.py:377` ("20 of WSDA's 24 forms are drafts"). | n/a | n/a | n/a | mapping-defect | 2 | open |
| T27 | HIGH | n/a | **O1 transcribed from rev. 2025/08/27; live is rev. 2026/03/25** (widened section D, 3 new checkboxes). 13 other OTCO forms match. | n/a | n/a | n/a | mapping-defect | 2 | source check closed; register edit open |
| T28 | MED | n/a | n/a | Demo text contradicts itself: "no conventional production anywhere" vs buffer rows sold conventional; "onion sets" as annual seedlings | n/a | n/a | specimen-gap | Fixture | **open**: a packet shown to a reviewer must not contradict itself |
| T29 | HIGH if compliance claimed | `FieldNote` keeps sender, sender_phone, received_at, confirmed_by and the event it became (`fieldnotes/models.py:231-341` @`7e0673e`) | n/a | untested live | The event and every export carry only the confirming user; nothing in event serializers, audit export or OSP PDF reads `FieldNote` (`history/views.py:4093-4142` @`7e0673e`) | the record does not say it came from a crew note | code-defect, open-question | 4 | open |
| T30 | MED | n/a | n/a | n/a | Landing: 205.103(b)(3) cited for 5-year retention, correct is (b)(4) (`components/organic-features.tsx:79`, `app/cog-pro-migration/page.tsx:129`, `lib/blog-data.ts:367,388,568`); "The score measures how many events were documented" (`app/methodology/page.tsx:841-842`) on a page that says there is never a score; "The full regulated record" (`components/dual-output.tsx:209`); "complete records" (`app/demo/page.tsx:81`, demo video captions); "Every lot reconciles…" (`components/organic-features.tsx:45-47`) | claims exceed what the packet substantiates | code-defect (copy), open-question (fuzzy "Verified", ERRATA) | 1 | open |

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

**Phase 3: renewal.** A filed-renewal fixture (prior-year baseline, changes made, planned changes,
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
