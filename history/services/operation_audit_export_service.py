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
import logging
from collections import OrderedDict
from datetime import date

from django.db.models import Q

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

from common.pdf_text import glyph_safe
from common.specimen import is_specimen, specimen_page_callback
from history.services.audit_export_service import production_period, records_span_line

from .audit_export_service import AuditExportService, OutlinedHeading, _add_page_number, _fmt_generated_date, _val

logger = logging.getLogger(__name__)


def _esc(text):
    """Escape XML specials for ReportLab Paragraph (section headers embed user data)."""
    return glyph_safe(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
        # The DMS is farm-scoped, so the document index belongs here — per-production it would
        # repeat the farm's whole shelf once per season. `documents_scope` below widens the
        # builder to list every upload, each labelled with the production it belongs to.
        "attached_documents",
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
        # Photo bytes, shared by every production's service across BOTH render passes (review of
        # #122). Each pass used to fetch independently, so a photo that loaded in one pass and
        # failed in the other changed a production's height and moved every page number after it.
        self._image_cache = {}

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
        qs = qs.filter(self.window_q(self.start_date, self.end_date))
        return list(qs.order_by("parcel__name", "-start_date"))

    @staticmethod
    def window_q(start_date, end_date, prefix=""):
        """The dossier's window, as a Q on a production (or on `<prefix>` pointing at one).

        Window = production active during [start, end]: it must not finish before the window
        opens (finish_date >= start, or still open) and must not start after the window closes.
        Shared with the certifier link's traceback, so the page traces exactly the seasons this
        dossier covers, and their sales whatever the sale's own date (a storage sale lands after
        the season finishes).
        """
        q = Q()
        if start_date:
            q &= Q(**{f"{prefix}finish_date__gte": start_date}) | Q(**{f"{prefix}finish_date__isnull": True})
        if end_date:
            q &= Q(**{f"{prefix}start_date__lte": end_date})
        return q

    def _group_by_parcel(self, productions):
        grouped = OrderedDict()
        for p in productions:
            key = p.parcel_id
            if key not in grouped:
                grouped[key] = (p.parcel, [])
            grouped[key][1].append(p)
        return grouped

    # ------------------------------------------------------------------

    #: Rows the certifier page lists as findings. The other statuses (NA, INFO, NOT ASSESSED)
    #: are facts about scope, not findings: the page folds them behind a toggle (recordkeeping
    #: review S9, F-16: 25 "Not assessed" rows sat among 19 findings).
    CERTIFIER_FINDING_STATUSES = frozenset({"REVIEW", "FAIL"})

    #: Grower-facing imperatives that the certifier page must not print as if addressed to the
    #: reviewer (F-16: "Add buyer + organic-on-invoice flag", "fill before audit"). Each entry
    #: is (pattern, replacement); the fact is kept, the instruction goes. The farmer's card keeps
    #: the original wording: it is the one the instruction is for.
    #: Review of back #137: a literal denylist missed "fill before inspection", "finish corrective
    #: action + notify certifier", "link the covering EM cleaning event", "add before inspection.
    #: Pathway: …" and more. The rule is the SHAPE: a dash followed by an imperative verb starts
    #: a grower instruction, which runs to the end of its sentence; what follows ("Pathway: …")
    #: is fact and stays.
    _IMPERATIVE_VERBS = (
        "fill|add|review|link|update|finish|classify|confirm|see|notify|remove|complete|upload|record|"
        "attach|enter|log|mark|set|check|resolve|reconcile|document|declare|name|start|file"
    )
    CERTIFIER_DETAIL_REWRITES = (
        (r"^Add buyer \+ organic-on-invoice flag$", "No sales record carries a buyer and the organic-on-invoice flag"),
        (r"\s*[—–-]\s*(?:" + _IMPERATIVE_VERBS + r")\b[^.;]*(?:[.;]\s*|$)", " "),
    )

    @classmethod
    def certifier_detail(cls, detail: str) -> str:
        import re

        text = (detail or "").strip()
        for pattern, replacement in cls.CERTIFIER_DETAIL_REWRITES:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        text = re.sub(r"\s{2,}", " ", text).strip(" ;,")
        return text or (detail or "")

    def readiness_rows_for_certifier(self):
        """`readiness_rows()` split for the certifier page: `findings` (REVIEW / FAIL, in the
        certifier's wording) and `not_assessed` (the rest, label and status only)."""
        out = []
        for entry in self.readiness_rows():
            findings, rest = [], []
            for row in entry["findings"]:
                if row["status"] in self.CERTIFIER_FINDING_STATUSES:
                    # Named fields, never the whole row: `detail_code` and `params` say the
                    # GROWER's sentence ("Add the missing suppliers before the audit"), the one
                    # `certifier_detail` exists to keep off this page (review of back #144).
                    findings.append(
                        {
                            "label": row["label"],
                            "row_key": row.get("row_key"),
                            "status": row["status"],
                            "detail": self.certifier_detail(row.get("detail", "")),
                            "section_hint": row.get("section_hint"),
                        }
                    )
                else:
                    # An INFO row can carry a disclosure the certifier wants ("self-reported, no
                    # USDA OID match on file"; review of back #137): the detail stays, in the
                    # certifier's words; only the grower-facing section hint is dropped.
                    rest.append(
                        {
                            "label": row["label"],
                            "row_key": row.get("row_key"),
                            "status": row["status"],
                            "detail": self.certifier_detail(row.get("detail", "")),
                        }
                    )
            out.append({**entry, "findings": findings, "not_assessed": rest})
        return out

    def readiness_rows(self):
        """Per-production compliance snapshot across this operation's whole window.

        Added 2026-08-04 for the certifier review page: the token link is operation + date-range
        scoped (this class's own reason to exist), but the actual CFR-cited checks — including
        `AuditExportService.compliance_snapshot_rows()`'s newest row, per-event record
        completeness — only exist per production. This walks the same production set the PDF
        dossier already covers (`_productions()`, so the page and the PDF can never disagree
        about what is in scope) and runs each one through the single existing snapshot method
        rather than re-implementing any check.

        Returns a list of `{production_id, production_name, finish_date, findings}`, one entry
        per production, `findings` already filtered to non-PASS (same convention as
        `company/views.py::certifier_readiness`).
        """
        from .audit_export_service import AuditExportService

        rows = []
        for production in self._productions():
            service = AuditExportService(production, certification_type=self.certification_type)
            findings = [r for r in service.compliance_snapshot_rows() if r["status"] != "PASS"]
            rows.append(
                {
                    "production_id": production.id,
                    "production_name": production.name,
                    "finish_date": production.finish_date,
                    "findings": findings,
                }
            )
        return rows

    # ------------------------------------------------------------------

    def generate_pdf(self, progress=None):
        """Build the operation dossier, with its Contents numbered (run 8, R8-28).

        The Contents table names each production's page, which is only known once the pages
        are laid out. The first pass lays the dossier out and records where each production
        heading lands; the second prints those numbers. The page numbers cannot move between
        the passes: the number column is the same width either way, and both passes embed the
        same photos because they share one fetch cache (`self._image_cache`).
        """
        _first, pages = self._render(progress=None, page_numbers=None)
        buffer, _ = self._render(progress=progress, page_numbers=pages)
        return buffer

    def _render(self, progress=None, page_numbers=None):
        """Build the dossier. `progress(current, total, label)`, when given, is called before
        the operation-wide sections and before each production so a background job can show
        "Production 4 of 12" instead of a spinner (documents/services/export_jobs.py)."""
        productions = self._productions()
        by_parcel = self._group_by_parcel(productions)
        total = len(productions)

        def _report(current, label):
            if progress is not None:
                progress(current, total, label)

        _report(0, "Operation-wide records")

        # One instance drives styles + header helpers + the reusable builder map. It constructs
        # fine with a None production (AuditExportService.__init__ only touches the production
        # inside the section builders, which we don't call in the no-productions branch), so the
        # empty-operation case still yields a cover-only PDF rather than a hard error.
        header_svc = AuditExportService(productions[0] if productions else None, self.certification_type)
        styles = header_svc._styles

        production_pages = {}
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
        # Submission-readiness banner FIRST, above the cover.
        #
        # The per-production AuditExportService already refuses to emit (and stamps
        # a red DO-NOT-SUBMIT banner) when the OFPP is missing. This service builds
        # its own cover and never ran that gate — so the one export that goes
        # straight to a certifier, via a share link, was the only one with no
        # guardrail. A farmer could hand their reviewer a dossier that SOE 2024
        # forbids certifying, and neither party would be told.
        story += self._build_readiness_banner(styles)
        story += self._build_operation_cover(styles, productions, by_parcel, page_numbers)
        story.append(PageBreak())

        if not productions:
            story.append(
                Paragraph(
                    "No productions were found for this operation in the selected window. "
                    "Log at least one production to generate a records dossier.",
                    styles["body"],
                )
            )
            _furniture = specimen_page_callback(
                letter, base_callback=_add_page_number, specimen=is_specimen(self.establishment)
            )
            doc.build(story, onFirstPage=_furniture, onLaterPages=_furniture)
            buffer.seek(0)
            return buffer, production_pages

        cert_sections = AuditExportService.CERTIFICATION_SECTIONS.get(
            self.certification_type, AuditExportService.CERTIFICATION_SECTIONS["all"]
        )
        est_keys = [k for k in cert_sections if k in self.ESTABLISHMENT_LEVEL]
        parcel_keys = [k for k in cert_sections if k in self.PARCEL_LEVEL]
        prod_keys = [k for k in cert_sections if k not in self.ESTABLISHMENT_LEVEL and k not in self.PARCEL_LEVEL]

        # --- Operation-wide sections (once) ---
        story.append(header_svc._section_header("Operation-Wide Records", level=0))
        header_svc.outline_level = 1
        # The document index is farm-scoped here, not lot-scoped: this dossier covers the whole
        # operation, so a certifier reading it should see every uploaded record once.
        header_svc.documents_scope = "establishment"
        # Operation-wide sections that read production-scoped records (the FSMA § 112.161(b)
        # sign-off table, SOE contamination incidents, lot / retention / sales status) would
        # otherwise describe `productions[0]` only — see AuditExportService._scope_productions.
        header_svc.scope_productions = list(productions)
        est_builders = header_svc._section_builders()
        for k in est_keys:
            story += est_builders[k]()

        # --- Per parcel ---
        built = 0
        for parcel, prods in by_parcel.values():
            story.append(PageBreak())
            story.append(header_svc._section_header(f"Parcel — {_esc(_val(getattr(parcel, 'name', None)))}", level=0))
            parcel_svc = AuditExportService(prods[0], self.certification_type)
            parcel_svc.outline_level = 1
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
                built += 1
                _report(built, f"{crop or prod.name or 'Production'} — {_val(getattr(parcel, 'name', None))}")
                span = production_period(prod, joiner=" – ")
                title = f"Production — {_esc(crop)} ({span})"
                story.append(
                    OutlinedHeading(
                        title,
                        header_svc._styles["section_header"],
                        level=1,
                        on_page=lambda n, pid=prod.pk: production_pages.setdefault(pid, n),
                    )
                )
                # Same disclosure the per-production cover carries: the declared cycle is the
                # headline, and when the records reach outside it the span is printed beside it.
                span_line = records_span_line(prod)
                if span_line:
                    story.append(Paragraph(_esc(span_line), header_svc._styles["footer_note"]))
                prod_svc = AuditExportService(prod, self.certification_type)
                prod_svc._image_cache = self._image_cache
                prod_svc.outline_level = 2
                # Run 7 (R7-09): the per-production compliance snapshot (compost pathway, manure
                # interval, ...) was printed on the production export and served to the review
                # page, but never in this dossier. Same rows from the same method, so the three
                # cannot disagree.
                story += prod_svc._build_compliance_snapshot()
                prod_builders = prod_svc._section_builders()
                for k in prod_keys:
                    story += prod_builders[k]()

        _report(total, "Laying out pages")
        _furniture = specimen_page_callback(
            letter, base_callback=_add_page_number, specimen=is_specimen(self.establishment)
        )
        doc.build(story, onFirstPage=_furniture, onLaterPages=_furniture)
        buffer.seek(0)
        return buffer, production_pages

    # ------------------------------------------------------------------

    def _build_readiness_banner(self, styles):
        """Red draft banner listing the open documentation gaps. Empty when there are none.

        Deliberately renders for the certifier too, not just the farmer: a reviewer
        who receives a blocked dossier should see WHY at the top rather than work it
        out from a missing section thirty pages in.
        """
        from .operation_readiness_service import OperationReadinessService

        try:
            readiness = OperationReadinessService(self.establishment, self.certification_type).evaluate()
        except Exception:  # noqa: BLE001 — never fail the export over the banner
            logger.exception("Readiness evaluation failed for establishment %s", self.establishment.id)
            return []

        if readiness["ready"]:
            return []

        banner_style = ParagraphStyle(
            "operation_draft_gaps_banner",
            parent=styles["body"],
            fontSize=11,
            fontName="Helvetica-Bold",
            textColor=colors.white,
            backColor=colors.HexColor("#B71C1C"),
            alignment=TA_CENTER,
            leading=14,
            borderPadding=8,
            spaceBefore=4,
            spaceAfter=8,
        )
        reasons = "; ".join(b["title"] for b in readiness["blockers"])
        return [
            Paragraph(
                # A documentation finding, never a compliance verdict: the certifying agent
                # decides compliance (pilot rehearsal 2026-10-17).
                f"[DRAFT: documentation gaps listed] {reasons}. "
                "Resolve these before handing this PDF to a reviewer; the certifying agent "
                "makes the compliance decision.",
                banner_style,
            )
        ]

    def _build_operation_cover(self, styles, productions, by_parcel, page_numbers=None):
        elements = []
        elements.append(Paragraph(f"Operation Audit Report — {_esc(self.establishment.name)}", styles["title"]))
        elements.append(Paragraph("Whole-operation NOP records dossier", styles["subtitle"]))

        # 🔴 2026-09-24 — the window SELECTS productions; it does not slice their records.
        #
        # A production overlapping the window is rendered whole, including sales dated outside
        # it, which is what makes the yield-to-sales reconciliation inside correct. But a cover
        # stamped "Audit Window: 2025-01-01 to 2025-12-31" invites a reader to treat everything
        # under it as a period statement, and the reconciliation section was until today called
        # "Mass-Balance" with a line reading "Net inventory reconciliation". Say which it is.
        window = "All productions"
        if self.start_date or self.end_date:
            window = (
                f"{self.start_date or '…'} to {self.end_date or '…'} — selects which "
                "productions appear; each is reported in full, including records dated "
                "outside the window. Not a period inventory statement."
            )
        cert_label = AuditExportService.CERTIFICATION_LABELS.get(
            self.certification_type, self.certification_type.upper()
        )
        meta_rows = [
            ["Generated", _fmt_generated_date()],
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
            index_rows = [["Parcel", "Crop", "Production Window", "Lot ID", "Page"]]
            for parcel, prods in by_parcel.values():
                for prod in prods:
                    try:
                        crop = prod.crop_type.name if prod.crop_type else (prod.product.name if prod.product else "")
                    except AttributeError:
                        crop = ""
                    span = production_period(prod, joiner=" – ", compact=True)
                    page = (page_numbers or {}).get(prod.pk)
                    index_rows.append(
                        [
                            _val(getattr(parcel, "name", None)),
                            _val(crop),
                            span,
                            _val(getattr(prod, "lot_id", None)),
                            str(page) if page else "\u2014",
                        ]
                    )
            index = Table(
                index_rows, colWidths=[1.6 * inch, 1.4 * inch, 2.0 * inch, 1.1 * inch, 0.5 * inch], repeatRows=1
            )
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
