"""Canonical shape for `Parcel.buffer_zones` — one vocabulary, one normalizer.

## Why this exists

`buffer_zones` is an untyped JSON blob with more than one writer, and until 2026-08-09 each
writer owned a different set of key spellings:

  * `ParcelViewSet.application` (the OSP Parcel Application wizard) wrote
    `adjacent_is_organic` / `crop_grown_in_buffer` / `buffer_width_ft` /
    `prohibited_use_last_date`.
  * `CreateParcelSerializer.validate_buffer_zones` (the Parcel page) rebuilt every row from a
    whitelist spelled `adjacent_organic` / `crop_in_buffer` / `buffer_width_m`.

Because the serializer *rebuilt* rather than merged, one save on the Parcel page destroyed the
wizard's answers, silently turned "the adjoining land is certified organic" into an affirmative
`False`, and dropped the § 205.202(c) prohibited-use date that decides whether a buffer is
required at all. The row then carried the other vocabulary, so the wizard's next PUT was
rejected with `unknown buffer keys` — the server refusing the payload its own GET had served.

Every writer now goes through `normalize_buffer_rows`. Adding a key means adding it HERE, once.

## Rules the normalizer enforces

- **Legacy spellings are accepted and mapped**, never dropped. If both spellings arrive, the
  canonical one wins.
- **An unanswered question stays unanswered.** Booleans are `None` when neither spelling is
  present — never `False`. A stored `False` is an affirmative "no" that the operator did not
  make, which is the same trap `clean_transport_method` avoids by refusing to be a boolean.
- **Both width units are always present and consistent**, derived from whichever one arrived.
  The farmer-facing entry unit is feet (the Common OSP's own example is "25-ft."); the audit
  export renders metres. Neither writer should have to know about the other's unit.
- **Unknown keys are rejected**, so a typo fails loudly instead of vanishing into the blob.
- **`direction` identifies the boundary and is required**; every other field is optional, but a
  row carrying nothing except a direction is an empty row and is rejected. A boundary whose only
  content is a `prohibited_use_last_date` is NOT empty — that date is the record proving the
  boundary needs no buffer at all.
"""

from __future__ import annotations

from datetime import date as _date

# The complete vocabulary. Every normalized row carries exactly these keys.
CANONICAL_KEYS = (
    "direction",
    "adjoining_land_use",
    "buffer_type",
    "buffer_width_ft",
    "buffer_width_m",
    "crop_grown_in_buffer",
    "adjacent_is_organic",
    "drift_risk",
    "prevention",
    "neighbor_notified",
    "neighbor_notification_date",
    # Date the adjoining land last received a prohibited material — decides whether a buffer
    # is required on this boundary at all (§ 205.202(c)).
    "prohibited_use_last_date",
    # Whether a crop grows in the buffer, as a yes/no of its own (2026-11-06). OTCO C2 2.2 and
    # CCOF ORGB49 D1 ask "Is crop grown in buffer area? (Y/N)"; `crop_grown_in_buffer` is the
    # crop's name, so an empty name could not say "no" and printed the same as an unanswered
    # border. True with no name is a yes; a name with False contradicts itself and is refused.
    "buffer_crop_grown",
    # WSDA AGR 2264 ref 14: "Include distance from prohibited material applications". Feet, the
    # unit the buffer width is entered in. Not the width: a 30-ft strip can sit 200 ft from the
    # sprayed rows.
    "prohibited_use_distance_ft",
)

# Pre-2026-08-09 spellings written by the Parcel page and its compliance card. Kept forever:
# they are what the migration reads, and an old client may still send them.
LEGACY_ALIASES = {
    "adjacent_organic": "adjacent_is_organic",
    "crop_in_buffer": "crop_grown_in_buffer",
}

ACCEPTED_KEYS = frozenset(CANONICAL_KEYS) | frozenset(LEGACY_ALIASES)

# Booleans the pre-2026-08-09 serializer stamped onto EVERY row whether or not the operator
# answered. A stored `False` in one of these carries no operator intent and must not be read
# as "the neighbour is not certified organic".
#
# Deliberately excludes `adjacent_is_organic`: that key is written only by the Parcel
# Application wizard, and only when a farmer touches the checkbox, so a `False` there IS the
# answer and must survive.
LEGACY_STAMPED_BOOLEANS = ("adjacent_organic", "neighbor_notified")

_TEXT_KEYS = ("buffer_type", "crop_grown_in_buffer", "drift_risk", "prevention")
_BOOL_KEYS = ("adjacent_is_organic", "neighbor_notified", "buffer_crop_grown")
_DATE_KEYS = ("neighbor_notification_date", "prohibited_use_last_date")

_FEET_PER_METRE = 3.28084


class BufferZoneError(ValueError):
    """Raised with a farmer-legible message; callers map it to a 400."""


def _text(value):
    if value is None:
        return None
    return str(value).strip() or None


