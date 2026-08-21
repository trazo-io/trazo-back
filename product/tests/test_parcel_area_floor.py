"""A parcel must have a positive area, on the path parcels are actually written.

The certifier dossier reconciles the farm's stated total acreage against the sum of its
parcels — "27.9 acres (parcels in this dossier total 27.9 acres)". A zero-area parcel makes
that line silently wrong while looking arithmetically fine, and a negative one is nonsense
that would subtract from the total.

`product/tests/test_models.py::test_parcel_area_validation` has asserted this since it was
written and has been FAILING: `Parcel.area` carried no validators at all. It sits in a file
where 45 sibling tests error on model fields removed long ago, which is why nobody noticed.

Both halves are enforced, deliberately: the model validator for anything that calls
`full_clean()`, and the serializer for the API — DRF calls `full_clean()` on neither
`create()` nor `update()`, the same gap that let a cultural-control pest event save without
its § 205.206(a) practice.
"""

from django.core.exceptions import ValidationError
from django.test import TestCase

from company.models import Company, Establishment
from product.models import Parcel
from product.serializers import CreateParcelSerializer


class ParcelAreaFloorTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Area Co")
        self.establishment = Establishment.objects.create(name="Area Farm", company=company)

    def test_a_positive_area_is_accepted(self):
        parcel = Parcel(name="Valid", establishment=self.establishment, area=15.75)
        parcel.full_clean()  # must not raise

    def test_zero_is_refused_by_the_model(self):
        with self.assertRaises(ValidationError):
            Parcel(name="Zero", establishment=self.establishment, area=0.0).full_clean()

    def test_negative_is_refused_by_the_model(self):
        with self.assertRaises(ValidationError):
            Parcel(name="Negative", establishment=self.establishment, area=-5.0).full_clean()

    def test_zero_is_refused_on_the_api_path_too(self):
        """The model validator alone guards nothing here — DRF never calls full_clean()."""
        serializer = CreateParcelSerializer(
            data={"name": "Zero via API", "establishment": self.establishment.pk, "area": 0}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("area", serializer.errors)

    def test_a_real_area_still_saves_through_the_serializer(self):
        serializer = CreateParcelSerializer(data={"name": "Real", "establishment": self.establishment.pk, "area": 5.06})
        self.assertTrue(serializer.is_valid(), serializer.errors)
