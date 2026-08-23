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
from common.pdf_text import glyph_safe
from common.specimen import is_specimen, specimen_page_callback

_REGISTRY_BY_KEY = {module.key: module for module in MODULE_REGISTRY}
from certifications.osp_modules.conditions import answer_value, visible_questions
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.common_osp_workbooks import WORKBOOKS, build_workbook
from certifications.services.osp_module_compiler import _format_answer_en
from certifications.services.osp_pdf_snapshot import _styles, generate_osp_snapshot_pdf


def _notice_when(n) -> str:
    """A notice's date for print. `date_notified` is nullable (blank is allowed on a § 205.400(f)(2)
    notice), so fall back to the day it was recorded and say so — never `None.isoformat()`."""
    if n.date_notified:
        return n.date_notified.isoformat()
    return f"{n.created_at.date().isoformat()} (recorded)" if n.created_at else "undated"


def _escape(value: str) -> str:
    return xml.sax.saxutils.escape(glyph_safe(value))


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
        # Typed years AND years derived from the seasons logged on this parcel — see
        # product/services/land_history.py for why reading only the typed table left the two
        # most recent (and best documented) years off a renewal's § 205.202(b) page.
        from product.services.land_history import land_history_rows

        # Unbounded on purpose. The Parcel Application is a LIVE document — its buffer rows,
        # map and identity render from current parcel state ("Live completion"), so capping
        # the derived years at the plan's filing date would make one page tell two dates. The
        # per-production packet, which IS a document of record for one season, caps its own
        # field-history table at that season's year.
        history = land_history_rows(parcel)
        if not history:
            out.append(Paragraph("No crop history recorded for this parcel.", styles["body"]))
        for row in history:
            crop = row.crop_grown or "—"
            if row.block_id:
                crop = f"{crop} ({row.block_id})"
            bits = [str(row.year), crop]
            if row.production_method_display:
                bits.append(row.production_method_display.lower())
            if row.cover_crop:
                bits.append(f"cover crop: {row.cover_crop}")
            if row.substances_applied and row.is_derived:
                bits.append(f"inputs applied: {row.substances_applied}")
            if row.last_prohibited_substance:
                when = row.date_last_prohibited
                bits.append(
                    f"last prohibited input: {row.last_prohibited_substance}"
                    + (f" ({when.isoformat()})" if when else "")
                )
            if row.is_derived:
                bits.append("from season records")
            out.append(Paragraph(_escape(" · ".join(bits)), styles["body"]))
        if any(r.is_derived for r in history):
            out.append(
                Paragraph(
                    _escape(
                        "Years marked “from season records” are compiled from the productions and "
                        "inputs logged on this parcel in Trazo; years without that mark were entered "
                        "by the operator as land-use history."
                    ),
                    styles["meta"],
                )
            )

    elif embed == "landowner_affidavit":
        count = parcel.landowner_affidavits.count()
        line = (
            f"{count} landowner affidavit(s) on file." if count else "No landowner affidavit on file for this parcel."
        )
        out.append(Paragraph(_escape(line), styles["body"]))

    elif embed == "adjoining_land_affidavit":
        rows = list(parcel.adjoining_land_affidavits.all().order_by("border_side", "id"))
        if not rows:
            out.append(Paragraph("No adjoining-land affidavit on file for this parcel.", styles["body"]))
        for a in rows:
            signed = a.neighbor_signed_date.isoformat() if a.neighbor_signed_date else "unsigned"
            side = a.get_border_side_display() if a.border_side else "—"
            out.append(
                Paragraph(
                    _escape(
                        f"{side}: {a.neighbor_name}"
                        + (f" ({a.neighbor_farm_name})" if a.neighbor_farm_name else "")
                        + f" — signed {signed}"
                        + (
                            f"; materials: {a.materials_display()}"
                            if hasattr(a, "materials_display") and a.materials_display()
                            else ""
                        )
                        + ("; agrees to notify before application" if a.agrees_to_notify else "")
                    ),
                    styles["body"],
                )
            )

    elif embed == "parcel_change_notifications":
        from certifications.models import OSPChangeNotification

        notices = list(
            OSPChangeNotification.objects.filter(parcel=parcel).select_related("osp").order_by("date_notified", "id")
        )
        if not notices:
            out.append(Paragraph("No change notification names this parcel.", styles["body"]))
        for n in notices:
            out.append(
                Paragraph(
                    f"<b>{_escape(_notice_when(n))}</b> — {_escape(n.get_change_category_display())}",
                    styles["body"],
                )
            )
            if n.description:
                out.append(Paragraph(_escape(n.description), styles["body"]))
            out.append(
                Paragraph(
                    _escape(
                        ("Acknowledged " + n.certifier_acknowledged_at.isoformat())
                        if n.certifier_acknowledged_at
                        else "Not yet acknowledged by the certifier"
                    )
                    + _escape(f" · filed against plan v{n.osp.version_number}"),
                    styles["meta"],
                )
            )
        if notices:
            out.append(
                Paragraph(
                    "A notice records what the certifier was told. The buffer, land-history and "
                    "identity rows on this application are the operation's current description — "
                    "they must say the same thing.",
                    styles["meta"],
                )
            )

    elif embed == "contamination_incidents":
        from history.models import GeneralEvent

        incidents = list(
            GeneralEvent.objects.filter(history__parcel=parcel, is_contamination_incident=True)
            .select_related("history")
            .order_by("date")
        )
        if not incidents:
            out.append(Paragraph("No contamination incident is recorded on this parcel.", styles["body"]))
        for e in incidents:
            source = (e.contamination_source or "").replace("_", " ") or "unspecified"
            head = f"{e.date.date().isoformat()} — {source}"
            if e.contamination_affected_area:
                head += f" — {float(e.contamination_affected_area):g} ac affected"
            out.append(Paragraph(f"<b>{_escape(head)}</b>", styles["body"]))
            if e.description:
                out.append(Paragraph(_escape(e.description), styles["body"]))
            bits = []
            if e.corrective_action_taken:
                bits.append(
                    "Corrective action"
                    + (f" ({e.corrective_action_date.isoformat()})" if e.corrective_action_date else "")
                    + f": {e.corrective_action_taken}"
                )
            if e.certifier_notified:
                bits.append(
                    "Certifier notified"
                    + (f" {e.certifier_notification_date.isoformat()}" if e.certifier_notification_date else "")
                )
            else:
                bits.append("Certifier notification not recorded — § 205.400(f)(1) requires it immediately")
            for b in bits:
                out.append(Paragraph(_escape(b), styles["meta"]))

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
    # Same authority as the audit packet (common/specimen.py). An OSP is the § 205.201
    # plan a certifier approves; a fabricated one must not read as an approved plan.
    doc.build(
        story,
        onFirstPage=specimen_page_callback(letter, specimen=is_specimen(getattr(osp, "establishment", None))),
        onLaterPages=specimen_page_callback(letter, specimen=is_specimen(getattr(osp, "establishment", None))),
    )
    return buffer.getvalue()


