"""Operator intake: a CSV in Trazo's own schema becomes records that point at the paper they came from.

The promise this keeps is the one in the pilot letter and in every cold email sent since 2026-10-20:
"send me your binder photos, your spreadsheet or your COG Pro export; you'll see a preview before
anything is saved". For a COG Pro export the importer beside this one reads their format. For
everything else (a handwritten spray sheet, an Excel log, a photo of a binder page) a person reads
the document and writes ONE flat CSV in the schema below, and this module turns it into records.

## Who does what

The operator (a setup account, `subscriptions.pilot_operator`) transcribes. The grower approves a
preview and stays the author (7 CFR 205.201(a)). Nothing here reads a photo or guesses a value: the
CSV is the operator's statement of what the document says, and a cell the operator could not read
stays EMPTY. The rules below exist so that an empty cell stays a visible gap instead of becoming an
invented number, the failure the COG Pro importer documents at `_map_area_unit`.

## The rules that refuse a row

* No date, or a date that is not `YYYY-MM-DD`: "mid May" and "Apr 10" are what a sheet says, and a
  record needs a day. The row waits for the grower.
* A number without a unit, a unit without a number, or a unit Trazo has no code for.
* A parcel the farm does not have, or a season that cannot be named without guessing (two open
  productions on the parcel), or a date inside a finished season (the API's own closed-record guard).
* A row on several parcels (`All`, or `Block 1; Block 2`) carrying a per-parcel amount: the sheet
  wrote one total for the whole orchard, and splitting it would invent the shares. Shared facts
  (product, rate, concentration, date) are copied to every record and the records share an
  `application_group`, exactly as the multi-parcel API writes them. Which kinds may fan out is
  read from `multi_target_spec.json`, never decided here.
* A row already recorded from the same document and locator: a fix-and-rerun writes only the rows
  that are new, so the batch is idempotent at row level.

A refused row is reported with its reason and its sheet row; nothing is silently dropped.

## Spray record columns (optional)

The 23 columns above are required in every file. A spray row (`fertilizer`, `pesticide`,
`fungicide`, `herbicide`) may also carry the spray record's own columns (overall review 2026-11,
OV-RK-C05). Each is optional: a file without it reads every cell of it as empty. Headers are
matched without regard to case, spaces or punctuation ("EPA Reg. No." is `epa_reg_no`), and the
aliases in `SPRAY_COLUMNS` are accepted. A filled spray column on a row of another kind refuses
the row, like any column the kind has no field for.

Column (model field): what it accepts.

* `epa_reg_no` (`epa_registration_number`), `applicator` (`applicator_name`), `applicator_license`
  (`applicator_certification`), `applicator_address`, `applicator_phone`, `supplier`
  (`supplier_name`), `purchase_invoice`, `input_lot` (`chemical_lot_number`), `apparatus_plate`
  (`apparatus_license_plate`): text, as long as the field holds.
* `rei_hours`, `phi_days`: a number the model accepts (0 to 168 hours, 0 to 365 days).
* `restricted_use` (`restricted_use_pesticide`): yes or no; yes needs `applicator_license`.
* `purchase_date`: `YYYY-MM-DD`. `quantity_purchased` + `quantity_purchased_unit`: a pair, the
  units of `amount_unit` for a spray.
* `organic_basis` (`organic_approved`): one of the model's codes, in any case. Nothing is mapped:
  "OMRI" is not `omri_listed`, it is a refused row.
* `wind_from`: N NE E SE S SW W NW calm. `wind_speed_mph`: 0 to 150. `air_temperature_f`: -40 to 140.
* `carrier_volume` + `carrier_volume_unit`: both or neither; `gal_per_acre`, `gal_total` (one parcel
  only), `l_per_ha`.
* `applied_by_business` (`applied_by_pcb`): yes or no. `firm_name` (`pcb_name`) and `firm_address`
  (`commercial_firm_address`) need it to be yes, as the app sends them only with the flag on.
* `concentration_not_on_record`, `time_not_on_record` (`concentration_not_recorded`,
  `time_not_recorded`): yes or no.
* `start_time`, `end_time` (`application_start`, `application_end`): `HH:MM`, 24-hour, the farm's
  wall clock. The start is also the record's time.
* `tank`: any label. `tank_role` (`tank_mix_role`): `product` (the default) or `adjuvant`.

Every value is checked by the rule the model already holds for its field (`_spray_values`): the
field's validators and choices, then `ChemicalEvent.clean()` for the rules that span fields. The
importer restates no range.

**A day without a time.** A spray row with no `start_time` is a day the source record gives no
clock time for, so the record is marked `time_not_recorded` and kept at the noon placeholder
(`history/services/not_on_source_record.py`). A row with a `start_time` keeps it. A row that says
`time_not_on_record` is `no` and gives no time contradicts itself and waits. A blank
`concentration` stays blank; it is marked not on the record only when that column says yes.

**A tank.** Rows naming the same `tank` on the same document, date and `parcel` cell are one tank:
written through `history/services/tank_mix.py` exactly as the API writes one, line order = row
order. What the pass shares (date and time, method, area, conditions, applicator, notes; the
split is the `tank_mix` block of `multi_target_spec.json`) must read the same on every row of the
tank, or every row of it waits with the disagreeing column named. A tank is written whole or not
at all, and a tank already recorded takes no new products.

## Provenance

Every record carries `extra_data["source"]` (`record_source.py`): the filed source document, the
locator on it ("sheet row 7"), the batch, the date. The audit dossier prints it beside the record.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from rest_framework.exceptions import ValidationError as ApiValidationError

from common.field_registry import UNIT_AMENDMENT, UNIT_APPLICATION_RATE, UNIT_AREA, UNIT_VOLUME, UNIT_YIELD
from documents.models import GeneratedDocument
from history.constants import (
    CHEMICAL_EVENT_TYPE,
    PEST_MANAGEMENT_EVENT_TYPE,
    PRODUCTION_EVENT_TYPE,
    SOIL_MANAGEMENT_EVENT_TYPE,
)
from history.models import ChemicalEvent, History, PestManagementEvent, ProductionEvent, SoilManagementEvent
from history.services import multi_target, tank_mix
from history.services.cogpro_import import ImportPlan, RowResult, _as_event_datetime
from history.services.record_source import KIND_TRANSCRIPTION, SOURCE_KEY, source_ref, write_record

#: Fixed namespace so the group id of one sheet row is the same on every run: a retry after a
#: failure cannot mint a second group for the same application.
INTAKE_NAMESPACE = uuid.UUID("6f3b1b1e-2c44-4a8e-9a53-7a2a0c5d9e11")

COLUMNS = (
    "kind",
    "date",
    "parcel",
    "production",
    "title",
    "product",
    "active_ingredient",
    "rate",
    "rate_unit",
    "concentration",
    "amount",
    "amount_unit",
    "area_treated",
    "area_unit",
    "target",
    "method",
    "variety",
    "lot",
    "applied_by",
    "observation",
    "private_note",
    "source_doc",
    "source_locator",
)

#: The spray record's optional columns: (column, aliases, the `ChemicalEvent` field it fills).
#: `tank` fills no field by itself: rows sharing it become one tank (`_resolve_tanks`).
SPRAY_COLUMNS = (
    ("epa_reg_no", ("epa_registration_number", "epa_reg", "epa_number", "epa_no"), "epa_registration_number"),
    ("rei_hours", ("rei",), "rei_hours"),
    ("phi_days", ("phi",), "phi_days"),
    ("restricted_use", ("restricted_use_pesticide", "rup"), "restricted_use_pesticide"),
    ("applicator", ("applicator_name",), "applicator_name"),
    (
        "applicator_license",
        ("applicator_licence", "applicator_certification", "license_number", "licence_number"),
        "applicator_certification",
    ),
    ("applicator_address", (), "applicator_address"),
    ("applicator_phone", (), "applicator_phone"),
    ("supplier", ("supplier_name",), "supplier_name"),
    ("purchase_date", (), "purchase_date"),
    ("purchase_invoice", ("invoice", "invoice_number"), "purchase_invoice"),
    ("input_lot", ("lot_number", "chemical_lot_number", "product_lot"), "chemical_lot_number"),
    ("quantity_purchased", (), "quantity_purchased"),
    ("quantity_purchased_unit", ("purchased_unit",), "quantity_purchased_unit"),
    ("organic_basis", ("organic_approved",), "organic_approved"),
    ("wind_from", ("wind_direction",), "wind_from"),
    ("wind_speed_mph", ("wind_mph", "wind_speed"), "wind_speed_mph"),
    ("air_temperature_f", ("temperature_f", "temp_f", "air_temp_f"), "air_temperature_f"),
    ("carrier_volume", (), "carrier_volume"),
    ("carrier_volume_unit", ("carrier_unit",), "carrier_volume_unit"),
    ("apparatus_plate", ("apparatus_license_plate", "license_plate"), "apparatus_license_plate"),
    ("applied_by_business", ("applied_by_pcb", "for_hire"), "applied_by_pcb"),
    ("firm_name", ("pcb_name", "business_name"), "pcb_name"),
    ("firm_address", ("commercial_firm_address", "business_address"), "commercial_firm_address"),
    ("concentration_not_on_record", ("concentration_not_recorded",), "concentration_not_recorded"),
    ("time_not_on_record", ("time_not_recorded",), "time_not_recorded"),
    ("start_time", ("time_started",), "application_start"),
    ("end_time", ("time_finished", "time_completed"), "application_end"),
    ("tank", ("tank_id", "tank_mix"), None),
    ("tank_role", ("tank_mix_role",), "tank_mix_role"),
)
OPTIONAL_COLUMNS = tuple(column for column, _aliases, _field in SPRAY_COLUMNS)
ALL_COLUMNS = COLUMNS + OPTIONAL_COLUMNS

#: Spray column -> its field, and field -> the CSV column the operator typed it in (for a refusal
#: they can act on).
_FIELD_OF = {column: model_field for column, _aliases, model_field in SPRAY_COLUMNS}
_SPRAY_COLUMN_OF = {model_field: column for column, _aliases, model_field in SPRAY_COLUMNS if model_field}

#: Every header spelling the reader accepts, normalised (`_header_key`), -> its column.
_HEADER_NAMES = {
    **{column: column for column in COLUMNS},
    **{column: column for column in OPTIONAL_COLUMNS},
    **{alias: column for column, aliases, _field in SPRAY_COLUMNS for alias in aliases},
}

_YES_NO_COLUMNS = ("restricted_use", "applied_by_business", "concentration_not_on_record", "time_not_on_record")
_YES = frozenset({"yes", "y"})
_NO = frozenset({"no", "n"})
#: Text columns: their length is checked by `_overlong`, against the model's max_length.
_TEXT_COLUMNS = (
    "epa_reg_no",
    "applicator",
    "applicator_license",
    "applicator_address",
    "applicator_phone",
    "supplier",
    "purchase_invoice",
    "input_lot",
    "apparatus_plate",
    "firm_name",
    "firm_address",
)
#: Columns whose value the model field itself parses and checks (a number, or one of its codes).
_MODEL_CHECKED_COLUMNS = (
    "rei_hours",
    "phi_days",
    "organic_basis",
    "wind_from",
    "wind_speed_mph",
    "air_temperature_f",
    "carrier_volume",
    "carrier_volume_unit",
)

ALL_PARCELS = "all"
PARCEL_SEPARATOR = ";"


@dataclass
class IntakePlan(ImportPlan):
    """An import plan plus what the file's header said: {optional column: the header as written}."""

    optional_columns: dict = field(default_factory=dict)


