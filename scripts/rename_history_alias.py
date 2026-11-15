"""Rename the `History` alias to `Production` in Python code (2026-11-15).

The model became `Production` in history 0264, and `History = Production` in history/models.py
kept every old import working. This rewrites each remaining use of the old name so the alias can
be deleted.

It changes NAME tokens only, which is what makes it safe to run over the whole tree:
- strings, comments and docstrings keep their words. Certifier forms really are called "Field
  History" and "Record Change History", and those labels print in the packet;
- migrations are skipped. They describe the model as it was when each one was written;
- the alias line itself is kept until the PR that deletes it.

Re-runnable and idempotent. A branch written before the rename runs it, then isort (two old
imports can become one duplicate name), and is done:

    poetry run python scripts/rename_history_alias.py && poetry run isort .
"""

import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "node_modules", "migrations"}
OLD, NEW = "History", "Production"
ALIAS_LINE = f"{OLD} = {NEW}"


def python_files(root: Path = ROOT):
    for path in sorted(root.rglob("*.py")):
        if not SKIP_DIRS.intersection(path.relative_to(root).parts):
            yield path


def old_name_positions(source: str) -> list[tuple[int, int]]:
    """(row, column) of every NAME token spelled `History`, columns in characters."""
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return [tok.start for tok in tokens if tok.type == tokenize.NAME and tok.string == OLD]


def rewrite(source: str) -> str:
    lines = source.splitlines(keepends=True)
    # Right to left, so an earlier replacement never shifts a later column.
    for row, col in sorted(old_name_positions(source), reverse=True):
        line = lines[row - 1]
        if line.strip() == ALIAS_LINE:
            continue
        lines[row - 1] = line[:col] + NEW + line[col + len(OLD) :]
    return "".join(lines)


def main() -> int:
    changed = 0
    for path in python_files():
        source = path.read_text()
        new = rewrite(source)
        if new != source:
            path.write_text(new)
            changed += 1
            print(path.relative_to(ROOT))
    print(f"{changed} file(s) rewritten", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
