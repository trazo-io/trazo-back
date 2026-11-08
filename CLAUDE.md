# CLAUDE.md — trazo-back (Django 5.2 + DRF + PostgreSQL)

Mirror of the review-critical subset of the workspace rules (`~/dev/trazo/CLAUDE.md`
+ `.claude/rules/*`), which live outside this repo and are therefore invisible to CI.
Keep this short; edit it deliberately when a rule below changes.

## Commands — ALWAYS Poetry, never bare `python`
```bash
poetry run python manage.py runserver
poetry run python manage.py migrate
poetry run python manage.py makemigrations
poetry run python manage.py test --noinput
./format.sh                     # Black + isort + flake8
docker compose -f compose.services.yml up -d    # ⛔ NOT compose.yml (both bind 5432)
```
- **Double quotes required.** Single quotes FAIL CI.
- ⛔ Never run the whole test suite in one process — per-app, serial. Piping to `tail` masks both
  the exit code and the traceback; log to a file. `--keepdb` is fine except for `subscriptions`.
- ⛔ 157 loose root-level `.py` files exist, 101 match `test*.py` and 81 execute at import, so a
  bare `manage.py test` is unusable.

## ⛔ Git: shared working trees

Several Claude sessions share this checkout. Two rules, both learned by breaking them on
2026-09-25:

- **Stage only paths you edited.** `git add <file>` takes the whole file, including another
  session's hunks. Run `git status` first; use `git add -p` when a file is dirty from both.
- **Branch from `origin/main`**, not the current HEAD:
  `git fetch origin && git switch -c <name> origin/main`. Then check
  `git log --oneline origin/main..HEAD` before opening the PR — anything unfamiliar there is
  someone's unreviewed work about to merge under your name.

⚠️ **A worktree must sit beside a matching `trazo-app` worktree.** 7 tests here resolve
the frontend as `Path(__file__).resolve().parents[3] / "trazo-app"`, and 30 frontend tests reach
back the other way. A worktree elsewhere either fails outright or, worse, silently compares
against whatever branch the main `trazo-app` tree happens to hold. Pair them:
`~/dev/trazo-wt/<task>/{trazo-back,trazo-app}`. Full recipe in the workspace CLAUDE.md.

⛔ Never create a worktree inside this repo (`.claude/worktrees/…`): it lands a second
copy of the tree inside every `rglob("*.py")` walk.

⛔ No AI attribution in commits or PR bodies.

## Apps
`carbon/` calculations + USDA · `company/` farms · `history/` productions, QR, events ·
`product/` parcels (geospatial) · `users/` multi-tenant auth · `subscriptions/` Stripe + gating ·
`education/` FAQs.

## ⛔ A template produces a PLAN, never a RECORD
Picking a crop template writes `ProductionPlanItem` rows — a season checklist carrying an
agronomic WINDOW ("December – February"), never a day. The operator authors the record in the
activity wizard with their own date, and only then does the plan item close (`fulfilled_by_*`).
**`logged` may be set in exactly ONE place: `EventViewSet.perform_create`, server-side.**
§205.201(a) makes the producer the author; §205.103(b)(2) needs records that survive an
inspector's trace-back. Writing dated, grower-attributed events straight from a template printed
into the certifier packet indistinguishable from observed practice (the backdated-glyphosate
class). Guard: `history/tests/test_season_plan_not_records.py`.
**A plan item carries NO field values — no `prefill` blob, ever.** `cleanEventData` in the wizard
is a passthrough with no allowlist, so anything merged into the form lands on the record whether
the form renders it or not.

## Subscriptions & billing
- **⛔ `create_plans` is the ONLY thing that creates plan rows.** Every migration patches rows
  that already exist and no-ops on a fresh database. A new tier ships by re-running `create_plans`,
  not by `migrate`, and **any guard written against the `Plan` table alone passes vacuously on a
  freshly migrated DB**. Lineup guard: `subscriptions/tests/test_seeded_lineup.py`.
- Live plans: Starter **free forever** (no card, no clock, ⛔ never "14-day free trial") ·
  Compliance **$249/yr** per farm · Operation **$1,200/yr** per operation (DERIVED from Compliance
  by spread, so the two cannot drift) · Pilot comped. Crossover at 8 farms.
- **Add-ons: exactly one is sold** — Extra Farm $149/yr. `extra-parcel`, `extra-production`,
  `extra-storage`, `blockchain-verification` are `is_active=False` and must stay that way.
  Guard: `subscriptions/tests/test_addon_billing_integrity.py`. A Stripe Price is IMMUTABLE.
- **⚠️ The retired ladder is LIVE as CONTRACTS.** `basic-*`/`standard-*`/`corporate-*`/`enterprise-*`
  were deactivated as products, not cancelled as subscriptions. **Any check of the form "is this
  farm paying?" must test the SUBSCRIPTION, never a slug allowlist.**
- Cancellation/`past_due` is a DOWNGRADE to Starter — never null `subscription_plan`, which locks
  a paid farm out of its own records.