EVENT_MODELS = {
    "ChemicalEvent": (ChemicalEvent, CHEMICAL_EVENT_TYPE),
    "ProductionEvent": (ProductionEvent, PRODUCTION_EVENT_TYPE),
    "SoilManagementEvent": (SoilManagementEvent, SOIL_MANAGEMENT_EVENT_TYPE),
    "PestManagementEvent": (PestManagementEvent, PEST_MANAGEMENT_EVENT_TYPE),
}


@dataclass(frozen=True)
class Kind:
    """One row vocabulary entry: which model and subtype, and which columns have a home there."""

    key: str
    target: str  # "ChemicalEvent:FE", split the way cogpro_import does
    label: str
    product: Optional[str]  # model field for `product`, None = the kind takes no product
    product_required: bool
    amount: Optional[tuple]  # (numeric field, unit field, unit vocabulary)
    area: Optional[tuple]
    rate: Optional[tuple]
    target_field: Optional[str]
    method_field: Optional[str]
    name_field: Optional[str]  # None = the model keeps its name in extra_data (pest)
    chemical: bool = False
    lot_field: Optional[str] = None


def _codes(vocabulary):
    return {code for code, _label in vocabulary}


_CHEMICAL_AMOUNT = ("volume_numeric", "volume_unit", UNIT_VOLUME)
_CHEMICAL_AREA = ("area_numeric", "area_unit", UNIT_AREA)
_CHEMICAL_RATE = ("application_rate", "application_rate_unit", UNIT_APPLICATION_RATE)
_AREA_COVERED = ("area_covered", "area_unit", UNIT_AREA)


def _chemical(key, subtype, label):
    return Kind(
        key=key,
        target=f"ChemicalEvent:{subtype}",
        label=label,
        product="commercial_name",
        product_required=True,
        amount=_CHEMICAL_AMOUNT,
        area=_CHEMICAL_AREA,
        rate=_CHEMICAL_RATE,
        target_field="target_pest_disease",
        method_field="way_of_application",
        name_field="name",
        chemical=True,
    )


