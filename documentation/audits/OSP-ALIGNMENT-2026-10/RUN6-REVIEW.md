# Trazo OSP alignment: run 6 review

Reviewed 2026-10-03. Scope: Phase 5, T18 materials identity and T24 question index, plus regression against the run-5 evidence.

## Decision

**Phase 5 is substantially demonstrated. The core material decisions, restriction disclosures and explicit PDF page references pass. T24 needs a small correction for omitted conditional states. T18's historical National List classification rendering remains unproven by this bundle. No regression was found in the run-5 fixes checked.**

Do not reopen the earlier corrective rounds. Make a focused index correction, improve the two missing suggestion candidates, and supply the missing classification evidence. The ordering and wording observations below can be addressed alongside the index correction.

This is a file-and-source review, not a live application test, CI run, or determination that a certifier accepts the packet.

## Evidence and scoring

Started with `MANIFEST.md`. Independently verified all 14 packet ZIP hashes and byte sizes. The manifest identifies backend commit `3998a7f6c8aeb9bac6fc3f44bc1fa9b8bc30181f`. Inspected all 14 Materials List workbooks, the supplied panels, the index PDFs, relevant service/test sources, and run-5 baseline outputs. Independently checked **2,751 explicit answer-label or cited-heading PDF references across the 12 registered-agent indexes**: every checked file, page and label/heading resolved. This confirms navigation, not semantic completeness of the underlying mapping.

Path shorthand:

- `A3/<agent>`: `packets/as-seeded/v3-active/calapooia-v3-active-<agent>.zip`.
- `A4/<agent>`: the corresponding `packets/as-seeded/v4-draft/calapooia-v4-draft-<agent>.zip`.
- `R3/<agent>`: `packets/routed/v3-active/calapooia-v3-active-<agent>.zip`.
- `D3/<agent>`: `packets/decided/v3-active/calapooia-v3-active-<agent>-decided.zip`.

References after those prefixes are ZIP members. PDF page numbers are physical pages. Workbook references are sheet and cell coordinates. JSON evidence has keys rather than pages.

Five-axis scores: **D** demonstrated within the supplied evidence; **P** partially demonstrated or an observed deficiency; **U** not established here; **—** not applicable. Schema runtime behavior remains U where supplied tests were inspected but not run.

| Reviewed behavior | Schema | Mapping | Specimen | Rendering | Disclosure |
|---|---|---|---|---|---|
| Explicit index page references and OCI fallback | U | D | D | D | D |
| Complete per-parcel conditional states, R6-01 | U | P | P | P | P |
| Seeded unresolved identities | U | D | D | D | D |
| Decided identities and retained approval warnings | U | D | D | D | D |
| Operator-transcribed restriction statement | U | D | D | D | D |
| Review suggestions, R6-02 | U | P | P | — | D |
| Historical National List classification export, R6-03 | U | U | U | U | U |
| Published-order claim and index framing, R6-04 | — | P | D | P | P |

## 1. Question index: navigation passes; conditional coverage is partial

**Observed.** The explicit page references work across active, draft, routed and decided variants. Examples checked directly:

| Index | Entry and index page | Target verified |
|---|---|---|
| `A3/ccof/06-question-index.pdf` | G6.0 A1, p25 | `modules/G6_0.pdf`, p1, buffer/separation question |
| `A3/otco/06-question-index.pdf` | C6 1 and 1a, p19 | `modules/G4_2.pdf`, p1, conservation agreement and agency/program questions |
| `A3/wsda/06-question-index.pdf` | E 2, p5 | `modules/G4_2.pdf`, p1, habitat, soil/water and invasive-species questions; `modules/G4_0.pdf`, p1, biological-diversity practices |
| `A3/otco/06-question-index.pdf` | OSP Update Step 4, p36 | `annual-update/2026-revision-2.pdf`, p1, and revision 3, p1, change-summary heading |
| `A3/wsda/06-question-index.pdf` | Renewal Fee Form 1, p34 | `annual-update/2026-revision-3.pdf`, p2, sales-records subtotal heading |

