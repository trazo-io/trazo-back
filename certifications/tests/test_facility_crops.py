"""Which crops each off-farm handler or storage facility takes (2026-11-09).

CCOF G6.1 C2 asks the finished products per handler, CCOF G6.2 A2 the crops stored per storage
facility, OTCO C7 7.7-2 and 7.10-2 the same per facility. A production already names the facilities
its crop went to, so the plan reads the crops from those links, never from a typed list, and prints
the products and packaging form the operation describes on the facility record beside them.
"""

import io
from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from carbon.models import CropType
from certifications.models import OrganicSystemPlan, PostHarvestFacility
from certifications.services.facility_crops import crops_by_facility, crops_for
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel
from users.models import User, WorksIn

AT = "2026-11-09T10:00:00+00:00"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _crop(name, slug):
    return CropType.objects.create(
        name=name,
        slug=slug,
        category="fruit" if name != "Garlic" else "vegetable",
        description=name,
        typical_farm_size="1-10 ha",
        growing_season="Mar-Sep",
        harvest_season="Jul-Sep",
        emissions_per_hectare=0.0,
        industry_average=0.0,
        best_practice=0.0,
        carbon_credit_potential=0.0,
        typical_cost_per_hectare=0.0,
        has_soil_contact=True,
    )


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Facility Crops Farm Co")
        self.est = Establishment.objects.create(name="River Farm", company=self.company, state="OR")
        self.other = Establishment.objects.create(name="Hill Farm", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="Block A", establishment=self.est, area=4.0)
        self.other_parcel = Parcel.objects.create(name="Hill 1", establishment=self.other, area=2.0)
        self.blueberries = _crop("Blueberries", "blueberries-fc")
        self.garlic = _crop("Garlic", "garlic-fc")
        self.packer = PostHarvestFacility.objects.create(
            establishment=self.est, name="Valley Packers", facility_type="packer", role="handling"
        )
        self.cold = PostHarvestFacility.objects.create(
            establishment=self.est, name="North Cold Store", facility_type="cold_storage", role="storage"
        )

    def season(self, crop, year, facilities, parcel=None):
        history = History.objects.create(
            parcel=parcel or self.parcel,
            crop_type=crop,
            name=f"{crop.name} {year}",
            start_date=timezone.make_aware(datetime(year, 3, 1)),
            finish_date=timezone.make_aware(datetime(year, 9, 1)),
        )
        history.post_harvest_facilities.set(facilities)
        return history

    def plan(self):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name="CCOF Certification Services, LLC",
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {
                    "g6_1_harvest_transport": {
                        "answers": {"handled_by_another_operation": {"at": AT, "value": "yes_certified"}}
                    }
                },
            },
        )


class CropsAreReadFromTheRecordsTests(_Farm):
    def test_crops_by_season_per_facility(self):
        self.season(self.blueberries, 2025, [self.packer, self.cold])
        self.season(self.blueberries, 2026, [self.packer])
        self.season(self.garlic, 2026, [self.cold])
        by_facility = crops_by_facility(self.est)
        self.assertEqual(by_facility[self.packer.pk], [("Blueberries", [2025, 2026])])
        self.assertEqual(by_facility[self.cold.pk], [("Blueberries", [2025]), ("Garlic", [2026])])
        self.assertEqual(crops_for(self.cold), by_facility[self.cold.pk])

    def test_another_farms_production_never_names_a_crop_here(self):
        self.season(self.garlic, 2026, [self.packer], parcel=self.other_parcel)
        self.assertEqual(crops_by_facility(self.est).get(self.packer.pk, []), [])
        self.assertEqual(crops_for(self.packer), [])


class ThePlanPrintsThemTests(_Farm):
    def test_the_facility_line_names_the_crops_and_the_described_products(self):
        self.season(self.blueberries, 2025, [self.packer])
        self.packer.products_detail = "Fresh blueberries, 1 pint clamshells\nProcess grade, 30 lb flats"
        self.packer.save()
        text = _text(generate_module_pdf(self.plan(), "g6_1_harvest_transport"))
        self.assertIn("Crops on the production records linked to this facility: Blueberries (2025).", text)
        self.assertIn(
            "Products, as the operation describes them: Fresh blueberries, 1 pint clamshells; Process grade, 30 lb flats.",
            text,
        )

    def test_a_facility_with_neither_is_flagged_for_review(self):
        text = _text(generate_module_pdf(self.plan(), "g6_1_harvest_transport"))
        self.assertIn("[REVIEW] No production record is linked to this facility and no products are described", text)


class ApiTests(_Farm):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(email="facility-crops@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_the_api_states_the_crops_and_takes_the_products(self):
        self.season(self.garlic, 2026, [self.cold])
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/post-harvest-facilities/{self.cold.id}/"
        r = self.client.patch(url, {"products_detail": "Garlic, braided, 25 lb boxes"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["products_detail"], "Garlic, braided, 25 lb boxes")
        self.assertEqual(r.json()["crops_recorded"], [{"crop": "Garlic", "years": [2026]}])
