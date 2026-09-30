"""A schedule with no runner must be a decision, not an accident.

Eleven tasks sat in `beat_schedule` with nothing in the deployed app spec to run them, including
the California ARL renewal reminder, whose own docstring explains why a scheduled task was chosen
over Stripe's `invoice.upcoming`. The reasoning was right; the mechanism was never deployed. Nothing
failed, because a schedule nobody reads produces silence and silence looks like success.

Then the first version of this guard missed FOUR more, because it only compared `beat_schedule` to
the registry, and those four declare their schedule in a docstring and nowhere else. A docstring
saying "Runs daily" is a weaker claim than a beat entry, not a stronger one, so the scan below reads
the task modules as source text. Source-text assertions are the house pattern for facts no import
can reach (`carbon/tests/test_voice_budget.py` does the same against `carbon/views.py`).

These tests do NOT assert that the work runs, which no test in this process can know. They assert
that every declared piece of periodic work has been LOOKED AT and carries a written answer to "what
runs this", and that nothing classified as dangerous is marked as running.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

from backend.celery import celery_app
from backend.scheduled_work import (
    BEAT,
    CLAIM_RISK,
    COMMAND,
    DOCSTRING_ONLY,
    MUST_BE_TRIAGED_BEFORE_A_SCHEDULER_EXISTS,
    MUST_NOT_BE_SILENTLY_DROPPED,
    NEUTERED,
    NOTHING,
    PERIODIC_WORK,
    RETENTION_RISK,
    RUNS,
)

REPO = Path(__file__).resolve().parents[2]

# Every module that defines Celery tasks. A new one here is the other way this guard can go blind,
# so the list is asserted to exist rather than globbed over silently.
TASK_MODULES = (
    "backend/celery.py",
    "carbon/services/api_key_rotation.py",
    "carbon/tasks.py",
    "carbon/tasks/key_rotation_tasks.py",
    "certifications/tasks.py",
    "history/tasks.py",
    "subscriptions/tasks.py",
)

# A docstring that claims a cadence. Deliberately narrow: it must name a period, so "Generate carbon
# reports" does not match and "Scheduled daily" does.
CLAIMS_A_SCHEDULE = re.compile(
    r"\b(scheduled|runs)\b[^.\n]{0,60}?\b(dail|weekl|monthl|nightl|hour|1st|first of)",
    re.IGNORECASE,
)


class EveryBeatEntryIsAccountedFor(SimpleTestCase):
    """The two lists are each other's guard, in both directions."""

    def setUp(self):
        self.beat_keys = set(celery_app.conf.beat_schedule)
        self.registered_beat = {key for key, spec in PERIODIC_WORK.items() if spec["source"] == BEAT}

    def test_a_new_beat_entry_must_be_registered(self):
        missing = self.beat_keys - self.registered_beat
        self.assertEqual(
            missing,
            set(),
            "These beat_schedule entries are not in backend/scheduled_work.py, so nobody has "
            f"recorded what runs them: {sorted(missing)}. Add each one with a runner and a note. If "
            "the answer is NOTHING, say so: that is the whole point of the file.",
        )

    def test_a_registered_beat_entry_must_still_exist(self):
        stale = self.registered_beat - self.beat_keys
        self.assertEqual(
            stale,
            set(),
            f"These entries are registered but are no longer in beat_schedule: {sorted(stale)}. If "
            "the task was deliberately cut, delete its row too, and check it is not in "
            "MUST_NOT_BE_SILENTLY_DROPPED first.",
        )


class ADocstringClaimingAScheduleCountsAsADeclaration(SimpleTestCase):
    """The miss that the first version of this file shipped.

    Four tasks said "Scheduled weekly" or "Runs daily" in their own docstring and appeared in no
    beat schedule at all. That is the weakest possible declaration: not only does nothing run them,
    nothing even says when they should. They are invisible to a beat-versus-registry comparison, so
    this reads the source.
    """

    def test_the_task_module_list_is_real(self):
        for rel in TASK_MODULES:
            with self.subTest(module=rel):
                self.assertTrue(
                    (REPO / rel).is_file(),
                    f"{rel} is listed in TASK_MODULES and does not exist. If it moved, update the "
                    "list; a stale path makes this guard scan nothing and pass.",
                )

    def test_every_task_claiming_a_cadence_is_registered(self):
        registered = set(PERIODIC_WORK)
        beat_task_paths = {spec["task"].rsplit(".", 1)[-1] for spec in celery_app.conf.beat_schedule.values()}
        unaccounted = []

        for rel in TASK_MODULES:
            source = (REPO / rel).read_text()
            # Each `def name(...)` and the docstring that follows it, up to the next def.
            for match in re.finditer(r"def (\w+)\s*\([^)]*\):\s*(?:\"\"\"(.*?)\"\"\")?", source, re.DOTALL):
                name, doc = match.group(1), match.group(2) or ""
                if not CLAIMS_A_SCHEDULE.search(doc):
                    continue
                if name in registered or name in beat_task_paths:
                    continue
                unaccounted.append(f"{rel}::{name}")

        self.assertEqual(
            unaccounted,
            [],
            "These tasks claim a cadence in their docstring and are in neither beat_schedule nor "
            f"backend/scheduled_work.py: {unaccounted}. A docstring is not a schedule. Register "
            "each one with source=DOCSTRING_ONLY and say what breaks, or delete the claim from the "
            "docstring.",
        )


