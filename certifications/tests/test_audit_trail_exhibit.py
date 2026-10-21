"""
05-audit-trail-exhibit.pdf — the § 205.103(b)(2) trace-back the packet now carries.

Two certifier asks, two rules. CCOF G8.0 B1 wants a sample audit trail with the linking elements
highlighted and the organic status shown; Oregon Tilth C12 Q6 wants a table of documents with the
element linking each to the next. Part A lists only record types the OPERATOR confirmed (the
producer authors the plan); Part B walks one real lot and states every missing link as missing.
"""

import io
import zipfile
from datetime import date, datetime

from django.test import TestCase
from django.utils import timezone

from certifications.models import OrganicSystemPlan
from certifications.services import common_osp_records
from certifications.services.audit_trail_exhibit import document_table, sample_trail
from certifications.services.osp_module_pdf import generate_osp_packet
from company.models import Company, Establishment
from history.models import History, ProductionEvent, SalesRecord
from product.models import Parcel, Product
from users.models import User, WorksIn

from .test_renewal_packet_contents import _pdf_text


class _ExhibitBase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Calapooia Bend Farm LLC")
        self.user = User.objects.create_user(email="laurel@test.com", password="x", first_name="Laurel")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Home Block", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="Upper Terrace", establishment=self.est, area=4.0)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")

    def _exhibit_text(self):
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp)))
        self.assertIn("05-audit-trail-exhibit.pdf", zf.namelist())
        return _pdf_text(zf.read("05-audit-trail-exhibit.pdf")), _pdf_text(zf.read("00-cover.pdf"))

    def _finished_season(self, lot_id="CBF-26-UT-01"):
        product = Product.objects.create(name="Blueberries")
        return History.objects.create(
            name="2026 blueberries",
            parcel=self.parcel,
            product=product,
            start_date=timezone.make_aware(datetime(2026, 3, 1)),
            finish_date=timezone.make_aware(datetime(2026, 8, 20)),
            lot_id=lot_id,
        )


class AbsencesAreStatedTests(_ExhibitBase):
    def test_the_packet_carries_the_exhibit_and_the_cover_lists_it(self):
        text, cover = self._exhibit_text()
        self.assertIn("Audit trail exhibit", text)
        self.assertIn("05.", cover)

    def test_no_confirmations_and_no_sale_are_stated_not_filled(self):
        text, _ = self._exhibit_text()
        self.assertIn("No record types have been confirmed", text)
        self.assertIn("No finished season with a recorded sale", text)
        self.assertNotIn("LOT —", text)

    def test_a_suggested_record_type_is_not_listed_until_confirmed(self):
        """Evidence exists (a harvest event) but the operator has not confirmed the record type —
        the auto-attestation this codebase already shipped once and undid."""
        season = self._finished_season()
        ProductionEvent.objects.create(
            history=season, type=ProductionEvent.HARVESTING, description="pick 1", date=timezone.now()
        )
        self.assertEqual(document_table(self.est, self.osp), [])


class DocumentTableTests(_ExhibitBase):
    def test_confirmed_record_types_print_with_trazos_linking_element(self):
        common_osp_records.confirm(self.osp, ["harvest_records", "invoices"], user=self.user)
        rows = {r.name: r for r in document_table(self.est, self.osp)}
        self.assertEqual(set(rows), {"Harvest records", "Invoices"})
        self.assertIn("Lot ID", rows["Harvest records"].linking_element)
        self.assertIn("Invoice number", rows["Invoices"].linking_element)
        text, _ = self._exhibit_text()
        self.assertIn("Harvest records", text)
        # A model field name on a certifier's page (2026-09-11). The link is the lot, said plainly.
        self.assertIn("Lot ID on the season record", text)
        self.assertNotIn("History.lot_id", text)

    def test_a_record_trazo_cannot_hold_leaves_the_link_for_the_operator(self):
        common_osp_records.confirm(self.osp, ["weigh_tickets"], user=self.user)
        [row] = document_table(self.est, self.osp)
        self.assertEqual(row.name, "Weigh tickets")
        self.assertIsNone(row.linking_element)
        text, _ = self._exhibit_text()
        self.assertIn("state the linking element", text)


