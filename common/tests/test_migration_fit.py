"""scripts/migration_fit.py: an open PR's new migrations must build on main's latest migration.

Two PRs that each added history 0247 (2026-10-21) and history 0256 (2026-11-11) passed CI on
their own and broke the production deploy once both merged: two leaf migrations, and `migrate`
refuses to run. The script re-checks every open PR whenever main moves. These tests hold its rule
on the shapes that happened (the 0256 pair replayed from the real files' dependencies, the 0248
merge migration) and the ones it must not flag.
"""

import importlib.util
from pathlib import Path

from django.test import SimpleTestCase

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "migration_fit.py"
_spec = importlib.util.spec_from_file_location("migration_fit", _PATH)
fit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fit)


def _migration(app, *deps, swappable=False):
    lines = [
        f'        ("{dep_app}", "{dep}"),' for dep_app, dep in ((d if isinstance(d, tuple) else (app, d)) for d in deps)
    ]
    if swappable:
        lines.append("        migrations.swappable_dependency(settings.AUTH_USER_MODEL),")
    return (
        "from django.conf import settings\nfrom django.db import migrations\n\n\n"
        "class Migration(migrations.Migration):\n\n    dependencies = [\n" + "\n".join(lines) + "\n    ]\n\n"
        "    operations = []\n"
    )


def _files(app, chain):
    """{path: source} for {name: deps}."""
    return {f"{app}/migrations/{name}.py": _migration(app, *deps) for name, deps in chain.items()}


#: history as main stood after #370 merged: 0254 -> 0255 -> 0256_retire_impact_summary.
MAIN_AFTER_370 = _files(
    "history",
    {
        "0254_retire_shopper_models": ["0253_backfill_activity_link"],
        "0255_drop_shopper_tables": ["0254_retire_shopper_models"],
        "0256_retire_impact_summary": ["0255_drop_shopper_tables"],
    },
)


class DependenciesTests(SimpleTestCase):
    def test_literal_pairs_are_read_and_a_swappable_dependency_is_skipped(self):
        source = _migration("history", "0255_drop_shopper_tables", ("carbon", "0054_x"), swappable=True)
        self.assertEqual(fit.dependencies(source), [("history", "0255_drop_shopper_tables"), ("carbon", "0054_x")])

    def test_only_numbered_top_level_migrations_count(self):
        self.assertEqual(fit.migration_of("history/migrations/0256_retire_impact_summary.py"),
                         ("history", "0256_retire_impact_summary"))  # fmt: skip
        for path in (
            "history/migrations/__init__.py",
            "history/tests/test_x.py",
            "trazo-back/history/migrations/0001_initial.py",  # a stray copy is not this repo's app
        ):
            self.assertIsNone(fit.migration_of(path), path)

    def test_the_real_0256_files_declare_what_the_replay_below_assumes(self):
        """The replay is built from these dependencies; read them off the repository."""
        migrations = Path(__file__).resolve().parents[2] / "history" / "migrations"
        self.assertIn(
            ("history", "0255_drop_shopper_tables"),
            fit.dependencies((migrations / "0256_retire_impact_summary.py").read_text()),
        )


class ProblemsTests(SimpleTestCase):
    def test_the_0256_collision_is_caught_against_main_after_the_first_merge(self):
        """#371 built on 0255 while #370 had already made 0256 main's leaf."""
        pr_371 = _files("history", {"0256_manure_interval_choices_read_as_a_floor": ["0255_drop_shopper_tables"]})
        (problem,) = fit.problems(MAIN_AFTER_370, pr_371)
        self.assertIn("0256_manure_interval_choices_read_as_a_floor builds on 0255_drop_shopper_tables", problem)
        self.assertIn("main's latest history migration is now 0256_retire_impact_summary", problem)

    def test_the_renumbered_migration_fits(self):
        """#373: the same migration as 0257 on top of 0256_retire_impact_summary."""
        pr_373 = _files("history", {"0257_manure_interval_choices_read_as_a_floor": ["0256_retire_impact_summary"]})
        self.assertEqual(fit.problems(MAIN_AFTER_370, pr_373), [])

    def test_several_new_migrations_in_a_chain_fit_when_the_first_builds_on_the_leaf(self):
        pr = _files("history", {"0257_a": ["0256_retire_impact_summary"], "0258_b": ["0257_a"]})
        self.assertEqual(fit.problems(MAIN_AFTER_370, pr), [])

    def test_a_merge_migration_on_main_is_its_leaf(self):
        """0248 merged the two 0247s: building on either 0247 now would fork again."""
        main = _files(
            "history",
            {
                "0246_x": ["0245_y"],
                "0247_event_application_group": ["0246_x"],
                "0247_pheromone_dispensers": ["0246_x"],
                "0248_merge": ["0247_event_application_group", "0247_pheromone_dispensers"],
            },
        )
        self.assertEqual(fit.leaves(fit.app_graph(main)["history"]), {"0248_merge"})
        self.assertEqual(fit.problems(main, _files("history", {"0249_ok": ["0248_merge"]})), [])
        self.assertEqual(len(fit.problems(main, _files("history", {"0248_late": ["0247_pheromone_dispensers"]}))), 1)

    def test_another_apps_main_does_not_matter(self):
        main = {**MAIN_AFTER_370, **_files("carbon", {"0055_a": ["0054_b"]})}
        pr = _files("carbon", {"0056_c": ["0055_a"]})
        self.assertEqual(fit.problems(main, pr), [])

    def test_a_new_apps_first_migration_fits(self):
        self.assertEqual(fit.problems(MAIN_AFTER_370, _files("newapp", {"0001_initial": []})), [])


class SharedAnchorsTests(SimpleTestCase):
    def test_two_open_prs_on_the_same_migration_each_name_the_other(self):
        """Before either merged, #370 and #371 both built on history 0255: warn both."""
        main = {k: v for k, v in MAIN_AFTER_370.items() if "0256" not in k}
        per_pr = {
            370: fit.anchors(main, _files("history", {"0256_retire_impact_summary": ["0255_drop_shopper_tables"]})),
            371: fit.anchors(main, _files("history", {"0256_manure": ["0255_drop_shopper_tables"]})),
            369: {},
        }
        self.assertEqual(
            fit.shared_anchors(per_pr),
            {
                370: [("history", "0255_drop_shopper_tables", [371])],
                371: [("history", "0255_drop_shopper_tables", [370])],
            },
        )
