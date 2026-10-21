"""Every route carries a written answer to "whose rows can a caller reach through it".

`backend/permissions.py` returns True whenever `view.company is None`, which is every flat route.
On those routes tenancy is whatever the view's own queryset happens to do, and on 2026-09-28 that
was nothing for seven of them (`company/tests/test_cross_tenant_routes.py`). Those seven were found
by a person probing routers by hand, which only finds the routes the person thought of.

This guard inverts that the way `test_anonymous_endpoint_inventory` did for public endpoints: a new
route fails CI until `backend/route_tenancy.py` declares its scope with a reason. It cannot tell you
a route is ISOLATED. It tells you nobody added one without saying who it belongs to, and it keeps
the count of company-scoped routes that no outsider test has ever exercised from growing.

Declarations are per VIEW, but routes are per ACTION: a new `@action` on a declared viewset adds no
new view. `backend/route_tenancy_routes.txt` is the per-route snapshot (path, view, permissions,
action), so that change cannot land without a diff in the same PR as the registry it may invalidate.
"""

import importlib
import os
import re
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from backend.route_tenancy import (
    ANONYMOUS,
    COMPANY,
    OPEN_FINDINGS_CEILING,
    ROUTE_TENANCY,
    SCOPES,
    STAFF,
    UNPROVEN_CEILING,
    USER,
)
from history.tests.test_anonymous_endpoint_inventory import REVIEWED_ANONYMOUS_ENDPOINTS, _view_identity

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO / "backend" / "route_tenancy_routes.txt"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"

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


def _snapshot_lines():
    """One line per route: path, view, permission signature, router action map."""
    lines = set()
    for route, pattern in _walk(get_resolver()):
        if route.startswith(SKIPPED_PREFIXES):
            continue
        _, permissions = _view_identity(pattern)
        actions = getattr(pattern.callback, "actions", None) or {}
        action_text = ",".join(f"{method}={name}" for method, name in sorted(actions.items())) or "-"
        lines.add(f"{route}\t{_view_key(pattern.callback)}\t{','.join(permissions) or 'EMPTY'}\t{action_text}")
    return sorted(lines)


def _is_anonymous(permissions):
    """The public inventory's definition: AllowAny, no checks at all, or no DRF layer."""
    return not permissions or any("AllowAny" in name for name in permissions) or permissions == ["NON-DRF"]


def _ci_modules():
    """Test labels passed to `manage.py test` in ci.yml, one per continued line."""
    return set(re.findall(r"^ {12}([a-z_][a-z0-9_.]*) \\$", CI_WORKFLOW.read_text(), re.MULTILINE))


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

    def test_open_findings_only_go_down(self):
        """Ratchet over every scope. A DEAD or CATALOG route can carry a cross-tenant write too
        (`john_deere_webhook`, `CarbonSourceViewSet`), and the unproven count above never sees
        them. Close a finding by replacing it with an outsider test, then lower the ceiling."""
        open_findings = sorted(k for k, r in ROUTE_TENANCY.items() if r.finding)
        self.assertEqual(
            len(open_findings),
            OPEN_FINDINGS_CEILING,
            f"{len(open_findings)} declarations carry a finding (ceiling {OPEN_FINDINGS_CEILING}). A new "
            "finding means a new leak to fix, not a ceiling to raise; a closed one means lower the ceiling.",
        )

    def test_outsider_tests_run_in_ci(self):
        """A proof that CI never runs proves nothing: a regression in it would ship green."""
        ci = _ci_modules()
        for key, route in ROUTE_TENANCY.items():
            for dotted in route.outsider_tests:
                module = dotted.rsplit(".", 2)[0]
                parts = module.split(".")
                prefixes = {".".join(parts[:i]) for i in range(1, len(parts) + 1)}
                with self.subTest(view=key, module=module):
                    self.assertTrue(prefixes & ci, f"{module} proves {key} but is not in ci.yml's test list")

    def test_route_snapshot_is_current(self):
        """Every route, per action. Regenerate with ROUTE_TENANCY_UPDATE_SNAPSHOT=1, then re-read the
        declaration of every view whose lines changed: a new action can widen a view's scope."""
        current = _snapshot_lines()
        if os.environ.get("ROUTE_TENANCY_UPDATE_SNAPSHOT") == "1":
            SNAPSHOT.write_text("\n".join(current) + "\n")
        recorded = SNAPSHOT.read_text().splitlines()
        added = sorted(set(current) - set(recorded))
        removed = sorted(set(recorded) - set(current))
        self.assertEqual(
            (added, removed),
            ([], []),
            "Routes changed since backend/route_tenancy_routes.txt was written.\n"
            + "".join(f"  + {line}\n" for line in added)
            + "".join(f"  - {line}\n" for line in removed)
            + "Check each changed view's ROUTE_TENANCY declaration still holds, then regenerate.",
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
        """ANONYMOUS defers to the claim/PII review in test_anonymous_endpoint_inventory.

        Matched on the inventory's FULL key, `<view>::<permissions>`, built by its own
        `_view_identity`: a bare name would let a new view reuse an approval it never earned.
        """
        anonymous_routes = {}
        for route, pattern in _walk(get_resolver()):
            key = _view_key(pattern.callback)
            declared = ROUTE_TENANCY.get(key)
            # The public inventory reviews `api/` only; health probes live outside it.
            if not route.startswith("api/") or declared is None or declared.scope != ANONYMOUS:
                continue
            name, permissions = _view_identity(pattern)
            if not _is_anonymous(permissions):
                continue  # a signed-in action on a mostly public view
            anonymous_routes.setdefault(key, []).append(route)
            entry = f"{name}::{','.join(permissions) or 'EMPTY'}"
            with self.subTest(view=key, route=route):
                self.assertIn(
                    entry, REVIEWED_ANONYMOUS_ENDPOINTS, f"{key} is declared ANONYMOUS; {entry} is unreviewed"
                )
        for key, route in ROUTE_TENANCY.items():
            if route.scope != ANONYMOUS or key.startswith("health."):
                continue
            with self.subTest(view=key):
                self.assertIn(key, anonymous_routes, f"{key} is declared ANONYMOUS but no route of it is anonymous")