def _production(key, subtype, label, amount=None, lot_field=None):
    return Kind(
        key=key,
        target=f"ProductionEvent:{subtype}",
        label=label,
        product=None,
        product_required=False,
        amount=amount,
        area=_AREA_COVERED,
        rate=None,
        target_field=None,
        method_field=None,
        name_field="name",
        lot_field=lot_field,
    )


KINDS = {
    "fertilizer": _chemical("fertilizer", ChemicalEvent.FERTILIZER, "Fertilizer application"),
    "pesticide": _chemical("pesticide", ChemicalEvent.PESTICIDE, "Pesticide application"),
    "fungicide": _chemical("fungicide", ChemicalEvent.FUNGICIDE, "Fungicide application"),
    "herbicide": _chemical("herbicide", ChemicalEvent.HERBICIDE, "Herbicide application"),
    "harvest": _production(
        "harvest",
        ProductionEvent.HARVESTING,
        "Harvest",
        amount=("yield_quantity", "yield_unit", UNIT_YIELD),
        lot_field="harvest_lot_code",
    ),
    "irrigate": _production("irrigate", ProductionEvent.IRRIGATION, "Irrigation"),
    "cultivate": _production("cultivate", ProductionEvent.CULTIVATION, "Cultivation"),
    "mow": _production("mow", ProductionEvent.MOWING, "Mowing"),
    "prune": _production("prune", ProductionEvent.PRUNING, "Pruning"),
    "thin": _production("thin", ProductionEvent.THINNING, "Thinning"),
    "compost": Kind(
        key="compost",
        target=f"SoilManagementEvent:{SoilManagementEvent.ORGANIC_MATTER}",
        label="Compost application",
        product="amendment_product_name",
        product_required=True,
        amount=("amendment_amount_numeric", "amendment_amount_unit", UNIT_AMENDMENT),
        area=_AREA_COVERED,
        rate=None,
        target_field=None,
        method_field=None,
        name_field="name",
    ),
    "scout": Kind(
        key="scout",
        target=f"PestManagementEvent:{PestManagementEvent.SCOUTING}",
        label="Scouting",
        product=None,
        product_required=False,
        amount=None,
        area=_AREA_COVERED,
        rate=None,
        target_field="pest_species",
        method_field=None,
        name_field=None,
    ),
}

#: Columns that have a home on every kind.
_COMMON_COLUMNS = frozenset(
    {
        "kind",
        "date",
        "parcel",
        "production",
        "title",
        "area_treated",
        "area_unit",
        "variety",
        "applied_by",
        "observation",
        "private_note",
        "source_doc",
        "source_locator",
    }
)


def _columns_with_a_home(kind: Kind) -> frozenset:
    cols = set(_COMMON_COLUMNS)
    if kind.product:
        cols.add("product")
    if kind.chemical:
        cols |= {"active_ingredient", "concentration"}
        cols |= set(OPTIONAL_COLUMNS)
    if kind.rate:
        cols |= {"rate", "rate_unit"}
    if kind.amount:
        cols |= {"amount", "amount_unit"}
    if kind.target_field:
        cols.add("target")
    if kind.method_field:
        cols.add("method")
    if kind.lot_field:
        cols.add("lot")
    return frozenset(cols)


def _parse_iso_date(text):
    """`YYYY-MM-DD` only. The sheet's own "3/28/26" and "mid May" are the operator's to resolve,
    and a date the operator could not resolve stays empty rather than becoming a guess here."""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_number(text, column, problems):
    """A measured quantity: a plain positive decimal with a dot.

    Stricter than cogpro's `_parse_decimal`, which treats a comma as a thousands separator: a
    sheet that writes "2,5" means two and a half, and 25.0 on a spray record is a 10x error the
    preview cannot show (it prints the parsed value). The API path refuses a zero or negative
    area or amount in `clean()`; this path never calls it, so the refusal lives here.
    """
    if "," in text:
        problems.append(f"{column} {text!r} has a comma; write decimals with a dot and no thousands separator")
        return None
    try:
        number = float(text)
    except ValueError:
        problems.append(f"{column} {text!r} is not a number")
        return None
    if number != number or number in (float("inf"), float("-inf")):
        problems.append(f"{column} {text!r} is not a number")
        return None
    if number <= 0:
        problems.append(f"{column} {text!r} must be greater than 0")
        return None
    return number


def _pair(row, number_col, unit_col, vocabulary, problems):
    """A measurement is a number AND a unit Trazo has a code for, or nothing at all."""
    raw_number = row.get(number_col, "")
    raw_unit = row.get(unit_col, "")
    if not raw_number and not raw_unit:
        return None, None
    if raw_number and not raw_unit:
        problems.append(
            f"{number_col} {raw_number!r} has no {unit_col}; a number without its unit is not a measurement"
        )
        return None, None
    if raw_unit and not raw_number:
        problems.append(f"{unit_col} {raw_unit!r} has no {number_col}")
        return None, None
    number = _parse_number(raw_number, number_col, problems)
    if number is None:
        return None, None
    codes = _codes(vocabulary)
    if raw_unit not in codes:
        problems.append(f"{unit_col} {raw_unit!r} is not a unit Trazo stores; one of: {', '.join(sorted(codes))}")
        return None, None
    return number, raw_unit


def _chemical_field(name):
    return ChemicalEvent._meta.get_field(name)


def _parse_clock(row, column, problems):
    """`HH:MM`, 24-hour, the farm's wall clock (stored as UTC, the convention every reader of
    `application_start` follows: see the note on that field). None when the cell is empty."""
    text = row[column]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError:
        problems.append(f"{column} {text!r} is not HH:MM (24-hour); a time the sheet does not state stays empty")
        return None


def _choice_code(model_field, text):
    """The model's own code for `text`, matched without regard to case ("nw" is "NW"). Nothing else
    is mapped: a value that is not one of the codes goes to the field's check as typed, and fails."""
    for code, _label in model_field.choices or ():
        if str(code).casefold() == text.casefold():
            return code
    return text


def _model_problems(exc, row, column_of) -> list:
    """A model ValidationError as one refusal per field, named by the CSV column, in the model's words."""
    out = []
    for name, messages in exc.message_dict.items():
        column = column_of.get(name, name)
        text = " ".join(messages)
        model_field = ChemicalEvent._meta.get_field(name) if name in _SPRAY_COLUMN_OF else None
        if model_field is not None and model_field.choices:
            text += f" One of: {', '.join(str(code) for code, _label in model_field.choices)}."
        raw = row.get(column, "")
        out.append(f"{column} {raw!r}: {text}" if raw else f"{column}: {text}")
    return out


