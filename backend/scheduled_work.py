"""Every piece of periodic work Trazo declares, and what actually runs it.

WHAT WAS WRONG, AND WHAT IS LEFT
--------------------------------
`backend/celery.py` once declared ELEVEN entries in `beat_schedule`, and nothing ran a single one of
them. The production app spec (DigitalOcean app `0a91c6a9-5d56-4f7d-9bb9-042bdcd67174`) contains
`services:` and no `jobs:` and no `workers:`, and `REDIS_URL` is not set, so `prod.py` takes the
`CELERY_TASK_ALWAYS_EAGER` branch. Request-triggered `.delay()` calls run inline, which is why
nothing ever looked broken. None of the eleven had ever fired in production.

Four further tasks claim a cadence in their own docstring and appear in no schedule at all, which is
a WEAKER declaration than a beat entry, not a stronger one: nothing runs them and nothing even says
when they should. They are the `DOCSTRING_ONLY` rows below, and the first version of this file missed
all four because it only compared `beat_schedule` to this registry.

NEVER: SCHEDULING WAS THE TRAP, AND THIS IS STILL THE POINT OF THE FILE
-----------------------------------------------------------------------
Deploying a worker and a beat process would not have "turned on what was meant to run". It would have
STARTED three tasks that wrote a self-assigned grade and one that deleted an audit trail inside a
retention window. So the list was triaged FIRST, on 2026-09-30, and only then given a scheduler:

  * DELETED: `generate_nightly_reports`, `update_industry_benchmarks`, `award_sustainability_badges`.
    The first was the worst of the eleven and was initially classified here as harmless hygiene. It
    wrote `CarbonReport.carbon_score`, 0 to 100, per establishment, nightly, against an industry
    average this product computed about itself, on a figure that netted offsets out of emissions. The
    badge task at least had its route cut in 2026-09-07; `/api/carbon/reports/` and
    `/api/carbon/benchmarks/` were both live, so there was no second gate. Both routes are now
    unregistered and guarded, and the `carbon_score` column, index and serializer field are dropped.
  * DELETED: `cleanup_old_audit_logs`, which deleted CarbonAuditLog over an arbitrary 365 days. The
    reasoning is in `carbon/tasks.py` where it used to live.
  * UNSCHEDULED, task kept: `batch_submit_monthly_summaries` and `reset_monthly_scan_counts`. See
    `DELIBERATELY_UNSCHEDULED_AND_WHY`.
  * RECLASSIFIED, not deleted: the two trial tasks. Both were called VESTIGIAL on the first pass and
    both are `NEUTERED` instead: one is a deliberately empty allowlist with a dated rationale, the
    other is live for paid plans and pinned by a CI test with a paid control.

Five beat entries remain, none of them scheduled through Celery. Five pieces of work are dispatched
by `manage.py run_due_maintenance`, defined as App Platform SCHEDULED jobs in `.do/jobs.yaml`.

TRIAGE BEFORE SCHEDULING. That order is not a preference, and the guard enforces it: nothing
classified `CLAIM_RISK` or `RETENTION_RISK` may carry a cadence.

HOW TO USE IT
-------------
Every key in `beat_schedule` must appear in `PERIODIC_WORK`, and every `BEAT` key here must appear
there. Guard: `backend/tests/test_scheduled_work_has_a_runner.py`, which also scans the task modules
as source text for a docstring that claims a schedule, because that is how the four `DOCSTRING_ONLY`
entries below were missed on the first pass.

NEVER: `runner=RUNS` is a claim about production, not about a developer's laptop. Do not set it
until something in the deployed app spec invokes the work.

HOW TO RE-CHECK THE PREMISE, WHICH IS OUT OF BAND
-------------------------------------------------
NOTE: the central fact here lives in the DigitalOcean console, not in this repo, so it can go stale
silently in exactly the way these tasks did. No test in this process can see it. Re-check with:

    doctl apps spec get 0a91c6a9-5d56-4f7d-9bb9-042bdcd67174 | grep -nE "^jobs:|^workers:|^services:|^functions:"
    doctl apps spec get 0a91c6a9-5d56-4f7d-9bb9-042bdcd67174 | grep -c REDIS_URL

Measured 2026-09-30: `143:services:` and `0`. Two further things no test here can see, so check both
before trusting any of this: `compose.yml` does define a `celery-beat` service, but that is the
local development stack and is not on the DO deploy path; and `django_celery_beat` is installed,
which means a schedule can also live in the DATABASE as a `PeriodicTask` row rather than in
`beat_schedule`. Neither is evidence that anything schedules in production, and neither is visible
from here.
"""

