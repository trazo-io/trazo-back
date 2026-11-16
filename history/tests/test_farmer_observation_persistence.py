"""The farmer's own words must survive the write path on every event type.

The event form's "Observations & Notes" field posts as `observation`, but every branch of
`cleanEventData` renamed it to `description` (CommonEvent.description is NOT NULL) and nothing
else. So the `observation` column stayed empty on every UI-logged event — and
ConsumerEventCard renders ONLY `observation`, quoted and attributed to the grower. A farmer was
shown "Your notes will be public — published as written", typed a paragraph about their season,
and no shopper ever saw a word of it.

Two properties are load-bearing and are pinned below:

  1. A note the farmer typed reaches the `observation` column, on ALL SEVEN event models —
     soil and pest had no such column at all before migration 0188.
  2. A `description` with no farmer note leaves `observation` empty. This is the honesty rule
     the 2026-08-01 removal of the `observation = description` mirror in eventDataNormalizer
     was written to protect: 328+ AI templates write `description`, and quoting machine copy in
     quotation marks as a grower's own words would be a fabricated consumer claim.
"""

import datetime as dt

from django.test import TestCase

from company.models import Company, Establishment
from history.models import Production
from history.serializers import (
    UpdateBusinessEventSerializer,
    UpdateChemicalEventSerializer,
    UpdateGeneralEventSerializer,
    UpdatePestManagementEventSerializer,
    UpdateProductionEventSerializer,
    UpdateSoilManagementEventSerializer,
    UpdateWeatherEventSerializer,
)
from product.models import Parcel, Product

FARMER_NOTE = (
    "We drill the cover mix the week after the first real rain and let it flower before we mow. "
    "My grandfather planted this block in 1974 and the middles have never been bare since."
)
TEMPLATE_DESCRIPTION = "Cover crop planted per NOP 7 CFR 205.203(b) soil fertility practice standard."

# (serializer, extra payload needed to satisfy that event type's required fields)
EVENT_SERIALIZERS = [
    (UpdateProductionEventSerializer, {"type": "IR"}),
    (UpdateChemicalEventSerializer, {"type": "FE", "commercial_name": "Fish emulsion"}),
    (UpdateSoilManagementEventSerializer, {"type": "CC"}),
    (UpdatePestManagementEventSerializer, {"type": "TM"}),
    (
        UpdateBusinessEventSerializer,
        {"type": "CE", "business_type": "certification", "certification_type": "organic_usda"},
    ),
    # GeneralEvent requires its own `name`.
    (UpdateGeneralEventSerializer, {"name": "Orchard walk"}),
    (UpdateWeatherEventSerializer, {"type": "FR"}),
]


class FarmerObservationPersistenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = Company.objects.create(name="Dry Creek Groves LLC")
        establishment = Establishment.objects.create(company=company, name="Dry Creek Home Ranch", state="CA")
        parcel = Parcel.objects.create(name="Block 4", establishment=establishment, area=15.62)
        product = Product.objects.create(name="Walnuts")
        cls.history = Production.objects.create(
            name="2024 Chandler Walnut Season",
            start_date=dt.datetime(2024, 2, 1, tzinfo=dt.timezone.utc),
            parcel=parcel,
            product=product,
        )

    def _payload(self, extra):
        payload = {
            "history": self.history.id,
            "date": "2024-02-20T08:00:00Z",
            "description": FARMER_NOTE,
        }
        payload.update(extra)
        return payload

    def test_observation_is_accepted_and_persisted_on_every_event_type(self):
        """Soil and pest are the point: neither had an `observation` column before 0188."""
        for serializer_cls, extra in EVENT_SERIALIZERS:
            with self.subTest(serializer=serializer_cls.__name__):
                payload = self._payload(extra)
                payload["observation"] = FARMER_NOTE
                serializer = serializer_cls(data=payload)
                self.assertTrue(serializer.is_valid(), serializer.errors)
                event = serializer.save()
                event.refresh_from_db()
                self.assertEqual(
                    (event.observation or "").strip(),
                    FARMER_NOTE,
                    f"{serializer_cls.__name__} dropped the farmer's note",
                )

    def test_a_description_without_a_farmer_note_leaves_observation_empty(self):
        """The anti-fabrication rule: template copy must never become a quoted grower voice."""
        for serializer_cls, extra in EVENT_SERIALIZERS:
            with self.subTest(serializer=serializer_cls.__name__):
                payload = self._payload(extra)
                payload["description"] = TEMPLATE_DESCRIPTION
                serializer = serializer_cls(data=payload)
                self.assertTrue(serializer.is_valid(), serializer.errors)
                event = serializer.save()
                event.refresh_from_db()
                self.assertFalse(
                    (event.observation or "").strip(),
                    f"{serializer_cls.__name__} mirrored a template description into observation — "
                    "that renders to shoppers as the farmer's own words",
                )

    def test_description_is_still_populated_alongside_the_note(self):
        """`description` is NOT NULL and feeds the producer modal + the certifier PDF.

        The frontend keeps renaming observation -> description; sending both must not blank it.
        """
        for serializer_cls, extra in EVENT_SERIALIZERS:
            with self.subTest(serializer=serializer_cls.__name__):
                payload = self._payload(extra)
                payload["observation"] = FARMER_NOTE
                serializer = serializer_cls(data=payload)
                self.assertTrue(serializer.is_valid(), serializer.errors)
                event = serializer.save()
                event.refresh_from_db()
                self.assertTrue((event.description or "").strip(), f"{serializer_cls.__name__} left description empty")
