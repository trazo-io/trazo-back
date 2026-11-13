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
    JOB,
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


class BeatScheduleStaysEmpty(SimpleTestCase):
    """The strongest form of the original finding.

    Eleven entries lived in `beat_schedule` and nothing ran any of them. Rather than leave a schedule
    that lies, it is empty and the work is dispatched by an App Platform SCHEDULED job. Keeping it
    empty also removes a double-declaration hazard: the job-dispatched work was briefly declared in
    BOTH places, so anyone who later deployed a beat process would have had every item run twice a
    day, which for the ARL notice means a subscriber told twice.
    """

    def test_beat_schedule_is_empty(self):
        self.assertEqual(
            dict(celery_app.conf.beat_schedule),
            {},
            "An entry was added to beat_schedule. Nothing runs a beat process in production, so it "
            "declares work that does not happen; and if one is ever deployed, anything also "
            "dispatched by run_due_maintenance runs twice. Give it a cadence in "
            "backend/scheduled_work.py instead.",
        )

    def test_no_entry_still_claims_to_be_a_beat_entry(self):
        stale = sorted(key for key, spec in PERIODIC_WORK.items() if spec["source"] == BEAT)
        self.assertEqual(stale, [], f"These claim source=BEAT and beat_schedule is empty: {stale}")


class EveryBeatEntryIsAccountedFor(SimpleTestCase):
    """Kept for if anyone re-adds a beat entry: the two lists guard each other both ways."""

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
                self.assertIn(spec["source"], (JOB, BEAT, COMMAND, DOCSTRING_ONLY))
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


class TheJobsFragmentMatchesTheRegistry(SimpleTestCase):
    """`.do/jobs.yaml` is the only repo-visible statement of what runs.

    The live app spec cannot be committed: `doctl apps spec get` returns environment variable
    VALUES, and 36 of this app's 38 are stored plaintext rather than type SECRET, so the real spec
    holds live credentials. The fragment carries the reviewable half. These tests keep it honest
    against the registry, which is the pair that rotted last time.
    """

    def setUp(self):
        import yaml

        path = REPO / ".do" / "jobs.yaml"
        self.assertTrue(path.is_file(), f"{path} is missing; step 4 of the scheduling fix is undone")
        self.spec = yaml.safe_load(path.read_text())
        self.jobs = self.spec["jobs"]

    def test_every_cadence_in_use_has_a_job(self):
        cadences = {spec["cadence"] for spec in PERIODIC_WORK.values() if spec.get("cadence")}
        commands = " ".join(job.get("run_command", "") for job in self.jobs)
        for cadence in sorted(cadences):
            with self.subTest(cadence=cadence):
                self.assertIn(
                    f"--cadence {cadence}",
                    commands,
                    f"work is registered with cadence={cadence!r} and no job in .do/jobs.yaml runs "
                    "it, so it is registered and still never runs.",
                )

    def test_every_job_is_scheduled_and_carries_a_cron(self):
        for job in self.jobs:
            with self.subTest(job=job.get("name")):
                self.assertEqual(job.get("kind"), "SCHEDULED")
                self.assertTrue(job.get("schedule", {}).get("cron"), "a SCHEDULED job needs a cron")
                self.assertTrue(
                    job.get("schedule", {}).get("time_zone"),
                    "set the time zone explicitly: the renewal notice is read by a person in a "
                    "specific place, and UTC drifts an hour against them twice a year",
                )

    def test_no_job_invokes_poetry(self):
        """The bug this guard exists for, found reading the fragment back against the Dockerfile.

        Production builds from `/Dockerfile`: `python:3.12-slim` installing with
        `pip install -r requirements.txt`. There is no poetry binary in the image, so a
        `poetry run ...` command fails with "poetry: not found" on every run. CLAUDE.md's "always
        use Poetry" is a rule about LOCAL development and reads like it applies here, which is
        exactly why this needs a test rather than a comment.
        """
        for job in self.jobs:
            with self.subTest(job=job.get("name")):
                self.assertNotIn(
                    "poetry",
                    job.get("run_command", ""),
                    "there is no poetry in the production image; call `python manage.py ...` directly",
                )

    def test_every_job_builds_the_same_image_as_the_service(self):
        """A job omitting dockerfile_path sends App Platform to buildpack detection."""
        self.assertTrue(
            (REPO / "Dockerfile").is_file(),
            "the fragment claims dockerfile_path: /Dockerfile and there is no Dockerfile",
        )
        for job in self.jobs:
            with self.subTest(job=job.get("name")):
                self.assertEqual(job.get("dockerfile_path"), "/Dockerfile")
                self.assertEqual(job.get("source_dir"), "/")
                self.assertTrue(
                    job.get("github", {}).get("deploy_on_push"),
                    "the trazo-back service is deploy_on_push: true, so a job at false would keep "
                    "running stale code after a push while the service ran the new code",
                )

    def test_every_job_runs_a_command_django_can_find(self):
        from django.core.management import get_commands

        available = get_commands()
        for job in self.jobs:
            cmd = job.get("run_command", "")
            with self.subTest(job=job.get("name")):
                self.assertIn("manage.py", cmd, "a maintenance job runs a management command")
                name = cmd.split("manage.py", 1)[1].split()[0]
                self.assertIn(name, available, f"{name!r} is not a discoverable management command")

    def test_a_job_never_runs_a_cadence_nothing_is_registered_for(self):
        """A job that runs nothing reports success forever, which is the bug in miniature."""
        registered = {spec["cadence"] for spec in PERIODIC_WORK.values() if spec.get("cadence")}
        for job in self.jobs:
            cmd = job.get("run_command", "")
            for cadence in ("daily", "monthly", "weekly", "hourly"):
                if f"--cadence {cadence}" in cmd:
                    with self.subTest(job=job.get("name")):
                        self.assertIn(cadence, registered, f"{job.get('name')} runs an empty cadence")


