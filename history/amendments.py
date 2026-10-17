"""Applying a correction to an event on a closed season.

The rule this module enforces, in one line: **a filed record is never quietly rewritten,
and never uncorrectable.**

Events on a finished production are locked against ordinary edit and delete. That is
right — the certifier packet is built from them and they must not drift. But "locked"
cannot mean "wrong forever": inspectors routinely ask operations to correct or clarify
records, and an operation that cannot is worse off at audit, not better. So corrections
go through here, where every one of them leaves a row saying what it was, what it is,
who changed it and why.

See history.models.EventAmendment for the regulatory grounding.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from history.constants import EVENT_TYPE_TO_MODEL
from history.models import EventAmendment

# Fields no amendment may touch, whatever the event type.
#
# `history` and `id` would move the record to another season or another row — that is not
# a correction, it is a different record. `album` is edited through the photo UI and
# carries no scalar an inspector reads. `reviewed`/`reviewer_name`/`review_date` are a
# sign-off attestation (FSMA PSR § 112.161(b)): re-asserting someone else's sign-off
# through a correction form is exactly the thing an audit trail exists to prevent.
PROTECTED_FIELDS = frozenset(
    {
        "id",
        "history",
        "history_id",
        "album",
        "album_id",
        "created_by",
        "created_by_id",
        "index",
        "reviewed",
        "reviewer_name",
        "review_date",
    }
)


class AmendmentError(DjangoValidationError):
    """A correction that must not be applied. Carries a farmer-readable message."""


# Field TYPES a free-text correction cannot express safely.
#
# JSONField is a correctness problem, not merely a UX one: `models.JSONField.to_python`
# returns the value unchanged, so correcting `extra_data` with "2000" would replace a
# dict with the string "2000" and silently destroy structured compliance data
# (`water_test_results`, `drift_warning`, `seed_search_attempts` are all JSON).
# Relational fields would have to be corrected by raw primary key typed into a text box,
# which is a footgun with no upside — a wrong pk repoints the record at another row.
# Both are better served by their own editors than by this form.
UNCORRECTABLE_INTERNAL_TYPES = frozenset({"JSONField", "ForeignKey", "OneToOneField", "ManyToManyField"})


def amendable_fields(event_model):
    """Concrete, editable scalar fields on this event model that a correction may target."""
    fields = []
    for field in event_model._meta.get_fields():
        if not getattr(field, "concrete", False):
            continue
        if field.auto_created or not field.editable:
            continue
        if field.name in PROTECTED_FIELDS:
            continue
        if field.get_internal_type() in UNCORRECTABLE_INTERNAL_TYPES:
            continue
        fields.append(field)
    return fields


def has_value(event, field):
    """Whether this record actually carries something in `field`.

    Drives the split the correction UI shows: a farmer correcting a record is almost
    always fixing a value they can SEE on it, and a harvest event has ~84 possible
    columns of which a real record populates a handful. Offering all 84 flat turns a
    30-second fix into a search. Blank fields stay available, but as the secondary case
    ("record something that was missed") rather than the default.
    """
    value = getattr(event, field.name, None)
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False

    # A field still holding its model default was never affirmatively recorded, and
    # showing it as "on the record" is misleading. Measured on a bare harvest event: this
    # is the difference between offering 12 fields and 8 — the twelve included four unit
    # columns whose paired quantity was blank (`area_unit` with no `area_covered`) and
    # three booleans sitting at their default False. Correcting those is really
    # "record something that was missed", which is the other list.
    if field.has_default():
        default = field.get_default()
        if callable(default):
            default = default()
        if value == default:
            return False

    return True


def _render(value):
    """How a value is stored in the trail and shown to an inspector.

    None renders as "" rather than "None": the packet line for a field that was
    previously blank should read as blank, not as a Python literal.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _actor_name(user):
    """A human name for the trail, never blank while a user exists.

    `User.get_full_name()` is `first_name + " " + last_name`, so a user with neither
    returns " " — a single space, which is TRUTHY. A naive `get_full_name() or email`
    therefore records a blank actor for every user who has not filled in their name, and
    an audit trail whose "By" column is empty is not an audit trail. Strip first, then
    fall back to the email, which every account has.
    """
    if not getattr(user, "is_authenticated", False):
        return ""
    full = (getattr(user, "get_full_name", lambda: "")() or "").strip()
    return full or (getattr(user, "email", "") or "").strip()


