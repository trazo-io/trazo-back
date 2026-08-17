"""
Buffer-zone write-path tests (2026-06 NOP-alignment audit, P0 BLOCKER A0).

Parcel.buffer_zones (7 CFR 205.202(c) per-boundary adjoining-land / drift-prevention
record) previously had no writable serializer, so a real pilot farmer could not record
buffers and the audit export fired the empty-state REVIEW flag on every non-seeded parcel.
These tests lock the write path, the structural validation, and the exact key shape the
audit export consumes (audit_export_service buffer-zone / field-map sections).
"""

from django.test import TestCase

from rest_framework.test import APIRequestFactory

from company.models import Company, Establishment
from product.models import Parcel
from product.serializers import CreateParcelSerializer, RetrieveParcelSerializer
from product.services.buffer_zones import CANONICAL_KEYS
from users.models import User

# The one canonical vocabulary, owned by product.services.buffer_zones. Every write path
# normalizes to exactly these keys — the 2026-08-09 P0 was two writers owning two different
# spellings of the same record.
EXPORT_BUFFER_KEYS = set(CANONICAL_KEYS)


class BufferZoneWritePathTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(email="buffer@test.com", password="x")
        self.company = Company.objects.create(name="Buffer Farm")
        self.establishment = Establishment.objects.create(name="BF1", company=self.company)

    def _ctx(self):
        # create()/update() read request.FILES; a JSON request carries an empty FILES.
        return {"request": self.factory.post("/", {}, format="json")}

    def _valid_buffers(self):
        return [
            {
                "direction": "North",
                "adjoining_land_use": "Conventional walnut orchard",
                "buffer_width_m": 8,
                "drift_risk": "Medium",
                "prevention": "8 m vegetative hedgerow + annual neighbor-notification letter",
                # CCOF OSP Sections D & E — legacy spellings, still accepted as aliases.
                "adjacent_organic": True,
                "buffer_type": "Hedgerow",
                "crop_in_buffer": "Unharvested native cover",
                # § 205.400(f)(1)
                "neighbor_notified": True,
                "neighbor_notification_date": "2026-02-15",
            },
            {
                "direction": "South",
                "adjoining_land_use": "Farm road",
                "buffer_width_m": "12",  # string coerces to float
                "drift_risk": "Low",
                "prevention": "Grass strip",
            },
        ]

    def test_create_persists_buffer_zones(self):
        data = {
            "name": "Tres Robles Block A",
            "establishment": self.establishment.id,
            "area": 32.0,
            "buffer_zones": self._valid_buffers(),
        }
        ser = CreateParcelSerializer(data=data, context=self._ctx())
        self.assertTrue(ser.is_valid(), ser.errors)
        parcel = ser.save()
        parcel.refresh_from_db()
        self.assertEqual(len(parcel.buffer_zones), 2)
        north = parcel.buffer_zones[0]
        self.assertEqual(set(north.keys()), EXPORT_BUFFER_KEYS)
        self.assertEqual(north["direction"], "North")
        self.assertEqual(north["buffer_width_m"], 8.0)
        # Feet derived from the metric entry — the farmer-facing unit is always populated.
        self.assertEqual(north["buffer_width_ft"], 26.2)
        # CCOF OSP Sections D & E round-trip, under the canonical spelling.
        self.assertIs(north["adjacent_is_organic"], True)
        self.assertEqual(north["buffer_type"], "Hedgerow")
        self.assertEqual(north["crop_grown_in_buffer"], "Unharvested native cover")
        self.assertIs(north["neighbor_notified"], True)
        self.assertEqual(north["neighbor_notification_date"], "2026-02-15")
        # Omitted D&E fields stay UNANSWERED (None), never an affirmative False. A stored
        # False is a claim the operator did not make — "the neighbour is not certified
        # organic" is a statement about someone else's farm.
        south = parcel.buffer_zones[1]
        self.assertIsNone(south["adjacent_is_organic"])
        self.assertIsNone(south["buffer_type"])
        self.assertIsNone(south["crop_grown_in_buffer"])
        self.assertIsNone(south["neighbor_notified"])
        self.assertIsNone(south["neighbor_notification_date"])
        # String width coerced to float so the export's numeric "X m" formatting works.
        self.assertEqual(south["buffer_width_m"], 12.0)

    def test_update_adds_buffer_zones_to_existing_parcel(self):
        parcel = Parcel.objects.create(name="Block B", establishment=self.establishment, area=18.0)
        self.assertIn(parcel.buffer_zones, (None, [], {}))  # none on file initially
        ser = CreateParcelSerializer(
            parcel,
            data={"buffer_zones": self._valid_buffers()},
            partial=True,
            context=self._ctx(),
        )
        self.assertTrue(ser.is_valid(), ser.errors)
        ser.save()
        parcel.refresh_from_db()
        self.assertEqual(len(parcel.buffer_zones), 2)

    def test_retrieve_serializer_exposes_buffer_zones(self):
        parcel = Parcel.objects.create(
            name="Block C",
            establishment=self.establishment,
            area=10.0,
            buffer_zones=self._valid_buffers(),
        )
        data = RetrieveParcelSerializer(parcel).data
        self.assertIn("buffer_zones", data)
        self.assertEqual(len(data["buffer_zones"]), 2)

    def test_missing_direction_rejected(self):
        bad = [{"adjoining_land_use": "Conventional orchard", "buffer_width_m": 8}]
        ser = CreateParcelSerializer(
            data={"name": "X", "establishment": self.establishment.id, "area": 5.0, "buffer_zones": bad},
            context=self._ctx(),
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("buffer_zones", ser.errors)

    def test_non_numeric_width_rejected(self):
        bad = [{"direction": "North", "adjoining_land_use": "Orchard", "buffer_width_m": "wide"}]
        ser = CreateParcelSerializer(
            data={"name": "X", "establishment": self.establishment.id, "area": 5.0, "buffer_zones": bad},
            context=self._ctx(),
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("buffer_zones", ser.errors)

    def test_non_list_rejected(self):
        ser = CreateParcelSerializer(
            data={
                "name": "X",
                "establishment": self.establishment.id,
                "area": 5.0,
                "buffer_zones": {"direction": "N"},
            },
            context=self._ctx(),
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("buffer_zones", ser.errors)
