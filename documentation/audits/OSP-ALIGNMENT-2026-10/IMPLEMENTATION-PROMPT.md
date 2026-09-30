# Claude Code implementation prompt — October 2026

Use this with `Trazo-OSP-Alignment-Audit-2026-10.md`, the supplied conformance-register ZIP and five Calapooia Bend OSP v4 packets. The packets were reported as generated from commit `4959284` against a local demo copy, not the live database.

Start in **Plan mode**. Inspect the repository and produce a concrete, bounded implementation plan with affected files, data changes, acceptance fixtures and migration risks. Then implement phase by phase in normal editing mode after I approve that plan. Do not spend another cycle rewriting broad product strategy. Use the strongest coding model available in my Claude Code account with high reasoning effort for the mapping/data-state work; this prompt does not assume a particular current model name or CLI setting.

## Prompt to paste

You are working on Trazo’s existing codebase. Read the attached October OSP audit before proposing changes. Your goal is to make exports honest, question-complete within their declared scope, and practical for a crop certifier to review. You are not certifying an operation or promising that an agent accepts a format.

Read repository instructions and inspect the relevant implementation before editing. Record the current commit and identify differences from audited commit 4959284. Treat audit observations as evidence about the supplied fixture, not proof that a feature is universally absent. Verify each affected path in code; report disagreements with precise evidence. Do not “fix” fictional farm answers to make tests pass.

The audit’s OTCO table contains **unverified builder claims**, not independently approved mappings. Obtain current official original forms before claiming OTCO conformance. If unavailable, mark that verification blocked and proceed with supported CCOF/WSDA fixes and universal export honesty. Never use the register as both the implementation and the independent oracle.

Constraints:

- Preserve existing records, agent identifiers, snapshots, attachments, specimen labels and explicit no-use/N/A attestations. Use reversible migrations where possible.
- Work on local/test fixtures. No production data changes, deployments, external messages, certifier submissions, subscription changes or season finalizations without my explicit instruction.
- Do not add a score, grade, “compliant,” “verified,” or agent-acceptance result derived from field presence or an ingredient lookup.
- Do not build support for every production system now. Unsupported applicable questions must be clearly disclosed and routed to the agent’s process.
- Do not contact certifiers or mention competitors in product copy.

### Phase 1 — eliminate silent gaps and misleading completion

Locate completion calculation, `04-coverage-and-scope`, module generation, parcel completion and packet manifests.

Separate at least these concepts in the existing architecture: source mapping verified; question applicable; answer provided; required evidence present; operator reviewed; exported; submitted/receipt recorded; agent decision recorded. Do not collapse them into one “complete” flag. A field with text is not automatically an adequate answer. A blank optional field is not a failure. A conditional skip needs its triggering answer, not an inferred crop stereotype.

For each official question, including subquestions and table columns, render one of: answer with precise location; justified N/A; unanswered action; unsupported scope with the official form and destination. Keep partial requirements visible. Coverage disclosure is not a substantive pass.

Replace “forms generated” where only a generic module is generated with precise language such as “answers cross-referenced to these forms.” Rename the generic certification-contract output to operation profile unless it truly renders the relevant executed agent agreement. Identify agreements, financial intake and signatures still required through the agent’s process; do not store payment-card data in the OSP.

Acceptance:

1. Remove WSDA record location: 2121-O5 appears unanswered and cannot be satisfied by a record-category checklist.
2. Leave CCOF G6.0 C2 equipment rows empty: the packet identifies the missing grid instead of claiming a complete Production form.
3. Leave G6.4 B1/B1b or WSDA L5 sanitation answers empty: produce-wash sanitizer text does not satisfy equipment cleaning/residue controls.
4. Remove required label artwork: G7/G6.1 and the coverage manifest identify the missing attachment. A document reference alone is not “attached.”
5. An explicit no-use answer skips only its dependent questions. Missing applicability stays unresolved. Unsupported applicable forms are conspicuous; optional blanks do not inflate warnings.
6. Demo markings remain on every generated PDF and workbook. Generating a packet cannot turn draft content into an executed agreement or submission.

