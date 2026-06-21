"""Regression: blank nullable date fields must NOT 400 the event.

The add-event form posts EVERY field for EVERY subtype, so a date column that is
irrelevant to the chosen subtype arrives as an empty string "". DRF's Date/DateTimeField
rejects "" ("Date has wrong format"), which 400'd the whole event with NO user-facing error
(the form swallowed the response). This hit:
  - Production seed_purchase_date / placement_date / removal_date (non-planting events)
  - Production cleaning_date (Harvest / Post-Harvest / Equipment events)
  - Chemical purchase_date / ca_dpr_permit_expires (subtypes that don't use them)

Fix: ``coerce_blank_nullable_dates()`` introspects each serializer's declared fields and
coerces "" -> None for every ``allow_null`` date field, so no hand-maintained list can miss
one. These tests lock that behaviour in at the serializer layer.
"""

from django.test import TestCase

from history.serializers import UpdateChemicalEventSerializer, UpdateProductionEventSerializer


class BlankDateCoercionTests(TestCase):
    def _blank_date_errors(self, serializer_cls, base, blank_date_fields):
        data = dict(base)
        for f in blank_date_fields:
            data[f] = ""
        serializer = serializer_cls(data=data)
        serializer.is_valid()
        return {f: serializer.errors[f] for f in blank_date_fields if f in serializer.errors}

    def test_production_non_planting_blank_dates_do_not_error(self):
        """Harvest event with every nullable date blank must validate (cleaning_date was missed
        by the original hand-maintained list and 400'd every Harvest/Post-Harvest event)."""
        errs = self._blank_date_errors(
            UpdateProductionEventSerializer,
            {
                "date": "2026-09-15T08:00",
                "type": "HA",
                "event_type": 1,
                "name": "Harvest",
                "description": "Harvest",
                "area_covered": "1",
                "parcels": ["183"],
            },
            ["seed_purchase_date", "placement_date", "removal_date", "cleaning_date"],
        )
        self.assertEqual(errs, {}, f"blank production dates should coerce to null, got: {errs}")

    def test_chemical_blank_dates_do_not_error(self):
        """Pesticide event with blank purchase_date / ca_dpr_permit_expires must validate."""
        errs = self._blank_date_errors(
            UpdateChemicalEventSerializer,
            {
                "date": "2026-04-10T09:00",
                "type": "PE",
                "event_type": 2,
                "name": "Spray",
                "description": "Spray",
                "volume": "1",
                "area": "1",
                "parcels": ["183"],
            },
            ["purchase_date", "ca_dpr_permit_expires"],
        )
        self.assertEqual(errs, {}, f"blank chemical dates should coerce to null, got: {errs}")
