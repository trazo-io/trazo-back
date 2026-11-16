"""A sale can be recorded while its season is still open, and every reader says so.

WHAT WAS WRONG (2026-10-26)
---------------------------
The production page rendered the sales editor only once the season was finished. The API never
refused an open-season sale (``SalesRecordViewSet.create`` has no finish check), so the gate was
frontend-only, copied in 2026-06 from the legacy single-sale editor with no stated reason. A
berry grower picks and sells all summer: they could log July's picks and not one of July's
sales until the season closed.

Opening the form makes a state common that the readers had only seen in fixtures: an OPEN
season with SOME sales. Three packet flags fired on it as if the season were closed:

  * "[REVIEW] N harvest record(s) are on no sales record", for picks simply not sold yet;
  * "[REVIEW] Output reconciliation incomplete", for a season with picks and no sale yet;
  * the boxes-to-pounds tolerance check, which a partly sold season fails by construction.

On an open season these are now stated as figures as at the export date, not as findings. On a
finished season they are unchanged, and that is asserted too: a guard that only checks the open
branch passes when the flag is deleted outright.

The invariant the old gate might have been protecting is the § 205.103(b)(4) retention floor.
It is not tied to the gate: ``retention_floor`` counts every sale's ``created_at``, so a sale
recorded mid-season is covered once the season is finished, and becomes undeletable then.
"""

import csv
import io
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import Production, ProductionEvent, SalesRecord, compute_retention_until
from history.retention import latest_covered_record_created
from product.models import Parcel, Product
from users.models import User, WorksIn


