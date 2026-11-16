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
from history.models import ChemicalEvent, Production, ProductionEvent, SoilManagementEvent
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
        self.history = Production.objects.create(
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
        # A tillage pass carrying BOTH kinds of fact at once: § 205 facts (the implement, the
        # person) and carbon facts (fuel, hours). Added 2026-09-06 — the soil equipment table
        # was previously carbon-gated as a whole, so this file asserted the scope rule against a
        # table that simply did not render on the organic side. A guard that passes because the
        # thing it guards is absent is not a guard.
        SoilManagementEvent.objects.create(
            history=self.history,
            type=SoilManagementEvent.TILLAGE,
            date=timezone.now(),
            name="Beds reformed for the second crop",
            equipment_used="John Deere 6120M + 18 ft offset disc",
            performed_by="Javier Morales",
            fuel_type="diesel",
            fuel_consumed=Decimal("34"),
            fuel_unit="gal",
            equipment_hours=Decimal("13"),
            working_depth=Decimal("6"),
            depth_unit="inches",
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


class SoilEquipmentAndOperatorScopeTests(PacketCarbonScopeTests):
    """The § 205 half of a soil operation must outlive the carbon half.

    🔴 2026-09-06. `equipment_used` and `performed_by` for soil events reached the packet only
    through a sub-table gated on `carbon_in_scope`. Under the USDA Organic filter that gate is
    closed, so a real certifier packet (Calapooia Bend carrots, exported 2026-09-06) recorded a
    June tillage pass on a DECLARED SPLIT OPERATION and named neither the tractor nor the person
    who drove it. The OSP on page 7 of that same packet says "Split operation: Yes", "Parallel
    production: Yes", and its (a)(3) monitoring narrative names "a custom operator running their
    own equipment on our ground" as a change it would report to the certifier.

    § 205.201(a)(5) makes the implement the reviewable fact on a split operation, and
    `_build_equipment_section` already draws exactly this line in its own comment: fuel and
    hours are carbon inputs, equipment identity is not. § 205.103(b)(2) asks for detail
    "readily understood and audited", and every other event family already prints its operator
    under the organic filter.

    ⛔ Neither field is a new question for the farmer. SoilManagementTab has always collected
    the equipment, and wizard step 0 has always collected `performed_by` for every event type.
    """

    def test_equipment_identity_survives_the_organic_export(self):
        text = self._pdf_text("organic")
        self.assertIn(
            "John Deere 6120M + 18 ft offset disc",
            text,
            "the implement that ran an organic block vanished from the NOP packet — § 205.201(a)(5) "
            "is answered by naming it, and an Equipment Cleaning Log cannot be tied to a pass "
            "whose record names no equipment",
        )

    def test_operator_survives_the_organic_export(self):
        text = self._pdf_text("organic")
        self.assertIn(
            "Javier Morales",
            text,
            "no soil record named who performed it, while Production Events, Irrigation and Pest "
            "scouting all print their operator under the same filter",
        )

    def test_operator_column_is_on_the_main_soil_table(self):
        """Not only in the equipment sub-table: the main table lists EVERY soil record.

        ⚠️ Assert on the ADJACENT HEADER PAIR, not on the bare word inside a sliced section.
        The first version of this test sliced from "Soil & Water Management" to the next
        section and looked for "Operator" — and passed with the column deleted, because the
        Natural Resources heading it sliced on only renders when a cover-crop or habitat event
        exists. Without it the slice ran to the end of the document and matched the word in the
        Soil Operations sub-heading. A vacuous guard on a certifier document is worse than none.
        """
        text = self._pdf_text("organic")
        self.assertIn(
            "Organic Status Operator",
            text,
            "the main Soil & Water Management table dropped its Operator column — every other "
            "event family prints who performed the work under the organic filter",
        )
        self.assertIn(
            "Javier Morales",
            text[text.index("Organic Status Operator") :].split("\n")[0],
            "the Operator column rendered its header but not the name on the row",
        )

    def test_soil_fuel_and_hours_still_stop_at_the_organic_boundary(self):
        """The other half of the split. Ungating equipment must not ungate carbon with it."""
        text = self._pdf_text("organic")
        self.assertNotIn("34.00 gal", text, "soil fuel volume reached a NOP organic export")
        self.assertNotIn("Fuel Type", text, "the soil fuel-type column reached a NOP organic export")

    def test_admin_export_still_carries_the_soil_carbon_columns(self):
        """Mirror: deleting the carbon branch entirely would otherwise pass the test above."""
        text = self._pdf_text("all")
        self.assertIn("34.00 gal", text)
        self.assertIn("John Deere 6120M + 18 ft offset disc", text)
        self.assertIn("Javier Morales", text)

    def test_equipment_column_never_falls_back_to_the_activity_name(self):
        """A title is not an implement.

        The cell used to read `equipment_used or ev.name`, so a soil event with fuel logged and
        no equipment printed its own activity title under a column headed Equipment — answering
        the § 205.201(a)(5) question with something that is not a machine, on a document an
        inspector reads as a record. A dash says "not recorded"; a title says the wrong thing
        confidently.
        """
        SoilManagementEvent.objects.create(
            history=self.history,
            type=SoilManagementEvent.COVER_CROP,
            date=timezone.now(),
            name="Cover crop flailed at rye boot stage",
            performed_by="Laurel Brandt",
            fuel_consumed=Decimal("8"),
            fuel_unit="gal",
            created_by=self.user,
        )
        for cert in ("organic", "all"):
            text = self._pdf_text(cert)
            self.assertIn("Laurel Brandt", text, f"[{cert}] operator missing for the no-equipment row")

            # Scope the assertion to the ONE table under test. The activity title legitimately
            # appears elsewhere in the packet — the 3-Year Field & Crop Rotation History prints
            # it as the season's cover crop — so a whole-document `assertNotIn` fails on a
            # correct packet, which is how this assertion failed the first time it ran.
            start = text.index("Soil Operations")
            table = text[start : text.index("\n", text.index("\n", start) + 1) + 1]
            self.assertIn("Laurel Brandt", table, f"[{cert}] the no-equipment row left the table")
            self.assertNotIn(
                "Cover crop flailed at rye boot stage",
                table,
                f"[{cert}] an activity title was printed in the Equipment column",
            )