The filed-document references locate text in the historical PDFs, including `annual-update/`; they do not assert that the located subtotal satisfies the agent's fee calculation. Revision 1 is not marked as frozen. OCI's active and draft indexes are one page, explicitly say no register is held, and list no forms or rows.

The index combines answer locations and unresolved parts rather than treating location as proof of completion. For example, CCOF Parcel Application F2, beginning on p8, names all six parcels, gives their answer locations, and separately states their unresolved route. Routed variants retain their route-specific reasons. No generated status inspected asserts that a question is met, accepted or compliant. Official question wording and operator statements are distinct from Trazo's status language.

### R6-01 — Conditional per-parcel states disappear from the index

**Observed; medium, targeted correction.** In `A3/ccof/06-question-index.pdf`, p5, Parcel Application A10a and A10b show only `parcels/parcel-application-<name>.pdf §A`, labelled as an unchecked register location. They do not name the parcels or explain why the conditional questions have no answer location. `A3/wsda/06-question-index.pdf`, p28, Site Application 12a has the same problem.

Each underlying parcel PDF p1 answers the treated-lumber question **No**. The index should reproduce that conditional state and its basis for each parcel. It should not leave a placeholder suggesting the reader can find an unanswered detail elsewhere.

**Inference supported by source.** `tests/question_index.py`, `build_index`, explicitly drops individual parts whose state is `not_applicable`. The supplied per-parcel acceptance test in `test_calapooia_renewal_specimen.py` skips a row if any part is `not_applicable`. That leaves exactly this omission untested.

**Recommendation.** Retain those parts and print each parcel's “does not apply” state with the triggering answer. Test a mixed row where one parcel is answered, one is unresolved and one is not applicable. Group identical states only if all affected parcels remain named. Close T24's conditional-state rendering after that focused check.

## 2. Seeded materials: unresolved names stay unresolved

**Observed.** All 11 seeded/routed Materials List workbooks retain **11 logged-name rows** marked “Identity not confirmed.” Across the as-seeded active agents, these occupy `Materials List!A7:F17`; the nine plan-material rows follow at rows 18–26. The values agree across CCOF, OTCO, WSDA and OCI.

For example, logged Neptune 2-3-1 remains separate from planned Neptune 2-4-1. Entrust SC, Serenade Opti, Grandevo WDG and Surround WP remain separate from the longer catalog names. I found no partial-name match promoted to a product-identity resolution in these workbooks.

`modules/materials_application.pdf`, p1, continues to flag the unmatched names. Its National List section lists the plan's three substance entries, with brand/formulation and manufacturer explicitly unstated. Those plan entries are not evidence that any particular logged product has been classified correctly.

### R6-03 — The National List provenance report cannot prove export rendering

**Observed; evidence gap, not a demonstrated code defect.** `panels/national-list-provenance.txt` reports 20 stored classifications, says all **will be** marked `legacy_unverified`, and reports that today's exact/alias rules would reach 14. It does not contain event IDs, their actual post-migration basis values, or the wording rendered for those events.

No event-classification dossier exhibiting those 20 records is supplied. The three plan-substance citations in the materials module are a different relationship and cannot validate historical ChemicalEvent classifications. Conversely, their presence is not evidence that the legacy suppression failed.

**Inference.** The supplied test source supports the intended design, but not a packet-observed pass. In particular, the test named `test_the_dossier_prints_a_legacy_classification_as_not_verified` checks the helper's return value rather than rendering a dossier.

**Recommendation.** Add a small export fixture with an event-level snapshot and the actual rendered result for: a legacy classification, a partial-name suggestion, an exact classification, and an operator-set classification. Include event ID and stored basis. That is sufficient to close this evidence gap; no full packet re-audit is needed. Do not mark all of T18's classification-rendering axis complete yet.

