"""The receipt files behind a record's purchase invoice, wherever they were filed.

A spray or amendment record can hold its receipt two ways: its own `receipt_document` field (set
from the record's form), or a file filed ON the record from the Documents page as a purchase
receipt (`event_type` / `event_id` with `source_kind="receipt"`, what the traceback's "Fix it
here" uploads). Other files on the same link (a soil test's lab report, a photo) are attachments
and never count. Until
2026-10-21 only the traceback read the second, so a receipt filed from a traceback gap closed the
gap there while the record's own Receipt field, the audit export's "[receipt on file]" and the
renewal packet's receipts/ folder all still said there was none.

A seed-sourced production record (planting, transplanting, seed search) names a seed purchase
too: supplier, invoice, lot. It has no receipt field, so its receipt is only ever a file filed on
it. Every certifier asks for seed purchase records (CCOF G3.0, OTCO C3, WSDA 2121-A), and until
2026-10-24 none of those files reached the trace's receipt check, the audit export or the packet.

One activity logged on several parcels is one record per parcel sharing an `application_group`,
and the purchase is a shared field there: one invoice, whatever it was spread over
(`history/services/multi_target.py`). A receipt filed on one record of the group is the receipt
of every record of the group on the same farm. `ReceiptFiles.shared_from` names the parcels it
was actually filed on, so a reader of the other parcels' pages sees where it lives instead of a
file that looks like it was filed twice.

Read-side only. Filing a document never rewrites the record: a closed or filed record's content
is covered by its revision chain, and a receipt is evidence ABOUT the record, not part of it.

Both ways are checked against the record's own farm. `receipt_document` is not trusted on its
own: the create path checks only the company, so a multi-farm company could link another farm's
file (review of back #191), and a packet must never carry another farm's document. A group is
read the same way: only siblings on the target record's own farm, and only files of that farm.
"""

from __future__ import annotations

from collections import defaultdict

from common.field_registry import SEED_SOURCED_SUBTYPES
from history.constants import CHEMICAL_EVENT_TYPE, PRODUCTION_EVENT_TYPE, SOIL_MANAGEMENT_EVENT_TYPE

#: The `GeneratedDocument.source_kind` of a purchase receipt filed on a record. Any other file
#: on the record (a lab report, a photo) is an attachment, not a receipt (review of back #207).
RECEIPT_KIND = "receipt"

#: The record types that carry a purchase invoice. A production record only for the subtypes
#: below; a harvest or an irrigation pass buys nothing.
RECEIPT_EVENT_TYPES = (CHEMICAL_EVENT_TYPE, SOIL_MANAGEMENT_EVENT_TYPE, PRODUCTION_EVENT_TYPE)

#: The production subtypes that name a seed or planting-stock purchase. The same set the form
#: shows the seed purchase fields on, decided once so the filing check, the trace, the audit
#: export and the packet cannot disagree about which records may hold a receipt.
RECEIPT_PRODUCTION_SUBTYPES = tuple(SEED_SOURCED_SUBTYPES)

#: The two record types that also carry a `receipt_document` field.
_FK_EVENT_TYPES = (CHEMICAL_EVENT_TYPE, SOIL_MANAGEMENT_EVENT_TYPE)


