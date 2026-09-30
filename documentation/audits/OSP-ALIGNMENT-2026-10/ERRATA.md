# Errata to AUDIT.md (run 2, 2026-09-30)

AUDIT.md is Astra's report, kept byte-for-byte (sha256 `3a80f421…5849`). It is not edited. Where we
read the code or the sources differently, the disagreement is recorded here, with our evidence
at a pinned commit, so a later reader can judge both.

Status values:
- `disputed`: our reading differs; neither side has re-read the official PDF against the other's
  claim yet. Settled in Phase 2.
- `confirmed-with-correction`: the finding holds, but its stated cause or scope is off.
- `ours-was-wrong`: our first check contradicted the audit and was itself the error.
- `closed-by-us`: an audit limitation we could remove.

Pins: trazo-back `4959284` (the packets were generated there; `certifications/`, `product/`,
`history/services/` and `documentation/compliance/` are unchanged at `7e0673e`), trazo-landing
`f3bb9fb`.

## Register size

**`ours-was-wrong`.** A verification sub-agent first reported 571 register rows (CCOF 152 / OTCO
240 / WSDA 179). A direct YAML count at both `4959284` and `7e0673e` gives **755: CCOF 227 / OTCO
283 / WSDA 245**, with status totals identical to AUDIT.md §6 (CCOF 34 covered / 123 partial /
42 not_covered / 28 out_of_scope; OTCO 48/167/44/24; WSDA 34/122/70/19). The audit's figures are
right. The register did not change between the two commits.

## T17: semantically wrong "covered" mappings (AUDIT §3, §6)

Ten mappings were named. Our reading of each register row against the Trazo question it cites
(`documentation/compliance/certifiers/…` and `certifications/osp_modules/…` at `4959284`):

| Item | Audit's claim | Our reading | Status |
|---|---|---|---|
| CCOF Contract D2 (direct or indirect export) | covered by "neither import nor export" | The only options are export / import / "Neither: all product is sold within the United States" (`g8_0_record_keeping.py:361-391`). A grower selling to a US broker who exports can only tick "Neither". Indirect export cannot be recorded. | **confirmed** |
| WSDA 2264 Q13 (dated application history) | covered by annual summaries | Row cites `crop_history` (display-only yearly summary) and `ParcelCropHistory.substance_applications`, whose date is free text. The form's N/A (no inputs at all) is mapped to `dlpm_none_within_tenure`, which declares no *prohibited* input and only shows when the parcel is not currently certified. | `confirmed-with-correction` |
| CCOF Parcel Application B | covered by a computed "Eligible" | Row cites the display-only transition card (`parcel_application.py:177`) plus dates; `currently_certified` exists but is not cited. Whether §B asks the operator to *apply* for transitional status needs the PDF. | `confirmed-with-correction` |
| CCOF G6.4 B1 / WSDA 2121-L 5, 5a | covered by a produce-wash additive | Dedicated equipment-sanitation questions exist (`stubs.py:413-672`: cleaning methods, sanitizer types, where used, residue assurance, residue testing). But B1, L5 and L5a **also** cite `uses_water` and `water_source_sanitizer`, which are about wash water. Those two citations are wrong; the rest stand. The demo farm did not answer the equipment questions. | `confirmed-with-correction` (stray citations) + specimen |
| WSDA 2121-O Q5 (where records are kept) | covered by a record-type checklist | Row cites `records_location` and `additional_records_locations` ("Are all of your organic records kept at your primary business location?" and, if not, where), not the checklist. | `disputed` |
| WSDA 2196 "how restrictions are met" | covered by product names | Row is already `partial` P1 and its own gap text says no per-material compliance field exists. The product-name row is separate. | `disputed` (already disclosed as partial) |
| CCOF G6.1 C1 (ownership with another handler) | covered by the handler list | Row cites `handled_by_another_operation`, which has an explicit option "ownership of the crop transfers to that operation before or upon delivery" (`g6_1_harvest_transport.py:509-539`). The handler list is cited on C2. | `disputed` |
| CCOF G8.0 A1 (records retained) | covered by selected records | Row cites `s11_records` + `records_retention_attestation`. Caveat accepted: the attestation covers the record types the operator confirmed, which is narrower than "all records needed". | `disputed` (scope caveat accepted) |
| CCOF G6.0 C2 (equipment grid) | silently absent | Row is `not_covered` P1, gate C1 also `not_covered`. No equipment-inventory question exists. The gap is real but disclosed in the register, not silent there; whether page 04 discloses it is T15. | `confirmed-with-correction` |
| CCOF G7.0 A1/B1/C1, G6.1 C4 (labels) | covered | A1, B1, C1 are `partial` P1 (gap text: uploaded label files never reach the packet); C2 `not_covered`; G6.1 C4 `out_of_scope`. The register is honest; the **packet** lacks the attachments, which LEDGER.md keeps in scope under T19. | `confirmed-with-correction` |

