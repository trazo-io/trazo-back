"""`productions/` serves exactly what `histories/` serves (expand step, 2026-11-15).

The model has been `Production` since history 0264, and the API still said `histories`. Renaming a
path the app calls takes two deploys: the backend serves BOTH names, the app moves to the new one,
and only then does the old one go. A twin that resolved to another view, or to the same view with
a different action map or permission signature, would turn that move into a behaviour change
nobody reviewed. These tests compare every twin with its original, so the contract step can
delete `histories` knowing each call the app moved lands where it landed before.

Out of scope on purpose, because the app never calls them (the contract step deletes them):
- the reviews route nested under `parcels/<id>/histories/<id>/reviews/` (the app uses the flat
  `reviews/` route). Its router is built on the parcel router's `histories` registration, so
  the contract step must delete both together or company/urls.py fails at import;
- `establishments/<id>/histories/` (`FARM_HISTORIES_URL` had no caller);
- `parcels/<id>/history/` (`ParcelViewSet.history`, no caller).
Payload keys (`history`, `history_id`) are a separate change.
"""

import re

from django.test import SimpleTestCase, TestCase
from django.urls import get_resolver

from rest_framework.test import APIClient

from backend.tests.test_route_tenancy_declared import _view_key, _walk
from carbon.middleware.security_middleware import CarbonAuditMiddleware, CarbonSecurityMiddleware
from company.models import Company, Establishment
from history.models import Production
from history.tests.test_anonymous_endpoint_inventory import _view_identity
from product.models import Parcel
from users.constants import PRODUCER
from users.models import User, WorksIn

_OLD_PREFIX = re.compile(r"(?<![a-z_-])histories/")
_NESTED_REVIEWS = "(?P<history_pk>"
# Parcel actions named after the old model, and the names they are also served under.
_PARCEL_ACTIONS = {"current_history": "current_production", "finish_history": "finish_production"}
# Parcel actions named after the old model that get no twin, because nothing calls them.
_PARCEL_NO_CALLER = {"history"}
# initkwargs that only name the route; everything else (permission, parser, throttle classes set
# on the @action) changes what a caller gets and must match between twins.
_NAMING_KWARGS = {"name", "basename", "suffix", "description"}
_PARCEL_VIEW = "product.views.ParcelViewSet"
_NO_CALLER = {"company.views.EstablishmentViewSet"}


def _signature(pattern):
    """View, HTTP methods, permission classes and per-action overrides: what a caller gets."""
    # DRF adds `head` to the shared actions dict on the first GET it serves; it mirrors `get`.
    actions = getattr(pattern.callback, "actions", None) or {}
    _, permissions = _view_identity(pattern)
    overrides = {
        k: v for k, v in (getattr(pattern.callback, "initkwargs", None) or {}).items() if k not in _NAMING_KWARGS
    }
    return (
        _view_key(pattern.callback),
        {m: a for m, a in actions.items() if m != "head"},
        tuple(permissions),
        overrides,
    )


def _routes():
    return {route: pattern for route, pattern in _walk(get_resolver()) if not route.startswith("admin/")}


def _pairs():
    """(old route, new route) for every route the app may reach under an old name."""
    routes = _routes()
    pairs = []
    for route, pattern in routes.items():
        if _view_key(pattern.callback) in _NO_CALLER or _NESTED_REVIEWS in route:
            continue
        if _OLD_PREFIX.search(route):
            pairs.append((route, _OLD_PREFIX.sub("productions/", route)))
        elif _view_key(pattern.callback) == _PARCEL_VIEW:
            for old, new in _PARCEL_ACTIONS.items():
                if f"/{old}" in route:
                    pairs.append((route, route.replace(f"/{old}", f"/{new}")))
    return routes, pairs


