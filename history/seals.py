"""Sealing a finished season, and checking a seal later. The one place either happens.

A seal is a hash over a season's events, stored in `History.extra_data` when the season is
finished, and recomputed by `verify_blockchain` to tell a buyer whether the record still matches.

Version 1 (every seal written before 2026-11-05) hashed
`values("id", "index", "date", "description")` per event model, tagged each row with the model's
CLASS NAME, and sorted by `index` only. Two defects, both measured on production:

- The order is not total. Rows that share an `index` keep the order the database happened to
  return them in, and without `ORDER BY` Postgres may return them differently from one query to
  the next. A Calapooia season resealed at 00:28:37 on 2026-11-05 (65 events, one `index`) failed
  its own check minutes later with nothing changed. 19 of 35 seasons had ties.
- The class name is part of the bytes, so renaming a model would break every seal.

Version 2 sorts by `(index, model position, pk)`, a total order, tags rows with a frozen KIND slug,
and records its version and algorithm next to the hash. It uses sha256 from the standard library,
so the result never depends on whether an optional package (web3) happens to import.

Version 1 seals are still checked, never rewritten: a stored seal is evidence of what was sealed.
Its check tries the database's order, then every order of the tied rows (when there are few
enough), then the orders the rows were most likely in when sealed. When none reproduces the hash,
the result is `mismatch` only if the season has no ties. With ties it is `inconclusive`: v1 cannot
tell a changed record from a changed row order, and calling that "tampered" would state more than
the evidence does.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from django.db import transaction
from django.utils import timezone

V1 = 1
V2 = 2
CURRENT_VERSION = V2

#: Version 1's model order and tags, frozen as the literal class names v1 hashed. Never derive
#: these from the models: a rename must not change what an existing seal is checked against.
V1_MODEL_ORDER: Tuple[str, ...] = (
    "WeatherEvent",
    "ChemicalEvent",
    "ProductionEvent",
    "GeneralEvent",
    "EquipmentEvent",
    "SoilManagementEvent",
    "PestManagementEvent",
    "BusinessEvent",
)

#: Version 2's tags: model -> kind slug, in v2's order. Frozen for the same reason. The slug is the
#: contract; the class it is read from may be renamed freely.
V2_KINDS: Tuple[Tuple[str, str], ...] = (
    ("WeatherEvent", "weather"),
    ("ChemicalEvent", "chemical"),
    ("ProductionEvent", "production"),
    ("GeneralEvent", "general"),
    ("EquipmentEvent", "equipment"),
    ("SoilManagementEvent", "soil"),
    ("PestManagementEvent", "pest"),
    ("BusinessEvent", "business"),
)
V2_ALGORITHM = "sha256"

#: Version 1 checks give up enumerating tie orders beyond this many.
MAX_TIE_ORDERS = 5000

INTACT = "intact"
MISMATCH = "mismatch"
INCONCLUSIVE = "inconclusive"
NO_SEAL = "no_seal"
ERROR = "error"


@dataclass(frozen=True)
class Verification:
    status: str
    version: Optional[int]
    event_count: Optional[int]
    detail: str = ""


def _serialise(rows: List[dict]) -> str:
    return json.dumps(rows, sort_keys=True, default=str, separators=(",", ":"))


def _model(name: str):
    from django.apps import apps

    return apps.get_model("history", name)


# --------------------------------------------------------------------------------------------
# Version 2
# --------------------------------------------------------------------------------------------


def v2_rows(history) -> List[dict]:
    rows = []
    for position, (name, kind) in enumerate(V2_KINDS):
        for row in _model(name).objects.filter(history=history).values("id", "index", "date", "description"):
            row["kind"] = kind
            row["_position"] = position
            rows.append(row)
    rows.sort(key=lambda r: (r["index"], r["_position"], r["id"]))
    for row in rows:
        del row["_position"]
    return rows


def v2_hash(history) -> Tuple[str, int]:
    rows = v2_rows(history)
    return hashlib.sha256(_serialise(rows).encode("utf-8")).hexdigest(), len(rows)


def seal_fields(history) -> Dict[str, object]:
    """The `extra_data` keys that seal `history` now. The caller stores them."""
    digest, count = v2_hash(history)
    return {
        "finalization_hash": digest,
        "finalization_hash_version": V2,
        "finalization_hash_algorithm": V2_ALGORITHM,
        "finalization_event_count": count,
        "finalization_timestamp": timezone.now().isoformat(),
    }


def seal(history) -> Dict[str, object]:
    """Seal `history` with the current version and save only `extra_data`."""
    fields = seal_fields(history)
    extra = dict(history.extra_data) if isinstance(history.extra_data, dict) else {}
    extra.update(fields)
    history.extra_data = extra
    history.save(update_fields=["extra_data"])
    return fields


# --------------------------------------------------------------------------------------------
# Version 1 (check only)
# --------------------------------------------------------------------------------------------


def v1_rows(history) -> List[dict]:
    """Version 1's preimage rows in the order v1 itself produced them (database order on ties)."""
    rows = []
    for name in V1_MODEL_ORDER:
        for row in _model(name).objects.filter(history=history).values("id", "index", "date", "description"):
            row["event_type"] = name
            rows.append(row)
    rows.sort(key=lambda r: r["index"])
    return rows


