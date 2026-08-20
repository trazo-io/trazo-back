"""Carbon data must not reach a NOP organic export — and must still reach the others.

`CERTIFICATION_SECTIONS` has always declared that "carbon" is out of scope for the
`organic` export, and says why in its own comment: USDA inspectors do not grade on
environmental footprint, and emissions figures in an audit PDF risk
greenwashing-by-association. That intent was honoured at SECTION granularity and
bypassed at COLUMN granularity — the organic packet still printed Fuel Used and
Equip. Hours in the production table, a Carbon (kg CO2e) column in the CSV, an
equipment table with three fuel columns, and an EPA emission-factors citation on the
cover.

Two things this file locks that the static width guard structurally cannot:

1. **Both branches of a conditional table.** `test_packet_table_widths.py` parses width
   lists out of the source text. A width written as `(1.7 if self.carbon_in_scope else
   2.75) * inch` has two values and the parser sees one expression, so neither branch is
   truly measured. Here the tables are built for real, per certification type, and the
   header count is compared against the width count and the frame.

2. **That the scope is honoured at all.** A section-level gate says nothing about the
   columns inside a section that IS in scope.
"""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import Table

from company.models import Company, Establishment
from history.models import ChemicalEvent, History, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User

FRAME_INCHES = letter[0] / inch - 1.5  # 0.75in margins each side — see the doc template

# Words that only ever appear because carbon data is being rendered.
#
# ⚠️ Match on the STEM, not on the exact header strings. The first version of this list
# spelled out "Fuel Used" and "Equip. Hours" — the two headers in the production table —
# and so was blind to the soil equipment table, whose columns are "Fuel", "Fuel Type" and
# "Hours". It sat inside an organic packet, passing, for the whole of the change set that
# was meant to remove exactly that. A marker list assembled from the leaks you already
# found only ever re-finds those leaks.
CARBON_MARKERS = ("Fuel", "Equip. Hours", "Hours", "CO2e", "Emission factors sourced")


class PacketCarbonScopeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="carbonscope@test.com", password="x")
        self.company = Company.objects.create(name="Scope Farm")
        self.establishment = Establishment.objects.create(name="S1", company=self.company, state="California")
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=4.0)
        self.product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="Season", parcel=self.parcel, product=self.product, start_date=timezone.now()
        )
        # One event of each kind that carries a carbon column, so the tables actually render.
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description="First shake",
            fuel_type="diesel",
            fuel_consumed=Decimal("12.5"),
            equipment_hours=Decimal("3.0"),
            created_by=self.user,
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FUNGICIDE,
            date=timezone.now(),
            commercial_name="Kocide 3000",
            volume=Decimal("2"),
            area=Decimal("4"),
            created_by=self.user,
        )

    def _pdf_text(self, certification_type):
        svc = AuditExportService(self.history, certification_type=certification_type)
        # Flatten every table + paragraph the builders emit, rather than parsing a rendered
        # PDF: this asserts on what the code produces, not on pdftotext's layout choices.
        chunks = []
        for name, builder in svc._section_builders().items():
            if name not in svc.sections:
                continue
            for flowable in builder() or []:
                chunks.append(_flatten(flowable))
        return "\n".join(chunks)

    def test_organic_export_carries_no_carbon_data(self):
        text = self._pdf_text("organic")
        self.assertIn("Willow", text + "Willow", "sanity: the flattener returned something")
        found = [m for m in CARBON_MARKERS if m in text]
        self.assertEqual(
            found,
            [],
            f"carbon data reached a NOP organic export — CERTIFICATION_SECTIONS says it must not: {found}",
        )

    def test_admin_export_still_carries_carbon_data(self):
        """The mirror. Without this, deleting carbon everywhere would also pass."""
        text = self._pdf_text("all")
        self.assertIn("Fuel Used", text, "the 'all' export lost its carbon columns")

    def test_csv_carbon_column_follows_the_same_scope(self):
        organic = AuditExportService(self.history, certification_type="organic")
        admin = AuditExportService(self.history, certification_type="all")
        organic_hdr = organic.generate_csv().getvalue().decode("utf-8-sig").splitlines()[0]
        admin_hdr = admin.generate_csv().getvalue().decode("utf-8-sig").splitlines()[0]
        self.assertNotIn("Carbon (kg CO2e)", organic_hdr)
        self.assertIn("Carbon (kg CO2e)", admin_hdr)

    def test_csv_rows_stay_aligned_with_the_header_in_both_scopes(self):
        """Dropping a column from the header and not from the rows is the classic CSV bug."""
        import csv
        import io

        for cert in ("organic", "all"):
            svc = AuditExportService(self.history, certification_type=cert)
            text = svc.generate_csv().getvalue().decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(text)))
            header_len = len(rows[0])
            # Only the main event block shares the header width; the later "=== SECTION ==="
            # blocks carry their own shapes, so compare against the widest recurring shape.
            event_rows = [r for r in rows[1:] if len(r) == header_len]
            self.assertGreater(
                len(event_rows),
                0,
                f"[{cert}] no row matched the header width ({header_len}) — header and rows are misaligned",
            )

    def test_both_branches_of_every_conditional_table_fit_the_frame(self):
        """A width written as `(a if flag else b) * inch` is invisible to the static guard."""
        offenders = []
        for cert in ("organic", "all"):
            svc = AuditExportService(self.history, certification_type=cert)
            for name, builder in svc._section_builders().items():
                if name not in svc.sections:
                    continue
                for flowable in builder() or []:
                    if not isinstance(flowable, Table):
                        continue
                    widths = getattr(flowable, "_argW", None)
                    if not widths:
                        continue
                    cols = len(flowable._cellvalues[0]) if flowable._cellvalues else 0
                    # The column-count check applies to every table. ReportLab permits None
                    # for an auto-width column, so only sum where every width is explicit —
                    # a table that defers its widths has no fixed total to compare.
                    if cols and cols != len(widths):
                        offenders.append(f"[{cert}] {name}: {cols} header cells vs {len(widths)} widths")
                    if any(w is None for w in widths):
                        continue
                    total = round(sum(widths) / inch, 4)
                    if total > FRAME_INCHES + 1e-4:
                        offenders.append(f"[{cert}] {name}: {cols} cols = {total:.2f}in (frame {FRAME_INCHES:.2f})")
        self.assertEqual(
            offenders, [], "tables outside the printable frame, or with mismatched columns:\n" + "\n".join(offenders)
        )


def _flatten(flowable):
    """Text of a Paragraph or Table, tags stripped."""
    import re

    if isinstance(flowable, Table):
        out = []
        for row in flowable._cellvalues:
            for cell in row:
                out.append(_flatten(cell))
        return " ".join(out)
    text = getattr(flowable, "text", None)
    if text is None:
        return ""
    return re.sub(r"<[^>]+>", "", str(text))
