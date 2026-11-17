"""Split history/models.py into the package history/models/ (2026-11-17).

The single file had grown to 5,849 lines and 25 top-level definitions. This moves each definition,
with the comments above it, into a module named for what it holds. The code does not change what it
does, and the package's `__init__.py` imports the modules in the old file's order. That order is also the order Django registers the models in, which decides
content type ids in a fresh database and the order `apps.get_models()` walks (account closure and
the schema census both walk it), so it is kept exactly.

Two kinds of line change, so that the code keeps its meaning one directory down:
- a RELATIVE import is resolved against the module it sits in, so `from .serializers import x` meant
  `history.serializers` in history/models.py and would mean the missing `history.models.serializers`
  in history/models/production.py. Every relative import is rewritten to its absolute form, as
  resolved from the old file;
- two methods referred to a model defined LATER in the old file, which a module cannot import at
  the top without registering that model early. Those get a function-local import from the
  package, `from history.models import ...`.

Re-runnable, so a branch written before the split can follow it. On that branch, before merging
main:

    git show origin/main:scripts/split_history_models.py > scripts/split_history_models.py
    poetry run python scripts/split_history_models.py
    git add -A history/models history/models.py scripts/split_history_models.py
    git commit -m "refactor(history): split models.py"

then merge main: what conflicts is only what both sides changed. A definition the branch added
that MODULES below does not name stops the script with its name; add it to the module it belongs
to (keeping file order) and run again.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

# The checkout the command runs in, so a copy of this script run from elsewhere still finds it.
ROOT = Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
)
OLD_MODULE = "history.models"
SOURCE = ROOT / "history" / "models.py"
PACKAGE = ROOT / "history" / "models"

# (module, one-line description, top-level names in it). The modules are listed in the old file's
# order and each is a contiguous run of it; the script refuses any other layout.
MODULES = [
    (
        "production",
        "A production season on a parcel, and its post-harvest facility link.",
        [
            "logger",
            "ORGANIC_LABEL_CATEGORY_CHOICES",
            "TRAZO_GREEN",
            "TRAZO_LEAF_LOGO",
            "compute_retention_until",
            "_FALSEY_PUBLISH_VALUES",
            "_parse_publish_flag",
            "Production",
            "ProductionPostHarvestFacility",
        ],
    ),
    ("activity", "One identity per activity record, whatever table holds it.", ["Activity"]),
    ("common_event", "The fields and behaviour every activity table shares.", ["CommonEvent"]),
    ("weather_event", "Weather activities.", ["WeatherEvent"]),
    ("chemical_event", "Chemical applications.", ["ChemicalEvent"]),
    ("production_event", "Production activities: planting through harvest.", ["ProductionEvent"]),
    ("general_event", "General activities.", ["GeneralEvent"]),
    (
        "history_scan",
        "Consumer QR scans of a production.",
        ["COUNTED_SCAN_BOT_SCORE_MAX", "HistoryScanQuerySet", "HistoryScan"],
    ),
    ("equipment_event", "Equipment activities (read-only rows; new ones are refused).", ["EquipmentEvent"]),
    ("soil_management_event", "Soil management activities.", ["SoilManagementEvent"]),
    ("pest_management_event", "Pest management activities.", ["PestManagementEvent"]),
    ("business_event", "Business activities.", ["BusinessEvent"]),
    (
        "sales",
        "Sales of a production's lots, and buyers' document requests.",
        ["BuyerDocRequest", "SalesRecordQuerySet", "SalesRecord"],
    ),
    ("label_image", "Container labels of a production.", ["LabelImage"]),
    ("event_amendment", "Corrections to an activity record.", ["EventAmendment"]),
    ("production_plan_item", "A season plan's checklist items.", ["ProductionPlanItem"]),
]


class Refused(Exception):
    pass


def _bound_names(node: ast.stmt) -> list[str]:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


class _Uses(ast.NodeVisitor):
    """Names a statement loads, and for each name used inside a function, the outermost function
    (a method, or a module-level function) it sits in."""

    def __init__(self):
        self.eager: set[str] = set()
        self.lazy: dict[str, set[ast.AST]] = {}
        self._outer: ast.AST | None = None

    def _function(self, node):
        for expr in node.decorator_list + node.args.defaults + [d for d in node.args.kw_defaults if d]:
            self.visit(expr)
        outer, self._outer = self._outer, self._outer or node
        for stmt in node.body:
            self.visit(stmt)
        self._outer = outer

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def visit_Lambda(self, node):
        outer, self._outer = self._outer, self._outer or node
        self.visit(node.body)
        self._outer = outer

    def visit_Name(self, node):
        if self._outer is None:
            self.eager.add(node.id)
        else:
            self.lazy.setdefault(node.id, set()).add(self._outer)


def plan(source: str):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    home = {name: index for index, (_, _, names) in enumerate(MODULES) for name in names}
    imports, chunks = [], [[] for _ in MODULES]  # chunks[i] = [(start_line, node)]
    previous_end, last_module = 0, 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
        else:
            names = _bound_names(node)
            if not names:
                raise Refused(f"line {node.lineno}: a top-level statement that binds no name: {ast.unparse(node)[:80]}")
            unknown = [n for n in names if n not in home]
            if unknown:
                raise Refused(f"line {node.lineno}: {', '.join(unknown)} is in no module; add it to MODULES")
            module = home[names[0]]
            if module < last_module:
                raise Refused(f"line {node.lineno}: {names[0]} would move before a model it follows in the file")
            last_module = module
            chunks[module].append((previous_end + 1, node))
        previous_end = node.end_lineno
    missing = sorted(set(home) - {n for chunk in chunks for _, node in chunk for n in _bound_names(node)})
    if missing:
        raise Refused(f"named in MODULES but not defined in history/models.py: {', '.join(missing)}")
    return tree, lines, imports, chunks, home


def _absolute(node: ast.ImportFrom) -> str:
    """The module a relative import named from history/models.py (`.x` is `history.x`, `..x` is `x`)."""
    if not node.level:
        return node.module
    package = OLD_MODULE.split(".")[:-1]
    up = node.level - 1
    base = package[: len(package) - up] if up <= len(package) else None
    if base is None or not (base or node.module):
        raise Refused(f"line {node.lineno}: a relative import that leaves the repository")
    return ".".join(base + ([node.module] if node.module else []))


def _import_lines(imports, wanted: set[str]) -> list[str]:
    out = []
    for node in imports:
        keep = [a for a in node.names if (a.asname or a.name).split(".")[0] in wanted]
        if not keep:
            continue
        names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in keep)
        if isinstance(node, ast.Import):
            out.append(f"import {names}\n")
        else:
            out.append(f"from {_absolute(node)} import {names}\n")
    return out


def render(source: str) -> dict[str, str]:
    tree, lines, imports, chunks, home = plan(source)
    imported = {(a.asname or a.name).split(".")[0] for node in imports for a in node.names}
    files = {}
    for index, (module, description, names) in enumerate(MODULES):
        uses = _Uses()
        for _, node in chunks[index]:
            uses.visit(node)
        used = uses.eager | set(uses.lazy)
        defined = set(names)

        header = [f'"""{description}"""\n', "\n"]
        wanted = used & imported
        if "logger" in used and "logger" not in defined:
            wanted.add("logging")
        header += _import_lines(imports, wanted)
        earlier: dict[str, list[str]] = {}
        later: dict[ast.AST, set[str]] = {}
        for name in sorted(used - defined):
            if name not in home or name == "logger":
                continue
            where = home[name]
            if where < index:
                earlier.setdefault(MODULES[where][0], []).append(name)
            elif name in uses.eager:
                raise Refused(f"{module}: {name} is needed at import time but is defined later, in {MODULES[where][0]}")
            else:
                for function in uses.lazy[name]:
                    later.setdefault(function, set()).add(name)
        header += [f"from .{other} import {', '.join(sorted(found))}\n" for other, found in earlier.items()]
        if "logger" in used and "logger" not in defined:
            header += ["\n", "logger = logging.getLogger(__name__)\n"]

        body_parts = []
        for start, node in chunks[index]:
            segment = lines[start - 1 : node.end_lineno]
            # Function-local imports for the forward references. Inserted bottom-up within this
            # segment, so each insert leaves the positions above it where they were.
            inserts = []
            for function, found in later.items():
                if node.lineno <= function.lineno <= node.end_lineno:
                    first = _first_statement(function)
                    line = f"{' ' * first.col_offset}from history.models import {', '.join(sorted(found))}\n"
                    inserts.append((first.lineno, line))
            # Relative imports inside the moved code, rewritten in place (same line count).
            for inner in ast.walk(node):
                if isinstance(inner, ast.ImportFrom) and inner.level:
                    at = inner.lineno - start
                    dots = "\\." * inner.level + (re.escape(inner.module) if inner.module else "")
                    fixed, count = re.subn(
                        rf"\bfrom\s+{dots}\s+import\b", f"from {_absolute(inner)} import", segment[at], count=1
                    )
                    if count != 1:
                        raise Refused(
                            f"line {inner.lineno}: could not rewrite the relative import {segment[at].strip()!r}"
                        )
                    segment[at] = fixed
            for lineno, line in sorted(inserts, reverse=True):
                segment.insert(lineno - start, line)
            body_parts.append("".join(segment).lstrip("\n").rstrip("\n") + "\n")
        files[f"{module}.py"] = "".join(header) + "\n\n" + "\n\n".join(body_parts)
    files["__init__.py"] = _init()
    return files


def _first_statement(function) -> ast.stmt:
    """The statement a function-local import goes above: the first one after any docstring."""
    body = function.body
    docstring = isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant)
    if docstring and isinstance(body[0].value.value, str) and len(body) > 1:
        return body[1]
    return body[0]


def _init() -> str:
    out = [
        '"""The history app\'s models, one module per model or group of models (2026-11-17).\n',
        "\n",
        "Until then this was the single file history/models.py. The modules below are imported in that\n",
        "file's order, which is the order Django registers the models in: it decides content type ids\n",
        "in a fresh database and the order `apps.get_models()` walks. Keep it. A new model goes in its\n",
        "own module, imported here; history.tests.test_models_package fails on a module left out.\n",
        '"""\n',
        "\n",
        "# isort: skip_file\n",
        "# Import order is model registration order; see above.\n",
    ]
    exported = []
    for module, _, names in MODULES:
        out.append(f"from .{module} import {', '.join(names)}\n")
        exported += names
    out += ["\n", "__all__ = [\n"] + [f'    "{name}",\n' for name in exported] + ["]\n"]
    return "".join(out)


def main() -> int:
    if not SOURCE.exists():
        state = "already split" if (PACKAGE / "__init__.py").exists() else "not a trazo-back checkout?"
        print(f"{SOURCE} does not exist ({state}); nothing to split.", file=sys.stderr)
        return 2
    if PACKAGE.exists():
        print(
            f"{PACKAGE.relative_to(ROOT)}/ already exists; remove it or run on the branch's own copy.", file=sys.stderr
        )
        return 2
    try:
        files = render(SOURCE.read_text())
    except Refused as exc:
        print(f"Not split: {exc}", file=sys.stderr)
        return 1
    PACKAGE.mkdir()
    for name, text in files.items():
        (PACKAGE / name).write_text(text)
    SOURCE.unlink()
    targets = [str(PACKAGE / name) for name in files]
    subprocess.run([sys.executable, "-m", "isort", "--quiet", *targets], check=True, cwd=ROOT)
    subprocess.run([sys.executable, "-m", "black", "--quiet", *targets], check=True, cwd=ROOT)
    print(f"history/models.py -> {len(files)} files in history/models/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
