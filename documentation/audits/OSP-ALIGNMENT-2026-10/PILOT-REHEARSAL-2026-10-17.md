# Pilot rehearsal: assisted setup of a fictional WSDA orchard (2026-10-17)

Goal: exercise one complete pilot journey on production, in the disposable company "ASTRA Test Pilot (not a farm)"
(company 17, farm 20). All data is fictional and marked ASTRA TEST. No signing, filing, external sharing,
publishing or billing.

## Roles and logins
- Operator (setup): oscar@trazo.io, switched to "ASTRA Test Pilot (not a farm)". Done by Claude, timed.
- Grower (review): oscar+astrapilot@trazo.io. Done by Astra.

## Fictional farm (what the operator enters, from a "paper binder")
- Farm "Test Block", moved to WA (Chelan County), farming method organic. Certifier WSDA (fictional certificate,
  self-reported; the USDA database check is expected not to match).
- Parcels: North Block, 6.0 ac, Honeycrisp apples. South Block, 4.5 ac, Gala apples.
- Season: "Honeycrisp 2026 (ASTRA TEST)" on North Block, Mar 1 to Oct 10, 2026, then finished (not published).
- Records on North Block (each typed from the binder, performed by "Crew lead (fictional)"):
  1. Mar 5 soil test (pH, organic matter) from a lab report.
  2. Mar 20 dormant pruning.
  3. Apr 10 fertilizer: Down To Earth Feather Meal 12-0-0, 300 lb/ac.
  4. Apr 25 pest control: Surround WP (kaolin), sunburn and pear psylla.
  5. May 15 pest control: Entrust SC (spinosad), codling moth, with a supplier invoice attached (fictional PDF).
  6. Jun 1 irrigation.
  7. Jun 10 pest scouting: codling moth traps, counts below threshold.
  8. Jul 1 hand thinning.
  9. Jul 20 equipment cleanout of the shared sprayer (certifier-only record).
  10. Aug 5 row-middle mowing.
  11. Sep 15 harvest: lot ASTRA-HC-26-01, 40 bins.
  12. Sep 16 transport to the packer.
  13. Oct 1 sale of lot ASTRA-HC-26-01 to "Fictional Packing Co." (sales record).

## Checks per step (pass / fail / note)
1. Pilot access (Astra, grower login): packet, workbooks and audit export are available without checkout or an
   upgrade prompt. Do not generate anything yet.
2. Setup work (operator): every record shows the operator as the person who entered it (not the grower); the
   attached invoice is kept with its record; nothing is invented (no date or value the operator did not enter).
   Operator notes time per record and any friction.
3. Grower review (Astra): the grower can find what the operator entered, tell who entered it, correct one value
   (change the Surround WP rate) and see the correction recorded; missing evidence (no OSP, no fraud prevention
   plan, unanswered modules) reads as missing, not as completed.
4. Renewal preparation (Astra): open the change-summary draft, acreage workbooks and the renewal packet; confirm
   they draw on these records and clearly list what still needs the grower's answers, review and signature.
   Generating files these as documents in company 17 (permanent): allowed for this test, nothing is sent.
5. Inspection trace (Astra): in the audit export, trace the May 15 Entrust SC application to its invoice and the
   Sep 15 harvest lot ASTRA-HC-26-01 to the Oct 1 sale.

## Out of scope
Signing, filing, review links, publishing, billing, emails. Invitation page language and production rate limiting
are known and tracked separately.

## Results
(filled in by Claude for step 2 and by Astra for steps 1, 3, 4, 5)

