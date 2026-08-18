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
        field_label=getattr(field, "verbose_name", "") or field_name,
        original_value=_render(original),
        corrected_value=_render(coerced),
        reason=reason,
        amended_by=user if getattr(user, "is_authenticated", False) else None,
        amended_by_name=_actor_name(user),
    )
