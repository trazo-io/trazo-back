"""
Regression for F01 (2026-06): blank Observations must NOT silently 400.

CommonEvent.description is a non-blank TextField, so an event saved with the
(clearly "Optional") notes field empty used to return
{"description":["This field may not be blank."]} with no UI feedback. The
Update*EventSerializers now default a blank description from the event name/type
(ensure_event_description / the chemical inline fallback). This locks that in for
every event type so the bug can't regress.
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import Production
from history.serializers import (
    UpdateChemicalEventSerializer,
    UpdateGeneralEventSerializer,
    UpdateProductionEventSerializer,
    UpdateSoilManagementEventSerializer,
    UpdateWeatherEventSerializer,
)
from product.models import Parcel, Product
from users.models import User


class EventDescriptionFallbackTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="f01@test.com", password="x")
        self.company = Company.objects.create(name="F01 Co")
        self.establishment = Establishment.objects.create(name="F01E", company=self.company)
        self.parcel = Parcel.objects.create(name="F01P", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Citrus")
        self.history = Production.objects.create(
            name="F01 Prod",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _date(self):
        return timezone.now().isoformat()

    def test_blank_description_does_not_400(self):
        cases = [
            (
                UpdateChemicalEventSerializer,
                {
                    "type": "PE",
                    "commercial_name": "Entrust SC",
                    "volume_applied": "12",
                    "area_treated": "8",
                    "application_method": "ground_spray",
                },
            ),
            (UpdateProductionEventSerializer, {"type": "HA", "area_covered": "5", "area_unit": "acres"}),
            (UpdateWeatherEventSerializer, {"type": "FR"}),
            (UpdateSoilManagementEventSerializer, {"type": "ST", "area_covered": "5", "area_unit": "acres"}),
            (UpdateGeneralEventSerializer, {"type": "GE", "name": "Walkthrough"}),
        ]
        for cls, payload in cases:
            data = {"history": self.history.id, "date": self._date(), **payload}
            serializer = cls(data=data)
            valid = serializer.is_valid()
            self.assertNotIn(
                "description",
                serializer.errors or {},
                f"{cls.__name__}: blank description should NOT raise (F01). errors={dict(serializer.errors)}",
            )
            self.assertTrue(valid, f"{cls.__name__} unexpectedly invalid: {dict(serializer.errors)}")
            instance = serializer.save()
            instance.refresh_from_db()
            self.assertTrue(
                str(instance.description or "").strip(),
                f"{cls.__name__}: description fallback should be non-empty",
            )
