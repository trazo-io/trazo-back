"""A beat entry with no runner must be a decision, not an accident.

Eleven tasks sat in `beat_schedule` with nothing in the deployed app spec to run them, including
the California ARL renewal reminder, whose own docstring explains why a scheduled task was chosen
over Stripe's `invoice.upcoming`. The reasoning was right; the mechanism was never deployed. Nothing
failed, because a schedule nobody reads produces silence and silence looks like success.

These tests make the next one loud. They do NOT assert that the work runs, which no test in this
process can know. They assert that every declared piece of periodic work has been LOOKED AT and
carries a written answer to "what runs this", so adding a twelfth means editing
`backend/scheduled_work.py` on purpose.
"""

from django.test import SimpleTestCase

from backend.celery import celery_app
from backend.scheduled_work import BEAT, CLAIM_RISK, COMMAND, MUST_NOT_BE_SILENTLY_DROPPED, NOTHING, PERIODIC_WORK, RUNS


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
            "recorded what runs them: "
            f"{sorted(missing)}. Add each one with a runner and a note. If the answer is NOTHING, "
            "say so: that is the whole point of the file.",
        )

    def test_a_registered_beat_entry_must_still_exist(self):
        stale = self.registered_beat - self.beat_keys
        self.assertEqual(
            stale,
            set(),
            "These entries are registered but are no longer in beat_schedule: "
            f"{sorted(stale)}. If the task was deliberately cut, delete its row too, and check it "
            "is not in MUST_NOT_BE_SILENTLY_DROPPED first.",
        )


class EveryEntryCarriesAnAnswer(SimpleTestCase):
    def test_every_entry_has_a_runner_a_kind_and_a_reason(self):
        for key, spec in PERIODIC_WORK.items():
            with self.subTest(work=key):
                self.assertIn(spec["source"], (BEAT, COMMAND))
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
    """NEVER: The trap this file exists to stop.

    The intuitive repair for "nothing runs the beat schedule" is to deploy a worker and a beat
    process. That would start `award_sustainability_badges`, which computes a score and writes
    badge rows: a self-assigned sustainability grade, retired as a concept and the label class
    ECGT 2024/825 bans. It has published nothing only because nothing has ever run it.

    So a claim-risky task must never be marked RUNS. Triage it out first.
    """

    def test_no_claim_risk_task_is_marked_as_running(self):
        running_claim_risks = [
            key for key, spec in PERIODIC_WORK.items() if spec["kind"] == CLAIM_RISK and spec["runner"] == RUNS
        ]
        self.assertEqual(
            running_claim_risks,
            [],
            "A task whose output is a retired claim was marked as running in production: "
            f"{running_claim_risks}. Cut the task instead. Scheduling it is how the badge ships.",
        )

    def test_the_badge_task_is_still_flagged(self):
        """Pins the specific one, so deleting the flag needs deleting the task."""
        spec = PERIODIC_WORK.get("award-sustainability-badges")
        if spec is None:
            return  # cut, which is the outcome this test wants
        self.assertEqual(spec["kind"], CLAIM_RISK)
        self.assertEqual(spec["runner"], NOTHING)
