"""
OSP PDF snapshot generator — Sprint 5A hardening.

When a farmer submits an OSP, we generate an immutable PDF capturing the exact
content at submission time. This is saved to `OrganicSystemPlan.submission_pdf`
and is the artifact the certifier receives (or, today, the farmer downloads and
forwards themselves).

Why immutable: an inspector asking "what exactly did you submit on this date?"
needs a frozen artifact. The JSONB `sections` field could be edited; the PDF
cannot. Combined with the post-submit edit lock (views.py perform_update),
this gives us trustworthy-records semantics (21 CFR Part 11 parallel).
"""

import io
import xml.sax.saxutils
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from common.pdf_text import glyph_safe
from common.specimen import is_specimen, specimen_page_callback

TRAZO_GREEN_DARK = colors.HexColor("#2E7D32")
DARK_GRAY = colors.HexColor("#333333")

SECTION_LABELS = {
    "practices_procedures": ("(a)(1)", "Practices & Procedures"),
    "inputs_list": ("(a)(2)", "Inputs / Materials List"),
    "monitoring_plan": ("(a)(3)", "Monitoring & Fraud Prevention"),
    "recordkeeping_description": ("(a)(4)", "Recordkeeping System"),
    "commingling_barriers": ("(a)(5)", "Commingling Prevention"),
    "additional_certifier_info": ("(a)(6)", "Additional Certifier Info"),
}


def _escape(text: str) -> str:
    """Escape + preserve paragraph breaks for ReportLab Paragraph."""
    if not text:
        return ""
    return xml.sax.saxutils.escape(glyph_safe(text)).replace("\n", "<br/>")


def _record_inventory(establishment):
    """Auto-generated inventory of the LIVE records backing the (a)(4) narrative.

    § 205.201(a)(4) requires the OSP to describe how records are maintained. A free-
    text description is compliant, but pairing it with the actual record counts and
    date ranges turns the claim into verifiable evidence for the certifier. Returns a
    list of (label, count, date-range-string); empty items are dropped by the caller.
    """
    from django.db.models import Count, Max, Min

    from history.models import (
        ChemicalEvent,
        GeneralEvent,
        History,
        PestManagementEvent,
        ProductionEvent,
        SoilManagementEvent,
    )

    est = establishment

    def _agg(qs, field="date"):
        r = qs.aggregate(n=Count("id"), lo=Min(field), hi=Max(field))
        n = r["n"] or 0
        if not n:
            return None
        lo, hi = r["lo"], r["hi"]

        def _d(v):
            try:
                return v.date().isoformat()
            except AttributeError:
                return v.isoformat() if v else "—"

        span = f"{_d(lo)} → {_d(hi)}" if lo and hi else "—"
        return (n, span)

    specs = [
        ("Production records", History.objects.filter(parcel__establishment=est), "start_date"),
        ("Chemical / spray records", ChemicalEvent.objects.filter(history__parcel__establishment=est), "date"),
        ("Field / production events", ProductionEvent.objects.filter(history__parcel__establishment=est), "date"),
        ("Soil management events", SoilManagementEvent.objects.filter(history__parcel__establishment=est), "date"),
        ("Pest management events", PestManagementEvent.objects.filter(history__parcel__establishment=est), "date"),
        ("General / compliance events", GeneralEvent.objects.filter(history__parcel__establishment=est), "date"),
    ]
    out = []
    for label, qs, field in specs:
        agg = _agg(qs, field)
        if agg:
            out.append((label, agg[0], agg[1]))
    return out


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "OSPSnapshotTitle",
            parent=base["Title"],
            fontSize=18,
            textColor=TRAZO_GREEN_DARK,
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "OSPSnapshotSubtitle",
            parent=base["Normal"],
            fontSize=11,
            textColor=DARK_GRAY,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "header": ParagraphStyle(
            "OSPSnapshotHeader",
            parent=base["Heading2"],
            fontSize=13,
            textColor=TRAZO_GREEN_DARK,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "OSPSnapshotBody",
            parent=base["Normal"],
            fontSize=10,
            leading=13,
        ),
        "meta": ParagraphStyle(
            "OSPSnapshotMeta",
            parent=base["Normal"],
            fontSize=9,
            textColor=DARK_GRAY,
            leading=12,
        ),
    }


