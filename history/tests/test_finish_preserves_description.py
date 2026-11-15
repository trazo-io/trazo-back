"""Finalizing a production must not erase the season description.

`History.finish()` aliases the finish form's "Observations" box onto `description` — the
season header the farmer typed on the Start Production form. It used to do so
unconditionally:

    self.description = history_data.get("observation", "")

Observations is OPTIONAL, and the finish form never pre-loads the existing description into
it, so the box is blank unless the farmer retypes their own text. Every finalization
therefore overwrote `description` with "". `description` ships on PublicHistorySerializer, so
this was silent, consumer-facing data loss on 100% of finishes.

Same class as the 2026-08-12 partial-update description destruction: a write path that treats
"the operator said nothing" as "the operator said empty".

No database needed — `finish()` only reads the dict, assigns attributes and calls `save()`,
which is stubbed. That keeps the guard runnable without Postgres.
"""

import datetime

from django.test import SimpleTestCase
from django.utils import timezone

from history.models import Production


def _finish(history, **overrides):
    """Run History.finish() against an unsaved instance with save() stubbed out."""
    history.save = lambda *args, **kwargs: None  # noqa: ARG005 - deliberate no-op
    payload = {
        "finish_date": timezone.make_aware(datetime.datetime(2026, 7, 30, 9, 0)),
        "production_amount": 1200,
        "lot_id": "LOT-1",
    }
    payload.update(overrides)
    history.finish(payload, images=[])
    return history


class FinishPreservesDescriptionTests(SimpleTestCase):
    SEASON_NOTE = "2026 Howard Walnut Season - Block 7, drip converted in March"

    def test_a_blank_observation_leaves_the_description_alone(self):
        """The regression. Optional field, absent key — nothing to write, so write nothing."""
        history = _finish(Production(description=self.SEASON_NOTE))
        self.assertEqual(history.description, self.SEASON_NOTE)

    def test_an_empty_string_observation_leaves_the_description_alone(self):
        """The form submits "" rather than omitting the key, which is the path that actually ran."""
        history = _finish(Production(description=self.SEASON_NOTE), observation="")
        self.assertEqual(history.description, self.SEASON_NOTE)

    def test_a_whitespace_only_observation_leaves_the_description_alone(self):
        history = _finish(Production(description=self.SEASON_NOTE), observation="   \n  ")
        self.assertEqual(history.description, self.SEASON_NOTE)

    def test_a_real_observation_still_wins(self):
        """The feature this aliasing exists for must keep working."""
        history = _finish(Production(description=self.SEASON_NOTE), observation="Hulled on site, 4% moisture")
        self.assertEqual(history.description, "Hulled on site, 4% moisture")

    def test_an_observation_is_stored_trimmed(self):
        history = _finish(Production(description=""), observation="  Rain delayed the last block  ")
        self.assertEqual(history.description, "Rain delayed the last block")

    def test_the_rest_of_finalization_still_lands(self):
        """Guards the guard: proves finish() actually RAN rather than bailing early.

        A test asserting only that a field is unchanged passes just as happily when nothing
        executed at all.
        """
        history = _finish(
            Production(description=self.SEASON_NOTE),
            production_unit="lb",
            quality_grade="premium",
            harvest_method="mechanical",
        )
        self.assertTrue(history.published)
        self.assertEqual(history.lot_id, "LOT-1")
        self.assertEqual(history.production_amount, 1200)
        self.assertEqual(history.production_unit, "lb")
        self.assertEqual(history.quality_grade, "premium")
        self.assertEqual(history.harvest_method, "mechanical")
        # NOP record retention is derived from the finish date, not from "now".
        self.assertIsNotNone(history.retention_until)