def _renewal_context(osp) -> dict:
    """The facts a renewal cover is read for, gathered once for the cover and the filing PDF.

    * the § 205.406 filing this packet carries — the annual update whose `new_osp` is this
      plan (a renewal that produced a new version), else the one whose `prior_osp` is this plan
      (a reaffirmation), else nothing;
    * the NOP certificate and certifier on file;
    * the § 205.401(b) responsible person and address.
    """
    from certifications.models import Certification, OSPAnnualUpdate

    est = osp.establishment
    filing = (
        OSPAnnualUpdate.objects.filter(new_osp=osp).order_by("-reporting_year", "-submitted_at").first()
        or OSPAnnualUpdate.objects.filter(prior_osp=osp).order_by("-reporting_year", "-submitted_at").first()
    )
    # The ACTIVE NOP certificate, newest first. Without the `is_active` filter a revoked or
    # expired certificate with a later effective date would print as the operation's
    # certificate on the renewal cover. `is_active` is a property (it reads today's date), so
    # the filter runs in Python over the few rows an operation has.
    nop_certs = sorted(
        Certification.objects.filter(establishment=est, certification_type__in=("usda_organic", "ccof")),
        key=lambda c: (c.effective_date or date.min),
        reverse=True,
    )
    cert = next((c for c in nop_certs if c.is_active), None) or (nop_certs[0] if nop_certs else None)
    company = getattr(est, "company", None)
    # § 205.401(b): "the name of the person completing the application". The farm profile's
    # contact person is that name when it is filled; the plan's author is the fallback, and an
    # email address is the last resort — it is never the name a certifier files.
    responsible = (getattr(est, "contact_person", None) or "").strip()
    created_by = getattr(osp, "created_by", None)
    if not responsible and created_by is not None:
        responsible = (created_by.get_full_name() or "").strip() or (created_by.email or "")
    address_bits = [
        getattr(est, "address", None),
        getattr(est, "city", None),
        getattr(est, "state", None),
        getattr(est, "zip_code", None) or getattr(est, "postal_code", None),
    ]
    return {
        "filing": filing,
        "certificate_number": getattr(cert, "certification_number", "") or "",
        "certifier_name": getattr(cert, "certifier_name", "") or "",
        "certificate_effective": getattr(cert, "effective_date", None),
        "legal_name": getattr(company, "name", "") or "",
        "responsible_person": responsible,
        "responsible_person_is_named": bool((getattr(est, "contact_person", None) or "").strip()),
        "address": ", ".join(str(b).strip() for b in address_bits if b),
        "phone": getattr(est, "phone", None)
        or getattr(est, "contact_phone", None)
        or getattr(company, "contact_phone", None)
        or "",
    }


