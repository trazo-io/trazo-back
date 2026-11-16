"""A production cycle is not a calendar year, and § 205.406 is filed per year.

WHAT WENT WRONG
---------------
The annual-update section chose which filing to show with
`target_year = self.production.start_date.year` — the START year, and only that. An overwintered
crop breaks the assumption: alliums, brassicas, winter grain and strawberries are sown in
October and harvested the following June, so every record made after 1 January belongs to a year
the packet never mentioned.

A packet for a 2025-10-05 → 2026-06-18 season showed **Reporting Year 2025** and said nothing
about 2026 — on a farm that had a 2026 filing sitting right there. A certifier read records
running to June 2026 under a § 205.406 section reaffirming only 2025.

WHY IT SURVIVED
---------------
The surrounding code is careful: when NO filing exists for the target year it falls back to the
newest and prints a loud [REVIEW] saying the shown filing "does not reaffirm the OSP for the year
under review". That warning is exactly right, and it is why this case stayed silent — it only
fires when nothing is on file, and here the start year's filing existed. The well-handled case
hid the unhandled one.
"""

from datetime import datetime
from datetime import timezone as dt_timezone

from django.test import TestCase

from carbon.models import CropType
from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


def _pdf_text(pdf_bytes):
    import io

    from pdfminer.high_level import extract_text

    return extract_text(io.BytesIO(pdf_bytes))


class SpanningProductionAnnualUpdateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="span@test.com", password="x")
        company = Company.objects.create(name="Span Co")
        self.est = Establishment.objects.create(name="Span Farm", company=company)
        self.parcel = Parcel.objects.create(name="Winter Block", establishment=self.est, area=3.0)
        self.crop = CropType.objects.create(
            name="Onions",
            slug="onions-span",
            category="vegetable",
            description="Allium",
            typical_farm_size="10-40 ha",
            growing_season="Oct-Jun",
            harvest_season="Jun",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        self.product = Product.objects.create(name="Onions")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", created_by=self.user
        )

    def _update(self, year, day=10):
        return OSPAnnualUpdate.objects.create(
            prior_osp=self.osp,
            reporting_year=year,
            changes_summary=f"{year} reaffirmation.",
            additions=[],
            deletions=[],
            submitted_at=datetime(year, 1, day, tzinfo=dt_timezone.utc),
        )

    def _season(self, start, finish):
        """An overwintered crop: sown in autumn, harvested the following summer."""
        history = Production.objects.create(
            parcel=self.parcel,
            product=self.product,
            crop_type=self.crop,
            operator=self.user,
            start_date=start,
            finish_date=finish,
        )
        # One record either side of the calendar boundary, which is the whole point.
        for when, label in ((start, "autumn pass"), (finish, "spring pass")):
            ChemicalEvent.objects.create(
                history=history, date=when, type="FE", commercial_name=label, performed_by="Operator"
            )
        return history

    def _render(self, history):
        buffer = AuditExportService(history, certification_type="usda_organic").generate_pdf()
        return _pdf_text(buffer.getvalue() if hasattr(buffer, "getvalue") else buffer)

    def test_second_year_is_disclosed_when_its_update_exists(self):
        """Fails on the pre-fix code, which showed 2025 and never mentioned 2026."""
        self._update(2025)
        self._update(2026)
        text = self._render(
            self._season(datetime(2025, 10, 5, tzinfo=dt_timezone.utc), datetime(2026, 6, 18, tzinfo=dt_timezone.utc))
        )
        self.assertIn("also covers 2026", text)
        self.assertIn("2026 annual update", text)

    def test_missing_second_year_update_is_a_review_finding(self):
        """The half of the season with no reaffirmed plan must be named, not implied."""
        self._update(2025)
        text = self._render(
            self._season(datetime(2025, 10, 5, tzinfo=dt_timezone.utc), datetime(2026, 6, 18, tzinfo=dt_timezone.utc))
        )
        self.assertIn("runs into 2026", text)
        self.assertIn("no annual update is on file for 2026", text)
        self.assertIn("REVIEW", text)

    def test_single_year_production_is_untouched(self):
        """The common case must gain no new sentence.

        A spurious 'this production also covers…' on every ordinary packet would be a worse bug
        than the one being fixed: the § 205.406 section is short, and noise there reads as a
        finding.
        """
        self._update(2025)
        text = self._render(
            self._season(datetime(2025, 3, 1, tzinfo=dt_timezone.utc), datetime(2025, 7, 14, tzinfo=dt_timezone.utc))
        )
        self.assertNotIn("also covers", text)
        self.assertNotIn("runs into", text)

    def _open_season(self, start, event_dates):
        history = Production.objects.create(
            parcel=self.parcel,
            product=self.product,
            crop_type=self.crop,
            operator=self.user,
            start_date=start,
            finish_date=None,
        )
        for when in event_dates:
            ChemicalEvent.objects.create(
                history=history, date=when, type="FE", commercial_name="pass", performed_by="Operator"
            )
        return history

    def test_open_season_does_not_invent_future_years(self):
        """An unfinished season within one year must gain no sentence."""
        self._update(2025)
        history = self._open_season(
            datetime(2025, 3, 1, tzinfo=dt_timezone.utc), [datetime(2025, 4, 1, tzinfo=dt_timezone.utc)]
        )
        text = self._render(history)
        self.assertNotIn("also covers", text)
        self.assertNotIn("runs into", text)

    def test_open_season_still_running_in_the_next_year_is_disclosed(self):
        """The case a finish_date cannot see, and the one packets are most often generated for.

        A season sown in October and still open carries records dated in the following year. An
        earlier draft of this fix keyed the range off `finish_date or expected_harvest`, so an
        open season reported `end_year == start year` and disclosed nothing — while its own
        record tables printed the next year's applications. The range comes from the records.
        """
        self._update(2025)
        self._update(2026)
        history = self._open_season(
            datetime(2025, 10, 5, tzinfo=dt_timezone.utc),
            [datetime(2025, 11, 12, tzinfo=dt_timezone.utc), datetime(2026, 3, 4, tzinfo=dt_timezone.utc)],
        )
        text = self._render(history)
        self.assertIn("also covers 2026", text)

    def test_backwards_dates_do_not_produce_a_range(self):
        """A finish date before its start is malformed data, not a multi-year season."""
        self._update(2025)
        history = Production.objects.create(
            parcel=self.parcel,
            product=self.product,
            crop_type=self.crop,
            operator=self.user,
            start_date=datetime(2025, 6, 1, tzinfo=dt_timezone.utc),
            finish_date=datetime(2024, 6, 1, tzinfo=dt_timezone.utc),
        )
        ChemicalEvent.objects.create(
            history=history,
            date=datetime(2025, 6, 2, tzinfo=dt_timezone.utc),
            type="FE",
            commercial_name="pass",
            performed_by="Operator",
        )
        text = self._render(history)
        self.assertNotIn("also covers", text)
        self.assertNotIn("runs into", text)