def _spray_values(row, day, column_of, problems) -> Optional[dict]:
    """The spray record columns of one row as `ChemicalEvent` values, or None with `problems` filled.

    Every value goes through the rule the model already holds for its field: the field's own
    parsing, validators and choices (`clean_fields`), then `ChemicalEvent.clean()` for the rules
    that span fields (a restricted-use product needs the applicator's licence, the REI and PHI
    ranges, a "not on the source record" flag never beside a value, a carrier volume with its
    unit). Text length is left to `_overlong`, which reads the same model. Nothing here restates a
    range, so a rule changed on the model changes here too.

    Returns {"fields": model values, "date": the record's datetime, "tank": label, "tank_role": role}.
    """
    found = len(problems)
    flags = {}
    for column in _YES_NO_COLUMNS:
        text = row[column]
        flags[column] = None
        if not text:
            continue
        if text.casefold() in _YES:
            flags[column] = True
        elif text.casefold() in _NO:
            flags[column] = False
        else:
            problems.append(f"{column} {text!r} is not yes or no")

    probe = {}
    checked = set()
    for column in _TEXT_COLUMNS:
        if row[column]:
            probe[_FIELD_OF[column]] = row[column]
    for column in _MODEL_CHECKED_COLUMNS:
        if row[column]:
            name = _FIELD_OF[column]
            probe[name] = _choice_code(_chemical_field(name), row[column])
            checked.add(name)

    if row["purchase_date"]:
        purchased = _parse_iso_date(row["purchase_date"])
        if purchased is None:
            problems.append(f"purchase_date {row['purchase_date']!r} is not YYYY-MM-DD")
        else:
            probe["purchase_date"] = purchased
    quantity, quantity_unit = _pair(
        row,
        "quantity_purchased",
        "quantity_purchased_unit",
        _chemical_field("quantity_purchased_unit").choices,
        problems,
    )
    if quantity is not None:
        # The text as typed, so the model field's own digit limits read it rather than a float.
        probe["quantity_purchased"] = row["quantity_purchased"]
        probe["quantity_purchased_unit"] = quantity_unit
        checked.add("quantity_purchased")

    start = _parse_clock(row, "start_time", problems)
    end = _parse_clock(row, "end_time", problems)
    if row["end_time"] and not row["start_time"]:
        problems.append(
            f"end_time {row['end_time']!r} has no start_time; the record's time is when the application "
            "started, so give the start the sheet shows, or leave both empty"
        )

    # A day with no clock time is what a day-only source record says: the record is marked so, and
    # the noon placeholder is never read as the time sprayed (`not_on_source_record`).
    stated = flags["time_not_on_record"]
    if row["start_time"]:
        time_flag = bool(stated)
    else:
        time_flag = True
        if stated is False:
            problems.append(
                "time_not_on_record is 'no' but the row gives no start_time; give the time the sheet "
                "shows, or leave time_not_on_record empty and the record says the time is not on it"
            )

    if (row["firm_name"] or row["firm_address"]) and not flags["applied_by_business"]:
        filled = ", ".join(c for c in ("firm_name", "firm_address") if row[c])
        problems.append(
            f"{filled} describe(s) an application made for hire; set applied_by_business to yes, or leave "
            "the firm empty"
        )
    role = ""
    if row["tank_role"]:
        # The roles the tank contract takes (`multi_target_spec.json`), not the model field's check:
        # Django skips `validate()` on a non-editable field, and `tank_mix_role` is one.
        role = _choice_code(_chemical_field("tank_mix_role"), row["tank_role"])
        if not row["tank"]:
            problems.append(f"tank_role {row['tank_role']!r} has no tank; a role is a product's place in a tank")
        elif role not in tank_mix.TANK.roles:
            problems.append(f"tank_role {row['tank_role']!r} is not one of: {', '.join(sorted(tank_mix.TANK.roles))}")

    def at(clock):
        return datetime.combine(day, clock, tzinfo=timezone.utc) if (day is not None and clock) else None

    probe.update(
        concentration=row["concentration"] or None,
        concentration_not_recorded=bool(flags["concentration_not_on_record"]),
        time_not_recorded=time_flag,
        application_start=at(start),
        application_end=at(end),
        restricted_use_pesticide=bool(flags["restricted_use"]),
        applied_by_pcb=bool(flags["applied_by_business"]),
    )
    instance = ChemicalEvent(**probe)
    try:
        instance.clean_fields(exclude=[f.name for f in ChemicalEvent._meta.fields if f.name not in checked])
    except DjangoValidationError as exc:
        problems.extend(_model_problems(exc, row, column_of))
        return None
    if len(problems) > found:
        return None
    try:
        instance.clean()
    except DjangoValidationError as exc:
        problems.extend(_model_problems(exc, row, column_of))
        return None

    values = {name: getattr(instance, name) for name in probe}
    when = values["application_start"] or (_as_event_datetime(day) if day is not None else None)
    return {
        "fields": values,
        "date": when,
        "tank": row["tank"],
        "tank_role": (role or tank_mix.ROLE_PRODUCT) if row["tank"] else "",
    }


def _parcel_names(text):
    if text.strip().lower() == ALL_PARCELS:
        return ALL_PARCELS
    names = [n.strip() for n in text.split(PARCEL_SEPARATOR)]
    return [n for n in names if n]


def _fan_out_allowed(event_type, subtype) -> bool:
    """Whether one row may become one record per parcel, read from the multi-parcel spec."""
    from history.services.multi_target import spec_for

    spec = spec_for(event_type)
    if spec is None:
        return False
    return spec.subtypes is None or subtype in spec.subtypes


def _season_for(parcel, named, problems):
    """The season a row writes to on one parcel: named, or the parcel's ONE open season.

    Same rule as the API's `_history_for_target`: two open seasons and no name is refused, and a
    finished season is reachable only by name.
    """
    if named:
        history = None
        if named.isdigit():
            history = History.objects.filter(id=int(named), parcel=parcel).first()
        else:
            try:
                history = History.objects.filter(public_id=uuid.UUID(named), parcel=parcel).first()
            except ValueError:
                history = None
        if history is None:
            problems.append(f"no production {named!r} on parcel {parcel.name!r}")
        return history
    open_seasons = list(History.objects.filter(parcel=parcel, finish_date__isnull=True).order_by("-start_date"))
    if not open_seasons:
        problems.append(f"parcel {parcel.name!r} has no open production; start one, or name the finished season")
        return None
    if len(open_seasons) > 1:
        problems.append(
            f"parcel {parcel.name!r} has {len(open_seasons)} open productions; name the one this row belongs to"
        )
        return None
    return open_seasons[0]


def _closed_season_reason(history, event_when):
    """The API's closed-record guard, as a reason instead of a 403."""
    from rest_framework.exceptions import PermissionDenied

    from history.views import EventViewSet

    try:
        EventViewSet._refuse_inside_closed_season(history, event_when)
    except PermissionDenied as exc:
        return str(exc.detail)
    return None


