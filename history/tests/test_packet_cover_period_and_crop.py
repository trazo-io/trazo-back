"""The packet cover must not assert a finished cycle for a crop still in the ground.

TWO DEFECTS, BOTH ON THE COVER LINE
-----------------------------------
1. `end = finish_date or expected_harvest` was printed at THREE sites — this packet's cover,
   and twice in the operation dossier — so an OPEN season rendered exactly like a closed one:

       "Carrot Production — 2026-06-20 to 2026-10-05"

   for a crop still growing, with an end date that had not happened yet. A certifier reads a
   completed cycle and can ask for harvest records against a date the farm has not reached.
   Presenting a projection as a record is the one thing an audit document must never do.

2. The singularizer trimmed a bare trailing "s", which mangled four of the seeded crops — and
   they are the ones this platform actually sells into: the cover said "Blueberrie Production",
   plus "Strawberrie", "Potatoe" and "Tomatoe". English plurals in -ies take -y and -oes take -o.
"""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import Production
from history.services.audit_export_service import AuditExportService, production_period
from product.models import Parcel, Product
from users.models import User


class _Stub:
    def __init__(self, start, finish=None, expected=None):
        self.start_date = start
        self.finish_date = finish
        self.expected_harvest = expected


D = dt_timezone.utc


class ProductionPeriodTests(SimpleTestCase):
    def test_finished_season_reads_as_a_closed_range(self):
        p = _Stub(datetime(2025, 3, 1, tzinfo=D), finish=datetime(2025, 7, 14, tzinfo=D))
        self.assertEqual(production_period(p), "2025-03-01 to 2025-07-14")

    def test_open_season_is_never_shown_as_closed(self):
        """The regression. Fails on `finish_date or expected_harvest`."""
        p = _Stub(datetime(2026, 6, 20, tzinfo=D), expected=datetime(2026, 10, 5, tzinfo=D))
        rendered = production_period(p)
        self.assertIn("in progress", rendered)
        self.assertNotEqual(rendered, "2026-06-20 to 2026-10-05")
        # The projection is still useful to an inspector — it just has to be labelled.
        self.assertIn("expected 2026-10-05", rendered)

    def test_open_season_without_a_projection(self):
        p = _Stub(datetime(2026, 6, 20, tzinfo=D))
        self.assertEqual(production_period(p), "2026-06-20, in progress")

    def test_compact_drops_the_projection_for_narrow_cells(self):
        """The dossier index gives this 2.1in of plain-string cell, which ReportLab will not wrap.

        MEASURED: the long form is 172.5pt at 8pt type against a 151.2pt column, so it would draw
        silently past its cell — the packet-width failure this codebase already has a rule about.
        """
        p = _Stub(datetime(2026, 4, 8, tzinfo=D), expected=datetime(2026, 9, 7, tzinfo=D))
        self.assertEqual(production_period(p, joiner=" – ", compact=True), "2026-04-08, in progress")

    def test_joiner_is_respected(self):
        p = _Stub(datetime(2025, 3, 1, tzinfo=D), finish=datetime(2025, 7, 14, tzinfo=D))
        self.assertEqual(production_period(p, joiner=" – "), "2025-03-01 – 2025-07-14")


class CoverCropLabelTests(TestCase):
    """Renders the real cover, because the singularizer only exists on that line."""

    def _packet_text_for(self, crop_name, slug):
        import io

        from pdfminer.high_level import extract_text

        user = User.objects.create_user(email=f"{slug}@test.com", password="x")
        company = Company.objects.create(name=f"{slug} Co")
        est = Establishment.objects.create(name=f"{slug} Farm", company=company)
        parcel = Parcel.objects.create(name="Block", establishment=est, area=1.0)
        crop = CropType.objects.create(
            name=crop_name,
            slug=slug,
            category="fruit",
            description="d",
            typical_farm_size="10-40 ha",
            growing_season="Mar-Aug",
            harvest_season="Jun",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        history = Production.objects.create(
            parcel=parcel,
            product=Product.objects.create(name=crop_name),
            crop_type=crop,
            operator=user,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=30),
        )
        buffer = AuditExportService(history, certification_type="usda_organic").generate_pdf()
        return extract_text(io.BytesIO(buffer.getvalue() if hasattr(buffer, "getvalue") else buffer))

    def test_ies_plural_becomes_y_not_a_truncated_word(self):
        text = self._packet_text_for("Blueberries", "blueberries-cover")
        self.assertIn("Blueberry Production", text)
        self.assertNotIn("Blueberrie Production", text)

    def test_oes_plural_keeps_its_o(self):
        text = self._packet_text_for("Potatoes", "potatoes-cover")
        self.assertIn("Potato Production", text)
        self.assertNotIn("Potatoe Production", text)

    def test_ordinary_plural_still_trims_one_s(self):
        text = self._packet_text_for("Walnuts", "walnuts-cover")
        self.assertIn("Walnut Production", text)

    def test_words_that_are_not_plurals_are_left_alone(self):
        """'Citrus' and 'Spinach' are not plurals; trimming them would invent a crop."""
        self.assertIn("Citrus Production", self._packet_text_for("Citrus", "citrus-cover"))
        self.assertIn("Spinach Production", self._packet_text_for("Spinach", "spinach-cover"))


