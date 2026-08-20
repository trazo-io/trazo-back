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


def _user_works_in(user, company):
    """Membership, asserted rather than assumed.

    These permissions resolve the target company from the REQUEST BODY, so without this a
    payload could name any company in the database. `CompanyNestedViewSet`'s default
    permissions are `[IsSuperUser | (ReadOnlyForViewers & AuthPermission)]` — `AuthPermission`
    is "is authenticated" and nothing more; `UserWorksInCompany` is NOT in that list.
    """
    from users.models import WorksIn

    if user.is_superuser:
        return True
    return WorksIn.objects.filter(user=user, company=company).exists()


class HasEstablishmentCreationPermission(permissions.BasePermission):
    """May the company that will OWN this farm add another one?

    ⚠️ Not `get_active_company()`. `EstablishmentViewSet` has no `perform_create` override and
    `company` is a writable field on `UpdateEstablishmentSerializer`, so the row is created on
    whatever company the PAYLOAD names. Asking the active company therefore checked a
    subscription that had nothing to do with the farm being created:

      * BYPASS — point the active company at one with headroom, post
        `{"company": <exhausted company>}`, and the farm cap is gone. Farms are the metric
        Trazo actually bills: Extra Farm is $149/yr and the Operation tier exists to lift
        exactly this cap.
      * CROSS-TENANT — the same payload created a farm on a company the user does not work in
        at all, because nothing on this path asserted membership.

    Both measured 2026-08-19 with the guards in
    `subscriptions/tests/test_creation_limits.py::FarmAndParcelQuotasAskTheRightCompany`.
    """

    message = "Your subscription plan does not allow creating more establishments."

    def has_permission(self, request, view):
        if request.method != "POST":
            return True

        company = self._target_company(request, view)
        if not company or not _user_works_in(request.user, company):
            return False
        return company.can_create_establishment()

    @staticmethod
    def _target_company(request, view):
        """The company the farm will belong to: payload, else the nested route, else active."""
        from company.models import Company

        raw = request.data.get("company")
        if raw in (None, ""):
            raw = getattr(view, "kwargs", {}).get("company_pk") if view is not None else None
        if raw in (None, ""):
            return request.user.get_active_company()
        try:
            return Company.objects.get(id=int(raw))
        except (Company.DoesNotExist, TypeError, ValueError):
            # The view answers a specific error for an unknown company; a 403 here would
            # replace it with a misleading "your plan does not allow this".
            return request.user.get_active_company()


class HasParcelCreationPermission(permissions.BasePermission):
    """May the company that OWNS THE ESTABLISHMENT add another parcel to it?

    The old version looked the establishment up through `company.establishment_set` on the
    ACTIVE company. That closed the bypass by accident — a foreign establishment raised
    DoesNotExist — but it answered False for a user legitimately working in a second company,
    and its bare `except Exception` turned any programming error (a renamed related accessor,
    say) into a polite "your plan does not allow this" that no one would ever debug.

    Resolving the establishment first and asking ITS company keeps the bypass closed for the
    right reason and stops punishing multi-company users.
    """

    message = "Your subscription plan does not allow creating more parcels."

    def has_permission(self, request, view):
        if request.method != "POST":
            return True

        from company.models import Establishment

        raw = request.data.get("establishment")
        if raw in (None, ""):
            raw = getattr(view, "kwargs", {}).get("establishment_pk") if view is not None else None
        if raw in (None, ""):
            return False

        try:
            establishment = Establishment.objects.select_related("company").get(id=int(raw))
        except (Establishment.DoesNotExist, TypeError, ValueError):
            return False

        company = establishment.company
        if not company or not _user_works_in(request.user, company):
            return False
        return company.can_create_parcel(establishment)


class HasProductionCreationPermission(permissions.BasePermission):
    """
    Check if the company that OWNS THE PARCEL may create another production this year.

    ⚠️ Not `get_active_company()`. A user can work in several companies, and the production is
    created on `parcel.establishment.company` — which the view resolves independently — so
    reading the quota off whichever company happens to be "active" checks the wrong
    subscription in BOTH directions:

      * false NEGATIVE — measured 2026-08-19 on the demo account: active company sat on a
        retired `corporate-*` plan capped at 6 productions/year and already at 6, so starting a
        season on the OTHER company's parcel (Compliance, unlimited) answered 403.
      * false POSITIVE, the one that matters — switch active company to any unlimited one and
        the exhausted company's quota is bypassed entirely. A limit that is defeated by a
        dropdown is not a limit.

    Same rule as the rest of the billing surface: a quota question is asked of the SUBSCRIPTION
    that will be billed, never of whatever context the client happens to be in.
    """

    message = "Your subscription plan has reached the maximum number of productions for this year."

    def has_permission(self, request, view):
        if request.method != "POST":
            return True

        company = self._company_for_request(request)
        return bool(company) and company.can_create_production()

    @staticmethod
    def _company_for_request(request):
        """The parcel's company when the payload names one, else the active company.

        Falls back rather than refusing: a malformed or absent `parcel_id` is the view's error
        to report (it answers a specific 400/404), and a permission class that 403s first would
        replace that with a misleading "your plan has reached its maximum".
        """
        from product.models import Parcel

        raw = request.data.get("parcel_id") or request.data.get("parcel")
        if raw not in (None, ""):
            try:
                parcel = Parcel.objects.select_related("establishment__company").get(id=int(raw))
            except (Parcel.DoesNotExist, TypeError, ValueError):
                return request.user.get_active_company()
            establishment = parcel.establishment
            return establishment.company if establishment else None

        return request.user.get_active_company()


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
