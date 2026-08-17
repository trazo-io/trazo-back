"""
Parcel Application (WS-5) — bindings, storage, and live completion.

Properties that matter:
  1. GET serves the definition + values read from REAL Parcel columns.
  2. PUT routes parcel_field answers to columns, everything else to
     application_answers; unknown buffer keys are refused.
  3. Completion reads LIVE state — adding crop-history rows or an affidavit
     moves the status without touching the application endpoint.
  4. The no-adjoining attestation is an explicit True — absence is not a claim.
"""

from datetime import date

from django.test import TestCase

from rest_framework.test import APIClient

from company.models import Company, Establishment
from product.models import Parcel, ParcelCropHistory
from product.services.parcel_application_status import parcel_application_status
from users.models import User, WorksIn


class ParcelApplicationStatusTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="App Farm")
        self.establishment = Establishment.objects.create(name="App Ranch", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="Quick Block", establishment=self.establishment, area=2.0)

    def test_quick_added_parcel_is_not_started(self):
        status = parcel_application_status(self.parcel)
        self.assertEqual(status["state"], "not_started")
        self.assertEqual(
            set(status["missing"]),
            {"identity", "transition", "buffers", "map", "land_history"},
        )

    def test_live_model_changes_move_the_status(self):
        self.parcel.apn = "042-031-007"
        self.parcel.date_began_managing = date(2020, 1, 1)
        self.parcel.polygon = [{"lat": 1, "lng": 2}]
        self.parcel.application_answers = {"no_adjoining_prohibited": True}
        self.parcel.save()
        for year in (2023, 2024, 2025):
            ParcelCropHistory.objects.create(parcel=self.parcel, year=year, crop_grown="Walnut")

        status = parcel_application_status(self.parcel)
        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["missing"], [])

    def test_container_production_skips_land_history(self):
        self.parcel.apn = "042-031-007"
        self.parcel.date_began_managing = date(2020, 1, 1)
        self.parcel.polygon = [{"lat": 1, "lng": 2}]
        self.parcel.container_production = True
        self.parcel.application_answers = {"no_adjoining_prohibited": True}
        self.parcel.save()
        self.assertEqual(parcel_application_status(self.parcel)["state"], "complete")

    def test_unanswered_buffer_attestation_is_not_a_claim(self):
        self.parcel.application_answers = {"no_adjoining_prohibited": False}
        self.parcel.save()
        self.assertIn("buffers", parcel_application_status(self.parcel)["missing"])


class ParcelApplicationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="App API Farm")
        self.user = User.objects.create_user(email="app@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="API Ranch", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="Block A", establishment=self.establishment, area=4.0)
        self.client.force_authenticate(user=self.user)

    def _url(self):
        return (
            f"/api/companies/{self.company.id}/establishments/{self.establishment.id}"
            f"/parcels/{self.parcel.id}/application/"
        )

    def test_get_serves_definition_and_bound_values(self):
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["definition"]["key"], "parcel_application")
        self.assertEqual(
            [p["key"] for p in r.data["definition"]["pages"]],
            ["a_location", "b_transition", "c_livestock", "d_buffers", "e_map", "f_land_history"],
        )
        self.assertEqual(r.data["values"]["parcel_name"], "Block A")
        self.assertEqual(r.data["status"]["state"], "not_started")

    def test_put_routes_fields_answers_and_buffers(self):
        r = self.client.put(
            self._url(),
            {
                "values": {
                    "apn": "042-031-007",
                    "date_began_managing": "2020-01-01",
                    "container_production": True,
                    "county": "Yolo",
                    "livestock_present": "no",
                },
                "buffer_zones": [
                    {
                        "direction": "North",
                        "adjoining_land_use": "Conventional almond",
                        "buffer_type": "Vegetative hedgerow",
                        "buffer_width_ft": 26,
                        "crop_grown_in_buffer": "None",
                        "adjacent_is_organic": False,
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)

        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.apn, "042-031-007")
        self.assertEqual(self.parcel.date_began_managing, date(2020, 1, 1))
        self.assertTrue(self.parcel.container_production)
        self.assertEqual(self.parcel.application_answers["county"], "Yolo")
        row = self.parcel.buffer_zones[0]
        self.assertEqual(row["buffer_width_ft"], 26)
        self.assertAlmostEqual(row["buffer_width_m"], 7.9)
        # container + identity + transition + buffers + no map yet
        self.assertEqual(r.data["status"]["missing"], ["map"])

    def test_buffer_prohibited_use_date_roundtrip_and_validation(self):
        # § 205.202(c) — the date the adjoining land last received a prohibited
        # material decides whether that border needs a buffer at all.
        r = self.client.put(
            self._url(),
            {
                "values": {},
                "buffer_zones": [{"direction": "East", "prohibited_use_last_date": "2024-06-15"}],
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.buffer_zones[0]["prohibited_use_last_date"], "2024-06-15")

        r = self.client.put(
            self._url(),
            {
                "values": {},
                "buffer_zones": [{"direction": "East", "prohibited_use_last_date": "last spring"}],
            },
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_put_refuses_unknown_buffer_keys(self):
        r = self.client.put(
            self._url(),
            {"values": {}, "buffer_zones": [{"direction": "North", "sneaky": "x"}]},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("sneaky", str(r.data))

    def test_put_invalid_date_400s(self):
        r = self.client.put(self._url(), {"values": {"date_began_managing": "not-a-date"}}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_outsider_gets_404(self):
        outsider = User.objects.create_user(email="out-app@test.com", password="x")
        other = Company.objects.create(name="Other Co")
        WorksIn.objects.create(user=outsider, company=other, role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(user=outsider)
        self.assertIn(self.client.get(self._url()).status_code, (403, 404))
