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
  4. A crop whose raw-manure floor the season's records already fall short of is refused, naming
     those records: a season with no crop holds no floor, so 90 days could be saved on it.
"""

from datetime import date

from django.utils import timezone

from rest_framework.test import APITestCase

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import Production, SoilManagementEvent
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
        return Production.objects.create(
            name="Imported Season",
            parcel=self.parcel,
            start_date=timezone.now(),
            published=False,
        )

    def test_repair_sets_crop_and_backfills_product(self):
        production = self._cropless_production()
        self.client.force_authenticate(self.owner)
        resp = self.client.patch(
            f"/api/productions/{production.id}/",
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
            f"/api/productions/{production.id}/",
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
            f"/api/productions/{production.id}/",
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
            f"/api/productions/{production.id}/",
            {"crop_type_id": 999999},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("crop_type_id", resp.data)


class CropSetIsHeldToTheManureFloorTests(APITestCase):
    """Every save path refuses raw manure at 90 days on a crop whose edible part touches the soil
    (§ 205.203(c)(1)(ii)). A season with no crop has no floor, so 90 days could be saved on it, and
    naming the crop afterwards left those records under the floor with nothing said (review of back
    #503)."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="crop-floor@test.com", password="x")
        cls.company = Company.objects.create(name="Floor Farm Co")
        cls.establishment = Establishment.objects.create(name="FF1", company=cls.company)
        WorksIn.objects.create(user=cls.owner, company=cls.company, role="CA")
        cls.parcel = Parcel.objects.create(name="FP1", establishment=cls.establishment, area=5.0)

        def crop(name, slug, category, soil):
            return CropType.objects.create(
                name=name,
                slug=slug,
                category=category,
                description=name,
                typical_farm_size="20-100 ha",
                growing_season="annual",
                harvest_season="fall",
                emissions_per_hectare=0.0,
                industry_average=0.0,
                best_practice=0.0,
                carbon_credit_potential=0.0,
                typical_cost_per_hectare=0.0,
                has_soil_contact=soil,
            )

        cls.carrots = crop("Floor Test Carrots", "floor-test-carrots", "vegetable", True)
        cls.walnuts = crop("Floor Test Walnuts", "floor-test-walnuts", "tree_nut", False)

    def _season_with_manure(self, *intervals):
        season = Production.objects.create(
            name="Imported Season", parcel=self.parcel, start_date=timezone.now(), published=False
        )
        for n, interval in enumerate(intervals, start=1):
            SoilManagementEvent.objects.create(
                history=season,
                type="OM",
                date=timezone.now(),
                description="Raw manure, incorporated",
                manure_treatment="raw",
                manure_application_date=date(2026, 3, n),
                manure_harvest_interval=interval,
            )
        return season

    def _set(self, season, crop):
        self.client.force_authenticate(self.owner)
        return self.client.patch(f"/api/productions/{season.id}/", {"crop_type_id": crop.id}, format="json")

    def test_a_soil_contact_crop_is_refused_while_a_record_keeps_90_days(self):
        season = self._season_with_manure("90", "120", "90")

        resp = self._set(season, self.carrots)

        self.assertEqual(resp.status_code, 400, resp.data)
        message = str(resp.data["crop_type_id"][0])
        self.assertIn("Floor Test Carrots: 2 raw-manure records keep", message)
        self.assertIn("2026-03-01, 2026-03-03", message)
        self.assertNotIn("2026-03-02", message)
        self.assertEqual(
            {k: str(v) for k, v in resp.data["error_codes"]["crop_type_id"].items()},
            {
                "code": "manure_below_floor_for_crop",
                "crop": "Floor Test Carrots",
                "count": "2",
                "dates": "2026-03-01, 2026-03-03",
                "days": "120",
            },
        )
        season.refresh_from_db()
        self.assertIsNone(season.crop_type_id)
        self.assertIsNone(season.product_id)

    def test_once_the_records_say_120_days_the_crop_is_set(self):
        season = self._season_with_manure("90")
        SoilManagementEvent.objects.filter(history=season).update(manure_harvest_interval="120")

        resp = self._set(season, self.carrots)

        self.assertEqual(resp.status_code, 200, resp.data)
        season.refresh_from_db()
        self.assertEqual(season.crop_type_id, self.carrots.id)

    def test_90_days_meets_the_floor_of_a_crop_that_does_not_touch_the_soil(self):
        season = self._season_with_manure("90")

        resp = self._set(season, self.walnuts)

        self.assertEqual(resp.status_code, 200, resp.data)
        season.refresh_from_db()
        self.assertEqual(season.crop_type_id, self.walnuts.id)
