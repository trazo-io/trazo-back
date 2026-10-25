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

## Provenance

Every record carries `extra_data["source"]` (`record_source.py`): the filed source document, the
locator on it ("sheet row 7"), the batch, the date. The audit dossier prints it beside the record.
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from django.db import transaction

from common.field_registry import UNIT_AMENDMENT, UNIT_APPLICATION_RATE, UNIT_AREA, UNIT_VOLUME, UNIT_YIELD
from documents.models import GeneratedDocument
from history.constants import (
    CHEMICAL_EVENT_TYPE,
    PEST_MANAGEMENT_EVENT_TYPE,
    PRODUCTION_EVENT_TYPE,
    SOIL_MANAGEMENT_EVENT_TYPE,
)
from history.models import ChemicalEvent, History, PestManagementEvent, ProductionEvent, SoilManagementEvent
from history.services.cogpro_import import ImportPlan, RowResult, _as_event_datetime, _parse_decimal
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

ALL_PARCELS = "all"
PARCEL_SEPARATOR = ";"

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
    number = _parse_decimal(raw_number)
    if number is None:
        problems.append(f"{number_col} {raw_number!r} is not a number")
        return None, None
    codes = _codes(vocabulary)
    if raw_unit not in codes:
        problems.append(f"{unit_col} {raw_unit!r} is not a unit Trazo stores; one of: {', '.join(sorted(codes))}")
        return None, None
    return number, raw_unit


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


def _read_rows(file_obj):
    raw = file_obj.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(raw))
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration:
        return None, None, "The file is empty."
    missing = [c for c in COLUMNS if c not in headers]
    unknown = [h for h in headers if h and h not in COLUMNS]
    if len(headers) != len(set(headers)):
        return None, None, "A column appears twice in the header."
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"missing column(s): {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown column(s): {', '.join(unknown)}")
        return None, None, "Not the intake schema: " + "; ".join(parts) + "."
    return headers, reader, ""


def build_plan(file_obj, farm) -> ImportPlan:
    """Parse an intake CSV against `farm`. Reads the database, writes nothing.

    `plan.error` is a file-level refusal (wrong schema). Every row is either importable, with a
    payload `execute` can write, or skipped with every reason the operator needs to fix it.
    """
    headers, reader, error = _read_rows(file_obj)
    if error:
        return ImportPlan(area=None, error=error)

    plan = ImportPlan(area=None)
    parcels = {p.name.casefold(): p for p in farm.parcels.all().order_by("name")}
    docs = {
        str(d.public_id): d
        for d in GeneratedDocument.objects.filter(establishment=farm, source="upload").only("public_id", "title")
    }
    recorded = _recorded_locators(farm, list(docs))
    seen_locators = set()

    for line_no, raw in enumerate(reader, start=2):
        if not any((c or "").strip() for c in raw):
            continue
        row = {h: (raw[i].strip() if i < len(raw) and raw[i] is not None else "") for i, h in enumerate(headers)}
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
                    plan.rows.append(
                        RowResult(
                            line=line_no,
                            action="skip",
                            reason=f"already recorded as {recorded[key]}; nothing to do",
                            summary=f"{row['date']} · {row['kind']} · {locator}",
                            payload={"source_locator": locator, "source_doc": row["source_doc"], "row": row},
                        )
                    )
                    continue

        if kind is not None:
            homeless = sorted(c for c in COLUMNS if row[c] and c not in _columns_with_a_home(kind))
            if homeless:
                problems.append(f"kind {kind.key!r} has no field for: {', '.join(homeless)}; put it in observation")
            if kind.product_required and not row["product"]:
                problems.append(f"kind {kind.key!r} needs a product")
            if kind.product == "commercial_name" and len(row["product"]) > 60:
                problems.append(
                    "product is longer than 60 characters; shorten it and keep the full name in observation"
                )
            if kind.lot_field and len(row["lot"]) > 60:
                problems.append("lot is longer than 60 characters")

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
            for parcel in chosen:
                season = _season_for(parcel, row["production"] if len(chosen) == 1 else "", problems)
                if season is not None:
                    targets.append(season)
            if day is not None:
                when = _as_event_datetime(day)
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
            plan.rows.append(
                RowResult(
                    line=line_no,
                    action="skip",
                    reason="; ".join(problems),
                    summary=f"{row['date'] or '(no date)'} · {row['kind'] or '(no kind)'} · {row['product'] or row['title'] or ''}".strip(
                        " ·"
                    ),
                    payload={"source_locator": locator, "source_doc": row["source_doc"], "row": row},
                )
            )
            continue

        # From here every value has a home and a unit.
        title = row["title"] or _default_title(kind, row)
        fields = {
            "type": subtype,
            "date": _as_event_datetime(day),
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

        classification, warning = "", False
        if kind.chemical:
            classification, warning = _classification_text(row["product"], row["active_ingredient"])

        group = str(uuid.uuid5(INTAKE_NAMESPACE, f"{row['source_doc']}|{locator}")) if len(targets) > 1 else None
        parcel_names = [t.parcel.name for t in targets]
        plan.rows.append(
            RowResult(
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
                    "classification": classification,
                    "warning": warning,
                    "source_doc": row["source_doc"],
                    "source_doc_title": doc.title,
                    "source_locator": locator,
                },
            )
        )
    return plan


def _default_title(kind: Kind, row) -> str:
    if kind.product and row["product"]:
        return f"{kind.label}: {row['product']}"
    if kind.key == "harvest" and row["variety"]:
        return f"Harvest: {row['variety']}"
    return kind.label


def execute(plan: ImportPlan, farm, created_by, batch: str) -> dict:
    """Write every importable row as records on `farm`, all or nothing.

    `created_by` is the operator who ran the import. Each record carries `extra_data["source"]`
    naming the filed document, the locator, and `batch` (the hash of the CSV the grower previewed).
    """
    if plan.error:
        raise ValueError(plan.error)
    created = []
    with transaction.atomic():
        for row in plan.importable:
            p = row.payload
            model_name, _subtype = p["target"].split(":")
            model, _event_type = EVENT_MODELS[model_name]
            group = uuid.UUID(p["application_group"]) if p["application_group"] else None
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
                        fields=dict(p["fields"]),
                        extra=extra,
                        created_by=created_by,
                        application_group=group,
                    )
                )
    return {"created": len(created), "skipped": len(plan.skipped), "records": created}
