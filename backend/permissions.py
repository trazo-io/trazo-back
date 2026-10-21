from django.shortcuts import get_object_or_404

from rest_framework import permissions, viewsets

from company.models import Company


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
        if view.company is None and view.kwargs.get("company_pk") is None:
            return True
        if WorksIn.objects.filter(user=request.user, company=view.company).exists():
            return True
        return False


class IsCompanyAdmin(permissions.BasePermission):
    """Only Company Admin (CA) role can access."""

    def has_permission(self, request, view):
        from users.models import WorksIn

        if not request.user.is_authenticated:
            return False
        if view.company is None and view.kwargs.get("company_pk") is None:
            return True
        return WorksIn.objects.filter(user=request.user, company=view.company, role=WorksIn.COMPANY_ADMIN).exists()


class IsCompanyAdminOrManager(permissions.BasePermission):
    """Company Admin (CA) or Farm Manager (FM) can access."""

    def has_permission(self, request, view):
        from users.models import WorksIn

        if not request.user.is_authenticated:
            return False
        if view.company is None and view.kwargs.get("company_pk") is None:
            return True
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
        if view.company is None and view.kwargs.get("company_pk") is None:
            return True
        membership = WorksIn.objects.filter(user=request.user, company=view.company).first()
        if not membership:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return membership.role in [WorksIn.COMPANY_ADMIN, WorksIn.FARM_MANAGER]


class ReadOnlyForViewersGlobal(permissions.BasePermission):
    """Role-based read/write for ViewSets without company in URL.

    Any authenticated user can read. Only users with CA/FM role in
    at least one company can write. Use this for standalone ViewSets
    (e.g. /carbon/, /histories/) that don't inherit CompanyNestedViewSet.
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
    the case on a route without `company_pk` (the flat `/api/parcels/`, `/api/histories/`,
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
    The queryset is narrowed with `scope_to_caller_companies`, so a foreign id fails with DRF's own
    "object does not exist" error: the refusal does not confirm that the id exists. A field named
    here that the serializer does not have raises, so a renamed field cannot silently drop its check.
    """

    caller_scoped_fields = {}

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        user = getattr(request, "user", None)
        for name, company_path in self.caller_scoped_fields.items():
            if name not in fields:
                raise AttributeError(f"{type(self).__name__}.caller_scoped_fields names missing field {name!r}")
            field = getattr(fields[name], "child_relation", fields[name])
            if field.read_only:
                continue
            field.queryset = scope_to_caller_companies(field.queryset, user, company_path)
        return fields
