"""Free, complete, machine-readable export of an establishment's records.

§ 205.103 records are the FARM's records. Until 2026-08-25 the only exports in
the product were the paid certifier artifacts (packet, dossier, audit PDF), so
a Starter farm had no way to take its own data out — a quiet lock-in that
contradicts the product's record-ownership story, and the first objection of
anyone who watched COG Pro shut down with their records inside.

This export is deliberately NOT gated on any plan and NOT pretty: one ZIP of
plain CSVs, every concrete column of every record family, JSON fields included
verbatim. The certifier-shaped artifacts stay paid; the raw data is the
farmer's.
"""

import csv
import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _model_csv(queryset) -> str:
    model = queryset.model
    fields = [f.name if not f.is_relation else f.attname for f in model._meta.concrete_fields]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(fields)
    for row in queryset.values_list(*[f.attname if hasattr(f, "attname") else f for f in model._meta.concrete_fields]):
        writer.writerow([_cell(v) for v in row])
    return out.getvalue()


def export_establishment_records_zip(establishment) -> bytes:
    """Return ZIP bytes: one CSV per record family plus parcels, productions,
    sales and photo references. Owner-facing raw data; no plan gating."""
    from history.models import (
        BusinessEvent,
        ChemicalEvent,
        GeneralEvent,
        History,
        PestManagementEvent,
        ProductionEvent,
        SalesRecord,
        SoilManagementEvent,
        WeatherEvent,
    )
    from product.models import Parcel

    est_filter = {"history__parcel__establishment": establishment}
    families = {
        "production_events.csv": ProductionEvent.objects.filter(**est_filter),
        "chemical_events.csv": ChemicalEvent.objects.filter(**est_filter),
        "soil_events.csv": SoilManagementEvent.objects.filter(**est_filter),
        "pest_events.csv": PestManagementEvent.objects.filter(**est_filter),
        "weather_events.csv": WeatherEvent.objects.filter(**est_filter),
        "general_events.csv": GeneralEvent.objects.filter(**est_filter),
        "business_events.csv": BusinessEvent.objects.filter(**est_filter),
        "productions.csv": History.objects.filter(parcel__establishment=establishment),
        "sales_records.csv": SalesRecord.objects.filter(production__parcel__establishment=establishment),
        "parcels.csv": Parcel.objects.filter(establishment=establishment),
    }

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, qs in families.items():
            zf.writestr(name, _model_csv(qs.order_by("pk")))

        # Photo references: family, event id, image URL — enough to fetch the
        # farmer's own photos out of their own album storage.
        photo_rows = io.StringIO()
        writer = csv.writer(photo_rows)
        writer.writerow(["event_family", "event_id", "event_date", "image_url", "s3_key"])
        family_models = {
            "production": ProductionEvent,
            "chemical": ChemicalEvent,
            "soil": SoilManagementEvent,
            "pest": PestManagementEvent,
            "weather": WeatherEvent,
            "general": GeneralEvent,
            "business": BusinessEvent,
        }
        for family, model in family_models.items():
            qs = (
                model.objects.filter(**est_filter)
                .exclude(album__isnull=True)
                .select_related("album")
                .prefetch_related("album__images")
            )
            for ev in qs:
                for img in ev.album.images.all():
                    writer.writerow(
                        [
                            family,
                            ev.pk,
                            ev.date.isoformat() if ev.date else "",
                            getattr(img, "image_url", "") or "",
                            getattr(img, "s3_key", "") or "",
                        ]
                    )
        zf.writestr("photos.csv", photo_rows.getvalue())

        zf.writestr(
            "README.txt",
            "Trazo records export\n"
            f"Establishment: {establishment.name} (id {establishment.pk})\n"
            "One CSV per record family. Columns are the raw database fields;\n"
            "JSON columns (extra_data, test_results, ...) hold structured detail.\n"
            "These are your records (7 CFR 205.103) — keep them for at least five years.\n",
        )
    return out.getvalue()