class _OpenSeason(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@open-season.test", password="x")
        self.company = Company.objects.create(name="Coast Fork Test Co")
        self.establishment = Establishment.objects.create(name="Home", company=self.company, state="OR")
        WorksIn.objects.create(user=self.owner, company=self.company, role="CA")
        self.parcel = Parcel.objects.create(name="North", establishment=self.establishment, area=3.0)
        self.product = Product.objects.create(name="Blueberries")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def _season(self, *, finished=False):
        kwargs = dict(
            name="2027 blueberries",
            start_date=timezone.now() - timedelta(days=90),
            product=self.product,
            parcel=self.parcel,
            operator=self.owner,
            is_outdoor=True,
        )
        if finished:
            kwargs.update(finish_date=timezone.now() - timedelta(days=1), production_amount=600, lot_id="BB-27")
        return Production.objects.create(**kwargs)

    def _pick(self, season, days_ago, qty=300, unit="lb"):
        return ProductionEvent.objects.create(
            history=season,
            type="HA",
            date=timezone.now() - timedelta(days=days_ago),
            created_by=self.owner,
            block_id="N",
            yield_quantity=qty,
            yield_unit=unit,
        )

    def _sale(self, season, picks=(), qty=300, unit="lb"):
        sale = SalesRecord.objects.create(
            production=season,
            sale_date=timezone.now().date() - timedelta(days=5),
            buyer_name="Willamette Valley Co-op",
            quantity=qty,
            quantity_unit=unit,
            organic_on_invoice=True,
        )
        sale.harvest_events.set(picks)
        return sale

    def _pdf_text(self, season):
        from history.services.audit_export_service import AuditExportService

        out = []
        for el in AuditExportService(season, certification_type="all")._build_mass_balance_section():
            text = getattr(el, "text", None)
            if text:
                out.append(str(text))
            if hasattr(el, "_cellvalues"):
                out.append(str(el._cellvalues))
        return " || ".join(out)

    def _csv_rows(self, season):
        from history.services.audit_export_service import AuditExportService

        raw = AuditExportService(season).generate_csv().getvalue()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig")
        return list(csv.reader(io.StringIO(raw)))


class OpenSeasonSaleApiTests(_OpenSeason):
    def test_a_sale_is_created_on_an_open_season_linked_to_a_pick(self):
        season = self._season()
        pick = self._pick(season, days_ago=10)
        self.assertIsNone(season.finish_date)

        lots = self.client.get(f"/api/sales_records/harvest_lots/?production_id={season.public_id}")
        self.assertEqual(lots.status_code, 200)
        self.assertEqual([row["id"] for row in lots.json()], [pick.pk])
        self.assertTrue(lots.json()[0]["lot_code"], "save() suggests a lot code for the pick")

        resp = self.client.post(
            "/api/sales_records/",
            {
                "production_id": str(season.public_id),
                "sale_date": (timezone.now().date() - timedelta(days=9)).isoformat(),
                "buyer_name": "Willamette Valley Co-op",
                "quantity": "300",
                "quantity_unit": "lb",
                "organic_on_invoice": True,
                "harvest_events": [pick.pk],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        sale = SalesRecord.objects.get(pk=resp.json()["id"])
        self.assertEqual(sale.production_id, season.pk)
        self.assertEqual(list(sale.harvest_events.values_list("pk", flat=True)), [pick.pk])
        self.assertEqual(resp.json()["harvest_lot_codes"], [pick.harvest_lot_code])

    def test_a_mid_season_sale_is_inside_the_retention_floor_once_finished(self):
        """What the old gate could have been protecting, shown not to depend on it."""
        season = self._season()
        pick = self._pick(season, days_ago=10)
        sale = self._sale(season, picks=[pick])
        self.assertIsNone(season.retention_until)

        season.finish(
            {
                "finish_date": timezone.now(),
                "production_amount": 300,
                "lot_id": "BB-27",
                "production_unit": "lb",
                "published": "false",
            },
            images=[],
        )
        season.refresh_from_db()
        self.assertGreaterEqual(latest_covered_record_created(season), sale.created_at.date())
        self.assertGreaterEqual(season.retention_until, compute_retention_until(sale.created_at))

        resp = self.client.delete(f"/api/sales_records/{sale.pk}/")
        self.assertEqual(resp.status_code, 423)
        self.assertTrue(SalesRecord.objects.filter(pk=sale.pk).exists())


class OpenSeasonPacketTests(_OpenSeason):
    def test_open_season_says_figures_are_as_at_not_season_totals(self):
        season = self._season()
        self._sale(season, picks=[self._pick(season, days_ago=10)])
        self._pick(season, days_ago=2)

        text = self._pdf_text(season)
        self.assertIn("Season open.", text)
        self.assertIn("not season totals", text)

    def test_a_pick_not_sold_yet_is_named_without_a_review_flag(self):
        season = self._season()
        self._sale(season, picks=[self._pick(season, days_ago=10)])
        self._pick(season, days_ago=2)

        text = self._pdf_text(season)
        self.assertIn("on no sales record as at", text)
        self.assertNotIn("[REVIEW] 1 harvest record(s)", text)

    def test_the_same_unsold_pick_on_a_finished_season_is_still_flagged(self):
        season = self._season(finished=True)
        self._sale(season, picks=[self._pick(season, days_ago=10)])
        self._pick(season, days_ago=2)

        text = self._pdf_text(season)
        self.assertIn("[REVIEW] 1 harvest record(s)", text)
        self.assertNotIn("Season open.", text)

    def test_picked_and_not_sold_yet_is_not_an_incomplete_trail(self):
        season = self._season()
        self._pick(season, days_ago=3)

        text = self._pdf_text(season)
        self.assertNotIn("Output reconciliation incomplete", text)
        self.assertIn("this reconciliation is assessed once it is finished", text)

        finished = self._season(finished=True)
        self._pick(finished, days_ago=3)
        self.assertIn("Output reconciliation incomplete", self._pdf_text(finished))

    def test_a_partly_sold_season_is_not_judged_against_the_shrink_tolerance(self):
        def boxed(finished):
            season = self._season(finished=finished)
            season.box_weight_lb = 10
            season.save(update_fields=["box_weight_lb"])
            self._pick(season, days_ago=10, qty=1000)
            self._sale(season, qty=30, unit="boxes")  # 300 lb of 1,000 picked
            return self._pdf_text(season)

        open_text = boxed(finished=False)
        self.assertIn("Not assessed: season open", open_text)
        self.assertNotIn("outside the", open_text)

        closed_text = boxed(finished=True)
        self.assertIn("outside the", closed_text)

    def test_sales_in_boxes_exceeding_the_picks_are_flagged_while_open(self):
        """With a harvest in lb and sales in boxes, the tolerance check is the only oversold check
        that runs, so an open season must not silence it when sold exceeds harvested."""
        season = self._season()
        season.box_weight_lb = 12
        season.save(update_fields=["box_weight_lb"])
        self._pick(season, days_ago=10, qty=1000)
        self._sale(season, qty=200, unit="boxes")  # 2,400 lb sold against 1,000 lb picked

        text = self._pdf_text(season)
        self.assertIn("outside the", text)
        self.assertNotIn("Not assessed: season open", text)

    def test_sales_that_cannot_be_summed_are_not_called_no_sale(self):
        """Mixed-unit sales leave the summed quantity empty; that is not "nothing sold yet"."""
        season = self._season()
        self._pick(season, days_ago=10)
        self._sale(season, qty=100, unit="lb")
        self._sale(season, qty=5, unit="boxes")

        text = self._pdf_text(season)
        self.assertNotIn("No quantity sold is recorded", text)
        self.assertIn("Output reconciliation incomplete", text)

    def test_overselling_is_still_flagged_while_the_season_is_open(self):
        """More sold than picked so far is not a timing artefact: a pick is missing."""
        season = self._season()
        self._sale(season, picks=[self._pick(season, days_ago=10, qty=300)], qty=500)

        # The exhibit's rule and words (overall review 2026-11, OV-FJ-C24).
        text = self._pdf_text(season)
        self.assertIn("[REVIEW]", text)
        self.assertIn("sales exceed the recorded harvest by 200", text)

    def test_the_csv_states_the_season_is_open(self):
        open_rows = self._csv_rows(self._season())
        self.assertIn("Season status", [row[0] for row in open_rows if row])

        closed_rows = self._csv_rows(self._season(finished=True))
        self.assertNotIn("Season status", [row[0] for row in closed_rows if row])


class OpenSeasonTracebackTests(_OpenSeason):
    def test_the_trace_balance_says_the_season_is_open(self):
        from history.services.traceback import trace_sale

        season = self._season()
        sale = self._sale(season, picks=[self._pick(season, days_ago=10)])
        self.assertTrue(trace_sale(sale).as_dict()["balance"]["season_open"])

        closed = self._season(finished=True)
        closed_sale = self._sale(closed, picks=[self._pick(closed, days_ago=10)])
        self.assertFalse(trace_sale(closed_sale).as_dict()["balance"]["season_open"])
