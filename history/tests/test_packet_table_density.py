"""A table that renders but says nothing is a defect, and it is measurable.

WHAT THIS GENERALISES. The Buffer Use row in the combined harvest table was a lot code and TEN
dashes — it passed every existing guard (widths fine, columns aligned, section present, field
"reaches the packet") and was still worthless to the reader it was written for. I found it by
reading the rendered PDF as an inspector would. That does not scale, and it does not survive me.

The judgment "is this layout good for a certifier" cannot be automated. But the specific
failure underneath it can: a row whose cells are overwhelmingly empty is not a formatting
preference, it is a row that costs an inspector attention and returns nothing. Same for a table
whose every data row is mostly blank — that is a table selecting the wrong events, which is
exactly what the BU row was.

WHAT THIS DELIBERATELY DOES NOT DO. It does not assert a density floor on a table that is
legitimately sparse for one event (a harvest with no brix reading is fine). It fires on the
AGGREGATE: when a whole table averages below the floor, the table is asking questions its rows
cannot answer, and the fix is to select different rows or print a different table.
"""

import io
import re

from django.test import TestCase
from django.utils import timezone

from reportlab.platypus import Table

from company.models import Company, Establishment
from history.models import History, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User

# Below this, a table's data rows are mostly dashes and it is not earning its space.
MIN_FILLED_RATIO = 0.30
EMPTY = {"", "—", "-", "N/A", "None", "null"}


def _cell_text(cell):
    if hasattr(cell, "text"):
        return re.sub(r"<[^>]+>", "", str(cell.text)).strip()
    return str(cell).strip() if cell is not None else ""


class PacketTableDensityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="density@test.com", password="x")
        company = Company.objects.create(name="Density Co")
        est = Establishment.objects.create(name="D1", company=company, state="California")
        parcel = Parcel.objects.create(name="Block 1", establishment=est, area=10)
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="Density Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        # A realistic mix, including the subtypes whose rows were thin.
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description="First shake",
            harvest_lot_code="LOT-D-1",
            # A REALISTIC harvest, not a minimal one. The first fixture filled four fields, so
            # the density check measured the FIXTURE's sparseness rather than the packet's
            # design — a guard calibrated against unrealistic data reports the wrong thing in
            # both directions.
            variety="Chandler",
            block_id="Block A",
            amount_determination="scale",
            harvest_quality_grade="us_no_1",
            storage_location="Cold store 2",
            area_covered=10,
            area_unit="acres",
            # harvest_method persists through extra_data, not a column.
            extra_data={"harvest_method": "mechanical_shake"},
            yield_quantity=1200,
            yield_unit="kg",
            harvest_destination="handler",
            created_by=self.user,
        )
        ProductionEvent.objects.create(
            history=self.history,
            type="TP",
            date=timezone.now(),
            description="Load out",
            harvest_lot_code="LOT-D-1",
            harvest_destination="handler",
            transport_origin="Farm, Chico CA",
            transport_destination_address="Huller, Yuba City CA",
            created_by=self.user,
        )
        ProductionEvent.objects.create(
            history=self.history,
            type="BU",
            date=timezone.now(),
            description="Buffer rows",
            harvest_lot_code="LOT-D-2",
            buffer_disposition="sold_conventional",
            buffer_disposition_quantity="400 lb",
            buffer_disposition_evidence="Tag 1",
            created_by=self.user,
        )

    def _tables(self):
        svc = AuditExportService(self.history, certification_type="organic")
        out = []
        for name, builder in svc._section_builders().items():
            if name not in svc.sections:
                continue
            for flowable in builder() or []:
                if isinstance(flowable, Table) and flowable._cellvalues:
                    out.append((name, flowable))
        return out

    def test_no_table_is_mostly_empty(self):
        """The BU-row defect, expressed as a measurement instead of a reading.

        ⚠️ TWO EXCLUSIONS, both learned the hard way when the first version of this test
        reported six tables and five were artifacts of the fixture rather than defects:

        1. EMPTY-STATE ROWS. A table with no data renders one row reading "No records for this
           production". That row IS mostly blank, and correctly so — it is the empty state, not
           a thin data row. Counting it measured whether the fixture happened to create an
           event of that family, which is a property of the test, not of the packet.

        2. SINGLE-ROW TABLES. One sparse row is a farmer who left optional fields blank — a
           harvest with no brix reading is a legitimate record. The defect being hunted is a
           table SELECTING events it cannot describe, and that only shows as a pattern. Two or
           more rows, all thin, is a pattern; one is a data point.

        Narrowing a guard until it stops crying wolf is not weakening it. A guard that reports
        five false positives gets muted, and then the real sixth goes with it.
        """
        thin = []
        for name, t in self._tables():
            rows = t._cellvalues[1:]  # skip the header
            rows = [r for r in rows if "no records" not in " ".join(_cell_text(c) for c in r).lower()]
            if len(rows) < 2:
                continue
            cells = [c for row in rows for c in row]
            if not cells:
                continue
            filled = sum(1 for c in cells if _cell_text(c) not in EMPTY)
            ratio = filled / len(cells)
            if ratio < MIN_FILLED_RATIO:
                header = " | ".join(_cell_text(c) for c in t._cellvalues[0])[:80]
                thin.append(f"{name}: {ratio:.0%} filled over {len(rows)} row(s) — [{header}]")
        self.assertEqual(
            thin,
            [],
            "these tables render rows that are mostly dashes. A row an inspector cannot read "
            "anything from is not neutral — it costs attention and returns nothing. Either "
            "select different events for the table, or give the facts their own table:\n  " + "\n  ".join(thin),
        )

    def test_the_measurement_is_real(self):
        """Non-vacuity: prove tables were actually found and measured."""
        tables = self._tables()
        self.assertGreater(len(tables), 5, "no tables were inspected — the check is vacuous")
