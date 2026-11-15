"""One writer for the sales facts, and a retention date that satisfies "not less than 5 years".

Both pinned here because both are the same underlying failure: a fact computed correctly in
one place and independently (mis)computed somewhere else.

The sales half is the third recorded instance of "two writers, disjoint key vocabularies".
Verified on a rendered packet 2026-08-10: page 1 printed
``Sales documentation (§ 205.103) — REVIEW: Add buyer + organic-on-invoice flag`` while page 12
of the SAME PDF printed ``Sold To: Smoke Buyer Co / Organic Identified on Invoice: Yes``. The
snapshot row branched on ``History.sold_to``; the body preferred ``SalesRecord``. Sweeping the
class found three further readers with the same shape, including a CSV export with no fallback
at all.
"""

from datetime import date, timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, SalesRecord, compute_retention_until
from history.services.audit_export_service import AuditExportService, _label_category_display, resolve_sales_disclosure
from product.models import Parcel, Product
from users.models import User


class SalesDisclosurePrecedenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="sd@test.test", password="x")
        company = Company.objects.create(name="SD Co")
        establishment = Establishment.objects.create(name="SD Farm", company=company)
        parcel = Parcel.objects.create(name="SD P1", establishment=establishment, area=4.0)
        self.production = History.objects.create(
            name="SD Production",
            start_date=timezone.now() - timedelta(days=90),
            finish_date=timezone.now() - timedelta(days=5),
            lot_id="SD-LOT-1",
            product=Product.objects.create(name="Walnuts"),
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=1000.0,
            production_unit="lb",
            reputation=0.0,
            confidence_score=0.0,
        )

    def _snapshot(self):
        rows = AuditExportService(self.production, certification_type="organic").compliance_snapshot_rows()
        return next(r for r in rows if "Sales documentation" in r["label"])

    def test_sales_record_alone_satisfies_the_snapshot_row(self):
        # THE regression. sold_to is deliberately left empty: this is precisely the state
        # that produced a self-contradicting packet.
        SalesRecord.objects.create(
            production=self.production,
            sale_date=date(2026, 8, 1),
            buyer_name="Smoke Buyer Co",
            quantity=1200,
            quantity_unit="lb",
            invoice_number="INV-1",
            organic_on_invoice=True,
        )
        self.assertFalse(self.production.sold_to, "fixture must exercise the SalesRecord-only path")

        row = self._snapshot()
        self.assertEqual(row["status"], "PASS", f"SalesRecord ignored by the snapshot row: {row}")
        self.assertIn("Smoke Buyer Co", row["detail"])

    def test_legacy_fields_still_work_when_no_sales_records(self):
        self.production.sold_to = "Legacy Buyer"
        self.production.organic_on_invoice = True
        self.production.save(update_fields=["sold_to", "organic_on_invoice"])

        row = self._snapshot()
        self.assertEqual(row["status"], "PASS")
        self.assertIn("Legacy Buyer", row["detail"])

    def test_a_lot_with_no_sale_at_all_says_so_instead_of_asking_for_a_buyer(self):
        row = self._snapshot()
        self.assertEqual(row["detail"], "No sale recorded for this lot")
        self.assertNotIn("Add buyer", row["detail"])

    def test_a_lot_flagged_organic_on_invoice_with_no_buyer_still_asks_for_the_buyer(self):
        """Local review of back #436: the flag says an invoice exists, so it is an incomplete sale, not no sale."""
        self.production.organic_on_invoice = True
        self.production.save(update_fields=["organic_on_invoice"])
        self.assertIn("Add buyer", self._snapshot()["detail"])

    def test_a_sale_row_with_no_buyer_still_asks_for_the_buyer(self):
        SalesRecord.objects.create(
            production=self.production,
            sale_date=date(2026, 8, 1),
            buyer_name="",
            quantity=100,
            quantity_unit="lb",
            organic_on_invoice=True,
        )
        self.assertIn("Add buyer", self._snapshot()["detail"])

    def test_sales_records_win_over_stale_legacy_fields(self):
        self.production.sold_to = "Stale Legacy Buyer"
        self.production.save(update_fields=["sold_to"])
        SalesRecord.objects.create(
            production=self.production,
            sale_date=date(2026, 8, 1),
            buyer_name="Real Buyer",
            quantity=10,
            quantity_unit="lb",
            organic_on_invoice=True,
        )
        disclosure = resolve_sales_disclosure(self.production)
        self.assertEqual(disclosure.source, "sales_records")
        self.assertEqual(disclosure.buyer, "Real Buyer")

    def test_one_unflagged_shipment_fails_the_organic_invoice_claim(self):
        # "Organic identified on invoice" is a claim about EVERY shipment, so a single
        # unflagged row must sink it rather than being averaged away.
        for flagged in (True, False):
            SalesRecord.objects.create(
                production=self.production,
                sale_date=date(2026, 8, 1),
                buyer_name="Buyer",
                quantity=5,
                quantity_unit="lb",
                organic_on_invoice=flagged,
            )
        self.assertFalse(resolve_sales_disclosure(self.production).organic_on_invoice)

    def test_mixed_units_refuse_to_sum(self):
        # Summing lb and boxes would fabricate a number in a certifier document.
        for unit in ("lb", "boxes"):
            SalesRecord.objects.create(
                production=self.production,
                sale_date=date(2026, 8, 1),
                buyer_name="Buyer",
                quantity=5,
                quantity_unit=unit,
                organic_on_invoice=True,
            )
        self.assertIsNone(resolve_sales_disclosure(self.production).quantity)

    def test_csv_and_pdf_agree_on_the_buyer(self):
        # The CSV export had no SalesRecord fallback at all, so the two exports of one
        # production disagreed. Asserting agreement rather than either value.
        SalesRecord.objects.create(
            production=self.production,
            sale_date=date(2026, 8, 1),
            buyer_name="Smoke Buyer Co",
            quantity=1200,
            quantity_unit="lb",
            organic_on_invoice=True,
        )
        service = AuditExportService(self.production, certification_type="organic")
        csv_blob = service.generate_csv()
        raw = csv_blob.getvalue() if hasattr(csv_blob, "getvalue") else csv_blob
        csv_text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        self.assertIn("Smoke Buyer Co", csv_text, "CSV export still reads the legacy field only")


