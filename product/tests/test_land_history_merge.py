"""Land history merges the years the operator typed with the years they logged.

WHY THIS EXISTS
---------------
Both § 205.202(b) surfaces — the Parcel Application's "F. Land history" and the dossier's
"3-Year Field & Crop Rotation History" — read only `ParcelCropHistory`, the hand-typed table,
and fell back to season records only when it was EMPTY. A pilot that typed 2023-2025 at setup
and then logged two full seasons filed its 2028 renewal with a "3-Year" history reading
2023 / 2024 / 2025; the first certified crop on a newly leased field was absent from that
field's own application. Found 2026-08-23 reading the generated renewal as a certifier.

These tests pin the merge rules: a typed year is verbatim and wins; a logged year with no typed
row is derived and says so; a season spanning two calendar years appears in both; a derived
row never states a last prohibited input.
"""

from datetime import datetime
from datetime import timezone as dt_tz

from django.test import TestCase

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production, SoilManagementEvent
from product.models import Parcel, ParcelCropHistory, Product
from product.services.land_history import SOURCE_DERIVED, SOURCE_RECORDED, land_history_rows


def _dt(y, m, d):
    return datetime(y, m, d, 9, 0, tzinfo=dt_tz.utc)


class LandHistoryMergeTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Merge Co")
        self.est = Establishment.objects.create(name="Merge Farm", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="Lease", establishment=self.est, area=3.97)
        self.carrots = Product.objects.create(name="Carrots")
        self.spinach = Product.objects.create(name="Spinach")
        self.crop = CropType.objects.create(
            name="Carrots",
            slug="carrots-lh",
            category="vegetable",
            description="d",
            typical_farm_size="1",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
        )

    def _season(self, name, product, start, finish=None, method="organic"):
        return Production.objects.create(
            name=name,
            parcel=self.parcel,
            product=product,
            crop_type=self.crop,
            start_date=start,
            finish_date=finish,
            production_method=method,
        )

    def test_typed_years_and_logged_years_both_appear_newest_first(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=2023,
            crop_grown="Ryegrass seed",
            production_method="conventional",
            last_prohibited_substance="Glyphosate",
            date_last_prohibited=_dt(2023, 6, 10).date(),
        )
        ParcelCropHistory.objects.create(parcel=self.parcel, year=2024, crop_grown="Fallow", production_method="fallow")
        self._season("Carrots 2027 — Lease", self.carrots, _dt(2027, 4, 12), _dt(2027, 10, 12))
        rows = land_history_rows(self.parcel)
        self.assertEqual([r.year for r in rows], [2027, 2024, 2023])
        self.assertEqual([r.source for r in rows], [SOURCE_DERIVED, SOURCE_RECORDED, SOURCE_RECORDED])
        self.assertEqual(rows[0].crop_grown, "Carrots")
        self.assertIn("Carrots 2027 — Lease", rows[0].notes)
        # The typed row is verbatim — the glyphosate attestation is the operator's.
        self.assertEqual(rows[2].last_prohibited_substance, "Glyphosate")

    def test_a_typed_year_wins_over_a_logged_one(self):
        """The operator's own statement for a year is never rewritten from records."""
        ParcelCropHistory.objects.create(
            parcel=self.parcel, year=2027, crop_grown="Carrots (hand-typed)", production_method="organic"
        )
        self._season("Carrots 2027 — Lease", self.carrots, _dt(2027, 4, 12), _dt(2027, 10, 12))
        rows = land_history_rows(self.parcel)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, SOURCE_RECORDED)
        self.assertEqual(rows[0].crop_grown, "Carrots (hand-typed)")

    def test_a_spanning_season_appears_in_both_years(self):
        """Sown October 2026, cut April 2027 — that field grew spinach in both years."""
        self._season("Overwintered Spinach 2027", self.spinach, _dt(2026, 10, 12), _dt(2027, 4, 20))
        rows = {r.year: r for r in land_history_rows(self.parcel)}
        self.assertEqual(set(rows), {2026, 2027})
        self.assertIn("Spinach", rows[2026].crop_grown)
        self.assertIn("harvested 2027", rows[2026].crop_grown)
        self.assertIn("sown 2026", rows[2027].crop_grown)

    def test_inputs_logged_that_year_are_listed_and_no_prohibited_input_is_claimed(self):
        s = self._season("Carrots 2027 — Lease", self.carrots, _dt(2027, 4, 12), _dt(2027, 10, 12))
        ChemicalEvent.objects.create(
            history=s, date=_dt(2027, 5, 1), type="FE", commercial_name="Neptune's Harvest Fish Fertilizer 2-3-1"
        )
        ChemicalEvent.objects.create(
            history=s, date=_dt(2027, 6, 1), type="FE", commercial_name="Neptune's Harvest Fish Fertilizer 2-3-1"
        )
        SoilManagementEvent.objects.create(
            history=s, date=_dt(2027, 10, 20), type="CC", name="Cereal rye / vetch cover drilled"
        )
        row = land_history_rows(self.parcel)[0]
        self.assertEqual(row.substances_applied, "Neptune's Harvest Fish Fertilizer 2-3-1")
        self.assertIn("Cereal rye", row.cover_crop)
        self.assertEqual(row.production_method, "organic")
        self.assertEqual(row.last_prohibited_substance, "")
        self.assertIsNone(row.date_last_prohibited)

    def test_through_year_caps_derived_rows_but_never_typed_ones(self):
        ParcelCropHistory.objects.create(parcel=self.parcel, year=2028, crop_grown="Onions (planned)")
        self._season("Carrots 2027 — Lease", self.carrots, _dt(2027, 4, 12), _dt(2027, 10, 12))
        self._season("Onions 2028 — Lease", self.carrots, _dt(2028, 4, 1))
        years = [r.year for r in land_history_rows(self.parcel, through_year=2027)]
        # 2028 typed row stays (it is the operator's statement); the 2028 SEASON is capped.
        self.assertEqual(years, [2028, 2027])
        self.assertEqual(
            [r.source for r in land_history_rows(self.parcel, through_year=2027)], [SOURCE_RECORDED, SOURCE_DERIVED]
        )

    def test_an_open_season_does_not_derive_years_that_have_not_happened(self):
        """A projection is not land use: an open season with a far-future expected harvest
        derives rows only through the current year."""
        from django.utils import timezone as tz

        this_year = tz.now().year
        Production.objects.create(
            name="Young orchard",
            parcel=self.parcel,
            product=self.carrots,
            crop_type=self.crop,
            start_date=_dt(this_year, 3, 1),
            expected_harvest=_dt(this_year + 3, 9, 1),
            production_method="organic",
        )
        years = [r.year for r in land_history_rows(self.parcel)]
        self.assertEqual(years, [this_year])

    def test_open_season_reads_as_in_progress(self):
        self._season("Carrots 2027 — Lease", self.carrots, _dt(2027, 4, 12))
        row = land_history_rows(self.parcel)[0]
        self.assertIn("in progress", row.crop_grown)