class SampleTrailTests(_ExhibitBase):
    def _sale(self, season, **kw):
        defaults = dict(
            production=season,
            sale_date=date(2026, 8, 25),
            buyer_name="Organically Grown Company",
            quantity=13400,
            quantity_unit="lb",
            invoice_number="INV-2026-0912",
            bill_of_lading="BOL-77120",
            organic_on_invoice=True,
        )
        defaults.update(kw)
        return SalesRecord.objects.create(**defaults)

    def _picked(self, season):
        ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.HARVESTING,
            description="first pick",
            date=timezone.make_aware(datetime(2026, 7, 14)),
            yield_quantity=6200,
            yield_unit="lb",
        )

    def test_a_label_the_operator_typed_is_not_printed_twice(self):
        """The OTCO desk read (2026-09-10) printed "BOL BOL CBF-26--RB-01..03": the operator had
        written the label into the field, and the renderer added its own."""
        season = self._finished_season()
        self._picked(season)
        self._sale(season, bill_of_lading="BOL CBF-26-UT-01..03", invoice_number="Invoice 4471")
        flat = " ".join(self._exhibit_text()[0].split())
        self.assertIn("BOL CBF-26-UT-01..03", flat)
        self.assertIn("Invoice 4471", flat)
        self.assertNotIn("BOL BOL", flat)
        self.assertNotIn("invoice Invoice", flat)

    def _pick(self, season, quantity, unit="lb", day=14):
        ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.HARVESTING,
            description="pick",
            date=timezone.make_aware(datetime(2026, 7, day)),
            yield_quantity=quantity,
            yield_unit=unit,
        )

    def test_the_balance_states_what_no_sale_accounts_for(self):
        """🔴 OTCO desk read (2026-09-10): Part B listed harvests and sales and never subtracted."""
        season = self._finished_season()
        self._pick(season, 6200, unit="lbs", day=14)
        self._pick(season, 3000, unit="lb", day=21)
        self._sale(season, quantity=8000, quantity_unit="lb")
        flat = " ".join(self._exhibit_text()[0].split())
        self.assertIn("Harvested 9,200 lb (2 harvest records)", flat)
        self.assertIn("sold 8,000 lb (1 sale)", flat)
        self.assertIn("1,200 lb harvested is on no sale, pack-out or loss record in Trazo for this lot", flat)

    def test_sales_above_the_harvest_are_flagged(self):
        season = self._finished_season()
        self._pick(season, 6200)
        self._sale(season, quantity=13400, quantity_unit="lb")
        flat = " ".join(self._exhibit_text()[0].split())
        self.assertIn("[REVIEW] Harvested 6,200 lb", flat)
        self.assertIn("sales exceed the recorded harvest by 7,200 lb", flat)

    def test_mixed_units_are_not_summed(self):
        """Bins and pounds: a total across them would be a fabricated number."""
        season = self._finished_season()
        self._pick(season, 40, unit="bins")
        self._sale(season, quantity=13400, quantity_unit="lb")
        flat = " ".join(self._exhibit_text()[0].split())
        # Worded since commit 740a739 (2026-10-17) to name which record carries which unit.
        self.assertIn(
            "Balance not computed: the harvest is recorded in bins and the sales in lb, and Trazo does not convert "
            "between units.",
            flat,
        )
        self.assertNotIn("Harvested 40", flat)

    def test_an_unlabelled_number_still_gets_its_label(self):
        season = self._finished_season()
        self._picked(season)
        self._sale(season, bill_of_lading="77120")
        flat = " ".join(self._exhibit_text()[0].split())
        self.assertIn("BOL 77120", flat)
        self.assertIn("invoice INV-2026-0912", flat)

    def test_the_trail_walks_lot_harvest_storage_and_sale(self):
        season = self._finished_season()
        ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.HARVESTING,
            description="first pick",
            date=timezone.make_aware(datetime(2026, 7, 14)),
            yield_quantity=6200,
            yield_unit="lb",
            storage_location="Cooler 2",
        )
        self._sale(season)
        trail = sample_trail(self.est)
        self.assertEqual(trail.lot_id, "CBF-26-UT-01")
        self.assertEqual(trail.storage_locations, ["Cooler 2"])
        # Thousands separated, like the balance line below it on the same page (2026-09-11).
        self.assertEqual(trail.harvests[0]["quantity"], "6,200 lb")
        self.assertEqual(trail.sales[0]["invoice"], "INV-2026-0912")
        text, _ = self._exhibit_text()
        for needle in (
            "CBF-26-UT-01",
            "2026-07-14",
            "Cooler 2",
            "Organically Grown Company",
            "INV-2026-0912",
            "BOL-77120",
        ):
            self.assertIn(needle, text)
        self.assertIn("organic status on invoice: Yes", text)

    def test_a_voided_sale_is_not_part_of_the_trail(self):
        season = self._finished_season()
        self._sale(season)
        self._sale(season, buyer_name="Voided Buyer Co", voided_at=timezone.now(), void_reason="duplicate entry")
        text, _ = self._exhibit_text()
        self.assertNotIn("Voided Buyer Co", text)
        self.assertIn("Organically Grown Company", text)

    def test_an_unsold_or_open_season_is_never_the_sample(self):
        open_season = self._finished_season()
        open_season.finish_date = None
        open_season.save()
        self._sale(open_season)
        self.assertIsNone(sample_trail(self.est))

    def test_a_missing_lot_id_is_reported_never_placeholdered(self):
        season = self._finished_season(lot_id="")
        self._sale(season)
        trail = sample_trail(self.est)
        self.assertIsNone(trail.lot_id)
        text, _ = self._exhibit_text()
        self.assertIn("Lot ID: none recorded", text)
        self.assertNotIn("LOT —", text)

    def test_the_newest_finished_sold_season_wins(self):
        older = self._finished_season(lot_id="OLD-25")
        older.finish_date = timezone.make_aware(datetime(2025, 8, 1))
        older.save()
        self._sale(older, sale_date=date(2025, 8, 5))
        newer = self._finished_season(lot_id="NEW-26")
        self._sale(newer)
        self.assertEqual(sample_trail(self.est).lot_id, "NEW-26")


