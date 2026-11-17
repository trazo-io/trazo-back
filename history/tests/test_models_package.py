"""history/models/ is a package, and everything in it is registered, in order (2026-11-17).

The single file history/models.py was split into one module per model or group of models
(scripts/split_history_models.py). Three ways that layout breaks without an error:

1. history/models.py comes back. A branch written before the split that edited it, merged with
   the conflict resolved by keeping its file, puts it next to the package, and Python imports the
   PACKAGE: the file is never read, and its edits are lost without a traceback.
2. A new module is never imported by `__init__.py`. Its models never register: no table, no
   migration, nothing fails until a query does.
3. A module imports a LATER module at the top. That registers the later module's models early,
   which changes content type ids in a fresh database and the order `apps.get_models()` walks
   (account closure and the schema census walk it).
"""

import ast
from pathlib import Path

from django.apps import apps
from django.test import SimpleTestCase

import history.models as package

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "history" / "models"


def _init_modules() -> list[str]:
    tree = ast.parse((PACKAGE / "__init__.py").read_text())
    return [node.module for node in tree.body if isinstance(node, ast.ImportFrom) and node.level == 1]


def _top_level_names(path: Path) -> set[str]:
    names = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


class ModelsPackageTests(SimpleTestCase):
    def test_the_old_single_file_is_gone(self):
        self.assertFalse(
            (ROOT / "history" / "models.py").exists(),
            "history/models.py is back next to the package, and Python never reads it: move its "
            "changes into history/models/ (scripts/split_history_models.py does it) and delete it",
        )

    def test_every_module_is_imported_and_every_name_exported(self):
        modules = _init_modules()
        on_disk = sorted(p.stem for p in PACKAGE.glob("*.py") if p.name != "__init__.py")
        self.assertGreater(len(on_disk), 10, f"only {on_disk} read")
        self.assertEqual(sorted(modules), on_disk, "a module in history/models/ that __init__.py never imports")
        for module in modules:
            for name in _top_level_names(PACKAGE / f"{module}.py"):
                if name == "logger":
                    continue
                with self.subTest(module=module, name=name):
                    self.assertIn(name, package.__all__)
                    self.assertIs(getattr(package, name), getattr(getattr(package, module), name))

    def test_models_register_in_the_order_init_imports_their_modules(self):
        position = {f"history.models.{module}": index for index, module in enumerate(_init_modules())}
        seen = [model.__module__ for model in apps.get_app_config("history").get_models()]
        self.assertGreater(len(seen), 15)
        positions = [position[module] for module in seen]
        self.assertEqual(positions, sorted(positions), f"registered out of order: {seen}")
