"""What a logged product name IS, decided by the operator and kept as evidence (T18, Phase 5 slice 2).

THE RULES (Oscar, 2026-10-02)
-----------------------------
* Nothing is inferred from a name. The operator decides, once per logged name, that the events using
  it used a product on the plan (`same_as`) or a product that is not (`different_product`).
* A decision covers the events it lists, each bound to the FINGERPRINT of its identity-relevant
  content when reviewed. Editing any of that content, or logging a new event under the same name,
  leaves the event unreviewed until the operator reviews it again (a new decision).
* A change of mind supersedes; nothing is edited or deleted. A decision that would cover an event
  already covered by another current decision is refused unless it names that decision as the one it
  supersedes.
* Operation-scoped and checked by the server: every event must belong to the plan's establishment,
  and a `same_as` target must be a PRODUCT on that plan (a plan entry, or an OMRI or WSDA row the plan
  approves). A National List substance is a classification, never an identity target.
* Formulation guard: a `same_as` whose names differ in any number (NPK, percentage, version) is
  refused unless the operator acknowledges the difference and says why.
* Identity is not classification and not approval. A decision writes nothing on an event or the
  plan. The drift detector may use it for ONE thing: answering "not matched to any approved input"
  (`unresolved`) for a covered event; the target is then checked like any named input, and every
  approval, restriction, expiry or date-of-use finding on it stands.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from certifications.models import MaterialIdentityDecision as MID

#: source -> (model path, name field, identity-relevant fields, extra filter)
SOURCES = {
    MID.SOURCE_CHEMICAL: (
        "history.ChemicalEvent",
        "commercial_name",
        (
            "commercial_name",
            "manufacturer",
            "epa_registration_number",
            "chemical_lot_number",
            "omri_product_id",
            "wsda_material_id",
        ),
        {},
    ),
    MID.SOURCE_AMENDMENT: (
        "history.SoilManagementEvent",
        "amendment_product_name",
        ("amendment_product_name", "amendment_manufacturer", "amendment_lot_number"),
        {},
    ),
    MID.SOURCE_SANITIZER: ("history.ProductionEvent", "sanitizer_name", ("sanitizer_name",), {"type": "PH"}),
}

COVERED = "covered"
UNREVIEWED = "unreviewed"
STALE = "stale"  # reviewed, then its identity-relevant content changed
EXCEPTED = "excepted"

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


class IdentityError(Exception):
    def __init__(self, message, status_code=400, field=None):
        super().__init__(message)
        self.status_code = status_code
        self.field = field


def _int(value, field):
    """A request value as an id, or a 400: malformed input is the client's error, never a 500 (review
    of back #98)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        raise IdentityError(f"'{value}' is not an id.", field=field)


def name_key(name) -> str:
    """The same key the materials list joins on (`plan_materials._norm`): case and spacing only."""
    return " ".join(str(name or "").split()).strip().lower()


def _model(source):
    from django.apps import apps

    path = SOURCES[source][0]
    return apps.get_model(*path.split("."))