### Phase 2 — correct the conformance register and agent navigation

Build an independent official-question inventory with source URL, retrieved date, revision, file hash, printed question reference, subquestion/grid column, optional/conditional status and source location. Preserve duplicate printed numbering with occurrence IDs; WSDA R has two 7a entries. Separate internal routing statements from official questions.

Review all existing “covered” claims for semantic equivalence, starting with:

- WSDA 2121-O5: record location, not record types.
- WSDA 2264 Q13: exact product and application date, not a yearly materials synopsis.
- WSDA 2196: full product identity and how use restrictions are met.
- CCOF G6.1 C1: ownership during off-farm handling; route certificates/finished-product questions accordingly.
- CCOF Contract D2: direct and indirect export markets.
- CCOF G8 A1: all applicable records and retention/access, not only ten confirmed categories.
- CCOF Parcel B: agent-issued transitional status, not calculated eligibility.
- CCOF G6.4 B1 and WSDA L5 family: capability to collect is distinct from a populated answer in this export.

Keep canonical internal IDs. Produce an agent-specific index in official order with exact PDF/module/page or workbook/sheet/row locations. The same farm’s answers may remain the same; renaming a heading alone is not question-level adaptation. Preserve the actual certificate issuer separately from a temporary export destination; changing an agent must not rewrite certification history or persist a preview selection.

Acceptance:

1. Every numbered question/subquestion and grid in the verified CCOF/WSDA source inventory is accounted for exactly once or by an explicit shared-answer reference.
2. In particular, WSDA 2121-F has an answer or disclosed unresolved/excluded status for every question, with optional detail handled correctly.
3. Tests use an independently reviewed source inventory, not a second transformation of the same YAML.
4. A source revision change marks the mapping for review; `register_status: complete` never makes a packet complete.
5. CCOF/OTCO/WSDA indices use the selected agent’s question order. A reviewer can find each answer without guessing which G-number contains it.
6. OTCO remains “source verification pending” until current originals, including C1 and the Update form, are independently checked. No green pass from unverified rows.

### Phase 3 — make annual renewal and notifications distinct

Inspect the annual-update model and exports. The audited packet’s `02` correctly warns that no annual update exists for v4; that is not proof the feature is absent. Build a completed fixture to test the actual flow.

Represent the renewal year, prior submitted baseline, current submitted snapshot, last-year deviations/changes, future additions/deletions, application-information changes, unchanged sections, operator confirmation and agent-specific filing tasks. Keep notice recorded, sent, received, approved and rejected separate. A February notice is not a June application event. Do not require a new annual filing for every draft revision or erase a legitimate earlier filing when a draft is created.

Agent-specific tasks:

- CCOF: annual renewal agreement/OSP accuracy confirmation, applicable Crop Update NOPB88, payment handled by the agent, and changed attachments.
- OTCO: original Update Application & Agreement, assigned cycle and sales period, signature/payment tasks after source verification.
- WSDA: AGR 2516 site number/name and crop/variety/acreage changes, removed-area map where applicable, plus annual application and AGR 2521 fee tasks. Alternative records must contain all required information; do not force a visual facsimile when the source allows alternatives.

Acceptance:

1. Fixture with a new parcel, changed crop area, new input, unchanged module and future deletion prints each in the correct year/category and links its source.
2. Fixture with no changes prints an explicit operator-confirmed no-change result.
3. A missing annual filing produces a warning and outstanding task; coverage never claims a completed 2516/Update form from that warning page.
4. A submitted renewal retains its contents after later activity edits; the later draft clearly states its own source dates and status.
5. Packet generation, user-recorded sending and certifier acknowledgment are visibly different states. A payment reminder is not a receipt.

### Phase 4 — materials, parcels, evidence and sample traces

Resolve product identity using the actual formulation/manufacturer/registration or listing identifiers and use context. Keep a planned input list and actual-use list separate, with unresolved reconciliation visible. Do not alias Neptune 2-3-1 to 2-4-1, or Tsunami to SaniDate, without evidence and operator review. National List ingredient classification must not equal product approval or compliant use. Preserve historical approval/listing evidence for the application date.

