"""A parcel may grow more than one crop in a year.

`ParcelCropHistory` carried `unique_together = ("parcel", "year")`, which made a SPLIT FIELD
unrecordable. Split fields are ordinary practice, and COG Pro's own data does it — South Field in
2011 carried tomatoes on rows 1-40 and melons on rows 41-80.

That is not a cosmetic limitation. 7 CFR 205.202 asks for a 36-month field history showing every
crop grown on the ground, so a migrating farm was forced to drop half of exactly the history the
regulation asks for, with nothing recording the loss.
"""

from django.db import IntegrityError, transaction
from django.test import TestCase


class SplitFieldTests(TestCase):
    def setUp(self):
        from company.models import Company, Establishment
        from product.models import Parcel

        company = Company.objects.create(name="Diversified Co")
        farm = Establishment.objects.create(name="Home Ranch", company=company, country="US", state="CA")
        self.parcel = Parcel.objects.create(name="South Field", establishment=farm, area=10.0)

    def _entry(self, **kwargs):
        from product.models import ParcelCropHistory

        return ParcelCropHistory.objects.create(parcel=self.parcel, **kwargs)

    def test_two_crops_in_one_parcel_year_are_recordable(self):
        # The exact shape found in COG Pro's demo export.
        self._entry(year=2011, crop_grown="Tomatoes & Peppers", block_id="Rows 1-40")
        self._entry(year=2011, crop_grown="Melons & Squash", block_id="Rows 41-80")

        from product.models import ParcelCropHistory

        rows = ParcelCropHistory.objects.filter(parcel=self.parcel, year=2011)
        self.assertEqual(rows.count(), 2)
        self.assertEqual(
            sorted(rows.values_list("crop_grown", flat=True)),
            ["Melons & Squash", "Tomatoes & Peppers"],
        )

    def test_two_crops_are_recordable_even_without_block_ids(self):
        # A farmer who knows two crops shared the ground but not which rows must still be able to
        # say so. Refusing the record because the block is unknown would lose real land history.
        self._entry(year=2011, crop_grown="Tomatoes")
        self._entry(year=2011, crop_grown="Melons")
        from product.models import ParcelCropHistory

        self.assertEqual(ParcelCropHistory.objects.filter(parcel=self.parcel, year=2011).count(), 2)

    def test_the_same_crop_in_different_blocks_is_recordable(self):
        self._entry(year=2011, crop_grown="Tomatoes", block_id="Rows 1-40")
        self._entry(year=2011, crop_grown="Tomatoes", block_id="Rows 41-80")
        from product.models import ParcelCropHistory

        self.assertEqual(ParcelCropHistory.objects.filter(parcel=self.parcel, year=2011).count(), 2)

    def test_an_exact_duplicate_is_still_refused(self):
        # Relaxing the constraint must not open the door to true duplicates: a land history that
        # double-counts a crop is as wrong as one that drops it.
        self._entry(year=2011, crop_grown="Melons", block_id="Rows 41-80")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._entry(year=2011, crop_grown="Melons", block_id="Rows 41-80")

    def test_an_exact_duplicate_with_no_block_is_refused_too(self):
        # `block_id` defaults to "" rather than NULL precisely for this: Postgres treats NULLs as
        # distinct, so a nullable column would have let these two rows both exist, and Django 4.1
        # has no `nulls_distinct` to prevent it.
        self._entry(year=2011, crop_grown="Melons")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._entry(year=2011, crop_grown="Melons")

    def test_block_id_defaults_to_empty_string_not_null(self):
        entry = self._entry(year=2012, crop_grown="Cover crop")
        entry.refresh_from_db()
        self.assertEqual(entry.block_id, "")
        self.assertIsNotNone(entry.block_id)

    def test_different_years_are_unaffected(self):
        self._entry(year=2011, crop_grown="Tomatoes")
        self._entry(year=2012, crop_grown="Tomatoes")
        from product.models import ParcelCropHistory

        self.assertEqual(ParcelCropHistory.objects.filter(parcel=self.parcel).count(), 2)
