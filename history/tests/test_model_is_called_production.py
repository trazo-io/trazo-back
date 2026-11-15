"""Code calls the model `Production`; the name `History` is gone from it (2026-11-15).

The model became `Production` in history 0264, and `History = Production` in history/models.py
kept old imports working while 354 files moved over (scripts/rename_history_alias.py). A new
`History` reference works only while that alias exists. Once it goes, the reference raises
NameError: at import time if it is an import, but at RUN time if it sits in a function body, where
no import check sees it. This test fails first.

Only NAME tokens count. Strings, comments and docstrings keep their words (certifier forms really
are called "Field History"), and migrations keep the model's name at the time they were written.

To fix a failure: poetry run python scripts/rename_history_alias.py && poetry run isort .
"""

import io
import os
import tokenize
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", "node_modules", "migrations", "__pycache__"}
OLD = "History"
# The alias itself, until the PR that deletes it.
ALIAS = ("history/models.py", "History = Production")


def _python_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath, name)


def _old_names(source: str) -> list[tuple[int, str]]:
    """(row, line) of every NAME token spelled `History`."""
    lines = source.splitlines()
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return [(t.start[0], lines[t.start[0] - 1]) for t in tokens if t.type == tokenize.NAME and t.string == OLD]


class TheModelIsCalledProductionTests(SimpleTestCase):
    def test_no_code_uses_the_name_history(self):
        hits = []
        for path in _python_files():
            rel = path.relative_to(ROOT).as_posix()
            for row, line in _old_names(path.read_text()):
                if (rel, line.strip()) != ALIAS:
                    hits.append(f"{rel}:{row}: {line.strip()}")
        self.assertEqual(hits, [], "run `poetry run python scripts/rename_history_alias.py && poetry run isort .`")

    def test_the_walk_reads_the_tree_it_is_about(self):
        """Guards the test above: a walk that read nothing, or a tokenizer that saw nothing, passes it."""
        files = {path.relative_to(ROOT).as_posix() for path in _python_files()}
        self.assertGreater(len(files), 700, f"only {len(files)} files read")
        self.assertIn("history/models.py", files)
        self.assertIn("scripts/rename_history_alias.py", files)
        self.assertFalse([f for f in files if "/migrations/" in f])

    def test_the_tokenizer_finds_code_and_skips_words(self):
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
        self.assertEqual([row for row, _ in _old_names(source)], [1, 3, 6])
