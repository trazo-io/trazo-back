"""Closing a season must close the season the farmer named.

`Parcel.current_history` holds whichever season started LAST. A perennial block routinely
carries two open at once, and the finish page is reached per-production — so this endpoint
validated and closed the wrong one.

Found live on 2026-08-20: closing "Honeycrisp 2025" (start 2025-03-15) with a finish date of
2025-09-22 returned *"Finish date cannot be before the production's start date (2026-03-18)"* —
the start of the 2026 season. The farmer could not complete the close at all, and the date in
the error was one they had never entered.

The branch that did NOT fire there is the dangerous one: with compatible dates the click would
have closed the WRONG season, and closing is irreversible by design — it makes the record
read-only and starts the § 205.103(b)(3) retention clock.

Exercised at the unit seam (`_resolve_finish_target` + `Parcel.finish_history_record`), the
same way test_finalization_validation.py pins the validator.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.response import Response

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import Production
from product.models import Parcel, Product
from product.views import ParcelViewSet


class FinishTargetResolutionTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Fin Co")
        est = Establishment.objects.create(name="Fin Farm", company=company)
        self.parcel = Parcel.objects.create(name="Ridge", establishment=est, area=11.5)
        self.crop = CropType.objects.create(
            name="Apple",
            slug="apple-fin",
            category="tree_fruit",
            description="d",
            typical_farm_size="1",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        self.product = Product.objects.create(name="Apple")
        self.resolve = ParcelViewSet()._resolve_finish_target

        self.older = self._season("Honeycrisp 2025", 520)
        self.newer = self._season("Honeycrisp 2026", 150)
        # the pointer holds the LAST started season — the whole problem
        self.parcel.current_history = self.newer
        self.parcel.save(update_fields=["current_history"])

    def _season(self, name, days_ago):
        return Production.objects.create(
            parcel=self.parcel,
            product=self.product,
            crop_type=self.crop,
            name=name,
            start_date=timezone.now() - timedelta(days=days_ago),
        )

    # ---- resolution -------------------------------------------------------

    def test_the_named_season_wins_over_the_pointer(self):
        target = self.resolve(self.parcel, {"history": self.older.id})
        self.assertEqual(target, self.older)

    def test_the_public_uuid_names_it_too(self):
        target = self.resolve(self.parcel, {"history": str(self.older.public_id)})
        self.assertEqual(target, self.older)

    def test_an_ambiguous_parcel_with_no_name_is_refused_and_lists_the_seasons(self):
        out = self.resolve(self.parcel, {})
        self.assertIsInstance(out, Response)
        self.assertEqual(out.status_code, 400)
        detail = str(out.data)
        self.assertIn("more than one open production", detail)
        self.assertIn(self.older.name, detail)
        self.assertIn(self.newer.name, detail)

    def test_a_single_open_season_still_resolves_without_a_name(self):
        """The common case keeps working — the guard is for ambiguity only."""
        self.newer.finish_date = timezone.now() - timedelta(days=10)
        self.newer.save(update_fields=["finish_date"])
        self.parcel.current_history = self.older
        self.parcel.save(update_fields=["current_history"])
        self.assertEqual(self.resolve(self.parcel, {}), self.older)

    def test_an_already_finished_season_is_refused(self):
        self.older.finish_date = timezone.now() - timedelta(days=100)
        self.older.save(update_fields=["finish_date"])
        out = self.resolve(self.parcel, {"history": self.older.id})
        self.assertIsInstance(out, Response)
        self.assertIn("already finished", str(out.data))

    def test_a_season_on_another_parcel_is_refused(self):
        other = Parcel.objects.create(name="Creek", establishment=self.parcel.establishment, area=6.8)
        theirs = Production.objects.create(
            parcel=other,
            product=self.product,
            crop_type=self.crop,
            name="Creek 2025",
            start_date=timezone.now() - timedelta(days=400),
        )
        out = self.resolve(self.parcel, {"history": theirs.id})
        self.assertIsInstance(out, Response)
        self.assertIn("No production", str(out.data))

    # ---- the close itself -------------------------------------------------

    def test_closing_a_non_pointer_season_leaves_the_pointer_alone(self):
        """Closing the 2025 season must not blank the parcel's current production."""
        data = {
            "production_amount": "971100",
            "production_unit": "lb",
            "lot_id": "CRO-2025-RB",
            "finish_date": (timezone.now() - timedelta(days=300)).isoformat(),
        }
        closed = self.parcel.finish_history_record(self.older, data, [])
        self.assertEqual(closed, self.older)
        self.older.refresh_from_db()
        self.newer.refresh_from_db()
        self.parcel.refresh_from_db()
        self.assertIsNotNone(self.older.finish_date, "the named season is the one closed")
        self.assertIsNone(self.newer.finish_date, "the other season is untouched")
        self.assertEqual(
            self.parcel.current_history_id,
            self.newer.id,
            "the pointer belongs to the still-open season and must survive",
        )

    def test_closing_the_pointer_season_clears_the_pointer(self):
        data = {
            "production_amount": "500000",
            "production_unit": "lb",
            "lot_id": "CRO-2026-RB",
            "finish_date": timezone.now().isoformat(),
        }
        self.parcel.finish_history_record(self.newer, data, [])
        self.parcel.refresh_from_db()
        self.assertIsNone(self.parcel.current_history_id)
