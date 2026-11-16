"""Land-history rows with months, acres, pasture and the seed / planting stock columns (2026-11-11).

CCOF ORGB49 (R11 3/14/2022) F7 asks each use "Fallow / Cover cropping / Pasture / Production of crops / Other,
each with a from-to month/year range"; WSDA AGR 2264 (R 05/26) ref 10 asks dates produced and acreage per crop;
OTCO C2 (2024/06/05) 2.4 lets the history begin "the day after the last prohibited substance application date"
and prints, per year, the crop or land use and the Seeds / Planting Stock Information: seed, seedling or
planting stock; GMO or non-GMO; treated or untreated. Rows carried a year and nothing finer.
"""

import io
from datetime import date

from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from history.models import Production
from product.models import Parcel, ParcelCropHistory, Product
from product.services.land_history import land_history_rows
from users.models import User, WorksIn


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Parcel(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Willamette Pasture LLC")
        self.user = User.objects.create_user(email="history@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Willamette Farm", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            certifier_name="Oregon Tilth Certified Organic (OTCO)",
        )
        self.parcel = Parcel.objects.create(name="Hay Ground", establishment=self.est, area=10.0)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def post(self, **data):
        return self.client.post(
            "/api/parcel-crop-history/",
            {
                "parcel": self.parcel.id,
                "year": 2024,
                "crop_grown": "Orchardgrass",
                "production_method": "pasture",
                **data,
            },
            format="json",
        )

    def page(self) -> str:
        return _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))


class TheApiTakesMonthsAcresAndPlanting(_Parcel):
    def test_a_month_input_is_stored_as_day_one(self):
        r = self.post(period_start="2024-03", period_end="2025-07-19", acres="9.5")
        self.assertEqual(r.status_code, 201, r.content)
        row = ParcelCropHistory.objects.get()
        self.assertEqual((row.period_start, row.period_end), (date(2024, 3, 1), date(2025, 7, 1)))
        self.assertEqual(str(row.acres), "9.50")
        self.assertEqual(row.production_method, "pasture")

    def test_blank_months_and_acres_are_not_stated(self):
        r = self.post(period_start="", period_end="", acres="")
        self.assertEqual(r.status_code, 201, r.content)
        row = ParcelCropHistory.objects.get()
        self.assertIsNone(row.period_start)
        self.assertIsNone(row.acres)

    def test_a_period_must_run_forward_and_hold_the_year(self):
        self.assertEqual(self.post(period_start="2024-07", period_end="2024-03").status_code, 400)
        self.assertEqual(self.post(period_start="2025-01").status_code, 400)
        self.assertEqual(self.post(period_end="2023-12").status_code, 400)
        self.assertEqual(self.post(acres="0").status_code, 400)
        self.assertFalse(ParcelCropHistory.objects.exists())

    def test_a_treatment_name_is_kept_only_for_treated_seed(self):
        r = self.post(seed_treated="untreated", seed_treatment_name="Apron XL")
        self.assertEqual(r.status_code, 201, r.content)
        row = ParcelCropHistory.objects.get()
        self.assertEqual(row.seed_treatment_name, "")
        r = self.client.patch(
            f"/api/parcel-crop-history/{row.id}/",
            {"seed_treated": "treated", "seed_treatment_name": "Apron XL"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        row.refresh_from_db()
        self.assertEqual(row.seed_treatment_name, "Apron XL")


class SectionFPrintsTheColumns(_Parcel):
    def test_months_acres_use_and_planting_print_on_the_year(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=2024,
            crop_grown="Sweet corn",
            production_method="organic",
            period_start=date(2024, 5, 1),
            period_end=date(2024, 9, 1),
            acres=6,
            propagule_type="seed",
            gmo_status="non_gmo",
            seed_treated="untreated",
        )
        ParcelCropHistory.objects.create(
            parcel=self.parcel, year=2023, crop_grown="Orchardgrass", production_method="pasture", acres=10
        )
        page = self.page()
        self.assertIn("2024 · 05/2024 to 09/2024 · Sweet corn · organic · 6 acres", page)
        self.assertIn("planting: seed, Non-GMO, untreated", page)
        self.assertIn("2023 · Orchardgrass · pasture · 10 acres", page)

    def test_a_type_with_no_gmo_answer_says_so(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel, year=2024, crop_grown="Corn", production_method="conventional", propagule_type="seed"
        )
        self.assertIn("planting: seed, GMO origin not stated, treatment not stated", self.page())

    def test_a_treated_seed_names_its_treatment(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=2024,
            crop_grown="Corn",
            production_method="conventional",
            propagule_type="seed",
            gmo_status="gmo",
            seed_treated="treated",
            seed_treatment_name="Cruiser 5FS",
        )
        self.assertIn("planting: seed, GMO, treated (Cruiser 5FS)", self.page())

    def test_a_year_from_season_records_prints_the_months_its_seasons_cover(self):
        Production.objects.create(
            name="Squash 2025",
            parcel=self.parcel,
            product=Product.objects.create(name="Squash"),
            start_date=timezone.make_aware(timezone.datetime(2025, 4, 14)),
            finish_date=timezone.make_aware(timezone.datetime(2025, 9, 30)),
        )
        row = next(r for r in land_history_rows(self.parcel) if r.year == 2025)
        self.assertTrue(row.is_derived)
        self.assertEqual((row.period_start, row.period_end), (date(2025, 4, 1), date(2025, 9, 1)))
        self.assertIsNone(row.acres)
        self.assertIn("2025 · 04/2025 to 09/2025 · Squash", self.page())


class ReviewFindingsOn383(_Parcel):
    def test_a_large_acreage_prints_in_full(self):
        from product.services.land_history import format_acres

        self.assertEqual(format_acres(1234567), "1,234,567")
        self.assertEqual(format_acres("12.50"), "12.5")
        self.assertEqual(format_acres(18), "18")
        ParcelCropHistory.objects.create(
            parcel=self.parcel, year=2023, crop_grown="Range", production_method="pasture", acres=1234567
        )
        page = self.page()
        self.assertIn("1,234,567 acres", page)
        self.assertNotIn("e+06", page)

    def test_an_open_season_dated_after_today_adds_no_months(self):
        today = timezone.now()
        Production.objects.create(
            name="Garlic (planned)",
            parcel=self.parcel,
            product=Product.objects.create(name="Garlic"),
            start_date=today + timezone.timedelta(days=20),
        )
        rows = land_history_rows(self.parcel)
        self.assertTrue(rows)
        for row in rows:
            if row.period_start and row.period_end:
                self.assertLessEqual(row.period_start, row.period_end, row)
