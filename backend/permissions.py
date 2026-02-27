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
