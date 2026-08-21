"""
Per-module OSP PDFs + the renewal packet ZIP (WS-2.5/2.6, plan Appendix A §g).

`generate_module_pdf(osp, module_key, parcel=None)` — one lettered module as a
certifier-readable PDF: header card (title, code, citations, version), the N/A
attestation when set, otherwise verbatim question/answer pairs for the visible
branch only (hidden branches never print — same rule as the compiler). For the
per-parcel module pass `parcel`; answers come from live model state via
`parcel_application_values`, never from module_responses.

`generate_osp_packet(osp)` — ZIP with cover PDF, the six-section narrative
snapshot, every farm-wide module PDF, one Parcel Application PDF per parcel,
and the four Common OSP workbooks. THIS function is the packet's single source
of content — the view files its bytes into the DMS and streams them; nothing
else assembles packet content.

Header color #2E7D32 (green.700) — the AA-safe PDF header standard.
"""

from __future__ import annotations

import io
import xml.sax.saxutils
import zipfile
from datetime import date

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from certifications.osp_modules import CONTENT_VERSION, MODULE_REGISTRY

_REGISTRY_BY_KEY = {module.key: module for module in MODULE_REGISTRY}
from certifications.osp_modules.conditions import answer_value, visible_questions
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.common_osp_workbooks import WORKBOOKS, build_workbook
from certifications.services.osp_module_compiler import _format_answer_en
from certifications.services.osp_pdf_snapshot import _styles, generate_osp_snapshot_pdf


def _escape(value: str) -> str:
    return xml.sax.saxutils.escape(str(value))


def _en(textmap) -> str:
    if isinstance(textmap, dict):
        return textmap.get("en", "")
    return str(textmap or "")


def _module_for_key(module_key: str):
    if module_key == PARCEL_APPLICATION.key:
        return PARCEL_APPLICATION
    module = _REGISTRY_BY_KEY.get(module_key)
    if module is None:
        raise ValueError(f"Unknown OSP module: {module_key!r}")
    return module


def _module_entry(osp, module_key: str) -> dict:
    # module_responses is an ENVELOPE: {"schema_version", "modules": {...},
    # "parcel_modules": {...}} — entries live under "modules" (WS-2.2 PUT shape).
    return ((osp.module_responses or {}).get("modules") or {}).get(module_key) or {}


def _record_registry_flowables(osp, styles) -> list:
    """Render the Common OSP § 11 record-type registry for the module PDF.

    Only rows the operator has CONFIRMED are listed. A derived row that Trazo can evidence
    but nobody has confirmed is a suggestion, not a statement by the producer
    (§ 205.201(a)) — printing it on a certifier-facing document would be exactly the
    tool-manufactured attestation this codebase refuses to make. Unconfirmed rows are
    summarised as a count so the certifier can see the plan is still in progress.
    """
    from certifications.services.common_osp_records import derive_record_types

    try:
        rows = derive_record_types(osp.establishment, osp=osp)
    except Exception:  # noqa: BLE001 — a registry failure must not sink the whole packet
        return []

    confirmed = [r for r in rows if r.get("confirmed")]
    if not confirmed:
        return [
            Paragraph(
                "No record types have been confirmed in the Common OSP § 11 registry yet.",
                styles["body"],
            ),
            Spacer(1, 6),
        ]

    out = [
        Paragraph(
            "<b>Record types confirmed by the operator (Common OSP § 11)</b>",
            styles["body"],
        )
    ]
    by_group: dict = {}
    for row in confirmed:
        by_group.setdefault(row.get("group") or "", []).append(row)

    for group, group_rows in by_group.items():
        if group:
            out.append(Paragraph(_escape(group), styles["meta"]))
        for row in group_rows:
            label = _escape(row.get("label") or row.get("key") or "")
            cite = _escape(row.get("cfr_cite") or "")
            basis = _escape(row.get("basis") or "")
            detail = f" — {basis}" if basis else ""
            cite_txt = f" ({cite})" if cite else ""
            out.append(Paragraph(f"• {label}{cite_txt}{detail}", styles["body"]))
        out.append(Spacer(1, 4))

    remaining = len(rows) - len(confirmed)
    if remaining:
        out.append(
            Paragraph(
                _escape(
                    f"{remaining} further record type(s) in the § 11 registry have not been "
                    "confirmed by the operator."
                ),
                styles["meta"],
            )
        )
    out.append(Spacer(1, 6))
    return out


