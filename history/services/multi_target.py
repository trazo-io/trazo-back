"""One application logged on several parcels at once: the request contract and its rules.

A grower sprays one tank mix over three blocks. That is ONE application, but it is written as
ONE RECORD PER PARCEL: a record belongs to a season (`CommonEvent.history`), the § 205.103(b)(2)
trace-back runs field by field, and each record is corrected on its own. The records share an
`application_group` UUID.

What may differ between the records is decided per event type in ONE place,
`multi_target_spec.json` beside this module. The frontend reads the same file (a parity test in
trazo-app), so the two sides cannot disagree about which field is per parcel:

* SHARED fields are written to every record: the product, the label rate, the date, the
  applicator, REI/PHI, the weather, the purchase. A purchase is one purchase whatever it was
  spread over, so `quantity_purchased` is shared and the packet's purchase table counts it once
  per group (`audit_export_service._purchase_rows`).
* PER-TARGET fields are the amounts and the "where": volume and area treated, block, PUR site
  identifiers. They are keyed on the REQUEST names the serializer accepts (`volume_applied`, not
  the `volume` column), and each target runs through its own serializer, so the aliasing and the
  numeric derivation in `to_internal_value` run per record. Overriding only `volume_numeric`
  would leave the legacy `volume` string carrying the shared total, and the CA PUR export reads
  that string first (`pur_export_service`) while the packet reads the numeric twin: the two
  documents would disagree about the same spray.
* PER-TARGET BY SUBTYPE: per-parcel keys that only one subtype has (`irrigation_depth` for
  irrigation, `plants_established` for planting, `hive_count` for pollination).
* EITHER: a setting sent once in the shared body OR once per parcel, never both (a frost
  protection's trigger temperature, a canopy pass number, a plant spacing).
* REFUSED fields have no honest per-parcel value in a multi-parcel save: season summary totals,
  tank-mix partner volumes, a soil reading taken in one place. They are refused rather than
  copied. Fuel and machine hours are per parcel, never split or copied.
* REFUSED VALUES: a shared key that is honest for some values and not others. A carrier volume
  in gallons per acre is the same on every parcel the tank covered; a carrier volume as a total
  for the tank would be copied onto every record as if each parcel got all of it.

A per-target field sent in the SHARED body is refused too. Copying it to every record is the
exact defect this module exists to prevent, and a silent copy is what a client that forgot to
split a field would otherwise get.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from rest_framework.exceptions import ValidationError

MAX_TARGETS = 50

# Keys of the request body that belong to the multi-parcel envelope, not to the record.
ENVELOPE_KEYS = frozenset({"targets", "application_group", "event_type"})

# Keys the single-parcel path understands that make no sense, or are unsafe, with several
# records. `parcels`/`history` name ONE place; a plan item and a crew note are answered by ONE
# record (the crew-note path spends the note inside the request that answers it).
SINGLE_RECORD_ONLY_KEYS = ("parcels", "history", "plan_item_id", "field_note", "field_note_proposal")

# Per target, beside the per-type fields below.
TARGET_ADDRESS_KEYS = frozenset({"parcel", "history"})

SPEC_PATH = Path(__file__).with_name("multi_target_spec.json")


@dataclass(frozen=True)
class MultiTargetSpec:
    per_target: frozenset
    refused: frozenset
    # `extra_data` keys refused for the same reason as `refused` (summary-mode totals live there).
    refused_extra_data: frozenset
    # None = every subtype of the event type.
    subtypes: frozenset = None
    per_target_by_subtype: dict = field(default_factory=dict)
    either: frozenset = frozenset()
    # {key: frozenset(values)}: the shared key is refused only when it holds one of these values.
    refused_values: dict = field(default_factory=dict)

    def per_target_for(self, subtype) -> frozenset:
        return self.per_target | self.per_target_by_subtype.get(subtype, frozenset())

    def per_target_any(self) -> frozenset:
        """Keys that are per parcel for at least one subtype: never valid in the shared body. An
        irrigation's shared `applied_scope` would be copied onto every parcel just like a planting's."""
        return self.per_target.union(*self.per_target_by_subtype.values())


def _load_specs(path=SPEC_PATH) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    specs = {}
    for event_type, entry in raw["types"].items():
        subtypes = entry.get("subtypes")
        specs[int(event_type)] = MultiTargetSpec(
            per_target=frozenset(entry["per_target"]),
            refused=frozenset(entry["refused"]),
            # Every key refused at the top level is refused inside extra_data too (several tabs
            # mirror fields there); the file lists only the extra_data-only additions.
            refused_extra_data=frozenset(entry["refused_extra_data"]) | frozenset(entry["refused"]),
            subtypes=None if subtypes is None else frozenset(subtypes),
            per_target_by_subtype={k: frozenset(v) for k, v in entry.get("per_target_by_subtype", {}).items()},
            either=frozenset(entry.get("either", [])),
            refused_values={k: frozenset(v) for k, v in entry.get("refused_values", {}).items()},
        )
    return specs


SPECS = _load_specs()


def _is_blank(value):
    return value is None or value == "" or value == [] or value == {} or value is False


def _parcel_id(value):
    """A parcel id from JSON: an integer or a string of digits. `int()` alone would take `True`
    as parcel 1 and truncate `1.9` to parcel 1, naming a parcel the client never sent."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def spec_for(event_type):
    return SPECS.get(event_type)


