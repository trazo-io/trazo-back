"""Unit tests for history.services.record_completeness.

DB-free: `missing_required_fields()` only reads attributes off its argument (`event.type`,
`event.commercial_name`, ...), so a plain object stands in for a real `ChemicalEvent` — same
approach as `test_transparency_calculator.py`, and for the same reason: the registry's logic
should be pinned without an Establishment/Parcel/History chain.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase

from history.services.record_completeness import (
    CHEMICAL_EVENT_REQUIRED_FIELDS,
    is_complete,
    missing_required_fields,
    summarize_chemical_events,
)


def chemical_event(**overrides):
    """A ChemicalEvent stand-in with every tracked field blank by default."""
    fields = dict(
        type=None,
        commercial_name=None,
        volume=None,
        volume_numeric=None,
        area=None,
        area_numeric=None,
        target_pest_disease=None,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


COMPLETE_PESTICIDE = dict(
    type="PE",
    commercial_name="Example 10G",
    volume="5",
    area="2",
    target_pest_disease="Aphids",
)


class RegistryShapeTests(SimpleTestCase):
    """Every entry must cite a real CFR section — the whole point of this module."""

    def test_every_required_field_carries_a_citation(self):
        for rf in CHEMICAL_EVENT_REQUIRED_FIELDS:
            self.assertTrue(rf.cfr_cite.startswith("§"), f"{rf.key} has no CFR citation: {rf.cfr_cite!r}")

    def test_registry_covers_product_amount_area_and_target(self):
        keys = {rf.key for rf in CHEMICAL_EVENT_REQUIRED_FIELDS}
        self.assertEqual(keys, {"commercial_name", "volume", "area", "target_pest_disease"})


class MissingRequiredFieldsTests(SimpleTestCase):
    def test_fully_blank_pesticide_event_is_missing_all_four(self):
        event = chemical_event(type="PE")
        missing = missing_required_fields(event)
        self.assertEqual(
            {m["key"] for m in missing},
            {"commercial_name", "volume", "area", "target_pest_disease"},
        )

    def test_complete_pesticide_event_has_nothing_missing(self):
        event = chemical_event(**COMPLETE_PESTICIDE)
        self.assertEqual(missing_required_fields(event), [])
        self.assertTrue(is_complete(event))

    def test_fertilizer_does_not_require_a_target_pest(self):
        """§ 205.206(a) governs pest/weed/disease management — a fertilizer has no target."""
        event = chemical_event(
            type="FE", commercial_name="Urea 46-0-0", volume="50", area="10", target_pest_disease=None
        )
        self.assertEqual(missing_required_fields(event), [])

    def test_fertilizer_still_requires_product_amount_and_area(self):
        event = chemical_event(type="FE")
        missing_keys = {m["key"] for m in missing_required_fields(event)}
        self.assertEqual(missing_keys, {"commercial_name", "volume", "area"})
        self.assertNotIn("target_pest_disease", missing_keys)

    def test_fungicide_and_herbicide_do_require_a_target(self):
        for subtype in ("FU", "HE"):
            with self.subTest(subtype=subtype):
                event = chemical_event(
                    type=subtype, commercial_name="X", volume="1", area="1", target_pest_disease=None
                )
                missing_keys = {m["key"] for m in missing_required_fields(event)}
                self.assertEqual(missing_keys, {"target_pest_disease"})

    def test_unrecorded_subtype_does_not_force_a_target_pest_guess(self):
        """`type` is nullable on the model — an event with no subtype gets a data-integrity flag
        elsewhere (test_event_subtype_validation.py), not a guessed pest requirement here."""
        event = chemical_event(type=None, commercial_name="X", volume="1", area="1")
        self.assertEqual(missing_required_fields(event), [])

    def test_numeric_field_satisfies_amount_and_area_without_the_legacy_string(self):
        """volume_numeric/area_numeric are the newer fields; either form of either field counts."""
        event = chemical_event(
            type="FE",
            commercial_name="X",
            volume=None,
            volume_numeric=12.5,
            area=None,
            area_numeric=3.0,
        )
        self.assertEqual(missing_required_fields(event), [])

    def test_whitespace_only_string_counts_as_missing(self):
        event = chemical_event(type="FE", commercial_name="   ", volume="1", area="1")
        missing_keys = {m["key"] for m in missing_required_fields(event)}
        self.assertEqual(missing_keys, {"commercial_name"})

    def test_missing_field_entries_carry_the_citation(self):
        event = chemical_event(type="PE")
        by_key = {m["key"]: m["cfr_cite"] for m in missing_required_fields(event)}
        self.assertEqual(by_key["commercial_name"], "§ 205.103(b)(2)")
        self.assertEqual(by_key["target_pest_disease"], "§ 205.206(a)")


class SummarizeChemicalEventsTests(SimpleTestCase):
    def test_empty_list_is_trivially_complete(self):
        summary = summarize_chemical_events([])
        self.assertEqual(summary.total, 0)
        self.assertTrue(summary.all_complete)

    def test_mixed_events_count_correctly(self):
        events = [
            chemical_event(**COMPLETE_PESTICIDE),
            chemical_event(type="PE"),  # missing everything
            chemical_event(type="FE", commercial_name="X", volume="1", area="1"),  # complete FE
        ]
        summary = summarize_chemical_events(events)
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.complete, 2)
        self.assertEqual(summary.incomplete, 1)
        self.assertFalse(summary.all_complete)

    def test_missing_field_counts_tally_across_events(self):
        events = [chemical_event(type="PE"), chemical_event(type="PE")]
        summary = summarize_chemical_events(events)
        self.assertEqual(summary.missing_field_counts["product name"], 2)
        self.assertEqual(summary.missing_field_counts["target pest or disease"], 2)

    def test_example_missing_labels_come_from_first_incomplete_event(self):
        events = [chemical_event(**COMPLETE_PESTICIDE), chemical_event(type="FE")]
        summary = summarize_chemical_events(events)
        self.assertEqual(set(summary.example_missing_labels), {"product name", "amount applied", "area treated"})
