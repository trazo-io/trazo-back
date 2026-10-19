"""The corpus's SHAPE, guarded for free.

`audit_crew_messages` measures the parser and spends an OpenAI call per entry, so it is run by a
person and never by CI. What CI can hold for nothing is that the corpus it reads stays usable: ids
unique, categories known, every trap category still populated, and labels in a form the scorer
understands. A corpus that silently loses its negation entries would report a clean run.

NO NETWORK, NO MODEL, NO DATABASE. This is a file-shape test: one file read, no API keys, and
`ci.yml` sets none, so nothing here can reach OpenAI or Deepgram even by accident.

WHAT EACH ASSERTION BUYS, because a guard nobody can justify gets deleted or, worse, padded:

  * unique ids            a repeat overwrites a result and the run silently scores 99.
  * the scorer's fields   a missing key is a crash mid-run, after the calls are paid for.
  * categories populated  the one that matters: a corpus that lost its negation cases reports a
                          cleaner result than the truth.
  * no unknown category   the typo twin of the above. One catches removal, the other misspelling.
  * duplicate text        outside the `duplicate` category it is copy-paste, which halves a
                          category without changing its count.
  * an unserved language  the landing copy says "English or Spanish" because the parser serves
                          those families. With no such message the refusal cannot be observed.

TRIMMED 2026-10-19: an assertion that the negation entries carried particular labels was removed
as redundant. `test_every_trap_category_is_populated` already fails if they go.
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
    # Records that are NOT applications, so the offer is allowed to fill. `isApplicationRecord`
    # covers CHEMICAL, SOIL with PA/OM and PEST with BR; irrigation, pruning, mowing and harvest
    # are none of those. The UI walk only ever tested the WITHHOLDING path, so the filling path
    # had no cases at all (added 2026-10-19).
    "fills",
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

    def test_the_voice_half_is_not_quietly_emptied(self):
        """Voice is the only path where a word can be LOST rather than mistyped.

        MEASURED 2026-10-19: Deepgram dropped "bines" from "ciento veinte bines", leaving a
        quantity with no unit. A corpus with no voice entries, or with none carrying `must_hear`,
        would report a clean run while that class went unmeasured.
        """
        voice = [e for e in self.entries if e.get("kind") == "voice"]
        self.assertGreaterEqual(len(voice), 8, "too few voice notes to measure anything")
        for entry in voice:
            self.assertTrue(entry.get("spoken"), "%s has no `spoken` line to synthesise" % entry["id"])
        # The negation cases are the reason this path is tested at all: a dropped "nada" inverts
        # a compliance record and the speaker is not the person reviewing it.
        negated = [e for e in voice if e["category"] == "negation"]
        self.assertTrue(negated, "no spoken negation left in the corpus")
        for entry in negated:
            self.assertTrue(
                entry["expect"].get("must_hear"),
                "%s is a spoken negation with no word required to survive" % entry["id"],
            )

    def test_every_value_in_the_models_own_vocabulary_is_exercised(self):
        """A label the model can answer and the corpus never asks about is an untested answer.

        `equipment` was expected five times and is not in the prompt at all, which scored a label
        error as a model error until the review of back #185 caught it. The reverse gap is this:
        `transplanting`, `post_harvest` and `general` were answerable and never asked.
        """
        vocabulary = {
            "fertilization",
            "irrigation",
            "pesticide",
            "herbicide",
            "fungicide",
            "harvest",
            "planting",
            "pruning",
            "transplanting",
            "cultivation",
            "thinning",
            "soil_management",
            "transport",
            "pollination",
            "frost_protection",
            "mowing",
            "post_harvest",
            "general",
        }
        asked = {e["expect"].get("event_type") for e in self.entries}
        self.assertEqual(vocabulary - asked, set(), "the model can answer these and is never asked")

    def test_no_expectation_uses_a_word_the_model_is_never_offered(self):
        vocabulary = {
            "fertilization",
            "irrigation",
            "pesticide",
            "herbicide",
            "fungicide",
            "harvest",
            "planting",
            "pruning",
            "transplanting",
            "cultivation",
            "thinning",
            "soil_management",
            "transport",
            "pollination",
            "frost_protection",
            "mowing",
            "post_harvest",
            "general",
            None,
            "ambiguous",
        }
        invented = {e["expect"].get("event_type") for e in self.entries} - vocabulary
        self.assertEqual(invented, set(), "expectations the extractor cannot satisfy by construction")

    def test_a_language_the_parser_does_not_serve_is_represented(self):
        # The copy says "English or Spanish" precisely because the parser serves those families and
        # refuses the rest. A corpus with no such message cannot show whether the refusal happens.
        self.assertTrue(
            any(e["lang"] == "other" for e in self.entries),
            "no unsupported-language message left in the corpus",
        )
