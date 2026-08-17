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
    completeness_gap_keys,
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

    def test_registry_covers_product_amount_area_target_and_purchase_quantity(self):
        keys = {rf.key for rf in CHEMICAL_EVENT_REQUIRED_FIELDS}
        self.assertEqual(
            keys,
            {"commercial_name", "volume", "area", "target_pest_disease", "quantity_purchased"},
        )

    def test_conditional_entries_declare_when_they_apply(self):
        # A field that is required only sometimes must say so in the registry rather than in
        # a caller. `quantity_purchased` is the first such entry: it is owed once the operator
        # has asserted a purchase, not on every application.
        conditional = [rf for rf in CHEMICAL_EVENT_REQUIRED_FIELDS if rf.applies_when is not None]
        self.assertEqual([rf.key for rf in conditional], ["quantity_purchased"])


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


class CompletenessGapKeysTests(SimpleTestCase):
    """`completeness_gap_keys` is the API-payload projection — keys only, same source registry."""

    def test_projects_keys_in_registry_order(self):
        event = chemical_event(type="PE")
        self.assertEqual(
            completeness_gap_keys(event),
            ["commercial_name", "volume", "area", "target_pest_disease"],
        )

    def test_complete_event_projects_an_empty_list(self):
        self.assertEqual(completeness_gap_keys(chemical_event(**COMPLETE_PESTICIDE)), [])


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


class PurchaseQuantityConditionalTests(SimpleTestCase):
    """§ 205.103(b)(2) — records must span "purchase or acquisition, through production".

    A certifier closes that trace by mass balance, and the packet says so itself when it
    cannot: "Mass balance cannot be reconciled. No purchase quantity is recorded on any
    chemical event." Measured 2026-08-11, that was true of 289 of 289 chemical events.

    The requirement is CONDITIONAL on purchase evidence, and the restraint is deliberate: not
    every application is a purchase. Inputs carry over from last season, get produced on farm,
    or arrive with a custom applicator — demanding a purchase quantity there would be Trazo
    inventing a requirement the regulation does not make, which is the exact mistake this
    module's docstring exists to prevent.
    """

    def test_silent_when_no_purchase_was_asserted(self):
        event = chemical_event(**COMPLETE_PESTICIDE)
        self.assertNotIn("quantity_purchased", {m["key"] for m in missing_required_fields(event)})
        self.assertTrue(is_complete(event), "an application with no purchase claim must stay complete")

    def test_fires_once_any_purchase_evidence_exists(self):
        for attr, value in [
            ("supplier_name", "Valley Ag Supply"),
            ("purchase_date", "2026-03-01"),
            ("purchase_invoice", "INV-77"),
            ("chemical_lot_number", "LOT-9"),
        ]:
            with self.subTest(evidence=attr):
                event = chemical_event(**COMPLETE_PESTICIDE, **{attr: value})
                missing = {m["key"] for m in missing_required_fields(event)}
                self.assertIn("quantity_purchased", missing, f"{attr} asserts a purchase with no quantity")

    def test_satisfied_when_the_quantity_is_recorded(self):
        event = chemical_event(**COMPLETE_PESTICIDE, supplier_name="Valley Ag Supply", quantity_purchased=40)
        self.assertEqual(missing_required_fields(event), [])

    def test_zero_is_a_recorded_quantity_not_a_blank(self):
        # Decimal("0")/0 are falsy. `_present` returns True for them by design — a recorded
        # zero is data, and the falsy-vs-None conflation has already produced two bugs in this
        # codebase (the NPK total and the carbon-credits validator).
        event = chemical_event(**COMPLETE_PESTICIDE, purchase_invoice="INV-77", quantity_purchased=0)
        self.assertEqual(missing_required_fields(event), [])

    def test_carries_the_span_citation(self):
        event = chemical_event(**COMPLETE_PESTICIDE, supplier_name="Valley Ag Supply")
        entry = next(m for m in missing_required_fields(event) if m["key"] == "quantity_purchased")
        self.assertEqual(entry["cfr_cite"], "§ 205.103(b)(2)")


class ManurePlannedHarvestFieldTests(SimpleTestCase):
    """USDA's crop form records estimated AND actual harvest dates side by side.

    Trazo enforced § 205.203(c)(1) against the ACTUAL harvest all along
    (`_validate_raw_manure_harvest_interval`), but stored no estimate — so a harvest that
    slipped and a plan that was never sound looked identical in the record. Tier 3, form #9.
    """

    def test_field_exists_on_the_model_with_the_right_shape(self):
        from history.models import SoilManagementEvent

        field = SoilManagementEvent._meta.get_field("manure_harvest_date_planned")
        self.assertEqual(field.get_internal_type(), "DateField")
        # Blank = not recorded. A defaulted date would read as an affirmative plan.
        self.assertTrue(field.null and field.blank)

    def test_exposed_by_both_serializers(self):
        # Read-only exposure would let a grower see the column but never fill it; update-only
        # would let them fill it and never see it back. The house standard is both.
        from history.serializers import UpdateSoilManagementEventSerializer

        self.assertIn("manure_harvest_date_planned", UpdateSoilManagementEventSerializer.Meta.fields)

    def test_blank_date_is_coerced_to_null_not_sent_as_empty_string(self):
        """A cleared date input submits "", which a DRF DateField rejects with a 400.

        The serializer coerces its listed date fields to None. This asserts the BEHAVIOUR
        rather than grepping the source for `date_fields` — the first version of this test did
        exactly that, and broke the moment the file was edited while the suite was running,
        because `inspect.getsource` reads from disk through linecache.
        """
        from history.serializers import UpdateSoilManagementEventSerializer

        serializer = UpdateSoilManagementEventSerializer(data={"manure_harvest_date_planned": ""}, partial=True)
        self.assertTrue(
            serializer.is_valid(),
            f"blank planned-harvest date rejected instead of coerced: {serializer.errors}",
        )
        self.assertIsNone(serializer.validated_data.get("manure_harvest_date_planned", "sentinel"))
