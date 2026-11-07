"""The operator's lot number key, read as CCOF G8.0 B2's Code / Signifies table.

CCOF asks the lot numbering system "as a Code / Signifies table (example: Lot Number 23123O10 —
Code 23 / 123 / O / 10, Signifies Year 2023 / Julian harvest date / Organic / Parcel ID)". The OSP
schema has no table kind, so G8.0 asks for one part per line ("26 = harvest year"). This module
splits those lines into rows, and names lot numbers that are on the operation's own production
records so a reviewer can read the key against them. Nothing is inferred: Trazo never decides what
a part of someone's lot number means, it only lays out what the operator wrote.
"""

from __future__ import annotations

import re
from typing import Optional

# "=" first: it is what the question asks for. A colon or a spaced dash is accepted because operators
# write keys that way on paper; an unspaced hyphen is not, because it sits inside codes ("26-HFE").
_SEPARATORS = re.compile(r"\s*=\s*|\s*:\s+|\s+[-–—]\s+")


def key_rows(answer) -> Optional[list]:
    """`[(code, signifies), ...]` when every non-blank line splits once into two non-empty parts.

    None otherwise: a key that does not read as a table is printed as the operator wrote it, never
    half as a table.
    """
    if not isinstance(answer, str):
        return None
    rows = []
    for line in answer.splitlines():
        line = line.strip().lstrip("-*• ").strip()
        if not line:
            continue
        parts = _SEPARATORS.split(line, maxsplit=1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            return None
        rows.append((parts[0].strip(), parts[1].strip()))
    return rows or None


def recorded_lot_ids(establishment, limit: int = 3) -> list:
    """Distinct lot numbers on the operation's production records, most recently finished first."""
    from django.db.models import F

    from history.models import History

    seen, out = set(), []
    qs = (
        History.objects.filter(parcel__establishment=establishment)
        .exclude(lot_id__isnull=True)
        .exclude(lot_id="")
        .order_by(F("finish_date").desc(nulls_last=True), "-pk")
        .values_list("lot_id", flat=True)
    )
    for lot in qs:
        lot = lot.strip()
        if lot and lot not in seen:
            seen.add(lot)
            out.append(lot)
            if len(out) >= limit:
                break
    return out
