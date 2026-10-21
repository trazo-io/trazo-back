"""
Traceback from one sale: the inspector's § 205.103(b)(2) exercise, run by the operation first.

The inspector picks a lot off a sales document and walks it back: sale -> harvest pick -> season ->
inputs. These tests pin the three things that would make the drill lie: picking one of several
matches for the operator, answering for another company's records, and naming an unclassified
input as anything but unclassified.
"""

from datetime import datetime, timedelta
from decimal import Decimal

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

    def _file(self, *, sale=None, kind="", event=None, establishment=None, title="scan.pdf"):
        """A filed document, as the Documents page or a sales row's "Attach document" creates one."""
        from documents.models import GeneratedDocument

        event_type = None
        if event is not None:
            event_type = {"ChemicalEvent": 2, "SoilManagementEvent": 5, "ProductionEvent": 1}[type(event).__name__]
        return GeneratedDocument.objects.create(
            establishment=establishment or self.est,
            folder="uploads",
            source="upload",
            title=title,
            sales_record=sale,
            source_kind=kind,
            event_type=event_type,
            event_id=event.pk if event is not None else None,
        )

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
        self._file(sale=sale, kind="invoice")
        trace = self._trace(sale.pk).json()
        self.assertTrue(trace["picks_linked"])
        self.assertEqual([p["lot_code"] for p in trace["picks"]], ["BLU-UT-20260801"])
        self.assertEqual(trace["season"]["lot_id"], "CBF-26-UT-01")
        self.assertEqual(trace["season"]["company_id"], self.company.pk)
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
            {(f"input_without_{f}", spray.pk, "chemical") for f in ("supplier", "invoice", "lot", "document")},
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


class DocumentsOnFileTests(_TraceBase):
    """The inspector asks to SEE the paper. The chain names each file the operation holds, by id
    (the page opens it through the farm's own documents route), and a missing one is a gap."""

    def test_a_sale_with_no_file_is_a_gap_and_its_files_are_listed_by_kind(self):
        season = self._season()
        sale = self._sale(season, picks=[self._pick(season)])
        self.assertIn("sale_without_document", {g["code"] for g in trace_sale(sale).as_dict()["gaps"]})
        bol = self._file(sale=sale, kind="bill_of_lading", title="BOL-77120.pdf")
        trace = trace_sale(sale).as_dict()
        self.assertEqual(
            trace["sale"]["documents"], [{"id": bol.pk, "title": "BOL-77120.pdf", "kind": "bill_of_lading"}]
        )
        self.assertNotIn("sale_without_document", {g["code"] for g in trace["gaps"]})

    def test_another_farms_file_is_never_shown_even_if_it_points_at_this_sale(self):
        season = self._season()
        sale = self._sale(season)
        other = Establishment.objects.create(name="Elsewhere", company=Company.objects.create(name="X"), state="OR")
        self._file(sale=sale, kind="invoice", establishment=other)
        trace = trace_sale(sale).as_dict()
        # Read something first: the sale hop rendered.
        self.assertEqual(trace["sale"]["invoice"], "INV-2026-0912")
        self.assertEqual(trace["sale"]["documents"], [])

    def test_an_input_receipt_or_a_receipt_filed_on_it_closes_the_document_gap(self):
        season = self._season()
        sale = self._sale(season)
        with_receipt = ChemicalEvent.objects.create(
            history=season,
            description="s",
            date=timezone.now(),
            commercial_name="Kocide",
            supplier_name="S",
            purchase_invoice="I",
            chemical_lot_number="L",
        )
        with_receipt.receipt_document = self._file(title="kocide-invoice.pdf")
        with_receipt.save(update_fields=["receipt_document"])
        with_attachment = ChemicalEvent.objects.create(
            history=season,
            description="s",
            date=timezone.now(),
            commercial_name="Entrust",
            supplier_name="S",
            purchase_invoice="I",
            chemical_lot_number="L",
        )
        self._file(event=with_attachment, title="entrust-invoice.pdf", kind="receipt")
        # Review of back #207: a lab report or photo filed on the record is shown, as an
        # attachment, and the missing-receipt gap stays.
        lab_report_only = ChemicalEvent.objects.create(
            history=season,
            description="s",
            date=timezone.now(),
            commercial_name="Grandevo",
            supplier_name="S",
            purchase_invoice="I",
            chemical_lot_number="L",
        )
        self._file(event=lab_report_only, title="residue-lab-report.pdf")
        bare = ChemicalEvent.objects.create(
            history=season,
            description="s",
            date=timezone.now(),
            commercial_name="Surround",
            supplier_name="S",
            purchase_invoice="I",
            chemical_lot_number="L",
        )
        trace = trace_sale(sale).as_dict()
        files = {r["product"]: [d["title"] for d in r["documents"]] for r in trace["inputs"]}
        self.assertEqual(
            files,
            {
                "Kocide": ["kocide-invoice.pdf"],
                "Entrust": ["entrust-invoice.pdf"],
                "Grandevo": ["residue-lab-report.pdf"],
                "Surround": [],
            },
        )
        kinds = {r["product"]: [d["kind"] for d in r["documents"]] for r in trace["inputs"]}
        self.assertEqual((kinds["Entrust"], kinds["Grandevo"]), (["receipt"], ["attachment"]))
        doc_gaps = {g["ref"] for g in trace["gaps"] if g["code"] == "input_without_document"}
        self.assertEqual(doc_gaps, {bare.pk, lab_report_only.pk})

    def test_a_beneficial_release_has_no_receipt_field_so_no_document_gap(self):
        season = self._season()
        sale = self._sale(season)
        PestManagementEvent.objects.create(
            history=season,
            type=PestManagementEvent.BENEFICIAL_RELEASE,
            description="b",
            date=timezone.now(),
            beneficial_species="Trichogramma",
            beneficial_supplier="S",
            beneficial_lot_number="L",
        )
        trace = trace_sale(sale).as_dict()
        self.assertEqual([r["kind"] for r in trace["inputs"]], ["beneficial"])
        self.assertNotIn("input_without_document", {g["code"] for g in trace["gaps"]})

    def test_a_bin_receipt_filed_on_the_pick_is_shown_not_required(self):
        season = self._season()
        pick = self._pick(season)
        sale = self._sale(season, picks=[pick])
        trace = trace_sale(sale).as_dict()
        self.assertEqual(trace["picks"][0]["documents"], [])
        self.assertNotIn("picks", {g["hop"] for g in trace["gaps"]})
        self._file(event=pick, title="bin-receipt.jpg")
        self.assertEqual([d["title"] for d in trace_sale(sale).as_dict()["picks"][0]["documents"]], ["bin-receipt.jpg"])