## 3. Decided materials: the requested outcomes pass

**Observed.** The three decided workbooks agree:

- **Neptune:** `Materials List!A24/F24` contains the planned 2-4-1 product and the original logged 2-3-1 name, with an operator-identification basis dated **2026-10-03**. The panel lists 28 covered events and records the formulation acknowledgment and fabricated fixture explanation. The workbook attributes identity to the operator; it does not declare approval.
- **Entrust:** `A8/F8` remains “Identity not confirmed.” `panels/decided-identities.json` records 13 covered events and one exception, **event 73**. All **14** corresponding entries in `panels/decided-drift-findings.json`, including 73, retain `reason_code: name_wsda_not_in_osp`. Identity has not erased that approval finding.
- **SaniDate:** `A16/F16` states that the operator identified it as a different product from the plan's, dated **2026-10-03**.

**Recommendation, wording only.** Entrust's generic explanation says the operator “has not identified it,” although 13 uses were identified. Keep the unresolved status, but prefer “not all logged uses have been resolved,” with reviewed/excepted counts or a pointer to the review history. This is not a failure of the requested conservative status.

The decided set is a fabricated, rolled-back review fixture. Its notes establish how the software displays an operator assertion, not that Neptune's formulations are actually identical.

## 4. Restriction statements: requested disclosure passes

**Observed.** In every `D3/<agent>/workbooks/Materials List.xlsx`, `Materials List!A20/F20` contains the Serenade restriction, source identifier and page, the phrase **“Restriction transcribed by the operator; not independently verified by Trazo,”** and a dated answer attributed to Seed Runner. It explicitly calls that answer the operator's statement, not a compliance finding. Both the restriction and answer identify their fabricated fixture provenance.

The other eight plan-material rows say **“Restriction not documented in Trazo.”** All nine plan-material rows carry that wording in the seeded active workbooks. Unresolved logged-name rows remain identity exceptions rather than being assigned another product's restriction.

The full restriction text is present in the cell and survives an independent workbook-to-PDF rendering check. The supplied workbook's print layout separates product columns and comments onto different pages; that is a usability observation, not evidence that the stored disclosure is missing.

The regulation-wording branch remains specimen-untested, as disclosed by the user. I do not infer its behavior from this operator-transcribed example.

## 5. Suggestions: safe examples, two missing candidates

**Observed.** `panels/as-seeded-identities.json` suggests Neptune 2-3-1 versus 2-4-1 and explicitly records that their numbers differ. SaniDate is shown alongside Tsunami 100 from two identified plan questions, with the catalog subtype and the plan's Peracetic acid entry. These are reasonable reconciliation prompts, not proof of interchangeability.

The other displayed candidates are Feather Meal, Entrust and Grandevo. No obviously unrelated pair appears in this specimen. The two Tsunami suggestions cite different questions; they are duplicate product candidates with distinct source locations. The packet does not publish these computed suggestions as decisions.

### R6-02 — Leading-word matching misses two obvious review prompts

**Observed; low, nonblocking improvement.** Both of these logged names have empty suggestion arrays despite corresponding plan-product names:

| Logged name | Plan product worth reviewing |
|---|---|
| Serenade Opti | Bayer Serenade Opti A Wettable Powder Biofungicide |
| Surround WP Crop Protectant | NovaSource Surround WP Agricultural Crop Protectant |

Evidence: the named objects in `panels/as-seeded-identities.json`; `A3/wsda/workbooks/Materials List.xlsx`, `A11/A21` and `A12/A26` respectively.

**Inference supported by source.** `tests/material_suggestions.py`, `shared_brand`, requires the first distinctive word to match. The manufacturer prefixes therefore prevent these candidates.

**Recommendation.** Add a conservative suggestion-only rule for distinctive product phrases after a manufacturer prefix. Keep generic-token exclusions and never auto-link. Add the two positive cases and a false-pair negative case. The gap affects convenience and candidate recall; it does not compromise the unresolved status or establish a product identity error.

