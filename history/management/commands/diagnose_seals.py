"""Explain, season by season, why a stored finalization hash does or does not verify. Read only.

The 2026-11 baseline census found 8 of 9 sealed seasons whose layer-1 hash no longer matches.
On the consumer QR page a mismatch reads as `tampered` (ProductDetail) and hides the Records
pillar, so each one needs a cause before anything is changed:

- WHOSE season it is (company and farm name, published or not), to tell seeded demo data from a
  grower's record. No e-mail addresses or other personal data are printed.
- How many events the seal covered and how many the season has now.
- Whether the seal predates its own events: every event's audit-log CREATE is AFTER the seal's
  `finalization_timestamp`. That is a seal copied onto newly created rows (a seeder that carries
  `extra_data` across but mints new ids), not a record edited after sealing.
- Audit-log changes to the season's events after the seal, by action and by the hashed fields
  (`date`, `description`, `index`), and corrections (EventAmendment) filed after it.
- Whether the stored hash is reproduced by the other hash function (keccak vs sha256), or by any
  order of events that tie on `index` (the seal's sort is not total).

    manage.py diagnose_seals            # every sealed season
    manage.py diagnose_seals --season 9 --season 10

Everything runs in one `REPEATABLE READ READ ONLY` transaction (common.services.census).
"""

import hashlib
import itertools
import json
import math
from datetime import timezone as dt_timezone

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from common.services.census import read_only_snapshot

#: The model order `History.compute_finalization_hash` iterates. Frozen here as literal NAMES on
#: purpose: this command diagnoses hashes computed with these names.
SEAL_MODEL_ORDER = (
    "WeatherEvent",
    "ChemicalEvent",
    "ProductionEvent",
    "GeneralEvent",
    "EquipmentEvent",
    "SoilManagementEvent",
    "PestManagementEvent",
    "BusinessEvent",
)
HASHED_FIELDS = ("date", "description", "index")
MAX_TIE_ORDERS = 5000


def _keccak(text):
    try:
        from web3 import Web3
    except ImportError:
        return None
    return Web3.keccak(text=text).hex().removeprefix("0x")


def _sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _serialise(rows):
    return json.dumps(rows, sort_keys=True, default=str, separators=(",", ":"))


def _season_rows(history):
    from django.apps import apps

    rows = []
    for name in SEAL_MODEL_ORDER:
        model = apps.get_model("history", name)
        for row in model.objects.filter(history=history).values("id", "index", "date", "description"):
            row["event_type"] = name
            rows.append(row)
    rows.sort(key=lambda r: r["index"])
    return rows


def _tie_orders(rows):
    """Every ordering that keeps the `index` sort but permutes rows sharing an index."""
    groups = [list(g) for _, g in itertools.groupby(rows, key=lambda r: r["index"])]
    total = math.prod(math.factorial(len(g)) for g in groups)
    if total > MAX_TIE_ORDERS:
        return total, None
    return total, (
        [row for group in combo for row in group]
        for combo in itertools.product(*(itertools.permutations(g) for g in groups))
    )


