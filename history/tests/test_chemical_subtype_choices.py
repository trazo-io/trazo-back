"""Every `chemical_subtype` a seeder writes must be one the column actually offers.

🔴 2026-09-02. `ChemicalEvent.chemical_subtype` declares `choices=CHEMICAL_SUBTYPE_CHOICES`,
but Django enforces `choices` only in `full_clean()` — which the seeders never call — so four
seeder sites had been writing SHORT forms for months:

    seed_showcase_walnut_farm  chemical_subtype="copper"      (FUNGICIDE)
    seed_showcase_walnut_farm  chemical_subtype="biological"  (PESTICIDE)
    _loewen_events             chemical_subtype="organic"     (FERTILIZER)

The carbon pipeline absorbs both spellings on purpose (`event_carbon_calculator.py:414`
accepts `["copper_fungicide", "copper"]`), so nothing ever broke loudly. The DISPLAY path is
where it showed: the frontend enum catalogue is keyed by the canonical values, so a short form
missed its authored label, fell through to a de-underscored slug ("Copper"), and — because the
Spanish value map is keyed by the English STRING — printed English on the Spanish consumer
card. Same failure shape as the dangling `enumSource` fixed the same day; see
trazo-app/src/config/events/__tests__/chemicalSubtypeLabels.test.ts.

The seeded farms are what a pilot grower is shown, so "only demo data" is not a defence.

Scope note: this reads the SEEDER SOURCE, not the database. A dev database also holds
`organic_insecticide` rows whose value appears in no code, front or back — residue from a
seeder that no longer exists. Guarding the source is what keeps new rows honest; the stale
ones are a data question, not a code one.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

from common.field_registry import CHEMICAL_SUBTYPE

# A model WRITE: `chemical_subtype="organic_fertilizer"` as a kwarg on a ChemicalEvent.
MODEL_WRITE = re.compile(r"""(?<!["'])chemical_subtype\s*=\s*["']([a-z_]+)["']""")

# A dict ENTRY: `"chemical_subtype": "fungicide"`. Every one of these lives inside a template
# catalogue's `backend_event_fields`, which since 2026-08-19 reaches a season PLAN and never an
# event row — a plan item carries no field values at all. Those catalogues hold values that are
# not compositions ("insecticide", "fungicide" — those are `type` codes), and nothing renders
# them, so they are out of scope here rather than quietly "fixed" into a structure no reader
# consumes. The second test below proves that exclusion still holds.
DICT_ENTRY = re.compile(r"""["']chemical_subtype["']\s*:\s*["']([a-z_]+)["']""")

# Directories whose files WRITE events. Excludes carbon/, whose matches are read-side
# comparisons that legitimately accept both spellings.
SEEDER_ROOTS = (
    Path(__file__).resolve().parent.parent / "management" / "commands",
    Path(__file__).resolve().parent.parent.parent / "carbon" / "management" / "commands",
)


class ChemicalSubtypeChoicesTest(SimpleTestCase):
    def test_registry_is_populated(self):
        """Guard against a vacuous pass if CHEMICAL_SUBTYPE is ever emptied or renamed."""
        self.assertGreaterEqual(len(CHEMICAL_SUBTYPE), 13)

    def _sources(self):
        for root in SEEDER_ROOTS:
            for path in sorted(root.rglob("*.py")):
                yield path, path.read_text(encoding="utf-8")

    def test_every_seeded_subtype_is_a_model_choice(self):
        valid = {value for value, _label in CHEMICAL_SUBTYPE}
        offenders = []
        scanned = 0
        for path, source in self._sources():
            for match in MODEL_WRITE.finditer(source):
                scanned += 1
                written = match.group(1)
                if written not in valid:
                    line = source[: match.start()].count("\n") + 1
                    offenders.append(f"{path.name}:{line} wrote '{written}'")

        self.assertGreater(scanned, 20, "the scan found almost nothing — the regex has drifted")
        self.assertEqual(
            offenders,
            [],
            "these values are not in ChemicalEvent.chemical_subtype choices, so they render "
            "as a capitalised slug with no Spanish translation on the consumer card:\n  " + "\n  ".join(offenders),
        )

    def test_dict_form_writes_are_still_only_template_catalogues(self):
        """The exclusion above is an ASSUMPTION, so it gets its own assertion.

        `"chemical_subtype": "..."` is excluded because every occurrence sits inside a
        `backend_event_fields` template catalogue, which cannot reach an event row. The moment
        someone builds a kwargs dict for `ChemicalEvent.objects.create(**fields)` in that shape,
        the exclusion starts hiding a real write — so fail then and force the decision.
        """
        escapees = []
        scanned = 0
        for path, source in self._sources():
            for match in DICT_ENTRY.finditer(source):
                scanned += 1
                # The nearest preceding anchor decides which structure this entry belongs to.
                before = source[: match.start()]
                catalogue = before.rfind("backend_event_fields")
                model = before.rfind("ChemicalEvent.objects")
                if catalogue < model:
                    line = before.count("\n") + 1
                    escapees.append(f"{path.name}:{line} → '{match.group(1)}'")

        self.assertGreater(scanned, 5, "no dict-form entries found — the regex has drifted")
        self.assertEqual(
            escapees,
            [],
            "a dict-form chemical_subtype now sits closer to a ChemicalEvent write than to a "
            "template catalogue, so the exclusion in this file is no longer safe:\n  " + "\n  ".join(escapees),
        )
