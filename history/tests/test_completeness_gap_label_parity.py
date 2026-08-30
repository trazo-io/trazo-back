"""Every completeness-gap key the API can emit must have a human label in the farmer's toast.

WHY (2026-08-27): `EventViewSet` echoes `completeness_gaps` on the 201/200 of an event save —
MACHINE KEYS, deliberately, because the human wording and its translation belong to the
frontend. `NewEvent.jsx` maps them through `COMPLETENESS_GAP_LABELS`.

That map was written for v1's four `ChemicalEvent` fields and never grew. The backend since
added `quantity_purchased` (§ 205.103(b)(2), conditional on purchase evidence) and the five
§ 205.204 seed fields for `SEED_SOURCED_SUBTYPES` — six of ten keys with no entry. The renderer
fell through to the key itself, so a grower saving a planting was told, in both locales:

    Saved — a certifier will also want: seed_certification_status, seed_search_attempts

A comment saying "keep these in step" is what the certifier-only strip list had, and it did not
work there either (see test_certifier_only_list_parity.py). This is the invariant.

Direction is one-way, same as that test: the backend registries are the authority and every key
they can produce must be mapped. Extra frontend entries are fine — a key retired from a registry
costs nothing sitting in the map.
"""

import json
import re
from pathlib import Path

from django.test import SimpleTestCase

from history.services.record_completeness import CHEMICAL_EVENT_REQUIRED_FIELDS, PLANTING_EVENT_REQUIRED_FIELDS

_REPO = Path(__file__).resolve().parents[3]
NEW_EVENT = _REPO / "trazo-app" / "src" / "views" / "Dashboard" / "Dashboard" / "components" / "forms" / "NewEvent.jsx"
LOCALES = [
    _REPO / "trazo-app" / "src" / "i18n" / "lang" / "en-US.json",
    _REPO / "trazo-app" / "src" / "i18n" / "lang" / "es-419.json",
]


def _emittable_keys() -> set:
    """Every key `completeness_gap_keys()` can return, from the registries themselves.

    Reads the registries rather than restating them: a list retyped here would go stale in
    exactly the way this test exists to prevent.
    """
    return {rf.key for rf in (*CHEMICAL_EVENT_REQUIRED_FIELDS, *PLANTING_EVENT_REQUIRED_FIELDS)}


def _parse_label_map(source: str) -> dict:
    """{gap_key: message_id} from COMPLETENESS_GAP_LABELS in NewEvent.jsx."""
    match = re.search(r"const COMPLETENESS_GAP_LABELS = \{(.*?)\n\};", source, re.DOTALL)
    if match is None:
        return {}
    body = match.group(1)
    return dict(re.findall(r"(\w+):\s*\{\s*id:\s*'([^']+)'", body))


class CompletenessGapLabelParityTests(SimpleTestCase):
    def setUp(self):
        if not NEW_EVENT.exists():
            self.skipTest(f"frontend checkout not present at {NEW_EVENT}")
        self.mapped = _parse_label_map(NEW_EVENT.read_text(encoding="utf-8"))
        self.assertGreaterEqual(
            len(self.mapped),
            4,
            "parsed suspiciously few entries out of COMPLETENESS_GAP_LABELS — if it was renamed "
            "or reshaped, update this test rather than deleting it.",
        )

    def test_registries_are_not_empty(self):
        """Anti-vacuity: an empty key set would make every assertion below pass on nothing."""
        self.assertGreater(len(_emittable_keys()), 8)

    def test_every_emittable_gap_key_has_a_frontend_label(self):
        missing = sorted(_emittable_keys() - set(self.mapped))
        self.assertEqual(
            missing,
            [],
            "These completeness_gaps keys reach the farmer's save toast as raw Python "
            f"identifiers: {missing}. Add them to COMPLETENESS_GAP_LABELS in "
            "trazo-app/src/views/Dashboard/Dashboard/components/forms/NewEvent.jsx, with an "
            "entry in BOTH locale files.",
        )

    def test_every_label_id_is_defined_in_both_locales(self):
        wanted_ids = {self.mapped[key] for key in _emittable_keys() if key in self.mapped}
        for locale in LOCALES:
            if not locale.exists():
                self.skipTest(f"locale file not present at {locale}")
            messages = json.loads(locale.read_text(encoding="utf-8"))
            missing = sorted(wanted_ids - set(messages))
            self.assertEqual(
                missing,
                [],
                f"{locale.name} has no translation for {missing}. react-intl would fall back to "
                "the English defaultMessage and log a missing-message error.",
            )
