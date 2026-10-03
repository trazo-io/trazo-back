# Trazo OSP alignment: run 6b confirmation

Date: 2026-10-03. Scope: confirmation of R6-01 through R6-04, the Entrust wording, and regression comparison against run 6.

**The four requested corrections and Entrust wording are demonstrated. One low-impact suggestion regression remains: the Down To Earth Feather Meal review candidate present in run 6 has disappeared. No other regression was found in the checked behavior.**

Close the original corrections on the demonstrated artifact axes. Track the lost suggestion as a small follow-up, R6b-01. It does not undermine identity safety, restriction disclosures, frozen filings or the verified page references.

## Evidence and five-axis scores

Started with `MANIFEST.md`. Independently verified the hashes and sizes of all 14 packet ZIPs. The manifest and both freeze logs identify backend commit `376a249869153e896a93c445964d2dddc84f63a1`. Compared the supplied panels, workbook cells, index pages and extracted packet text with run 6. Inspected representative changed index pages visually.

Scores: **D** demonstrated in supplied artifacts; **P** partially demonstrated or observed deficiency; **U** runtime implementation not independently exercised; **—** not applicable. Supplied test/source files do not establish CI execution. The classification findings below concern the supplied rendering extract, not a separately executed dossier render or live database inspection.

| Item | Schema | Mapping | Specimen | Rendering | Disclosure | Result |
|---|---|---|---|---|---|---|
| R6-01: conditional parcel states | U | D | D | D | D | Pass |
| R6-02: Serenade and Surround candidates | U | D | D | — | D | Requested examples pass; see regression |
| R6-03: classification rendering extract | U | D | D | D | D | Pass within extract scope |
| R6-04: ordering and document wording | U | D | D | D | D | Pass |
| Entrust count wording | U | D | D | D | D | Pass |
| R6b-01: Feather Meal candidate lost | U | P | P | — | — | Low-impact regression |

Paths: `A3/<agent>` denotes `packets/as-seeded/v3-active/calapooia-v3-active-<agent>.zip`; `A4/<agent>` is the corresponding v4-draft ZIP; `R3/<agent>` denotes the routed active ZIP; `D3/<agent>` denotes `packets/decided/v3-active/calapooia-v3-active-<agent>-decided.zip`. Member paths follow those prefixes. PDF page references are physical pages.

## R6-01: pass

**Observed.** In `A3/ccof/06-question-index.pdf`, p5, Parcel Application A10a and A10b name all six parcels. Each says “does not apply” and quotes the readable trigger: “Is treated lumber in contact with crops or soil?” answered **No**. Neither row retains the register placeholder or prints a stored trigger key.

`A3/wsda/06-question-index.pdf`, p29, Site Application 12a does the same. The corresponding as-seeded draft and decided rows also pass. WSDA repeats the same six trigger explanations for its two mapped conditional parts; this is redundant but readable and does not alter the result.

**Observed.** Routed existing-acreage packets correctly retain the higher-level “not asked on this route” reason instead of replacing it with the treated-lumber branch. The reasons name all parcels: CCOF A10a/A10b, index pp3–4; WSDA 12a, p25. This preserves the route distinction accepted previously.

**Recommendation.** Close R6-01. Deduplicating identical WSDA explanations is optional polish, not a blocker.

## R6-02: requested candidates pass

**Observed.** `panels/as-seeded-identities.json` now includes:

- `Serenade Opti` → `Bayer Serenade Opti A Wettable Powder Biofungicide`, OMRI target 1057.
- `Surround WP Crop Protectant` → `NovaSource Surround WP Agricultural Crop Protectant`, OMRI target 6186.

Both are suggestion objects, with `after_prefix: true`, not identity decisions. Neptune, Entrust, Grandevo and the two source-specific Tsunami prompts remain. No newly introduced, obviously unrelated pair appears in this specimen. This is a review of the displayed examples, not proof that the heuristic can never suggest a false pair.

### R6b-01: the Feather Meal suggestion regressed

**Observed; low impact.** The run-6 panel suggested `Down To Earth Feather Meal 12-0-0` against `Down to Earth All Natural Fertilizers Feather Meal 12-0-0`, OMRI target 2924. The same logged row in run 6b has `suggestions: []`, although that plan product remains in the Materials List. Evidence: the named row in each bundle's `panels/as-seeded-identities.json`, plus `A3/wsda/workbooks/Materials List.xlsx`, sheet `Materials List`, A7 and A22.

