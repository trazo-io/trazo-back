"""An activity must not be filed against a guessed season.

`Parcel.current_history` is ONE pointer and it holds whichever season was started last. A
perennial block routinely carries two open seasons at once — last year's crop still being
picked while the next one is under way — and in that state the fallback silently picked one.

Found live on 2026-08-20: an application logged from the 2025 season's own page, dated
14 May 2025, was written to the 2026 season, which had not yet begun. The 2025 packet showed
no record; the 2026 packet showed an application from before its own start date. Nothing
surfaced it. That is a misfiled record in the § 205.103(b)(2) trace-back.

Where the caller knows the season it sends `history`. Where it does not, and the answer is
genuinely ambiguous, the request is REFUSED rather than guessed.
"""

from datetime import timedelta

from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import Production, WeatherEvent
from product.models import Parcel, Product
from users.models import User


class AmbiguousSeasonTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="amb@t.test", password="x")
        company = Company.objects.create(name="Amb Co")
        # A real grower is a MEMBER of the company they log against. The fixture omitted this and
        # the create path did not care, because it resolved `parcels` from request data with an
        # unscoped queryset (fixed 2026-09-16, see test_event_tenancy.EventCrossTenantCreateTests).
        # Without the membership this suite's user is a stranger writing to a stranger's parcel,
        # which is the vulnerability, not the behaviour under test here.
        self.user.companies.add(company)
        self.est = Establishment.objects.create(name="Amb Farm", company=company)
        self.parcel = Parcel.objects.create(name="Block", establishment=self.est, area=4.0)
        self.crop = CropType.objects.create(
            name="Apple",
            slug="apple-amb",
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
        self.client.force_authenticate(self.user)

    def _season(self, name, days_ago, finished=False):
        h = Production.objects.create(
            parcel=self.parcel,
            product=self.product,
            crop_type=self.crop,
            name=name,
            start_date=timezone.now() - timedelta(days=days_ago),
            finish_date=timezone.now() - timedelta(days=1) if finished else None,
        )
        self.parcel.current_history = h
        self.parcel.save(update_fields=["current_history"])
        return h

    def _post(self, payload):
        return self.client.post("/api/events/", payload, format="json")

    def _weather_payload(self, **extra):
        base = {
            "parcels": [self.parcel.id],
            "event_type": 0,
            "type": "HT",
            "date": timezone.now().isoformat(),
            "description": "Heat event",
            "observation": "104F on the ridge",
        }
        base.update(extra)
        return base

    def test_one_open_season_still_resolves_without_an_explicit_history(self):
        """The common case must keep working — the guard is for ambiguity only."""
        only = self._season("2025 season", 200)
        resp = self._post(self._weather_payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(WeatherEvent.objects.get().history_id, only.id)

    def test_two_open_seasons_without_a_history_is_refused_and_names_them(self):
        older = self._season("Honeycrisp 2025", 400)
        newer = self._season("Honeycrisp 2026", 60)
        resp = self._post(self._weather_payload())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        detail = str(resp.data)
        self.assertIn("more than one open production", detail)
        # Naming them is the point — the farmer has to be able to pick.
        self.assertIn(older.name, detail)
        self.assertIn(newer.name, detail)
        self.assertEqual(WeatherEvent.objects.count(), 0, "nothing may be written while ambiguous")

    def test_an_explicit_history_wins_over_the_pointer(self):
        older = self._season("Honeycrisp 2025", 400)
        self._season("Honeycrisp 2026", 60)  # becomes current_history
        resp = self._post(self._weather_payload(history=older.id))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(
            WeatherEvent.objects.get().history_id,
            older.id,
            "the named season must win over parcel.current_history",
        )

    def test_a_finished_season_does_not_make_the_parcel_ambiguous(self):
        """Only OPEN seasons compete. A closed one is not a candidate."""
        self._season("Honeycrisp 2024", 700, finished=True)
        open_one = self._season("Honeycrisp 2025", 200)
        resp = self._post(self._weather_payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(WeatherEvent.objects.get().history_id, open_one.id)

    def test_a_non_numeric_history_is_refused_not_crashed(self):
        """`?production=` carries a UUID on the season-plan path and a pk from the production
        page. The serializer validates `history` as a PK, so the UUID is refused at the door —
        a 400, never a 500, and nothing written. The frontend sends the numeric id.
        """
        self._season("Honeycrisp 2025", 400)
        self._season("Honeycrisp 2026", 60)
        for bad in ("not-a-uuid-or-a-number", "20f63409-ea43-48ac-8979-c61d9e6a243f"):
            resp = self._post(self._weather_payload(history=bad))
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, bad)
        self.assertEqual(WeatherEvent.objects.count(), 0)

    def test_a_history_belonging_to_another_parcel_is_refused(self):
        """The serializer only checks the FK exists — not that it is THIS parcel's season.

        Without the parcel filter in perform_create, naming another block's production would
        file the record against a season on land the activity never happened on.
        """
        mine = self._season("Ridge 2025", 200)
        other_parcel = Parcel.objects.create(name="Creek", establishment=self.est, area=3.0)
        theirs = Production.objects.create(
            parcel=other_parcel,
            product=self.product,
            crop_type=self.crop,
            name="Creek 2025",
            start_date=timezone.now() - timedelta(days=200),
        )
        resp = self._post(self._weather_payload(history=theirs.id))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertIn("No production", str(resp.data))
        self.assertEqual(WeatherEvent.objects.count(), 0)
        self.assertEqual(Production.objects.filter(pk=mine.pk).count(), 1)


class SeasonRefusalsCarryACodeTests(AmbiguousSeasonTests):
    """Each refusal keeps its English sentence and adds `error_codes`, so the app can word it in the
    reader's language (recordkeeping checklist run 2026-11-16, VID-07: a Spanish grower read these in
    English). Runs the parent's tests too; they must keep passing with the codes added."""

    def _code(self, resp, key):
        return {k: str(v) for k, v in resp.data["error_codes"][key].items()}

    def test_two_open_seasons_names_them_in_the_code(self):
        self._season("Honeycrisp 2025", 400)
        self._season("Honeycrisp 2026", 60)
        resp = self._post(self._weather_payload())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("more than one open production", str(resp.data["history"][0]))
        self.assertEqual(
            self._code(resp, "history"),
            {"code": "season_ambiguous", "seasons": "Honeycrisp 2026, Honeycrisp 2025"},
        )

    def test_a_season_the_parcel_does_not_have(self):
        self._season("Honeycrisp 2026", 60)
        elsewhere = Production.objects.create(
            parcel=Parcel.objects.create(name="Other Block", establishment=self.est, area=2.0),
            product=self.product,
            crop_type=self.crop,
            name="Other Block 2026",
            start_date=timezone.now() - timedelta(days=30),
        )
        resp = self._post(self._weather_payload(history=elsewhere.id))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._code(resp, "history"), {"code": "season_not_on_parcel"})

    def test_a_parcel_with_no_season(self):
        resp = self._post(self._weather_payload())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No active production", str(resp.data["detail"][0]))
        self.assertEqual(self._code(resp, "detail"), {"code": "no_open_season"})

    def test_a_record_dated_inside_a_finished_season(self):
        finished = self._season("Honeycrisp 2025", 400, finished=True)
        resp = self._post(
            self._weather_payload(history=finished.id, date=(timezone.now() - timedelta(days=3)).isoformat())
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("closed record", resp.data["detail"])
        self.assertEqual(
            self._code(resp, "detail"),
            {"code": "season_closed", "finish_date": timezone.localdate(finished.finish_date).isoformat()},
        )
        self.assertEqual(WeatherEvent.objects.count(), 0)
