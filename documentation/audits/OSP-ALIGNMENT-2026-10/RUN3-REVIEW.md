# Trazo OSP alignment: run 3 verification

Review date: 2026-10-02. Evidence: `Trazo-Review-Handoff-2026-10-01.zip`, starting with its `MANIFEST.md`. Declared producer commit: backend `75226a4`; app `4c86274`. This is an independent review of the supplied artifacts, not a code review or a live filing test.

**Verdict: substantial progress, but do not close T20 or T21-F1 across all five axes yet.** Frozen-file delivery and legacy disclosure are demonstrated. The main certified-parcel source readings are supported, subject to applicability. However, the coverage page still demands skipped questions, fallback parcels make an unsupported exemption claim, and CCOF's active-packet summary undercounts missing evidence. The renewal crosswalk has a demonstrably incorrect OTCO mapping, and the signed specimen still contradicts its own current plan.

## Evidence and scoring conventions

Paths below are relative to the extracted handoff. `v3/<agent>/<file>` means the member `<file>` inside `packets/v3-active/calapooia-v3-active-<agent>.zip`; `v4/` means the corresponding v4-draft ZIP. `all` means all five agents. Pages are one-based PDF pages.

- **Observed:** directly in the supplied files, independently calculated from their bytes, or read in the downloaded official source.
- **Inference:** a likely implication or implementation cause that the artifacts alone cannot establish.
- **Recommendation:** the requested correction or next verification step.

Five-axis scores are categorical, not a compliance percentage: **D** demonstrated for the stated scope; **P** partly demonstrated; **F** contradicted or defective in this evidence; **U** unverified by this bundle; **—** not applicable. Schema means persistence/workflow capability, not merely a field appearing on paper. Mapping means the semantic correspondence with the official requirement. Rendering includes whether the correct content and state print, not just typography.

I extracted and indexed text from all 355 PDFs in the ten packet ZIPs, checked the requested renewal and parcel sections across agents, compared v3/v4 parcel output, searched for overclaims and reviewed their context, and visually inspected seven selected pages. This is not a claim that every page or every workbook cell received visual inspection. All 30 active-packet parcel applications were checked for the certified route and summary; their draft counterparts were compared as well. No production database, UI, migration, test suite or certifier acknowledgment was independently exercised.

## 1. Renewal: what passes and what remains open

### Integrity and state: demonstrated

**Observed:** All ten packet ZIP SHA-256 hashes, byte sizes and member counts match `frozen/evidence.json` and the corresponding manifest hashes/counts. The separate frozen PDF hashes to:

`e20e05678556cc1e3c22a802defd7442ed2a19daa21a125a91359f70d92761b7`

Every active packet's `02-annual-update.pdf` and `annual-update/2026-revision-2.pdf` has that same hash. That independently establishes byte identity across all eleven copies, including the separate frozen file.

**Observed:** `v3/all/annual-update/2026-revision-1.pdf`, p1, explicitly says it was rendered from records as they stood on October 1, is not the filed document, and was not signed in Trazo. `v3/all/02s-renewal-status-and-routing.pdf`, p1, repeats the limitation, identifies revision 1 as superseded and revision 2 as current, and says no agent acknowledgment is recorded. This is honest legacy handling. The newer draft is correctly identified in `v4/all/02-annual-update.pdf`, p1, and `02s`, p1, as 2027, unsigned/unfiled. The v4 OSP snapshot also says “Draft, not submitted.”

**Observed / limitation:** `frozen/evidence.json` reports equal before/after byte and content hashes, an equal post-edit packet hash, and the four attempted edits. However, those edits are descriptive strings, not captured requests/responses or before/after records. The canonical signed-content payload is absent. I can verify the file hash and consistency of this log; I cannot independently replay the edits, verify the HTTP 409, or recompute the signed-content hash from its underlying canonical data. This is corroborating test output, not independent proof of all mutation guards.

### Does revision 2 carry §205.406(a)(1)–(4)?

| Requirement | Artifact evidence | Verdict |
|---|---|---|
| (a)(1), previous-plan changes supported by documentation | `v3/all/02-annual-update.pdf` p1 describes changes; `03-change-notifications.pdf` supplies one recorded Grandevo notice. The named agent ticket is a narrative reference, not an attached agent response. | Content present; documentary sufficiency is not established merely by the narrative. |
| (a)(2), additions/deletions intended for the coming year | Same p1 has headings and three additions, but the text describes February/June 2026 actions already undertaken and continuing work begun in 2024. The deletion answer describes the past. | Structurally present; prospective specimen answer not demonstrated. See R3-01. |
| (a)(3), changes to §205.401(b) information | Same p1 expressly attests no changes to operation/contact/responsible-person information. | Demonstrated as an operator statement, not independently verified facts. |
| (a)(4), other agent-required information | Same p2 supplies an explicit answer referring to the materials update. | Answer present. Whether it exhausts actual agent requests is not proven. |