@transaction.atomic
def apply_amendment(*, event, event_type, field_name, new_value, reason, user):
    """Correct one field on `event`, recording the original.

    Returns the created EventAmendment. Raises AmendmentError with a message meant to be
    shown to the farmer verbatim.

    Deliberately NOT restricted to finished productions. On an open season the ordinary
    edit path is simpler and already audit-logged, but a farmer who reaches for
    "correct this" on a still-open record should get a correction, not an error — and a
    trail that is stricter than it needs to be costs nothing.
    """
    reason = (reason or "").strip()
    if not reason:
        raise AmendmentError({"reason": "Say why this record is being corrected. The reason is part of the record."})

    model = EVENT_TYPE_TO_MODEL.get(event_type)
    if model is None or not isinstance(event, model):
        raise AmendmentError({"event_type": "That event type does not match the event being corrected."})

    allowed = {f.name: f for f in amendable_fields(model)}
    field = allowed.get(field_name)
    if field is None:
        raise AmendmentError({"field_name": f"'{field_name}' is not a field that can be corrected on this record."})

    original = getattr(event, field_name)

    # Coerce through the field itself so "2000" becomes the right type for a numeric
    # column and an unparseable value is refused BEFORE anything is written.
    try:
        coerced = field.to_python(new_value)
    except DjangoValidationError as exc:
        raise AmendmentError({field_name: " ".join(exc.messages)})

    # Compare the typed values first, then their rendered forms. Decimal("200.00") and
    # Decimal("200") are equal as numbers but render as different strings, so a rendered
    # comparison alone would accept "200" over a stored 200.00 and write a correction
    # line reading "200.00 -> 200" — noise in a document an inspector reads closely.
    if coerced == original or _render(coerced) == _render(original):
        raise AmendmentError({field_name: "That is the value already on the record — nothing to correct."})

    setattr(event, field_name, coerced)
    try:
        # `clean_fields`, NOT `full_clean`. full_clean(exclude=...) skips the excluded
        # FIELDS but still runs the model's own `clean()`, and 8 of these event models
        # define one enforcing cross-field compliance rules. Running those here would
        # refuse a correction because of an unrelated pre-existing gap elsewhere on the
        # record — making exactly the old, incomplete events that most need fixing
        # permanently uncorrectable, which is the failure this feature exists to remove.
        # The corrected field still gets its full field-level validation (type, choices,
        # max_length, validators), which is what bounds the value being written.
        event.clean_fields(
            exclude=[f.name for f in model._meta.get_fields() if getattr(f, "concrete", False) and f.name != field_name]
        )
    except DjangoValidationError as exc:
        # Put the event back the way it was. The DB is protected by the atomic block,
        # but the caller is holding this instance and a rejected correction must not
        # leave a bad value sitting on it.
        setattr(event, field_name, original)
        raise AmendmentError(exc.message_dict if hasattr(exc, "message_dict") else {field_name: str(exc)})

    event.save(update_fields=[field_name])

    return EventAmendment.objects.create(
        event_type=event_type,
        event_id=event.id,
        history=event.history,
        field_name=field_name,
        field_label=history_field_label(field_name),
        original_value=_render(original),
        corrected_value=_render(coerced),
        reason=reason,
        amended_by=user if getattr(user, "is_authenticated", False) else None,
        amended_by_name=_actor_name(user),
    )


# --------------------------------------------------------------------------------------
# The season header (F7, 2026-08-21)
# --------------------------------------------------------------------------------------

