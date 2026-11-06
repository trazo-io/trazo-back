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


#: What a carbon row's figure rests on, read from its status. Factor sources are per input
#: class (compliance.md): never a blanket "EPA/USDA".
#: The factor sources, by input class: the one sentence both exports state (the audit PDF in a
#: note under its carbon table, this export on each row).
FACTOR_SOURCES_BY_CLASS = (
    "diesel, petrol, electricity: EPA-published; nitrogen: EPA + IPCC-published; "
    "phosphorus and potassium: Trazo estimate; pesticides and herbicides: academic LCA"
)
_PUBLISHED_FACTOR = f"Published factor applied; source per input class ({FACTOR_SOURCES_BY_CLASS})"
PUBLISHED_FACTOR = _PUBLISHED_FACTOR
PUBLISHED_FACTORS_AGGREGATED = "Published factors applied and aggregated; source per input class"
FACTOR_BASIS = _FACTOR_BASIS = {
    # Every status `event_carbon_calculator` writes for a row with a published factor applied
    # (review of back #132): one wording, the source still per input class.
    "factors_verified": _PUBLISHED_FACTOR,
    "usda_verified": _PUBLISHED_FACTOR,
    "epa_usda_verified": _PUBLISHED_FACTOR,
    "epa_usda_sourced": _PUBLISHED_FACTOR,
    "usda_ipcc_factors_verified": _PUBLISHED_FACTOR,
    "epa_verified": _PUBLISHED_FACTOR,
    "enhanced_factors": _PUBLISHED_FACTOR,
    "verified": _PUBLISHED_FACTOR,
    "verified_zero": "Published factor applied to a recorded quantity of zero",
    "epa_usda_verified_aggregate": PUBLISHED_FACTORS_AGGREGATED,
    "no_factor_applied": "No factor applied",
    "estimated": "Estimated; no published factor applied",
    "area_estimate": "Estimated from the area recorded on the activity (per-hectare factor); no fuel recorded",
    "not_estimated": "Not estimated: no fuel, energy or area recorded",
}


def _factor_basis(status) -> str:
    return _FACTOR_BASIS.get((status or "").strip().lower(), "Factor basis not stated")


def _model_csv(queryset, specimen: bool = False, exclude: tuple = (), extra: tuple = ()) -> str:
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
    # `extra` adds computed columns: (name, function of the row dict) pairs, written after the
    # concrete ones. Used for a carbon row's factor basis, which is a reading of its status
    # rather than a stored field (recordkeeping review F-10, 2026-10-07).
    out = io.StringIO()
    writer = csv.writer(out)
    if specimen:
        writer.writerow([SPECIMEN_LINE])
    writer.writerow(fields + [name for name, _fn in extra])
    attnames = [f.attname if hasattr(f, "attname") else f for f in concrete]
    for row in queryset.values_list(*attnames):
        record = dict(zip(attnames, row))
        writer.writerow([_cell(v) for v in row] + [_cell(fn(record)) for _name, fn in extra])
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
        # `reputation` and `confidence_score` are the retired score (transparency-first.md); they
        # stay in the column until the drop-the-column slice lands and leave this export now
        # (recordkeeping review F-10).
        "productions.csv": (
            History.objects.filter(parcel__establishment=establishment),
            ("reputation", "confidence_score"),
        ),
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
        #
        # Recordkeeping review F-10 (2026-10-07): the row carried the retired carbon-credit
        # vocabulary (`trust_score` 0.5 on every row, `verification_level`, `audit_status`,
        # `additionality_verified`, registry fields) and a blanket `data_source` of "USDA
        # Agricultural Research Service" on all 417 specimen rows, area estimates included. Those
        # columns are out; `factor_basis` says, per row, what its figure rests on.
        "carbon_entries.csv": (
            CarbonEntry.objects.filter(establishment=establishment),
            (
                "trust_score",
                "verification_level",
                "additionality_verified",
                "audit_status",
                "audit_scheduled_date",
                "third_party_verification_url",
                "registry_verification_id",
                "usda_factors_based",
                "data_source",
                "blockchain_verified",
                # Written with blanket claims until 2026-11-05 ("USDA_<CLASS>", "verified farm event
                # data"), never read: existing rows still carry the text, so the columns leave the
                # export. (`explanation_text`, the third, left the model in carbon migration 0048.)
                "methodology_template",
                "permanence_plan",
            ),
            (("factor_basis", lambda record: _factor_basis(record.get("verification_status"))),),
        ),
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
            exclude, extra = (), ()
            if isinstance(qs, tuple):
                qs, exclude, *rest = qs
                extra = rest[0] if rest else ()
            identity = tuple(
                f.name
                for f in qs.model._meta.concrete_fields
                if f.is_relation and f.related_model is not None and f.related_model._meta.label == "history.Activity"
            )
            if identity:
                # Internal identities (history.models.Activity: an event's own, or the record a
                # correction, plan item or crew note points at) are not something the operator
                # recorded: the export stays exactly what it was before the identity table.
                exclude = tuple(exclude) + identity
            zf.writestr(name, _model_csv(qs.order_by("pk"), specimen=specimen, exclude=exclude, extra=extra))

        # Sale-to-harvest links (run 7, R7-08). `_model_csv` writes concrete columns only, so the
        # many-to-many saying which harvest lots a sale came from was lost, and the dossier's
        # "Lot(s)" column could not be reconstructed from this ZIP.
        link_rows = io.StringIO()
        link_writer = csv.writer(link_rows)
        if specimen:
            link_writer.writerow([SPECIMEN_LINE])
        link_writer.writerow(["sale_id", "harvest_event_id", "harvest_lot_code"])
        links = (
            SalesRecord.harvest_events.through.objects.filter(
                salesrecord__production__parcel__establishment=establishment
            )
            .select_related("productionevent")
            .order_by("salesrecord_id", "productionevent_id")
        )
        for link in links:
            link_writer.writerow(
                [link.salesrecord_id, link.productionevent_id, link.productionevent.harvest_lot_code or ""]
            )
        zf.writestr("sale_harvest_links.csv", link_rows.getvalue())

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
            + "These are your records (7 CFR 205.103) — keep them for at least five years.\n"
            + "sale_harvest_links.csv joins sales_records.id to production_events.id (harvest lots).\n"
            + "\nNot in this export (run 7, R7-08); each lives where noted:\n"
            + "- Organic System Plan versions, sections, annual updates and change notifications:\n"
            + "  the OSP renewal packet (filed annual updates as their frozen PDFs).\n"
            + "- The plan's materials list, identity decisions and restriction statements, and the\n"
            + "  OMRI / WSDA / National List rows the material ids above refer to: the OSP packet.\n"
            + "- Post-harvest facilities and certifications: the audit dossier.\n"
            + "- Uploaded documents (receipts, labels, certificates): Documents in the app; the\n"
            + "  *_document_id columns above refer to them.\n"
            + "- Record amendments and the edit history: the audit dossier.\n"
            + "- Equipment events: the audit dossier.\n",
        )
    return out.getvalue()
