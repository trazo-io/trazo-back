"""Schema census: a read-only fingerprint of every stored row, and the domain facts a remodel must keep.

Phase 1 of the schema remodel plan (Production / Activity). A census taken before a migration and
one taken after must agree on everything the migration did not declare it would change. That is
the proof that nothing was lost, so this module is deliberately boring:

- It only reads. `take_census` runs in one transaction opened as
  `REPEATABLE READ READ ONLY`, so Postgres itself refuses any write a helper might attempt, and
  every number comes from the same snapshot.
- Every concrete table is covered, including auto-created M2M tables, content types and the
  audit trail. Each row gets a SHA-256 of its canonical values, keyed by its primary key. The plan
  keeps every primary key (the Activity identity table is additive), so the pk is a stable key.
- Values are canonicalised so the digest does not move with the driver: datetimes in UTC ISO
  with microseconds, Decimal via str, float via repr, JSON with sorted keys, bytes as hex, NULL
  kept distinct from "".
- Per table it also keeps one digest per column, so a diff can say WHICH column moved.

The domain section records what a row digest cannot show: id collisions across the event tables,
`index` ties inside a season (the seal's sort is not total), whether each sealed season's two hash
layers verify today and the order of its v1 preimage, loose `(event_type, event_id)` pairs and
their orphans, and the rows that carry an event class name as text.

`compare` reads two censuses and returns what was lost, changed, added or stopped verifying.
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import hashlib
import json
import re
import uuid
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from django.apps import apps
from django.db import connection, transaction

CENSUS_VERSION = 1
CELL_HASH_CHARS = 8

#: Tables whose rows churn on every request: counted, never digested. A session or a refresh token
#: changing between two censuses is not data loss.
VOLATILE_APP_LABELS = {"sessions", "token_blacklist"}

#: Loose `(type, id)` pairs that point at an event row by code with no foreign key behind them.
#: model label -> (type column, id column). ProductionPlanItem.event_type is ROUTING, not a target.
LOOSE_EVENT_PAIRS = {
    "history.EventAmendment": ("event_type", "event_id"),
    "history.ProductionPlanItem": ("fulfilled_by_event_type", "fulfilled_by_id"),
    "documents.GeneratedDocument": ("event_type", "event_id"),
    "fieldnotes.FieldNote": ("fulfilled_by_event_type", "fulfilled_by_id"),
    "fieldnotes.FieldNoteConfirmation": ("event_type", "event_id"),
}

#: MaterialIdentityDecision.source -> the event model its JSON `event_id`s point into.
MATERIAL_IDENTITY_SOURCES = {
    "chemical": "history.ChemicalEvent",
    "amendment": "history.SoilManagementEvent",
    "sanitizer": "history.ProductionEvent",
}

CARBON_TEXT_LINK = re.compile(r"\b([A-Z][A-Za-z]+Event)\(ID=(\d+)\)")


# --------------------------------------------------------------------------------------------
# Canonical values
# --------------------------------------------------------------------------------------------


def canonical(value: Any) -> Any:
    """A JSON-safe value whose serialisation is identical for identical stored data."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return {"float": repr(value)}
    if isinstance(value, decimal.Decimal):
        return {"decimal": str(value)}
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(dt.timezone.utc)
        return {"datetime": value.isoformat(timespec="microseconds")}
    if isinstance(value, dt.date):
        return {"date": value.isoformat()}
    if isinstance(value, dt.time):
        return {"time": value.isoformat(timespec="microseconds")}
    if isinstance(value, dt.timedelta):
        return {"timedelta": value.total_seconds()}
    if isinstance(value, uuid.UUID):
        return {"uuid": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"bytes": base64.b16encode(bytes(value)).decode()}
    if isinstance(value, dict):
        return {"json": json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)}
    if isinstance(value, (list, tuple)):
        return {"json": json.dumps(list(value), sort_keys=True, separators=(",", ":"), default=str)}
    return {"repr": repr(value)}