The regulation distinguishes previous-year changes from coming-year intentions. Four populated headings are not evidence that all four obligations are substantively satisfied. Source: [7 CFR 205.406](https://www.ecfr.gov/current/title-7/subtitle-B/chapter-I/subchapter-M/part-205/subpart-E/section-205.406).

### Agent routing: correct destinations, incomplete crosswalk truth

| Agent | `v3/<agent>/02s-renewal-status-and-routing.pdf` | Assessment |
|---|---|---|
| CCOF | pp1–2: renewal contract and NOPB88 crop update | Correct agent names/forms; the packet distinguishes supporting material from the agent's own forms. This review did not independently reproduce the captured web contract. |
| WSDA | pp1–2: annual renewal application, AGR 2516 and AGR 2521 R05/26 | Appropriate routing; own-record alternative for 2516 is acknowledged. Fee-basis caveat needs to reach the user-facing PDF; see R3-03. |
| OTCO | pp1–2: OSP Update Application & Agreement | Correct form, but Step 5-4 is semantically mismapped and Step 6's locator is stale; see R3-02. |
| OCI / MOSA | p1 | No borrowed renewal-form names or numbers. Pass for renewal routing. The separate parcel fallback defect remains R3-06. |

## 2. Certified parcels: challenge against original sources

I downloaded the official CCOF parcel PDF, WSDA 2264/2516/2521 PDFs, and OTCO C2/FACT-04/OSP Update DOCX files on October 2. Their bytes match the corresponding supplied source hashes. The C2 source is a Word document, not a PDF; its actual content was read, rather than relying on the register's transcription.

| Agent | Independent source reading | Assessment of supplied parcel branch |
|---|---|---|
| CCOF | NOPB49 p3 F2 Yes skips to G. P4 G requires both a current certificate listing the parcel and no-lapse verification; examples include certifier confirmation or an appropriate affidavit. | The detail correctly keeps the checkbox distinct from verification and names both missing evidence items. The active summary does not count them. |
| WSDA | AGR 2264 p1 describes initial applications, new/increased acreage and transfers; the transfer example is between WSDA-certified operations. AGR 2516 p1 handles changed site information and permits other records carrying its required identifiers and information. | The existing-site branch is supported for a site already on the operation's relevant certification. The printed coverage page nevertheless calls 2264 questions unfinished. |
| OTCO | C2's opening instructions say new applications/additional acreage use C2, it need not be updated, and existing-acreage updates use FACT-04. C2 also has a specific recent-inspection OTCO-to-OTCO transfer alternative. Section 2.4 allows certificate-plus-continuity evidence instead of its history table; section 2.5 has affirmation requirements. | Existing-acreage route supported. Do not generalize it to all land certified by any agency or to new/transfer applications. The supplied specimens do not demonstrate those alternate branches. Page 04 still calls C2 history unfinished. |
| OCI / MOSA | No agent-specific source route supplied or claimed as mapped. | Correct to defer to the agent. Incorrect to follow that disclaimer with a categorical claim that its form does not ask for 36-month accounting. |

**Applicability precedes the within-form branch.** CCOF NOPB49 p1 itself directs existing client-profile crop updates to the Crop Update form, while parcel applications concern applicants/new parcels. “F2 Yes → G” is correct when NOPB49 applies; it is not a basis for demanding a fresh parcel application for every ordinary renewal. Similarly, ownership under the same operation is not, by itself, proof that acreage is already on the selected agent's certification. The demo's fictional certifier is an acknowledged limitation, not a new defect here. The unseen new-site/transfer routing must still be tested with explicit fixtures or runtime evidence.

Parcel route/detail page index, identical across the five active agents:

| Parcel file under `parcels/` | Route / certification detail page | Summary page |
|---|---:|---:|
| `parcel-application-Home Field East.pdf` | 4 | 1 |
| `parcel-application-Home Field West.pdf` | 4 | 1 |
| `parcel-application-River Block.pdf` | 4 | 1 |
| `parcel-application-Bottom Ground A.pdf` | 3 | 1 |
| `parcel-application-Bottom Ground B.pdf` | 3 | 1 |
| `parcel-application-Upper Terrace.pdf` | 3 | 1 |

The original T21-F1 sentence demanding a declaration the certified branch never offers is gone. The detail correctly says the declaration is not asked. **The defect is not fully closed because other pages and summaries disagree with that branch.**

## 3. Findings and five-axis scores

These scores assess the described finding, not the whole product. A schema U does not allege that the schema is broken; it means this file-only review did not establish that cause or capability.

| Finding | Priority | Schema | Mapping | Specimen | Rendering | Disclosure |
|---|---|---|---|---|---|---|
| R3-01 Renewal prospective answer not demonstrated | Medium | U | P | F | D | P |
| R3-02 OTCO renewal crosswalk wrong/stale | High | U | F | F | F | F |
| R3-03 WSDA income basis not sufficiently distinguished | Medium | U | P | P | P | F |
| R3-04 Coverage page demands skipped parcel questions | High | U | F | F | F | F |
| R3-05 CCOF v3 summary undercounts missing evidence | High | U | P | F | F | F |
| R3-06 Fallback parcel falsely asserts agent exemption | High | U | F | F | F | F |
| R3-07 Current specimen contradictions remain | Medium | — | — | F | D | F |
| R3-08 Cover contradicts document provenance and deletion answer | Medium | U | — | F | F | F |
| R3-09 Evidence cannot independently close all runtime axes | Review limit | U | — | P | D | P |

### R3-01: a retrospective answer under a prospective heading

**Observed:** `v3/all/02-annual-update.pdf` p1 and the identical revision-2 PDF put already-completed 2026 changes under coming-year additions. “None” under deletions is explained as no removal since the 2025 plan, not an explicit future intention. The correction was signed October 1. No clear intended period or explanation says these were intentions recorded before implementation.

**Inference:** The demo may have reused the changes list as its prospective list. This does not prove a schema limitation.

**Recommendation:** Give additions/deletions an explicit intended period and separate completed changes from future intentions. Correct the specimen through a new signed revision if the filed content is changed. Do not overwrite frozen revision 2. Do not invent future farming decisions; an explicit operator-confirmed no-planned-change answer is acceptable when true.

### R3-02: OTCO Step 5-4 is not the notification undertaking

**Observed:** `v3/otco/02s-renewal-status-and-routing.pdf` p2 calls Step 5-4 “in this packet” and points to the §205.400(f) notification line. The official OSP Update form's Step 5(4) instead undertakes continued operation according to applicable standards **and Oregon Tilth policies**. A promise to notify changes does not establish that undertaking. The supplied `register/otco/forms/OSP-Update-Form.yaml` row `5-4` is `covered` and repeats that incorrect correspondence.

The same PDF page says Step 6 is “in part in this packet” then points to none of its documents and an external dossier. Yet `02-annual-update.pdf` p2 actually contains a 2025 sales subtotal. The official OTCO form's sales scope also includes certified products not sold as organic, subject to its exclusion process; the printed subtotal is not automatically that fee figure.

**Recommendation:** Make Step 5-4 an agreement the operator gives on OTCO's form unless the full undertaking is explicitly captured. Fix the row's status and printed locator together. For Step 6, point to the actual subtotal and disclose the missing scope/reconciliation, rather than saying no packet document contains sales information. Test meaning, not merely field existence.

### R3-03: the WSDA subtotal is not its requested income figure

**Observed:** `v3/wsda/02-annual-update.pdf` p2 defines a total of organic-invoiced sales dated in 2025, then says fee-setting agents ask for “this figure.” AGR 2521 p1 asks for income received in the previous calendar year, including organic products/services. The supplied register correctly recognizes payments versus invoices and service income as gaps, but the PDF does not clearly carry that distinction. `02s` p2 merely says “in part.”

**Recommendation:** Label it as an unreconciled sales-record subtotal, explicitly not the WSDA fee-basis total. State that receipts/payment timing, service income and completeness must be reconciled to the operation's books. Do not add fee computation before the basis is established. This finding concerns the claim about the subtotal, not whether the specimen's arithmetic happens to be correct.

### R3-04: the coverage page still asks for skipped items

**Observed:** `v3/otco/04-coverage-and-scope.pdf` p1 lists C2 2.4 as not yet answered and 2.5 as not checked. Its parcel route pages say C2's land-history items are not asked again on this existing-site route. `v3/wsda/04-coverage-and-scope.pdf` p2 similarly lists AGR 2264 questions 6a, 8 and 14 as unanswered, despite each parcel saying 2264 is not asked for this existing-site renewal. These are presented as “Still open,” not a separate generic capability inventory.

**Recommendation:** Apply the same parcel/form applicability assessment to page 04, the detail and the summary. Distinguish an applicable unanswered question from a question skipped on this route and from general product coverage limitations. Also apply CCOF's form-level new-parcel versus crop-update distinction before F2→G. Do not manufacture answers to clear irrelevant warnings.

### R3-05: active and draft CCOF summaries disagree

**Observed:** All six `v3/ccof/parcels/parcel-application-*.pdf` files p1 say one supporting item is outstanding: the operator map. Their route pages explicitly list no certificate copy and no no-lapse verification attached or referenced. All six v4 CCOF equivalents p1 count three items instead. Their route content otherwise matches after normalizing the OSP version. The draft exposes internal names `certified_certificate` and `certified_continuity` in the summary.

**Inference:** This looks like inconsistent assessment inputs/state between the active summary and detail, potentially related to export-agent selection or cached status. No implementation cause is established without code.

**Recommendation:** Use the same selected-agent, plan-version and applicability context for all renderers. Under the presently printed NOPB49 route, count all three missing items, with readable labels. Test active and draft output plus temporary certifier switching. If the route is an ordinary existing-parcel renewal where NOPB49 does not apply, state that instead of adding requirements. The known absence of uploads is not itself the finding; the contradictory count is.

### R3-06: OCI/MOSA disclaimer is undone on the same page

**Observed:** `v3/{oci,mosa}/parcels/parcel-application-*.pdf`, route pages indexed above, first defer to the agent's own unknown form, then state that the agent's form does not ask for 36-month accounting. Both v4 fallback sets reproduce this. The fallback has no source mapping to justify that assertion.

**Recommendation:** Say Trazo does not assess this agent's land-history requirements and no agent-specific exemption is determined. Keep operator statements and supplied records visible. Remove the unsupported agent claim from every shared paragraph, not only the route-specific introduction.

### R3-07: the frozen current filing and current plan still contradict each other

**Observed:** `v3/all/02-annual-update.pdf` p1 says no split or parallel production. `v3/all/modules/G6_0.pdf` p1 answers Yes to both and describes buffer-fruit segregation. This is the current frozen revision 2 versus current v3, not merely the preserved historical v1 exception recorded in the ledger.

A second contradiction remains within `v3/all/parcels/parcel-application-Home Field East.pdf` p1: the buffer description calls a blueberry row unharvested and immediately says the buffer fruit is picked and sold conventionally. The v4 copy also retains it.

A third state contradiction: `02-annual-update.pdf` p1 describes acknowledgment of the Grandevo notification on February 26 under a ticket, while `03-change-notifications.pdf` p1 marks the February 12 Grandevo notice “not yet acknowledged.” This concerns the input-change acknowledgment, separately from the correctly disclosed absence of acknowledgment of the annual renewal itself.

**Recommendation:** Reconcile those statements with the operator's intended facts. Preserve old frozen bytes and issue a disclosed corrective revision for any signed filing changes. Add focused fixture checks spanning the renewal, module and parcel documents. The onion-transplant wording is fixed in `modules/G3_0a.pdf` p1; the revised shed/lug descriptions are improved. Do not describe T28 as wholly unresolved, but do not claim the current packet is contradiction-free.

### R3-08: cover copy is stale for a mixed live/frozen packet

**Observed:** `v3/all/00-cover.pdf` p2 says every document is generated from live records, which conflicts with the demonstrated frozen filing. P1 reports one deletion while `02` p1's sole deletion entry says none. The count is counting a “None” entry as a deletion.

**Recommendation:** Identify frozen filed documents, reconstructed legacy documents, and current supporting records accurately on the cover. Count substantive additions/deletions or label the count as entries without implying a deletion occurred. Use “Forms to file / renewal routing” rather than “Renewal forms filed” when no evidence establishes filing of those specific agent forms, especially on the 2027 draft. The existing no-acknowledgment disclosure should remain.

### R3-09: narrow the independently verified claim

**Observed:** `frozen/evidence.json` and the artifacts support successful snapshot delivery and recorded test results, but contain no reproducible mutation test, API transcript or canonical signed payload. The PDFs do not exercise authorization, cross-company access, race conditions, migrations or rejected writes.

**Recommendation:** Keep developer-tested and artifact-observed columns separate. Retain a small reproducible freeze test with its commit, canonical payload/hash method, changed record identifiers, before/after values and actual conflict response. This is an evidence request, not an assertion that immutability is broken.

## 4. Ledger honesty: closure by axis

The ledger often appropriately leaves unproved work open. The table below distinguishes demonstrated printed behavior from implementation assertions. “Not established here” does not retract independently retained CI evidence; it prevents this packet review from being cited as proof of it.

| Ledger row | What this bundle demonstrates | What should remain qualified/open |
|---|---|---|
| T15, partly disclosure | Page 04 now names unanswered, partial and missing-upload states instead of treating every mapping as completed. | Applicability/disclosure fails R3-04. Runtime evaluation of all row/gate types is unverified. |
| T16, partly disclosure | `modules/operation_profile.pdf` is renamed; CCOF page 04 p2 distinguishes NOPB06 filed with the agent from supporting material. | Contract capture/agreement completeness remains unproved. The old A–H wording should follow the A–J erratum. |
| T17, mapping corrected with followups | Register edits are present; G8 p1 visibly treats the retired export answer as unconfirmed. | New option capture cannot be proven by a specimen still using the old answer. The new OTCO mapping defect is R3-02. |
| T18, open | No closure sought. | Remains open; no repeated finding on known material-identity limitations. |
| T19, partly attachments/disclosure/specimen | G7 p1 names a real ZIP member and its bytes exist in all packets. | The supplied “label proof” is a text specimen and explicitly does not reproduce the seal. It demonstrates file transport, not complete label-artwork review. Missing/unreadable/over-budget branches are not represented. Cleaning/brand-owner gaps remain as ledger states. |
| T20, complete on five axes | Frozen bytes, legacy disclosure, separate status page, a current signed revision and an unsigned next-year draft are demonstrated. | Reopen mapping/specimen/disclosure for R3-01–03, R3-07–08. Schema/workflow correctness remains developer-tested, not independently demonstrated by these PDFs. |
| T21, partly | All active parcel p1s avoid an eligibility award; dated input records and the explicit no-inputs No are visible. | Unsupported evidence count and route discrepancies remain. Unknown/prohibited cases are intentionally absent and not judged. |
| T22, partly attachments | `05` p2 names the invoice ZIP member and distinguishes the other sale's typed references from attached evidence. | Only the shown invoice branch is artifact-demonstrated; not all attachment types/failure paths. Allocation/loss/custody remain open as acknowledged, without a new finding here. |
| T23, partly fallback | OCI/MOSA `02s` and page 04 do not route users to borrowed renewal forms. | Parcel fallback disclosure fails R3-06. G-coded module filenames remain the separately open T24 matter. |
| T24, open | Existing module naming remains. | No new closure assessment needed. |
| T25, merged | All five v4 `01` p1 titles explicitly say draft/not submitted. | Rendering/disclosure pass for this specimen. Other status branches are not exercised here. |
| T26, done | All 58 form YAMLs have source hashes. Their ordered refs match the corresponding inventories after excluding four explicitly marked interpretation rows. | This checks internal agreement, not independent re-extraction of all 58 official originals or semantic correctness. This review independently matched seven downloaded source hashes. |
| T27, source/mapping corrected | The supplied O1 register/inventory record the newer edition and retain the capture gap. | This review did not independently download/re-extract O1 or all 13 other crop forms. Keep its prior source verification as separate evidence. |
| T28, two contradictions done | Onion cell-tray wording and organic-only handling separation improvements print. | The current frozen renewal still says no split/parallel, and the unharvested-buffer contradiction persists. R3-07 qualifies the claimed closure. |
| T29 | Explicitly excluded from this snapshot review. | No judgment. |
| T30, done | Public landing/app copy is not supplied as rendered evidence. | Not demonstrated by these packets. The ledger itself retains the video-caption exception, so “done” should name the excluded caption work. No new live-site review performed. |
| T17-F1 | G8 p1 names compost records as unconfirmed and marks the earlier Yes unsupported. | Persistence gate and all trigger cases are not demonstrated by the static specimen. Storage/sales/transport triggers remain open as disclosed. |
| T17-F2 | Every active parcel answers no-inputs No separately and prints dated input records beside history. | Branch capture/enforcement is not proven by PDFs; typed historic dates remain partial as disclosed. |
| T21-F1, addressed | Main detail no longer demands the hidden prohibited-material declaration; source branch readings substantially correct. | Cannot close packet-wide rendering/disclosure while R3-04–06 remain. New-site, transfer, attached/referenced evidence and conflict branches are not demonstrated here. |
| T26-F1, closed | Thirteen OTCO crop inventories are present and internally align with registered source refs. | Extraction correctness across all originals is not independently re-run here. |
| T27-F1, open | No closure sought. | Remains open. |

Current register count is **58 forms, 907 total rows: 857 questions, 46 instructions, 4 interpretations**. Source inventories contain the 903 non-interpretation rows. The four extra interpretation rows are explicitly distinguished; they are not an inventory mismatch. Historical ledger counts can remain if labeled by phase/date.

## 5. What to do next in Claude Code

Use a focused corrective plan rather than rerunning all phases. Preserve frozen historical filings. Do not expand this work into T29 or storage changes from a later snapshot.

1. **Unify route-dependent output:** make page 04, parcel summary and parcel detail consume the same agent/form/parcel applicability decision. Fix active-vs-draft CCOF evidence counts and the fallback exemption sentence. Test existing, new and transfer routes separately; test temporary agent selection without persistence and use readable missing-evidence labels.
2. **Correct renewal semantics:** fix OTCO Step 5-4 and Step 6 locators, carry agent-specific fee-basis limitations into the PDF, and distinguish routing instructions from evidence of filed agent forms.
3. **Repair the specimen without rewriting history:** clarify the intended year, reconcile split/parallel and buffer descriptions, issue a new correction when changing signed filing content, and fix cover provenance/deletion counting. Keep revision 2 byte-for-byte unchanged.
4. **Regenerate a small review bundle:** active and draft CCOF, OTCO, WSDA plus one fallback, each with cover, 02, 02s, page 04 and the relevant parcel. Include both frozen hashes and a reproducible mutation-test result. Mark ledger axes by what tests prove and what reviewers can observe.

Approval criterion: no document contradicts the route or evidence status shown elsewhere; no promise is marked covered by a different promise; no operator statement or invoice subtotal is presented as certifier verification or a reconciled fee figure.

## Source verification record

These are official-source downloads independently inspected in this run, with SHA-256 matching the supplied inventory/register. Retrieval used public official URLs; no `api.trazo.io` access was attempted.

| Source | SHA-256 |
|---|---|
| [CCOF NOPB49](https://www.ccof.org/wp-content/uploads/2025/04/Parcel-Application-NOPB49.pdf) | `a6b70892820c1d6e5c3c59697296397c8c9241dd0e2ab64918f7ac92c4a8ddd4` |
| [WSDA AGR 2264](https://cms.agr.wa.gov/WSDAKentico/Documents/FSCS/Organic/Forms_organic/2264_Site_Application.pdf?/2264_Site_Application) | `2700cb9b99f3f8e4cb942fb0e928c8205fc9cae04525e92406d6169bc81824e6` |
| [WSDA AGR 2516](https://cms.agr.wa.gov/WSDAKentico/Documents/FSCS/Organic/Forms_organic/2516_Site_Update_Information.pdf?/2516_Site_Update_Information) | `3a1c0366f6409758ce641f1500b167c5d517169f94d4a767075ecfb57407e3e4` |
| [WSDA AGR 2521 R05/26](https://cms.agr.wa.gov/WSDAKentico/Documents/FSCS/Organic/Forms_organic/2521_Renewal_Fee_Form.pdf) | `3afe3d3f572d7619754936881b2a41b0815e0e5ded5a2c010f145f892e318df6` |
| [OTCO C2](https://tilth.org/wp-content/uploads/2015/05/C2CropsAcreageLandHistory.docx) | `24785f863cbd165fb04354dd0ba9d6dbd55f9ab0cfe21a7eb773b676e9d9fb9f` |
| [OTCO FACT-04](https://tilth.org/wp-content/uploads/2015/01/FieldAndCropTableFACT.docx) | `8677f2616b0450325849c6d1593ccd2b8ecb482a4a4d39487d93308c0984cb65` |
| [OTCO OSP Update](https://tilth.org/wp-content/uploads/2023/03/OSPUpdateFormWeb.docx) | `c1d81ce1c8c3140829e35bf8c974ae378b96006224a5c7ae69f7038d461bfe35` |

The source contents support the limited routing conclusions above; they do not establish acceptance of Trazo output by any certifier. T22's acknowledged allocation/loss/custody limits, deliberately absent demonstration cases, fictional certifier names, T29 and private storage are not newly reported as defects.
