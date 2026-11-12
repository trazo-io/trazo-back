"""Several products sprayed from one tank: the request contract, the per-line split, the one pass.

WHY (overall review 2026-11, OV-RK-C04 / OV-FJ-C10). A tank of Entrust, Kocide and a
spreader-sticker could not be held as one application: the products after the first went into
`tank_mix_partners`, a block with no rate, REI, PHI, lot, invoice, receipt or National List
classification, and a spray over several blocks refused it. Three products on three blocks were
nine records typed by hand, and nothing stored that they shared a tank.

THE SHAPE (owner decision 2026-11-11). One FULL `ChemicalEvent` per product line and per target,
written in one request, all or none, tied by `tank_mix_group` (the client-minted tank id) and
numbered by `tank_mix_line`. Never a header table with product lines: every reader (the packet,
the CA PUR, the National List classification, the drift check, purchases, receipts, corrections,
Activity) already works one product per record, and each of them then sees an adjuvant as the
full record it is. Adjuvants and spreader-stickers are full lines too, `tank_mix_role="adjuvant"`.

WHAT IS PER LINE AND WHAT IS SHARED is in ONE place, the `tank_mix` block of
`multi_target_spec.json` (the app reads the same file):

* per line: what identifies and accounts for one product (name, EPA number, active ingredient,
  concentration or "not on my record", unit, rate, REI, PHI, organic basis and listings, target
  pest and purpose, nutrients, the purchase: supplier, date, invoice, receipt, quantity, lot, CA
  permit). The target pest is the product's: Kocide goes on for fire blight and Entrust for
  codling moth from the same tank, and a shared value printed the wrong pest on one record;
* per line and per target: the amount of that product on that place;
* shared: everything about the one pass (date and times, method, area and where, wind,
  temperature, carrier, apparatus, applicator, notes, photos);
* line 1 only: the pass's fuel. One tractor pass burns its fuel once.

`application_group` is NOT the tank. It keeps meaning "one product over several parcels", which is
what the purchase table counts once and what a receipt is shared across. Each line gets its own,
derived from the tank id and the line number (`line_application_group`), so a retried request
derives the same ids, and only when the tank covers two or more targets.

THE PASS. Each line keeps its own manufacturing estimate; the application (fuel) emissions of the
pass are counted once per target, on the lowest-numbered line of the tank still recorded there
(`carries_application_pass`). Deleting that line hands the pass to the next one
(`history/signals.py`).
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass, field

from rest_framework.exceptions import ValidationError

from history.constants import CHEMICAL_EVENT_TYPE
from history.services import multi_target

ROLE_PRODUCT = "product"
ROLE_ADJUVANT = "adjuvant"

#: Keys of a tank request that belong to the envelope, not to any record.
ENVELOPE_KEYS = frozenset({"event_type", "tank_mix_group", "products", "targets"})


@dataclass(frozen=True)
class TankMixSpec:
    min_lines: int
    max_lines: int
    roles: frozenset
    per_line: frozenset
    per_line_default_from_shared: frozenset
    per_line_per_target: frozenset
    first_line_only: frozenset
    refused: frozenset


def _load(path=multi_target.SPEC_PATH) -> TankMixSpec:
    raw = json.loads(path.read_text(encoding="utf-8"))["types"][str(CHEMICAL_EVENT_TYPE)]["tank_mix"]
    return TankMixSpec(
        min_lines=int(raw["min_lines"]),
        max_lines=int(raw["max_lines"]),
        roles=frozenset(raw["roles"]),
        per_line=frozenset(raw["per_line"]),
        per_line_default_from_shared=frozenset(raw["per_line_default_from_shared"]),
        per_line_per_target=frozenset(raw["per_line_per_target"]),
        first_line_only=frozenset(raw["first_line_only"]),
        refused=frozenset(raw["refused"]),
    )


TANK = _load()


@dataclass
class TankLine:
    number: int
    role: str
    fields: dict = field(default_factory=dict)


@dataclass
class TankRequest:
    tank_id: uuid.UUID
    shared: dict
    lines: list
    targets: list
    target_keys: list


def _is_blank(value):
    return multi_target._is_blank(value)


def line_application_group(tank_id: uuid.UUID, line: int) -> uuid.UUID:
    """The `application_group` of one line across the targets of a tank. Deterministic, so a retry
    derives the same id; uuid5 of the client's random tank id, so it cannot meet another group."""
    return uuid.uuid5(tank_id, f"tank-mix-line-{line}")