def _v1_digests(rows: List[dict]) -> Tuple[str, Optional[str]]:
    """v1 used keccak when web3 imported and sha256 otherwise; a v1 seal may be either."""
    text = _serialise(rows)
    sha = hashlib.sha256(text.encode()).hexdigest()
    try:
        from web3 import Web3
    except ImportError:
        return sha, None
    return sha, Web3.keccak(text=text).hex().removeprefix("0x")


def _v1_candidate_orders(rows: List[dict]):
    yield rows
    groups = [list(g) for _, g in itertools.groupby(rows, key=lambda r: r["index"])]
    if all(len(g) == 1 for g in groups):
        return
    if math.prod(math.factorial(len(g)) for g in groups) <= MAX_TIE_ORDERS:
        for combo in itertools.product(*(itertools.permutations(g) for g in groups)):
            yield [row for group in combo for row in group]
        return
    position = {name: i for i, name in enumerate(V1_MODEL_ORDER)}
    for key in (
        lambda r: (r["index"], position[r["event_type"]], r["id"]),
        lambda r: (r["index"], position[r["event_type"]], -r["id"]),
        lambda r: (r["index"], position[r["event_type"]], str(r["date"]), r["id"]),
    ):
        yield sorted(rows, key=key)


def _has_ties(rows: List[dict]) -> bool:
    indexes = [r["index"] for r in rows]
    return len(indexes) != len(set(indexes))


def _verify_v1(history, stored: str) -> Verification:
    rows = v1_rows(history)
    for order in _v1_candidate_orders(rows):
        if stored in _v1_digests(order):
            return Verification(INTACT, V1, len(rows))
    if _has_ties(rows):
        return Verification(
            INCONCLUSIVE,
            V1,
            len(rows),
            "Sealed with the first method, whose event order is not fixed: the record cannot be " "re-checked exactly.",
        )
    return Verification(MISMATCH, V1, len(rows), "The events do not match the sealed record.")


# --------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------


def verify(history) -> Verification:
    """Check `history`'s stored seal against its events now. Never writes."""
    extra = history.extra_data if isinstance(history.extra_data, dict) else {}
    stored = extra.get("finalization_hash")
    if not stored:
        return Verification(NO_SEAL, None, None)
    version = extra.get("finalization_hash_version", V1)
    try:
        # Own savepoint: a database error inside a caller's transaction aborts it in Postgres, and
        # catching the exception INSIDE an atomic block would leave Django releasing a savepoint of
        # an aborted transaction. Rolled back here, the caller's transaction stays usable.
        with transaction.atomic():
            if version == V2:
                digest, count = v2_hash(history)
                if digest == stored:
                    return Verification(INTACT, V2, count)
                return Verification(MISMATCH, V2, count, "The events do not match the sealed record.")
            if version == V1:
                return _verify_v1(history, stored)
            return Verification(ERROR, version, None, f"Unknown seal version {version!r}.")
    except Exception as exc:  # a check must answer, never raise into a public page
        return Verification(ERROR, version, None, f"{exc.__class__.__name__}")
