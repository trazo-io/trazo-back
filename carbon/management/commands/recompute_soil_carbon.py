"""Recompute the stored carbon of soil-management events after the 2026-10-28 soil methodology.

A soil event's CarbonEntry is only recalculated when the event is saved again
(`history/signals.py`), and the signal stores an entry only when co2e > 0. Rows written before the
soil changes therefore still carry the old figures and labels:

  * a per-pass tillage soil-CO2 flux (61 kg for 1 acre of tillage; the term was removed);
  * "from recorded inputs" on figures built only from a per-hectare default (`area_estimate`);
  * 0.41 kg on a lab analysis, which counts no emission at all;
  * the operation default added on top of recorded fuel, and lime with no named carbonate.
  * 2026-11-11: a per-hectare soil-carbon CREDIT (cover crop -0.8, composting -1.0, organic
    matter -0.6, no-till -0.5 kg CO2e/ha) netted into figures that also carried recorded fuel or
    amendment nitrogen. The soil table no longer has one; a re-run recomputes those rows. The
    apply now keeps its restore text on the DataOperationLog row: `--restore log:<id>`.

For every soil event this command asks the calculator what a re-save would store now and compares
it with what is stored. Four outcomes are kept apart, and none of them is a stored zero:

  * figure_changed      the entry is replaced by the new figure and basis;
  * basis_only          same figure, different label or method;
  * now_not_estimated   the new calculation yields no figure (<= 0): the entry is REMOVED, the
                        convention of the soil signal. A 0 is never written, because a stored 0
                        reads as a measured zero;
  * estimate_created    no entry, but the calculation now yields a figure: one is stored;
  * unchanged           nothing to do (also what a record already at the new value reports).

What is written, and what is not:

  * Only CarbonEntry rows and the rows that hang off them (USDA compliance record, calculation
    audit rows). NEVER the SoilManagementEvent row: no save(), so no signal, no touched fields.
  * The recalculation is recorded as a SYSTEM recalculation. There is no recalculated_by on
    CarbonEntry, so the method version goes in the entry's `calculation_details` JSON and in the
    calculation audit's `processor_version`. The entry keeps the `created_by` it already had, the
    audit's `calculated_by` is NULL, and no amendment, correction or attestation is created.
  * Frozen and filed documents (OSP annual-update snapshots, DMS documents, signed hashes) are
    never read or written. Totals are derived live from CarbonEntry by `CarbonCalculatorService`;
    there is no stored per-season total to refresh. (`CarbonReport` snapshots were counted here
    until 2026-11-07; the model is retiring, and production held 0 rows.)

Production safety rule (see `common/services/data_operations.py`):

  1. Dry run by default. It writes a PLAN file: per record the old and new figure and basis, the
     classification, and a fingerprint of the event's calculation inputs and of its current
     entries. It also reports each season's producer and buyer total before and after, taken from
     `CarbonCalculatorService.calculate_production_carbon` (the same function the producer
     dashboard and the buyer page read) inside a transaction that is always rolled back.
  2. `--apply <plan>` recomputes both fingerprints per record. A record whose event or entry
     changed since the dry run is SKIPPED and reported; a difference that is not in the reviewed
     plan is never applied. Each record is its own transaction. The prior state of every record
     is written to a restore file BEFORE its change commits.
  3. A second apply of the same plan changes nothing: a record already at the planned value is
     reported unchanged, and a fresh dry run then lists no changes.
  4. `--restore <restore file>` puts every applied record back exactly, deleted entries and
     their dependent rows included.

    manage.py recompute_soil_carbon --report /tmp/soil-plan.json                       # dry run
    manage.py recompute_soil_carbon --apply /tmp/soil-plan.json --restore-file /tmp/soil-restore.json
    manage.py recompute_soil_carbon --report /tmp/soil-check.json                      # expect 0 changes
    manage.py recompute_soil_carbon --restore /tmp/soil-restore.json

Scope with --company / --establishment / --history (repeatable). Default: every soil event.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import CASCADE

OPERATION = "recompute_soil_carbon_2026_10_28"
METHOD_VERSION = "soil-2026-10-28"
PLAN_KIND = "soil-carbon-plan"
RESTORE_KIND = "soil-carbon-restore"
EPSILON = 1e-6

FIGURE_CHANGED = "figure_changed"
BASIS_ONLY = "basis_only"
NOW_NOT_ESTIMATED = "now_not_estimated"
ESTIMATE_CREATED = "estimate_created"
UNCHANGED = "unchanged"
CALCULATION_ERROR = "calculation_error"
ERROR = "error"
CHANGING = (FIGURE_CHANGED, BASIS_ONLY, NOW_NOT_ESTIMATED, ESTIMATE_CREATED)

# Everything the soil calculator reads from the record (and from `_detect_lime_type`,
# `_convert_area_to_hectares` and the metadata step), so the fingerprint moves when any input
# does. The model has no `updated_at`; it is added below when one exists.
INPUT_FIELDS = (
    "type",
    "date",
    "history_id",
    "description",
    "area_covered",
    "area_unit",
    "fuel_consumed",
    "fuel_unit",
    "fuel_type",
    "equipment_hours",
    "amendment_type",
    "amendment_amount",
    "amendment_amount_numeric",
    "amendment_amount_unit",
    "amendment_product_name",
    "amendment_nitrogen_percentage",
    "soil_ph",
    "organic_matter_percentage",
    "test_results",
    "sample_matrix",
    "working_depth",
    "depth_unit",
    "extra_data",
)


class Abort(Exception):
    """Raised inside a transaction to roll one record (or one simulated season) back."""


# --------------------------------------------------------------------------------------
# Reading the stored state
# --------------------------------------------------------------------------------------


def _entries_for(event):
    """The event's stored entries, found the way the soil signal finds them."""
    from carbon.event_link import entries_for_event

    # Read-only: a dry run must not write, not even a link.
    return entries_for_event(event, link=False).order_by("pk")