def _classification_text(product, active_ingredient):
    """What the National List classifier WILL store for this row, computed without saving.

    The classifier is the `pre_save` receiver itself, run on an unsaved instance, so the preview
    and the committed record cannot disagree. A prohibited listing is a WARNING the operator and
    the grower read before commit, never a refusal: the sheet says what was applied, and the
    record is the grower's to make.
    """
    from certifications.services.omri_verifier import OMRIProductVerifier
    from history.services.national_list_basis import confirmed_national_list_substance, unconfirmed_national_list
    from history.signals import auto_classify_chemical_against_national_list

    if not OMRIProductVerifier().health_check():
        return "National List: not seeded in this environment; the classification is made where it is", False

    instance = ChemicalEvent(
        commercial_name=product,
        extra_data={"active_ingredient": active_ingredient} if active_ingredient else {},
    )
    auto_classify_chemical_against_national_list(ChemicalEvent, instance)

    # Read through `national_list_basis`, like every other reader that turns the classification
    # into a statement: a confirmed listing may be cited, a partial-name suggestion may not.
    listed = confirmed_national_list_substance(instance)
    if listed is not None:
        text = f"National List: {listed.substance_name}, § {listed.cfr_section}, {listed.status}"
        if listed.is_conditionally_permitted:
            text += " (allowed only for the use the listing names)"
            return f"{text} [{instance.national_list_basis}]", False
        return f"{text} [{instance.national_list_basis}]", listed.status == "prohibited"
    suggestion, note = unconfirmed_national_list(instance)
    if suggestion is not None:
        return (
            f"National List: possible match {suggestion.substance_name} (§ {suggestion.cfr_section}), "
            f"{note}; name the active ingredient exactly as the label does",
            False,
        )
    return "National List: no listing matched this name; check the active ingredient on the label", False


def _recorded_locators(farm, doc_ids):
    """{(doc public_id, locator): "Model #id"} for every record already transcribed from these documents."""
    recorded = {}
    for model, _event_type in EVENT_MODELS.values():
        rows = model.objects.filter(
            history__parcel__establishment=farm,
            **{f"extra_data__{SOURCE_KEY}__doc__in": doc_ids},
        ).values_list("id", "extra_data")
        for pk, extra in rows:
            src = (extra or {}).get(SOURCE_KEY) or {}
            if src.get("doc") and src.get("locator"):
                recorded[(src["doc"], src["locator"])] = f"{model._meta.verbose_name} #{pk}"
    return recorded


_HEADER_NOISE = re.compile(r"[^0-9a-z]+")


def _header_key(text):
    """A header as the reader compares it: case, spaces and punctuation ignored, so "EPA Reg. No."
    and "Wind speed (mph)" read as `epa_reg_no` and `wind_speed_mph`."""
    return _HEADER_NOISE.sub("_", text.strip().casefold()).strip("_")


def _read_rows(file_obj):
    """(columns by position, the row reader, {optional column: header as written}, error)."""
    raw = file_obj.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(raw))
    try:
        written = [h.strip() for h in next(reader)]
    except StopIteration:
        return None, None, {}, "The file is empty."
    headers, unknown, spelled = [], [], {}
    for text in written:
        column = _HEADER_NAMES.get(_header_key(text)) if text else None
        if text and column is None:
            unknown.append(text)
        if column is not None:
            spelled.setdefault(column, []).append(text)
        headers.append(column)
    twice = {column: names for column, names in spelled.items() if len(names) > 1}
    if twice or written.count("") > 1:
        named = "; ".join(f"{column} ({', '.join(names)})" for column, names in twice.items())
        return None, None, {}, "A column appears twice in the header" + (f": {named}." if named else ".")
    missing = [c for c in COLUMNS if c not in spelled]
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"missing column(s): {', '.join(missing)}")
        if unknown:
            parts.append(
                f"unknown column(s): {', '.join(unknown)} (optional spray columns: {', '.join(OPTIONAL_COLUMNS)})"
            )
        return None, None, {}, "Not the intake schema: " + "; ".join(parts) + "."
    optional = {column: spelled[column][0] for column in OPTIONAL_COLUMNS if column in spelled}
    return headers, reader, optional, ""