class ReviewOf191Tests(_TraceBase):
    """Review of back #191: a receipt from another farm of the SAME company is not this trace's."""

    def test_a_receipt_from_the_companys_other_farm_is_not_shown_and_the_gap_stays(self):
        season = self._season()
        sale = self._sale(season)
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
        trace = trace_sale(sale).as_dict()
        [row] = trace["inputs"]
        self.assertEqual(row["product"], "Kocide")
        self.assertEqual(row["documents"], [])
        self.assertIn(("input_without_document", spray.pk), {(g["code"], g["ref"]) for g in trace["gaps"]})

    def test_a_season_without_a_parcel_does_not_crash(self):
        season = self._season()
        sale = self._sale(season)
        History.objects.filter(pk=season.pk).update(parcel=None)
        sale.refresh_from_db()
        trace = trace_sale(sale).as_dict()
        self.assertEqual(trace["sale"]["documents"], [])
        self.assertIsNone(trace["season"]["establishment_id"])


class RecallSearchTests(_TraceBase):
    """The two calls a grower gets that start from something other than a sales document: the
    packer quoting its own receipt number, and a supplier recalling a lot of something applied."""

    def test_the_packers_receipt_on_a_pick_finds_the_sale(self):
        season = self._season()
        pick = self._pick(season)
        ProductionEvent.objects.filter(pk=pick.pk).update(handler_document_reference="SVP-RCV-55120")
        sale = self._sale(season, picks=[pick])
        rows = self._search(q=" svp-rcv-55120 ").json()["results"]
        self.assertEqual([(r["sale_id"], r["matched_on"]) for r in rows], [(sale.pk, "handler_document")])

    def test_the_packers_receipt_also_finds_the_seasons_unlinked_sales(self):
        season = self._season()
        pick = self._pick(season)
        ProductionEvent.objects.filter(pk=pick.pk).update(handler_document_reference="SVP-RCV-55120")
        unlinked = self._sale(season)
        rows = self._search(q="SVP-RCV-55120").json()["results"]
        self.assertEqual([(r["sale_id"], r["matched_on"]) for r in rows], [(unlinked.pk, "handler_document_season")])

    def test_an_input_lot_or_invoice_lists_every_sale_of_each_season_it_was_applied_in(self):
        from history.models import SoilManagementEvent

        treated, untreated = self._season(name="treated"), self._season(name="untreated", lot_id="OTHER")
        a = self._sale(treated, invoice_number="A", quantity=4000)
        b = self._sale(treated, invoice_number="B")
        self._sale(untreated, invoice_number="C")
        SoilManagementEvent.objects.create(
            history=treated,
            description="compost",
            date=timezone.make_aware(datetime(2026, 3, 10)),
            amendment_product_name="Compost",
            amendment_lot_number="CMP-4471",
            amendment_purchase_invoice="GRO-88231",
        )
        for q, label in (("cmp-4471", "input_lot"), ("GRO-88231", "input_invoice")):
            with self.subTest(q=q):
                rows = self._search(q=q).json()["results"]
                self.assertEqual({(r["sale_id"], r["matched_on"]) for r in rows}, {(a.pk, label), (b.pk, label)})
        # Read as a recall list: who got how much.
        rows = {r["sale_id"]: r["quantity"] for r in self._search(q="CMP-4471").json()["results"]}
        self.assertEqual(rows[a.pk], "4,000 lb")

    def test_a_spray_lot_from_another_company_matches_nothing(self):
        other = Company.objects.create(name="Other")
        est = Establishment.objects.create(name="X", company=other)
        season = self._season(parcel=Parcel.objects.create(name="P", establishment=est, area=1))
        self._sale(season)
        ChemicalEvent.objects.create(
            history=season, description="s", date=timezone.now(), commercial_name="X", chemical_lot_number="LOT-9"
        )
        self.assertEqual(self._search(q="LOT-9").json()["results"], [])


