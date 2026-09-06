"""
A fingerprint of everything the operation dossier reads.

Why: the certifier review link regenerated the whole operation dossier on every open so the
reviewer always saw current records. On a 12-production farm that is ~15 s of CPU locally and
about a minute in production (2026-09-05 measurement), for a document that has not changed
since the last open. The honest alternative is not "cache for an hour" — a certifier who opens
the link after the grower's correction must see the correction — but "rebuild when the records
changed, and only then". This module answers "have they?" in ~25 cheap queries.

What it hashes, per establishment: the farm and parcel rows themselves, the productions, every
event model's row count plus the newest audit-log entry against its rows (auditlog is registered
for all eight event models and for History, so a create OR an edit moves the timestamp; a delete
moves the count), the photos attached to those events, the plan layer (OSP versions, approved
input change log, plan materials, annual updates, change notifications), the certification and
registration records, farmer uploads, documented corrections and sales records.

What it is NOT: a proof of identity of the rendered bytes. Two builds from the same fingerprint
can differ in the "Generated" date on the cover and nothing else. Callers key the cached build
on (fingerprint, kind, certification type, window) — see `documents/services/export_jobs.py`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Max, Q

from history.models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    EventAmendment,
    GeneralEvent,
    History,
    PestManagementEvent,
    ProductionEvent,
    SalesRecord,
    SoilManagementEvent,
    WeatherEvent,
)

EVENT_MODELS = (
    ProductionEvent,
    ChemicalEvent,
    SoilManagementEvent,
    PestManagementEvent,
    BusinessEvent,
    WeatherEvent,
    GeneralEvent,
    EquipmentEvent,
)


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, memoryview)):
        return hashlib.sha256(bytes(value)).hexdigest()
    return str(value) if not isinstance(value, (int, float, bool, type(None), str, list, dict)) else value


def _rows(queryset):
    """Full rows of a SMALL table, in a stable order, JSON-safe. For models with no
    `updated_at` and no audit log (the farm, its parcels, sales records) the row content is
    the only honest signal of change."""
    return [{k: _jsonable(v) for k, v in row.items()} for row in queryset.order_by("pk").values()]


def _count_and_max(queryset, field):
    agg = queryset.aggregate(n=Count("pk"), latest=Max(field))
    return [agg["n"], _jsonable(agg["latest"])]


def records_fingerprint_signals(establishment) -> dict:
    """The raw signals, keyed by name — exposed so a test can show WHICH one moved."""
    from auditlog.models import LogEntry

    from certifications.models import (
        AdjoiningLandAffidavit,
        ApprovedInputChangeLog,
        Certification,
        LandownerAffidavit,
        OrganicSystemPlan,
        OSPAnnualUpdate,
        OSPChangeNotification,
        PlanMaterialEntry,
        PostHarvestFacility,
        StateOrganicRegistration,
    )
    from common.models import GalleryImage
    from company.models import Establishment
    from documents.models import GeneratedDocument
    from product.models import Parcel

    est_id = establishment.pk
    signals = {
        "establishment": _rows(Establishment.objects.filter(pk=est_id)),
        "parcels": _rows(Parcel.objects.filter(establishment_id=est_id)),
        "productions": _count_and_max(History.objects.filter(parcel__establishment_id=est_id), "updated_at"),
    }

    content_types = ContentType.objects.get_for_models(History, *EVENT_MODELS)
    album_filter = Q()
    for model in EVENT_MODELS:
        rows = model.objects.filter(history__parcel__establishment_id=est_id)
        # `count` catches a delete (the audit row survives but the object is gone from the
        # subquery below); the newest audit entry catches a create or an edit.
        latest_log = LogEntry.objects.filter(
            content_type=content_types[model], object_id__in=rows.values("pk")
        ).aggregate(latest=Max("timestamp"))["latest"]
        signals[f"events.{model.__name__}"] = [rows.count(), _jsonable(latest_log)]
        album_filter |= Q(gallery_id__in=rows.exclude(album__isnull=True).values("album_id"))
    signals["production_log"] = _jsonable(
        LogEntry.objects.filter(
            content_type=content_types[History],
            object_id__in=History.objects.filter(parcel__establishment_id=est_id).values("pk"),
        ).aggregate(latest=Max("timestamp"))["latest"]
    )
    signals["photos"] = _count_and_max(GalleryImage.objects.filter(album_filter), "updated_at")

    plans = OrganicSystemPlan.objects.filter(establishment_id=est_id)
    signals["osp"] = _count_and_max(plans, "updated_at")
    signals["osp_input_changes"] = _count_and_max(
        ApprovedInputChangeLog.objects.filter(osp__establishment_id=est_id), "changed_at"
    )
    signals["plan_materials"] = _count_and_max(
        PlanMaterialEntry.objects.filter(osp__establishment_id=est_id), "updated_at"
    )
    signals["annual_updates"] = _count_and_max(
        OSPAnnualUpdate.objects.filter(Q(new_osp__establishment_id=est_id) | Q(prior_osp__establishment_id=est_id)),
        "updated_at",
    )
    signals["change_notifications"] = _count_and_max(
        OSPChangeNotification.objects.filter(osp__establishment_id=est_id), "created_at"
    )
    signals["certifications"] = _count_and_max(Certification.objects.filter(establishment_id=est_id), "updated_at")
    signals["post_harvest_facilities"] = _count_and_max(
        PostHarvestFacility.objects.filter(establishment_id=est_id), "updated_at"
    )
    signals["state_registrations"] = _count_and_max(
        StateOrganicRegistration.objects.filter(establishment_id=est_id), "updated_at"
    )
    signals["landowner_affidavits"] = _count_and_max(
        LandownerAffidavit.objects.filter(parcel__establishment_id=est_id), "updated_at"
    )
    signals["adjoining_land_affidavits"] = _count_and_max(
        AdjoiningLandAffidavit.objects.filter(parcel__establishment_id=est_id), "updated_at"
    )
    signals["uploads"] = _count_and_max(
        GeneratedDocument.objects.filter(establishment_id=est_id, source="upload"), "created_at"
    )
    signals["amendments"] = _count_and_max(
        EventAmendment.objects.filter(history__parcel__establishment_id=est_id), "created_at"
    )
    signals["sales"] = _rows(SalesRecord.objects.filter(production__parcel__establishment_id=est_id))
    return signals


def records_fingerprint(establishment) -> str:
    """sha256 over the signals — stable across processes, changes when the dossier would."""
    payload = json.dumps(records_fingerprint_signals(establishment), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
