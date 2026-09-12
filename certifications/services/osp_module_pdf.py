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
import logging
import re
import xml.sax.saxutils
import zipfile
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from certifications.osp_modules import CONTENT_VERSION, MODULE_REGISTRY
from common.pdf_text import glyph_safe
from common.specimen import is_specimen, specimen_page_callback

_REGISTRY_BY_KEY = {module.key: module for module in MODULE_REGISTRY}
from certifications.osp_modules.conditions import answer_value, visible_questions
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.common_osp_workbooks import build_workbook, workbooks_for
from certifications.services.osp_module_compiler import _format_answer_en
from certifications.services.osp_pdf_snapshot import SECTION_LABELS, _styles, generate_osp_snapshot_pdf, signature_block

logger = logging.getLogger(__name__)


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
                # "Section 11 of the USDA Common OSP", never "§ 11": the section sign reads as a CFR
                # citation, and there is no 7 CFR § 11 (WSDA specimen read, 2026-09-11).
                "No record types have been confirmed on the record-types list (USDA Common OSP, section 11) yet.",
                styles["body"],
            ),
            Spacer(1, 6),
        ]

    out = [
        Paragraph(
            "<b>Record types confirmed by the operator (USDA Common OSP, section 11)</b>",
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
            # The operator's own name for a free-text row. Printed AFTER the registry label
            # rather than replacing it, so the line still maps to the form's "Other:" and the
            # certifier can see both what was asked and what was answered.
            custom = _escape(row.get("custom_label") or "")
            if custom:
                label = f"{label}: {custom}"
            cite = _escape(row.get("cfr_cite") or "")
            basis = _escape(row.get("basis") or "")
            detail = f" — {basis}" if basis else ""
            cite_txt = f" ({cite})" if cite else ""
            # WHEN the operator confirmed it, always. A confirmed list with no date reads as
            # current whatever its age, and a renewal clones these answers forward — so a
            # reviewer had no way to tell a statement made for this season from one made two
            # seasons ago. A carried row says so in as many words rather than hiding behind a
            # stale date the reviewer would have to notice on their own.
            when = (row.get("confirmed_at") or "")[:10]
            stamp = f" [confirmed {when}]" if when else ""
            if row.get("carried_from_version"):
                stamp = (
                    f" [confirmed {when}, carried forward from plan v{row['carried_from_version']} "
                    "and not re-stated on this plan]"
                    if when
                    else f" [carried forward from plan v{row['carried_from_version']}]"
                )
            out.append(Paragraph(f"• {label}{cite_txt}{detail}{_escape(stamp)}", styles["body"]))
        out.append(Spacer(1, 4))

    remaining = len(rows) - len(confirmed)
    if remaining:
        out.append(
            Paragraph(
                # What the count IS: the rest of a fixed form list. "Have not been confirmed" read
                # as 25 records the operation failed to keep.
                _escape(
                    f"The list has {remaining} other record {'type' if remaining == 1 else 'types'}; "
                    "only the ones the operator confirmed are listed above."
                ),
                styles["meta"],
            )
        )
    out.append(Spacer(1, 6))
    return out


def _post_harvest_facility_flowables(osp, styles) -> list:
    """Render the operation's off-farm handlers and storage facilities.

    🔴 The largest blocker in the certifier register (6 rows across both certifiers, 2026-08-28).
    `PostHarvestFacility` has always held name, address, facility type, certifier, certificate
    number, effective and expiry dates, and computes a `cert_is_current` tri-state — and no OSP
    module read any of it. So the plan layer answered "who handles or stores your crop" from free
    text while the structured record sat in a different artifact, and the pilot packet named the
    same handler two different ways under one certificate number with nothing comparing them.

    CCOF G6.1 §C and G6.2 §A ask this as a table with the handler's certificate attached; WSDA
    J13 / K1 / L1 gate an entire required section on it, and a "Yes" there declares an attached
    AGR 2519. An unanswered gate is a bounce, not a request for information.

    The certificate line states what the record supports and no more: `cert_is_current` returns
    None when there is no effective date, and that prints as "not stated", never as current.
    """
    facilities = list(osp.establishment.post_harvest_facilities.all()) if osp.establishment_id else []
    if not facilities:
        return [
            Paragraph(
                "No off-farm handler or storage facility is recorded for this operation.",
                styles["body"],
            ),
            Spacer(1, 6),
        ]

    # The heading, and each facility's first line, stay with what follows them: the heading
    # printed alone at a page foot on the specimen (2026-09-11).
    out = [Paragraph("<b>Off-farm handlers and storage facilities</b>", _sticks_to_next(_style(styles, "body")))]
    for facility in facilities:
        where = ", ".join(x for x in (facility.address, facility.city, facility.state) if x)
        role = facility.get_role_display() if facility.role else ""
        head = f"{facility.name} — {facility.get_facility_type_display()}" + (f" ({role})" if role else "")
        out.append(Paragraph(f"• {_escape(head)}", _sticks_to_next(_style(styles, "body"))))
        if where:
            out.append(Paragraph(_escape(where), styles["meta"]))

        current = facility.cert_is_current
        if facility.certification_number or facility.certifier_name:
            cert = " ".join(
                x
                for x in (
                    facility.certifier_name or "",
                    f"#{facility.certification_number}" if facility.certification_number else "",
                )
                if x
            )
            if current is True:
                state = "certificate current"
            elif current is False:
                state = "[REVIEW] certificate expired or older than 15 months"
            else:
                state = "[REVIEW] certificate date not stated"
            dates = ""
            if facility.effective_date:
                dates = f", effective {facility.effective_date.isoformat()}"
                if facility.expiry_date:
                    dates += f", expires {facility.expiry_date.isoformat()}"
            out.append(Paragraph(_escape(f"Organic certificate: {cert}{dates} — {state}"), styles["meta"]))
        else:
            out.append(
                Paragraph(
                    "[REVIEW] No organic certificate is on file for this facility. If it is a "
                    "certified operation, record its certificate; if it is not certified, the "
                    "records preserving your product's organic identity must be described.",
                    styles["meta"],
                )
            )
        if not facility.cert_document:
            out.append(
                Paragraph(
                    "A copy of the certificate is not embedded in this document.",
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
    from certifications.osp_modules.conditions import answer_value
    from certifications.services.plan_materials import (
        none_used_contradictions,
        plan_materials,
        post_harvest_listing_review,
    )

    answers = _module_entry(osp, "materials_application").get("answers") or {}
    rows = plan_materials(osp)
    if not rows:
        # 2026-09-09 — an operation with genuinely no inputs printed "No input materials have
        # been added…", which reads as an UNFINISHED list (OTCO C11 Hdr-2, CCOF NOPB41 Header C).
        # The operator's own statement, when made, replaces it; an absence stays an absence.
        if answer_value(answers, "no_materials_used") is True:
            out = [
                Paragraph(
                    "The operator states that no input materials or substances are used in the organic system.",
                    styles["body"],
                )
            ]
            for line in none_used_contradictions(osp, answers):
                out.append(Paragraph(_escape(line), styles["meta"]))
            out.append(Spacer(1, 6))
            return out
        # 🔴 2026-09-10 (WSDA desk read) — this sentence was the whole page, so a plan with an empty
        # list and seventeen logged applications showed a reviewer none of them, calcium chloride
        # included, under an attestation that every input was "entered in this list".
        return [
            Paragraph(
                "No input materials have been added to this plan's materials list.",
                styles["body"],
            ),
            *_unmatched_logged_flowables(osp, styles, list_is_empty=True),
            Spacer(1, 6),
        ]

    out = [Paragraph("<b>Input materials on this plan</b>", styles["body"])]
    out.append(
        Paragraph(
            "Each row: product — manufacturer — listing — reason for use; a National List substance "
            "with no product row also says so. A cell the plan does not hold is stated as not stated, "
            "never left blank.",
            styles["meta"],
        )
    )
    # Grouped from the ROWS, never from a literal list of source names. This function exists
    # because an earlier renderer read two of the three registries and silently dropped the
    # third — and a hardcoded tuple here would have dropped operator-entered rows the same way
    # the day they shipped (caught on review, 2026-08-28). Known sources keep their order;
    # anything new appears rather than vanishing.
    known = ("National List", "OMRI", "WSDA", "Operator-entered")
    seen = list(dict.fromkeys(r.source for r in rows))
    for source in [s for s in known if s in seen] + [s for s in seen if s not in known]:
        group = [r for r in rows if r.source == source]
        if not group:
            continue
        out.append(Paragraph(_escape(source), styles["meta"]))
        for row in group:
            out.append(Paragraph(f"• {_escape(row.display(stated_absences=True))}", styles["body"]))

    # A logged wash-water sanitizer the plan lists only under § 205.601, or under nothing.
    for line in post_harvest_listing_review(osp):
        out.append(Paragraph(_escape(line), styles["meta"]))

    # CCOF Materials Application §D is its own table — materials that contact the crop AFTER
    # harvest (wash-water additives, sanitizers, gases), under § 205.605 rather than § 205.601.
    # The operator files a row under that category; print those rows again under §D's own
    # heading so a CCOF reviewer finds the table where the form has it. Only when rows exist:
    # the operator's "none used" statement is the N/A, and an absence stays an absence.
    post_harvest = [r for r in rows if r.category == "post_harvest"]
    if post_harvest:
        out.append(Spacer(1, 4))
        out.append(
            Paragraph(
                "<b>Post-harvest contact materials</b> — wash-water additives, sanitizers, gases (§ 205.605)",
                styles["body"],
            )
        )
        for row in post_harvest:
            out.append(Paragraph(f"• {_escape(row.display(stated_absences=True))}", styles["body"]))

    for line in none_used_contradictions(osp, answers):
        out.append(Paragraph(_escape(line), styles["meta"]))

    # State the disagreement instead of leaving the reader to find it. The packet used to print
    # this list beside an event-derived workbook that held different products, under five
    # attestations that everything in use was "entered in this list".
    out += _unmatched_logged_flowables(osp, styles)
    out.append(Spacer(1, 6))
    return out


def _unmatched_logged_flowables(osp, styles, list_is_empty: bool = False) -> list:
    """A [REVIEW] line naming the logged products this plan's materials list does not hold."""
    from certifications.services.plan_materials import unmatched_logged_materials

    unmatched = unmatched_logged_materials(osp)
    if not unmatched:
        return []
    # Cap, and announce the cap. An operation with a hundred inputs would otherwise swallow
    # the page, and a silently truncated list reads as a complete one.
    shown = unmatched[:12]
    listed = ", ".join(shown)
    if len(unmatched) > len(shown):
        listed += f", and {len(unmatched) - len(shown)} more"
    if list_is_empty:
        sentence = (
            f"[REVIEW] The list is empty, but {len(unmatched)} product(s) appear in the logged "
            "applications: " + _escape(listed) + ". Add each one the operation uses or intends to use."
        )
    else:
        sentence = (
            f"[REVIEW] {len(unmatched)} product name(s) in the logged applications do not match "
            "an entry above: " + _escape(listed) + ". A brand name and the substance entry that "
            "covers it read differently, so some of these may already be accounted for — "
            "confirm each one and add anything genuinely missing."
        )
    return [Spacer(1, 4), Paragraph(sentence, styles["meta"])]


#: DMS `linked_section` used for an operator-supplied parcel map. The document model already
#: carries a `parcel` FK, so the map needs no new storage — only a section key that says what the
#: file IS, so the packet can ship it and the Parcel Application can name it.
PARCEL_MAP_SECTION = "parcel_application_map"


def parcel_map_documents(parcel):
    """Operator-supplied map documents for one parcel, newest first."""
    try:
        return list(parcel.documents.filter(linked_section=PARCEL_MAP_SECTION).order_by("-created_at"))
    except Exception:  # noqa: BLE001 — a document lookup must never take the packet down
        logger.exception("Could not load parcel map documents for parcel %s", getattr(parcel, "pk", None))
        return []


def _parcel_map_upload(parcel) -> str:
    """Filename of the operator's map as it appears in the packet ZIP, or "" if there is none."""
    docs = parcel_map_documents(parcel)
    if not docs:
        return ""
    doc = docs[0]
    ext = ("." + doc.file.name.rsplit(".", 1)[-1]) if "." in (doc.file.name or "") else ""
    safe_title = (doc.title or "map").replace("/", "-")[:60]
    return f"{doc.pk}-{safe_title}{ext}"


def _sticks_to_next(style):
    """`style`, but the paragraph will not be the last line on a page.

    A cloned ParagraphStyle rather than a `KeepTogether` wrapper: these flowables are read
    directly by tests and by callers that flatten the list, and nesting them hides their text.
    """
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(f"{style.name}KeepNext", parent=style, keepWithNext=1)


def _style(styles, name: str, fallback: str = "body"):
    """A named style, falling back rather than raising.

    `styles` arrives from more than one place — the module PDF's own sheet, and callers that
    build a minimal ReportLab stylesheet to render one embed in isolation (see
    `product/tests/test_parcel_area_units.py`, which pins the acres-vs-hectares regression on
    this very block). A renderer that hard-indexes a style key it happens to want turns a
    missing style into a crash on the § 205.202 page, which is the last page that should be
    fragile. ReportLab's own stylesheet raises KeyError on a miss, so ask it politely.
    """
    try:
        return styles[name]
    except (KeyError, IndexError):
        return styles[fallback]


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
        from product.services.transition_status_service import compute_transition_status, transition_verdict

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
        # NOT "Eligible for organic harvest: Yes/Not yet". Eligibility under § 205.202(b) is the
        # certifying agent's determination, and `is_eligible` is true by absence of contrary
        # evidence — which is indistinguishable from having no field history at all. One shared
        # resolver states what the records support; see transition_verdict().
        verdict = transition_verdict(status)
        if verdict == "Eligible" and (parcel.application_answers or {}).get("currently_certified") == "yes":
            # "Eligible" beside "currently certified: yes" read as a parcel still in transition
            # (WSDA specimen read, 2026-09-11). The records support "nothing prohibited in the
            # window"; that it IS certified is the operator's statement in section F, and says so.
            verdict = (
                "Certified organic, as the operation states in F below; no prohibited substance is on record "
                "in the last 36 months"
            )
        out.append(Paragraph(_escape(f"Organic transition status: {verdict}"), styles["body"]))
        if status.note:
            out.append(Paragraph(_escape(status.note), styles["meta"]))

    elif embed == "buffer_editor":
        rows = parcel.buffer_zones or []
        if not rows:
            out.append(Paragraph("No buffer or adjoining-land records on file.", styles["body"]))
        for row in rows:
            if not isinstance(row, dict):
                continue
            # One boundary reads as one block: its "West:" line was stranded at a page foot with
            # the width and the prevention overleaf, on two parcels of the specimen (2026-09-11).
            head = _escape(f"{row.get('direction') or '—'}: {row.get('adjoining_land_use') or '—'}")
            out.append(Paragraph(f"<b>{head}</b>", _sticks_to_next(_style(styles, "body"))))
            bits = []
            width_ft = row.get("buffer_width_ft")
            if width_ft is not None:
                bits.append(f"buffer width {width_ft} ft")
            if row.get("buffer_type"):
                bits.append(f"type: {row['buffer_type']}")
            if row.get("adjacent_is_organic") is True:
                bits.append("adjoining land is certified organic — no buffer required")
            if row.get("crop_grown_in_buffer"):
                # State the crop, NOT its organic status. "never sold as organic" had the packet
                # asserting the exact fact § 205.202(c) asks the operator to PROVE, on the strength
                # of a free-text parcel field. What became of the crop is evidenced by the
                # buffer-use disposition records, not by this line.
                bits.append(f"crop grown in buffer: {row['crop_grown_in_buffer']}")
            if row.get("prohibited_use_last_date"):
                bits.append(f"adjoining land last received a prohibited material {row['prohibited_use_last_date']}")
            if row.get("drift_risk"):
                # The wizard stores low / medium / high; older rows carry "Low". Print one form.
                risk = str(row["drift_risk"]).strip()
                bits.append(f"drift risk: {risk[:1].upper() + risk[1:].lower()}")
            if row.get("neighbor_notified") is True:
                when = row.get("neighbor_notification_date") or ""
                bits.append(f"neighbor notified{(' ' + when) if when else ''}")
            prevention = row.get("prevention")
            if bits:
                style = _sticks_to_next(_style(styles, "body")) if prevention else styles["body"]
                out.append(Paragraph(_escape("; ".join(bits) + "."), style))
            if prevention:
                out.append(Paragraph(_escape(str(prevention)), styles["body"]))
            out.append(Spacer(1, 4))

    elif embed == "parcel_map":
        # 🔴 Until 2026-08-28 this printed one sentence — "Field map on file (boundary recorded
        # in Trazo)" — and no map, on the page whose entire job is to prove land eligibility.
        # CCOF NOPB49 §E requires the map ATTACHED and reviewed before a new parcel is
        # inspected; WSDA AGR 2264 requires one with every site application. A sentence saying
        # the map exists somewhere the reviewer is not looking is worse than printing nothing.
        #
        # The schematic comes from `certifications.services.parcel_map`, shared with the
        # per-production audit export so the two documents cannot draw the same parcel
        # differently.
        from certifications.services.parcel_map import CCOF_MAP_ELEMENTS, parcel_map_caption, parcel_map_drawing

        drawing = parcel_map_drawing(parcel)
        if drawing is not None:
            out.append(drawing)
            out.append(Paragraph(_escape(parcel_map_caption(parcel)), styles["body"]))
            out.append(
                Paragraph(
                    "Schematic parcel boundary drawn from the recorded field geometry — not a "
                    "surveyed plat, not to scale, and not satellite imagery. Compass labels "
                    "carry the adjoining land use recorded for each boundary.",
                    _style(styles, "meta"),
                )
            )
        else:
            # The identity line prints in BOTH branches. The first cut only printed it beside a
            # drawing, which silently dropped the parcel's ACREAGE from §E for any parcel whose
            # boundary is not yet recorded — the one number CCOF asks to see annotated on the map
            # and the subject of the acres-vs-hectares regression this page already carries a
            # test for. Caught by that test (`product/tests/test_parcel_area_units.py`).
            out.append(Paragraph(_escape(parcel_map_caption(parcel)), styles["body"]))
            out.append(
                Paragraph(
                    "[REVIEW] No field-boundary geometry is on file for this parcel, so no map "
                    "could be drawn. Record the parcel boundary in Trazo, or attach your own "
                    "map below.",
                    _style(styles, "meta"),
                )
            )

        # An uploaded map is the operator's own document and outranks the schematic — CCOF
        # prefers satellite imagery, and several of its eleven required elements (roads and
        # landmarks, permanent identifiers, other operation areas) cannot appear on a boundary
        # schematic at all. Say which of the two the reviewer is holding.
        uploaded = _parcel_map_upload(parcel)
        if uploaded:
            out.append(
                Paragraph(
                    _escape(f"Operator-supplied map attached to this packet: parcels/maps/{uploaded}."),
                    styles["body"],
                )
            )
        else:
            out.append(
                Paragraph(
                    "[REVIEW] No operator-supplied map is attached. A schematic boundary cannot "
                    "carry every element a certifier asks for — "
                    + _escape(", ".join(CCOF_MAP_ELEMENTS[:6]))
                    + " and the rest. Attach an 8.5x11 map (satellite imagery preferred) on the "
                    "parcel page.",
                    _style(styles, "meta"),
                )
            )

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
            # 2026-09-09 — was gated on `row.is_derived`, so an operator-typed year (which is what
            # a 36-month history on newly acquired ground IS) printed no materials at all. WSDA AGR
            # 2264 ref 13 and OTCO C2 2.4-8/2.4-9 ask for every material by name and date.
            if row.substances_applied:
                bits.append(f"inputs applied: {row.substances_applied}")
            if row.last_prohibited_substance:
                when = row.date_last_prohibited
                bits.append(
                    f"last prohibited input: {row.last_prohibited_substance}"
                    + (f" ({when.isoformat()})" if when else "")
                )
            if row.is_derived:
                bits.append("from season records")
            elif row.season_names:
                # A typed year the operation ALSO logged seasons for. The typed line is the
                # operator's own statement and stands; hiding the seasons behind it let a page
                # read as hand-entered history while the audit trail traced dated records of the
                # same season (WSDA specimen read, 2026-09-12).
                bits.append("also logged in Trazo: " + "; ".join(row.season_names))
            out.append(Paragraph(_escape(" · ".join(bits)), styles["body"]))
            # The structured material / manufacturer / date rows the Field History form asks for,
            # one line each under the year. Never derived from the prose blob (see the model).
            from certifications.services.parcel_land_history import structured_substances

            for material, manufacturer, dates in structured_substances(row):
                out.append(
                    Paragraph(
                        _escape(
                            f"— {material} · {manufacturer or 'manufacturer not recorded'} · "
                            f"applied {dates or 'date not recorded'}"
                        ),
                        _style(styles, "meta"),
                    )
                )
        if any(r.is_derived or r.season_names for r in history):
            out.append(
                Paragraph(
                    _escape(
                        "Years marked “from season records” are compiled from the productions and "
                        "inputs logged on this parcel in Trazo; years without that mark were entered "
                        "by the operator as land-use history. Where a year carries both, the "
                        "operator's own line is printed and the seasons logged for that year are "
                        "named beside it."
                    ),
                    styles["meta"],
                )
            )

    elif embed == "landowner_affidavit":
        # 2026-09-09 — printed "N landowner affidavit(s) on file." The names, periods and
        # last-prohibited dates CCOF §F6, OTCO 2.5-1/2.5-5 and WSDA AGR 2262 ask for lived only in
        # the per-production audit dossier. Same table here, plus the current manager as the first
        # row (OTCO 2.5-4) and an accounting of the 36-month window.
        from reportlab.platypus import Table, TableStyle

        from certifications.services.parcel_land_history import (
            CURRENT_MANAGER,
            coverage,
            current_manager_row,
            fmt_period_edge,
            prior_manager_rows,
        )

        prior = prior_manager_rows(parcel)
        current = current_manager_row(parcel, parcel.application_answers or {})
        account = coverage(parcel, prior)
        out.append(Paragraph(_escape(account.text), styles["body"]))
        if not prior:
            out.append(Paragraph("No prior-manager affidavit on file for this parcel.", styles["body"]))

        meta = _style(styles, "meta")
        header = ["Manager", "Role", "From", "To", "Last prohibited", "Materials", "Signed", "Attachment"]
        data = [[Paragraph(f"<b>{_escape(h)}</b>", meta) for h in header]]
        for r in [current] + prior:
            data.append(
                [
                    Paragraph(_escape(r.name), meta),
                    Paragraph(_escape(r.role), meta),
                    Paragraph(_escape(fmt_period_edge(r.period_start)), meta),
                    Paragraph(
                        _escape(fmt_period_edge(r.period_end, present_when_none=(r.role == CURRENT_MANAGER))), meta
                    ),
                    Paragraph(_escape(r.last_prohibited.isoformat() if r.last_prohibited else "none recorded"), meta),
                    Paragraph(_escape(r.declared), meta),
                    Paragraph(
                        _escape(
                            r.signed.isoformat() if r.signed else ("—" if r.role == CURRENT_MANAGER else "unsigned")
                        ),
                        meta,
                    ),
                    Paragraph(
                        _escape("—" if r.role == CURRENT_MANAGER else ("attached" if r.attachment else "not attached")),
                        meta,
                    ),
                ]
            )
        table = Table(
            data,
            colWidths=[
                1.35 * inch,
                0.7 * inch,
                0.6 * inch,
                0.6 * inch,
                0.8 * inch,
                1.2 * inch,
                0.7 * inch,
                0.85 * inch,
            ],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.grey),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        out.append(table)
        for r in prior:
            bits = []
            if r.attachment:
                bits.append("signed affidavit attached at " + r.attachment)
            if r.legal_description:
                bits.append("land as described by signer: " + r.legal_description)
            if r.landowner:
                bits.append("landowner: " + r.landowner)
            if bits:
                out.append(Paragraph(_escape(f"{r.name}: " + "; ".join(bits)), meta))
        for r in [current] + prior:
            if r.contradiction:
                out.append(
                    Paragraph(
                        _escape(
                            f"[REVIEW] {r.name}: a declaration of no prohibited material sits over a record "
                            "that names one. Both are shown; the records are not reconciled here."
                        ),
                        meta,
                    )
                )
        out.append(
            Paragraph(
                "A prior manager's signed affidavit, where one is attached, is in the packet's "
                "parcels/affidavits/ folder. Dates are as each signer stated them.",
                meta,
            )
        )

    elif embed == "certificate_of_record":
        # CCOF §G, OTCO 2.4-2, WSDA AGR 2264 ref 6: for a parcel already certified, the current
        # certificate is the land-history evidence. It printed on the cover only.
        from certifications.services.parcel_land_history import certificate_line

        line = certificate_line(parcel.establishment)
        if line.on_file:
            bits = [
                f"Certificate of record: {line.number}"
                + (f" — {line.agent}" if line.agent else " — issuing agent not recorded")
            ]
            if line.effective:
                bits.append(f"effective {line.effective.isoformat()}")
            if line.expiry:
                bits.append(f"expires {line.expiry.isoformat()}")
            out.append(Paragraph(_escape("; ".join(bits)), styles["body"]))
            out.append(
                Paragraph(
                    _escape(
                        f"Certificate document: {line.document_url}"
                        if line.document_url
                        else "Certificate document: not attached to this packet — the issued certificate is the certifier's own record."
                    ),
                    _style(styles, "meta"),
                )
            )
        else:
            out.append(
                Paragraph(
                    "No certificate is on file for this operation in Trazo. The parcel is stated above as "
                    "currently certified; the certifying agent's own record governs.",
                    styles["body"],
                )
            )
        out.append(
            Paragraph(
                "This is the operation's certificate. The parcels it covers are listed on the certificate " "itself.",
                _style(styles, "meta"),
            )
        )

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
        # The state is an enum slug ("in_progress"); printed raw it read as a leak of internals on
        # every parcel page of the OTCO desk read (2026-09-10).
        state = parcel_application_status(parcel)["state"]
        entry = {"status_line": f"Parcel application: {state.replace('_', ' ')}"}
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
                elif question.embed == "post_harvest_facilities":
                    rendered = _post_harvest_facility_flowables(osp, styles)
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
            # An attestation stored before the gate existed can still be affirmative over an empty
            # list. The API refuses to write one now, but a plan attested earlier keeps it, and
            # printing a bare "Yes" under a section that says "no record types have been confirmed"
            # is the contradiction this whole fix is about. Qualify it rather than hide it: the
            # answer is the operator's and stays visible.
            if getattr(question, "attests_embed", None) and value is True:
                from certifications.services.attestation_gates import blocked_attestations

                if blocked_attestations(module, {question.key: True}, osp):
                    story.append(
                        Paragraph(
                            "[REVIEW] Nothing in the list above is confirmed, so this attestation "
                            "is not supported by the plan as it stands.",
                            styles["meta"],
                        )
                    )
            story.append(Spacer(1, 6))
        if not answered_any:
            story.append(Paragraph("No answers recorded for this module yet.", styles["body"]))

    # The definition stamp is a page footer, not the story's last paragraph. As a paragraph it
    # followed whatever the page ended on, and a parcel page whose § F table filled the sheet
    # (parcel 49, 2026-09-10) pushed it alone onto a third page that said nothing else. A
    # canvas footer never orphans, and a stapled packet gets page numbers.
    # The document's own name leads the footer. Every module is its own PDF with its own page 1,
    # so in a stapled or merged packet "Page 1" alone recurred twenty times with nothing to say
    # which document it belonged to (WSDA specimen read, 2026-09-11).
    if parcel is not None:
        doc_label = f"Parcel Application — {parcel.name}"
    else:
        doc_label = " ".join(x for x in (module.code or "", _en(module.title) or "") if x) or module.key
    footer = _definition_footer(f"{doc_label} · Definition version {definition_version} — generated by Trazo")
    # Same authority as the audit packet (common/specimen.py). An OSP is the § 205.201
    # plan a certifier approves; a fabricated one must not read as an approved plan.
    specimen = is_specimen(getattr(osp, "establishment", None))
    doc.build(
        story,
        onFirstPage=specimen_page_callback(letter, base_callback=footer, specimen=specimen),
        onLaterPages=specimen_page_callback(letter, base_callback=footer, specimen=specimen),
    )
    return buffer.getvalue()


def _definition_footer(text: str):
    """Per-page callback: the definition stamp bottom-left, the page number bottom-right."""

    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        y = 0.45 * inch
        canvas.drawString(doc.leftMargin, y, text)
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, y, f"Page {doc.page}")
        canvas.restoreState()

    return _draw


# Every file in the packet ZIP can be opened on its own, and that is how the "no annual
# update" page was first read — with nothing on it to say it belonged to a draft fork rather
# than to the plan on file. Each document a reader can open in isolation names its plan
# version AND that version's status.
_PLAN_STATUS_LABEL = {
    "draft": "draft — not yet submitted",
    "submitted": "submitted to certifier",
    "active": "active",
    "superseded": "superseded",
    "withdrawn": "withdrawn",
}


def _count_phrase(n: int, noun: str) -> str:
    """'1 addition', '3 additions', 'no deletions'. Not 'addition(s)', which is a form's grammar."""
    if not n:
        return f"no {noun}s"
    return f"{n} {noun}{'' if n == 1 else 's'}"


#: The § 205.406(a)(3) answer, kept beside the section attestations it resembles: a dated
#: statement by the operator that something is unchanged since the prior update. Not a
#: § 205.201(a) section, so it is never listed among them.
APPLICATION_INFO_KEY = "application_information"


def _gross_organic_sales(establishment, year: int):
    """(total, count) of the organic sales dated in `year`, from the operation's own sales records.

    WSDA sets the renewal fee from the prior year's gross organic sales (WAC 16-157-251), and
    other agencies ask for the figure too. Voided sales are excluded; a sale counts as organic
    only when its invoice identifies it as organic, which is the § 205.103(b)(3) test.
    """
    from django.db.models import Count, Sum

    from history.models import SalesRecord

    agg = (
        SalesRecord.objects.live()
        .filter(production__parcel__establishment=establishment, organic_on_invoice=True, sale_date__year=year)
        .aggregate(total=Sum("sale_amount"), n=Count("id"))
    )
    return agg["total"], agg["n"] or 0


def _plan_version_label(osp) -> str:
    status = (getattr(osp, "status", "") or "").strip()
    label = _PLAN_STATUS_LABEL.get(status, status)
    return f"OSP v{osp.version_number}" + (f" ({label})" if label else "")


def _other_filing_sentence(other) -> str:
    """Name the filing that IS on file when none is linked to the version being exported.

    "No annual update is on file" and "your annual update is recorded against v3" are
    different facts, and only the first is an action item. Printing only the first sent an
    operator who had filed weeks earlier looking for a filing they had already made. This
    sentence never presents that update as this packet's filing — it continues its own year.
    """
    where = (
        f"v{other.prior_osp.version_number} to v{other.new_osp.version_number}"
        if other.new_osp_id
        else f"v{other.prior_osp.version_number}"
    )
    filed = other.submitted_at.date().isoformat() if other.submitted_at else "started but not yet filed"
    return (
        f"The most recent annual update on file for this operation is the {other.reporting_year} "
        f"update ({filed}), recorded against {where}. It continues that year, not this plan version."
    )


def _renewal_context(osp) -> dict:
    """The facts a renewal cover is read for, gathered once for the cover and the filing PDF.

    * the § 205.406 filing this packet carries — the annual update whose `new_osp` is this
      plan (a renewal that produced a new version), else the one whose `prior_osp` is this plan
      (a reaffirmation), else nothing;
    * `other_filing` — when nothing is linked to THIS version, the operation's most recent
      filing anyway, so the empty page can say which version it is recorded against instead of
      leaving the operator to conclude they never filed;
    * the NOP certificate and certifier on file;
    * the § 205.401(b) responsible person and address.
    """
    from certifications.models import OSPAnnualUpdate
    from certifications.services.operation_certificate import certificate_of_record

    est = osp.establishment
    filing = (
        OSPAnnualUpdate.objects.filter(new_osp=osp).order_by("-reporting_year", "-submitted_at").first()
        or OSPAnnualUpdate.objects.filter(prior_osp=osp).order_by("-reporting_year", "-submitted_at").first()
    )
    other_filing = None
    if filing is None:
        # Scoped through `prior_osp` — the same relation `OSPAnnualUpdateViewSet.get_queryset`
        # scopes by, so the packet and the OSP screen agree on what "this operation has filed"
        # means. Ordered newest-year-first; ties broken by filing date, then id.
        other_filing = (
            OSPAnnualUpdate.objects.filter(prior_osp__establishment=est)
            .select_related("prior_osp", "new_osp")
            .order_by("-reporting_year", "-submitted_at", "-id")
            .first()
        )
    # 🔴 2026-09-07 — the activation gate is the OTHER home of this fact, and until now the only
    # one a renewing operation actually fills. `OSPViewSet.activate` REQUIRES an approval
    # document, a certificate number and a certifying agent's name before a plan may go active;
    # it writes all three to the OSP itself. The cover read `Certification` rows — the farm
    # profile's certification list, which nothing in the OSP flow asks for — so a farm that had
    # just satisfied the strictest gate in the product printed "Certificate: —" on the document
    # its certifier reads.
    #
    # `certificate_of_record` takes both halves from ONE record. The first version of this fix
    # filled each half independently and could print a CCOF certificate number beside a WSDA
    # agent name — a number attributed to an agent that did not issue it, which is worse than the
    # blank. See `operation_certificate` for the rule and the rest of the reasoning.
    certificate = certificate_of_record(est.id)
    certificate_number = certificate.number
    certifier_name = certificate.agent
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
        "other_filing": other_filing,
        "certificate_number": certificate_number,
        "certifier_name": certifier_name,
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

    def kv(label, value, note=None):
        text = f"<b>{_escape(label)}:</b> {_escape(str(value))}"
        if note:
            text += f" ({_escape(note)})"
        return Paragraph(text, styles["body"])

    year_line = f"Continuation for {filing.reporting_year}" if filing else "Continuation year not filed"
    story = [
        Paragraph("Organic System Plan — Renewal Packet", styles["title"]),
        Paragraph(
            _escape(f"{osp.establishment.name} · {_plan_version_label(osp)} · {year_line}"),
            styles["subtitle"],
        ),
        Spacer(1, 8),
    ]
    # A draft is not a filing. The packet button exports the version the operator is WORKING
    # on, which is the right default during a renewal and the wrong thing to hand a certifier
    # unlabelled — "Plan submitted: not yet submitted", eleven rows down, is not a label.
    if (getattr(osp, "status", "") or "") == "draft":
        story.append(
            Paragraph(
                "<b>This plan version is a draft and has not been submitted.</b> This packet is a "
                "working copy for the operation to review — it is not the plan on file with the "
                "certifying agent.",
                styles["body"],
            )
        )
        story.append(Spacer(1, 8))
    story += [
        Paragraph("Operation (7 CFR 205.401(b))", styles["header"]),
        kv("Legal name", ctx["legal_name"] or "—"),
        kv("Operation", osp.establishment.name),
        # 🔴 2026-09-07 — the value and the warning must not contradict each other. When no
        # contact person is on the farm profile the packet falls back to the plan's author, and
        # the cover printed "Responsible person: Dale Brennan" followed one line later by "The
        # operation has no contact person" — two adjacent lines on the certifier's own document
        # asserting opposite things. The fallback is still the right VALUE (a name a reviewer can
        # call beats a dash); it just has to say what it is.
        kv(
            "Responsible person",
            ctx["responsible_person"] or "—",
            note=None if ctx["responsible_person_is_named"] else "plan author — not yet confirmed on the farm profile",
        ),
    ]
    if not ctx["responsible_person_is_named"]:
        story.append(
            Paragraph(
                "§ 205.401(b) asks for the person responsible for the operation by name. Set the "
                "contact person on the farm profile so this line is the operation's own answer "
                "rather than the plan author Trazo fell back to.",
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
            # "Continues certification for", never "Reporting year": the filing continues THIS year's
            # certification and reports on the season before it, and a grower reads "reporting year
            # 2026" as the year being reported on (WSDA specimen read, 2026-09-11). The title line
            # above already says "Continuation for {year}"; this says the same thing the same way.
            kv("Continues certification for", filing.reporting_year),
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
                "Additions and deletions reported",
                f"{_count_phrase(len(filing.additions or []), 'addition')}, "
                f"{_count_phrase(len(filing.deletions or []), 'deletion')}",
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
        if ctx.get("other_filing") is not None:
            story.append(Paragraph(_escape(_other_filing_sentence(ctx["other_filing"])), styles["meta"]))

    # ---- plan review ---------------------------------------------------------------------
    review = plan_review(osp)
    story += [
        Spacer(1, 8),
        Paragraph("Plan review — records dated after the plan's answers were written", styles["header"]),
    ]
    if review.answers_as_of:
        story.append(kv("Newest answer in this plan", review.answers_as_of))
    if review.is_clean:
        story.append(
            Paragraph(
                # Says WHICH window it is speaking for. On a filed plan the review stops at the
                # filing date, while the record counts further down the packet run to today, and
                # the flat sentence read as a claim about both (WSDA specimen read, 2026-09-12).
                _escape(
                    "No operation change is recorded between the plan's newest answer and " f"{review.reference_date}."
                ),
                styles["body"],
            )
        )
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
        Paragraph(
            "03. § 205.400(f) change notifications filed against this plan or its earlier versions", styles["body"]
        ),
        Paragraph("04. What this packet covers, what it does not, and who authored it", styles["body"]),
        Paragraph(
            "05. Audit trail exhibit — the § 205.103(b)(2) document table and one lot traced field to sale",
            styles["body"],
        ),
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
            Paragraph(_escape(f"{osp.establishment.name} · {_plan_version_label(osp)}"), styles["subtitle"]),
            Spacer(1, 10),
            Paragraph(
                _escape(
                    f"No § 205.406(a) annual update is on file for OSP v{osp.version_number}. The packet "
                    "cannot stand in for the filing: record the year's changes, planned additions and "
                    "deletions, and file it before the packet is sent."
                ),
                styles["body"],
            ),
        ]
        # Which is a different sentence from "this operation has never filed one", and the
        # operator cannot act on the first without knowing the second.
        if ctx.get("other_filing") is not None:
            story += [
                Spacer(1, 8),
                Paragraph(_escape(_other_filing_sentence(ctx["other_filing"])), styles["body"]),
            ]
    else:
        story += [
            Paragraph(
                _escape(
                    # 🔴 2026-09-07: this said "(a)(1)–(3)" while rendering (a)(1) and (a)(2)
                    # only. `OSPAnnualUpdate` has no field for (a)(3) — additions to or
                    # deletions from the § 205.401(b) application information (the person
                    # completing the application, the business name, address and telephone
                    # number, and for a corporation the person authorized to act on its
                    # behalf) — and the wizard posts no such key. Claiming the paragraph is
                    # the packet asserting something the record cannot support. State the
                    # range the document actually carries; the (a)(3) position is stated
                    # below rather than left as a silent gap.
                    f"{osp.establishment.name} · {_plan_version_label(osp)} · "
                    f"continuation for {filing.reporting_year} · 7 CFR 205.406(a)(1)–"
                    + (
                        "(3)"
                        if (filing.sections_unchanged_attestation or {}).get(APPLICATION_INFO_KEY) is True
                        else "(2)"
                    )
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
        # (a)(3) is the OPERATOR's statement or it is nothing. Only an explicit attestation says the
        # § 205.401(b) details are unchanged; anything else prints as not stated, never as "None
        # stated" (which would assert what the operator never said). Until 2026-09-11 there was no
        # way to make the statement at all, and the grower's own filing carried a sentence about
        # what Trazo does not track.
        application_unchanged = (filing.sections_unchanged_attestation or {}).get(APPLICATION_INFO_KEY) is True
        story += [
            Spacer(1, 8),
            Paragraph("(a)(3) Changes to the application information under § 205.401(b)", styles["header"]),
            Paragraph(
                (
                    (
                        "No changes. The operator attests that the business name, address and telephone "
                        "number, the person responsible for the operation and, for a company, the person "
                        "authorized to act on its behalf are unchanged since the prior update."
                    )
                    if application_unchanged
                    else (
                        "Not stated on this filing. Any change to the business name, address or telephone "
                        "number, or to the person responsible for the operation, goes to the certifying "
                        "agent with this update."
                    )
                ),
                styles["body"],
            ),
        ]
        # 🔴 2026-09-10 (WSDA desk read) — this printed storage keys ("practices procedures") and
        # wrote "changed" beside every box left unticked. The form sends all six keys, unticked as
        # False, so an operator who attested one section was filed as reporting five changes they
        # never stated. Only True is an attestation; an unticked box is silence, and is omitted.
        attested = [
            key
            for key, val in (filing.sections_unchanged_attestation or {}).items()
            if val is True and key != APPLICATION_INFO_KEY
        ]
        if attested:
            order = list(SECTION_LABELS)
            story += [Spacer(1, 8), Paragraph("Sections attested unchanged since the prior plan", styles["header"])]
            for key in sorted(attested, key=lambda k: (order.index(k) if k in order else len(order), k)):
                clause, label = SECTION_LABELS.get(key, (None, key.replace("_", " ")))
                line = f"• § 205.201{clause} — {label}" if clause else f"• {label}"
                story.append(Paragraph(_escape(line), styles["body"]))
        prior_year = filing.reporting_year - 1
        total, n_sales = _gross_organic_sales(osp.establishment, prior_year)
        story += [Spacer(1, 8), Paragraph(f"Gross organic sales, {prior_year}", styles["header"])]
        story.append(
            Paragraph(
                _escape(
                    f"${total:,.2f} across {_count_phrase(n_sales, 'sale')} invoiced as organic and dated in "
                    f"calendar {prior_year}, from the operation's sales records in Trazo. Certifying agents that "
                    "set fees from gross organic sales (WSDA: WAC 16-157-251) ask for this figure with the "
                    f"renewal. Fruit of the {prior_year} crop settled after 31 December is not in it."
                    if n_sales
                    else f"No sale invoiced as organic is dated {prior_year} in the operation's records. State the "
                    "figure the certifying agent's fee schedule asks for."
                ),
                styles["body"],
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
            *signature_block(osp.establishment, styles["body"]),
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
            _escape(
                f"{osp.establishment.name} · "
                + (f"plan versions v1 to v{osp.version_number}" if osp.version_number > 1 else "plan v1")
            ),
            styles["subtitle"],
        ),
        Spacer(1, 8),
    ]
    if not notices:
        story.append(
            Paragraph("No change notifications are on file for this plan or its earlier versions.", styles["body"])
        )
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


def _workbook_filename(spec) -> str:
    """The workbook's own form name as a ZIP entry, not its code key.

    🔴 2026-09-07 — the packet wrote `workbooks/{spec.key}.xlsx`, so a certifier opening the ZIP
    met `field_and_crop_information.xlsx` and `crop_livestock_product_list.xlsx`: Trazo's
    identifiers, in the one place the reader has nothing else to go on. Every other document in
    this packet is named for what it IS. `/` is a path separator inside a ZIP, so the one title
    that carries it ("Crop/Livestock Product List") is hyphenated rather than nested.
    """
    title = (getattr(spec, "title", None) or spec.key).replace("/", "-")
    safe = "".join(c if c.isalnum() or c in "-_ &." else "_" for c in title).strip()
    return f"{safe or spec.key}.xlsx"


def _lot_balance_flowables(balance, styles) -> list:
    """Part B step 4 — harvested minus sold for the traced lot, stated or explained."""
    from certifications.services.audit_trail_exhibit import fmt_total

    out = [Paragraph("<b>4. Balance</b> — harvested minus sold, for this lot", styles["body"])]
    if balance is None or balance.difference is None:
        reason = balance.not_computed if balance is not None else "no harvest or sale is on record"
        out.append(
            Paragraph(
                _escape(f"Balance not computed: {reason}. The operator states the balance on this page."),
                styles["meta"],
            )
        )
        return out
    plural = "s" if balance.harvest_count != 1 else ""
    sale_plural = "s" if balance.sale_count != 1 else ""
    line = (
        f"Harvested {fmt_total(balance.harvested, balance.unit)} ({balance.harvest_count} harvest record{plural})"
        f" \u00b7 sold {fmt_total(balance.sold, balance.unit)} ({balance.sale_count} sale{sale_plural})"
    )
    diff = balance.difference
    packed = balance.packed_out
    if packed is not None and diff == 0:
        # Balanced AND packed: the fresh pack-out and the processing fruit are separate sales of
        # the same delivery, and the pack-out is the number a reviewer reads first.
        line += f" \u00b7 packed out by the handler {fmt_total(packed, balance.unit)}, the rest sold on the "
        line += "same settlement \u00b7 harvest and sales balance."
    elif packed is not None and diff > 0:
        # A packed crop: the handler's pack-out is on every harvest record, so the gap between
        # harvest and sale is stated from the records, not handed back to the operator.
        shrink = balance.harvested - packed
        unsold = packed - balance.sold
        line += f" \u00b7 packed out by the handler {fmt_total(packed, balance.unit)}."
        if unsold == 0:
            line += (
                f" Sales match the pack-out; the {fmt_total(shrink, balance.unit)} between harvest and "
                "pack-out is the handler's culls and shrink, from the pack-out figures on the harvest records."
            )
        elif unsold > 0:
            line += (
                f" {fmt_total(unsold, balance.unit)} of the packed-out crop is not accounted for by a sale of "
                "this lot. State whether it is in storage or was sold under another record."
            )
        else:
            line = (
                f"[REVIEW] {line} Sales exceed the handler's pack-out by {fmt_total(-unsold, balance.unit)}. "
                "A pack-out figure is missing, or a sale is filed against the wrong lot."
            )
    elif diff == 0:
        line += " \u00b7 harvest and sales balance."
    elif diff > 0:
        line += (
            f" \u00b7 {fmt_total(diff, balance.unit)} harvested is not accounted for by a sale of this lot. "
            "State whether it is in storage, culled or lost to shrink."
        )
    else:
        line = (
            f"[REVIEW] {line} \u00b7 sales exceed the recorded harvest by {fmt_total(-diff, balance.unit)}. "
            "A harvest record is missing, or a sale is filed against the wrong lot."
        )
    out.append(Paragraph(_escape(line), styles["body"]))
    out.extend(_buffer_crop_flowables(balance, styles))
    return out


def _buffer_crop_flowables(balance, styles) -> list:
    """The § 205.202(c) buffer crop, stated beside the organic balance it is kept out of."""
    from certifications.services.audit_trail_exhibit import fmt_total

    if balance is None or (balance.buffer_harvested is None and balance.buffer_sold is None):
        return []
    bits = []
    if balance.buffer_harvested is not None:
        bits.append(f"{fmt_total(balance.buffer_harvested, balance.unit)} harvested from the buffer row")
    if balance.buffer_sold is not None:
        bits.append(
            f"{fmt_total(balance.buffer_sold, balance.unit)} sold on "
            f"{_count_phrase(balance.buffer_sale_count, 'invoice')} that do not identify it as organic"
        )
    return [
        Paragraph(
            _escape(
                "Buffer crop (7 CFR 205.202(c)), counted apart from the organic lot above: " + " · ".join(bits) + "."
            ),
            styles["meta"],
        )
    ]


def _audit_trail_exhibit_pdf(osp) -> bytes:
    """05 — the § 205.103(b)(2) audit trail exhibit: the document table and one sample lot.

    See `audit_trail_exhibit` for the two rules this page keeps: the table lists only record
    types the operator CONFIRMED in G8.0 §A, and the sample trail is one real lot walked through
    the operation's own dated records — an absence is stated, never filled in.
    """
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    from certifications.services.audit_trail_exhibit import OPERATOR_COMPLETES, document_table, sample_trail

    establishment = osp.establishment
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="Audit trail exhibit")
    story = [
        Paragraph("Audit trail exhibit", styles["title"]),
        Paragraph(
            _escape(f"{establishment.name} · OSP v{osp.version_number} · 7 CFR 205.103(b)(2)"), styles["subtitle"]
        ),
        Paragraph(
            "Records must be traceable from sale or disposition back through storage, harvest and "
            "production to the field. Part A names each document the operation keeps and the element "
            "that links it to the next and previous document in the chain. Part B walks one lot "
            "through the operation's own dated records. Both parts are compiled from records the "
            "operation logged; the record types in Part A are the ones the operator confirmed in "
            "module G8.0 §A, and nothing here is inferred.",
            styles["body"],
        ),
        Spacer(1, 8),
        Paragraph("Part A — Documents and linking elements", styles["header"]),
    ]

    rows = document_table(establishment, osp)
    if not rows:
        story.append(
            Paragraph(
                "No record types have been confirmed in module G8.0 §A yet, so this table is empty. "
                "It fills in as the operator confirms the records the operation maintains; a "
                "suggestion Trazo derived from logged events is not a confirmation and is not listed.",
                styles["meta"],
            )
        )
    else:
        head = [
            Paragraph("<b>Name of document</b>", styles["meta"]),
            Paragraph("<b>Activity the document describes</b>", styles["meta"]),
            Paragraph("<b>Linking element to the next and previous document</b>", styles["meta"]),
        ]
        data = [head]
        for row in rows:
            link = row.linking_element if row.linking_element else OPERATOR_COMPLETES
            data.append(
                [
                    Paragraph(_escape(row.name), styles["meta"]),
                    Paragraph(_escape(row.activity), styles["meta"]),
                    Paragraph(_escape(link), styles["meta"]),
                ]
            )
        # The packet's text frame is 7.00 in wide; three columns that sum to it.
        table = Table(data, colWidths=[1.9 * inch, 2.1 * inch, 3.0 * inch], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2EFDA")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(table)
        story.append(
            Paragraph(
                "Rows whose linking element reads as the operator's own document are records Trazo does "
                "not hold (weigh tickets, delivery slips, the operation's own forms); the operator states "
                "the link on this page.",
                styles["meta"],
            )
        )

    story += [Spacer(1, 10), Paragraph("Part B — Sample trail, one lot from field to sale", styles["header"])]
    trail = sample_trail(establishment)
    if trail is None:
        story.append(
            Paragraph(
                "No finished season with a recorded sale exists yet, so no sample trail is drawn. The "
                "trail is generated from the most recently finished season that has at least one sale "
                "on record; an open season or an unsold one is not a trace-back and is not shown.",
                styles["meta"],
            )
        )
    else:
        story.append(
            Paragraph(
                _escape(
                    f"Season: {trail.season_name or '—'} · Crop: {trail.crop or '—'} · Parcel: {trail.parcel or '—'}"
                ),
                styles["body"],
            )
        )
        if trail.lot_id:
            story.append(Paragraph(f"<b>Linking element — Lot ID: [ {_escape(trail.lot_id)} ]</b>", styles["body"]))
        else:
            story.append(
                Paragraph(
                    _escape(
                        "Linking element — Lot ID: none recorded on this season. "
                        + (
                            trail.lot_blocker
                            or "A lot identifier is required before containers can be labeled (§ 205.307(a)(2))."
                        )
                    ),
                    styles["body"],
                )
            )
        story.append(Paragraph("<b>1. Harvest records</b> — link: Lot ID + harvest date + parcel", styles["body"]))
        if trail.harvests:
            for h in trail.harvests:
                bits = [h["date"] or "undated"]
                if h["quantity"]:
                    bits.append(h["quantity"])
                if h["block"]:
                    bits.append(f"block {h['block']}")
                if h["storage"]:
                    bits.append(f"to storage: {h['storage']}")
                story.append(Paragraph(_escape("• " + " · ".join(bits)), styles["meta"]))
        else:
            story.append(Paragraph("• No harvest event is recorded on this season.", styles["meta"]))
        story.append(
            Paragraph("<b>2. Storage</b> — link: storage location on the harvest record + Lot ID", styles["body"])
        )
        if trail.storage_locations:
            for loc in trail.storage_locations:
                story.append(Paragraph(_escape(f"• {loc}"), styles["meta"]))
        else:
            story.append(
                Paragraph("• No storage location is recorded on this season's harvest records.", styles["meta"])
            )
        story.append(
            Paragraph(
                "<b>3. Sales records</b> — link: invoice / bill of lading number + Lot ID + buyer; organic status as identified on the invoice",
                styles["body"],
            )
        )
        for sale in trail.sales:
            bits = [sale["date"] or "undated", sale["buyer"]]
            if sale["quantity"]:
                bits.append(sale["quantity"])
            if sale["invoice"]:
                bits.append(_labelled("invoice", sale["invoice"], _INVOICE_WRITTEN))
            if sale["bol"]:
                bits.append(_labelled("BOL", sale["bol"], _BOL_WRITTEN))
            bits.append("organic status on invoice: " + ("Yes" if sale["organic_on_invoice"] else "No"))
            if sale["label_category"]:
                bits.append(f"label claim: {sale['label_category']}")
            story.append(Paragraph(_escape("• " + " · ".join(bits)), styles["meta"]))
        story.append(
            Paragraph(
                "Voided sales are not shown. Every line above is a dated record the operation logged; a "
                "link that is missing is reported as missing rather than supplied.",
                styles["meta"],
            )
        )
        story.extend(_lot_balance_flowables(trail.balance, styles))

    # 🔴 2026-09-11 — the one packet document that was built without the wash. A demo farm's
    # packet carried SPECIMEN on every page except these two, which hold the most record-like
    # content in the ZIP: a named lot walked field to sale with invoice and BOL numbers. The
    # surface-coverage guard could not see it because it checks per FILE, and this file already
    # consults common.specimen for its other documents. `test_packet_specimen_every_document`
    # now checks every page of every document in a built packet.
    spec = is_specimen(establishment)
    doc.build(
        story,
        onFirstPage=specimen_page_callback(letter, specimen=spec),
        onLaterPages=specimen_page_callback(letter, specimen=spec),
    )
    return buffer.getvalue()


#: An operator who types the label into the value — "BOL CBF-26-RB-01" in the bill-of-lading
#: field — got it twice: the OTCO desk read (2026-09-10) printed "BOL BOL CBF-26--RB-01..03".
#: The operator's text is never edited; the renderer only skips the label it would have added.
_BOL_WRITTEN = re.compile(r"\s*(?:bol|b/l|bill\s+of\s+lading)\b", re.I)
_INVOICE_WRITTEN = re.compile(r"\s*invoice\b", re.I)


def _labelled(label: str, value: str, written: re.Pattern) -> str:
    """`label value`, unless the value already opens with the label."""
    return value if written.match(value) else f"{label} {value}"


def _packet_parcels(establishment):
    """The operation's parcels in the order it entered them.

    Unordered, the ZIP followed whatever order the database returned: on the WSDA specimen the
    home block printed last, and two builds of the same data put the parcels in different orders.
    """
    return establishment.parcels.order_by("id")


def _parcel_application_filename(parcel) -> str:
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in parcel.name).strip()
    return f"parcels/parcel-application-{safe or parcel.id}.pdf"


def _coverage_location(location: str, parcel_names: list) -> str:
    """The coverage row's location, with the one-per-parcel placeholder made concrete.

    `packet_coverage` speaks for every operation, so it says "<parcel>"; this page speaks for one,
    and printed the placeholder verbatim to a reviewer (WSDA specimen read, 2026-09-11).
    """
    from certifications.services.packet_coverage import PARCEL_APPLICATION_LOCATION

    if PARCEL_APPLICATION_LOCATION not in location:
        return location
    listed = ", ".join(parcel_names) if parcel_names else "none recorded"
    return location.replace(PARCEL_APPLICATION_LOCATION, f"parcels/, one Parcel Application per parcel ({listed})")


def _coverage_pdf(osp) -> bytes:
    """04 — what this packet covers, what it does not, and who authored it.

    CCOF's Guide routes by activity, so a reviewer already knows which forms a crop operation owes.
    Stating what is absent, and why, is the difference between a scope decision and an omission.
    """
    from certifications.services.packet_coverage import (
        coverage_rows,
        exclusion_rows,
        outstanding_modules,
        packet_agent,
        packet_certifier,
        unreviewed_form_count,
    )

    certifier, is_own_agent = packet_certifier(osp)
    # The agent as the records name it. On the fallback path this is the one sentence that tells
    # the reviewer whose packet they are holding: "is not one Trazo holds a register for" used to
    # leave them to guess which agent was meant.
    stated_agent = packet_agent(osp).name
    # A register folder is a slug; a third agent registered as "oregon_tilth" must not print as
    # "OREGON_TILTH" on a document that agent reads.
    agent_label = {"ccof": "CCOF", "wsda": "WSDA", "otco": "Oregon Tilth"}.get(certifier) or certifier.replace(
        "_", " "
    ).title()

    buffer = io.BytesIO()
    styles = _styles()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="Packet coverage")
    story = [
        Paragraph("What this packet covers", styles["title"]),
        Paragraph(_escape(f"{osp.establishment.name} · OSP v{osp.version_number}"), styles["subtitle"]),
        Paragraph(
            "Trazo drafted the documents in this packet from the operation's own records. The "
            "producer is the author of this organic system plan (7 CFR 205.201(a)) and reviews, "
            "corrects and signs it; every compliance determination is the certifying agent's.",
            styles["body"],
        ),
        Spacer(1, 8),
    ]

    rows = coverage_rows(certifier)
    if rows:
        # State the numbering this page speaks, and WHY it is that one. CCOF and WSDA are overlays
        # of the same federal content — 7 CFR 205.201 — so an operation certified by either holds
        # the same documents under its own agent's numbers. When the operation's agent is in the
        # register the page uses those numbers; when it is not, it says which numbering it fell
        # back to instead of letting the reader assume it is theirs.
        story.append(Paragraph("Forms generated in this packet", styles["header"]))
        # No row carries a form number: the register could not be read, so the list below is the
        # packet's own contents with no agent numbering at all. Say that rather than print a
        # sentence claiming numbering the page is not showing.
        has_numbering = any(row.document_id for row in rows)
        story.append(
            Paragraph(
                (
                    "The form-by-form numbering could not be read for this packet, so the "
                    "documents below are listed by filename only. Their content is unchanged."
                    if not has_numbering
                    else (
                        f"Listed against {agent_label}'s own form numbering — the certifying agent on "
                        "this operation's record — which is how a reviewer navigates."
                        if is_own_agent
                        else (
                            (
                                f"This operation's certifying agent, {_escape(stated_agent)}, is not one "
                                "Trazo holds a form register for"
                                if stated_agent
                                else "No certifying agent is named on this operation's records"
                            )
                            + f", so the list is numbered against {agent_label}'s Common OSP. Agents "
                            "package the same 7 CFR 205.201 content under their own form numbers: the "
                            "documents are unchanged and only the numbering differs."
                        )
                    )
                ),
                styles["meta"],
            )
        )
        parcel_names = [p.name for p in _packet_parcels(osp.establishment)]
        for row in rows:
            if not row.generated:
                continue
            # A packet module no form of this agent claims still ships, and still has to be listed
            # — with no number rather than a borrowed one.
            named = f"{row.form} ({row.document_id})" if row.document_id else row.form
            story.append(
                Paragraph(_escape(f"{named} — {_coverage_location(row.location, parcel_names)}"), styles["body"])
            )
        elsewhere = [r for r in rows if not r.generated]
        if elsewhere:
            story.append(Spacer(1, 6))
            # NOT "reviewed in the plan": these are registered in the conformance comparison but
            # have no Trazo module, so nothing about them is answered here.
            story.append(
                Paragraph(
                    f"Compared against, but not generated — file {agent_label}'s own form where it applies",
                    styles["header"],
                )
            )
            for row in elsewhere:
                # The register knows which of these every grower owes. The rest are conditional, and
                # an apple grower was told, without qualification, to file the mushroom section.
                condition = "" if row.required_of_every_grower else " — only where it applies to the operation"
                story.append(Paragraph(_escape(f"{row.form} ({row.document_id}){condition}"), styles["body"]))
        # Draft register entries are counted, never listed: an unfinished comparison must not
        # print as either coverage or an absence. See the DRAFT rule in packet_coverage.
        pending_review = unreviewed_form_count(certifier)
        if pending_review:
            story.append(Spacer(1, 4))
            story.append(
                Paragraph(
                    _escape(
                        # One verb per number: this printed "1 further Oregon Tilth form have
                        # not yet been compared" on the OTCO desk read (2026-09-10).
                        f"{pending_review} further {agent_label} "
                        f"{'form has' if pending_review == 1 else 'forms have'} "
                        "not yet been compared against this plan, and "
                        f"{'is' if pending_review == 1 else 'are'} not stated either way above."
                    ),
                    styles["meta"],
                )
            )
    else:
        story.append(
            Paragraph(
                "The form-by-form coverage list could not be read for this packet. The documents "
                "present are listed on the cover page.",
                styles["body"],
            )
        )

    # The four Common OSP workbooks ship in every packet and this page — whose title is "what
    # this packet covers" — did not mention them, so a reviewer met four spreadsheets the
    # contents page had not led them to expect (2026-09-07). An agent's own sheet (OTCO's
    # FACT-04) is listed only in that agent's packet, the same filter the ZIP applies.
    from certifications.services.common_osp_workbooks import workbooks_for

    sheets = workbooks_for(certifier if is_own_agent else None)
    if sheets:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Workbooks generated in this packet", styles["header"]))
        story.append(
            Paragraph(
                "Spreadsheets in the packet's workbooks/ folder. A printed or merged copy of the PDFs does not "
                "include them.",
                styles["meta"],
            )
        )
        for spec in sheets:
            story.append(
                Paragraph(
                    _escape(f"{spec.title} — workbooks/{_workbook_filename(spec)}"),
                    styles["body"],
                )
            )

    exclusions = exclusion_rows(certifier)
    if exclusions:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Forms Trazo does not generate", styles["header"]))
        story.append(
            Paragraph(
                "File these directly with your certifying agent where they apply to this "
                "operation. They are listed so their absence from this packet is a stated "
                "scope, not an oversight.",
                styles["meta"],
            )
        )
        for row in exclusions:
            label = f"{row.form}" + (f" ({row.document_id})" if row.document_id else "")
            story.append(Paragraph(f"<b>{_escape(label)}</b>", styles["body"]))
            story.append(Paragraph(_escape(row.reason), styles["meta"]))

    pending = outstanding_modules(osp)
    if pending:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Sections of this plan still to finish", styles["header"]))
        story.append(
            Paragraph(
                "Listed by the operation, for the operation — a reviewer finding these first is "
                "worse than the operation naming them.",
                styles["meta"],
            )
        )
        for name in pending:
            story.append(Paragraph(f"• {_escape(name)}", styles["body"]))

    # Same specimen authority as every other packet document (common/specimen.py): a demo
    # operation's coverage page must be as unmistakably marked as its records.
    spec = is_specimen(getattr(osp, "establishment", None))
    doc.build(
        story,
        onFirstPage=specimen_page_callback(letter, specimen=spec),
        onLaterPages=specimen_page_callback(letter, specimen=spec),
    )
    return buffer.getvalue()


def _refresh_narratives_if_editable(osp) -> None:
    """Recompile § 205.201(a) before assembling the packet, on plans that may still change.

    🔴 Found 2026-08-28 by generating the pilot's real packet and reading it: the same ZIP listed
    "Rexius Organic Compost" in `modules/materials_application.pdf` and omitted it from the
    (a)(2) narrative two files away. One packet, two answers — the exact defect
    `plan_materials()` was written to end, arriving through a door nobody had closed.

    The cause is structural, not local. `osp.sections` is STORED prose, and the only writers that
    recompiled it were the ones that change module ANSWERS (the module PUT, the sections PATCH,
    submit). But the compiler also reads three catalogue M2Ms, the operator-authored materials
    table and the establishment's post-harvest facilities — none of which live in module answers,
    and two of which are edited on entirely different screens (the approved-inputs panel; a
    production's post-harvest section). Adding a handler on the production page left the (a)(5)
    paragraph stale with nothing to warn you.

    Fixing each writer would fix today's writers. Recompiling here fixes the packet for every
    writer, including the next thing the compiler learns to read — the same reason claim decisions
    live at one chokepoint rather than at each call site.

    ⛔ EDITABLE PLANS ONLY. A submitted or superseded plan's sections are the text that was FILED;
    its frozen `submission_pdf` is "the exact content the certifier receives". Recompiling those
    would rewrite history. `compile_modules_to_sections` is idempotent and reports whether
    anything actually changed, so a no-op costs one comparison and no write.
    """
    if getattr(osp, "status", None) not in ("draft", "active"):
        return
    try:
        from certifications.services.osp_module_compiler import compile_modules_to_sections

        if compile_modules_to_sections(osp):
            osp.save(update_fields=["sections", "updated_at"])
    except Exception:  # noqa: BLE001 — a stale narrative is bad; no packet at all is worse
        logger.exception("Could not refresh narratives before assembling the packet for OSP %s", osp.pk)


def generate_osp_packet(osp) -> bytes:
    """Assemble the renewal packet ZIP. Single source of packet content."""
    _refresh_narratives_if_editable(osp)
    establishment = osp.establishment
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00-cover.pdf", _packet_cover_pdf(osp))
        # "01-organic-system-plan.pdf", not "01-narrative-snapshot.pdf" (2026-09-07). This file
        # IS the organic system plan — the § 205.201(a) narratives plus the § 205.401(d)
        # producer attestation — and it is the document a reviewer opens the ZIP looking for.
        # "Narrative snapshot" describes how we build it (a frozen copy of the narratives at
        # submission), which is our vocabulary, not theirs. The frozen-version meaning is not
        # lost: the page itself is subtitled "Submission Snapshot" and carries the version.
        zf.writestr("01-organic-system-plan.pdf", generate_osp_snapshot_pdf(osp))
        # The two documents a renewal IS, and which the "renewal packet" did not contain until
        # 2026-08-23: the § 205.406(a) filing and the § 205.400(f) notices that support it.
        zf.writestr("02-annual-update.pdf", _annual_update_pdf(osp))
        zf.writestr("03-change-notifications.pdf", _change_notifications_pdf(osp))
        # 04 — scope. CCOF's Guide routes by activity, so what is missing is as readable as what
        # is present; this states it rather than leaving a reviewer to infer an omission.
        zf.writestr("04-coverage-and-scope.pdf", _coverage_pdf(osp))
        # 05 — the § 205.103(b)(2) trace, generated (2026-09-09): the document table OTCO C12 Q6
        # asks for and the sample audit trail CCOF G8.0 B1 asks to attach.
        zf.writestr("05-audit-trail-exhibit.pdf", _audit_trail_exhibit_pdf(osp))
        for module in MODULE_REGISTRY:
            code = (module.code or module.key).replace(".", "_")
            zf.writestr(
                f"modules/{code}.pdf",
                generate_module_pdf(osp, module.key),
            )
        for parcel in _packet_parcels(establishment):
            zf.writestr(
                _parcel_application_filename(parcel),
                generate_module_pdf(osp, PARCEL_APPLICATION.key, parcel=parcel),
            )
        # The agent-neutral USDA sheets always; an agent's own sheet (OTCO FACT-04) only when the
        # packet is numbered to that agent — the coverage page applies the same filter.
        from certifications.services.packet_coverage import packet_certifier

        agent, is_own = packet_certifier(osp)
        for spec in workbooks_for(agent if is_own else None):
            workbook = build_workbook(establishment, spec.key, osp=osp)
            zf.writestr(f"workbooks/{_workbook_filename(spec)}", workbook.getvalue())

        # Operator-supplied parcel maps (2026-08-28). CCOF NOPB49 §E requires the map reviewed
        # BEFORE a new parcel is inspected and WSDA AGR 2264 requires one with every site
        # application — a mandatory attachment that never rode in the packet. The Parcel
        # Application PDF names the file it expects to find here, so the two agree or neither
        # does. Same loop shape as receipts below, and outside the workbook loop for the same
        # reason: inside it, every file would be written once per workbook.
        for _parcel in establishment.parcels.all():
            for _map_doc in parcel_map_documents(_parcel):
                try:
                    with _map_doc.file.open("rb") as _fh:
                        _map_data = _fh.read()
                except Exception:  # noqa: BLE001 — a missing file must not sink the packet
                    logger.exception("Parcel map %s could not be read into the packet", _map_doc.pk)
                    continue
                zf.writestr(f"parcels/maps/{_parcel_map_upload(_parcel)}", _map_data)
                break  # the newest map is the one the Parcel Application names

        # Signed prior-manager affidavits (2026-09-09). CCOF Parcel Application §G and OTCO C2 2.5
        # ask for the signed affidavit itself; the parcel page's table names the exact path each
        # file rides under, so the page and the ZIP agree or neither does.
        from certifications.services.parcel_land_history import affidavit_attachment_name

        for _parcel in establishment.parcels.all():
            for _aff in _parcel.landowner_affidavits.all():
                _name = affidavit_attachment_name(_aff)
                if not _name:
                    continue
                try:
                    with _aff.signed_document.open("rb") as _fh:
                        _aff_data = _fh.read()
                except Exception:  # noqa: BLE001 — a missing file must not sink the packet
                    logger.exception("Affidavit %s could not be read into the packet", _aff.pk)
                    continue
                zf.writestr(f"parcels/affidavits/{_name}", _aff_data)

        # Purchase receipts (2026-08-25): every uploaded receipt FILE referenced by a
        # chemical or soil event rides in the packet verbatim. The audit tables mark
        # the matching rows "[receipt on file]" — the number on the record and the
        # paper behind it finally travel together. (Outside the workbook loop: the
        # first cut sat inside it and wrote every receipt once per workbook.)
        from history.models import ChemicalEvent as _ChemEv
        from history.models import SoilManagementEvent as _SoilEv

        _receipt_docs = {}
        for _model in (_ChemEv, _SoilEv):
            for _ev in _model.objects.filter(
                history__parcel__establishment=osp.establishment,
                receipt_document__isnull=False,
            ).select_related("receipt_document"):
                _receipt_docs[_ev.receipt_document_id] = _ev.receipt_document
        for _doc in _receipt_docs.values():
            try:
                with _doc.file.open("rb") as _fh:
                    _data = _fh.read()
            except Exception:
                continue  # a missing file must not sink the whole packet
            _ext = ("." + _doc.file.name.rsplit(".", 1)[-1]) if "." in _doc.file.name else ""
            _safe_title = (_doc.title or "receipt").replace("/", "-")[:60]
            zf.writestr(f"receipts/{_doc.pk}-{_safe_title}{_ext}", _data)
    return out.getvalue()