def _approved_inputs_flowables(osp, styles) -> list:
    """Render the OSP's approved input materials for the Materials Application PDF.

    The module attests five times that materials are entered "in this list" / "in the
    materials list above" — and the list itself is an `embed`, which the renderer skipped,
    so the certifier read five attestations pointing at nothing. Same defect as G8.0's
    "records confirmed above" and the Parcel Application's missing § 205.202 evidence.

    Note this is the OSP's approved-inputs panel, which is a different source from the
    Materials List workbook (built from logged application events). A material approved
    here but never applied appears in one and not the other, and vice versa — worth
    knowing when the two are read side by side.
    """
    substances = list(osp.approved_national_list_substances.all())
    products = list(osp.approved_omri_products.all())
    if not substances and not products:
        return [
            Paragraph(
                "No input materials have been added to the approved list for this plan.",
                styles["body"],
            ),
            Spacer(1, 6),
        ]

    out = [Paragraph("<b>Approved input materials on this plan</b>", styles["body"])]
    if substances:
        out.append(Paragraph("National List substances", styles["meta"]))
        for item in substances:
            out.append(Paragraph(f"• {_escape(str(item))}", styles["body"]))
    if products:
        out.append(Paragraph("Listed products (OMRI / WSDA)", styles["meta"]))
        for item in products:
            out.append(Paragraph(f"• {_escape(str(item))}", styles["body"]))
    out.append(Spacer(1, 6))
    return out


def _parcel_embed_flowables(embed: str, parcel, styles) -> list:
    """Render the Parcel Application's embedded § 205.202 evidence.

    Sections D (buffers), E (map) and F (land history) are `info` questions carrying an
    embed, and `info` questions used to be skipped by this renderer — so a Parcel
    Application PDF stamped "complete" reached the certifier showing only the parcel name,
    APN and address. Everything that actually proves land eligibility was missing from the
    one document whose entire job is to prove it.
    """
    out: list = []

    if embed == "transition_card":
        from product.services.transition_status_service import compute_transition_status

        try:
            status = compute_transition_status(parcel)
        except Exception:  # noqa: BLE001
            return []
        if status.last_prohibited_date:
            out.append(
                Paragraph(
                    _escape(f"Last prohibited substance applied: {status.last_prohibited_date.isoformat()}"),
                    styles["body"],
                )
            )
        if status.transition_complete_date:
            out.append(
                Paragraph(
                    _escape(f"36-month transition complete: {status.transition_complete_date.isoformat()}"),
                    styles["body"],
                )
            )
        out.append(
            Paragraph(
                _escape(f"Eligible for organic harvest: {'Yes' if status.is_eligible else 'Not yet'}"),
                styles["body"],
            )
        )
        if status.note:
            out.append(Paragraph(_escape(status.note), styles["meta"]))

    elif embed == "buffer_editor":
        rows = parcel.buffer_zones or []
        if not rows:
            out.append(Paragraph("No buffer or adjoining-land records on file.", styles["body"]))
        for row in rows:
            if not isinstance(row, dict):
                continue
            head = _escape(f"{row.get('direction') or '—'}: {row.get('adjoining_land_use') or '—'}")
            out.append(Paragraph(f"<b>{head}</b>", styles["body"]))
            bits = []
            width_ft = row.get("buffer_width_ft")
            if width_ft is not None:
                bits.append(f"buffer width {width_ft} ft")
            if row.get("buffer_type"):
                bits.append(f"type: {row['buffer_type']}")
            if row.get("adjacent_is_organic") is True:
                bits.append("adjoining land is certified organic — no buffer required")
            if row.get("crop_grown_in_buffer"):
                bits.append(f"crop in buffer (never sold as organic): {row['crop_grown_in_buffer']}")
            if row.get("prohibited_use_last_date"):
                bits.append(f"adjoining land last received a prohibited material {row['prohibited_use_last_date']}")
            if row.get("drift_risk"):
                bits.append(f"drift risk: {row['drift_risk']}")
            if row.get("neighbor_notified") is True:
                when = row.get("neighbor_notification_date") or ""
                bits.append(f"neighbour notified{(' ' + when) if when else ''}")
            if bits:
                out.append(Paragraph(_escape("; ".join(bits) + "."), styles["body"]))
            if row.get("prevention"):
                out.append(Paragraph(_escape(str(row["prevention"])), styles["body"]))
            out.append(Spacer(1, 4))

    elif embed == "parcel_map":
        has_map = bool(parcel.polygon)
        area = getattr(parcel, "area", None)
        line = "Field map on file (boundary recorded in Trazo)." if has_map else "No field map on file."
        out.append(Paragraph(_escape(line), styles["body"]))
        if area:
            # 🔴 2026-08-20 — printed `parcel.area` (HECTARES) with the word "acres" beside it.
            # This is the § 205.202 page a certifier works from, so a WSDA reviewer read a
            # 28.4-acre Honeycrisp block as 11.49 acres and would have issued a certificate
            # (and a fee) for 24.0 acres against a 59.4-acre operation. The workbook on the
            # facing page had the right numbers, which is what made it findable.
            out.append(Paragraph(_escape(f"Mapped area: {parcel.area_display()}."), styles["body"]))

    elif embed == "crop_history":
        history = sorted(parcel.crop_history.all(), key=lambda h: h.year, reverse=True)
        if not history:
            out.append(Paragraph("No crop history recorded for this parcel.", styles["body"]))
        for row in history:
            bits = [str(row.year), row.crop_grown or "—"]
            if getattr(row, "cover_crop", ""):
                bits.append(f"cover crop: {row.cover_crop}")
            if getattr(row, "last_prohibited_substance", ""):
                when = getattr(row, "date_last_prohibited", None)
                bits.append(
                    f"last prohibited input: {row.last_prohibited_substance}"
                    + (f" ({when.isoformat()})" if when else "")
                )
            out.append(Paragraph(_escape(" · ".join(bits)), styles["body"]))

    elif embed == "landowner_affidavit":
        count = parcel.landowner_affidavits.count()
        line = (
            f"{count} landowner affidavit(s) on file." if count else "No landowner affidavit on file for this parcel."
        )
        out.append(Paragraph(_escape(line), styles["body"]))

    if out:
        out.append(Spacer(1, 6))
    return out


