# Run 7c confirmation (Astra, 2026-10-04)

Filed as received, against `Trazo-Review-Handoff-2026-10-04-run7c` (trazo-back main 50b60fd). Astra
returned its run 7c result as the corrective request below: R7-09 and the targeted R7-12 corrections
passed; R7-01 and R7-02 stay open.

> Finish R7-01 and R7-02 with a focused corrective PR.
>
> 1. R7-01: replace "the operation keeps that facility's organic certificate" with an instruction:
>    "Retain the handler's organic certificate with the lot records for inspection. Whether Trazo
>    holds a copy is stated in the handler's certificate block." Do not imply that an external copy
>    exists without recorded evidence.
>
> 2. R7-02: investigate why the dossier prints signed-content hash ff48aeca... while the frozen
>    revision 3 prints da2ebd6b.... Identify which payload each hash represents. The dossier must
>    reproduce the original filing's signed-content hash when referencing that filing. If a
>    reseeded or reconstructed payload has a different hash, label it separately; never present it
>    as the frozen filing's signed hash. Do not alter the frozen PDF or original signature evidence
>    to make the values agree.
>
> Add tests for both failures and confirm the frozen revision 2 and 3 bytes remain unchanged. Keep
> the existing warning, classification and quantity checks.
>
> Update the ledger: R7-09 and the targeted R7-12 corrections passed run 7c; R7-01 and R7-02 remain
> open until these outputs are demonstrated.
>
> Return a small run-7d confirmation bundle containing the changed dossier pages, frozen revision 3,
> relevant hash provenance and test results. No full audit or further planning round is needed.