def _method_from_description(description: str) -> str:
    marker = " event: "
    return description.split(marker, 1)[1].strip() if marker in (description or "") else ""


def _entry_state(entry) -> Dict[str, Any]:
    """What the entry says about its figure. The id is deliberately absent: a recalculation
    replaces the row, and 'already at the new value' must not depend on the row's id."""
    breakdown = entry.baseline_data if isinstance(entry.baseline_data, dict) else {}
    return {
        "co2e": round(float(entry.co2e_amount or 0.0), 6),
        "type": entry.type,
        "verification_status": entry.verification_status,
        "usda_factors_based": bool(entry.usda_factors_based),
        "calculation_method": _method_from_description(entry.description),
        "calculation_basis": breakdown.get("calculation_basis", ""),
    }


def _states(entries: Iterable) -> List[Dict[str, Any]]:
    return [_entry_state(e) for e in entries]


def _stable(value) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _sha(value) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


def event_fingerprint(event, calculator) -> str:
    """Hash of everything the calculation reads, plus `updated_at` where the model has one."""
    inputs = {name: getattr(event, name, None) for name in INPUT_FIELDS}
    if hasattr(event, "updated_at"):
        inputs["updated_at"] = getattr(event, "updated_at")
    try:
        inputs["_state"] = calculator._get_establishment_location(event)[0]
    except Exception:  # noqa: BLE001 - a location we cannot read is part of the fingerprint
        inputs["_state"] = "unreadable"
    return _sha(inputs)


def entry_fingerprint(entries: Iterable) -> str:
    """Hash of every current entry of the event: id, figure, and the fields that carry its basis.

    `description` holds the calculation method and `baseline_data` the calculation basis, the two
    fields that separate `basis_only` from `unchanged`; an edit to either alone must still read as
    a change, or `--apply` and `--restore` would write over it.
    """
    rows = [
        {
            "id": e.pk,
            "co2e": round(float(e.co2e_amount or 0.0), 6),
            "amount": round(float(e.amount or 0.0), 6),
            "type": e.type,
            "verification_status": e.verification_status,
            "usda_factors_based": bool(e.usda_factors_based),
            "description": e.description or "",
            "baseline_data": e.baseline_data,
        }
        for e in entries
    ]
    return _sha(rows)


def result_fingerprint(result: Dict[str, Any]) -> str:
    breakdown = result.get("breakdown") or {}
    return _sha(
        {
            "co2e": round(float(result.get("co2e") or 0.0), 6),
            "verification_status": result.get("verification_status"),
            "usda_factors_based": bool(result.get("usda_factors_based")),
            "calculation_method": result.get("calculation_method"),
            "calculation_basis": breakdown.get("calculation_basis", ""),
        }
    )


def stores_entry(result: Dict[str, Any]) -> bool:
    """The soil signal's rule: an entry exists only for a figure above zero."""
    return result.get("verification_status") != "calculation_error" and (result.get("co2e") or 0) > 0


