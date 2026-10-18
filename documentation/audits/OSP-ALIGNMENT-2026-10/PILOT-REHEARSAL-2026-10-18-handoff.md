# Certifier handoff rehearsal (2026-10-18)

Script: `CERTIFIER-HANDOFF-REHEARSAL-SCRIPT.md`. Farm: company 17 / farm 20, "ASTRA Test Pilot (not a farm)",
fictional data marked ASTRA TEST. Backend deployed at `403c97d` (back #174, per-link hourly ceilings); app #141
(checklist off the farm profile) merged 2026-10-18 14:26 UTC.

Two runs:
- **Run A (Astra, grower).** Created link "Rehearsal 2026-10" and revoked it in the same session. The recipient part
  was not run: the browser had no separate, cookie-free profile, and a second tab would not establish isolation.
- **Run B (recipient side, scripted).** Oscar created link "Rehearsal 2026-10b" as the grower and revoked it on
  request. The recipient was a fresh Chromium profile with no cookies, driven by Playwright against production
  (app.trazo.io, api.trazo.io). The token is not recorded here.

Decisions taken before the runs (Astra, then Oscar): disposable link GO; one permanent dossier document in farm
20's exports folder GO. The inert-throttle exception was not needed: back #174 was deployed.

Columns: **Designed** = implemented as designed? **Finish** = could the grower or recipient finish the task?
**Evidence** = live, file (read in the downloaded PDF) or not tested.

| Step | Designed | Finish | Evidence | Result |
|---|---|---|---|---|
| 1 What is shared | No | Partly | live (A) | The Getting Started panel covered the link card; Astra dismissed it. Run A was before app #141 merged, so the panel's behaviour after #141 is not yet observed. The card says (ES): a link to the operation's audit dossier, no account needed, always current, revocable. It does not say the dossier includes prices, private notes, applicator or worker names, unpublished seasons, or the login emails of the people who edited records (see step 4). |
| 2 Create | Yes | Yes | live (A, B) | Period Jan 1 to Dec 31, 2026; expiry Jan 16, 2027 (90 days). No blockers. |
| 3 Recipient opens | Yes | Yes | live (B) | Profile started with 0 cookies; no request to the review routes carried a cookie or an Authorization header. Page shows "ORGANIC AUDIT DOSSIER", Test Block, Chelan, WA, the covered period, "These are documentation checks on the records in Trazo, not a compliance decision", per-finding badges ("Missing", "For review") with "In the dossier: …" hints, and "This link expires Jan 16, 2027". The page does not say who prepared the records (operator or grower). |
| 4 Surround correction | Yes | Yes | file (B) | Download through the page's own button: 202 on the status poll, then the PDF in 9 s (71 KB, 21 pages, built for this request). Page 9: Surround 300.00 lbs (45.00 lbs/acre) with "[REVIEW] corrected: rate x area = 270 lbs, not the amount recorded". Page 21, Documented Corrections: application_rate originally 50.000, corrected to 45, reason given, by John Doe, 2026-10-17; plus the lot-header unit correction (units to bins) by the operator. The disagreement is flagged, nothing auto-changed. Found by text search; the landing page gave no pointer to the corrections section. |
| 5 Entrust evidence | Yes | Partly | file (B) | Record fields: supplier, invoice ASTRA-INV-2605-01, purchase 2026-05-08, lot ASTRA-ENT-26-001, 128.00 oz "(fluid or weight not stated)", application 36.00 oz (6.00 fl oz/acre). Page 5 index: "ASTRA TEST invoice ASTRA-INV-2605-01 (Entrust SC, May 15 application)", linked to the SEASON "Honeycrisp 2026 (ASTRA TEST)", not to the application. The file itself cannot be opened: "This is an index, not the documents … produced on request at inspection". |
| 6 Gaps and drafts | Yes | Partly | file (B) | Drafts are unmistakable: "DRAFT — NOT FOR CERTIFIER SUBMISSION"; OSP v1 "Draft (not yet submitted)"; "Revision 1 of the 2027 annual update is a draft: it has not been filed"; signature "Not signed in Trazo"; the 2027 filing "does not reaffirm the OSP". Gaps listed with [REVIEW]: field map, buffer record, buffer disposition documentation, water test, planting stock, prior load on the transport unit, 36-month history. Two readings a recipient could get wrong, see findings H-1 and H-2. |
| 7 Downloads | Yes | Partly | live (B) | Only the PDF is downloadable. No source documents, packet, CSV or PUR. Enough to verify the correction and the gaps, not to see the invoice or the fraud prevention plan file. Grower-side activity log: not checked, because a revoked link disappears from the card (finding H-5). Whether the exports folder gained one dossier: not checked. |
| 8 Isolation (UI) | Yes | Yes | live (B) | One character of the token changed: "This link is no longer available". Raw API, cross-account and viewer-role checks: not tested (separate technical test). |
| 9 Revocation | Yes (server); No (grower card) | Yes (recipient) / Partly (grower) | live (A, B) | After revoke: reload shows "This link is no longer available" (metadata and readiness 404); the Download button is gone; re-issuing the ORIGINAL download request (`…/dossier/?job=<id>`) from the same profile returns 404 JSON, no PDF. A copy already saved stays with the recipient; that is outside the link's control. On the grower's card the revoked link disappears with its access log (H-5). |
| 10 Expiry | n/a | n/a | not tested | Not tested live; covered by `test_expired_link_is_404_not_410`. |

The per-link hourly ceiling (back #174) was not exercised: the run stayed well below it. Its 429 page is untested
live.

## Findings

- **H-1 (high). The producer attestation names the operator.** Dossier page 3, "Producer Attestation (7 CFR
  205.401 / 205.400(a))": "Producer / Operator: Oscar Munoz (Trazo setup)". That is Trazo's setup login, not the
  grower. In an assisted setup the attestation block tells a certifier the wrong person stands behind the records
  (§ 205.201(a) makes the producer the author). The SOE section on the same dossier names the grower ("John Doe")
  as responsible for the fraud prevention plan, so the two disagree.
- **H-2. One page, two answers on inputs.** The documentation snapshot (page 8) says "No production or handling
  inputs are on file, so (a)(2) cannot be evaluated", two rows above "3/3 inputs have supplier on file" and "3/3
  chemical records have product, amount, area". The first means the OSP's inputs list is empty; it reads as if no
  inputs were applied. Separately, the recipient sees "1 input record(s) not confirmed against the plan's inputs
  list" (Surround only), while the grower's readiness panel says "3 registered products are not in your materials
  list". Same farm, two counts.
- **H-3. Source documents are listed, not reachable.** The invoice is indexed but cannot be opened, and the index
  links it to the season, not the application. Implemented as designed, and it does not let an inspector verify
  the invoice without asking the grower. Decision pending (attach to dossier / token-scoped download / keep the
  index and say so to the grower).
- **H-4. Login emails reach the recipient.** Record Change History prints actor emails (`oscar+astraop@…`,
  `oscar+astrapilot@…`). The grower card does not disclose this. Part of the step 1 disclosure gap.
- **H-5. A revoked or expired link vanishes from the grower's card**, and with it the record of whether the
  certifier opened it (`CertifierLinkCard.tsx` lists `is_active` links only). The backend keeps the rows. The card's
  own header promises the grower can see whether the certifier opened the link.
- **H-6 (for review, not a defect).** Harvest yield basis prints "Scale-Verified (weigh ticket)" with no weigh ticket
  in the document index; the cleanout note says "Shared airblast sprayer" while the cleaning log says shared with
  conventional "No" and the snapshot marks contamination prevention DOCUMENTED. Both are the operator's entries;
  an inspector will ask.
- **H-7 (disclosed, production data).** "Not confirmed current: National List (eCFR) — last attempt 2026-09-07 error,
  no successful sync on record."

Outside scope, noticed (Astra, run A), not investigated: the fraud prevention plan card shows the signed URL as its
file name (known, PR-17-b); the dashboard shows "0" finished seasons ("Aún sin temporada finalizada") although farm
20 has one finished season.

## Milestone status

The grower can share a disposable dossier and lose nothing on revocation server-side; the recipient can open it
anonymously, find the Surround correction and the open discrepancy, see that every draft is a draft, and loses
access, including to the original download request, when the link is revoked. Not met: the grower cannot tell in
advance what the dossier exposes (step 1, H-4), the recipient cannot open the Entrust invoice (H-3), the
attestation names the wrong person (H-1), and the grower loses the access history on revoke (H-5). The milestone
stays open on those four.

## Not tested
Expiry live; the 429 ceiling live; raw API, cross-account and viewer-role isolation; the checklist on the farm
profile after app #141; whether the exports folder gained exactly one dossier; prices and private-note values in
the dossier (none are recorded on farm 20, so their disclosure could not be observed).
