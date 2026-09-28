"""Write access to the roster, checked against the company actually being written to.

FOUND IN REVIEW OF #50, and the plan for this feature had already written the warning down:
"`user.companies` returns every company with any `WorksIn` row REGARDLESS OF ROLE, so the tenancy
filter and the role check are two separate things and both are required."

`ReadOnlyForViewersGlobal` asks whether the caller holds CA or FM in ANY company, globally. It never
looks at which company is being written to. `user.companies` is a role-agnostic M2M through
`WorksIn`, so it answers membership and says nothing about role. Put those two together and they are
satisfied, on two different axes, by one person: a VIEWER in the company being written to who holds
FARM MANAGER in an unrelated one. They could add, edit and deactivate roster rows in a company where
they are read-only.

`destroy` is the case that makes an object-level check mandatory rather than merely tidy: it calls
`get_object()` and never touches the serializer, so a check living in `validate()` does not apply to
it at all, and the thing it does is turn a crew member's number off.
"""

from rest_framework import permissions

from users.models import WorksIn


def may_write_roster(user, company_id):
    """Does this user hold CA or FM in THIS company?

    Not "is a member of", and not "holds the role somewhere". Those are the two mistakes this
    function exists to stop being made again.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if company_id is None:
        return False
    return WorksIn.objects.filter(
        user=user,
        company_id=company_id,
        role__in=[WorksIn.COMPANY_ADMIN, WorksIn.FARM_MANAGER],
    ).exists()


class MayWriteCrewSender(permissions.BasePermission):
    """Read for any authenticated caller the queryset lets through; write only for CA/FM in that company.

    The CREATE case is enforced in `CrewSenderSerializer.validate_company` instead, and deliberately:
    the target company arrives as request DATA, so no permission class ever sees it, and a
    FIELD-level validator is the only hook that runs before the auto-generated
    `UniqueTogetherValidator` that would otherwise answer first and leak whether a number is already
    on a foreign roster.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return may_write_roster(request.user, obj.company_id)
