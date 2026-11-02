"""
Traceback from a harvest lot: the inspector points at product in storage, not at a sale.

Same chain as the sale trace (`history.services.traceback`), anchored on one harvest pick: back to
its season and inputs, forward to the sales that name it. These tests pin what would make that
lie: answering for another farm's pick or receipt, inventing a sale for a pick nobody sold,
choosing one of two sales, and counting a voided sale.
"""

from datetime import datetime

from django.urls import reverse
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, ProductionEvent, SalesRecord
from history.services.traceback import trace_pick
from history.tests.test_sale_traceback import _TraceBase
from product.models import Parcel
from users.models import WorksIn


class _LotBase(_TraceBase):
    def _lot_search(self, **params):
        return self.client.get(reverse("sales-records-lot-traceback-search"), params)

    def _lot_trace(self, pick_id, **params):
        return self.client.get(reverse("sales-records-lot-traceback", args=[pick_id]), params)

    def _foreign_season(self, lot_id="FOREIGN-LOT"):
        other = Company.objects.create(name="Neighbour")
        est = Establishment.objects.create(name="N", company=other, state="OR")
        return self._season(parcel=Parcel.objects.create(name="N1", establishment=est, area=1.0), lot_id=lot_id)


class LotSearchTests(_LotBase):
    def test_each_identifier_on_stored_product_finds_the_pick(self):
        season = self._season()
        pick = self._pick(season)
        ProductionEvent.objects.filter(pk=pick.pk).update(handler_document_reference="BR-5602")
        for q, label in (("BLU-UT-20260801", "pick_lot_code"), ("BR-5602", "handler_document")):
            with self.subTest(q=q):
                rows = self._lot_search(q=f"  {q.lower()} ").json()["results"]
                self.assertEqual([(r["pick_id"], r["matched_on"]) for r in rows], [(pick.pk, label)])

    def test_the_seasons_lot_id_lists_every_pick_never_one(self):
        season = self._season()
        a, b = self._pick(season, lot_code="A", day=1), self._pick(season, lot_code="B", day=5)
        rows = self._lot_search(q="CBF-26-UT-01").json()["results"]
        self.assertEqual([r["pick_id"] for r in rows], [b.pk, a.pk])
        self.assertEqual({r["matched_on"] for r in rows}, {"season_lot_id"})

    def test_a_code_shared_by_two_seasons_returns_both(self):
        s1, s2 = self._season(name="2025"), self._season(name="2026", lot_id="CBF-26-UT-02")
        a, b = self._pick(s1, lot_code="SHARED-1"), self._pick(s2, lot_code="SHARED-1")
        rows = self._lot_search(q="SHARED-1").json()["results"]
        self.assertEqual({r["pick_id"] for r in rows}, {a.pk, b.pk})

    def test_another_companys_lot_code_matches_nothing(self):
        self._pick(self._foreign_season(), lot_code="FOREIGN-PICK")
        self.assertEqual(self._lot_search(q="FOREIGN-PICK").json(), {"results": [], "truncated": False})
        self.assertEqual(self._lot_search(q="FOREIGN-LOT").json()["results"], [])

    def test_the_companys_other_farm_is_left_out_when_the_page_names_a_farm(self):
        sister = Establishment.objects.create(name="Lower Ranch", company=self.company, state="OR")
        self._pick(self._season(parcel=Parcel.objects.create(name="L1", establishment=sister, area=1.0)), "SAME")
        here = self._pick(self._season(), "SAME")
        rows = self._lot_search(q="SAME", establishment_id=str(self.est.pk)).json()["results"]
        self.assertEqual([r["pick_id"] for r in rows], [here.pk])

    def test_a_planting_is_not_a_lot(self):
        season = self._season()
        planting = ProductionEvent.objects.create(
            history=season, type=ProductionEvent.PLANTING, description="p", date=timezone.now()
        )
        ProductionEvent.objects.filter(pk=planting.pk).update(harvest_lot_code="NOT-A-PICK")
        self.assertEqual(self._lot_search(q="NOT-A-PICK").json()["results"], [])
        self.assertEqual(self._lot_trace(planting.pk).status_code, 404)

    def test_bad_requests_and_a_viewer_role(self):
        self.assertEqual(self._lot_search().status_code, 400)
        self.assertEqual(self._lot_search(q="x", establishment_id="abc").status_code, 400)
        pick = self._pick(self._season())
        WorksIn.objects.filter(user=self.user).update(role=WorksIn.VIEWER)
        self.assertEqual(self._lot_search(q="BLU-UT-20260801").json()["results"], [])
        self.assertEqual(self._lot_trace(pick.pk).status_code, 404)


class LotTraceAccessTests(_LotBase):
    def test_a_foreign_pick_is_the_same_404_as_a_missing_one(self):
        foreign = self._pick(self._foreign_season())
        foreign_resp, missing_resp = self._lot_trace(foreign.pk), self._lot_trace(foreign.pk + 999)
        self.assertEqual(foreign_resp.status_code, 404)
        self.assertEqual(foreign_resp.json(), missing_resp.json())

    def test_a_pick_on_the_companys_other_farm_is_not_traced_under_this_one(self):
        sister = Establishment.objects.create(name="Lower Ranch", company=self.company, state="OR")
        pick = self._pick(self._season(parcel=Parcel.objects.create(name="L1", establishment=sister, area=1.0)))
        self.assertEqual(self._lot_trace(pick.pk, establishment_id=str(self.est.pk)).status_code, 404)
        self.assertEqual(self._lot_trace(pick.pk, establishment_id=str(sister.pk)).status_code, 200)
        self.assertEqual(self._lot_trace(pick.pk, establishment_id="x").status_code, 404)


