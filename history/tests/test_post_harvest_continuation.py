"""A finished production accepts records dated AFTER its finish date, and refuses records
dated inside the sealed season.

WHY THIS EXISTS
---------------
Until 2026-08-23 `EventViewSet.perform_create` refused every new record on a finished
production and told the farmer to log it "against the parcel's current or next production
instead". Read against what a farm does after harvest that was wrong twice over:

  * a storage crop ships for months — "load 3 of 3 to the distributor", forty days after the
    onions were lifted, is part of THAT lot's harvest → storage → transport → sale trail, the
    one § 205.103(b)(2) and the CCOF audit follow lot by lot. Filing it on next spring's carrots
    breaks the trail where an inspector follows it;
  * winter cover drilled after the carrots, the season's irrigation summary, post-harvest mowing
    and trap counts past the last pick are that field's year, and on vegetable ground there is
    no "next production" to receive them until the following spring.

Forty-nine records in one pilot's own history were dated after their season closed — every one
a record the API had come to refuse.

The integrity the lock protects is against BACKDATING into a harvest window a certifier has
already seen as closed. A record dated after the finish does not rewrite that window; it extends
the lot's trail forward under its own later date. So the line is the finish DATE: after it,
accepted; on or before it, refused with the correction path named. The lot header stays frozen
(test_closed_record_integrity) and existing records stay behind 423 + /amend
(test_event_amendments) — neither of those moves here.
"""

from datetime import timedelta

from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import Production, ProductionEvent, SoilManagementEvent
from product.models import Parcel, Product
from users.models import User, WorksIn


class PostHarvestContinuationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ph@t.test", password="x")
        company = Company.objects.create(name="PH Co")
        WorksIn.objects.create(user=self.user, company=company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="PH Farm", company=company)
        self.parcel = Parcel.objects.create(name="Bottom Ground B", establishment=self.est, area=6.6)
        self.crop = CropType.objects.create(
            name="Onions",
            slug="onions-ph",
            category="vegetable",
            description="d",
            typical_farm_size="1",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        self.product = Product.objects.create(name="Onions")
        # Lifted and closed 40 days ago; the lot is still shipping from the shed.
        self.finish = timezone.now() - timedelta(days=40)
        self.season = Production.objects.create(
            parcel=self.parcel,
            product=self.product,
            crop_type=self.crop,
            name="Onions 2026",
            start_date=self.finish - timedelta(days=180),
            finish_date=self.finish,
            lot_id="CBF-26-BGB",
            production_amount=340800,
            published=True,
        )
        # Finishing NULLS `parcel.current_history` (Parcel.finish_current_history). The record
        # therefore has to reach the season by its explicit `history` id — which is what the
        # season's own page sends — and the explicit-id branch must not hide behind a
        # `current_history is not None` test. Leaving the pointer null here is the realistic
        # state; setting it would have let this suite pass against a guard nobody could reach.
        self.assertIsNone(self.parcel.current_history)
        self.client.force_authenticate(self.user)

    def _post(self, event_type, **fields):
        payload = {"event_type": event_type, "history": self.season.id, "parcels": [self.parcel.id]}
        payload.update(fields)
        return self.client.post("/api/events/", payload, format="json")

    # -- accepted: dated after the finish ---------------------------------------------------
    def test_a_storage_shipment_after_the_close_stays_on_its_own_lot(self):
        res = self._post(
            1,
            type="TP",
            date=(self.finish + timedelta(days=38)).isoformat(),
            name="Load 3 of 3 to Cascade Organic Distributors",
            description="Third load of stored onions, 78 mi.",
            transportation_distance=78,
            transportation_unit="miles",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(ProductionEvent.objects.get(pk=res.data["id"]).history_id, self.season.id)

    def test_winter_cover_after_the_close_is_that_fields_year(self):
        res = self._post(
            5,
            type="CC",
            date=(self.finish + timedelta(days=20)).isoformat(),
            name="Winter cover seeded",
            description="Cereal rye / hairy vetch drilled.",
            amendment_type="cover_crop",
            area_covered=16.4,
            area_unit="acres",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(SoilManagementEvent.objects.get(pk=res.data["id"]).history_id, self.season.id)

    def test_published_does_not_add_a_second_lock(self):
        """`published` implies finished; a post-harvest record on a published lot is fine."""
        self.assertTrue(self.season.published)
        res = self._post(
            1,
            type="MO",
            date=(self.finish + timedelta(days=5)).isoformat(),
            name="Alley mowing",
            description="After the last pick.",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)

    # -- refused: dated inside the sealed season ---------------------------------------------
    def test_a_record_dated_inside_the_season_is_refused_and_names_the_correction_path(self):
        res = self._post(
            2,
            type="PE",
            date=(self.finish - timedelta(days=30)).isoformat(),
            commercial_name="Entrust SC",
            description="A spray nobody logged at the time.",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.data)
        detail = str(res.data.get("detail", res.data))
        self.assertIn(self.finish.date().isoformat(), detail)
        self.assertIn("correction", detail)
        self.assertIn("after the finish date", detail)

    def test_a_record_dated_on_the_finish_day_is_inside_the_season(self):
        res = self._post(1, type="MO", date=self.finish.isoformat(), name="Mowing", description="x")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.data)

    def test_an_open_season_is_not_touched_by_this_rule(self):
        open_season = Production.objects.create(
            parcel=self.parcel,
            product=self.product,
            crop_type=self.crop,
            name="Onions 2027",
            start_date=timezone.now() - timedelta(days=10),
        )
        res = self.client.post(
            "/api/events/",
            {
                "event_type": 1,
                "history": open_season.id,
                "parcels": [self.parcel.id],
                "type": "MO",
                "date": (timezone.now() - timedelta(days=400)).isoformat(),
                "name": "Old mowing",
                "description": "Dated long before the season — an open season does not seal anything.",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
