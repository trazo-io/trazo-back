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
_SEPARATORS = re.compile(r"\s*=\s*|\s*:\s+|\s+[-\u2013\u2014]\s+")

# A code is a short token ("26", "HFE", "CBF-26", "Julian day"), never a clause. Without this a prose
# answer with an incidental colon ("Lot codes are built like this: farm, year, block") printed one half
# of a sentence under "Code" (review of back #331).
_CODE_MAX_CHARS = 24
_CODE_MAX_SPACES = 2


def _looks_like_code(code: str) -> bool:
    return len(code) <= _CODE_MAX_CHARS and code.count(" ") <= _CODE_MAX_SPACES


def key_rows(answer) -> Optional[list]:
    """`[(code, signifies), ...]` when every non-blank line splits once into a code and its meaning.

    None otherwise: a key that does not read as a table is printed as the operator wrote it, never
    half as a table. A one-line answer reads as a table only when it uses "=", the form the question
    asks for: a lone colon or dash is too often punctuation in a sentence.
    """
    if not isinstance(answer, str):
        return None
    rows, separators = [], []
    for line in answer.splitlines():
        line = line.strip().lstrip("-*\u2022 ").strip()
        if not line:
            continue
        match = _SEPARATORS.search(line)
        if match is None:
            return None
        code, meaning = line[: match.start()].strip(), line[match.end() :].strip()
        if not code or not meaning or not _looks_like_code(code):
            return None
        rows.append((code, meaning))
        separators.append("=" in match.group(0))
    if len(rows) == 1 and not separators[0]:
        return None
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
