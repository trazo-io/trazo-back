"""One harvest-against-sales figure, on every document an inspector is handed.

WHAT WAS WRONG (overall review 2026-11, OV-FJ-C24 / OV-RK-C06)
---------------------------------------------------------------
The same season gave two figures. The trace and the audit trail exhibit said "Harvested minus
sold: 212 bins", with the 182-bin sale "counted apart" because its invoice did not identify the
fruit as organic; the audit dossier's Output Reconciliation said "Balance: 30 bins".

`_lot_balance` read EVERY sale not marked organic on the invoice as the buffer-row crop, in a
season with no buffer crop at all, and `organic_on_invoice` defaults to False: a grower who left the
box unticked had every sale left out, on the trace and in the storage reading (fruit sold still "on
hand"). The dossier computed its own balance: every sale against every pick, buffer picks
included, a header fallback, and its own 2% oversell rule.

Now one rule decides what leaves the organic lot (`buffer_sales`: a sale is the buffer crop only
on evidence) and one sentence states the balance (`balance_statement`), printed by the exhibit and
the dossier alike.
"""

import csv
import io
from datetime import date, datetime

from django.utils import timezone

from certifications.services.audit_trail_exhibit import (
    _lot_balance,
    balance_statement,
    buffer_dispositions,
    sample_trail,
)
from certifications.tests.test_audit_trail_exhibit import _ExhibitBase
from history.models import Production, ProductionEvent, SalesRecord
from history.services.storage_on_hand import on_hand_by_location
from history.services.traceback import trace_sale
from product.models import Product


def _flat(text: str) -> str:
    return " ".join(text.split())


class _Season(_ExhibitBase):
    def _season(self, *, finished=True):
        kwargs = dict(
            name="2026 Gala",
            parcel=self.parcel,
            product=Product.objects.create(name="Apples"),
            start_date=timezone.make_aware(datetime(2026, 3, 1)),
            lot_id="CB-26-B1",
        )
        if finished:
            kwargs["finish_date"] = timezone.make_aware(datetime(2026, 10, 20))
        return Production.objects.create(**kwargs)

    def _pick(self, season, qty, unit="bins", day=14, **kw):
        return ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.HARVESTING,
            description="pick",
            date=timezone.make_aware(datetime(2026, 9, day)),
            yield_quantity=qty,
            yield_unit=unit,
            **kw,
        )

    def _sale(self, season, qty, unit="bins", picks=(), organic=True, invoice="INV-1"):
        sale = SalesRecord.objects.create(
            production=season,
            sale_date=date(2026, 10, 1),
            buyer_name="Columbia Fruit Packers",
            quantity=qty,
            quantity_unit=unit,
            invoice_number=invoice,
            organic_on_invoice=organic,
            organic_label_category="organic" if organic else "",
        )
        sale.harvest_events.set(picks)
        return sale

    def _dossier_text(self, season):
        from history.services.audit_export_service import AuditExportService

        out = []
        for el in AuditExportService(season, certification_type="all")._build_mass_balance_section():
            text = getattr(el, "text", None)
            if text:
                out.append(str(text))
        return _flat(" || ".join(out))

    def _dossier_csv(self, season):
        from history.services.audit_export_service import AuditExportService

        raw = AuditExportService(season).generate_csv().getvalue()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig")
        return {row[0]: row[1] for row in csv.reader(io.StringIO(raw)) if len(row) >= 2}

    def _statement(self, season, **kw):
        picks = list(ProductionEvent.objects.filter(history=season, type=ProductionEvent.HARVESTING))
        return balance_statement(_lot_balance(picks, list(SalesRecord.objects.live().filter(production=season))), **kw)


