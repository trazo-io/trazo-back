"""The API calls a production `productions/`; `histories/` is gone (contract step, 2026-11-15).

The model has been `Production` since history 0264. Back #438 served `productions/` beside
`histories/`, app #394 moved every call to the new name, and this step deleted the old one:
- the flat and parcel-nested `histories/` routes and the UUID `histories/<uuid>/audit-export/`;
- the parcel actions `current_history/` and `finish_history/`, now `current_production/` and
  `finish_production/`;
- three routes no client called: `establishments/<id>/histories/`, `parcels/<id>/history/`, and the
  reviews route nested under `parcels/<id>/histories/<id>/reviews/` (reviews use the flat route).

These tests keep the old names gone and the new ones answering. A route brought back under an old
name is one the app cannot call: its own guard (`apiCallsProductionsNotHistories.test.ts`) fails
on any call to one.

Not routes, so not in scope: payload keys (`history`, `history_id`), model fields
(`Parcel.current_history`) and the `public_history` action, which names what it serves.
"""

import re
import uuid

from django.test import SimpleTestCase, TestCase
from django.urls import Resolver404, get_resolver, resolve

from rest_framework.test import APIClient

from backend.tests.test_route_tenancy_declared import _view_key, _walk
from carbon.middleware.security_middleware import CarbonAuditMiddleware, CarbonSecurityMiddleware
from company.models import Company, Establishment
from history.models import Production
from product.models import Parcel
from users.constants import PRODUCER
from users.models import User, WorksIn

# An old name as a whole route segment. Route strings mix path converters and regexes
# (`api/^productions/(?P<pk>[^/.]+)/$`), so a segment may follow `/` or `^` and end at `/` or `$`.
# `history` counts too: outside `admin/` (Django's own per-object history view, and the app label)
# the only route that had it was the deleted `parcels/<id>/history/`.
_OLD_SEGMENT = re.compile(r"(?:^|[/^])(?:history|histories|current_history|finish_history)(?=[/$]|\Z)")
_OLD_ACTIONS = {"history", "histories", "current_history", "finish_history"}

_PARCEL = "/api/companies/1/establishments/2/parcels/3"
_UUID = uuid.UUID(int=7)


def _routes():
    return {route: pattern for route, pattern in _walk(get_resolver()) if not route.startswith("admin/")}