def _packet_cover_pdf(osp) -> bytes:
    """The cover a certifier reads first.

    Was four lines — name, version, today's date, a contents list — which is a cover for a
    document set, not for a renewal. A renewal cover is read for WHICH operation (certificate
    number, certifier, the § 205.401(b) responsible person), WHICH year it continues, and WHAT
    changed; none of that was on it, and the § 205.406 filing the packet exists to carry was not
    in the packet at all. It also now carries the plan review — the list of things the
    operation's own records did after the plan's answers were written — because that is the
    one page where the operator will see it before the packet leaves.
    """
    from certifications.services.plan_review import plan_review

    styles = _styles()
    ctx = _renewal_context(osp)
    filing = ctx["filing"]
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="OSP Packet")

    def kv(label, value):
        return Paragraph(f"<b>{_escape(label)}:</b> {_escape(str(value))}", styles["body"])

    year_line = f"Continuation for {filing.reporting_year}" if filing else "Continuation year not filed"
    story = [
        Paragraph("Organic System Plan — Renewal Packet", styles["title"]),
        Paragraph(
            _escape(f"{osp.establishment.name} · OSP v{osp.version_number} · {year_line}"),
            styles["subtitle"],
        ),
        Spacer(1, 8),
        Paragraph("Operation (7 CFR 205.401(b))", styles["header"]),
        kv("Legal name", ctx["legal_name"] or "—"),
        kv("Operation", osp.establishment.name),
        kv("Responsible person", ctx["responsible_person"] or "—"),
    ]
    if not ctx["responsible_person_is_named"]:
        story.append(
            Paragraph(
                "The operation has no contact person on its farm profile. § 205.401(b) asks for the "
                "responsible person by name — set it before this packet is sent.",
                styles["meta"],
            )
        )
    story += [
        kv("Address", ctx["address"] or "—"),
        kv("Phone", ctx["phone"] or "—"),
        kv(
            "Certificate",
            f"{ctx['certificate_number'] or '—'}" + (f" — {ctx['certifier_name']}" if ctx["certifier_name"] else ""),
        ),
        kv("Plan submitted", osp.submitted_at.date().isoformat() if osp.submitted_at else "not yet submitted"),
        kv("Packet generated", date.today().isoformat()),
        Spacer(1, 8),
        Paragraph("Continuation of certification (7 CFR 205.406)", styles["header"]),
    ]
    if filing:
        story += [
            kv("Reporting year", filing.reporting_year),
            kv("Filed", filing.submitted_at.date().isoformat() if filing.submitted_at else "draft — not yet filed"),
            kv(
                "Plan version",
                (
                    f"v{filing.prior_osp.version_number} to v{filing.new_osp.version_number}"
                    if filing.new_osp_id
                    else f"v{filing.prior_osp.version_number} reaffirmed"
                ),
            ),
            kv(
                "Changes reported",
                f"{len(filing.additions or [])} addition(s), {len(filing.deletions or [])} deletion(s)",
            ),
            Paragraph(
                "The filing itself — the change summary, additions and deletions — is document 02 in this packet.",
                styles["meta"],
            ),
        ]
    else:
        story.append(
            Paragraph(
                "No annual update is on file for this plan version. § 205.406(a) requires one each year the "
                "operation continues certification; file it before this packet is sent.",
                styles["body"],
            )
        )

    # ---- plan review ---------------------------------------------------------------------
    review = plan_review(osp)
    story += [
        Spacer(1, 8),
        Paragraph("Plan review — what the records did after these answers were written", styles["header"]),
    ]
    if review.answers_as_of:
        story.append(kv("Newest answer in this plan", review.answers_as_of))
    if review.is_clean:
        story.append(Paragraph("No operation changes are recorded after the plan's newest answer.", styles["body"]))
    else:
        for f in review.findings:
            story.append(Paragraph(f"<b>{_escape(f.message)}</b> — {f.count}", styles["body"]))
            for d in f.details[:8]:
                story.append(Paragraph(_escape(f"• {d}"), styles["meta"]))
            if len(f.details) > 8:
                story.append(Paragraph(_escape(f"• … and {len(f.details) - 8} more"), styles["meta"]))
        if review.parcels_not_named:
            story.append(
                Paragraph(
                    "<b>Parcels this plan never names</b> — " + _escape(", ".join(review.parcels_not_named)),
                    styles["body"],
                )
            )
        if review.stale_modules:
            story.append(Paragraph("<b>Modules not revisited in the last year</b>", styles["body"]))
            for m in review.stale_modules:
                story.append(
                    Paragraph(
                        _escape(
                            f"• {m['module']} — last answered {m['answered_at']} ({m['days_before_submission']} days before submission)"
                        ),
                        styles["meta"],
                    )
                )
        story.append(
            Paragraph(
                "This list is compiled from dated records and names no conclusion: each item is something to "
                "confirm is still described correctly in the plan, or to add to the change summary.",
                styles["meta"],
            )
        )

    story += [
        Spacer(1, 10),
        Paragraph("Contents", styles["header"]),
        Paragraph("00. This cover", styles["body"]),
        Paragraph("01. Six-section narrative snapshot (7 CFR 205.201(a))", styles["body"]),
        Paragraph("02. Annual update — the § 205.406(a) filing", styles["body"]),
        Paragraph("03. § 205.400(f) change notifications filed against this plan lineage", styles["body"]),
        Paragraph("modules/ — one PDF per guided module, N/A attestations included", styles["body"]),
        Paragraph("parcels/ — one Parcel Application per parcel (§ 205.202)", styles["body"]),
        Paragraph("workbooks/ — Common OSP workbooks (field/crop, product list, materials, suppliers)", styles["body"]),
        Spacer(1, 14),
        Paragraph(
            "Every document is generated from the operation's live records. "
            "Workbook cells the operation has not recorded remain blank for the operator to complete.",
            styles["meta"],
        ),
    ]
    # Same authority as the audit packet (common/specimen.py). An OSP is the § 205.201
    # plan a certifier approves; a fabricated one must not read as an approved plan.
    doc.build(
        story,
        onFirstPage=specimen_page_callback(letter, specimen=is_specimen(getattr(osp, "establishment", None))),
        onLaterPages=specimen_page_callback(letter, specimen=is_specimen(getattr(osp, "establishment", None))),
    )
    return buffer.getvalue()


