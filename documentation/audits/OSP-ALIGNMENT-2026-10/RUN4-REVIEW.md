# Trazo OSP alignment: run 4 verification

Reviewed 2026-10-02. Evidence: `Trazo-Review-Handoff-2026-10-02-run4.zip`, beginning with `MANIFEST.md`. Declared backend commit: `743c3bfde8a09aa1e90ba516fb585e6a279533d7`.

**Verdict: most run-3 corrections are demonstrated. Keep the route-disclosure and history findings open for a small follow-up; do not restart the four slices.** The routed existing-acreage output works, frozen files and canonical signed hashes verify, and the principal renewal and specimen corrections print. Remaining issues concern unresolved evidence being labeled “not asked,” a changed historical replacement date, and an unexplained inconsistency in the freeze evidence. The active OTCO crosswalk also needs a self-contained scope caveat.

## Scope and notation

`A3/<agent>/file` means the member inside `packets/as-seeded/v3-active/calapooia-v3-active-<agent>.zip`; `A4/` means as-seeded/v4-draft; `R3/` means routed/v3-active. Agents are `ccof`, `otco`, `wsda`, `oci`, where supplied. All page references are one-based PDF pages.

I extracted text from all 399 packet PDFs, checked all 66 parcel applications for the requested route/accounting states, compared the 24 active as-seeded parcels against their 24 draft counterparts, checked renewal output across all eleven packets, and visually inspected six representative pages. I inspected the relevant assertions in the three supplied test modules. **I did not execute the Django tests, inspect the full implementation, verify CI/mutation-test runs, or exercise production.** Test source shows what an assertion checks, not that the test passed at the manifest commit.

Labels: **Observed** means present in files or independently calculated. **Inference** means a conclusion whose cause is not directly established. **Recommendation** means the proposed correction.

Five axes: **D** demonstrated for the stated scope; **P** partial; **F** defective/contradicted; **U** not established by this bundle; **—** not applicable. A schema U is not an allegation of a schema defect.

## 1. One route per parcel

### What now passes

**Observed:** All 36 as-seeded CCOF/OTCO/WSDA parcel PDFs, across active and draft, state that the route is unresolved because the fictional certifier is not recognized. None selects that agent's existing-acreage route. All 12 OCI parcel PDFs defer to the agent and disclaim an agent-specific exemption. All 48 as-seeded parcels print the accounting window rather than the old blanket 36-month exemption.

All 18 routed parcel PDFs select the expected existing-acreage route, replace the window accounting with the corresponding not-asked explanation, and agree with page 04 at the form level:

| Packet | Detail route | Page 04 evidence |
|---|---|---|
| `R3/ccof` | Existing CCOF parcel, Crop Update NOPB88 | `04-coverage-and-scope.pdf` p2 puts NOPB49 under forms not filed for these parcels. |
| `R3/otco` | Existing OTCO acreage, FACT-04 | Same file p2 puts C2 under forms not filed for these parcels. |
| `R3/wsda` | Existing WSDA site, AGR 2516 | Same file p2 puts AGR 2264 and AGR 2262 under forms not filed for these parcels. |

These limited existing-site readings remain consistent with the official sources checked in run 3. CCOF's current NOPB49 p1 explicitly distinguishes adding a parcel from updating crops already on the client profile. WSDA's current forms guidance and Oregon Tilth's update guidance likewise distinguish existing-acreage updates from new land. This does not establish certifier acceptance or verify the operator's certification statement.

As-seeded page 04 now identifies unresolved parcel routes instead of silently skipping their forms: `A3/ccof` p2; `A3/otco` p1; `A3/wsda` pp2–3. OCI page 04 states that Trazo lacks its agent form register. General capability gaps are still listed separately within these coverage descriptions; they are not evidence of a resolved route.

All active/draft as-seeded parcel texts are identical after normalizing the OSP version. No internal `certified_certificate`/`certified_continuity` keys appear in their summaries. The routed CCOF summary's one missing map is **not** the old three-versus-one defect: this set now takes the existing-parcel Crop Update route, where the former NOPB49 G evidence requests are not being imposed.

### R4-01: unresolved and fallback evidence still says “Not asked”

**Observed, high priority:** Every as-seeded parcel route page labels both the certificate copy and no-lapse verification:

> “Not asked on this branch; shown for reference.”

For the 36 mapped-agent parcels, that sits immediately below an introduction saying nothing is treated as not asked. For the 12 OCI parcels, it follows the statement that no agent-specific exemption is determined. The distinction between **unknown applicability** and **not required on a resolved route** is therefore still lost at the individual evidence-item level.

The page-1 summary also continues to say answers are complete, five of five, with one supporting item outstanding, without surfacing the unresolved route. That limited count is not proof that the total required evidence has been determined. Do not fix this by assuming the two uncertain documents are mandatory and counting three; disclose the unresolved assessment separately.