class Command(BaseCommand):
    help = "Read-only: explain why each sealed season's finalization hash does or does not verify."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, action="append", default=[], help="History pk (repeatable).")

    def handle(self, *args, **options):
        from auditlog.models import LogEntry

        from history.models import EventAmendment, History

        with read_only_snapshot():
            sealed = History.objects.filter(extra_data__has_key="finalization_hash").select_related(
                "parcel__establishment__company"
            )
            if options["season"]:
                sealed = sealed.filter(pk__in=options["season"])
            event_cts = {
                ct.model: ct.pk
                for ct in ContentType.objects.filter(
                    app_label="history", model__in=[n.lower() for n in SEAL_MODEL_ORDER]
                )
            }

            reports = []
            for history in sealed.order_by("pk"):
                reports.append(self._diagnose(history, event_cts, LogEntry, EventAmendment))

        for report in reports:
            self.stdout.write(json.dumps(report, sort_keys=True, default=str))
        verdicts = {}
        for report in reports:
            verdicts[report["verdict"]] = verdicts.get(report["verdict"], 0) + 1
        self.stdout.write(json.dumps({"seasons": len(reports), "verdicts": verdicts}, sort_keys=True))

    def _diagnose(self, history, event_cts, LogEntry, EventAmendment):
        extra = history.extra_data if isinstance(history.extra_data, dict) else {}
        stored = extra.get("finalization_hash")
        sealed_at_raw = extra.get("finalization_timestamp")
        sealed_at = parse_datetime(sealed_at_raw) if isinstance(sealed_at_raw, str) else None
        if sealed_at is not None and timezone.is_naive(sealed_at):
            sealed_at = timezone.make_aware(sealed_at, dt_timezone.utc)
        establishment = getattr(history.parcel, "establishment", None) if history.parcel_id else None
        company = getattr(establishment, "company", None) if establishment else None

        rows = _season_rows(history)
        text = _serialise(rows)
        keccak, sha = _keccak(text), _sha256(text)

        tie_total, orders = _tie_orders(rows)
        tie_match = None
        if tie_total > 1 and orders is not None:
            for order in orders:
                candidate = _serialise(order)
                if stored in (_keccak(candidate), _sha256(candidate)):
                    tie_match = True
                    break
            else:
                tie_match = False

        # The seal's sort is by `index` only, so rows that tie keep the order the database returned
        # them in: each model's rows in physical order, models in SEAL_MODEL_ORDER. Physical order
        # is roughly insertion (pk) order until an UPDATE moves a row, and an UPDATE made by a
        # migration leaves no audit-log entry. Trying all permutations of a 22-way tie is out of
        # reach, but the orders the rows were most likely in when sealed are cheap to try. A
        # match means the content is exactly what was sealed and only the row order moved.
        row_order_match = None
        if tie_total > 1 and not tie_match:
            position = {name: i for i, name in enumerate(SEAL_MODEL_ORDER)}
            candidates = {
                "pk_ascending": lambda r: (r["index"], position[r["event_type"]], r["id"]),
                "pk_descending": lambda r: (r["index"], position[r["event_type"]], -r["id"]),
                "date_then_pk": lambda r: (r["index"], position[r["event_type"]], str(r["date"]), r["id"]),
            }
            for label, key in candidates.items():
                candidate = _serialise(sorted(rows, key=key))
                if stored in (_keccak(candidate), _sha256(candidate)):
                    row_order_match = label
                    break

        # Audit trail of this season's CURRENT events.
        ids_by_model = {}
        for row in rows:
            ids_by_model.setdefault(row["event_type"].lower(), []).append(str(row["id"]))
        created_after_seal = created_before_seal = 0
        with_create_entry = set()
        changes_after = {"update": 0, "delete": 0, "create": 0}
        hashed_fields_changed = set()
        for model, ids in ids_by_model.items():
            entries = LogEntry.objects.filter(content_type_id=event_cts.get(model), object_pk__in=ids)
            for object_pk, action, timestamp, changes in entries.values_list(
                "object_pk", "action", "timestamp", "changes"
            ):
                if action == LogEntry.Action.CREATE:
                    with_create_entry.add((model, object_pk))
                after_seal = sealed_at is not None and timestamp > sealed_at
                if action == LogEntry.Action.CREATE:
                    if sealed_at is None:
                        continue
                    if after_seal:
                        created_after_seal += 1
                    else:
                        created_before_seal += 1
                if not after_seal:
                    continue
                key = {
                    LogEntry.Action.CREATE: "create",
                    LogEntry.Action.UPDATE: "update",
                    LogEntry.Action.DELETE: "delete",
                }.get(action)
                if key:
                    changes_after[key] += 1
                if action == LogEntry.Action.UPDATE and isinstance(changes, dict):
                    hashed_fields_changed.update(f for f in HASHED_FIELDS if f in changes)

        # Events DELETED after the seal are not among `rows` (those are the events that exist
        # now), so the loop above cannot see their DELETE entries (review of back #291). Find them
        # by the season they belonged to: auditlog records a deleted row's foreign key in
        # `changes` as ["<old pk>", "None"].
        if sealed_at is not None:
            changes_after["delete"] = LogEntry.objects.filter(
                content_type_id__in=[pk for pk in event_cts.values() if pk],
                action=LogEntry.Action.DELETE,
                timestamp__gt=sealed_at,
                changes__history__0=str(history.pk),
            ).count()

        amendments_after = (
            EventAmendment.objects.filter(history=history, created_at__gt=sealed_at).count() if sealed_at else None
        )
        stored_count = extra.get("finalization_event_count")
        verdict = self._verdict(
            stored,
            keccak,
            sha,
            tie_match,
            row_order_match,
            stored_count,
            len(rows),
            created_after_seal,
            created_before_seal,
            hashed_fields_changed,
            changes_after,
        )
        return {
            "season": history.pk,
            "public_id": str(history.public_id),
            "name": history.name,
            "company": getattr(company, "name", None),
            "farm": getattr(establishment, "name", None),
            "published": history.published,
            "finish_date": history.finish_date,
            "sealed_at": sealed_at_raw,
            "stored_event_count": stored_count,
            "current_event_count": len(rows),
            "matches_keccak": keccak == stored,
            "matches_sha256": sha == stored,
            "tie_orders": tie_total,
            "matches_a_tie_order": tie_match,
            "matches_row_order": row_order_match,
            "events_created_before_seal": created_before_seal,
            "events_created_after_seal": created_after_seal,
            # Bulk-created or seeded rows never fire auditlog: no CREATE entry at all.
            "events_without_create_entry": len(rows) - len(with_create_entry),
            "audit_after_seal": changes_after,
            "hashed_fields_changed_after_seal": sorted(hashed_fields_changed),
            "amendments_after_seal": amendments_after,
            "has_blockchain_data_hash": bool(extra.get("blockchain_data_hash")),
            "verdict": verdict,
        }

    @staticmethod
    def _verdict(
        stored,
        keccak,
        sha,
        tie_match,
        row_order_match,
        stored_count,
        current_count,
        created_after,
        created_before,
        fields_changed,
        changes_after,
    ):
        if stored in (keccak, sha):
            return "intact" if stored == keccak else "intact_with_sha256"
        if tie_match:
            return "tie_order"
        if row_order_match:
            return "row_order_changed"
        # EVERY current event must be created after the seal; events with no CREATE entry at all
        # are no evidence either way (review of back #291).
        if created_after and not created_before and created_after == current_count:
            return "seal_predates_its_events"
        if stored_count is not None and stored_count != current_count:
            return "event_count_changed"
        if fields_changed:
            return "hashed_field_edited_after_seal"
        if any(changes_after.values()):
            return "changed_after_seal"
        return "unexplained"