class ReceiptFiles(dict):
    """`{(event_type, event_id): [GeneratedDocument, ...]}`, plus where shared receipts live.

    `shared_from[key]` is the sorted parcel names of the OTHER records of the key's group that its
    receipt was filed on. Absent when every receipt of the record is its own.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shared_from: dict[tuple[int, int], tuple[str, ...]] = {}


def _event_type_of(event) -> int | None:
    from history.models import ChemicalEvent, ProductionEvent, SoilManagementEvent

    if isinstance(event, ChemicalEvent):
        return CHEMICAL_EVENT_TYPE
    if isinstance(event, SoilManagementEvent):
        return SOIL_MANAGEMENT_EVENT_TYPE
    if isinstance(event, ProductionEvent) and event.type in RECEIPT_PRODUCTION_SUBTYPES:
        return PRODUCTION_EVENT_TYPE
    return None


def is_receipt_record(event_type: int | None, event) -> bool:
    """Whether a record of this `EVENT_TYPE_TO_MODEL` key may hold a purchase receipt."""
    return event_type in RECEIPT_EVENT_TYPES and _event_type_of(event) == event_type


def _models():
    from history.models import ChemicalEvent, ProductionEvent, SoilManagementEvent

    return {
        CHEMICAL_EVENT_TYPE: ChemicalEvent,
        SOIL_MANAGEMENT_EVENT_TYPE: SoilManagementEvent,
        PRODUCTION_EVENT_TYPE: ProductionEvent,
    }


def _columns(event_type: int) -> list[str]:
    columns = ["pk", "history__parcel__establishment_id", "application_group", "history__parcel__name"]
    if event_type in _FK_EVENT_TYPES:
        columns.append("receipt_document_id")
    return columns


def receipt_files(events) -> ReceiptFiles:
    """The receipt files of the receipt-bearing records given, keyed `(event_type, event_id)`.

    Per record: its own `receipt_document` first, then files filed on it or on a record of its
    group, oldest first, each once. Records with no receipt are absent. One query per record type
    given, one more per type whose records belong to a group, then one for the documents.
    """
    from django.db.models import Q

    from documents.models import GeneratedDocument

    by_type: dict[int, list] = defaultdict(list)
    for ev in events:
        event_type = _event_type_of(ev)
        if event_type is not None and ev.pk is not None:
            by_type[event_type].append(ev)
    if not by_type:
        return ReceiptFiles()

    models = _models()
    # (event_type, pk) -> (farm, group, parcel name, receipt_document_id)
    record: dict[tuple[int, int], tuple] = {}
    for event_type, evs in by_type.items():
        for row in models[event_type].objects.filter(pk__in=[e.pk for e in evs]).values_list(*_columns(event_type)):
            pk, farm, group, parcel, *fk = row
            if farm is not None:
                record[(event_type, pk)] = (farm, group, parcel, fk[0] if fk else None)
    if not record:
        return ReceiptFiles()

    # The other records of each group, on the target record's farm only. A group is single-farm
    # when it is created, but the farm is compared anyway: a packet never borrows another farm's
    # file, whatever a future write path lets into a group.
    members: dict[tuple[int, object, int], list[tuple[int, int]]] = defaultdict(list)
    for (event_type, pk), (farm, group, _parcel, _fk) in record.items():
        if group is not None:
            members.setdefault((event_type, group, farm), [])
    for event_type in by_type:
        groups = {g for (t, g, _f) in members if t == event_type}
        if not groups:
            continue
        siblings = models[event_type].objects.filter(application_group__in=groups)
        if event_type == PRODUCTION_EVENT_TYPE:
            siblings = siblings.filter(type__in=RECEIPT_PRODUCTION_SUBTYPES)
        for row in siblings.values_list(*_columns(event_type)):
            pk, farm, group, parcel, *fk = row
            if (event_type, group, farm) in members:
                members[(event_type, group, farm)].append((event_type, pk))
                record.setdefault((event_type, pk), (farm, group, parcel, fk[0] if fk else None))

    def _group_of(key):
        farm, group, _parcel, _fk = record[key]
        return members.get((key[0], group, farm)) or [key]

    wanted_fks = {fk for (_f, _g, _p, fk) in record.values() if fk is not None}
    wanted = Q(pk__in=wanted_fks)
    for event_type in by_type:
        ids = [pk for (t, pk) in record if t == event_type]
        if ids:
            wanted |= Q(event_type=event_type, event_id__in=ids, source_kind=RECEIPT_KIND)
    docs = list(GeneratedDocument.objects.filter(wanted).order_by("created_at", "pk"))

    by_pk = {d.pk: d for d in docs}
    filed_on: dict[tuple[int, int], list] = defaultdict(list)
    for d in docs:
        if d.event_type is not None and d.source_kind == RECEIPT_KIND:
            filed_on[(d.event_type, d.event_id)].append(d)

    out = ReceiptFiles()
    for event_type, evs in by_type.items():
        for ev in evs:
            key = (event_type, ev.pk)
            if key not in record:
                continue
            farm = record[key][0]
            # Where each file came from: the record itself or another record of its group.
            origin: dict[int, set] = defaultdict(set)
            found = []
            for member in [key, *(m for m in _group_of(key) if m != key)]:
                fk_doc = by_pk.get(record[member][3])
                candidates = ([fk_doc] if fk_doc is not None else []) + filed_on.get(member, [])
                for d in candidates:
                    if d.establishment_id != farm:
                        continue
                    origin[d.pk].add(member)
                    if d not in found:
                        found.append(d)
            if not found:
                continue
            out[key] = found
            shared = {record[m][2] for d in found if key not in origin[d.pk] for m in origin[d.pk] if record[m][2]}
            if shared:
                out.shared_from[key] = tuple(sorted(shared))
    return out


def has_receipt(files: dict, event) -> bool:
    """Whether `event` has a receipt in a `receipt_files(...)` result."""
    return (_event_type_of(event), event.pk) in files


def shared_from(files: dict, event) -> tuple[str, ...]:
    """The parcels whose records `event`'s receipt was filed on, when not on `event` itself."""
    return getattr(files, "shared_from", {}).get((_event_type_of(event), event.pk), ())


def establishment_receipts(establishment) -> list:
    """Every receipt file of the farm's receipt-bearing records, each once, oldest first."""
    from history.models import ChemicalEvent, ProductionEvent, SoilManagementEvent

    events = [
        *ChemicalEvent.objects.filter(history__parcel__establishment=establishment).only("pk"),
        *SoilManagementEvent.objects.filter(history__parcel__establishment=establishment).only("pk"),
        *ProductionEvent.objects.filter(
            history__parcel__establishment=establishment, type__in=RECEIPT_PRODUCTION_SUBTYPES
        ).only("pk", "type"),
    ]
    seen, out = set(), []
    for files in receipt_files(events).values():
        for d in files:
            if d.pk not in seen:
                seen.add(d.pk)
                out.append(d)
    return sorted(out, key=lambda d: (d.created_at, d.pk))