Evidence paths for every as-seeded active/draft agent:

| Parcel member | Summary | Route/evidence labels |
|---|---:|---:|
| `parcels/parcel-application-Home Field East.pdf` | p1 | p4 |
| `parcels/parcel-application-Home Field West.pdf` | p1 | p4 |
| `parcels/parcel-application-River Block.pdf` | p1 | p4 |
| `parcels/parcel-application-Bottom Ground A.pdf` | p1 | p3 |
| `parcels/parcel-application-Bottom Ground B.pdf` | p1 | p3 |
| `parcels/parcel-application-Upper Terrace.pdf` | p1 | p3 |

**Inference:** The route-level three-state decision is reaching the main paragraph and page 04, but an evidence-item formatter still collapses unresolved into not asked. The implementation cause is not proven here.

**Recommendation:** Give evidence items the same three-state semantics. For unresolved/fallback: “Applicability not determined; none attached or referenced.” Surface “Route unresolved; required evidence not yet determined” in the summary. Keep the requested full accounting, clearly described as records available in Trazo rather than a certifier ruling. Do not restore a false exemption or invent a declaration.

The supplied `RouteFollowsTheSelectedAgentTests` tests for the absence of one old accounting sentence, and `FallbackAgentsClaimNoExemptionTests` tests the same specific exemption language. Neither prohibits this surviving “Not asked on this branch” prefix. Add an assertion for every evidence item in unresolved and fallback output, including MOSA. The summary tests compare counts to the same assessment's missing list; they do not test whether that count discloses unresolved applicability.

## 2. Renewal meaning

**Observed:** OTCO Step 5-4 now says “not in this packet; answer it on the form,” without using the notification promise. This prints in `A3/otco` and `R3/otco` `02s-renewal-status-and-routing.pdf` p2 and the draft equivalent. Step 6 points to the actual sales subtotal instead of an absent external dossier. The supplement heading now says forms **to file**.

Every active packet's frozen 02 p2 labels the 2025 sales subtotal unreconciled and not any certifying agent's fee figure. Its neutral wording is appropriate: it was frozen under the fictional agent and must not be rewritten to suit a later export selection. The manifest discloses this accurately.

The draft 02 PDFs provide direct specimen evidence of agent-specific wording, not just test coverage:

- `A4/wsda/02-annual-update.pdf` p1 names AGR 2521 and the receipts/services distinction; it does not name OTCO's form.
- `A4/otco/02-annual-update.pdf` p1 names Step 6 and certified products not sold as organic; it does not name AGR 2521.
- CCOF and OCI draft equivalents use neutral fee-basis wording.

**R4-04, medium priority, remaining disclosure gap:** In active OTCO packets, the Step 6 locator is repaired but the agent-specific sales scope is not explained in the supplement. It says 02 identifies the subtotal as not OTCO's figure; the frozen 02 only says it is not any agent's fee figure. That warning is truthful, but it does not tell the user that OTCO's scope includes certified products not sold as organic or explain the exclusion process noted in run 3. The relevant ledger cell says Step 6 “states its scope gap,” which is stronger than the active specimen demonstrates.

**Recommendation:** Put the current agent's reconciliation caveat in the mutable routing supplement, independently of whether the frozen filing has neutral or agent-specific language. Preserve frozen revision 3. Test the combination of a neutral frozen filing and OTCO export, not only a new unfrozen update under OTCO. This is a small disclosure completion, not a failed subtotal calculation or wrong Step 5 mapping.

## 3. Specimen and preserved history

### Corrections demonstrated

**Observed:** Revision 3, `02-annual-update.pdf` pp1–2 in every active packet, identifies four corrections and expressly preserves revision 2. Split/parallel production now agrees with `modules/G6_0.pdf` p1. No current parcel description calls the buffer row unharvested. The 2026 completed changes appear in (a)(1), rather than being presented as future additions.

Grandevo's claimed acknowledgment is now labeled the operation's account, while `03-change-notifications.pdf` p1 says no acknowledgment is recorded in Trazo. Those statements can coexist. No new acknowledgment evidence is supplied or claimed as recorded. The test source additionally asserts that the fixture did not create an acknowledgment record; its execution is not independently verified here.

The future additions/deletions say **“None stated,” not “the operator confirms none are planned.”** That is honest about the missing intention and follows the instruction not to invent one. It closes the misleading retrospective-answer defect, but does not demonstrate a fully answered prospective section. The ledger's R3-01 untested cell acknowledges this. The test named `test_each_406a_item_is_populated_on_the_current_revision` checks empty additions/deletions lists, so its name must not be used as proof that all substantive answers are complete. Section 205.406(a)(2) concerns intended coming-year changes; an absent intention is not an affirmative no-change attestation.