def check_tank_envelope(data, event_type) -> TankRequest:
    """Validate a tank request's shape before anything is resolved or written.

    Raises ValidationError with every problem found; reads nothing from the database.
    """
    if event_type != CHEMICAL_EVENT_TYPE:
        raise ValidationError({"products": ["Only a spray takes several products from one tank."]})
    spec = multi_target.spec_for(event_type)

    present = [key for key in multi_target.SINGLE_RECORD_ONLY_KEYS if not _is_blank(data.get(key))]
    if present:
        raise ValidationError(
            {key: ["Not accepted with a tank mix: each target names its own parcel and season."] for key in present}
        )
    try:
        tank_id = uuid.UUID(str(data.get("tank_mix_group")))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError({"tank_mix_group": ["A UUID minted by the client is required."]})

    products = data.get("products")
    if not isinstance(products, list) or not all(isinstance(p, dict) for p in products):
        raise ValidationError({"products": ["Expected a list of objects, one per product in the tank."]})
    if len(products) < TANK.min_lines:
        raise ValidationError(
            {"products": ["A tank mix has two or more products. Log one product without `products`."]}
        )
    if len(products) > TANK.max_lines:
        raise ValidationError({"products": [f"At most {TANK.max_lines} products in one tank."]})

    raw_targets = data.get("targets")
    parcel_ids = multi_target.check_targets(raw_targets, min_targets=1)
    targets = [{**target, "parcel": parcel_id} for target, parcel_id in zip(raw_targets, parcel_ids)]
    keys = multi_target.target_keys(targets)

    shared = {key: value for key, value in data.items() if key not in ENVELOPE_KEYS}
    if shared.get("type") is not None and not isinstance(shared.get("type"), str):
        raise ValidationError({"type": ["Expected a subtype code."]})

    errors = multi_target.shared_errors(spec, shared, targets)
    refused = sorted(key for key in TANK.refused if not _is_blank(shared.get(key)))
    if refused:
        errors.setdefault("refused", []).append(
            f"Not accepted with a tank mix: {', '.join(refused)}. Each product is its own line in `products`."
        )
    extra = shared.get("extra_data") if isinstance(shared.get("extra_data"), dict) else {}
    per_line_only = TANK.per_line - TANK.per_line_default_from_shared
    misplaced = sorted(key for key in per_line_only if not _is_blank(shared.get(key)) or not _is_blank(extra.get(key)))
    if misplaced:
        errors.setdefault("shared", []).append(
            f"Send per product, inside each line of `products`: {', '.join(misplaced)}."
        )

    one_target = len(targets) == 1
    line_keys = TANK.per_line | {"tank_mix_role"} | (TANK.per_line_per_target if one_target else frozenset())
    lines = []
    for number, product in enumerate(products, start=1):
        problems = []
        unknown = sorted(set(product) - line_keys)
        if unknown:
            hint = (
                " The amount of each product on each parcel goes in that target's `products` list."
                if TANK.per_line_per_target & set(unknown)
                else ""
            )
            problems.append(f"Not a field of one product here: {', '.join(unknown)}.{hint}")
        role = product.get("tank_mix_role")
        if role not in TANK.roles:
            problems.append(f"`tank_mix_role` is one of: {', '.join(sorted(TANK.roles))}.")
        if problems:
            errors.setdefault("products", {})[str(number)] = problems
        lines.append(TankLine(number, role, {k: v for k, v in product.items() if k != "tank_mix_role"}))
    if "products" not in errors and not any(line.role == ROLE_PRODUCT for line in lines):
        errors["products"] = ["A tank holds at least one product, not only adjuvants."]

    allowed_in_target = (
        (spec.per_target_any() - TANK.per_line_per_target)
        | spec.either
        | multi_target.TARGET_ADDRESS_KEYS
        | {"products"}
    )
    for target, key in zip(targets, keys):
        problems = []
        unknown = sorted(set(target) - allowed_in_target)
        if unknown:
            hint = (
                " The amount of each product goes in this target's `products` list, one entry per line."
                if TANK.per_line_per_target & set(unknown)
                else ""
            )
            problems.append(f"Not a per-parcel field here: {', '.join(unknown)}.{hint}")
        amounts = target.get("products")
        if amounts is not None:
            if (
                not isinstance(amounts, list)
                or len(amounts) != len(products)
                or not all(a is None or isinstance(a, dict) for a in amounts)
            ):
                problems.append(f"`products` here is one entry per line of the tank ({len(products)}), in order.")
            else:
                for number, amount in enumerate(amounts, start=1):
                    amount = amount or {}
                    stray = sorted(set(amount) - TANK.per_line_per_target)
                    if stray:
                        problems.append(f"Line {number}: only the amount goes here, not {', '.join(stray)}.")
                    on_line = any(not _is_blank(products[number - 1].get(k)) for k in TANK.per_line_per_target)
                    here = any(not _is_blank(amount.get(k)) for k in TANK.per_line_per_target)
                    if one_target and on_line and here:
                        problems.append(f"Line {number}: send the amount on the line or in the target, not both.")
        if problems:
            errors.setdefault("targets", {})[key] = problems
    if errors:
        raise ValidationError(errors)

    return TankRequest(tank_id=tank_id, shared=shared, lines=lines, targets=targets, target_keys=keys)


