"""
Repair-only crop assignment on productions (HistoryWriteSerializer.crop_type_id).

The state under test comes from one real path: the COG Pro white-glove importer
targets hand-created productions, which can lack crop_type/product. UI creations
can't (start_production requires crop and backfills Product). The rules:

  1. A production with NO crop accepts crop_type_id once — and the Product row
     is backfilled exactly the way start_production does it.
  2. A production WITH a crop refuses a different crop_type_id (events,
     templates, and PUR rows are keyed to it) — with an actionable message.
  3. Re-sending the SAME crop id is a no-op, not an error.
"""

from django.utils import timezone

from rest_framework.test import APITestCase

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, Product
from users.models import User, WorksIn


class ProductionCropRepairTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="crop-repair@test.com", password="x")
        cls.company = Company.objects.create(name="Repair Farm Co")
        cls.establishment = Establishment.objects.create(name="RF1", company=cls.company)
        WorksIn.objects.create(user=cls.owner, company=cls.company, role="CA")
        cls.parcel = Parcel.objects.create(name="RP1", establishment=cls.establishment, area=5.0)
        cls.crop = CropType.objects.create(
            name="Walnut Test Crop",
            slug="walnut-test-crop",
            category="tree_nut",
            description="Test crop",
            typical_farm_size="20-100 ha",
            growing_season="deciduous",
            harvest_season="fall",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=False,
        )
        cls.other_crop = CropType.objects.create(
            name="Almond Test Crop",
            slug="almond-test-crop",
            category="tree_nut",
            description="Test crop",
            typical_farm_size="20-100 ha",
            growing_season="deciduous",
            harvest_season="fall",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=False,
        )

    def _cropless_production(self):
        return History.objects.create(
            name="Imported Season",
            parcel=self.parcel,
            start_date=timezone.now(),
            published=False,
        )

    def test_repair_sets_crop_and_backfills_product(self):
        production = self._cropless_production()
        self.client.force_authenticate(self.owner)
        resp = self.client.patch(
            f"/api/histories/{production.id}/",
            {"crop_type_id": self.crop.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        production.refresh_from_db()
        self.assertEqual(production.crop_type_id, self.crop.id)
        self.assertIsNotNone(production.product_id)
        self.assertEqual(production.product.name, self.crop.name)

    def test_change_of_existing_crop_is_refused(self):
        production = self._cropless_production()
        production.crop_type = self.crop
        production.product = Product.objects.create(name=self.crop.name + " P")
        production.save(update_fields=["crop_type", "product"])

        self.client.force_authenticate(self.owner)
        resp = self.client.patch(
            f"/api/histories/{production.id}/",
            {"crop_type_id": self.other_crop.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cannot be changed", str(resp.data))
        production.refresh_from_db()
        self.assertEqual(production.crop_type_id, self.crop.id)

    def test_same_crop_id_is_a_noop(self):
        production = self._cropless_production()
        production.crop_type = self.crop
        production.save(update_fields=["crop_type"])

        self.client.force_authenticate(self.owner)
        resp = self.client.patch(
            f"/api/histories/{production.id}/",
            {"crop_type_id": self.crop.id, "name": "Renamed Season"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        production.refresh_from_db()
        self.assertEqual(production.name, "Renamed Season")
        self.assertEqual(production.crop_type_id, self.crop.id)

    def test_unknown_crop_id_is_a_field_error(self):
        production = self._cropless_production()
        self.client.force_authenticate(self.owner)
        resp = self.client.patch(
            f"/api/histories/{production.id}/",
            {"crop_type_id": 999999},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("crop_type_id", resp.data)
