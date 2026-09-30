"""A route that STAYS live must not serve a grade in its payload (2026-09-30).

DIFFERENT FROM `test_retired_claim_routes_stay_retired.py`, and that is the whole reason this file
exists. That one asserts the ABSENCE OF A ROUTE, which is the right shape when the endpoint's only
purpose was the claim. These two routes are not like that: `/api/carbon/entries/summary/` and
`/api/carbon/establishments/<pk>/summary/` serve measured quantities a grower needs, and the grade
was riding along on top. Closing them would take the numbers with it, so the assertion has to be
about payload SHAPE on a live route.

WHAT WAS THERE, until this commit, on authenticated routes any signed-in caller could reach:

  * `carbon_score` in BOTH payloads, computed two different ways: offset percentage x 0.85 in
    `CarbonEntryViewSet.summary`, and a 10-to-95 band ladder in
    `CarbonEstablishmentSummaryViewSet.summary`. Two formulas for one retired concept, which is how
    four of them accumulated before (`serializers_consumer.py` held a fourth).
  * `industry_average`, from `CarbonBenchmark.average_emissions`, which is computed from Trazo's own
    CarbonEntry rows. With no real users that is an average of demo and test data shown to a farmer
    as an industry baseline. It is the DENOMINATOR the `benchmarks` route was unregistered over, so
    the comparison stayed alive on a sibling of the route that was closed for it.
  * `performance_tier`, which returned {"tier": "Excellent", "color": "green", "description":
    "Carbon negative or very low impact"}. A word, A COLOUR, and a sentence of judgement. The colour
    is the part that hides: a self-created label can be a colour and an icon, so stripping the
    number alone would have moved the grade into the palette rather than removing it.
  * `premium_eligibility.premium_percentage`, a hardcoded "10-15%" or "5-10%" keyed off an arbitrary
    1000 kg threshold. `.claude/rules/compliance.md` bans price and premium claims by name, and the
    identical literal had already been removed from a sibling payload on 2026-08-19.

`carbon/urls.py` had recorded all of this in writing as knowingly unfixed. A note is not a guard.

WHY THE CHECK IS A DENYLIST OVER THE WHOLE RESPONSE rather than a list of expected keys: these
payloads carry a dozen legitimate fields and grow, so pinning the exact key set would fail on every
honest addition and get relaxed. What must never come back is a specific, small vocabulary, and a
recursive walk catches it wherever it is nested, including inside `entries_count` or a future
`summary` sub-object.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from carbon.models import CarbonEntry
from company.models import Company
from product.models import Establishment
from users.models import WorksIn

# Keys that must not appear anywhere in a live carbon payload, each a retired claim.
#
# `offset_ratio`, `net_carbon`, `total_emissions` and `total_offsets` are deliberately ABSENT from
# this list: they are measured quantities, not verdicts about them, and a farmer needs them.
FORBIDDEN_KEYS = {
    "carbon_score",
    "transparency_score",
    "efficiency_score",
    "sustainability_score",
    "performance_tier",
    "industry_average",
    "premium_eligibility",
    "premium_percentage",
    "potential_premium",
}

# Grade WORDS, checked on string values as well as keys, because the tier came back as a value.
FORBIDDEN_VALUES = {"excellent", "very good", "needs improvement", "poor performance"}


def walk(node, path="$"):
    """Every (path, key, value) in a nested response, so a claim cannot hide one level down."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield path, key, value
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, (list, tuple)):
        for i, value in enumerate(node):
            yield from walk(value, f"{path}[{i}]")


def assert_carries_no_grade(testcase, payload, where):
    for path, key, value in walk(payload):
        testcase.assertNotIn(
            key,
            FORBIDDEN_KEYS,
            f"{where} serves a retired claim at {path}.{key}. See the docstring in this file: this "
            f"route stays live, so the grade has to be absent from the PAYLOAD.",
        )
        if isinstance(value, str):
            testcase.assertNotIn(
                value.strip().lower(),
                FORBIDDEN_VALUES,
                f"{where} serves the grade WORD {value!r} at {path}.{key}. A tier label is a grade "
                f"whether or not a number came with it.",
            )


class LiveCarbonPayloadsTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="grade@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Grade Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Grade Farm", company=self.company)
        self.client.force_authenticate(user=self.user)

    def emission(self, co2e, year=2026):
        return CarbonEntry.objects.create(
            establishment=self.establishment, type="emission", amount=co2e, co2e_amount=co2e, year=year
        )

    def offset(self, co2e, year=2026):
        return CarbonEntry.objects.create(
            establishment=self.establishment,
            type="offset",
            amount=co2e,
            co2e_amount=-co2e,
            effective_amount=co2e,
            year=year,
        )

    def test_the_entry_summary_carries_no_grade(self):
        response = self.client.get(reverse("carbonentry-summary"), {"establishment": self.establishment.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert_carries_no_grade(self, response.data, "/api/carbon/entries/summary/")

    def test_the_entry_summary_still_serves_the_measured_quantities(self):
        """The point of fixing the payload rather than closing the route.

        If this ever fails, the fix went too far: a grower opening the carbon page needs these, and
        only the verdict about them had to go.
        """
        response = self.client.get(reverse("carbonentry-summary"), {"establishment": self.establishment.id})
        for key in ("total_emissions", "total_offsets", "net_carbon"):
            self.assertIn(key, response.data)

    def test_the_entry_summary_carries_no_grade_with_real_entries(self):
        """WITH DATA, because every score path was guarded by `if total_emissions > 0`.

        An empty establishment took the zero branch and would have looked clean while the scoring
        code was untouched. This is the arrangement that actually exercised it.
        """
        # `amount` is required and offsets are aggregated on `effective_amount`, NOT `co2e_amount`
        # (both summaries do this), so an offset row without it leaves total_offsets at 0 and the
        # score branch never runs, which is the arrangement this test exists to avoid.
        self.emission(100)
        self.offset(60)
        response = self.client.get(
            reverse("carbonentry-summary"), {"establishment": self.establishment.id, "year": 2026}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # NOT VACUOUS: every score path was behind `if total_emissions > 0`, so a payload that came
        # back with zeroes would satisfy the denylist without the scoring code ever executing. These
        # two assertions prove the data actually reached the aggregate.
        self.assertEqual(response.data["total_emissions"], 100)
        self.assertEqual(response.data["total_offsets"], 60)
        assert_carries_no_grade(self, response.data, "/api/carbon/entries/summary/ with entries")

    def test_the_establishment_summary_carries_no_grade(self):
        response = self.client.get(
            reverse("carbon-establishment-summary-summary", args=[self.establishment.id]), {"year": 2026}
        )
        # 200 or a handled error; either way it must not carry a grade.
        assert_carries_no_grade(self, response.data, "/api/carbon/establishments/<pk>/summary/")

    def test_the_establishment_summary_carries_no_grade_with_real_entries(self):
        # Offsets EXCEED emissions on purpose: that took the >= 100% branch, which was the one
        # that produced the highest number and the "Excellent" tier with its green colour.
        self.emission(100)
        self.offset(120)
        response = self.client.get(
            reverse("carbon-establishment-summary-summary", args=[self.establishment.id]), {"year": 2026}
        )
        assert_carries_no_grade(
            self, response.data, "/api/carbon/establishments/<pk>/summary/ with entries carbon-negative"
        )


class TheGuardCanActuallyFailTests(APITestCase):
    """Because a walker with a bug passes everything, silently.

    The repo has shipped guards that asserted nothing: a `/\\bpage\\b/` check that matched its own
    prose, a review that reported green having reviewed nothing. The cheapest defence is a test that
    feeds the checker a known-bad payload and insists it complains.
    """

    def test_a_forbidden_key_is_caught_at_the_top_level(self):
        with self.assertRaises(AssertionError):
            assert_carries_no_grade(self, {"carbon_score": 80}, "fixture")

    def test_a_forbidden_key_is_caught_when_NESTED(self):
        # The nesting case is the one a flat `in response.data` check misses.
        with self.assertRaises(AssertionError):
            assert_carries_no_grade(self, {"data": {"summary": {"performance_tier": {"tier": "Good"}}}}, "fixture")

    def test_a_forbidden_key_is_caught_inside_a_list(self):
        with self.assertRaises(AssertionError):
            assert_carries_no_grade(self, {"rows": [{"ok": 1}, {"industry_average": 3.0}]}, "fixture")

    def test_a_grade_word_is_caught_as_a_VALUE(self):
        # `performance_tier` renamed to something innocuous still returns "Excellent".
        with self.assertRaises(AssertionError):
            assert_carries_no_grade(self, {"standing": "Excellent"}, "fixture")

    def test_a_measured_quantity_is_not_caught(self):
        # The guard must not be so broad that the honest payload trips it.
        assert_carries_no_grade(self, {"total_emissions": 10, "net_carbon": -2, "offset_ratio": 120.0}, "fixture")