# What invokes this work in production today.
NOTHING = "NOTHING"  # declared, never fires: no beat process and no scheduler exists
RUNS = "RUNS"  # something in the deployed app spec actually invokes it

# Where the declaration lives, weakest last.
JOB = "JOB"  # dispatched by `manage.py run_due_maintenance` from a job in .do/jobs.yaml
BEAT = "BEAT"  # an entry in backend/celery.py beat_schedule. NEVER: should stay at zero
COMMAND = "COMMAND"  # a management command, with no beat entry
DOCSTRING_ONLY = "DOCSTRING_ONLY"  # the docstring claims a schedule and nothing declares one

# Why the work exists, which decides what happens to it in triage.
LEGAL = "LEGAL"  # a statute or regulation requires the notice or the deletion
PROMISE = "PROMISE"  # user-visible copy states that this happens
HYGIENE = "HYGIENE"  # internal correctness; nobody outside is told
CLAIM_RISK = "CLAIM_RISK"  # NEVER: running it would publish a claim Trazo has retired
RETENTION_RISK = "RETENTION_RISK"  # NEVER: running it would delete inside a required window
VESTIGIAL = "VESTIGIAL"  # written for a product shape that no longer exists
NEUTERED = "NEUTERED"  # deliberately reduced to a no-op or a narrow guard, and kept on purpose