### Step 2: setup work (operator, done by Claude on 2026-10-17, 13:05 to 13:23)
Login oscar+astraop@trazo.io ("Oscar Munoz (Trazo setup)"), created with `add_pilot_operator` after the one-company fix (back #165).
Entered: farm moved to WA (Chelan, organic, orchard); North Block (6 ac) and South Block (4.5 ac); season "Honeycrisp 2026 (ASTRA TEST)" on North Block; 12 records (soil test, pruning, feather meal, Surround WP, Entrust SC, irrigation, codling moth trap check, hand thinning, sprayer cleanout, mowing, harvest lot ASTRA-HC-26-01 40 bins, transport); the Entrust invoice PDF filed under Activity Attachments and linked to the season; season finished on Oct 10 with "publish buyer page" UNCHECKED (published: false); sale of lot ASTRA-HC-26-01 to Fictional Packing Co. on Oct 1 with invoice, bill of lading and carrier.
The 18 minutes were scripted browser time, not a measure of a person typing from a binder.

Pass:
- Every record shows "Oscar Munoz (Trazo setup)" as the author, never the grower.
- The Entrust record carries supplier, invoice number, lot, quantity bought and manufacturer; on the public card the invoice reference in the field note reads "[reference withheld]".
- Finishing offers an explicit "publish the buyer page" opt-out, and it held.
- The sale links to the harvest lot and accepts a source document.

Findings (for fixes, with reproduction):
1. BLOCKER, fixed during the rehearsal: the operator could not reach the pilot company at all (oscar@ belonged to two companies; the app loads only the first). Fixed by back #165 (one operator login per pilot, add/remove operator commands).
2. Pest form: after choosing Trap Monitoring the required event name is blank, and Continue does nothing: no message, no highlighted field. Repro: Log activity > Pest & scouting > step 2 > type Trap Monitoring > Continue.
3. Finish form: production amount is prefilled from the harvest (40) but the unit defaults to kg, and "bins" is not in the unit list. Saving as offered turns 40 bins into 40 kg. Repro: harvest recorded in bins > Finish production.
4. Source documents: an event record cannot take a document (photos only), and an uploaded document links to the season, not to the specific application. The sale record does accept documents.
5. Documents list shows the operator's upload as source "Farmer upload".
6. Event detail carbon block says "Estimated direct emissions" (methodology wording rule: own emissions plus purchased-input manufacturing).
7. The operator sees the grower's checklist text "Send your existing records to Oscar".
8. Copy: empty parcels list "build transparency for consumers"; farm description help "what consumers see ... tell your story"; farm form "automated USDA Organic verification"; post-save toast "what buyers can see" on certifier-side records.
9. Farm header kept the old state (OR) until a reload after editing.

### Steps 1, 3, 4, 5 (Astra as grower, 2026-10-17)
1. Pilot access: PASS (packet and audit export offered without checkout or upgrade prompt).
3. Grower correction: PASS in the export (Documented Corrections: 50.000 -> 45, reason, date, John Doe; audit log names oscar+astrapilot as corrector and oscar+astraop as original author). App display gap: the record's detail view shows 45 with no history.
4. Renewal preparation: PARTLY. Packet and four workbooks draw on the records and disclose what is missing (acreage 10.5 ac; materials "Identity not confirmed"; supplier rows; draft cover; no annual update; unfinished modules; unsigned). Grower setup still to do: select WSDA, responsible person, applications and evidence, annual update. No invented "no changes" answers.
5. Inspection trace: PARTLY. Entrust -> invoice ASTRA-INV-2605-01 / May 8 / batch ASTRA-ENT-26-001 agrees. Harvest -> sale shares the lot but does not reconcile (40 bins vs 40 units), sale documents are typed text only, buffer disposition conflicts with the organic sale.
Normal (strict) export not yet demonstrated: it refuses without a fraud prevention plan (422 audit_pdf_ofpp_missing); the preview was used.

Additional findings from Astra: fl oz printed as oz (36 oz beside 6 fl oz/ac; invoice 128 fl oz vs export 128 oz); audit-trail exhibit lists 40 bins then says no harvest exists; buffer "sold conventional" with no quantity read as all 40 bins; preview prints "NON-COMPLIANT DOSSIER" / "NON-CONFORMANCE"; draft OSP pages say "as submitted"; G2.0 split-operation answer disagrees with the audit's "wholly organic"; a rate-only amendment leaves amount/area/rate inconsistent with no review prompt.

### Fix batch and final operator leg (2026-10-17)
Merged and deployed: back #167, #168, #169 (8fead0b); app #129, #133, #135, #136.
Operator actions in company 17 (each through the app's own correction path, reasons on file):
- Lot header unit corrected units -> bins (correction recorded, by "(Trazo setup)").
- Sale voided (units) and re-recorded as 40 bins; a second re-record was voided because it was saved without its lot link (my script's mistake); the active sale is 40 bins linked to lot ASTRA-HC-26-01.
- Fictional fraud prevention plan uploaded (responsible person and plan date set).
Normal (strict) audit export now generates (20 pages): no compliance verdict words; Harvest Yield 40.00 bins = Quantity Sold 40.00 bins; voided sales listed with reasons; buffer row "Not recorded" (no longer claims the lot); split operation "Not answered"; rate correction flagged (45 x 6 = 270 vs 300 recorded, nothing auto-changed).
Residual: the Entrust application row (recorded before the fix) still prints "36.00 oz" without the fluid/weight qualifier; only the purchase totals carry the note. New small findings: the fraud prevention plan card shows the signed download URL as the file name; the lot-header unit correction is free text, not a unit list.
Pending: Astra as grower selects WSDA and starts the annual update with real answers; re-checks the normal export and the correction display.

### Final leg (2026-10-17, evening)
Astra (grower): step 3 PASS (Corrections block on the record: 50.000 -> 45, reason, John Doe, Oct 17); step 5 PASS (normal export: 40 bins harvested = 40 bins sold, balance 0; voided sales excluded; buffer "Not recorded"; split "Not answered"; corrections and the 270 vs 300 flag); step 4 PARTLY (WSDA selected and a 2027 draft saved with open answers; packet not yet re-verified).
New defect found: once the annual-update draft existed the renewal packet failed (500) because sales without amounts made the subtotal None. Fixed in back #170 (no subtotal while any sale lacks its amount; same rule as the audit export) and deployed (adbcf13). "Plan v1 reaffirmed" / "reaffirmed without a new version" / "No changes - OSP reaffirmed" replaced by "continues v1" / "Not stated on this filing" (back #170, app #137).
Fresh packet renewal-packet-v3-WSDA.zip generated: names WSDA, carries the 2027 draft, no subtotal, no "reaffirmed".
Open: setup checklist overlaps the annual update's Save button.

### Step 4 closed (Astra, 2026-10-17)
PASS on renewal-packet-v3-WSDA.zip: names WSDA and routes to AGR 2516 / AGR 2521; carries the 2027 draft (revision 1, draft, not yet filed; identical copy under annual-update/); unsupported answers left open ("None stated", "Not stated on this filing"); 04-coverage-and-scope lists unanswered questions, missing attachments and unfinished modules; blank signature fields and "draft, not signed"; no "reaffirmed"; the unpriced sale gives no subtotal.
Outcome: the assisted-setup workflow produces an honest, incomplete draft for grower review. The specimen is not ready for submission, by design.
Still open: setup checklist overlaps the annual update's Save button; previously disclosed evidence gaps (external documents for the sale, buffer disposition evidence).