class PreHarvestIntervalTests(_TraceBase):
    def _spray(self, season, day, phi=None, block="UT", month=7):
        return ChemicalEvent.objects.create(
            history=season,
            description="spray",
            date=timezone.make_aware(datetime(2026, month, day)),
            commercial_name="Entrust SC",
            block_id=block,
            phi_days=phi,
        )

    def _rows(self, sale):
        return {r["event_id"]: r for r in trace_sale(sale).as_dict()["inputs"]}

    def test_days_to_the_next_pick_sit_beside_the_recorded_phi(self):
        season = self._season()
        sale = self._sale(season, picks=[self._pick(season, day=10)])
        ok, early = self._spray(season, day=25, phi=7, month=7), self._spray(season, day=7, phi=7, month=8)
        # A 7-day PHI allows the pick on day 7: the boundary is outside, not inside.
        exact = self._spray(season, day=3, phi=7, month=8)
        rows = self._rows(sale)
        self.assertEqual((rows[exact.pk]["days_to_pick"], rows[exact.pk]["inside_phi"]), (7, False))
        self.assertEqual(
            (rows[ok.pk]["days_to_pick"], rows[ok.pk]["phi_days"], rows[ok.pk]["inside_phi"]), (16, "7", False)
        )
        self.assertEqual((rows[early.pk]["days_to_pick"], rows[early.pk]["inside_phi"]), (3, True))

    def test_a_phi_prints_as_days_never_in_scientific_notation(self):
        season = self._season()
        sale = self._sale(season, picks=[self._pick(season, day=20)])
        ids = {
            phi: self._spray(season, day=1, phi=phi, month=8).pk
            for phi in (Decimal("10"), Decimal("0.0"), Decimal("1.5"))
        }
        rows = self._rows(sale)
        self.assertEqual(
            {phi: rows[pk]["phi_days"] for phi, pk in ids.items()},
            {Decimal("10"): "10", Decimal("0.0"): "0", Decimal("1.5"): "1.5"},
        )

    def test_a_fertilizer_or_dispensers_with_no_phi_get_no_days_line(self):
        season = self._season()
        sale = self._sale(season, picks=[self._pick(season, day=20)])
        feed = self._spray(season, day=1, month=8)
        ChemicalEvent.objects.filter(pk=feed.pk).update(type=ChemicalEvent.FERTILIZER)
        ties = self._spray(season, day=2, month=8)
        ChemicalEvent.objects.filter(pk=ties.pk).update(application_method_structured="hand_dispenser")
        rows = self._rows(sale)
        self.assertEqual((rows[feed.pk]["days_to_pick"], rows[ties.pk]["days_to_pick"]), (None, None))

    def test_no_recorded_phi_is_never_read_as_inside_it(self):
        season = self._season()
        sale = self._sale(season, picks=[self._pick(season, day=2)])
        spray = self._spray(season, day=1, month=8)
        row = self._rows(sale)[spray.pk]
        self.assertEqual((row["days_to_pick"], row["phi_days"], row["inside_phi"]), (1, "", False))

    def test_a_pick_on_another_block_or_before_the_spray_does_not_count(self):
        season = self._season()
        sale = self._sale(
            season,
            picks=[self._pick(season, day=1, block="UT"), self._pick(season, day=3, block="LOWER", lot_code="L")],
        )
        spray = self._spray(season, day=2, phi=14, month=8)
        row = self._rows(sale)[spray.pk]
        self.assertEqual((row["days_to_pick"], row["inside_phi"]), (None, False))
