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
    `history/tests/test_record_retention.py` pins as deliberate. An unfinished season that HOLDS
    records is refused separately, by `unfinished_histories_holding_records` (OV-ST-C02).
    """
    from history.models import History

    return History.objects.filter(retention_until__gt=timezone.now().date(), **lookup)


def unfinished_histories_holding_records(**lookup):
    """Seasons under `lookup` not yet finished that hold records (OV-ST-C02).

    `retention_until` is written when a season finishes, so a season still being logged has none,
    and until 2026-11-13 that made it deletable with everything in it: a pilot's whole first year,
    one click on "Delete season" or one API call on its parcel, farm or company. 7 CFR 205.103(b)(4)
    keeps records "not less than 5 years beyond their creation", and an activity is created when
    it is logged, not when the season closes. An EMPTY draft still deletes: that is the case the
    NULL rule above was written for.

    "Not finished" is the same test `assert_child_record_deletable` uses for a closed season
    (`finish_date` set or `published`), keyed on that and NOT on a NULL `retention_until`: a legacy
    finished season can have no retention date, and its activities are already locked, so telling
    the grower to delete them first would send them to a button that is not there (review on #422).
    """
    from django.db.models import Q

    from history.models import History

    holds = Q()
    for relation in RECORD_RELATIONS:
        holds |= Q(**{f"{relation}__isnull": False})
    return History.objects.filter(finish_date__isnull=True, published=False, **lookup).filter(holds).distinct()


def record_count(history):
    """How many records (activities, sales, amendments) one season holds."""
    total = 0
    for relation in RECORD_RELATIONS:
        manager = getattr(history, relation, None)
        if manager is not None:
            total += manager.count()
    return total


def unfinished_season_refusal(history):
    """The farmer-facing sentence for a season that holds records and has no retention date."""
    count = record_count(history)
    noun = "record" if count == 1 else "records"
    return (
        f"This season has {count} {noun} logged in it, so it cannot be deleted as a whole: that "
        "would erase records an organic operation keeps for 5 years (7 CFR 205.103(b)(4)). If it "
        "was started by mistake, delete its activities one by one while it is open, then delete "
        "the empty season."
    )


def assert_deletable(container_label, **lookup):
    """Raise RetentionConflict if deleting this container would erase retained records.

    `container_label` names the thing being deleted ("parcel", "farm", "company") so the
    farmer reads why THIS delete failed rather than a generic refusal.
    """
    _assert_no_unretained_records(container_label, **lookup)
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
                f"{'it' if count == 1 else 'them'}." + state_retention_sentence(blocking)
            ),
            "retention_until": until,
            "blocking_production_count": count,
        }
    )


def _assert_no_unretained_records(container_label, **lookup):
    """Refuse a container delete that would erase records of a season not yet finished."""
    seasons = list(unfinished_histories_holding_records(**lookup))
    if not seasons:
        return
    records = sum(record_count(season) for season in seasons)
    s_noun = "season" if len(seasons) == 1 else "seasons"
    r_noun = "record" if records == 1 else "records"
    raise RetentionConflict(
        {
            "error": "Season holds records",
            "detail": (
                f"This {container_label} has {len(seasons)} {s_noun} not yet finished with {records} "
                f"{r_noun} logged. Deleting the {container_label} would erase records an organic "
                f"operation keeps for 5 years (7 CFR 205.103(b)(4))."
            ),
            # No "retention_until" key: an unfinished season has no date, and APIException turns
            # None into the string "None" rather than JSON null (review on #422).
            "blocking_production_count": len(seasons),
            "record_count": records,
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
                + state_retention_sentence(history)
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


# ---------------------------------------------------------------------------------------------
# The retention floor (run 7, R7-10).
#
# `retention_until` was the finish date plus five years, written once in `History.finish()`.
# 7 CFR 205.103(b)(4) keeps records "not less than 5 years beyond their creation", and a season
# keeps acquiring records after it closes: a sale invoiced in January, an amendment correcting a
# field, a void. The floor is therefore the later of finish + 5 years and the newest covered
# record's creation + 5 years, and it moves forward (never back) when such a record arrives.
# ---------------------------------------------------------------------------------------------

EVENT_RELATIONS = (
    "history_productionevent_events",
    "history_chemicalevent_events",
    "history_weatherevent_events",
    "history_generalevent_events",
    "history_equipmentevent_events",
    "history_soilmanagementevent_events",
    "history_pestmanagementevent_events",
    "history_businessevent_events",
)

#: What makes a season hold records, by the relation names on History. Events, sales and
#: amendments are the rows 7 CFR 205.103 is about; a season PLAN (`ProductionPlanItem`) is not a
#: record (a template produces a plan, never a record), so an untouched draft stays deletable.
RECORD_RELATIONS = EVENT_RELATIONS + ("sales_records", "amendments")


def latest_covered_record_created(history):
    """When the newest record of this production was created, or None.

    Sales and amendments carry `created_at`. Events do not: their creation time lives in the
    audit log (`auditlog` create entries), and the event's own date is a lower bound for an event
    the log does not cover (a seeded or imported row)."""
    from django.contrib.contenttypes.models import ContentType
    from django.db.models import Max

    from auditlog.models import LogEntry

    stamps = [getattr(history, "created_at", None)]
    if history.pk is None:
        # An unsaved production has no related records to read.
        dates = [s.date() if hasattr(s, "date") else s for s in stamps if s is not None]
        return max(dates) if dates else None
    # A void is a dated record of its own (review of #113).
    sales = history.sales_records.aggregate(created=Max("created_at"), voided=Max("voided_at"))
    stamps += [sales["created"], sales["voided"]]
    stamps.append(history.amendments.aggregate(m=Max("created_at"))["m"])
    for relation in EVENT_RELATIONS:
        manager = getattr(history, relation, None)
        if manager is None:
            continue
        ids = list(manager.values_list("pk", flat=True))
        if not ids:
            continue
        stamps.append(manager.aggregate(m=Max("date"))["m"])
        content_type = ContentType.objects.get_for_model(manager.model)
        stamps.append(
            LogEntry.objects.filter(
                content_type=content_type, object_pk__in=[str(pk) for pk in ids], action=LogEntry.Action.CREATE
            ).aggregate(m=Max("timestamp"))["m"]
        )
    dates = [s.date() if hasattr(s, "date") else s for s in stamps if s is not None]
    return max(dates) if dates else None


# ---------------------------------------------------------------------------------------------
# A state floor on top (overall review 2026-11, OV-CMP-C08).
#
# WAC 16-228-1320(3): a Washington pesticide application record "shall be kept for a period of
# seven years from the date of the application". The rule covers "all persons applying pesticides
# to more than one acre of agricultural land in a calendar year", organic products included, so a
# Washington season holding a spray keeps seven years from its newest application, when that is
# later than the five-year organic floor. Kept per SEASON like the rest of this module: the floor
# is what `retention_until` stores, and a season is what the deletion guard refuses to erase.
# Applied to every Washington farm's spray, never only above one acre: keeping a record longer
# than a rule asks costs nothing, and Trazo does not know the farm's yearly sprayed acreage.
# ---------------------------------------------------------------------------------------------

#: State code -> (years from the application date, the rule that says so).
STATE_SPRAY_RETENTION = {"WA": (7, "WAC 16-228-1320(3)")}


def _state_spray_rule(history):
    """`(years, citation)` when this season's farm keeps spray records longer than five years."""
    from common.us_states import resolve_establishment_state

    parcel = getattr(history, "parcel", None)
    establishment = getattr(parcel, "establishment", None) if parcel is not None else None
    return STATE_SPRAY_RETENTION.get(resolve_establishment_state(establishment))


def state_spray_retention_floor(history):
    """Seven years after the newest pesticide application of a Washington farm's season, or None.

    None for a farm in any other state, for a season with no pesticide, fungicide or herbicide
    record, and for an unsaved season."""
    rule = _state_spray_rule(history)
    if rule is None or history.pk is None:
        return None
    from django.db.models import Max

    from history.models import ChemicalEvent, compute_retention_until
    from history.services.wa_spray_record_service import WA_RECORD_TYPES

    latest = ChemicalEvent.objects.filter(history=history, type__in=WA_RECORD_TYPES).aggregate(m=Max("date"))["m"]
    if latest is None:
        return None
    return compute_retention_until(latest, years=rule[0])


def state_retention_sentence(history) -> str:
    """The sentence a refusal citing 7 CFR 205.103(b)(4) appends when the season carries the
    Washington floor, naming WAC 16-228-1320(3) and the date; "" otherwise."""
    try:
        floor = state_spray_retention_floor(history)
    except Exception:  # noqa: BLE001 - a refusal message must never fail on its own wording
        return ""
    if floor is None:
        return ""
    # Said only when the stored date carries the state floor. A season closed before this floor
    # existed keeps its five-year date until its next record moves it (`extend_retention`), and a
    # refusal must not promise a date the guard does not hold.
    stored = getattr(history, "retention_until", None)
    if stored is not None and stored < floor:
        return ""
    years, citation = _state_spray_rule(history)
    return (
        f" This season holds pesticide application records of a Washington farm, which are kept "
        f"{years} years from the date of the application ({citation}): until at least {floor.isoformat()}."
    )


def retention_floor(history):
    """The earliest date this production's records may be released: never before five years after
    its finish, nor before five years after its newest record was created, nor, for a Washington
    farm's season holding a spray, before seven years after its newest application. The later date
    wins, so a state floor never brings a date forward. None when the season has neither a finish
    date nor any record."""
    from history.models import compute_retention_until

    candidates = []
    if history.finish_date:
        candidates.append(compute_retention_until(history.finish_date))
    latest = latest_covered_record_created(history)
    if latest is not None:
        candidates.append(compute_retention_until(latest))
    state_floor = state_spray_retention_floor(history)
    if state_floor is not None:
        candidates.append(state_floor)
    return max(candidates) if candidates else None


def extend_retention(history):
    """Move a finished production's stored `retention_until` forward to its floor. Never shortens
    it, and leaves an open season's NULL alone (its deletion rule is a separate decision)."""
    if history is None or not history.finish_date:
        return
    from django.db.models import Q

    floor = retention_floor(history)
    if floor is None:
        return
    # Conditional on the STORED value, never the in-memory one: the instance a related record
    # holds can be stale, and comparing against it once overwrote a later date with an earlier one.
    moved = (
        type(history)
        .objects.filter(pk=history.pk)
        .filter(Q(retention_until__isnull=True) | Q(retention_until__lt=floor))
        .update(retention_until=floor)
    )
    if moved:
        history.retention_until = floor
