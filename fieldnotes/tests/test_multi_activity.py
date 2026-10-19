"""The two-job caution, scored against the labelled corpus.

WHY THE CORPUS AND NOT A HANDFUL OF EXAMPLES. The detector is a keyword table, and a keyword table
is exactly the thing that looks right on the three sentences its author had in mind. Scored over
all 100 labelled messages it cannot be tuned to a sentence without the cost showing up somewhere
else, and a later edit that catches one more message at the price of ten false cautions fails here
rather than on a farmer's screen.

FREE IN CI: no model, no network, no database. The same corpus file the paid audit reads.
"""

import json
from pathlib import Path

from django.test import SimpleTestCase

from fieldnotes.services.multi_activity import families_mentioned, mentions_multiple_activities

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "crew_messages.json"


def _entries():
    return json.loads(CORPUS.read_text(encoding="utf-8"))["entries"]


def _holds_two_jobs(entry):
    return entry["category"] == "multi_task" or entry["expect"].get("event_type") == "ambiguous"


class MultiActivityCautionTests(SimpleTestCase):
    def test_it_catches_every_two_job_message_in_the_corpus(self):
        missed = [
            (e["id"], e["text"], families_mentioned(e["text"]))
            for e in _entries()
            if _holds_two_jobs(e) and not mentions_multiple_activities(e["text"])
        ]
        self.assertEqual(missed, [], "a message holding two jobs raised no caution")

    def test_it_does_not_cry_wolf_on_single_job_messages(self):
        # A caution on every second note is a caution nobody reads. MEASURED at zero over the 94
        # single-job messages; this asserts zero rather than a tolerance, because the moment a
        # budget exists it gets spent.
        false_cautions = [
            (e["id"], e["text"], families_mentioned(e["text"]))
            for e in _entries()
            if not _holds_two_jobs(e) and mentions_multiple_activities(e["text"])
        ]
        self.assertEqual(false_cautions, [], "a single-job message raised a two-job caution")

    def test_two_blocks_is_not_two_jobs(self):
        # One activity across two parcels is ONE record. The detector must read the work, never
        # the conjunction, or every "block 2 and block 3" message cautions.
        self.assertFalse(mentions_multiple_activities("Took soil samples from block 2 and block 3"))
        self.assertFalse(mentions_multiple_activities("Regamos el bloque 2 y el bloque 3"))

    def test_it_reads_the_work_and_survives_a_phone_keyboard(self):
        # No accents, no capitals: what a crew member types with gloves on.
        self.assertTrue(mentions_multiple_activities("regamos el bloque 2 y despues podamos el 3"))
        self.assertTrue(mentions_multiple_activities("Regamos el bloque 2 y después podamos el 3"))

    def test_a_stem_does_not_match_inside_another_word(self):
        # `arado` sits inside `descascaradora`, so a bare substring read "I took the load to the
        # huller" as ploughing plus transport. The boundary is why this is one family.
        self.assertEqual(families_mentioned("Lleve la carga a la descascaradora, 12 toneladas"), ["transport"])

    def test_an_application_verb_alone_names_no_family(self):
        # "Aplicar" covers compost and sulfur alike, so it cannot separate fertilization from a
        # spray and used to flag four single-job messages as two.
        self.assertNotIn("spray", families_mentioned("Aplique compost en el bloque 2"))

    def test_equipment_on_irrigation_gear_is_one_job(self):
        # The pump is equipment; "irrigation" there names the gear, not the work.
        self.assertFalse(mentions_multiple_activities("Replaced the filter on the irrigation pump"))
        self.assertFalse(mentions_multiple_activities("Flushed the drip lines on block 7"))