def _annual_update_pdf(osp) -> bytes:
    """Document 02 — the § 205.406(a) filing, rendered as the certifier would file it."""
    from history.services.audit_export_service import _fmt_change_entries

    styles = _styles()
    ctx = _renewal_context(osp)
    filing = ctx["filing"]
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="Annual Update")
    story = [Paragraph("Annual Update — Continuation of Certification", styles["title"])]
    if filing is None:
        story += [
            Paragraph(_escape(f"{osp.establishment.name} · OSP v{osp.version_number}"), styles["subtitle"]),
            Spacer(1, 10),
            Paragraph(
                "No § 205.406(a) annual update is on file for this plan version. The packet cannot stand "
                "in for the filing: record the year's changes, planned additions and deletions, and file "
                "it before the packet is sent.",
                styles["body"],
            ),
        ]
    else:
        story += [
            Paragraph(
                _escape(
                    f"{osp.establishment.name} · reporting year {filing.reporting_year} · " f"7 CFR 205.406(a)(1)–(3)"
                ),
                styles["subtitle"],
            ),
            Spacer(1, 8),
            Paragraph(
                f"<b>Filed:</b> {_escape(filing.submitted_at.date().isoformat() if filing.submitted_at else 'draft — not yet filed')}",
                styles["body"],
            ),
            Paragraph(
                "<b>Plan version:</b> "
                + _escape(
                    f"v{filing.prior_osp.version_number} to v{filing.new_osp.version_number}"
                    if filing.new_osp_id
                    else f"v{filing.prior_osp.version_number} reaffirmed without a new version"
                ),
                styles["body"],
            ),
        ]
        if filing.certifier_acknowledged_at:
            story.append(
                Paragraph(
                    f"<b>Certifier acknowledged:</b> {filing.certifier_acknowledged_at.date().isoformat()}",
                    styles["body"],
                )
            )
        story += [
            Spacer(1, 10),
            Paragraph("(a)(1) Summary of deviations, changes and modifications to the previous plan", styles["header"]),
            Paragraph(_escape(filing.changes_summary or "—"), styles["body"]),
            Spacer(1, 8),
            Paragraph("(a)(2) Additions planned for the coming year", styles["header"]),
        ]
        # `_fmt_change_entries` renders a LIST into one "; "-joined string (it was written for a
        # table cell). One call per entry keeps each addition on its own bullet here.
        adds = [_fmt_change_entries([a]) for a in (filing.additions or [])]
        adds = [a for a in adds if a]
        story += [Paragraph(_escape(f"• {a}"), styles["body"]) for a in adds] or [
            Paragraph("None stated.", styles["body"])
        ]
        story += [Spacer(1, 8), Paragraph("(a)(2) Deletions planned for the coming year", styles["header"])]
        dels = [_fmt_change_entries([d]) for d in (filing.deletions or [])]
        dels = [d for d in dels if d]
        story += [Paragraph(_escape(f"• {d}"), styles["body"]) for d in dels] or [
            Paragraph("None stated.", styles["body"])
        ]
        att = filing.sections_unchanged_attestation or {}
        if att:
            story += [Spacer(1, 8), Paragraph("Sections attested unchanged since the prior plan", styles["header"])]
            for key, val in sorted(att.items()):
                story.append(
                    Paragraph(
                        _escape(f"• {key.replace('_', ' ')}: {'unchanged' if val else 'changed'}"), styles["body"]
                    )
                )
        story += [
            Spacer(1, 10),
            Paragraph(
                "Producer attestation (7 CFR 205.401(d)): the information above is true, complete and accurate to "
                "the best of my knowledge, and I will notify my certifying agent of any change that may affect "
                "the organic status of the operation (7 CFR 205.400(f)).",
                styles["meta"],
            ),
        ]
    spec = is_specimen(getattr(osp, "establishment", None))
    doc.build(
        story,
        onFirstPage=specimen_page_callback(letter, specimen=spec),
        onLaterPages=specimen_page_callback(letter, specimen=spec),
    )
    return buffer.getvalue()


