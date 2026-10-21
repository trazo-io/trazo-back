"""The traceback through a certifier review link: the inspector's own test, done remotely.

The page traces a sale the way the operation does on screen (`history.services.traceback`), on
the LINK's farm and window only, read-only, logged on the grower's card, under the link's hourly
ceiling. Files open only when the grower included source files; otherwise the reviewer sees the
title and that a file exists.
"""

from datetime import date, datetime, timedelta

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from certifications.models import CertifierAccessLink, CertifierAccessLog
from company.models import Company, Establishment
from documents.services.filing import file_document
from history.models import History, ProductionEvent, SalesRecord
from product.models import Parcel, Product

DUMMY_CACHE = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}


@override_settings(CACHES=DUMMY_CACHE)
class CertifierReviewTracebackTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Cascade Ridge")
        self.est = Establishment.objects.create(name="Cascade Ridge Orchards", company=self.company, state="WA")
        self.season = self._season(self.est)
        pick = ProductionEvent.objects.create(
            history=self.season,
            type=ProductionEvent.HARVESTING,
            description="pick",
            date=timezone.make_aware(datetime(2026, 9, 26)),
            yield_quantity=41,
            yield_unit="bins",
        )
        ProductionEvent.objects.filter(pk=pick.pk).update(harvest_lot_code="HON-NB2-20260926")
        self.sale = self._sale(self.season, "CVFP-2026-1240", date(2026, 9, 27))
        self.sale.harvest_events.set([pick])
        self.bol = file_document(
            establishment=self.est,
            source="upload",
            folder="uploads",
            title="BR-2026-5602 bin receipt",
            filename="br.pdf",
            content=ContentFile(b"%PDF-1.4 bin receipt").read(),
        )
        self.bol.sales_record = self.sale
        self.bol.source_kind = "bill_of_lading"
        self.bol.save(update_fields=["sales_record", "source_kind"])
        other = Establishment.objects.create(name="Neighbour", company=Company.objects.create(name="N"), state="WA")
        self.foreign_sale = self._sale(self._season(other), "CVFP-2026-1240", date(2026, 9, 27))

    def _season(self, est):
        return History.objects.create(
            name="Honeycrisp 2026",
            parcel=Parcel.objects.create(name="North Bench", establishment=est, area=18.5),
            product=Product.objects.create(name="Honeycrisp Apple"),
            start_date=timezone.make_aware(datetime(2026, 3, 1)),
            finish_date=timezone.make_aware(datetime(2026, 9, 30)),
            lot_id="CRO-HON-2026",
        )

    def _sale(self, season, invoice, on):
        return SalesRecord.objects.create(
            production=season,
            buyer_name="Columbia Valley Fruit Packers",
            sale_date=on,
            quantity=41,
            quantity_unit="bins",
            invoice_number=invoice,
            organic_on_invoice=True,
            organic_label_category="organic",
        )

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
        return self.client.get(reverse("certifier_review_traceback_search", args=[link.token]), params)

    def _trace(self, link, sale_id):
        return self.client.get(reverse("certifier_review_traceback", args=[link.token, sale_id]))

    def test_search_finds_only_this_farms_sale_and_is_logged(self):
        link = self._link()
        body = self._search(link, q="cvfp-2026-1240").json()
        self.assertEqual([r["sale_id"] for r in body["results"]], [self.sale.pk])
        self.assertEqual(CertifierAccessLog.objects.filter(link=link, action="traceback").count(), 1)

    def test_the_chain_is_the_operations_own_trace_without_internal_ids(self):
        link = self._link()
        trace = self._trace(link, self.sale.pk).json()
        self.assertEqual([p["lot_code"] for p in trace["picks"]], ["HON-NB2-20260926"])
        self.assertEqual(trace["season"]["lot_id"], "CRO-HON-2026")
        for key in ("id", "public_id", "parcel_id", "establishment_id", "company_id"):
            self.assertNotIn(key, trace["season"])
        self.assertNotIn("id", trace["sale"])

    def test_a_file_opens_only_when_the_grower_included_source_files(self):
        closed = self._trace(self._link(), self.sale.pk).json()
        self.assertEqual(
            closed["sale"]["documents"],
            [{"title": "BR-2026-5602 bin receipt", "kind": "bill_of_lading", "file_id": None}],
        )
        opened = self._trace(self._link(include_source_files=True), self.sale.pk).json()
        self.assertEqual(opened["sale"]["documents"][0]["file_id"], str(self.bol.public_id))
        # A dossier profile without the document index opens no file, whatever the opt-in says.
        fsma = self._trace(self._link(include_source_files=True, certification_type="fsma204"), self.sale.pk).json()
        self.assertIsNone(fsma["sale"]["documents"][0]["file_id"])

    def test_another_farms_sale_is_the_same_404_as_an_unknown_one(self):
        link = self._link()
        foreign, unknown = self._trace(link, self.foreign_sale.pk), self._trace(link, 999999)
        self.assertEqual((foreign.status_code, unknown.status_code), (404, 404))
        self.assertEqual(foreign.content, unknown.content)

    def test_a_season_outside_the_dossiers_window_is_not_traced(self):
        # The season finished 2026-09-30; a window opening 2026-10-01 excludes it from the dossier.
        link = self._link(period_start=date(2026, 10, 1), period_end=date(2026, 12, 31))
        self.assertEqual(self._search(link, q="CVFP-2026-1240").json()["results"], [])
        self.assertEqual(self._trace(link, self.sale.pk).status_code, 404)

    def test_the_window_is_the_seasons_not_the_sale_date(self):
        """Review of back #194: a storage sale dated inside the window, from a season the dossier
        excludes, must not trace; a covered season's sale dated after the window must."""
        SalesRecord.objects.filter(pk=self.sale.pk).update(sale_date=date(2026, 11, 15))
        excluded = self._link(period_start=date(2026, 10, 1), period_end=date(2026, 12, 31))
        self.assertEqual(self._trace(excluded, self.sale.pk).status_code, 404)
        covered = self._link(period_start=date(2026, 1, 1), period_end=date(2026, 9, 30))
        self.assertEqual(self._trace(covered, self.sale.pk).status_code, 200)

    def test_no_internal_primary_key_reaches_the_reviewer(self):
        from history.models import ChemicalEvent

        ChemicalEvent.objects.create(
            history=self.season,
            description="s",
            date=timezone.make_aware(datetime(2026, 4, 2)),
            commercial_name="Lime sulfur",
            supplier_name="",
            purchase_invoice="I",
            chemical_lot_number="L",
        )
        trace = self._trace(self._link(), self.sale.pk).json()
        self.assertEqual([p["id"] for p in trace["picks"]], ["p1"])
        self.assertEqual([r["event_id"] for r in trace["inputs"]], ["i1"])
        # A gap still points at its row, by label.
        refs = {g["code"]: g["ref"] for g in trace["gaps"]}
        self.assertEqual(refs["input_without_supplier"], "i1")
        self.assertNotIn(self.sale.pk, [g["ref"] for g in trace["gaps"]])
        self.assertTrue(all(g["ref"] is None or isinstance(g["ref"], str) for g in trace["gaps"]))

    def test_a_revoked_link_or_a_buyer_token_traces_nothing(self):
        revoked = self._link(revoked_at=timezone.now())
        self.assertEqual(self._search(revoked, q="CVFP-2026-1240").status_code, 404)
        buyer = self._link(audience="buyer")
        self.assertEqual(self._trace(buyer, self.sale.pk).status_code, 404)

    @override_settings(CERTIFIER_REVIEW_LINK_HOURLY_LIMITS={"traceback": 2})
    def test_the_links_hourly_ceiling_applies(self):
        link = self._link()
        for _ in range(2):
            self.assertEqual(self._search(link, q="x").status_code, 200)
        self.assertEqual(self._search(link, q="x").status_code, 429)