def build_plan(file_obj, farm) -> ImportPlan:
    """Parse an intake CSV against `farm`. Reads the database, writes nothing.

    `plan.error` is a file-level refusal (wrong schema). Every row is either importable, with a
    payload `execute` can write, or skipped with every reason the operator needs to fix it.
    """
    headers, reader, optional, error = _read_rows(file_obj)
    if error:
        return IntakePlan(area=None, error=error)

    plan = IntakePlan(area=None, optional_columns=optional)
    parcels = {p.name.casefold(): p for p in farm.parcels.all().order_by("name")}
    docs = {
        str(d.public_id): d
        for d in GeneratedDocument.objects.filter(establishment=farm, source="upload").only("public_id", "title")
    }
    recorded = _recorded_locators(farm, list(docs))
    seen_locators = set()
    # Every row naming a tank, refused or not: a tank is written whole or not at all.
    tank_rows = []

    for line_no, raw in enumerate(reader, start=2):
        if not any((c or "").strip() for c in raw):
            continue
        row = dict.fromkeys(ALL_COLUMNS, "")
        row.update(
            {h: (raw[i].strip() if i < len(raw) and raw[i] is not None else "") for i, h in enumerate(headers) if h}
        )
        problems = []

        kind = KINDS.get(row["kind"].lower())
        if kind is None:
            problems.append(f"kind {row['kind']!r} is not one of: {', '.join(KINDS)}")

        if not row["date"]:
            problems.append("no date; the row waits for the grower")
            day = None
        else:
            day = _parse_iso_date(row["date"])
            if day is None:
                problems.append(
                    f"date {row['date']!r} is not YYYY-MM-DD; a day the sheet does not state stays empty, never guessed"
                )

        doc = None
        locator = row["source_locator"]
        if not row["source_doc"] or not locator:
            problems.append(
                "source_doc and source_locator are required: every record points at the document it came from"
            )
        else:
            doc = docs.get(row["source_doc"])
            if doc is None:
                problems.append(f"source_doc {row['source_doc']!r} is not an uploaded document on this farm")
            else:
                key = (row["source_doc"], locator)
                if key in seen_locators:
                    problems.append(f"source_locator {locator!r} appears twice in this file for the same document")
                seen_locators.add(key)
                if key in recorded:
                    result = RowResult(
                        line=line_no,
                        action="skip",
                        reason=f"already recorded as {recorded[key]}; nothing to do",
                        summary=f"{row['date']} · {row['kind']} · {locator}",
                        payload={
                            "source_locator": locator,
                            "source_doc": row["source_doc"],
                            "row": row,
                            "recorded": True,
                        },
                    )
                    plan.rows.append(result)
                    if row["tank"]:
                        tank_rows.append((result, row))
                    continue

        column_of = _column_of(kind) if kind is not None else {}
        spray = None
        if kind is not None:
            homeless = sorted(c for c in ALL_COLUMNS if row[c] and c not in _columns_with_a_home(kind))
            if homeless:
                hint = " (an input's lot goes in input_lot)" if kind.chemical and "lot" in homeless else ""
                problems.append(
                    f"kind {kind.key!r} has no field for: {', '.join(homeless)}; put it in observation{hint}"
                )
            if kind.product_required and not row["product"]:
                problems.append(f"kind {kind.key!r} needs a product")
            if kind.chemical:
                spray = _spray_values(row, day, column_of, problems)

        # Parcels, then the season on each.
        targets = []
        if kind is not None:
            names = _parcel_names(row["parcel"]) if row["parcel"] else []
            if names == ALL_PARCELS:
                chosen = list(parcels.values())
                if not chosen:
                    problems.append("parcel is 'All' but the farm has no parcels yet")
            else:
                chosen = []
                for name in names:
                    parcel = parcels.get(name.casefold())
                    if parcel is None:
                        problems.append(
                            f"no parcel named {name!r} on this farm; parcels: {', '.join(p.name for p in parcels.values()) or 'none'}"
                        )
                    elif parcel not in chosen:
                        chosen.append(parcel)
                if not names:
                    problems.append("no parcel")
            model_name, subtype = kind.target.split(":")
            event_type = EVENT_MODELS[model_name][1]
            if len(chosen) > 1:
                if not _fan_out_allowed(event_type, subtype):
                    problems.append(f"kind {kind.key!r} is logged on one parcel at a time; one row per parcel")
                for col in ("amount", "area_treated"):
                    if row[col]:
                        problems.append(
                            f"{col} on a row covering {len(chosen)} parcels would be copied to every one; "
                            "the sheet wrote one total, so give one row per parcel or leave it empty"
                        )
                if row["production"]:
                    problems.append("production names one season; a row on several parcels cannot name one")
                if spray is not None:
                    # A value honest on one parcel and not on several (a carrier total), read from
                    # the multi-parcel spec the API checks the same field against.
                    shared = multi_target.shared_errors(
                        multi_target.spec_for(event_type), spray["fields"], [{} for _parcel in chosen]
                    )
                    problems.extend(message for messages in shared.values() for message in messages)
            for parcel in chosen:
                season = _season_for(parcel, row["production"] if len(chosen) == 1 else "", problems)
                if season is not None:
                    targets.append(season)
            if day is not None:
                when = spray["date"] if spray is not None else _as_event_datetime(day)
                for season in targets:
                    closed = _closed_season_reason(season, when)
                    if closed:
                        problems.append(closed)

        # Measurements.
        amount = unit = area = area_unit = rate = rate_unit = None
        if kind is not None:
            if kind.amount:
                amount, unit = _pair(row, "amount", "amount_unit", kind.amount[2], problems)
            if kind.area:
                area, area_unit = _pair(row, "area_treated", "area_unit", kind.area[2], problems)
            if kind.rate:
                rate, rate_unit = _pair(row, "rate", "rate_unit", kind.rate[2], problems)

        if problems:
            result = RowResult(
                line=line_no,
                action="skip",
                reason="; ".join(problems),
                summary=f"{row['date'] or '(no date)'} · {row['kind'] or '(no kind)'} · {row['product'] or row['title'] or ''}".strip(
                    " ·"
                ),
                payload={"source_locator": locator, "source_doc": row["source_doc"], "row": row},
            )
            plan.rows.append(result)
            if row["tank"]:
                tank_rows.append((result, row))
            continue

        # From here every value has a home and a unit.
        title = row["title"] or _default_title(kind, row)
        fields = {
            "type": subtype,
            "date": spray["date"] if spray is not None else _as_event_datetime(day),
            "description": title,
            "observation": row["observation"] or None,
            "private_note": row["private_note"],
            "performed_by": row["applied_by"] or None,
            "variety": row["variety"] or None,
        }
        extra = {}
        if kind.name_field:
            fields[kind.name_field] = title
        else:
            extra["name"] = title
        if kind.product:
            fields[kind.product] = row["product"]
        if kind.chemical:
            fields["concentration"] = row["concentration"] or None
            if row["active_ingredient"]:
                extra["active_ingredient"] = row["active_ingredient"]
            # The legacy string beside the numeric twin, the way the API and cogpro write it; a
            # blank unit when nothing was measured, never the model's "gal" default (rehearsal
            # finding 14: a default unit on an unfilled field is an invented measurement).
            fields["volume"] = str(amount) if amount is not None else None
        if kind.key == "compost":
            fields["amendment_type"] = "compost"
            fields["amendment_amount"] = f"{amount:g} {unit}" if amount is not None else ""
        if kind.target_field and row["target"]:
            fields[kind.target_field] = row["target"]
        if kind.method_field and row["method"]:
            fields[kind.method_field] = row["method"]
        if kind.lot_field and row["lot"]:
            fields[kind.lot_field] = row["lot"]
        if kind.amount:
            fields[kind.amount[0]] = amount
            fields[kind.amount[1]] = unit or ""
        if kind.area:
            fields[kind.area[0]] = area
            fields[kind.area[1]] = area_unit or ""
        if kind.rate:
            fields[kind.rate[0]] = rate
            fields[kind.rate[1]] = rate_unit or ""
        if spray is not None:
            fields.update(spray["fields"])

        # Every text column against its column's limit, BEFORE the row is shown as "will be
        # recorded": `write_record` never calls full_clean(), and an over-length value would
        # surface as a DataError at commit that rolls back the whole batch with no row named.
        too_long = _overlong(EVENT_MODELS[model_name][0], fields, column_of)
        if too_long:
            result = RowResult(
                line=line_no,
                action="skip",
                reason="; ".join(too_long),
                summary=f"{day.isoformat()} · {kind.label} · {row['product'] or title}",
                payload={"source_locator": locator, "source_doc": row["source_doc"], "row": row},
            )
            plan.rows.append(result)
            if row["tank"]:
                tank_rows.append((result, row))
            continue

        classification, warning = "", False
        if kind.chemical:
            classification, warning = _classification_text(row["product"], row["active_ingredient"])

        group = str(uuid.uuid5(INTAKE_NAMESPACE, f"{row['source_doc']}|{locator}")) if len(targets) > 1 else None
        parcel_names = [t.parcel.name for t in targets]
        result = RowResult(
            line=line_no,
            action="import",
            summary=f"{day.isoformat()} · {kind.label} · {row['product'] or title} → {', '.join(parcel_names)}",
            payload={
                "kind": kind.key,
                "target": kind.target,
                "date": day,
                "histories": [t.id for t in targets],
                "parcels": parcel_names,
                "fields": fields,
                "extra": extra,
                "application_group": group,
                "tank": None,
                "classification": classification,
                "warning": warning,
                "source_doc": row["source_doc"],
                "source_doc_title": doc.title,
                "source_locator": locator,
            },
        )
        plan.rows.append(result)
        if row["tank"]:
            tank_rows.append((result, row))
            result.payload["tank_role"] = spray["tank_role"]
            result.payload["parcel_ids"] = [t.parcel_id for t in targets]
    _resolve_tanks(tank_rows)
    return plan