def record_bodies(tank: TankRequest):
    """The serializer body of every record the tank writes, target by target, line by line.

    Yields `(target_index, line, body)`; the caller adds `history`. Each body is a deep copy: the
    serializer moves keys in and out of `extra_data` in place, and a dict shared between records
    would carry one line's active ingredient onto the next.
    """
    for index, target in enumerate(tank.targets):
        target_fields = {
            key: value
            for key, value in target.items()
            if key not in multi_target.TARGET_ADDRESS_KEYS and key != "products"
        }
        amounts = target.get("products") or [None] * len(tank.lines)
        for line, amount in zip(tank.lines, amounts):
            body = copy.deepcopy(tank.shared)
            body.update(copy.deepcopy(line.fields))
            body.update(copy.deepcopy(target_fields))
            body.update(copy.deepcopy(amount or {}))
            if line.number > 1:
                # One pass burns its fuel once: the fuel goes on line 1, never on lines 2..N.
                for key in TANK.first_line_only:
                    body.pop(key, None)
            yield index, line, body


# ------------------------------------------------------------------------------------------------
# The one pass
# ------------------------------------------------------------------------------------------------


def same_target_lines(event):
    """The records of `event`'s tank on the same target (season and block), `event` included."""
    from history.models import ChemicalEvent

    return ChemicalEvent.objects.filter(
        tank_mix_group=event.tank_mix_group,
        history_id=event.history_id,
        block_id=event.block_id,
    )


def _positive(value) -> bool:
    """A recorded number above zero (a Decimal, or a string such as "24" or "24 fl oz")."""
    if value is None:
        return False
    match = re.match(r"\s*(\d+(?:\.\d+)?)", str(value))
    return bool(match) and float(match.group(1)) > 0


def records_application_figure(record) -> bool:
    """Whether this record holds what its pass's application figure is computed from.

    A recorded amount of the product (never a count of dispensers, which the calculator does not
    convert), or the pass's recorded fuel. A record with neither cannot carry the pass: given the
    pass, it would either count nothing (an amount of 0) or count it on a default amount nobody
    recorded (a blank amount), while every other line skipped it.
    """
    from common.field_registry import is_count_unit

    if is_count_unit(getattr(record, "volume_unit", None)):
        return False
    if _positive(getattr(record, "application_fuel_consumed", None)):
        return True
    return _positive(getattr(record, "volume_numeric", None)) or _positive(getattr(record, "volume", None))


def _line_order(record):
    line = record.tank_mix_line if record.tank_mix_line is not None else 10**6
    return (line, record.pk or 0)


def carrier_of(records):
    """The ONE record, of these records of one target, that carries the pass: the lowest
    (line, pk) that records an application figure. None when none does, and then no record skips
    the pass. Ordered by pk after the line, so two records left with one line number (a block
    correction can do that) never both carry it."""
    for record in sorted(records, key=_line_order):
        if records_application_figure(record):
            return record
    return None


def pass_carrier(event):
    """The record that carries the tank's application pass on `event`'s target, or None (not a
    saved tank line, or no record there records an application figure)."""
    from history.models import ChemicalEvent

    # A saved record only: the carbon preview hands the calculator a plain stand-in object.
    if not isinstance(event, ChemicalEvent) or not event.tank_mix_group or event.pk is None:
        return None
    return carrier_of(same_target_lines(event))


def pass_carrier_line(event):
    """The line number of the record that carries the pass on `event`'s target, or None."""
    carrier = pass_carrier(event)
    return carrier.tank_mix_line if carrier is not None else None