PERIODIC_WORK = {
    # --- Legal obligations. The reason this file is not a cleanup ticket. ---
    "send-renewal-reminders": {
        "source": JOB,
        "cadence": "daily",
        "run": "subscriptions.tasks.send_renewal_reminders",
        "runner": NOTHING,
        "kind": LEGAL,
        "note": (
            "CA Automatic Renewal Law as amended by AB 2863, in force 2025-07-01: a retainable "
            "reminder 15 to 45 days before an annual auto-renewal. Compliance ($249/yr) and "
            "Operation ($1,200/yr) are both in scope and the ICP is California and Washington. "
            "send_renewal_reminder_email has exactly one caller, this task, and the Stripe "
            "dispatcher does not handle invoice.upcoming, so there is no other path. Harmless only "
            "while there are zero paying subscribers; the first one makes it live."
        ),
    },
    "gdpr-cleanup-scan-data": {
        "source": JOB,
        "cadence": "daily",
        "command": "cleanup_scan_data",
        "runner": NOTHING,
        "kind": LEGAL,
        "note": (
            "Anonymises consented scans past data_retention_until, deletes non-consented scans "
            "older than 7 days, removes duplicates over 90 days. Three retention promises, no "
            "deleter. NOTE: this is the one task where never having run means data was KEPT that "
            "should have been destroyed, so the exposure grows with every scan."
        ),
    },
    # --- NEVER schedule. Running these is how the incident happens. ---
    # --- Written for a product that no longer exists. Cut, do not schedule. ---
    # --- Genuine hygiene. Real work, nothing outside depends on its timing. ---
    "reverify-certifications-monthly": {
        "source": JOB,
        "cadence": "monthly",
        "run": "certifications.tasks.reverify_all_certifications",
        "runner": NOTHING,
        "kind": HYGIENE,
        "note": (
            "Monthly batch re-verification of active certifications against the registries. "
            "Findings are STORED rather than recomputed on read, so they go stale silently rather "
            "than loudly, which is the argument for scheduling this one early once the list is "
            "triaged. The only one of the eleven that should simply be turned on."
        ),
    },
    "check-national-list-ecfr": {
        "source": JOB,
        "cadence": "monthly",
        "run": "certifications.services.national_list_check.check_national_list_ecfr",
        "runner": NOTHING,
        "kind": HYGIENE,
        "note": (
            "Fetches 7 CFR 205.601/205.602 from the eCFR API, stores a hashed NationalListRevision "
            "and writes one IngestionRun. Read-only against eCFR, append-only here. Triaged "
            "2026-11-02 out of refresh_organic_input_catalogs, whose other three steps re-read "
            "committed CSVs and are not scheduled (see DELIBERATELY_UNSCHEDULED_AND_WHY). A text "
            "change since the last seed_national_list run keeps the job FAILING every month, so "
            "the heartbeat reports it, until a person updates the committed list. Monthly, not "
            "weekly: eCFR republishes Title 7 irregularly, NOSB amendments arrive by Federal "
            "Register rule with an effective date weeks out, and there is no weekly cadence. "
            "Never running means the packet line reads 'never synced', which is true."
        ),
    },
    # --- Declared only in a docstring. Nothing, not even a schedule, says when these run. ---
    "cleanup_processed_webhook_events": {
        "source": DOCSTRING_ONLY,
        "runner": NOTHING,
        "kind": HYGIENE,
        "note": (
            "subscriptions/tasks.py, docstring says 'Scheduled weekly'. It is in no beat schedule. "
            "Purges ProcessedWebhookEvent rows over 90 days, the Stripe idempotency table, so "
            "never running means it only grows. Cost is storage and index size, not correctness."
        ),
    },
    "check_api_key_rotation_status": {
        "source": DOCSTRING_ONLY,
        "runner": NOTHING,
        "kind": PROMISE,
        "note": (
            "carbon/tasks/key_rotation_tasks.py, docstring says it 'Runs daily to monitor key age "
            "and notify when rotation is needed'. It is in no beat schedule. So the key-age "
            "monitoring and the rotation alerts this product believes it has do not exist at any "
            "level, not scheduled and not even declared. Read alongside the open items on "
            "unrotated credentials: nothing was ever going to notice."
        ),
    },
    "validate_all_api_keys": {
        "source": DOCSTRING_ONLY,
        "runner": NOTHING,
        "kind": PROMISE,
        "note": (
            "Same module, docstring says it 'Runs weekly to catch any keys that may have been "
            "revoked'. In no beat schedule. A revoked upstream key would be discovered by a user "
            "hitting the failure, which is the detection path this task exists to replace."
        ),
    },
    "cleanup_old_key_backups": {
        "source": DOCSTRING_ONLY,
        "runner": NOTHING,
        "kind": HYGIENE,
        "note": (
            "Same module. Prunes old API key backups in the secrets manager so they stop "
            "accumulating. No beat entry. Never running means old key material is retained longer "
            "than intended, which is a small exposure rather than a broken feature."
        ),
    },
    # --- Declared as a command, never wired to anything. ---
    "release_stale_field_note_audio": {
        "source": JOB,
        "cadence": "daily",
        "command": "release_stale_field_note_audio",
        "runner": NOTHING,
        "kind": PROMISE,
        "note": (
            "The crew consent notice tells a worker their recording is deleted once the note is "
            "reviewed. Confirm and discard both call the provider's delete inline, so the common "
            "path holds. This command covers what those two miss: a refused note, a note stuck "
            "being read, and a release the provider rejected. Twilio keeps media until it is "
            "deleted through the API, so for those rows the promise is unenforced. NEVER: schedule "
            "it or soften the notice before a crew number is handed to a farm."
        ),
    },
}

# Work whose absence has a named party on the other side. Deleting an entry from here is a decision
# about a statute or about something a person was told, never a cleanup.
MUST_NOT_BE_SILENTLY_DROPPED = frozenset(key for key, spec in PERIODIC_WORK.items() if spec["kind"] in (LEGAL, PROMISE))