Several of the audit's "no answer printed" observations are true and are caused by the demo
farm not answering a question that exists. LEDGER.md scores those on the *specimen* axis, not the
*mapping* axis.

## T18: materials

`confirmed-with-correction`. Blank "In use / Intended" and "Comments" cells are deliberate: they
fill only from the plan's per-material status and from National List or prohibited matches
(`common_osp_workbooks.py:785-808`, `:471`). The Neptune 2-4-1 vs 2-3-1 and Tsunami 100 vs
SaniDate 5.0 conflicts are in the demo data (`history/management/commands/_calapooia_bend_data.json`).
The code share of the finding is that rows match by exact normalised name only
(`_norm_name`, `:364`), so a near-duplicate product is shown as two rows and flagged nowhere.

## T27: OTCO source verification

`closed-by-us`, and it found a real defect. The originals download with a browser user agent and
a referer (see `sources/otco/MANIFEST.md`). 13 of 14 registered OTCO forms match the register's
revision stamp. **O1 does not:** the register transcribed rev. 2025/08/27; the live URL serves
rev. 2026/03/25, which widens the certification-history questions to responsibly connected
persons and adds three affirmation/reinstatement checkboxes.

## T28: narrative contradictions

`confirmed-with-correction`. Both contradictions come from demo text in
`_calapooia_bend_data.json`: "no conventional production anywhere" vs buffer rows sold as
conventional process fruit, and "onion sets" typed into the annual-seedlings answer. No code maps
a crop name to a stock class. It stays OPEN in LEDGER.md as a reviewer-fixture task.

## T30: public copy

Mostly confirmed (LEDGER.md). One item is `disputed` as a defect and raised as a policy question:
`methodology/page.tsx:136-139` says fuzzy matching at a 90% threshold displays as "Verified via
USDA Organic Integrity Database". `.claude/rules/compliance.md` explicitly permits that phrase
"only for DB matches", and the same rule file lists the 90% fuzzy match as a known limitation. The
tension (a fuzzy match labelled "verified") is real and is Oscar's call, not a copy fix.

## NOPB06 sections: A–H or also I/J?

`open-question`. AUDIT.md describes CCOF's Certification Contract as "sections A–H" (§3, line 39; T16,
line 207) and, in §6 (line 102), says optional "Contract I/J fields" are missing from the register.
Both cannot hold for one edition unless I/J are unlettered optional blocks after H. The register
stops at H. Phase 2 re-reads NOPB06 V2 R5 before any row is added.

## "Six alignment verdicts" (AUDIT.md line 1186)

`confirmed-with-correction`. The request that produced the audit defined six verdicts. The report's
own legend (line 238) uses four (D, P, X, N) because it found no instance of "answered, same
structure" or "Trazo asks something the form doesn't" (§4 says so). Read line 1186's "six" as the
requested vocabulary; the tables use four.

## Audit §2: packet provenance

The audit notes that packet provenance was "a builder statement". For the record: the five packets
were generated on 2026-09-29 by `generate_osp_packet` at trazo-back `4959284`, from a detached
worktree, against the local development database's Calapooia Bend OSP id 66 (v4, draft). Each
certifier was set on the plan inside a transaction that was rolled back; `certifier_name` read
back as empty afterwards. Local data can differ from production's copy of the same demo farm.