def generate_module_pdf(osp, module_key: str, parcel=None) -> bytes:
    """Render one module (or one parcel's application) as a PDF. Returns bytes."""
    module = _module_for_key(module_key)

    if module.repeat_per_parcel:
        if parcel is None:
            raise ValueError(f"Module {module_key!r} repeats per parcel — a parcel is required")
        from product.services.parcel_application_status import parcel_application_status, parcel_application_values

        raw_values = parcel_application_values(parcel)
        answers = {k: {"value": v} for k, v in raw_values.items() if v not in (None, "")}
        entry = {"status_line": f"Live completion: {parcel_application_status(parcel)['state']}"}
        not_applicable = False
        na_attestation = None
        definition_version = CONTENT_VERSION
    else:
        entry = _module_entry(osp, module_key)
        answers = entry.get("answers") or {}
        not_applicable = bool(entry.get("not_applicable"))
        na_attestation = entry.get("na_attestation")
        definition_version = entry.get("definition_version") or CONTENT_VERSION

    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        title=f"OSP Module — {_en(module.title)}",
    )
    story = []

    heading = _en(module.title)
    if module.code:
        heading = f"{module.code} — {heading}"
    story.append(Paragraph(_escape(heading), styles["title"]))
    subtitle_bits = [", ".join(module.nop_cites), f"OSP v{osp.version_number}"]
    if parcel is not None:
        subtitle_bits.append(f"Parcel: {parcel.name}")
    story.append(Paragraph(_escape(" · ".join(subtitle_bits)), styles["subtitle"]))
    establishment = osp.establishment
    story.append(
        Paragraph(
            _escape(f"{establishment.name} — generated {date.today().isoformat()}"),
            styles["meta"],
        )
    )
    if entry.get("status_line"):
        story.append(Paragraph(_escape(entry["status_line"]), styles["meta"]))
    story.append(Spacer(1, 12))

    if not_applicable:
        stamp = ""
        if isinstance(na_attestation, dict):
            who = na_attestation.get("by") or ""
            when = na_attestation.get("at") or ""
            stamp = f" (attested by {who} on {when})" if who or when else ""
        na_text = _en(module.na_label) or "Reviewed — does not apply to this operation."
        story.append(Paragraph(_escape(f"Not applicable{stamp}: {na_text}"), styles["body"]))
    else:
        pairs = visible_questions(module, answers)
        answered_any = False
        current_page_key = None
        for page, question in pairs:
            # Embedded panels (§ 11 registry, approved inputs, the Parcel Application's
            # § 205.202 evidence) carry no `answers` value — they render from live records.
            # They were skipped wholesale until 2026-08-09, which left modules attesting to
            # "the records confirmed above" and "the materials list above" with nothing
            # above. ONE dispatch point: `test_every_embed_has_a_renderer` fails if a new
            # embed lands without a branch here.
            if question.embed:
                if parcel is not None:
                    rendered = _parcel_embed_flowables(question.embed, parcel, styles)
                elif question.embed == "s11_record_types":
                    rendered = _record_registry_flowables(osp, styles)
                elif question.embed == "approved_inputs":
                    rendered = _approved_inputs_flowables(osp, styles)
                else:
                    rendered = []
                if rendered:
                    if page.key != current_page_key:
                        current_page_key = page.key
                        story.append(Paragraph(_escape(_en(page.title)), styles["header"]))
                    answered_any = True
                    story.extend(rendered)
                continue
            if question.kind in ("info", "upload"):
                continue
            # 🔴 2026-08-20 — was `(answers.get(key) or {}).get("value")`, which assumes the
            # ENVELOPE shape `{"value": ..., "at": ...}` the REST write path stores
            # (certifications/views.py). The module wizard stores the BARE value, so a module
            # a farmer actually answered raised
            #     AttributeError: 'list' object has no attribute 'get'
            # and took down the whole OSP packet ZIP with it — the artifact a grower downloads
            # for the § 205.406 renewal, plus every per-module PDF and the parcel application.
            #
            # `answer_value` is the accessor that already exists for exactly this ("tolerating
            # both envelope and bare shapes"); the compiler and the visibility evaluator both
            # use it. This was the one reader that did not.
            value = answer_value(answers, question.key)
            if value in (None, "", []):
                continue
            if page.key != current_page_key:
                current_page_key = page.key
                story.append(Paragraph(_escape(_en(page.title)), styles["header"]))
            answered_any = True
            story.append(Paragraph(f"<b>{_escape(_en(question.label))}</b>", styles["body"]))
            story.append(Paragraph(_escape(_format_answer_en(question, value)), styles["body"]))
            story.append(Spacer(1, 6))
        if not answered_any:
            story.append(Paragraph("No answers recorded for this module yet.", styles["body"]))

    story.append(Spacer(1, 18))
    story.append(
        Paragraph(
            _escape(f"Definition version {definition_version} — generated by Trazo"),
            styles["meta"],
        )
    )
    doc.build(story)
    return buffer.getvalue()


