"""Every field a form asks must survive the save — the round-trip matrix.

2026-08-25: the add-event forms post every field top-level; a field that is
neither a model column, nor in its family's extra_data lift list, nor packed
into a JSON pocket (soil lab -> test_results) is SILENTLY discarded by DRF.
The matrix found five such fields, all production: the whole pollination
section (pollinator_type, hive_count, placement_date, removal_date) and
pruning_passes — a farmer's hive record saved as an empty event.

This test re-runs that matrix in CI: it parses the frontend display registry
(the authority for what each form asks, same cross-repo pattern as
test_certifier_only_list_parity) and asserts every form-surface field has a
storage home. A new form field with no home fails here before it can eat data.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

from history import models as hm
from history import serializers as hs

FRONT = Path(__file__).resolve().parents[3] / "trazo-app" / "src" / "config" / "events"

FAMILIES = {
    "productionEvent.ts": (hm.ProductionEvent, "production"),
    "chemicalEvent.ts": (hm.ChemicalEvent, "chemical"),
    "soilEvent.ts": (hm.SoilManagementEvent, "soil"),
    "pestEvent.ts": (hm.PestManagementEvent, "pest"),
    "businessEvent.ts": (hm.BusinessEvent, "business"),
    "generalEvent.ts": (hm.GeneralEvent, "general"),
    "weatherEvent.ts": (hm.WeatherEvent, "weather"),
}

#: Fields the form posts under a different wire name, derives client-side, or
#: that are packed into a JSON pocket by a dedicated code path. Do not add to
#: this list to silence a failure — a new entry means you verified WHERE the
#: value is stored and HOW it is read back (modal + card), not that the test
#: is inconvenient.
VIRTUAL = {
    # renamed on the wire (chemical)
    "volume_numeric",
    "area_numeric",
    "volume_applied",
    "area_treated",
    "application_method",
    # packed into SoilManagementEvent.test_results by the soil form (F19) and
    # flattened back by LAB_RESULT_FIELDS on both read serializers
    "lab_name",
    "lab_report_date",
    "lab_sample_id",
    "lab_nitrogen",
    "lab_phosphorus",
    "lab_potassium",
    "lab_cec",
    "lab_zinc_ppm",
    "lab_boron_ppm",
    "lab_manganese_ppm",
    "lab_iron_ppm",
    # derived / UI-only
    "water_test_summary",
    "custom_fields",
    "operation_efficiency",
    "seed_search_attempts",
}


def _form_fields(source: str) -> list[str]:
    names = []
    for m in re.finditer(
        r"\{\s*(?://[^\n]*\n\s*)*name:\s*'([a-z_0-9]+)'(.*?)surfaces:\s*\{(.*?)\}",
        source,
        re.DOTALL,
    ):
        name, _mid, surfaces = m.groups()
        if re.search(r"\bform:|\bquick_form:", surfaces):
            names.append(name)
    return names


def _inline_lift_list(serializer_source: str, class_name: str) -> set[str]:
    """Extract the quoted names inside a family's to_internal_value body."""
    m = re.search(
        rf"class {class_name}.*?def to_internal_value(.*?)\n    def ",
        serializer_source,
        re.DOTALL,
    )
    if not m:
        return set()
    return set(re.findall(r'"([a-z_0-9]+)"', m.group(1)))


class FormFieldRoundTripTests(SimpleTestCase):
    def test_every_form_field_has_a_storage_home(self):
        if not FRONT.exists():
            self.skipTest(f"frontend checkout not present at {FRONT}")

        serializer_src = Path(hs.__file__).read_text(encoding="utf-8")
        lifts = {
            "production": set(hs.UpdateProductionEventSerializer.EXTRA_DATA_FIELDS)
            | _inline_lift_list(serializer_src, "UpdateProductionEventSerializer"),
            "chemical": _inline_lift_list(serializer_src, "UpdateChemicalEventSerializer"),
            "soil": _inline_lift_list(serializer_src, "UpdateSoilManagementEventSerializer"),
            "pest": _inline_lift_list(serializer_src, "UpdatePestManagementEventSerializer"),
            "business": _inline_lift_list(serializer_src, "UpdateBusinessEventSerializer"),
            "general": _inline_lift_list(serializer_src, "UpdateGeneralEventSerializer"),
            "weather": _inline_lift_list(serializer_src, "UpdateWeatherEventSerializer"),
        }
        # Guard-the-guard: the inline parses must find real lists.
        self.assertGreater(len(lifts["soil"]), 10, "soil lift parse looks broken")
        self.assertGreater(len(lifts["weather"]), 8, "weather lift parse looks broken")

        problems = []
        checked = 0
        for fname, (model, family) in FAMILIES.items():
            path = FRONT / fname
            columns = {f.name for f in model._meta.get_fields()}
            for field in _form_fields(path.read_text(encoding="utf-8")):
                checked += 1
                if field in columns or field in lifts[family] or field in VIRTUAL:
                    continue
                problems.append(f"{fname}: {field}")

        self.assertGreater(checked, 150, "registry parse looks broken")

        # The five fields the 2026-08-25 matrix caught, pinned explicitly: the
        # inline-lift parser above collects every quoted name in a family's
        # to_internal_value, so a field named in an unrelated string could
        # false-pass the matrix — these five must be in the REAL constant.
        for rescued in (
            "pollinator_type",
            "hive_count",
            "placement_date",
            "removal_date",
            "pruning_passes",
        ):
            self.assertIn(
                rescued,
                hs.UpdateProductionEventSerializer.EXTRA_DATA_FIELDS,
                f"{rescued} fell out of the production extra_data lift again",
            )
        self.assertEqual(
            problems,
            [],
            "These form fields have NO storage home (not a model column, not in the "
            "family's extra_data lift, not a known pocket) — the wizard collects them "
            f"and DRF silently discards them on save: {problems}",
        )
