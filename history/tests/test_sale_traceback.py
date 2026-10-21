"""
Traceback from one sale: the inspector's § 205.103(b)(2) exercise, run by the operation first.

The inspector picks a lot off a sales document and walks it back: sale -> harvest pick -> season ->
inputs. These tests pin the three things that would make the drill lie: picking one of several
matches for the operator, answering for another company's records, and naming an unclassified
input as anything but unclassified.
"""

from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import ChemicalEvent, History, PestManagementEvent, ProductionEvent, SalesRecord
from history.services.traceback import trace_sale
from product.models import Parcel, Product
from users.models import User, WorksIn


class _TraceBase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Calapooia Bend Farm LLC")
        self.user = User.objects.create_user(email="laurel@test.com", password="x", first_name="Laurel")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Home Block", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="Upper Terrace", establishment=self.est, area=4.0)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _season(self, parcel=None, lot_id="CBF-26-UT-01", name="2026 blueberries"):
        return History.objects.create(
            name=name,
            parcel=parcel or self.parcel,
            product=Product.objects.create(name="Blueberries"),
            start_date=timezone.make_aware(datetime(2026, 3, 1)),
            finish_date=timezone.make_aware(datetime(2026, 8, 20)),
            lot_id=lot_id,
        )

    def _pick(self, season, lot_code="BLU-UT-20260801", block="UT", day=1, qty=13400):
        ev = ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.HARVESTING,
            description="pick",
            date=timezone.make_aware(datetime(2026, 8, day)),
            block_id=block,
            yield_quantity=qty,
            yield_unit="lb",
        )
        # `save()` fills a blank code from crop + block; set the stored value directly.
        ProductionEvent.objects.filter(pk=ev.pk).update(harvest_lot_code=lot_code)
        ev.refresh_from_db()
        return ev

    def _sale(self, season, picks=(), **kw):
        defaults = dict(
            production=season,
            sale_date=timezone.now().date() - timedelta(days=30),
            buyer_name="Organically Grown Company",
            quantity=13400,
            quantity_unit="lb",
            invoice_number="INV-2026-0912",
            bill_of_lading="BOL-77120",
            organic_on_invoice=True,
            organic_label_category="organic",
        )
        defaults.update(kw)
        sale = SalesRecord.objects.create(**defaults)
        sale.harvest_events.set(picks)
        return sale

    def _search(self, **params):
        return self.client.get(reverse("sales-records-traceback-search"), params)

    def _trace(self, pk, **params):
        return self.client.get(reverse("sales-records-traceback", args=[pk]), params)


