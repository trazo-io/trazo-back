"""One place that answers "would deleting this erase a record NOP still requires?".

`History.delete()` refuses to erase a production inside its 7 CFR 205.103(b)(4) five-year
window, but that guard only fires on a bound model delete. Every FK above History is
`on_delete=CASCADE` — History.parcel, Parcel.establishment, Establishment.company — and
Django's collector deletes cascaded rows in BULK, so `History.delete()` is never called.
Deleting a parcel, a farm, or a company therefore erased retained productions (and their
events, scans, sales records and carbon rows) straight past the guard.

Guarding at each container rather than loosening the CASCADEs: the parcel really does own
its productions, and orphaning them would be worse than deleting them. What must not
happen is losing them SILENTLY.

Kept in one module because the three call sites differ only by lookup path, and three
hand-written copies of a compliance check is how they drift apart.
"""

from django.utils import timezone

from rest_framework import status
from rest_framework.exceptions import APIException


class RetentionConflict(APIException):
    """409 for a delete refused by the NOP 5-year record-retention floor.

    409 rather than 400: this is a conflict with stored state, not a malformed request —
    the caller cannot fix it by editing their payload, only by waiting out the retention
    period. Rather than 403 too: the caller is permitted, the record simply is not
    deletable yet.
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Record retention period active."


def histories_in_retention(**lookup):
    """Productions under `lookup` whose retention floor has not yet passed.

    A NULL `retention_until` never blocks: it is written only by `History.finish()`, so a
    draft or abandoned season has none. Blocking those would strand them forever, which
    `history/tests/test_record_retention.py` pins as deliberate.
    """
    from history.models import History

    return History.objects.filter(retention_until__gt=timezone.now().date(), **lookup)


def assert_deletable(container_label, **lookup):
    """Raise RetentionConflict if deleting this container would erase retained records.

    `container_label` names the thing being deleted ("parcel", "farm", "company") so the
    farmer reads why THIS delete failed rather than a generic refusal.
    """
    in_retention = histories_in_retention(**lookup)
    blocking = in_retention.order_by("-retention_until").first()
    if blocking is None:
        return

    count = in_retention.count()
    until = blocking.retention_until.isoformat()
    raise RetentionConflict(
        {
            "error": "Record retention period active",
            "detail": (
                f"This {container_label} has {count} finished production"
                f"{'' if count == 1 else 's'} that must be kept until {until} under "
                f"7 CFR 205.103(b)(4). Deleting the {container_label} would erase "
                f"{'it' if count == 1 else 'them'}."
            ),
            "retention_until": until,
            "blocking_production_count": count,
        }
    )


class RecordLocked(APIException):
    """423 for a child row of a finished production, refused by the same 5-year floor.

    423 rather than the 409 above because this mirrors the EVENT contract
    (`EventViewSet.destroy`, and the generated API docs describe it as such): the row is not
    in conflict with a concurrent change, it is locked because the season it belongs to closed.
    One status for "a record inside a closed production may not be erased", whichever kind of
    record it is.
    """

    status_code = status.HTTP_423_LOCKED
    default_detail = "Record is locked by the retention period."


def assert_child_record_deletable(record_label, history, *, correctable=False):
    """Raise RecordLocked if `history` is closed, so its child records must be kept.

    🔴 2026-09-07 — `SalesRecordViewSet.destroy` checked the caller's ROLE and then called
    `record.delete()`. No override, no `pre_delete`, no call to this module. Meanwhile
    `binding_clauses` names `SalesRecord` and `SalesRecord.organic_label_category` as the
    implementation of § 205.103(b)(2) AND (b)(3), both `SOFTWARE_SATISFIES`, and a single
    EVENT on a finished production is refused with 423 citing § 205.103(b)(4). The sale is the
    far end of the audit trail (b)(2) means by "to sale or transport" — the half a traceback
    exercise starts from — and it had none of that protection.

    A finished-but-unretained production (legacy rows written before `retention_until` existed)
    is treated as retained: `finish_date` is what makes the season a closed record.
    """
    retention_until = getattr(history, "retention_until", None)
    finished = history.finish_date is not None or getattr(history, "published", False)
    still_retained = retention_until is not None and retention_until > timezone.now().date()
    if not (finished or still_retained):
        return

    until = retention_until.isoformat() if retention_until else None
    raise RecordLocked(
        {
            "error": "Record is locked",
            "detail": (
                f"This production is finished, so its {record_label} must be kept"
                f"{f' until {until}' if until else ''} under 7 CFR 205.103(b)(4). "
                f"The audit trail a certifier follows runs from production to sale, so this "
                f"row is part of what the plan has to be able to show."
                + (
                    " If it is wrong, void it instead: the row stays on the record with your "
                    "reason, and stops counting as a sale."
                    if correctable
                    else ""
                )
            ),
            "correctable": correctable,
            "production_id": history.id,
            "retention_until": until,
        }
    )