def _column_of(kind: Kind) -> dict:
    """Model field -> the CSV column the operator typed, for a refusal they can act on."""
    pairs = {
        kind.product: "product",
        kind.method_field: "method",
        kind.target_field: "target",
        kind.lot_field: "lot",
        "concentration": "concentration",
        "performed_by": "applied_by",
        "variety": "variety",
        "name": "title",
        "description": "title",
    }
    if kind.chemical:
        pairs.update(_SPRAY_COLUMN_OF)
        pairs.update(
            {
                "commercial_name": "product",
                "type": "kind",
                "observation": "observation",
                "private_note": "private_note",
                "volume": "amount",
                "volume_numeric": "amount",
                "volume_unit": "amount_unit",
                "area_numeric": "area_treated",
                "area_unit": "area_unit",
                "application_rate": "rate",
                "application_rate_unit": "rate_unit",
                "active_ingredient": "active_ingredient",
                "date": "start_time",
                "history": "production",
            }
        )
    return {field: column for field, column in pairs.items() if field}


def _overlong(model, fields, column_of) -> list:
    from django.core.exceptions import FieldDoesNotExist

    out = []
    for name, value in fields.items():
        if not isinstance(value, str):
            continue
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            continue
        limit = getattr(field, "max_length", None)
        if limit and len(value) > limit:
            column = column_of.get(name, name)
            out.append(
                f"{column} is {len(value)} characters and the record holds {limit}; shorten it and keep the "
                "full text in observation"
            )
    return out


def plan_fingerprint(plan: ImportPlan) -> str:
    """A hash of what the plan RESOLVES to: every row's action and reason, and for an importable
    row the records it would write (target, seasons, parcels, fields, group). The file hash says
    which file the grower saw; this says the farm still reads it the same way, so a parcel or a
    season created after the preview cannot turn a refused row into an unapproved record."""
    rows = []
    for row in plan.rows:
        p = row.payload
        rows.append(
            {
                "line": row.line,
                "action": row.action,
                "reason": row.reason,
                "target": p.get("target"),
                "histories": p.get("histories"),
                "parcels": p.get("parcels"),
                "fields": p.get("fields"),
                "extra": p.get("extra"),
                "group": p.get("application_group"),
                "tank": p.get("tank"),
                "source": [p.get("source_doc"), p.get("source_locator")],
            }
        )
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]


def _default_title(kind: Kind, row) -> str:
    if kind.product and row["product"]:
        return f"{kind.label}: {row['product']}"
    if kind.key == "harvest" and row["variety"]:
        return f"Harvest: {row['variety']}"
    return kind.label


# ------------------------------------------------------------------------------------------------
# Tanks: rows naming one tank become the records the API's tank write path makes
# ------------------------------------------------------------------------------------------------


def _tank_key(row) -> str:
    """Which rows are one tank: the same label on the same document, date and parcel cell."""
    names = _parcel_names(row["parcel"]) if row["parcel"] else []
    where = ALL_PARCELS if names == ALL_PARCELS else sorted({name.casefold() for name in names})
    return json.dumps([row["source_doc"], row["tank"].casefold(), row["date"], where])


def _refuse(result, row, reason):
    """Turn a row that would have been recorded into one that waits, with the tank's reason."""
    result.action = "skip"
    result.reason = reason
    result.payload = {"source_locator": row["source_locator"], "source_doc": row["source_doc"], "row": row}


def _locators(members) -> str:
    return ", ".join(row["source_locator"] or f"line {result.line}" for result, row in members)


def _tank_split(payload, spec, titled):
    """One row's record split the way the tank contract splits a request (the `tank_mix` block of
    `multi_target_spec.json`): (what the pass shares, this product's line, the place, left out).

    A blank amount on a tank over several parcels is left out rather than sent: the contract takes
    an amount only per target there, and the importer never splits one. Without a `title`, each
    line keeps its own "<Kind>: <product>" title, as the API derives one per product.
    """
    shared, line, place, left_out = {}, {}, {}, {}
    several = len(payload["histories"]) > 1
    for key, value in payload["fields"].items():
        if key in ("description", "name") and not titled:
            continue
        if key in tank_mix.TANK.per_line_per_target:
            if several and value in (None, ""):
                left_out[key] = value
            else:
                line[key] = value
        elif key in tank_mix.TANK.per_line:
            line[key] = value
        elif key in spec.per_target_any():
            place[key] = value
        else:
            shared[key] = value
    if payload["extra"].get("active_ingredient"):
        line["active_ingredient"] = payload["extra"]["active_ingredient"]
    return shared, line, place, left_out


def _tank_disagreement(label, members, spec) -> Optional[str]:
    """The refusal naming every shared column whose value differs across the tank's rows, or None."""
    first_result, first_row = members[0]
    titled = bool(first_row["title"])
    column_of = _column_of(KINDS[first_result.payload["kind"]])
    shared, _line, place, _left = _tank_split(first_result.payload, spec, titled)
    reference = {**shared, **place}
    differing = []
    for result, row in members[1:]:
        shared, _line, place, _left = _tank_split(result.payload, spec, titled)
        values = {**shared, **place}
        for key in sorted(set(reference) | set(values)):
            if reference.get(key) != values.get(key):
                differing.append(column_of.get(key, key))
        if row["title"] != first_row["title"]:
            differing.append("title")
        if result.payload["histories"] != first_result.payload["histories"]:
            differing.append("production")
    if not differing:
        return None
    parts = []
    for column in dict.fromkeys(differing):
        cells = ", ".join(f"{row['source_locator']}: {row.get(column, '')!r}" for _result, row in members)
        parts.append(f"{column} ({cells})")
    detail = "; ".join(parts)
    return (
        f"tank {label!r} is one pass, so what the pass shares must read the same on every row of it, "
        f"and these differ: {detail}"
    )


def _api_detail(detail) -> str:
    if isinstance(detail, dict):
        return "; ".join(f"{key}: {_api_detail(value)}" for key, value in detail.items())
    if isinstance(detail, (list, tuple)):
        return " ".join(_api_detail(item) for item in detail)
    return str(detail)


