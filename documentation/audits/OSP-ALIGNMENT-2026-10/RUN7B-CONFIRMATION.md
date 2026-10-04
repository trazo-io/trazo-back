# Run 7b confirmation (Astra, 2026-10-04)

Filed as received, against `Trazo-Review-Handoff-2026-10-04-run7b` (trazo-back main 9d0c509).

**Most corrections are demonstrated, but R7-01, R7-02, R7-09 and R7-12 should remain partly open.** The specified numerical and frozen-file regression checks passed.

| R7 ID | Result | Evidence and residual issue |
|---|---|---|
| **01** | **Partly** | D, *Off-Farm Handler Certificate*, pp34–35, production 2: dates, missing copy and self-reported verification are separated correctly. However, the following handling footer still asserts the certificate **“is retained with the lot records”**, contradicting “No copy…is held in Trazo.” |
| **02** | **Partly** | D, *OSP Reference / Annual Continuation*, pp2,9–10: active status, v1 notification, revision identity, hashes and superseded dates are corrected. **Application changes (a)(3) prints “—”**, although `annual-update/2026-revision-3.pdf` p2 contains the explicit no-changes attestation. That answer is lost in the summary. |
| **03** | **Pass** | D, *Inputs Not Matched*, pp114–116, production 7: full reasons, local-lookup qualification and sanitizer limitation are present. All 95 warning rows reconcile with source records and production PDFs. |
| **04** | **Pass** | D, *Soil & Water Management*, pp179,234,387; soil IDs **2,30,12**: legacy approval selections are qualified. Production CSVs distinguish performer/recorder and self-reported verification. D p119 limits the nitrogen statement to the operator’s selection. |
| **05** | **Pass** | D, *Post-Harvest Sanitation*, pp40,61, productions **2,5**: dates appear; residuals say **“no limit assessed”**; references are operator-entered and flagged for review. No residual PASS verdict remains. |
| **06** | **Pass** | D, *Inputs Purchased*, pp148–149; chemical IDs **49,51**: shared Entrust purchase is counted once provisionally. Purchase dates, qualifications and soil purchases agree with production CSVs. |
| **07** | **Pass** | D, *Output Reconciliation / Itemized Sales*, p149; sale **9**: all three fresh lots appear, including `CBF-26-HFE-P1`. The difference is explicitly unreconciled. The unlinked-lot warning branch is not exercised by this specimen. |
| **08** | **Pass, scoped** | `records-export.zip`: `sale_harvest_links.csv` contains **32 links**, including sale **9 → harvest 135**. README names omitted families; production CSVs now include warning and classification tables. Full relational export remains deferred. |
| **09** | **Partly** | D, *Documentation Snapshot / Compost Temperature Records*, pp29,36; soil **6**: unresolved manure assessment replaces N/A correctly. But the adjacent **“Compliant” column says “No (C:N)”**, while the disclosure says it is unknown whether that C:N describes the starting mix. The table still makes a stronger determination than its evidence. Same pattern appears elsewhere, including p433. |
| **10** | **Pass for observed output** | D, *Record Retention*, p12; `productions.csv`, IDs **1–12**: calculated date is 2031-10-04; finished-season stored dates agree, and open-season non-protection is disclosed. Actual deletion refusal and later-record recalculation are not demonstrated by these files. |
| **11** | **Pass** | D, *Crop Sent for Off-Farm Handling*, pp125,337; productions **7,9**: rows distinguish transport from harvesting, and sent dates follow the recorded movements. Transport rows remain visible. |
| **12** | **Partly** | Several fixes appear: fertigation, hive-removal date, cull disposition, acreage and compost completion. However, D p120, chemical **50**, still references Entrust on **19 June**, while corrected chemical **49** is dated **23 June**. D pp120–121 also says Serenade was applied at dusk but the revised hive narrative says before 7 a.m. The previously noted Grandevo “Entire planting” versus buffer-skipped ambiguity remains. |
| **13** | **Pass** | D, *Field Operations / Weather*, pp121,147,201; production event **127** and temperature rows: −2.2°C, 30°F and 102°F render with appropriate units. |
| **14** | **Pass for specimen** | D, *Seed & Planting Stock*, p126, production **7**, and other blueberry sections: absence of a planting record is stated, prior crop history is identified, and replacement planting remains a recordkeeping question. The automatic “standard inspection finding” is gone. |

**Specified regression checks**

- **Frozen PDFs unchanged:** revision 2 hashes to `e20e0567…92761b7`; revision 3 to `4cd62bbf…dbe3bb`, matching run 7.
- **Warnings/classifications unchanged:** 95 warnings; 80 classification rows comprising 20 legacy-unverified and 60 without classifications. No legacy classification became citable; suggestions remain unconfirmed. Chemical 49’s warning follows its corrected application date.
- **Harvest/sales unchanged:** **2,071,040 lb harvested; 1,574,348 lb sold**. Per-production totals reconcile across raw records, dossier, production PDFs and CSVs.
- **Purchase corrections reconcile:** ounce totals changed for productions **3: 896→640; 4: 806→550; 7: 488→360; 8: 768→640; 9: 678→550**. These provisional grouping reductions agree across PDF/CSV outputs.
- **Readiness:** event counts reconcile at **513**, up from 512 through added soil record **47**. Readiness does not supply purchase/harvest/sales totals, so it cannot independently confirm those.
- **Correction-related residuals:** the stale 19 June reference and new before-7-a.m./dusk inconsistency are described under R7-12.

**Axis closure**

Close the demonstrated **mapping, rendering and disclosure corrections** for **R7-03–08, R7-11, R7-13 and R7-14**, within the stated scope. For **R7-10**, close the observed deadline rendering/disclosure only; enforcement remains untested here.

Keep **R7-01, R7-02, R7-09 and R7-12** partly open. R7-12’s specimen fixes are only partially complete. These files do not independently establish schema/code correctness.

The README’s deliberate deferrals remain out of scope. Missing external documents remain open on the **specimen** axis.
