from django.shortcuts import get_object_or_404

from rest_framework import permissions, viewsets

from company.models import Company

# How a CompanyNestedViewSet may serve a route with no company in the URL (`/api/parcels/`,
# `/api/events/`...). On such a route the permission layer cannot check membership, so the view
# must say why the route is safe. Until 2026-10-21 these classes returned True instead, for every
# flat route, and tenancy rested on each view's queryset happening to scope itself; the route
# inventory found the ones that did not (backend/route_tenancy.py).
#
#   "caller_scoped"  get_queryset narrows rows to the caller's companies, and the view names
#                    `object_company_path` so writes are role-checked against the OBJECT's company
#                    (ReadOnlyForViewers.has_object_permission).
#   "catalog"        rows are the same for every caller; safe methods only.
#
# NEVER: return True for an undeclared flat route. Guard: backend/tests/test_flat_routes_fail_closed.py
CALLER_SCOPED = "caller_scoped"
CATALOG_ROUTE = "catalog"


def _is_flat_route(view):
    return getattr(view, "company", None) is None and view.kwargs.get("company_pk") is None


def _flat_route_allowed(request, view):
    declared = getattr(view, "flat_route_tenancy", None)
    if declared == CALLER_SCOPED:
        return True
    if declared == CATALOG_ROUTE:
        return request.method in permissions.SAFE_METHODS
    return False


def _object_company(view, obj):
    """The Company an object belongs to, by walking the view's `object_company_path`."""
    path = getattr(view, "object_company_path", None)
    if not path:
        return None
    current = obj
    for part in path.split("__"):
        current = getattr(current, part, None)
        if current is None:
            return None
    return current if isinstance(current, Company) else None


class IsSuperUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class AuthPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class UserWorksInCompany(permissions.BasePermission):
    def has_permission(self, request, view):
        from users.models import WorksIn

        if not request.user.is_authenticated:
            return False
        if _is_flat_route(view):
            return _flat_route_allowed(request, view)
        if WorksIn.objects.filter(user=request.user, company=view.company).exists():
            return True
        return False


class IsCompanyAdmin(permissions.BasePermission):
    """Only Company Admin (CA) role can access."""

    def has_permission(self, request, view):
        from users.models import WorksIn

        if not request.user.is_authenticated:
            return False
        if _is_flat_route(view):
            return _flat_route_allowed(request, view)
        return WorksIn.objects.filter(user=request.user, company=view.company, role=WorksIn.COMPANY_ADMIN).exists()


class IsCompanyAdminOrManager(permissions.BasePermission):
    """Company Admin (CA) or Farm Manager (FM) can access."""

    def has_permission(self, request, view):
        from users.models import WorksIn

        if not request.user.is_authenticated:
            return False
        if _is_flat_route(view):
            return _flat_route_allowed(request, view)
        return WorksIn.objects.filter(
            user=request.user,
            company=view.company,
            role__in=[WorksIn.COMPANY_ADMIN, WorksIn.FARM_MANAGER],
        ).exists()


class ReadOnlyForViewers(permissions.BasePermission):
    """Any company member can read; only CA/FM can write."""

    def has_permission(self, request, view):
        from users.models import WorksIn

        if not request.user.is_authenticated:
            return False
        if _is_flat_route(view):
            return _flat_route_allowed(request, view)
        membership = WorksIn.objects.filter(user=request.user, company=view.company).first()
        if not membership:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return membership.role in [WorksIn.COMPANY_ADMIN, WorksIn.FARM_MANAGER]

    def has_object_permission(self, request, view, obj):
        """On a flat route `has_permission` saw no company, so check the object's.

        Until 2026-10-21 a Viewer could PATCH or DELETE events, scans and parcels of their own
        company through the flat routes, because nothing compared their role with anything. On
        a nested route `has_permission` already checked the URL's company and the queryset ties
        the object to it.
        """
        from users.models import WorksIn

        if not _is_flat_route(view):
            # Nested: has_permission checked the caller's role in the URL's company, so the object
            # must belong to THAT company. A view whose queryset spans every company the caller
            # belongs to (HistoryScanViewSet did) otherwise let a Company Admin of A delete B's
            # row through A's URL while only a Viewer in B. Review finding on #209.
            if getattr(view, "object_company_path", None):
                return _object_company(view, obj) == view.company
            return True
        if getattr(view, "flat_route_tenancy", None) == CATALOG_ROUTE:
            return request.method in permissions.SAFE_METHODS
        company = _object_company(view, obj)
        if company is None:
            return False
        membership = WorksIn.objects.filter(user=request.user, company=company).first()
        if membership is None:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return membership.role in [WorksIn.COMPANY_ADMIN, WorksIn.FARM_MANAGER]


