# Trazo OSP alignment: run 5 confirmation

Date: 2026-10-02. Scope: R4-01 through R4-04 and regression comparison with the run-4 evidence.

**All four follow-ups pass within the supplied artifact scope. No regression was found in the previously passed packet behavior checked.** Close these four packet/evidence findings and proceed to Phase 5. This does not close unrelated findings or establish certifier acceptance.

## Evidence and scoring

Reviewed the run-5 manifest, 11 packet ZIPs, both freeze logs and frozen filings, the supplied command and test sources, and the corresponding run-4 outputs. All 11 ZIP hashes, sizes and entry counts match the manifest. The manifest identifies backend commit `e7044ebbea6090e51b06ea9382e8e0e5ef2ee052`.

Scores below mean **D: demonstrated by supplied artifacts and independent inspection/recomputation; U: runtime implementation not independently exercised; —: not a separate claim for this finding**. A U is an evidence boundary, not a failed correction. Test source was inspected; the tests and command were not executed in this review, and this bundle does not demonstrate CI execution.

| Finding | Schema | Mapping | Specimen | Rendering | Disclosure | Result |
|---|---|---|---|---|---|---|
| R4-01: unresolved evidence requirements | U | D | D | D | D | Pass |
| R4-02: replacement dates | U | — | D | D | D | Pass |
| R4-03: freeze-evidence stages | U | — | D | — | D | Pass |
| R4-04: agent-specific renewal scope | U | D | D | D | D | Pass |

Paths below identify members inside the packet ZIPs. `A3/<agent>` means `packets/as-seeded/v3-active/calapooia-v3-active-<agent>.zip`; `A4/<agent>` is the corresponding `v4-draft` ZIP; `R3/<agent>` means `packets/routed/v3-active/calapooia-v3-active-<agent>.zip`.

## R4-01: unknown requirements remain unknown

**Observed.** All 48 as-seeded parcel PDFs, across active and draft packets for CCOF, OTCO, WSDA and OCI, avoid “Not asked on this branch” for the certificate and continuity items. Both items instead say: “Whether this is asked is not determined on this route; shown for reference.” The full 36-month accounting remains printed.

All 36 mapped-agent unresolved summaries explicitly say that the evidence the agent asks for is not determined. The 12 OCI summaries use different, adequate wording: “This agent's own form sets the evidence it asks for; Trazo does not assess it.” That communicates non-assessment without claiming an exemption.

All 18 routed parcel PDFs retain “Not asked on this branch” where the resolved route does not ask. Their existing-acreage routing and page-04 coverage behavior remain unchanged from run 4.

Evidence: `A3/{ccof,otco,wsda,oci}` and `A4/{ccof,otco,wsda,oci}`, `parcels/parcel-application-*.pdf`, **p1** summaries; certificate/continuity and route detail on **p4** for Home Field East, Home Field West and River Block, and **p3** for Bottom Ground A, Bottom Ground B and Upper Terrace. Resolved comparison: the same members in `R3/{ccof,otco,wsda}`. Coverage comparison: `04-coverage-and-scope.pdf` in all 11 packets.

**Inference.** The displayed distinction between unresolved, fallback and resolved routes now holds consistently across the supplied specimens. This is not additional verification of the agents' source requirements beyond run 4.

## R4-02: each historical replacement date is preserved

**Observed.** All seven active packets print revision 1 as replaced on **2026-10-01**, revision 2 as replaced on **2026-10-02**, and revision 3 as current.

Evidence: `A3/{ccof,otco,wsda,oci}` and `R3/{ccof,otco,wsda}`, `02s-renewal-status-and-routing.pdf`, **p1**.

The supplied `tests/test_annual_update_revisions.py` includes a three-revision test checking distinct replacement dates and their PDF rendering. Its source supports the intended regression protection; execution is unverified here.

## R4-03: the freeze evidence now reconciles

**Observed.** Both `evidence/freeze-2026-revision-2.json` and `evidence/freeze-2026-revision-3.json` distinguish the original state, the state after packet generation recompiles narratives, and the state after rollback. Stage 1 equals stage 3. The sections edit begins from stage 2, which explains the previously unexplained difference.

For both logs:

- The before and after section canonical strings reproduce exactly under `sections_hash_method`, and all four section digests recompute correctly.
- The six signed-content canonical payloads, across before, after edits and after rollback, hash correctly under the stated signed-content method. Each revision's payload remains unchanged across those stages.
- The created notification includes its ID and content: plan ID, category, description, notification date and method.
- The logged PATCH response is **409**, with the body identifying the annual-update revision as locked.
- The rollback evidence reconciles with the original recorded state.

The supplied command source explains the stage ordering and records the notification values. These are internally consistent recorded results, supported by independently recomputed hashes; they are not an independently replayed API test.

Frozen PDF SHA-256 values, independently checked and unchanged from run 4:

| Filing | SHA-256 |
|---|---|
| Revision 2 | `e20e05678556cc1e3c22a802defd7442ed2a19daa21a125a91359f70d92761b7` |
| Revision 3 | `4cd62bbfb9367fd8287c9e7fb56abfb9cc777802935abff96b6aea5e79dbe3bb` |

The embedded historical copies match these frozen files. All seven active `02-annual-update.pdf` files match frozen revision 3.

## R4-04: renewal scope is on the correct mutable page

**Observed.** `R3/otco/02s-renewal-status-and-routing.pdf`, **p1**, states that Step 6 includes everything on the certificate, including products not sold as organic, and describes the written-petition condition for excluding a portion not sold as organic from the fee. It identifies the printed subtotal as unreconciled and not the agent's fee figure.

`R3/wsda/02s-renewal-status-and-routing.pdf`, **p1**, names **AGR 2521**, previous-calendar-year income received and organic services. OTCO's routing page does not name AGR 2521; WSDA's does not name OTCO Step 6. The same agent separation holds across the other supplied routing supplements.

The frozen active `02-annual-update.pdf` remains neutral and byte-identical. The new agent-specific explanation therefore does not rewrite the historical filing.

## Regression check and disposition

**Observed.** Compared PDF text across all 11 packets with run 4. The covers, coverage pages, change notifications and G6.0 module outputs remain unchanged. Routed parcel output remains unchanged. The 11 plan snapshots differ only in fresh-seed UUIDs. Other textual changes correspond to the requested parcel disclosures, corrected revision dates and renewal-scope wording in mutable documents. Both frozen PDFs remain byte-identical. Representative changed parcel and routing pages were also visually inspected and remain legible.

**Inference.** No regression is demonstrated in the previously passed packet behavior covered by this comparison. This does not establish live application behavior, frontend deployment, or CI success.

**Recommendation.** Close R4-01 through R4-04 on the demonstrated packet/evidence axes and resume Phase 5. Retain the established limits, including the deliberate absence of a stated 2027 intention. This confirmation does not create a new corrective round.
