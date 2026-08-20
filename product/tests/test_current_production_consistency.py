"""The parcel page must not contradict itself about whether a season is open.

`Parcel.current_history` is a denormalised OneToOne pointer. The fact it stands for — "a
production on this parcel that has not been finished" — is derivable from `finish_date`, and
the two drift, because only the production-create and finish paths maintain the pointer.

On 2026-08-19 that drift was visible on a single screen: the parcel page rendered
"No current production yet" (from this endpoint) directly beside a Productions list showing
"1 ongoing" and the open season itself. Two demo seeders already carried a
`fix_parcel_current_history` repair helper, which is the tell that the derivation is the real
source of truth and the pointer is a cache of it.

The endpoint now derives when the pointer is missing, and heals the pointer on the way past.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, Product
from product.views import ParcelViewSet
from users.models import User, WorksIn
from django.test import TestCase


class CurrentProductionConsistencyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="curprod@test.com", password="x")
        self.company = Company.objects.create(name="Cur Farm")
        WorksIn.objects.create(user=self.user, company=self.company, role="CA")
        self.est = Establishment.objects.create(name="Blk", company=self.company)
        self.parcel = Parcel.objects.create(name="P1", establishment=self.est, area=1.0)
        crop = CropType.objects.create(
            name="Walnuts", slug="walnuts-curprod", category="tree_nut", description="n",
            typical_farm_size="10", growing_season="s", harvest_season="h",
            emissions_per_hectare=0.0, industry_average=0.0, best_practice=0.0,
            carbon_credit_potential=0.0, typical_cost_per_hectare=0.0, has_soil_contact=True,
        )
        self.product = Product.objects.create(name="Walnuts")
        self.crop = crop

    def _open_season(self):
        return History.objects.create(
            parcel=self.parcel, product=self.product, crop_type=self.crop,
            start_date=timezone.now() - timedelta(days=30),
        )

    def _call(self):
        factory = APIRequestFactory()
        request = factory.get("/")
        force_authenticate(request, user=self.user)
        view = ParcelViewSet.as_view({"get": "current_history"})
        return view(request, pk=self.parcel.pk, company_pk=self.company.pk)

    def test_open_season_is_reported_even_when_the_pointer_was_never_set(self):
        season = self._open_season()
        self.parcel.current_history = None
        self.parcel.save(update_fields=["current_history"])

        response = self._call()
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            response.data,
            "the parcel has an unfinished season, so the page must not say there is none",
        )
        self.assertEqual(response.data["id"], season.id)

    def test_the_pointer_is_healed_so_the_next_read_is_cheap(self):
        season = self._open_season()
        self.parcel.current_history = None
        self.parcel.save(update_fields=["current_history"])

        self._call()
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.current_history_id, season.id)

    def test_a_parcel_whose_seasons_are_all_finished_still_reports_none(self):
        season = self._open_season()
        season.finish_date = timezone.now()
        season.save(update_fields=["finish_date"])
        self.parcel.current_history = None
        self.parcel.save(update_fields=["current_history"])

        response = self._call()
        self.assertIsNone(
            response.data,
            "a finished season must not be resurrected as the current one",
        )
