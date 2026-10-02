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

from common.specimen import SPECIMEN_LINE, is_specimen


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


def _model_csv(queryset, specimen: bool = False, exclude: tuple = ()) -> str:
    """One record family as CSV, marked when the operation is fabricated.

    🔴 2026-08-29 — this export shipped on 2026-08-25, four days AFTER the specimen-marking
    work that put one authority (`common.specimen`) behind every artifact leaving the product,
    and it was never wired to it. So a demo operation's complete records ZIP was
    indistinguishable from a real farm's — the exact defect that work exists to prevent, arriving
    through a door built after the fix. Caught by its own guard,
    `test_every_export_surface_consults_the_authority`.

    Marked the way the PUR and audit CSVs already do it: `SPECIMEN_LINE` as the first row, so it
    survives being opened in a spreadsheet rather than living in metadata nobody reads.
    """
    model = queryset.model
    concrete = [f for f in model._meta.concrete_fields if f.name not in exclude]
    fields = [f.name if not f.is_relation else f.attname for f in concrete]
    out = io.StringIO()
    writer = csv.writer(out)
    if specimen:
        writer.writerow([SPECIMEN_LINE])
    writer.writerow(fields)
    for row in queryset.values_list(*[f.attname if hasattr(f, "attname") else f for f in concrete]):
        writer.writerow([_cell(v) for v in row])
    return out.getvalue()


def export_establishment_records_zip(establishment) -> bytes:
    """Return ZIP bytes: one CSV per record family plus parcels, productions,
    sales and photo references. Owner-facing raw data; no plan gating."""
    from carbon.models import CarbonEntry
    from fieldnotes.models import FieldNote, FieldNoteConfirmation
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
        # Carbon entries are DERIVED records about this farm, and they belong to the farm.
        #
        # Added 2026-08-29, when removing the multi-standard export picker made carbon
        # unreachable from every export at once: it had only ever ridden along in the `all`,
        # `roc` and `scs` variants, which are gone because they carried it into a CERTIFIER
        # document — inspectors do not grade on emissions and putting them in an audit PDF is a
        # greenwashing-by-association risk. Keeping it out of the certifier packet is right;
        # letting it become unexportable was not, and contradicts this product's own stated
        # position that records "should never be trapped in any tool, including this one".
        #
        # This is the FREE, ungated door, which is where a farmer's own data belongs.
        "carbon_entries.csv": CarbonEntry.objects.filter(establishment=establishment),
        # Crew messages and their confirmation history (OSP alignment audit T29): the export has to
        # reproduce where a record came from, not only the record. The sender's full number and the
        # provider's media reference stay out (the confirmation rows carry the last four digits).
        "crew_messages.csv": (
            FieldNote.objects.filter(establishment=establishment),
            ("sender_phone", "provider_media_ref"),
        ),
        "crew_message_confirmations.csv": FieldNoteConfirmation.objects.filter(note__establishment=establishment),
    }

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        # `Establishment.is_demo` decides, in one place, for every family in the ZIP. Its default
        # of False is load-bearing: marking a REAL farm's export invites a certifier to reject it.
        specimen = is_specimen(establishment)
        for name, qs in families.items():
            exclude = ()
            if isinstance(qs, tuple):
                qs, exclude = qs
            zf.writestr(name, _model_csv(qs.order_by("pk"), specimen=specimen, exclude=exclude))

        # Photo references: family, event id, image URL — enough to fetch the
        # farmer's own photos out of their own album storage.
        photo_rows = io.StringIO()
        writer = csv.writer(photo_rows)
        # photos.csv is hand-built rather than going through `_model_csv`, so it needs the mark
        # applied explicitly — a per-file marking scheme is only as good as its least-visited path.
        if specimen:
            writer.writerow([SPECIMEN_LINE])
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

        # The README is the first file anyone opens, so it carries the mark FIRST — before the
        # establishment name, which is the line that would otherwise make fabricated records read
        # as a real farm's.
        zf.writestr(
            "README.txt",
            (f"{SPECIMEN_LINE}\n\n" if specimen else "")
            + "Trazo records export\n"
            + f"Establishment: {establishment.name} (id {establishment.pk})\n"
            + "One CSV per record family. Columns are the raw database fields;\n"
            + "JSON columns (extra_data, test_results, ...) hold structured detail.\n"
            + "These are your records (7 CFR 205.103) — keep them for at least five years.\n",
        )
    return out.getvalue()