# The lot header a finished season is identified BY — the same tuple
# `HistoryWriteSerializer._CLOSED_RECORD_FIELDS` freezes, minus `finish_date`.
#
# `finish_date` is deliberately NOT correctable here. Re-dating a finished season is not a
# correction to what was recorded: `retention_until` is computed once inside `History.finish()`
# and moving the date afterwards leaves the 5-year floor keyed to the old one, and clearing it
# reopens every event lock at once. That is a reopen, and it needs its own decision, not a
# text box labelled "correct this".
HISTORY_AMENDABLE_FIELDS = (
    "production_amount",
    "production_unit",
    "lot_id",
    "quality_grade",
    "harvest_method",
)

# Written out rather than derived from `verbose_name`. None of these columns declares one, so
# Django derives the label from the attribute name and the picker read "production amount",
# "lot id", "harvest method" — lowercase, underscored-looking, and not what the page beside it
# calls them. `.title()` is not the fix either: it is the same function that turned an
# operator's "WA Extra Fancy" into "Wa Extra Fancy" on 2026-08-20. Five fixed strings, named.
HISTORY_FIELD_LABELS = {
    "production_amount": "Production amount",
    "production_unit": "Unit",
    "lot_id": "Lot ID",
    "quality_grade": "Quality grade",
    "harvest_method": "Harvest method",
}


def history_amendable_fields():
    """The season-header fields a correction may target, as model field objects."""
    from history.models import History

    by_name = {f.name: f for f in History._meta.get_fields() if getattr(f, "concrete", False)}
    return [by_name[name] for name in HISTORY_AMENDABLE_FIELDS if name in by_name]


def history_field_label(field_name: str) -> str:
    """The farmer-facing name for a lot-header field, captured onto the amendment row."""
    return HISTORY_FIELD_LABELS.get(field_name, field_name)


@transaction.atomic
def apply_history_amendment(*, history, field_name, new_value, reason, user):
    """Correct one field on a season HEADER, recording the original.

    🔴 2026-08-21 (F7). The closed-record guard freezes the lot header once a season is
    finished — right, it is the traceability spine § 205.103(b)(2) asks to be auditable —
    and events on that season have had `/amend` since the corrections table shipped. The
    header had nothing: a farmer who finished with the wrong yield could neither edit it
    (423) nor amend it, and the only repair was a developer with ORM access. An
    uncorrectable wrong number is still a wrong number, and a repair with no row behind it
    is the shape NOP 4002 calls concealment.

    Same contract as `apply_amendment`: the header carries the corrected value so every
    export reads the truth without special-casing, and the amendment carries the original,
    the actor and the mandatory reason.
    """
    from history.models import EventAmendment, History

    reason = (reason or "").strip()
    if not reason:
        raise AmendmentError({"reason": "Say why this record is being corrected. The reason is part of the record."})

    if not isinstance(history, History):
        raise AmendmentError({"history": "That is not a production."})

    allowed = {f.name: f for f in history_amendable_fields()}
    field = allowed.get(field_name)
    if field is None:
        raise AmendmentError(
            {
                "field_name": (
                    f"'{field_name}' is not part of the lot header. Only the harvest figures that "
                    "identify a finished lot are corrected here; everything else on a production "
                    "is edited normally."
                )
            }
        )

    original = getattr(history, field_name)

    try:
        coerced = field.to_python(new_value)
    except DjangoValidationError as exc:
        raise AmendmentError({field_name: " ".join(exc.messages)})

    # Same two-step comparison as the event path: Decimal("200.00") == Decimal("200") as
    # numbers but renders differently, and a correction line reading "200.00 -> 200" is
    # noise in a document an inspector reads closely.
    if coerced == original or _render(coerced) == _render(original):
        raise AmendmentError({field_name: "That is the value already on the record — nothing to correct."})

    setattr(history, field_name, coerced)
    try:
        # `clean_fields` on the corrected column only — see `apply_amendment` for why
        # `full_clean` is the wrong tool here.
        history.clean_fields(
            exclude=[
                f.name for f in History._meta.get_fields() if getattr(f, "concrete", False) and f.name != field_name
            ]
        )
    except DjangoValidationError as exc:
        setattr(history, field_name, original)
        raise AmendmentError(exc.message_dict if hasattr(exc, "message_dict") else {field_name: str(exc)})

    history.save(update_fields=[field_name])

    return EventAmendment.objects.create(
        # Both NULL — this correction targets the header, not an event on it.
        event_type=None,
        event_id=None,
        history=history,
        field_name=field_name,
        field_label=history_field_label(field_name),
        original_value=_render(original),
        corrected_value=_render(coerced),
        reason=reason,
        amended_by=user if getattr(user, "is_authenticated", False) else None,
        amended_by_name=_actor_name(user),
    )