def fingerprint(event, source) -> str:
    fields = SOURCES[source][2]
    values = [getattr(event, f, None) for f in fields]
    canonical = json.dumps(values, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def numbers(name) -> list:
    """The numbers in a product name, in order: '2-3-1', '25%', 'v5.0'. Order matters (2-3-1 != 1-3-2)."""
    return [n.replace(",", ".") for n in _NUMBER.findall(str(name or ""))]


def formulation_differs(a, b) -> bool:
    return numbers(a) != numbers(b)


def events_for(establishment_id, source, key=None):
    """The source's events on this establishment that carry a name, optionally only those under `key`."""
    _path, name_field, _fields, extra = SOURCES[source]
    qs = (
        _model(source)
        .objects.filter(history__parcel__establishment_id=establishment_id, **extra)
        .exclude(**{f"{name_field}__isnull": True})
    )
    out = []
    for event in qs.order_by("date", "id"):
        name = (getattr(event, name_field) or "").strip()
        if not name:
            continue
        if key is None or name_key(name) == key:
            out.append(event)
    return out


def current_decision(establishment_id, source, key) -> Optional[MID]:
    return (
        MID.objects.filter(establishment_id=establishment_id, source=source, name_key=key, superseded_at__isnull=True)
        .order_by("-decided_at", "-id")
        .first()
    )


@dataclass(frozen=True)
class Coverage:
    state: str
    decision: Optional[MID] = None


def coverage(event, source) -> Coverage:
    """Whether a current decision covers this event as it is NOW."""
    name_field = SOURCES[source][1]
    key = name_key(getattr(event, name_field, ""))
    est_id = getattr(getattr(getattr(event, "history", None), "parcel", None), "establishment_id", None)
    if not key or est_id is None:
        return Coverage(UNREVIEWED)
    decision = current_decision(est_id, source, key)
    if decision is None:
        return Coverage(UNREVIEWED)
    reviewed = {r.get("event_id"): r.get("fingerprint") for r in decision.reviewed or []}
    if event.pk not in reviewed:
        return Coverage(UNREVIEWED, decision)
    if event.pk in {x.get("event_id") for x in decision.exceptions or []}:
        return Coverage(EXCEPTED, decision)
    if reviewed[event.pk] != fingerprint(event, source):
        return Coverage(STALE, decision)
    return Coverage(COVERED, decision)


def covering_same_as(event, source) -> Optional[MID]:
    """The `same_as` decision that covers this event as it is now, else None."""
    cov = coverage(event, source)
    if cov.state == COVERED and cov.decision is not None and cov.decision.decision == MID.SAME_AS:
        return cov.decision
    return None


def basis_text(decision) -> str:
    when = decision.decided_at.date().isoformat() if decision.decided_at else ""
    if decision.decision == MID.SAME_AS:
        return f"identified by the operator as {decision.target_name} on {when}"
    return f"identified by the operator as a different product, not the plan's, on {when}"


def _target(osp, kind, target_id):
    """The plan's product the decision names, or None. Never a National List substance."""
    if kind == MID.TARGET_PLAN_ENTRY:
        entry = osp.plan_material_entries.filter(pk=target_id).first()
        return entry, getattr(entry, "product_name", "")
    if kind == MID.TARGET_OMRI:
        row = osp.approved_omri_products.filter(pk=target_id).first()
        return row, getattr(row, "product_name", "")
    if kind == MID.TARGET_WSDA:
        row = osp.approved_wsda_materials.filter(pk=target_id).first()
        return row, getattr(row, "brand_name", "")
    return None, ""


def target_on_plan(osp, decision) -> bool:
    """Whether the decision's product is on `osp` (which may be a later version than the decision's).

    OMRI and WSDA rows are compared by id. A plan entry is compared by its exact name, because forking
    a plan copies entries into new rows."""
    if osp is None or decision is None or decision.decision != MID.SAME_AS:
        return False
    if decision.target_kind == MID.TARGET_OMRI:
        return osp.approved_omri_products.filter(pk=decision.target_id).exists()
    if decision.target_kind == MID.TARGET_WSDA:
        return osp.approved_wsda_materials.filter(pk=decision.target_id).exists()
    if decision.target_kind == MID.TARGET_PLAN_ENTRY:
        return any(name_key(e.product_name) == name_key(decision.target_name) for e in osp.plan_material_entries.all())
    return False


def target_object(decision):
    from certifications.models import OMRIProduct, PlanMaterialEntry, WSDAMaterial

    model = {
        MID.TARGET_PLAN_ENTRY: PlanMaterialEntry,
        MID.TARGET_OMRI: OMRIProduct,
        MID.TARGET_WSDA: WSDAMaterial,
    }.get(decision.target_kind)
    return model.objects.filter(pk=decision.target_id).first() if model else None


@transaction.atomic
def record_decision(osp, user, data) -> MID:
    """Validate and store one decision. Raises IdentityError (400/404/409) and writes nothing then."""
    source = data.get("source")
    if source not in SOURCES:
        raise IdentityError("Unknown source.", field="source")
    logged_name = (data.get("logged_name") or "").strip()
    key = name_key(logged_name)
    if not key:
        raise IdentityError("Name the logged product this decision is about.", field="logged_name")
    decision = data.get("decision")
    if decision not in (MID.SAME_AS, MID.DIFFERENT_PRODUCT):
        raise IdentityError("Choose same_as or different_product.", field="decision")

    est_id = osp.establishment_id
    event_ids = [_int(x, "event_ids") for x in (data.get("event_ids") or [])]
    if not event_ids:
        raise IdentityError("List the events you reviewed.", field="event_ids")
    model = _model(source)
    name_field = SOURCES[source][1]
    extra = SOURCES[source][3]
    # The same filter the reader (`events_for`) applies: a decision may only name events the reader shows
    # (review of back #98: a non-post-harvest ProductionEvent passed as a sanitizer).
    events = {
        e.pk: e for e in model.objects.filter(pk__in=event_ids, history__parcel__establishment_id=est_id, **extra)
    }
    missing = [i for i in event_ids if i not in events]
    if missing:
        # Another operation's event, or no such event: never a silent filter.
        raise IdentityError(f"Events not found on this operation: {missing}.", status_code=404, field="event_ids")
    wrong_name = [i for i, e in events.items() if name_key(getattr(e, name_field, "")) != key]
    if wrong_name:
        raise IdentityError(f"Events {wrong_name} are not logged under '{logged_name}'.", field="event_ids")

    exceptions = []
    for row in data.get("exceptions") or []:
        if not isinstance(row, dict):
            raise IdentityError("Each exception is an event and a reason.", field="exceptions")
        eid = _int(row.get("event_id"), "exceptions")
        reason = (row.get("reason") or "").strip()
        if eid not in events:
            raise IdentityError(f"Exception {eid} is not among the reviewed events.", field="exceptions")
        if not reason:
            raise IdentityError("Say why each excluded event is excluded.", field="exceptions")
        exceptions.append({"event_id": eid, "reason": reason})

    target_kind, target_id, target_name = "", None, ""
    ack = bool(data.get("formulation_difference_acknowledged"))
    formulation_note = (data.get("formulation_note") or "").strip()
    if decision == MID.SAME_AS:
        target_kind = data.get("target_kind") or ""
        if target_kind == "national_list":
            raise IdentityError(
                "A National List substance is a classification, not a product. Choose the product on the plan.",
                field="target_kind",
            )
        if target_kind not in (MID.TARGET_PLAN_ENTRY, MID.TARGET_OMRI, MID.TARGET_WSDA):
            raise IdentityError("Choose the plan's product this name is.", field="target_kind")
        try:
            target_id = int(data.get("target_id"))
        except (TypeError, ValueError):
            raise IdentityError("Choose the plan's product this name is.", field="target_id")
        obj, target_name = _target(osp, target_kind, target_id)
        if obj is None:
            raise IdentityError("That product is not on this plan.", field="target_id")
        if formulation_differs(logged_name, target_name) and not (ack and formulation_note):
            raise IdentityError(
                f"'{logged_name}' and '{target_name}' differ in their numbers. Confirm the difference is "
                "understood and say why they are the same product.",
                field="formulation_difference_acknowledged",
            )
    elif data.get("target_kind") or data.get("target_id"):
        raise IdentityError("A different product names no plan product.", field="target_kind")

    existing = (
        MID.objects.select_for_update()
        .filter(establishment_id=est_id, source=source, name_key=key, superseded_at__isnull=True)
        .first()
    )
    supersedes_id = data.get("supersedes")
    if supersedes_id is not None:
        supersedes_id = _int(supersedes_id, "supersedes")
    if existing is not None and (supersedes_id is None or supersedes_id != existing.pk):
        raise IdentityError(
            f"A current decision already covers '{logged_name}'. Supersede it explicitly.",
            status_code=409,
            field="supersedes",
        )
    if existing is None and supersedes_id is not None:
        raise IdentityError("There is no current decision to supersede.", status_code=409, field="supersedes")
    # Overlap: no listed event may be covered by any other current decision.
    for eid, event in events.items():
        cov = coverage(event, source)
        if cov.state == COVERED and cov.decision is not None and cov.decision.pk != getattr(existing, "pk", None):
            raise IdentityError(f"Event {eid} is covered by another current decision.", status_code=409)

    now = timezone.now()
    if existing is not None:
        existing.superseded_at = now
        existing.save(update_fields=["superseded_at"])
    name = ""
    if user is not None and getattr(user, "is_authenticated", False):
        name = (user.get_full_name() or "").strip() or (getattr(user, "email", "") or "")
    from django.db import IntegrityError

    try:
        with transaction.atomic():
            return _create(
                est_id,
                osp,
                source,
                logged_name,
                key,
                decision,
                target_kind,
                target_id,
                target_name,
                events,
                exceptions,
                ack,
                formulation_note,
                data,
                user,
                name,
                now,
                existing,
            )
    except IntegrityError:
        raise IdentityError(
            f"Another decision about '{logged_name}' was recorded at the same time. Reload and review it.",
            status_code=409,
        )


def _create(
    est_id,
    osp,
    source,
    logged_name,
    key,
    decision,
    target_kind,
    target_id,
    target_name,
    events,
    exceptions,
    ack,
    formulation_note,
    data,
    user,
    name,
    now,
    existing,
):
    return MID.objects.create(
        establishment_id=est_id,
        osp=osp,
        source=source,
        logged_name=logged_name,
        name_key=key,
        decision=decision,
        target_kind=target_kind,
        target_id=target_id,
        target_name=target_name,
        reviewed=[{"event_id": e.pk, "fingerprint": fingerprint(e, source)} for e in events.values()],
        exceptions=exceptions,
        formulation_difference_acknowledged=ack if decision == MID.SAME_AS else False,
        formulation_note=formulation_note if decision == MID.SAME_AS else "",
        note=(data.get("note") or "").strip(),
        decided_by=user if getattr(user, "is_authenticated", False) else None,
        decided_by_name=name,
        decided_at=now,
        supersedes=existing,
    )


def _decision_json(d) -> dict:
    return {
        "id": d.pk,
        "decision": d.decision,
        "target_kind": d.target_kind,
        "target_id": d.target_id,
        "target_name": d.target_name,
        "reviewed_event_ids": [r.get("event_id") for r in d.reviewed or []],
        "exceptions": d.exceptions or [],
        "formulation_difference_acknowledged": d.formulation_difference_acknowledged,
        "formulation_note": d.formulation_note,
        "note": d.note,
        "decided_by_name": d.decided_by_name,
        "decided_at": d.decided_at.isoformat() if d.decided_at else None,
        "plan_version": getattr(d.osp, "version_number", None),
        "supersedes": d.supersedes_id,
        "superseded_at": d.superseded_at.isoformat() if d.superseded_at else None,
        "basis": basis_text(d),
    }


def identities(osp) -> list:
    """Every logged name on the plan's operation not exactly on the plan, or under a decision.

    Names that match a plan material exactly need no decision and are left out."""
    from certifications.services.plan_materials import plan_materials

    on_plan = {name_key(m.name) for m in plan_materials(osp)}
    est_id = osp.establishment_id
    out = []
    for source, (_p, name_field, _f, _x) in SOURCES.items():
        groups: dict = {}
        for event in events_for(est_id, source):
            groups.setdefault(name_key(getattr(event, name_field)), []).append(event)
        for key, events in groups.items():
            history = list(
                MID.objects.filter(establishment_id=est_id, source=source, name_key=key).order_by("decided_at", "id")
            )
            if key in on_plan and not history:
                continue
            current = next((d for d in reversed(history) if d.superseded_at is None), None)
            rows = []
            for event in events:
                cov = coverage(event, source)
                rows.append(
                    {
                        "id": event.pk,
                        "date": event.date.isoformat() if getattr(event, "date", None) else None,
                        "state": cov.state,
                    }
                )
            out.append(
                {
                    "source": source,
                    "logged_name": (getattr(events[0], name_field) or "").strip(),
                    "name_key": key,
                    "events": rows,
                    "current": _decision_json(current) if current else None,
                    "history": [_decision_json(d) for d in history],
                }
            )
    return out


def plan_targets(osp) -> list:
    """The products on this plan a `same_as` may name. National List substances are not among them."""
    out = [
        {"kind": MID.TARGET_PLAN_ENTRY, "id": e.pk, "name": e.product_name}
        for e in osp.plan_material_entries.all().order_by("product_name")
    ]
    out += [
        {"kind": MID.TARGET_OMRI, "id": o.pk, "name": o.product_name}
        for o in osp.approved_omri_products.all().order_by("product_name")
    ]
    out += [
        {"kind": MID.TARGET_WSDA, "id": w.pk, "name": w.brand_name}
        for w in osp.approved_wsda_materials.all().order_by("brand_name")
    ]
    return out
