"""
F21 (2026-06): supervisor review / sign-off + GLOBALG.A.P. authorizer.

- FSMA Produce Safety Rule § 112.161(b): records reviewed by a supervisor
  (reviewer name + review date). Universal review fields live on CommonEvent.
- GLOBALG.A.P. IFA v6 FV-GFS 32.02.01 #10: the technically-responsible person who
  authorized a plant-protection-product application (authorizer_name on ChemicalEvent).

These lock the round-trip through the chemical serializer (create path) and confirm
the review fields exist on every event type's model (CommonEvent).
"""

from datetime import date

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import (
    ChemicalEvent,
    GeneralEvent,
    History,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from history.serializers import ChemicalEventSerializer, UpdateChemicalEventSerializer
from product.models import Parcel, Product
from users.models import User


class EventReviewSignoffTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="f21@test.com", password="x")
        self.company = Company.objects.create(name="F21 Co")
        self.establishment = Establishment.objects.create(name="F21E", company=self.company)
        self.parcel = Parcel.objects.create(name="F21P", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Avocado")
        self.history = History.objects.create(
            name="F21 Prod",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def test_chemical_authorizer_and_review_round_trip(self):
        payload = {
            "history": self.history.id,
            "type": "PE",
            "date": "2026-06-13T07:00:00Z",
            "commercial_name": "Entrust SC",
            "volume_applied": "12",
            "area_treated": "8",
            "application_method": "ground_spray",
            "authorizer_name": "J. Smith, PCA #12345",
            "reviewed": True,
            "reviewer_name": "Office Manager",
            "review_date": "2026-07-02",
        }
        s = UpdateChemicalEventSerializer(data=payload)
        self.assertTrue(s.is_valid(), f"errors: {dict(s.errors)}")
        e = s.save()
        e.refresh_from_db()
        self.assertEqual(e.authorizer_name, "J. Smith, PCA #12345")
        self.assertTrue(e.reviewed)
        self.assertEqual(e.reviewer_name, "Office Manager")
        self.assertEqual(e.review_date, date(2026, 7, 2))

        # Read serializer exposes them for edit / farmer modal.
        rep = ChemicalEventSerializer(e).data
        self.assertEqual(rep.get("authorizer_name"), "J. Smith, PCA #12345")
        self.assertTrue(rep.get("reviewed"))
        self.assertEqual(rep.get("reviewer_name"), "Office Manager")

    def test_review_fields_on_all_event_types(self):
        # The review trio is universal (CommonEvent) — every concrete event has it.
        for model in (ChemicalEvent, ProductionEvent, WeatherEvent, SoilManagementEvent, GeneralEvent):
            field_names = {f.name for f in model._meta.get_fields()}
            for f in ("reviewed", "reviewer_name", "review_date"):
                self.assertIn(f, field_names, f"{model.__name__} missing review field {f}")

    def test_review_defaults_unreviewed(self):
        e = ChemicalEvent.objects.create(history=self.history, type="PE", commercial_name="x", date=timezone.now())
        self.assertFalse(e.reviewed)
        self.assertIsNone(e.reviewer_name)
        self.assertIsNone(e.review_date)