class LotChainTests(_LotBase):
    def test_a_pick_walks_back_to_its_season_and_inputs_with_the_same_gap_codes(self):
        season = self._season(lot_id="")
        pick = self._pick(season, lot_code="")
        spray = ChemicalEvent.objects.create(
            history=season,
            description="s",
            date=timezone.make_aware(datetime(2026, 7, 20)),
            commercial_name="Mystery oil",
            phi_days=7,
        )
        trace = self._lot_trace(pick.pk, establishment_id=str(self.est.pk)).json()
        self.assertEqual(trace["anchor"], "pick")
        self.assertNotIn("sale", trace)
        self.assertEqual([p["id"] for p in trace["picks"]], [pick.pk])
        self.assertEqual(trace["season"]["name"], "2026 blueberries")
        [row] = trace["inputs"]
        # Unclassified is never prohibited.
        self.assertEqual(row["listing"], "not_classified")
        # Days counted to THIS pick (Jul 20 -> Aug 1).
        self.assertEqual(row["days_to_pick"], 12)
        codes = {(g["hop"], g["code"], g["ref"]) for g in trace["gaps"]}
        self.assertIn(("picks", "pick_without_lot_code", pick.pk), codes)
        self.assertIn(("season", "season_without_lot_id", None), codes)
        for code in ("input_without_supplier", "input_without_invoice", "input_without_lot"):
            self.assertIn(("inputs", code, spray.pk), codes)
        # No sale hop on a lot trace, so no sale gap.
        self.assertFalse(any(g["hop"] == "sale" for g in trace["gaps"]))

    def test_a_pick_no_sale_names_is_not_a_gap_and_lists_the_seasons_unlinked_sales(self):
        season = self._season()
        pick = self._pick(season)
        unlinked = self._sale(season, invoice_number="NO-PICK")
        trace = trace_pick(pick).as_dict()
        self.assertEqual(trace["sales"], [])
        self.assertEqual([s["sale_id"] for s in trace["sales_naming_no_pick"]], [unlinked.pk])
        self.assertFalse(any(g["code"] == "sale_not_linked_to_pick" for g in trace["gaps"]))

    def test_a_pick_named_by_two_sales_lists_both_and_says_what_else_each_names(self):
        season = self._season()
        pick = self._pick(season)
        other = self._pick(season, lot_code="OTHER", day=3)
        a = self._sale(season, picks=[pick], invoice_number="A", quantity=6000)
        b = self._sale(season, picks=[pick, other], invoice_number="B", quantity=9000)
        trace = trace_pick(pick).as_dict()
        self.assertEqual([(s["sale_id"], s["picks_named"]) for s in trace["sales"]], [(a.pk, 1), (b.pk, 2)])
        self.assertEqual(trace["sales_naming_no_pick"], [])

    def test_a_voided_sale_never_reads_as_where_the_pick_went(self):
        season = self._season()
        pick = self._pick(season)
        sale = self._sale(season, picks=[pick])
        unlinked = self._sale(season, invoice_number="U")
        SalesRecord.objects.filter(pk__in=[sale.pk, unlinked.pk]).update(
            voided_at=timezone.now(), void_reason="duplicate"
        )
        trace = trace_pick(pick).as_dict()
        self.assertEqual((trace["sales"], trace["sales_naming_no_pick"]), ([], []))

    def test_another_farms_receipt_or_file_never_appears_on_the_lot(self):
        season = self._season()
        pick = self._pick(season)
        sister = Establishment.objects.create(name="Lower Ranch", company=self.company, state="OR")
        spray = ChemicalEvent.objects.create(
            history=season,
            description="s",
            date=timezone.now(),
            commercial_name="Kocide",
            supplier_name="S",
            purchase_invoice="I",
            chemical_lot_number="L",
        )
        spray.receipt_document = self._file(title="lower-ranch-invoice.pdf", establishment=sister)
        spray.save(update_fields=["receipt_document"])
        self._file(event=pick, establishment=sister, title="lower-ranch-bin-tag.pdf")
        mine = self._file(event=pick, title="bin-tag.pdf")
        trace = trace_pick(pick).as_dict()
        [row] = trace["inputs"]
        self.assertEqual(row["documents"], [])
        self.assertIn(("input_without_document", spray.pk), {(g["code"], g["ref"]) for g in trace["gaps"]})
        self.assertEqual([d["id"] for d in trace["picks"][0]["documents"]], [mine.pk])

    def test_seed_status_is_never_read_as_allowed(self):
        season = self._season()
        pick = self._pick(season)
        ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.PLANTING,
            description="p",
            date=timezone.make_aware(datetime(2026, 3, 10)),
            variety="Duke",
            seed_supplier_name="Nursery",
            seed_certification_status="non_organic_untreated",
        )
        [row] = trace_pick(pick).as_dict()["inputs"]
        self.assertEqual(row["kind"], "seed")
        self.assertEqual(row["listing"], "recorded_other")
