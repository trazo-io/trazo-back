"""
NOP 7 CFR 205.202 — Transition status service tests (Sprint 2.2).
"""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel, ParcelCropHistory, Product
from product.services.transition_status_service import TRANSITION_MONTHS, compute_transition_status
from users.models import User


class TransitionStatusServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="t@test.com", password="x")
        self.company = Company.objects.create(name="Transition Farm")
        self.establishment = Establishment.objects.create(name="Field T", company=self.company)
        self.parcel = Parcel.objects.create(name="P-T", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Tomato")

    def _new_history(self):
        return History.objects.create(
            name="H",
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
        )

    def test_no_evidence_returns_eligible_with_note(self):
        status = compute_transition_status(self.parcel)
        self.assertTrue(status.is_eligible)
        self.assertEqual(status.findings, [])
        self.assertIn("affidavits", status.note)

    def test_old_prohibited_substance_eligible(self):
        old = date.today() - relativedelta(months=TRANSITION_MONTHS) - timedelta(days=30)
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=old.year,
            crop_grown="Wheat",
            production_method="conventional",
            substances_applied="Glyphosate",
            date_last_prohibited=old,
        )
        status = compute_transition_status(self.parcel)
        self.assertTrue(status.is_eligible)
        self.assertEqual(status.last_prohibited_date, old)

    def test_recent_prohibited_substance_not_eligible(self):
        recent = date.today() - timedelta(days=400)
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=recent.year,
            crop_grown="Corn",
            production_method="conventional",
            substances_applied="Atrazine",
            date_last_prohibited=recent,
        )
        status = compute_transition_status(self.parcel)
        self.assertFalse(status.is_eligible)
        self.assertEqual(status.last_prohibited_date, recent)
        self.assertEqual(
            status.transition_complete_date,
            recent + relativedelta(months=TRANSITION_MONTHS),
        )
        self.assertGreater(status.days_remaining, 0)

    def test_chemical_event_classified_organic_does_not_trigger(self):
        history = self._new_history()
        ChemicalEvent.objects.create(
            history=history,
            created_by=self.user,
            description="OMRI-listed fungicide",
            date=timezone.now() - timedelta(days=100),
            chemical_subtype="copper_fungicide",
            commercial_name="Champ",
            organic_approved="omri_listed",
        )
        status = compute_transition_status(self.parcel)
        self.assertTrue(status.is_eligible)
        self.assertEqual(status.findings, [])

    def test_chemical_event_synthetic_resets_clock(self):
        history = self._new_history()
        applied = timezone.now() - timedelta(days=200)
        ChemicalEvent.objects.create(
            history=history,
            created_by=self.user,
            description="Synthetic herbicide",
            date=applied,
            chemical_subtype="synthetic_herbicide",
            commercial_name="RoundUp",
            organic_approved="not_organic",
        )
        status = compute_transition_status(self.parcel)
        self.assertFalse(status.is_eligible)
        self.assertEqual(status.last_prohibited_date, applied.date())
        self.assertEqual(len(status.findings), 1)
        self.assertEqual(status.findings[0].source, "ChemicalEvent")

    def test_uses_most_recent_prohibited_when_multiple(self):
        old = date.today() - relativedelta(months=TRANSITION_MONTHS) - timedelta(days=100)
        recent = date.today() - timedelta(days=600)
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=old.year,
            crop_grown="Wheat",
            production_method="conventional",
            substances_applied="Glyphosate",
            date_last_prohibited=old,
        )
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=recent.year,
            crop_grown="Corn",
            production_method="conventional",
            substances_applied="Atrazine",
            date_last_prohibited=recent,
        )
        status = compute_transition_status(self.parcel)
        self.assertEqual(status.last_prohibited_date, recent)
        self.assertEqual(len(status.findings), 2)
