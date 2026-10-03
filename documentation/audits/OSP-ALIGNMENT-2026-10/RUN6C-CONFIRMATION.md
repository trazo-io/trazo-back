# Run 6c confirmation (Astra, 2026-10-03)

Filed as received, against `Trazo-Review-Handoff-2026-10-03-run6c` (trazo-back main 223b1ba).

**Pass on the requested behavior. T18 can close R6b-01.** No regression found within this focused comparison.

Checked all nine packets directly; their hashes match `bundle-log.json`. References below apply to CCOF, OTCO and WSDA.

| Item | Result | Evidence |
|---|---|---|
| Feather Meal suggestion restored | **Pass** | `panels/r6b-01-feather-meal.json`: correct plan product, OMRI ID **2924**. |
| All eight suggestions | **Pass** | `panels/as-seeded/identities.json`: no obvious maker-only or generic-word false pair. The two Tsunami prompts cite separate plan questions; they do not establish equivalence. |
| Neptune undo | **Pass** | Withdrawn `workbooks/Materials List.xlsx`, sheet **Materials List**, **A8:F8** and **A25:F25**, exactly matches seeded values. `modules/materials_application.pdf`, **p1**, restores Neptune to the `[REVIEW]` list. |
| Neptune drift | **Pass** | `panels/{as-seeded,decided,withdrawn}/drift-findings.json`: all **28** uses return from no finding to `unresolved`, with the original substantive wording. Recompute timestamps differ. |
| Serenade withdrawal | **Pass** | Withdrawn workbook **F21** returns to “Restriction not documented in Trazo.” Seeded value matches exactly. |
| Entrust preserved | **Pass** | Decided **F8** equals withdrawn **F12**: **13 of 14 identified, one excluded**. All **14** approval findings remain in all three drift payloads. |
| Withdrawal history | **Pass** | Withdrawn `identities.json` retains Neptune decision **17**; `restrictions.json` retains Serenade statement **7**. Both preserve **Seed Runner**, withdrawal timestamps and explicit reasons. Neither remains current. |
| No approval/compliance inferred | **Pass** | Changed workbook text attributes decisions to the operator. The restriction statement explicitly disclaims a compliance finding. No decision-generated approval claim found. |

The supplied diff summary is corroborated for these behaviors. Across all three agents, withdrawn PDF text matches seeded PDF text; Entrust’s retained decision explains its different workbook wording.

**Should the certifier-facing packet disclose withdrawn decisions? Yes.** Include relevant withdrawals in the **private audit-history exhibit or appendix**. Otherwise, a reviewer cannot distinguish “never decided” from “previously asserted, then withdrawn,” especially where the reason was the wrong product or label. That is an auditability recommendation, not a failure of the current-state restoration checked here.