class TheLaneCaseTests(_Season):
    """212 bins picked, one 182-bin sale whose invoice does not say organic, no buffer crop."""

    def setUp(self):
        super().setUp()
        self.season = self._season()
        self.pick = self._pick(self.season, 212)
        self.sale = self._sale(self.season, 182, organic=False)

    def test_the_trace_subtracts_the_sale_and_names_it(self):
        balance = trace_sale(self.sale).as_dict()["balance"]
        self.assertEqual(
            (balance["harvested"], balance["sold"], balance["difference"]), ("212 bins", "182 bins", "30 bins")
        )
        self.assertEqual((balance["sold_not_organic"], balance["sold_not_organic_count"]), ("182 bins", 1))
        self.assertEqual((balance["buffer_sold"], balance["buffer_sale_count"]), ("", 0))

    def test_the_exhibit_and_the_dossier_print_one_sentence(self):
        text, review = self._statement(self.season)
        self.assertFalse(review)
        self.assertIn("sold 182 bins (1 sale), of which 182 bins on 1 invoice that do not identify it as organic", text)
        self.assertIn("30 bins harvested is on no sale", text)

        exhibit = _flat(self._exhibit_text()[0])
        self.assertIn(text, exhibit)
        self.assertNotIn("Buffer crop", exhibit)

        dossier = self._dossier_text(self.season)
        self.assertIn(f"Organic lot: harvested minus sold:</b> {text}", dossier)
        self.assertNotIn("Balance (Yield", dossier)

        self.assertEqual(self._dossier_csv(self.season)["Organic lot: harvested minus sold"], text)

    def test_part_c_lists_no_buffer_sale(self):
        self.assertEqual(buffer_dispositions(self.est), [])

    def test_storage_no_longer_keeps_sold_fruit_on_hand(self):
        ProductionEvent.objects.filter(pk=self.pick.pk).update(storage_location="CA Room 2")
        self.sale.harvest_events.set([self.pick])
        [row] = on_hand_by_location(self.season)["locations"]
        self.assertEqual((row["sold"], row["difference"], row["sold_not_organic"]), ("182 bins", "30 bins", "182 bins"))


class TheBufferCropIsStillCountedApartTests(_Season):
    """A sale is the buffer crop on evidence: a link to buffer picks, or a season that sells one."""

    def test_a_sale_linked_only_to_buffer_picks_is_counted_apart(self):
        season = self._season()
        lot = self._pick(season, 200)
        buffer = self._pick(
            season, 20, day=15, buffer_disposition="sold_conventional", buffer_disposition_quantity="20 bins"
        )
        self._sale(season, 150, picks=[lot])
        self._sale(season, 20, picks=[buffer], organic=False, invoice="CONV-1")

        balance = sample_trail(self.est).balance
        self.assertEqual((balance.harvested, balance.sold, balance.difference), (200, 150, 50))
        self.assertEqual((balance.buffer_sold, balance.buffer_sale_count, balance.sold_not_organic_count), (20, 1, 0))
        dossier = self._dossier_text(season)
        self.assertIn("Buffer crop (7 CFR 205.202(c)), counted apart from the organic lot", dossier)
        [part_c] = buffer_dispositions(self.est)
        self.assertEqual([s[3] for s in part_c.sales], ["CONV-1"])

    def test_an_unlinked_unmarked_sale_in_a_season_that_sells_buffer_crop_is_counted_apart(self):
        # Calapooia records its buffer crop as buffer-use (BU) records, not as harvest records.
        season = self._season()
        self._pick(season, 200)
        ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.BUFFER_USE,
            description="buffer row",
            date=timezone.make_aware(datetime(2026, 9, 16)),
            buffer_disposition="sold_conventional",
            buffer_disposition_quantity="20 bins",
        )
        self._sale(season, 150)
        self._sale(season, 20, organic=False, invoice="CONV-1")

        balance = sample_trail(self.est).balance
        self.assertEqual((balance.sold, balance.difference, balance.buffer_sale_count), (150, 50, 1))

    def test_a_sale_linked_to_the_lot_is_the_lot_whatever_the_invoice_says(self):
        season = self._season()
        lot = self._pick(season, 200)
        self._pick(season, 20, day=15, buffer_disposition="sold_conventional", buffer_disposition_quantity="20 bins")
        self._sale(season, 50, picks=[lot], organic=False, invoice="CONV-1")

        balance = sample_trail(self.est).balance
        self.assertEqual((balance.sold, balance.sold_not_organic_count, balance.buffer_sale_count), (50, 1, 0))


