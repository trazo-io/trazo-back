"""
Operation-wide NOP audit export.

The per-production ``AuditExportService`` emits one PDF per ``History``. A real CCOF/NOP
inspection covers the WHOLE operation — every parcel × crop in the audit window — so an
establishment with 4 parcels × 2 crops means 8 separate PDFs, each re-embedding the identical
OSP / affidavit / registration / buffer records. This service assembles ONE combined,
indexed dossier:

  * Operation-wide sections (OSP, producer attestation, regulatory scope, farm overview, CDFA
    registration, SOE compliance, certifications) render ONCE.
  * Parcel-level sections (field map, buffer zones, field history) render once per parcel.
  * Production-level sections (events, mass-balance, traceability, photos, …) render per
    production, grouped under their parcel.

It reuses every existing per-production section builder via ``AuditExportService._section_builders()``
— no section logic is duplicated. Photo/OFPP strict gates are OFF here (this is a comprehensive
records bundle); the per-production export remains the strict, single-production submission path.
"""

import io
from collections import OrderedDict
from datetime import date

from django.db.models import Q
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

from .audit_export_service import AuditExportService, _add_page_number, _fmt_date, _val


def _esc(text):
    """Escape XML specials for ReportLab Paragraph (section headers embed user data)."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class OperationAuditExportService:
    # Sections that describe the OPERATION/OSP — identical across every production, render once.
    ESTABLISHMENT_LEVEL = (
        "osp_reference",
        "producer_attestation",
        "regulatory_scope",
        "farm",
        "state_organic_registration",
        "soe_compliance",
        "certifications",
    )
    # Sections that describe a PARCEL — render once per parcel.
    PARCEL_LEVEL = (
        "field_map",
        "buffer_zones",
        "field_history",
    )

    def __init__(self, establishment, certification_type="organic", start_date=None, end_date=None):
        self.establishment = establishment
        self.certification_type = (certification_type or "organic").lower()
        self.start_date = start_date
        self.end_date = end_date

    # ------------------------------------------------------------------

    def _productions(self):
        """All productions across the establishment's parcels, optionally windowed by overlap.

        Prefetches the event managers + photo albums + carbon entries so assembling the combined
        dossier across N productions doesn't N+1 (mirrors the per-production audit-export view).
        """
        from django.db.models import Prefetch

        from carbon.models import CarbonEntry
        from history.models import (
            BusinessEvent,
            ChemicalEvent,
            EquipmentEvent,
            GeneralEvent,
            History,
            PestManagementEvent,
            ProductionEvent,
            SoilManagementEvent,
            WeatherEvent,
        )

        def _ev(name, model):
            return Prefetch(name, queryset=model.objects.select_related("album").prefetch_related("album__images"))

        qs = (
            History.objects.filter(parcel__establishment=self.establishment)
            .select_related("parcel__establishment__company", "product", "crop_type", "operator")
            .prefetch_related(
                _ev("history_weatherevent_events", WeatherEvent),
                _ev("history_chemicalevent_events", ChemicalEvent),
                _ev("history_productionevent_events", ProductionEvent),
                _ev("history_generalevent_events", GeneralEvent),
                _ev("history_equipmentevent_events", EquipmentEvent),
                _ev("history_soilmanagementevent_events", SoilManagementEvent),
                _ev("history_pestmanagementevent_events", PestManagementEvent),
                _ev("history_businessevent_events", BusinessEvent),
                Prefetch(
                    "carbonentry_set", queryset=CarbonEntry.objects.select_related("source").order_by("-timestamp")
                ),
            )
        )
        # Window = production active during [start, end]: it must not finish before the window
        # opens (finish_date >= start, or still open) and must not start after the window closes.
        if self.start_date:
            qs = qs.filter(Q(finish_date__gte=self.start_date) | Q(finish_date__isnull=True))
        if self.end_date:
            qs = qs.filter(start_date__lte=self.end_date)
        return list(qs.order_by("parcel__name", "-start_date"))

    def _group_by_parcel(self, productions):
        grouped = OrderedDict()
        for p in productions:
            key = p.parcel_id
            if key not in grouped:
                grouped[key] = (p.parcel, [])
            grouped[key][1].append(p)
        return grouped

    # ------------------------------------------------------------------

    def generate_pdf(self):
        productions = self._productions()
        by_parcel = self._group_by_parcel(productions)

        # One instance drives styles + header helpers + the reusable builder map. It constructs
        # fine with a None production (AuditExportService.__init__ only touches the production
        # inside the section builders, which we don't call in the no-productions branch), so the
        # empty-operation case still yields a cover-only PDF rather than a hard error.
        header_svc = AuditExportService(productions[0] if productions else None, self.certification_type)
        styles = header_svc._styles

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.9 * inch,
            bottomMargin=0.75 * inch,
            title=f"Trazo Operation Audit Report — {self.establishment.name}",
        )

        story = []
        story += self._build_operation_cover(styles, productions, by_parcel)
        story.append(PageBreak())

        if not productions:
            story.append(
                Paragraph(
                    "No productions were found for this operation in the selected window. "
                    "Log at least one production to generate a records dossier.",
                    styles["body"],
                )
            )
            doc.build(story, onFirstPage=_add_page_number, onLaterPages=_add_page_number)
            buffer.seek(0)
            return buffer

        cert_sections = AuditExportService.CERTIFICATION_SECTIONS.get(
            self.certification_type, AuditExportService.CERTIFICATION_SECTIONS["all"]
        )
        est_keys = [k for k in cert_sections if k in self.ESTABLISHMENT_LEVEL]
        parcel_keys = [k for k in cert_sections if k in self.PARCEL_LEVEL]
        prod_keys = [k for k in cert_sections if k not in self.ESTABLISHMENT_LEVEL and k not in self.PARCEL_LEVEL]

        # --- Operation-wide sections (once) ---
        story.append(header_svc._section_header("Operation-Wide Records"))
        est_builders = header_svc._section_builders()
        for k in est_keys:
            story += est_builders[k]()

        # --- Per parcel ---
        for parcel, prods in by_parcel.values():
            story.append(PageBreak())
            story.append(header_svc._section_header(f"Parcel — {_esc(_val(getattr(parcel, 'name', None)))}"))
            parcel_svc = AuditExportService(prods[0], self.certification_type)
            parcel_builders = parcel_svc._section_builders()
            for k in parcel_keys:
                story += parcel_builders[k]()

            # --- Per production within the parcel ---
            for prod in prods:
                story.append(PageBreak())
                crop = ""
                try:
                    crop = prod.crop_type.name if prod.crop_type else (prod.product.name if prod.product else "")
                except AttributeError:
                    crop = ""
                span = f"{_fmt_date(prod.start_date)} – {_fmt_date(prod.finish_date or prod.expected_harvest)}"
                title = f"Production — {_esc(crop)} ({span})"
                story.append(header_svc._section_header(title))
                prod_svc = AuditExportService(prod, self.certification_type)
                prod_builders = prod_svc._section_builders()
                for k in prod_keys:
                    story += prod_builders[k]()

        doc.build(story, onFirstPage=_add_page_number, onLaterPages=_add_page_number)
        buffer.seek(0)
        return buffer

    # ------------------------------------------------------------------

    def _build_operation_cover(self, styles, productions, by_parcel):
        elements = []
        elements.append(Paragraph(f"Operation Audit Report — {_esc(self.establishment.name)}", styles["title"]))
        elements.append(Paragraph("Whole-operation NOP records dossier", styles["subtitle"]))

        window = "All productions"
        if self.start_date or self.end_date:
            window = f"{self.start_date or '…'} to {self.end_date or '…'}"
        cert_label = AuditExportService.CERTIFICATION_LABELS.get(
            self.certification_type, self.certification_type.upper()
        )
        meta_rows = [
            ["Generated", _fmt_date(date.today())],
            ["Certification Filter", cert_label],
            ["Audit Window", window],
            ["Parcels", str(len(by_parcel))],
            ["Productions", str(len(productions))],
        ]
        meta = Table(meta_rows, colWidths=[2 * inch, 4 * inch])
        meta.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        elements.append(meta)

        if productions:
            elements.append(Paragraph("Contents", styles["section_header"]))
            index_rows = [["Parcel", "Crop", "Production Window", "Lot ID"]]
            for parcel, prods in by_parcel.values():
                for prod in prods:
                    try:
                        crop = prod.crop_type.name if prod.crop_type else (prod.product.name if prod.product else "")
                    except AttributeError:
                        crop = ""
                    span = f"{_fmt_date(prod.start_date)} – {_fmt_date(prod.finish_date or prod.expected_harvest)}"
                    index_rows.append(
                        [_val(getattr(parcel, "name", None)), _val(crop), span, _val(getattr(prod, "lot_id", None))]
                    )
            index = Table(index_rows, colWidths=[1.7 * inch, 1.5 * inch, 2.1 * inch, 1.2 * inch], repeatRows=1)
            index.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F5E9")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            elements.append(index)

        return elements