class EveryDispatchTargetResolves(SimpleTestCase):
    """A typo'd target would fail at 08:30 rather than in CI."""

    def test_named_management_commands_exist(self):
        from django.core.management import get_commands

        available = get_commands()
        for key, spec in PERIODIC_WORK.items():
            if not spec.get("command"):
                continue
            with self.subTest(work=key):
                self.assertIn(
                    spec["command"],
                    available,
                    f"{key} dispatches management command {spec['command']!r}, which Django does not "
                    "discover. NOTE: `backend` is not in INSTALLED_APPS, so a command placed there "
                    "is invisible.",
                )

    def test_named_callables_import(self):
        from django.utils.module_loading import import_string

        for key, spec in PERIODIC_WORK.items():
            if not spec.get("run"):
                continue
            with self.subTest(work=key):
                self.assertTrue(callable(import_string(spec["run"])), f"{key}: {spec['run']} is not callable")

    def test_the_dangerous_set_is_currently_empty(self):
        """NOTE: this is what makes the two tripwires above non-vacuous.

        All three CLAIM_RISK tasks and the one RETENTION_RISK task were DELETED on 2026-09-30, so
        `MUST_BE_TRIAGED_BEFORE_A_SCHEDULER_EXISTS` is empty and every assertion keyed off it passes
        trivially. That is the state we want and it is indistinguishable from a broken guard, so
        assert the emptiness directly: this test fails the moment someone adds work that writes a
        retired claim or deletes inside a retention window, which is when the tripwires start
        mattering again.
        """
        self.assertEqual(
            set(MUST_BE_TRIAGED_BEFORE_A_SCHEDULER_EXISTS),
            set(),
            "New CLAIM_RISK or RETENTION_RISK work appeared: "
            f"{sorted(MUST_BE_TRIAGED_BEFORE_A_SCHEDULER_EXISTS)}. That is allowed, but it means the "
            "tripwires in this class are live again. Read their notes, confirm the entry has no "
            "cadence and is not marked RUNS, then update this test's expectation deliberately.",
        )

    def test_every_dispatched_item_has_exactly_one_target(self):
        """An entry with a cadence and no target passed every other test and failed at 08:30."""
        for key, spec in PERIODIC_WORK.items():
            if not spec.get("cadence"):
                continue
            with self.subTest(work=key):
                targets = [t for t in ("command", "run") if spec.get(t)]
                self.assertEqual(
                    len(targets),
                    1,
                    f"{key} is dispatched and names {targets or 'nothing'}. It needs exactly one of "
                    "'command' (a management command) or 'run' (a dotted callable).",
                )

    def test_every_registered_cadence_is_one_the_command_accepts(self):
        """The registry could otherwise declare a cadence --cadence rejects at startup."""
        from common.management.commands.run_due_maintenance import CADENCES

        for key, spec in PERIODIC_WORK.items():
            cadence = spec.get("cadence")
            if not cadence:
                continue
            with self.subTest(work=key):
                self.assertIn(
                    cadence,
                    CADENCES,
                    f"{key} declares cadence={cadence!r}, which run_due_maintenance would refuse. "
                    "Add it to CADENCES and give it a job, or use one that exists.",
                )

    def test_nothing_dangerous_is_dispatched(self):
        """A CLAIM_RISK or RETENTION_RISK entry must never acquire a cadence."""
        dispatched = sorted(k for k in MUST_BE_TRIAGED_BEFORE_A_SCHEDULER_EXISTS if PERIODIC_WORK[k].get("cadence"))
        self.assertEqual(
            dispatched,
            [],
            f"These are dispatched by a scheduled job: {dispatched}. Each publishes a retired claim "
            "or deletes inside a required retention window. Cut the work, not the classification.",
        )

    def test_every_item_with_a_named_party_is_dispatched_or_says_why_not(self):
        """The two LEGAL items and the crew audio promise are the reason any of this exists."""
        for key in (
            "send-renewal-reminders",
            "gdpr-cleanup-scan-data",
            "release_stale_field_note_audio",
            "purge_closure_exports",
            "backup_database_offsite",
        ):
            with self.subTest(work=key):
                self.assertTrue(
                    PERIODIC_WORK[key].get("cadence"),
                    f"{key} has a statute or a person on the other side and no cadence, so nothing " "dispatches it.",
                )