class SearchTests(_TraceBase):
    def test_each_document_identifier_finds_the_sale(self):
        season = self._season()
        pick = self._pick(season)
        sale = self._sale(season, picks=[pick])
        for q, label in (
            ("INV-2026-0912", "invoice"),
            ("BOL-77120", "bill_of_lading"),
            ("BLU-UT-20260801", "pick_lot_code"),
            ("CBF-26-UT-01", "season_lot_id"),
        ):
            with self.subTest(q=q):
                rows = self._search(q=f"  {q.lower()} ").json()["results"]
                self.assertEqual([(r["sale_id"], r["matched_on"]) for r in rows], [(sale.pk, label)])

    def test_a_code_shared_by_two_seasons_returns_both_never_one(self):
        s1, s2 = self._season(name="2025"), self._season(name="2026", lot_id="CBF-26-UT-02")
        a = self._sale(s1, picks=[self._pick(s1, lot_code="SHARED-1")], invoice_number="A")
        b = self._sale(s2, picks=[self._pick(s2, lot_code="SHARED-1")], invoice_number="B")
        rows = self._search(q="SHARED-1").json()["results"]
        self.assertEqual({r["sale_id"] for r in rows}, {a.pk, b.pk})

    def test_another_companys_invoice_matches_nothing(self):
        other = Company.objects.create(name="Neighbour")
        est = Establishment.objects.create(name="N", company=other, state="OR")
        season = self._season(parcel=Parcel.objects.create(name="N1", establishment=est, area=1.0))
        self._sale(season, invoice_number="FOREIGN-1")
        self.assertEqual(self._search(q="FOREIGN-1").json()["results"], [])
        self.assertEqual(self._search(q="NO-SUCH-INVOICE").json()["results"], [])

    def test_a_voided_sale_is_neither_found_nor_drawn_at_random(self):
        sale = self._sale(self._season())
        SalesRecord.objects.filter(pk=sale.pk).update(voided_at=timezone.now(), void_reason="duplicate")
        self.assertEqual(self._search(q="INV-2026-0912").json()["results"], [])
        self.assertEqual(self._search(random="1").json()["results"], [])

    def test_random_draws_a_live_sale(self):
        sale = self._sale(self._season())
        rows = self._search(random="1").json()["results"]
        self.assertEqual([(r["sale_id"], r["matched_on"]) for r in rows], [(sale.pk, "random")])

    def test_no_query_is_a_400(self):
        self.assertEqual(self._search().status_code, 400)

    def test_an_unlinked_sale_is_found_by_its_seasons_pick_code(self):
        """The commonest gap must not read as "no match": the pick exists, the sale just names none."""
        season = self._season()
        self._pick(season, lot_code="BLU-UT-20260801")
        sale = self._sale(season)  # names no pick
        rows = self._search(q="BLU-UT-20260801").json()["results"]
        self.assertEqual([(r["sale_id"], r["matched_on"]) for r in rows], [(sale.pk, "pick_lot_code_season")])

    def test_a_sale_that_names_another_pick_is_not_offered_by_the_season_fallback(self):
        """Found by the browser run: S1 names pick R1, so pick R2's code must find only the unlinked S2."""
        season = self._season()
        r1 = self._pick(season, lot_code="HAS-R1", block="R1")
        self._pick(season, lot_code="HAS-R2", block="R2", day=5)
        self._sale(season, picks=[r1], invoice_number="S1")
        s2 = self._sale(season, invoice_number="S2")
        rows = self._search(q="HAS-R2").json()["results"]
        self.assertEqual([(r["sale_id"], r["matched_on"]) for r in rows], [(s2.pk, "pick_lot_code_season")])

    def test_matches_past_the_cap_are_flagged_not_dropped_silently(self):
        season = self._season()
        for i in range(21):
            self._sale(season, invoice_number="SAME")
        body = self._search(q="SAME").json()
        self.assertEqual(len(body["results"]), 20)
        self.assertTrue(body["truncated"])

    def test_another_companys_establishment_id_returns_nothing(self):
        other = Company.objects.create(name="Neighbour")
        est = Establishment.objects.create(name="N", company=other, state="OR")
        self._sale(self._season(parcel=Parcel.objects.create(name="N1", establishment=est, area=1.0)))
        self._sale(self._season())
        body = self._search(q="INV-2026-0912", establishment_id=str(est.pk)).json()
        self.assertEqual(body, {"results": [], "truncated": False})

    def test_a_viewer_role_traces_nothing(self):
        sale = self._sale(self._season())
        WorksIn.objects.filter(user=self.user).update(role=WorksIn.VIEWER)
        self.assertEqual(self._search(q="INV-2026-0912").json()["results"], [])
        self.assertEqual(self._trace(sale.pk).status_code, 404)


