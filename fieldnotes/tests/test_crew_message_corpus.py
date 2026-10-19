"""The corpus's SHAPE, guarded for free.

`audit_crew_messages` measures the parser and spends an OpenAI call per entry, so it is run by a
person and never by CI. What CI can hold for nothing is that the corpus it reads stays usable: ids
unique, categories known, every trap category still populated, and labels in a form the scorer
understands. A corpus that silently loses its negation entries would report a clean run.

NO NETWORK, NO MODEL, NO DATABASE. This is a file-shape test.
"""

import json
from collections import Counter
from pathlib import Path

from django.test import SimpleTestCase

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "crew_messages.json"

# Each of these exists because it broke something or could. Losing one silently would make a run
# look cleaner than it is, so the test names them rather than counting whatever happens to be there.
REQUIRED_CATEGORIES = {
    "plain",
    "negation",
    "no_date",
    "past_date",
    "multi_task",
    "unknown_block",
    "prohibited",
    "worker_named",
    "non_work",
    "noisy",
    "units",
    "privacy",
    "duplicate",
    "optout",
}


class CrewMessageCorpusTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        cls.entries = cls.corpus["entries"]

    def test_ids_are_unique(self):
        duplicates = [i for i, n in Counter(e["id"] for e in self.entries).items() if n > 1]
        self.assertEqual(duplicates, [], "a repeated id overwrites a result silently")

    def test_every_entry_has_the_fields_the_scorer_reads(self):
        for entry in self.entries:
            for key in ("id", "lang", "category", "text", "expect"):
                self.assertIn(key, entry, "%s is missing %r" % (entry.get("id"), key))
            self.assertTrue(entry["text"].strip(), "%s has no message" % entry["id"])
            for key in ("event_type", "date_stated", "negation"):
                self.assertIn(key, entry["expect"], "%s expects no %r" % (entry["id"], key))

    def test_every_trap_category_is_populated(self):
        present = {e["category"] for e in self.entries}
        missing = REQUIRED_CATEGORIES - present
        self.assertEqual(missing, set(), "a trap category was emptied: a clean run would mean less")

    def test_no_unlabelled_category_creeps_in(self):
        extra = {e["category"] for e in self.entries} - REQUIRED_CATEGORIES
        self.assertEqual(extra, set(), "a category the scorer does not group: add it to the set")

    def test_text_is_duplicated_only_where_that_is_the_point(self):
        # The `duplicate` category sends the same words twice on purpose, once under a repeated
        # message id and once under a fresh one. Anywhere else, two identical messages are a
        # copy-paste slip that quietly halves a category.
        for text, n in Counter(e["text"] for e in self.entries).items():
            if n > 1:
                categories = {e["category"] for e in self.entries if e["text"] == text}
                self.assertEqual(
                    categories, {"duplicate"}, "repeated text outside the duplicate category: %r" % text[:50]
                )

    def test_the_negated_entries_say_what_they_expect(self):
        negations = [e for e in self.entries if e["category"] == "negation"]
        self.assertGreaterEqual(len(negations), 4, "too few negation cases to measure anything")
        # One dropped word inverts a compliance record, so at least one entry must carry the mixed
        # case: a message where part of the work happened and part did not.
        self.assertIn("mixed", [e["expect"].get("negation") for e in negations])

    def test_a_language_the_parser_does_not_serve_is_represented(self):
        # The copy says "English or Spanish" precisely because the parser serves those families and
        # refuses the rest. A corpus with no such message cannot show whether the refusal happens.
        self.assertTrue(
            any(e["lang"] == "other" for e in self.entries),
            "no unsupported-language message left in the corpus",
        )
