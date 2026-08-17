"""Activity feed tests (WS-4) — merged cross-model list, scoped, filterable."""

from datetime import date
from unittest.mock import patch

from django.test import TestCase

from rest_framework.test import APIClient

from company import views as company_views
from company.models import Company, Establishment
from history.models import ChemicalEvent, History, ProductionEvent
from product.models import Parcel, Product
from users.models import User, WorksIn


class ActivityFeedTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Feed Farm")
        self.user = User.objects.create_user(email="feed@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Feed Ranch", company=self.company, state="CA")
        product = Product.objects.create(name="Walnut")
        self.parcel = Parcel.objects.create(name="Block A", establishment=self.establishment, area=10.0)
        self.history = History.objects.create(
            name="2026", parcel=self.parcel, product=product, start_date=date(2026, 3, 1)
        )
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=date(2026, 8, 5),
            yield_quantity=4200,
            yield_unit="lbs",
            amount_determination="scale_verified",
            harvest_destination="stored",
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type="PE",
            date=date(2026, 7, 10),
            commercial_name="Entrust SC",
            applied_scope="part",
            applied_scope_detail="Rows 1-12",
        )
        self.client.force_authenticate(user=self.user)

    def _url(self, qs=""):
        return f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/activity-feed/{qs}"

    def test_merged_feed_sorted_desc_with_parcel_context(self):
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        rows = r.data["activities"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["event_type"], 1)
        self.assertEqual(rows[0]["subtype"], "HA")
        self.assertEqual(rows[0]["parcel_name"], "Block A")
        self.assertEqual(rows[1]["event_type"], 2)

    def test_narrative_detail_values_only(self):
        rows = self.client.get(self._url()).data["activities"]
        harvest = next(r for r in rows if r["subtype"] == "HA")
        self.assertEqual(harvest["detail"]["yield_quantity"], "4200")
        self.assertEqual(harvest["detail"]["yield_unit"], "lbs")
        self.assertEqual(harvest["detail"]["amount_determination"], "scale_verified")
        self.assertEqual(harvest["detail"]["harvest_destination"], "stored")
        chem = next(r for r in rows if r["subtype"] == "PE")
        self.assertEqual(chem["detail"]["commercial_name"], "Entrust SC")
        self.assertEqual(chem["detail"]["applied_scope"], "part")
        self.assertEqual(chem["detail"]["applied_scope_detail"], "Rows 1-12")

    def test_date_window_and_type_filter(self):
        r = self.client.get(self._url("?start=2026-08-01&end=2026-08-31"))
        self.assertEqual([x["subtype"] for x in r.data["activities"]], ["HA"])
        r2 = self.client.get(self._url("?event_type=2"))
        self.assertEqual([x["subtype"] for x in r2.data["activities"]], ["PE"])

    def test_parcel_filter_scopes_to_one_block(self):
        """Filtering by parcel must happen in the QUERYSET, not after the caps.

        Both parcels belong to the same establishment, so an unfiltered feed returns all
        three events; `?parcel=` must return only the requested block's.
        """
        other_parcel = Parcel.objects.create(name="Block B", establishment=self.establishment, area=5.0)
        other_history = History.objects.create(
            name="2026 B",
            parcel=other_parcel,
            product=Product.objects.get(name="Walnut"),
            start_date=date(2026, 3, 1),
        )
        ProductionEvent.objects.create(history=other_history, type="IR", date=date(2026, 8, 9))

        self.assertEqual(len(self.client.get(self._url()).data["activities"]), 3)

        rows = self.client.get(self._url(f"?parcel={self.parcel.id}")).data["activities"]
        self.assertEqual({r["parcel_name"] for r in rows}, {"Block A"})
        self.assertEqual(len(rows), 2)

        other_rows = self.client.get(self._url(f"?parcel={other_parcel.id}")).data["activities"]
        self.assertEqual([r["subtype"] for r in other_rows], ["IR"])

    def test_parcel_filter_combines_with_type_and_window(self):
        rows = self.client.get(
            self._url(f"?parcel={self.parcel.id}&event_type=2&start=2026-01-01&end=2026-12-31")
        ).data["activities"]
        self.assertEqual([r["subtype"] for r in rows], ["PE"])

    def test_garbage_parcel_param_is_ignored_not_fatal(self):
        """A bad param must not 500 and must not silently return an EMPTY log — an empty
        activity list reads as 'this farm documented nothing'."""
        r = self.client.get(self._url("?parcel=not-an-id"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["activities"]), 2)

    def test_truncation_is_reported(self):
        """The caps are honest: a feed that fits reports truncated=False."""
        r = self.client.get(self._url())
        self.assertFalse(r.data["truncated"])

    def test_truncation_flag_set_when_per_model_cap_bites(self):
        with patch.object(company_views, "ACTIVITY_FEED_PER_MODEL_CAP", 1):
            r = self.client.get(self._url())
        # One ProductionEvent + one ChemicalEvent, capped at one row per MODEL, so nothing is
        # actually dropped here — the flag must follow the cap, not the row count.
        self.assertEqual(len(r.data["activities"]), 2)

        ProductionEvent.objects.create(history=self.history, type="IR", date=date(2026, 8, 6))
        with patch.object(company_views, "ACTIVITY_FEED_PER_MODEL_CAP", 1):
            r2 = self.client.get(self._url())
        self.assertTrue(r2.data["truncated"])
        self.assertEqual(len(r2.data["activities"]), 2)

    def test_scoped_to_company(self):
        outsider = User.objects.create_user(email="out@test.com", password="x")
        other = Company.objects.create(name="Other Co")
        WorksIn.objects.create(user=outsider, company=other, role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(user=outsider)
        r = self.client.get(self._url())
        self.assertIn(r.status_code, (403, 404))