class ProductionsRoutesMirrorHistoriesTests(SimpleTestCase):
    def test_every_old_route_has_a_twin_with_the_same_view_methods_and_permissions(self):
        routes, pairs = _pairs()
        problems = []
        for old, new in pairs:
            if new not in routes:
                problems.append(f"no twin: {new}")
                continue
            old_view, old_actions, old_perms, old_overrides = _signature(routes[old])
            new_view, new_actions, new_perms, new_overrides = _signature(routes[new])
            if old_view != new_view:
                problems.append(f"{new} serves {new_view}, {old} serves {old_view}")
            if old_perms != new_perms:
                problems.append(f"{new} checks {new_perms}, {old} checks {old_perms}")
            if old_overrides != new_overrides:
                problems.append(f"{new} overrides {new_overrides}, {old} overrides {old_overrides}")
            renamed = {m: _PARCEL_ACTIONS.get(a, a) for m, a in old_actions.items()}
            if new_actions != renamed:
                problems.append(f"{new} maps {new_actions}, {old} maps {old_actions}")
        self.assertEqual(problems, [])

    def test_every_parcel_action_named_after_the_old_model_is_classified(self):
        """A new `*_history` action would otherwise ship with no twin and no test noticing."""
        from product.views import ParcelViewSet

        named = {a.__name__ for a in ParcelViewSet.get_extra_actions() if "history" in a.__name__}
        self.assertEqual(named, set(_PARCEL_ACTIONS) | _PARCEL_NO_CALLER)

    def test_the_walk_found_the_routes_it_is_about(self):
        """Guards the guard: a walk that matched nothing would pass the test above."""
        _, pairs = _pairs()
        olds = {old for old, _ in pairs}
        self.assertGreaterEqual(len(pairs), 70, f"only {len(pairs)} old routes found")
        self.assertIn("api/histories/<uuid:public_id>/audit-export/", olds)
        self.assertTrue(any(r.startswith("api/^histories/") for r in olds))
        self.assertTrue(any("/parcels/(?P<parcel_pk>[^/.]+)/histories/" in r for r in olds))
        for old in _PARCEL_ACTIONS:
            self.assertTrue(any(f"/{old}/" in r for r in olds), old)

    def test_the_carbon_middleware_treats_both_names_alike(self):
        """Both classes match paths by substring, so a name missing from a list skips that check."""
        middleware = CarbonSecurityMiddleware(lambda request: None)
        audit = CarbonAuditMiddleware(lambda request: None)

        class _Request:
            def __init__(self, path, method):
                self.path, self.method = path, method

        for old in (
            "/api/histories/",
            "/api/histories/7/",
            "/api/histories/7/public_history/",
            "/api/companies/1/establishments/2/parcels/3/histories/",
        ):
            new = old.replace("/histories/", "/productions/")
            for method in ("GET", "POST", "PATCH", "DELETE"):
                with self.subTest(path=old, method=method):
                    self.assertEqual(middleware._is_carbon_endpoint(new), middleware._is_carbon_endpoint(old))
                    self.assertEqual(middleware._is_critical_endpoint(new), middleware._is_critical_endpoint(old))
                    self.assertEqual(
                        audit._should_audit(_Request(new, method)), audit._should_audit(_Request(old, method))
                    )
                    self.assertEqual(
                        audit._is_critical_operation(_Request(new, method), None),
                        audit._is_critical_operation(_Request(old, method), None),
                    )


def _admin_of(company, email):
    user = User.objects.create_user(
        email=email, password="x", first_name="T", last_name="T", user_type=PRODUCER, is_active=True
    )
    WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
    return user


class ProductionsAnswersLikeHistoriesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Blue Oak Orchards")
        cls.owner = _admin_of(cls.company, "owner@blueoak.example")
        cls.farm = Establishment.objects.create(name="Home Ranch", company=cls.company)
        cls.parcel = Parcel.objects.create(name="Block A", establishment=cls.farm, area=4.0)
        cls.season = Production.objects.create(name="2026 Walnuts", parcel=cls.parcel)
        cls.parcel.current_history = cls.season
        cls.parcel.save(update_fields=["current_history"])
        cls.outsider = _admin_of(Company.objects.create(name="Outsider Co"), "admin@outsider.example")

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def _parcel_url(self, action):
        return f"/api/companies/{self.company.id}/establishments/{self.farm.id}/parcels/{self.parcel.id}/{action}/"

    def assertSameAnswer(self, old, new, status):
        self.assertEqual(old.status_code, status, old.content[:300])
        self.assertEqual(new.status_code, status, new.content[:300])
        self.assertEqual(new.json(), old.json())

    def test_the_owner_reads_the_same_season_under_both_names(self):
        client = self._client(self.owner)
        old = client.get(f"/api/histories/{self.season.id}/")
        new = client.get(f"/api/productions/{self.season.id}/")
        self.assertSameAnswer(old, new, 200)
        self.assertEqual(new.json()["id"], self.season.id)

    def test_the_nested_list_is_the_same_under_both_names(self):
        client = self._client(self.owner)
        base = f"/api/companies/{self.company.id}/establishments/{self.farm.id}/parcels/{self.parcel.id}"
        self.assertSameAnswer(client.get(f"{base}/histories/"), client.get(f"{base}/productions/"), 200)

    def test_an_outsider_is_refused_the_same_way_under_both_names(self):
        client = self._client(self.outsider)
        old = client.get(f"/api/histories/{self.season.id}/")
        new = client.get(f"/api/productions/{self.season.id}/")
        self.assertIn(old.status_code, (403, 404), old.content[:300])
        self.assertEqual(new.status_code, old.status_code, new.content[:300])

    def test_current_production_answers_like_current_history(self):
        client = self._client(self.owner)
        old = client.get(self._parcel_url("current_history"))
        new = client.get(self._parcel_url("current_production"))
        self.assertSameAnswer(old, new, 200)
        self.assertEqual(new.json()["id"], self.season.id)

    def test_finish_production_runs_the_same_checks_as_finish_history(self):
        """A body with no amount or date is refused before anything is written, on both names.
        Multipart, as the finish form sends it: `ParcelViewSet` parses nothing else."""
        client = self._client(self.owner)
        body = {"history": self.season.id}
        old = client.post(self._parcel_url("finish_history"), body, format="multipart")
        new = client.post(self._parcel_url("finish_production"), body, format="multipart")
        self.assertSameAnswer(old, new, 400)
        self.assertIn("finish_date", new.json())
        self.season.refresh_from_db()
        self.assertIsNone(self.season.finish_date)