For parcels, distinguish no prohibited use attested from no events recorded. Track history period, knowledge basis, manager, signature/confirmation and evidence. Handle existing certified sites, newly added sites and prior management with their proper branches. Do not automatically re-request new-site declarations annually. Missing address/map/history evidence must remain visible even if all narrative prompts were answered.

Export a manifest for required evidence with embedded, accessible link, separately held/location, missing or N/A status. Use stable attachment versions and identify inaccessible/replaced evidence. Define a minimal inspector bundle linking a selected sale or actual application to source records. Do not turn absence from an OSP packet into a claim of absence from the database.

Acceptance:

1. Input restriction compliance prints for WSDA 2196; exact product/use can be traced to its supporting label/approval basis, or the missing evidence is explicit.
2. A parcel with no logged applications and no attested history never receives an unqualified eligibility/certification label.
3. An unresolved handler/storage name such as WVF Salem IQF is flagged for review; do not silently merge it into another business.
4. The River Block fixture retains 114,240 lb harvested and 110,702 lb sold. Its 3,538 lb difference is not automatically classified as verified shrink. Allocations, losses and closing stock cite actual records or remain unresolved.
5. A selected actual application exposes event date, product, rate/units, treated area, parcel/buffer, performer and linked source documents. A planned notice cannot satisfy that test.
6. Conflicting farm-wide organic-only prose and buffer conventional sales trigger operator review, without overwriting the operator’s text.

### Phase 5 — fallback agents, crew notes and public copy

OCI/MOSA and other unmapped agents: describe a general preparation/records packet. Remove “only numbering differs” and CCOF-specific filing instructions. Link to the selected agent’s process without claiming acceptance. Keep supported crop scope explicit.

WhatsApp: preserve sender, performer/observer, record enterer, reviewer, source message ID, original text/transcript, proposed values, corrections, occurrence time and entry/review times. Match signature/initial requirements to record type; supervisor confirmation alone cannot be assumed to satisfy FSMA performer/observer requirements. Do not claim that NOP requires the farmer personally to write every record, or that every chemical use always needs a licensed applicator. Route unsupported pesticide notes to the proper workflow without losing the source note. Define retained authoritative records before deleting source audio.

Acceptance cases: English/Spanish negation; chemical mention; missing date/quantity; duplicate delivery; unregistered/cross-company number; correction; mandatory playback gate; 375px source-and-proposal review. Missing values remain missing. No record is created before valid confirmation. Record provenance survives export. Use local mocks/test numbers; no unsolicited replies to real people.

Public copy: align homepage, methodology, consumer descriptions and badges with actual implemented behavior. Remove residual score language, reconcile carbon audience/boundary statements, use current 205.103(b)(4) for five-year retention, and distinguish database matches from verified operation/event claims. The audit rejected a stale search copy of the old methodology; do not rebuild a retired feature based on that stale source. Test current anonymous QR output separately.

### Verification and completion

Generate the five fixture packets after the changes. Inspect rendered PDFs and workbook contents, not only serializer snapshots. The audit’s Poppler spacing issue did not reproduce in MuPDF; investigate only if reproducible in supported readers. Keep workbook omission from a merged PDF explicitly disclosed.

Run focused regression tests for affected mappings, conditional routing, states, attachment versions and cross-tenant access to changed endpoints. Do not treat the previous security-fix claim as independently verified. Test date-only behavior in the operation’s timezone where touched. Preserve existing controls; no broad unrelated refactor.

For each phase, report: changed behavior, affected files/migrations, observable tests performed, generated examples and remaining unsupported scope. Finish with a finding-by-finding disposition for T15–T30: fixed with evidence, partly fixed, blocked on source/evidence, or disagreed with cited implementation evidence. Never mark a blocked or untested item passed.

A successful result is a reviewer who can see every applicable answer and every remaining task, and a grower who does not have to discover missing requirements after submitting the packet. Certifier acceptance remains an external pilot gate, not a unit-test result.