class EveryEntryCarriesAnAnswer(SimpleTestCase):
    def test_every_entry_has_a_runner_a_kind_and_a_reason(self):
        for key, spec in PERIODIC_WORK.items():
            with self.subTest(work=key):
                self.assertIn(spec["source"], (BEAT, COMMAND, DOCSTRING_ONLY))
                if spec["kind"] == NEUTERED:
                    self.assertEqual(
                        spec["runner"],
                        NOTHING,
                        f"{key} is NEUTERED, a no-op kept on purpose. Marking it RUNS claims the "
                        "no-op is doing work. If it became real work again, change the kind.",
                    )
                self.assertIn(spec["runner"], (NOTHING, RUNS))
                self.assertTrue(spec["kind"], "every entry states why the work exists")
                self.assertGreater(
                    len(spec["note"].strip()),
                    40,
                    "a one-word note is not an answer. Say what breaks if this never runs.",
                )

    def test_work_with_someone_on_the_other_side_is_named(self):
        """A statute or a promise to a person cannot be reclassified quietly."""
        self.assertIn("send-renewal-reminders", MUST_NOT_BE_SILENTLY_DROPPED)
        self.assertIn("gdpr-cleanup-scan-data", MUST_NOT_BE_SILENTLY_DROPPED)
        self.assertIn("release_stale_field_note_audio", MUST_NOT_BE_SILENTLY_DROPPED)


class SchedulingIsNotTheSameAsFixing(SimpleTestCase):
    """NEVER: the trap this file exists to stop.

    The intuitive repair for "nothing runs the beat schedule" is to deploy a worker and a beat
    process. That would start three tasks that write a self-assigned grade and one that deletes an
    audit trail inside the 5-year window at 7 CFR 205.103(b)(4). None of them can be marked as
    running; they have to be triaged out first.
    """

    def test_nothing_dangerous_is_marked_as_running(self):
        running = [key for key in MUST_BE_TRIAGED_BEFORE_A_SCHEDULER_EXISTS if PERIODIC_WORK[key]["runner"] == RUNS]
        self.assertEqual(
            running,
            [],
            f"Marked as running in production: {running}. Each of these publishes a retired claim "
            "or deletes inside a required retention window. Cut the work, or cut what it writes. "
            "Scheduling it is how the incident ships.",
        )

    def test_the_nightly_score_is_the_one_to_remember(self):
        """Pinned by name because it is the finding most likely to be lost.

        It was classified as harmless hygiene on the first pass. It writes a 0-100 grade for every
        establishment nightly, and unlike the badge task its route is registered, so there is no
        second gate behind the scheduler.
        """
        spec = PERIODIC_WORK.get("generate-nightly-reports")
        if spec is None:
            return  # cut, which is the outcome this test wants
        self.assertEqual(spec["kind"], CLAIM_RISK)
        self.assertEqual(spec["runner"], NOTHING)
        self.assertIn("generate-nightly-reports", MUST_BE_TRIAGED_BEFORE_A_SCHEDULER_EXISTS)

    def test_the_badge_task_is_still_flagged(self):
        spec = PERIODIC_WORK.get("award-sustainability-badges")
        if spec is None:
            return  # cut, which is the outcome this test wants
        self.assertEqual(spec["kind"], CLAIM_RISK)
        self.assertEqual(spec["runner"], NOTHING)

    def test_the_audit_log_purge_is_flagged_as_a_retention_risk(self):
        """It fails in the opposite direction to the others: running it destroys data."""
        spec = PERIODIC_WORK.get("cleanup-old-audit-logs")
        if spec is None:
            return
        self.assertEqual(spec["kind"], RETENTION_RISK)
        self.assertEqual(spec["runner"], NOTHING)