def _tristate(row, key):
    """True / False / None — absent means unanswered, not "no"."""
    if key not in row or row[key] is None:
        return None
    value = row[key]
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _iso_date(value, key, index):
    text = _text(value)
    if text is None:
        return None
    try:
        _date.fromisoformat(text)
    except ValueError:
        raise BufferZoneError(f"buffer_zones[{index}].{key} must be an ISO date (YYYY-MM-DD)")
    return text


def _distance(row, index):
    """`prohibited_use_distance_ft` as a non-negative number of feet, or None."""
    raw = row.get("prohibited_use_distance_ft")
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise BufferZoneError(f"buffer_zones[{index}].prohibited_use_distance_ft must be a number")
    if value < 0:
        raise BufferZoneError(f"buffer_zones[{index}].prohibited_use_distance_ft cannot be negative")
    return value


def _width(row, index):
    """Return (feet, metres).

    **Feet is the entry unit and the source of truth.** Every UI that collects a buffer width
    collects feet — the Common OSP's own worked example is "25-ft." and the operators are in
    the US. `buffer_width_m` is a DERIVED value kept on the record only because the audit
    export renders metres.

    Metres is therefore always recomputed from feet whenever feet is present, and is never
    trusted as an independent input. Doing otherwise means two editable numbers for one
    quantity: a row saved by a surface that edits feet and then by a surface that edits metres
    keeps both values, they disagree, and the buffer width on the compliance record depends on
    which reader you ask. Deriving feet FROM metres happens only for rows written before
    migration 0023, which carried metres alone.
    """

    def _number(key):
        raw = row.get(key)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise BufferZoneError(f"buffer_zones[{index}].{key} must be a number")

    feet = _number("buffer_width_ft")
    metres = _number("buffer_width_m")
    for label, value in (("buffer_width_ft", feet), ("buffer_width_m", metres)):
        if value is not None and value < 0:
            raise BufferZoneError(f"buffer_zones[{index}].{label} cannot be negative")
    if feet is not None:
        metres = round(feet / _FEET_PER_METRE, 1)
    elif metres is not None:
        feet = round(metres * _FEET_PER_METRE, 1)
    return feet, metres


def normalize_buffer_row(row, index: int = 0) -> dict:
    """Normalize one boundary record to `CANONICAL_KEYS`. Raises `BufferZoneError`."""
    if not isinstance(row, dict):
        raise BufferZoneError(f"buffer_zones[{index}] must be an object")

    unknown = sorted(set(row) - ACCEPTED_KEYS)
    if unknown:
        raise BufferZoneError(f"unknown buffer keys: {unknown}")

    # Canonical spelling wins when a client sends both.
    merged = dict(row)
    for legacy, canonical in LEGACY_ALIASES.items():
        if legacy in merged:
            value = merged.pop(legacy)
            merged.setdefault(canonical, value)

    direction = _text(merged.get("direction"))
    if not direction:
        raise BufferZoneError(f"buffer_zones[{index}] requires a 'direction' to identify the boundary")

    feet, metres = _width(merged, index)
    normalized = {
        "direction": direction,
        "adjoining_land_use": _text(merged.get("adjoining_land_use")),
        "buffer_width_ft": feet,
        "buffer_width_m": metres,
    }
    for key in _TEXT_KEYS:
        normalized[key] = _text(merged.get(key))
    for key in _BOOL_KEYS:
        normalized[key] = _tristate(merged, key)
    for key in _DATE_KEYS:
        normalized[key] = _iso_date(merged.get(key), key, index)
    normalized["prohibited_use_distance_ft"] = _distance(merged, index)
    if normalized["buffer_crop_grown"] is False and normalized["crop_grown_in_buffer"]:
        raise BufferZoneError(
            f"buffer_zones[{index}] ('{direction}') says no crop is grown in the buffer but names "
            f"'{normalized['crop_grown_in_buffer']}'"
        )

    # A direction on its own is an empty row. Anything else on the boundary makes it a
    # real record — including a lone prohibited-use date, which is precisely the record
    # that proves a boundary needs NO buffer (§ 205.202(c)).
    if not any(value is not None for key, value in normalized.items() if key != "direction"):
        raise BufferZoneError(
            f"buffer_zones[{index}] ('{direction}') is empty — record the adjoining land use, "
            f"the buffer, or the date the adjoining land last received a prohibited material"
        )
    return normalized


def normalize_buffer_rows(rows) -> list:
    """Normalize a whole `buffer_zones` list. Raises `BufferZoneError`."""
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise BufferZoneError("buffer_zones must be a list of boundary records")
    return [normalize_buffer_row(row, i) for i, row in enumerate(rows)]


def drop_stamped_booleans(row: dict) -> dict:
    """Return a copy of `row` with meaningless stamped `False` values removed.

    Used by migration product.0023 before normalizing a pre-existing row, so a `False` the
    old serializer wrote unprompted becomes "unanswered" rather than an assertion about a
    neighbour's certification status that the operator never made. See
    `LEGACY_STAMPED_BOOLEANS` for why `adjacent_is_organic` is not in that list.
    """
    cleaned = dict(row)
    for key in LEGACY_STAMPED_BOOLEANS:
        if cleaned.get(key) is False:
            cleaned.pop(key)
    return cleaned