# --------------------------------------------------------------------------------------
# Related quantities on an input application (pilot rehearsal, 2026-10-17)
# --------------------------------------------------------------------------------------

#: The three numbers on an input application that state one fact twice: the amount applied is
#: the rate times the treated area. A correction changes exactly ONE field, on purpose, so a
#: corrected rate (50 -> 45 lb/acre) left the amount (300 lb) and the area (6 acres) as they
#: were, and the record no longer agreed with itself. Trazo must not change the other two: which
#: number is wrong is the operator's to say. What it can do is compute the disagreement and show
#: it, in the correction form and in the packet.
APPLICATION_QUANTITY_FIELDS = ("volume_numeric", "area_numeric", "application_rate")
APPLICATION_QUANTITY_UNIT_FIELDS = ("volume_unit", "area_unit", "application_rate_unit")
APPLICATION_QUANTITY_LABELS = {
    "volume_numeric": "Amount applied",
    "area_numeric": "Area treated",
    "application_rate": "Application rate",
    "volume_unit": "Amount unit",
    "area_unit": "Area unit",
    "application_rate_unit": "Rate unit",
}

#: Relative gap between amount and rate x area treated as agreement. Stored values carry two or
#: three decimals, so an exact comparison would report rounding as a disagreement.
APPLICATION_QUANTITY_TOLERANCE = 0.01


def _plain_number(value) -> str:
    """'45', '6', '270', '0.375': no trailing zeros, never rounded beyond 3 decimals."""
    from decimal import Decimal

    d = Decimal(str(value)).quantize(Decimal("0.001")).normalize()
    text = format(d, "f")
    return text


