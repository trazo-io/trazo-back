"""Perennial or annual is the grower's statement, never a default (2026-11-13).

`History.type` ("OR" perennial, "GA" annual) decides whether the audit export attaches the
§ 205.204(a)(4) 12-month verdict to planting stock. `start_production` stored "OR" whenever the
body left it out, and both create paths passed any string straight into the choices column (raw
model kwarg, no serializer). An unstated season stays NULL, which prints the elapsed time with no
perennial verdict; an unknown code is refused.
"""

from django.urls import reverse

from history.models import Production
from history.tests.test_season_plan_not_records import SeasonPlanFixture


class StartProductionStoresWhatTheGrowerStated(SeasonPlanFixture):
    def _start(self, **extra):
        body = {
            "name": "2026 Walnuts",
            "parcel_id": self.parcel.id,
            "crop_type": self.crop_type.id,
            "start_date": "2026-03-01T00:00:00Z",
            "production_method": "organic",
            **extra,
        }
        return self.client.post(reverse("productions-start-production"), body, format="json")

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.user)

    def test_an_unstated_season_is_not_recorded_as_perennial(self):
        response = self._start()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIsNone(Production.objects.get(name="2026 Walnuts").type)

    def test_an_empty_choice_is_unstated_too(self):
        response = self._start(type="")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIsNone(Production.objects.get(name="2026 Walnuts").type)

    def test_each_stated_value_is_kept(self):
        for code in ("OR", "GA"):
            with self.subTest(code=code):
                Production.objects.filter(name=f"Season {code}").delete()
                response = self._start(name=f"Season {code}", type=code)
                self.assertEqual(response.status_code, 201, response.content)
                self.assertEqual(Production.objects.get(name=f"Season {code}").type, code)

    def test_an_unknown_code_is_refused_before_anything_is_written(self):
        before = Production.objects.count()
        response = self._start(type="XX")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("type", response.json())
        self.assertEqual(Production.objects.count(), before)


class NestedCreateRefusesAnUnknownCode(SeasonPlanFixture):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.user)
        self.url = reverse(
            "parcel-productions-list",
            kwargs={
                "company_pk": self.company.id,
                "establishment_pk": self.establishment.id,
                "parcel_pk": self.parcel.id,
            },
        )

    def _post(self, **extra):
        body = {"parcel": self.parcel.id, "product": "Walnuts", "start_date": "2026-03-01T00:00:00Z", **extra}
        return self.client.post(self.url, body, format="json")

    def test_unknown_code_is_a_400(self):
        before = Production.objects.count()
        response = self._post(type="XX")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Production.objects.count(), before)

    def test_unstated_is_null(self):
        response = self._post()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIsNone(Production.objects.latest("id").type)