**Inference supported by source.** In `tests/material_suggestions.py`, `_product_lead` removes maker words from the target name, but the comparison still uses the logged name's original lead. For this pair, the target moves past “Down to Earth” while the logged lead remains “Down”; the new prefix rule does not recover the pair.

**Recommendation.** Restore this candidate through conservative product-phrase handling and add a regression case alongside Serenade and Surround. Keep a negative case for distinct products from the same maker. Do not restore broad manufacturer-only matching or automatic linking. The record remains “Identity not confirmed,” so this is a lost review convenience rather than a false identity or approval claim.

## R6-03: pass within the supplied rendering evidence

**Observed.** `panels/classification-rendering.json` includes 20 seeded event records: 14 Entrust/Spinosad and six Rex Lime Sulfur/Lime sulfur. Their IDs and commercial names reconcile with the corresponding events in `panels/as-seeded-identities.json`.

Every seeded record has `stored_basis: legacy_unverified`. Each supplied dossier cell names the stored substance followed by “recorded before Trazo kept how it was matched; not verified.” None includes a regulatory citation.

The three rolled-back examples also agree internally:

| Event | Stored basis and substance | Supplied dossier cell |
|---|---|---|
| 87, Ethanol | `exact`; Ethanol | `Ethanol (205.601a)` |
| 88, Ethanol 25% REVIEW FIXTURE | Empty basis; no stored classification; Ethanol suggestion | `Ethanol: possible listing from a partial name match, not confirmed` |
| 89, REVIEW FIXTURE operator product | `operator`; Ash from manure burning | `Ash from manure burning (205.602a)` |

**Inference.** This closes the prior absence of event-level classification/rendering evidence at the scope requested. A citation is not being treated here as approval or a compliance finding. The extract does not independently establish live database values, the appearance of a complete dossier PDF, or CI execution.

**Recommendation.** Close R6-03's supplied-extract evidence gap with that scope recorded.

## R6-04: pass

**Observed.** Every registered-agent index now gives its order source and retrieval date on p1, describing the sequence as **Trazo's registered order**:

| Agent | Disclosed source | Retrieval date |
|---|---|---|
| CCOF | `https://www.ccof.org/ccof-osp-forms/` | 2026-09-07 |
| OTCO | `https://tilth.org/help-center/blank-forms-all/` | 2026-09-09 |
| WSDA | `https://agr.wa.gov/departments/organic/forms-and-applications` | 2026-09-07 |

This confirms the disclosure correction; it does not revalidate those historical inventories against today's websites. WSDA's Crop Producer Organic System Plan header now precedes section A on p1 in every WSDA variant.

“Form located in” is absent from all indexes. Documents that do not name the form are introduced as **“Related packet document”**, retaining the explanatory qualification. OCI correctly remains a one-page no-register disclosure with no rows; it does not invent an order source or date.

**Recommendation.** Close R6-04.

## Entrust wording: pass

**Observed.** All three decided workbooks, `Materials List!F8`, now say:

> Identity not confirmed for every logged use: 13 of 14 logged uses identified by the operator, 1 excluded by the operator.

This agrees with the identity panel's 13 covered uses and one exception. All 14 `name_wsda_not_in_osp` findings remain, including excluded event 73. The misleading “the operator has not identified it” wording is gone from that row.

## Regression comparison

**Observed.** Apart from R6b-01:

- All **2,751 explicit PDF answer-label/heading references** still resolve to the cited file and page.
- After normalizing fresh-seed UUIDs, the only changed packet PDF texts are the 14 question indexes. Previously passed parcel routes, renewal chronology, agent-specific scope, material-module content and disclosures remain unchanged.
- All seeded and routed Materials List cell values are unchanged. The sole decided-workbook cell change is the requested Entrust wording. Neptune's operator-attributed join, SaniDate's different-product statement and Serenade's unverified operator restriction disclosure remain intact.
- Frozen revisions 2 and 3 remain byte-identical to run 6. Every active 02 still matches frozen revision 3.
- Both new freeze logs identify the manifest commit. Stage 1 equals stage 3, the sections edit starts at stage 2, all four section digests and six signed-payload digests recompute, and both recorded PATCH refusals remain 409. The earlier commit-provenance mismatch is resolved.

**Recommendation.** Accept the focused corrections and repair R6b-01 with a small suggestion test and panel check. No full audit round or reopening of the earlier packet fixes is warranted.
