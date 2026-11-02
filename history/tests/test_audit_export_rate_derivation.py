"""
Per-area rates in the audit exports.

WHY (2026-08-01): the Input Application Log printed "340.00 oz" and stopped. But a pesticide
label maximum, a manure-loading limit and a nitrogen budget are all written PER UNIT AREA
("4-10 fl oz/acre", "29 fl oz/acre/season"), so the rate — not the total — is the number a
reviewer checks an application against. Both exports left that division to the reader.

The value is derivable from data already on the event, so there was never a reason to omit it.
This pins three things that are easy to regress:

  1. The arithmetic and the unit string ("oz/acre", not "oz/acres").
  2. That it reaches BOTH exports. The PDF and the CSV are read by the same certifier, and
     they had already drifted once — the CSV was still printing the raw enum "air_blast" after
     the PDF was fixed.
  3. That the same treatment reaches SOIL amendments, not just chemicals. Compost tonnage per
     acre and kg N per acre are what 7 CFR 205.203 and the California ILRP nitrogen summary
     actually ask for.
"""

import csv
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, History, SoilManagementEvent
from history.services.audit_export_service import AuditExportService, _rate_per_area
from product.models import Parcel, Product
from users.models import User


class RatePerAreaHelperTests(TestCase):
    def test_derives_rate_and_singularises_the_area_unit(self):
        self.assertEqual(_rate_per_area(Decimal("340"), Decimal("42.5"), "oz", "acres"), "8.00 oz/acre")

    def test_handles_a_hectare_denominated_application(self):
        self.assertEqual(_rate_per_area(Decimal("150"), Decimal("15"), "kg", "ha"), "10.00 kg/ha")

    def test_returns_none_rather_than_dividing_by_zero(self):
        self.assertIsNone(_rate_per_area(Decimal("10"), Decimal("0"), "oz", "acres"))

    def test_returns_none_when_either_side_is_missing(self):
        self.assertIsNone(_rate_per_area(None, Decimal("42.5"), "oz", "acres"))
        self.assertIsNone(_rate_per_area(Decimal("340"), None, "oz", "acres"))

    def test_returns_none_without_an_area_unit(self):
        """A bare number with no unit cannot be presented as a rate."""
        self.assertIsNone(_rate_per_area(Decimal("340"), Decimal("42.5"), "oz", ""))

    def test_survives_a_non_numeric_value(self):
        self.assertIsNone(_rate_per_area("about ten", Decimal("42.5"), "oz", "acres"))


class RateReachesBothExportsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="rate@test.com", password="x")
        self.company = Company.objects.create(name="Rate Farm")
        self.establishment = Establishment.objects.create(name="RF1", company=self.company)
        self.parcel = Parcel.objects.create(name="Block 1", establishment=self.establishment, area=42.5)
        self.product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="Rate Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            volume_numeric=Decimal("340.00"),
            volume_unit="oz",
            area_numeric=Decimal("42.50"),
            area_unit="acres",
            date=timezone.now(),
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            type="OM",
            amendment_type="compost",
            amendment_amount_numeric=Decimal("170.00"),
            amendment_amount_unit="tons",
            area_covered=Decimal("42.50"),
            area_unit="acres",
            date=timezone.now(),
        )

    def _pdf_text(self):
        """Extracted PDF text with whitespace collapsed.

        A table cell wraps, so the rate reaches the page as "340.00 oz\n(8.00\noz/acre)".
        Collapsing whitespace asserts on the VALUE rather than on where ReportLab happened to
        break the line.
        """
        import re

        from pdfminer.high_level import extract_text

        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(
            strict_photos=False, strict_ofpp=False
        )
        data = buf.read() if hasattr(buf, "read") else buf
        return re.sub(r"\s+", " ", extract_text(io.BytesIO(data)))

    def _csv_rows(self):
        raw = AuditExportService(self.history, certification_type="organic").generate_csv().getvalue()
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
        return list(csv.reader(io.StringIO(text)))

    @staticmethod
    def _event_rows(rows):
        """Only the event block.

        The CSV appends further sections after the events ("=== ADDITIONAL FARMER-RECORDED
        DATA ==="), which are deliberately narrower than the header. Selecting on a leading
        ISO date keeps the alignment assertion pointed at the rows it is about.
        """
        import re

        # The event block ends at the first blank row; later sections (the National List classification
        # among them) also lead with a date and must not be read as events.
        block = []
        for r in rows[1:]:
            if not r or r[0].startswith("==="):
                break
            block.append(r)
        return [r for r in block if re.match(r"^\d{4}-\d{2}-\d{2}", r[0])]

    def test_csv_has_a_rate_column_and_stays_aligned(self):
        rows = self._csv_rows()
        header = rows[0]
        self.assertIn("Rate", header)
        width = len(header)
        data_rows = self._event_rows(rows)
        self.assertTrue(data_rows, "expected event rows in the CSV")
        for row in data_rows:
            self.assertEqual(
                len(row),
                width,
                "adding the Rate column must not misalign a row against the header",
            )

    def test_csv_carries_the_chemical_and_amendment_rates(self):
        rows = self._csv_rows()
        rate_idx = rows[0].index("Rate")
        rates = {r[rate_idx] for r in self._event_rows(rows)}
        self.assertIn("8.00 oz/acre", rates)
        self.assertIn("4.00 tons/acre", rates)

    def test_pdf_prints_the_chemical_rate_beside_the_total(self):
        text = self._pdf_text()
        self.assertIn("8.00 oz/acre", text, "Input Application Log must show the per-acre rate")

    def test_pdf_prints_the_amendment_rate(self):
        text = self._pdf_text()
        self.assertIn("4.00 tons/acre", text, "amendment tonnage must carry a per-acre rate")