class TheOldNamesAreGoneTests(SimpleTestCase):
    def test_no_route_has_an_old_name_as_a_segment(self):
        routes = _routes()
        self.assertGreater(len(routes), 500, "the walk found too few routes to prove anything")
        self.assertEqual(sorted(r for r in routes if _OLD_SEGMENT.search(r)), [])

    def test_the_segment_pattern_matches_the_shapes_the_old_routes_had(self):
        """Guards the test above: each of these was a real route before this step."""
        for route in (
            "api/^histories/$",
            "api/^histories/(?P<pk>[^/.]+)/$",
            "api/histories/<uuid:public_id>/audit-export/",
            "api/^companies/(?P<company_pk>[^/.]+)/establishments/(?P<establishment_pk>[^/.]+)/parcels/"
            "(?P<parcel_pk>[^/.]+)/histories/$",
            "api/^companies/(?P<company_pk>[^/.]+)/establishments/(?P<establishment_pk>[^/.]+)/parcels/"
            "(?P<pk>[^/.]+)/current_history/$",
            "api/^companies/(?P<company_pk>[^/.]+)/establishments/(?P<establishment_pk>[^/.]+)/parcels/"
            "(?P<pk>[^/.]+)/finish_history/$",
            "api/^companies/(?P<company_pk>[^/.]+)/establishments/(?P<establishment_pk>[^/.]+)/parcels/"
            "(?P<pk>[^/.]+)/history/$",
        ):
            with self.subTest(route=route):
                self.assertTrue(_OLD_SEGMENT.search(route))
        for route in ("api/^productions/(?P<pk>[^/.]+)/public_history/$", "api/^productions/$"):
            with self.subTest(route=route):
                self.assertFalse(_OLD_SEGMENT.search(route))

    def test_no_viewset_keeps_an_action_named_after_the_old_model(self):
        """Every viewset the resolver reaches, not only the two that had one."""
        viewsets = {
            cls
            for cls in (getattr(p.callback, "cls", None) for p in _routes().values())
            if cls is not None and hasattr(cls, "get_extra_actions")
        }
        self.assertGreater(len(viewsets), 50, "the walk found too few viewsets to prove anything")
        self.assertIn("ParcelViewSet", {cls.__name__ for cls in viewsets})
        found = sorted(
            f"{cls.__module__}.{cls.__name__}.{a.__name__}"
            for cls in viewsets
            for a in cls.get_extra_actions()
            if a.__name__ in _OLD_ACTIONS
        )
        self.assertEqual(found, [])

    def test_the_old_paths_do_not_resolve(self):
        for path in (
            "/api/histories/",
            "/api/histories/7/",
            f"/api/histories/{_UUID}/audit-export/",
            "/api/companies/1/establishments/2/histories/",
            f"{_PARCEL}/histories/",
            f"{_PARCEL}/histories/4/reviews/",
            f"{_PARCEL}/current_history/",
            f"{_PARCEL}/finish_history/",
            f"{_PARCEL}/history/",
        ):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)

    def test_the_new_paths_resolve_to_the_views_the_app_calls(self):
        for path, view, actions in (
            ("/api/productions/", "history.views.HistoryViewSet", {"get": "list", "post": "create"}),
            ("/api/productions/7/", "history.views.HistoryViewSet", {"get": "retrieve"}),
            (f"/api/productions/{_UUID}/audit-export/", "history.views.audit_export_by_uuid", None),
            (f"{_PARCEL}/productions/", "history.views.HistoryViewSet", {"get": "list"}),
            (f"{_PARCEL}/current_production/", "product.views.ParcelViewSet", {"get": "current_production"}),
            (f"{_PARCEL}/finish_production/", "product.views.ParcelViewSet", {"post": "finish_production"}),
        ):
            with self.subTest(path=path):
                match = resolve(path)
                self.assertEqual(_view_key(match.func), view)
                served = getattr(match.func, "actions", None)
                for method, action in (actions or {}).items():
                    self.assertEqual(served.get(method), action)

    def test_the_carbon_middleware_covers_productions_like_events(self):
        """Both classes match paths by substring, and `/events/` sits in every list `/productions/`
        must be in. Removing `/histories/` from those lists must not drop the new name with it."""
        middleware = CarbonSecurityMiddleware(lambda request: None)
        audit = CarbonAuditMiddleware(lambda request: None)

        class _Request:
            def __init__(self, path, method):
                self.path, self.method = path, method

        # The anchors: without these, both names dropping out of a list would still compare equal.
        for path in ("/api/productions/", "/api/productions/7/"):
            with self.subTest(path=path):
                self.assertTrue(middleware._is_carbon_endpoint(path))
                self.assertTrue(middleware._is_critical_endpoint(path))
                self.assertTrue(audit._should_audit(_Request(path, "POST")))

        # `/public_history/` is on the public list, so it is deliberately not critical: compare
        # with the sibling rather than assert a value.
        for suffix in ("", "7/", "7/public_history/"):
            ours, sibling = f"/api/productions/{suffix}", f"/api/events/{suffix}"
            for method in ("GET", "POST", "PATCH", "DELETE"):
                with self.subTest(path=ours, method=method):
                    self.assertEqual(middleware._is_carbon_endpoint(ours), middleware._is_carbon_endpoint(sibling))
                    self.assertEqual(middleware._is_critical_endpoint(ours), middleware._is_critical_endpoint(sibling))
                    self.assertEqual(
                        audit._should_audit(_Request(ours, method)), audit._should_audit(_Request(sibling, method))
                    )
                    self.assertEqual(
                        audit._is_critical_operation(_Request(ours, method), None),
                        audit._is_critical_operation(_Request(sibling, method), None),
                    )


def _admin_of(company, email):
    user = User.objects.create_user(
        email=email, password="x", first_name="T", last_name="T", user_type=PRODUCER, is_active=True
    )
    WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
    return user


class ProductionsAnswersTests(TestCase):
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

    def test_the_owner_reads_the_season(self):
        response = self._client(self.owner).get(f"/api/productions/{self.season.id}/")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["id"], self.season.id)

    def test_the_nested_list_holds_the_season(self):
        response = self._client(self.owner).get(self._parcel_url("productions"))
        self.assertEqual(response.status_code, 200, response.content[:300])
        body = response.json()
        rows = body["results"] if isinstance(body, dict) else body
        self.assertIn(self.season.id, [row["id"] for row in rows])

    def test_an_outsider_is_refused(self):
        response = self._client(self.outsider).get(f"/api/productions/{self.season.id}/")
        self.assertIn(response.status_code, (403, 404), response.content[:300])

    def test_current_production_serves_the_open_season(self):
        response = self._client(self.owner).get(self._parcel_url("current_production"))
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["id"], self.season.id)

    def test_finish_production_refuses_a_body_with_no_date_before_writing(self):
        """Multipart, as the finish form sends it: `ParcelViewSet` parses nothing else."""
        response = self._client(self.owner).post(
            self._parcel_url("finish_production"), {"history": self.season.id}, format="multipart"
        )
        self.assertEqual(response.status_code, 400, response.content[:300])
        self.assertIn("finish_date", response.json())
        self.season.refresh_from_db()
        self.assertIsNone(self.season.finish_date)