class TraceAccessTests(_TraceBase):
    def test_a_foreign_sale_is_the_same_404_as_a_missing_one(self):
        other = Company.objects.create(name="Neighbour")
        est = Establishment.objects.create(name="N", company=other, state="OR")
        foreign = self._sale(self._season(parcel=Parcel.objects.create(name="N1", establishment=est, area=1.0)))
        foreign_resp, missing_resp = self._trace(foreign.pk), self._trace(foreign.pk + 999)
        self.assertEqual(foreign_resp.status_code, 404)
        self.assertEqual(foreign_resp.json(), missing_resp.json())

    def test_a_sale_on_the_companys_other_farm_is_not_traced_under_this_one(self):
        """The page's URL names a farm; a sale from the company's other farm must not render under
        its breadcrumb. Same 404 body as a sale that does not exist."""
        other_farm = Establishment.objects.create(name="Lower Ranch", company=self.company, state="OR")
        sale = self._sale(self._season(parcel=Parcel.objects.create(name="L1", establishment=other_farm, area=1.0)))
        # Read something first: the sale IS traceable under its own farm.
        self.assertEqual(self._trace(sale.pk, establishment_id=other_farm.pk).status_code, 200)
        wrong, missing = self._trace(sale.pk, establishment_id=self.est.pk), self._trace(sale.pk + 999)
        self.assertEqual(wrong.status_code, 404)
        self.assertEqual(wrong.json(), missing.json())
        self.assertEqual(self._trace(sale.pk, establishment_id="x").status_code, 404)

    def test_a_voided_sale_cannot_be_traced(self):
        sale = self._sale(self._season())
        SalesRecord.objects.filter(pk=sale.pk).update(voided_at=timezone.now(), void_reason="duplicate")
        self.assertEqual(self._trace(sale.pk).status_code, 404)