class OneSaleTracedTests(_ExhibitBase):
    """Part B2: one sale of the sample season walked back to the inputs, by the same
    `trace_sale` the operation runs on screen. Part B stops at the sale; an inspector does not."""

    _sale = SampleTrailTests._sale
    _picked = SampleTrailTests._picked

    def test_a_typed_label_is_not_printed_twice_in_b2_either(self):
        season = self._finished_season()
        self._picked(season)
        self._sale(season, bill_of_lading="BOL CBF-26-UT-01..03", invoice_number="Invoice 4471")
        text = " ".join(self._exhibit_text()[0].split())
        b2 = text[text.index("Part B2") :]
        self.assertIn("BOL CBF-26-UT-01..03", b2)
        self.assertNotIn("BOL BOL", b2)
        self.assertNotIn("invoice Invoice", b2)

    def test_the_sale_is_walked_to_its_pick_and_every_input(self):
        from history.models import ChemicalEvent

        season = self._finished_season()
        pick = ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.HARVESTING,
            description="pick",
            date=timezone.make_aware(datetime(2026, 7, 14)),
            yield_quantity=13400,
            yield_unit="lb",
            block_id="UT",
        )
        ProductionEvent.objects.filter(pk=pick.pk).update(harvest_lot_code="BLU-UT-20260714")
        sale = self._sale(season, organic_label_category="organic")
        sale.harvest_events.set([pick])
        ChemicalEvent.objects.create(
            history=season,
            description="spinosad",
            date=timezone.make_aware(datetime(2026, 6, 2)),
            commercial_name="Entrust SC",
            supplier_name="Wilbur-Ellis",
            purchase_invoice="WE-4471",
            chemical_lot_number="",
        )
        flat = " ".join(self._exhibit_text()[0].split())
        self.assertIn("Part B2: One sale traced back to the inputs applied", flat)
        self.assertIn("Pick named on the sale: BLU-UT-20260714", flat)
        self.assertIn("Entrust SC · supplier Wilbur-Ellis · invoice WE-4471 · lot not recorded", flat)
        # Missing links are stated in the certifier's words, never as a verdict.
        self.assertIn("2026-06-02 Entrust SC: no supplier lot number recorded.", flat)
        self.assertIn("2026-06-02 Entrust SC: no purchase receipt file attached.", flat)
        self.assertIn("No invoice, bill of lading or pack-out file is attached to the sale", flat)
        self.assertNotIn("Pick named on the sale: none", flat)

    def test_an_organic_sale_is_traced_ahead_of_a_newer_conventional_one(self):
        season = self._finished_season()
        self._picked(season)
        self._sale(season, invoice_number="ORG-1", sale_date=date(2026, 8, 20))
        self._sale(season, invoice_number="BUF-9", sale_date=date(2026, 8, 30), organic_on_invoice=False)
        text = " ".join(self._exhibit_text()[0].split())
        b2 = text[text.index("Part B2") :]
        self.assertIn("invoice ORG-1", b2)
        self.assertNotIn("invoice BUF-9", b2[: b2.index("Inputs applied")])

    def test_an_unlinked_sale_says_so(self):
        season = self._finished_season()
        self._picked(season)
        self._sale(season)
        flat = " ".join(self._exhibit_text()[0].split())
        self.assertIn("Pick named on the sale: none. The season's picks are listed in Part B.", flat)
        self.assertIn("The sale does not name the harvest pick it came from.", flat)

    def test_no_sale_means_no_part_b2(self):
        text, _ = self._exhibit_text()
        self.assertIn("No finished season with a recorded sale", text)
        self.assertNotIn("Part B2", text)