def pass_counted_on_line(event):
    """The line this record's application pass is counted on INSTEAD, or None when this record
    carries it (a single product always does, and so does every line when none can)."""
    carrier = pass_carrier(event)
    if carrier is None or carrier.pk == event.pk:
        return None
    return carrier.tank_mix_line


def carries_application_pass(event) -> bool:
    return pass_counted_on_line(event) is None


FUEL_FIELDS = ("application_fuel_type", "application_fuel_consumed", "application_fuel_unit")


def hand_off_fuel(leaving, remaining):
    """Keep a pass's MEASURED fuel when the record that carried it leaves its target.

    The write path records the pass's fuel on one record (line 1), and the others never hold it
    (`record_bodies`). When that record is deleted, the next carrier would otherwise count the
    pass from an area estimate: a measured figure turned into an estimate with nothing saying so.
    The fuel is written onto the new carrier through `save()`, so the change is on its audit trail.
    Nothing is written when the leaving record did not carry the pass or recorded no fuel, or when
    the new carrier recorded fuel of its own. Returns the record written to, or None.
    """
    remaining = list(remaining)
    if not remaining or not _positive(getattr(leaving, "application_fuel_consumed", None)):
        return None
    if carrier_of([leaving, *remaining]) is not leaving:
        return None
    successor = carrier_of(remaining) or sorted(remaining, key=_line_order)[0]
    if _positive(successor.application_fuel_consumed):
        return None
    for name in FUEL_FIELDS:
        setattr(successor, name, getattr(leaving, name))
    successor.save(update_fields=list(FUEL_FIELDS))
    return successor


CARRIER_MOVE_REFUSED = (
    "This product holds the measured fuel of its tank's pass, and the tank's other products are "
    "still recorded on this block. Move them first and this one last: the fuel goes with the last "
    "product to leave."
)


def carrier_move_refusal(event, history_id, block_id, fuel=None):
    """The message refusing to move a record off its target, or None when the move is fine.

    Moving the record that carries a pass's measured fuel while other products of the tank stay on
    the block would leave them counting that pass from an estimate, and whose pass the fuel was is
    not something Trazo can decide. `fuel` is the fuel the record will hold after the change.
    """
    from history.services.block_ids import normalize_block_id

    if not getattr(event, "tank_mix_group", None) or getattr(event, "pk", None) is None:
        return None
    if (history_id, normalize_block_id(block_id)) == (event.history_id, event.block_id):
        return None
    if not _positive(event.application_fuel_consumed if fuel is None else fuel):
        return None
    carrier = pass_carrier(event)
    if carrier is None or carrier.pk != event.pk or not other_lines(event):
        return None
    return CARRIER_MOVE_REFUSED


def other_lines(event):
    """The other records of `event`'s tank on its target, in line order: what the detail and the
    packet name as "one tank with"."""
    if not getattr(event, "tank_mix_group", None):
        return []
    return list(same_target_lines(event).exclude(pk=event.pk).order_by("tank_mix_line", "pk"))


def role_label(role) -> str:
    return "adjuvant" if role == ROLE_ADJUVANT else "product"


def tank_cell_text(event, others=None) -> str:
    """ "line 1 of 3. One tank with: Kocide 3000-O, Dyne-Amic (adjuvant)", or "" outside a tank.

    What the packet's Application Context table and the audit CSV's Notes say about a tank line.
    "of 3" counts the lines recorded on this record's target.
    """
    if not getattr(event, "tank_mix_group", None):
        return ""
    others = other_lines(event) if others is None else others
    line = f"line {event.tank_mix_line} of {len(others) + 1}"
    if event.tank_mix_role == ROLE_ADJUVANT:
        line = f"{line}, adjuvant"
    with_text = one_tank_with_text(event, others)
    return f"{line}. {with_text}" if with_text else line


def one_tank_with_text(event, others=None) -> str:
    """ "One tank with: Kocide 3000-O, Dyne-Amic (adjuvant)", or "" outside a tank.

    The products are named as the records name them; an unnamed record reads as its line.
    """
    if not getattr(event, "tank_mix_group", None):
        return ""
    others = other_lines(event) if others is None else others
    names = []
    for other in others:
        name = (other.commercial_name or "").strip() or f"line {other.tank_mix_line}"
        if other.tank_mix_role == ROLE_ADJUVANT:
            name = f"{name} (adjuvant)"
        names.append(name)
    return f"One tank with: {', '.join(names)}" if names else ""
