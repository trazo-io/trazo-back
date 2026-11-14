"""A season's production method is the grower's statement, never a default (2026-11-13).

`History.production_method` carried `default="conventional"`, and `start_production` fell back to
it as well. The value reaches certifier records: land history derives each year's method from the
seasons logged in it, and the renewal land table lists a certified parcel's "conventional" years
from those rows. A season created without a stated method (the nested create never passes one)
therefore told the certifier the parcel was farmed conventionally that year.

Same rule as `noDefaultProductionMethod.test.ts` in trazo-app, which closed the form's own
preselection on 2026-10-01; this closes the server's. Unstated is NULL.
"""

from datetime import datetime
from datetime import timezone as dt_tz

from django.urls import reverse

from history.models import History
from history.tests.test_season_plan_not_records import SeasonPlanFixture
from product.services.land_history import land_history_rows


class TheModelAssumesNoMethod(SeasonPlanFixture):
    def test_a_new_season_has_no_method_until_one_is_stated(self):
        self.assertIsNone(History().production_method)

    def test_a_season_logged_without_a_method_is_not_a_conventional_year(self):
        History.objects.create(
            name="2026 Walnuts",
            parcel=self.parcel,
            crop_type=self.crop_type,
            start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc),
        )
        rows = [row for row in land_history_rows(self.parcel, through_year=2026) if row.year == 2026]
        self.assertEqual(len(rows), 1, rows)  # the year was derived from the season
        self.assertEqual(rows[0].production_method, "")


class BothCreatePathsStoreUnstatedAsNull(SeasonPlanFixture):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.user)

    def test_start_production_without_a_method(self):
        response = self.client.post(
            reverse("histories-start-production"),
            {
                "name": "2026 Walnuts",
                "parcel_id": self.parcel.id,
                "crop_type": self.crop_type.id,
                "start_date": "2026-03-01T00:00:00Z",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIsNone(History.objects.get(name="2026 Walnuts").production_method)

    def test_start_production_keeps_a_stated_method(self):
        response = self.client.post(
            reverse("histories-start-production"),
            {
                "name": "2026 Walnuts",
                "parcel_id": self.parcel.id,
                "crop_type": self.crop_type.id,
                "start_date": "2026-03-01T00:00:00Z",
                "production_method": "conventional",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(History.objects.get(name="2026 Walnuts").production_method, "conventional")

    def test_the_nested_create(self):
        url = reverse(
            "parcel-histories-list",
            kwargs={
                "company_pk": self.company.id,
                "establishment_pk": self.establishment.id,
                "parcel_pk": self.parcel.id,
            },
        )
        body = {"parcel": self.parcel.id, "product": "Walnuts", "start_date": "2026-03-01T00:00:00Z"}
        response = self.client.post(url, body, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIsNone(History.objects.latest("id").production_method)
