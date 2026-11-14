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
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from django.apps import apps
from django.db import connection, transaction

CENSUS_VERSION = 1
CELL_HASH_CHARS = 8

#: Tables whose rows churn on every request: counted, never digested. A session or a refresh token
#: changing between two censuses is not data loss.
VOLATILE_APP_LABELS = {"sessions", "token_blacklist"}

#: Models whose table may leave the census without counting as a loss, but only when the census
#: before counted 0 rows in it (see `compare`). Each one names the migration that retired it.
RETIRED_TABLES = {
    # carbon 0050 (2026-11-06) took them out of the model state; 0051 dropped the tables.
    "carbon.CarbonIntelligence",
    "carbon.GreenPoints",
    "carbon.MicroOffset",
    "carbon.RegionalEmissionFactor",
    "carbon.SustainabilityBadge",
    "carbon.SustainabilityBadge_establishments",
    "carbon.SustainabilityBadge_productions",
    # Retiring 2026-11-07: carbon 0052 takes them out of the model state, its step 2 drops the
    # tables. Production held 0 rows in each on 2026-11-07.
    "carbon.CarbonBenchmark",
    "carbon.CarbonOffsetCertificate",
    "carbon.CarbonOffsetProject",
    "carbon.CarbonOffsetPurchase",
    "carbon.CarbonReport",
    # carbon 0054 (2026-11-08): the score log, emptied first by clear_optimized_carbon_calculations
    # (the command lives in the code up to #347's merge commit c109495a; 0054 deletes it).
    "carbon.OptimizedCarbonCalculation",
    # Retiring 2026-11-09: history 0254 takes the shopper models out of the model state, its step 2
    # drops the tables. Production held 0 rows in each on 2026-11-09.
    "history.UserFavorite",
    "history.UserLocalRecommendation",
    "history.UserLocalRecommendation_recommended_products",
    "history.UserProductComparison",
    "history.UserProductComparison_products",
    "history.UserShoppingGoal",
    "history.UserShoppingInsight",
    # history 0256 (2026-11-10) takes UserImpactSummary out of the model state, 0258 drops the table.
    # Emptied first by clear_impact_summaries (the command lives in the code up to #367's merge
    # commit ff15233b; 0256 deletes it); production held 0 rows after its apply on 2026-11-11.
    "history.UserImpactSummary",
}

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
        # history.seals checks the seal at the version it was written with, in its own savepoint:
        # a database error inside this read-only transaction would otherwise abort it, and every
        # later query with it (review of back #289). The error is recorded and the census goes on.
        from history.seals import ERROR, verify

        check = verify(history)
        event_count = check.event_count
        layer1 = f"error: {check.detail}" if check.status == ERROR else check.status

        stored_data_hash = extra.get("blockchain_data_hash")
        if stored_data_hash:
            try:
                company_id = history.parcel.establishment.company_id if history.parcel else None
                with transaction.atomic():
                    _raw, data_hash, *_ = build_blockchain_raw_data(history, company_id)
                layer2 = "intact" if data_hash == stored_data_hash else "mismatch"
            except Exception as exc:
                layer2 = f"error: {exc.__class__.__name__}"
        else:
            layer2 = "not_submitted"

        seasons[str(history.pk)] = {
            "public_id": str(history.public_id),
            "layer1": layer1,
            "seal_version": extra.get("finalization_hash_version", 1),
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


#: The Activity foreign key each loose pair now carries next to it (schema remodel plan, Phase 2).
ACTIVITY_LINKS = {
    "history.EventAmendment": "activity_id",
    "history.ProductionPlanItem": "fulfilled_by_activity_id",
    "documents.GeneratedDocument": "activity_id",
    "fieldnotes.FieldNote": "fulfilled_by_activity_id",
    "fieldnotes.FieldNoteConfirmation": "activity_id",
}


def _loose_pair_facts() -> Dict[str, Any]:
    models = _event_models()
    identity = {
        code: (
            dict(m.objects.values_list("pk", "activity_id"))
            if any(f.name == "activity" for f in m._meta.concrete_fields)
            else {pk: None for pk in m.objects.values_list("pk", flat=True)}
        )
        for code, m in models.items()
    }
    out = {}
    for label, (type_col, id_col) in LOOSE_EVENT_PAIRS.items():
        model = apps.get_model(label)
        link = ACTIVITY_LINKS.get(label)
        has_link = link is not None and any(f.attname == link for f in model._meta.concrete_fields)
        columns = ["pk", type_col, id_col] + ([link] if has_link else [])
        pairs = list(
            model.objects.exclude(**{f"{type_col}__isnull": True})
            .exclude(**{f"{id_col}__isnull": True})
            .values_list(*columns)
        )
        orphans = sorted(row[0] for row in pairs if row[2] not in identity.get(row[1], {}))
        facts = {"with_target": len(pairs), "orphans": {"count": len(orphans), "ids": orphans}}
        if has_link:
            # The FK must name exactly the identity of the event the pair names. A live target
            # with no FK, or an FK that names another identity, is a broken dual write.
            unlinked, disagreeing = [], []
            for pk, code, target, activity_id in pairs:
                expected = identity.get(code, {}).get(target)
                if expected is None:
                    continue
                if activity_id is None:
                    unlinked.append(pk)
                elif activity_id != expected:
                    disagreeing.append(pk)
            facts["activity_link"] = {
                "linked": sum(1 for row in pairs if row[3] is not None),
                "live_target_unlinked": {"count": len(unlinked), "ids": sorted(unlinked)},
                "disagrees_with_pair": {"count": len(disagreeing), "ids": sorted(disagreeing)},
            }
        out[label] = facts

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
    facts = {
        "carbon_entries": entry.objects.count(),
        "carbon_entries_text_linked": linked,
        "carbon_entries_text_link_orphans": orphans,
        "carbon_entries_by_class_name": dict(names),
    }
    if any(f.attname == "activity_id" for f in entry._meta.concrete_fields):
        facts["carbon_entry_activity_link"] = _carbon_entry_link_facts(entry, models)
    return facts


def _carbon_entry_link_facts(entry, models) -> Dict[str, Any]:
    """The CarbonEntry -> Activity link against the writer's text, under carbon/event_link.py's
    strict rule (the one migration carbon 0047 froze).

    `live_target_unlinked`: no link, though the rule ties the row to a live event of its own
    production (a straggler: `manage.py link_carbon_entries` links it). `disagrees_with_text`: the
    link names another identity than the event the text names.
    """
    from carbon.event_link import named_event, user_created

    live = {
        m.__name__: {pk: (a, h) for pk, a, h in m.objects.values_list("pk", "activity_id", "history_id")}
        for m in models.values()
    }
    unlinked, disagreeing, per_activity = [], [], Counter()
    rows = entry.objects.annotate(created_by_user=user_created()).values_list(
        "pk", "activity_id", "production_id", "description", "registry_verification_id", "created_by_user"
    )
    linked = 0
    for pk, activity_id, production_id, description, registry_id, by_user in rows:
        if activity_id is not None:
            linked += 1
            per_activity[activity_id] += 1
        named = named_event(description, registry_id)
        target = live.get(named[0], {}).get(named[1]) if named else None
        if target is None:
            continue
        if activity_id is None:
            if not by_user and target[1] == production_id:
                unlinked.append(pk)
        elif activity_id != target[0]:
            disagreeing.append(pk)
    return {
        "linked": linked,
        "live_target_unlinked": {"count": len(unlinked), "ids": sorted(unlinked)},
        "disagrees_with_text": {"count": len(disagreeing), "ids": sorted(disagreeing)},
        "activities_with_more_than_one_entry": sum(1 for n in per_activity.values() if n > 1),
    }


def _activity_facts() -> Dict[str, Any]:
    """The Activity identity table (history.models.Activity) holds together.

    Postgres can enforce one event per Activity WITHIN a table (OneToOne), not across the eight
    tables, and cannot check that an Activity's `kind` names the table that points at it. So the
    census does: events without an identity, identities shared by two events, kinds that disagree,
    and identities with no event that are not tombstones.
    """
    if not apps.is_installed("history"):
        return {}
    try:
        Activity = apps.get_model("history", "Activity")
    except LookupError:
        return {}
    referenced = Counter()
    kind_mismatch = 0
    without = {}
    activity_kind = dict(Activity.objects.values_list("pk", "kind"))
    for code, model in _event_models().items():
        rows = list(model.objects.values_list("activity_id", flat=True))
        without[model._meta.label] = sum(1 for a in rows if a is None)
        for activity_id in rows:
            if activity_id is None:
                continue
            referenced[activity_id] += 1
            kind_mismatch += int(activity_kind.get(activity_id) != code)
    tombstoned = set(Activity.objects.exclude(deleted_at__isnull=True).values_list("pk", flat=True))
    unreferenced_live = [pk for pk in activity_kind if pk not in referenced and pk not in tombstoned]
    return {
        "activities": len(activity_kind),
        "tombstones": len(tombstoned),
        "events_without_activity": without,
        "activities_shared_by_two_events": sum(1 for n in referenced.values() if n > 1),
        "kind_mismatches": kind_mismatch,
        "unreferenced_live_activities": len(unreferenced_live),
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


@contextmanager
def read_only_snapshot():
    """One transaction in which Postgres refuses every write, all reads seeing one snapshot.

    Yields `(taken_at, snapshot)`. Must open a REAL transaction: `SET TRANSACTION` has to be its
    first statement, so inside an outer `atomic()` (a test's TestCase, a caller's own transaction)
    Postgres refuses it.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SELECT now(), txid_current_snapshot()::text")
            taken_at, snapshot = cursor.fetchone()
        yield taken_at, snapshot


def take_census(label: str = "") -> Dict[str, Any]:
    """Read everything once, in one read-only snapshot."""
    with read_only_snapshot() as (taken_at, snapshot):
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
                "activity": _activity_facts(),
                "retiring_columns": _retiring_column_facts(),
            },
        }
    return census


def _retiring_columns() -> Dict[str, Dict[str, Any]]:
    """Model label -> {column: the value it holds when empty}, for columns due to be dropped.

    A column listed here may disappear between two censuses without counting as a loss, but only
    if no row held anything but that value before (see `compare`).
    """
    from carbon.retired_columns import RETIRED_CARBON_ENTRY_COLUMNS

    return {
        "carbon.CarbonEntry": RETIRED_CARBON_ENTRY_COLUMNS,
        # The foreign key to CarbonReport, retiring with it (carbon 0052, then its step 2).
        "carbon.CarbonAuditLog": {"report_id": None},
    }


def _retiring_column_facts() -> Dict[str, Dict[str, int]]:
    """Per retiring column still in the schema, how many rows hold something other than empty."""
    out: Dict[str, Dict[str, int]] = {}
    for label, columns in _retiring_columns().items():
        model = apps.get_model(label)
        # Keyed by DATABASE column, as `_table_census` lists them and `compare` diffs them. For a
        # foreign key the column (`report_id`) is not the field name (`report`); keyed by name, the
        # declaration matched nothing and the drop read as undeclared.
        fields = {f.column: f for f in model._meta.concrete_fields}
        out[label] = {
            column: model.objects.exclude(**{fields[column].attname: empty}).count()
            for column, empty in sorted(columns.items())
            if column in fields
        }
    return out


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
        "activity": domain.get("activity", {}),
        "retiring_columns": domain.get("retiring_columns", {}),
    }


def to_json(census: Dict[str, Any]) -> str:
    return json.dumps(census, sort_keys=True, separators=(",", ":"))


#: How much a seal layer establishes, for telling a downgrade from a lateral move. `inconclusive`
#: (a v1 seal whose ties are too wide to re-check) is below `intact` and above a failure.
_SEAL_RANK = {"intact": 3, "not_submitted": 2, "inconclusive": 2, "no_seal": 2}


def compare(before: Dict[str, Any], after: Dict[str, Any], renames: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """What a migration lost, changed or added between two censuses.

    `renames` maps a model label in `before` to its label in `after` (a declared rename). A row
    missing after, a table missing after (unless it is in RETIRED_TABLES and `before` counted 0
    rows in it), a dropped column (unless `before` counted it as a
    retiring column with no row holding a value), or a seal that verified before and does not
    after are LOSSES and make `ok` False. Changed and new rows are listed for a person to judge:
    on a live system users keep writing between two censuses.
    """
    renames = renames or {}
    losses: List[str] = []
    notes: List[str] = []
    changes: Dict[str, Any] = {}
    additions: Dict[str, int] = {}

    after_tables = after["tables"]
    for label, b in before["tables"].items():
        a = after_tables.get(renames.get(label, label))
        if a is None:
            # A declared retired table may go, but only if the census before it went counted no
            # row in it. Any other table that disappears is a loss, empty or not.
            if label in RETIRED_TABLES and b["count"] == 0:
                notes.append(f"table {label} retired, empty before")
            elif label in RETIRED_TABLES:
                losses.append(f"retired table {label} is missing while it held {b['count']} rows")
            else:
                losses.append(f"table {label} is missing")
            continue
        dropped = sorted(set(b["columns"]) - set(a["columns"]))
        # A declared retiring column may go, but only if the census before it went found no row
        # holding a value in it (the values were cleared through a logged data operation first).
        # Anything else that disappears is a loss, as is a retiring column dropped with values.
        retiring = before["domain"].get("retiring_columns", {}).get(label, {})
        emptied = [c for c in dropped if retiring.get(c) == 0]
        if emptied:
            notes.append(f"{label}: retired columns dropped, every row held the empty value before: {emptied}")
        still_held = {c: retiring[c] for c in dropped if retiring.get(c)}
        if still_held:
            losses.append(f"{label}: retired columns dropped while rows still held a value {still_held}")
        undeclared = [c for c in dropped if c not in retiring]
        if undeclared:
            losses.append(f"{label}: columns dropped {undeclared}")
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
            was, is_now = seal[layer], (now or {}).get(layer)
            if _SEAL_RANK.get(is_now, 0) < _SEAL_RANK.get(was, 0):
                losses.append(f"season {pk}: {layer} was {was} and is {is_now} after")
        # The order a v1 seal's tied rows come back in is the database's, not the record's: any
        # UPDATE to those rows moves it (the Activity backfill did, 2026-11-05, with no value
        # changed). Whether the seal still verifies is what the layer checks above judge, so a
        # moved order is a note, never a loss.
        if now is not None and seal["v1_preimage_order"] != now["v1_preimage_order"]:
            notes.append(f"season {pk}: database order of tied rows moved (seal status {now['layer1']})")

    for label, b in before["domain"]["loose_pairs"].items():
        if "orphans" not in b:
            continue
        a = after["domain"]["loose_pairs"].get(renames.get(label, label), {})
        for key in ("live_target_unlinked", "disagrees_with_pair"):
            was = b.get("activity_link", {}).get(key, {}).get("count", 0)
            now = a.get("activity_link", {}).get(key, {}).get("count", 0)
            if now > was:
                losses.append(f"{label}: activity link {key} grew {was} -> {now}")
        if a.get("orphans", {}).get("count", 0) > b["orphans"]["count"]:
            losses.append(f"{label}: orphan pairs grew {b['orphans']['count']} -> {a['orphans']['count']}")

    b_act, a_act = before["domain"].get("activity", {}), after["domain"].get("activity", {})
    for key in ("activities_shared_by_two_events", "kind_mismatches", "unreferenced_live_activities"):
        if a_act.get(key, 0) > b_act.get(key, 0):
            losses.append(f"activity identity: {key} grew {b_act.get(key, 0)} -> {a_act.get(key, 0)}")
    if b_act.get("activities", 0) > a_act.get("activities", 0):
        losses.append(
            f"activity identity: activities shrank {b_act.get('activities', 0)} -> {a_act.get('activities', 0)}"
        )

    b_carbon = before["domain"].get("class_name_as_data", {}).get("carbon_entry_activity_link", {})
    a_carbon = after["domain"].get("class_name_as_data", {}).get("carbon_entry_activity_link", {})
    for key in ("live_target_unlinked", "disagrees_with_text"):
        was = b_carbon.get(key, {}).get("count", 0)
        now = a_carbon.get(key, {}).get("count", 0)
        if now > was:
            losses.append(f"carbon.CarbonEntry: activity link {key} grew {was} -> {now}")
    if b_carbon.get("linked", 0) > a_carbon.get("linked", 0):
        losses.append(f"carbon.CarbonEntry: activity links shrank {b_carbon['linked']} -> {a_carbon.get('linked', 0)}")

    b_ct = before["domain"]["audit_trail"].get("auditlog_entries_by_content_type", {})
    a_ct = after["domain"]["audit_trail"].get("auditlog_entries_by_content_type", {})
    # Content types are keyed "<app_label>.<model>" in LOWER case (ContentType.model), while
    # `renames` uses model labels ("history.History"). Compare in one case, or a declared rename
    # reads as the whole audit trail vanishing (review of back #289).
    ct_renames = {k.lower(): v.lower() for k, v in renames.items()}
    for ct, n in b_ct.items():
        now = a_ct.get(ct_renames.get(ct, ct), 0)
        if now < n:
            losses.append(f"auditlog entries for {ct} shrank {n} -> {now}")

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

    new_tables = sorted(
        label for label in after["tables"] if label not in set(renames.get(b, b) for b in before["tables"])
    )
    return {
        "ok": not losses,
        "losses": losses,
        "changed": changes,
        "added": additions,
        "new_tables": new_tables,
        "notes": notes,
    }


def _cells(entry: Dict[str, Any], row: str) -> Dict[str, str]:
    """Column name -> cell hash for one stored row of `entry`."""
    cells = row.split(":", 1)[1]
    n = CELL_HASH_CHARS
    return {c: cells[i * n : (i + 1) * n] for i, c in enumerate(entry["columns"])}


def _pk_sort(key: str):
    return (0, int(key)) if key.lstrip("-").isdigit() else (1, key)
