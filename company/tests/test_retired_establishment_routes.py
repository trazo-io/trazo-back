"""Establishment routes that were removed for what they CLAIM, not for being unused.

The sibling of `carbon/tests/test_retired_claim_routes_stay_retired.py`, which could not host
these: that module probes `/api/carbon/<prefix>/`, and these are nested company routes.

`carbon_scope_breakdown` is the first entry, and it is worth reading the reason rather than the
status code. It had been answering HTTP 500 for every establishment with any carbon entry: all
six methods it called on `EnhancedCarbonCalculator` had been renamed to private variants, and
with no `__getattr__` the first call raised `AttributeError` into the view's broad
`except Exception`. The only surviving 200 was the early return for a farm with NO carbon data,
which is exactly why nobody reported it. The empty case worked.

Broken is why it was free to delete. It is not why it had to go. What it declared it would
serve had no source behind it:

  * `transparency_score`, from `assess_data_quality()`, a method that did not exist;
  * `industry_percentile`, via `_calculate_percentile_ranking()`, whose own comment read
    "This would use real benchmark data in production" directly above hardcoded returns of
    95 / 75 / 50 / 25 / 10 chosen by emission thresholds;
  * `usda_comparison`, and a `methodology` string reading "USDA/EPA emission factors with GHG
    Protocol scope categorization". `.claude/rules/compliance.md` puts a blanket EPA/USDA
    provenance claim in the UNSAFE column; provenance is per input class
    (`.claude/rules/carbon-methodology.md`).

`trazo-app` declared a response type for it that the endpoint never produced, including an
`roi_estimate` string per improvement opportunity. Deleted in app #55.

The service behind it (`carbon/services/enhanced_carbon_calculator.py`, 445 lines) is deleted
outright. This view was its ONLY instantiation anywhere, and its one public entry point,
`calculate_establishment_carbon_scopes()`, had zero callers in the codebase and zero tests.

A scope breakdown is not forbidden. GHG Protocol scope categorisation over measured quantities
is a legitimate B2B output. If it is wanted, it needs a new endpoint with no percentile, no
invented benchmark and no quality grade, and this entry deleted in the same change that adds it.
"""

from django.test import SimpleTestCase
from django.urls import Resolver404, get_resolver, resolve

#: exact path -> why it may not come back. Probed as given.
RETIRED_ESTABLISHMENT_PATHS = {
    "/api/companies/1/establishments/2/carbon_scope_breakdown/": (
        "carbon_scope_breakdown: served a transparency_score from a method that did not exist, "
        "an industry_percentile from hardcoded 95/75/50/25/10 returns under a comment admitting "
        "it was not real benchmark data, and a methodology string claiming blanket USDA/EPA "
        "provenance that compliance.md forbids. It answered HTTP 500 for every farm with carbon "
        "data, so the shape was never even delivered; a reader would have restored it from the "
        "type declaration rather than from behaviour."
    ),
}

#: The DRF action name the nested router generated. A route can come back through its name
#: under a different path, so both doors are checked, the way the carbon register does it.
RETIRED_ESTABLISHMENT_ROUTE_NAMES = ("company-establishments-carbon-scope-breakdown",)


class RetiredEstablishmentRoutesTests(SimpleTestCase):
    def test_every_entry_has_a_written_reason(self):
        """A path listed with a shrug is not a decision."""
        for path, reason in RETIRED_ESTABLISHMENT_PATHS.items():
            with self.subTest(path=path):
                self.assertGreater(
                    len(reason.strip()),
                    60,
                    "say what the route claimed and which rule it fell foul of, not just 'broken'",
                )

    def test_the_retired_paths_do_not_resolve(self):
        still_routed = []
        for path in RETIRED_ESTABLISHMENT_PATHS:
            try:
                match = resolve(path)
            except Resolver404:
                continue
            still_routed.append("%s -> %s" % (path, match.func))
        self.assertEqual(
            still_routed,
            [],
            "A retired establishment route is registered again. Returning 500 was not the "
            "reason it went; read this module's docstring, and if the payload really is wanted, "
            "delete its entry here in the same change that registers it:\n  " + "\n  ".join(still_routed),
        )

    def test_the_retired_route_names_are_not_registered(self):
        """The other door: re-adding the @action restores the name under any prefix."""
        registered = get_resolver().reverse_dict
        back = [name for name in RETIRED_ESTABLISHMENT_ROUTE_NAMES if name in registered]
        self.assertEqual(back, [], "retired routes are registered again under these names:\n  " + "\n  ".join(back))

    def test_the_checks_above_can_actually_fail(self):
        """A negative assertion must prove it read something.

        Both checks above are satisfied by a URLconf that failed to load, and the name check is
        also satisfied by a typo in RETIRED_ESTABLISHMENT_ROUTE_NAMES: a misspelled name is
        absent from reverse_dict for the wrong reason and the test passes vacuously. So exercise
        each mechanism against sibling actions on the SAME viewset that are still live.
        """
        registered = get_resolver().reverse_dict

        live = resolve("/api/companies/1/establishments/2/dashboard_comprehensive/")
        self.assertEqual(live.url_name, "company-establishments-dashboard-comprehensive")
        self.assertIn("company-establishments-dashboard-comprehensive", registered)

        # A second live action, to show the nested prefix itself is not what is 404ing.
        self.assertEqual(
            resolve("/api/companies/1/establishments/2/certifier-readiness/").url_name,
            "company-establishments-certifier-readiness",
        )

    def test_the_deleted_service_is_not_importable(self):
        """EnhancedCarbonCalculator went with the view. The view was its only instantiation."""
        with self.assertRaises(ImportError):
            from carbon.services.enhanced_carbon_calculator import EnhancedCarbonCalculator  # noqa: F401

    def test_a_kept_carbon_service_is_still_importable(self):
        """Proves the import check above fails on absence, not on a broken carbon.services."""
        from carbon.services.timeline_service import TimelineService  # noqa: F401