class RecordsSpanDisclosureTests(TestCase):
    """The declared period is the headline; when records reach outside it, the cover says so.

    13.5% of a pilot's records sat outside the period the packet printed for them — dormant
    pruning and the seed search weeks before `start_date`, winter cover and a storage crop's
    third load weeks after `finish_date`. "Period: 1 March – 12 July" above a 9 February record
    is a document that states a range it does not keep to, and a certifier queries it. The
    period line is kept (it is the crop cycle the operator declared); one line beside it now
    prints the record span and which side was overrun. Nothing prints when the records sit
    inside the period — the disclosure is owed only when it is true.
    """

    def setUp(self):
        from history.models import ProductionEvent

        self.ProductionEvent = ProductionEvent
        user = User.objects.create_user(email="span@test.com", password="x")
        company = Company.objects.create(name="Span Co")
        est = Establishment.objects.create(name="Span Farm", company=company)
        self.parcel = Parcel.objects.create(name="Home Field East", establishment=est, area=5.0)
        crop = CropType.objects.create(
            name="Blueberries",
            slug="blueberries-span",
            category="fruit",
            description="d",
            typical_farm_size="10",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        self.start = datetime(2026, 3, 1, 8, tzinfo=dt_timezone.utc)
        self.finish = datetime(2026, 7, 12, 17, tzinfo=dt_timezone.utc)
        self.history = Production.objects.create(
            parcel=self.parcel,
            product=Product.objects.create(name="Blueberries"),
            crop_type=crop,
            operator=user,
            start_date=self.start,
            finish_date=self.finish,
        )

    def _event(self, when, **extra):
        fields = {"type": "MO", "name": "Mowing"}
        fields.update(extra)
        return self.ProductionEvent.objects.create(history=self.history, date=when, **fields)

    def _cover_text(self):
        import io

        from pdfminer.high_level import extract_text

        buffer = AuditExportService(self.history, certification_type="usda_organic").generate_pdf()
        text = extract_text(io.BytesIO(buffer.getvalue() if hasattr(buffer, "getvalue") else buffer))
        return " ".join(text.split())

    def test_records_inside_the_period_print_no_span_line(self):
        self._event(self.start + timedelta(days=30))
        self._event(self.finish - timedelta(days=2))
        self.assertNotIn("Records:", self._cover_text())

    def test_pre_season_and_post_harvest_records_are_disclosed_beside_the_period(self):
        from history.services.audit_export_service import records_outside_period, records_span_line

        self._event(datetime(2026, 2, 9, 9, tzinfo=dt_timezone.utc), type="PR", name="Dormant pruning")
        self._event(datetime(2026, 8, 31, 9, tzinfo=dt_timezone.utc), type="IR", name="Irrigation summary")
        over = records_outside_period(self.history)
        self.assertTrue(over["before"] and over["after"])
        line = records_span_line(self.history)
        self.assertIn("Records: 2026-02-09 to 2026-08-31", line)
        self.assertIn("pre-season work from 2026-02-09", line)
        self.assertIn("post-harvest records through 2026-08-31", line)
        text = self._cover_text()
        self.assertIn("Production — 2026-03-01 to 2026-07-12", text)  # the declared cycle stays
        self.assertIn("Records: 2026-02-09 to 2026-08-31", text)

    def test_only_the_overrun_side_is_named(self):
        from history.services.audit_export_service import records_span_line

        self._event(self.start + timedelta(days=10))
        self._event(self.finish + timedelta(days=50), type="IR", name="Irrigation summary")
        line = records_span_line(self.history)
        self.assertIn("post-harvest records through", line)
        self.assertNotIn("pre-season", line)
