"""history/taxonomy.py is the one definition of the event kinds, and everything else agrees with it."""

from django.test import SimpleTestCase

from history import constants, seals, taxonomy
from history.management.commands.export_event_taxonomy import SNAPSHOT_PATH, render

#: The wire contract, written out on purpose. A code is what `?event_type=` carries and what six
#: tables store in `(event_type, event_id)` pairs; a slug is what v2 seals hash. Changing either
#: silently re-files records under another kind, so this list may only ever GROW.
FROZEN = {
    0: "weather",
    1: "production",
    2: "chemical",
    3: "general",
    4: "equipment",
    5: "soil",
    6: "pest",
    7: "business",
}


class TaxonomyTests(SimpleTestCase):
    def test_codes_and_slugs_are_frozen(self):
        self.assertEqual({k.code: k.slug for k in taxonomy.KINDS}, FROZEN)

    def test_codes_slugs_and_models_are_unique(self):
        for attr in ("code", "slug", "model_name"):
            values = [getattr(k, attr) for k in taxonomy.KINDS]
            self.assertEqual(len(values), len(set(values)), attr)

    def test_every_kind_names_a_real_model(self):
        for k in taxonomy.KINDS:
            with self.subTest(kind=k.slug):
                self.assertEqual(k.model.__name__, k.model_name)

    def test_constants_are_read_from_the_taxonomy(self):
        expected = {
            "WEATHER_EVENT_TYPE": "weather",
            "PRODUCTION_EVENT_TYPE": "production",
            "CHEMICAL_EVENT_TYPE": "chemical",
            "GENERAL_EVENT_TYPE": "general",
            "EQUIPMENT_EVENT_TYPE": "equipment",
            "SOIL_MANAGEMENT_EVENT_TYPE": "soil",
            "PEST_MANAGEMENT_EVENT_TYPE": "pest",
            "BUSINESS_EVENT_TYPE": "business",
        }
        for name, slug in expected.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(constants, name), taxonomy.BY_SLUG[slug].code)

    def test_event_type_to_model_matches_the_taxonomy(self):
        self.assertEqual(
            {code: model.__name__ for code, model in constants.EVENT_TYPE_TO_MODEL.items()},
            {k.code: k.model_name for k in taxonomy.KINDS},
        )

    def test_the_v2_seal_tags_with_the_taxonomy_slugs(self):
        """seals.V2_KINDS is a frozen copy (a seal's bytes must not move); it may not drift."""
        self.assertEqual(dict(seals.V2_KINDS), {k.model_name: k.slug for k in taxonomy.KINDS})

    def test_other_modules_use_the_taxonomy_codes(self):
        from fieldnotes.services import confirmation
        from history.services import activity_detail

        self.assertEqual(
            (confirmation.CHEMICAL, confirmation.SOIL, confirmation.PEST),
            (taxonomy.BY_SLUG["chemical"].code, taxonomy.BY_SLUG["soil"].code, taxonomy.BY_SLUG["pest"].code),
        )
        self.assertEqual(
            (activity_detail.PRODUCTION_EVENT, activity_detail.CHEMICAL_EVENT),
            (taxonomy.BY_SLUG["production"].code, taxonomy.BY_SLUG["chemical"].code),
        )

    def test_subtypes_come_from_the_models_own_choices(self):
        from history.models import ChemicalEvent, GeneralEvent, ProductionEvent

        self.assertEqual(
            [code for code, _ in taxonomy.subtypes(1)],
            [code for code, _ in ProductionEvent._meta.get_field("type").choices],
        )
        self.assertEqual(
            [code for code, _ in taxonomy.subtypes(2)],
            [code for code, _ in ChemicalEvent._meta.get_field("type").choices],
        )
        self.assertFalse(hasattr(GeneralEvent, "type") and GeneralEvent._meta.get_field("type"), "General has no type")
        self.assertEqual(taxonomy.subtypes(3), [])

    def test_kind_of_resolves_instances_and_classes(self):
        from history.models import SoilManagementEvent

        self.assertEqual(taxonomy.kind_of(SoilManagementEvent).slug, "soil")
        self.assertEqual(taxonomy.kind_of(SoilManagementEvent()).code, 5)

    def test_the_committed_snapshot_is_current(self):
        """The frontend parity tests read history/taxonomy.json from this repo."""
        self.assertEqual(
            SNAPSHOT_PATH.read_text(encoding="utf-8"),
            render(),
            "history/taxonomy.json is stale: run `manage.py export_event_taxonomy` and commit it",
        )
