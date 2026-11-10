"""Who a Company Admin may remove from the team, or give a different role, on Settings > Team.

The same rules decide what the screen offers (`CompanyMemberSerializer.can_manage`) and what the
server accepts (`CompanyViewSet.member`), so the app never renders a control the API refuses.

THE RULES, in the order they are checked:

  * Only a Company Admin of the company in the URL may change its team (the view's permission).
  * Not the setup operator. That account enters a pilot grower's records; who is on the grower's
    team is the grower's decision, like signing (`subscriptions.pilot_operator`).
  * Not yourself. An admin cannot remove themself or change their own role here: one click would
    lock them out with nobody else told. Another Company Admin can do it.
  * Not the setup operator's row. Trazo removes it with `remove_pilot_operator`, which refuses while
    the account authored records in the company and keeps the company from being left with no
    member. The screen does not repeat those checks, so it does not touch the row.
  * Never the last Company Admin. Removing or demoting one must leave at least one Company Admin who
    is not a setup operator. With the self rule above the caller is always that admin, so this only
    bites when two admins act on each other at once; the view locks the team's rows to make that
    race answer the same way every time.
"""

from users.models import WorksIn

NOT_ADMIN = "not_admin"
SETUP_OPERATOR_CALLER = "setup_operator_caller"
SELF = "self"
SETUP_OPERATOR_TARGET = "setup_operator"
LAST_ADMIN = "last_admin"

REFUSALS = {
    NOT_ADMIN: "Only a Company Admin can change the team.",
    SETUP_OPERATOR_CALLER: (
        "This is the setup account for this farm. It enters records, but who is on the team is the "
        "grower's decision: the grower signs in to their account and does it there."
    ),
    SELF: "You cannot remove yourself or change your own role. Another Company Admin can.",
    SETUP_OPERATOR_TARGET: (
        "This is the Trazo setup account that enters your records. Write to Trazo to remove it or " "change its role."
    ),
    LAST_ADMIN: "This is the only Company Admin. Make someone else a Company Admin first.",
}


def manage_refusal(caller, target):
    """Why `caller` (a WorksIn row, or None) may not change `target` at all, or None if it may.

    The last-admin rule depends on the change, so it is `change_refusal`'s.
    """
    if caller is None or caller.role != WorksIn.COMPANY_ADMIN or caller.company_id != target.company_id:
        # The view's permission refuses these before any rule runs. Here it keeps the serializer
        # from offering controls to someone the view would refuse, and catches an admin demoted
        # between the permission check and the lock.
        return NOT_ADMIN
    if caller.is_setup_operator:
        return SETUP_OPERATOR_CALLER
    if caller.pk == target.pk:
        return SELF
    if target.is_setup_operator:
        return SETUP_OPERATOR_TARGET
    return None


def change_refusal(caller, target, new_role, team):
    """Why the change may not happen, or None. `new_role` None means removal.

    `team` is every WorksIn row of the company, read under lock by the caller.
    """
    refusal = manage_refusal(caller, target)
    if refusal:
        return refusal
    loses_admin = target.role == WorksIn.COMPANY_ADMIN and new_role != WorksIn.COMPANY_ADMIN
    if loses_admin:
        others = [
            row
            for row in team
            if row.pk != target.pk and row.role == WorksIn.COMPANY_ADMIN and not row.is_setup_operator
        ]
        if not others:
            return LAST_ADMIN
    return None
