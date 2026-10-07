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


def signature_block(establishment, style) -> list:
    """The lines the attestation is signed on.

    The packet says "I, the undersigned, hereby certify under penalty of law" and, until
    2026-09-11, carried no line anywhere in its 45 pages for anyone to sign, name or date. A
    certifier reads an attestation with no signature as not given. The name is printed when the
    farm profile names the responsible person (§ 205.401(b)); otherwise it is a line to fill in,
    never the plan author guessed into place.
    """
    name = (getattr(establishment, "contact_person", None) or "").strip()
    gap = "&nbsp;" * 4
    return [
        Spacer(1, 0.14 * inch),
        Paragraph(f"Signature: {'_' * 40}{gap}Date: {'_' * 16}", style),
        Spacer(1, 0.08 * inch),
        Paragraph(f"Printed name: {_escape(name) if name else '_' * 30}{gap}Title: {'_' * 24}", style),
    ]


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

        # "to", not an arrow: the standard PDF fonts carry no U+2192, and it came out as "->".
        span = f"{_d(lo)} to {_d(hi)}" if lo and hi else "—"
        return (n, span)

    specs = [
        ("Production records", History.objects.filter(parcel__establishment=est), "start_date"),
        ("Chemical / spray records", ChemicalEvent.objects.filter(history__parcel__establishment=est), "date"),
        ("Field / production events", ProductionEvent.objects.filter(history__parcel__establishment=est), "date"),
        ("Soil management events", SoilManagementEvent.objects.filter(history__parcel__establishment=est), "date"),
        # Named for what it counts. The § 11 registry's "pest management" row counts these AND the
        # pesticide sprays, and with both labelled "pest management" the two pages read as a
        # contradiction (WSDA specimen read, 2026-09-12).
        (
            "Pest monitoring and IPM records",
            PestManagementEvent.objects.filter(history__parcel__establishment=est),
            "date",
        ),
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
            # A heading never ends a page on its own. Every packet document takes its styles from
            # here, and "E. Field map" and "[G7.0 Labeling]" were printing as a page's last line
            # with their content overleaf (WSDA specimen read, 2026-09-11).
            keepWithNext=1,
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


#: Statuses a plan can hold only after it has been handed to the agent.
_SUBMITTED_STATUSES = ("submitted", "active", "superseded")


GENERATED_FROM_RECORDS_NOTE = (
    "Section narratives as held in Trazo for v{version}, generated from the operation's current "
    "records when this document was built. Trazo holds no copy generated at submission for this "
    "version, so this document does not compare them with the copy filed with the certifier."
)


def _generated_from_current_records(osp) -> bool:
    """True when document 01 is a reconstruction: the plan is past draft and holds no frozen
    submission copy, so its narratives are compiled from current records at build time."""
    if getattr(osp, "status", None) == "draft":
        return False
    return not bool(getattr(osp, "submission_pdf", None))


def snapshot_title(osp) -> str:
    """The plan's own title line, stated from its record.

    🔴 2026-09-30 (OSP alignment audit, T25). Every version printed "Submission Snapshot", so a
    draft read as a submission one page after the cover called it a draft. "Submission" is claimed
    only when the status says the plan was submitted AND the submission time is on record.
    """
    if osp.status in _SUBMITTED_STATUSES and osp.submitted_at:
        return "Organic System Plan — Submission Snapshot"
    if osp.status == "withdrawn":
        return "Organic System Plan: Withdrawn, not in effect"
    if osp.status == "draft":
        return "Organic System Plan: Draft, not submitted"
    # A later status with no submission time (an imported or activated plan). Nothing on record
    # says when, or whether, Trazo submitted it, so the title claims neither.
    return "Organic System Plan"


def generate_osp_snapshot_pdf(osp, generated_from_records=None) -> bytes:
    """
    Render an immutable PDF snapshot of the OSP. Returns raw bytes.

    `generated_from_records`: whether document 01 is a reconstruction from current records.
    None derives it from the plan (past draft, no frozen copy). The SUBMIT flow passes False:
    it sets the status to "submitted" and saves BEFORE rendering, and assigns `submission_pdf`
    only after, so at render time the plan looks exactly like a reconstruction while the bytes
    being rendered ARE the frozen copy (review of back #129).

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
        title=f"{snapshot_title(osp)} v{osp.version_number} — {osp.establishment.name}",
    )

    story = []
    story.append(Paragraph(snapshot_title(osp), styles["title"]))
    story.append(Paragraph(f"7 CFR 205.201 — Version {osp.version_number}", styles["subtitle"]))
    story.append(Spacer(1, 0.15 * inch))

    # Metadata block.
    meta_lines = [
        f"<b>Establishment:</b> {_escape(osp.establishment.name)}",
        f"<b>OSP Version:</b> v{osp.version_number}",
        # A date, like every other date in the packet. The full ISO timestamp with microseconds and
        # a UTC offset printed on the plan's own first page (WSDA specimen read, 2026-09-11).
        f"<b>Submitted:</b> {osp.submitted_at.date().isoformat() if osp.submitted_at else '(pending)'}",
        # Stated when set, omitted when not: a blank printed "Certifier Template: —" at the head of
        # the plan, a line no reader can act on (OTCO and WSDA desk reads, 2026-09-10).
        *(
            [f"<b>Certifier Template:</b> {_escape(osp.certifier_template_name)}"]
            if osp.certifier_template_name
            else []
        ),
        f"<b>Snapshot Generated:</b> {date.today().isoformat()}",
        f"<b>OSP Public ID:</b> {osp.public_id}",
    ]
    for line in meta_lines:
        story.append(Paragraph(line, styles["meta"]))
    # A plan that was activated without a submission copy (imported, or marked active from the
    # lifecycle page) has no frozen text of its own. The packet compiles its narratives from the
    # operation's current records at build time and must say so, as the dossier does; until the
    # recordkeeping review (F-06, 2026-10-07) only the dossier did, and document 01 printed
    # "Last updated: <today>" with nothing to tell the reader why.
    if generated_from_records is None:
        generated_from_records = _generated_from_current_records(osp)
    if generated_from_records:
        story.append(
            Paragraph(
                "<i>" + _escape(GENERATED_FROM_RECORDS_NOTE.format(version=osp.version_number)) + "</i>",
                styles["meta"],
            )
        )
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
    # Outline entries (PDF bookmarks) on the plan's headings: the dossier gained them in run 8
    # (R8-28); document 01, eleven pages on the specimen, had none (recordkeeping review F-17).
    from history.services.audit_export_service import OutlinedHeading

    story.append(OutlinedHeading("Producer Attestation (7 CFR 205.401(d))", styles["header"], level=0))
    story.append(Paragraph(attestation, styles["body"]))
    story.append(Spacer(1, 0.1 * inch))
    story.extend(signature_block(osp.establishment, styles["body"]))

    # Per-section content.
    story.append(PageBreak())
    story.append(OutlinedHeading("OSP Sections — § 205.201(a)(1)-(6)", styles["header"], level=0))
    # The six parts are the REGULATION's, which is the only claim this sentence can make for every
    # certifier. It used to say "the same structure used by CCOF, Oregon Tilth and other
    # certifiers" and that each section "maps to the corresponding field on the certifier's OSP
    # form": untrue for WSDA, whose AGR 2121 runs sections A-S, and it named two other agencies
    # on page 3 of a WSDA packet (2026-09-11). The form-by-form layout is the modules/ folder.
    story.append(
        Paragraph(
            "<i>Structured per 7 CFR 205.201(a)(1)-(6), the six elements every organic system plan "
            "must contain. The same answers, laid out question by question, are in the module "
            "documents that follow this plan.</i>",
            styles["meta"],
        )
    )

    # 🔴 2026-09-07 — `last_updated` has two authors: the module compiler stamps a full ISO-8601
    # datetime, the section editor a plain date. The dossier normalised this on 2026-08-19
    # (`_osp_section_date`); THIS renderer — document 01, the organic system plan itself — did
    # not, so a module-authored section printed "Last updated: 2026-09-07T16:49:10.093478+00:00"
    # beside a hand-edited one reading "2026-09-07". Same defect, sibling surface.
    #
    # Imported here rather than at module scope: `audit_export_service` reaches across most of the
    # app, and certifications is on its import path. Function-scope keeps that lazy. It is the
    # dossier's private helper being borrowed — the two renderers of one field agreeing matters
    # more than the underscore, and a second copy is how they drifted in the first place.
    from history.services.audit_export_service import _osp_section_date

    sections = osp.sections or {}
    for key in OSP_SECTION_KEYS:
        cfr, label = SECTION_LABELS.get(key, ("—", key))
        section = sections.get(key, {}) or {}
        narrative = (section.get("narrative") or "").strip()
        last_updated = _osp_section_date(section.get("last_updated")) or "—"

        story.append(OutlinedHeading(f"<b>{cfr} — {label}</b>", styles["header"], level=1))
        if generated_from_records:
            story.append(
                Paragraph(f"<i>Generated from current records: {date.today().isoformat()}</i>", styles["meta"])
            )
        else:
            story.append(Paragraph(f"<i>Last updated: {last_updated}</i>", styles["meta"]))
        if narrative:
            story.append(Paragraph(_escape(narrative), styles["body"]))
        else:
            story.append(Paragraph("<i>(Section empty at submission time.)</i>", styles["meta"]))

        # (a)(2) and the materials table below it are TWO readings of one list: the narrative is
        # the text as filed, the table is the list as it stands. On a plan filed in February and
        # read in September they can differ — the operation changed its own list — and the
        # document said nothing, so one PDF carried two answers about the same material four
        # pages apart (WSDA specimen read, 2026-09-12). Each says which it is.
        if key == "inputs_list" and osp.submitted_at:
            story.append(
                Paragraph(
                    f"<i>This is the § 205.201(a)(2) narrative as filed on "
                    f"{osp.submitted_at.date().isoformat()}. The materials list further down this "
                    "document is the operation's list as it stands today; where the two differ, the "
                    "operation changed its list after filing.</i>",
                    styles["meta"],
                )
            )

        # (a)(4) Recordkeeping: append the live record inventory so the narrative
        # claim ("records are maintained in Trazo…") is backed by verifiable counts.
        if key == "recordkeeping_description":
            try:
                inventory = _record_inventory(osp.establishment)
            except Exception:
                inventory = []
            if inventory:
                story.append(Spacer(1, 0.05 * inch))
                # Counted when the packet is built, which on a filed plan is after the filing: the
                # plan text above is as submitted, these counts are not. Saying so is what keeps the
                # "snapshot" claim true (a February plan printed August records unlabelled).
                story.append(
                    Paragraph(
                        f"<b>Record inventory as of {date.today().isoformat()}, counted from the "
                        "operation's records (including records made after the plan was submitted):</b>",
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
    # Only the certifying agent approves an input. "Approved Inputs — requested scope" read as the
    # operator granting what it is asking for.
    story.append(
        Paragraph(
            "<b>Inputs on this plan, for the certifying agent's review (§ 205.201(a)(2))</b>",
            styles["header"],
        )
    )
    story.append(
        Paragraph(
            f"<i>The operation's materials list as it stands on {date.today().isoformat()}"
            + (
                f", which may differ from the narrative filed on {osp.submitted_at.date().isoformat()} above."
                if osp.submitted_at
                else "."
            )
            + "</i>",
            styles["meta"],
        )
    )
    # 🔴 2026-09-07 — this block read `approved_omri_products` and
    # `approved_national_list_substances` and NOTHING ELSE. `approved_wsda_materials` and the
    # operator-entered `plan_material_entries` were dropped silently, in the one artifact the
    # certifier actually receives and the operator cannot correct: post-submission edits are
    # refused (`views.py` `_APPROVED_INPUTS_EDITABLE_STATUSES`), and the footer below calls this
    # "the exact content submitted".
    #
    # The failure was not cosmetic. A plan whose materials are WSDA-listed or operator-entered —
    # the compost / manure / gypsum / limestone case CCOF NOPB41 §A asks for by name, which no
    # catalog can supply — printed "No structured inputs attached to this OSP" three inches below
    # a § 205.201(a)(2) narrative listing every one of them, because the narrative compiler reads
    # `plan_materials()` and this renderer did not. One document, two answers.
    #
    # `plan_materials()` was written to end exactly this ("reading two of the three is the bug
    # this function exists to make impossible to repeat"); the fix that landed in
    # `osp_module_pdf` on 2026-08-28 was never carried across to the higher-stakes builder.
    from certifications.services.plan_materials import plan_materials

    rows = plan_materials(osp)
    if not rows:
        story.append(
            Paragraph(
                "<i>No structured inputs attached to this OSP. The narrative in "
                "§ 205.201(a)(2) above describes the intended inputs; the certifier "
                "is expected to enumerate approvals in their response.</i>",
                styles["meta"],
            )
        )
    else:
        # Grouped FROM THE ROWS, never from a literal list of source names — a hardcoded tuple
        # is how the fourth source would disappear the day a fifth one ships. Known sources keep
        # their reading order; anything new appears rather than vanishing.
        known = ("National List", "OMRI", "WSDA", "Operator-entered")
        seen = list(dict.fromkeys(r.source for r in rows))
        for source in [s for s in known if s in seen] + [s for s in seen if s not in known]:
            group = sorted((r for r in rows if r.source == source), key=lambda r: r.name.lower())
            if not group:
                continue
            story.append(Paragraph(f"<b>{_escape(source)}</b>", styles["body"]))
            for row in group:
                # `display()` is the ONE author of a material's line — name, manufacturer, the
                # identifier its registry actually publishes, and the [REVIEW] qualifier on a
                # § 205.602 row. Reassembling it here would be a second author for the sentence
                # a certifier reads. `stated_absences` is the certifier-facing form: a missing
                # manufacturer or reason is said to be missing, never left as a silent gap.
                story.append(Paragraph(f"• {_escape(row.display(stated_absences=True))}", styles["body"]))
            story.append(Spacer(1, 0.05 * inch))

    # Footer note.
    story.append(Spacer(1, 0.2 * inch))
    story.append(
        Paragraph(
            "The plan text in this document is as submitted. The live plan may be edited in later "
            "versions; this document keeps the submitted text. The record inventory is counted when "
            "the document is generated. Source: 7 CFR 205.201 (eCFR).",
            styles["meta"],
        )
    )

    _furniture = specimen_page_callback(letter, specimen=is_specimen(getattr(osp, "establishment", None)))
    doc.build(story, onFirstPage=_furniture, onLaterPages=_furniture)
    return buffer.getvalue()
