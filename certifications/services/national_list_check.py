"""The scheduled eCFR check of 7 CFR 205.601/205.602, and the record a person reads after it.

WHY ONLY THIS STEP IS SCHEDULED
-------------------------------
`refresh_organic_input_catalogs` runs four steps. Three of them (OMRI, WSDA, CDFA OIM) read CSV
files committed to this repository, so their input changes only when code is deployed. Running
them on a cron re-applies the same file: no new information, and each run writes an
`IngestionRun(status="ok")` that the certifier packet prints as "Input catalogs last synced:
OMRI <today>", a freshness date for a catalogue that is still the edition transcribed months
earlier. They are post-deploy work, recorded in `backend/scheduled_work.py`
(`DELIBERATELY_UNSCHEDULED_AND_WHY`). The eCFR step is the only one that reads something outside
the repository, so it is the only one a schedule can make more current.

A DRIFT STAYS VISIBLE UNTIL A PERSON CLEARS IT
----------------------------------------------
`sync_national_list_ecfr` compares each fetch to the PREVIOUS fetch. On its own that makes a
regulation change visible for exactly one run: the next month's fetch matches the changed text,
reads "unchanged", and the drift disappears while `seed_national_list.py` still carries the old
list. So the status written here compares against the last REVIEW instead. A review is a run of
`manage.py seed_national_list`, which records `IngestionRun(source="national_list_seed")`; any
change eCFR showed after that run keeps this check at "changed", every month, until the committed
list has been reviewed and re-seeded.

NEVER: the first snapshot a database ever stores is a baseline, not a change, even though
`sync_national_list_ecfr` marks it `change_detected=True` (it has no predecessor). It is excluded
below. The limit that follows, and that no code here can close: a change that landed on eCFR
BEFORE the first snapshot is not detected by this check. The committed list says it was taken from
the eCFR text of 2026-04-13.

UNTIL THE FIRST REVIEW IS RECORDED, ONLY THE LATEST FETCH COUNTS. `seed_national_list` started
writing its review row on 2026-11-02, so a database seeded before then has none, and its older
revisions may carry `change_detected=True` for reasons nobody can now reconstruct (the 2026-08-09
section-slicing fix changed every hash without the regulation changing). Treating all of them as
unreviewed would fail the first scheduled run on history, not on a change. So with no review on
record, a change is reported only when the newest fetch shows it, and the message says to record a
review; stickiness starts with the first `seed_national_list` run. After deploying this, run it
once (it is idempotent and already step 5 of the production runbook).

HOW A PERSON FINDS OUT
----------------------
Three places, none of them new infrastructure:
  * the `IngestionRun` admin, status "Changed - review committed seed", with the sections and the
    date each change was first seen in `message`;
  * the scheduled job FAILS (`check_national_list_ecfr` raises), so `run_due_maintenance` pings the
    heartbeat's `/fail` endpoint and the monthly job exits non-zero, every month until reviewed;
  * the certifier packet's catalog line names the National List as not confirmed current instead
    of printing a "last synced" date (`AuditExportService._catalog_freshness_line`).
"""

import logging
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

logger = logging.getLogger(__name__)

SOURCE = "national_list_ecfr"
REVIEW_SOURCE = "national_list_seed"
SECTIONS = ("205.601", "205.602")


def unreviewed_changes():
    """{section: first revision showing a change since the last review}, empty when none."""
    from certifications.models import IngestionRun, NationalListRevision

    last_review = IngestionRun.objects.filter(source=REVIEW_SOURCE, status="ok").order_by("-ran_at").first()
    found = {}
    for section in SECTIONS:
        revisions = NationalListRevision.objects.filter(cfr_section=section)
        baseline = revisions.order_by("fetched_at", "pk").first()
        if baseline is None:
            continue
        if last_review is None:
            newest = revisions.order_by("-fetched_at", "-pk").first()
            if newest.pk != baseline.pk and newest.change_detected:
                found[section] = newest
            continue
        changes = revisions.filter(change_detected=True).exclude(pk=baseline.pk)
        if last_review is not None:
            changes = changes.filter(fetched_at__gt=last_review.ran_at)
        first_change = changes.order_by("fetched_at", "pk").first()
        if first_change is not None:
            found[section] = first_change
    return found


def record_national_list_check():
    """Fetch the live text, store the revision, and write exactly one IngestionRun.

    A failed fetch is recorded as `status="error"` and then RE-RAISED, so each caller decides
    whether a failure stops it. The orchestrator swallows it (a transient eCFR outage must not fail
    a deploy step); the scheduled entry point lets it propagate to the heartbeat.
    """
    from certifications.models import IngestionRun

    buf = StringIO()
    try:
        call_command("sync_national_list_ecfr", stdout=buf)
        output = buf.getvalue().strip()
        pending = unreviewed_changes()
        reviewed_before = IngestionRun.objects.filter(source=REVIEW_SOURCE, status="ok").exists()
    except Exception as exc:
        # Any failure before the outcome is known, not only the fetch, so the run is never left
        # without a row: the orchestrator relies on this and writes none of its own.
        IngestionRun.objects.create(source=SOURCE, status="error", message=str(exc))
        raise

    if not pending:
        return IngestionRun.objects.create(source=SOURCE, status="unchanged", message=output)

    detail = "; ".join(
        f"§ {section} text changed on eCFR, first seen {revision.fetched_at.date().isoformat()}"
        for section, revision in sorted(pending.items())
    )
    summary = (
        f"UNREVIEWED NATIONAL LIST CHANGE: {detail}. Review "
        "certifications/management/commands/seed_national_list.py against the live text, deploy it, "
        "then run `python manage.py seed_national_list`, which records the review and clears this."
    )
    if not reviewed_before:
        summary += (
            " No review is on record yet, so until that command runs this check only reports a change "
            "the newest fetch shows."
        )
    logger.error(summary)
    return IngestionRun.objects.create(source=SOURCE, status="changed", message=f"{summary}\n\n{output}")


def check_national_list_ecfr():
    """Scheduled entry point, dispatched monthly by `run_due_maintenance` (backend/scheduled_work.py).

    Raises on a failed fetch AND on an unreviewed change. The second is deliberate: App Platform has
    no job-failure alert and this project has no email for operators, so the heartbeat's `/fail`
    ping is the only signal that reaches a person without them going to look.
    """
    run = record_national_list_check()
    if run.status == "changed":
        raise CommandError(run.message.split("\n\n", 1)[0])
    return run