def _sha(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------------------------


def _census_models() -> List[Any]:
    out = []
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if meta.proxy or not meta.managed or meta.abstract:
            continue
        out.append(model)
    return sorted(out, key=lambda m: m._meta.label)


def _table_census(model) -> Dict[str, Any]:
    meta = model._meta
    qn = connection.ops.quote_name
    columns = [f.column for f in meta.concrete_fields]
    pk_column = meta.pk.column
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {qn(meta.db_table)}")
        count = cursor.fetchone()[0]
    entry: Dict[str, Any] = {"table": meta.db_table, "columns": columns, "pk": pk_column, "count": count}
    if meta.app_label in VOLATILE_APP_LABELS:
        entry["volatile"] = True
        return entry

    # Each row is stored as "<row digest>:<cell hashes>", the cell hashes being the first
    # CELL_HASH_CHARS hex characters of each column's value hash, in `columns` order. The row
    # digest says WHETHER a row moved; the cell hashes say WHICH columns did, compared by column
    # name, so a column a migration ADDS does not make every row look changed.
    rows: Dict[str, str] = {}
    select = ", ".join(qn(c) for c in columns)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {select} FROM {qn(meta.db_table)} ORDER BY {qn(pk_column)}")
        pk_index = columns.index(pk_column)
        for record in cursor:
            values = [canonical(v) for v in record]
            cells = "".join(_sha(v)[:CELL_HASH_CHARS] for v in values)
            rows[str(record[pk_index])] = f"{_sha(dict(zip(columns, values)))}:{cells}"
    entry["rows"] = rows
    entry["digest"] = _sha(rows)
    return entry


def _sequences() -> Dict[str, Dict[str, Any]]:
    """Every serial/identity sequence against the max of the column it feeds."""
    out = {}
    qn = connection.ops.quote_name
    for model in _census_models():
        meta = model._meta
        pk = meta.pk
        if pk.get_internal_type() not in ("AutoField", "BigAutoField", "SmallAutoField"):
            continue
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", [meta.db_table, pk.column])
            seq = cursor.fetchone()[0]
            if not seq:
                continue
            cursor.execute(f"SELECT last_value, is_called FROM {seq}")
            last_value, is_called = cursor.fetchone()
            cursor.execute(f"SELECT MAX({qn(pk.column)}) FROM {qn(meta.db_table)}")
            max_pk = cursor.fetchone()[0]
        # The next value is last_value + 1 once called, last_value itself before the first call.
        next_value = last_value + 1 if is_called else last_value
        out[meta.label] = {
            "sequence": seq,
            "next_value": next_value,
            "max_pk": max_pk,
            "ok": max_pk is None or next_value > max_pk,
        }
    return out


# --------------------------------------------------------------------------------------------
# Domain facts
# --------------------------------------------------------------------------------------------


def _event_models():
    from history.constants import EVENT_TYPE_TO_MODEL

    return dict(sorted(EVENT_TYPE_TO_MODEL.items()))


def _event_facts() -> Dict[str, Any]:
    models = _event_models()
    ids_by_table = {code: set(m.objects.values_list("pk", flat=True)) for code, m in models.items()}
    owner = defaultdict(list)
    for code, ids in ids_by_table.items():
        for pk in ids:
            owner[pk].append(code)
    collisions = sorted(pk for pk, codes in owner.items() if len(codes) > 1)

    per_season_index = defaultdict(Counter)
    for model in models.values():
        for history_id, index in model.objects.exclude(history__isnull=True).values_list("history_id", "index"):
            per_season_index[history_id][index] += 1
    ties = sorted(h for h, counts in per_season_index.items() if any(n > 1 for n in counts.values()))

    general = models[3]
    activity_types = Counter(general.objects.values_list("activity_type", flat=True))

    equipment = models[4]
    return {
        "counts": {m._meta.label: len(ids_by_table[code]) for code, m in models.items()},
        "id_collisions": {"count": len(collisions), "sample": collisions[:50]},
        "seasons_with_index_ties": {"count": len(ties), "ids": ties},
        "general_activity_types": {str(k): v for k, v in sorted(activity_types.items(), key=lambda kv: str(kv[0]))},
        "equipment_events": {
            "count": len(ids_by_table[4]),
            "on_sealed_seasons": equipment.objects.filter(history__extra_data__has_key="finalization_hash").count(),
        },
    }


def _v1_preimage_order(history) -> List[List[Any]]:
    """The order `History.compute_finalization_hash` puts events in, reproduced read-only.

    Same queries, same model order, same stable sort on `index`. Ties keep the database's return
    order, which is exactly why `seasons_with_index_ties` is recorded next to it.
    """
    rows = []
    from history.models import (
        BusinessEvent,
        ChemicalEvent,
        EquipmentEvent,
        GeneralEvent,
        PestManagementEvent,
        ProductionEvent,
        SoilManagementEvent,
        WeatherEvent,
    )

    for model in (
        WeatherEvent,
        ChemicalEvent,
        ProductionEvent,
        GeneralEvent,
        EquipmentEvent,
        SoilManagementEvent,
        PestManagementEvent,
        BusinessEvent,
    ):
        for row in model.objects.filter(history=history).values("id", "index"):
            rows.append([model.__name__, row["id"], row["index"]])
    rows.sort(key=lambda r: r[2])
    return [[name, pk] for name, pk, _ in rows]


def _seal_facts() -> Dict[str, Any]:
    from carbon.tasks import build_blockchain_raw_data
    from history.models import History

    seasons = {}
    sealed = History.objects.filter(extra_data__has_key="finalization_hash").select_related("parcel__establishment")
    for history in sealed.order_by("pk"):
        extra = history.extra_data if isinstance(history.extra_data, dict) else {}
        stored = extra.get("finalization_hash")
        try:
            current, event_count = history.compute_finalization_hash()
            layer1 = "intact" if current == stored else "mismatch"
        except Exception as exc:  # recorded, never raised: a census must finish
            current, event_count, layer1 = None, None, f"error: {exc.__class__.__name__}"

        stored_data_hash = extra.get("blockchain_data_hash")
        if stored_data_hash:
            try:
                company_id = history.parcel.establishment.company_id if history.parcel else None
                _raw, data_hash, *_ = build_blockchain_raw_data(history, company_id)
                layer2 = "intact" if data_hash == stored_data_hash else "mismatch"
            except Exception as exc:
                layer2 = f"error: {exc.__class__.__name__}"
        else:
            layer2 = "not_submitted"

        seasons[str(history.pk)] = {
            "public_id": str(history.public_id),
            "layer1": layer1,
            "layer2": layer2,
            "stored_event_count": extra.get("finalization_event_count"),
            "current_event_count": event_count,
            "v1_preimage_order": _v1_preimage_order(history),
        }
    return {
        "count": len(seasons),
        "layer1": dict(Counter(s["layer1"] for s in seasons.values())),
        "layer2": dict(Counter(s["layer2"] for s in seasons.values())),
        "seasons": seasons,
    }


def _loose_pair_facts() -> Dict[str, Any]:
    models = _event_models()
    existing = {code: set(m.objects.values_list("pk", flat=True)) for code, m in models.items()}
    out = {}
    for label, (type_col, id_col) in LOOSE_EVENT_PAIRS.items():
        model = apps.get_model(label)
        pairs = list(
            model.objects.exclude(**{f"{type_col}__isnull": True})
            .exclude(**{f"{id_col}__isnull": True})
            .values_list("pk", type_col, id_col)
        )
        orphans = sorted(pk for pk, code, target in pairs if target not in existing.get(code, set()))
        out[label] = {"with_target": len(pairs), "orphans": {"count": len(orphans), "ids": orphans}}

    audit = apps.get_model("carbon.USDACalculationAudit")
    out["carbon.USDACalculationAudit"] = {
        "count": audit.objects.count(),
        "event_type_slugs": dict(Counter(audit.objects.values_list("event_type", flat=True))),
    }

    mid = apps.get_model("certifications.MaterialIdentityDecision")
    by_source = {}
    for source, reviewed, exceptions in mid.objects.values_list("source", "reviewed", "exceptions"):
        target_label = MATERIAL_IDENTITY_SOURCES.get(source)
        target_ids = set(apps.get_model(target_label).objects.values_list("pk", flat=True)) if target_label else set()
        bucket = by_source.setdefault(source, {"decisions": 0, "reviewed": 0, "exceptions": 0, "orphans": 0})
        bucket["decisions"] += 1
        for item in reviewed or []:
            bucket["reviewed"] += 1
            bucket["orphans"] += int(item.get("event_id") not in target_ids)
        for item in exceptions or []:
            bucket["exceptions"] += 1
            bucket["orphans"] += int(item.get("event_id") not in target_ids)
    out["certifications.MaterialIdentityDecision"] = by_source
    return out


def _class_name_as_data_facts() -> Dict[str, Any]:
    models = _event_models()
    by_name = {m.__name__: set(m.objects.values_list("pk", flat=True)) for m in models.values()}
    entry = apps.get_model("carbon.CarbonEntry")
    linked, orphans, names = 0, 0, Counter()
    for description in entry.objects.filter(description__contains="(ID=").values_list("description", flat=True):
        match = CARBON_TEXT_LINK.search(description or "")
        if not match:
            continue
        linked += 1
        name, pk = match.group(1), int(match.group(2))
        names[name] += 1
        orphans += int(pk not in by_name.get(name, set()))
    return {
        "carbon_entries": entry.objects.count(),
        "carbon_entries_text_linked": linked,
        "carbon_entries_text_link_orphans": orphans,
        "carbon_entries_by_class_name": dict(names),
    }


def _audit_trail_facts() -> Dict[str, Any]:
    from django.contrib.contenttypes.models import ContentType

    content_types = {f"{ct.app_label}.{ct.model}": ct.pk for ct in ContentType.objects.order_by("pk")}
    out: Dict[str, Any] = {"content_types": content_types}
    if apps.is_installed("auditlog"):
        log_entry = apps.get_model("auditlog.LogEntry")
        counts = Counter()
        for app_label, model in log_entry.objects.values_list("content_type__app_label", "content_type__model"):
            counts[f"{app_label}.{model}"] += 1
        out["auditlog_entries_by_content_type"] = dict(sorted(counts.items()))
    notification = apps.get_model("notifications.Notification")
    out["notification_targets_by_content_type"] = dict(
        Counter(
            f"{a}.{m}"
            for a, m in notification.objects.exclude(content_type__isnull=True).values_list(
                "content_type__app_label", "content_type__model"
            )
        )
    )
    return out


# --------------------------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------------------------


def take_census(label: str = "") -> Dict[str, Any]:
    """Read everything once, in one read-only snapshot."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            # Must be the transaction's first statement. READ ONLY makes Postgres refuse any write.
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SELECT now(), txid_current_snapshot()::text")
            taken_at, snapshot = cursor.fetchone()
        tables = {m._meta.label: _table_census(m) for m in _census_models()}
        census = {
            "census_version": CENSUS_VERSION,
            "label": label,
            "taken_at": taken_at.astimezone(dt.timezone.utc).isoformat(),
            "snapshot": snapshot,
            "tables": tables,
            "sequences": _sequences(),
            "domain": {
                "events": _event_facts(),
                "seals": _seal_facts(),
                "loose_pairs": _loose_pair_facts(),
                "class_name_as_data": _class_name_as_data_facts(),
                "audit_trail": _audit_trail_facts(),
            },
        }
    return census


def summary(census: Dict[str, Any]) -> Dict[str, Any]:
    """The part a person reads: counts and verdicts, no row digests."""
    domain = census["domain"]
    return {
        "label": census["label"],
        "taken_at": census["taken_at"],
        "tables": len(census["tables"]),
        "rows": sum(t["count"] for t in census["tables"].values()),
        "row_counts": {label: t["count"] for label, t in census["tables"].items() if t["count"]},
        "sequences_behind": [label for label, s in census["sequences"].items() if not s["ok"]],
        "events": domain["events"],
        "seals": {k: v for k, v in domain["seals"].items() if k != "seasons"},
        "loose_pairs": domain["loose_pairs"],
        "class_name_as_data": domain["class_name_as_data"],
        "auditlog_entries_by_content_type": domain["audit_trail"].get("auditlog_entries_by_content_type", {}),
    }


def to_json(census: Dict[str, Any]) -> str:
    return json.dumps(census, sort_keys=True, separators=(",", ":"))


def compare(before: Dict[str, Any], after: Dict[str, Any], renames: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """What a migration lost, changed or added between two censuses.

    `renames` maps a model label in `before` to its label in `after` (a declared rename). A row
    missing after, a table missing after, a dropped column, or a seal that verified before and does
    not after are LOSSES and make `ok` False. Changed and new rows are listed for a person to judge:
    on a live system users keep writing between two censuses.
    """
    renames = renames or {}
    losses: List[str] = []
    changes: Dict[str, Any] = {}
    additions: Dict[str, int] = {}

    after_tables = after["tables"]
    for label, b in before["tables"].items():
        a = after_tables.get(renames.get(label, label))
        if a is None:
            losses.append(f"table {label} is missing")
            continue
        dropped = sorted(set(b["columns"]) - set(a["columns"]))
        if dropped:
            losses.append(f"{label}: columns dropped {dropped}")
        if b.get("volatile") or a.get("volatile"):
            continue
        missing = sorted(set(b["rows"]) - set(a["rows"]), key=_pk_sort)
        if missing:
            losses.append(f"{label}: {len(missing)} rows missing, e.g. {missing[:10]}")
        common = [c for c in b["columns"] if c in a["columns"]]
        changed, changed_columns = [], set()
        for key, b_row in b["rows"].items():
            a_row = a["rows"].get(key)
            if a_row is None:
                continue
            b_cells, a_cells = _cells(b, b_row), _cells(a, a_row)
            moved = [c for c in common if b_cells[c] != a_cells[c]]
            if moved:
                changed.append(key)
                changed_columns.update(moved)
        if changed:
            changed.sort(key=_pk_sort)
            changes[label] = {"rows": len(changed), "sample": changed[:10], "columns": sorted(changed_columns)}
        added = len(set(a["rows"]) - set(b["rows"]))
        if added:
            additions[label] = added

    b_seals = before["domain"]["seals"]["seasons"]
    a_seals = after["domain"]["seals"]["seasons"]
    for pk, seal in b_seals.items():
        now = a_seals.get(pk)
        for layer in ("layer1", "layer2"):
            if seal[layer] == "intact" and (now is None or now[layer] != "intact"):
                losses.append(f"season {pk}: {layer} verified before and is {now and now[layer]} after")
        if now is not None and seal["v1_preimage_order"] != now["v1_preimage_order"]:
            losses.append(f"season {pk}: v1 preimage order changed")

    for label, b in before["domain"]["loose_pairs"].items():
        if "orphans" not in b:
            continue
        a = after["domain"]["loose_pairs"].get(label, {})
        if a.get("orphans", {}).get("count", 0) > b["orphans"]["count"]:
            losses.append(f"{label}: orphan pairs grew {b['orphans']['count']} -> {a['orphans']['count']}")

    b_ct = before["domain"]["audit_trail"].get("auditlog_entries_by_content_type", {})
    a_ct = after["domain"]["audit_trail"].get("auditlog_entries_by_content_type", {})
    for ct, n in b_ct.items():
        if a_ct.get(renames.get(ct, ct), 0) < n:
            losses.append(f"auditlog entries for {ct} shrank {n} -> {a_ct.get(renames.get(ct, ct), 0)}")

    # A sequence already behind before is reported by `summary`, not blamed on the migration. One
    # that falls behind across it is a loss: the next insert into that table collides on its pk.
    before_label = {v: k for k, v in renames.items()}
    newly_behind = [
        label
        for label, seq in after["sequences"].items()
        if not seq["ok"] and before["sequences"].get(before_label.get(label, label), {}).get("ok", True)
    ]
    if newly_behind:
        losses.append(f"sequences fell behind max(pk): {newly_behind}")

    return {"ok": not losses, "losses": losses, "changed": changes, "added": additions}


def _cells(entry: Dict[str, Any], row: str) -> Dict[str, str]:
    """Column name -> cell hash for one stored row of `entry`."""
    cells = row.split(":", 1)[1]
    n = CELL_HASH_CHARS
    return {c: cells[i * n : (i + 1) * n] for i, c in enumerate(entry["columns"])}


def _pk_sort(key: str):
    return (0, int(key)) if key.lstrip("-").isdigit() else (1, key)
