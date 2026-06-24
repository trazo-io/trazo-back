"""
Trazo Audit Export Service
Generates PDF and CSV audit-ready reports from production data.

Supports certification-specific filtering for:
  organic, globalgap, roc, fsma204, scs, all
"""

# Defer annotation evaluation (PEP 563) so PEP 604 syntax like `str | None`
# works on Python 3.9. Production runs python:3.9-slim per Dockerfile, where
# `X | None` raises TypeError at class-body execution time without this.
from __future__ import annotations

import csv
import io
import logging
import os
from datetime import date, timedelta

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)

# Trazo brand green
TRAZO_GREEN = colors.HexColor("#4CAF50")
TRAZO_GREEN_DARK = colors.HexColor("#2E7D32")
LIGHT_GRAY = colors.HexColor("#F5F5F5")
MID_GRAY = colors.HexColor("#CCCCCC")
DARK_GRAY = colors.HexColor("#333333")

# Display labels for event type codes
PRODUCTION_TYPE_LABELS = {
    "PL": "Planting",
    "HA": "Harvesting",
    "IR": "Irrigation",
    "PR": "Pruning",
    "TR": "Transplanting",
    "EM": "Equipment Maintenance",
    "CU": "Cultivation",
    "TH": "Thinning",
    "PO": "Pollination",
    "PH": "Post-Harvest Processing",
    "CM": "Canopy Management",
}

CHEMICAL_TYPE_LABELS = {
    "FE": "Fertilizer",
    "PE": "Pesticide",
    "FU": "Fungicide",
    "HE": "Herbicide",
}

SOIL_TYPE_LABELS = {
    "ST": "Soil Test",
    "PA": "pH Adjustment",
    "OM": "Organic Matter Addition",
    "CC": "Cover Crop",
    "TI": "Tillage",
    "CO": "Composting",
    "GR": "Grazing Management",
    "HD": "Habitat Development",
    "NS": "Nesting / Shelter Structures",
}

# Humanize SoilManagementEvent.habitat_type (HD / NS subtypes) for the Biodiversity & Habitat
# Records sub-table. Mirrors the frontend HABITAT_TYPES enum (soilEvent.ts); unknown values fall through.
HABITAT_TYPE_LABELS = {
    # HD — Habitat Development (NRCS conservation practice codes noted for the certifier)
    "hedgerow": "Hedgerow (NRCS 422)",
    "insectary_strip": "Insectary / Beneficial-Insect Strip",
    "native_planting": "Native Planting",
    "pollinator_habitat": "Pollinator Habitat (NRCS 327)",
    "field_border": "Field Border (NRCS 386)",
    "riparian_buffer": "Riparian Buffer (NRCS 391)",
    "living_groundcover_habitat": "Living Groundcover Habitat",
    "wildlife_corridor": "Wildlife Corridor",
    # NS — Nesting / Shelter structures
    "barn_owl_box": "Barn-Owl Box",
    "raptor_perch": "Raptor Perch",
    "songbird_box": "Songbird Box",
    "native_bee_block": "Native-Bee Nest Block",
    "bat_box": "Bat Box",
    "insect_hotel": "Insect Hotel",
    "beetle_bank": "Beetle Bank",
    "brush_pile_hibernacula": "Brush Pile / Hibernacula",
}

# SoilManagementEvent.amendment_type is a free CharField (no model-level choices),
# so get_<field>_display() is unavailable. Mirror the frontend
# AMENDMENT_TYPE_LABELS (soilEvent.ts) so the inspector sees "Quick Lime" instead
# of raw "calcium_oxide". Unknown values fall through to the stored string.
AMENDMENT_TYPE_LABELS = {
    "limestone": "Limestone",
    "dolomite": "Dolomite",
    "calcium_oxide": "Quick Lime",
    "calcium_hydroxide": "Hydrated Lime",
    "gypsum": "Gypsum",
    "compost": "Compost",
    "manure": "Manure",
    "other": "Other Amendment",
}

# Humanize SoilManagementEvent.grazing_purpose for the Grazing Management Records sub-table.
# Mirrors the frontend grazing_purpose choices (soilEvent.ts); unknown values fall through.
GRAZING_PURPOSE_LABELS = {
    "weed_control": "Weed Control",
    "cover_crop": "Cover Crop Termination",
    "soil_health": "Soil Health",
    "vegetation_management": "Vegetation Management",
}


def _amendment_type_label(value, fallback="\u2014"):
    """Humanize amendment_type for PDF/CSV display; fall back to stored value.

    Matches `_val()` semantics: returns the em-dash fallback when the stored
    value is empty/None so CSV cells and PDF cells render consistently.
    Callers inside `_cell()` may override with fallback="" — `_cell()` will
    substitute an em-dash on its own.
    """
    if value is None or value == "":
        return fallback
    return AMENDMENT_TYPE_LABELS.get(value, value)


PEST_TYPE_LABELS = {
    "SC": "Scouting",
    "BR": "Beneficial Release",
    "TM": "Trap Monitoring",
    "PI": "Pest Identification",
    "TA": "Threshold Assessment",
    "IP": "IPM Implementation",
}

EQUIPMENT_TYPE_LABELS = {
    "MN": "Maintenance",
    "RE": "Repair",
    "CA": "Calibration",
    "FC": "Fuel Consumption",
    "BD": "Breakdown",
    "EI": "Inspection",
}

WEATHER_TYPE_LABELS = {
    "FR": "Frost",
    "DR": "Drought",
    "HL": "Hailstorm",
    "HT": "High Temperature",
    "TS": "Tropical Storm",
    "HW": "High Winds",
    "HH": "High Humidity",
    "LH": "Low Humidity",
}


def _fmt_date(dt):
    """Format a datetime or date as YYYY-MM-DD; return dash if None."""
    if dt is None:
        return "\u2014"
    if hasattr(dt, "date"):
        return dt.date().isoformat()
    if isinstance(dt, date):
        return dt.isoformat()
    return str(dt)


def _fmt_float(value, decimals=2):
    """Format a numeric value with fixed decimals; return dash if None."""
    if value is None:
        return "\u2014"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def _val(value, fallback="\u2014"):
    """Return value as string if truthy, else the fallback dash."""
    if value is None or value == "":
        return fallback
    return str(value)


def _truncate(text, max_len=80):
    """Truncate text to max_len characters, appending ellipsis if needed."""
    if text is None:
        return "\u2014"
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "\u2026"


# Minimum narrative length considered "materially complete" for § 205.201(a)
# sections. Used by both the audit PDF snapshot and the OSP serializer's
# registry-sync diff so the inspector-facing banners and the PDF never disagree.
# Research basis: real CCOF / Oregon Tilth OSP templates show per-section
# narratives average 150-500 words; 400 chars (~70 words) is a reasonable floor.
OSP_NARRATIVE_MATERIAL_FLOOR = 400

# Below this structured-input count, a long narrative implies the farmer is
# describing inputs in prose that aren't wired into the drift detector's
# baseline. Surface a REVIEW so the farmer reconciles before the audit.
REGISTRY_THIN_THRESHOLD = 3


def _normalize_input_name(name):
    """Lowercase + strip all non-alphanumerics for registry↔narrative matching.
    'Kocide 3000' and 'kocide-3000' collapse to the same key so a farmer's
    casual narrative mention still matches the registry entry.
    """
    import re

    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _compute_registry_sync_diff(*, inputs_narrative, omri_products, wsda_materials, nl_substances):
    """Forward-match every approved registry entry against the § 205.201(a)(2)
    narrative text. Returns:
      - registry_total: total M2M entries across OMRI + WSDA + NL
      - registry_entries: [{source, name, in_narrative: bool}, ...]

    We deliberately only do FORWARD matching (registry ⊂ narrative). Reverse
    extraction (find narrative-only mentions) requires NLP-style name detection
    that's too error-prone to surface to farmers without high false-positive
    rates. The inspector-value signal is "you have a registered input the
    narrative doesn't describe" — fixed by editing the narrative.
    """
    normalized_narrative = _normalize_input_name(inputs_narrative)
    entries = []
    for p in omri_products:
        name = p.product_name or ""
        norm = _normalize_input_name(name)
        in_narr = bool(norm) and norm in normalized_narrative
        entries.append({"source": "OMRI", "name": name, "in_narrative": in_narr})
    for m in wsda_materials:
        name = m.brand_name or ""
        norm = _normalize_input_name(name)
        in_narr = bool(norm) and norm in normalized_narrative
        entries.append({"source": "WSDA", "name": name, "in_narrative": in_narr})
    for s in nl_substances:
        name = s.substance_name or ""
        norm = _normalize_input_name(name)
        in_narr = bool(norm) and norm in normalized_narrative
        entries.append({"source": "National List", "name": name, "in_narrative": in_narr})
    return {
        "registry_total": len(entries),
        "registry_entries": entries,
    }


def _photo_count(event):
    """Return integer photo count for an event instance."""
    try:
        if event.album and hasattr(event.album, "images"):
            return event.album.images.count()
    except Exception:
        pass
    return 0


class _PageNumCanvas:
    """
    Mixin used by SimpleDocTemplate to add page numbers in the footer.
    ReportLab calls build() with onFirstPage / onLaterPages callbacks;
    we use a single callback for both.
    """

    pass


