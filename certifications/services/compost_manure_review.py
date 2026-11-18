"""G4.1's "none of these are used" set against the soil records (CCOF G4.1 A1, OTCO C4 4.3, WSDA AGR 2121 D 13).

G4.1 can say no compost, manure or animal-based soil input is used two ways: the module's not-applicable attestation
(CCOF A1's "Not applicable, none of these are used") or the "None of these are used" option of `materials_applied`.
Either one stands next to the soil records in the same packet, and an inspector reads both. A record that names
compost or manure, a composting record, a raw-manure interval or application date, or a grazing record says otherwise.
The line names those records with their dates; it does not change the answer, because an old record can predate a
change of practice and only the operator knows which.
"""

from __future__ import annotations

# Words in an amendment's type or product name that put it under G4.1 (§ 205.203(c)). "Worm castings" is vermicompost.
_WORDS = ("compost", "manure", "worm casting")


def _what(event) -> str:
    from history.services.manure_interval import interval_days

    named = (event.amendment_product_name or "").strip() or (event.amendment_type or "").strip()
    if named:
        return named
    if event.type == event.COMPOSTING:
        return "composting record"
    if event.type == event.GRAZING:
        return "grazing record"
    if interval_days(event.manure_harvest_interval) is not None or event.manure_application_date:
        return "raw manure record"
    return "soil record"


def contradicting_records(establishment) -> list:
    """Soil records of this establishment that are G4.1 material: compost, manure, composting or grazing."""
    from history.models import SoilManagementEvent
    from history.services.manure_interval import interval_days

    if establishment is None:
        return []
    out = []
    for event in SoilManagementEvent.objects.filter(history__parcel__establishment=establishment).order_by(
        "date", "pk"
    ):
        words = f"{event.amendment_type or ''} {event.amendment_product_name or ''}".lower()
        if (
            event.type in (SoilManagementEvent.COMPOSTING, SoilManagementEvent.GRAZING)
            or interval_days(event.manure_harvest_interval) is not None
            or event.manure_application_date
            or any(word in words for word in _WORDS)
        ):
            out.append(event)
    return out


def none_used_lines(osp, how: str) -> list[str]:
    """[REVIEW] lines for a G4.1 that says nothing is used while the records name G4.1 material. Empty otherwise.

    `how` is the way the plan says it: "not_applicable" (the module's attestation) or "none" (the option).
    """
    records = contradicting_records(getattr(osp, "establishment", None))
    if not records:
        return []
    said = (
        "G4.1 is marked not applicable"
        if how == "not_applicable"
        else "G4.1 answers that none of these materials are used"
    )
    names = sorted({_what(e) for e in records}, key=str.lower)
    shown = ", ".join(names[:6]) + (f", and {len(names) - 6} more" if len(names) > 6 else "")
    first, last = records[0].date.date().isoformat(), records[-1].date.date().isoformat()
    span = first if first == last else f"{first} to {last}"
    count = len(records)
    return [
        f"[REVIEW] {said}, but {count} soil record{'s' if count != 1 else ''} ({span}) "
        f"name{'' if count != 1 else 's'} compost, manure or grazing: {shown}."
    ]
