# Run 7d confirmation (Astra, 2026-10-05)

Filed as received, against `Trazo-Review-Handoff-2026-10-05-run7d` (trazo-back main ba23b56).
Page references are to `operation-dossier-changed-pages.pdf`.

**Both targeted corrections pass. R7-01 and R7-02 can close on the demonstrated axes.**

| Check | Result | Evidence |
|---|---|---|
| **R7-01: handling footer** | **Pass** | Extract pp2-4, *Post-Harvest Handling*: "Retain the handler's organic certificate..." is an instruction; copy availability is stated separately. No supplied page asserts possession. Absence across all 446 pages is reported by `pages-and-frozen-files.json`; the full dossier was not supplied for independent searching. |
| **R7-02: signed versus held hash** | **Pass** | Extract p1, *Annual Continuation*: signed hash is `da2ebd6b...6242b92`. Database hash `3cd1d5ee...632b4859` appears separately under **"Content held in Trazo"**, explicitly described as recomputed and not established as signed content. |
| **R7-02: provenance** | **Pass** | Independently recomputed `signed-hash-provenance.json`: revision 3's canonical content with original IDs **prior_osp_id=1, corrects_id=2** produces exactly `da2ebd6b...6242b92`; current IDs **9,10** produce `3cd1d5ee...632b4859`. Revision 2 also reproduces its original signed hash. |
| **Frozen-file regression** | **Pass** | Revision 2 and 3 PDF hashes match the previously verified values: `e20e0567...92761b7` and `4cd62bbf...dbe3bb`. |
| **Freeze evidence** | **Pass** | Both `freeze-evidence-filing-10.json` and `-11.json`: canonical and section hashes recompute correctly; before/after filing bytes and signed hashes agree; packet hashes match frozen files; PATCH responses are **409**; rollback values reconcile. The different held-payload hash is disclosed separately. |

**Closure:** R7-01 closes on **rendering and disclosure**. R7-02 closes on **mapping, specimen, rendering and disclosure** for the hash correction. These files do not independently establish schema correctness or live enforcement. No new overstatement was found on the supplied changed pages; missing external certificates remain open on the specimen axis.
