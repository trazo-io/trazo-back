"""Every piece of periodic work Trazo declares, and what actually runs it.

WHY THIS FILE EXISTS
--------------------
`backend/celery.py` declares eleven entries in `beat_schedule`. The production app spec
(DigitalOcean app `0a91c6a9-5d56-4f7d-9bb9-042bdcd67174`) contains `services:` and no `jobs:` and
no `workers:`, and `REDIS_URL` is not set, so `prod.py` takes the `CELERY_TASK_ALWAYS_EAGER` branch.
Request-triggered `.delay()` calls therefore run inline, which is why nothing looked broken.
Nothing at all runs a beat schedule. None of those eleven has ever fired in production.

Four more tasks claim a schedule in their own docstring and have no beat entry at all, which is a
weaker declaration than the eleven: nothing anywhere, not even a schedule, says when they run.

NEVER: THE OBVIOUS FIX IS A TRAP, AND THIS IS THE POINT OF THE FILE
-------------------------------------------------------------------
Deploying a worker and a beat process would not "turn on what was meant to run". Of the eleven beat
entries, by the classification below: three would publish a claim this product has retired, one
would delete records inside a retention window, and four were written for a product shape that no
longer exists. Two are the real obligations. One is genuine hygiene.

The single worst one is NOT the badge task. It is `generate_nightly_reports`, which writes a
`carbon_score` of 1 to 100 per establishment, every night, derived from an industry average this
product computes about itself, with offsets netted into the numerator. `/api/carbon/reports/` and
`/api/carbon/benchmarks/` are both REGISTERED, `IsAuthenticated`, and absent from
`carbon/tests/test_retired_claim_routes_stay_retired.py`. So unlike the badge task there is no
second gate: the rows would be served the night they are written. The table is empty today only
because nothing has ever run the task.

TRIAGE THE LIST, THEN ADD THE SCHEDULER. That order is not a preference.

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
BEAT = "BEAT"  # an entry in backend/celery.py beat_schedule
COMMAND = "COMMAND"  # a management command, with no beat entry
DOCSTRING_ONLY = "DOCSTRING_ONLY"  # the docstring claims a schedule and nothing declares one

# Why the work exists, which decides what happens to it in triage.
LEGAL = "LEGAL"  # a statute or regulation requires the notice or the deletion
PROMISE = "PROMISE"  # user-visible copy states that this happens
HYGIENE = "HYGIENE"  # internal correctness; nobody outside is told
CLAIM_RISK = "CLAIM_RISK"  # NEVER: running it would publish a claim Trazo has retired
RETENTION_RISK = "RETENTION_RISK"  # NEVER: running it would delete inside a required window
VESTIGIAL = "VESTIGIAL"  # written for a product shape that no longer exists


PERIODIC_WORK = {
    # --- Legal obligations. The reason this file is not a cleanup ticket. ---
    "send-renewal-reminders": {
        "source": BEAT,
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
        "source": BEAT,
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
    "generate-nightly-reports": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": CLAIM_RISK,
        "note": (
            "THE WORST ONE, and it was first classified here as hygiene, wrongly. It writes "
            "CarbonReport.carbon_score, an IntegerField validated 0 to 100 and labelled 'Score "
            "from 1 to 100', for EVERY establishment, EVERY night. The score is "
            "100 * (1 - net_footprint / industry_average), so it is (a) a self-assigned 0-100 "
            "grade, the artefact retired as a CONCEPT, (b) COMPARATIVE against an average this "
            "product computes about itself, and (c) computed on net_footprint, which nets OFFSETS "
            "out of emissions, the exact netting already banned on consumer surfaces. "
            "NEVER: unlike the badge task there is NO SECOND GATE. /api/carbon/reports/ is "
            "REGISTERED in carbon/urls.py, permission_classes = [IsAuthenticated], carbon_score is "
            "in the serializer fields, and the route is NOT in "
            "carbon/tests/test_retired_claim_routes_stay_retired.py. Rows would be served the night "
            "they are written, and an authenticated reader is not a safe reader. Cut the score, or "
            "cut the task."
        ),
    },
    "update-industry-benchmarks": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": CLAIM_RISK,
        "note": (
            "Also first classified as hygiene, wrongly. It writes CarbonBenchmark.average_emissions "
            "per industry from Trazo's OWN CarbonEntry rows, and /api/carbon/benchmarks/ is "
            "registered and IsAuthenticated. Two problems that compound: it is the DENOMINATOR of "
            "the score above, so scheduling it arms that task; and with zero real users the "
            "'industry average' would be computed from demo and test data, which makes it a "
            "fabricated comparative baseline rather than a thin one. Cut it with the score."
        ),
    },
    "award-sustainability-badges": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": CLAIM_RISK,
        "note": (
            "Computes a carbon score per establishment and writes SustainabilityBadge rows: a "
            "self-assigned sustainability grade, the self-created-label class EU ECGT 2024/825 "
            "bans without third-party verification. NEVER: cut the task. "
            "NOTE: two gates are closed here, unlike the report task, and they COMPOUND rather "
            "than back each other up. The route is unregistered (carbon/urls.py:26-43, guarded by "
            "carbon/tests/test_retired_claim_routes_stay_retired.py) and no rows exist. That "
            "2026-09-07 decision deliberately KEPT the models and cut only the route, on the "
            "reasoning that the route is the part someone rediscovers and wires into a surface by "
            "accident. So the EMPTY TABLE is doing safety work: an accidental re-registration "
            "today serves nothing, whereas scheduling this first would populate the table and turn "
            "that same accident into a grade served for every establishment."
        ),
    },
    "cleanup-old-audit-logs": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": RETENTION_RISK,
        "note": (
            "Third one first classified as hygiene, wrongly, and it fails in the opposite "
            "direction to the others: running it DESTROYS data rather than publishing a claim. It "
            "deletes CarbonAuditLog older than ONE year. Those rows are the create/update/delete/"
            "verify trail on CarbonEntry, CarbonCertification and CarbonReport, which back organic "
            "records, and 7 CFR 205.103(b)(4) requires records maintained not less than FIVE years "
            "beyond creation, with (b)(2) requiring detail sufficient to be audited. A one-year "
            "purge sits inside that window. Decide the retention period against the reg before "
            "scheduling this, and never inherit the 365 in the code as if it were considered."
        ),
    },
    # --- Written for a product that no longer exists. Cut, do not schedule. ---
    "reset-monthly-scan-counts": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": VESTIGIAL,
        "note": (
            "Resets subscription scan_count monthly, for a quota that no longer exists: "
            "create_plans.py lists monthly_scan_limit in RETIRED_FEATURE_KEYS, described there as "
            "a feature key that no longer exists anywhere in the product. Classified as hygiene on "
            "the first pass by reading the task name instead of the plan seeder."
        ),
    },
    "expire-starter-trials": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": VESTIGIAL,
        "note": "Starter is free forever: no card, no clock, no trial. There is nothing to expire.",
    },
    "send-trial-lifecycle-emails": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": VESTIGIAL,
        "note": (
            "Emails keyed to a trial_end date that no plan has. Migration 0015 exists because a "
            "phantom trial claim survived once already, so this is the second time the same dead "
            "concept has been found still wired up."
        ),
    },
    "batch-submit-monthly-summaries": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": VESTIGIAL,
        "note": (
            "Blockchain monthly reconciliation. It selects companies with an ACTIVE BLOCKCHAIN "
            "SUBSCRIPTION, and blockchain-verification is is_active=False and withdrawn, so the "
            "query cannot match. NOTE: that makes it empty rather than disabled, which is the "
            "weaker of the two. A flag being False is not a retired route."
        ),
    },
    # --- Genuine hygiene. Real work, nothing outside depends on its timing. ---
    "reverify-certifications-monthly": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": HYGIENE,
        "note": (
            "Monthly batch re-verification of active certifications against the registries. "
            "Findings are STORED rather than recomputed on read, so they go stale silently rather "
            "than loudly, which is the argument for scheduling this one early once the list is "
            "triaged. The only one of the eleven that should simply be turned on."
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
        "source": COMMAND,
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
MUST_BE_TRIAGED_BEFORE_A_SCHEDULER_EXISTS = frozenset(
    key for key, spec in PERIODIC_WORK.items() if spec["kind"] in (CLAIM_RISK, RETENTION_RISK)
)