Cover p1 now counts entries without treating “None” as a deletion. Cover p2 distinguishes frozen filings, reconstructed legacy filings and current records. Those R3-08 corrections pass.

### R4-02: revision 1's replacement date has moved

**Observed, medium priority:** Every active `02s-renewal-status-and-routing.pdf` p1 says revision 1 was replaced as the year's filing on **2026-10-02**. Yet the preserved `annual-update/2026-revision-2.pdf` p1 is filed **2026-10-01** and explicitly corrects revision 1. Run 3's status supplement also reported revision 1 replaced on October 1. Revision 2's own replacement on October 2 is consistent; revision 1's date is not the immediate replacement chronology shown by the chain.

**Inference:** Either subsequent filing updates prior supersession timestamps, or the seeder/status renderer represents them incorrectly. The PDFs do not identify which.

**Recommendation:** Preserve the historical immediate successor and replacement timestamp for each revision: 1 → 2 on October 1; 2 → 3 on October 2. If the application instead means “the latest revision is current as of October 2,” print that separately. Add a three-revision regression test asserting the first replacement timestamp survives the second correction. The included legacy test only checks that `superseded_at` is non-null, which does not catch this change. Repair mutable status/history; do not rewrite frozen revision 2 or 3.

## 4. Freeze evidence

### Independent byte and hash checks

All eleven ZIP hashes, sizes and entry counts match the manifest. Both separate frozen PDFs match their declared hashes. Each revision's seven copies under `annual-update/` match its frozen file; all seven active `02-annual-update.pdf` copies match revision 3.

| Revision | Frozen PDF SHA-256 | Recomputed signed-content SHA-256 |
|---|---|---|
| 2 | `e20e05678556cc1e3c22a802defd7442ed2a19daa21a125a91359f70d92761b7` | `1eb204103b5e634263819131b4c8cf0350692cf225a2a3fea47b2a2780d616f0` |
| 3 | `4cd62bbfb9367fd8287c9e7fb56abfb9cc777802935abff96b6aea5e79dbe3bb` | `da2ebd6ba4a802e9afc4ca240dd4bfbe456ff7941d0e1954143e312a56242b92` |

For each evidence JSON, I parsed the canonical string, serialized using the stated sorting/separator/default rules, checked that it reproduced the supplied canonical string, and SHA-256 hashed its UTF-8 bytes. This succeeded for `before`, `after_edits` and `after_rollback`, six recomputations total. Payloads are identical across those three stages within each revision.

The logs now contain actual-shaped PATCH requests, target IDs, attempted content, 409 status and refusal bodies for revisions 2 and 3. They also record a farm rename, plan-sections edit and new notification ID. The target revision/year and refusal content agree. Returned record-state summaries say the farm name/plan state were restored and the created notification no longer exists. This is materially stronger evidence than run 3. It supports the reported freeze checks; it is not an independently replayed server execution.

### R4-03: unexplained plan-section hashes limit edit/rollback verification

**Observed, medium priority, evidence defect:** In both files, the edit and rollback sections claim to concern plan 3's sections but report different starting hashes:

| Evidence | `edits` plan-sections `before_sha256` | `records_before.plan_sections_sha256` |
|---|---|---|
| revision 2 | `ee312d422d101e693000f6c57764865fb1b3f1f8540b28dbf50daf6dd714f180` | `ab2e400d8496ad7cec4ed0add921449b26bec59dc5bd4ff1e3854f833a2713a1` |
| revision 3 | `b48ef4e4ccb69379264d82b56e9539552ba2681079ce179177556f467cd3d843` | `ab2e400d8496ad7cec4ed0add921449b26bec59dc5bd4ff1e3854f833a2713a1` |

Both rollback hashes match the latter baseline. The evidence does not explain different normalization, snapshots or intermediate mutations. Its `hash_method` describes signed filing content, not these section hashes. The section before/after values are absent; only digests and an added key appear. The created notification's content is absent too.

**Inference:** Different serialization or intermediate state could explain this. It is not proof that the filing changed or rollback failed. The independently recomputed filing hashes still pass.

**Recommendation:** State one section canonicalization method and include its before/after canonical data, or label and explain the distinct stages. Show why the edit's starting digest matches its intended baseline. Include the created notification's relevant content and the evidence-command source/test or a reproducible invocation with its result. Keep `unchanged` scoped to the demonstrated filing bytes/content; qualify complete edit/rollback reproduction until the mismatch is explained.

## 5. Five-axis finding scores