# NEVER: scheduling any of these publishes a retired claim or deletes inside a required window. Cut
# the work, or cut what it writes, before any scheduler reaches it.
# Removed from beat_schedule on 2026-09-30, kept here as the record of WHY, because the next
# person to find a bare task with no schedule will otherwise wonder whether it was an oversight.
# NEVER: none of these is a candidate for scheduling.
DELIBERATELY_UNSCHEDULED_AND_WHY = {
    "expire_trials": (
        "Kept, declared nowhere. EXPIRABLE_TRIAL_PLAN_SLUGS is an empty list with a dated 2026-08-13 "
        "rationale: filtering plan__slug='starter' once nulled Company.subscription_plan and 403'd "
        "every creation, locking out the COG Pro refugees October targets. A deliberately empty "
        "allowlist kept for a future Stripe-side trial is not dead code. NEVER: do not delete it and "
        "do not add a catch-all slug."
    ),
    "send_trial_emails": (
        "Kept, declared nowhere, and LIVE for paid plans. Starter has no trial, but a paid plan can "
        "sit in Stripe status 'trialing' with a trial_end, and the task guards Starter specifically. "
        "subscriptions/tests/test_starter_is_free_forever.py::"
        "test_starter_never_receives_trial_expiry_emails pins it with a paid control asserting "
        "day_11 == 1, and records that a Starter-only assertion passed with the guard deleted. "
        "NEVER: deleting the task would delete a live path and the guard proving it excludes Starter."
    ),
    "refresh_organic_input_catalogs (seed steps)": (
        "Command kept, run by hand after a deploy that changes certifications/data/*_seed.csv. "
        "seed_omri_minimal, seed_wsda_materials and seed_cdfa_oim read committed files, so a cron "
        "re-applies an unchanged edition and writes IngestionRun(status='ok'), which the certifier "
        "packet prints as 'Input catalogs last synced: OMRI <today>' for a list transcribed months "
        "earlier. Triaged 2026-11-02: re-running them is stable (no duplicates, no deleted or "
        "re-keyed row, OSP citations intact, certifications/tests/test_catalog_refresh_rerun.py), "
        "so the reason is the false freshness date, not data damage. Only the eCFR step is "
        "scheduled, as check-national-list-ecfr."
    ),
    "generate_nightly_reports": "DELETED. Wrote CarbonReport.carbon_score, 0-100, per establishment, nightly.",
    "update_industry_benchmarks": "DELETED. Wrote the denominator of that score from Trazo's own rows.",
    "award_sustainability_badges": "DELETED. Wrote SustainabilityBadge rows. Same class.",
    "batch_submit_monthly_summaries": (
        "Task kept, beat entry removed. Selects companies with an active blockchain subscription and "
        "that add-on is is_active=False, so the query cannot match. Shares "
        "_submit_single_production_to_blockchain with the immediate path, which is why it survives."
    ),
    "reset_monthly_scan_counts": (
        "Task and command kept, beat entry removed. Resets Subscription.scan_count, which the API "
        "does not read: SubscriptionSerializer._compute_scan_count counts HistoryScan rows from "
        "current_period_start. The real dead thing is the column, and dropping it is a migration."
    ),
}

# Work the scheduled jobs in `.do/jobs.yaml` actually dispatch, via
# `manage.py run_due_maintenance --cadence <c>`. An entry earns a `cadence` only once something is
# meant to run it; `runner` stays NOTHING until the job exists in the live app spec, because that is
# a fact about production and no test here can see it.
DISPATCHED_BY_CADENCE = {
    cadence: frozenset(key for key, spec in PERIODIC_WORK.items() if spec.get("cadence") == cadence)
    for cadence in ("daily", "monthly")
}

MUST_BE_TRIAGED_BEFORE_A_SCHEDULER_EXISTS = frozenset(
    key for key, spec in PERIODIC_WORK.items() if spec["kind"] in (CLAIM_RISK, RETENTION_RISK)
)