class OneRuleTests(_Season):
    def test_an_open_season_says_so_far_not_state_where_it_went(self):
        season = self._season(finished=False)
        pick = self._pick(season, 300, unit="lb")
        self._sale(season, 100, unit="lb", picks=[pick])
        dossier = self._dossier_text(season)
        self.assertIn("200 lb harvested is on no sale recorded so far (the season is open, as at", dossier)
        self.assertNotIn("State where it went", dossier)

    def test_overselling_is_one_review_on_the_exhibit_and_the_dossier(self):
        season = self._season()
        self._pick(season, 6200, unit="lb")
        self._sale(season, 13400, unit="lb")
        text, review = self._statement(season)
        self.assertTrue(review)
        self.assertIn("sales exceed the recorded harvest by 7,200 lb", text)
        self.assertIn(f"[REVIEW] {text}", _flat(self._exhibit_text()[0]))
        dossier = self._dossier_text(season)
        self.assertIn(f"[REVIEW] 7 CFR 205.103(b)(2): Organic lot, harvested minus sold: {text}", dossier)
        self.assertNotIn("EXCEEDS harvest yield", dossier)

    def test_lb_and_lbs_are_one_unit_for_the_yield_row_too(self):
        season = self._season()
        self._pick(season, 6200, unit="lbs")
        self._pick(season, 3000, unit="lb", day=21)
        self._sale(season, 9200, unit="lb")
        dossier = self._dossier_text(season)
        self.assertIn("sum of 2 harvest record(s)", dossier)
        self.assertIn("harvest and sales balance", dossier)


class ReviewOf448Tests(_Season):
    """The review of back #448: evidence, invoice wording, the oversell check, and the header gap."""

    def test_a_lot_record_answering_the_buffer_question_is_not_evidence_of_a_buffer_sale(self):
        # The disposition with no buffer quantity is the lot's own record (`_is_buffer_pick`).
        season = self._season()
        self._pick(season, 212, buffer_disposition="sold_conventional")
        self._sale(season, 182, organic=False)
        balance = sample_trail(self.est).balance
        self.assertEqual((balance.sold, balance.difference, balance.buffer_sale_count), (182, 30, 0))
        self.assertEqual(balance.sold_not_organic_count, 1)

    def test_a_buffer_sale_invoiced_as_organic_is_never_said_to_be_unidentified(self):
        season = self._season()
        self._pick(season, 200)
        buffer = self._pick(
            season, 20, day=15, buffer_disposition="sold_conventional", buffer_disposition_quantity="20 bins"
        )
        self._sale(season, 20, picks=[buffer], organic=True, invoice="BUF-ORG")
        dossier = self._dossier_text(season)
        self.assertIn("20 bins sold on 1 invoice, each identifying it as organic", dossier)
        self.assertNotIn("that do not identify it as organic", dossier)

    def test_overselling_is_flagged_when_the_balance_cannot_be_computed(self):
        # One pick carries no quantity: the balance is not computed, and the yield row's total
        # (the picks that carry one) still catches a sale above it.
        season = self._season()
        self._pick(season, 100, unit="lb")
        self._pick(season, None, unit="lb", day=21)
        self._sale(season, 150, unit="lb")
        dossier = self._dossier_text(season)
        self.assertIn("Balance not computed: 1 of 2 harvest record(s) carry no quantity", dossier)
        self.assertIn("EXCEEDS harvest yield", dossier)

    def test_the_header_gap_is_reported_across_lb_and_lbs(self):
        season = self._season()
        Production.objects.filter(pk=season.pk).update(production_amount=9000, production_unit="lb")
        self._pick(season, 6200, unit="lbs")
        self._pick(season, 3000, unit="lb", day=21)
        self._sale(season, 9200, unit="lb")
        self.assertIn("The harvest records total", self._dossier_text(season))