def check_envelope(data, event_type):
    """Validate the request shape before anything is resolved or written.

    Returns `(shared, targets)`: the shared body (the record fields, envelope removed) and the
    target list. Raises ValidationError; nothing has been read from the database yet.
    """
    spec = spec_for(event_type)
    if spec is None:
        raise ValidationError({"targets": ["This activity type is logged on one parcel at a time."]})

    present = [key for key in SINGLE_RECORD_ONLY_KEYS if not _is_blank(data.get(key))]
    if present:
        raise ValidationError(
            {key: ["Not accepted with `targets`: each target names its own parcel and season."] for key in present}
        )

    targets = data.get("targets")
    if not isinstance(targets, list) or not all(isinstance(t, dict) for t in targets):
        raise ValidationError({"targets": ["Expected a list of objects."]})
    if len(targets) < 2:
        raise ValidationError({"targets": ["Send two or more parcels, or use `parcels` for one."]})
    if len(targets) > MAX_TARGETS:
        raise ValidationError({"targets": [f"At most {MAX_TARGETS} parcels per activity."]})

    parcel_ids = []
    for target in targets:
        parcel_id = _parcel_id(target.get("parcel"))
        if parcel_id is None:
            raise ValidationError({"targets": ["Every target needs a numeric `parcel`."]})
        parcel_ids.append(parcel_id)
    if len(set(parcel_ids)) != len(parcel_ids):
        raise ValidationError({"targets": ["A parcel appears more than once."]})

    shared = {key: value for key, value in data.items() if key not in ENVELOPE_KEYS}

    subtype = shared.get("type")
    if subtype is not None and not isinstance(subtype, str):
        # Used as a lookup key below; a list or an object here is a malformed request, not a 500.
        raise ValidationError({"type": ["Expected a subtype code."]})
    if spec.subtypes is not None and subtype not in spec.subtypes:
        raise ValidationError({"type": ["This kind of activity is logged on one parcel at a time."]})

    per_target = spec.per_target_for(subtype)
    extra = shared.get("extra_data") if isinstance(shared.get("extra_data"), dict) else {}

    errors = {}
    # A per-parcel key in the shared body, at the top level or inside extra_data, would be copied.
    # Any subtype's per-parcel keys count: they are never a shared fact.
    copied = sorted(
        {key for key in spec.per_target_any() if not _is_blank(shared.get(key)) or not _is_blank(extra.get(key))}
    )
    if copied:
        errors["shared"] = [f"Send per parcel, inside each target: {', '.join(copied)}."]
    refused = sorted(
        {key for key in spec.refused if not _is_blank(shared.get(key))}
        | {key for key in spec.refused_extra_data if not _is_blank(extra.get(key))}
    )
    if refused:
        errors["refused"] = [f"Not accepted when one activity covers several parcels: {', '.join(refused)}."]
    refused_values = sorted(
        f"{key}={shared.get(key)}"
        for key, values in spec.refused_values.items()
        if isinstance(shared.get(key), str) and shared.get(key) in values
    )
    if refused_values:
        errors.setdefault("refused", []).append(
            "Not accepted when one activity covers several parcels, because it would be copied onto "
            f"every parcel: {', '.join(refused_values)}. Send it as an amount per area instead."
        )
    twice = sorted(
        key
        for key in spec.either
        if (not _is_blank(shared.get(key)) or not _is_blank(extra.get(key)))
        and any(not _is_blank(target.get(key)) for target in targets)
    )
    if twice:
        errors["either"] = [f"Send once for every parcel or once per parcel, not both: {', '.join(twice)}."]

    allowed_in_target = per_target | spec.either | TARGET_ADDRESS_KEYS
    for target, parcel_id in zip(targets, parcel_ids):
        unknown = sorted(set(target) - allowed_in_target)
        if unknown:
            errors.setdefault("targets", {})[str(parcel_id)] = [f"Not a per-parcel field here: {', '.join(unknown)}."]
    if errors:
        raise ValidationError(errors)

    return shared, [{**target, "parcel": parcel_id} for target, parcel_id in zip(targets, parcel_ids)]
