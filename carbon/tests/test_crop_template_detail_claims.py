"""The crop template detail payload carries no benchmark and no carbon-credit figure.

`GET /api/carbon/crop-templates/<id>/` is live: the production quick start calls it and reads
`name` and `events`. Until 2026-11-07 it also returned two keys nothing rendered:

* `benchmark`: a CarbonBenchmark row for the crop, introduced in the code as a "USDA
  benchmark". The rows are an industry average Trazo computes about itself, and the seeders
  that write them label simulated company counts with a USDA source.
* `carbon_credit_potential`: the template's projected emissions reduction, presented as
  tradable credits. A carbon-offset claim, 16 CFR 260.5, the class the offset routes were
  retired for.

The test seeds a benchmark that matches the crop and a non-zero projected reduction, so the old
code would have served both keys with values.
"""

from rest_framework.test import APITestCase

from carbon.models import CarbonBenchmark, CropType, EventTemplate, ProductionTemplate
from users.models import User

RETIRED_KEYS = ("benchmark", "carbon_credit_potential")


class CropTemplateDetailClaimsTests(APITestCase):
    def setUp(self):
        crop = CropType.objects.create(
            name="Detail Crop",
            slug="detail-crop",
            category="vegetable",
            description="d",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
        )
        self.template = ProductionTemplate.objects.create(
            crop_type=crop,
            name="Detail Template",
            slug="detail-template",
            farming_approach="organic",
            description="d",
            complexity_level="intermediate",
            projected_emissions_reduction=25.0,
        )
        EventTemplate.objects.create(
            production_template=self.template,
            name="Plant",
            event_type="planting",
            description="d",
            timing="Spring",
            frequency="annual",
            typical_duration="1 day",
            order_sequence=1,
            carbon_impact=0.0,
            carbon_category="low",
            cost_estimate=0.0,
            efficiency_tips="",
            backend_event_type=1,
        )
        CarbonBenchmark.objects.create(
            industry="vegetable",
            year=2026,
            average_emissions=1500.0,
            unit="kg CO2e/ha",
            source="seeded",
            crop_type="Detail Crop",
        )
        self.client.force_authenticate(User.objects.create_user(email="detail@t.test", password="x"))

    def _detail(self):
        response = self.client.get(f"/api/carbon/crop-templates/{self.template.id}/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_the_retired_keys_are_not_served(self):
        payload = self._detail()
        self.assertEqual([key for key in RETIRED_KEYS if key in payload], [])

    def test_what_the_quick_start_reads_is_still_served(self):
        payload = self._detail()
        self.assertEqual(payload["name"], "Detail Template")
        self.assertEqual([event["name"] for event in payload["events"]], ["Plant"])