| Finding | Schema | Mapping | Specimen | Rendering | Disclosure |
|---|---|---|---|---|---|
| R4-01 Unresolved evidence labeled not asked; summary omits unresolved state | U | P | F | F | F |
| R4-02 Revision 1 replacement chronology changes | U | — | F | F | F |
| R4-03 Edit/rollback starting hashes not reconciled | U | — | P | — | P |
| R4-04 Active OTCO routing omits the specific scope caveat | U | P | P | P | P |

The following are positive findings, not whole-product approvals:

| Verified correction | Schema | Mapping | Specimen | Rendering | Disclosure |
|---|---|---|---|---|---|
| Existing-acreage form routing for the three routed agents | U | D | D | D | D |
| OTCO Step 5-4 correspondence and subtotal locator | U | D | D | D | D |
| Draft agent-specific fee-basis disclosures | U | D | D | D | D |
| Revision 3's stated corrections; no invented future intention | U | P | D | D | D |
| Frozen PDF identity and recomputable signed payload | P | — | D | D | D |

## 6. Ledger honesty and test limits

The three-column separation is a substantial improvement. The packet-observed column correctly describes run-3 evidence, and run-4 review is still marked pending. Do not interpret that historical column as a current contradiction. Update it with this review's outcomes, rather than simply replacing every pending cell with “passed.”

| Row | Run-4 verdict and qualification |
|---|---|
| R3-01 | Misplaced completed changes corrected. Missing future intention honestly remains unstated. Do not close prospective-answer completeness. |
| R3-02 | Step 5-4 and actual subtotal pointer demonstrated. “States its scope gap” is not fully demonstrated by active OTCO output; R4-04. The supplied pointer test checks strings/locator, not presence of the missing scope explanation. |
| R3-03 | Unreconciled/non-fee labeling demonstrated in all packets. Agent-specific wording is visible in draft packets. The cited `test_packet_second_wsda_read` module is not supplied, although relevant tests and rendered specimens are. |
| R3-04 | Existing-route page-04 defect corrected; unresolved routes are identified. Do not extend this to “every item agrees” while R4-01 remains. The cited `test_r3_route_applicability` name is not present as a supplied module/function; relevant assertions are in `test_certified_parcel_branch.py`. |
| R3-05 | Old active/draft inconsistency and internal-key leakage not reproduced. Counts agree for the supplied states. Required-evidence completeness under unresolved applicability is still not established. |
| R3-06 | The specific blanket 36-month exemption is removed. Both OCI and MOSA appear in test source. OCI's output still contains the item-level not-asked defect, so packet-wide no-exemption closure would overclaim. |
| R3-07 | Named specimen contradictions corrected with acknowledgment provenance preserved. No full database proof of “no new acknowledgment” was executed by this reviewer. |
| R3-08 | Cover provenance/count and routing heading fixes demonstrated. The new R4-02 history finding is separate and remains open. |
| R3-09 | Canonical hash, file identity and refusal-log checks independently verified. The claim that every edit includes before/after values exceeds the JSON for plan sections and the created notification. `test_annual_update_revisions.FreezeEvidenceCommandTests` and the command implementation are not supplied. R4-03 prevents full reproduction of those edit-state checks here. |

No CI output or mutation-test transcript is included. The ledger may retain those as developer-verified claims backed by external CI, but this bundle cannot establish that every named test passed or was mutation-checked. The supplied tests do meaningfully cover alternate routes, attachment/reference distinctions and an unsaved agent selection; these remain source-inspected test cases, not executed evidence from this review. Do not require demo uploads merely to replace the deliberately test-covered branches.

## 7. Recommended next action

A small backend follow-up is enough:

1. Correct unresolved/fallback evidence labels and show unresolved applicability in the parcel summary. Assert this across every item and both fallback agents.
2. Preserve or accurately label each revision's immediate replacement history; test a three-revision chain.
3. Explain/reconcile the evidence-command section hashes and include the missing reproduction material.
4. Add the agent-specific reconciliation caveat to OTCO's mutable renewal routing page when the attached frozen filing is neutral.

Regenerate only the affected parcel pages, coverage page, status/routing supplement and freeze evidence for confirmation. Keep both frozen revisions unchanged. Preserve the successful corrections and carry the stated incomplete future intention as an open specimen fact. These fixes do not require reopening T29, storage, T22 or the acknowledged acreage discrepancy.

Official references rechecked for context: [7 CFR 205.406](https://www.ecfr.gov/current/title-7/subtitle-B/chapter-I/subchapter-M/part-205/subpart-E/section-205.406); [CCOF NOPB49](https://www.ccof.org/wp-content/uploads/2025/04/Parcel-Application-NOPB49.pdf); [WSDA forms guidance](https://agr.wa.gov/departments/organic/forms-and-applications); [Oregon Tilth farm updates](https://tilth.org/help-center/additions-and-updates-to-farm-certification/). Detailed original-source hashes remain in run 3's review. No certifier acceptance or live production behavior is claimed.