def _change_notifications_pdf(osp) -> bytes:
    """Document 03 — every § 205.400(f) notice filed against this plan and its previous versions.

    § 205.406(a)(1) asks for the changes "supported by documentation"; these notices ARE the
    documentation, and until now they lived only on the OSP screen.
    """
    from certifications.models import OSPChangeNotification

    styles = _styles()
    lineage, cursor = [], osp
    while cursor is not None and cursor.pk not in lineage:
        lineage.append(cursor.pk)
        cursor = cursor.previous_version
    notices = list(
        OSPChangeNotification.objects.filter(osp_id__in=lineage)
        .select_related("osp", "parcel")
        .order_by("date_notified", "created_at", "id")
    )
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="Change Notifications")
    story = [
        Paragraph("Change Notifications — 7 CFR 205.400(f)", styles["title"]),
        Paragraph(
            _escape(f"{osp.establishment.name} · plan lineage through v{osp.version_number}"), styles["subtitle"]
        ),
        Spacer(1, 8),
    ]
    if not notices:
        story.append(Paragraph("No change notifications are on file for this plan lineage.", styles["body"]))
    for n in notices:
        # The category label already says "(IMMEDIATE)" for § 205.400(f)(1); no second flag.
        story += [
            Paragraph(
                f"<b>{_escape(_notice_when(n))}</b> — {_escape(n.get_change_category_display())}"
                + (f" — {_escape(n.parcel.name)}" if n.parcel_id else ""),
                styles["body"],
            ),
            Paragraph(_escape(n.description or "—"), styles["body"]),
            Paragraph(
                _escape(
                    f"Method: {n.get_method_display()} · Documentation: {n.get_documentation_timing_display()}"
                    + (
                        f" · Acknowledged {n.certifier_acknowledged_at.date().isoformat()}"
                        if n.certifier_acknowledged_at
                        else " · not yet acknowledged"
                    )
                    + (f" · Plan v{n.osp.version_number}" if n.osp_id != osp.pk else "")
                ),
                styles["meta"],
            ),
            Spacer(1, 6),
        ]
    spec = is_specimen(getattr(osp, "establishment", None))
    doc.build(
        story,
        onFirstPage=specimen_page_callback(letter, specimen=spec),
        onLaterPages=specimen_page_callback(letter, specimen=spec),
    )
    return buffer.getvalue()


def generate_osp_packet(osp) -> bytes:
    """Assemble the renewal packet ZIP. Single source of packet content."""
    establishment = osp.establishment
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00-cover.pdf", _packet_cover_pdf(osp))
        zf.writestr("01-narrative-snapshot.pdf", generate_osp_snapshot_pdf(osp))
        # The two documents a renewal IS, and which the "renewal packet" did not contain until
        # 2026-08-23: the § 205.406(a) filing and the § 205.400(f) notices that support it.
        zf.writestr("02-annual-update.pdf", _annual_update_pdf(osp))
        zf.writestr("03-change-notifications.pdf", _change_notifications_pdf(osp))
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
