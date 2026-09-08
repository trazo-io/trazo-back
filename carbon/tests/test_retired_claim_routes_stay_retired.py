"""
Routes that were retired because of what they CLAIM, not because they were unused.

Unused is why they were easy to remove. It is not why they had to go.

`SustainabilityBadge` is a grade this product awards itself. EU ECGT 2024/825 (live 2026-09-27)
bans self-created sustainability labels without third-party verification, and
`.claude/rules/transparency-first.md` had already pulled every badge widget off every rendered
surface. What survived that removal was the API: `GET /api/carbon/badges/` still returned badge
rows to any authenticated caller, with nothing in front of it. `green-points` is the same shape
with a different noun. The offset marketplace — projects, purchases, and a route literally called
`offset-certificates` — is pre-pivot: Trazo measures direct operational emissions and makes no
offset claim, so a "certificate" endpoint is the sharpest unearned word in the codebase.

The audit that found them (`documentation/audits/CARBON_SURFACE_AUDIT_2026-09-07.md`) also found
why this is worth a test rather than a delete: **a route is the part that gets rediscovered.**
Six months from now the models are still there, the serializers are still there, and the viewsets
are still there — someone wiring a dashboard finds `SustainabilityBadgeViewSet`, registers it in
four characters, and the claim is back with no discussion. Re-registering one of these is a
product decision about what Trazo asserts, and this test is where that decision has to be made
out loud.

The models are deliberately NOT dropped. That is a separate call with a migration behind it, and
it is not the part that leaks.
"""

from django.test import SimpleTestCase
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

#: route prefix -> why it may not come back.
RETIRED_CLAIM_ROUTES = {
    "badges": (
        "SustainabilityBadge: a self-assigned sustainability grade. EU ECGT 2024/825 bans "
        "self-created sustainability labels without third-party verification; the widgets were "
        "removed in 2026-08 and this endpoint outlived them."
    ),
    "green-points": (
        "GreenPoints: gamification score Trazo invents about itself. Same class as badges — a "
        "grade with the number filed off is still a grade."
    ),
    "micro-offsets": (
        "MicroOffset: consumer micro-offset purchases from the pre-pivot offset marketplace. "
        "Trazo makes no offset claim."
    ),
    "offset-projects": "CarbonOffsetProject: pre-pivot offset marketplace. No offset claim is made.",
    "offset-purchases": "CarbonOffsetPurchase: pre-pivot offset marketplace. No offset claim is made.",
    "offsets": (
        "CarbonOffsetViewSet.certified_projects: served CarbonOffsetProject rows decorated with a "
        "hardcoded verification_badges dict reading 'VCS Verified'. A third-party verification "
        "claim we wrote ourselves about our own rows — the UNSAFE column of compliance.md."
    ),
    "offset-certificates": (
        "CarbonOffsetCertificate: a 'certificate' nobody audits, issued by us, about us. The "
        "single strongest unearned word the carbon app ever exposed."
    ),
}

#: The DRF basenames those routers would have produced. Kept separate from the prefixes because
#: `reverse()` works on names and `resolve()` works on paths, and a route can come back through
#: either door.
RETIRED_ROUTE_NAMES = (
    "sustainabilitybadge-list",
    "greenpoints-list",
    "microoffset-list",
    "carbonoffsetproject-list",
    "carbonoffsetpurchase-list",
    "carbonoffsetcertificate-list",
    "carbon-offset-list",
    "carbon-offset-certified-projects",
)


class RetiredClaimRoutesTests(SimpleTestCase):
    def test_every_retired_prefix_has_a_written_reason(self):
        """The register is the point. A prefix listed with a shrug is not a decision."""
        for prefix, reason in RETIRED_CLAIM_ROUTES.items():
            with self.subTest(route=prefix):
                self.assertGreater(
                    len(reason.strip()),
                    60,
                    "say what the route claimed and which rule it fell foul of, not just 'unused'",
                )

    def test_the_retired_routes_do_not_resolve(self):
        still_routed = []
        for prefix in RETIRED_CLAIM_ROUTES:
            try:
                match = resolve(f"/api/carbon/{prefix}/")
            except Resolver404:
                continue
            still_routed.append(f"/api/carbon/{prefix}/ -> {match.func}")
        self.assertEqual(
            still_routed,
            [],
            "A retired claim route is registered again. Removing it is not a refactor to undo — "
            "read this module's docstring, and if the claim really is wanted, delete its entry "
            "from RETIRED_CLAIM_ROUTES in the same change that registers it:\n  " + "\n  ".join(still_routed),
        )

    def test_the_retired_route_names_are_not_reversible(self):
        """The other door: a viewset re-registered under any prefix restores these names."""
        reversible = []
        for name in RETIRED_ROUTE_NAMES:
            try:
                reversible.append(f"{name} -> {reverse(name)}")
            except NoReverseMatch:
                continue
        self.assertEqual(reversible, [], "retired viewsets are routed again:\n  " + "\n  ".join(reversible))

    def test_the_checks_above_can_actually_fail(self):
        """A negative assertion has to prove it read something.

        Both checks above are satisfied by a URLconf that failed to load, and the `reverse()` one
        is also satisfied by a typo in RETIRED_ROUTE_NAMES — a misspelled name raises
        NoReverseMatch for the wrong reason and the test passes vacuously. So exercise both
        mechanisms against a route that IS live. If either line here breaks, the two checks above
        are proving nothing and must be fixed before they are trusted.
        """
        match = resolve("/api/carbon/entries/")
        self.assertEqual(match.url_name, "carbonentry-list")
        self.assertEqual(reverse("carbonentry-list"), "/api/carbon/entries/")
