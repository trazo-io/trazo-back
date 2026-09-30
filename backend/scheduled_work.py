"""Every piece of periodic work Trazo declares, and what actually runs it.

WHY THIS FILE EXISTS
--------------------
`backend/celery.py` declares eleven entries in `beat_schedule`. The production app spec
(DigitalOcean app `0a91c6a9-5d56-4f7d-9bb9-042bdcd67174`) contains `services:` and **no `jobs:` and
no `workers:`**, and `REDIS_URL` is not set, so `prod.py` takes the `CELERY_TASK_ALWAYS_EAGER`
branch. Request-triggered `.delay()` calls therefore run inline, which is why nothing looked broken.
**Nothing at all runs a beat schedule.** None of those eleven has ever fired in production.

Two of them are legal obligations. `send_renewal_reminders` carries a docstring explaining that
California's Automatic Renewal Law as amended by AB 2863 wants a retainable reminder 15 to 45 days
before an annual auto-renewal, and explaining why Stripe's `invoice.upcoming` was rejected for it
(its default lead time is 3 days, outside the window). The reasoning is right and the mechanism is
absent. `gdpr_cleanup_scan_data` is the retention half of the same class.

NEVER: **SO THE OBVIOUS FIX IS A TRAP.** Adding a worker and a beat process today would not "turn on
what was meant to run". It would start `award_sustainability_badges`, which computes a score per
establishment and writes `SustainabilityBadge` rows: a self-assigned sustainability grade, which is
the exact artefact retired as a concept and the label class EU ECGT 2024/825 targets. It would also
start two tasks written for Starter trials, and Starter has no trial. **Triage the list first, then
add the scheduler.** That order is the whole point of this file.

HOW TO USE IT
-------------
Every key in `beat_schedule` must appear in `PERIODIC_WORK`, and every key here must appear there,
except entries whose `source` is `COMMAND` (a management command with no beat entry at all). The
guard is `backend/tests/test_scheduled_work_has_a_runner.py`. Adding periodic work without deciding
what runs it now fails a test instead of quietly never running.

NEVER: `runner=RUNS` is a claim about production, not about a developer's laptop. Do not set it until
something in the deployed app spec invokes the work.
"""

# What invokes this work in production today.
NOTHING = "NOTHING"  # declared, never fires: no beat process and no scheduler exists
RUNS = "RUNS"  # something in the deployed app spec actually invokes it

# Where the declaration lives.
BEAT = "BEAT"  # an entry in backend/celery.py beat_schedule
COMMAND = "COMMAND"  # a management command, with no beat entry

# Why the work exists, which decides what happens to it in triage.
LEGAL = "LEGAL"  # a statute or regulation requires the notice or the deletion
PROMISE = "PROMISE"  # user-visible copy states that this happens
HYGIENE = "HYGIENE"  # internal correctness; nobody outside is told
CLAIM_RISK = "CLAIM_RISK"  # NEVER: running it would publish a claim Trazo has retired
VESTIGIAL = "VESTIGIAL"  # written for a product shape that no longer exists


PERIODIC_WORK = {
    # --- Legal obligations. These are the reason this file is not a cleanup ticket. ---
    "send-renewal-reminders": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": LEGAL,
        "note": (
            "CA Automatic Renewal Law as amended by AB 2863, in force 2025-07-01: a retainable "
            "reminder 15 to 45 days before an annual auto-renewal. Compliance ($249/yr) and "
            "Operation ($1,200/yr) are both in scope and the ICP is California and Washington. "
            "Harmless only while there are zero paying subscribers; the first one makes it live."
        ),
    },
    "gdpr-cleanup-scan-data": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": LEGAL,
        "note": "Retention deletion for consumer scan data. A retention promise with no deleter.",
    },
    # --- NEVER: Do not schedule. Running these would create the incident. ---
    "award-sustainability-badges": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": CLAIM_RISK,
        "note": (
            "Computes a carbon score per establishment and writes SustainabilityBadge rows. That is "
            "a self-assigned sustainability grade: retired as a CONCEPT, not hidden, and the "
            "self-created-label class EU ECGT 2024/825 bans without third-party verification. It "
            "has produced no badges only because nothing has ever run it. NEVER: Cut the task, do not "
            "schedule it."
        ),
    },
    "batch-submit-monthly-summaries": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": VESTIGIAL,
        "note": (
            "Blockchain monthly submission. BLOCKCHAIN_ENABLED is False and the add-on is "
            "withdrawn. NEVER: A flag being False is not a retired route: this is a route."
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
        "note": "Same: emails about a trial end date that no plan has. Migration 0015 exists "
        "because a phantom trial claim survived once already.",
    },
    # --- Hygiene. Real work, nothing depends on it being timely. ---
    "reset-monthly-scan-counts": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": HYGIENE,
        "note": (
            "Zeroes the monthly QR scan counters. Never having run means counters accumulate "
            "forever, so any per-month figure read off them is a lifetime total wearing a "
            "monthly label. Nothing bills on it today, so nobody has been overcharged."
        ),
    },
    "generate-nightly-reports": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": HYGIENE,
        "note": (
            "Nightly carbon aggregation. NOTE: Check what it writes before scheduling it: anything "
            "that lands a derived number on a consumer-reachable surface is the same class of "
            "problem as the badge task below."
        ),
    },
    "cleanup-old-audit-logs": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": HYGIENE,
        "note": (
            "Prunes audit log rows. Never having run means the table only grows, which costs "
            "storage and nothing else. NOTE: Confirm no retention policy anywhere promises this "
            "deletion before treating it as hygiene rather than a promise."
        ),
    },
    "update-industry-benchmarks": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": HYGIENE,
        "note": "Benchmark refresh. NOTE: Check what it publishes before scheduling it.",
    },
    "reverify-certifications-monthly": {
        "source": BEAT,
        "runner": NOTHING,
        "kind": HYGIENE,
        "note": (
            "Re-verification against the registries. Drift findings are STORED, so they go stale "
            "silently rather than loudly, which is the argument for scheduling this one early."
        ),
    },
    # --- Declared as a command, never wired to anything. ---
    "release_stale_field_note_audio": {
        "source": COMMAND,
        "runner": NOTHING,
        "kind": PROMISE,
        "note": (
            "The crew consent notice tells a worker their recording is deleted once the note is "
            "reviewed. Confirm and discard both call the provider's delete, so the common path "
            "holds. This command covers what those two miss: a refused note, a note stuck being "
            "read, and a release the provider rejected. Twilio keeps media until it is deleted "
            "through the API, so for those rows the promise is currently unenforced. NEVER: Schedule it "
            "or soften the notice before a crew number is handed to a farm."
        ),
    },
}

# Work whose absence has a named party on the other side. Deleting an entry from here is a decision
# about a statute or about something a person was told, never a cleanup.
MUST_NOT_BE_SILENTLY_DROPPED = frozenset(key for key, spec in PERIODIC_WORK.items() if spec["kind"] in (LEGAL, PROMISE))