class ChainTests(_TraceBase):
    def _codes(self, trace, hop=None):
        return {g["code"] for g in trace["gaps"] if hop is None or g["hop"] == hop}

    def test_a_linked_sale_walks_to_its_pick_season_and_balance(self):
        season = self._season()
        pick = self._pick(season)
        sale = self._sale(season, picks=[pick])
        trace = self._trace(sale.pk).json()
        self.assertTrue(trace["picks_linked"])
        self.assertEqual([p["lot_code"] for p in trace["picks"]], ["BLU-UT-20260801"])
        self.assertEqual(trace["season"]["lot_id"], "CBF-26-UT-01")
        self.assertEqual(trace["balance"]["harvested"], "13,400 lb")
        self.assertEqual(trace["balance"]["difference"], "0 lb")
        self.assertEqual(trace["gaps"], [])

    def test_an_unlinked_sale_is_the_gap_and_still_lists_the_seasons_picks(self):
        season = self._season()
        self._pick(season)
        trace = trace_sale(self._sale(season)).as_dict()
        self.assertFalse(trace["picks_linked"])
        self.assertEqual(len(trace["picks"]), 1)
        self.assertIn("sale_not_linked_to_pick", self._codes(trace, "picks"))

    def test_missing_identifiers_are_named_at_their_hop(self):
        season = self._season(lot_id="")
        pick = self._pick(season, lot_code="")
        trace = trace_sale(self._sale(season, picks=[pick], invoice_number="", bill_of_lading="")).as_dict()
        self.assertIn("no_sale_document", self._codes(trace, "sale"))
        self.assertIn("pick_without_lot_code", self._codes(trace, "picks"))
        self.assertIn("season_without_lot_id", self._codes(trace, "season"))

    def test_an_input_missing_its_purchase_identifiers_is_named_per_field(self):
        season = self._season()
        sale = self._sale(season, picks=[self._pick(season)])
        spray = ChemicalEvent.objects.create(
            history=season, description="copper", date=timezone.make_aware(datetime(2026, 5, 2)), commercial_name="X"
        )
        trace = trace_sale(sale).as_dict()
        [row] = trace["inputs"]
        self.assertEqual(row["event_id"], spray.pk)
        gaps = {(g["code"], g["ref"], g["kind"]) for g in trace["gaps"] if g["hop"] == "inputs"}
        self.assertEqual(
            gaps,
            {(f"input_without_{f}", spray.pk, "chemical") for f in ("supplier", "invoice", "lot")},
        )

    def test_an_unclassified_input_is_not_classified_never_prohibited(self):
        season = self._season()
        sale = self._sale(season)
        ChemicalEvent.objects.create(history=season, description="x", date=timezone.now(), commercial_name="X")
        ProductionEvent.objects.create(
            history=season, type=ProductionEvent.PLANTING, description="p", date=timezone.now(), seed_lot_number="L-1"
        )
        PestManagementEvent.objects.create(
            history=season, type=PestManagementEvent.BENEFICIAL_RELEASE, description="b", date=timezone.now()
        )
        inputs = trace_sale(sale).as_dict()["inputs"]
        # Read something first: a negative assertion over an empty list proves nothing.
        self.assertEqual({r["kind"] for r in inputs}, {"chemical", "seed", "beneficial"})
        self.assertEqual({r["listing"] for r in inputs}, {"not_classified"})

    def test_a_planting_with_no_purchase_record_is_not_an_input_gap(self):
        """Farm-saved seed has no supplier to name; three unclosable gaps would be noise."""
        season = self._season()
        sale = self._sale(season)
        ProductionEvent.objects.create(
            history=season, type=ProductionEvent.PLANTING, description="p", date=timezone.now()
        )
        stock = ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.TRANSPLANTING,
            description="t",
            date=timezone.now(),
            seed_supplier_name="Capay Valley Nursery",
        )
        trace = trace_sale(sale).as_dict()
        self.assertEqual([(r["kind"], r["event_id"]) for r in trace["inputs"]], [("seed", stock.pk)])
        self.assertEqual(
            {g["code"] for g in trace["gaps"] if g["hop"] == "inputs"}, {"input_without_invoice", "input_without_lot"}
        )

    def test_trace_queries_do_not_grow_with_the_spray_count(self):
        from certifications.models import OMRIProduct

        season = self._season()
        sale = self._sale(season, picks=[self._pick(season)])

        def spray(n, start):
            # A real OMRI match on each: a null FK costs no query, so only a set one can expose N+1.
            for i in range(start, start + n):
                ChemicalEvent.objects.create(
                    history=season,
                    description="s",
                    date=timezone.now(),
                    commercial_name=f"S{i}",
                    omri_product=OMRIProduct.objects.create(omri_id=f"tb-{i}", product_name=f"S{i}"),
                )

        spray(2, 0)
        baseline = self._count_queries(sale)
        spray(5, 2)
        with self.assertNumQueries(baseline):
            trace_sale(sale)

    def _count_queries(self, sale):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            trace_sale(sale)
        return len(ctx.captured_queries)

    def test_an_input_on_another_block_is_marked_not_hidden(self):
        season = self._season()
        sale = self._sale(season, picks=[self._pick(season, block="UT")])
        for block in ("UT", "LOWER"):
            ChemicalEvent.objects.create(
                history=season, description="s", date=timezone.now(), commercial_name=block, block_id=block
            )
        rows = {r["block"]: r["other_block"] for r in trace_sale(sale).as_dict()["inputs"]}
        self.assertEqual(rows, {"UT": False, "LOWER": True})

    def test_seed_status_is_never_read_as_allowed_unless_certified_organic(self):
        season = self._season()
        sale = self._sale(season)
        for status in ("certified_organic", "transitional", "non_organic_untreated", "non_organic_treated"):
            ProductionEvent.objects.create(
                history=season,
                type=ProductionEvent.PLANTING,
                description=status,
                date=timezone.now(),
                seed_certification_status=status,
                seed_lot_number=status,
            )
        listing = {r["lot"]: r["listing"] for r in trace_sale(sale).as_dict()["inputs"]}
        self.assertEqual(
            listing,
            {
                "certified_organic": "recorded_by_farm",
                "transitional": "recorded_other",
                "non_organic_untreated": "recorded_other",
                "non_organic_treated": "recorded_other",
            },
        )

    def test_a_sale_not_invoiced_as_organic_is_stated_beside_the_balance(self):
        season = self._season()
        pick = self._pick(season)
        sale = self._sale(season, picks=[pick], quantity=13000)
        self._sale(season, invoice_number="BUF", quantity=400, organic_on_invoice=False, organic_label_category="")
        balance = trace_sale(sale).as_dict()["balance"]
        self.assertEqual(
            (balance["sold"], balance["sold_not_organic"], balance["sold_not_organic_count"]),
            ("13,000 lb", "400 lb", 1),
        )

    def test_the_balance_never_counts_a_voided_sale(self):
        season = self._season()
        pick = self._pick(season)
        sale = self._sale(season, picks=[pick])
        self._sale(season, invoice_number="DUP", voided_at=timezone.now(), void_reason="duplicate")
        self.assertEqual(trace_sale(sale).as_dict()["balance"]["sold"], "13,400 lb")