def generate_osp_snapshot_pdf(osp) -> bytes:
    """
    Render an immutable PDF snapshot of the OSP. Returns raw bytes.

    The PDF includes: cover with establishment + version + submission metadata,
    § 205.401(d) attestation, then each § 205.201(a)(1)-(6) section verbatim.
    """
    from certifications.models import OSP_SECTION_KEYS

    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.75 * inch,
        title=f"OSP Submission v{osp.version_number} — {osp.establishment.name}",
    )

    story = []
    story.append(Paragraph("Organic System Plan — Submission Snapshot", styles["title"]))
    story.append(Paragraph(f"7 CFR 205.201 — Version {osp.version_number}", styles["subtitle"]))
    story.append(Spacer(1, 0.15 * inch))

    # Metadata block.
    meta_lines = [
        f"<b>Establishment:</b> {_escape(osp.establishment.name)}",
        f"<b>OSP Version:</b> v{osp.version_number}",
        f"<b>Submitted:</b> {osp.submitted_at.isoformat() if osp.submitted_at else '(pending)'}",
        f"<b>Certifier Template:</b> {_escape(osp.certifier_template_name) or '—'}",
        f"<b>Snapshot Generated:</b> {date.today().isoformat()}",
        f"<b>OSP Public ID:</b> {osp.public_id}",
    ]
    for line in meta_lines:
        story.append(Paragraph(line, styles["meta"]))
    story.append(Spacer(1, 0.15 * inch))

    # § 205.401(d) attestation — the same wording used in the audit export.
    attestation = (
        "I, the undersigned, hereby certify under penalty of law that the "
        "information contained in this document is true, complete, and "
        "accurate to the best of my knowledge and belief, and that all "
        "organic production practices described herein comply with the "
        "requirements of the USDA National Organic Program (7 CFR Part 205). "
        "I agree to promptly notify my certifying agent of any changes to "
        "the production, handling, or management practices that may affect "
        "the organic status of the operation (7 CFR 205.400(f))."
    )
    story.append(Paragraph("Producer Attestation (7 CFR 205.401(d))", styles["header"]))
    story.append(Paragraph(attestation, styles["body"]))
    story.append(Spacer(1, 0.1 * inch))

    # Per-section content.
    story.append(PageBreak())
    story.append(Paragraph("OSP Sections — § 205.201(a)(1)-(6)", styles["header"]))
    # Certifier crosswalk: this snapshot follows the six-part § 205.201(a)(1)-(6)
    # structure that CCOF, Oregon Tilth, and other USDA-accredited certifiers use
    # for their Organic System Plan forms, so a reviewer can map each section to the
    # equivalent field on their own OSP application.
    story.append(
        Paragraph(
            "<i>Structured per 7 CFR 205.201(a)(1)-(6) — the same six-part Organic System "
            "Plan structure used by CCOF, Oregon Tilth and other USDA-accredited certifiers; "
            "each section below maps to the corresponding field on the certifier's OSP form.</i>",
            styles["meta"],
        )
    )

    sections = osp.sections or {}
    for key in OSP_SECTION_KEYS:
        cfr, label = SECTION_LABELS.get(key, ("—", key))
        section = sections.get(key, {}) or {}
        narrative = (section.get("narrative") or "").strip()
        last_updated = section.get("last_updated") or "—"

        story.append(Paragraph(f"<b>{cfr} — {label}</b>", styles["header"]))
        story.append(Paragraph(f"<i>Last updated: {last_updated}</i>", styles["meta"]))
        if narrative:
            story.append(Paragraph(_escape(narrative), styles["body"]))
        else:
            story.append(Paragraph("<i>(Section empty at submission time.)</i>", styles["meta"]))

        # (a)(4) Recordkeeping: append the live record inventory so the narrative
        # claim ("records are maintained in Trazo…") is backed by verifiable counts.
        if key == "recordkeeping_description":
            try:
                inventory = _record_inventory(osp.establishment)
            except Exception:
                inventory = []
            if inventory:
                story.append(Spacer(1, 0.05 * inch))
                story.append(
                    Paragraph(
                        "<b>Record inventory (auto-generated from live records):</b>",
                        styles["meta"],
                    )
                )
                for label_i, count_i, span_i in inventory:
                    story.append(Paragraph(f"• {_escape(label_i)}: {count_i} ({_escape(span_i)})", styles["body"]))
        story.append(Spacer(1, 0.1 * inch))

    # Approved Inputs — structured list of substances/products the producer is
    # requesting certifier approval for (§ 205.201(a)(2)). Freezing this list
    # into the submission snapshot is what makes the drift detector meaningful
    # downstream: the certifier has a specific enumerated scope to approve, and
    # post-submission additions to approved_inputs are blocked in the viewset.
    story.append(Spacer(1, 0.15 * inch))
    story.append(
        Paragraph(
            "<b>Approved Inputs — requested scope (§ 205.201(a)(2))</b>",
            styles["header"],
        )
    )
    omri = list(osp.approved_omri_products.all().order_by("product_name"))
    nl = list(osp.approved_national_list_substances.all().order_by("substance_name"))
    if not omri and not nl:
        story.append(
            Paragraph(
                "<i>No structured inputs attached to this OSP. The narrative in "
                "§ 205.201(a)(2) above describes the intended inputs; the certifier "
                "is expected to enumerate approvals in their response.</i>",
                styles["meta"],
            )
        )
    else:
        if omri:
            story.append(Paragraph("<b>OMRI-listed products</b>", styles["body"]))
            for p in omri:
                omri_id = f" (OMRI #{p.omri_id})" if p.omri_id else ""
                mfr = f" — {p.manufacturer}" if p.manufacturer else ""
                story.append(
                    Paragraph(
                        f"• {_escape(p.product_name)}{_escape(omri_id)}{_escape(mfr)}",
                        styles["body"],
                    )
                )
            story.append(Spacer(1, 0.05 * inch))
        if nl:
            story.append(Paragraph("<b>National List substances</b>", styles["body"]))
            for s in nl:
                cfr = f" ({s.cfr_section})" if s.cfr_section else ""
                status_suffix = f" — status: {s.status}" if s.status and s.status != "allowed" else ""
                story.append(
                    Paragraph(
                        f"• {_escape(s.substance_name)}{_escape(cfr)}{_escape(status_suffix)}",
                        styles["body"],
                    )
                )

    # Footer note.
    story.append(Spacer(1, 0.2 * inch))
    story.append(
        Paragraph(
            "This is an immutable snapshot of the Organic System Plan content at "
            "the moment of submission. The live plan may be edited in subsequent "
            "versions; this artifact records the exact content submitted. Source: "
            "7 CFR 205.201 (eCFR).",
            styles["meta"],
        )
    )

    _furniture = specimen_page_callback(letter, specimen=is_specimen(getattr(osp, "establishment", None)))
    doc.build(story, onFirstPage=_furniture, onLaterPages=_furniture)
    return buffer.getvalue()
