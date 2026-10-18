# Certifier handoff rehearsal: script (not run)

Written 2026-10-17 from code read at back `724ab5a`, app `4f1b3522`. Nothing here has been run. Creating the
disposable review link is authorized separately, at the start of the live session.

**Milestone.** The grower knowingly shares a disposable dossier. The recipient finds the Surround correction,
traces Entrust to the evidence that exists, recognises the unresolved gaps, and loses access when the link is
revoked.

## Decisions needed before the session (none taken here)
1. Create one disposable certifier link on company 17 / farm 20 ("ASTRA Test Pilot (not a farm)").
2. **Proposed, not accepted:** run with the review-link throttles inert. Production `CACHES` is DummyCache, so
   no DRF throttle counts (LEDGER, "Production rate limiting is inert"). The proposal covers one link, revoked
   in the same session. Sharing a real pilot's records is a separate decision.
3. Accept the side effect: a dossier build files a permanent document in farm 20's exports folder
   (`documents/services/export_jobs.py`). A build happens only when the records changed since the last filed
   dossier (`certifications/views.py`, `certifier_review_dossier`); a repeat download streams the filed copy.

## Roles
- Grower: oscar+astrapilot@trazo.io (Astra). Creates and revokes the link. If this account's role cannot
  create a link, record that as a result. Do not switch to the operator.
- Recipient: a separate browser profile, signed out, no cookies.
- Operator access is not part of this script.

## Preconditions: record them, do not manufacture them
Creation is refused (400 with `readiness` and `blockers`) without a fraud prevention plan, an OSP that is not
materially incomplete, and records. Farm 20 has a fictional fraud prevention plan and a draft OSP from the
2026-10-17 rehearsal. If creation is refused, copy the blockers into the results and stop.

## What the code says exists (claims to confirm, not results)
- One link covers one farm. Optional period: seasons overlapping it, published or not. Expiry defaults to 90
  days. Revoking is permanent. Opening the metadata, the findings and the dossier is logged.
- Grower UI: the certifier link card on `farm/:farmId/profile`. Inputs: label and period (current year, last
  12 months, all records). No expiry or certification-type choice. A one-sentence description and a readiness
  panel. Each link row shows expiry, last opened, an activity log, copy and revoke.
- Recipient page `/certifier-review/:token`: no login; the token is the credential. Findings per season
  ("Missing", "For review", "In the dossier: {section}"), a disclaimer, an expiry note, and "Download audit
  dossier (PDF)".
- The dossier carries the corrections, the voided sales, the OSP marked as a current draft, the annual update
  marked as a draft revision, unsigned attestations marked [REVIEW], a banner of open gaps, and a document
  INDEX only ("an index, not the documents", up to 60 rows). It includes private notes, supplier names,
  invoices, prices and applicator names. No carbon section.
- The PDF streams through the API; the recipient is never handed a storage URL. An unknown, expired or revoked
  token gets 404 on every route.
- Not reachable through the link: individual records, photos, document files, the renewal packet, CA PUR, CSV.

## How to report
Two answers per step:
- **Implemented as designed?** yes / no
- **Could the grower or recipient finish the task?** yes / no / partly

A step can be correct as implemented and still fail the task. That is a finding, not a "limitation".

## Steps
1. **Grower: what is shared, what stays private.** Sign in as the grower, open `farm/20/profile`. Copy the
   card's description and readiness panel verbatim. Before sharing, can the grower tell that prices, applicator
   names, private notes, unpublished seasons and worker names will be in the dossier? Write down what the
   grower expects to share; compare it with step 4. Note whether the Getting Started panel covers the card's
   buttons (seen locally at 1280 px wide on 2026-10-17; not yet seen in production).
2. **Grower: create.** One link, period "current year", label "Rehearsal 2026-10". Record the expiry shown
   (expected: about 90 days out). If refused, record the blockers and stop.
3. **Recipient: open.** In the signed-out profile, open the copied link. Record the header (operation,
   location, period), the findings, the disclaimer and the expiry note. Does the recipient know what they are
   looking at and who prepared it?
4. **Recipient: the Surround correction.** Download the dossier once and time it (the page may wait for a
   build first). Find the Apr 25 Surround WP application: original rate 50, corrected 45, reason, who
   corrected it, when; and the 300 lb recorded against 45 lb/ac x 6 ac (270) left for review. Record how long
   it took and how the recipient found it (page hint or PDF search).
5. **Recipient: Entrust source evidence.** Find the May 15 Entrust SC application and trace it to invoice
   ASTRA-INV-2605-01 (May 8, batch ASTRA-ENT-26-001): the invoice fields on the record and the document index
   row for the invoice PDF. Record whether the index row names the application or only the season. Can the
   recipient open the invoice itself? The code says no (index only). If so, report "implemented as designed:
   yes; recipient can finish: no". The Entrust invoice is not evidence for Surround; do not count it there.
6. **Recipient: gaps and drafts.** List every "Missing" and "For review" finding and match each to a dossier
   section. In the PDF confirm: the OSP is a current draft; the 2027 annual update is revision 1, a draft,
   continuing plan v1, with no "reaffirmed"; missing answers, review and signature are visible; unsigned
   attestations are marked [REVIEW]; the sale and buffer evidence gaps are disclosed. Could the recipient
   mistake any draft or unsigned item for a filed one?
7. **Downloads.** Record what the recipient can download (expected: the PDF only) and whether that was enough
   to finish steps 4 to 6. The grower checks the link's activity log and whether the exports folder gained a
   dossier.
8. **Isolation, through supported UI paths only.** (a) The recipient changes one character of the token in the
   address bar: expected "no longer available". (b) If the farm 22 account is available, confirm nothing of
   farm 20's links or dossier is reachable from its UI. Raw API calls, cross-account requests and viewer-role
   checks belong to a separately authorized technical test: mark them "not tested" here. Do not work around the
   `api.trazo.io` browser restriction.
9. **Revocation.** Before revoking, keep the recipient's tab open and keep the dossier's entry in the browser's
   download list. The grower revokes. Then, as the recipient:
   - reload the review page: expected "no longer available";
   - press Download again: expected refusal;
   - **retry the original download request** from the browser's download list (its retry or "download again"
     action re-requests the issued URL): record whether the server still serves the file. The code says 404,
     because that URL goes through the token route. If the browser cannot re-issue the request from its own
     UI, mark this check "not tested". Do not rebuild the URL by hand.
   Opening the PDF already saved on disk is a different thing. It says nothing about server access, and saved
   copies are outside the link's control; state that in the results. The grower's card should show the link
   as revoked with its earlier log entries kept.
10. **Expiry.** The UI cannot set a short expiry. Record "not tested live; covered in code by
    `test_expired_link_is_404_not_410`", unless the session separately authorizes an API-created link with a
    next-day expiry. No database edits in production.

## Output
`PILOT-REHEARSAL-2026-10-<day>-handoff.md` with both answers per step and the evidence kind (live, file,
code/test, not tested). Update the LEDGER's "Not tested" entries for the review link.

## Candidate changes (not built; decide from what the session shows)
- A grower-facing list of what the dossier exposes.
- Recipient access to the documents the index names, or a per-record view.
- An expiry choice in the UI; a notice to the grower when a link is opened.
- A per-link limit that works without Redis, or Redis after the scheduler triage.
- A link scoped to one season.