def _packet_cover_pdf(osp) -> bytes:
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="OSP Packet")
    story = [
        Paragraph("Organic System Plan — Renewal Packet", styles["title"]),
        Paragraph(
            _escape(f"{osp.establishment.name} · OSP v{osp.version_number} · {date.today().isoformat()}"),
            styles["subtitle"],
        ),
        Spacer(1, 10),
        Paragraph("Contents", styles["header"]),
        Paragraph("1. Six-section narrative snapshot (7 CFR 205.201(a))", styles["body"]),
        Paragraph("2. One PDF per guided module, N/A attestations included", styles["body"]),
        Paragraph("3. One Parcel Application per parcel (§ 205.202)", styles["body"]),
        Paragraph("4. Common OSP workbooks (field/crop, product list, materials, suppliers)", styles["body"]),
        Spacer(1, 14),
        Paragraph(
            "Every document is generated from the operation's live records. "
            "Workbook cells the operation has not recorded remain blank for the operator to complete.",
            styles["meta"],
        ),
    ]
    doc.build(story)
    return buffer.getvalue()


def generate_osp_packet(osp) -> bytes:
    """Assemble the renewal packet ZIP. Single source of packet content."""
    establishment = osp.establishment
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00-cover.pdf", _packet_cover_pdf(osp))
        zf.writestr("01-narrative-snapshot.pdf", generate_osp_snapshot_pdf(osp))
        for module in MODULE_REGISTRY:
            code = (module.code or module.key).replace(".", "_")
            zf.writestr(
                f"modules/{code}.pdf",
                generate_module_pdf(osp, module.key),
            )
        for parcel in establishment.parcels.all():
            safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in parcel.name).strip()
            zf.writestr(
                f"parcels/parcel-application-{safe or parcel.id}.pdf",
                generate_module_pdf(osp, PARCEL_APPLICATION.key, parcel=parcel),
            )
        for spec in WORKBOOKS:
            workbook = build_workbook(establishment, spec.key)
            zf.writestr(f"workbooks/{spec.key}.xlsx", workbook.getvalue())
    return out.getvalue()
