# Run 3 corrective plan (R3-01 to R3-09)

Source: `RUN3-REVIEW.md` (Astra, 2026-10-02, against the handoff built at back `75226a4`, app
`4c86274`). Approved by Oscar on 2026-10-02 with five requirements, restated here because each one
is a test:

1. The applicability assessment is evaluated separately for each parcel and each form, with the
   export's selected agent and plan version. Unknown applicability stays unresolved. "Currently
   certified" does not by itself mean existing acreage under the selected agent.
2. Revision 2's frozen bytes do not change through any template or specimen change. Revision 3
   describes its own corrections, explicitly.
3. The Grandevo acknowledgment wording is reconciled against the fixture's evidence. No
   acknowledgment and no future farming intention is invented.
4. The ledger is updated in the first slice and separates three things: what the packets show,
   what code and tests verify, and what stays untested.
5. OCI and MOSA are both in the regression tests, even though the review bundle carries one
   fallback agent.

Nothing in T29 or private storage changes here; Astra kept both out of scope.

## Slice 1: one applicability decision (R3-04, R3-05, R3-06)

Cause of R3-05, read in code: the parcel summary line called `parcel_application_status(parcel)`,
which resolved the agent through `assess_for_wizard`, i.e. the newest plan in the database. The
detail page used the packet's plan. Two inputs, two answers. R3-04 is the same class: page 04
evaluated parcel-form rows with no route at all.

* `certified_parcel_branch.assess_for_plan(parcel, osp)` is the one entry point for a packet:
  the plan's agent, the plan's version, this parcel. The summary line, the parcel detail, the
  land-history embed, the attachment manifest and page 04 all call it with the packet's plan.
  The wizard keeps `assess_for_wizard` and names the plan version it assessed for.
* Whether the parcel is already on the selected agent's certification is decided from what the
  operator reported, in two parts, and never from "currently certified" alone:
  - the operation named on the certificate is this operation (blank, or one of its names), and
  - the certifying agent named for the parcel is the selected agent (exact name match through
    `certifying_agents.agent_for_name`, never fuzzy).
  If the agent named is another known agent, the parcel is new to the selected agent. If no agent
  is named, or the name is one Trazo does not recognise, the route is **unresolved**: nothing is
  treated as not asked, the accounting is shown in full, and a review item names the reason.
* Routes, against each agent's own source:
  - CCOF: already on this operation's CCOF certification -> `ccof_crop_update` (NOPB49 p1 sends
    existing client-profile crops to the Crop Update, NOPB88; NOPB49 is not filed for it). New to
    CCOF and currently certified -> `ccof_g` (F2 Yes, skip to G).
  - WSDA: existing site -> `wsda_existing_site` (AGR 2516). From another WSDA-certified operation
    -> `wsda_transfer` (2264 6a). Certified by another agent -> `wsda_new_site` (2264 filed, land
    history asked; what another agent's certificate satisfies is WSDA's determination).
  - OTCO: existing acreage -> `otco_existing_site` (FACT-04). From another operation ->
    `otco_transfer`. Certified by another agent on this operation -> `otco_new_acreage` (C2
    filed; 2.4 accepts a certificate with continuity evidence in place of the history table).
  - Any other agent (OCI, MOSA, none): `agent_form`, which now says Trazo does not assess that
    agent's land-history requirements and that no agent-specific exemption is determined. The
    36-month accounting prints in full. The sentence claiming the form "does not ask for the
    36-month accounting" is gone from every shared paragraph.
* `land_history_asked` becomes three-valued: asked, not asked on this route, undetermined. Only
  "not asked on this route" replaces the accounting with the not-asked sentence.
* Page 04 evaluates a parcel-form row per parcel through the same assessment: applicable and
  unanswered stays "still open"; a row the parcel's route does not file is listed apart as "not
  asked on this parcel's route" with the reason; an undetermined route is "unresolved" with the
  reason. A form no parcel files on its route is listed as such, never as answered.
* The summary counts every asked item that is missing, with readable labels (no
  `certified_certificate`).
* Tests: every route (existing, new, transfer, unresolved, fallback) for CCOF, WSDA, OTCO, OCI and
  MOSA; active and draft plans; an agent chosen on the plan in memory and not saved; summary,
  detail, embed and page 04 asserted to agree. Each mutation-checked.

## Slice 2: renewal meaning (R3-02, R3-03, part of R3-08)

* OTCO OSP Update Step 5-4 (operate per applicable standards and Oregon Tilth policies) is an
  agreement the operator gives on OTCO's form. Register row status and the 02s locator change
  together; the §205.400(f) line is no longer offered for it.
* OTCO Step 6 points at the 2025 sales subtotal that 02 actually prints and states its scope gap
  (products certified but not sold as organic, OTCO's own exclusion process).
* WSDA: the subtotal is labelled an unreconciled sales-record subtotal, not the AGR 2521 income
  figure; receipts timing, service income and completeness are named as the operator's
  reconciliation. No fee computation.
* 02s and the cover say "forms to file" / "renewal routing", never "filed", unless a filing with
  that agent is recorded.

## Slice 3: specimen and cover, history intact (R3-01, R3-07, R3-08)

* Revision 2 stays byte-identical; a guard compares its SHA-256 before and after every step.
* Revision 3 is a new signed corrective revision whose text lists each correction: the
  split/parallel answer reconciled with G6.0, the coming-year additions separated from changes
  already made (an explicit operator-confirmed "no planned change" where that is what the fixture
  supports; no invented intentions), and the Grandevo acknowledgment wording made to match the
  notification record the fixture holds.
* The buffer description stops calling the row both unharvested and harvested.
* The cover separates frozen filed documents, reconstructed legacy documents and documents made
  from live records, and counts a deletion only when one is reported ("None" is not one).

## Slice 4: evidence and review bundle (R3-09)

* A reproducible freeze test that writes the canonical payload, the hash method, the changed
  record ids, before and after values and the actual 409 response to a JSON file.
* A small bundle for run 4: CCOF, OTCO and WSDA active and draft, plus one fallback agent (OCI),
  each with cover, 02, 02s, page 04 and the parcel pages; both frozen hashes; the freeze test
  output. MOSA stays covered by the tests.
* Ledger: per finding, packet-observed, code/test-verified and untested, kept apart.

## Order

Backend first in each slice, app after, each PR CI-green with the review bot's comments read and
answered before merge.
