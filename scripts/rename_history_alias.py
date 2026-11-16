"""Rename the `History` alias to `Production` in Python code (2026-11-15).

The model became `Production` in history 0264, and `History = Production` in history/models.py
kept every old import working. This rewrites each remaining use of the old name so the alias can
be deleted.

It changes NAME tokens only, which is what makes it safe to run over the whole tree:
- strings, comments and docstrings keep their words. Certifier forms really are called "Field
  History" and "Record Change History", and those labels print in the packet;
- migrations are skipped. They describe the model as it was when each one was written;
- only files git tracks are read, so a local virtualenv or a worktree nested under `.claude/` is
  never touched;
- the alias line itself is kept until the PR that deletes it.

A file where `History` is something else (imported from another library, or a class of its own)
is not rewritten: the script lists it and exits 1, and that file is fixed by hand.

Re-runnable and idempotent. A branch written before the rename runs it, then isort (two old
imports can become one duplicate name), and is done:

    poetry run python scripts/rename_history_alias.py && poetry run isort .
"""

import ast
import io
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD, NEW = "History", "Production"
ALIAS_LINE = f"{OLD} = {NEW}"
MODEL_MODULE = "history.models"


def python_files(root: Path = ROOT):
    """Every tracked `.py` file outside migrations. Untracked files are not the repo's."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", "*.py"], check=True, capture_output=True, text=True
    ).stdout
    for rel in sorted(filter(None, listed.split("\0"))):
        if "migrations" not in Path(rel).parts:
            yield root / rel


def old_name_positions(source: str) -> list[tuple[int, int]]:
    """(row, column) of every NAME token spelled `History`, columns in characters.

    Needs Python 3.12+: before PEP 701 an f-string was one STRING token, so `f"{History.x}"`
    would be invisible here.
    """
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return [tok.start for tok in tokens if tok.type == tokenize.NAME and tok.string == OLD]


def _absolute(module: str | None, level: int, rel: str) -> str:
    """`from ..models import x` in history/services/y.py is `history.models`."""
    if not level:
        return module or ""
    package = list(Path(rel).parent.parts)
    base = package[: len(package) - (level - 1)]
    return ".".join(base + ([module] if module else []))


def other_bindings(source: str, rel: str) -> list[int]:
    """Lines where `History` is bound to something other than the model."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and _absolute(node.module, node.level, rel) != MODEL_MODULE:
            lines += [node.lineno for alias in node.names if alias.name == OLD]
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == OLD:
            lines.append(node.lineno)
    return lines


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
    if sys.version_info < (3, 12):
        print("Python 3.12+ is required: older tokenizers hide names inside f-strings.", file=sys.stderr)
        return 2
    changed, refused = 0, []
    for path in python_files():
        source = path.read_text()
        if not old_name_positions(source):
            continue
        clashes = other_bindings(source, path.relative_to(ROOT).as_posix())
        if clashes:
            refused += [f"{path.relative_to(ROOT)}:{line}" for line in clashes]
            continue
        new = rewrite(source)
        if new != source:
            path.write_text(new)
            changed += 1
            print(path.relative_to(ROOT))
    print(f"{changed} file(s) rewritten", file=sys.stderr)
    if refused:
        print("Not rewritten, `History` is something else here; fix by hand:", file=sys.stderr)
        print("\n".join(f"  {where}" for where in refused), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
