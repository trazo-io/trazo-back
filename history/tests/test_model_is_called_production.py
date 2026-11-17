"""Code calls the model `Production`; the name `History` is gone from it (2026-11-15).

The model became `Production` in history 0264, and `History = Production` in history/models.py
kept old imports working while 354 files moved over (scripts/rename_history_alias.py). The alias
was deleted on 2026-11-16, so a `History` reference now fails, often late. An import of it fails
when its module loads, which for a management command no test imports is the day someone runs it;
`models.History` fails only when that line runs, and no linter sees it. Branches written before
the rename bring such references in when they merge. This test names the line first.

Only NAME tokens count. Strings, comments and docstrings keep their words (certifier forms really
are called "Field History"), and migrations keep the model's name at the time they were written.

To fix a failure: poetry run python scripts/rename_history_alias.py && poetry run isort .
"""

import importlib.util
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("rename_history_alias", ROOT / "scripts" / "rename_history_alias.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)
# The fix and this check share one walker and one tokenizer, so they cannot disagree about scope.


class TheModelIsCalledProductionTests(SimpleTestCase):
    def test_no_code_uses_the_name_history(self):
        hits = []
        for path in script.python_files():
            rel = path.relative_to(ROOT).as_posix()
            source = path.read_text()
            lines = source.splitlines()
            for row, _ in script.old_name_positions(source):
                hits.append(f"{rel}:{row}: {lines[row - 1].strip()}")
        self.assertEqual(hits, [], "run `poetry run python scripts/rename_history_alias.py && poetry run isort .`")

    def test_the_walk_reads_the_tree_it_is_about(self):
        """Guards the test above: a walk that read nothing, or a tokenizer that saw nothing, passes it.
        The walk is `git ls-files`, so a local virtualenv or a nested worktree is never in it."""
        files = {path.relative_to(ROOT).as_posix() for path in script.python_files()}
        self.assertGreater(len(files), 700, f"only {len(files)} files read")
        self.assertIn("history/models/production.py", files)
        self.assertIn("scripts/rename_history_alias.py", files)
        self.assertFalse([f for f in files if "/migrations/" in f])

    def test_the_tokenizer_finds_code_and_skips_words(self):
        """Needs Python 3.12+ (PEP 701): on 3.11 the f-string row is missed and this fails, loudly."""
        source = "\n".join(
            [
                "from history.models import History",
                'label = "Field History"  # History, in a comment',
                'count = f"{History.objects.count()} seasons"',
                '"""A docstring about History."""',
                "class HistoryScan: pass",
                "x = models.History",
            ]
        )
        self.assertEqual([row for row, _ in script.old_name_positions(source)], [1, 3, 6])

    def test_the_script_leaves_a_different_history_alone(self):
        """Another library's `History`, or a class of its own, is reported, never renamed."""
        cases = (
            ("from history.models import History", "certifications/views.py", []),
            ("from .models import History", "history/views.py", []),
            ("from ..models import History", "history/services/example.py", []),
            # Same words, another module: `history.services.models` is not the model's.
            ("from .models import History", "history/services/example.py", [1]),
            ("from prompt_toolkit.history import History", "history/views.py", [1]),
            ("class History:\n    pass", "product/tests/test_example.py", [1]),
            # Any other binding, the deleted alias first: rewriting it would leave `Production = Production`.
            ("History = Production", "history/models.py", [1]),
            ("History: type = Production", "history/models.py", [1]),
            ("for History in rows:\n    pass", "product/views.py", [1]),
            ("with open(path) as History:\n    pass", "product/views.py", [1]),
            ("try:\n    pass\nexcept ValueError as History:\n    pass", "product/views.py", [3]),
            ("def count(History):\n    return History", "product/views.py", [1]),
            ("import prompt_toolkit.history as History", "history/views.py", [1]),
            ("from history.models import Production as History", "history/views.py", [1]),
        )
        for source, rel, expected in cases:
            with self.subTest(source=source, rel=rel):
                self.assertEqual(script.other_bindings(source, rel), expected)
