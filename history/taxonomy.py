"""The event taxonomy: the one definition of what kinds of activity exist and how they are coded.

Before this module the integer codes 0-7 lived in about 11 copies in the backend (constants
redeclared in fieldnotes, activity_detail, the template seeder, literal ints in the carbon
timeline...) and about 13 in the frontend, with no test comparing the two (schema remodel plan,
2026-11-04). Each copy that drifted was a record filed under the wrong kind.

What lives here, and only here:

- `KINDS`: code, slug and model for each kind. The CODE is the wire value (`?event_type=`), the
  SLUG is the stable name (the v2 seal tags rows with it, `history.seals.V2_KINDS`), the MODEL is
  where the rows are stored. A model may be renamed; code and slug may not change.
- `subtypes(code)`: the stored `type` codes of a kind, read from the model's own `choices`, so the
  model stays their single definition (GeneralEvent has no `type`: free-text `activity_type`).

How the UI groups these (the 17 tiles) is a presentation decision and lives in the frontend
(`config/activityVerbs.ts`). Storage follows the shape of the data, not the tiles.

`history/taxonomy.json` is a generated snapshot of this module for the frontend's parity tests,
which read the backend repo as a sibling checkout. `history/tests/test_taxonomy.py` fails when the
snapshot is stale; regenerate it with `manage.py export_event_taxonomy`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from django.apps import apps


@dataclass(frozen=True)
class Kind:
    code: int
    slug: str
    model_name: str

    @property
    def model(self):
        return apps.get_model("history", self.model_name)


KINDS: Tuple[Kind, ...] = (
    Kind(0, "weather", "WeatherEvent"),
    Kind(1, "production", "ProductionEvent"),
    Kind(2, "chemical", "ChemicalEvent"),
    Kind(3, "general", "GeneralEvent"),
    Kind(4, "equipment", "EquipmentEvent"),
    Kind(5, "soil", "SoilManagementEvent"),
    Kind(6, "pest", "PestManagementEvent"),
    Kind(7, "business", "BusinessEvent"),
)

BY_CODE: Dict[int, Kind] = {k.code: k for k in KINDS}
BY_SLUG: Dict[str, Kind] = {k.slug: k for k in KINDS}
BY_MODEL_NAME: Dict[str, Kind] = {k.model_name: k for k in KINDS}


def kind(code: int) -> Kind:
    return BY_CODE[code]


def kind_of(instance_or_model) -> Kind:
    """The kind of an event instance or event model class."""
    cls = instance_or_model if isinstance(instance_or_model, type) else type(instance_or_model)
    return BY_MODEL_NAME[cls.__name__]


def subtypes(code: int) -> List[Tuple[str, str]]:
    """The stored `type` codes of a kind with their labels, from the model's own choices."""
    model = BY_CODE[code].model
    try:
        field = model._meta.get_field("type")
    except Exception:
        return []
    return [(str(value), str(label)) for value, label in (field.choices or [])]


def snapshot() -> dict:
    """The JSON the frontend parity tests read (`history/taxonomy.json`)."""
    return {
        "kinds": [
            {
                "code": k.code,
                "slug": k.slug,
                "model": k.model_name,
                "subtypes": [code for code, _label in subtypes(k.code)],
            }
            for k in KINDS
        ]
    }
