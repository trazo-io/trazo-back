"""Block / row / section identifiers — normalisation and the per-parcel vocabulary.

`CommonEvent.block_id` is free text on all 8 event types, and it is load-bearing: it is emitted
as **CA PUR box 22 (Block ID)**, folded into the audit export's Input Application Log, and it is
where a COG Pro migration lands the grower's "Row/Section ID".

Free text plus no vocabulary is a traceability leak that compounds silently. A grower types
"Block 3" in March, "block 3 " in May and "Blk 3" in July; a certifier asking "show me everything
that happened in Block 3" gets a third of it, and nothing anywhere reports the gap.

This is not hypothetical. `audit_export_service.py` already carries a regex specifically because
growers name blocks "Block 1" and a blind "Blk " prefix produced **"Blk Block 1"** on a live
export — a band-aid over exactly this defect. And dev data, which is mostly seeded, already
contains `ds` alongside both `Hillside Grove A` and
`Hillside Grove A — East Buffer Zone (rows 1-12)`.

The fix has two halves and they only work together:

* `normalize_block_id` collapses the mechanical variation (whitespace, casing of the pattern) on
  every write, so equal blocks compare equal.
* `known_block_ids_for_parcel` gives the UI a vocabulary to offer, so the grower **picks** an
  existing block instead of retyping it. Imported COG Pro values seed that list for free, which
  is what stops a migration's block structure diverging the first time the farmer logs an event.
"""

from __future__ import annotations

import re

# Collapse runs of any whitespace (including the non-breaking spaces phone keyboards emit).
_WHITESPACE = re.compile(r"\s+")


def normalize_block_id(value):
    """Canonical storage form for a block identifier.

    Deliberately conservative: it fixes only mechanical variation and never re-words the grower's
    label. `"Block 3"` stays `"Block 3"` — it is NOT rewritten to `"3"` or `"BLOCK 3"`, because the
    farmer's own name for a block is what they will look for on an audit, and rewriting it would
    make the record disagree with their paper map.

    Returns `None` for anything empty so the column holds NULL rather than `""` — two spellings
    of "no block" would otherwise both exist.
    """
    if value is None:
        return None
    text = _WHITESPACE.sub(" ", str(value).replace(" ", " ")).strip()
    return text or None


def blocks_match(a, b) -> bool:
    """Do two identifiers refer to the same block, ignoring case and spacing?"""
    na, nb = normalize_block_id(a), normalize_block_id(b)
    if na is None or nb is None:
        return False
    return na.casefold() == nb.casefold()


def known_block_ids_for_parcel(parcel) -> list:
    """Distinct block identifiers already recorded against this parcel's events.

    Powers the autocomplete on the event forms.

    Case variants collapse to ONE entry, and the winner is the spelling the grower has used
    MOST — so a block written "Block 3" forty times and "BLOCK 3" once by accident is offered
    back as "Block 3". Ties break alphabetically purely so the result is deterministic: an
    earlier version kept "the first spelling seen", but `.distinct()` carries no ORDER BY, so
    which variant won depended on Postgres row order and could change between calls.

    Ordered alphabetically and case-insensitively: this is a picker, not a timeline, and a farm
    with 20 blocks needs to scan it.
    """
    if parcel is None:
        return []
    return known_block_ids_for_parcels([parcel.pk])[parcel.pk]


def known_block_ids_for_parcels(parcel_ids) -> dict:
    """`known_block_ids_for_parcel` for many parcels at once: `{parcel_id: [...]}`.

    One query per event model (8 in total) whatever the number of parcels, so a farm-wide list,
    such as the multi-parcel picker's section chips, does not cost 8 queries per parcel. Every
    requested id is a key, with `[]` when the parcel has no sections recorded. Same rules as the
    single-parcel version, which delegates here so they cannot drift.
    """
    ids = list(dict.fromkeys(int(pid) for pid in parcel_ids))
    result: dict = {pid: [] for pid in ids}
    if not ids:
        return result

    from django.db.models import Count

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

    models = (
        ChemicalEvent,
        ProductionEvent,
        SoilManagementEvent,
        PestManagementEvent,
        GeneralEvent,
        WeatherEvent,
        BusinessEvent,
        EquipmentEvent,
    )

    # {parcel_id: {casefolded key: {exact spelling: times used}}}
    spellings: dict = {pid: {} for pid in ids}
    for model in models:
        rows = (
            model.objects.filter(history__parcel_id__in=ids)
            .exclude(block_id__isnull=True)
            .exclude(block_id="")
            .values("history__parcel_id", "block_id")
            .annotate(uses=Count("id"))
        )
        for row in rows:
            normalized = normalize_block_id(row["block_id"])
            if not normalized:
                continue
            bucket = spellings[row["history__parcel_id"]].setdefault(normalized.casefold(), {})
            bucket[normalized] = bucket.get(normalized, 0) + row["uses"]

    for pid, keyed in spellings.items():
        # Most-used spelling wins; alphabetical tie-break keeps the result deterministic.
        winners = [max(sorted(bucket), key=lambda s: bucket[s]) for bucket in keyed.values()]
        result[pid] = sorted(winners, key=str.casefold)
    return result