class ReadOnlyForViewersGlobal(permissions.BasePermission):
    """Role-based read/write for ViewSets without company in URL.

    Any authenticated user can read. Only users with CA/FM role in
    at least one company can write. Use this for standalone ViewSets
    (e.g. /carbon/, /productions/) that don't inherit CompanyNestedViewSet.
    """

    def has_permission(self, request, view):
        from users.models import WorksIn

        if not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser:
            return True
        return WorksIn.objects.filter(
            user=request.user,
            role__in=[WorksIn.COMPANY_ADMIN, WorksIn.FARM_MANAGER],
        ).exists()


class CompanyNestedViewSet(viewsets.GenericViewSet):
    permission_classes = [IsSuperUser | (ReadOnlyForViewers & AuthPermission)]
    perms_map = {}
    company = None
    model = None

    def initial(self, request, *args, **kwargs):
        lookup_field = "company_pk"
        company_pk = kwargs.get(lookup_field)
        if company_pk is not None:
            self.company = get_object_or_404(Company, pk=company_pk)
        if establishment_pk := kwargs.get("establishment_pk"):
            self.establishment = get_object_or_404(self.company.establishment_set.all(), pk=establishment_pk)

        super().initial(request, *args, **kwargs)


def scope_to_caller_companies(queryset, user, company_path):
    """Tenancy floor: only rows that belong to one of the caller's companies.

    Every permission class above returns True when `view.company` is None, which is always
    the case on a route without `company_pk` (the flat `/api/parcels/`, `/api/productions/`,
    `/api/scans/` routes, and `CompanyViewSet` itself). On those routes the permission layer
    only proves the caller is signed in, so the queryset has to do the tenancy check. Found
    2026-09-28: any signed-in account could read or edit other companies' seasons, parcels,
    scans and carbon entries by id. `EventViewSet._scope_to_caller` is the same rule, written
    earlier for events.

    `company_path` is the ORM path from the model to its Company, e.g.
    "parcel__establishment__company". Superusers see everything; anonymous users nothing.
    """
    if not user or not user.is_authenticated:
        return queryset.none()
    if user.is_superuser:
        return queryset
    return queryset.filter(**{f"{company_path}__in": user.companies.all()})


class CallerScopedRelatedFields:
    """Serializer mixin: writable foreign keys accept only rows in the caller's companies.

    A `PrimaryKeyRelatedField` validates the id against its queryset, and the default queryset is
    every row of the model. So a PATCH naming another company's establishment, parcel, season, OSP,
    certification or support ticket saved it: a parcel moved onto another tenant's farm, false
    205.202 land history landed in another tenant's packet. Found by the 2026-10-20 route inventory.

    Declare `caller_scoped_fields = {"<field>": "<ORM path from the target model to Company>"}`.

    `establishment_scoped_fields = {"<field>": "<ORM path to Establishment id>"}` narrows further, to
    the farm in the URL (`establishment_pk`), on nested routes: a company with several farms could
    otherwise link farm B's certificate into farm A's OSP. Off a nested route it does nothing.

    `caller_scoped_staff_bypass = True` exempts `is_staff` users, for the one place staff act across
    companies by design (support agents on customers' tickets). Default off: everywhere else
    `scope_to_caller_companies` exempts superusers only.
    The queryset is narrowed with `scope_to_caller_companies`, so a foreign id fails with DRF's own
    "object does not exist" error: the refusal does not confirm that the id exists. A field named
    here that the serializer does not have raises, so a renamed field cannot silently drop its check.
    """

    caller_scoped_fields = {}
    establishment_scoped_fields = {}
    caller_scoped_staff_bypass = False

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        user = getattr(request, "user", None)
        staff_bypass = self.caller_scoped_staff_bypass and getattr(user, "is_staff", False)
        view = self.context.get("view")
        establishment_pk = getattr(view, "kwargs", {}).get("establishment_pk")
        for name in {**self.caller_scoped_fields, **self.establishment_scoped_fields}:
            if name not in fields:
                raise AttributeError(f"{type(self).__name__} scopes missing field {name!r}")
        for name, company_path in self.caller_scoped_fields.items():
            field = getattr(fields[name], "child_relation", fields[name])
            if field.read_only or staff_bypass:
                continue
            field.queryset = scope_to_caller_companies(field.queryset, user, company_path)
        for name, establishment_path in self.establishment_scoped_fields.items():
            field = getattr(fields[name], "child_relation", fields[name])
            if field.read_only or establishment_pk is None:
                continue
            field.queryset = field.queryset.filter(**{establishment_path: establishment_pk})
        return fields
