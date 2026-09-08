# E2E Audit 2026-09 — Progress Ledger

Companion to `PLAN.md`. One row per finding; one entry per slice. Update at every completed slice.
Status: `open` · `in progress` · `done` · `blocked` · `deferred` · `rejected`. Decisions are D1–D11 in PLAN.md §5/§11.

## Findings

| ID | Title | Status | Decision refs | Slices | Changed files | Validation | Remaining risk | Next action |
|---|---|---|---|---|---|---|---|---|
| T01 | Public disclosure vs free text | in progress | D1 | A1a, A1b | — | — | extra_data vendors only redacted on exact match | A1a |
| T02 | Demo shows USDA "Verified" | in progress | D2 | A2 | — | — | prod fixture rows need re-seed | A2 |
| T03 | Allocation & remainder | blocked | D10 (held) | B2 | — | — | model revision required (processing batch) | D10 rev. |
| T04 | Review link "no longer available" | open | — | A3 | — | — | root cause unestablished | A3 |
| T05 | Daily forms | open | — | C1, C2 | — | — | — | C1 |
| T06 | "On file" vs attached | blocked | B3 (held) | B3 | — | — | versioning design required | B3 rev. |
| T07 | Purchase counted twice | open | — | B-design, B1 | — | — | — | B-design |
| T08 | Dates | blocked | D4, D11 (held) | A4-interim | — | — | timezone inventory required | A4-interim |
| T09 | OSP completion conflation | open | — | D1-OSP | — | — | — | order 6 |
| T10 | Consumer prose | open | — | E1 | — | — | — | order 6 |
| T11 | Carbon boundary copy | open | — | A5, E2 | — | — | — | order 3 |
| T12 | Export scope | open | — | A5, B4 | — | — | — | order 3 |
| T13 | Density / i18n | open (tour keys done in staged work) | D6 | C3 | — | — | — | order 6 |
| T14 | Production count | open | — | A5 | — | — | — | order 3 |
| §6 retention cite / wording | blocked | D9 (needs Oscar) | — | — | — | legal page | D9 |
| §9 grade/method public | in progress | D5 | A1a | — | — | — | A1a |
| §4 amend GET permission parity | in progress | — | A1a | — | — | — | A1a |
| §16 late entry | open | — | D3 | — | — | migration | order 6 |

## Untested / blocked environments
- Production payloads and prod review-link behaviour: not checked (no prod access by design). Oscar runs one check after deploy.
- Real phone devices, offline: not tested; Playwright viewports only.
- Playwright: local runs only until CI wiring (cross-repo token) — **release condition**: a passing local run against the exact release revision.

## Slice log

### S0 — Baseline (2026-09-08)
- Started. Staged-work boundary: `trazo-back` 87 staged files on `chore/remove-dead-ec2-deploy`; `trazo-app` 37 staged files on `chore/producer-analytics-posture`; `trazo-landing` clean. Oscar commits the staged sets; no migration is numbered before that.
- Another session was running `manage.py test certifications` at start; all runs here use `DATABASE_NAME=trazo_e2e_a|b`.
- Logs: `baseline/*.log` (results filled in below when runs finish).
