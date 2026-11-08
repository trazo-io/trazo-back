"""No self-assigned 0-100 score leaves the backend, on any carbon payload (2026-11-08).

The score is retired as a CONCEPT (EU ECGT 2024/825, FTC 16 CFR 260.4), not merely hidden. By
2026-11-07 no surface rendered one, but `efficiency_score` was still produced in about sixty
places and served unrenamed on authenticated payloads that test_live_carbon_payloads_carry_no_grade
never exercised:

* `calculate-event-carbon/` (OptimizedCarbonCalculator: a band ladder 90/80/70/60, and
  `confidence_level * 100`), which also wrote every result's score into an
  OptimizedCarbonCalculation row that nothing ever read;
* `calculate-event-impact/`, `enhanced-event-impact/`, `calculator/calculate/`
  (EventCarbonCalculator: fixed 70.0, 85.0, 100.0 "perfect score for no emissions");
* `carbon_data` on every event in `/api/events/` and `/api/histories/<id>/`
  (`"efficiency_score": 90.0 if factors_based else 75.0`, invented in the serializer);
* `carbon_efficiency_score` on an establishment's comprehensive dashboard, `carbon_score` on the
  scan list (always 0: History has no such field).

A payload nobody renders is still a claim the next component can render. Two guards:

1. SOURCE: no production module may name the keys at all. Routes multiply and fixtures go stale;
   a string literal cannot hide from an AST walk. `carbon/models.py` is the one exemption, with
   its reason: `OptimizedCarbonCalculation.efficiency_score` is a stored column, retired in its own
   slice, and nothing writes it any more (asserted below).
2. LIVE: the event serializer's `carbon_data` and `calculate-event-carbon/` for every event type,
   walked with the same `assert_carries_no_grade` the summary routes use.
"""

import ast
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from rest_framework.test import APITestCase

from carbon.models import CarbonEntry, OptimizedCarbonCalculation
from carbon.tests.test_live_carbon_payloads_carry_no_grade import assert_carries_no_grade
from company.models import Company, Establishment
from history.models import History, PestManagementEvent
from history.serializers import PestManagementEventSerializer
from product.models import Parcel
from users.models import WorksIn

BACKEND = Path(__file__).resolve().parents[2]
RETIRED_KEYS = {"efficiency_score", "carbon_efficiency_score", "carbon_score"}
APPS = ("carbon", "history", "company", "common", "notifications", "certifications", "documents", "backend")
#: path -> why it may still name a retired key.
EXEMPT = {
    "carbon/models.py": (
        "OptimizedCarbonCalculation.efficiency_score is a stored column and its index; the model "
        "retires in its own migration slice. Nothing writes it (see the live test)."
    ),
    "history/models_consumer.py": (
        "UserLocalRecommendation.carbon_score, a stored 0-100 field on a shopper model with 0 rows "
        "in production. Its serializer no longer emits it; the shopper models retire in their own "
        "migration slice (review of #347)."
    ),
}


def _production_modules():
    for app in APPS:
        for path in sorted((BACKEND / app).rglob("*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if any(part in ("tests", "migrations", "management") for part in path.parts) or rel in EXEMPT:
                continue
            if path.name.startswith("test_"):
                continue
            yield rel, path


def _string_literals(source):
    """Every name a module could carry a score under: string literals (dict keys, serializer field
    lists), variable and field names, attributes, keyword arguments, function and parameter names.
    Literals alone missed a model field declared as `carbon_score = models.IntegerField(...)`
    (review of #347)."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.Name):
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute):
            yield node.lineno, node.attr
        elif isinstance(node, (ast.keyword, ast.arg)) and getattr(node, "arg", None):
            yield getattr(node, "lineno", 0), node.arg
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.lineno, node.name


class NoModuleNamesARetiredScoreTests(APITestCase):
    def test_no_production_module_names_a_retired_score_key(self):
        offenders, read = [], 0
        for rel, path in _production_modules():
            read += 1
            for lineno, value in _string_literals(path.read_text()):
                if value in RETIRED_KEYS:
                    offenders.append(f"{rel}:{lineno}: {value!r}")
        self.assertGreater(read, 100, "the walk read almost nothing; it is proving nothing")
        self.assertEqual(
            offenders,
            [],
            "A retired 0-100 score is back in a payload builder. The score is retired as a concept, "
            "not hidden: do not rename it, do not add it to a response.\n  " + "\n  ".join(offenders),
        )

    def test_the_exemptions_still_need_to_exist(self):
        for rel in EXEMPT:
            source = (BACKEND / rel).read_text()
            self.assertTrue(
                any(value in RETIRED_KEYS for _, value in _string_literals(source)),
                f"{rel} no longer names a retired key: drop its exemption.",
            )


class LivePayloadsCarryNoScoreTests(APITestCase):
    def setUp(self):
        cache.clear()  # calculate-event-carbon/ answers from the cache when it can
        company = Company.objects.create(name="Score Co")
        self.establishment = Establishment.objects.create(name="Score Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=self.establishment, area=2)
        self.season = History.objects.create(parcel=parcel, name="2026", start_date=timezone.now())
        user = get_user_model().objects.create_user(email="score@example.com", password="x")
        WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(user)

    def test_an_events_carbon_data_carries_no_score(self):
        event = PestManagementEvent.objects.create(
            history=self.season, type="SC", description="scouting", date=timezone.now()
        )
        event.refresh_from_db()
        CarbonEntry.objects.filter(production=self.season).delete()  # whatever the receivers wrote
        CarbonEntry.objects.create(
            production=self.season,
            establishment=self.establishment,
            activity_id=event.activity_id,
            type="emission",
            amount=4.0,
            co2e_amount=4.0,
            year=timezone.now().year,
            usda_factors_based=True,
        )
        carbon_data = PestManagementEventSerializer(event).data["carbon_data"]
        self.assertEqual(carbon_data["co2e"], 4.0)  # the entry was found: the walk reads a real payload
        assert_carries_no_grade(self, carbon_data, "EventSerializer.carbon_data")

    def test_calculate_event_carbon_carries_no_score_and_writes_no_score_row(self):
        payloads = {
            "chemical": {"volume": "10", "volume_unit": "L", "area": "1", "area_unit": "acres", "type": "HE"},
            "production": {"type": "IR", "area": "1", "area_unit": "acres"},
            "equipment": {"type": "FC", "fuel_amount": "20", "fuel_unit": "liters", "fuel_type": "diesel"},
            "weather": {"type": "FR"},
            "soil_management": {"type": "ST"},
            "pest_management": {"type": "SC"},
            "business": {"type": "SA"},
            "general": {"description": "Crew meeting"},
        }
        for event_type, event_data in payloads.items():
            with self.subTest(event_type=event_type):
                response = self.client.post(
                    "/api/carbon/calculate-event-carbon/",
                    {"event_type": event_type, "event_data": event_data},
                    format="json",
                )
                # A 500's error dict carries no score either, so a failing route would pass the
                # walk below for the wrong reason (review of #347).
                self.assertEqual(response.status_code, 200, response.content)
                self.assertIsInstance(response.json(), dict, response.content)
                assert_carries_no_grade(self, response.json(), f"calculate-event-carbon/ ({event_type})")
        self.assertEqual(OptimizedCarbonCalculation.objects.count(), 0)