def _add_page_number(canvas, doc):
    """Footer callback: renders page number at bottom-right."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#888888"))
    page_num_text = f"Page {doc.page}"
    canvas.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, page_num_text)
    canvas.drawString(0.75 * inch, 0.5 * inch, "Generated by Trazo  |  EPA/USDA-sourced emission factors")
    canvas.restoreState()


class PhotoEmbedMisconfigurationError(Exception):
    """
    Raised when the audit PDF cannot embed inspector-visible photo evidence
    because the host environment is misconfigured (prod without S3 bucket, or
    prod with S3 bucket but 100% photo fetch failures). A PDF without embedded
    photos is not audit-defensible — inspectors, downstream organic operations,
    and supply-chain traceability auditors (§ 205.501(a)(21)) all rely on the
    evidence layer actually being present.

    The caller (the download view) catches this and returns a 503 with a
    human-readable message rather than silently shipping a degraded PDF.
    """

    def __init__(self, mode: str, detail: str):
        self.mode = mode
        self.detail = detail
        super().__init__(f"[{mode}] {detail}")


class OFPPMissingError(Exception):
    """
    Raised when strict-mode export is requested for an organic audit and the
    establishment either (a) has no Organic Fraud Prevention Plan uploaded, or
    (b) has an OFPP upload whose filename matches the misfiled-invoice
    heuristic. SOE 2024 (88 FR 3622, effective 2024-03-19) makes the OFPP a
    certification-eligibility requirement under 7 CFR 205.201(a)(3).

    Strict mode is OPT-IN: it is meant for the "Mark as Submitted" or
    certifier-handoff export flow. The default ``generate_pdf()`` call still
    produces a PDF with a page-1 FAIL row so farmers can DIAGNOSE missing
    OFPP in a preview. Blocking generation entirely would hide the finding
    from the farmer, which is exactly the feedback loop we want.

    The caller (the download view) catches this and returns a 422 with a
    structured message prompting OFPP upload before re-submission.
    """

    def __init__(self, reason: str, doc_name: str | None = None):
        self.reason = reason
        self.doc_name = doc_name
        super().__init__(f"OFPP blocker: {reason}" + (f" (file: {doc_name})" if doc_name else ""))


class AuditExportService:
    """
    Generates audit-ready PDF and CSV exports for a given production.

    Usage:
        service = AuditExportService(production, certification_type="organic")
        pdf_buffer = service.generate_pdf()    # BytesIO
        csv_buffer = service.generate_csv()    # BytesIO
    """

    CERTIFICATION_SECTIONS = {
        "all": [
            "osp_reference",
            "drift_findings",
            "producer_attestation",
            "regulatory_scope",
            "farm",
            "production",
            "chemicals",
            "production_events",
            "seed_stock",
            "soil",
            "pest",
            "equipment",
            "weather",
            "carbon",
            "traceability",
            "photos",
            "custom_data",
            "certifications",
            "business_events",
            "mass_balance",
            "field_history",
            "general_events",
            "soe_compliance",
            "change_history",
        ],
        "organic": [
            "osp_reference",  # 7 CFR 205.201 — OSP header (Sprint 5A)
            "drift_findings",  # Sprint 5.1 — OSP ↔ events drift (§ 205.400(f)(2) operation change)
            "producer_attestation",  # 7 CFR 205.401(d) — signed attestation
            "regulatory_scope",  # FSMA 204 + PSR + ICS scoping statements
            "farm",
            "production",
            "chemicals",
            "production_events",  # 7 CFR 205.272 water mgmt + 205.270 post-harvest
            "seed_stock",
            "soil",
            "pest",  # NOP 7 CFR 205.206(e) requires pest mgmt + threshold rationale docs
            "equipment",
            "weather",  # Climate-impact attestations supporting § 205.201(a)(3) monitoring
            # "carbon" intentionally excluded from NOP organic export — USDA inspectors
            # do not grade on environmental footprint, and including emissions data in
            # an audit PDF risks greenwashing-by-association claims. Carbon remains in
            # the "all" (admin), "roc", and "scs" exports where certifiers request it.
            "photos",
            "custom_data",
            "certifications",
            "business_events",
            "mass_balance",
            "field_history",
            "general_events",  # § 205.103(b)(1) "adapted to particular business" notes
            "soe_compliance",
            "change_history",
        ],
        "globalgap": [
            "farm",
            "production",
            "chemicals",
            "soil",
            "pest",
            "equipment",
            "photos",
            "custom_data",
            "business_events",
        ],
        "roc": [
            "farm",
            "production",
            "chemicals",
            "production_events",
            "seed_stock",
            "soil",
            "pest",
            "weather",
            "carbon",
            "photos",
            "custom_data",
            "certifications",
            "business_events",
            "mass_balance",
            "field_history",
        ],
        "fsma204": ["farm", "production", "traceability", "photos", "custom_data"],
        "scs": ["farm", "production", "chemicals", "soil", "pest", "carbon", "photos", "custom_data"],
    }

    CERTIFICATION_LABELS = {
        "all": "All Sections",
        "organic": "USDA Organic",
        "globalgap": "GlobalG.A.P.",
        "roc": "Regenerative Organic Certified",
        "fsma204": "FSMA 204 Traceability",
        "scs": "SCS Global Services",
    }

    def __init__(self, production, certification_type="all"):
        self.production = production
        self.certification_type = certification_type.lower()
        self.sections = self.CERTIFICATION_SECTIONS.get(
            self.certification_type,
            self.CERTIFICATION_SECTIONS["all"],
        )
        self._styles = self._build_styles()
        # Photo-embed counters. Dev-skipped (expected in local-dev without S3)
        # are separated from prod-failed (genuine S3 misconfig or fetch errors)
        # so the PDF banner can match the severity. Any bare `_photos_not_embedded`
        # reference treats both as the same — we keep it for backward compat.
        self._photos_not_embedded = 0
        self._photos_dev_skipped = 0
        self._photos_prod_failed = 0
        self._photos_prod_errors = []  # list of (url, reason) tuples, capped at 10

    # ------------------------------------------------------------------
    # Style helpers
    # ------------------------------------------------------------------

    def _build_styles(self):
        base = getSampleStyleSheet()
        styles = {}

        styles["title"] = ParagraphStyle(
            "AuditTitle",
            parent=base["Title"],
            fontSize=22,
            textColor=TRAZO_GREEN_DARK,
            spaceAfter=6,
            alignment=TA_CENTER,
        )
        styles["subtitle"] = ParagraphStyle(
            "AuditSubtitle",
            parent=base["Normal"],
            fontSize=13,
            textColor=DARK_GRAY,
            spaceAfter=4,
            alignment=TA_CENTER,
        )
        styles["section_header"] = ParagraphStyle(
            "SectionHeader",
            parent=base["Heading2"],
            fontSize=12,
            textColor=TRAZO_GREEN_DARK,
            spaceBefore=14,
            spaceAfter=4,
            borderPad=2,
        )
        styles["body"] = ParagraphStyle(
            "AuditBody",
            parent=base["Normal"],
            fontSize=9,
            textColor=DARK_GRAY,
            spaceAfter=3,
        )
        styles["label"] = ParagraphStyle(
            "AuditLabel",
            parent=base["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#555555"),
            spaceAfter=2,
        )
        styles["footer_note"] = ParagraphStyle(
            "FooterNote",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#888888"),
            spaceBefore=6,
            alignment=TA_LEFT,
        )
        styles["cell"] = ParagraphStyle(
            "CellText",
            parent=base["Normal"],
            fontSize=7,
            textColor=DARK_GRAY,
            leading=9,
        )
        styles["cell_header"] = ParagraphStyle(
            "CellHeader",
            parent=base["Normal"],
            fontSize=7,
            textColor=colors.white,
            fontName="Helvetica-Bold",
            leading=9,
            alignment=TA_CENTER,
        )
        return styles

    def _section_header(self, text):
        return Paragraph(text, self._styles["section_header"])

    def _body(self, text):
        return Paragraph(text, self._styles["body"])

    def _label_value(self, label, value):
        v = _val(value)
        return Paragraph(f"<b>{label}:</b> {v}", self._styles["body"])

    def _spacer(self, height=0.1):
        return Spacer(1, height * inch)

    def _cell(self, text, max_len=120):
        """Wrap text in a Paragraph so ReportLab can word-wrap inside table cells."""
        t = _truncate(text, max_len) if text else "\u2014"
        # Escape XML special characters for Paragraph
        t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Paragraph(t, self._styles["cell"])

    def _hdr(self, text):
        """Header cell wrapped in Paragraph for word-wrapping."""
        return Paragraph(str(text), self._styles["cell_header"])

    def _warning_style(self):
        """Return a ParagraphStyle for NOP compliance warnings."""
        if not hasattr(self, "_cached_warning_style"):
            self._cached_warning_style = ParagraphStyle(
                "nop_warning",
                parent=self._styles["body"],
                fontSize=7,
                textColor=colors.HexColor("#B71C1C"),
                spaceBefore=4,
                spaceAfter=4,
            )
        return self._cached_warning_style

    def _sub_header_style(self):
        """Return a ParagraphStyle for sub-section headers within audit sections."""
        if not hasattr(self, "_cached_sub_header_style"):
            self._cached_sub_header_style = ParagraphStyle(
                "nop_sub_header",
                parent=self._styles["body"],
                fontSize=8,
                spaceBefore=6,
                spaceAfter=4,
            )
        return self._cached_sub_header_style

    # ------------------------------------------------------------------
    # Table style helpers
    # ------------------------------------------------------------------

    def _base_table_style(self):
        return TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), TRAZO_GREEN),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                ("TOPPADDING", (0, 0), (-1, 0), 5),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
                ("GRID", (0, 0), (-1, -1), 0.4, MID_GRAY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 1), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )

    def _empty_table(self, headers):
        """Return a single-row table with headers and 'No records' message."""
        col_count = len(headers)
        data = [headers, ["No records for this production"] + [""] * (col_count - 1)]
        t = Table(data, repeatRows=1)
        style = self._base_table_style()
        style.add("SPAN", (0, 1), (-1, 1))
        style.add("ALIGN", (0, 1), (-1, 1), "CENTER")
        style.add("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#888888"))
        t.setStyle(style)
        return t

    def _event_note_text(self, ev):
        """
        Farmer-authored free-text note for an event.

        ChemicalEvent (and Production/General) carry a dedicated
        ``observation`` column. Soil and Pest events have NO observation
        column — the form's note arrives via ``extra_data`` (``observation``
        / ``observations_summary``, the keys the event serializers stash
        free-text into). Returns "" when no note exists.
        """
        note = (getattr(ev, "observation", None) or "").strip()
        if note:
            return note
        extra = getattr(ev, "extra_data", None)
        if isinstance(extra, dict):
            for key in ("observation", "observations_summary", "notes"):
                value = extra.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def _build_event_notes_subtable(self, events, title, type_labels):
        """
        Supplemental notes sub-table (date | type label | note ≤120 chars).

        Mirrors the Production Event Notes pattern: the main section tables
        keep one compact row per event, so free-text notes — the richest
        farmer-authored documentation — would overflow them. Renders ONLY
        when at least one event has a non-empty note; returns [] otherwise.
        """
        noted = [(ev, self._event_note_text(ev)) for ev in events]
        noted = [(ev, note) for ev, note in noted if note]
        if not noted:
            return []

        elements = [self._spacer(0.15), self._body(f"<b>{title}</b>"), self._spacer(0.05)]

        notes_headers = ["Date", "Type", "Notes"]
        notes_data = [[self._hdr(h) for h in notes_headers]]
        for ev, note in noted:
            notes_data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(type_labels.get(ev.type, _val(ev.type))),
                    self._cell(note, 120),
                ]
            )

        notes_widths = [0.7 * inch, 1.0 * inch, 4.9 * inch]
        notes_table = Table(notes_data, colWidths=notes_widths, repeatRows=1)
        notes_table.setStyle(self._base_table_style())
        elements.append(notes_table)
        return elements

    # ------------------------------------------------------------------
    # PDF generation — public entry point
    # ------------------------------------------------------------------

    def generate_pdf(
        self,
        strict_photos: bool = True,
        strict_ofpp: bool | None = None,
    ):
        """
        Return a BytesIO containing the complete audit PDF.

        Parameters
        ----------
        strict_photos : bool, default True
            When True AND this production has photos attached, the PDF
            emission is GATED on photo-evidence integrity:
              * in ``prod_s3_misconfig`` (prod without S3 bucket configured),
                a pre-flight check raises ``PhotoEmbedMisconfigurationError``
                BEFORE the document is built — an inspector-grade PDF cannot
                be shipped without the evidence layer, and the misconfig is
                unrecoverable in-process.
              * after build, if ANY photo fetch failed in prod mode
                (``_photos_prod_failed > 0``), ``PhotoEmbedMisconfigurationError``
                is raised post-build and the partial buffer is discarded.
                Unembedded photo evidence is not acceptable for an
                inspector-facing artifact.
            Productions with zero photos are NOT gated — an all-text PDF
            does not need S3 to be inspector-ready.

            Callers that want a best-effort preview (farmer dashboard,
            internal debugging) can pass ``strict_photos=False`` to bypass
            both gates and accept a PDF that transparently declares its
            photo-evidence gap via the in-document banner.

        strict_ofpp : bool | None, default None (derives from cert type)
            When True AND this is an organic export (``certification_type``
            = "organic" or "all"), refuse to emit the PDF if the
            establishment's OFPP is a [FAIL] on the compliance snapshot
            (not uploaded at all OR uploaded with a misfiled-invoice
            filename pattern). Raises ``OFPPMissingError`` before building.

            When None (the default), the flag is derived from the
            certification type:
              * "organic" or "all" → strict_ofpp defaults to True, on the
                premise that any export filtered for NOP compliance must
                be submission-ready. A partial-preview dossier that
                silently admits a § 205.201(a)(3) non-compliance is the
                exact "NO-GO" artifact CCOF inspectors will not process.
              * All other cert types → False.

            Callers that explicitly want a diagnostic preview (farmer
            dashboard, pre-submit gap-analysis) MUST pass
            ``strict_ofpp=False`` to opt out of the gate. The view layer
            threads ``strict_ofpp=false`` from a query parameter for
            exactly this purpose.

            Non-organic cert types are unaffected regardless — OFPP is a
            NOP construct.
        """
        # Pre-flight: in prod without S3 bucket, refuse to emit a PDF only
        # when this production actually has photos to embed. A production
        # with zero photos attached is text-only and unaffected by the S3
        # gap, so there's no reason to block it here.
        env = self._photo_embed_environment()
        has_photos = self._production_has_any_photos()
        if strict_photos and has_photos and env["mode"] == "prod_s3_misconfig":
            raise PhotoEmbedMisconfigurationError(
                mode=env["mode"],
                detail=(
                    "Production environment has no AWS_STORAGE_BUCKET_NAME "
                    "configured — photo evidence cannot be embedded. Refusing "
                    "to emit audit PDF. Configure S3 before re-exporting."
                ),
            )

        # Pre-flight: strict-OFPP gate for organic / all-certs exports.
        # Runs BEFORE document build so the caller gets a fast, structured
        # error rather than a PDF that effectively admits non-compliance.
        # When the caller passes None (our default), derive strict from
        # the cert type: organic / all-certs exports are strict by default
        # because a NOP-filtered dossier MUST be submission-ready under
        # SOE 2024. Diagnostic previews must explicitly opt out via
        # ``strict_ofpp=False``.
        if strict_ofpp is None:
            strict_ofpp = self.certification_type in ("organic", "all")
        if strict_ofpp and self.certification_type in ("organic", "all"):
            ofpp_flags = self._ofpp_flags()
            if ofpp_flags["establishment"]:
                if not ofpp_flags["uploaded"]:
                    raise OFPPMissingError(
                        reason=(
                            "No Organic Fraud Prevention Plan on file. SOE "
                            "2024 (7 CFR 205.201(a)(3), effective 2024-03-"
                            "19) requires every certified operation to "
                            "maintain a written OFPP with a vulnerability "
                            "assessment and monitoring procedures. An "
                            "operation without a valid OFPP is ineligible "
                            "for certification."
                        )
                    )
                if ofpp_flags["filename_suspicious"]:
                    raise OFPPMissingError(
                        reason=(
                            "OFPP upload filename matches the misfiled-"
                            "invoice heuristic. Trazo treats this as a "
                            "missing OFPP for submission purposes — upload "
                            "a substantive OFPP (vulnerability assessment + "
                            "monitoring procedures + supplier verification) "
                            "before re-exporting."
                        ),
                        doc_name=ofpp_flags.get("doc_name"),
                    )

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.9 * inch,
            bottomMargin=0.75 * inch,
            title=f"Trazo Audit Report — {self._farm_name()}",
        )

        story = []
        story += self._build_cover_page()
        story.append(PageBreak())

        section_builders = {
            "osp_reference": self._build_osp_reference_section,
            "drift_findings": self._build_drift_findings_section,
            "producer_attestation": self._build_producer_attestation_section,
            "regulatory_scope": self._build_regulatory_scope_section,
            "farm": self._build_farm_overview,
            "production": self._build_production_summary,
            "chemicals": self._build_chemical_log,
            "production_events": self._build_production_events,
            "seed_stock": self._build_seed_stock_section,
            "soil": self._build_soil_section,
            "pest": self._build_pest_section,
            "equipment": self._build_equipment_section,
            "weather": self._build_weather_section,
            "carbon": self._build_carbon_section,
            "traceability": self._build_traceability_section,
            "photos": self._build_photos_section,
            "custom_data": self._build_custom_data_section,
            "certifications": self._build_certifications_section,
            "business_events": self._build_business_events_section,
            "mass_balance": self._build_mass_balance_section,
            "field_history": self._build_field_history_section,
            "general_events": self._build_general_events_section,
            "soe_compliance": self._build_soe_compliance_section,
            "change_history": self._build_change_history_section,
        }

        for section_key in self.sections:
            builder = section_builders.get(section_key)
            if builder:
                story += builder()

        doc.build(story, onFirstPage=_add_page_number, onLaterPages=_add_page_number)

        # Post-build gate: in prod with S3 configured, any photo that failed
        # to embed indicates a bucket-policy / IAM / DNS issue that must be
        # resolved before the PDF ships to a certifier. An inspector-facing
        # audit artifact is only as trustworthy as its evidence layer; a
        # banner that says "3 of 25 photos unavailable" reads as an
        # incomplete filing to a CCOF reviewer. Refuse rather than emit.
        if strict_photos and env["mode"] == "prod_s3_ok":
            prod_failed = getattr(self, "_photos_prod_failed", 0)
            if prod_failed > 0:
                raise PhotoEmbedMisconfigurationError(
                    mode=env["mode"],
                    detail=(
                        f"{prod_failed} photo(s) failed to embed in production "
                        "(S3 fetch errors). Refusing to emit an inspector-grade "
                        "audit PDF without complete evidence. Check IAM "
                        "permissions / bucket policy / DNS and re-export."
                    ),
                )

        buffer.seek(0)
        return buffer

    def _production_has_any_photos(self) -> bool:
        """
        Cheap existence check — does this production have ANY photos
        attached across all event categories? Used by the photo-evidence
        gate to skip the S3 check for text-only productions.

        Walks the same related managers as ``_build_photos_section`` but
        returns on the first hit instead of building the full category
        list. Never raises — a DB error here must not prevent PDF export.
        """
        try:
            for _, related_name in self._photos_category_order_for():
                qs = getattr(self.production, related_name, None)
                if qs is None:
                    continue
                for ev in qs.all():
                    if _photo_count(ev) > 0:
                        return True
        except Exception:  # noqa: BLE001 — gate must degrade open, not crash.
            return False
        return False

    # ------------------------------------------------------------------
    # Cover page
    # ------------------------------------------------------------------

    def _farm_name(self):
        try:
            return self.production.parcel.establishment.name
        except AttributeError:
            return "Farm"

    def _build_cover_page(self):
        p = self.production
        elements = []

        elements.append(self._spacer(1.2))

        elements.append(Paragraph(f"Audit Report \u2014 {self._farm_name()}", self._styles["title"]))
        elements.append(self._spacer(0.1))

        crop_name = ""
        try:
            crop_name = p.crop_type.name if p.crop_type else (p.product.name if p.product else "")
        except AttributeError:
            pass

        start = _fmt_date(p.start_date)
        end = _fmt_date(p.finish_date or p.expected_harvest)
        elements.append(
            Paragraph(
                f"{crop_name} Production \u2014 {start} to {end}",
                self._styles["subtitle"],
            )
        )

        elements.append(self._spacer(0.6))

        cert_label = self.CERTIFICATION_LABELS.get(self.certification_type, self.certification_type.upper())
        meta_rows = [
            ["Generated", _fmt_date(date.today())],
            ["Certification Filter", cert_label],
            ["Production ID", _val(str(p.public_id))],
            ["Lot ID", _val(p.lot_id)],
        ]
        meta_table = Table(meta_rows, colWidths=[2 * inch, 4 * inch])
        meta_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, MID_GRAY),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        elements.append(meta_table)

        elements.append(self._spacer(0.4))

        # Non-compliant-dossier banner. We compute this from the OFPP flag
        # (the SOE 2024 hard-blocker under § 205.201(a)(3)). When OFPP is
        # FAIL the dossier is NOT submission-ready; surface that ABOVE the
        # snapshot so an inspector reading page 1 can never mistake a
        # diagnostic preview for a submission-ready filing. Default mode
        # (non-strict) still produces the PDF so the farmer can see WHY
        # they are non-compliant; strict-mode export raises a 422 instead.
        try:
            ofpp_flags = self._ofpp_flags()
        except Exception:  # noqa: BLE001 — banner must not crash the cover page
            ofpp_flags = {"establishment": False, "uploaded": False, "filename_suspicious": False}
        ofpp_blocker = (
            self.certification_type in ("organic", "all")
            and ofpp_flags.get("establishment")
            and (not ofpp_flags.get("uploaded") or ofpp_flags.get("filename_suspicious"))
        )
        if ofpp_blocker:
            banner_style = ParagraphStyle(
                "noncompliant_banner",
                parent=self._styles["body"],
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
            banner_text = (
                "[NON-COMPLIANT DOSSIER \u2014 DO NOT SUBMIT TO CERTIFIER] "
                "OFPP (\u00a7 205.201(a)(3)) is FAIL. SOE 2024 prohibits "
                "certification without a valid Organic Fraud Prevention Plan. "
                "Resolve the OFPP finding on page 1 / SOE Compliance Status "
                "before handing this PDF to a CCOF reviewer."
            )
            elements.append(Paragraph(banner_text, banner_style))

        elements += self._build_compliance_snapshot()

        # Pre-Export Consistency Check — cross-references production
        # header fields against the raw event stream (yield, carton count,
        # lot ID, handler). Surfaces internal inconsistencies to the farmer
        # BEFORE the PDF reaches a certifier. Under SOE § 205.103(b)(2) and
        # § 205.501(a)(21), these are exactly the kind of questions a
        # supply-chain traceability audit is designed to ask.
        # The linter must NEVER crash PDF generation — an unexpected data
        # shape in the narrative should degrade to "no findings" rather
        # than an empty PDF.
        try:
            consistency = self._build_consistency_findings()
        except Exception:  # noqa: BLE001 — linter is informational, not blocking
            logger.exception("Consistency linter raised; rendering PDF without it")
            consistency = []
        if consistency:
            elements.append(self._spacer(0.15))
            elements += consistency

        elements.append(self._spacer(0.3))
        elements.append(
            Paragraph(
                "Generated by Trazo  |  Transparency-first agricultural platform  |  trazo.io",
                self._styles["footer_note"],
            )
        )
        elements.append(
            Paragraph(
                "Emission factors sourced from EPA 40 CFR Part 98 and USDA Agricultural Research Service.",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # Compliance Snapshot — page-1 executive summary
    # ------------------------------------------------------------------

    def _build_compliance_snapshot(self):
        """
        One-table audit snapshot: ✓ / ⚠ / ✗ for the items an inspector
        scans for first. Goal is a 30-second compliance overview that
        replaces the inspector's manual checklist for this operation.
        """

        from certifications.models import OrganicSystemPlan

        p = self.production

        # Counts — each section header below mirrors a real inspector worksheet.
        # All seven event types contribute to the documentation-depth roll-up
        # at the bottom of the snapshot; weather/equipment/business are quieter
        # but still part of the operation's record-keeping footprint.
        chemicals = list(p.history_chemicalevent_events.all())
        soils = list(p.history_soilmanagementevent_events.all())
        pests = list(p.history_pestmanagementevent_events.all())
        production_events = list(p.history_productionevent_events.all())
        gen_events = list(p.history_generalevent_events.all())
        weather_events = list(p.history_weatherevent_events.all())
        business_events = list(p.history_businessevent_events.all())
        equipment_events = list(p.history_equipmentevent_events.all())
        all_events = (
            chemicals
            + soils
            + pests
            + production_events
            + gen_events
            + weather_events
            + business_events
            + equipment_events
        )
        photos_total = sum(_photo_count(ev) for ev in all_events)

        # OSP completeness — material floor is 400 chars per § 205.201(a).
        osp = None
        try:
            est = p.parcel.establishment
            osp = (
                OrganicSystemPlan.objects.filter(establishment=est, status="active").order_by("-version_number").first()
            )
            if osp is None:
                osp = OrganicSystemPlan.objects.filter(establishment=est).order_by("-version_number").first()
        except Exception:  # noqa: BLE001 — snapshot must never crash the PDF
            est = None

        if osp:
            from certifications.models import OSP_SECTION_KEYS

            sections_data = osp.sections or {}
            section_hits = {
                k: len((sections_data.get(k) or {}).get("narrative", "").strip()) >= 400 for k in OSP_SECTION_KEYS
            }

            # Registry Sync gate: (a)(2) inputs narrative is not "substantively
            # filled" if the OSP's structured approved-inputs registry has
            # entries that are not referenced in the narrative. Prevents the
            # page-1 snapshot from reading "100% complete" while the detail
            # section shows unreferenced registry entries (a CCOF inspector
            # would call this a contradiction on the face of the document).
            try:
                inputs_narrative_text = (sections_data.get("inputs_list") or {}).get("narrative", "") or ""
                registry_diff = _compute_registry_sync_diff(
                    inputs_narrative=inputs_narrative_text,
                    omri_products=list(osp.approved_omri_products.all()),
                    wsda_materials=list(osp.approved_wsda_materials.all()),
                    nl_substances=list(osp.approved_national_list_substances.all()),
                )
                unref = sum(1 for r in registry_diff["registry_entries"] if not r["in_narrative"])
                if unref > 0:
                    section_hits["inputs_list"] = False
            except Exception:  # noqa: BLE001 — snapshot must never crash the PDF
                unref = 0

            material_complete = sum(1 for hit in section_hits.values() if hit)
            osp_pct = int(material_complete * 100 / len(OSP_SECTION_KEYS))
            osp_status = "PASS" if osp_pct >= 100 else ("REVIEW" if osp_pct >= 50 else "FAIL")
            osp_detail = f"v{osp.version_number} {osp.get_status_display()} — {osp_pct}% materially complete"
            if unref > 0:
                osp_detail += f"; (a)(2) gap: {unref} registry entr" f"{'y' if unref == 1 else 'ies'} unreferenced"
        else:
            osp_status = "FAIL"
            osp_detail = "No Organic System Plan on file"

        # Drift findings (Sprint 5.1 detector).
        drift_count = sum(1 for ev in chemicals + soils if ev.drift_warning)

        # Compost compliance per § 205.203(c)(2).
        # Full classifier: C:N 25–40 AND temp 131–170°F AND method-specific duration/turnings.
        # - Windrow: 15+ days at temp, 5+ turnings.
        # - Static aerated / in-vessel: 3+ days at temp.
        # Missing C:N / method / temp / duration → REVIEW. C:N out of range → FAIL.
        compost_events = [ev for ev in soils if ev.type == "CO"]
        compost_compliant = 0
        compost_missing_cn = 0
        compost_cn_out_of_range = 0
        compost_missing_method = 0
        compost_missing_temp_or_duration = 0
        # Pathway tracking — § 205.203(c)(2) has three pathways: (i) C:N
        # precondition 25:1–40:1, (ii) in-vessel 131–170°F × 3+ days, (iii)
        # windrow 131–170°F × 15+ days with 5+ turnings. Static-aerated piles
        # follow the same 3-day duration as in-vessel. Inspector wants to know
        # which pathway(s) were used, not just PASS/FAIL.
        compost_pathway_counts = {"windrow": 0, "static_aerated": 0, "in_vessel": 0, "unspecified": 0}
        compost_cn_min = None
        compost_cn_max = None
        for ev in compost_events:
            cn = float(ev.compost_initial_cn_ratio) if ev.compost_initial_cn_ratio is not None else None
            if cn is not None:
                compost_cn_min = cn if compost_cn_min is None else min(compost_cn_min, cn)
                compost_cn_max = cn if compost_cn_max is None else max(compost_cn_max, cn)
            method_key = getattr(ev, "compost_method", None) or "unspecified"
            if method_key not in compost_pathway_counts:
                method_key = "unspecified"
            compost_pathway_counts[method_key] = compost_pathway_counts.get(method_key, 0) + 1
            if cn is None:
                compost_missing_cn += 1
                continue
            if not (25.0 <= cn <= 40.0):
                compost_cn_out_of_range += 1
                continue
            if not ev.compost_method:
                compost_missing_method += 1
                continue
            if ev.compost_peak_temp_f is None or ev.compost_duration_days_at_temp is None:
                compost_missing_temp_or_duration += 1
                continue
            temp_ok = 131 <= float(ev.compost_peak_temp_f) <= 170
            if ev.compost_method == "windrow":
                duration_ok = ev.compost_duration_days_at_temp >= 15 and (ev.compost_turning_count or 0) >= 5
            else:
                duration_ok = ev.compost_duration_days_at_temp >= 3
            if temp_ok and duration_ok:
                compost_compliant += 1

        def _compost_pathway_summary():
            """Human-readable pathway + C:N summary for the snapshot detail cell."""
            labels = {
                "windrow": "Windrow (§ 205.203(c)(2)(iii))",
                "static_aerated": "Static aerated pile (§ 205.203(c)(2))",
                "in_vessel": "In-vessel (§ 205.203(c)(2)(ii))",
                "unspecified": "Pathway unspecified",
            }
            parts = [f"{count}× {labels[k]}" for k, count in compost_pathway_counts.items() if count]
            pathway_str = "; ".join(parts) if parts else "no pathway data"
            if compost_cn_min is not None and compost_cn_max is not None:
                if abs(compost_cn_max - compost_cn_min) < 0.05:
                    cn_str = f"C:N {compost_cn_min:.1f}:1"
                else:
                    cn_str = f"C:N {compost_cn_min:.1f}–{compost_cn_max:.1f}:1"
                if compost_cn_min < 25.0 or compost_cn_max > 40.0:
                    cn_str += " [outside § 205.203(c)(2)(i) 25:1–40:1 floor]"
                return f"{pathway_str} · {cn_str}"
            return pathway_str

        # Manure interval — every raw-manure event must have an interval set.
        manure_events = [ev for ev in soils if ev.manure_application_date or ev.manure_harvest_interval]
        manure_with_interval = sum(1 for ev in manure_events if ev.manure_harvest_interval)
        # Classification-mismatch count: farmer selected an interval that
        # doesn't match the crop's soil-contact rule. The timing may still
        # be compliant (e.g. farmer chose 120-day on a tree crop and
        # harvested at 99 days — compliant under the correct 90-day floor
        # but IN-violation under the farmer's own 120-day selection).
        # Either reading makes page-1 an executive-summary signal, not a
        # clean PASS. Count it here so the snapshot row below can demote
        # the status without re-deriving the rule.
        _rule_for_count = self._manure_interval_rule_for_crop()
        _expected_days = _rule_for_count["days"]
        manure_classification_mismatches = 0
        for ev in manure_events:
            raw = (ev.manure_harvest_interval or "").split("_")[0]
            if raw.isdigit() and int(raw) != _expected_days:
                manure_classification_mismatches += 1

        # Pest threshold rationale per § 205.206(e). Strip whitespace so a
        # placeholder " " doesn't pass for a documented rationale.
        threshold_met_events = [ev for ev in pests if ev.action_threshold_met]
        threshold_with_rationale = sum(
            1 for ev in threshold_met_events if ev.threshold_rationale and ev.threshold_rationale.strip()
        )

        # IPM strategy presence per § 205.206(a).
        pests_with_ipm = sum(1 for ev in pests if ev.ipm_strategy and ev.ipm_strategy.strip())

        # Chemical traceability per § 205.103(b) — supplier required for every input.
        # Also detect supplier-name variants ("Hydra", "Hydra Gardens", "Hydra-Gardens")
        # that collapse to the same normalized form — inspector treats those as REVIEW,
        # not PASS, because it's a data-integrity signal.
        import re

        def _normalize_supplier(name):
            return re.sub(r"[\s\-_,.]+", "", (name or "").strip().lower())

        chems_with_supplier = sum(1 for ev in chemicals if ev.supplier_name and ev.supplier_name.strip())
        supplier_variants = {}
        for ev in chemicals:
            raw = (ev.supplier_name or "").strip()
            if not raw:
                continue
            key = _normalize_supplier(raw)
            supplier_variants.setdefault(key, set()).add(raw)
        supplier_variant_groups = [raws for raws in supplier_variants.values() if len(raws) > 1]

        # § 205.272 contamination prevention — when the operation uses equipment
        # shared with conventional, evidence is required in the form of EM
        # (Equipment Maintenance) events carrying cleaning date + method + performer.
        # One shared-equipment exposure ⇒ at least one fully-documented EM event
        # should exist. Rinse-step documentation lands in P0-6.
        any_shared_equipment = any(ev.shared_with_conventional for ev in production_events)
        em_cleaning_events = [ev for ev in production_events if ev.type == "EM"]
        em_fully_documented = sum(
            1
            for ev in em_cleaning_events
            if ev.cleaning_date and (ev.cleaning_method or "").strip() and (ev.cleaned_by or "").strip()
        )

        # Contamination incidents per § 205.201(b). Both fields must be non-empty.
        contamination_events = [ev for ev in gen_events if ev.is_contamination_incident]
        contamination_with_action = sum(
            1
            for ev in contamination_events
            if ev.corrective_action_taken and ev.corrective_action_taken.strip() and ev.certifier_notified
        )

        # Helper to render PASS/REVIEW/FAIL with color coding.
        def status_paragraph(status):
            color = {"PASS": "#2E7D32", "REVIEW": "#E65100", "FAIL": "#B71C1C"}.get(status, "#555555")
            mark = {"PASS": "PASS", "REVIEW": "REVIEW", "FAIL": "FAIL"}.get(status, status)
            return Paragraph(
                f'<b><font color="{color}">{mark}</font></b>',
                ParagraphStyle("snap_status", parent=self._styles["body"], fontSize=8, alignment=TA_CENTER),
            )

        def detail_paragraph(text):
            return Paragraph(
                self._safe_narrative(str(text)),
                ParagraphStyle("snap_detail", parent=self._styles["body"], fontSize=8, leading=10),
            )

        def detail_paragraph_with_hint(detail_text, hint_text):
            """Escape the data-origin detail, then append a trusted-origin
            section-hint fragment verbatim. The hint is Trazo-authored and
            safe to pass as ReportLab inline markup (``<i>...</i>``); the
            detail comes from user/DB data and must be escaped."""
            safe_detail = self._safe_narrative(str(detail_text))
            return Paragraph(
                f"{safe_detail} <i>({hint_text})</i>",
                ParagraphStyle("snap_detail", parent=self._styles["body"], fontSize=8, leading=10),
            )

        # Build rows. Each row: (Requirement, status PASS/REVIEW/FAIL, detail).
        snapshot_rows = []

        # OSP filed
        snapshot_rows.append(("Organic System Plan (§ 205.201)", osp_status, osp_detail))

        # OSP completeness — § 205.201(a)(2) requires the OSP to "include a
        # description of the substances to be used as production or
        # handling inputs." A registry-narrative gap is a technical
        # violation: the structured registry has inputs the narrative does
        # not describe. Surface this as its OWN row (not just a suffix on
        # the OSP row above) so an inspector reading the snapshot does
        # not miss the load-bearing (a)(2) signal. Status:
        #   PASS  — every registry input is referenced in the narrative
        #   REVIEW — 1-3 unreferenced (typo / minor narrative gap)
        #   FAIL — 4+ unreferenced (substantive narrative deficit)
        if osp:
            if unref == 0:
                snapshot_rows.append(
                    (
                        "OSP completeness (\u00a7 205.201(a)(2))",
                        "PASS",
                        "All registry inputs are referenced in the OSP narrative",
                    )
                )
            elif unref <= 3:
                snapshot_rows.append(
                    (
                        "OSP completeness (\u00a7 205.201(a)(2))",
                        "REVIEW",
                        (
                            f"{unref} registry input"
                            f"{'s are' if unref != 1 else ' is'} not "
                            "referenced in the OSP narrative \u2014 update "
                            "the narrative or remove the unused entries"
                        ),
                    )
                )
            else:
                snapshot_rows.append(
                    (
                        "OSP completeness (\u00a7 205.201(a)(2))",
                        "FAIL",
                        (
                            f"{unref} registry inputs are not referenced in "
                            "the OSP narrative. \u00a7 205.201(a)(2) requires "
                            "the OSP to describe every input used; an "
                            "inspector will issue an RFI before approving "
                            "the materials."
                        ),
                    )
                )

        # Unapproved-input findings (OSP practice change)
        if drift_count == 0:
            snapshot_rows.append(
                (
                    "Unapproved-input findings (§ 205.400(f)(2))",
                    "PASS",
                    "0 unresolved unapproved-input findings",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Unapproved-input findings (§ 205.400(f)(2))",
                    "REVIEW",
                    f"{drift_count} unapproved-input finding(s) \u2014 see Unapproved-Input Findings section",
                )
            )

        # Chemical input traceability — FAIL on missing supplier, REVIEW on
        # name variants that may refer to the same vendor (data-integrity signal).
        if not chemicals:
            snapshot_rows.append(("Input traceability (§ 205.103)", "PASS", "No chemical inputs applied"))
        elif chems_with_supplier != len(chemicals):
            snapshot_rows.append(
                (
                    "Input traceability (§ 205.103)",
                    "FAIL",
                    f"{chems_with_supplier}/{len(chemicals)} inputs have supplier — fill before audit",
                )
            )
        elif supplier_variant_groups:
            # Render the first variant group inline so the farmer sees what to fix.
            first_group = sorted(supplier_variant_groups[0])
            sample = ", ".join(f'"{n}"' for n in first_group[:3])
            extra = f" (+ {len(supplier_variant_groups) - 1} more)" if len(supplier_variant_groups) > 1 else ""
            snapshot_rows.append(
                (
                    "Input traceability (§ 205.103)",
                    "REVIEW",
                    f"Supplier name variants may refer to same vendor: {sample}{extra}",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Input traceability (§ 205.103)",
                    "PASS",
                    f"{chems_with_supplier}/{len(chemicals)} inputs have supplier on file",
                )
            )

        # Compost compliance — C:N out of range is a hard FAIL (pile reverts to
        # raw manure). Pathway info is surfaced in every case so the inspector
        # sees which § 205.203(c)(2) route was used.
        if not compost_events:
            snapshot_rows.append(("Compost (§ 205.203(c)(2))", "PASS", "No compost events to validate"))
        elif compost_cn_out_of_range > 0:
            snapshot_rows.append(
                (
                    "Compost (§ 205.203(c)(2))",
                    "FAIL",
                    (
                        f"{compost_cn_out_of_range}/{len(compost_events)} event(s) have initial C:N outside "
                        "25:1–40:1 — must be handled as raw manure under (c)(1). "
                        f"Pathway: {_compost_pathway_summary()}"
                    ),
                )
            )
        elif compost_missing_cn > 0 or compost_missing_method > 0 or compost_missing_temp_or_duration > 0:
            missing_parts = []
            if compost_missing_cn > 0:
                missing_parts.append(f"{compost_missing_cn} missing C:N")
            if compost_missing_method > 0:
                missing_parts.append(f"{compost_missing_method} missing method")
            if compost_missing_temp_or_duration > 0:
                missing_parts.append(f"{compost_missing_temp_or_duration} missing temp/duration")
            snapshot_rows.append(
                (
                    "Compost (§ 205.203(c)(2))",
                    "REVIEW",
                    f"{' · '.join(missing_parts)} — add before inspection. " f"Pathway: {_compost_pathway_summary()}",
                )
            )
        elif compost_compliant == len(compost_events):
            snapshot_rows.append(
                (
                    "Compost (§ 205.203(c)(2))",
                    "PASS",
                    f"{compost_compliant}/{len(compost_events)} events meet C:N 25–40 + temp + method duration. "
                    f"Pathway: {_compost_pathway_summary()}",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Compost (§ 205.203(c)(2))",
                    "REVIEW",
                    f"{compost_compliant}/{len(compost_events)} compliant — review non-compliant events. "
                    f"Pathway: {_compost_pathway_summary()}",
                )
            )

        # Manure interval — § 205.203(c)(1) governs raw manure (compost is (c)(2)).
        # (c)(1)(i) land used for a crop not intended for human consumption.
        # (c)(1)(ii) 120 days when the edible portion has direct soil contact
        # (root crops, leafy greens, fruits on the ground).
        # (c)(1)(iii) 90 days when the edible portion does NOT have direct soil
        # contact (tree fruits, tree nuts, elevated vine fruits).
        # Citing (ii) for a 90-day interval inverts the rule — a CCOF inspector
        # would read it as a category mismatch / regulatory misanchor.
        manure_interval_rule = self._manure_interval_rule_for_crop()
        manure_row_label = f"Raw manure interval ({manure_interval_rule['cite']})"
        if not manure_events:
            snapshot_rows.append((manure_row_label, "PASS", "No raw manure events"))
        elif manure_with_interval != len(manure_events):
            # Missing interval selection on at least one event — hard FAIL
            # regardless of classification; can't verify safety without the
            # selection.
            snapshot_rows.append(
                (
                    manure_row_label,
                    "FAIL",
                    (
                        f"{manure_with_interval}/{len(manure_events)} events have the "
                        f"{manure_interval_rule['label']} interval recorded — safety-critical"
                    ),
                )
            )
        elif manure_classification_mismatches > 0:
            # Every event has an interval AND the timing may satisfy the
            # regulatory floor, BUT the farmer-selected classification
            # (90/120-day category) doesn't match the crop rule. REVIEW
            # rather than PASS: an inspector reading the record will ask
            # why the selection conflicts with the crop's soil-contact
            # classification, and if the farmer's selected interval is
            # stricter than the regulatory floor, the actual harvest may
            # sit INSIDE the farmer's own self-imposed window — a record-
            # integrity issue under § 205.103(b)(2) even when the
            # regulatory timing passes.
            snapshot_rows.append(
                (
                    manure_row_label,
                    "REVIEW",
                    (
                        f"{manure_with_interval}/{len(manure_events)} events meet the "
                        f"{manure_interval_rule['label']} regulatory floor, but "
                        f"{manure_classification_mismatches} event(s) have a farmer-"
                        f"selected interval that does not match the crop-rule "
                        f"classification — see Pre-Export Consistency Check + "
                        f"Manure Handling Records for the per-event mismatch list."
                    ),
                )
            )
        else:
            snapshot_rows.append(
                (
                    manure_row_label,
                    "PASS",
                    (
                        f"{manure_with_interval}/{len(manure_events)} events meet the "
                        f"{manure_interval_rule['label']} pre-harvest interval"
                    ),
                )
            )

        # § 205.272 contamination prevention — cleaning-log evidence when any
        # equipment is shared with conventional operations. Distinguish:
        # - no EM events at all → FAIL (no cleaning record created)
        # - EM events exist but all incomplete / partially documented → REVIEW
        # - all EM events fully documented → PASS
        if not any_shared_equipment:
            snapshot_rows.append(
                (
                    "Contamination prevention (§ 205.272)",
                    "PASS",
                    "No equipment shared with conventional operations",
                )
            )
        elif not em_cleaning_events:
            snapshot_rows.append(
                (
                    "Contamination prevention (§ 205.272)",
                    "FAIL",
                    "Shared equipment in use but no Equipment Maintenance cleaning events on file",
                )
            )
        elif em_fully_documented < len(em_cleaning_events):
            snapshot_rows.append(
                (
                    "Contamination prevention (§ 205.272)",
                    "REVIEW",
                    (
                        f"{em_fully_documented}/{len(em_cleaning_events)} EM cleaning events fully documented — "
                        "remaining events missing date / method / performer"
                    ),
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Contamination prevention (§ 205.272)",
                    "PASS",
                    (
                        f"{em_fully_documented} EM cleaning event(s) on file with date + method + performer for "
                        "shared-equipment exposure"
                    ),
                )
            )

        # Pest threshold rationale
        if not threshold_met_events:
            snapshot_rows.append(
                ("Pest threshold rationale (§ 205.206(e))", "PASS", "No pest events with action threshold met")
            )
        elif threshold_with_rationale == len(threshold_met_events):
            snapshot_rows.append(
                (
                    "Pest threshold rationale (§ 205.206(e))",
                    "PASS",
                    f"{threshold_with_rationale}/{len(threshold_met_events)} threshold-met events documented",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Pest threshold rationale (§ 205.206(e))",
                    "FAIL",
                    f"{threshold_with_rationale}/{len(threshold_met_events)} have rationale — required before any control material",
                )
            )

        # IPM strategy
        if not pests:
            snapshot_rows.append(("IPM strategy (§ 205.206(a))", "PASS", "No pest events"))
        elif pests_with_ipm == len(pests):
            snapshot_rows.append(
                ("IPM strategy (§ 205.206(a))", "PASS", f"{pests_with_ipm}/{len(pests)} pest events document IPM")
            )
        else:
            snapshot_rows.append(
                (
                    "IPM strategy (§ 205.206(a))",
                    "REVIEW",
                    f"{pests_with_ipm}/{len(pests)} have IPM strategy — fill before inspection",
                )
            )

        # Lot traceability — post-SOE § 205.307(a) requires (1) organic identity
        # and (2) lot/shipping-ID on every non-retail container; § 205.103(b)(2)
        # requires records that enable one-step trace from sales unit back to
        # production lot. § 205.273 is the Imports section — NOT the correct
        # cite for domestic lot traceability.
        if p.lot_id:
            snapshot_rows.append(("Lot traceability (§ 205.307 / § 205.103(b)(2))", "PASS", f"Lot ID: {p.lot_id}"))
        else:
            snapshot_rows.append(
                ("Lot traceability (§ 205.307 / § 205.103(b)(2))", "REVIEW", "Lot ID assigned at finish")
            )

        # Sales record
        if p.sold_to:
            snapshot_rows.append(
                (
                    "Sales documentation (§ 205.103)",
                    "PASS",
                    f"Sold to: {_truncate(p.sold_to, 50)}; organic on invoice = {'Yes' if p.organic_on_invoice else 'No'}",
                )
            )
        else:
            snapshot_rows.append(("Sales documentation (§ 205.103)", "REVIEW", "Add buyer + organic-on-invoice flag"))

        # Contamination — § 205.272 is the commingling/contact-with-prohibited-substance
        # prevention practice standard. § 205.201(b) is the OSP-substitution clause and
        # is NOT the correct cite for contamination incident logs.
        if not contamination_events:
            snapshot_rows.append(
                (
                    "Contamination log (§ 205.272)",
                    "PASS",
                    "Contamination incidents logged this period: 0 (logging system active)",
                )
            )
        elif contamination_with_action == len(contamination_events):
            snapshot_rows.append(
                (
                    "Contamination log (§ 205.272)",
                    "PASS",
                    f"{len(contamination_events)} incident(s); all have corrective action + certifier notified",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Contamination log (§ 205.272)",
                    "FAIL",
                    f"{contamination_with_action}/{len(contamination_events)} incidents complete — finish corrective action + notify certifier",
                )
            )

        # Land requirements (§ 205.202) — 36-month transition. Under NOP, an
        # organic certification is only issued once a land parcel has completed
        # its 3-year transition, so an ACTIVE verified organic cert covering the
        # production period is evidence of transition compliance. Self-reported
        # certs get REVIEW (transition not independently verified via the USDA
        # Organic Integrity Database). We do NOT parse OSP narrative text.
        est_for_land = None
        try:
            est_for_land = self.production.parcel.establishment
        except AttributeError:
            est_for_land = None
        if est_for_land is not None:
            from certifications.models import Certification as _Cert

            prod_start = self.production.start_date.date() if self.production.start_date else date.today()
            # Certification.certification_type stores enum keys (e.g. "usda_organic",
            # "ccof", "roc") — NOT display labels. An icontains="organic" match
            # would miss CCOF / CNG / ROC because their keys don't contain the
            # string "organic". Explicit allow-list of organic-conferring cert
            # types keeps the check accurate as new types are added.
            ORGANIC_CERT_TYPES = (
                "usda_organic",
                "ccof",
                "cng",
                "real_organic_project",
                "roc",
            )
            organic_certs = list(
                _Cert.objects.filter(
                    establishment=est_for_land,
                    certification_type__in=ORGANIC_CERT_TYPES,
                ).order_by("effective_date")
            )
            covering = [
                c
                for c in organic_certs
                if c.is_active
                and c.effective_date
                and c.effective_date <= prod_start
                and (not c.expiry_date or c.expiry_date >= prod_start)
            ]
            if covering:
                verified = [c for c in covering if c.verification_status == "verified"]
                if verified:
                    earliest = min((c.effective_date for c in verified))
                    snapshot_rows.append(
                        (
                            "Land requirements (§ 205.202)",
                            "PASS",
                            f"Certified organic since {earliest.isoformat()} (USDA OID verified) — 36-month transition complete",
                        )
                    )
                else:
                    earliest = min((c.effective_date for c in covering))
                    snapshot_rows.append(
                        (
                            "Land requirements (§ 205.202)",
                            "REVIEW",
                            f"Self-reported organic cert since {earliest.isoformat()} — confirm transition via USDA OID and OSP (a)(6)",
                        )
                    )
            else:
                snapshot_rows.append(
                    (
                        "Land requirements (§ 205.202)",
                        "REVIEW",
                        "No active organic certification covering production period — confirm 36-month transition in OSP (a)(6)",
                    )
                )

        # OFPP (§ 205.201(a)(3)) — page-1 signal. A suspicious-filename upload
        # is a harder FAIL than "not uploaded" because it looks compliant at a
        # glance. Inspector must open the document to confirm.
        ofpp_flags = self._ofpp_flags()
        if not ofpp_flags["establishment"]:
            pass  # no snapshot row when establishment missing — covered elsewhere
        elif not ofpp_flags["uploaded"]:
            snapshot_rows.append(
                (
                    "OFPP (§ 205.201(a)(3))",
                    "FAIL",
                    "No Organic Fraud Prevention Plan on file — required under SOE 2024",
                )
            )
        elif ofpp_flags["filename_suspicious"]:
            snapshot_rows.append(
                (
                    "OFPP (§ 205.201(a)(3))",
                    "FAIL",
                    f"Uploaded file <{ofpp_flags['doc_name']}> matches the "
                    "misfiled-invoice pattern. Trazo treats this as a missing "
                    "Organic Fraud Prevention Plan — SOE 2024 requires a "
                    "substantive plan with vulnerability assessment + monitoring "
                    "procedures; no certification without one.",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "OFPP (§ 205.201(a)(3))",
                    "PASS",
                    f"Uploaded {ofpp_flags['date_str']}: {ofpp_flags['doc_name']}",
                )
            )

        # Documentation depth — all 7 event types + photos total. PASS at 10+
        # photos is a reasonable floor for a 22-event organic production; below
        # that, an inspector will likely ask for more visual evidence.
        snapshot_rows.append(
            (
                "Documentation depth",
                "PASS" if photos_total >= 10 else "REVIEW",
                f"{len(all_events)} events, {photos_total} photos",
            )
        )

        header = [
            Paragraph(
                "<b>Compliance check</b>",
                ParagraphStyle("snap_h1", parent=self._styles["body"], fontSize=8, fontName="Helvetica-Bold"),
            ),
            Paragraph(
                "<b>Status</b>",
                ParagraphStyle(
                    "snap_h2", parent=self._styles["body"], fontSize=8, fontName="Helvetica-Bold", alignment=TA_CENTER
                ),
            ),
            Paragraph(
                "<b>Detail</b>",
                ParagraphStyle("snap_h3", parent=self._styles["body"], fontSize=8, fontName="Helvetica-Bold"),
            ),
        ]
        # Section-lookup table: when a snapshot row is NOT PASS, the inspector
        # needs a deterministic pointer to the section that carries the full
        # evidence. Without this, a FAIL row on page 1 reads as an unresolved
        # finding rather than a "see page N" breadcrumb. Key is the row label
        # as written above; value is the downstream section header text.
        section_hint_by_label = {
            "Organic System Plan (§ 205.201)": "Organic System Plan section",
            "Unapproved-input findings (§ 205.400(f)(2))": "Unapproved-Input Findings section",
            "Input traceability (§ 205.103)": "Chemical Log section",
            "Compost (§ 205.203(c)(2))": "Soil Management section",
            "Raw manure interval (§ 205.203(c)(1))": "Soil Management section",
            "Raw manure interval (§ 205.203(c)(1)(ii))": "Soil Management section",
            "Raw manure interval (§ 205.203(c)(1)(iii))": "Soil Management section",
            "Contamination log (§ 205.272)": "General Documentation section",
            "Land requirements (§ 205.202)": "Farm Overview section",
            "OFPP (§ 205.201(a)(3))": "SOE Compliance Status section",
            "Lot traceability (§ 205.307 / § 205.103(b)(2))": "Traceability section",
            "Documentation depth": "Event logs + Photo Evidence sections",
        }
        table_data = [header]
        for label, status, detail in snapshot_rows:
            hint = None
            if status != "PASS":
                hint_candidate = section_hint_by_label.get(label)
                if hint_candidate and hint_candidate.lower() not in (detail or "").lower():
                    hint = hint_candidate
            if hint:
                detail_cell = detail_paragraph_with_hint(detail, f"see {hint}")
            else:
                detail_cell = detail_paragraph(detail)
            table_data.append(
                [
                    detail_paragraph(label),
                    status_paragraph(status),
                    detail_cell,
                ]
            )

        col_widths = [2.6 * inch, 0.7 * inch, 3.7 * inch]
        snap_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        snap_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), TRAZO_GREEN),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("ALIGN", (0, 0), (-1, 0), "LEFT"),
                    ("ALIGN", (1, 0), (1, 0), "CENTER"),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                    ("TOPPADDING", (0, 0), (-1, 0), 4),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
                    ("GRID", (0, 0), (-1, -1), 0.4, MID_GRAY),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 1), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
                ]
            )
        )

        return [
            Paragraph(
                "<b>Compliance Snapshot</b> — auditor pre-read",
                ParagraphStyle(
                    "snap_title",
                    parent=self._styles["section_header"],
                    fontSize=11,
                    spaceBefore=2,
                    spaceAfter=4,
                ),
            ),
            snap_table,
            Paragraph(
                "PASS = compliant. REVIEW = needs inspector attention. FAIL = blocking finding likely. "
                "Each row links to its source section in the body of this report.",
                self._styles["footer_note"],
            ),
        ]

    # ------------------------------------------------------------------
    # Pre-Export Consistency Check — cross-references production header
    # fields against the raw event stream. An inspector conducting a
    # supply-chain traceability audit (§ 205.501(a)(21)) will ask:
    #   - "Your sales invoice says 1700 boxes × 25 lb = 42,500 lb but your
    #      packing-shed event says 1500 cartons. Which is on the lot?"
    #   - "Your Production record says lot SV-AVO-2026-001 but your packing-
    #      shed event narrative says SVR-2026-HA-001. Which is on the boxes?"
    #   - "Your sales record says Whole Foods but your post-harvest narrative
    #      says OGC pickup. How many channels is this fruit moving through?"
    # Trazo's value-add is catching these before the certifier does.
    # ------------------------------------------------------------------

    # Tolerance for the harvest-yield vs event-narrative cross-check.
    # Field-to-narrative deltas are common (thinning estimates vs post-
    # thinning yields, drying losses, carrier-weight rounding). ±15% leaves
    # room for that without tolerating an order-of-magnitude mismatch.
    CONSISTENCY_YIELD_TOLERANCE = 0.15

    @staticmethod
    def _extract_pound_values(text: str):
        """
        Extract numbers quoted in 'lb' / 'lbs' / 'pound(s)' from a free-text
        description. Handles commas ("45,000 lb"), decimals ("11,200.5 lbs"),
        and mixed unit adjacency. Returns a list of floats. Used by the
        consistency linter to find yield claims inside event narratives.
        """
        import re

        if not text:
            return []
        values = []
        # Match e.g. "45,000 lb", "11200 lbs", "5,080 kg (11,200 pounds)"
        pattern = re.compile(
            r"(\d[\d,]*(?:\.\d+)?)\s*(?:lb|lbs|pound|pounds)\b",
            re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            try:
                values.append(float(m.group(1).replace(",", "")))
            except ValueError:
                continue
        return values

    @staticmethod
    def _extract_lot_ids(text: str):
        """
        Pull lot-ID-shaped tokens from a narrative (``Lot: <ID>`` or common
        alphanumeric prefixes like ``SV-AVO-`` / ``SVR-`` seen on Solana
        Verde packing labels). Case-insensitive. Used by the consistency
        linter so an event that mentions a different lot ID than the
        production record triggers a finding.
        """
        import re

        if not text:
            return []
        # "Lot: <token>" explicit mentions — strongest signal
        explicit = re.findall(r"[Ll]ot\s*[:#]\s*([A-Z0-9][A-Z0-9\-]{4,})", text)
        return [tok.strip() for tok in explicit]

    def _build_consistency_findings(self):
        """
        Run cross-consistency checks and return a list of flowables for the
        cover page. Returns an empty list when everything reconciles — an
        all-clean PDF shows only the Compliance Snapshot, no additional
        section. When one or more checks fail, a small table surfaces each
        finding with its source and the two conflicting values.
        """
        p = self.production
        findings = []

        # ---------- Check 1: yield reconciliation -------------------------
        # Production header yield vs the yield numbers appearing in harvest
        # event descriptions. Only flag when the delta exceeds the
        # tolerance — normal shrinkage / rounding is tolerated. Harvest
        # events are ProductionEvent rows with type == "HA"; the
        # WeatherEvent code "HH" (High Humidity) is a distinct model and
        # MUST NOT be mixed in here — an earlier draft did, with no
        # effective harm since production events cannot have type "HH",
        # but the test reads wrong.
        harvest_events = [ev for ev in p.history_productionevent_events.all() if ev.type == "HA"]
        narrative_yields = []
        for ev in harvest_events:
            narrative_yields.extend(self._extract_pound_values(ev.description or ""))
        header_yield_lb = None
        if p.production_amount and p.production_unit:
            unit = str(p.production_unit).lower().strip()
            if unit in ("lb", "lbs", "pound", "pounds"):
                header_yield_lb = float(p.production_amount)
            elif unit in ("kg", "kilogram", "kilograms"):
                header_yield_lb = float(p.production_amount) * 2.20462
            elif unit in ("t", "ton", "tons"):
                # Short ton (US) = 2000 lb. We do NOT attempt to detect
                # metric tonne here — ambiguous unit label; skip rather
                # than guess and risk a false-positive finding.
                header_yield_lb = float(p.production_amount) * 2000.0
        if header_yield_lb and narrative_yields:
            # Smart-match: pick the narrative value CLOSEST to the header
            # yield, not the MAX. A farmer's narrative may legitimately
            # quote multiple sub-totals ("Field A: 25,000 lb, Field B:
            # 20,000 lb, total 45,000 lb") and MAX would arbitrarily pick
            # the largest regardless of whether a matching total appears.
            # Closest-match gives the benefit of the doubt — flag only
            # when NO narrative value lands within tolerance of the header.
            closest = min(narrative_yields, key=lambda v: abs(v - header_yield_lb))
            delta_pct = abs(closest - header_yield_lb) / header_yield_lb
            if delta_pct > self.CONSISTENCY_YIELD_TOLERANCE:
                # Report the full spread so the farmer sees what the
                # linter saw. Deduplicate + sort for stable output.
                unique_sorted = sorted({int(round(v)) for v in narrative_yields})
                narrative_summary = ", ".join(f"{v:,}" for v in unique_sorted)
                findings.append(
                    (
                        "Yield reconciliation",
                        (
                            f"Production header: {int(header_yield_lb):,} lb · "
                            f"Harvest-event narrative value(s): {narrative_summary} lb · "
                            f"closest delta {delta_pct * 100:.1f}% (tolerance ±"
                            f"{int(self.CONSISTENCY_YIELD_TOLERANCE * 100)}%)"
                        ),
                    )
                )

        # ---------- Check 2: quantity_sold vs packed-carton narrative ------
        # quantity_sold × box_weight should match the carton count mentioned
        # in the post-harvest event description. A mismatch means the
        # packing-shed log and the sales invoice are telling different
        # stories — exactly what a supply-chain traceability audit asks.
        import re

        ph_events = [ev for ev in p.history_productionevent_events.all() if ev.type == "PH"]
        if ph_events and p.quantity_sold and p.box_weight_lb:
            sold_lb_equivalent = float(p.quantity_sold) * float(p.box_weight_lb)
            narrative_cartons = []
            for ev in ph_events:
                for m in re.finditer(r"(\d[\d,]*)\s*(?:cartons?|boxes)", ev.description or "", re.IGNORECASE):
                    try:
                        narrative_cartons.append(int(m.group(1).replace(",", "")))
                    except ValueError:
                        continue
            if narrative_cartons and sold_lb_equivalent:
                # Use closest-match to the sold total for the same reason
                # as the yield check: a PH narrative may quote pallet /
                # batch sub-totals as well as the grand total, and MAX
                # would pick the largest regardless of whether a matching
                # total is present.
                sold_boxes_equivalent = sold_lb_equivalent / float(p.box_weight_lb)
                closest_cartons = min(narrative_cartons, key=lambda v: abs(v - sold_boxes_equivalent))
                packed_lb = closest_cartons * float(p.box_weight_lb)
                delta_pct = abs(packed_lb - sold_lb_equivalent) / sold_lb_equivalent
                if delta_pct > self.CONSISTENCY_YIELD_TOLERANCE:
                    unique_sorted = sorted(set(narrative_cartons))
                    narrative_summary = ", ".join(f"{v:,}" for v in unique_sorted)
                    findings.append(
                        (
                            "Packed cartons vs sold quantity",
                            (
                                f"Packing-shed narrative: {narrative_summary} cartons · "
                                f"closest match {closest_cartons:,} × {float(p.box_weight_lb):g} lb "
                                f"= {int(packed_lb):,} lb · "
                                f"Sales record: {p.quantity_sold} {p.quantity_sold_unit or 'units'} × "
                                f"{float(p.box_weight_lb):g} lb = {int(sold_lb_equivalent):,} lb · "
                                f"delta {delta_pct * 100:.1f}%"
                            ),
                        )
                    )

        # ---------- Check 3: lot ID in production vs event narratives ------
        header_lot = (p.lot_id or "").strip()
        if header_lot:
            lot_mismatches = set()
            for ev in p.history_productionevent_events.all():
                for tok in self._extract_lot_ids(ev.description or ""):
                    if tok.upper() != header_lot.upper():
                        lot_mismatches.add(tok)
            if lot_mismatches:
                findings.append(
                    (
                        "Lot ID consistency (§ 205.307)",
                        (
                            f"Production record lot: {header_lot} · "
                            f"Other lot ID(s) in event narratives: "
                            f"{', '.join(sorted(lot_mismatches))}. "
                            "Inspector will ask which lot is on the non-retail containers."
                        ),
                    )
                )

        # ---------- Check 4: drift-response notification delay -------------
        # § 205.400(f)(1) requires the producer to notify the certifying
        # agent "immediately" when a prohibited substance has been applied
        # or come into contact with a certified operation. A multi-day gap
        # between the incident date and the certifier-notified date is the
        # kind of finding a CCOF inspector would circle in red even if the
        # corrective action was eventually taken. Surface the gap here so
        # the farmer addresses it BEFORE the inspector does. 3-day threshold
        # is lenient — "immediately" reasonably accommodates a weekend plus
        # a verification phone call. Longer than that needs a why.
        try:
            contamination_incidents = [
                ev for ev in p.history_generalevent_events.filter(is_contamination_incident=True)
            ]
        except Exception:  # noqa: BLE001 — linter degrades to no finding
            contamination_incidents = []
        notify_delay_rows = []
        from datetime import date as _date
        from datetime import datetime as _datetime

        for cev in contamination_incidents:
            incident_date = getattr(cev, "date", None)
            notify_date = getattr(cev, "certifier_notification_date", None)
            if incident_date is None or notify_date is None:
                continue
            # ``CommonEvent.date`` is a datetime; ``certifier_notification_date``
            # is a date. Subtracting datetime from date raises TypeError, so
            # we MUST explicitly downcast datetime → date. Note that
            # ``isinstance(datetime_obj, date)`` returns True (datetime is a
            # subclass of date), so a ``not isinstance(..., type(notify_date))``
            # branch would silently skip the conversion and hide this bug —
            # do the conversion unconditionally based on the concrete type.
            if isinstance(incident_date, _datetime):
                incident_date = incident_date.date()
            if not isinstance(incident_date, _date) or not isinstance(notify_date, _date):
                continue
            try:
                gap_days = (notify_date - incident_date).days
            except Exception:  # noqa: BLE001 — odd date types shouldn't kill the linter
                continue
            if gap_days > 3:
                notify_delay_rows.append((cev, gap_days, incident_date, notify_date))
        if notify_delay_rows:
            # One row per incident so the inspector sees each gap distinctly.
            for cev, gap_days, incident_date, notify_date in notify_delay_rows:
                source = ""
                try:
                    if cev.contamination_source:
                        source = cev.get_contamination_source_display()
                except Exception:
                    source = ""
                source_suffix = f" ({source})" if source else ""
                findings.append(
                    (
                        "Drift-response notification delay (§ 205.400(f)(1))",
                        (
                            f"Contamination incident {incident_date}{source_suffix} · "
                            f"certifier notified {notify_date} · gap {gap_days} days. "
                            "§ 205.400(f)(1) requires 'immediately.' Inspector will ask "
                            "why the delay — document the reason in the event record."
                        ),
                    )
                )

        # ---------- Check 5: downstream handler consistency ----------------
        # sold_to (sales record) should match any handler named in the OSP
        # (a)(5) commingling narrative AND any handler/pickup mentioned in
        # the post-harvest event narrative. Detect mismatched distributor /
        # retailer names — the classic "packing says OGC, sales says Whole
        # Foods" signal.
        sold_to = (p.sold_to or "").strip()
        if sold_to:
            handler_tokens = set()
            # Scan post-harvest narratives for "<Name> pickup" or
            # "delivery to <Name>" — simple tokeniser that looks for a
            # capitalised two-word name adjacent to a handler verb.
            # The verb portion uses an inline (?i:...) case-insensitive
            # group so "Transport" / "transport" / "Delivery" / "delivery"
            # all match, while the capture group stays case-sensitive —
            # we need "[A-Z][A-Za-z&]+" to match Capitalized words only,
            # otherwise a phrase like "Transport to Mission Produce uses
            # Missions" swallows the lowercase "uses" and captures four
            # words instead of the intended two.
            handler_verbs = re.compile(
                r"(?i:pickup by|pickup on [^\n]{0,30}?by|delivery to|shipped to|transport(?:ed)? to)\s+"
                r"([A-Z][A-Za-z&]+(?:\s+[A-Z][A-Za-z&]+){0,3})",
            )
            pickup_verbs = re.compile(
                r"([A-Z][A-Za-z&]+(?:\s+[A-Z][A-Za-z&]+){0,3})\s+(?i:pickup)\b",
            )
            for ev in ph_events:
                text = ev.description or ""
                for m in handler_verbs.finditer(text):
                    handler_tokens.add(m.group(1).strip())
                for m in pickup_verbs.finditer(text):
                    handler_tokens.add(m.group(1).strip())
            # Also pull from OSP (a)(5) commingling narrative if available
            try:
                establishment = p.parcel.establishment
                from certifications.models import OrganicSystemPlan

                osp = (
                    OrganicSystemPlan.objects.filter(establishment=establishment, status="active")
                    .order_by("-version_number")
                    .first()
                )
                if osp:
                    a5 = (osp.sections or {}).get("commingling_barriers", {}).get("narrative", "") or ""
                    for m in handler_verbs.finditer(a5):
                        handler_tokens.add(m.group(1).strip())
                    for m in pickup_verbs.finditer(a5):
                        handler_tokens.add(m.group(1).strip())
            except Exception:  # noqa: BLE001 — linter must never crash the PDF
                pass

            def _normalise(s: str) -> str:
                return re.sub(r"[^a-z0-9]", "", s.lower())

            sold_to_norm = _normalise(sold_to)
            handler_mismatches = [
                tok
                for tok in handler_tokens
                # Treat a handler as consistent if it is referenced in
                # (or references) the sold_to string — handles "Mission
                # Produce → Whole Foods" chains where Mission is the
                # intermediate handler and Whole Foods is the retailer.
                if _normalise(tok) not in sold_to_norm and sold_to_norm not in _normalise(tok)
            ]
            # Flag only when ≥2 distinct handler names appear that do not
            # match the sales-record retailer. A single-handler mismatch
            # (e.g. "Mission Produce" as the intermediate handler with
            # Whole Foods as the retailer) is usually a legitimate
            # handoff chain, not a discrepancy — the farmer names the
            # handler in OSP (a)(5) and mentions them at packing-shed
            # pickup, which is exactly the correct paper trail. Two or
            # more distinct non-retailer names is the channel-confusion
            # signal we actually want ("packing says OGC, OSP says
            # Mission, sales says Whole Foods" = three channels = ask).
            if handler_mismatches and len(handler_mismatches) >= 2:
                findings.append(
                    (
                        "Handler chain (§ 205.201(a)(5))",
                        (
                            f"Sales record: {sold_to} · "
                            f"Other handler(s) named in event/OSP narratives: "
                            f"{', '.join(sorted(set(handler_mismatches)))}. "
                            "Confirm the handoff chain with the inspector."
                        ),
                    )
                )

        # ---------- Check 6: manure interval vs crop-rule consistency -----
        # Per eCFR 7 CFR 205.203(c)(1), the required pre-harvest interval is
        # determined by whether the edible portion contacts the soil:
        # (c)(1)(ii) 120 days when it does, (c)(1)(iii) 90 days when it
        # does not. Farmers enter their interval selection directly on the
        # SoilManagementEvent form; a mismatch between what the farmer
        # selected and what the crop's soil-contact flag dictates is a
        # classic inspector-will-flag signal ("operator doesn't understand
        # their own practice standard"). Surface it here so the producer
        # fixes it before the inspection.
        try:
            from history.models import SoilManagementEvent

            manure_events_strict = list(
                SoilManagementEvent.objects.filter(
                    history_id=getattr(p, "id", None),
                )
                .exclude(manure_harvest_interval__in=["", "na"])
                .exclude(manure_harvest_interval__isnull=True)
            )
        except Exception:  # noqa: BLE001 — linter must not kill the PDF
            manure_events_strict = []
        if manure_events_strict:
            rule = self._manure_interval_rule_for_crop()
            expected_days = rule["days"]  # 90 or 120
            expected_cite = rule["cite"]
            # Build a label describing what the crop rule dictates so the
            # finding text reads as a question the inspector would ask.
            if expected_days == 90:
                crop_description = "tree / canopy crop (edible portion does NOT contact soil)"
            else:
                crop_description = "soil-contact crop (edible portion has direct contact with soil)"
            mismatched = []
            for mev in manure_events_strict:
                try:
                    farmer_days = int(mev.manure_harvest_interval)
                except (TypeError, ValueError):
                    continue
                if farmer_days != expected_days:
                    mismatched.append((mev, farmer_days))
            if mismatched:
                # One row per mismatched event so the farmer sees each
                # date/interval distinctly. Keeps the finding actionable.
                for mev, farmer_days in mismatched:
                    event_date = getattr(mev, "date", None)
                    event_date_str = (
                        event_date.date().isoformat()
                        if hasattr(event_date, "date")
                        else (event_date.isoformat() if event_date else "unknown date")
                    )
                    findings.append(
                        (
                            f"Manure interval vs crop rule ({expected_cite})",
                            (
                                f"Soil event {event_date_str}: farmer selected "
                                f"{farmer_days}-day interval. Crop rule derived "
                                f"from {expected_cite} requires {expected_days}-day "
                                f"interval for this production — "
                                f"{crop_description}. Inspector will ask why the "
                                "selected interval does not match the crop's "
                                "soil-contact classification."
                            ),
                        )
                    )

        # ---------- Check 7: OSP narrative cert-continuity vs metadata ----
        # When the OSP narrative claims "since YEAR" or "first certified
        # YEAR" (a transition / 36-month-history / continuous-management
        # claim under § 205.401(c) or § 205.202), and that year does NOT
        # match the earliest certification on file, an inspector reads it
        # as either (a) a record-keeping gap (the cert metadata is
        # incomplete) or (b) an unsupported land-eligibility claim. Either
        # way it is a question the producer must be ready to answer.
        # Tolerance: ±1 year — a "since 2012" narrative against a 2013
        # cert is well within the rounding farmers use when speaking
        # casually; a 6-year gap (2012 vs 2018) is the signal we want.
        try:
            from certifications.models import Certification as _Cert
            from certifications.models import OrganicSystemPlan as _OSP

            est_for_cert = p.parcel.establishment
        except Exception:  # noqa: BLE001
            est_for_cert = None
        if est_for_cert is not None:
            # Earliest cert effective_date on file (active or historical) —
            # represents the operation's documented certification chain.
            try:
                earliest_cert_date = None
                for c in _Cert.objects.filter(establishment=est_for_cert).only("effective_date"):
                    if c.effective_date is None:
                        continue
                    if earliest_cert_date is None or c.effective_date < earliest_cert_date:
                        earliest_cert_date = c.effective_date
            except Exception:  # noqa: BLE001
                earliest_cert_date = None
            if earliest_cert_date is not None:
                # Pull narrative text we already need to scan. Look at the
                # active OSP's (a)(1) / (a)(6) sections specifically.
                narrative_text = ""
                try:
                    osp = (
                        _OSP.objects.filter(establishment=est_for_cert, status="active")
                        .order_by("-version_number")
                        .first()
                    )
                    if osp:
                        secs = osp.sections or {}
                        for key in ("practices_procedures", "additional_certifier_info"):
                            sec = secs.get(key) or {}
                            narrative_text += " " + (sec.get("narrative", "") or "")
                except Exception:  # noqa: BLE001
                    narrative_text = ""
                # Match certification-context year claims ONLY. Bare "since
                # 2012" is too loose — a farmer saying "using drip
                # irrigation since 2020" is NOT making a cert-continuity
                # claim and would false-positive. We require the year to
                # sit alongside a word that unambiguously anchors the
                # claim to certification / organic status: "first
                # certified", "first certified in", "certified organic",
                # "organic since", "certified since". Years 1990-2099.
                year_pattern = re.compile(
                    r"(?i:\b(?:first\s+certified(?:\s+in)?|certified\s+organic|organic\s+since|certified\s+since)\s+)(\d{4})\b"
                )
                narrative_years = []
                for m in year_pattern.finditer(narrative_text):
                    try:
                        y = int(m.group(1))
                        if 1990 <= y <= 2099:
                            narrative_years.append(y)
                    except ValueError:
                        continue
                if narrative_years:
                    # Smallest narrative year is the strongest claim
                    # ("since 2012" beats "since 2015" — they imply each
                    # other but 2012 is the load-bearing assertion).
                    earliest_narrative_year = min(narrative_years)
                    earliest_cert_year = earliest_cert_date.year
                    delta_years = earliest_cert_year - earliest_narrative_year
                    # Flag only when narrative reaches MORE than 1 year
                    # earlier than the metadata. The reverse direction
                    # (cert older than narrative claim) is normal — a
                    # producer may simply not have updated the OSP text.
                    if delta_years > 1:
                        findings.append(
                            (
                                "Cert continuity vs OSP narrative (\u00a7 205.401(c))",
                                (
                                    f"OSP narrative claims continuous organic "
                                    f"management / first-certified year "
                                    f"{earliest_narrative_year}; earliest "
                                    f"certification on file is "
                                    f"{earliest_cert_date.isoformat()} "
                                    f"({delta_years}-year gap). \u00a7 205.401(c) "
                                    "requires a history of previous applications. "
                                    "Either upload the missing certificate(s) "
                                    "from the gap years or update the OSP "
                                    "narrative to match the documented chain."
                                ),
                            )
                        )

        # ---------- Render ------------------------------------------------
        if not findings:
            return []

        header = [
            Paragraph(
                "<b>Check</b>",
                ParagraphStyle("cons_h1", parent=self._styles["body"], fontSize=8, fontName="Helvetica-Bold"),
            ),
            Paragraph(
                "<b>Detail</b>",
                ParagraphStyle("cons_h2", parent=self._styles["body"], fontSize=8, fontName="Helvetica-Bold"),
            ),
        ]
        cell_style = ParagraphStyle("cons_cell", parent=self._styles["body"], fontSize=8, leading=10)
        table_data = [header]
        for label, detail in findings:
            table_data.append(
                [
                    Paragraph(self._safe_narrative(label), cell_style),
                    Paragraph(self._safe_narrative(detail), cell_style),
                ]
            )
        col_widths = [2.2 * inch, 4.8 * inch]
        cons_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        cons_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E65100")),  # orange "review"
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("ALIGN", (0, 0), (-1, 0), "LEFT"),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                    ("TOPPADDING", (0, 0), (-1, 0), 4),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
                    ("GRID", (0, 0), (-1, -1), 0.4, MID_GRAY),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 1), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
                ]
            )
        )
        return [
            Paragraph(
                "<b>Pre-Export Consistency Check</b> — cross-reference against event stream",
                ParagraphStyle(
                    "cons_title",
                    parent=self._styles["section_header"],
                    fontSize=11,
                    spaceBefore=2,
                    spaceAfter=4,
                ),
            ),
            cons_table,
            Paragraph(
                "These findings cross-check the production header (yield, sales, lot, handler) "
                "against what the individual event narratives actually say. Resolve each row "
                "before handing this PDF to a certifier — under SOE § 205.103(b)(2) and § 205.501(a)(21), "
                "a supply-chain traceability audit will ask the same questions. Trazo's value-add is "
                "catching these gaps first. An empty section (no findings shown) means all cross-checks passed.",
                self._styles["footer_note"],
            ),
        ]

    # ------------------------------------------------------------------
    # Section 2: Farm Overview
    # ------------------------------------------------------------------

    def _build_farm_overview(self):
        p = self.production
        elements = [self._section_header("Farm Overview")]

        try:
            est = p.parcel.establishment
        except AttributeError:
            elements.append(self._body("Farm data not available."))
            return elements

        # Rows required by § 205.400(a): operator legal identity + contact info.
        # Render blanks as "(not provided)" rather than em-dash so an inspector
        # sees an explicit disclosure gap instead of ambiguous silence.
        required_contact_rows = [
            ("Farm Name", est.name),
            ("Address", est.address),
            ("City", est.city),
            ("State / Province", est.state),
            ("Country", est.country),
            ("Contact Person", est.contact_person),
            ("Contact Phone", est.contact_phone),
            ("Contact Email", est.contact_email or est.email),
        ]
        optional_rows = [
            (
                "GPS Coordinates",
                f"{est.latitude}, {est.longitude}" if est.latitude and est.longitude else None,
            ),
            ("Total Acreage", f"{est.total_acreage} acres" if est.total_acreage else None),
            ("Farming Method", est.farming_method),
            # "Certifications" legacy text field — suppressed here because the
            # structured Active Certification Summary table renders the real data.
            # Leaving this row would duplicate and confuse.
            ("Year Established", str(est.year_established) if est.year_established else None),
        ]

        def _render(label, value, required):
            if not value:
                shown = "(not provided)" if required else "\u2014"
            else:
                shown = value
            elements.append(self._label_value(label, shown))

        for label, value in required_contact_rows:
            _render(label, value, required=True)
        for label, value in optional_rows:
            _render(label, value, required=False)

        return elements

    # ------------------------------------------------------------------
    # Section 3: Production Summary
    # ------------------------------------------------------------------

    def _build_production_summary(self):
        p = self.production
        elements = [self._section_header("Production Summary")]

        crop_name = ""
        try:
            crop_name = p.crop_type.name if p.crop_type else (p.product.name if p.product else "")
        except AttributeError:
            pass

        parcel_name = ""
        parcel_area = ""
        try:
            parcel_name = p.parcel.name
            parcel_area = f"{p.parcel.area} ha" if p.parcel.area else ""
        except AttributeError:
            pass

        rows = [
            ("Production Name", p.name),
            ("Crop Type", crop_name),
            ("Parcel", parcel_name),
            ("Parcel Area", parcel_area),
            ("Start Date", _fmt_date(p.start_date)),
            ("Expected Harvest", _fmt_date(p.expected_harvest)),
            ("Finish Date", _fmt_date(p.finish_date)),
            ("Lot ID", p.lot_id),
            (
                "Harvest Amount",
                f"{_fmt_float(p.production_amount)} {_val(p.production_unit, '')}" if p.production_amount else None,
            ),
            ("Quality Grade", p.get_quality_grade_display() if p.quality_grade else None),
            ("Harvest Method", p.get_harvest_method_display() if p.harvest_method else None),
            ("Production Method", p.get_production_method_display() if p.production_method else None),
        ]
        # Transparency Score is a Trazo product metric (self-reported
        # engagement signal), not a regulatory quantity. Suppress it in the
        # NOP organic export so a CCOF inspector doesn't read it as a
        # compliance grade. It still appears in the "all" / consumer-facing
        # exports where that confusion doesn't apply.
        if self.certification_type != "organic":
            rows.append(
                ("Transparency Score", f"{_fmt_float(p.transparency_score, 1)}%" if p.transparency_score else None)
            )

        for label, value in rows:
            elements.append(self._label_value(label, value))

        return elements

    # ------------------------------------------------------------------
    # Section 4: Input Application Log (Chemical Events)
    # ------------------------------------------------------------------

    def _build_chemical_log(self):
        """
        Input Application Log — 7 CFR 205.103(b)(1) compliant.

        Auditor-facing table with two parts:
        1. Application details: what was applied, where, how, and compliance fields
        2. NOP supplier/purchase traceability: links each application to a purchase
           record for mass-balance cross-reference (top non-conformance finding)
        """
        elements = [self._section_header("Input Application Log")]

        events = list(self.production.history_chemicalevent_events.all().order_by("date"))

        if not events:
            elements.append(
                self._empty_table(
                    ["Date", "Product", "Type", "NPK / Conc.", "Amount", "Area", "Method", "Organic Status"]
                )
            )
            return elements

        # --- Table 1: Application Details (primary audit record) ---
        app_headers = [
            "Date",
            "Product",
            "Type",
            "NPK / Conc.",
            "Amount",
            "Area",
            "Method",
            "Target",
            "Organic Status",
        ]

        # Add EPA/WPS columns for organic and globalgap certifications
        if self.certification_type in ("organic", "globalgap", "roc", "all"):
            app_headers.extend(["REI (hrs)", "PHI (days)", "Buffer (m)"])

        # 7 CFR 205.206 + EPA WPS — restricted-use materials require EPA reg #
        # documentation for organic and ROC inspections, not just GlobalG.A.P.
        # RUP flag (40 CFR 152.175): inspectors cross-check restricted-use
        # materials against the applicator certification in Table 2.
        if self.certification_type in ("organic", "globalgap", "roc", "all"):
            app_headers.append("EPA Reg #")
            app_headers.append("RUP")

        app_header_row = [self._hdr(h) for h in app_headers]
        app_data = [app_header_row]

        for ev in events:
            amount = ""
            if ev.volume_numeric:
                amount = f"{_fmt_float(ev.volume_numeric)} {_val(ev.volume_unit, '')}"
            elif ev.volume:
                amount = _val(ev.volume)

            area = ""
            if ev.area_numeric:
                area = f"{_fmt_float(ev.area_numeric)} {_val(ev.area_unit, '')}"
            elif ev.area:
                area = _val(ev.area)

            # Use structured application method with fallback to legacy field
            method = ev.application_method_structured or ev.way_of_application

            row = [
                self._cell(_fmt_date(ev.date)),
                self._cell(ev.commercial_name, 40),
                self._cell(CHEMICAL_TYPE_LABELS.get(ev.type, _val(ev.type))),
                self._cell(ev.concentration),
                self._cell(amount or None),
                self._cell(area or None),
                self._cell(method),
                self._cell(ev.target_pest_disease, 40),
                self._cell(ev.get_organic_approved_display() if ev.organic_approved else None),
            ]

            if self.certification_type in ("organic", "globalgap", "roc", "all"):
                row.append(self._cell(str(ev.rei_hours) if ev.rei_hours is not None else None))
                row.append(self._cell(str(ev.phi_days) if ev.phi_days is not None else None))
                row.append(self._cell(_fmt_float(ev.buffer_zone_meters) if ev.buffer_zone_meters is not None else None))

            if self.certification_type in ("organic", "globalgap", "roc", "all"):
                row.append(self._cell(ev.epa_registration_number))
                row.append(self._cell("Yes" if ev.restricted_use_pesticide else None))

            app_data.append(row)

        # Dynamic column widths based on columns present
        # Target total <=7.0" (letter portrait, 0.75" margins). Globalgap+all cert
        # packs the most columns and must still fit — trimmed Target + EPA Reg to budget.
        base_widths = [
            0.55 * inch,  # Date
            0.9 * inch,  # Product
            0.5 * inch,  # Type
            0.55 * inch,  # NPK / Conc.
            0.55 * inch,  # Amount
            0.45 * inch,  # Area
            0.55 * inch,  # Method
            0.65 * inch,  # Target
            0.55 * inch,  # Organic
        ]
        if self.certification_type in ("organic", "globalgap", "roc", "all"):
            base_widths.extend([0.4 * inch, 0.4 * inch, 0.4 * inch])  # REI, PHI, Buffer
        if self.certification_type in ("organic", "globalgap", "roc", "all"):
            base_widths.append(0.5 * inch)  # EPA Reg
            # RUP is a narrow Yes/— column. Adding it pushes the packed
            # variant past the 7.0" budget, so trim Product, NPK, Target and
            # Organic to compensate (base variant keeps its original widths).
            base_widths.append(0.35 * inch)  # RUP
            base_widths[1] -= 0.10 * inch  # Product 0.9 -> 0.8
            base_widths[3] -= 0.05 * inch  # NPK / Conc. 0.55 -> 0.5
            base_widths[7] -= 0.10 * inch  # Target 0.65 -> 0.55
            base_widths[8] -= 0.05 * inch  # Organic 0.55 -> 0.5

        t = Table(app_data, colWidths=base_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # --- Table 2: NOP Supplier & Purchase Traceability ---
        # Required for mass-balance audit (7 CFR 205.103(b)(2))
        # This is the #1 non-conformance finding in organic audits
        if self.certification_type in ("organic", "roc", "all"):
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Input Purchase Traceability (7 CFR 205.103)</b>"))
            elements.append(self._spacer(0.05))

            trace_headers = [
                "Date Applied",
                "Product",
                "Supplier",
                "Purchase Date",
                "Invoice #",
                "Qty Purchased",
                "Applicator",
                "Cert #",
                "CA DPR Permit",
            ]
            trace_header_row = [self._hdr(h) for h in trace_headers]
            trace_data = [trace_header_row]
            missing_supplier = 0

            for ev in events:
                qty_purchased = ""
                if ev.quantity_purchased is not None:
                    qty_purchased = f"{_fmt_float(ev.quantity_purchased)} {_val(ev.quantity_purchased_unit, '')}"

                # CA DPR restricted-materials permit (county Ag Commissioner).
                # Surface expiry inline so the inspector can check validity
                # against the application date without leaving the table.
                dpr_permit = None
                if ev.ca_dpr_permit_number:
                    dpr_permit = ev.ca_dpr_permit_number
                    if ev.ca_dpr_permit_expires:
                        dpr_permit += f" exp {ev.ca_dpr_permit_expires:%Y-%m-%d}"

                trace_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(ev.commercial_name, 35),
                        self._cell(ev.supplier_name, 35),
                        self._cell(_fmt_date(ev.purchase_date) if ev.purchase_date else None),
                        self._cell(ev.purchase_invoice, 25),
                        self._cell(qty_purchased or None),
                        self._cell(ev.applicator_name or ev.performed_by, 25),
                        self._cell(ev.applicator_certification, 20),
                        self._cell(dpr_permit, 40),
                    ]
                )

                if not ev.supplier_name:
                    missing_supplier += 1

            # Column widths: Purchase Date widened to fit "YYYY-MM-DD" without
            # wrapping; Supplier widened so common org names ("Hydra Organics",
            # "Pacific Gold Dairy") render fully; Cert # narrowed to compensate.
            # CA DPR Permit gets 0.95" so "PERMIT-# exp YYYY-MM-DD" wraps to
            # two clean lines; total stays inside the 7.0" budget.
            trace_widths = [
                0.55 * inch,  # Date Applied
                0.85 * inch,  # Product
                1.05 * inch,  # Supplier
                0.75 * inch,  # Purchase Date
                0.70 * inch,  # Invoice #
                0.65 * inch,  # Qty Purchased
                0.70 * inch,  # Applicator
                0.45 * inch,  # Cert #
                0.95 * inch,  # CA DPR Permit
            ]
            t2 = Table(trace_data, colWidths=trace_widths, repeatRows=1)
            t2.setStyle(self._base_table_style())
            elements.append(t2)

            if missing_supplier > 0:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"Warning: {missing_supplier} input(s) missing supplier information. "
                        "NOP auditors require supplier traceability for all purchased inputs "
                        "to complete mass-balance reconciliation.",
                        self._styles["footer_note"],
                    )
                )

        # --- Table 3: OMRI / National List Verification (Sprint 3) ---
        # 7 CFR 205.601 (allowed synthetics) + 205.602 (prohibited nonsynthetics).
        # Distinguishes farmer-confirmed OMRI IDs, National List matches, and
        # pure self-report. Flags any National List "prohibited" match.
        if self.certification_type in ("organic", "roc", "all") and events:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>OMRI / National List Verification (7 CFR 205.601 / 205.602)</b>"))
            elements.append(self._spacer(0.05))

            ver_headers = ["Date", "Product", "OMRI ID", "National List Match", "Status"]
            ver_data = [[self._hdr(h) for h in ver_headers]]
            prohibited_hits = 0
            self_reported_count = 0

            for ev in events:
                omri = getattr(ev, "omri_product", None)
                nl = getattr(ev, "national_list_substance", None)

                omri_display = omri.omri_id if omri else None
                if nl:
                    nl_display = f"{nl.substance_name} ({nl.cfr_section}{nl.subsection or ''})"
                    status_display = "Allowed" if nl.status == "allowed" else "PROHIBITED"
                    if nl.status == "prohibited":
                        prohibited_hits += 1
                else:
                    nl_display = None
                    status_display = "Self-reported" if not omri else "Farmer-reported OMRI"

                if not omri and not nl:
                    self_reported_count += 1

                ver_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(ev.commercial_name, 30),
                        self._cell(omri_display, 15),
                        self._cell(nl_display, 35),
                        self._cell(status_display, 18),
                    ]
                )

            ver_widths = [0.65 * inch, 1.3 * inch, 0.9 * inch, 2.3 * inch, 1.0 * inch]
            t3 = Table(ver_data, colWidths=ver_widths, repeatRows=1)
            t3.setStyle(self._base_table_style())
            elements.append(t3)

            if prohibited_hits > 0:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"<b>[WARNING] 7 CFR 205.602: {prohibited_hits} input(s) match a PROHIBITED "
                        f"substance on the National List. Use of these inputs disqualifies the "
                        f"crop from organic sale. Review with certifier immediately.</b>",
                        self._warning_style(),
                    )
                )

            if self_reported_count > 0:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"Note: {self_reported_count} input(s) are self-reported only "
                        f"(no OMRI ID and no National List match). Inspector should verify each "
                        f"against omri.org or 7 CFR 205.601 directly.",
                        self._styles["footer_note"],
                    )
                )

        # --- Application Notes (mirrors the Production Event Notes pattern) ---
        elements.extend(self._build_event_notes_subtable(events, "Application Notes", CHEMICAL_TYPE_LABELS))

        return elements

    # ------------------------------------------------------------------
    # Section 5: Production Events
    # ------------------------------------------------------------------

    def _build_production_events(self):
        elements = [self._section_header("Production Events")]

        # Method (operation technique — e.g. "Hand thinning", "Mechanical harvester")
        # and Block/Section ID are required for NOP lot traceability and practice
        # documentation. Method lives in extra_data.method (distinct from
        # History.production_method, which is organic/conventional).
        headers = [
            "Date",
            "Type",
            "Description",
            "Method",
            "Area Covered",
            "Block",
            "Fuel Used",
            "Equip. Hours",
            "Operator",
        ]

        events = list(self.production.history_productionevent_events.all().order_by("date"))

        if not events:
            elements.append(self._empty_table(headers))
            return elements

        header_row = [self._hdr(h) for h in headers]
        data = [header_row]
        for ev in events:
            area = f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}" if ev.area_covered else None
            fuel = f"{_fmt_float(ev.fuel_consumed)} {_val(ev.fuel_unit, '')}" if ev.fuel_consumed else None
            extra = ev.extra_data or {}
            method = extra.get("method") if isinstance(extra, dict) else None
            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type))),
                    # Description can be long (post-harvest sanitation steps,
                    # lot-tracking details, etc.); let ReportLab word-wrap
                    # inside the column instead of cutting mid-sentence at
                    # 80 chars. A 600-char cap still guards against pasted
                    # walls of text that would blow the row height, but
                    # normal regulatory-detail descriptions fit under it.
                    self._cell(ev.description, 600),
                    self._cell(method, 30),
                    self._cell(area),
                    self._cell(ev.block_id, 15),
                    self._cell(fuel),
                    self._cell(str(ev.equipment_hours) if ev.equipment_hours else None),
                    self._cell(ev.performed_by),
                ]
            )

        col_widths = [
            0.55 * inch,  # Date
            0.65 * inch,  # Type
            1.7 * inch,  # Description
            0.85 * inch,  # Method (NEW)
            0.6 * inch,  # Area
            0.5 * inch,  # Block (NEW)
            0.55 * inch,  # Fuel
            0.5 * inch,  # Hours
            0.7 * inch,  # Operator
        ]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # --- Irrigation Records (7 CFR 205.272 water quality / NOP water use) ---
        # Irrigation details (water source, method, depth, pump/energy) are model
        # columns on ProductionEvent (IR subtype) but aren't shown in the summary
        # table. Required for organic water-quality compliance and carbon audits.
        ir_events = [ev for ev in events if ev.type == "IR"]
        if ir_events:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Irrigation Records (7 CFR 205.272 / NOP water management)</b>"))
            elements.append(self._spacer(0.05))

            ir_headers = [
                "Date",
                "Water Source",
                "Method",
                "Depth",
                "Pump Depth (ft)",
                "Power Source",
                "Area",
            ]
            ir_header_row = [self._hdr(h) for h in ir_headers]
            ir_data = [ir_header_row]

            for ev in ir_events:
                depth_display = None
                if ev.irrigation_depth is not None:
                    depth_display = f"{_fmt_float(ev.irrigation_depth)} {_val(ev.irrigation_depth_unit, 'in')}"
                water_src = ev.get_water_source_display() if ev.water_source else None
                method_disp = ev.get_irrigation_method_display() if ev.irrigation_method else None
                elec_src = ev.get_electricity_source_display() if ev.electricity_source else None
                ir_area = f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}" if ev.area_covered else None

                ir_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(water_src, 25),
                        self._cell(method_disp, 25),
                        self._cell(depth_display),
                        self._cell(_fmt_float(ev.pump_depth_ft) if ev.pump_depth_ft else None),
                        self._cell(elec_src, 20),
                        self._cell(ir_area),
                    ]
                )

            ir_widths = [0.75 * inch, 1.2 * inch, 1.1 * inch, 0.75 * inch, 0.85 * inch, 1.0 * inch, 0.65 * inch]
            ir_table = Table(ir_data, colWidths=ir_widths, repeatRows=1)
            ir_table.setStyle(self._base_table_style())
            elements.append(ir_table)

        # --- Post-Harvest Processing Records (7 CFR 205.270-272) ---
        # Handlers of organic product must document cleaning/sanitation, processing
        # aids, and temperature controls to maintain organic integrity. PH-specific
        # fields live in extra_data (no model columns).
        ph_events = [ev for ev in events if ev.type == "PH"]
        if ph_events:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Post-Harvest Processing Records (7 CFR 205.270-272)</b>"))
            elements.append(self._spacer(0.05))

            ph_headers = [
                "Date",
                "Processing Type",
                "Duration (hrs)",
                "Temp. Controlled",
                "Variety",
                "Operator",
            ]
            ph_header_row = [self._hdr(h) for h in ph_headers]
            ph_data = [ph_header_row]

            # Mirror frontend PROCESSING_TYPE_LABELS (productionEvent.ts) so the PDF
            # shows identical labels to the consumer QR view. A raw .title() fallback
            # silently loses e.g. "Cooling / Pre-cooling" → "Cooling".
            PROCESSING_TYPE_PDF_LABELS = {
                "washing": "Washing",
                "cooling": "Cooling / Pre-cooling",
                "drying": "Drying",
                "sorting": "Sorting",
                "grading": "Grading",
                "packing": "Packing",
                "hulling": "Hulling",
                "shelling": "Shelling",
                "pressing": "Pressing",
                "milling": "Milling",
                "smoking": "Smoking",
            }

            for ev in ph_events:
                extra = ev.extra_data or {}
                proc_type_raw = extra.get("processing_type") or ""
                proc_type_display = (
                    PROCESSING_TYPE_PDF_LABELS.get(proc_type_raw, proc_type_raw.replace("_", " ").title())
                    if proc_type_raw
                    else None
                )
                duration = extra.get("processing_duration_hours")
                temp_ctrl = extra.get("temperature_control")
                if isinstance(temp_ctrl, str):
                    temp_display = "Yes" if temp_ctrl.lower() in ("true", "yes", "1") else "No"
                elif isinstance(temp_ctrl, bool):
                    temp_display = "Yes" if temp_ctrl else "No"
                else:
                    temp_display = None

                ph_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(proc_type_display),
                        self._cell(_fmt_float(duration) if duration else None),
                        self._cell(temp_display),
                        self._cell(ev.variety, 20),
                        self._cell(ev.performed_by, 25),
                    ]
                )

            ph_widths = [0.75 * inch, 1.3 * inch, 0.85 * inch, 1.0 * inch, 1.0 * inch, 1.2 * inch]
            ph_table = Table(ph_data, colWidths=ph_widths, repeatRows=1)
            ph_table.setStyle(self._base_table_style())
            elements.append(ph_table)

        # --- Harvest Records (per-event detail) ---
        # NOP / GlobalG.A.P. auditors expect per-harvest documentation: yield,
        # variety, quality grade, method. The main Production Events table
        # above lists every event generically; this table surfaces the
        # harvest-specific fields (stored on ProductionEvent HA subtype) so
        # reviewers can reconcile yield, variety, and quality without opening
        # each row. harvest_method lives in extra_data; we mirror from
        # top-level if present for forward compat.
        ha_events = [ev for ev in events if ev.type == "HA"]
        if ha_events:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Harvest Records</b>"))
            elements.append(self._spacer(0.05))

            ha_headers = [
                "Date",
                "Variety",
                "Yield",
                "Quality Grade",
                "Method",
                "Brix / Moisture",
                "Storage",
                "Operator",
            ]
            ha_header_row = [self._hdr(h) for h in ha_headers]
            ha_data = [ha_header_row]

            # Match the frontend HARVEST_METHOD_LABELS (productionEvent.ts) so the
            # audit PDF shows the same consumer-facing labels as the QR transparency
            # flow. Unknown values pass through with underscores converted to spaces.
            HARVEST_METHOD_PDF_LABELS = {
                "hand_picking": "Hand Picking",
                "selective_hand_picking": "Selective Hand Picking",
                "mechanical": "Mechanical Harvester",
                "shake_and_catch": "Shake and Catch",
                "strip_picking": "Strip Picking",
                "manual": "Manual Harvest",
                "mixed": "Mixed (Manual + Mechanical)",
            }

            for ev in ha_events:
                extra = ev.extra_data or {}
                yield_display = (
                    f"{_fmt_float(ev.yield_quantity)} {_val(ev.yield_unit, '')}" if ev.yield_quantity else None
                )
                quality_raw = ev.harvest_quality_grade or None
                quality_display = quality_raw.replace("_", " ").title() if quality_raw else None

                # harvest_method: prefer top-level (defensive, if ever promoted),
                # fall back to extra_data where the form currently writes it.
                method_raw = getattr(ev, "harvest_method", None) or extra.get("harvest_method") or ""
                structured_method = (
                    HARVEST_METHOD_PDF_LABELS.get(
                        method_raw, method_raw.replace("_", " ").title() if method_raw else None
                    )
                    if method_raw
                    else None
                )

                # Free-text production_method ("Hand harvest with ATV bin transport")
                # stored at extra_data.method by ProductionTab.jsx onSubmit. This is
                # the richer narrative that drives the manual-operation carbon
                # short-circuit — auditors need to see both the structured dropdown
                # value AND the farmer's documented detail to reconcile the carbon
                # calculation basis and NOP labor-documentation expectations.
                freetext_method = (extra.get("method") or extra.get("production_method") or "").strip()
                if structured_method and freetext_method and freetext_method.lower() != structured_method.lower():
                    method_display = f"{structured_method} ({freetext_method})"
                elif structured_method:
                    method_display = structured_method
                elif freetext_method:
                    method_display = freetext_method
                else:
                    method_display = None

                # Brix vs grain moisture: show whichever is populated (fruits use
                # Brix, grain crops use moisture %). Both shown if both filled.
                measurements = []
                brix = ev.brix_level or extra.get("brix_level") or extra.get("brix_levels")
                if brix:
                    try:
                        measurements.append(f"{_fmt_float(float(brix))}° Brix")
                    except (TypeError, ValueError):
                        measurements.append(f"{brix}° Brix")
                if ev.grain_moisture:
                    measurements.append(f"{_fmt_float(ev.grain_moisture)}% moisture")
                # F43: dry-matter % — avocado/nut maturity (the CA orchard ICP metric)
                if getattr(ev, "dry_matter_percentage", None) is not None:
                    measurements.append(f"{_fmt_float(ev.dry_matter_percentage)}% dry matter")
                measurement_display = " / ".join(measurements) if measurements else None

                # Sprint 3.2 — storage location + optional temperature on HA events
                storage_parts = []
                if ev.storage_location:
                    storage_parts.append(ev.storage_location)
                if ev.storage_temperature_f is not None:
                    storage_parts.append(f"{_fmt_float(ev.storage_temperature_f)}°F")
                storage_display = " @ ".join(storage_parts) if storage_parts else None

                ha_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(ev.variety, 20),
                        self._cell(yield_display),
                        self._cell(quality_display),
                        self._cell(method_display),
                        self._cell(measurement_display),
                        self._cell(storage_display, 30),
                        self._cell(ev.performed_by, 25),
                    ]
                )

            ha_widths = [
                0.65 * inch,
                0.8 * inch,
                0.8 * inch,
                0.85 * inch,
                0.95 * inch,
                0.95 * inch,
                0.95 * inch,
                0.75 * inch,
            ]
            ha_table = Table(ha_data, colWidths=ha_widths, repeatRows=1)
            ha_table.setStyle(self._base_table_style())
            elements.append(ha_table)

        # --- Production Event Notes (Field Notes / observation) ---
        # The main Production Events table keeps one row per event compact (Date,
        # Type, Description, Method, Area, Block, Fuel, Hours, Operator). Free-text
        # observations — the richest farmer-authored documentation surfaced on the
        # consumer QR card as "Farmer's Field Notes" — would overflow that table.
        # Auditors still need these, so we surface them here as a supplemental
        # sub-table. Mirrors the Business Events "Supporting Detail" pattern.
        notes_events = [ev for ev in events if (ev.observation or "").strip()]
        if notes_events:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Production Event Notes (Field Notes)</b>"))
            elements.append(self._spacer(0.05))

            notes_headers = ["Date", "Type", "Notes"]
            notes_header_row = [self._hdr(h) for h in notes_headers]
            notes_data = [notes_header_row]

            for ev in notes_events:
                notes_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(ev.observation, 120),
                    ]
                )

            notes_widths = [0.7 * inch, 1.0 * inch, 4.9 * inch]
            notes_table = Table(notes_data, colWidths=notes_widths, repeatRows=1)
            notes_table.setStyle(self._base_table_style())
            elements.append(notes_table)

        return elements

    # ------------------------------------------------------------------
    # Section 5b: Seed & Planting Stock Records (NOP 5029)
    # ------------------------------------------------------------------

    def _build_seed_stock_section(self):
        """
        Seed & Planting Stock Records — 7 CFR 205.204 / NOP 5029.

        NOP requires:
        - Use of organically produced seed when commercially available
        - Documentation of 3+ supplier searches when non-organic seed used
        - Seed variety, source, and organic status for each planting event

        This is a common non-conformance finding per CCOF inspection checklists.
        """
        elements = [self._section_header("Seed & Planting Stock Records")]

        # Seed source data lives on ProductionEvent (PL subtype), NOT on History.
        # Query all planting events for seed info.
        planting_events = list(self.production.history_productionevent_events.filter(type="PL").order_by("date"))

        # Also check ANY production event for seed_source (some templates set it on non-PL events)
        all_prod_events = list(self.production.history_productionevent_events.all())
        events_with_seed = [ev for ev in all_prod_events if ev.seeds_source or ev.seed_certification_status]

        if not planting_events and not events_with_seed:
            # Perennial crops (tree fruit, tree nut, vine) are planted once and produce
            # for decades; no annual planting event is expected. For these, NOP 205.204
            # covers the ORIGINAL planting stock records, which live on the establishment's
            # OSP / history binder rather than each production. Render an appropriate
            # message rather than a blanket "no records found" red flag.
            is_perennial = False
            try:
                crop = self.production.crop_type
                if crop and getattr(crop, "has_soil_contact", True) is False:
                    # has_soil_contact=False is our tree-fruit/tree-nut marker
                    is_perennial = True
                # Also detect by name for defense in depth.
                crop_name = (crop.name if crop else "").lower()
                perennial_keywords = (
                    "avocado",
                    "citrus",
                    "orange",
                    "lemon",
                    "grapefruit",
                    "apple",
                    "pear",
                    "cherry",
                    "peach",
                    "plum",
                    "apricot",
                    "almond",
                    "walnut",
                    "pistachio",
                    "pecan",
                    "grape",
                    "wine",
                    "olive",
                )
                if any(k in crop_name for k in perennial_keywords):
                    is_perennial = True
            except Exception:
                pass

            if is_perennial:
                elements.append(
                    self._body(
                        "No planting event recorded for this production (perennial crop). "
                        "Original nursery/planting-stock records for § 205.204 compliance "
                        "are maintained at the establishment level; see the OSP Additional "
                        "Certifier Information section for the operation history and the "
                        "land-history affidavit on file. For perennial operations, § 205.204 "
                        "applies to the initial planting, not to each harvest cycle."
                    )
                )
            else:
                elements.append(
                    Paragraph(
                        "<b>NO SEED/PLANTING STOCK RECORDS FOUND.</b> NOP 7 CFR 205.204 "
                        "requires documentation of seed source and organic status for all "
                        "plantings (and 3+ commercial-availability search attempts when "
                        "non-organic seed is used). This is a standard CCOF inspection finding.",
                        self._warning_style(),
                    )
                )
            return elements

        # Seed source information from production events
        if events_with_seed:
            # Use the first event with seed source as the representative
            seed_ev = events_with_seed[0]
            seed_source_display = seed_ev.get_seeds_source_display() if seed_ev.seeds_source else None
            elements.append(self._label_value("Seed Source", seed_source_display))

            # Organic seed search documentation (NOP 5029)
            search_attempts = getattr(seed_ev, "seed_search_attempts", None) or []
            if search_attempts and isinstance(search_attempts, list) and len(search_attempts) > 0:
                elements.append(self._spacer(0.1))
                elements.append(self._body("<b>Organic Seed Commercial Availability Search (NOP 5029)</b>"))
                elements.append(self._spacer(0.05))

                search_headers = ["Supplier Contacted", "Date", "Result", "Notes"]
                search_header_row = [self._hdr(h) for h in search_headers]
                search_data = [search_header_row]

                for attempt in search_attempts:
                    if isinstance(attempt, dict):
                        search_data.append(
                            [
                                self._cell(attempt.get("supplier_name", "")),
                                self._cell(attempt.get("date_contacted", "")),
                                self._cell(attempt.get("result", "")),
                                self._cell(attempt.get("notes", ""), 60),
                            ]
                        )

                if len(search_data) > 1:
                    sw = [1.5 * inch, 0.8 * inch, 1.2 * inch, 3.0 * inch]
                    t = Table(search_data, colWidths=sw, repeatRows=1)
                    t.setStyle(self._base_table_style())
                    elements.append(t)
            elif seed_ev.seed_certification_status in (
                "non_organic_untreated",
                "non_organic_treated",
            ):
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        "Note: Non-organic seed indicated but no commercial availability "
                        "search documented. NOP 5029 (7 CFR 205.204(a)(1)) requires "
                        "documentation of at least 3 supplier searches when organic seed is not used.",
                        self._styles["footer_note"],
                    )
                )

        # Planting event details
        if planting_events:
            elements.append(self._spacer(0.1))
            elements.append(self._body("<b>Planting Event Details</b>"))
            elements.append(self._spacer(0.05))

            pl_headers = ["Date", "Description", "Variety", "Seed Source", "Cert Status", "Area", "Operator"]
            pl_header_row = [self._hdr(h) for h in pl_headers]
            pl_data = [pl_header_row]

            for ev in planting_events:
                area = f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}" if ev.area_covered else None
                seed_src = ev.get_seeds_source_display() if ev.seeds_source else None
                cert_status = ev.get_seed_certification_status_display() if ev.seed_certification_status else None
                pl_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(ev.description, 50),
                        self._cell(ev.variety),
                        self._cell(seed_src),
                        self._cell(cert_status),
                        self._cell(area),
                        self._cell(ev.performed_by),
                    ]
                )

            pl_widths = [
                0.65 * inch,
                1.55 * inch,
                0.8 * inch,
                0.9 * inch,
                0.9 * inch,
                0.65 * inch,
                0.85 * inch,
            ]
            t = Table(pl_data, colWidths=pl_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)

            # --- NOP 7 CFR 205.204 Seed Traceability Sub-Table ------------------
            # Supplier / invoice / lot / treatment for each planting event with traceability data.
            traceable = [
                ev
                for ev in planting_events
                if any(
                    [
                        ev.seed_supplier_name,
                        ev.seed_purchase_invoice,
                        ev.seed_lot_number,
                        ev.seed_purchase_date,
                        ev.seed_treatment,
                    ]
                )
            ]
            if traceable:
                elements.append(self._spacer(0.12))
                elements.append(self._body("<b>Seed Supplier &amp; Purchase Traceability (NOP 7 CFR 205.204)</b>"))
                elements.append(self._spacer(0.05))

                trace_headers = [
                    "Date",
                    "Variety",
                    "Supplier",
                    "Purchase Date",
                    "Invoice #",
                    "Lot #",
                    "Treatment",
                ]
                trace_rows = [[self._hdr(h) for h in trace_headers]]
                for ev in traceable:
                    trace_rows.append(
                        [
                            self._cell(_fmt_date(ev.date)),
                            self._cell(ev.variety),
                            self._cell(ev.seed_supplier_name),
                            self._cell(_fmt_date(ev.seed_purchase_date)),
                            self._cell(ev.seed_purchase_invoice),
                            self._cell(ev.seed_lot_number),
                            self._cell(ev.seed_treatment, 50),
                        ]
                    )
                trace_widths = [
                    0.7 * inch,
                    0.85 * inch,
                    1.15 * inch,
                    0.8 * inch,
                    0.8 * inch,
                    0.8 * inch,
                    1.2 * inch,
                ]
                tt = Table(trace_rows, colWidths=trace_widths, repeatRows=1)
                tt.setStyle(self._base_table_style())
                elements.append(tt)

                # Warning for non-organic treated seed (disqualifying per 7 CFR 205.204(a)(5))
                treated = [ev for ev in traceable if ev.seed_certification_status == "non_organic_treated"]
                if treated:
                    elements.append(self._spacer(0.05))
                    elements.append(
                        Paragraph(
                            "<b>[WARNING] NOP 7 CFR 205.204(a)(5):</b> Non-organic seed treated "
                            "with prohibited substances disqualifies the crop from organic sale. "
                            "Review the highlighted planting events with your certifier before harvest.",
                            self._warning_style(),
                        )
                    )

        return elements

    # ------------------------------------------------------------------
    # Section 6: Soil & Water Management
    # ------------------------------------------------------------------

    def _build_soil_section(self):
        elements = [self._section_header("Soil & Water Management")]

        headers = [
            "Date",
            "Type",
            "Soil pH",
            "Organic Matter %",
            "Amendment",
            "Amount",
            "Area",
            "Organic Status",
        ]

        events = list(self.production.history_soilmanagementevent_events.all().order_by("date"))

        if not events:
            elements.append(self._empty_table(headers))
            return elements

        header_row = [self._hdr(h) for h in headers]
        data = [header_row]
        has_amendments_without_approval = False
        compost_events = []
        grazing_events = []
        habitat_events = []
        st_events = []  # F19: soil tests carrying lab results (test_results JSON)
        for ev in events:
            amount = ""
            if ev.amendment_amount_numeric:
                amount = f"{_fmt_float(ev.amendment_amount_numeric)} {_val(ev.amendment_amount_unit, '')}"
            elif ev.amendment_amount:
                # Legacy CharField path: still append the unit when one is recorded
                # so an inspector reading "3500 kg" knows the magnitude, not just "3500".
                unit = ev.amendment_amount_unit or ""
                amount = f"{_val(ev.amendment_amount)} {unit}".strip()

            area = f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}" if ev.area_covered else None

            # Track amendment approval gaps
            organic_status = ""
            if ev.amendment_type:
                if ev.amendment_organic_approved:
                    organic_status = ev.get_amendment_organic_approved_display()
                else:
                    organic_status = "NOT SPECIFIED"
                    has_amendments_without_approval = True

            # Cover-crop species lives in extra_data.cover_crop_species, NOT amendment_type, so a
            # cover-crop row otherwise showed a blank "Amendment" cell — the planted mix (the whole
            # point of the record) was dropped from the dossier. Surface it in the Amendment column.
            amendment_display = _amendment_type_label(ev.amendment_type)
            if not ev.amendment_type and ev.type == "CC":
                _ed = ev.extra_data if isinstance(ev.extra_data, dict) else {}
                _species = _ed.get("cover_crop_species")
                if _species:
                    amendment_display = _species

            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(SOIL_TYPE_LABELS.get(ev.type, _val(ev.type))),
                    self._cell(str(ev.soil_ph) if ev.soil_ph is not None else None),
                    self._cell(str(ev.organic_matter_percentage) if ev.organic_matter_percentage is not None else None),
                    self._cell(amendment_display, 50),
                    self._cell(amount or None),
                    self._cell(area),
                    self._cell(organic_status or None),
                ]
            )

            # Collect composting events for sub-table
            if ev.type == "CO":
                compost_events.append(ev)
            # Collect grazing events for sub-table — the main soil table's amendment-oriented
            # columns leave every grazing detail blank, so integrated grazing (a key regenerative
            # practice) was invisible to the certifier. Surface it in a dedicated sub-table below.
            if ev.type == "GR":
                grazing_events.append(ev)
            # Collect biodiversity / habitat events (HD developed habitat, NS nesting/shelter) for a
            # dedicated sub-table — the amendment-oriented main columns leave habitat detail blank.
            if ev.type in ("HD", "NS"):
                habitat_events.append(ev)
            # F19: collect soil tests that carry lab RESULTS (test_results JSON) for a dedicated
            # sub-table — the main table shows only pH/OM; a certifier needs N/P/K/CEC + lab + date.
            if ev.type == "ST" and isinstance(ev.test_results, dict) and ev.test_results:
                st_events.append(ev)

        col_widths = [
            0.6 * inch,
            0.8 * inch,
            0.5 * inch,
            0.7 * inch,
            1.1 * inch,
            0.8 * inch,
            0.7 * inch,
            1.0 * inch,
        ]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # NOP Warning: amendments without organic approval status
        if has_amendments_without_approval:
            elements.append(
                Paragraph(
                    "<b>[WARNING] NOP 7 CFR 205.203(b):</b> Some amendments are missing organic approval status. "
                    "All soil amendments must be OMRI-listed or NOP-approved for organic operations.",
                    self._warning_style(),
                )
            )

        # NOP Composting Records Sub-Table (7 CFR 205.203(c)(2)).
        # § 205.203(c)(1) is the raw-manure interval rule; composted plant /
        # animal materials live under (c)(2). Header was previously mis-cited
        # to (c)(1) — fixed 2026-04-15.
        if compost_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Compost Temperature Records (7 CFR 205.203(c)(2))</b>",
                    self._sub_header_style(),
                )
            )
            compost_headers = [
                "Date",
                "Peak Temp (°F)",
                "Days at Temp",
                "Turnings",
                "Feedstock",
                "Amendment",
                "Compliant",
            ]
            compost_data = [[self._hdr(h) for h in compost_headers]]
            for cev in compost_events:
                peak = str(cev.compost_peak_temp_f) if cev.compost_peak_temp_f is not None else "—"
                days = str(cev.compost_duration_days_at_temp) if cev.compost_duration_days_at_temp is not None else "—"
                turns = str(cev.compost_turning_count) if cev.compost_turning_count is not None else "—"

                # NOP compliance check per § 205.203(c)(2). Two acceptable pathways:
                #   • Windrow:        131-170°F for 15+ days, with 5+ turnings
                #   • In-vessel /
                #     static pile:    131-170°F for 3+ days  (no turning requirement)
                # Most demo / windrow operations document turnings; small organic farms
                # often run static piles (no turnings) and were previously stamped
                # "Non-Compliant" by the windrow-only rule.
                compliant = "—"
                if cev.compost_peak_temp_f is not None and cev.compost_duration_days_at_temp is not None:
                    temp_ok = 131 <= float(cev.compost_peak_temp_f) <= 170
                    windrow_path = cev.compost_duration_days_at_temp >= 15 and (cev.compost_turning_count or 0) >= 5
                    static_path = cev.compost_duration_days_at_temp >= 3
                    compliant = "Yes" if (temp_ok and (windrow_path or static_path)) else "No"

                compost_data.append(
                    [
                        self._cell(_fmt_date(cev.date)),
                        self._cell(peak),
                        self._cell(days),
                        self._cell(turns),
                        self._cell(cev.compost_feedstock, 40),
                        self._cell(cev.amendment_type, 30),
                        self._cell(compliant),
                    ]
                )
            compost_widths = [
                0.65 * inch,
                0.8 * inch,
                0.65 * inch,
                0.55 * inch,
                1.25 * inch,
                0.95 * inch,
                0.6 * inch,
            ]
            ct = Table(compost_data, colWidths=compost_widths, repeatRows=1)
            ct.setStyle(self._base_table_style())
            elements.append(ct)

            # F24: the NOP 5021 temperature-monitoring readings (free-text log) — the detailed
            # readings behind the peak-temp summary above. Shown verbatim per event.
            log_events = [ev for ev in compost_events if (ev.compost_temperature_log or "").strip()]
            if log_events:
                elements.append(Spacer(1, 6))
                log_data = [[self._hdr("Date"), self._hdr("Temperature Monitoring Readings")]]
                for lev in log_events:
                    log_data.append([self._cell(_fmt_date(lev.date)), self._cell(lev.compost_temperature_log, 200)])
                lt = Table(log_data, colWidths=[0.8 * inch, 5.6 * inch], repeatRows=1)
                lt.setStyle(self._base_table_style())
                elements.append(lt)

            # Warning if any compost event is missing temperature data
            missing_temp = any(
                ev.compost_peak_temp_f is None or ev.compost_duration_days_at_temp is None for ev in compost_events
            )
            if missing_temp:
                elements.append(
                    Paragraph(
                        "<b>[WARNING] NOP 7 CFR 205.203(c)(2):</b> Some composting events are missing temperature "
                        "or duration records. Composting must document peak temperature (131-170°F) and either "
                        "(a) windrow: minimum 15 days at temperature with 5+ turnings, or "
                        "(b) in-vessel / static pile: minimum 3 days at temperature.",
                        self._warning_style(),
                    )
                )

        # --- Grazing Management Records ---
        # Integrated livestock grazing is a documented soil-health / weed-control practice (and a
        # core regenerative signal). The main soil table carries no animal columns, so surface the
        # detail here: animal type/count, grazing days, purpose, and — for summary-mode entries —
        # the rotation period and number of passes.
        if grazing_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Grazing Management Records</b>",
                    self._sub_header_style(),
                )
            )
            grazing_headers = ["Period", "Animal", "Count", "Grazing Days", "Passes", "Purpose", "Area"]
            grazing_data = [[self._hdr(h) for h in grazing_headers]]
            for gev in grazing_events:
                ed = gev.extra_data if isinstance(gev.extra_data, dict) else {}
                is_summary = ed.get("is_summary") in (True, "true")

                if is_summary and ed.get("date_start") and ed.get("date_end"):
                    period = f"{ed.get('date_start')} – {ed.get('date_end')}"
                else:
                    period = _fmt_date(gev.date)

                grazing_days = ed.get("total_grazing_days") if is_summary else gev.grazing_duration_days
                # Pass count only applies to a summary rotation; single events render a dash via _cell.
                passes = ed.get("event_count") if is_summary else None

                area_total = ed.get("area_covered_total") if is_summary else None
                area_val = area_total if area_total else gev.area_covered
                area_disp = f"{_fmt_float(area_val)} {_val(gev.area_unit, '')}".strip() if area_val else None

                purpose = GRAZING_PURPOSE_LABELS.get(gev.grazing_purpose, _val(gev.grazing_purpose))

                grazing_data.append(
                    [
                        self._cell(period),
                        self._cell(_val(gev.animal_type)),
                        self._cell(str(gev.animal_count) if gev.animal_count is not None else None),
                        self._cell(str(grazing_days) if grazing_days not in (None, "") else None),
                        self._cell(str(passes) if passes not in (None, "") else None),
                        self._cell(purpose, 40),
                        self._cell(area_disp),
                    ]
                )
            grazing_widths = [1.3 * inch, 0.8 * inch, 0.6 * inch, 0.9 * inch, 0.6 * inch, 1.2 * inch, 0.7 * inch]
            gt = Table(grazing_data, colWidths=grazing_widths, repeatRows=1)
            gt.setStyle(self._base_table_style())
            elements.append(gt)

        # --- Biodiversity & Habitat Records ---
        # Documented habitat PRACTICES (HD: hedgerows, insectary, riparian, living groundcover) and
        # nesting/shelter structures (NS: owl/raptor/bee/bat boxes, insect hotels) — facts a ROC /
        # Bee Better auditor reads directly. NO biodiversity score/index (banned self-label class);
        # the living-floor / bugs / birds proof rides on the event photos, not a number.
        if habitat_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Biodiversity &amp; Habitat Records</b>",
                    self._sub_header_style(),
                )
            )
            habitat_headers = [
                "Date",
                "Category",
                "Practice / Structure",
                "Count",
                "Since",
                "Area",
                "Species / Notes",
            ]
            habitat_data = [[self._hdr(h) for h in habitat_headers]]
            for hev in habitat_events:
                ed = hev.extra_data if isinstance(hev.extra_data, dict) else {}
                category = SOIL_TYPE_LABELS.get(hev.type, _val(hev.type))
                practice = HABITAT_TYPE_LABELS.get(hev.habitat_type, _val(hev.habitat_type))
                count = str(hev.habitat_structure_count) if hev.habitat_structure_count is not None else None
                since = _fmt_date(hev.habitat_install_date) if hev.habitat_install_date else None
                area_disp = (
                    f"{_fmt_float(hev.area_covered)} {_val(hev.area_unit, '')}".strip() if hev.area_covered else None
                )
                notes = (
                    " · ".join(
                        p
                        for p in (
                            ed.get("species_planted"),
                            ed.get("structure_notes"),
                            ed.get("wildlife_observed"),
                        )
                        if p
                    )
                    or None
                )
                habitat_data.append(
                    [
                        self._cell(_fmt_date(hev.date)),
                        self._cell(category),
                        self._cell(practice, 40),
                        self._cell(count),
                        self._cell(since),
                        self._cell(area_disp),
                        self._cell(notes, 60),
                    ]
                )
            habitat_widths = [0.8 * inch, 1.0 * inch, 1.3 * inch, 0.45 * inch, 0.7 * inch, 0.6 * inch, 1.45 * inch]
            ht = Table(habitat_data, colWidths=habitat_widths, repeatRows=1)
            ht.setStyle(self._base_table_style())
            elements.append(ht)

        # --- Soil Test Results (F19) ---
        # Lab results (N/P/K/CEC) + provenance for ST events — a soil test with only pH/OM is an
        # incomplete agronomic/certifier record. Read from the test_results JSONField.
        if st_events:
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("<b>Soil Test Results</b>", self._sub_header_style()))
            st_headers = ["Date", "Lab", "Sample #", "Report Date", "N (ppm)", "P (ppm)", "K (ppm)", "CEC"]
            st_data = [[self._hdr(h) for h in st_headers]]
            for sev in st_events:
                tr = sev.test_results if isinstance(sev.test_results, dict) else {}
                st_data.append(
                    [
                        self._cell(_fmt_date(sev.date)),
                        self._cell(tr.get("lab_name"), 24),
                        self._cell(tr.get("sample_id")),
                        self._cell(tr.get("report_date")),
                        self._cell(_val(tr.get("nitrogen"))),
                        self._cell(_val(tr.get("phosphorus"))),
                        self._cell(_val(tr.get("potassium"))),
                        self._cell(_val(tr.get("cec"))),
                    ]
                )
            st_widths = [0.7 * inch, 1.2 * inch, 0.8 * inch, 0.8 * inch, 0.6 * inch, 0.6 * inch, 0.6 * inch, 0.6 * inch]
            st_table = Table(st_data, colWidths=st_widths, repeatRows=1)
            st_table.setStyle(self._base_table_style())
            elements.append(st_table)

        # --- Soil Equipment Operations (CC mowing, OM/PA spreading, etc.) ---
        # Soil events with fuel/equipment data (cover crop termination, amendment
        # spreading) need their fuel and hours surfaced for carbon audits — the main
        # soil table doesn't carry those columns.
        equip_events = [ev for ev in events if (ev.fuel_consumed and float(ev.fuel_consumed) > 0) or ev.equipment_hours]
        if equip_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Soil Management Equipment Operations</b>",
                    self._sub_header_style(),
                )
            )
            eq_headers = ["Date", "Type", "Equipment", "Fuel", "Fuel Type", "Hours", "Operator"]
            eq_data = [[self._hdr(h) for h in eq_headers]]
            for ev in equip_events:
                fuel_disp = f"{_fmt_float(ev.fuel_consumed)} {_val(ev.fuel_unit, '')}" if ev.fuel_consumed else None
                eq_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(SOIL_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(ev.equipment_used or ev.name, 30),
                        self._cell(fuel_disp),
                        self._cell(ev.fuel_type),
                        self._cell(str(ev.equipment_hours) if ev.equipment_hours else None),
                        self._cell(ev.performed_by, 25),
                    ]
                )
            eq_widths = [0.65 * inch, 0.8 * inch, 1.4 * inch, 0.75 * inch, 0.7 * inch, 0.55 * inch, 1.0 * inch]
            eq_table = Table(eq_data, colWidths=eq_widths, repeatRows=1)
            eq_table.setStyle(self._base_table_style())
            elements.append(eq_table)

        # NOP Raw Manure Harvest Interval Records Sub-Table (7 CFR 205.203(c)(1)).
        # Raw animal manure requires 90 or 120 day pre-harvest interval depending on
        # crop-soil contact (§ 205.203(c)(1)(ii)/(iii)). Certifiers review this to
        # verify no contamination risk. Composted materials live under (c)(2) — do
        # not confuse the citations.
        # Filter on the manure-specific fields rather than the OM subtype: farmers
        # may log a manure application as Cover Crop (CC) or Organic Matter (OM);
        # the regulatory data is on the model, not the subtype label.
        manure_events = [ev for ev in events if ev.manure_harvest_interval or ev.manure_application_date]
        if manure_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Manure Handling Records (7 CFR 205.203(c)(1))</b>",
                    self._sub_header_style(),
                )
            )
            manure_headers = [
                "Date Applied",
                "Harvest Interval",
                "Amendment Type",
                "Earliest Safe Harvest",
                "Crop-Rule Check",
            ]
            # Resolve the crop's required interval ONCE so each row can be
            # checked against it. Inline per-row rule check makes the
            # mismatch impossible to miss when an inspector flips to this
            # page (the page-2 Pre-Export Consistency Check covers the
            # same finding at the executive summary level).
            try:
                expected_rule = self._manure_interval_rule_for_crop()
            except Exception:  # noqa: BLE001
                expected_rule = None
            manure_data = [[self._hdr(h) for h in manure_headers]]
            row_warning_indices = []  # 1-based row indices that need red-text styling
            any_mismatch = False
            for mev in manure_events:
                interval_display = mev.get_manure_harvest_interval_display() if mev.manure_harvest_interval else "—"
                # Earliest safe harvest = application_date + interval days (if both present)
                earliest_harvest = None
                if mev.manure_application_date and mev.manure_harvest_interval:
                    try:
                        from datetime import timedelta

                        # manure_harvest_interval stored as "90", "120", or "na"
                        # (MANURE_INTERVAL_CHOICES on SoilManagementEvent). Split on
                        # "_" is a defensive no-op that also tolerates legacy
                        # "90_days" / "120_days" rows imported before the schema
                        # tightened — isdigit() filters out "na".
                        interval_str = str(mev.manure_harvest_interval).split("_")[0]
                        if interval_str.isdigit():
                            earliest_harvest = (
                                mev.manure_application_date + timedelta(days=int(interval_str))
                            ).isoformat()
                    except (ValueError, AttributeError):
                        earliest_harvest = None

                # Crop-rule check column. The page-2 consistency linter
                # surfaces these mismatches at the cover-page level; here
                # we annotate the offending row directly so the inspector
                # sees it in context, not just as an executive-summary line.
                rule_check_text = "—"
                rule_check_is_warning = False
                if expected_rule and mev.manure_harvest_interval:
                    interval_str = str(mev.manure_harvest_interval).split("_")[0]
                    if interval_str.isdigit():
                        try:
                            farmer_days = int(interval_str)
                            if farmer_days == expected_rule["days"]:
                                rule_check_text = f"OK — matches {expected_rule['cite']}"
                            else:
                                rule_check_text = (
                                    f"MISMATCH — crop requires "
                                    f"{expected_rule['days']}-day per "
                                    f"{expected_rule['cite']}"
                                )
                                rule_check_is_warning = True
                                any_mismatch = True
                        except ValueError:
                            pass

                manure_data.append(
                    [
                        self._cell(_fmt_date(mev.manure_application_date) if mev.manure_application_date else None),
                        self._cell(interval_display),
                        self._cell(_amendment_type_label(mev.amendment_type), 40),
                        self._cell(earliest_harvest),
                        self._cell(rule_check_text, 40),
                    ]
                )
                if rule_check_is_warning:
                    row_warning_indices.append(len(manure_data) - 1)
            manure_widths = [0.85 * inch, 1.0 * inch, 1.1 * inch, 1.05 * inch, 1.5 * inch]
            mt = Table(manure_data, colWidths=manure_widths, repeatRows=1)
            # Apply red text to mismatched rows so the inspector's eye is
            # drawn straight to the offending entry. Merge the warning
            # overlays into the base style's command list BEFORE the
            # single setStyle() call — ReportLab's Table.setStyle contract
            # between versions has varied between "append" and "replace",
            # so we assemble one TableStyle and set it once to be safe.
            # Coordinate convention: (col, row), 0-indexed, header is
            # row 0.
            base_cmds = list(self._base_table_style().getCommands())
            warning_overlay_cmds = []
            for ridx in row_warning_indices:
                warning_overlay_cmds.append(("TEXTCOLOR", (4, ridx), (4, ridx), colors.HexColor("#B71C1C")))
                warning_overlay_cmds.append(("FONTNAME", (4, ridx), (4, ridx), "Helvetica-Bold"))
            mt.setStyle(TableStyle(base_cmds + warning_overlay_cmds))
            elements.append(mt)
            if any_mismatch:
                elements.append(
                    Paragraph(
                        "<b>[WARNING] § 205.203(c)(1):</b> One or more manure "
                        "events above have a farmer-selected harvest interval "
                        "that does not match the soil-contact classification "
                        "required for this crop. The Pre-Export Consistency "
                        "Check on page 2 lists each mismatched event by date "
                        "with the correct interval. Update the event record "
                        "before submitting this dossier to a certifier — an "
                        "inspector will flag the mismatch as a record-keeping "
                        "failure even when no contamination occurred.",
                        self._warning_style(),
                    )
                )

        # --- Soil Notes (mirrors the Production Event Notes pattern) ---
        elements.extend(self._build_event_notes_subtable(events, "Soil Notes", SOIL_TYPE_LABELS))

        return elements

    # ------------------------------------------------------------------
    # Section 7: Pest Management
    # ------------------------------------------------------------------

    def _build_pest_section(self):
        elements = [self._section_header("Pest Management")]

        headers = [
            "Date",
            "Type",
            "Pest Species",
            "Identified By",
            "Pressure",
            "Damage %",
            "Area",
            "Threshold Met",
            "IPM Strategy",
            "Beneficial / Qty",
        ]

        events = list(self.production.history_pestmanagementevent_events.all().order_by("date"))

        if not events:
            elements.append(self._empty_table(headers))
            return elements

        header_row = [self._hdr(h) for h in headers]
        data = [header_row]
        has_threshold_without_rationale = False
        for ev in events:
            identified = ""
            if ev.identified_by:
                identified = ev.get_identified_by_display()
                if ev.identification_method:
                    identified += f" ({ev.identification_method[:30]})"

            if ev.action_threshold_met and not ev.threshold_rationale:
                has_threshold_without_rationale = True

            beneficial_display = ev.beneficial_species or ""
            if ev.release_quantity:
                beneficial_display = (
                    f"{beneficial_display} ({ev.release_quantity})" if beneficial_display else str(ev.release_quantity)
                )

            damage_display = f"{_fmt_float(ev.damage_percentage)}%" if ev.damage_percentage is not None else None
            area_display = (
                f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}".strip() if ev.area_covered else None
            )

            # F44: surface the quantitative UC-IPM monitoring count next to the qualitative pressure
            pressure_display = ev.pest_pressure_level or None
            if ev.monitoring_count is not None:
                # Compact units (the Pressure column is narrow) — e.g. "low · 5/leaf".
                _unit_lbls = {
                    "per_leaf": "/leaf",
                    "per_trap": "/trap",
                    "per_tree": "/tree",
                    "per_100_fruit": "/100fr",
                    "percent_infested": "% inf",
                    "per_sample": "/sample",
                }
                _cnt = f"{_fmt_float(ev.monitoring_count)}{_unit_lbls.get(ev.monitoring_unit, '')}"
                pressure_display = f"{pressure_display} · {_cnt}" if pressure_display else _cnt

            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(PEST_TYPE_LABELS.get(ev.type, _val(ev.type))),
                    self._cell(ev.pest_species, 50),
                    self._cell(identified or None, 40),
                    self._cell(pressure_display),
                    self._cell(damage_display),
                    self._cell(area_display),
                    self._cell(
                        "Not assessed"
                        if ev.action_threshold_met is None
                        else ("Yes" if ev.action_threshold_met else "No")
                    ),
                    self._cell(ev.ipm_strategy, 60),
                    self._cell(beneficial_display or None, 40),
                ]
            )

        col_widths = [
            0.55 * inch,  # Date
            0.55 * inch,  # Type
            0.85 * inch,  # Pest Species
            0.75 * inch,  # Identified By
            0.45 * inch,  # Pressure
            0.45 * inch,  # Damage %
            0.55 * inch,  # Area
            0.5 * inch,  # Threshold Met
            1.0 * inch,  # IPM Strategy
            0.8 * inch,  # Beneficial / Qty
        ]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # --- Beneficial-Release & Trap Detail (7 CFR 205.206) ---
        # Source traceability for introduced biological controls (supplier / lot / organic status)
        # and real trap-monitoring catch data — the main table stays readable; a certifier reads the
        # release provenance and trap pressure here.
        BR_ORGANIC_LABELS = {"yes": "Yes", "no": "No", "unknown": "Unknown"}
        TRAP_TYPE_LABELS = {
            "sticky": "Sticky card",
            "pheromone": "Pheromone lure",
            "delta": "Delta trap",
            "bucket_funnel": "Bucket / funnel",
            "other": "Other",
        }
        detail_events = [
            ev
            for ev in events
            if ev.beneficial_supplier
            or ev.beneficial_lot_number
            or ev.beneficial_organic_approved
            or ev.trap_type
            or ev.pest_catch_count is not None
        ]
        if detail_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Beneficial-Release &amp; Trap Detail (7 CFR 205.206)</b>",
                    self._sub_header_style(),
                )
            )
            detail_headers = [
                "Date",
                "Type",
                "Supplier",
                "Lot #",
                "Organic OK",
                "Trap Type",
                "Catch",
            ]
            detail_data = [[self._hdr(h) for h in detail_headers]]
            for ev in detail_events:
                detail_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(PEST_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(ev.beneficial_supplier, 40),
                        self._cell(ev.beneficial_lot_number, 30),
                        self._cell(BR_ORGANIC_LABELS.get(ev.beneficial_organic_approved)),
                        self._cell(TRAP_TYPE_LABELS.get(ev.trap_type) if ev.trap_type else None),
                        self._cell(str(ev.pest_catch_count) if ev.pest_catch_count is not None else None),
                    ]
                )
            detail_widths = [0.7 * inch, 1.0 * inch, 1.5 * inch, 0.9 * inch, 0.7 * inch, 1.0 * inch, 0.6 * inch]
            dt = Table(detail_data, colWidths=detail_widths, repeatRows=1)
            dt.setStyle(self._base_table_style())
            elements.append(dt)

        # NOP Threshold Monitoring & Rationale Sub-Table (7 CFR 205.206(a) + (e))
        # Per § 205.206(a), scouting/monitoring decisions are documented whether or
        # not an action threshold was met — hiding "below-threshold" rationale
        # would erase the IPM paper trail an inspector needs to confirm prevention.
        rationale_events = [ev for ev in events if ev.threshold_rationale and ev.threshold_rationale.strip()]
        if rationale_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Action Threshold Monitoring &amp; Rationale (7 CFR 205.206(a), (e))</b>",
                    self._sub_header_style(),
                )
            )
            rationale_headers = ["Date", "Pest Species", "Threshold Met", "Rationale"]
            rationale_data = [[self._hdr(h) for h in rationale_headers]]
            for ev in rationale_events:
                rationale_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(ev.pest_species, 40),
                        self._cell(
                            "Not assessed"
                            if ev.action_threshold_met is None
                            else ("Yes" if ev.action_threshold_met else "No")
                        ),
                        self._cell(ev.threshold_rationale, 120),
                    ]
                )
            rationale_widths = [0.7 * inch, 1.5 * inch, 0.7 * inch, 3.3 * inch]
            rt = Table(rationale_data, colWidths=rationale_widths, repeatRows=1)
            rt.setStyle(self._base_table_style())
            elements.append(rt)

        # Warning if threshold met but no rationale documented
        if has_threshold_without_rationale:
            elements.append(
                Paragraph(
                    "<b>[WARNING] NOP 7 CFR 205.206(e):</b> Some pest events have action threshold met "
                    "but no rationale documented. Organic operations must document why the threshold "
                    "was reached before applying any pest control material.",
                    self._warning_style(),
                )
            )

        # Warning when the IPM strategy field is blank — § 205.206(a) requires a
        # documented prevention strategy (cultural/mechanical/biological practices).
        # Inspector should never see a blank strategy on any pest event.
        missing_ipm = [ev for ev in events if not (ev.ipm_strategy and ev.ipm_strategy.strip())]
        if missing_ipm:
            elements.append(
                Paragraph(
                    f"<b>[WARNING] NOP 7 CFR 205.206(a):</b> {len(missing_ipm)} pest event(s) "
                    "missing IPM strategy. Operations must document the cultural, mechanical, "
                    "or biological prevention practices used before any pest-control intervention.",
                    self._warning_style(),
                )
            )

        # --- Pest Notes (mirrors the Production Event Notes pattern) ---
        elements.extend(self._build_event_notes_subtable(events, "Pest Notes", PEST_TYPE_LABELS))

        return elements

    # ------------------------------------------------------------------
    # Section 8: Equipment & Maintenance
    # ------------------------------------------------------------------

    def _build_equipment_section(self):
        """
        Equipment & Maintenance — includes cleaning logs per 7 CFR 205.272.

        NOP requires equipment cleaning documentation when equipment is shared
        between organic and conventional operations. This is a common audit
        non-conformance finding.
        """
        elements = [self._section_header("Equipment & Maintenance")]

        headers = [
            "Date",
            "Type",
            "Equipment",
            "Fuel Used",
            "Fuel Type",
            "Hours",
            "Area Worked",
        ]

        events = list(self.production.history_equipmentevent_events.all().order_by("date"))

        if not events:
            # Render the empty-equipment placeholder but do NOT return: the
            # Equipment Cleaning Logs + Post-Harvest Sanitation subsections
            # below live on ProductionEvent (EM subtype), which is independent
            # of EquipmentEvent. Early-returning here hid both from inspectors
            # on farms that don't track EquipmentEvent separately.
            elements.append(self._empty_table(headers))
        else:
            header_row = [self._hdr(h) for h in headers]
            data = [header_row]
            for ev in events:
                fuel = ev.fuel_consumed or ev.fuel_amount
                fuel_display = f"{_fmt_float(fuel)} {_val(ev.fuel_unit, '')}" if fuel else None
                hours = ev.hours_operated or ev.hours_used
                area = str(ev.area_worked) if ev.area_worked else (str(ev.area_covered) if ev.area_covered else None)

                data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(EQUIPMENT_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(ev.equipment_name),
                        self._cell(fuel_display),
                        self._cell(ev.fuel_type),
                        self._cell(str(hours) if hours else None),
                        self._cell(area),
                    ]
                )

            col_widths = [0.65 * inch, 0.9 * inch, 1.5 * inch, 0.85 * inch, 0.85 * inch, 0.6 * inch, 0.9 * inch]
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)

        # --- Equipment Cleaning Logs (7 CFR 205.272) ---
        # Required for shared equipment between organic and conventional.
        # Cleaning fields are on ProductionEvent (EM subtype), NOT EquipmentEvent.
        # An EM event counts as a cleaning record if it carries ANY of the
        # cleaning-log fields OR any of the post-harvest sanitizer fields —
        # otherwise the sanitation subsection below would be hidden on events
        # that recorded sanitizer detail without completing the cleaning core.
        cleaning_events = [
            ev
            for ev in self.production.history_productionevent_events.filter(type="EM")
            if ev.cleaning_date
            or ev.cleaning_method
            or ev.shared_with_conventional
            or ev.sanitizer_name
            or ev.sanitizer_ppm is not None
            or ev.sanitizer_nop_reference
            or ev.rinse_step_documented
        ]

        if cleaning_events or self.certification_type in ("organic", "roc", "all"):
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Equipment Cleaning Logs (7 CFR 205.272)</b>"))
            elements.append(self._spacer(0.05))

            if cleaning_events:
                cl_headers = [
                    "Equipment",
                    "Op Type",
                    "Cleaning Date",
                    "Method",
                    "Materials Used",
                    "Cleaned By",
                    "Shared w/ Conv.",
                    "Protocol Ref",
                ]
                cl_header_row = [self._hdr(h) for h in cl_headers]
                cl_data = [cl_header_row]

                # Map equipment_operation_type code → human-readable label for audit clarity
                EQ_OP_LABELS = {
                    "FC": "Fuel Consumption",
                    "MN": "Maintenance",
                    "RE": "Repair",
                    "CA": "Calibration",
                    "BD": "Breakdown",
                    "EI": "Inspection",
                    "CL": "Cleaning",
                }

                for ev in cleaning_events:
                    op_type_display = EQ_OP_LABELS.get(ev.equipment_operation_type, ev.equipment_operation_type or "—")
                    # FIX: ProductionEvent has no `equipment_used` column (that lives on
                    # SoilManagementEvent). Prefer equipment_type display, then event name,
                    # then description. The previous reference would AttributeError at runtime.
                    equipment_label = (
                        (ev.get_equipment_type_display() if ev.equipment_type else None) or ev.name or ev.description
                    )
                    cl_data.append(
                        [
                            self._cell(equipment_label, 30),
                            self._cell(op_type_display),
                            self._cell(_fmt_date(ev.cleaning_date) if ev.cleaning_date else None),
                            self._cell(ev.cleaning_method, 40),
                            self._cell(ev.cleaning_materials_used, 40),
                            self._cell(ev.cleaned_by),
                            self._cell("Yes" if ev.shared_with_conventional else "No"),
                            self._cell(ev.cleaning_protocol_reference, 50),
                        ]
                    )

                cl_widths = [
                    0.9 * inch,
                    0.75 * inch,
                    0.6 * inch,
                    0.9 * inch,
                    0.9 * inch,
                    0.7 * inch,
                    0.6 * inch,
                    0.8 * inch,
                ]
                t2 = Table(cl_data, colWidths=cl_widths, repeatRows=1)
                t2.setStyle(self._base_table_style())
                elements.append(t2)

                # --- Post-Harvest Sanitation subsection (7 CFR 205.272 + § 205.605) ---
                # Only render when at least one cleaning event has sanitizer detail;
                # no need to surface an empty table when sanitation isn't in scope.
                sanitizer_events = [
                    ev
                    for ev in cleaning_events
                    if ev.sanitizer_name
                    or ev.sanitizer_ppm is not None
                    or ev.sanitizer_nop_reference
                    or ev.rinse_step_documented
                ]
                if sanitizer_events:
                    elements.append(self._spacer(0.2))
                    elements.append(self._body("<b>Post-Harvest Sanitation (7 CFR 205.272 + § 205.605)</b>"))
                    elements.append(self._spacer(0.05))

                    san_headers = ["Date", "Sanitizer", "ppm", "Rinse Step", "NOP / § 205.605 Ref"]
                    san_data = [[self._hdr(h) for h in san_headers]]
                    for ev in sanitizer_events:
                        san_data.append(
                            [
                                self._cell(_fmt_date(ev.cleaning_date) if ev.cleaning_date else None),
                                self._cell(ev.sanitizer_name, 35),
                                self._cell(str(ev.sanitizer_ppm) if ev.sanitizer_ppm is not None else None),
                                self._cell("Yes" if ev.rinse_step_documented else "No"),
                                self._cell(ev.sanitizer_nop_reference, 45),
                            ]
                        )
                    san_widths = [
                        0.8 * inch,
                        1.5 * inch,
                        0.6 * inch,
                        0.8 * inch,
                        1.7 * inch,
                    ]
                    t_san = Table(san_data, colWidths=san_widths, repeatRows=1)
                    t_san.setStyle(self._base_table_style())
                    elements.append(t_san)

                    # Per-event attestation gaps: missing name / ppm / rinse step / ref → inspector flag.
                    gap_notes = []
                    for ev in sanitizer_events:
                        missing = []
                        if not (ev.sanitizer_name or "").strip():
                            missing.append("sanitizer name")
                        if ev.sanitizer_ppm is None:
                            missing.append("concentration (ppm)")
                        if not ev.rinse_step_documented:
                            missing.append("potable-water rinse step")
                        if not (ev.sanitizer_nop_reference or "").strip():
                            missing.append("§ 205.605 reference")
                        if missing:
                            label = _fmt_date(ev.cleaning_date) if ev.cleaning_date else (ev.name or "event")
                            gap_notes.append(f"{label}: missing {', '.join(missing)}")
                    if gap_notes:
                        elements.append(self._spacer(0.05))
                        elements.append(
                            self._body(
                                "<b>Inspector flag:</b> "
                                + "; ".join(gap_notes)
                                + ". § 205.272(b) requires rinse step after sanitizer contact; "
                                "§ 205.605 lists allowed synthetic sanitizers."
                            )
                        )
                    else:
                        elements.append(self._spacer(0.05))
                        elements.append(
                            self._body(
                                "Sanitizer, concentration, rinse step, and § 205.605 reference "
                                "documented for every post-harvest cleaning event."
                            )
                        )
            else:
                elements.append(
                    self._body(
                        "No equipment cleaning records found. If equipment is shared between "
                        "organic and conventional operations, cleaning logs are required."
                    )
                )

        return elements

    # ------------------------------------------------------------------
    # Section 8b: Weather Events
    # ------------------------------------------------------------------

    def _build_weather_section(self):
        """
        Weather events — supports § 205.201(a)(3) monitoring plan.

        Documents climate impacts (frost, heat waves, storms) so an inspector can
        cross-reference yield variances and emergency irrigation events to the
        weather they responded to. Most detail-level fields (temperature,
        start/end dates, wind speed) live in `WeatherEvent.extra_data` since the
        model itself only carries `type`, `observation`, and `extra_data`.
        """

        elements = [self._section_header("Weather Events")]

        events = list(self.production.history_weatherevent_events.all().order_by("date"))

        headers = ["Date", "Type", "Magnitude", "Start", "End", "Impact / Notes"]

        if not events:
            elements.append(self._empty_table(headers))
            return elements

        # ISO timestamps in extra_data ("2026-04-12T11:21") are noisy in a
        # date column — keep only the date portion so the table reads cleanly.
        def _iso_date_only(raw):
            if raw in (None, ""):
                return None
            s = str(raw)
            for sep in ("T", " "):
                if sep in s:
                    return s.split(sep, 1)[0]
            return s

        header_row = [self._hdr(h) for h in headers]
        data = [header_row]
        for ev in events:
            extra = ev.extra_data if isinstance(ev.extra_data, dict) else {}

            # Magnitude — pick the most specific value present and append the
            # unit recorded in extra_data when one exists. Temperature events
            # carry a `temperature_unit` ("F" or "C"); wind / precip / hail use
            # standard US units. Bare "°" without F/C would be ambiguous to an
            # auditor reading the PDF.
            temp_unit = str(extra.get("temperature_unit") or "F").upper()
            temp_suffix = f"°{temp_unit}" if temp_unit in ("F", "C") else "°"
            magnitude = None
            for key, unit in (
                ("highest_temperature", temp_suffix),
                ("lowest_temperature", temp_suffix),
                ("temperature", temp_suffix),
                ("wind_speed", " mph"),
                ("precipitation", " in"),
                ("humidity", "%"),
                ("hail_size", " in"),
            ):
                value = extra.get(key)
                if value not in (None, ""):
                    magnitude = f"{value}{unit}"
                    break

            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(WEATHER_TYPE_LABELS.get(ev.type, _val(ev.type))),
                    self._cell(magnitude),
                    self._cell(_iso_date_only(extra.get("start_date"))),
                    self._cell(_iso_date_only(extra.get("end_date"))),
                    self._cell(ev.observation, 80),
                ]
            )

        col_widths = [
            0.7 * inch,  # Date
            1.0 * inch,  # Type
            0.9 * inch,  # Magnitude
            0.85 * inch,  # Start
            0.85 * inch,  # End
            2.7 * inch,  # Impact / Notes
        ]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)
        return elements

    # ------------------------------------------------------------------
    # Section 9: Environmental Impact
    # ------------------------------------------------------------------

    def _build_carbon_section(self):
        elements = [self._section_header("Environmental Impact")]

        try:
            from carbon.models import CarbonEntry

            entries = list(CarbonEntry.objects.filter(production=self.production).select_related("source"))
        except Exception as exc:
            logger.warning("Could not load carbon data for audit: %s", exc)
            entries = []

        total_co2e = sum(e.co2e_amount or e.amount or 0.0 for e in entries)

        elements.append(
            self._label_value(
                "Total Carbon Emissions",
                f"{_fmt_float(total_co2e)} kg CO2e",
            )
        )
        elements.append(
            self._label_value("Methodology", "Direct Operational Emissions \u2014 EPA/USDA-sourced factors")
        )
        elements.append(
            self._label_value(
                "Transparency Score",
                f"{_fmt_float(self.production.transparency_score, 1)}%" if self.production.transparency_score else None,
            )
        )

        elements.append(self._spacer(0.15))

        if entries:
            headers = ["Source", "Type", "Amount (kg CO2e)", "Verification Status"]
            header_row = [self._hdr(h) for h in headers]
            data = [header_row]
            for entry in entries:
                source_name = entry.source.name if entry.source else _val(entry.description)
                data.append(
                    [
                        self._cell(source_name),
                        self._cell(entry.type),
                        self._cell(_fmt_float(entry.co2e_amount or entry.amount)),
                        self._cell(entry.verification_status),
                    ]
                )
            col_widths = [2.2 * inch, 1.0 * inch, 1.5 * inch, 1.6 * inch]
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)
        else:
            elements.append(self._body("No carbon emission records found for this production."))

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "Note: Emissions represent direct operational activities (fuel, fertilizer, equipment) "
                "within the farm boundary. Full lifecycle or supply-chain emissions are excluded.",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # Section 10: Traceability (FSMA 204)
    # ------------------------------------------------------------------

    def _build_traceability_section(self):
        p = self.production
        elements = [self._section_header("Traceability Record (FSMA 204)")]

        lat = lon = None
        try:
            lat = p.parcel.establishment.latitude
            lon = p.parcel.establishment.longitude
        except AttributeError:
            pass

        gps_display = f"{lat}, {lon}" if lat and lon else None

        rows = [
            ("Lot ID", p.lot_id),
            ("Harvest Date", _fmt_date(p.finish_date)),
            ("Harvest Location (GPS)", gps_display),
            (
                "Quantity Harvested",
                f"{_fmt_float(p.production_amount)} {_val(p.production_unit, '')}" if p.production_amount else None,
            ),
            ("Quality Grade", p.get_quality_grade_display() if p.quality_grade else None),
            ("Harvest Method", p.get_harvest_method_display() if p.harvest_method else None),
        ]

        # Harvester name from the last harvesting production event
        harvester = None
        try:
            harvest_ev = self.production.history_productionevent_events.filter(type="HA").order_by("-date").first()
            if harvest_ev:
                harvester = harvest_ev.performed_by or (
                    harvest_ev.created_by.get_full_name() if harvest_ev.created_by else None
                )
        except Exception:
            pass

        rows.append(("Operator / Harvester", harvester))

        for label, value in rows:
            elements.append(self._label_value(label, value))

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "This section supports FSMA Section 204 traceability requirements for "
                "produce supply chains. Lot IDs link to the production record in Trazo.",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # Section 11: Photo Evidence Summary
    # ------------------------------------------------------------------

    # Photos-section limits — keep the PDF reliably under ~30 MB even for a
    # production with dense photographic evidence. Inspectors who need every
    # photo have the dashboard URL; the PDF embeds the most useful subset.
    PHOTOS_MAX_PER_EVENT = 4
    PHOTOS_MAX_TOTAL = 60
    PHOTOS_FETCH_TIMEOUT_SEC = 8
    PHOTOS_TARGET_PIXEL_WIDTH = 1400

    # NOP-priority order: events whose photo evidence usually decides a finding
    # appear first in the gallery so a remote inspector can verify them without
    # paging through routine production shots. Default order is generalist
    # (fits GlobalG.A.P. / ROC / SCS); organic-specific NOP inspectors risk-
    # weight restricted-synthetic applications (copper/sulfur) and raw-manure
    # applications above routine pest monitoring, so the organic export
    # reorders the categories below via ``_photos_category_order_for()``.
    PHOTOS_CATEGORY_ORDER = [
        ("Pest Management", "history_pestmanagementevent_events"),
        ("Soil Management", "history_soilmanagementevent_events"),
        ("Chemical Applications", "history_chemicalevent_events"),
        ("Equipment / Cleaning", "history_equipmentevent_events"),
        ("Contamination & General", "history_generalevent_events"),
        ("Production Events", "history_productionevent_events"),
        ("Weather", "history_weatherevent_events"),
        ("Business / Certification", "history_businessevent_events"),
    ]

    # NOP-organic photo ordering: chemical applications (restricted synthetics
    # like copper hydroxide) precede soil/compost, which precede pest
    # management. Rationale: NOP inspectors flag synthetic applications and
    # raw-manure intervals first; IPM/pest evidence is secondary.
    PHOTOS_CATEGORY_ORDER_ORGANIC = [
        ("Chemical Applications", "history_chemicalevent_events"),
        ("Soil Management", "history_soilmanagementevent_events"),
        ("Pest Management", "history_pestmanagementevent_events"),
        ("Equipment / Cleaning", "history_equipmentevent_events"),
        ("Contamination & General", "history_generalevent_events"),
        ("Production Events", "history_productionevent_events"),
        ("Weather", "history_weatherevent_events"),
        ("Business / Certification", "history_businessevent_events"),
    ]

    def _photos_category_order_for(self):
        """Return the category ordering appropriate to this export's cert type."""
        if self.certification_type == "organic":
            return self.PHOTOS_CATEGORY_ORDER_ORGANIC
        return self.PHOTOS_CATEGORY_ORDER

    def _photo_embed_environment(self):
        """
        Classify the environment for photo embedding so the PDF can surface
        an accurate banner. The three states matter to an inspector:

          * ``prod_s3_ok``         - prod with S3 configured; any fetch failure
                                     is a genuine error worth flagging loudly.
          * ``prod_s3_misconfig``  - prod with ``AWS_STORAGE_BUCKET_NAME`` unset
                                     (should never ship; banner fails hardest).
          * ``dev_no_s3``          - local dev without S3; "None.s3" URLs are
                                     expected, not a compliance issue.

        Cached on the instance so we don't re-read settings for every photo.
        """
        if hasattr(self, "_photo_env_cache"):
            return self._photo_env_cache
        try:
            from django.conf import settings

            debug = bool(getattr(settings, "DEBUG", False))
            bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)
        except Exception:
            debug, bucket = True, None
        if bucket:
            mode = "prod_s3_ok" if not debug else "dev_with_s3"
        else:
            mode = "dev_no_s3" if debug else "prod_s3_misconfig"
        self._photo_env_cache = {"mode": mode, "bucket": bucket, "debug": debug}
        return self._photo_env_cache

    def _fetch_image_for_pdf(self, image_obj):
        """
        Download an image from S3 (or local storage), normalize, resize, and
        return a BytesIO of JPEG bytes ready to embed via ReportLab. Returns
        None on any failure — callers must render a placeholder in that case.
        Failures are tracked in two buckets:

          * dev-expected (``_photos_dev_skipped``) — S3 not configured locally.
          * prod-failure (``_photos_prod_failed``) — real error the inspector
            must know about; first 10 errors retained in
            ``_photos_prod_errors`` for structured per-photo rendering.

        Failures are logged but never raise; one bad image must not break the
        whole PDF.
        """
        env = self._photo_embed_environment()
        url = None
        try:
            url = image_obj.thumbnail_url("md")
        except Exception:
            url = None
        if not url:
            try:
                url = image_obj.url
            except Exception:
                url = None
        if not url:
            # No URL at all — count as prod-failure in prod, dev-skip in dev.
            if env["mode"].startswith("prod"):
                self._photos_prod_failed += 1
                if len(self._photos_prod_errors) < 10:
                    self._photos_prod_errors.append(("<no-url>", "thumbnail_url and url both unavailable"))
            else:
                self._photos_dev_skipped += 1
            return None
        # Malformed-bucket URL: expected in dev_no_s3, a critical misconfig in prod.
        if "None.s3" in url or "://None" in url:
            if env["mode"] in ("dev_no_s3", "dev_with_s3"):
                logger.info("Audit photo S3 URL has None bucket (dev, expected): %s", url)
                self._photos_dev_skipped += 1
            else:
                logger.error(
                    "Audit photo S3 URL has None bucket in prod — AWS_STORAGE_BUCKET_NAME " "not configured: %s",
                    url,
                )
                self._photos_prod_failed += 1
                if len(self._photos_prod_errors) < 10:
                    self._photos_prod_errors.append((url, "S3 bucket not configured (None.s3 URL)"))
            return None

        try:
            import requests
            from PIL import Image as PILImage

            resp = requests.get(url, timeout=self.PHOTOS_FETCH_TIMEOUT_SEC)
            if resp.status_code != 200:
                logger.warning("Audit photo fetch %s returned HTTP %s", url, resp.status_code)
                self._photos_prod_failed += 1
                if len(self._photos_prod_errors) < 10:
                    self._photos_prod_errors.append((url, f"HTTP {resp.status_code}"))
                return None

            img = PILImage.open(io.BytesIO(resp.content))
            # ReportLab's JPEG embedder needs RGB. PNG-with-alpha and grayscale
            # both flatten to white-background RGB.
            if img.mode in ("RGBA", "LA", "P"):
                background = PILImage.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            if max(img.size) > self.PHOTOS_TARGET_PIXEL_WIDTH:
                img.thumbnail((self.PHOTOS_TARGET_PIXEL_WIDTH, self.PHOTOS_TARGET_PIXEL_WIDTH), PILImage.LANCZOS)

            out = io.BytesIO()
            img.save(out, format="JPEG", quality=78, optimize=True)
            out.seek(0)
            return out
        except Exception as exc:
            logger.warning("Audit photo embed failed for %s: %s", url, exc)
            env = self._photo_embed_environment()
            if env["mode"].startswith("prod"):
                self._photos_prod_failed += 1
                if len(self._photos_prod_errors) < 10:
                    self._photos_prod_errors.append((url, f"fetch/decode error: {exc!r}"))
            else:
                self._photos_dev_skipped += 1
            return None

    def _photo_caption(self, image_obj, idx, total):
        """
        Build a short caption with the metadata an inspector needs to trust the
        photo: ordinal, capture date (EXIF when present, else upload date), GPS,
        and Vision-API validation status. Falls back gracefully when fields are
        missing.
        """
        extra = image_obj.extra_data if isinstance(image_obj.extra_data, dict) else {}
        parts = [f"Photo {idx} of {total}"]

        # EXIF capture date if Vision API or upload pipeline stored it.
        captured = extra.get("captured_at") or extra.get("exif_datetime")
        if captured:
            captured_str = str(captured)
            if "T" in captured_str:
                captured_str = captured_str.split("T", 1)[0]
            elif " " in captured_str:
                captured_str = captured_str.split(" ", 1)[0]
            parts.append(f"taken {captured_str}")
        elif image_obj.created_at:
            parts.append(f"uploaded {image_obj.created_at.date().isoformat()}")

        # GPS coordinates if EXIF carried them through.
        gps = extra.get("gps") if isinstance(extra.get("gps"), dict) else None
        if gps:
            lat = gps.get("lat") or gps.get("latitude")
            lng = gps.get("lng") or gps.get("longitude") or gps.get("lon")
            if lat is not None and lng is not None:
                try:
                    parts.append(f"GPS {float(lat):.4f}, {float(lng):.4f}")
                except (TypeError, ValueError):
                    pass

        # Vision-API validation status (Trazo runs Google Vision on each upload
        # to confirm the image is agricultural — flagged-as-non-agri is rare
        # but worth surfacing for the auditor.)
        validation = extra.get("content_validation")
        if isinstance(validation, dict):
            if validation.get("is_valid") is False:
                parts.append("[Vision: NON-AGRICULTURAL FLAG]")
            elif validation.get("is_valid") is True:
                parts.append("Vision-validated")

        # File size for inspector confidence (>50 KB suggests not a placeholder
        # / corrupt image). Skip when missing.
        if image_obj.file_size and image_obj.file_size >= 1024:
            kb = image_obj.file_size / 1024
            parts.append(f"{kb:.0f} KB" if kb < 1024 else f"{kb / 1024:.1f} MB")

        return " · ".join(parts)

    def _build_event_photo_block(self, event, category_label, photos_remaining):
        """
        Return a list of flowables for one event's photo block: a one-line
        header (category, date, description, total count) followed by a 2-column
        grid of up to PHOTOS_MAX_PER_EVENT photos. The block is wrapped in
        KeepTogether so the header doesn't orphan from its photos across page
        breaks.

        `photos_remaining` is the global budget so callers can stop adding
        photos once the document-wide cap is reached.
        """
        try:
            all_photos = list(event.album.images.all().order_by("id")) if event.album else []
        except Exception:
            all_photos = []
        if not all_photos:
            return [], 0

        photos_for_this_event = all_photos[: min(self.PHOTOS_MAX_PER_EVENT, photos_remaining)]
        if not photos_for_this_event:
            return [], 0

        block = []

        # Header line — keep it dense; auditor reads this row first.
        type_label = ""
        if hasattr(event, "type") and event.type:
            type_label = (
                CHEMICAL_TYPE_LABELS.get(event.type)
                or SOIL_TYPE_LABELS.get(event.type)
                or PEST_TYPE_LABELS.get(event.type)
                or PRODUCTION_TYPE_LABELS.get(event.type)
                or EQUIPMENT_TYPE_LABELS.get(event.type)
                or WEATHER_TYPE_LABELS.get(event.type)
                or str(event.type)
            )
        descriptor = (
            getattr(event, "description", None)
            or getattr(event, "name", None)
            or getattr(event, "commercial_name", None)
            or getattr(event, "amendment_type", None)
            or getattr(event, "pest_species", None)
            or ""
        )
        # Escape ONLY the user-content slots (descriptor + type label) — the
        # <b>/<i> tags are ours and must reach ReportLab's Paragraph parser
        # un-escaped so they render as bold/italic instead of literal text.
        # Earlier version escaped the whole header and the markup leaked
        # through as "&lt;b&gt;..." in the PDF (caught in screenshot review).
        safe_descriptor = self._safe_narrative(_truncate(str(descriptor), 80)) if descriptor else ""
        safe_type_label = self._safe_narrative(type_label) if type_label else ""
        header_text = (
            f"<b>{category_label}</b> · {_fmt_date(event.date)}"
            + (f" · <i>{safe_type_label}</i>" if safe_type_label else "")
            + (f" · {safe_descriptor}" if safe_descriptor else "")
            + f" · {len(all_photos)} photo(s) on file, {len(photos_for_this_event)} embedded below"
        )
        header_style = ParagraphStyle(
            "PhotoBlockHeader",
            parent=self._styles["body"],
            fontSize=8,
            textColor=DARK_GRAY,
            spaceBefore=6,
            spaceAfter=4,
        )
        block.append(Paragraph(header_text, header_style))

        # Build the grid. Two photos per row at 2.7" wide x 2.1" max height
        # (proportional). Each cell is [Image, caption Paragraph]. We use
        # Image with `kind="proportional"` so portrait shots aren't squashed.
        cell_caption_style = ParagraphStyle(
            "PhotoCaption",
            parent=self._styles["body"],
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#555555"),
            alignment=TA_CENTER,
            spaceBefore=2,
            spaceAfter=4,
        )
        photo_cells = []
        for idx, photo in enumerate(photos_for_this_event, 1):
            buf = self._fetch_image_for_pdf(photo)
            caption_text = self._photo_caption(photo, idx, len(photos_for_this_event))
            if buf is None:
                self._photos_not_embedded += 1
                # P0-2 — Render photo metadata instead of a useless placeholder.
                # Inspector sees: filename, upload date, file size — enough to
                # request the image directly or verify it in the dashboard.
                meta_parts = [f"<i>[Photo {idx}: image not embedded]</i>"]
                fname = None
                try:
                    fname = os.path.basename(photo.image.name) if photo.image and photo.image.name else None
                except Exception:
                    pass
                if fname:
                    meta_parts.append(f"File: {self._safe_narrative(fname)}")
                if photo.created_at:
                    meta_parts.append(f"Uploaded: {photo.created_at.date().isoformat()}")
                if photo.file_size:
                    kb = photo.file_size / 1024
                    meta_parts.append(f"Size: {kb:.0f} KB" if kb < 1024 else f"Size: {kb / 1024:.1f} MB")
                meta_parts.append("Visible in dashboard")
                cell = [
                    Paragraph("<br/>".join(meta_parts), cell_caption_style),
                    Paragraph(self._safe_narrative(caption_text), cell_caption_style),
                ]
            else:
                rl_img = RLImage(buf, width=2.7 * inch, height=2.1 * inch, kind="proportional")
                cell = [rl_img, Paragraph(self._safe_narrative(caption_text), cell_caption_style)]
            photo_cells.append(cell)

        # Pack cells two per row.
        rows = []
        for i in range(0, len(photo_cells), 2):
            row = [photo_cells[i]]
            row.append(photo_cells[i + 1] if i + 1 < len(photo_cells) else "")
            rows.append(row)

        grid_style = TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
        grid = Table(rows, colWidths=[3.3 * inch, 3.3 * inch])
        grid.setStyle(grid_style)
        block.append(grid)

        # Wrap in KeepTogether so a 4-photo block doesn't orphan its header
        # at the bottom of a page. ReportLab will start a new page if needed.
        return [KeepTogether(block)], len(photos_for_this_event)

    def _build_photos_section(self):
        """
        Photo Evidence section — three layers:
          1. Summary table (count per event with photos) for fast scanning.
          2. Embedded photo gallery, NOP-priority order, with captions.
          3. Footer note explaining the dashboard cross-reference and the
             SHA-256 audit trail Trazo retains for tamper-evidence.
        """

        elements = [self._section_header("Photo Evidence")]

        # Track photos that fail to embed. Reset both counters so a previous
        # section's failures don't leak into this one.
        self._photos_not_embedded = 0
        self._photos_dev_skipped = 0
        self._photos_prod_failed = 0
        self._photos_prod_errors = []

        # Environment banner — inspector sees this FIRST, before the summary
        # table, so there's no ambiguity about why embeds may be missing.
        env = self._photo_embed_environment()
        if env["mode"] == "prod_s3_misconfig":
            elements.append(
                Paragraph(
                    "<b>[ERROR] PDF generated without S3 configuration.</b> "
                    "<code>AWS_STORAGE_BUCKET_NAME</code> is not set in this environment, "
                    "so NO photo evidence can be embedded for inspector review. "
                    "This PDF should not be relied upon for a real audit until "
                    "the S3 configuration is corrected and the report is re-exported.",
                    self._warning_style(),
                )
            )
            elements.append(self._spacer(0.08))
        elif env["mode"] in ("dev_no_s3", "dev_with_s3"):
            elements.append(
                Paragraph(
                    "<i>[Development mode]</i> This PDF was generated in a development "
                    "environment. Photo metadata (filename, upload date, size) is shown "
                    "inline in place of embedded images. Re-export from production to "
                    "embed the actual photos.",
                    self._styles["footer_note"],
                )
            )
            elements.append(self._spacer(0.05))

        # Pull all events across categories once. Cache for both the summary
        # table and the gallery so we don't double-query.
        category_events = []
        for label, related_name in self._photos_category_order_for():
            qs = getattr(self.production, related_name).all().order_by("date")
            category_events.append((label, list(qs)))

        # ---------- Layer 1: summary table ----------
        summary_headers = ["Event Category", "Event Date", "Description", "Photos"]
        summary_header_row = [self._hdr(h) for h in summary_headers]
        summary_data = [summary_header_row]
        total_photos = 0

        for category_label, events in category_events:
            for ev in events:
                count = _photo_count(ev)
                if count > 0:
                    summary_data.append(
                        [
                            self._cell(category_label),
                            self._cell(_fmt_date(ev.date)),
                            self._cell(ev.description if hasattr(ev, "description") else None, 90),
                            self._cell(str(count)),
                        ]
                    )
                    total_photos += count

        if len(summary_data) == 1:
            elements.append(self._body("No photo evidence has been attached to events in this production."))
            elements.append(self._spacer(0.1))
            elements.append(
                Paragraph(
                    "When photos are uploaded, Trazo records each file's S3 object key, "
                    "upload timestamp, file size, and uploader account on the producer "
                    "dashboard for audit-trail cross-reference.",
                    self._styles["footer_note"],
                )
            )
            return elements

        col_widths = [1.5 * inch, 0.85 * inch, 4.0 * inch, 0.65 * inch]
        summary_table = Table(summary_data, colWidths=col_widths, repeatRows=1)
        summary_table.setStyle(self._base_table_style())
        elements.append(summary_table)
        elements.append(self._spacer(0.08))
        elements.append(self._label_value("Total Photos Attached", str(total_photos)))

        # ---------- Layer 2: embedded gallery ----------
        elements.append(self._spacer(0.18))
        elements.append(
            Paragraph(
                "<b>Photo Gallery</b> — embedded for inspector pre-read",
                self._sub_header_style(),
            )
        )
        elements.append(
            Paragraph(
                (
                    "Photos appear in NOP-organic priority order: chemical "
                    "applications (restricted synthetics), soil/compost + manure, "
                    "pest management, equipment cleaning, contamination, then "
                    "routine production. "
                    if self.certification_type == "organic"
                    else "Photos appear in NOP-priority order: pest, soil/compost, "
                    "chemical, equipment cleaning, contamination, then routine production. "
                )
                + "Each photo carries its capture date and (when EXIF was preserved at "
                "upload) its GPS coordinates and Vision-API validation status. "
                f"Embedded photos are resized to ~{self.PHOTOS_TARGET_PIXEL_WIDTH}px "
                "wide for PDF size; originals remain in the dashboard.",
                self._styles["footer_note"],
            )
        )
        elements.append(self._spacer(0.05))

        photos_remaining = self.PHOTOS_MAX_TOTAL
        embedded_count = 0
        skipped_events = 0
        for category_label, events in category_events:
            for ev in events:
                if photos_remaining <= 0:
                    if _photo_count(ev) > 0:
                        skipped_events += 1
                    continue
                block_elements, embedded = self._build_event_photo_block(ev, category_label, photos_remaining)
                if block_elements:
                    elements.extend(block_elements)
                    photos_remaining -= embedded
                    embedded_count += embedded

        # Prominent failure banner for PROD-only failures (dev-skipped photos
        # are expected and covered by the dev-mode header banner). Listed with
        # per-photo error codes so the inspector can triage quickly.
        if self._photos_prod_failed > 0:
            total_attempts = embedded_count + self._photos_prod_failed
            elements.append(self._spacer(0.08))
            elements.append(
                Paragraph(
                    f"<b>[WARNING: {self._photos_prod_failed} of {total_attempts} "
                    "photo(s) could not be embedded — S3 access error.]</b> "
                    "Inspector should verify originals via the Trazo producer dashboard "
                    "and treat this section as incomplete.",
                    self._warning_style(),
                )
            )
            if self._photos_prod_errors:
                err_lines = []
                for url, reason in self._photos_prod_errors:
                    display_url = url if len(url) < 80 else url[:77] + "…"
                    err_lines.append(f"• {self._safe_narrative(reason)} — {self._safe_narrative(display_url)}")
                if self._photos_prod_failed > len(self._photos_prod_errors):
                    err_lines.append(
                        f"• (additional {self._photos_prod_failed - len(self._photos_prod_errors)}"
                        " error(s) not shown)"
                    )
                elements.append(Paragraph("<br/>".join(err_lines), self._styles["footer_note"]))

        # Dev-skipped photos — quiet note, not a failure.
        if self._photos_dev_skipped > 0 and self._photos_prod_failed == 0:
            elements.append(self._spacer(0.06))
            elements.append(
                Paragraph(
                    f"<i>[{self._photos_dev_skipped} photo(s) rendered as metadata-only "
                    "because this PDF was generated in a development environment without "
                    "S3. Production exports will embed the actual images.]</i>",
                    self._styles["footer_note"],
                )
            )

        # ---------- Layer 3: footer with cap notice + tamper-evidence ----------
        elements.append(self._spacer(0.12))
        if skipped_events > 0 or embedded_count >= self.PHOTOS_MAX_TOTAL:
            elements.append(
                Paragraph(
                    f"<b>Note:</b> Embedded {embedded_count} of {total_photos} photos "
                    f"(PDF cap: {self.PHOTOS_MAX_TOTAL} photos to keep file size under "
                    "~30 MB). The remaining photos are available in the Trazo producer "
                    "dashboard under each event.",
                    self._styles["footer_note"],
                )
            )
        elements.append(
            Paragraph(
                "Audit-trail metadata for each embedded photo: original S3 object key, "
                "upload timestamp, file size, and uploader account are retained in the "
                "producer dashboard and can be cross-referenced against the photos shown "
                "above. Captions reflect EXIF capture date and GPS when those tags were "
                "preserved at upload; photos taken on a device that strips EXIF will show "
                "the upload date instead.",
                self._styles["footer_note"],
            )
        )
        return elements

    # ------------------------------------------------------------------
    # Section 11b: Additional Farmer-Recorded Data (Custom Fields)
    # ------------------------------------------------------------------

    def _build_custom_data_section(self):
        """
        Custom fields added by the farmer on any event.

        Auditors need to see ALL data recorded by the farmer, including
        ad-hoc fields they created (lab reference numbers, supplier certs,
        equipment calibration notes, etc.). Omitting these would be an
        incomplete audit record.
        """
        elements = [self._section_header("Additional Farmer-Recorded Data")]

        from history.custom_fields import extract_custom_fields_for_display

        event_querysets = [
            ("Production", self.production.history_productionevent_events.all()),
            ("Chemical", self.production.history_chemicalevent_events.all()),
            ("Soil Management", self.production.history_soilmanagementevent_events.all()),
            ("Pest Management", self.production.history_pestmanagementevent_events.all()),
            ("Equipment", self.production.history_equipmentevent_events.all()),
            ("General", self.production.history_generalevent_events.all()),
            ("Weather", self.production.history_weatherevent_events.all()),
            ("Business", self.production.history_businessevent_events.all()),
        ]

        headers = ["Event Date", "Event Category", "Event Description", "Field Name", "Field Value", "Type"]
        header_row = [self._hdr(h) for h in headers]
        data = [header_row]

        for category_label, qs in event_querysets:
            for ev in qs:
                extra = getattr(ev, "extra_data", None)
                if not extra or not isinstance(extra, dict):
                    continue

                # Extract all custom fields (visibility=all for audit — auditors see everything)
                custom_fields = extract_custom_fields_for_display(extra, visibility_filter="all", include_empty=False)

                for cf in custom_fields:
                    data.append(
                        [
                            self._cell(_fmt_date(ev.date)),
                            self._cell(category_label),
                            self._cell(ev.description, 50),
                            self._cell(cf.get("label", ""), 40),
                            self._cell(cf.get("value", ""), 60),
                            self._cell(cf.get("field_type", "text")),
                        ]
                    )

        if len(data) == 1:
            elements.append(self._body("No additional custom fields were recorded on events in this production."))
        else:
            col_widths = [0.65 * inch, 0.75 * inch, 1.5 * inch, 1.1 * inch, 1.8 * inch, 0.5 * inch]
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)
            elements.append(self._spacer(0.05))
            elements.append(self._label_value("Total Custom Fields", str(len(data) - 1)))

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "Custom fields are farmer-created data points added during event documentation. "
                "All fields are self-reported. Field visibility: consumer (shown on QR page), "
                "internal (producer only), b2b (shared with buyers).",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # Section 12: Active Certification Summary
    # ------------------------------------------------------------------

    def _build_certifications_section(self):
        """
        Render two tables: Active Certifications (is_active=True) and
        Historical / Expired (is_active=False). Inspector-review finding:
        an expired cert in an "Active" table is flagged as misleading; split
        prevents any ambiguity.
        """
        from certifications.models import Certification

        elements = []

        try:
            establishment = self.production.parcel.establishment
        except AttributeError:
            elements.append(self._section_header("Active Certification Summary"))
            elements.append(self._body("Establishment data not available."))
            return elements

        all_certs = list(
            Certification.objects.filter(establishment=establishment).order_by("certification_type", "-created_at")
        )

        if not all_certs:
            elements.append(self._section_header("Active Certification Summary"))
            elements.append(self._body("No certification records found for this establishment."))
            return elements

        today = date.today()
        warning_threshold_days = 90

        active_certs = [c for c in all_certs if c.is_active]
        historical_certs = [c for c in all_certs if not c.is_active]

        # Column header uses neutral wording. Per NOP 2603 and 7 CFR
        # § 205.404(d), USDA Organic certificates do NOT have expiration
        # dates — the stored date is the annual-update / anniversary due
        # date. Private-label certifications (ROC, GlobalG.A.P., SCS) DO
        # have true expiry semantics. "Next Review Date" reads correctly
        # for BOTH cases without putting the misleading word "Expiry"
        # anywhere in a USDA Organic row.
        headers = [
            "Certification Type",
            "Certifier",
            "Certificate #",
            "Effective Date",
            "Next Review Date",
            "Verification",
        ]
        col_widths = [
            1.2 * inch,  # Certification Type
            1.2 * inch,  # Certifier
            1.0 * inch,  # Certificate #
            0.85 * inch,  # Effective Date
            1.1 * inch,  # Next Review Date
            1.35 * inch,  # Verification
        ]

        def _verification_label(cert):
            if cert.verification_status == "verified":
                return "Verified (USDA OID)"
            if cert.verification_status == "self_reported":
                return "Self-Reported"
            if cert.verification_status in ("expired", "revoked", "suspended"):
                return cert.get_verification_status_display()
            return _val(cert.get_verification_status_display())

        # USDA Organic certificates do NOT expire — per 7 CFR § 205.404(d) a
        # certification "continues in effect until surrendered by the organic
        # operation or suspended or revoked by the certifying agent..." NOP
        # 2603 likewise instructs that certificates cannot include expiration
        # dates. For USDA Organic rows we render the stored date as
        # "Anniversary: YYYY-MM-DD" and explicitly state no expiry applies;
        # private-label certs continue to render as "Expires: YYYY-MM-DD"
        # because that IS their legal semantic.
        _USDA_ORGANIC_TYPES = ("usda_organic", "ccof", "ccof_organic", "ams_organic")

        def _is_usda_organic(cert):
            ctype = (getattr(cert, "certification_type", "") or "").lower()
            # Exact key match against the USDA NOP set. CCOF acts as a USDA-
            # accredited certifying agent, so a CCOF-issued NOP certificate
            # falls under the same § 205.404(d) "no expiry" rule.
            return ctype in _USDA_ORGANIC_TYPES

        def _date_cell_display(cert):
            if _is_usda_organic(cert):
                # NOP 2603: certificates cannot include expiration dates.
                # The stored date is the next annual-update due date. We
                # render it with the "Anniversary:" prefix and never use
                # the word "expiry" / "expires" for USDA Organic rows.
                if cert.expiry_date:
                    return f"Anniversary: {_fmt_date(cert.expiry_date)}"
                return "N/A (does not expire per \u00a7 205.404(d))"
            # Private-label cert — actual expiry semantics.
            if not cert.expiry_date:
                return "—"
            base = _fmt_date(cert.expiry_date)
            days_remaining = (cert.expiry_date - today).days
            if days_remaining < 0:
                return f"Expires: {base} (EXPIRED)"
            if days_remaining <= warning_threshold_days:
                return f"Expires: {base} (in {days_remaining}d)"
            return f"Expires: {base}"

        def _build_table(certs):
            data = [[self._hdr(h) for h in headers]]
            for cert in certs:
                data.append(
                    [
                        self._cell(cert.get_certification_type_display()),
                        self._cell(cert.certifier_name, 50),
                        self._cell(cert.certification_number, 40),
                        self._cell(_fmt_date(cert.effective_date)),
                        self._cell(_date_cell_display(cert)),
                        self._cell(_verification_label(cert)),
                    ]
                )
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            return t

        # --- Active certifications ----------------------------------------
        elements.append(self._section_header("Active Certification Summary"))
        if active_certs:
            elements.append(_build_table(active_certs))
        else:
            elements.append(
                Paragraph(
                    "<b>NO ACTIVE CERTIFICATIONS.</b> For a USDA Organic audit "
                    "export, at least one active verified organic certification "
                    "is expected.",
                    self._warning_style(),
                )
            )
        elements.append(self._spacer(0.08))
        elements.append(
            Paragraph(
                "Verification status reflects cross-reference against the USDA "
                "Organic Integrity Database for USDA Organic certifications. All "
                "other certifications are self-reported unless independently "
                "audited. <b>USDA Organic certificates do not expire</b> per "
                "7 CFR \u00a7 205.404(d) \u2014 the date shown for those rows is "
                "the next annual update / anniversary, not a regulatory expiry. "
                "Private-label certifications (ROC, GlobalG.A.P., SCS, etc.) "
                "do expire; expiry warnings shown for those expiring within "
                "90 days.",
                self._styles["footer_note"],
            )
        )

        # --- Historical / Expired certifications --------------------------
        # Claim-defensibility window: an expired cert is "relevant" to this
        # production if and only if it was ACTIVE AT SOME POINT during the
        # production period (effective_date <= production_end AND expiry_date
        # >= production_start). That's the regulatory question an inspector
        # asks when reviewing claims made on this lot. A cert that expired
        # months before production started was never backing the claim; a
        # cert with no effective_date on file is treated as "unknown — err
        # toward inclusion" so the inspector sees it. Everything else is
        # summarised to a single line with a dossier referral.
        if historical_certs:
            production_start = self.production.start_date.date() if self.production.start_date else today
            production_end = self.production.finish_date.date() if self.production.finish_date else today

            def _was_active_during_production(cert):
                """True when the cert's validity window overlaps the production
                period. Null effective_date → err toward showing (unknown
                start is not grounds to hide a cert the inspector may care
                about). Null expiry_date → the cert is still active today,
                wouldn't be in historical_certs in the first place, but be
                defensive."""
                expiry_ok = cert.expiry_date is None or cert.expiry_date >= production_start
                effective_ok = cert.effective_date is None or cert.effective_date <= production_end
                return expiry_ok and effective_ok

            relevant_historical = [c for c in historical_certs if _was_active_during_production(c)]
            hidden_count = len(historical_certs) - len(relevant_historical)

            if relevant_historical:
                elements.append(self._spacer(0.15))
                elements.append(
                    self._section_header("Historical / Expired Certifications (active during this production)")
                )
                elements.append(_build_table(relevant_historical))
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        "These certifications were active at some point during the "
                        f"production period ({production_start.isoformat()} to "
                        f"{production_end.isoformat()}) and may have supported claims "
                        "made on this lot. They are no longer active and do NOT "
                        "support current organic claims.",
                        self._styles["footer_note"],
                    )
                )
                if hidden_count:
                    elements.append(self._spacer(0.04))
                    elements.append(
                        Paragraph(
                            f"{hidden_count} additional historical certification"
                            f"{'s' if hidden_count != 1 else ''} (never active during "
                            "this production period) available in the establishment "
                            "dossier; omitted here to keep the audit focus on the "
                            "production under review.",
                            self._styles["footer_note"],
                        )
                    )
            elif hidden_count:
                # None of the historical certs overlapped production. Provide
                # continuity context so "expired" does not imply a gap in
                # certification. An inspector reviewing a long-certified
                # operation expects to see the chain: earliest effective date
                # on record → current active certificate, with no gap.
                earliest_historical_effective = None
                for hc in historical_certs:
                    if hc.effective_date is None:
                        continue
                    if earliest_historical_effective is None or hc.effective_date < earliest_historical_effective:
                        earliest_historical_effective = hc.effective_date
                current_active_effective = None
                for ac in active_certs:
                    if ac.effective_date is None:
                        continue
                    if current_active_effective is None or ac.effective_date < current_active_effective:
                        current_active_effective = ac.effective_date
                elements.append(self._spacer(0.05))
                if earliest_historical_effective and current_active_effective:
                    elements.append(
                        Paragraph(
                            f"Note: establishment has {hidden_count} historical "
                            f"certification{'s' if hidden_count != 1 else ''} on file "
                            f"pre-dating the current active certificate. Certification "
                            f"continuity: first certified "
                            f"{earliest_historical_effective.isoformat()}; current "
                            f"certificate effective "
                            f"{current_active_effective.isoformat()}. None overlap "
                            "this production period, so they do not back the "
                            "organic claim on this lot directly; full history "
                            "available in the establishment dossier on request.",
                            self._styles["footer_note"],
                        )
                    )
                else:
                    elements.append(
                        Paragraph(
                            f"Note: establishment has {hidden_count} historical / "
                            f"expired certification{'s' if hidden_count != 1 else ''} "
                            "on file from earlier periods; none overlap this "
                            "production period. This is a historical record for "
                            "the operation and does not imply a gap in the "
                            "current certification. Full history available in the "
                            "establishment dossier on request.",
                            self._styles["footer_note"],
                        )
                    )

        return elements

    # ------------------------------------------------------------------
    # Section 12b: Inspection & Compliance Event History
    # ------------------------------------------------------------------

    def _build_business_events_section(self):
        """
        Chronological log of certification, compliance, and inspection events
        (BusinessEvent rows) tied to this production.

        The Active Certification Summary above lists current certifications held
        by the establishment. This section documents the *events* — annual
        inspections, compliance checks, third-party audits — that the farmer
        logged during this production cycle. NOP auditors rely on this trail
        (inspector name, certificate reference, verification status) to trace
        the path from farm practices back to the certifying body.
        """
        elements = [self._section_header("Inspection & Compliance Event History")]

        events = list(self.production.history_businessevent_events.all().order_by("date"))

        if not events:
            elements.append(
                self._body("No certification, inspection, or compliance events were logged for this production.")
            )
            return elements

        # Label maps mirror history.models.BusinessEvent choices. Kept inline so
        # PDF labels stay accurate if model choices change behind us; update
        # both together.
        business_type_labels = {
            "certification": "Certification",
            "verification": "Third-Party Verification",
            "sustainability_audit": "Sustainability Audit",
            "transparency": "Transparency Initiative",
            "carbon_credits": "Carbon Credits",
            "compliance": "Regulatory Compliance",
        }
        sustainability_labels = {
            "cover_cropping": "Cover Cropping",
            "no_till": "No-Till Farming",
            "integrated_pest": "Integrated Pest Management",
            "water_conservation": "Water Conservation",
            "renewable_energy": "Renewable Energy",
            "composting": "On-Farm Composting",
            "biodiversity": "Biodiversity Conservation",
            "soil_health": "Soil Health Improvement",
        }

        headers = [
            "Date",
            "Activity",
            "Certification",
            "Certifier / Auditor",
            "Certificate #",
            "Inspector",
            "Status",
        ]
        header_row = [self._hdr(h) for h in headers]
        data = [header_row]

        # Events that carry supplemental detail (practice / credits / observation)
        # drive a follow-up sub-table so the primary row stays compact.
        supplemental_rows = []

        for ev in events:
            activity_label = business_type_labels.get(
                ev.business_type or "",
                _val(ev.business_type),
            )

            cert_display = None
            if ev.certification_type:
                try:
                    cert_display = ev.get_certification_type_display()
                except Exception:
                    cert_display = ev.certification_type

            status_display = None
            if ev.verification_status:
                try:
                    status_display = ev.get_verification_status_display()
                except Exception:
                    status_display = ev.verification_status

            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(activity_label),
                    self._cell(cert_display),
                    self._cell(ev.verified_certifier_name, 40),
                    self._cell(ev.certificate_number, 30),
                    self._cell(ev.performed_by, 30),
                    self._cell(status_display),
                ]
            )

            if ev.sustainability_practice or ev.observation or ev.carbon_credits_earned:
                supplemental_rows.append(ev)

        col_widths = [
            0.7 * inch,  # Date
            1.0 * inch,  # Activity
            1.2 * inch,  # Certification
            1.2 * inch,  # Certifier / Auditor
            0.8 * inch,  # Certificate #
            1.0 * inch,  # Inspector
            0.75 * inch,  # Status
        ]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        if supplemental_rows:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Supporting Detail</b>"))
            elements.append(self._spacer(0.05))

            detail_headers = ["Date", "Sustainability Practice", "Carbon Credits", "Observations"]
            detail_header_row = [self._hdr(h) for h in detail_headers]
            detail_data = [detail_header_row]

            for ev in supplemental_rows:
                credits_display = None
                if ev.carbon_credits_earned is not None and ev.carbon_credits_earned != 0:
                    unit = ev.carbon_credits_unit or "tCO2e"
                    credits_display = f"{_fmt_float(ev.carbon_credits_earned)} {unit}"

                practice_display = None
                if ev.sustainability_practice:
                    practice_display = sustainability_labels.get(
                        ev.sustainability_practice,
                        ev.sustainability_practice.replace("_", " ").title(),
                    )

                detail_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(practice_display),
                        self._cell(credits_display),
                        self._cell(ev.observation, 80),
                    ]
                )

            detail_widths = [0.75 * inch, 1.5 * inch, 1.1 * inch, 3.3 * inch]
            dt = Table(detail_data, colWidths=detail_widths, repeatRows=1)
            dt.setStyle(self._base_table_style())
            elements.append(dt)

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "Inspection and certification events are self-reported by the farmer. "
                "Certificate numbers and inspector names are recorded at the time of the event "
                "and are not independently verified by Trazo. Cross-reference with the Active "
                "Certification Summary above for establishment-level verification status.",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # Section 13: Mass-Balance Audit Summary
    # ------------------------------------------------------------------

    # Crop-specific default box / carton weights (pounds) and reconciliation
    # tolerances, used when History.box_weight_lb is not explicitly set.
    # Sources:
    #   * Avocado 25 lb — USDA-AMS Marketing Order 915 (standard Hass carton).
    #   * Avocado 10 lb lug — USDA-AMS retail-packout standard.
    #   * Citrus 38 lb — USDA-AMS navel carton (California Navel Marketing).
    #   * Blueberry 12 lb flat — USDA-AMS shipping point inspection standards.
    # Tolerance default is 10% because specialty-crop post-harvest shrink
    # (moisture, cull-out, grade-down) typically runs 8–12% between field
    # weight and pack-out weight — a tighter threshold produces false
    # non-conformances that do not reflect packing-house reality.
    CROP_DEFAULT_BOX_WEIGHTS = {
        # crop_type_lower: (lb_per_box, tolerance_fraction)
        "avocado": (25.0, 0.10),
        "avocados": (25.0, 0.10),
        "citrus": (38.0, 0.10),
        "orange": (38.0, 0.10),
        "oranges": (38.0, 0.10),
        "lemon": (38.0, 0.10),
        "lemons": (38.0, 0.10),
        "lime": (38.0, 0.10),
        "grapefruit": (38.0, 0.10),
        "mandarin": (25.0, 0.10),
        "blueberry": (12.0, 0.10),
        "blueberries": (12.0, 0.10),
        "strawberry": (11.0, 0.10),
        "strawberries": (11.0, 0.10),
        "apple": (42.0, 0.10),
        "apples": (42.0, 0.10),
    }
    DEFAULT_BOX_WEIGHT_TOLERANCE = 0.10

    def _box_weight_for_production(self):
        """
        Resolve (lb_per_box, tolerance) for the current production.

        Priority:
          1. ``self.production.box_weight_lb`` — explicit farmer / certifier value.
          2. ``CROP_DEFAULT_BOX_WEIGHTS[product.crop_type]`` — industry default.
          3. ``(None, DEFAULT_BOX_WEIGHT_TOLERANCE)`` — unknown; caller handles.
        """
        explicit = getattr(self.production, "box_weight_lb", None)
        if explicit is not None:
            try:
                return (float(explicit), self.DEFAULT_BOX_WEIGHT_TOLERANCE)
            except (TypeError, ValueError):
                pass
        crop_type = ""
        try:
            product = getattr(self.production, "product", None)
            if product is not None:
                crop_type = (getattr(product, "crop_type", "") or getattr(product, "name", "") or "").strip().lower()
        except Exception:
            crop_type = ""
        if crop_type and crop_type in self.CROP_DEFAULT_BOX_WEIGHTS:
            return self.CROP_DEFAULT_BOX_WEIGHTS[crop_type]
        return (None, self.DEFAULT_BOX_WEIGHT_TOLERANCE)

    def _build_mass_balance_section(self):
        elements = [self._section_header("Mass-Balance Audit Summary (§ 205.103(b)(2) / § 205.2)")]

        p = self.production

        # --- Input side: sum quantity_purchased from ChemicalEvents ---
        chemical_events = list(p.history_chemicalevent_events.all().order_by("date"))

        purchased_rows = []
        total_purchased_by_unit = {}
        missing_purchase_count = 0

        for ev in chemical_events:
            if ev.quantity_purchased is not None:
                unit = _val(ev.quantity_purchased_unit, "units")
                total_purchased_by_unit[unit] = total_purchased_by_unit.get(unit, 0) + float(ev.quantity_purchased)
                purchased_rows.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(ev.commercial_name, 40),
                        self._cell(CHEMICAL_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(ev.supplier_name, 30),
                        self._cell(ev.purchase_invoice, 20),
                        self._cell(_fmt_float(ev.quantity_purchased)),
                        self._cell(unit),
                    ]
                )
            else:
                missing_purchase_count += 1

        # --- Output side: harvest yield + quantity sold ---
        harvest_amount = p.production_amount
        harvest_unit = _val(p.production_unit, "")
        quantity_sold = p.quantity_sold
        sold_unit = _val(p.quantity_sold_unit, harvest_unit)

        # --- Render input table ---
        elements.append(self._body("<b>Inputs Purchased (Chemical Events)</b>"))
        elements.append(self._spacer(0.05))

        if purchased_rows:
            input_headers = ["Date", "Product", "Type", "Supplier", "Invoice #", "Qty Purchased", "Unit"]
            input_header_row = [self._hdr(h) for h in input_headers]
            input_data = [input_header_row] + purchased_rows
            col_widths = [
                0.60 * inch,
                1.10 * inch,
                0.65 * inch,
                1.00 * inch,
                0.75 * inch,
                0.80 * inch,
                0.60 * inch,
            ]
            t = Table(input_data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)

            # Subtotals per unit
            elements.append(self._spacer(0.08))
            for unit, total in sorted(total_purchased_by_unit.items()):
                elements.append(self._label_value(f"Total Purchased ({unit})", _fmt_float(total)))
        else:
            elements.append(self._body("No purchase quantity data recorded on chemical events."))

        if missing_purchase_count > 0:
            elements.append(
                Paragraph(
                    f"Note: {missing_purchase_count} chemical event(s) have no quantity_purchased recorded "
                    "and are excluded from totals.",
                    self._styles["footer_note"],
                )
            )

        # --- Render output reconciliation ---
        elements.append(self._spacer(0.12))
        elements.append(self._body("<b>Output Reconciliation</b>"))
        elements.append(self._spacer(0.05))

        output_rows = [
            (
                "Harvest Yield",
                f"{_fmt_float(harvest_amount)} {harvest_unit}".strip() if harvest_amount else None,
            ),
            (
                "Quantity Sold",
                f"{_fmt_float(quantity_sold)} {sold_unit}".strip() if quantity_sold else None,
            ),
            ("Sold To", p.sold_to),
            ("Sale Date", _fmt_date(p.sale_date) if p.sale_date else None),
            (
                "Organic Identified on Invoice",
                "Yes" if p.organic_on_invoice else "No",
            ),
        ]

        # Direct same-unit comparison only when it is actually meaningful —
        # not for boxes-vs-pounds where the units are explicitly incomparable
        # without a conversion. Boxes→lb reconciliation follows below.
        if harvest_amount and quantity_sold and harvest_unit == sold_unit:
            balance = float(harvest_amount) - float(quantity_sold)
            output_rows.append(
                (
                    "Balance (Yield \u2212 Sold, same unit)",
                    f"{_fmt_float(balance)} {harvest_unit}".strip(),
                )
            )

        for label, value in output_rows:
            elements.append(self._label_value(label, value))

        # --- Harvest reconciliation (§ 205.103(b)(2) / § 205.2 one-step audit) ---
        # Convert boxes → pounds using box_weight_lb (or the crop-default
        # fallback) and compare to the harvest yield. ±10% is the default
        # tolerance because packing-house shrink is typically 8–12% on
        # specialty crops. A larger delta warrants inspector review but is
        # not itself a regulatory violation.
        elements.append(self._spacer(0.12))
        elements.append(self._body("<b>Harvest Reconciliation (boxes \u2192 pounds)</b>"))
        elements.append(self._spacer(0.04))

        box_weight, tolerance = self._box_weight_for_production()
        box_weight_source = (
            "explicit production.box_weight_lb"
            if getattr(self.production, "box_weight_lb", None) is not None
            else "crop-default lookup"
        )

        harvest_lb = None
        if harvest_amount and harvest_unit.lower() in ("lb", "pounds", "pound", "lbs"):
            try:
                harvest_lb = float(harvest_amount)
            except (TypeError, ValueError):
                harvest_lb = None

        sold_is_boxes = sold_unit.lower() in ("boxes", "box", "cartons", "carton", "lugs", "lug")

        if not harvest_amount or not quantity_sold:
            elements.append(
                self._body(
                    "Incomplete data — fill both the harvest yield and the quantity sold "
                    "to enable the boxes \u2192 pounds reconciliation."
                )
            )
        elif not sold_is_boxes:
            elements.append(
                self._body(
                    f"Quantity sold is expressed in \u201c{sold_unit}\u201d, not boxes/"
                    "cartons/lugs. Boxes-to-pounds reconciliation is skipped — confirm "
                    "directly that harvest yield and quantity sold are in the same unit."
                )
            )
        elif box_weight is None:
            elements.append(
                self._body(
                    f"Box weight is not configured for this production (product "
                    f"crop-type \u201c{getattr(self.production.product, 'crop_type', '') or getattr(self.production.product, 'name', '') or '-'}\u201d). "
                    "Set the <b>box_weight_lb</b> field on the production record to enable "
                    "the boxes \u2192 pounds reconciliation, or consult the USDA-AMS "
                    "Marketing Order for the crop-specific standard."
                )
            )
        elif harvest_lb is None:
            elements.append(
                self._body(
                    f"Harvest yield is expressed in \u201c{harvest_unit}\u201d, not "
                    "pounds. Boxes-to-pounds reconciliation requires harvest yield in "
                    "pounds; convert before re-exporting."
                )
            )
        else:
            boxes = float(quantity_sold)
            estimated_lb = boxes * box_weight
            delta_lb = harvest_lb - estimated_lb
            if harvest_lb > 0:
                delta_pct = (delta_lb / harvest_lb) * 100.0
            else:
                delta_pct = 0.0
            within_tolerance = abs(delta_pct) <= (tolerance * 100.0)
            status_label = "PASS" if within_tolerance else "REVIEW"
            elements.append(
                self._label_value(
                    "Boxes \u00d7 lb/box",
                    f"{boxes:.0f} \u00d7 {box_weight:g} = {estimated_lb:,.0f} lb estimated "
                    f"(source: {box_weight_source})",
                )
            )
            elements.append(
                self._label_value(
                    "Harvest yield",
                    f"{harvest_lb:,.0f} lb",
                )
            )
            # "Calculated Shrinkage" is the packing-house term inspectors use
            # for the field-to-pack weight difference (moisture loss, culls,
            # grade-down). "Delta" reads like an unexplained discrepancy —
            # shrinkage is the domain-correct framing.
            #
            # Sign convention: ``delta_lb = harvest_lb - estimated_lb`` is
            # ALREADY shrinkage in the correct direction. Harvest > packed
            # means weight was lost between field and pack-out — the
            # normal, positive shrinkage case. A negative shrinkage
            # ("packed more than harvested") is physically implausible and
            # signals a data-entry error; we preserve the sign so an
            # inspector sees that state immediately rather than its
            # absolute value.
            shrink_lb = delta_lb
            shrink_pct = delta_pct
            elements.append(
                self._label_value(
                    "Calculated Shrinkage",
                    f"{shrink_lb:+,.0f} lb ({shrink_pct:+.1f}%) vs \u00b1{tolerance * 100.0:.0f}% tolerance",
                )
            )
            elements.append(
                self._label_value(
                    "Net inventory reconciliation",
                    status_label,
                )
            )
            if not within_tolerance:
                elements.append(
                    Paragraph(
                        f"<b>[REVIEW]</b> Calculated shrinkage is {shrink_pct:+.1f}%, "
                        f"outside the \u00b1{tolerance * 100.0:.0f}% tolerance configured for this "
                        "crop. Specialty-crop natural shrink (moisture, cull-out, grade-"
                        "down) typically runs 8–12%; a shrinkage of this magnitude warrants "
                        "an inspector review of pack-out documentation (pack-out weights, "
                        "shrink logs, grade-down allocations).",
                        self._warning_style(),
                    )
                )

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "Mass-balance reconciliation supports the § 205.2 audit-trail definition "
                "and the § 205.103(b)(2) SOE enhanced-traceability requirement by "
                "connecting inputs purchased and harvest yield to the sales quantity shipped. "
                "Box weight defaults are industry standards drawn from USDA-AMS packing-house "
                "references; override per-production via the <b>box_weight_lb</b> field on "
                "the production record. The \u00b110% tolerance reflects typical specialty-"
                "crop pack-out shrink and is advisory \u2014 larger deltas warrant review, "
                "not an automatic non-conformance.",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # Section 14: 3-Year Field / Crop Rotation History
    # ------------------------------------------------------------------

    def _build_field_history_section(self):
        from product.models import ParcelCropHistory

        elements = [self._section_header("3-Year Field & Crop Rotation History")]

        parcel = None
        try:
            parcel = self.production.parcel
        except AttributeError:
            pass

        if parcel is None:
            elements.append(self._body("Parcel data not available for this production."))
            return elements

        elements.append(self._label_value("Parcel", parcel.name))

        # NOP 7 CFR 205.202 — computed transition status (Sprint 2.2)
        try:
            from product.services.transition_status_service import compute_transition_status

            ts = compute_transition_status(parcel)
            if ts.is_eligible:
                elements.append(self._label_value("Organic Transition Status", "Eligible"))
            else:
                elements.append(
                    self._label_value(
                        "Organic Transition Status",
                        f"In transition — {ts.days_remaining} days remaining "
                        f"(eligible {ts.transition_complete_date})",
                    )
                )
            if ts.last_prohibited_date:
                elements.append(self._label_value("Last Prohibited Substance Date", str(ts.last_prohibited_date)))
            if ts.note:
                elements.append(self._body(ts.note))
        except Exception:  # noqa: BLE001 — non-fatal; export should still render
            pass

        # --- Primary: structured ParcelCropHistory entries ---
        crop_history = list(ParcelCropHistory.objects.filter(parcel=parcel).order_by("-year")[:10])

        if crop_history:
            headers = [
                "Year",
                "Crop Grown",
                "Production Method",
                "Substances Applied",
                "Last Prohibited Substance",
                "Notes",
            ]
            header_row = [self._hdr(h) for h in headers]
            data = [header_row]

            for entry in crop_history:
                data.append(
                    [
                        self._cell(str(entry.year)),
                        self._cell(entry.crop_grown, 50),
                        self._cell(entry.get_production_method_display() if entry.production_method else None),
                        self._cell(entry.substances_applied, 80),
                        self._cell(_fmt_date(entry.date_last_prohibited)),
                        self._cell(entry.notes, 80),
                    ]
                )

            col_widths = [
                0.45 * inch,  # Year
                1.1 * inch,  # Crop Grown
                0.9 * inch,  # Production Method
                1.8 * inch,  # Substances Applied
                1.0 * inch,  # Last Prohibited Substance
                1.5 * inch,  # Notes
            ]
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)

        else:
            # --- Fallback: derive history from previous History objects on the same parcel ---
            elements.append(
                Paragraph(
                    "No structured crop history records found. Showing previous productions on "
                    "this parcel as a fallback.",
                    self._styles["footer_note"],
                )
            )
            elements.append(self._spacer(0.08))

            from history.models import History

            prev_productions = list(
                History.objects.filter(parcel=parcel)
                .exclude(pk=self.production.pk)
                .select_related("crop_type", "product")
                .order_by("-start_date")[:15]
            )

            if prev_productions:
                fb_headers = [
                    "Start Date",
                    "Finish Date",
                    "Crop",
                    "Production Method",
                    "Harvest Amount",
                    "Lot ID",
                ]
                fb_header_row = [self._hdr(h) for h in fb_headers]
                fb_data = [fb_header_row]

                for prod in prev_productions:
                    crop_name = ""
                    try:
                        crop_name = (
                            prod.crop_type.name if prod.crop_type else (prod.product.name if prod.product else "")
                        )
                    except AttributeError:
                        pass

                    harvest = (
                        f"{_fmt_float(prod.production_amount)} {_val(prod.production_unit, '')}".strip()
                        if prod.production_amount
                        else None
                    )

                    fb_data.append(
                        [
                            self._cell(_fmt_date(prod.start_date)),
                            self._cell(_fmt_date(prod.finish_date)),
                            self._cell(crop_name, 50),
                            self._cell(prod.get_production_method_display() if prod.production_method else None),
                            self._cell(harvest),
                            self._cell(prod.lot_id, 30),
                        ]
                    )

                col_widths = [
                    0.75 * inch,
                    0.75 * inch,
                    1.2 * inch,
                    1.0 * inch,
                    1.0 * inch,
                    0.8 * inch,
                ]
                t = Table(fb_data, colWidths=col_widths, repeatRows=1)
                t.setStyle(self._base_table_style())
                elements.append(t)
            else:
                elements.append(self._body("No previous production records found on this parcel."))

        # --- Landowner affidavits (MOFGA FM-2024-20 canonical) — Sprint 5A ---
        # When someone other than the applicant managed the parcel during the
        # transition window, § 205.202(b) proof requires a signed affidavit. Surface
        # any on file here so the inspector doesn't have to hunt for them.
        from certifications.models import LandownerAffidavit

        affidavits = list(
            LandownerAffidavit.objects.filter(parcel=parcel).order_by("-last_prohibited_date", "-created_at")
        )
        if affidavits:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Landowner Affidavits (prior-manager attestation)</b>"))
            aff_headers = [
                "Previous Manager",
                "Last Prohibited Substance",
                "Signed Date",
                "Document",
            ]
            aff_data = [[self._hdr(h) for h in aff_headers]]
            for aff in affidavits:
                aff_data.append(
                    [
                        self._cell(aff.previous_manager_name or "\u2014", 40),
                        self._cell(_fmt_date(aff.last_prohibited_date)),
                        self._cell(_fmt_date(aff.previous_manager_signed_date)),
                        self._cell("Attached" if aff.signed_document else "Not attached"),
                    ]
                )
            aff_t = Table(
                aff_data,
                colWidths=[2.2 * inch, 1.5 * inch, 1.1 * inch, 1.0 * inch],
                repeatRows=1,
            )
            aff_t.setStyle(self._base_table_style())
            elements.append(aff_t)
            elements.append(self._spacer(0.06))
            elements.append(
                Paragraph(
                    "Attestation (standard wording per MOFGA FM-2024-20): "
                    f"\u201c{LandownerAffidavit.ATTESTATION_TEXT}\u201d",
                    self._styles["footer_note"],
                )
            )

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "USDA Organic (7 CFR 205.202) requires 36-month field history showing crops grown and "
                "substances applied. Add structured entries via the Parcel History section in the "
                "producer dashboard for a complete inspector-ready record.",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # SOE Compliance Status
    # ------------------------------------------------------------------

    # Module-level OSP_NARRATIVE_MATERIAL_FLOOR (= 400) is the single source of
    # truth; this class attribute aliases it for in-method convenience and
    # backward-compat with any external callers reading the class constant.
    OSP_NARRATIVE_MATERIAL_FLOOR = OSP_NARRATIVE_MATERIAL_FLOOR

    # Below this completeness ratio the PDF is stamped DRAFT — per CCOF/OEFFA practice,
    # an OSP with < 50% of required sections substantively filled is a Notice-of-Noncompliance
    # item, not a certification artifact.
    OSP_DRAFT_COMPLETENESS_THRESHOLD = 0.5

    def _safe_narrative(self, text: str, max_chars: int = 2400) -> str:
        """
        Escape narrative text for ReportLab Paragraph rendering.

        ReportLab's Paragraph parses XML-like markup (<b>, <br/>, <font>, ...). A
        farmer pasting `<script>`, `<onclick>`, or a stray `<` would either inject
        markup or crash PDF generation with a ParaFrag parse error. We escape all
        XML specials, then preserve paragraph breaks by converting `\n` -> `<br/>`.
        Truncate overlong narratives so a 500KB paste doesn't hang the renderer.
        """
        import xml.sax.saxutils

        if not text:
            return ""
        truncated = text if len(text) <= max_chars else (text[:max_chars] + "\u2026")
        escaped = xml.sax.saxutils.escape(truncated)
        return escaped.replace("\n", "<br/>")

    def _osp_section_status(self, narrative: str) -> str:
        """
        Three-tier status label for the summary table. Matches the validator
        thresholds used on Submit (views.py) so farmers see the same bar an
        inspector applies: EMPTY / BRIEF (insufficient) / COMPLETE.
        """
        length = len(narrative.strip())
        if length == 0:
            return "EMPTY"
        if length < self.OSP_NARRATIVE_MATERIAL_FLOOR:
            return f"BRIEF — {length} chars (insufficient)"
        return f"Complete — {length} chars"

    # Crops where the edible portion does NOT contact the soil. § 205.203(c)(1)(iii)
    # applies (90-day pre-harvest interval). Everything else falls back to (c)(1)(ii)
    # with 120 days (root crops, leafy greens, cucurbits, strawberries, melons).
    # Note: (c)(1)(i) covers land used for a crop not intended for human
    # consumption — out of scope for any Trazo production record.
    _NON_SOIL_CONTACT_CROP_KEYWORDS = (
        "avocado",
        "citrus",
        "orange",
        "lemon",
        "lime",
        "grapefruit",
        "mandarin",
        "tangerine",
        "apple",
        "pear",
        "cherry",
        "peach",
        "nectarine",
        "plum",
        "apricot",
        "mango",
        "papaya",
        "almond",
        "walnut",
        "pistachio",
        "pecan",
        "hazelnut",
        "grape",
        "wine",
        "olive",
        "fig",
        "pomegranate",
        "date",
        "persimmon",
    )

    def _manure_interval_rule_for_crop(self) -> dict:
        """
        Return the § 205.203(c)(1) sub-rule that applies to this production.

        Per eCFR 7 CFR 205.203(c)(1):
        (i)   land used for a crop not intended for human consumption.
        (ii)  120 days when the edible portion has direct contact with soil
              surface or soil particles (root crops, leafy greens, fruits
              growing on the ground).
        (iii) 90 days when the edible portion does NOT have direct contact
              with soil (tree fruits, tree nuts, elevated vine fruits).

        Defaults to (c)(1)(ii) / 120 days when crop type is unknown — the
        stricter human-consumption rule is always regulation-safe.
        """
        non_soil_contact = False
        try:
            crop = self.production.crop_type
            has_soil_contact_flag = getattr(crop, "has_soil_contact", None) if crop else None
            if has_soil_contact_flag is False:
                non_soil_contact = True
            else:
                crop_name = (crop.name if crop else "").lower()
                if any(k in crop_name for k in self._NON_SOIL_CONTACT_CROP_KEYWORDS):
                    non_soil_contact = True
        except Exception:
            non_soil_contact = False
        if non_soil_contact:
            return {"cite": "§ 205.203(c)(1)(iii)", "label": "90-day", "days": 90}
        return {"cite": "§ 205.203(c)(1)(ii)", "label": "120-day", "days": 120}

    # Regex patterns for narrative lint hints. Module-level-ish constants kept
    # inline so `_osp_narrative_lint_hints()` stays self-contained and fast to
    # audit for regulatory accuracy.
    _LINT_PRACTICE_CHANGE_KEYWORDS = (
        "material change",
        "activity change",
        "practice change",
        "procedure change",
        "change request",
        "change-request",
        "material/activity",
    )

    def _osp_narrative_lint_hints(self, narrative: str) -> list:
        """
        Scan farmer-authored OSP narrative for common regulatory miscitations.

        Returns a list of human-readable hints to render directly beneath the
        narrative in the PDF. Never rewrites the farmer's filing — verbatim
        content is preserved per § 205.201 filing practice — but inspectors
        and Trazo-side reviewers both benefit from Trazo flagging what a
        careful certifier-side reviewer would question.

        Three lint classes currently detected:
          1. § 205.400(f)(1) used in a "practice/activity change" context.
             (f)(1) governs application of a prohibited substance; (f)(2)
             governs operation changes. Very common miscitation.
          2. Self-imposed numeric SLA ("within 24 hours") against the
             regulation's "immediately" standard — creates a
             self-manufactured non-compliance trap.
          3. § 205.504 cited in producer-facing text. § 205.504 is
             certifier-side AMS accreditation evidence; producer duty under
             SOE is § 205.501(a)(21) (cooperation) + § 205.201(a)(3)
             (fraud-prevention / supplier-verification procedures).
        """
        import re

        if not narrative:
            return []
        hints = []
        lower = narrative.lower()

        if "205.400(f)(1)" in narrative and any(keyword in lower for keyword in self._LINT_PRACTICE_CHANGE_KEYWORDS):
            hints.append(
                "Regulatory hint: § 205.400(f)(1) governs the application of a "
                "prohibited substance. Changes in practices, procedures, or "
                "approved materials are governed by § 205.400(f)(2). Consider "
                "updating the citation in this section."
            )

        # Only flag "within N hours/days" SLAs that appear in proximity (~120
        # chars) to a certifier-notification / § 205.400(f) context — the
        # narrative often legitimately uses "within N days" to describe past
        # corrective-action windows ("corrected within 10 days") that carry
        # no regulatory SLA.
        sla_pattern = re.compile(
            r"(?:certifier|certifying agent|205\.400|notif(?:y|ied|ication))"
            r"[^\.]{0,120}?within\s+\d+\s+(?:hour|hr|day|business day|week)",
            re.IGNORECASE,
        )
        if sla_pattern.search(narrative):
            hints.append(
                "Regulatory hint: § 205.400(f) requires certifier notification "
                '"immediately." A self-imposed numeric SLA (e.g. "within 24 '
                'hours") in the OSP narrative can create an accidental '
                "non-compliance trap if notification slips past that deadline. "
                "The regulation defers to a reasonableness standard."
            )

        if "205.504" in narrative:
            hints.append(
                "Regulatory hint: § 205.504 describes evidence that certifying "
                "agents must submit to AMS for accreditation — it is not a "
                "producer duty. The producer-side supply-chain traceability "
                "audit duty is § 205.501(a)(21) (producer cooperation) in "
                "conjunction with § 205.201(a)(3) (fraud-prevention / "
                "supplier-verification procedures)."
            )

        return hints

    def _build_osp_reference_section(self):
        """
        Organic System Plan reference — 7 CFR 205.201.

        Shows the active OSP version for the establishment this production belongs
        to. Certifiers expect the audit export to cite the OSP it is supporting so
        they can cross-reference practices in the plan against the evidence in the
        report. If no OSP exists, we print a prominent "NOT ON FILE" warning —
        required per § 205.201.

        Renders each required § 205.201(a)(1)-(6) section's narrative verbatim
        after the summary table so inspectors can review substance, not just
        char counts (agent-2025 finding: summary-only presentation hides
        trivially short narratives).
        """
        from certifications.models import OSP_SECTION_KEYS, OrganicSystemPlan

        elements = [self._section_header("Organic System Plan (7 CFR 205.201)")]

        try:
            establishment = self.production.parcel.establishment
        except AttributeError:
            elements.append(self._body("Establishment data not available."))
            return elements

        active_osp = (
            OrganicSystemPlan.objects.filter(establishment=establishment, status="active")
            .order_by("-version_number")
            .first()
        )
        # Fall back to the most recent draft/submitted version if no active one — gives
        # inspectors something to review even for operations mid-certification.
        osp = active_osp or (
            OrganicSystemPlan.objects.filter(establishment=establishment).order_by("-version_number").first()
        )

        if osp is None:
            elements.append(
                Paragraph(
                    "<b>NO ORGANIC SYSTEM PLAN ON FILE.</b> "
                    "7 CFR 205.201 requires an OSP for every certified organic operation. "
                    "This operation has not yet filed one in Trazo. Evidence below is "
                    "audit-ready but cannot be cross-referenced to a master plan.",
                    self._warning_style(),
                )
            )
            return elements

        status_label = osp.get_status_display()
        effective = _fmt_date(osp.effective_date)
        submitted = _fmt_date(osp.submitted_at)
        approved = _fmt_date(osp.approved_at)
        template = osp.certifier_template_name or "\u2014"

        elements.append(self._label_value("Active Version", f"v{osp.version_number} ({status_label})"))
        elements.append(self._label_value("Effective Date", effective))
        elements.append(self._label_value("Submitted", submitted))
        elements.append(self._label_value("Approved by Certifier", approved))
        elements.append(self._label_value("Certifier Template", template))

        # Recompute completion using the material floor (400 chars), not the model's
        # "any non-empty" check. This matches how an inspector reads the PDF.
        sections_data = osp.sections or {}
        material_section_hits = {
            k: len((sections_data.get(k) or {}).get("narrative", "").strip()) >= self.OSP_NARRATIVE_MATERIAL_FLOOR
            for k in OSP_SECTION_KEYS
        }

        # Registry Sync gate — narrative char-count alone is not enough. If the
        # § 205.201(a)(2) inputs narrative is long but the OSP's structured
        # approved-inputs registry has entries that are not referenced in the
        # narrative, the (a)(2) section reads as incomplete to an inspector
        # (Page-4 Registry Sync diff contradicts a "100% substantively filled"
        # Page-3 row otherwise). Demote (a)(2) to "incomplete" when there are
        # unreferenced registry entries; the detail table below will still
        # surface the actual gap count so the farmer knows what to reconcile.
        #
        # Load approved-inputs M2Ms ONCE here with order_by — the detail
        # tables below (~150 lines further down) reuse these same lists via
        # the alias names ``omri_products`` / ``nl_substances`` /
        # ``wsda_materials`` to avoid a second round of queries.
        omri_products = list(osp.approved_omri_products.all().order_by("product_name"))
        nl_substances = list(osp.approved_national_list_substances.all().order_by("substance_name"))
        wsda_materials = list(osp.approved_wsda_materials.all().order_by("brand_name"))
        inputs_narrative_text = (sections_data.get("inputs_list") or {}).get("narrative", "") or ""
        registry_sync_diff = _compute_registry_sync_diff(
            inputs_narrative=inputs_narrative_text,
            omri_products=omri_products,
            wsda_materials=wsda_materials,
            nl_substances=nl_substances,
        )
        unreferenced_count = sum(1 for r in registry_sync_diff["registry_entries"] if not r["in_narrative"])
        if unreferenced_count > 0:
            material_section_hits["inputs_list"] = False

        material_completion = sum(1 for hit in material_section_hits.values() if hit) / len(OSP_SECTION_KEYS)
        completion_detail = f"{int(material_completion * 100)}% of § 205.201(a)(1)-(6) substantively filled"
        if unreferenced_count > 0:
            completion_detail += (
                f" — (a)(2) demoted: {unreferenced_count} registry entr"
                f"{'y' if unreferenced_count == 1 else 'ies'} not referenced in narrative"
            )
        elements.append(
            self._label_value(
                "Section Completion (material)",
                completion_detail,
            )
        )

        # DRAFT warning when the OSP is materially incomplete — per CCOF/OEFFA
        # Notice-of-Noncompliance templates (7 CFR 205.662(c)).
        if material_completion < self.OSP_DRAFT_COMPLETENESS_THRESHOLD:
            elements.append(self._spacer(0.05))
            elements.append(
                Paragraph(
                    "<b>DRAFT — NOT FOR CERTIFIER SUBMISSION.</b> "
                    "This OSP is materially incomplete and would not be accepted by an "
                    "accredited certifier. Per 7 CFR 205.662(c), an OSP missing required "
                    "§ 205.201(a) sections is grounds for a Notice of Noncompliance with "
                    "a 30-day cure window before proposed suspension.",
                    self._warning_style(),
                )
            )
        elements.append(self._spacer(0.12))

        # Section-by-section summary: shows inspectors that all six required
        # § 205.201(a) sections exist and how recently they were updated.
        headers = ["§ 205.201(a)", "Section", "Status", "Last Updated"]
        data = [[self._hdr(h) for h in headers]]
        section_labels = {
            "practices_procedures": ("(a)(1)", "Practices & Procedures"),
            "inputs_list": ("(a)(2)", "Inputs / Materials List"),
            "monitoring_plan": ("(a)(3)", "Monitoring & Fraud Prevention"),
            "recordkeeping_description": ("(a)(4)", "Recordkeeping System"),
            "commingling_barriers": ("(a)(5)", "Commingling Prevention"),
            "additional_certifier_info": ("(a)(6)", "Additional Certifier Info"),
        }
        for key in OSP_SECTION_KEYS:
            section = sections_data.get(key, {}) or {}
            narrative = (section.get("narrative") or "").strip()
            last_updated = section.get("last_updated") or "\u2014"
            cfr, label = section_labels.get(key, ("\u2014", key))

            # Status cell: char-count suffices UNLESS an additional signal
            # demotes the section (e.g. Registry Sync gate → (a)(2) gap).
            # Mirror the demotion inline so the table cell matches the
            # header and page-1 snapshot (avoid "Complete — 870 chars"
            # vs "(a)(2) demoted" contradiction).
            status_text = self._osp_section_status(narrative)
            if key == "inputs_list" and unreferenced_count > 0:
                status_text = (
                    f"{status_text} \u26a0 {unreferenced_count} registry "
                    f"entr{'y' if unreferenced_count == 1 else 'ies'} unreferenced"
                )
            data.append(
                [
                    self._cell(cfr),
                    self._cell(label, 40),
                    self._cell(status_text, 60),
                    self._cell(str(last_updated)),
                ]
            )

        t = Table(
            data,
            colWidths=[0.8 * inch, 2.4 * inch, 2.0 * inch, 1.3 * inch],
            repeatRows=1,
        )
        t.setStyle(self._base_table_style())
        elements.append(t)
        elements.append(self._spacer(0.15))

        # --- Full narratives per section (rendered verbatim) ------------------
        # Inspectors need to read the substance, not a char-count summary. We
        # XML-escape to protect against ReportLab Paragraph markup injection.
        elements.append(
            Paragraph(
                "<b>Section narratives</b> — verbatim content filed with the certifier.",
                self._styles["body"],
            )
        )
        elements.append(self._spacer(0.08))

        for key in OSP_SECTION_KEYS:
            section = sections_data.get(key, {}) or {}
            narrative = (section.get("narrative") or "").strip()
            cfr, label = section_labels.get(key, ("\u2014", key))
            elements.append(
                Paragraph(
                    f"<b>{cfr} — {label}</b>",
                    self._styles["body"],
                )
            )
            if narrative:
                elements.append(Paragraph(self._safe_narrative(narrative), self._styles["body"]))
                # Lint hints surface regulatory-citation issues in the farmer's
                # verbatim text without rewriting it. Inspectors see the
                # farmer's filing AND Trazo's cautionary note — both are useful
                # signals. Lint is additive: absence = no detected issue, not
                # "this narrative is perfect."
                for hint in self._osp_narrative_lint_hints(narrative):
                    elements.append(
                        Paragraph(
                            f"<i>{hint}</i>",
                            self._styles["footer_note"],
                        )
                    )
            else:
                elements.append(
                    Paragraph(
                        "<i>(Section empty — will be flagged as non-compliant by certifier.)</i>",
                        self._styles["footer_note"],
                    )
                )
            elements.append(self._spacer(0.08))

        # --- Approved inputs — the scope the certifier approved ---------------
        # Inspectors reviewing the Unapproved-Input Findings section (if
        # present) need to know what WAS approved so they can cross-reference
        # "this event references X, X is not in the approved list" against
        # the concrete list. Without this, an unapproved-input finding is
        # unfalsifiable.
        # NOTE: ``omri_products`` / ``nl_substances`` / ``wsda_materials`` were
        # loaded above for the Registry Sync gate — reused here to avoid a
        # second set of queries.
        elements.append(self._spacer(0.12))
        elements.append(
            Paragraph(
                "<b>Approved inputs — certifier-approved scope (§ 205.201(a)(2))</b>",
                self._styles["body"],
            )
        )
        if not omri_products and not nl_substances and not wsda_materials:
            elements.append(
                Paragraph(
                    "<i>No structured inputs recorded on this OSP. Drift findings "
                    "(if any) are measured against the narrative § 205.201(a)(2) "
                    "text only.</i>",
                    self._styles["footer_note"],
                )
            )
        else:
            if omri_products:
                elements.append(
                    Paragraph(
                        f"<b>OMRI-listed products ({len(omri_products)})</b>",
                        self._styles["body"],
                    )
                )
                for p in omri_products:
                    omri_id = f" (OMRI #{p.omri_id})" if p.omri_id else ""
                    mfr = f" — {p.manufacturer}" if p.manufacturer else ""
                    elements.append(
                        Paragraph(
                            f"• {self._safe_narrative(p.product_name + omri_id + mfr)}",
                            self._styles["body"],
                        )
                    )
            if wsda_materials:
                elements.append(
                    Paragraph(
                        f"<b>WSDA Materials List ({len(wsda_materials)})</b>",
                        self._styles["body"],
                    )
                )
                for m in wsda_materials:
                    wsda_id = f" (WSDA #{m.wsda_id})" if m.wsda_id else ""
                    mfr = f" — {m.manufacturer}" if m.manufacturer else ""
                    cat = f" [{m.category}]" if m.category else ""
                    elements.append(
                        Paragraph(
                            f"• {self._safe_narrative(m.brand_name + wsda_id + mfr + cat)}",
                            self._styles["body"],
                        )
                    )
            if nl_substances:
                elements.append(
                    Paragraph(
                        f"<b>National List substances ({len(nl_substances)})</b>",
                        self._styles["body"],
                    )
                )
                for s in nl_substances:
                    cfr = f" ({s.cfr_section})" if s.cfr_section else ""
                    elements.append(
                        Paragraph(
                            f"• {self._safe_narrative(s.substance_name + cfr)}",
                            self._styles["body"],
                        )
                    )

        # --- Registry Sync Status — narrative ↔ registry diff (P0-5) ----------
        # CCOF inspector will treat "narrative mentions 6 inputs but registry has 2"
        # as an incomplete § 205.201(a)(2) filing. Surface the diff inline so the
        # farmer can reconcile before the audit. The diff was already computed
        # above for the Registry Sync completeness gate — reuse it here.
        inputs_narrative = inputs_narrative_text
        sync = registry_sync_diff
        elements.append(self._spacer(0.12))
        elements.append(
            Paragraph(
                "<b>Registry Sync Status — narrative ↔ structured inputs</b>",
                self._styles["body"],
            )
        )
        if sync["registry_total"] == 0 and not inputs_narrative.strip():
            elements.append(
                Paragraph(
                    "<i>No inputs filed — neither narrative nor registry populated.</i>",
                    self._styles["footer_note"],
                )
            )
        elif sync["registry_total"] == 0:
            elements.append(
                Paragraph(
                    "<b>⚠ REVIEW:</b> § 205.201(a)(2) narrative is populated but no "
                    "structured inputs are on the OSP registry. Inspector may read "
                    "this as an incomplete filing. Add each input mentioned in the "
                    "narrative to the OSP page so drift detection has a concrete "
                    "baseline to check against.",
                    self._warning_style(),
                )
            )
        else:
            # Build a table: each registry entry × whether its name appears in narrative.
            sync_header = [
                self._hdr("Source"),
                self._hdr("Name"),
                self._hdr("In (a)(2) narrative?"),
            ]
            sync_rows = [sync_header]
            for row in sync["registry_entries"]:
                sync_rows.append(
                    [
                        self._cell(row["source"]),
                        self._cell(row["name"], 45),
                        self._cell("Yes" if row["in_narrative"] else "No — add to narrative"),
                    ]
                )
            sync_table = Table(
                sync_rows,
                colWidths=[1.0 * inch, 3.4 * inch, 2.1 * inch],
                repeatRows=1,
            )
            sync_table.setStyle(self._base_table_style())
            elements.append(sync_table)
            # Inline note if any registry entries are missing from narrative OR
            # narrative is long (>400 chars) yet registry is thin (<3 entries).
            missing_from_narrative = sum(1 for r in sync["registry_entries"] if not r["in_narrative"])
            if missing_from_narrative:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"<b>⚠ {missing_from_narrative} registry entr"
                        f"{'y' if missing_from_narrative == 1 else 'ies'} "
                        "not referenced in the § 205.201(a)(2) narrative.</b> "
                        "Inspectors cross-check the narrative against the registry. "
                        "Update the narrative to describe every structured input.",
                        self._warning_style(),
                    )
                )
            elif (
                len(inputs_narrative.strip()) >= OSP_NARRATIVE_MATERIAL_FLOOR
                and sync["registry_total"] < REGISTRY_THIN_THRESHOLD
            ):
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        "<b>⚠ REVIEW:</b> § 205.201(a)(2) narrative is substantial "
                        f"({len(inputs_narrative.strip())} chars) but only "
                        f"{sync['registry_total']} structured input"
                        f"{'s' if sync['registry_total'] != 1 else ''} registered. "
                        "Verify every input mentioned in the narrative has a "
                        "corresponding OMRI / WSDA / National List entry on the OSP page.",
                        self._warning_style(),
                    )
                )

        # --- Approved inputs change log — § 205.400(f)(2) paper trail ----------
        # Adding/removing an approved input is a "change in a certified operation"
        # and falls under § 205.400(f)(2), not (f)(1). (f)(1) is the drift /
        # prohibited-substance-application notification; (f)(2) is the practice /
        # operation-change notification. Inspectors ask "when did you add Copper
        # hydroxide, and which certifier letter backs it?" — this table answers that.
        elements.append(self._spacer(0.12))
        elements.append(
            Paragraph(
                "<b>Change log — approved-inputs history (§ 205.400(f)(2))</b>",
                self._styles["body"],
            )
        )
        from certifications.models import ApprovedInputChangeLog

        change_logs = list(osp.approved_input_changes.all().select_related("changed_by"))
        if not change_logs:
            elements.append(
                Paragraph(
                    "<i>No recorded changes.</i>",
                    self._styles["footer_note"],
                )
            )
        else:
            # Wrap every cell in a Paragraph so long cert refs / product names
            # word-wrap inside the column width (ReportLab Tables do NOT wrap
            # raw-string cells — WORDWRAP is not a valid TableStyle command,
            # it's silently ignored. Only Paragraph/XPreformatted flowables
            # actually wrap inside a Table cell.) Also gives us free XML
            # escaping via _safe_narrative for any <, >, & in user input.
            cell_style = ParagraphStyle(
                "ChangeLogCell",
                parent=self._styles["body"],
                fontSize=7,
                leading=9,
            )
            header_style = ParagraphStyle(
                "ChangeLogHeader",
                parent=cell_style,
                fontName="Helvetica-Bold",
            )
            col_labels = ["Date", "Action", "Input", "Cert-notification ref", "By"]
            table_data = [[Paragraph(h, header_style) for h in col_labels]]
            for entry in change_logs:
                date_str = entry.changed_at.strftime("%Y-%m-%d") if entry.changed_at else "-"
                action_str = entry.get_action_display()
                input_name = entry.target_name_at_change or "-"
                cert_ref = (entry.change_notification_reference or "").strip() or "-"
                by_user = "-"
                if entry.changed_by is not None:
                    u = entry.changed_by
                    full = (f"{u.first_name} {u.last_name}").strip()
                    by_user = full or getattr(u, "email", "-")
                table_data.append(
                    [
                        Paragraph(date_str, cell_style),
                        Paragraph(self._safe_narrative(action_str), cell_style),
                        Paragraph(self._safe_narrative(input_name), cell_style),
                        Paragraph(self._safe_narrative(cert_ref), cell_style),
                        Paragraph(self._safe_narrative(by_user), cell_style),
                    ]
                )

            col_widths = [62, 48, 120, 160, 90]
            tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
            tbl.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F5E9")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BDBDBD")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            elements.append(tbl)

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "Source: 7 CFR 205.201 (eCFR). Each evidence section of this report "
                "satisfies one or more practices described in the OSP above.",
                self._styles["footer_note"],
            )
        )
        return elements

    def _build_drift_findings_section(self):
        """
        OSP ↔ events drift — 7 CFR 205.400(f)(2).

        Lists every ChemicalEvent and SoilManagementEvent on this production
        whose input is not in the establishment's active OSP approved_inputs
        set. An input used that is not on the OSP approved-inputs list is a
        *change in a certified operation* under § 205.400(f)(2), triggering
        the producer's change-notification obligation. (f)(1) is reserved for
        the actual application of a prohibited substance — a distinct and
        more severe finding this section does not represent.)

        Sprint 5.1 (drift detector): post_save signals on ChemicalEvent /
        SoilManagementEvent populate `drift_warning` JSONB on the event; this
        section materializes that data at audit-export time.
        """
        from history.models import ChemicalEvent, ProductionEvent, SoilManagementEvent

        # Section name deliberately avoids the word "Drift" in isolation. In
        # NOP usage "drift" is the term of art for external contamination
        # from adjacent land (governed by § 205.400(f)(1)). Internal
        # application of an input not on the OSP approved-inputs list is a
        # *practice change* under § 205.400(f)(2) — a distinct finding.
        # Labeling internal unapproved-material use as "Drift" confuses the
        # audit trail; we call it what the rule calls it.
        elements = [self._section_header("Unapproved-Input Findings \u2014 OSP Practice Change (7 CFR 205.400(f)(2))")]

        history_id = getattr(self.production, "id", None)
        if history_id is None:
            elements.append(self._body("Production data not available."))
            return elements

        # Branch wording on OSP presence so the prose never claims cross-
        # reference against an "active OSP" when none is on file. Drift
        # signal still resolves against the establishment-level approved-
        # inputs registry; the OSP-narrative master plan is what's missing.
        from certifications.models import OrganicSystemPlan

        try:
            establishment = self.production.parcel.establishment
        except AttributeError:
            establishment = None
        osp_on_file = False
        if establishment is not None:
            osp_on_file = OrganicSystemPlan.objects.filter(establishment=establishment).exists()

        # `self.production` is the History row (naming is historical). Events
        # link to it via CommonEvent.history, so a single-hop filter covers
        # every ChemicalEvent / SoilManagementEvent / planting ProductionEvent
        # on this production cycle. ProductionEvent drift_warning is populated
        # only on Planting (type='PL') subtypes per § 205.204.
        chem_drift = list(
            ChemicalEvent.objects.filter(history_id=history_id, drift_warning__isnull=False).order_by("date")
        )
        soil_drift = list(
            SoilManagementEvent.objects.filter(history_id=history_id, drift_warning__isnull=False).order_by("date")
        )
        seed_drift = list(
            ProductionEvent.objects.filter(history_id=history_id, type="PL", drift_warning__isnull=False).order_by(
                "date"
            )
        )

        if not chem_drift and not soil_drift and not seed_drift:
            if osp_on_file:
                summary_body = (
                    "<b>No drift findings.</b> Every chemical input, soil amendment, "
                    "and planting-event seed source logged during this production "
                    "cycle matched an entry on the establishment's active OSP "
                    "approved-inputs list and § 205.204 seed documentation requirements."
                )
                summary_note = (
                    "Inputs are cross-checked against the active OSP's "
                    "approved_national_list_substances and approved_omri_products "
                    "sets at event save-time. 7 CFR 205.400(f)(2) requires producers "
                    "to notify their certifying agent of any change in practices or "
                    "procedures that may affect the organic status of the operation."
                )
            else:
                summary_body = (
                    "<b>No drift findings.</b> Every chemical input, soil amendment, "
                    "and planting-event seed source logged during this production "
                    "cycle resolved against the establishment-level approved-inputs "
                    "registry and § 205.204 seed documentation requirements. Once "
                    "the OSP is filed, this section will additionally cross-check "
                    "against the OSP's approved-inputs list."
                )
                summary_note = (
                    "Inputs are cross-checked against the establishment's "
                    "approved_national_list_substances and approved_omri_products "
                    "registry at event save-time. 7 CFR 205.400(f)(2) requires "
                    "producers to notify their certifying agent of any change in "
                    "practices or procedures that may affect the organic status of "
                    "the operation; an OSP-on-file is the canonical location for "
                    "that approved-inputs list."
                )
            elements.append(Paragraph(summary_body, self._styles["body"]))
            elements.append(self._spacer(0.05))
            elements.append(Paragraph(summary_note, self._styles["footer_note"]))
            return elements

        if osp_on_file:
            findings_warning = (
                "<b>The events listed below reference inputs not present on the "
                "active OSP's approved-inputs registry at event save-time.</b> "
                "Per 7 CFR 205.400(f)(2), the producer must notify the certifier "
                "of any change in practices or procedures that may affect the "
                "organic status of the operation. Add the input to the OSP "
                "(if approved), or document the change-notification filing "
                "submitted to the certifier."
            )
        else:
            findings_warning = (
                "<b>The events listed below reference inputs not present on the "
                "establishment's approved-inputs registry at event save-time, "
                "and no Organic System Plan is on file to cross-reference.</b> "
                "Per 7 CFR 205.400(f)(2), the producer must notify the certifier "
                "of any change in practices or procedures that may affect the "
                "organic status of the operation. File the OSP and add each "
                "input below to the OSP approved-inputs list, or document the "
                "change-notification filing submitted to the certifier."
            )
        elements.append(Paragraph(findings_warning, self._warning_style()))
        elements.append(self._spacer(0.05))

        headers = ["Event Date", "Event Type", "Input", "Reason", "Resolution", "Verified"]
        col_widths = [0.75 * inch, 0.95 * inch, 1.4 * inch, 1.95 * inch, 1.15 * inch, 0.85 * inch]

        def _format_verified_cell(dw):
            """Render per-catalog lookup timestamps as a compact string.

            ReportLab's ``Paragraph`` treats raw ``\\n`` as whitespace, and
            ``_cell`` XML-escapes ``<`` / ``>`` (so ``<br/>`` would leak
            through as literal text). Fall back to a ``' · '`` separator
            which wraps naturally inside the column.

            Legacy drift findings (written before per-finding timestamping)
            lack these keys and render as ``—`` so we never fabricate a
            verification date the system does not actually have on file.
            """
            labels = [
                ("omri_verified_at", "OMRI"),
                ("wsda_verified_at", "WSDA"),
                ("national_list_verified_at", "NL"),
                ("cdfa_oim_verified_at", "CDFA"),
            ]
            parts = []
            for key, label in labels:
                stamp = dw.get(key)
                if not stamp:
                    continue
                try:
                    # "2026-04-16T14:02:11.123456+00:00" → "2026-04-16 14:02Z"
                    date_part, time_part = stamp.split("T", 1)
                    hhmm = time_part[:5]
                    parts.append(f"{label} {date_part} {hhmm}Z")
                except Exception:
                    parts.append(f"{label} {stamp[:16]}")
            if not parts:
                return "\u2014"
            return " \u00b7 ".join(parts)

        def _row_from(event, event_type_label):
            dw = event.drift_warning or {}
            resolution = dw.get("resolved_via") or "\u2014"
            resolution_label = {
                "omri": "OMRI lookup",
                "wsda": "WSDA Materials List",
                "national_list": "National List lookup",
                "unresolved": "Name match only (unresolved)",
                # Phase 2 — seed source findings (§ 205.204 / NOP 5029).
                "seed_certification_missing": "Seed certification not documented",
                "seed_search_incomplete": "NOP 5029 search incomplete",
                "seed_treated_prohibited": "Treated seed — confirm with certifier",
            }.get(resolution, resolution)

            # Phase 1 additive fields — inline " · " separators (not "\n")
            # because _cell escapes <br/> and a raw "\n" inside a ReportLab
            # Paragraph does not produce a line break. Single-line renders
            # cleanly and Paragraph will word-wrap naturally.
            extras = []
            cdfa = dw.get("cdfa_oim_status") or {}
            if cdfa.get("status") == "missing":
                extras.append("[CA: CDFA OIM missing]")
            elif cdfa.get("status") == "registered" and cdfa.get("cdfa_oim_reg_number"):
                extras.append(f"[CA: CDFA OIM {cdfa['cdfa_oim_reg_number']}]")
            dpr = dw.get("ca_dpr_permit_status") or {}
            if dpr.get("status") == "missing":
                extras.append("[CA DPR permit missing]")
            elif dpr.get("status") == "expired":
                extras.append(f"[CA DPR permit #{dpr.get('permit_number')} expired {dpr.get('expires')}]")
            elif dpr.get("status") == "present" and dpr.get("permit_number"):
                county_part = f" ({dpr['county']})" if dpr.get("county") else ""
                extras.append(f"[CA DPR permit #{dpr['permit_number']}{county_part}]")
            if resolution == "unresolved" and dw.get("omri_search_url"):
                extras.append(f"Search: {dw['omri_search_url']}")
            resolution_cell = resolution_label
            if extras:
                resolution_cell = resolution_label + " · " + " · ".join(extras)

            return [
                self._cell(_fmt_date(event.date)),
                self._cell(event_type_label, 40),
                self._cell(dw.get("input_label") or "(unknown)", 60),
                self._cell(dw.get("reason") or "\u2014", 120),
                self._cell(resolution_cell, 80),
                # "Verified" column — up to 4 catalog timestamps joined with
                # " · " so a 120-char cap is right-sized (allows word-wrap
                # without truncating any individual stamp).
                self._cell(_format_verified_cell(dw), 120),
            ]

        data = [[self._hdr(h) for h in headers]]
        for e in chem_drift:
            data.append(_row_from(e, f"Chemical / {e.get_type_display() or ''}"))
        for e in soil_drift:
            data.append(_row_from(e, f"Soil / {e.get_type_display() or ''}"))
        for e in seed_drift:
            data.append(_row_from(e, f"Planting / {e.get_type_display() or ''}"))

        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # Legend for the "Verified" column — the abbreviations ("OMRI", "WSDA",
        # "NL", "CDFA") and the timestamp format are cryptic otherwise. Placing
        # the legend immediately beneath the table keeps it paired with the
        # column whether or not the table breaks across pages.
        elements.append(self._spacer(0.04))
        elements.append(
            Paragraph(
                "<b>Verified column legend.</b> Per-finding catalog lookup "
                "timestamps recorded at event save-time. Abbreviations: "
                "<b>OMRI</b> = OMRI product catalog; <b>WSDA</b> = Washington "
                "State Department of Agriculture Organic Materials List; "
                "<b>NL</b> = USDA National List of Allowed and Prohibited "
                "Substances (7 CFR 205.600-606); <b>CDFA</b> = California "
                "Department of Food and Agriculture Organic Input Materials "
                "(CA-only). Timestamps render as "
                "<i>CATALOG YYYY-MM-DD HH:MMZ</i> in UTC. A dash ("
                "\u2014) means the finding pre-dates per-lookup timestamping.",
                self._styles["footer_note"],
            )
        )

        # Prominent OMRI-subset disclaimer — inspector must see this before
        # drawing conclusions from the drift-findings table. OMRI is the
        # system of record; Trazo's reference subset is a convenience, not a
        # verification substitute.
        elements.append(self._spacer(0.08))
        elements.append(
            Paragraph(
                "<b>OMRI reference subset — read before relying on findings above.</b> "
                "This report cross-references inputs against a curated OMRI reference "
                "subset maintained by Trazo. <b>OMRI (omri.org) is the authoritative "
                "database of record.</b> For any input shown as \u201cunresolved\u201d in the "
                "table above, use the embedded OMRI search link to verify against the "
                "full OMRI listing before approving or rejecting. A full-coverage OMRI "
                "Certifier Subscription is on the Trazo roadmap.",
                self._warning_style(),
            )
        )

        elements.append(self._spacer(0.06))
        elements.append(
            Paragraph(
                "Drift detector compares event inputs against the active OSP's "
                "approved_national_list_substances, approved_omri_products, and "
                "approved_wsda_materials sets. An empty resolution column means "
                "the input name could not be matched to any local catalog; in "
                "that case Trazo provides a deep-link into omri.org so the "
                "farmer can verify manually. California establishments also get "
                "an inline CDFA OIM registration check on fertilizer / amendment "
                "inputs — a registered product passes with its OIM reg number "
                "shown, a missing registration is flagged independently of OSP "
                "approval. The farmer should reconcile with the certifier before "
                "the next annual update (§ 205.406).",
                self._styles["footer_note"],
            )
        )

        # Catalog freshness stamp — proves the drift findings above were
        # checked against current sources, not stale seeds. Pulled from the
        # IngestionRun table populated by refresh_organic_input_catalogs.
        freshness_line = self._catalog_freshness_line()
        if freshness_line:
            elements.append(self._spacer(0.05))
            elements.append(Paragraph(freshness_line, self._styles["footer_note"]))

        return elements

    def _catalog_freshness_line(self):
        """One-line summary of when each input catalog was last refreshed.

        Auditor-facing: proves Trazo checks the live regulation on a schedule
        rather than relying on a stale seed. Returns an empty string if no
        runs are recorded yet (fresh install) so the PDF still renders cleanly.
        """
        try:
            from certifications.models import IngestionRun
        except ImportError:  # pragma: no cover — defensive
            return ""

        labels = {
            "omri": "OMRI",
            "wsda": "WSDA",
            "cdfa_oim": "CDFA OIM",
            "national_list_ecfr": "National List (eCFR)",
        }
        parts = []
        for source, label in labels.items():
            latest = IngestionRun.objects.filter(source=source).order_by("-ran_at").first()
            if latest is not None:
                parts.append(f"{label} {latest.ran_at.date().isoformat()}")
        if not parts:
            return ""
        return "Input catalogs last synced: " + ", ".join(parts) + "."

    def _build_producer_attestation_section(self):
        """
        Signed producer attestation — 7 CFR 205.401(d).

        A certifier-acceptable submission requires a dated statement from the
        producer affirming the truth of the submitted information. Trazo can't
        produce a wet signature from a PDF generator, but we CAN surface a
        typed attestation + attribution. The statement language mirrors the
        canonical § 205.401(d) certification used by CCOF, Oregon Tilth, and
        MOFGA.
        """
        elements = [self._section_header("Producer Attestation (7 CFR 205.401(d))")]

        try:
            establishment = self.production.parcel.establishment
        except AttributeError:
            establishment = None

        operator = None
        try:
            operator = self.production.operator
        except AttributeError:
            pass

        operator_name = operator.get_full_name() if operator and operator.get_full_name() else ""
        operator_name = operator_name or (operator.email if operator and operator.email else "(operator not set)")
        farm_name = establishment.name if establishment else "(farm not set)"

        # Canonical § 205.401(d) attestation wording — do NOT alter without
        # regulatory review; this is the language every major certifier accepts.
        attestation_text = (
            "I, the undersigned, hereby certify under penalty of law that the "
            "information contained in this document is true, complete, and "
            "accurate to the best of my knowledge and belief, and that all "
            "organic production practices described herein comply with the "
            "requirements of the USDA National Organic Program (7 CFR Part 205). "
            "I agree to promptly notify my certifying agent of any changes to "
            "the production, handling, or management practices that may affect "
            "the organic status of the operation (7 CFR 205.400(f))."
        )

        elements.append(Paragraph(attestation_text, self._styles["body"]))
        elements.append(self._spacer(0.15))

        # Attribution block — operator, farm, date. In a real signed submission
        # the producer signs below; this PDF records the equivalent digital
        # attribution (consistent with 21 CFR Part 11 electronic-records).
        elements.append(self._label_value("Farm / Operation", farm_name))
        elements.append(self._label_value("Producer / Operator", operator_name))
        elements.append(self._label_value("Export Date", date.today().isoformat()))
        elements.append(
            self._label_value(
                "Submission basis",
                "Trazo digital export — electronic attestation per 21 CFR Part 11",
            )
        )
        elements.append(self._spacer(0.1))

        # Signature block (physical review fallback).
        elements.append(
            Paragraph(
                "<b>Signature</b>: ____________________________________________ "
                "&nbsp;&nbsp;&nbsp; <b>Date</b>: _______________",
                self._styles["body"],
            )
        )
        elements.append(self._spacer(0.05))
        elements.append(
            Paragraph(
                "Some certifiers require a wet or digital signature in addition "
                "to the electronic attestation. If required, print this section "
                "and sign above before submitting to your certifier.",
                self._styles["footer_note"],
            )
        )
        return elements

    def _build_regulatory_scope_section(self):
        """
        Regulatory scope declarations — explicit N/A statements for regulations
        an auditor will ask about. Inspector-review finding (2025): silence on
        FSMA 204 / FSMA PSR / § 205.201(c) ICS creates an information gap;
        one-line affirmative statements close the question pre-emptively.
        """
        from certifications.models import OrganicSystemPlan

        elements = [self._section_header("Regulatory Scope Declarations")]

        try:
            establishment = self.production.parcel.establishment
        except AttributeError:
            establishment = None

        # --- FSMA 204 Food Traceability Rule (21 CFR 1.1300, effective 2028-07-20) ---
        crop_type_name = ""
        try:
            crop_type_name = (self.production.crop_type.name or "").lower() if self.production.crop_type else ""
        except AttributeError:
            pass

        # FSMA 204 Food Traceability List (FTL). Simplified match — covered crops
        # include leafy greens, tomatoes, peppers, cucumbers, herbs, tropical
        # tree fruits (but NOT avocados), melons, sprouts. Do not claim coverage
        # we can't verify — only apply the exemption if we recognize the crop.
        ftl_covered_keywords = (
            "leafy green",
            "spinach",
            "lettuce",
            "arugula",
            "kale",
            "tomato",
            "pepper",
            "cucumber",
            "herb",
            "melon",
            "sprout",
        )
        ftl_exempt_keywords = (
            "avocado",
            "citrus",
            "orange",
            "lemon",
            "apple",
            "pear",
            "stone fruit",
            "cherry",
            "peach",
        )
        if any(kw in crop_type_name for kw in ftl_covered_keywords):
            fsma_204_status = (
                "COVERED. Crop is on the FDA Food Traceability List. FSMA 204 "
                "KDEs/CTEs required at harvest, cooling, packing, and shipping "
                "by 2028-07-20. Trazo lot tracking captures the identifiers; "
                "formal CTE/KDE export is on the roadmap."
            )
        elif any(kw in crop_type_name for kw in ftl_exempt_keywords):
            fsma_204_status = (
                "NOT COVERED. Crop is not on the FDA Food Traceability List "
                "(21 CFR 1.1300). No FSMA 204 KDE/CTE tracking required. Lot "
                "tracking still maintained voluntarily."
            )
        else:
            fsma_204_status = (
                "STATUS UNKNOWN for this crop. Operator to confirm with "
                "certifier whether the crop appears on the FDA Food Traceability "
                "List (21 CFR 1.1300)."
            )
        elements.append(self._label_value("FSMA 204 (Food Traceability Rule)", fsma_204_status))

        # --- FSMA Produce Safety Rule water testing (21 CFR 112.44) ---------
        # PSR applies to covered produce farms >$25k revenue. Avocados are
        # NOT "rarely consumed raw" for FDA purposes; they ARE covered.
        elements.append(
            self._label_value(
                "FSMA Produce Safety Rule (21 CFR 112)",
                (
                    "Agricultural water testing records (if required for this "
                    "operation's size and crop classification) are maintained "
                    "outside the NOP scope of this export. Operator to provide "
                    "annual water test results to the certifier on request."
                ),
            )
        )

        # --- Producer Group ICS (§ 205.201(c)) ----------------------------
        # Producer groups require an Internal Control System per SOE. Single-
        # operation farms skip it. The OSP's additional_certifier_info section
        # also declares this; the scope section repeats for inspector clarity.
        is_producer_group = False
        if establishment:
            # Best-effort heuristic: has_split_operation or multi-parcel multi-
            # operator setups aren't the same as a producer group. Without an
            # explicit "is_group" flag, default to N/A.
            is_producer_group = False
        ics_status = (
            "APPLICABLE — producer group. Internal Control System required per "
            "§ 205.201(c); see OSP additional_certifier_info section."
            if is_producer_group
            else "NOT APPLICABLE — single-operation farm. § 205.201(c) Internal "
            "Control System requirements do not apply."
        )
        elements.append(self._label_value("§ 205.201(c) Internal Control System", ics_status))

        # --- SOE Fraud Prevention (§ 205.201(a)(3)) — cross-reference -----
        elements.append(
            self._label_value(
                "SOE Fraud Prevention Plan",
                (
                    "Described in OSP § 205.201(a)(3) Monitoring & Fraud "
                    "Prevention section. Establishment-level OFPP status "
                    "summarized under 'SOE Compliance Status' below."
                ),
            )
        )

        # --- NOP Import Certificates (handlers only) -----------------------
        elements.append(
            self._label_value(
                "NOP Import Certificates (SOE)",
                "Not applicable — this operation is a producer, not a handler/importer.",
            )
        )

        # --- Labeling review (§ 205.303-311) -------------------------------
        elements.append(
            self._label_value(
                "Labeling Review (§ 205.303-311)",
                (
                    "Product labels must be certifier-approved before use. Label "
                    "artifacts (product label image, PLU sticker, bin tag) are "
                    "maintained separately and submitted to the certifier at "
                    "OSP filing. Not embedded in this export."
                ),
            )
        )

        # --- Rootstock / commercial-availability (§ 205.204, perennial) ----
        # For perennial crops, § 205.204(a)(1) requires a commercial-availability
        # search when non-organic planting stock is used. Trazo does not yet
        # maintain a structured rootstock dossier; the honest disclosure is that
        # the documentation lives in the parcel dossier and must be provided
        # directly to the inspector on request.
        elements.append(
            self._label_value(
                "Rootstock commercial-availability (§ 205.204)",
                (
                    "Perennial rootstock certification and, for non-organic "
                    "rootstock, the § 205.204(a)(1) commercial-availability "
                    "search affidavit are maintained in the parcel dossier. "
                    "Operator provides these directly to the inspector on "
                    "request. Trazo does not yet structure rootstock records "
                    "in this export."
                ),
            )
        )

        # --- Residue testing (§ 205.670(e)) --------------------------------
        # Certifier-directed sampling. The farm does not proactively log residue
        # tests; attachments are added to the production record when sampled.
        elements.append(
            self._label_value(
                "Residue testing (§ 205.670(e))",
                (
                    "Residue testing is certifier-directed sampling under "
                    "§ 205.670 (risk-based, ~5% pool). The producer attaches "
                    "lab results to the Trazo production record when sampling "
                    "occurs. Absent sampling, this section is intentionally empty."
                ),
            )
        )

        elements.append(self._spacer(0.08))
        elements.append(
            Paragraph(
                "Sources: FDA FSMA 204 Final Rule (21 CFR 1.1300), FDA FSMA "
                "Produce Safety Rule (21 CFR 112), USDA NOP 7 CFR 205.201(c), "
                "205.204, 205.303-311, 205.670, SOE Final Rule (88 FR 3622).",
                self._styles["footer_note"],
            )
        )
        return elements

    # ------------------------------------------------------------------
    # Section: General Documentation (non-contamination notes)
    # ------------------------------------------------------------------

    def _build_general_events_section(self):
        """
        General farm documentation notes — § 205.103(b)(1) "adapted to the
        particular business" recordkeeping. These are the season-summary,
        training, certification-prep, and ad-hoc notes farmers log under the
        General event type. Contamination incidents are intentionally excluded
        — they render in the SOE Compliance section's own Contamination Log.
        """

        elements = [self._section_header("General Documentation")]

        events = list(
            self.production.history_generalevent_events.filter(is_contamination_incident=False).order_by("date")
        )

        # Pointer to the excluded incidents — an inspector scanning this
        # section must not conclude contamination went undocumented just
        # because the rows live in the SOE Compliance Status section.
        contamination_count = self.production.history_generalevent_events.filter(is_contamination_incident=True).count()
        contamination_pointer = None
        if contamination_count > 0:
            contamination_pointer = Paragraph(
                f"<i>{contamination_count} contamination incident(s) recorded — "
                "see SOE Compliance Status section (§ 205.272).</i>",
                self._styles["footer_note"],
            )

        headers = ["Date", "Activity Type", "Name", "People", "Duration", "Notes", "By"]

        if not events:
            elements.append(self._empty_table(headers))
            if contamination_pointer is not None:
                elements.append(contamination_pointer)
            return elements

        header_row = [self._hdr(h) for h in headers]
        data = [header_row]
        for ev in events:
            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(ev.activity_type, 30),
                    self._cell(ev.activity_name or ev.name, 30),
                    self._cell(str(ev.people_involved) if ev.people_involved is not None else None),
                    self._cell(ev.duration),
                    # Notes can run long — season summaries, training logs,
                    # certification-prep narratives. Let ReportLab word-wrap
                    # inside the column instead of cutting mid-sentence.
                    # Same cap as the Production Events description column.
                    self._cell(ev.observation, 600),
                    self._cell(ev.performed_by, 25),
                ]
            )

        col_widths = [
            0.7 * inch,  # Date
            1.0 * inch,  # Activity Type
            1.0 * inch,  # Name
            0.5 * inch,  # People
            0.7 * inch,  # Duration
            2.3 * inch,  # Notes
            0.8 * inch,  # By
        ]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)
        if contamination_pointer is not None:
            elements.append(contamination_pointer)
        return elements

    # OFPP filename heuristic — surfaces misfiled receipts/invoices uploaded
    # in place of an actual Organic Fraud Prevention Plan. The filename check
    # is a first-pass integrity signal; the inspector still has to open the
    # file to confirm content.
    _OFPP_SUSPICIOUS_FILENAME_PATTERNS = ("factura", "invoice", "receipt", "comprobante", "recibo")

    def _ofpp_flags(self):
        """
        Compute OFPP state in ONE place so both the SOE section and the
        page-1 Compliance Snapshot can consult the same verdict.

        Returns dict::

            {
                "establishment": <Establishment | None>,
                "uploaded": bool,
                "doc_name": str,                 # basename or "—"
                "doc_hash": str,                 # sha256 prefix or ""
                "date_str": str,
                "responsible": str,
                "filename_suspicious": bool,     # TRUE => hard-FAIL, inspector non-conformance
            }
        """
        establishment = None
        if self.production.parcel and self.production.parcel.establishment:
            establishment = self.production.parcel.establishment
        result = {
            "establishment": establishment,
            "uploaded": False,
            "doc_name": "—",
            "doc_hash": "",
            "date_str": "Not set",
            "responsible": "Not assigned",
            "filename_suspicious": False,
        }
        if not establishment:
            return result
        result["uploaded"] = bool(establishment.fraud_prevention_plan_uploaded)
        if establishment.fraud_prevention_plan_date:
            result["date_str"] = establishment.fraud_prevention_plan_date.strftime("%Y-%m-%d")
        result["responsible"] = establishment.ofpp_responsible_person or "Not assigned"
        doc = establishment.fraud_prevention_plan_document
        if doc and doc.name:
            try:
                result["doc_name"] = os.path.basename(doc.name)
            except Exception:
                result["doc_name"] = "—"
            try:
                import hashlib

                with doc.open("rb") as f:
                    result["doc_hash"] = hashlib.sha256(f.read()).hexdigest()[:16]
            except Exception:
                result["doc_hash"] = "unavailable"
            lowered = result["doc_name"].lower()
            result["filename_suspicious"] = any(p in lowered for p in self._OFPP_SUSPICIOUS_FILENAME_PATTERNS)
        return result

    def _build_soe_compliance_section(self):
        """SOE compliance status: OFPP, record retention, traceability."""
        elements = [self._section_header("SOE Compliance Status")]

        ofpp = self._ofpp_flags()
        establishment = ofpp["establishment"]
        ofpp_doc_name = ofpp["doc_name"]
        ofpp_doc_hash = ofpp["doc_hash"]
        ofpp_date = ofpp["date_str"]
        ofpp_person = ofpp["responsible"]

        if establishment:
            # OFPP Status — filename heuristic promotes "Uploaded" to an
            # explicit [NON-CONFORMANCE] status when the filename matches a
            # misfiled-invoice/receipt pattern. An empty-upload remains a
            # NOT UPLOADED non-conformance.
            if not ofpp["uploaded"]:
                ofpp_status = "NOT UPLOADED"
            elif ofpp["filename_suspicious"]:
                ofpp_status = "[NON-CONFORMANCE] filename suggests misfile"
            else:
                ofpp_status = "Uploaded"
            ofpp_filename_warning = (
                " [NON-CONFORMANCE: filename matches misfiled invoice/receipt pattern"
                " — inspector must open the document to verify it actually implements"
                " § 205.201(a)(3) OFPP requirements; if not, the operation is"
                " non-compliant regardless of the upload flag]"
                if ofpp["filename_suspicious"]
                else ""
            )

            split_plan_text = (
                establishment.split_operation_plan
                if establishment.split_operation_plan
                else (
                    "Commingling prevention plan required (7 CFR 205.272)"
                    if establishment.has_split_operation
                    else "Single-operation farm — no commingling plan required"
                )
            )

            # Wrap every cell in a Paragraph so long values word-wrap inside the
            # column (ReportLab Table does NOT wrap raw-string cells — same
            # WORDWRAP gotcha we hit in the change-log table). Also gives XML
            # escaping for '<', '>', '&' in user-supplied text.
            cell_style = ParagraphStyle(
                "SOECell",
                parent=self._styles["body"],
                fontSize=8,
                leading=10,
            )
            header_style = ParagraphStyle(
                "SOEHeader",
                parent=cell_style,
                fontName="Helvetica-Bold",
            )

            def P(text):
                return Paragraph(self._safe_narrative(str(text)), cell_style)

            rows = [
                [Paragraph(h, header_style) for h in ("Requirement", "Status", "Details")],
                [
                    P("Organic Fraud Prevention Plan"),
                    P(ofpp_status),
                    P(
                        f"Date: {ofpp_date} · Responsible: {ofpp_person} · "
                        f"Document: {ofpp_doc_name}"
                        + (f" · SHA-256: {ofpp_doc_hash}" if ofpp_doc_hash else "")
                        + ofpp_filename_warning
                    ),
                ],
                [
                    P("Record Retention (5 years)"),
                    P("Active" if self.production.retention_until else "Not set"),
                    P(
                        f"Until: {self.production.retention_until}"
                        if self.production.retention_until
                        else "Set automatically at production finish"
                    ),
                ],
                [
                    P("Lot Traceability"),
                    P("Assigned" if self.production.lot_id else "Missing"),
                    P(
                        f"Lot ID: {self.production.lot_id}"
                        if self.production.lot_id
                        else "Assign lot ID at production finish"
                    ),
                ],
                [
                    P("Post-Harvest Sales Record"),
                    P("Recorded" if self.production.sold_to else "Not recorded"),
                    P(
                        f"Sold to: {self.production.sold_to}"
                        if self.production.sold_to
                        else "Add sales data after harvest"
                    ),
                ],
                [
                    P("Organic on Invoice"),
                    P("Yes" if self.production.organic_on_invoice else "No / Not set"),
                    P("SOE requires organic identification on sales documents"),
                ],
                [
                    P("Split Operation (7 CFR 205.272)"),
                    P("Yes" if establishment.has_split_operation else "No"),
                    P(split_plan_text),
                ],
            ]

            col_widths = [2.0 * inch, 1.2 * inch, 3.5 * inch]
            t = Table(rows, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)

            # Split operation warning
            if establishment.has_split_operation and not establishment.split_operation_plan:
                elements.append(
                    Paragraph(
                        "<b>[WARNING] NOP 7 CFR 205.272:</b> This is a split operation (organic + conventional) "
                        "but no commingling prevention plan is documented. "
                        "Document labeling, storage separation, and equipment cleaning protocols.",
                        self._warning_style(),
                    )
                )
        else:
            elements.append(self._body("No establishment linked to this production."))

        # Contamination Incident Log — § 205.272 is the correct cite for
        # commingling / contact-with-prohibited-substance prevention. § 205.201(b)
        # is the OSP-substitution clause and does not govern contamination logs.
        contamination_events = list(
            self.production.history_generalevent_events.filter(is_contamination_incident=True).order_by("date")
        )
        if contamination_events:
            elements.append(self._spacer(0.1))
            elements.append(
                Paragraph(
                    "<b>Contamination Incident Log (7 CFR 205.272)</b>",
                    self._sub_header_style(),
                )
            )
            cont_headers = [
                "Date",
                "Source",
                "Area (ac)",
                "Corrective Action",
                "Action Date",
                "Certifier Notified",
            ]
            cont_data = [[self._hdr(h) for h in cont_headers]]
            for cev in contamination_events:
                source_display = ""
                if cev.contamination_source:
                    source_display = cev.get_contamination_source_display()
                cont_data.append(
                    [
                        self._cell(_fmt_date(cev.date)),
                        self._cell(source_display),
                        self._cell(str(cev.contamination_affected_area) if cev.contamination_affected_area else "—"),
                        # Raise corrective-action cell cap so the action
                        # narrative wraps in-column instead of truncating
                        # mid-sentence ("Notified CCOF inspector within
                        # 24…" kind of cutoff). Same pattern as the
                        # Production Events / General Documentation fix.
                        self._cell(cev.corrective_action_taken, 600),
                        self._cell(_fmt_date(cev.corrective_action_date) if cev.corrective_action_date else None),
                        self._cell(
                            f"Yes ({_fmt_date(cev.certifier_notification_date)})"
                            if cev.certifier_notified and cev.certifier_notification_date
                            else ("Yes" if cev.certifier_notified else "No")
                        ),
                    ]
                )
            cont_widths = [0.65 * inch, 0.9 * inch, 0.6 * inch, 2.4 * inch, 0.75 * inch, 1.0 * inch]
            ct = Table(cont_data, colWidths=cont_widths, repeatRows=1)
            ct.setStyle(self._base_table_style())
            elements.append(ct)

        # ----------------------------------------------------------------
        # SOE 2024 Compliance Items (88 FR 3622, effective 2024-03-19)
        # Inspectors look for these items during the annual inspection.
        # The block surfaces what Trazo CAN verify from data on file plus the
        # operator's standing attestations — not blanket Trazo guarantees.
        # Phrasing matters: claiming the operation "maintains X" when the
        # underlying field is empty would be a fraudulent attestation under
        # FTC Green Guides and § 205.401(d). Each item below either reads from
        # actual establishment / production state or is phrased as the operator's
        # own declaration.
        # ----------------------------------------------------------------
        elements.append(self._spacer(0.18))
        elements.append(
            Paragraph(
                "<b>SOE 2024 Compliance Items (88 FR 3622)</b>",
                self._sub_header_style(),
            )
        )

        # 1. Fraud Prevention Plan — REPORT actual state, never assert one exists
        # when it doesn't. Status comes from the establishment row. A suspicious
        # filename pattern promotes the item to an explicit [NON-CONFORMANCE]
        # with equal severity to "not uploaded" — uploading a PDF labelled
        # "ComprobanteFactura.pdf" is worse than honest non-compliance because
        # it looks compliant at a glance.
        if establishment is not None and ofpp["uploaded"] and not ofpp["filename_suspicious"]:
            ofpp_text = (
                "<b>Fraud Prevention Plan (7 CFR 205.201(a)(3)):</b> "
                "Operator has uploaded a written Organic Fraud Prevention Plan "
                f"(file: {ofpp_doc_name}; effective {ofpp_date}; responsible: {ofpp_person}). "
                "Inspector should review the plan for documented monitoring procedures, "
                "supplier verification, and deviation/corrective-action protocols."
            )
        elif establishment is not None and ofpp["uploaded"] and ofpp["filename_suspicious"]:
            ofpp_text = (
                "<b>[NON-CONFORMANCE \u2014 treat as missing OFPP] "
                "Fraud Prevention Plan (7 CFR 205.201(a)(3)):</b> "
                f"An OFPP file is uploaded (<code>{ofpp_doc_name}</code>) but its "
                "filename matches the pattern of a misfiled invoice/receipt. Trazo "
                "treats this upload as a missing OFPP for compliance-snapshot "
                "purposes: \u00a7 205.201(a)(3) (SOE, effective 2024-03-19) requires "
                "a substantive plan with a vulnerability assessment, supplier "
                "verification, monitoring procedures, and deviation / corrective-"
                "action protocols. An operation without a valid OFPP is ineligible "
                "for certification. The operator must upload a real OFPP before the "
                "next inspection; inspectors should not be asked to discover that "
                "the file is an invoice during the audit."
            )
        else:
            ofpp_text = (
                "<b>[NON-CONFORMANCE] Fraud Prevention Plan (7 CFR 205.201(a)(3)):</b> "
                "No Organic Fraud Prevention Plan is on file for this operation. "
                "SOE (effective 2024-03-19) requires every certified operation to "
                "maintain a written OFPP. Upload the plan via the Establishment "
                "settings before the next inspection."
            )
        elements.append(Paragraph(ofpp_text, self._styles["body"]))

        # 2. Record retention — Trazo describes its OWN durability promise; the
        # 5-year retention is a regulatory requirement the operator is responsible
        # for. We attest to the platform behavior, not the operator's compliance.
        elements.append(
            Paragraph(
                "<b>Record retention (7 CFR 205.103(b)(4)):</b> "
                "Trazo retains all event logs, OSP versions, approved-input change logs, "
                "and audit-trail entries for this production in PostgreSQL with point-in-"
                "time recovery, and stores attached media in S3. Records remain accessible "
                "for the regulatory minimum of 5 years from creation. The operator is "
                "responsible for retaining any paper / off-platform records to the same "
                "standard.",
                self._styles["body"],
            )
        )

        # 3. Unannounced inspection — describe the data availability Trazo provides
        # rather than asserting staff are trained.
        elements.append(
            Paragraph(
                "<b>Unannounced inspection readiness (7 CFR 205.661):</b> "
                "All event logs, OSP narratives, input purchases, and sales records "
                "for this production are maintained in real time and can be exported "
                "(this report) within minutes of a certifier or USDA request — no "
                "advance preparation required.",
                self._styles["body"],
            )
        )

        # 4. Non-retail container labeling — § 205.307 is the correct cite.
        # § 205.273 covers Imports and is NOT about non-retail labeling. Under
        # the post-SOE rule (88 FR 3622, effective 2024-03-19), § 205.307(a)
        # requires ONLY two items on a non-retail container: (1) identification
        # of the product as organic, and (2) the production lot number /
        # shipping ID / other unique identifier linking the container to audit
        # trail documentation. Operation name and certifying-agent name are
        # NOT mandatory on non-retail containers (they are mandatory on retail
        # under § 205.303 but § 205.307 was deliberately narrowed by AMS to
        # reduce burden on bulk shipping / harvest bins). Flagging their
        # absence invents a regulatory hurdle the rule does not impose.
        if self.production.lot_id:
            label_text = (
                "<b>Non-retail container labeling (7 CFR 205.307):</b> "
                f"Lot ID <b>{self.production.lot_id}</b> is assigned to this production "
                "and links every harvest container to the events recorded in this "
                "report. Under the post-SOE § 205.307(a), each non-retail container "
                "must display only: (1) identification of the product as organic "
                "(e.g., the word \u201corganic\u201d or \u201cORG\u201d), and (2) a "
                "unique identifier \u2014 typically this lot / shipping ID \u2014 "
                "linking the container to audit-trail documentation. Operation name, "
                "certifying-agent name, and USDA seal are permitted but not required "
                "on non-retail containers. Operator attests that every non-retail "
                "container leaving the farm bears both the organic identity mark and "
                "this lot / shipping ID."
            )
        else:
            label_text = (
                "<b>[REVIEW] Non-retail container labeling (7 CFR 205.307):</b> "
                "No lot ID has been assigned to this production yet. Under post-SOE "
                "\u00a7 205.307(a), each non-retail container must bear (1) "
                "identification of the product as organic, and (2) a unique "
                "identifier (lot / shipping ID) that links it to audit-trail "
                "documentation. Assign a lot ID at production finish so every "
                "non-retail container can be traced back to the harvest events "
                "recorded in this report."
            )
        elements.append(Paragraph(label_text, self._styles["body"]))

        # 5. Import certificate — neutral statement; we don't track imports yet.
        elements.append(
            Paragraph(
                "<b>NOP Import Certificate (SOE 2024):</b> "
                "Trazo does not currently track imported organic inputs. If any "
                "imported organic input was used in this production period, the "
                "NOP Import Certificate issued by the foreign certifier must "
                "accompany the shipment and be retained for 5 years; provide it "
                "directly to the inspector during the on-site visit.",
                self._styles["body"],
            )
        )

        # 6. Supply-chain traceability audit readiness — producer-side cites.
        # § 205.501(a)(21) authorises certifiers to conduct risk-based supply-
        # chain traceability audits; § 205.201(a)(3) is the producer-side duty
        # to maintain supplier-verification / fraud-prevention procedures.
        # § 205.504(b)(7) is deliberately NOT cited here — it addresses the
        # evidence certifiers must submit to AMS for accreditation, which is
        # not a producer duty. "SOE 24-hour response window" is likewise not a
        # regulatory deadline — Trazo exposes rapid-retrieval as a capability,
        # not as a self-imposed non-compliance trap.
        elements.append(
            Paragraph(
                "<b>Supply-chain traceability audit readiness "
                "(7 CFR 205.501(a)(21) / 205.201(a)(3)):</b> "
                "Producer attests that all event logs, OSP narratives, input "
                "purchases, drift-detector findings, mass-balance aggregates, "
                "and sales records in this report are the same records that "
                "would be pulled for a certifier-initiated supply-chain "
                "traceability audit. Trazo infrastructure supports rapid "
                "retrieval (target: 24-hour response) of the full farm-to-QR "
                "trail via API or direct dashboard access, and producer will "
                "cooperate with traceability audits initiated by the "
                "certifying agent, AMS, or downstream certified operations.",
                self._styles["body"],
            )
        )

        elements.append(self._spacer(0.08))
        elements.append(
            Paragraph(
                "SOE (Strengthening Organic Enforcement) rule effective March 19, 2024 requires "
                "fraud prevention plans (7 CFR 205.201(a)(3)), enhanced traceability "
                "(7 CFR 205.103(b)(2)), 5-year record retention (7 CFR 205.103(b)(4)), "
                "and supply-chain traceability audits (7 CFR 205.501(a)(21)).",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # Section: Record Change History (Sprint 2.1 — django-auditlog)
    # ------------------------------------------------------------------

    def _build_change_history_section(self):
        """
        Per-record edit log from django-auditlog.

        Inspector uses this to verify trustworthy-records principles (21 CFR Part 11):
        every modification has a user, timestamp, and field-level diff. Records edited
        after production finish_date are flagged.
        """
        from auditlog.models import LogEntry

        elements = [self._section_header("Record Change History")]
        elements.append(
            self._body(
                "Edit attribution and field-level diffs for this production and its events. "
                "Every change is timestamped and attributed to the user who made it "
                "(NOP digital recordkeeping trustworthiness, per 7 CFR 205.103)."
            )
        )

        all_entries = list(LogEntry.objects.get_for_object(self.production))
        event_querysets = [
            self.production.history_productionevent_events.all(),
            self.production.history_chemicalevent_events.all(),
            self.production.history_soilmanagementevent_events.all(),
            self.production.history_pestmanagementevent_events.all(),
            self.production.history_businessevent_events.all(),
            self.production.history_weatherevent_events.all(),
            self.production.history_generalevent_events.all(),
        ]
        for qs in event_querysets:
            for ev in qs:
                all_entries.extend(LogEntry.objects.get_for_object(ev))

        if not all_entries:
            elements.append(self._spacer(0.1))
            elements.append(
                self._body(
                    "No edit history recorded yet. (Audit-trail capture began on Sprint 2.1 "
                    "rollout — earlier records are reported as 'unmodified since creation'.)"
                )
            )
            return elements

        all_entries.sort(key=lambda le: le.timestamp, reverse=True)

        finalize_date = self.production.finish_date.date() if self.production.finish_date else None
        post_finalize_count = (
            sum(
                1
                for le in all_entries
                if finalize_date and le.action == LogEntry.Action.UPDATE and le.timestamp.date() > finalize_date
            )
            if finalize_date
            else 0
        )

        elements.append(self._spacer(0.1))
        summary_text = (
            f"Total recorded changes: {len(all_entries)}. "
            f"Production finalized: {finalize_date.isoformat() if finalize_date else 'No (in progress)'}."
        )
        elements.append(self._body(summary_text))

        if post_finalize_count:
            elements.append(self._spacer(0.05))
            elements.append(
                Paragraph(
                    f"<b>[REVIEW] {post_finalize_count} edit(s) recorded after production was finalized "
                    f"on {finalize_date.isoformat()}. Inspector should review these changes for "
                    f"corrective-action context.</b>",
                    self._warning_style(),
                )
            )

        elements.append(self._spacer(0.1))

        action_map = {
            LogEntry.Action.CREATE: "Created",
            LogEntry.Action.UPDATE: "Updated",
            LogEntry.Action.DELETE: "Deleted",
            LogEntry.Action.ACCESS: "Accessed",
        }
        headers = ["Timestamp", "Actor", "Action", "Record", "Fields Changed"]
        data = [[self._hdr(h) for h in headers]]

        for le in all_entries[:200]:  # cap to avoid runaway PDFs
            # Actor attribution, per 21 CFR Part 11 / ALCOA+: prefer the logged-in
            # user recorded by AuditlogMiddleware; fall back to the underlying
            # record's created_by; last-resort is an explicit "system (background
            # task)" label so an inspector can distinguish a signal/migration
            # side-effect from a user-initiated change. Never render bare "system".
            actor = None
            if le.actor:
                try:
                    actor = le.actor.email or str(le.actor)
                except Exception:
                    actor = str(le.actor)
            if not actor:
                try:
                    record = le.content_type.model_class().objects.filter(pk=le.object_pk).only("created_by").first()
                    if record is not None and getattr(record, "created_by", None):
                        cb = record.created_by
                        actor = getattr(cb, "email", None) or str(cb)
                except Exception:
                    actor = None
            if not actor:
                actor = "system (background task)"
            model_name = le.content_type.model_class().__name__ if le.content_type else "Unknown"
            record_label = f"{model_name} #{le.object_pk}"
            changed_fields = ", ".join(le.changes_dict.keys()) if le.changes_dict else "—"
            data.append(
                [
                    self._cell(le.timestamp.strftime("%Y-%m-%d %H:%M")),
                    self._cell(actor),
                    self._cell(action_map.get(le.action, "?")),
                    self._cell(record_label),
                    self._cell(changed_fields, 80),
                ]
            )

        col_widths = [1.2 * inch, 1.4 * inch, 0.7 * inch, 1.3 * inch, 2.0 * inch]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        if len(all_entries) > 200:
            elements.append(self._spacer(0.05))
            elements.append(
                Paragraph(
                    f"Note: showing the most recent 200 of {len(all_entries)} total entries. "
                    f"Full audit trail available via the audit-trail API endpoint.",
                    self._styles["footer_note"],
                )
            )

        return elements

    # ------------------------------------------------------------------
    # CSV generation — public entry point
    # ------------------------------------------------------------------

    def generate_csv(self):
        """
        Return a BytesIO containing a UTF-8 BOM CSV with all events
        in chronological order.
        """
        buffer = io.BytesIO()
        # UTF-8 BOM for Excel compatibility
        buffer.write(b"\xef\xbb\xbf")

        wrapper = io.TextIOWrapper(buffer, encoding="utf-8", newline="", write_through=True)
        writer = csv.writer(wrapper)

        headers = [
            "Date",
            "Event Category",
            "Event Type",
            "Description",
            "Product / Input",
            "Amount",
            "Unit",
            "Method",
            "Operator",
            "Photos Count",
            "Carbon (kg CO2e)",
            "Notes",
            "Supplier",
            "Purchase Date",
            "Invoice #",
            "Concentration / NPK",
            "Organic Status",
            "REI (hrs)",
            "PHI (days)",
        ]
        writer.writerow(headers)

        all_rows = []

        # 7 extra columns for NOP traceability (chemical-only, others padded with "")
        nop_pad = ["", "", "", "", "", "", ""]

        # --- Production Events ---
        # CSV-specific harvest_method labels (mirrors the PDF table above and
        # the frontend HARVEST_METHOD_LABELS registry for consistency).
        _CSV_HARVEST_METHOD_LABELS = {
            "hand_picking": "Hand Picking",
            "selective_hand_picking": "Selective Hand Picking",
            "mechanical": "Mechanical Harvester",
            "shake_and_catch": "Shake and Catch",
            "strip_picking": "Strip Picking",
            "manual": "Manual Harvest",
            "mixed": "Mixed (Manual + Mechanical)",
        }

        for ev in self.production.history_productionevent_events.all():
            extra = ev.extra_data or {}

            # HA-specific columns: yield takes precedence over fuel, variety fills
            # Product/Input, harvest_method fills Method. Non-HA events keep the
            # fuel-centric default layout so existing exports don't change shape.
            if ev.type == "HA":
                if ev.yield_quantity:
                    amount = _fmt_float(ev.yield_quantity)
                    unit = _val(ev.yield_unit, "")
                else:
                    amount = _fmt_float(ev.fuel_consumed) if ev.fuel_consumed else ""
                    unit = _val(ev.fuel_unit, "") if ev.fuel_consumed else ""
                product_input = _val(ev.variety) or ""
                method_raw = getattr(ev, "harvest_method", None) or extra.get("harvest_method") or ""
                structured_method = (
                    _CSV_HARVEST_METHOD_LABELS.get(
                        method_raw, method_raw.replace("_", " ").title() if method_raw else ""
                    )
                    if method_raw
                    else ""
                )
                # Combine structured dropdown + free-text production_method so the CSV
                # carries the same hand-labor narrative the PDF Harvest Records table
                # surfaces (and the consumer QR card shows). Avoids duplicating when
                # the two strings are identical (case-insensitive).
                freetext_method = (extra.get("method") or extra.get("production_method") or "").strip()
                if structured_method and freetext_method and freetext_method.lower() != structured_method.lower():
                    method_val = f"{structured_method} ({freetext_method})"
                elif structured_method:
                    method_val = structured_method
                else:
                    method_val = freetext_method
            else:
                amount = _fmt_float(ev.fuel_consumed) if ev.fuel_consumed else ""
                unit = _val(ev.fuel_unit, "") if ev.fuel_consumed else ""
                product_input = ""
                # Non-HA: free-text production_method from extra_data (manual-labor
                # documentation for thinning/pruning/etc.)
                method_val = _val(extra.get("method") or extra.get("production_method"), "")

            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Production",
                        PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type)),
                        _val(ev.description),
                        product_input,
                        amount,
                        unit,
                        method_val,
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        _val(ev.observation),
                    ]
                    + nop_pad,
                )
            )

        # --- Chemical Events ---
        for ev in self.production.history_chemicalevent_events.all():
            amount = _fmt_float(ev.volume_numeric) if ev.volume_numeric else _val(ev.volume, "")
            unit = _val(ev.volume_unit, "") if ev.volume_numeric else ""
            method = ev.application_method_structured or ev.way_of_application
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Chemical",
                        CHEMICAL_TYPE_LABELS.get(ev.type, _val(ev.type)),
                        _val(ev.description),
                        _val(ev.commercial_name),
                        amount,
                        unit,
                        _val(method),
                        _val(ev.applicator_name or ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        _val(ev.observation),
                        # NOP traceability columns
                        _val(ev.supplier_name),
                        _fmt_date(ev.purchase_date) if ev.purchase_date else "",
                        _val(ev.purchase_invoice),
                        _val(ev.concentration),
                        _val(ev.organic_approved),
                        str(ev.rei_hours) if ev.rei_hours is not None else "",
                        str(ev.phi_days) if ev.phi_days is not None else "",
                    ],
                )
            )

        # --- Soil Management Events ---
        for ev in self.production.history_soilmanagementevent_events.all():
            amount = (
                _fmt_float(ev.amendment_amount_numeric)
                if ev.amendment_amount_numeric
                else _val(ev.amendment_amount, "")
            )
            unit = _val(ev.amendment_amount_unit, "") if ev.amendment_amount_numeric else ""
            # NOP: include organic approval and compost data in notes
            notes = ""
            if ev.amendment_organic_approved:
                notes = f"Organic: {ev.get_amendment_organic_approved_display()}"
            if ev.type == "CO":
                compost_parts = []
                if ev.compost_peak_temp_f is not None:
                    compost_parts.append(f"Peak: {ev.compost_peak_temp_f}°F")
                if ev.compost_duration_days_at_temp is not None:
                    compost_parts.append(f"Days: {ev.compost_duration_days_at_temp}")
                if ev.compost_turning_count is not None:
                    compost_parts.append(f"Turns: {ev.compost_turning_count}")
                if compost_parts:
                    notes = (notes + " | " if notes else "") + ", ".join(compost_parts)
            if ev.manure_harvest_interval and ev.manure_harvest_interval != "na":
                manure_info = f"Manure interval: {ev.manure_harvest_interval} days"
                if ev.manure_application_date:
                    manure_info += f" (applied: {_fmt_date(ev.manure_application_date)})"
                notes = (notes + " | " if notes else "") + manure_info

            # Cover-crop species lives in extra_data, not amendment_type — surface it in the
            # Amendment column so the CSV matches the PDF (and doesn't drop the planted mix).
            _soil_ed = ev.extra_data if isinstance(ev.extra_data, dict) else {}
            amendment_label = _amendment_type_label(ev.amendment_type)
            if not ev.amendment_type and ev.type == "CC" and _soil_ed.get("cover_crop_species"):
                amendment_label = _soil_ed["cover_crop_species"]

            # Grazing detail (animal/count/days/purpose + rotation) has no dedicated columns —
            # fold it into notes so integrated grazing isn't dropped from the CSV dossier.
            if ev.type == "GR":
                _is_summary = _soil_ed.get("is_summary") in (True, "true")
                g_parts = []
                if ev.animal_type:
                    g_parts.append(f"{ev.animal_type}" + (f" x{ev.animal_count}" if ev.animal_count else ""))
                _g_days = _soil_ed.get("total_grazing_days") if _is_summary else ev.grazing_duration_days
                if _g_days not in (None, ""):
                    g_parts.append(f"{_g_days} grazing days")
                if _is_summary and _soil_ed.get("event_count"):
                    g_parts.append(f"{_soil_ed['event_count']} passes")
                if _is_summary and _soil_ed.get("date_start") and _soil_ed.get("date_end"):
                    g_parts.append(f"{_soil_ed['date_start']}–{_soil_ed['date_end']}")
                if ev.grazing_purpose:
                    g_parts.append(GRAZING_PURPOSE_LABELS.get(ev.grazing_purpose, ev.grazing_purpose))
                if g_parts:
                    notes = (notes + " | " if notes else "") + "Grazing: " + ", ".join(g_parts)

            # NOP pad: organic status goes in column index 16 (Organic Status).
            # Use get_<field>_display() so the inspector sees "OMRI Listed", not raw
            # "omri_listed" codes — matches the other two render sites in this file.
            soil_nop = [
                "",
                "",
                "",
                "",
                ev.get_amendment_organic_approved_display() if ev.amendment_organic_approved else "",
                "",
                "",
            ]
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Soil Management",
                        SOIL_TYPE_LABELS.get(ev.type, _val(ev.type)),
                        _val(ev.description),
                        amendment_label,
                        amount,
                        unit,
                        "",
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        notes,
                    ]
                    + soil_nop,
                )
            )

        # --- Pest Management Events ---
        for ev in self.production.history_pestmanagementevent_events.all():
            # NOP: include identification and threshold data in notes
            notes = _val(ev.pest_pressure_level)
            if ev.identified_by:
                notes = (notes + " | " if notes else "") + f"ID by: {ev.get_identified_by_display()}"
            if ev.threshold_rationale:
                notes = (notes + " | " if notes else "") + f"Rationale: {ev.threshold_rationale[:60]}"
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Pest Management",
                        PEST_TYPE_LABELS.get(ev.type, _val(ev.type)),
                        _val(ev.description),
                        _val(ev.pest_species),
                        "",
                        "",
                        _val(ev.ipm_strategy),
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        notes,
                    ]
                    + nop_pad,
                )
            )

        # --- Equipment Events ---
        for ev in self.production.history_equipmentevent_events.all():
            fuel = ev.fuel_consumed or ev.fuel_amount
            amount = _fmt_float(fuel) if fuel else ""
            unit = _val(ev.fuel_unit, "") if fuel else ""
            hours = ev.hours_operated or ev.hours_used
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Equipment",
                        EQUIPMENT_TYPE_LABELS.get(ev.type, _val(ev.type)),
                        _val(ev.description),
                        _val(ev.equipment_name),
                        amount,
                        unit,
                        "",
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        _val(str(hours) if hours else None),
                    ]
                    + nop_pad,
                )
            )

        # --- General Events ---
        for ev in self.production.history_generalevent_events.all():
            # NOP: flag contamination incidents in category and notes
            category = "Contamination Incident" if ev.is_contamination_incident else "General"
            notes = _val(ev.observation)
            if ev.is_contamination_incident:
                parts = []
                if ev.contamination_source:
                    parts.append(f"Source: {ev.get_contamination_source_display()}")
                if ev.corrective_action_taken:
                    parts.append(f"Action: {ev.corrective_action_taken[:60]}")
                if ev.certifier_notified:
                    date_str = (
                        _fmt_date(ev.certifier_notification_date) if ev.certifier_notification_date else "date not set"
                    )
                    parts.append(f"Certifier notified: {date_str}")
                notes = " | ".join(parts) if parts else notes
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        category,
                        _val(ev.activity_type),
                        _val(ev.description),
                        "",
                        "",
                        "",
                        "",
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        notes,
                    ]
                    + nop_pad,
                )
            )

        # --- Weather Events ---
        for ev in self.production.history_weatherevent_events.all():
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Weather",
                        _val(ev.type),
                        _val(ev.description),
                        "",
                        "",
                        "",
                        "",
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        _val(ev.observation),
                    ]
                    + nop_pad,
                )
            )

        # --- Business Events ---
        for ev in self.production.history_businessevent_events.all():
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Business",
                        _val(ev.type),
                        _val(ev.description),
                        "",
                        "",
                        "",
                        "",
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        "",
                    ]
                    + nop_pad,
                )
            )

        # Sort all rows chronologically; None dates sort to the end
        all_rows.sort(key=lambda r: (r[0] is None, r[0]))

        for _, row in all_rows:
            writer.writerow(row)

        # --- Custom Fields section ---
        if "custom_data" in self.sections:
            from history.custom_fields import extract_custom_fields_for_display

            writer.writerow([])
            writer.writerow(["=== ADDITIONAL FARMER-RECORDED DATA (Custom Fields) ==="])
            writer.writerow(["Event Date", "Event Category", "Event Description", "Field Name", "Field Value", "Type"])

            event_querysets = [
                ("Production", self.production.history_productionevent_events.all()),
                ("Chemical", self.production.history_chemicalevent_events.all()),
                ("Soil Management", self.production.history_soilmanagementevent_events.all()),
                ("Pest Management", self.production.history_pestmanagementevent_events.all()),
                ("Equipment", self.production.history_equipmentevent_events.all()),
                ("General", self.production.history_generalevent_events.all()),
                ("Weather", self.production.history_weatherevent_events.all()),
                ("Business", self.production.history_businessevent_events.all()),
            ]

            for category_label, qs in event_querysets:
                for ev in qs:
                    extra = getattr(ev, "extra_data", None)
                    if not extra or not isinstance(extra, dict):
                        continue
                    custom_fields = extract_custom_fields_for_display(
                        extra, visibility_filter="all", include_empty=False
                    )
                    for cf in custom_fields:
                        writer.writerow(
                            [
                                _fmt_date(ev.date),
                                category_label,
                                _val(ev.description),
                                cf.get("label", ""),
                                cf.get("value", ""),
                                cf.get("field_type", "text"),
                            ]
                        )

        # --- Certifications section ---
        if "certifications" in self.sections:
            writer.writerow([])
            writer.writerow(["=== ACTIVE CERTIFICATIONS ==="])
            writer.writerow(
                [
                    "Certification Type",
                    "Certifier",
                    "Certificate #",
                    "Effective Date",
                    "Expiry Date",
                    "Active",
                    "Verification Status",
                ]
            )
            try:
                from certifications.models import Certification

                establishment = self.production.parcel.establishment
                today = date.today()
                for cert in Certification.objects.filter(establishment=establishment).order_by("certification_type"):
                    expiry_display = _fmt_date(cert.expiry_date)
                    if cert.expiry_date:
                        days_remaining = (cert.expiry_date - today).days
                        if days_remaining < 0:
                            expiry_display = f"{expiry_display} (EXPIRED)"
                        elif days_remaining <= 90:
                            expiry_display = f"{expiry_display} (expires in {days_remaining}d)"
                    writer.writerow(
                        [
                            cert.get_certification_type_display(),
                            _val(cert.certifier_name),
                            _val(cert.certification_number),
                            _fmt_date(cert.effective_date),
                            expiry_display,
                            "Yes" if cert.is_active else "No",
                            cert.get_verification_status_display(),
                        ]
                    )
            except Exception as exc:
                logger.warning("CSV certifications section error: %s", exc)
                writer.writerow(["Error loading certification data"])

        # --- Inspection & Compliance Event History section ---
        # Mirrors the PDF _build_business_events_section so CSV consumers (auditors
        # parsing structured data) get the same cert #, inspector, and status
        # traceability that the PDF presents visually.
        if "business_events" in self.sections:
            business_events = list(self.production.history_businessevent_events.all().order_by("date"))
            if business_events:
                writer.writerow([])
                writer.writerow(["=== INSPECTION & COMPLIANCE EVENT HISTORY ==="])
                writer.writerow(
                    [
                        "Date",
                        "Activity",
                        "Certification",
                        "Certifier / Auditor",
                        "Certificate #",
                        "Inspector",
                        "Status",
                        "Sustainability Practice",
                        "Carbon Credits",
                        "Observations",
                    ]
                )
                for ev in business_events:
                    try:
                        cert_display = ev.get_certification_type_display() if ev.certification_type else ""
                    except Exception:
                        cert_display = _val(ev.certification_type)
                    try:
                        status_display = ev.get_verification_status_display() if ev.verification_status else ""
                    except Exception:
                        status_display = _val(ev.verification_status)
                    try:
                        biz_display = ev.get_business_type_display() if ev.business_type else ""
                    except Exception:
                        biz_display = _val(ev.business_type)

                    practice_display = ""
                    if ev.sustainability_practice:
                        try:
                            practice_display = ev.get_sustainability_practice_display()
                        except Exception:
                            practice_display = ev.sustainability_practice.replace("_", " ").title()

                    credits_display = ""
                    if ev.carbon_credits_earned is not None and ev.carbon_credits_earned != 0:
                        unit = ev.carbon_credits_unit or "tCO2e"
                        credits_display = f"{_fmt_float(ev.carbon_credits_earned)} {unit}"

                    writer.writerow(
                        [
                            _fmt_date(ev.date),
                            biz_display,
                            cert_display,
                            _val(ev.verified_certifier_name),
                            _val(ev.certificate_number),
                            _val(ev.performed_by),
                            status_display,
                            practice_display,
                            credits_display,
                            _val(ev.observation),
                        ]
                    )

        # --- Mass balance section ---
        if "mass_balance" in self.sections:
            writer.writerow([])
            writer.writerow(["=== MASS-BALANCE AUDIT SUMMARY ==="])
            writer.writerow(["Field", "Value"])
            p = self.production
            harvest_amount = p.production_amount
            harvest_unit = _val(p.production_unit, "")
            quantity_sold = p.quantity_sold
            sold_unit = _val(p.quantity_sold_unit, harvest_unit)
            writer.writerow(
                [
                    "Harvest Yield",
                    f"{_fmt_float(harvest_amount)} {harvest_unit}".strip() if harvest_amount else "\u2014",
                ]
            )
            writer.writerow(
                [
                    "Quantity Sold",
                    f"{_fmt_float(quantity_sold)} {sold_unit}".strip() if quantity_sold else "\u2014",
                ]
            )
            writer.writerow(["Sold To", _val(p.sold_to)])
            writer.writerow(["Sale Date", _fmt_date(p.sale_date) if p.sale_date else "\u2014"])
            writer.writerow(["Organic on Invoice", "Yes" if p.organic_on_invoice else "No"])
            # Inputs purchased sub-table
            writer.writerow([])
            writer.writerow(["Date", "Product", "Type", "Qty Purchased", "Unit"])
            for ev in p.history_chemicalevent_events.all().order_by("date"):
                if ev.quantity_purchased is not None:
                    writer.writerow(
                        [
                            _fmt_date(ev.date),
                            _val(ev.commercial_name),
                            CHEMICAL_TYPE_LABELS.get(ev.type, _val(ev.type)),
                            _fmt_float(ev.quantity_purchased),
                            _val(ev.quantity_purchased_unit),
                        ]
                    )

        # --- Field history section ---
        if "field_history" in self.sections:
            from product.models import ParcelCropHistory

            writer.writerow([])
            writer.writerow(["=== 3-YEAR FIELD & CROP ROTATION HISTORY ==="])
            try:
                parcel = self.production.parcel
                crop_history = list(ParcelCropHistory.objects.filter(parcel=parcel).order_by("-year")[:10])
                if crop_history:
                    writer.writerow(
                        [
                            "Year",
                            "Crop Grown",
                            "Production Method",
                            "Substances Applied",
                            "Last Prohibited Substance Date",
                            "Notes",
                        ]
                    )
                    for entry in crop_history:
                        writer.writerow(
                            [
                                str(entry.year),
                                _val(entry.crop_grown),
                                entry.get_production_method_display() if entry.production_method else "\u2014",
                                _val(entry.substances_applied),
                                _fmt_date(entry.date_last_prohibited),
                                _val(entry.notes),
                            ]
                        )
                else:
                    writer.writerow(["No structured crop history. Showing previous productions on this parcel."])
                    from history.models import History

                    writer.writerow(
                        [
                            "Start Date",
                            "Finish Date",
                            "Crop",
                            "Production Method",
                            "Harvest Amount",
                            "Lot ID",
                        ]
                    )
                    prev_productions = list(
                        History.objects.filter(parcel=parcel)
                        .exclude(pk=self.production.pk)
                        .select_related("crop_type", "product")
                        .order_by("-start_date")[:15]
                    )
                    for prod in prev_productions:
                        crop_name = ""
                        try:
                            crop_name = (
                                prod.crop_type.name if prod.crop_type else (prod.product.name if prod.product else "")
                            )
                        except AttributeError:
                            pass
                        harvest = (
                            f"{_fmt_float(prod.production_amount)} {_val(prod.production_unit, '')}".strip()
                            if prod.production_amount
                            else "\u2014"
                        )
                        writer.writerow(
                            [
                                _fmt_date(prod.start_date),
                                _fmt_date(prod.finish_date),
                                _val(crop_name),
                                _val(prod.get_production_method_display() if prod.production_method else None),
                                harvest,
                                _val(prod.lot_id),
                            ]
                        )
            except AttributeError as exc:
                logger.warning("CSV field_history section error: %s", exc)
                writer.writerow(["Parcel data not available"])

        wrapper.flush()
        # Detach the TextIOWrapper from the BytesIO before returning. Without this, the wrapper is
        # garbage-collected when this frame exits and its __del__ CLOSES the underlying buffer — so
        # the caller (FileResponse / .getvalue()) receives a closed buffer ("I/O operation on closed
        # file"). detach() flushes and severs the link, leaving the BytesIO open and complete.
        wrapper.detach()
        buffer.seek(0)
        return buffer