def application_quantities(event):
    """The amount / area / rate on an input application, and whether they agree.

    Returns None for a record that is not an input application. Otherwise a dict:

      fields   name, label, value (str or None) and printed unit for each of the three
      factor   amount = rate x area x factor, in the amount's own unit; None when the units
               cannot be compared (different dimensions, a unit Trazo does not convert, or the
               legacy "oz" that does not say which ounce)
      computed_amount  rate x area in the amount's unit, as text, when it can be computed
      agrees   True / False when all three are recorded and comparable, else None

    `agrees` is None far more often than False, and None is never reported as a problem.
    """
    from decimal import Decimal, InvalidOperation

    from history.models import ChemicalEvent
    from history.services.audit_export_service import (
        _ACRES_PER_HECTARE,
        _AREA_IN_ACRES,
        _RATE_UNIT_LABELS,
        _UNIT_IN_BASE,
        _rate_unit_parts,
        _volume_unit_text,
    )

    if not isinstance(event, ChemicalEvent):
        return None

    # The legacy "oz" is left out of the comparison: it does not say whether it is a fluid or a
    # weight ounce, and comparing it would decide that for the operator.
    units_in_base = {k: v for k, v in _UNIT_IN_BASE.items() if k != "oz"}

    amount = getattr(event, "volume_numeric", None)
    area = getattr(event, "area_numeric", None)
    rate = getattr(event, "application_rate", None)
    amount_unit = (getattr(event, "volume_unit", "") or "").strip()
    area_unit = (getattr(event, "area_unit", "") or "").strip()
    rate_code = (getattr(event, "application_rate_unit", "") or "").strip()

    fields = [
        {
            "name": "volume_numeric",
            "label": APPLICATION_QUANTITY_LABELS["volume_numeric"],
            "value": None if amount is None else _plain_number(amount),
            "unit": _volume_unit_text(amount_unit) if amount_unit else "",
        },
        {
            "name": "area_numeric",
            "label": APPLICATION_QUANTITY_LABELS["area_numeric"],
            "value": None if area is None else _plain_number(area),
            "unit": area_unit,
        },
        {
            "name": "application_rate",
            "label": APPLICATION_QUANTITY_LABELS["application_rate"],
            "value": None if rate is None else _plain_number(rate),
            "unit": _RATE_UNIT_LABELS.get(rate_code, ""),
        },
    ]

    factor = None
    parts = _rate_unit_parts(rate_code) if rate_code else None
    total_base = units_in_base.get(amount_unit)
    acres = _AREA_IN_ACRES.get(area_unit)
    if parts and total_base and acres is not None:
        numerator, denominator = parts
        rate_base = units_in_base.get(numerator)
        if rate_base and rate_base[0] == total_base[0]:
            per_area = acres if denominator == "ac" else acres / _ACRES_PER_HECTARE
            factor = rate_base[1] * per_area / total_base[1]

    result = {
        "fields": fields,
        "factor": None if factor is None else float(factor),
        "tolerance": APPLICATION_QUANTITY_TOLERANCE,
        "computed_amount": None,
        "agrees": None,
    }
    if factor is None or rate is None or area is None:
        return result
    try:
        computed = Decimal(str(rate)) * Decimal(str(area)) * factor
    except (InvalidOperation, TypeError, ValueError):
        return result
    result["computed_amount"] = f"{_plain_number(computed)} {_volume_unit_text(amount_unit)}".strip()
    if amount is None:
        return result
    actual = Decimal(str(amount))
    if actual <= 0 or computed <= 0:
        return result
    result["agrees"] = abs(computed - actual) <= actual * Decimal(str(APPLICATION_QUANTITY_TOLERANCE))
    return result


def quantity_disagreement_text(quantities) -> str:
    """'45 lbs/acre x 6 acres = 270 lbs; the amount recorded is 300 lbs.' (plain text)."""
    by_name = {f["name"]: f for f in quantities["fields"]}
    rate, area, amount = by_name["application_rate"], by_name["area_numeric"], by_name["volume_numeric"]
    return (
        f"{rate['value']} {rate['unit']} × {area['value']} {area['unit']} = {quantities['computed_amount']}; "
        f"the amount recorded is {amount['value']} {amount['unit']}."
    ).replace("  ", " ")


def corrected_quantity_disagreements(history):
    """Input applications on `history` whose amount / area / rate were CORRECTED and now disagree.

    {event_id: {"quantities": ..., "fields": [corrected field labels]}}. Limited to corrected
    records: a record that disagreed as first written is a different finding, already covered
    by the packet's order-of-magnitude reconciliation, and this is about what a one-field
    correction leaves behind.
    """
    from history.constants import CHEMICAL_EVENT_TYPE
    from history.models import ChemicalEvent

    watched = set(APPLICATION_QUANTITY_FIELDS) | set(APPLICATION_QUANTITY_UNIT_FIELDS)
    corrected = {}
    for a in EventAmendment.objects.filter(
        history=history, event_type=CHEMICAL_EVENT_TYPE, field_name__in=watched
    ).order_by("created_at"):
        corrected.setdefault(a.event_id, []).append(APPLICATION_QUANTITY_LABELS[a.field_name])
    out = {}
    for event in ChemicalEvent.objects.filter(pk__in=list(corrected)):
        quantities = application_quantities(event)
        if quantities and quantities["agrees"] is False:
            out[event.pk] = {"quantities": quantities, "fields": corrected[event.pk]}
    return out
