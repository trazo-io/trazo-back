"""
WS-4 field adds (parity plan Part 3): harvest-record completeness + input scope.

What matters:
  1. New fields persist and round-trip through the serializers.
  2. harvest_date_end before the harvest start date is refused at clean().
  3. NULL buffer_disposition stays NULL — absence of an answer is not a denial
     (7 CFR 205.202(c) posture).
"""

from datetime import date, datetime, timezone

from django.core.exceptions import ValidationError
from django.test import TestCase

from company.models import Company, Establishment
from history.models import ChemicalEvent, Production, ProductionEvent
from history.serializers import ProductionEventSerializer, UpdateProductionEventSerializer
from product.models import Parcel, Product


class WS4FieldAddsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="WS4 Farm")
        self.establishment = Establishment.objects.create(name="WS4 Ranch", company=self.company, state="CA")
        product = Product.objects.create(name="Walnut")
        self.parcel = Parcel.objects.create(name="Block A", establishment=self.establishment, area=10.0)
        self.history = Production.objects.create(
            name="2026", parcel=self.parcel, product=product, start_date=date(2026, 3, 1)
        )

    def _harvest(self, **kwargs):
        return ProductionEvent(
            history=self.history,
            type=ProductionEvent.HARVESTING,
            date=datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc),
            description="Walnut shake and pickup, north block",
            **kwargs,
        )

    def test_harvest_fields_persist_and_serialize(self):
        ev = self._harvest(
            amount_determination="scale_verified",
            harvest_date_end=date(2026, 8, 7),
            harvest_destination="stored",
            storage_location="Cooler 3",
            buffer_disposition="not_harvested",
        )
        ev.full_clean()
        ev.save()

        row = ProductionEvent.objects.get(pk=ev.pk)
        self.assertEqual(row.amount_determination, "scale_verified")
        self.assertEqual(row.harvest_date_end, date(2026, 8, 7))
        self.assertEqual(row.harvest_destination, "stored")
        self.assertEqual(row.buffer_disposition, "not_harvested")

        data = ProductionEventSerializer(row).data
        self.assertEqual(data["amount_determination"], "scale_verified")
        self.assertEqual(data["harvest_destination"], "stored")
        self.assertEqual(data["buffer_disposition"], "not_harvested")

    def test_harvest_end_before_start_refused(self):
        ev = self._harvest(harvest_date_end=date(2026, 8, 1))
        with self.assertRaises(ValidationError) as ctx:
            ev.full_clean()
        self.assertIn("harvest_date_end", ctx.exception.message_dict)

    def test_buffer_disposition_null_stays_null(self):
        ev = self._harvest()
        ev.full_clean()
        ev.save()
        self.assertIsNone(ProductionEvent.objects.get(pk=ev.pk).buffer_disposition)

    def test_update_serializer_accepts_new_fields(self):
        ev = self._harvest()
        ev.save()
        ser = UpdateProductionEventSerializer(
            ev,
            data={
                "amount_determination": "estimated",
                "harvest_destination": "sold_direct",
            },
            partial=True,
        )
        self.assertTrue(ser.is_valid(), ser.errors)
        ser.save()
        ev.refresh_from_db()
        self.assertEqual(ev.amount_determination, "estimated")
        self.assertEqual(ev.harvest_destination, "sold_direct")

    def test_invalid_choice_refused(self):
        ser = UpdateProductionEventSerializer(self._harvest(), data={"amount_determination": "guessed"}, partial=True)
        self.assertFalse(ser.is_valid())
        self.assertIn("amount_determination", ser.errors)

    def test_chemical_applied_scope_roundtrip(self):
        ev = ChemicalEvent(
            history=self.history,
            type="PE",
            date=datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc),
            commercial_name="Entrust SC",
            description="Spinosad application for codling moth",
            applied_scope="part",
            applied_scope_detail="Rows 1-12, north block",
        )
        ev.full_clean()
        ev.save()
        row = ChemicalEvent.objects.get(pk=ev.pk)
        self.assertEqual(row.applied_scope, "part")
        self.assertEqual(row.applied_scope_detail, "Rows 1-12, north block")