## R6-04 — Qualify the index's ordering and location wording

**Observed; low, index polish and evidence qualification.** The section sequences are useful: CCOF's G-series and OTCO's C-series run in numeric order; shared row references retain their order relative to the earlier supplied register. But run 6 does not include its current register/inventory, so exact current-register completeness and ordering cannot be independently certified from this bundle.

Two visible qualifications matter:

1. The WSDA index places the umbrella **Crop Producer Organic System Plan / Header** after section C on p3, between C and D. Put the form header before A. This is consistent with sorting equal document IDs by label rather than explicit section rank.
2. OTCO's index places OFPP immediately after O1. The current official blank-forms webpage lists OFPP after the crop-series forms. An older recorded inventory may intentionally use another source order, but “the agent's published order” is too unqualified. Identify the source/edition being followed, or say “Trazo's registered form order.”

Also, change **“Form located in”** to **“Related packet document”** when the record merely points to a packet document whose text does not name the form. Example: `R3/wsda/06-question-index.pdf`, p28, Renewal Fee Form, names frozen 02 as a form location while immediately admitting it does not name that form. The actual row-level heading references are accurate; the introductory label overstates what the lookup established.

Primary ordering sources checked on 2026-10-03:

- Oregon Tilth: https://tilth.org/help-center/blank-forms-all/ (Crop OSP Forms & Documents).
- WSDA: https://agr.wa.gov/departments/organic/forms-and-applications (Crop Producer sections).
- CCOF: https://www.ccof.org/ccof-osp-forms/.

These checks concern navigation order only. They do not reopen the prior form-requirements audit.

## Run-5 regression result

**Observed: no regression found in the checked outputs.**

- All 48 as-seeded parcel PDFs retain the unknown certificate/no-lapse requirement wording and the correct unresolved/fallback summaries. Routed parcel text remains unchanged apart from generation dates.
- All 10 active packets, including the three decided fixtures, retain revision 1's **2026-10-01** and revision 2's **2026-10-02** replacement dates.
- Frozen revisions 2 and 3 are byte-identical to run 5. Every active 02 matches frozen revision 3. Their SHA-256 values remain `e20e05678556cc1e3c22a802defd7442ed2a19daa21a125a91359f70d92761b7` and `4cd62bbfb9367fd8287c9e7fb56abfb9cc777802935abff96b6aea5e79dbe3bb`.
- Both supplied freeze logs reconcile stage 1 with stage 3; the section edit starts at stage 2. Independently recomputed all four section digests and six signed-payload digests, and confirmed the recorded 409 responses.
- The logs identify commit **`8fb1ce449e1845735d4aa8bf6f633f564dea0fd9`**, not the manifest's `3998a7f…`. Their internal evidence passes, but they are not proof of a freeze-command run at the final bundle commit. Preserve that distinction.
- OTCO's written-petition scope and WSDA's AGR 2521 scope remain intact on 02s, with no cross-agent fee-form leakage. Covers, coverage pages and notifications retain their prior content after generation-date normalization.
- Other PDF differences are fresh-seed UUIDs, the rolling window advancing one day, and headings/questions moving with their answers in G4.0, G5.0 and G6.0. These layout changes support the index and are not content regressions.

## Closure recommendation

**T18:** accept the demonstrated seeded/decided identity behavior, retention of approval warnings, and operator-sourced restriction disclosure. Keep historical-classification export verification open under R6-03. Treat R6-02 as a small suggestion-quality improvement.

**T24:** accept explicit page references, filed-document lookup and fallback behavior. Close the remaining rendering/disclosure portion after R6-01 and the small R6-04 index corrections or qualifications.

A focused follow-up needs only the affected index pages, the suggestion panel, and an actual classification export with event-level provenance. Keep all known unrelated limits unchanged. No new broad audit round is warranted by these findings.
