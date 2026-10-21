"""The receipt files behind an input record's purchase invoice, wherever they were filed.

A spray or amendment record can hold its receipt two ways: its own `receipt_document` field (set
from the record's form), or a file filed ON the record from the Documents page
(`GeneratedDocument.event_type` / `event_id`, what the traceback's "Fix it here" uploads). Until
2026-10-21 only the traceback read the second, so a receipt filed from a traceback gap closed the
gap there while the record's own Receipt field, the audit export's "[receipt on file]" and the
renewal packet's receipts/ folder all still said there was none.

Read-side only. Filing a document never rewrites the record: a closed or filed record's content
is covered by its revision chain, and a receipt is evidence ABOUT the record, not part of it.

Both ways are checked against the record's own farm. `receipt_document` is not trusted on its
own: the create path checks only the company, so a multi-farm company could link another farm's
file (review of back #191), and a packet must never carry another farm's document.
"""

from __future__ import annotations

from collections import defaultdict

from history.constants import CHEMICAL_EVENT_TYPE, SOIL_MANAGEMENT_EVENT_TYPE

#: The two record types that carry a purchase invoice and a receipt field.
RECEIPT_EVENT_TYPES = (CHEMICAL_EVENT_TYPE, SOIL_MANAGEMENT_EVENT_TYPE)


def _event_type_of(event) -> int | None:
    from history.models import ChemicalEvent, SoilManagementEvent

    if isinstance(event, ChemicalEvent):
        return CHEMICAL_EVENT_TYPE
    if isinstance(event, SoilManagementEvent):
        return SOIL_MANAGEMENT_EVENT_TYPE
    return None


def receipt_files(events) -> dict[tuple[int, int], list]:
    """`{(event_type, event_id): [GeneratedDocument, ...]}` for the receipt-bearing records given.

    The record's own `receipt_document` first, then files filed on the record, oldest first, each
    once. Records with no receipt are absent from the dict. Two queries for any number of records:
    the records' farms, then the documents.
    """
    from django.db.models import Q

    from documents.models import GeneratedDocument
    from history.models import ChemicalEvent, SoilManagementEvent

    by_type: dict[int, list] = defaultdict(list)
    for ev in events:
        event_type = _event_type_of(ev)
        if event_type is not None and ev.pk is not None:
            by_type[event_type].append(ev)
    if not by_type:
        return {}

    models = {CHEMICAL_EVENT_TYPE: ChemicalEvent, SOIL_MANAGEMENT_EVENT_TYPE: SoilManagementEvent}
    farm_of: dict[tuple[int, int], int] = {}
    fk_of: dict[tuple[int, int], int] = {}
    for event_type, evs in by_type.items():
        rows = (
            models[event_type]
            .objects.filter(pk__in=[e.pk for e in evs])
            .values_list("pk", "history__parcel__establishment_id", "receipt_document_id")
        )
        for pk, farm, fk in rows:
            if farm is not None:
                farm_of[(event_type, pk)] = farm
                if fk is not None:
                    fk_of[(event_type, pk)] = fk
    if not farm_of:
        return {}

    wanted = Q(pk__in=set(fk_of.values()))
    for event_type in by_type:
        ids = [pk for (t, pk) in farm_of if t == event_type]
        if ids:
            wanted |= Q(event_type=event_type, event_id__in=ids)
    docs = list(GeneratedDocument.objects.filter(wanted).order_by("created_at", "pk"))

    by_pk = {d.pk: d for d in docs}
    filed_on: dict[tuple[int, int], list] = defaultdict(list)
    for d in docs:
        if d.event_type is not None:
            filed_on[(d.event_type, d.event_id)].append(d)
    out: dict[tuple[int, int], list] = {}
    for key, farm in farm_of.items():
        found = []
        fk_doc = by_pk.get(fk_of.get(key))
        if fk_doc is not None and fk_doc.establishment_id == farm:
            found.append(fk_doc)
        found += [d for d in filed_on.get(key, ()) if d.establishment_id == farm and d not in found]
        if found:
            out[key] = found
    return out


def has_receipt(files: dict, event) -> bool:
    """Whether `event` has a receipt in a `receipt_files(...)` result."""
    return (_event_type_of(event), event.pk) in files


def establishment_receipts(establishment) -> list:
    """Every receipt file of the farm's spray and amendment records, each once, oldest first."""
    from history.models import ChemicalEvent, SoilManagementEvent

    events = [
        *ChemicalEvent.objects.filter(history__parcel__establishment=establishment).only("pk"),
        *SoilManagementEvent.objects.filter(history__parcel__establishment=establishment).only("pk"),
    ]
    seen, out = set(), []
    for files in receipt_files(events).values():
        for d in files:
            if d.pk not in seen:
                seen.add(d.pk)
                out.append(d)
    return sorted(out, key=lambda d: (d.created_at, d.pk))
