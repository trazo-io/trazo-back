from rest_framework import permissions


class IsCompanyAdminForSubscription(permissions.BasePermission):
    """Only Company Admins can manage billing and subscriptions."""

    message = "Only Company Admins can manage subscriptions."

    def has_permission(self, request, view):
        from users.models import WorksIn

        if not request.user.is_authenticated:
            return False
        if request.user.is_staff or request.user.is_superuser:
            return True
        return WorksIn.objects.filter(user=request.user, role=WorksIn.COMPANY_ADMIN).exists()


class HasEstablishmentCreationPermission(permissions.BasePermission):
    """
    Check if the user's company has permission to create a new establishment
    """

    message = "Your subscription plan does not allow creating more establishments."

    def has_permission(self, request, view):
        if request.method != "POST":
            return True

        company = request.user.get_active_company()
        return company and company.can_create_establishment()


class HasParcelCreationPermission(permissions.BasePermission):
    """
    Check if the user's company has permission to create a new parcel
    """

    message = "Your subscription plan does not allow creating more parcels."

    def has_permission(self, request, view):
        if request.method != "POST":
            return True

        company = request.user.get_active_company()
        establishment_id = request.data.get("establishment")

        if not company or not establishment_id:
            return False

        try:
            establishment_id = int(establishment_id)
            establishment = company.establishment_set.get(id=establishment_id)
            return company.can_create_parcel(establishment)
        except Exception:
            return False


class HasProductionCreationPermission(permissions.BasePermission):
    """
    Check if the user's company has permission to create a new production
    """

    message = "Your subscription plan has reached the maximum number of productions for this year."

    def has_permission(self, request, view):
        if request.method != "POST":
            return True

        company = request.user.get_active_company()
        return company and company.can_create_production()


class HasFeaturePermission(permissions.BasePermission):
    """
    Check if the user's company has access to a specific feature
    Usage: HasFeaturePermission('establishment_full_description')
    """

    def __init__(self, feature_name):
        self.feature_name = feature_name
        self.message = f"Your subscription plan does not include the {feature_name} feature."

    def has_permission(self, request, view):
        company = request.user.get_active_company()
        return company and company.has_feature(self.feature_name)
