"""The preview a grower reads before anything is saved: one PDF, two tables.

The pilot letter promises "you'll see a preview before anything is saved". This is that document.
It is built from the intake plan (`record_intake.build_plan`) and nothing else, so what the grower
approves is exactly what `--commit` writes: the command refuses to commit a batch whose preview
was never filed.

A PDF rather than a spreadsheet because the grower opens it from an email on a phone, reads it,
and answers "row 7 is wrong". It carries the sheet's OWN row numbers (the `source_locator`), not
the CSV's, because the sheet is what the grower has in hand.

Two tables, nothing else: what will be recorded, and what will not be recorded until the grower
answers. A row the operator could not place honestly is in the second table with its reason; it
is never quietly left out.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from common.specimen import SPECIMEN_LINE, is_specimen, specimen_page_callback

NOTHING_SAVED = "Nothing has been saved. Reply with corrections, or reply ok and these records are loaded as listed."


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=15, leading=18, spaceAfter=4),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=9.5, leading=12),
        "head": ParagraphStyle("h", parent=base["Heading3"], fontSize=11, leading=13, spaceBefore=8, spaceAfter=3),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontSize=8, leading=9.5),
        "cell_head": ParagraphStyle("ch", parent=base["Normal"], fontSize=8, leading=9.5, fontName="Helvetica-Bold"),
        "warn": ParagraphStyle(
            "w", parent=base["Normal"], fontSize=8, leading=9.5, textColor=colors.HexColor("#B71C1C")
        ),
    }


def _p(text, style):
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def _table_style():
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F5E9")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9E9E9E")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
    )


def _measure(fields, number_key, unit_key):
    number = fields.get(number_key)
    if number is None:
        return ""
    unit = fields.get(unit_key) or ""
    return f"{number:g} {unit}".strip()


def _details(payload) -> list:
    """The product and its numbers, one short line each, the way the sheet stated them."""
    fields = payload["fields"]
    lines = []
    product = fields.get("commercial_name") or fields.get("amendment_product_name")
    if product:
        lines.append(product)
    active = payload["extra"].get("active_ingredient")
    if active and active != product:
        lines.append(f"active ingredient: {active}")
    rate = _measure(fields, "application_rate", "application_rate_unit")
    if rate:
        lines.append(f"rate: {rate}")
    if fields.get("concentration"):
        lines.append(f"concentration: {fields['concentration']}")
    for number_key, unit_key, label in (
        ("volume_numeric", "volume_unit", "amount"),
        ("yield_quantity", "yield_unit", "harvested"),
        ("amendment_amount_numeric", "amendment_amount_unit", "amount"),
        ("area_numeric", "area_unit", "area"),
        ("area_covered", "area_unit", "area"),
    ):
        value = _measure(fields, number_key, unit_key)
        if value:
            lines.append(f"{label}: {value}")
    for key, label in (
        ("target_pest_disease", "target"),
        ("pest_species", "pest"),
        ("way_of_application", "method"),
        ("variety", "variety"),
        ("harvest_lot_code", "lot"),
    ):
        if fields.get(key):
            lines.append(f"{label}: {fields[key]}")
    return lines


def _notes(payload) -> str:
    fields = payload["fields"]
    parts = []
    if fields.get("observation"):
        parts.append(f"note (public on the buyer page): {fields['observation']}")
    if fields.get("private_note"):
        parts.append(f"private note: {fields['private_note']}")
    return "\n".join(parts)


def render_preview_pdf(plan, farm, documents, batch, operator, today=None) -> bytes:
    """Build the preview. `documents` are the filed source documents the rows name."""
    styles = _styles()
    today = today or date.today()
    specimen = is_specimen(farm)
    operator_name = " ".join(p for p in (operator.first_name, operator.last_name) if p).strip() or operator.email

    elements = [_p(f"Records to be loaded: {farm.name}", styles["title"])]
    if specimen:
        elements.append(_p(SPECIMEN_LINE, styles["warn"]))
    elements.append(
        _p(
            f"Prepared by {operator_name} on {today.isoformat()} from: "
            + "; ".join(d.title for d in documents)
            + f". Batch {batch}.",
            styles["body"],
        )
    )
    elements.append(_p(NOTHING_SAVED, styles["body"]))
    elements.append(Spacer(1, 0.1 * inch))

    importable = plan.importable
    elements.append(_p(f"Will be recorded ({len(importable)} rows)", styles["head"]))
    if importable:
        data = [
            [
                _p(h, styles["cell_head"])
                for h in ("Row", "Date", "Block(s)", "Activity", "What the sheet says", "Who", "Notes")
            ]
        ]
        for row in importable:
            p = row.payload
            detail = _details(p)
            cls = p.get("classification")
            cell = [_p("\n".join(detail), styles["cell"])]
            if cls:
                cell.append(_p(cls, styles["warn"] if p.get("warning") else styles["cell"]))
            blocks = ", ".join(p["parcels"])
            if len(p["parcels"]) > 1:
                blocks += f" ({len(p['parcels'])} records, one per block)"
            data.append(
                [
                    _p(p["source_locator"], styles["cell"]),
                    _p(p["date"].isoformat(), styles["cell"]),
                    _p(blocks, styles["cell"]),
                    _p(p["fields"].get("description", ""), styles["cell"]),
                    cell,
                    _p(p["fields"].get("performed_by") or "", styles["cell"]),
                    _p(_notes(p), styles["cell"]),
                ]
            )
        table = Table(
            data,
            colWidths=[0.6 * inch, 0.75 * inch, 1.0 * inch, 1.0 * inch, 2.15 * inch, 0.55 * inch, 0.95 * inch],
            repeatRows=1,
        )
        table.setStyle(_table_style())
        elements.append(table)
    else:
        elements.append(_p("No row can be recorded yet.", styles["body"]))

    skipped = plan.skipped
    elements.append(_p(f"Not recorded, needs your answer ({len(skipped)} rows)", styles["head"]))
    if skipped:
        data = [[_p(h, styles["cell_head"]) for h in ("Row", "What the sheet says", "Why it waits")]]
        for row in skipped:
            raw = row.payload.get("row") or {}
            said = " · ".join(
                v
                for v in (
                    raw.get("date"),
                    raw.get("parcel"),
                    raw.get("kind"),
                    raw.get("product"),
                    raw.get("observation"),
                )
                if v
            )
            data.append(
                [
                    _p(row.payload.get("source_locator") or f"line {row.line}", styles["cell"]),
                    _p(said or row.summary, styles["cell"]),
                    _p(row.reason, styles["cell"]),
                ]
            )
        table = Table(data, colWidths=[0.6 * inch, 2.4 * inch, 4.0 * inch], repeatRows=1)
        table.setStyle(_table_style())
        elements.append(table)
    else:
        elements.append(_p("Every row could be placed.", styles["body"]))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=f"Records to be loaded: {farm.name}",
    )
    furniture = specimen_page_callback(letter, specimen=specimen)
    doc.build(elements, onFirstPage=furniture, onLaterPages=furniture)
    return buffer.getvalue()