def _same_state(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if abs(x["co2e"] - y["co2e"]) > EPSILON:
            return False
        for key in ("type", "verification_status", "usda_factors_based", "calculation_method", "calculation_basis"):
            if x[key] != y[key]:
                return False
    return True


def _figure(states: List[Dict[str, Any]]) -> Optional[float]:
    return round(sum(s["co2e"] for s in states), 6) if states else None


# --------------------------------------------------------------------------------------
# Seasons: the totals, from the functions the product itself reads
# --------------------------------------------------------------------------------------


def season_totals(history_id: int) -> Dict[str, Any]:
    """Producer and buyer totals of one season, from `CarbonCalculatorService`.

    `total_emissions` is the producer figure: every emission row, the farmer's dashboard.
    `recorded_emissions` is the buyer figure: only rows whose basis is in
    `CarbonCalculatorService.RECORDED_BASIS_STATUSES`. The filter lives in the service; it is not
    repeated here.
    """
    from carbon.services.calculator_service import CarbonCalculatorService

    data = CarbonCalculatorService().calculate_production_carbon(history_id)
    return {
        "producer_total": round(float(data.get("total_emissions", 0.0)), 6),
        "buyer_total": round(float(data.get("recorded_emissions", 0.0)), 6),
        "producer_net": round(float(data.get("net_emissions", 0.0)), 6),
        "producer_gross_per_kg": round(float(data.get("gross_co2_kg_per_kg", 0.0)), 8),
        "buyer_per_kg": round(float(data.get("recorded_co2_kg_per_kg", 0.0)), 8),
        "entry_count": int(data.get("entry_count", 0)),
        "excluded_from_buyer_count": int(data.get("excluded_entry_count", 0)),
    }


# --------------------------------------------------------------------------------------
# Writing: one function, used by the dry run (inside a rollback) and by the apply
# --------------------------------------------------------------------------------------


def _cascade_rows(instances: List) -> List:
    """The instances and every row that would be deleted with them, parents first."""
    out: List = []
    seen = set()
    frontier = list(instances)
    while frontier:
        batch: List = []
        for obj in frontier:
            key = (obj._meta.label, obj.pk)
            if key in seen:
                continue
            seen.add(key)
            out.append(obj)
            batch.append(obj)
        frontier = []
        by_model: Dict[Any, List] = OrderedDict()
        for obj in batch:
            by_model.setdefault(obj._meta.model, []).append(obj)
        for model, objs in by_model.items():
            for rel in model._meta.related_objects:
                if not (rel.one_to_many or rel.one_to_one) or rel.on_delete is not CASCADE:
                    continue
                related = rel.related_model._base_manager.filter(**{f"{rel.field.name}__in": objs}).order_by("pk")
                frontier.extend(list(related))
    return out


def dump_entries(entries: Iterable) -> str:
    """Entries plus every dependent row, as fixture JSON (raw restore keeps auto_now values)."""
    return serializers.serialize("json", _cascade_rows(list(entries)))


def load_fixture(text: str) -> None:
    for obj in serializers.deserialize("json", text):
        obj.save()


def _stamp_system_recalculation(new_entry, prior_states, prior_ids, created_by_id) -> None:
    """Mark the rebuilt entry as a system recalculation. Nothing here names a person."""
    from carbon.models import CarbonEntry, USDACalculationAudit, USDAComplianceRecord

    marker = {
        "system_recalculation": {
            "method_version": METHOD_VERSION,
            "source": "system",
            "operation": OPERATION,
            "recalculated_at": datetime.now(timezone.utc).isoformat(),
            "replaces_entry_ids": prior_ids,
            "previous": prior_states,
        }
    }
    # `created_by` is carried from the row it replaces, as a re-save does not change authorship of
    # the figure's record; the rebuild itself is attributed to no one. QuerySet.update skips
    # CarbonEntry.save(), which re-validates the event for the establishment.
    CarbonEntry.objects.filter(pk=new_entry.pk).update(created_by_id=created_by_id, calculation_details=marker)
    # The calculator's own create path names the event's creator as the validator and the
    # calculator of the new rows. A recalculation is the system's, so both are cleared.
    USDACalculationAudit.objects.filter(carbon_entry_id=new_entry.pk).update(
        calculated_by=None, processor_version=f"2.0_enhanced/{METHOD_VERSION}"[:50]
    )
    USDAComplianceRecord.objects.filter(carbon_entry_id=new_entry.pk).update(validated_by=None)


def write_event_carbon(event, result: Dict[str, Any], calculator) -> List:
    """Replace the event's stored entries with what a re-save would store.

    Deletes the entries (the compliance and audit rows go with them), then, only when the figure
    is above zero, rebuilds one through the calculator's own `create_carbon_entry_from_event`, so
    the stored row is what the signal would have written. Returns the entries created.
    """
    from carbon.models import CarbonEntry

    old = list(_entries_for(event))
    prior_states = _states(old)
    prior_ids = [e.pk for e in old]
    created_by_id = next((e.created_by_id for e in old if e.created_by_id), None)
    if old:
        CarbonEntry.objects.filter(pk__in=prior_ids).delete()
    if not stores_entry(result):
        return []
    entry = calculator.create_carbon_entry_from_event(event, result)
    if entry is None:
        raise Abort("the calculator did not create the entry")
    _stamp_system_recalculation(entry, prior_states, prior_ids, created_by_id)
    entry.refresh_from_db()
    return [entry]


# --------------------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------------------


def _scope_queryset(options):
    from history.models import SoilManagementEvent

    qs = SoilManagementEvent.objects.select_related(
        "history", "history__parcel", "history__parcel__establishment", "history__parcel__establishment__company"
    ).exclude(history__isnull=True)
    if options.get("company"):
        qs = qs.filter(history__parcel__establishment__company_id__in=options["company"])
    if options.get("establishment"):
        qs = qs.filter(history__parcel__establishment_id__in=options["establishment"])
    if options.get("history"):
        qs = qs.filter(history_id__in=options["history"])
    return qs.order_by("history_id", "pk")


def _where(event) -> Dict[str, Any]:
    history = event.history
    parcel = getattr(history, "parcel", None)
    est = getattr(parcel, "establishment", None)
    company = getattr(est, "company", None)
    return {
        "company_id": getattr(company, "pk", None),
        "company": getattr(company, "name", None),
        "establishment_id": getattr(est, "pk", None),
        "farm": getattr(est, "name", None),
        "season_id": history.pk,
        "season": history.name,
    }


def _basis(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if state is None:
        return None
    return {
        "verification_status": state["verification_status"],
        "usda_factors_based": state["usda_factors_based"],
        "calculation_method": state["calculation_method"],
        "calculation_basis": state["calculation_basis"],
    }


def _describe(states: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The report's view of a stored figure: co2e (None when there is no entry) and its basis."""
    if not states:
        return {"stored": False, "co2e": None, "basis": None}
    return {"stored": True, "co2e": _figure(states), "basis": _basis(states[0]), "entries": len(states)}


def classify(old_states, new_states, stored_after: bool, result) -> str:
    if result.get("verification_status") == "calculation_error":
        return CALCULATION_ERROR
    if not old_states and not stored_after:
        return UNCHANGED
    if not old_states and stored_after:
        return ESTIMATE_CREATED
    if old_states and not stored_after:
        return NOW_NOT_ESTIMATED
    if _same_state(old_states, new_states):
        return UNCHANGED
    if abs((_figure(old_states) or 0.0) - (_figure(new_states) or 0.0)) > EPSILON:
        return FIGURE_CHANGED
    return BASIS_ONLY


def _reason(kind: str, old_states, new_states, result) -> str:
    if kind == NOW_NOT_ESTIMATED:
        method = result.get("calculation_method", "")
        return (
            f"the recalculation yields no figure above zero ({method}); the stored entry is removed, "
            "as the soil signal stores none for a zero"
        )
    if kind == ESTIMATE_CREATED:
        return "no entry is stored and the recalculation now yields a figure"
    if kind == FIGURE_CHANGED:
        return f"{_figure(old_states)} -> {_figure(new_states)} kg CO2e"
    if kind == BASIS_ONLY:
        return "same figure; the stored basis or method label differs from the current rule"
    if kind == CALCULATION_ERROR:
        return f"the calculator reported an error ({result.get('error', '')}); the entry is left as it is"
    return ""


def build_plan(options) -> Dict[str, Any]:
    from carbon.models import CarbonEntry
    from carbon.services.event_carbon_calculator import EventCarbonCalculator

    calculator = EventCarbonCalculator()
    records: List[Dict[str, Any]] = []
    by_history: "OrderedDict[int, List[Dict[str, Any]]]" = OrderedDict()

    events = list(_scope_queryset(options))
    pending: List[tuple] = []  # (record, event, result) needing a simulated write
    for event in events:
        record: Dict[str, Any] = {
            "event_id": event.pk,
            "subtype": event.type,
            "subtype_label": event.get_type_display(),
            **_where(event),
        }
        try:
            result = calculator.calculate_soil_management_event_impact(event)
            old_entries = list(_entries_for(event))
            old_states = _states(old_entries)
            record["event_fingerprint"] = event_fingerprint(event, calculator)
            record["entry_fingerprint"] = entry_fingerprint(old_entries)
            record["entry_ids"] = [e.pk for e in old_entries]
            record["result_fingerprint"] = result_fingerprint(result)
            record["old"] = _describe(old_states)
            record["legacy_extra_data_figure"] = bool(
                isinstance(event.extra_data, dict) and event.extra_data.get("carbon_calculation")
            )
            if result.get("verification_status") == "calculation_error":
                record.update(classification=CALCULATION_ERROR, new=record["old"])
                record["reason"] = _reason(CALCULATION_ERROR, old_states, [], result)
            elif not stores_entry(result) and not old_states:
                record.update(classification=UNCHANGED, new=_describe([]), reason="")
            elif stores_entry(result) and len(old_states) == 1 and _quick_same(old_states[0], result):
                record.update(classification=UNCHANGED, new=record["old"], reason="")
            else:
                pending.append((record, event, result))
        except Exception as exc:  # noqa: BLE001 - one bad record never hides the others
            record.update(classification=ERROR, reason=f"{type(exc).__name__}: {exc}", new=None)
            record.setdefault("old", None)
        records.append(record)
        by_history.setdefault(event.history_id, []).append(record)

    # Simulate, season by season, inside a transaction that is always rolled back: the stored
    # state after the change is what the calculator's own create path would write, and the season
    # totals come from the real service rather than from a copy of its filters.
    totals: Dict[int, Dict[str, Any]] = {}
    pending_by_history: Dict[int, List[tuple]] = OrderedDict()
    for item in pending:
        pending_by_history.setdefault(item[1].history_id, []).append(item)
    for history_id, items in pending_by_history.items():
        before = season_totals(history_id)
        try:
            with transaction.atomic():
                for record, event, result in items:
                    old_states = _states(_entries_for(event))
                    try:
                        with transaction.atomic():
                            created = write_event_carbon(event, result, calculator)
                            new_states = _states(created)
                            kind = classify(old_states, new_states, bool(created), result)
                            record["new"] = _describe(new_states)
                            record["classification"] = kind
                            record["reason"] = _reason(kind, old_states, new_states, result)
                            record["new_state"] = new_states
                            record["old_state"] = old_states
                    except Exception as exc:  # noqa: BLE001
                        record.update(classification=ERROR, reason=f"{type(exc).__name__}: {exc}", new=None)
                after = season_totals(history_id)
                raise Abort("dry run: roll back")
        except Abort:
            pass
        totals[history_id] = {"before": before, "after": after}

    # A season in scope with changes only because a record is unchanged after simulation still has
    # equal totals; list seasons that carry at least one changing record.
    seasons: List[Dict[str, Any]] = []
    for history_id, recs in by_history.items():
        if not any(r["classification"] in CHANGING for r in recs):
            continue
        t = totals.get(history_id)
        seasons.append(
            {
                "season_id": history_id,
                "season": recs[0]["season"],
                "farm": recs[0]["farm"],
                "company": recs[0]["company"],
                "before": t["before"] if t else None,
                "after": t["after"] if t else None,
            }
        )

    for record in records:
        record.setdefault("new", None)

    counts: Dict[str, int] = {}
    for record in records:
        counts[record["classification"]] = counts.get(record["classification"], 0) + 1

    history_ids = list(by_history.keys())
    unattributed = (
        CarbonEntry.objects.filter(
            production_id__in=history_ids, activity__isnull=True, description__icontains="SoilManagementEvent"
        )
        .exclude(description__contains="(ID=")
        .exclude(registry_verification_id__startswith="REG-SoilManagementEvent-")
        .count()
    )
    return {
        "kind": PLAN_KIND,
        "operation": OPERATION,
        "method_version": METHOD_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": {k: v for k, v in options.items() if k in ("company", "establishment", "history") and v},
        "counts": counts,
        "records": records,
        "seasons": seasons,
        "notes": {
            "unattributed_legacy_soil_entries_not_touched": unattributed,
            "events_with_legacy_extra_data_carbon_figure_not_rewritten": sum(
                1 for r in records if r.get("legacy_extra_data_figure") and r["classification"] == NOW_NOT_ESTIMATED
            ),
        },
    }


def _quick_same(state: Dict[str, Any], result: Dict[str, Any]) -> bool:
    """True when the stored entry is exactly what the result says it should be, so no simulated
    write is needed. When the flag differs (the create path may upgrade it) the full simulation
    decides."""
    breakdown = result.get("breakdown") or {}
    return (
        abs(state["co2e"] - round(float(result.get("co2e") or 0.0), 6)) <= EPSILON
        and state["verification_status"] == result.get("verification_status")
        and state["usda_factors_based"] == bool(result.get("usda_factors_based"))
        and state["calculation_method"] == result.get("calculation_method")
        and state["calculation_basis"] == breakdown.get("calculation_basis", "")
    )


# --------------------------------------------------------------------------------------
# Report text
# --------------------------------------------------------------------------------------

LABELS = {
    FIGURE_CHANGED: "changed figure",
    BASIS_ONLY: "same figure, basis relabelled",
    NOW_NOT_ESTIMATED: "now not estimated (entry removed)",
    ESTIMATE_CREATED: "estimate created (no entry before)",
    UNCHANGED: "unchanged",
    CALCULATION_ERROR: "skipped, calculator error (entry left as is)",
    ERROR: "skipped, error while checking",
}


def _fmt_side(side: Optional[Dict[str, Any]]) -> str:
    if not side:
        return "n/a"
    if not side["stored"]:
        return "no entry (not estimated)"
    b = side["basis"]
    return (
        f"{side['co2e']:.3f} kg CO2e | status={b['verification_status']} | "
        f"usda_factors_based={b['usda_factors_based']} | method={b['calculation_method'] or '-'} | "
        f"basis={b['calculation_basis'] or '-'}"
    )


def render_plan(plan: Dict[str, Any], show_unchanged: bool = False) -> str:
    lines: List[str] = []
    counts = plan["counts"]
    lines.append(f"Soil carbon recompute, method {plan['method_version']}")
    scope = plan["scope"] or "all soil events"
    lines.append(f"Scope: {scope}")
    lines.append(f"Soil events checked: {len(plan['records'])}")
    for key in (
        FIGURE_CHANGED,
        BASIS_ONLY,
        NOW_NOT_ESTIMATED,
        ESTIMATE_CREATED,
        UNCHANGED,
        CALCULATION_ERROR,
        ERROR,
    ):
        if counts.get(key):
            lines.append(f"  {LABELS[key]:<42} {counts[key]}")
    lines.append("")
    lines.append("RECORDS (unchanged ones are only counted; --show-unchanged lists them)")
    for r in plan["records"]:
        if r["classification"] == UNCHANGED and not show_unchanged:
            continue
        lines.append(
            f"event {r['event_id']} | {r['subtype']} {r['subtype_label']} | "
            f"company {r['company']} (#{r['company_id']}) / farm {r['farm']} (#{r['establishment_id']}) | "
            f"season #{r['season_id']} {r['season']}"
        )
        lines.append(f"  old: {_fmt_side(r['old'])}")
        lines.append(f"  new: {_fmt_side(r['new'])}")
        lines.append(f"  change: {r['classification']}" + (f" ({r['reason']})" if r["reason"] else ""))
    lines.append("")
    lines.append("SEASON TOTALS, kg CO2e (producer = every emission row; buyer = recorded-basis rows only)")
    if not plan["seasons"]:
        lines.append("  no season changes")
    for s in plan["seasons"]:
        lines.append(f"season #{s['season_id']} {s['season']} | farm {s['farm']} | company {s['company']}")
        b, a = s["before"], s["after"]
        if not b or not a:
            lines.append("  totals not available")
            continue
        lines.append(f"  {'':8}{'producer total':>16}{'buyer total':>14}{'buyer kg/kg':>14}")
        lines.append(f"  {'before':8}{b['producer_total']:>16.3f}{b['buyer_total']:>14.3f}{b['buyer_per_kg']:>14.6f}")
        lines.append(f"  {'after':8}{a['producer_total']:>16.3f}{a['buyer_total']:>14.3f}{a['buyer_per_kg']:>14.6f}")
        lines.append(
            f"  {'change':8}{a['producer_total'] - b['producer_total']:>16.3f}"
            f"{a['buyer_total'] - b['buyer_total']:>14.3f}"
            f"{a['buyer_per_kg'] - b['buyer_per_kg']:>14.6f}"
        )
    lines.append("")
    n = plan["notes"]
    lines.append(
        "Not touched: soil event rows; filed or frozen documents; "
        f"{n['unattributed_legacy_soil_entries_not_touched']} legacy soil entries with no event id; "
        f"{n['events_with_legacy_extra_data_carbon_figure_not_rewritten']} removed-entry events whose own "
        "extra_data still holds an old figure."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------------------


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> str:
    text = json.dumps(payload, indent=1, sort_keys=True, default=str)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return text


def _matches_planned(current_states, record) -> bool:
    planned = record["new_state"]
    return _same_state(current_states, planned)


def apply_plan(plan: Dict[str, Any], restore_path: Path, run_by: str) -> Dict[str, Any]:
    from carbon.services.event_carbon_calculator import EventCarbonCalculator
    from history.models import SoilManagementEvent

    calculator = EventCarbonCalculator()
    outcome: Dict[str, List[Dict[str, Any]]] = {
        "applied": [],
        "already_at_planned_value": [],
        "changed_since_dry_run": [],
        "error": [],
    }
    restore = {
        "kind": RESTORE_KIND,
        "operation": OPERATION,
        "method_version": METHOD_VERSION,
        "plan_sha256": plan["_sha256"],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "records": [],
    }

    restore_started = False
    for record in plan["records"]:
        if record["classification"] not in CHANGING:
            continue
        info = {"event_id": record["event_id"], "season_id": record["season_id"]}
        try:
            with transaction.atomic():
                event = (
                    SoilManagementEvent.objects.select_related("history", "history__parcel__establishment__company")
                    .filter(pk=record["event_id"])
                    .first()
                )
                if event is None or event.history_id is None:
                    outcome["changed_since_dry_run"].append({**info, "why": "the event no longer exists"})
                    continue
                current = list(_entries_for(event))
                current_states = _states(current)
                if _matches_planned(current_states, record):
                    outcome["already_at_planned_value"].append(info)
                    continue
                if event_fingerprint(event, calculator) != record["event_fingerprint"]:
                    outcome["changed_since_dry_run"].append({**info, "why": "the event's inputs changed"})
                    continue
                if entry_fingerprint(current) != record["entry_fingerprint"]:
                    outcome["changed_since_dry_run"].append({**info, "why": "the stored entry changed"})
                    continue
                result = calculator.calculate_soil_management_event_impact(event)
                if result_fingerprint(result) != record["result_fingerprint"]:
                    outcome["changed_since_dry_run"].append({**info, "why": "the calculation now gives another result"})
                    continue
                prior_fixture = dump_entries(current)
                created = write_event_carbon(event, result, calculator)
                if not _same_state(_states(created), record["new_state"]):
                    raise Abort("the rebuilt entry differs from the reviewed plan")
                restore["records"].append(
                    {
                        "event_id": event.pk,
                        "season_id": event.history_id,
                        "prior_entries": prior_fixture,
                        "after_entry_fingerprint": entry_fingerprint(created),
                    }
                )
                # Written inside the transaction, before it commits: a crash after this line and
                # before the commit leaves a restore record for an unchanged event, which restores
                # to the same state; a crash cannot leave a change with no record of its prior state.
                if not restore_started and restore_path.exists():
                    raise CommandError(
                        f"{restore_path} already exists. It may be the restore file of an earlier apply; "
                        "give --restore-file a new path."
                    )
                _write_json_atomic(restore_path, restore)
                restore_started = True
                outcome["applied"].append({**info, "classification": record["classification"]})
        except Abort as exc:
            restore["records"] = [r for r in restore["records"] if r["event_id"] != record["event_id"]]
            outcome["changed_since_dry_run"].append({**info, "why": str(exc)})
        except CommandError:
            raise
        except Exception as exc:  # noqa: BLE001
            restore["records"] = [r for r in restore["records"] if r["event_id"] != record["event_id"]]
            outcome["error"].append({**info, "why": f"{type(exc).__name__}: {exc}"})

    touched = sorted({o["season_id"] for o in outcome["applied"]})
    outcome["season_totals_after"] = {sid: season_totals(sid) for sid in touched}
    outcome["restore_sha256"] = None
    if restore["records"]:
        outcome["restore_sha256"] = hashlib.sha256(restore_path.read_text().encode("utf-8")).hexdigest()
    return outcome


# --------------------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------------------


def restore_records(restore: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    from carbon.models import CarbonEntry
    from history.models import SoilManagementEvent

    out: Dict[str, List[Dict[str, Any]]] = {"restored": [], "not_restored": []}
    for rec in restore["records"]:
        info = {"event_id": rec["event_id"], "season_id": rec["season_id"]}
        with transaction.atomic():
            event = SoilManagementEvent.objects.select_related("history").filter(pk=rec["event_id"]).first()
            if event is None or event.history_id is None:
                out["not_restored"].append({**info, "why": "the event no longer exists"})
                continue
            current = list(_entries_for(event))
            if entry_fingerprint(current) != rec["after_entry_fingerprint"]:
                out["not_restored"].append(
                    {**info, "why": "the stored entry changed since the apply; restoring would overwrite it"}
                )
                continue
            if current:
                CarbonEntry.objects.filter(pk__in=[e.pk for e in current]).delete()
            load_fixture(rec["prior_entries"])
            out["restored"].append(info)
    return out


# --------------------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------------------


#: `--restore log:<id>` reads the restore text stored on that apply's DataOperationLog row.
LOG_PREFIX = "log:"


class Command(BaseCommand):
    help = (
        "Recompute stored soil-event carbon under the 2026-10-28 methodology. Dry run by default: "
        "writes a plan. --apply <plan> applies it; --restore <restore file> reverts an apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--report", default="", help="Dry run: where to write the plan (JSON).")
        parser.add_argument("--apply", default="", metavar="PLAN", help="Apply a reviewed plan file.")
        parser.add_argument("--restore-file", default="", help="With --apply: where to write the restore file.")
        parser.add_argument(
            "--restore", default="", metavar="RESTORE_FILE", help="Revert an apply: a restore file, or log:<id>."
        )
        parser.add_argument("--company", type=int, action="append", help="Company id (repeatable).")
        parser.add_argument("--establishment", type=int, action="append", help="Establishment id (repeatable).")
        parser.add_argument("--history", type=int, action="append", help="Season (History) id (repeatable).")
        parser.add_argument("--show-unchanged", action="store_true", help="List unchanged records too.")
        parser.add_argument("--run-by", default="", help="Who ran it, recorded in the operation log.")

    def handle(self, *args, **options):
        if sum([bool(options["report"]), bool(options["apply"]), bool(options["restore"])]) != 1:
            raise CommandError("Give exactly one of --report (dry run), --apply <plan> or --restore <file>.")
        if options["restore"]:
            return self._restore(options)
        if options["apply"]:
            return self._apply(options)
        return self._dry_run(options)

    # -- dry run ---------------------------------------------------------------------
    def _dry_run(self, options):
        path = Path(options["report"])
        if path.exists():
            existing = _read_json(path)
            if existing.get("kind") == RESTORE_KIND:
                raise CommandError(f"{path} is a restore file. Write the plan to a new path.")
        plan = build_plan(options)
        text = json.dumps(plan, indent=1, sort_keys=True, default=str)
        path.write_text(text)
        self.stdout.write(render_plan(plan, show_unchanged=options["show_unchanged"]))
        self.stdout.write("")
        self.stdout.write(f"Dry run, nothing saved. Plan: {path} (sha256 {hashlib.sha256(text.encode()).hexdigest()})")

    # -- apply -----------------------------------------------------------------------
    def _apply(self, options):
        from common.models import DataOperationLog

        if not options["restore_file"]:
            raise CommandError("--apply needs --restore-file <path>: it is the rollback of this apply.")
        plan_path = Path(options["apply"])
        text = plan_path.read_text()
        plan = json.loads(text)
        if plan.get("kind") != PLAN_KIND or plan.get("operation") != OPERATION:
            raise CommandError(f"{plan_path} is not a plan written by this command's dry run.")
        plan["_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        restore_path = Path(options["restore_file"])

        outcome = apply_plan(plan, restore_path, options["run_by"])
        applied = outcome["applied"]
        if applied:
            counts: Dict[str, int] = {"records": len(applied)}
            for a in applied:
                counts[a["classification"]] = counts.get(a["classification"], 0) + 1
            # The restore text goes on the log row too, byte for byte the text `report_sha256`
            # hashes. Until 2026-11-11 it lived only in --restore-file, and in production that is
            # a path on an App Platform container whose disk is gone after the next deploy: the
            # only copy of the removed entries did not outlive the console session.
            log = DataOperationLog.objects.create(
                operation=OPERATION,
                action=DataOperationLog.ACTION_APPLY,
                report_sha256=outcome["restore_sha256"] or plan["_sha256"],
                counts=counts,
                run_by=options["run_by"],
                report=restore_path.read_text() if outcome["restore_sha256"] else "",
            )
        self.stdout.write(f"Applied plan {plan_path} (sha256 {plan['_sha256']}).")
        self.stdout.write(f"  applied                      {len(applied)}")
        self.stdout.write(f"  already at the planned value {len(outcome['already_at_planned_value'])} (unchanged)")
        self.stdout.write(f"  skipped, changed since dry run {len(outcome['changed_since_dry_run'])}")
        self.stdout.write(f"  skipped, error               {len(outcome['error'])}")
        for item in outcome["changed_since_dry_run"]:
            self.stdout.write(f"    event {item['event_id']} (season #{item['season_id']}): {item['why']}")
        for item in outcome["error"]:
            self.stdout.write(f"    event {item['event_id']} (season #{item['season_id']}): {item['why']}")
        planned = {s["season_id"]: s for s in plan["seasons"]}
        if outcome["season_totals_after"]:
            self.stdout.write("SEASON TOTALS after the apply, kg CO2e (planned in brackets)")
            for sid, after in outcome["season_totals_after"].items():
                before = (planned.get(sid) or {}).get("before") or {}
                plan_after = (planned.get(sid) or {}).get("after") or {}
                self.stdout.write(
                    f"  season #{sid}: producer {before.get('producer_total', 0):.3f} -> {after['producer_total']:.3f} "
                    f"[{plan_after.get('producer_total', 0):.3f}] | buyer {before.get('buyer_total', 0):.3f} -> "
                    f"{after['buyer_total']:.3f} [{plan_after.get('buyer_total', 0):.3f}]"
                )
        if applied:
            self.stdout.write(
                f"Restore file: {restore_path}. Also kept on DataOperationLog #{log.pk}: "
                f"`--restore {LOG_PREFIX}{log.pk}` works after this container is gone."
            )

    # -- restore ---------------------------------------------------------------------
    def _restore(self, options):
        from common.models import DataOperationLog

        path = options["restore"]
        if path.startswith(LOG_PREFIX):
            log = DataOperationLog.objects.filter(
                pk=path[len(LOG_PREFIX) :] if path[len(LOG_PREFIX) :].isdigit() else None,
                operation=OPERATION,
                action=DataOperationLog.ACTION_APPLY,
            ).first()
            if log is None or not log.report:
                raise CommandError(f"{path}: no apply of {OPERATION} with a stored restore. Nothing was restored.")
            text = log.report
        else:
            text = Path(path).read_text()
        restore = json.loads(text)
        if restore.get("kind") != RESTORE_KIND or restore.get("operation") != OPERATION:
            raise CommandError(f"{path} is not a restore file written by this command's apply.")
        out = restore_records(restore)
        if out["restored"]:
            DataOperationLog.objects.create(
                operation=OPERATION,
                action=DataOperationLog.ACTION_RESTORE,
                report_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                counts={"records": len(out["restored"])},
                run_by=options["run_by"],
            )
        self.stdout.write(f"Restored {len(out['restored'])} record(s) from {path}.")
        for item in out["not_restored"]:
            self.stdout.write(f"  event {item['event_id']} NOT restored: {item['why']}")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {}