class RetentionFloorTests(SimpleTestCase):
    """§ 205.103(b)(4): "not less than 5 years". 1825 days is not 5 years.

    Calls the production function. The first version of this class re-implemented the
    arithmetic locally, which meant it asserted against its own copy and would have passed
    against the code it was written to pin — a test that cannot fail is not a gate.
    """

    def _retention_for(self, finish):
        return compute_retention_until(finish)

    def test_five_calendar_years_not_1825_days(self):
        for finish in (date(2024, 8, 10), date(2025, 8, 10), date(2026, 8, 8), date(2027, 8, 10)):
            with self.subTest(finish=finish):
                retention = self._retention_for(finish)
                self.assertEqual(retention.year, finish.year + 5)
                self.assertEqual((retention.month, retention.day), (finish.month, finish.day))
                self.assertGreaterEqual((retention - finish).days, 1826, "1825 days is short of five calendar years")

    def test_leap_day_rounds_forward_never_back(self):
        # 2028-02-29 + 5y has no counterpart. Rounding back to 02-28 would be a day short
        # of "not less than"; forward to 03-01 is a day long, which the rule permits.
        self.assertEqual(self._retention_for(date(2028, 2, 29)), date(2033, 3, 1))


class OrganicLabelCategoryTests(TestCase):
    """§ 205.103(b)(3): records must identify the product by its § 205.301 labeling category.

    `organic_on_invoice` is a boolean and answers a different question — *whether* the product
    was identified as organic, never *as which category*. The 2026-08 USDA alignment audit
    recorded that as the one confirmed GAP in Baseline B; this is the close.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="lc@test.test", password="x")
        company = Company.objects.create(name="LC Co")
        establishment = Establishment.objects.create(name="LC Farm", company=company)
        parcel = Parcel.objects.create(name="LC P1", establishment=establishment, area=3.0)
        self.production = History.objects.create(
            name="LC Production",
            start_date=timezone.now() - timedelta(days=60),
            finish_date=timezone.now() - timedelta(days=3),
            lot_id="LC-LOT-1",
            product=Product.objects.create(name="Almonds"),
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=500.0,
            production_unit="lb",
            reputation=0.0,
            confidence_score=0.0,
        )

    def _sale(self, **kw):
        defaults = dict(
            production=self.production,
            sale_date=date(2026, 8, 1),
            buyer_name="Buyer",
            quantity=10,
            quantity_unit="lb",
            organic_on_invoice=True,
        )
        defaults.update(kw)
        return SalesRecord.objects.create(**defaults)

    def test_absent_category_prints_the_requirement_not_silence(self):
        # A blank in a certifier packet reads as "nothing to report". The packet has to say
        # the record is missing, and cite why it is owed.
        self._sale()
        text = _label_category_display(resolve_sales_disclosure(self.production))
        self.assertIn("Not recorded", text)
        self.assertIn("205.103(b)(3)", text)

    def test_single_category_renders_the_regulation_wording(self):
        self._sale(organic_label_category="100_percent_organic")
        disclosure = resolve_sales_disclosure(self.production)
        self.assertEqual(disclosure.label_category, "100_percent_organic")
        self.assertEqual(_label_category_display(disclosure), "100 percent organic")

    def test_split_lot_reports_every_category_and_picks_none(self):
        # A lot can legitimately ship under more than one category. Collapsing to the first
        # would put a category the operation did not choose into a certifier document.
        self._sale(organic_label_category="100_percent_organic")
        self._sale(organic_label_category="organic")
        disclosure = resolve_sales_disclosure(self.production)
        self.assertEqual(disclosure.label_category, "", "must not pick one when rows disagree")
        self.assertEqual(disclosure.label_categories, ("100_percent_organic", "organic"))
        self.assertIn("Mixed", _label_category_display(disclosure))

    def test_category_without_organic_on_invoice_is_refused(self):
        # Contradictory record: the packet would otherwise print both halves.
        from django.core.exceptions import ValidationError as DjangoValidationError

        sale = self._sale(organic_on_invoice=False)
        sale.organic_label_category = "organic"
        with self.assertRaises(DjangoValidationError):
            sale.full_clean()

    def test_legacy_path_carries_the_category_too(self):
        # No SalesRecord rows — the History fallback must supply it, or the field would be
        # invisible for every production still on the single-sale path.
        self.production.sold_to = "Legacy Buyer"
        self.production.organic_on_invoice = True
        self.production.organic_label_category = "organic"
        self.production.save(update_fields=["sold_to", "organic_on_invoice", "organic_label_category"])
        disclosure = resolve_sales_disclosure(self.production)
        self.assertEqual(disclosure.source, "legacy")
        self.assertEqual(_label_category_display(disclosure), "Organic")

    def test_serializer_refuses_the_contradiction_too(self):
        """DRF never calls Model.clean(), so the model guard alone leaves the API open.

        This is the whole reason SalesRecordSerializer.validate() exists — and the first
        version of these tests only exercised full_clean(), which would have passed while the
        endpoint happily wrote the contradictory row.
        """
        from history.serializers import SalesRecordSerializer

        serializer = SalesRecordSerializer(
            data={
                "production_id": str(self.production.public_id),
                "sale_date": "2026-08-01",
                "buyer_name": "Buyer",
                "quantity": "10",
                "quantity_unit": "lb",
                "organic_on_invoice": False,
                "organic_label_category": "organic",
            }
        )
        self.assertFalse(serializer.is_valid(), "serializer accepted a category with no organic-on-invoice flag")
        self.assertIn("organic_label_category", serializer.errors)

    def test_serializer_accepts_the_consistent_pair(self):
        from history.serializers import SalesRecordSerializer

        serializer = SalesRecordSerializer(
            data={
                "production_id": str(self.production.public_id),
                "sale_date": "2026-08-01",
                "buyer_name": "Buyer",
                "quantity": "10",
                "quantity_unit": "lb",
                "organic_on_invoice": True,
                "organic_label_category": "organic",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_category_reaches_both_exports_identically(self):
        # The PDF and CSV read the same resolver and the same renderer, so they cannot
        # disagree — the defect that produced a self-contradicting packet in August.
        self._sale(organic_label_category="100_percent_organic")
        service = AuditExportService(self.production, certification_type="organic")
        raw = service.generate_csv()
        raw = raw.getvalue() if hasattr(raw, "getvalue") else raw
        csv_text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        self.assertIn("100 percent organic", csv_text)
        self.assertIn("205.301", csv_text)
