"""One application logged on several parcels at once: the request contract and its rules.

A grower sprays one tank mix over three blocks. That is ONE application, but it is written as
ONE RECORD PER PARCEL: a record belongs to a season (`CommonEvent.history`), the § 205.103(b)(2)
trace-back runs field by field, and each record is corrected on its own. The records share an
`application_group` UUID.

What may differ between the records is decided HERE, per event type, and nowhere else:

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
* REFUSED fields have no honest per-parcel value in a multi-parcel save: season summary totals,
  tank-mix partner volumes, fuel and machine hours. They are refused rather than copied.

A per-target field sent in the SHARED body is refused too. Copying it to every record is the
exact defect this module exists to prevent, and a silent copy is what a client that forgot to
split a field would otherwise get.
"""

from dataclasses import dataclass

from rest_framework.exceptions import ValidationError

from history.constants import CHEMICAL_EVENT_TYPE, SOIL_MANAGEMENT_EVENT_TYPE

MAX_TARGETS = 50

# Keys of the request body that belong to the multi-parcel envelope, not to the record.
ENVELOPE_KEYS = frozenset({"targets", "application_group", "event_type"})

# Keys the single-parcel path understands that make no sense, or are unsafe, with several
# records. `parcels`/`history` name ONE place; a plan item and a crew note are answered by ONE
# record (the crew-note path spends the note inside the request that answers it).
SINGLE_RECORD_ONLY_KEYS = ("parcels", "history", "plan_item_id", "field_note", "field_note_proposal")

# Per target, beside the per-type fields below.
TARGET_ADDRESS_KEYS = frozenset({"parcel", "history"})


@dataclass(frozen=True)
class MultiTargetSpec:
    per_target: frozenset
    refused: frozenset
    # `extra_data` keys refused for the same reason as `refused` (summary-mode totals live there).
    refused_extra_data: frozenset
    # None = every subtype of the event type.
    subtypes: frozenset = None


_CHEMICAL_TOTALS = frozenset(
    {
        "area_treated_total",
        "volume_applied_total",
        "active_ingredient_total_kg",
        "nitrogen_total_kg",
        "phosphorus_total_kg",
        "potassium_total_kg",
        "fuel_consumption_total",
    }
)

SPECS = {
    CHEMICAL_EVENT_TYPE: MultiTargetSpec(
        per_target=frozenset(
            {
                # The amount and the area treated, under every name the serializer accepts.
                "volume_applied",
                "volume",
                "volume_numeric",
                "area_treated",
                "area",
                "area_numeric",
                # Where on the parcel. Copying "rows 1-12" to every block is false.
                "applied_scope",
                "applied_scope_detail",
                "block_id",
                "planted_area",
                # CA PUR site identity: the export prints these per row and they override the
                # parcel's own values, so a copy files parcel A's site on parcel B's row.
                "site_id",
                "application_county",
                "mtrs_section",
                "mtrs_township",
                "mtrs_range",
                "mtrs_base_meridian",
            }
        ),
        refused=frozenset({"tank_mix_partners", "application_fuel_consumed"}) | _CHEMICAL_TOTALS,
        refused_extra_data=_CHEMICAL_TOTALS,
    ),
    SOIL_MANAGEMENT_EVENT_TYPE: MultiTargetSpec(
        per_target=frozenset({"amendment_amount", "amendment_amount_numeric", "area_covered", "block_id"}),
        refused=frozenset(
            {
                "fuel_consumed",
                "equipment_hours",
                "is_summary",
                "area_covered_total",
                "event_count",
                "total_grazing_days",
                "animal_count",
            }
        ),
        refused_extra_data=frozenset({"area_covered_total"}),
        # Spreading an amendment (lime, gypsum, compost, manure) over several blocks. Soil tests,
        # tillage, grazing, habitat and pile composting are per-place observations or work and stay
        # single-parcel.
        subtypes=frozenset({"PA", "OM"}),
    ),
}


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

    if spec.subtypes is not None and shared.get("type") not in spec.subtypes:
        raise ValidationError({"type": ["This kind of activity is logged on one parcel at a time."]})

    errors = {}
    copied = sorted(key for key in spec.per_target if not _is_blank(shared.get(key)))
    if copied:
        errors["shared"] = [f"Send per parcel, inside each target: {', '.join(copied)}."]
    refused = sorted(key for key in spec.refused if not _is_blank(shared.get(key)))
    extra = shared.get("extra_data") if isinstance(shared.get("extra_data"), dict) else {}
    refused += sorted(key for key in spec.refused_extra_data if not _is_blank(extra.get(key)))
    if refused:
        errors["refused"] = [f"Not accepted when one activity covers several parcels: {', '.join(refused)}."]

    allowed_in_target = spec.per_target | TARGET_ADDRESS_KEYS
    for target, parcel_id in zip(targets, parcel_ids):
        unknown = sorted(set(target) - allowed_in_target)
        if unknown:
            errors.setdefault("targets", {})[str(parcel_id)] = [f"Not a per-parcel field here: {', '.join(unknown)}."]
    if errors:
        raise ValidationError(errors)

    return shared, [{**target, "parcel": parcel_id} for target, parcel_id in zip(targets, parcel_ids)]