- **Quota must be read against the same company the view writes to** (`parcel.establishment.company`),
  not `get_active_company()` — otherwise the cap is bypassable by switching active company. Grep
  the CONSTANT, not one call site.
- Storage: photos are HARD-limited (upload refused at the ceiling); DMS documents are counted but
  NEVER refused — generated rows are undeletable and no storage add-on exists. See
  `subscriptions/storage_accounting.py`. Per-file cap `DOCUMENT_UPLOAD_MAX_BYTES` (50 MB).
- Starter is bounded by what it can PRODUCE, not how much it can log. The OSP renewal packet,
  audit export, CA PUR export and certifier review link are what Compliance buys, enforced in
  `subscriptions/gating.py`. ⛔ The plain records export is FREE and ungated — never plan-gate it.

## Carbon methodology
Scope is **the operation's own emissions plus the manufacturing of what it buys** — NOT "direct
on-farm only". The included list carries fertilizer NPK manufacturing and chemical manufacturing,
which are upstream. State both halves or neither. Not a full LCA (never "carbon footprint",
never "carbon neutral").

⛔ **Factors are NOT all "EPA/USDA-sourced" — say it per input class, never as a blanket:**

| Input | Provenance |
|---|---|
| Diesel, petrol, electricity | EPA — published |
| Nitrogen (10.5) | EPA 40 CFR 98 + IPCC 2006/2019 — published |
| **P2O5 (1.19), K2O (0.65)** | **`PROVENANCE_INTERNAL_ESTIMATE` — Trazo conservative estimate** |
| Pesticide (8.8), herbicide | Audsley et al. 2009 / Hillier et al. 2009 — academic LCA, not a US agency |

Each factor carries its own `source` and `provenance`; copy must READ them rather than generalise.
Diesel 10.21 kg CO2/gal · Electricity **0.365** kg CO2e/kWh delivered (eGRID2023 rev.2, 4.2% grid
loss — was 0.821, then a miscited 0.39) · Nitrogen 10.5 kg CO2/kg N.
Source of truth: `carbon/services/verified_emission_factors.py`. ⛔ Verify a factor against its
SOURCE, never against the code.

## ⛔ The transparency score is RETIRED as a CONCEPT
No weights table, no formula, no 0-100, no percentage, no grade — and **never** described as
"a silent backend KPI" or "an internal metric", because while the concept exists it gets printed.
The `History.transparency_score` column is gone (history 0237/0238) and
`transparency_calculator.py` returns counts only (2026-11-08); **do not add back** a reader, a
serializer field, a percentage or a nudge. Producer dashboard = COUNTS plus a per-record checklist naming the specific missing
document. Consumer/anonymous payloads = factual evidence only.

## Consumer payload safety
One place decides public claims; a denylist encodes only the last incident. "Demo data" is no
defence on a public endpoint. ⛔ Never auto-populate `omri_product`. Blockchain says "recorded",
never "verified" (`BLOCKCHAIN_ENABLED=False` sets `mock_mode` — a False flag is not a retired
route). Visibility is decided by UNIFORM POLICY, never per-farm choice: privacy toggles yes
(worker-name consent, location disclosure, season publish/unpublish), editorial per-field hide
controls on logged practice records NO — extend the CATEGORICAL policy
(`_CONSUMER_WITHHELD_PRODUCTION_SUBTYPES`, `_CERTIFIER_ONLY_EVENT_FIELDS`) with a written reason
and frontend parity tests instead.

## Domain constants
7 event types: Production(1) / Chemical(2) / General(3) / Equipment(4) / Soil(5) / Pest(6) /
Business(7) / Weather(0); Equipment is merged into Production in the UI.
33 US crops (`_get_crop_type_data()`). ⚠️ "328+ AI templates" is UNSOURCED — do not quote it.
National List classification runs on every save; the drift detector needs `status="active"`,
which a first-year pilot cannot have — two different checks, constantly confused. ⛔ Never fuzzy-
match the National List alias crosswalk. Drift findings are STORED — recompute after deploy.
`Parcel.area` is HECTARES. A certifier is an AGENT, not a cert type.

## Django gotchas
- ⛔ `.exclude(features__key=True)` on a JSONField returns ZERO rows. Exclude by `pk__in`.
- ⛔ `post_save.connect()` with a local closure is garbage-collected unless `weak=False`.
- ⛔ `DEFAULT_FILE_STORAGE` is SILENTLY IGNORED in Django 5.1+ — use `STORAGES`.
- `dev.py` MIDDLEWARE and throttle rates override `base.py` — keep them in sync.
- Auth is pure httpOnly cookie JWT (access 15min, refresh 7-30d, `logged_in` cookie for session
  detection). Every auth endpoint sets cookies; logout blacklists and deletes all of them.
- Redis deferred: `CELERY_TASK_ALWAYS_EAGER=True`; background work uses `threading.Thread(daemon=True)`.
- Anti-enumeration responses are deliberate — a test demanding a distinguishable "user not found"
  is the bug, not the code.
