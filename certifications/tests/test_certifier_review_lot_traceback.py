"""The lot trace through a certifier review link: product in storage, traced remotely.

Same rules as the sale trace on the link (`test_certifier_review_traceback`): the LINK's farm and
season window only, read-only, internal ids stripped, files only when the grower shared them,
logged on the grower's card, under the link's hourly ceiling.
"""

from datetime import date, datetime, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from certifications.models import CertifierAccessLink, CertifierAccessLog
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production, ProductionEvent, SalesRecord
from product.models import Parcel, Product

DUMMY_CACHE = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}


@override_settings(CACHES=DUMMY_CACHE)
class CertifierReviewLotTracebackTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Cascade Ridge")
        self.est = Establishment.objects.create(name="Cascade Ridge Orchards", company=self.company, state="WA")
        self.season = self._season(self.est)
        self.pick = self._pick(self.season, "HON-NB2-20260926", "CA Room 4")
        self.sale = SalesRecord.objects.create(
            production=self.season,
            buyer_name="Columbia Valley Fruit Packers",
            sale_date=date(2026, 9, 27),
            quantity=20,
            quantity_unit="bins",
            invoice_number="CVFP-2026-1240",
            organic_on_invoice=True,
            organic_label_category="organic",
        )
        self.sale.harvest_events.set([self.pick])
        other = Establishment.objects.create(name="Neighbour", company=Company.objects.create(name="N"), state="WA")
        self.foreign_pick = self._pick(self._season(other), "HON-NB2-20260926", "Cooler 1")

    def _season(self, est):
        return Production.objects.create(
            name="Honeycrisp 2026",
            parcel=Parcel.objects.create(name="North Bench", establishment=est, area=18.5),
            product=Product.objects.create(name="Honeycrisp Apple"),
            start_date=timezone.make_aware(datetime(2026, 3, 1)),
            finish_date=timezone.make_aware(datetime(2026, 9, 30)),
            lot_id="CRO-HON-2026",
        )

    def _pick(self, season, code, storage):
        pick = ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.HARVESTING,
            description="pick",
            date=timezone.make_aware(datetime(2026, 9, 26)),
            yield_quantity=41,
            yield_unit="bins",
        )
        ProductionEvent.objects.filter(pk=pick.pk).update(harvest_lot_code=code, storage_location=storage)
        pick.refresh_from_db()
        return pick

    def _link(self, **kw):
        defaults = dict(
            establishment=self.est,
            token=CertifierAccessLink.generate_token(),
            label="WSDA 2026",
            audience="certifier",
            certification_type="organic",
            expires_at=timezone.now() + timedelta(days=30),
        )
        defaults.update(kw)
        return CertifierAccessLink.objects.create(**defaults)

    def _search(self, link, **params):
        return self.client.get(reverse("certifier_review_lot_traceback_search", args=[link.token]), params)

    def _trace(self, link, pick_id):
        return self.client.get(reverse("certifier_review_lot_traceback", args=[link.token, pick_id]))

    def test_search_finds_only_this_farms_pick_and_is_logged(self):
        link = self._link()
        body = self._search(link, q="hon-nb2-20260926").json()
        self.assertEqual([r["pick_id"] for r in body["results"]], [self.pick.pk])
        self.assertEqual(body["results"][0]["storage"], "CA Room 4")
        self.assertEqual(CertifierAccessLog.objects.filter(link=link, action="traceback").count(), 1)

    def test_the_lots_route_is_not_read_as_a_sale_id(self):
        self.assertEqual(self._search(self._link()).status_code, 400)  # q is required, not "no such sale"

    def test_the_chain_reads_both_directions_without_internal_ids(self):
        ChemicalEvent.objects.create(
            history=self.season,
            description="s",
            date=timezone.make_aware(datetime(2026, 4, 2)),
            commercial_name="Lime sulfur",
            supplier_name="",
            purchase_invoice="I",
            chemical_lot_number="L",
        )
        trace = self._trace(self._link(), self.pick.pk).json()
        self.assertEqual(trace["anchor"], "pick")
        self.assertEqual([p["id"] for p in trace["picks"]], ["p1"])
        self.assertEqual([r["event_id"] for r in trace["inputs"]], ["i1"])
        self.assertEqual({g["code"]: g["ref"] for g in trace["gaps"]}["input_without_supplier"], "i1")
        for key in ("id", "public_id", "parcel_id", "establishment_id", "company_id"):
            self.assertNotIn(key, trace["season"])
        # Forward: the sale that names the pick, openable through the link's own sale trace.
        self.assertEqual([s["invoice"] for s in trace["sales"]], ["CVFP-2026-1240"])
        sale_trace = self.client.get(
            reverse("certifier_review_traceback", args=[self._link().token, trace["sales"][0]["sale_id"]])
        )
        self.assertEqual(sale_trace.status_code, 200)
        [room] = trace["on_hand"]["locations"]
        self.assertEqual((room["location"], room["difference"]), ("CA Room 4", "21 bins"))

    def test_another_farms_pick_is_the_same_404_as_an_unknown_one(self):
        link = self._link()
        foreign, unknown = self._trace(link, self.foreign_pick.pk), self._trace(link, 999999)
        self.assertEqual((foreign.status_code, unknown.status_code), (404, 404))
        self.assertEqual(foreign.content, unknown.content)

    def test_a_season_outside_the_dossiers_window_is_not_traced(self):
        link = self._link(period_start=date(2026, 10, 1), period_end=date(2026, 12, 31))
        self.assertEqual(self._search(link, q="HON-NB2-20260926").json()["results"], [])
        self.assertEqual(self._trace(link, self.pick.pk).status_code, 404)

    def test_a_revoked_link_or_a_buyer_token_traces_nothing(self):
        self.assertEqual(self._search(self._link(revoked_at=timezone.now()), q="x").status_code, 404)
        self.assertEqual(self._trace(self._link(audience="buyer"), self.pick.pk).status_code, 404)

    @override_settings(CERTIFIER_REVIEW_LINK_HOURLY_LIMITS={"traceback": 2})
    def test_the_links_hourly_ceiling_applies(self):
        link = self._link()
        for _ in range(2):
            self.assertEqual(self._search(link, q="x").status_code, 200)
        self.assertEqual(self._trace(link, self.pick.pk).status_code, 429)
