"""A route with no company in the URL is denied unless its view says why it is safe.

The four company permission classes in `backend/permissions.py` returned True whenever the URL named
no company, which is every flat route (`/api/parcels/`, `/api/events/`, `/api/scans/`...). Tenancy
then rested on each view's queryset happening to scope itself, and the 2026-10-20 route inventory
found the ones that did not. Since 2026-10-21 an undeclared flat route is refused, and a declared
one is role-checked against the company of the OBJECT it touches: before that, a Viewer could
PATCH or DELETE their own company's parcels, scans and events through the flat routes, because
nothing compared their role with anything.
"""

from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import get_resolver

from rest_framework.test import APIClient

from backend.permissions import (
    CALLER_SCOPED,
    CATALOG_ROUTE,
    CompanyNestedViewSet,
    IsCompanyAdmin,
    IsCompanyAdminOrManager,
    ReadOnlyForViewers,
    UserWorksInCompany,
)
from backend.route_tenancy import COMPANY, ROUTE_TENANCY
from backend.tests.test_route_tenancy_declared import _view_key, _walk
from company.models import Company, Establishment
from history.models import GeneralEvent, History, HistoryScan
from product.models import Parcel
from users.constants import PRODUCER
from users.models import User, WorksIn

# CALLER_SCOPED without an object path, each with the reason it needs none.
NO_OBJECT_PATH_NEEDED = {
    "company.views.CompanyViewSet": "initial() sets self.company from pk, so no detail route is flat",
}


def _flat_nested_views():
    """CompanyNestedViewSet subclasses reachable through a route with no company_pk."""
    found = {}
    for route, pattern in _walk(get_resolver()):
        view_class = getattr(pattern.callback, "cls", None)
        if view_class is None or not issubclass(view_class, CompanyNestedViewSet):
            continue
        if "company_pk" in route:
            continue
        found[_view_key(pattern.callback)] = view_class
    return found


class FlatRouteDeclarationTests(SimpleTestCase):
    def test_every_flat_nested_view_declares_its_tenancy(self):
        for key, view_class in _flat_nested_views().items():
            with self.subTest(view=key):
                declared = getattr(view_class, "flat_route_tenancy", None)
                self.assertIn(
                    declared,
                    (CALLER_SCOPED, CATALOG_ROUTE),
                    f"{key} serves a route with no company in the URL; declare flat_route_tenancy "
                    "(see backend/permissions.py) or the route is refused",
                )

    def test_caller_scoped_views_name_the_object_path_and_are_proven(self):
        for key, view_class in _flat_nested_views().items():
            if getattr(view_class, "flat_route_tenancy", None) != CALLER_SCOPED:
                continue
            with self.subTest(view=key):
                if key not in NO_OBJECT_PATH_NEEDED:
                    self.assertTrue(
                        getattr(view_class, "object_company_path", None),
                        f"{key} is caller_scoped but names no object_company_path, so writes on its "
                        "flat routes cannot be role-checked",
                    )
                route = ROUTE_TENANCY[key]
                self.assertEqual(route.scope, COMPANY)
                self.assertTrue(route.outsider_tests, f"{key} opts its flat routes in with no outsider test")

    def test_the_walk_sees_the_flat_routes(self):
        """Guards the guard: a walk that found nothing would pass both tests above."""
        self.assertIn("product.views.ParcelViewSet", _flat_nested_views())
        self.assertIn("history.views.EventViewSet", _flat_nested_views())


class UndeclaredFlatRouteIsDeniedTests(SimpleTestCase):
    def test_every_company_permission_refuses_an_undeclared_flat_route(self):
        class Undeclared:
            company = None
            kwargs = {}

        request = RequestFactory().get("/api/anything/")
        request.user = User(email="x@example.com", is_active=True)
        request.user.is_superuser = False
        for permission in (ReadOnlyForViewers, UserWorksInCompany, IsCompanyAdmin, IsCompanyAdminOrManager):
            with self.subTest(permission=permission.__name__):
                self.assertFalse(permission().has_permission(request, Undeclared()))

    def test_catalog_routes_are_read_only(self):
        class Catalog:
            company = None
            kwargs = {}
            flat_route_tenancy = CATALOG_ROUTE

        user = User(email="x@example.com", is_active=True)
        for method, allowed in (("get", True), ("post", False), ("delete", False)):
            with self.subTest(method=method):
                request = getattr(RequestFactory(), method)("/api/products/")
                request.user = user
                self.assertEqual(ReadOnlyForViewers().has_permission(request, Catalog()), allowed)


class FlatRouteWritesAreRoleCheckedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Farm Co")
        farm = Establishment.objects.create(name="Farm", company=cls.company)
        cls.parcel = Parcel.objects.create(name="Block 1", establishment=farm, area=2.0)
        cls.season = History.objects.create(name="2026", parcel=cls.parcel)
        cls.scan = HistoryScan.objects.create(history=cls.season)
        cls.event = GeneralEvent.objects.create(
            history=cls.season, name="Walked rows", description="d", date="2026-05-01T10:00:00Z"
        )
        cls.viewer = cls._member("viewer@farm.example", WorksIn.VIEWER)
        cls.manager = cls._member("manager@farm.example", WorksIn.FARM_MANAGER)

    @classmethod
    def _member(cls, email, role):
        user = User.objects.create_user(
            email=email, password="x", first_name="T", last_name="T", user_type=PRODUCER, is_active=True
        )
        WorksIn.objects.create(user=user, company=cls.company, role=role)
        return user

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_viewer_cannot_edit_or_delete_through_flat_routes(self):
        viewer = self._client(self.viewer)
        cases = (
            ("patch", f"/api/parcels/{self.parcel.id}/", {"name": "PWNED"}),
            ("delete", f"/api/parcels/{self.parcel.id}/", None),
            ("delete", f"/api/scans/{self.scan.id}/", None),
            ("patch", f"/api/events/{self.event.id}/?event_type=3", {"name": "PWNED"}),
            ("delete", f"/api/events/{self.event.id}/?event_type=3", None),
        )
        for method, url, body in cases:
            with self.subTest(method=method, url=url):
                # Parcels take multipart (the parcel form uploads images), the rest take JSON.
                fmt = "multipart" if "/parcels/" in url and method == "patch" else "json"
                response = getattr(viewer, method)(url, body, format=fmt)
                self.assertEqual(response.status_code, 403, response.content[:300])
        self.assertTrue(Parcel.objects.filter(pk=self.parcel.pk, name="Block 1").exists())
        self.assertTrue(HistoryScan.objects.filter(pk=self.scan.pk).exists())
        self.assertTrue(GeneralEvent.objects.filter(pk=self.event.pk, name="Walked rows").exists())

    def test_viewer_still_reads_through_flat_routes(self):
        viewer = self._client(self.viewer)
        for url in (f"/api/parcels/{self.parcel.id}/", f"/api/scans/{self.scan.id}/"):
            with self.subTest(url=url):
                self.assertEqual(viewer.get(url).status_code, 200)

    def test_manager_still_edits_through_flat_routes(self):
        response = self._client(self.manager).patch(
            f"/api/parcels/{self.parcel.id}/", {"name": "Block 1 North"}, format="multipart"
        )
        self.assertEqual(response.status_code, 200, response.content[:300])


class CrossCompanyObjectTests(TestCase):
    """Review findings on #209: the object must belong to the URL's company on nested routes, and
    EventViewSet needed a genuine outsider test, not only a same-company role test."""

    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="A Farms")
        cls.farm_a = Establishment.objects.create(name="A Farm", company=cls.company_a)
        cls.company_b = Company.objects.create(name="B Farms")
        farm_b = Establishment.objects.create(name="B Farm", company=cls.company_b)
        parcel_b = Parcel.objects.create(name="B Block", establishment=farm_b, area=1.0)
        season_b = History.objects.create(name="B 2026", parcel=parcel_b)
        cls.scan_b = HistoryScan.objects.create(history=season_b)
        cls.event_b = GeneralEvent.objects.create(
            history=season_b, name="B work", description="d", date="2026-05-01T10:00:00Z"
        )
        cls.two_hats = User.objects.create_user(
            email="two-hats@example.com", password="x", first_name="T", last_name="H", user_type=PRODUCER
        )
        WorksIn.objects.create(user=cls.two_hats, company=cls.company_a, role=WorksIn.COMPANY_ADMIN)
        WorksIn.objects.create(user=cls.two_hats, company=cls.company_b, role=WorksIn.VIEWER)
        cls.outsider = User.objects.create_user(
            email="outsider@example.com", password="x", first_name="O", last_name="U", user_type=PRODUCER
        )
        WorksIn.objects.create(
            user=cls.outsider, company=Company.objects.create(name="Elsewhere"), role=WorksIn.COMPANY_ADMIN
        )

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_admin_of_a_cannot_delete_bs_scan_through_as_url(self):
        url = f"/api/companies/{self.company_a.id}/establishments/{self.farm_a.id}/scans/{self.scan_b.id}/"
        response = self._client(self.two_hats).delete(url)
        self.assertIn(response.status_code, (403, 404), response.content[:300])
        self.assertTrue(HistoryScan.objects.filter(pk=self.scan_b.pk).exists())

    def test_outsider_cannot_touch_another_companys_event_on_the_flat_route(self):
        client = self._client(self.outsider)
        url = f"/api/events/{self.event_b.id}/?event_type=3"
        for method, body in (("get", None), ("patch", {"name": "PWNED"}), ("delete", None)):
            with self.subTest(method=method):
                response = getattr(client, method)(url, body, format="json")
                self.assertIn(response.status_code, (403, 404), response.content[:300])
        self.assertTrue(GeneralEvent.objects.filter(pk=self.event_b.pk, name="B work").exists())
