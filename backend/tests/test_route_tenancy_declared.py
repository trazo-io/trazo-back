"""Every route carries a written answer to "whose rows can a caller reach through it".

`backend/permissions.py` returns True whenever `view.company is None`, which is every flat route.
On those routes tenancy is whatever the view's own queryset happens to do, and on 2026-09-28 that
was nothing for seven of them (`company/tests/test_cross_tenant_routes.py`). Those seven were found
by a person probing routers by hand, which only finds the routes the person thought of.

This guard inverts that the way `test_anonymous_endpoint_inventory` did for public endpoints: a new
route fails CI until `backend/route_tenancy.py` declares its scope with a reason. It cannot tell you
a route is ISOLATED. It tells you nobody added one without saying who it belongs to, and it keeps
the count of company-scoped routes that no outsider test has ever exercised from growing.
"""

import importlib

from django.test import SimpleTestCase
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from backend.route_tenancy import ANONYMOUS, COMPANY, ROUTE_TENANCY, SCOPES, STAFF, UNPROVEN_CEILING, USER
from history.tests.test_anonymous_endpoint_inventory import REVIEWED_ANONYMOUS_ENDPOINTS, _view_identity

# Staff-only by construction: AdminSite.admin_view wraps every one of these in a staff check.
SKIPPED_PREFIXES = ("admin/",)


def _walk(resolver, prefix=""):
    for pattern in resolver.url_patterns:
        full = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            yield from _walk(pattern, full)
        elif isinstance(pattern, URLPattern):
            yield full, pattern


def _view_key(callback):
    """Module-qualified view name.

    `@api_view` functions surface as a `WrappedAPIView` class renamed to the function, so the
    class `__name__` is the function name; `__qualname__` would be the decorator's local class.
    """
    # `cls` on DRF views, `view_class` on plain Django class-based views.
    view_class = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
    if view_class is not None:
        return f"{view_class.__module__}.{view_class.__name__}"
    return f"{callback.__module__}.{getattr(callback, '__name__', repr(callback))}"


def _routes():
    found = {}
    for route, pattern in _walk(get_resolver()):
        if route.startswith(SKIPPED_PREFIXES):
            continue
        found.setdefault(_view_key(pattern.callback), set()).add(route)
    return found


def _view_class(key):
    """The class behind a key; an `@api_view` function's module attribute is the wrapper view."""
    module, _, name = key.rpartition(".")
    view = getattr(importlib.import_module(module), name)
    return getattr(view, "cls", view)


class RouteTenancyDeclaredTests(SimpleTestCase):
    def test_every_route_declares_its_scope(self):
        found = _routes()
        undeclared = sorted(set(found) - set(ROUTE_TENANCY))
        detail = "\n".join(f"  {key}\n     routes: {sorted(found[key])[:3]}" for key in undeclared)
        self.assertEqual(
            undeclared,
            [],
            "Route(s) with no tenancy declaration.\n\n"
            f"{detail}\n\n"
            "Add each to ROUTE_TENANCY in backend/route_tenancy.py: which caller may reach which "
            "rows, and where the code enforces it. On a flat route the permission classes check "
            "nothing about the company, so the answer is the queryset, not the permission.",
        )

    def test_no_stale_declarations(self):
        """An entry for a route that is gone silently re-approves it if it comes back."""
        stale = sorted(set(ROUTE_TENANCY) - set(_routes()))
        self.assertEqual(stale, [], f"ROUTE_TENANCY declares routes that no longer exist: {stale}")

    def test_the_walk_actually_finds_routes(self):
        """Guards the guard: a walker returning nothing would pass both tests above."""
        found = _routes()
        self.assertGreaterEqual(len(found), 150, f"Only {len(found)} views discovered; the walk is broken.")
        self.assertIn("company.views.CompanyViewSet", found)
        self.assertIn("carbon.views.get_crop_templates", found)  # an @api_view function

    def test_every_scope_is_known_and_every_reason_written(self):
        for key, route in ROUTE_TENANCY.items():
            with self.subTest(view=key):
                self.assertIn(route.scope, SCOPES)
                self.assertTrue(route.why.strip(), "a declaration with no reason is not a decision")

    def test_outsider_tests_exist(self):
        """A proof that names a renamed or deleted test proves nothing."""
        for key, route in ROUTE_TENANCY.items():
            for dotted in route.outsider_tests:
                with self.subTest(view=key, test=dotted):
                    module, cls, method = dotted.rsplit(".", 2)
                    test_class = getattr(importlib.import_module(module), cls)
                    self.assertTrue(callable(getattr(test_class, method, None)), f"{dotted} does not exist")

    def test_unproven_tenant_routes_only_go_down(self):
        """Ratchet. Lower UNPROVEN_CEILING when an outsider test lands; never raise it."""
        unproven = sorted(k for k, r in ROUTE_TENANCY.items() if r.scope in (COMPANY, USER) and not r.outsider_tests)
        self.assertLessEqual(
            len(unproven),
            UNPROVEN_CEILING,
            f"{len(unproven)} company/user-scoped views have no outsider test (ceiling {UNPROVEN_CEILING}). "
            "A new tenant route ships with a test that an outsider account is refused.",
        )
        self.assertEqual(
            len(unproven),
            UNPROVEN_CEILING,
            f"Unproven count fell to {len(unproven)}: lower UNPROVEN_CEILING to match so it cannot creep back.",
        )

    def test_staff_declarations_match_the_permission_classes(self):
        """STAFF is the one scope a permission class can prove on its own, so check it does."""
        for key, route in ROUTE_TENANCY.items():
            if route.scope != STAFF or "." not in key:
                continue
            with self.subTest(view=key):
                view = _view_class(key)
                names = {getattr(p, "__name__", "") for p in getattr(view, "permission_classes", [])}
                self.assertTrue(names & {"IsAdminUser", "IsSuperUser"}, f"{key} declared STAFF but permits {names}")

    def test_anonymous_declarations_are_on_the_reviewed_public_list(self):
        """ANONYMOUS defers to the claim/PII review in test_anonymous_endpoint_inventory; it must be there.

        Names come from that inventory's own `_view_identity`, so the two guards cannot disagree
        about what a view is called.
        """
        reviewed = {entry.split("::")[0] for entry in REVIEWED_ANONYMOUS_ENDPOINTS}
        for route, pattern in _walk(get_resolver()):
            key = _view_key(pattern.callback)
            # The public inventory reviews `api/` only; health probes live outside it.
            declared = ROUTE_TENANCY.get(key)
            if not route.startswith("api/") or declared is None or declared.scope != ANONYMOUS:
                continue
            with self.subTest(view=key, route=route):
                self.assertIn(
                    _view_identity(pattern)[0],
                    reviewed,
                    f"{key} is declared ANONYMOUS but has no entry in REVIEWED_ANONYMOUS_ENDPOINTS",
                )
