# Trazo run 7: audit dossier review

Reviewed 3 October 2026. Evidence: `Trazo-Review-Handoff-2026-10-03-run7.zip`, attributed by its README to backend commit `95e52a6`. This is a review of the supplied specimen records, not a certification decision about a real operation.

## Verdict

**Useful inspection working papers, but not yet a dependable, self-contained dossier for completing these two trace-backs.** The underlying event lists and production totals reconcile across exports. Material problems remain in evidence availability, purchase aggregation, lot relationships, status wording, and the projection of newer OSP records into the dossier.

The most consequential problems are:

- The dossier says no change notification exists although the OSP packet supplies one, and conflates an active plan with approval.
- Purchase totals sum repeated purchase references carried on applications.
- A harvest-minus-sales difference is called an “uninvoiced remainder” without evidence that it is unsold product.
- Sanitizer output applies an unsupported blanket rinse requirement and prints a residual “PASS” without establishing the applicable limit.
- The raw export omits relationships and reference records needed to reconstruct parts of the PDF.

**Recommendation:** correct the misleading output and export omissions before describing this dossier as inspection-ready. Keep the explicitly deferred inventory work separate; a truthful statement that a balance is unresolved does not require building the entire inventory design.

The review standard is [7 CFR 205.103](https://www.ecfr.gov/current/title-7/subtitle-B/chapter-I/subchapter-M/part-205/subpart-B/section-205.103): records must disclose the operation's activities and transactions sufficiently for audit, support traceability and organic identification, and be retained for at least five years after creation. The regulation does not require every operator log to have a photograph or external attachment. Findings below distinguish a recorded statement from a missing document that the statement itself relies on.

## Evidence conventions and coverage

Paths below are relative to the handoff root, or to the specified nested ZIP. PDF page numbers are physical, one-based pages. CSV rows are logical CSV records, counting the specimen notice as row 1 and the header as row 2; quoted multiline cells do not create extra rows. Table row numbers exclude the column headings.

| Alias | File |
|---|---|
| D | `dossier/operation-dossier-organic.pdf` |
| P2 | `dossier/productions/2-Bottom-Ground-A-Spinach-2026-Bottom-Ground-A-spring.pdf` |
| P7 | `dossier/productions/7-Home-Field-East-Duke-2026-Home-Field-East.pdf` |
| P8 | `dossier/productions/8-Home-Field-West-Draper-2026-Home-Field-West.pdf` |
| P9 | `dossier/productions/9-River-Block-Liberty-2026-River-Block.pdf` |
| C2, C7, C8, C9 | Corresponding `.csv` beside those PDFs |
| R/ | Members of `records/records-export.zip` |
| O/ | Members of `osp-packet/calapooia-v3-active-ccof.zip` |

I verified every file hash listed in `bundle-log.json`. I examined the 427-page operation dossier, all 12 production PDFs and CSVs, all raw-record families, readiness JSON, and the relevant OSP packet pages and workbook. All **95 drift-warning rows and 80 chemical-classification rows** were matched by production, date and input name to the raw records, in both the operation PDF and the production PDFs. I also checked the 15 soil approval-status entries and eight sanitizer-reference entries. Selected finding pages were rendered to distinguish actual output defects from diagonal-watermark extraction artifacts.

**Observed** means shown directly by the supplied files. **Inference** is an interpretation or possible code cause, not verified implementation. **Recommendation** is the next inspection or product action. The build script is available; the exporting services and their test execution are not.

## 1. Input application trace-back

Selected: **ChemicalEvent 49**, Entrust SC, Home Field East / Duke 2026, 19 June 2026.

**First broken link: the claimed purchase cannot be corroborated against its source document.** A supplier, purchase date, invoice number and product lot are recorded, but the receipt is not included and `receipt_document_id` is blank. This is an evidence gap, not a claim that the application log itself is invalid.

| Step | Observation and evidence | Inspection result |
|---|---|---|
| Purchase / source | D p111, purchase table row 3: Wilco Ag, Tangent OR; purchased 8 June; invoice `WILCO-2026-20411`; lot `ENT-26-0288`; 128 oz. R/`chemical_events.csv` row 51, id 49, agrees and has no receipt document id. D p11 lists only a blueberry label proof and a sales invoice. | **First source-evidence gap.** Request the purchase invoice and confirm formulation, lot and purchased quantity. |
| Product label / listing | D p110, application row 2: Entrust SC, 22.5%, EPA 62719-621. Organic status explicitly says grower-selected, no listing on file. D p111: no OMRI id; historical Spinosad classification expressly unverified. No product label or listing document is included. | Identity, label directions and applicable restrictions cannot be independently checked from this bundle. |
| Plan approval | D pp8–9 contains planned “Entrust SC Naturalyte Insect Control”, OMRI `dow-2900`. O/`workbooks/Materials List.xlsx`, A9/F9, keeps logged Entrust SC unresolved; A23 is the separately named planned product. D p111 OSP Approval is a dash. | A planned material exists, but identity equivalence and operation-specific approval are not demonstrated. Do not treat the OMRI entry as the missing certifier approval. |
| Application | D p110 row 2: 19 June, 62.50 oz over 12.50 acres, 5.00 oz/acre, ground spray, SWD target, REI 4 h, PHI 3 d. D p111 names Javier Morales. Parcel context is D pp108–109. C7 row 35 and R/`chemical_events.csv` row 51 agree. | Core application record is present. Actual label compliance is not established by these fields alone. |
| Classification / warning | D p108 row 2: resolves to a WSDA entry absent from the active OSP registry. Raw warning has `reason_code=name_wsda_not_in_osp`, WSDA id 229. D p111 labels the stored Spinosad link “recorded before Trazo kept how it was matched; not verified”. | The warning survives and does not become approval. The displayed reason is truncated; the raw CSV contains its full wording. |
| Practice justification | D p138 dates the first female-SWD threshold assessment to 22 June, after this 19 June application, while D p3 describes application only after that threshold. | Ask why this application preceded the stated trigger. This is a specimen contradiction, not proof that the product was prohibited. |

The second Entrust application, 3 July, repeats the same 128 oz purchase reference. That matters to the aggregation finding below; it is not evidence of a second purchase.

## 2. Sale trace-back

Selected: **SalesRecord 13**, River Block / Liberty 2026, fresh fruit sold to Cascade Organic Distributors on 16 August 2026, invoice `CBF-INV-26--RB-F`.

**First source-evidence gap, reading from harvest forward:** D p320 calls the harvest weights “Scale-Verified (weigh ticket)”, but the weigh tickets are not included. The harvest logs themselves are present. If those logs are accepted as the operation's primary harvest record, the next unresolved handoff is the movement to the handler: the recorded sent dates conflict with the transport dates, and receiving/pack-out documents are only referenced.

| Step | Observation and evidence | Inspection result |
|---|---|---|
| Harvest and parcel | D p320, harvest rows dated 20, 25 and 31 July: 30,800 + 32,600 + 29,700 = **93,100 lb**, River Block, Liberty. R/`production_events.csv` rows 195, 198, 201, ids 193/196/199. | Logs and arithmetic agree. Referenced scale evidence is absent. |
| Lot identity | Harvest lots `CBF-26-RB-01`, `-02`, `-03` appear in D p320 and the sale's Lot(s) cell, D p346 row 1. | PDF linkage exists. The raw sales CSV does not export the sale-to-harvest relationship. |
| Storage and handler | D pp319–323: farm cooler at 34°F; COD named as handler. D p322 records 29,630 + 31,361 + 28,571 = **89,562 lb** returned/packed-out against receiving references R-26-4100/4107/4114. | These are typed quantities and references. No receiving records, pack-out sheets or handler certificates are included. Sent dates are one day earlier than the corresponding transport events. |
| Sale | D p346 row 1 and R/`sales_records.csv` row 15: 89,562 lb, $340,335.60, COD, 16 August, invoice and BOL references. | Date, buyer, quantity and amount agree; 89,562 × $3.80 = $340,335.60. |
| Invoice / BOL | O/`audit-trail/sale-13/2-Invoice CBF-INV-26--RB-F (specimen).pdf`, p1, contains the invoice and BOL references, buyer, destination, carrier and quantity in its notes. It is visibly a specimen. | Attachment exists, but does **not** print an organic product designation or the three harvest lot codes; no separate BOL is included. “Organic on Invoice: Yes” in the sales record is not demonstrated by this attachment. |
| Quantity reconciliation | D p346: total season harvest 114,240 lb; two sales total 110,702 lb; difference **3,538 lb**. O/`05-audit-trail-exhibit.pdf`, p2, describes the same difference relative to recorded handler pack-out. | Arithmetic agrees. D calls it “uninvoiced remainder”; the evidence establishes neither that it remains inventory nor that it awaits invoicing. Obtain the handler's explanation and disposition records. |

The absence of loss/custody evidence is the existing T03/T22 limitation re-observed in the requested trace, not evidence that deferred inventory functionality was promised as completed.

## 3. Findings and five-axis scores

Scores assess each finding's specific evidence chain: **2** = demonstrated adequately; **1** = partial; **0** = missing, contradicted or misleading; **?** = not observable. Order is **S / M / Sp / R / D**: schema capability, mapping, specimen, rendering, disclosure. Schema scores use fields/records actually visible; they do not certify the underlying implementation. No summed compliance score is intended.

Severity is inspection priority: **High** obstructs traceability or can materially mislead a decision; **Medium** requires correction or clarification but does not alone determine organic status.

| ID | Severity | Axes S/M/Sp/R/D | Observed finding and file/page/row | Recommendation: inspector action |
|---|---|---|---|---|
| **R7-01** | High | 1/1/0/1/1 | Referenced evidence is missing or overstated. Input receipt/label absent (D pp110–111; R/chemical_events row 51); handler certificates absent yet D p322 says “DOCUMENTED … on file and current”. Self-reported and attachment-absent caveats help but do not establish current status. Selected invoice attachment p1 lacks the organic designation asserted in D p346. | Request the named source documents. Keep operator statements separate from document-present and independently checked status. |
| **R7-02** | High | 2/0/2/0/0 | D p9 says no change notifications on file, while O/03 p1 contains the 12 February v1 notification. D p2 calls v3 “Active / Approved” with approval blank and calls narratives verbatim filed content. D p9 reproduces part of revision 3 without identifying the corrective revision or directing the reader to its complete frozen filing; it omits the signed hash and parts (a)(3)–(4). A clearly labelled summary would be acceptable. Its footer says evidence sections “satisfy” OSP practices. | Use the actual notification and frozen renewal documents. Do not infer certifier approval, filed snapshot identity, or satisfaction from active status and populated text. |
| **R7-03** | Medium | 2/1/2/1/1 | All 95 warnings survive, but **86 reasons end in an ellipsis**; D pp107–108 illustrates loss of the decisive match text. “Verified” means local lookup time, while the footnote says every catalog is never synced. Seven SaniDate records have no drift warning although O/Materials List F17 says identity not confirmed. | Read full raw reasons; distinguish unresolved identity, registry membership and current-list verification. Do not regard absence of a sanitizer warning as clearance. |
| **R7-04** | High | 2/1/1/0/0 | Soil status `yes` prints unqualified “Yes - Organic Approved” (D p223, 18 March row; also pp170,371). C8 rows 5–7 drops the qualification even for OMRI and operator-claimed certifier approval. C9's inspection-history row 80 calls Laurel Brandt “Inspector” and status “Verified”; D p344 correctly separates performer/recorder and qualifies verification as self-reported. | Obtain the approval evidence; retain actor roles and provenance qualifications across PDF and CSV. Do not read an enum label as an independent finding. |
| **R7-05** | High | 2/0/1/0/0 | D p138 asserts §205.605(b) requires a potable rinse after sanitizer contact generally. D pp38,58 gives SaniDate residual `4.00 (PASS vs 4.0)` with no applicable product/use limit established, prints §205.601(a)(6) under a §205.605 heading, and leaves five processing-row dates blank although R/production_events has dates. | Check the actual label, use and applicable provision; withdraw unsupported pass/fail conclusions. Restore dates and identify operator-entered regulatory references. See regulatory check below. |
| **R7-06** | High | 1/0/1/0/0 | D p140 counts Entrust invoice WILCO-2026-20411 / lot ENT-26-0288 / 128 oz twice and prints **488 oz** total purchased including 232 oz Serenade. The same purchase identity counted once gives **360 oz** for these rows. R/chemical_events rows 51,53 and C7 rows 110,112 confirm repetition. “Inputs Purchased” dates are application dates (19 June/3 July), not purchase date 8 June. | Reconcile against receipts and unique purchase lines; do not treat the sum of application-carried purchase quantities as purchasing or inventory. |
| **R7-07** | High | 1/1/0/0/1 | D p346 / C9 row 92 labels 3,538 lb “uninvoiced remainder” without disposition evidence. D p141 links the 99,086 lb HFE fresh sale only to lots -02/-03, whose harvest totals are **66,500 lb**; the first pick is now `CBF-26-HFE-P1` (D p113; R/production_events row 137) and is absent from that sale cell. | Reconcile the missing lot link and disposition; report the difference as unresolved until its cause is documented. Preserve the useful explicit “not a period mass balance” limitation. |
| **R7-08** | High | 2/0/1/0/1 | R/sales_records contains no harvest ids or join table; R contains no OSP/renewal/notification, material-reference catalogs, document-link export, or amendment/history tables. The PDF knows sale lots and change history that the raw ZIP cannot reproduce. Per-production CSV purchase summaries omit soil amendments: C9 rows 96–107 versus D p345's Tiger sulfur row. | Obtain a relational export or accompanying evidence package. Do not describe this CSV ZIP alone as a reconstructable copy of the complete record. |
| **R7-09** | High | 2/0/1/0/1 | Readiness production ids 2/5/6/10/11 flags compost C:N 18:1 and says handle as raw manure, then labels raw-manure interval N/A. P2 p1 shows both; D pp33–34 omits the structured C:N/process assessment. R/soil_events rows 8,18,23,39,43 retains the data; feedstocks include manure. | Resolve supplier process evidence and whether 18:1 is initial or finished C:N. If a manure interval applies, assess it; do not leave it N/A after explicitly invoking it. Carry the unresolved issue into the operation dossier. |
| **R7-10** | Medium | 2/0/1/0/0 | D p12 retention “Until: 2031-08-12” follows latest finished season, while promising five years from creation. R/productions row 11 was created 3 October 2026 but says retain until 12 August 2031; row 3 says July 2030 despite the same October 2026 creation date. | Confirm the actual retention policy; correct the displayed deadline basis. This proves inconsistent metadata, not actual deletion or loss of retained records. |
| **R7-11** | Medium | 2/2/0/1/0 | River Block handler table D p322 says sent on 20/25/31 July and 7 August; transport records D pp319–320 say 21/26 July and 1/8 August. The table also labels transport-event dates as “Harvest Date”. “WVF Salem” in storage/handler references is not reconciled to Marion Bend in the handler/sale records. | Resolve the handoff date and facility identity with BOLs and receiving records; distinguish harvest, departure and receipt. |
| **R7-12** | Medium | 2/2/0/2/0 | Operational statements conflict: Neptune is chemigated/through drip but Fertigated=No (D pp109,112); the 19 June Entrust precedes the 22 June female threshold (pp3,138); hives removed 16 May in the placement note but 13 May in the event, with April/May sprays despite no-spraying narrative (pp112–113); the same 1,550 lb culls go to process in p113 but are buried in p138. Further particulars below. | Interview the operator and reconcile the underlying entries with amendments, not silent overwrites. No prohibited-input conclusion follows solely from these contradictions. |
| **R7-13** | Medium | 1/0/0/0/0 | D p318 renders frost protection “to 30°C”; p344 renders heat “max 101°C”, beside notes explicitly describing 30°F and 99–101°F. R/production_events row 186 / weather_events row 16 contain bare numbers in JSON. | Confirm units and correct the record/rendering basis before using temperatures as evidence. Files do not establish whether entry, schema conventions or rendering caused the mistake. |
| **R7-14** | Medium | 2/0/1/0/0 | D pp223,323 declares no seed/planting-stock records and calls it a standard inspection finding for mature blueberry seasons, although D p2 gives 2006/2013/2016 establishment history and says no planting since 2016. It also attributes a fixed “3+” search rule to §205.204. | Review the standing perennial-stock history and relevant certifier requirements. A missing current-season planting event is not sufficient to declare an inspection finding. |

**Code inferences:** R7-02 is consistent with a dossier renderer that has not adopted the packet's cross-version notification and renewal model. R7-06 is consistent with summing purchase metadata per event rather than per purchase. R7-08 demonstrates missing exported relationships, but not their absence in the database. R7-13 suggests a missing or ignored temperature-unit convention. These are hypotheses for Claude to verify against code, not code-reviewed root causes.

### Regulatory checks behind R7-05, R7-09 and R7-14

- [§205.605(b)](https://www.ecfr.gov/current/title-7/subtitle-B/chapter-I/subchapter-M/part-205/subpart-G/subject-group-ECFR0ebc5d139b750cd/section-205.605) distinguishes chlorine materials and their rinse conditions from peracetic/peroxyacetic acid use. It does not supply the blanket all-sanitizers rinse rule printed by Trazo. The PAA provision refers to FDA limits for wash/rinse water and use on food-contact surfaces. Nothing supplied establishes 4.0 ppm as the applicable SaniDate limit. This review does **not** conclude that the recorded no-rinse use is permitted; the product label and use conditions are missing.
- [§205.601(a)(6)](https://www.ecfr.gov/current/title-7/subtitle-B/chapter-I/subchapter-M/part-205/subpart-G/subject-group-ECFR0ebc5d139b750cd/section-205.601) concerns specified crop-production disinfectant uses of peracetic acid. Printing that citation does not establish a processed-food wash-water use under §205.605.
- [§205.203(c)](https://www.ecfr.gov/current/title-7/subtitle-B/chapter-I/subchapter-M/part-205/subpart-C/section-205.203) distinguishes raw manure, qualifying compost process conditions, and uncomposted plant material. The purchased-compost records actually name manure. Supplier evidence may resolve the initial-versus-finished C:N ambiguity; the current warning and N/A interval cannot simply both be accepted. Separately, the Upper Terrace plant-only windrow is not automatically a raw-manure case.
- [§205.204](https://www.ecfr.gov/current/title-7/subtitle-B/chapter-I/subchapter-M/part-205/subpart-C/section-205.204) establishes organic seed/stock and commercial-availability provisions, but does not state a universal numeric three-supplier minimum. Such a procedure needs its actual certifier or guidance basis identified.

## 4. Exhaustive warning/classification check

### Drift warnings

| Input family | Number | Printed / raw status |
|---|---:|---|
| Rex Lime Sulfur | 6 | Unresolved; possible OMRI/WSDA/National List matches, not confirmed |
| Feather Meal 12-0-0 | 11 | Unresolved; possible OMRI match |
| Serenade Opti | 12 | Unresolved; possible OMRI match |
| Neptune Fish Fertilizer 2-3-1 | 28 | Unresolved; possible 2-4-0.5 OMRI match remains explicitly unconfirmed |
| Surround WP | 6 | Unresolved; possible OMRI match |
| Entrust SC | 14 | WSDA name resolution, product not in OSP registry |
| Grandevo WDG | 3 | Unresolved; possible OMRI match |
| Tiger elemental sulfur | 6 | Unresolved; possible National List match |
| Douglas-fir sawdust | 4 | Unresolved |
| Rexius Organic Compost | 5 | Unresolved |
| **Total** | **95** | **80 chemical + 15 soil; no production-event drift warnings** |

**Observed pass:** every warning is present in both PDF export types and in its raw CSV row; each production's readiness warning count agrees. None of the possible-name matches clears a warning. Entrust's 14 approval-registry warnings remain. The OSP workbook keeps the corresponding logged names separate and unresolved (A7:F17).

**Observed limitations:** the dossier's “Unapproved-Input” heading is stronger than an unresolved name establishes. The full raw reasons make the distinction, but most PDF reasons truncate it or the candidate name. The lookup-time legend and never-synced warning are useful and should remain; “Verified” still risks suggesting a current authoritative check. No current catalog status was independently established by this bundle.

### Classifications and approval wording

- **80 chemical classification rows:** all read Self-reported, with no attached OMRI id and no OSP Approval value. **20** historical National List links are correctly qualified: 6 Lime sulfur and 14 Spinosad; raw bases are `legacy_unverified`. The other 60 have no stored National List link. No legacy link is printed as an authoritative citation. D pp17,29,48,70,89,111,164,216,266,317,365,413; matching tables in all 12 production PDFs. This part of Phase 5 holds.
- **15 soil status entries:** 11 OMRI selections, 1 claimed certifier approval and 3 legacy `yes` selections. The first two types receive a grower-selected caveat in the PDF; the three `yes` rows do not. The production CSV removes those caveats. R7-04 remains.
- **Eight sanitizer references:** seven SaniDate entries and one Tsunami entry print operator-stored regulatory text. These are not verified product listings. Their dates, legal conclusion and residual-check problems are R7-05. The absence of a SaniDate drift warning does not agree with the workbook's unresolved identity if read as full material coverage.
- **Plan catalog entries:** the six OMRI names/ids and three National List substance names on D pp8–9 agree with the OSP registry/workbook. They establish what the plan names, not a match to each logged formulation, a current listing, use-condition satisfaction, or certifier approval. The “Active / Approved” wrapper wrongly encourages that broader reading.
- **Other generated assurance:** D pp17,111 says documented nitrogen source means “no prohibited synthetic nitrogen”. The visible evidence is a selected source category, not product analysis or resolved identity. Treat this as another R7-04 disclosure problem, not as proof of prohibited use.

## 5. Internal consistency

### Counts and totals that agree

The 12 productions cover six parcels. There are **512 events** across the seven operational event families, **15 sales**, and no event photos. Event counts below agree between the raw CSVs, the first event table in every production CSV, and readiness. Event-date multisets agree as well. Later sections of a production CSV repeat dates for purchases/certification/reconciliation; they must not be counted as extra events.

| Production id | Events | Drift warnings | Harvest lb | Sales lb |
|---:|---:|---:|---:|---:|
| 1 | 65 | 12 | 118,750 | 114,916 |
| 2 | 22 | 3 | 111,600 | 100,440 |
| 3 | 66 | 12 | 154,000 | 148,870 |
| 4 | 64 | 13 | 112,000 | 108,542 |
| 5 | 26 | 4 | 446,400 | 392,832 |
| 6 | 22 | 4 | 393,600 | 334,560 |
| 7 | 65 | 12 | 121,250 | 117,336 |
| 8 | 69 | 14 | 151,200 | 146,150 |
| 9 | 62 | 12 | 114,240 | 110,702 |
| 10 | 19 | 4 | No harvest | No sale |
| 11 | 21 | 4 | 348,000 | No sale |
| 12 | 11 | 1 | No harvest | No sale |

Harvest and sales totals agree between raw detail, D and all production PDFs. Open Upper Terrace has a harvest record but no finalized production total; its raw production header is zero. The dossier correctly uses the event's 348,000 lb. This is **not** a counting defect. Missing sale/harvest fields render as dashes for productions 10/12, not evidence of a recorded zero transaction.

### Disagreements and ambiguities requiring follow-up

In addition to the exact differences in R7-02 through R7-13:

| Check | Observed disagreement / limit | Evidence |
|---|---|---|
| HFE purchase lot | Feather-meal purchase table says `DTE-FM-2512-880`; application narrative says `DTE-FM-2512-088`. | D pp110,112; R/chemical_events row 44. |
| HFE application scope | Grandevo note says buffer row skipped, but structured scope says Entire planting and block rows 1–42. This may mean the production excludes the buffer, but that boundary is not clear on the application. | D pp110,112; R/chemical_events row 52. |
| HFE spray policy | OSP says no material applied with hives present. The 27 April record explicitly says hives present and biological spray at dusk. Placement note says removal 16 May before first Serenade, despite 27 April and 7 May Serenade records; removal event is 13 May. | D pp3,112–113. |
| HFE threshold/rate rationale | Threshold occurs after the application; threshold JSON recommends 6 fl oz/ac while the selected application records 5 oz/acre. No label resolves the unit/rate difference here. | R/pest_events row 78, id76; R/chemical_events row51; D p138. |
| HFE cull disposition | The same 1,550 lb from pick 1 is sent toward process in the packing note and later described as buried. A changed disposition is possible, but not linked/explained. | D pp113,138; R/production_events row138. |
| HFE shipping | First-pick narrative names COD fleet/R-117 and BOL CBF-26-0623-1; aggregate fresh sale names own reefer/OR-TRL-44821 and BOL CBF-26-HFE-01..03. Could be multiple legs, but the chain does not explain them. | D pp113,141; R/production_events row139. |
| Certified acreage | April 2026 event claims 54.2 organic acres across six parcels; farm/renewal summary gives 86.9 acres. The 138.6 total operation acreage is separately disclosed and is not itself the contradiction. | D pp9,11,140; R/business_events row7, id5. This was a known earlier specimen limitation, now re-observed, not a new regression claim. |
| Conventional buffer sale | Plan says a separate sales record exists for 2,300 lb buffer fruit. The buffer-use entry records disposition, but all 15 exported SalesRecords claim organic and none is that conventional sale. | D pp4,12; R/production_events row149, id147; all R/sales_records rows. Do not infer the conventional disposition is absent altogether. |
| Compost completion | OSP says two final windrow turns finished by 8 September; raw UT-2 record still documents only three through 25 August. Could be a historical snapshot, but the later completion record is not supplied. | D p5; R/soil_events row48, id46. |
| Warning omission versus raw data | Production CSV has no drift-warning/classification table, although raw-family CSV and PDF do. Its soil-purchase summaries omit amendments present in the PDF. | C7/C9 section inventories; R/chemical_events and soil_events; D pp140,345. |
| Table label versus event type | Off-farm handler table mixes transport events and harvest events under “Harvest Date”; their different dates are real source values, not a timezone conversion. | D p322; R/production_events rows195/197,198/200,201/203,204/206. |

These are file observations. They do not prove that the same contradictions exist in the live database or that the application introduced them rather than the demo fixture.

## 6. Run-1 items re-observed

| Item | Status from these files | Evidence and boundary |
|---|---|---|
| **T03 allocation / remainder** | **Still present** | D p346's unsupported uninvoiced interpretation and D p141's incomplete lot linkage. The disclosed absence of period inventory is good. `context/D10-INVENTORY.md` is a deferred design, not implementation evidence; this review does not order its full build. |
| **T05 daily forms** | **Not observable** | Static exports show stored fields, not data-entry gates, collapsible sections, repeat/recent behavior or season-close interaction. No form changes or live mutations were attempted. |
| **T06 “on file” versus attached** | **Still present, partly improved** | D p11 honestly identifies an attachment index, and the OSP ZIP supplies two specimen documents. Purchase/handler evidence remains absent; D p322 still calls a self-reported certificate current and documented. |
| **T07 purchase counted twice** | **Still present** | D p140 / P7 p47 / R/chemical_events rows51,53 repeat one 128 oz invoice/lot and aggregate it twice. |
| **T08 dates** | **Not observable for the original editor/consumer issue** | All 512 exported event dates match the raw stored date portions. This does not test local-time editing or the public page. Separate observed export-date defects are the blank sanitizer dates and mislabeled purchase/handler dates; no previously retracted timezone defect is revived. |
| **T12 export scope** | **Still present** | Sales-to-harvest links, reference catalogs, amendments/history, document relationships and OSP tables cannot be reconstructed from the raw ZIP. PDF and separate OSP packet preserve some information, but are not an equivalent relational export. |

## 7. What could not be tested

- No live app cross-check was used. The bundle is authoritative for this request; record ids are local. No records or documents were created, edited, deleted, generated or filed in Trazo.
- No source-code review of the exporting services, migrations, permission boundaries, retention jobs or schema constraints; no CI/test execution evidence. The build script and outputs do not prove those behaviors.
- No real supplier invoices, product labels/listings, certifier approvals, handler certificates, weigh tickets, receiving sheets or loss/disposition documents for the chosen traces. Fictional content and specimen watermarks are intentional, not findings by themselves.
- No current OMRI/WSDA product-status verification. The supplied dossier itself warns its local catalogs are not confirmed current. A current public listing would not prove historical approval for the recorded use.
- No audit of five-year operational retention, backups, completeness of records outside this package, or the original electronic-signature action. D p10's producer-attestation text and blank signature line do not demonstrate that Seed Runner attested to this newly assembled dossier. The signed renewal is a separate document.
- No crew-message provenance specimens, live WhatsApp, QR/public experience, mobile workflow, private-storage behavior, or daily-form interactions. Those are outside what these files demonstrate.
- No proof of full chronological completeness: matching totals and dates establish agreement among these exports, not that every real-world activity was entered. The missing 2025 filing and deliberately absent certificate uploads are not reclassified as newly introduced product failures.

**Disposition:** retain the demonstrated Phase 5 identity/classification safeguards. Reopen the dossier-specific mapping, rendering and disclosure issues identified here; keep missing external evidence and demo contradictions on their own axes. Do not close T03, T06, T07 or T12 from this bundle.