def _tank_records(tank_id, members, spec):
    """Every line's record, built by the API's own tank contract: `check_tank_envelope` checks the
    request (two to ten lines, a product among them, nothing per line sent as shared, no total
    copied onto several parcels) and `record_bodies` composes each record from it.

    Returns (the tank, {line number: body}, each row's split). Raises the contract's ValidationError.
    """
    titled = bool(members[0][1]["title"])
    first = members[0][0].payload
    splits = [_tank_split(result.payload, spec, titled) for result, _row in members]
    shared, _line, place, _left = splits[0]
    data = {
        **shared,
        "event_type": CHEMICAL_EVENT_TYPE,
        "tank_mix_group": str(tank_id),
        "products": [
            {**line, "tank_mix_role": result.payload["tank_role"]}
            for (result, _row), (_shared, line, _place, _left) in zip(members, splits)
        ],
        "targets": [
            {"parcel": parcel_id, "history": history_id, **place}
            for parcel_id, history_id in zip(first["parcel_ids"], first["histories"])
        ],
    }
    tank = tank_mix.check_tank_envelope(data, CHEMICAL_EVENT_TYPE)
    bodies = {}
    for _index, line, body in tank_mix.record_bodies(tank):
        # Every target of an imported tank holds the same values (an amount or an area on several
        # parcels is refused per row), so the first target's body is every target's.
        bodies.setdefault(line.number, body)
    return tank, bodies, splits


def _resolve_tanks(tank_rows):
    """Rows naming one tank become one tank, or every row of it waits.

    A tank is written whole or not at all, so one waiting row holds the rest. A tank already
    recorded (by these rows, or under the same tank id) takes no new products: its records are
    written once, like the API's tank, and a correction can never add a line to it. The tank id is
    derived from the tank's key, so a replay derives the same id and finds it.
    """
    spec = multi_target.spec_for(CHEMICAL_EVENT_TYPE)
    groups = {}
    for result, row in tank_rows:
        groups.setdefault(_tank_key(row), []).append((result, row))

    for key, group in groups.items():
        members = [(result, row) for result, row in group if result.action == "import"]
        if not members:
            continue
        label = members[0][1]["tank"]
        tank_id = uuid.uuid5(INTAKE_NAMESPACE, f"tank|{key}")
        recorded = [(result, row) for result, row in group if result.payload.get("recorded")]
        waiting = [
            (result, row) for result, row in group if result.action == "skip" and not result.payload.get("recorded")
        ]

        reason = None
        if recorded or ChemicalEvent.objects.filter(tank_mix_group=tank_id).exists():
            where = f" from {_locators(recorded)}" if recorded else ""
            reason = (
                f"tank {label!r} is already recorded{where}, and a recorded tank takes no new products; "
                "leave tank empty to record this product on its own"
            )
        elif waiting:
            reason = f"tank {label!r} is recorded whole or not at all, and these rows of it wait: {_locators(waiting)}"
        elif len(members) < tank_mix.TANK.min_lines:
            row = members[0][1]
            reason = (
                f"tank {label!r} has one product on {row['date']}, {row['parcel']}; a tank holds "
                f"{tank_mix.TANK.min_lines} or more, and its rows name the same date and parcel. Leave "
                "tank empty for a single product"
            )
        else:
            reason = _tank_disagreement(label, members, spec)
        if reason is None:
            try:
                tank, bodies, splits = _tank_records(tank_id, members, spec)
            except ApiValidationError as exc:
                reason = f"tank {label!r}: {_api_detail(exc.detail)}"
        if reason:
            for result, row in members:
                _refuse(result, row, reason)
            continue

        titled = bool(members[0][1]["title"])
        several = len(members[0][0].payload["histories"]) > 1
        for line, (result, _row), (_shared, _line, _place, left_out) in zip(tank.lines, members, splits):
            p = result.payload
            body = dict(bodies[line.number])
            active = body.pop("active_ingredient", None)
            fields = {**left_out, **body}
            if not titled:
                fields["description"] = p["fields"]["description"]
                fields["name"] = p["fields"]["name"]
            extra = {k: v for k, v in p["extra"].items() if k != "active_ingredient"}
            if active:
                extra["active_ingredient"] = active
            p["fields"] = fields
            p["extra"] = extra
            p["tank"] = {
                "group": str(tank_id),
                "label": label,
                "line": line.number,
                "lines": len(members),
                "role": line.role,
            }
            # Each line over several parcels is its own "one product, several parcels" group, as
            # the API derives it; never the tank (the purchase table counts a group's purchase once).
            p["application_group"] = str(tank_mix.line_application_group(tank_id, line.number)) if several else None


def execute(plan: ImportPlan, farm, created_by, batch: str) -> dict:
    """Write every importable row as records on `farm`, all or nothing.

    `created_by` is the operator who ran the import. Each record carries `extra_data["source"]`
    naming the filed document, the locator, and `batch` (the hash of the CSV the grower previewed).
    """
    if plan.error:
        raise ValueError(plan.error)
    created = []
    tanks = sorted({row.payload["tank"]["group"] for row in plan.importable if row.payload.get("tank")})
    with transaction.atomic():
        # The API's replay rule for a tank id (`_replay_multi_target`): a tank already written is
        # never written again. `build_plan` refuses such rows; this holds if the farm changed since.
        for tank_id in tanks:
            if ChemicalEvent.objects.filter(tank_mix_group=uuid.UUID(tank_id)).exists():
                raise ValueError(f"tank {tank_id} is already recorded; build the plan again before committing")
        for row in plan.importable:
            p = row.payload
            model_name, _subtype = p["target"].split(":")
            model, _event_type = EVENT_MODELS[model_name]
            group = uuid.UUID(p["application_group"]) if p["application_group"] else None
            fields = dict(p["fields"])
            tank = p.get("tank")
            if tank:
                fields.update(
                    tank_mix_group=uuid.UUID(tank["group"]), tank_mix_line=tank["line"], tank_mix_role=tank["role"]
                )
            for history_id in p["histories"]:
                history = History.objects.select_related("parcel__establishment").get(id=history_id)
                if history.parcel.establishment_id != farm.id:
                    raise ValueError(f"production {history_id} is not on farm {farm.id}")
                extra = dict(p["extra"])
                extra[SOURCE_KEY] = source_ref(
                    KIND_TRANSCRIPTION,
                    locator=p["source_locator"],
                    doc=p["source_doc"],
                    doc_title=p["source_doc_title"],
                    batch=batch,
                )
                created.append(
                    write_record(
                        model,
                        history=history,
                        fields=dict(fields),
                        extra=extra,
                        created_by=created_by,
                        application_group=group,
                    )
                )
    return {"created": len(created), "skipped": len(plan.skipped), "records": created}
