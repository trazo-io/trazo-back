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
from certifications.osp_modules.conditions import (
    answer_value,
    effective_value,
    is_answered,
    visible_pages,
    visible_questions,
)
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


def _option_review_lines(osp, module, question, value) -> list:
    """[REVIEW] lines for the chosen options of a choice question (`Option.review`, and
    `Option.requires_upload` when nothing is filed to that upload question)."""
    from certifications.services.packet_attachments import ATTACHED, current_manifest

    if not question.options:
        return []
    chosen = set(value) if isinstance(value, (list, tuple)) else {value}
    lines = []
    for option in question.options:
        if option.value not in chosen:
            continue
        if option.review:
            lines.append(f"[REVIEW] {option.review}")
        if option.requires_upload:
            requirement = f"{module.key}.{option.requires_upload}"
            # Inside a packet build the manifest decides, like the upload questions do (OSP
            # alignment audit T19): a filed document that could not be read or did not fit is not
            # in the ZIP, so the answer is not backed by what the certifier receives.
            manifest = current_manifest()
            if manifest is not None:
                if not any(e.state == ATTACHED for e in manifest.for_requirement(requirement)):
                    lines.append(
                        f"[REVIEW] The answer says it is attached ({_en(option.label)}), but this "
                        "packet carries no file for it."
                    )
            elif not osp.establishment.documents.filter(requirement=requirement).exists():
                lines.append(
                    f"[REVIEW] The answer says it is attached ({_en(option.label)}), but no file is "
                    "attached to this plan for it."
                )
    return lines


def _answer_evidence_lines(osp, question, value, bundles: dict) -> list:
    """What is logged in Trazo for the chosen options that name a kind of record (`Option.evidence`).

    One evidence bundle per PDF, built on first use: most modules declare no evidence."""
    if not question.options:
        return []
    chosen = set(value) if isinstance(value, (list, tuple)) else {value}
    keys = [o.evidence for o in question.options if o.evidence and o.value in chosen]
    if not keys:
        return []
    from certifications.services.common_osp_records import ANSWER_EVIDENCE, EvidenceBundle

    try:
        if "bundle" not in bundles:
            bundles["bundle"] = EvidenceBundle(osp.establishment)
        return [ANSWER_EVIDENCE[key].sentence(bundles["bundle"]) for key in keys]
    except Exception:  # noqa: BLE001 — a count that cannot be read must not sink the packet
        logger.exception("Answer evidence could not be counted for %s", question.key)
        return ["In Trazo: these records could not be counted."]


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


def _missing_required_flowables(osp, styles) -> list:
    """The records this plan's OWN answers require that are not confirmed, each named with its state
    (OSP alignment audit T17-F1). CCOF G8.0 A1 asks for every record the activities need; the
    confirmed list alone cannot show which of those are missing.

    Rendered whether or not anything is confirmed: with nothing confirmed, every required record is
    missing, which is the case this exists for (review of back #84). Guarded like the registry
    itself: a failure here must not sink the packet.
    """
    from certifications.services.required_records import NOT_KEPT, UNRESOLVED, missing_required

    try:
        missing = missing_required(osp)
    except Exception:  # noqa: BLE001 — a derivation failure must not sink the whole packet
        logger.exception("Required record types could not be derived for OSP %s", getattr(osp, "pk", None))
        return []
    if not missing:
        return []
    out = [
        Paragraph(
            "<b>Records this plan's activities require that are not confirmed above</b>",
            styles["body"],
        )
    ]
    for record in missing:
        if record.state == NOT_KEPT:
            why = f"the operation states it does not keep this record ({record.reason})"
        elif record.state == UNRESOLVED:
            why = f"not yet decided: {record.because}"
        else:
            why = f"not confirmed; required because {record.because}"
        out.append(Paragraph(_escape(f"• {record.label}: {why}"), styles["body"]))
    return out


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
            *_missing_required_flowables(osp, styles),
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
    out.extend(_missing_required_flowables(osp, styles))
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
        # The copy itself: CCOF G6.1 C3 and OTCO C7 7.10-3 ask for it attached. In a packet it rides
        # under handlers/ and this line names the path, or says why it is not in the packet.
        if facility.cert_document:
            from certifications.services.packet_attachments import (
                current_manifest,
                facility_certificate_source,
                state_words,
            )

            manifest = current_manifest()
            entries = manifest.for_source(facility_certificate_source(facility)) if manifest else []
            line = (
                state_words(entries[0])
                if entries
                else "A copy of the certificate is held in Trazo; it is not included in this document."
            )
        else:
            line = "No copy of the certificate is held in Trazo."
        out.append(Paragraph(_escape(line), styles["meta"]))
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
        # been added…", which reads as an UNFINISHED list (OTCO C11 Hdr-2, CCOF ORGB41 Header C).
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
            # Decisions are made on logged events, which a "none used" answer does not remove
            # (review of back #109).
            out += _withdrawn_by_operator_flowables(osp, styles)
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
            *_withdrawn_by_operator_flowables(osp, styles),
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
    out += _withdrawn_by_operator_flowables(osp, styles)
    out.append(Spacer(1, 6))
    return out


def _withdrawn_by_operator_flowables(osp, styles) -> list:
    """Identity decisions and restriction statements the operator withdrew (run 6c, R6c-01).

    The current-state readers drop a withdrawn row, so without this a reviewer could not tell a name
    never decided from one asserted and then taken back. Stated when there are none, so the absence
    is read rather than inferred."""
    from certifications.services.material_identity import withdrawn_decision_lines
    from certifications.services.material_restrictions import withdrawn_statement_lines

    lines = withdrawn_decision_lines(osp) + withdrawn_statement_lines(osp)
    out = [Spacer(1, 4), Paragraph("<b>Decisions withdrawn by the operator</b>", _sticks_to_next(styles["body"]))]
    if not lines:
        out.append(
            Paragraph("No material identity decision or restriction statement has been withdrawn.", styles["meta"])
        )
        return out
    for line in lines:
        out.append(Paragraph(f"• {_escape(line)}", styles["meta"]))
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
            f"[REVIEW] {len(unmatched)} logged product name(s) are not confirmed against "
            "an entry above: " + _escape(listed) + ". A brand name and the substance entry that "
            "covers it read differently, so some of these may already be accounted for — "
            "confirm each one on the plan's identity panel (Logged names not on the plan) and add "
            "anything genuinely missing."
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
    from certifications.services.packet_attachments import safe_title

    return f"{doc.pk}-{safe_title(doc.title, 'map')}{ext}"


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


def _parcel_assessment(parcel, osp):
    """The certified-branch assessment this parcel page prints: for the packet's plan (its agent and
    version) when there is one, else for the plan the operator is working on. The summary line, the
    route, the land-history accounting and page 04 all call through here or `assess_for_plan`, so they
    cannot answer for two different plans (run 3, R3-05)."""
    from certifications.services import certified_parcel_branch as cpb

    return cpb.assess_for_wizard(parcel) if osp is None else cpb.assess_for_plan(parcel, osp)


def _parcel_embed_flowables(embed: str, parcel, styles, osp=None) -> list:
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
        # The records line and the operator's statements are separate lines. Until 2026-09-30 a
        # "yes" to currently_certified rewrote the verdict into a sentence about inputs the
        # operator never declared (audit T21). See operator_statement_lines().
        from product.services.transition_status_service import operator_statement_lines

        out.append(Paragraph(_escape(f"Organic transition status: {transition_verdict(status)}"), styles["body"]))
        for line in operator_statement_lines(parcel):
            out.append(Paragraph(_escape(line), styles["body"]))
        if status.note:
            out.append(Paragraph(_escape(status.note), styles["meta"]))

    elif embed == "certified_branch":
        # OSP alignment audit T21-F1. The route the selected agent's form takes for a currently
        # certified parcel, and what is on file for it. Availability only; never acceptance.
        from certifications.services import certified_parcel_branch as cpb

        assessment = _parcel_assessment(parcel, osp)
        if assessment is not None:
            route_line, *rest = cpb.lines(assessment)
            out.append(Paragraph(_escape(route_line), _style(styles, "meta")))
            for line in rest:
                out.append(Paragraph(_escape(line), styles["body"]))

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
        # CCOF ORGB49 §E requires the map ATTACHED and reviewed before a new parcel is
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
        from certifications.services.packet_attachments import ATTACHED, PARCEL_MAP_REQUIREMENT, current_manifest

        manifest = current_manifest()
        shipped = manifest.for_requirement(PARCEL_MAP_REQUIREMENT, parcel_id=parcel.pk) if manifest else []
        if uploaded and shipped and shipped[0].state != ATTACHED:
            # Uploaded, but the bytes did not make it into this ZIP. Saying "attached" here was
            # the old behaviour: the page named a file the reader would not find (T19).
            out.append(
                Paragraph(
                    _escape(
                        f"The operator's map for this parcel is not in this packet: {shipped[0].detail}. "
                        "It is in Trazo's document store."
                    ),
                    _style(styles, "meta"),
                )
            )
        elif uploaded:
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
        # Dated input events beside each year (WSDA AGR 2264 ref 13; audit T17-F2). The typed
        # history's dates are free text and stay labelled as typed; these come from dated records.
        from product.services.input_evidence import describe, parcel_inputs

        dated_inputs = parcel_inputs(parcel)
        # Each dated input prints ONCE: under the first land-history line of its year (a split
        # field has one line per block for the same year), or in the closing list when no line
        # carries its year. Joining on the year alone printed it once per block and dropped any
        # input whose year had no line (review of back #83).
        printed_years = set()
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
                            f"applied {dates or 'date not recorded'} (typed)"
                        ),
                        _style(styles, "meta"),
                    )
                )
            if row.year not in printed_years:
                printed_years.add(row.year)
                for record in (r for r in dated_inputs if r.day.year == row.year):
                    out.append(Paragraph(_escape(f"— {describe(record)} (dated record)"), _style(styles, "meta")))
        unplaced = [r for r in dated_inputs if r.day.year not in printed_years]
        if unplaced:
            out.append(
                Paragraph(
                    "Dated input records in years with no land-history line above:",
                    styles["body"],
                )
            )
            for record in unplaced:
                out.append(Paragraph(_escape(f"— {describe(record)} (dated record)"), _style(styles, "meta")))
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
        from certifications.services import certified_parcel_branch as cpb

        certified_route = None
        if cpb.is_certified(parcel):
            certified_route = _parcel_assessment(parcel, osp)
        # The same assessment the page prints decides whether an attached verification counts.
        account = coverage(parcel, prior, assessment=certified_route)
        # Only a route that does not ask for it replaces the accounting. An undetermined one (unresolved,
        # or an agent Trazo does not assess) prints it in full (run 3, R3-06).
        if certified_route is not None and certified_route.land_history_asked is False:
            # T21-F1: on this route the agent's form does not ask for the 36-month accounting, so it
            # is not printed as a demand. The table below stays as the record of who managed the land.
            out.append(Paragraph(_escape(cpb.COVERAGE_NOT_ASKED_TEXT), styles["body"]))
        else:
            out.append(Paragraph(_escape(account.text), styles["body"]))
        from certifications.services.parcel_land_history import season_evidence_lines

        seasons = season_evidence_lines(parcel)
        if seasons:
            out.append(
                Paragraph(
                    "Seasons logged in Trazo on this parcel inside the window, listed as supporting records "
                    "(the accounting above rests only on the statements and documents it names):",
                    _style(styles, "meta"),
                )
            )
            for line in seasons:
                out.append(Paragraph(_escape(f"• {line}"), _style(styles, "meta")))
        if not prior:
            out.append(
                Paragraph(
                    "No prior-manager affidavit on file for this parcel; the table lists the current manager only.",
                    _sticks_to_next(styles["body"]),
                )
            )

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
            # The parcel's own certificate upload (certified branch) is the copy in this packet. Saying
            # "not attached" above a line that names it attached read as a contradiction (2026-10-31).
            from certifications.services import certified_parcel_branch as cpb

            # Only on the operation's own certificate: on a transfer, or land certified under another
            # operation, the parcel's upload is that operation's certificate (review of back #251).
            assessment = _parcel_assessment(parcel, osp)
            # `route_for` reaches wsda_transfer / otco_transfer only from another operation's branch.
            own = assessment is not None and assessment.branch == cpb.EXISTING_SITE
            copy = next(
                (
                    item
                    for item in (assessment.items if own else [])
                    if item.key == cpb.CERTIFICATE and item.state == cpb.ATTACHED
                ),
                None,
            )
            if line.document_url:
                document = f"Certificate document: {line.document_url}"
            elif copy is not None:
                document = f"Certificate document: a copy is attached at {copy.path}."
            else:
                document = (
                    "Certificate document: not attached to this packet — the issued certificate is the "
                    "certifier's own record."
                )
            out.append(
                Paragraph(
                    _escape(document),
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


#: Evidence keys → what a certifier reads. Kept beside the renderer, not in the service: the
#: service names FACTS (`operator_map`), a reviewer needs a phrase. ⛔ None of these asserts that
#: the evidence satisfies any agent's requirements — that determination is the agent's.
EVIDENCE_LABELS = {
    "map": "no field map on file",
    "operator_map": "no operator-supplied map attached",
    "map_geometry_disagrees_with_area": "recorded geometry disagrees with the stated parcel area",
    "affidavit_document": "landowner affidavit recorded but not signed",
    # Run 3, R3-05: the certified route's items, in words. The draft packet printed the keys.
    "certified_certificate": "no copy of the certificate attached or referenced",
    "certified_continuity": "no verification of no lapse attached or referenced",
    "certified_prior_manager": "no signed document from every prior manager",
}

#: The answered-question checks, for the "N of M" the header prints. Mirrors the service's own
#: list; `test_parcel_two_axes.py` fails if the two drift.
PARCEL_APPLICATION_CHECKS = (
    "identity",
    "transition",
    "buffers",
    "land_history",
    "certification_status",
)


def _question_label(module, page, question, styles):
    """The bold label of an answered question. It records the page it lands on during a packet build,
    for the question index (T24); outside one it is an ordinary paragraph."""
    from certifications.services.packet_index_recorder import QuestionLabel

    label = _en(question.label)
    return QuestionLabel(
        f"<b>{_escape(label)}</b>",
        styles["label"],
        anchor=(module.key, question.key, _en(page.title), label),
    )


#: Optional "kept elsewhere, say where" questions that stand in for a file. The certified-parcel card
#: already prints each file's state ("none attached or referenced"), so listing the blank reference
#: as an open question says the same thing twice.
_STANDS_IN_FOR_A_FILE = {
    "parcel_application.certificate_reference",
    "parcel_application.continuity_reference",
}

#: Upload requirements the packet answers with a document it generates, so an empty upload is not an
#: open question. The question's own coaching says the exhibit is already in the packet.
_GENERATED_FOR_UPLOAD = {"g8_0_record_keeping.audit_trail_exhibit": "05-audit-trail-exhibit.pdf"}


def _page_does_not_apply(module, page, answers) -> str:
    """Why a page of the module is not printed, worded from the condition that hides it."""
    conds = tuple(getattr(page, "visible_when", ()) or ())
    if not conds:
        return "Does not apply to this operation."
    questions = {q.key: q for p in module.pages for q in p.questions}
    phrases = []
    for cond in conds:
        trigger = questions.get(cond.question)
        if trigger is None:
            continue
        label = _en(trigger.label).rstrip("?.: ")
        if answer_value(answers, cond.question) in (None, "", []):
            # Hidden because the deciding question is open, not because the answer rules it out.
            return f"Not shown until “{label}” is answered."
        names = {o.value: _en(o.label) for o in trigger.options}
        values = cond.value if isinstance(cond.value, (list, tuple)) else [cond.value]
        shown = " or ".join(names.get(v, str(v)) for v in values if v is not None)
        if cond.op == "truthy":
            phrases.append(f"the answer to “{label}” is Yes")
        elif cond.op == "falsy":
            phrases.append(f"the answer to “{label}” is No")
        elif cond.op in ("includes", "includes_any"):
            phrases.append(f"the answer to “{label}” includes {shown}")
        elif cond.op in ("eq", "one_of"):
            phrases.append(f"the answer to “{label}” is {shown}")
        elif cond.op == "ne":
            phrases.append(f"the answer to “{label}” is not {shown}")
        elif cond.op == "not_includes":
            phrases.append(f"the answer to “{label}” does not include {shown}")
    if not phrases:
        return "Does not apply to this operation."
    return "Does not apply: asked only when " + " and ".join(phrases) + "."


def _attester_name(user_id) -> str:
    """The name of the account that attested a module N/A, or "the operator" when it has none."""
    from users.models import User

    # The write path stores an int; anything else (an older email-shaped value) names nobody and must
    # not take down the packet build.
    user = User.objects.filter(pk=user_id).first() if str(user_id or "").isdigit() else None
    name = (user.get_full_name() or "").strip() if user is not None else ""
    return name or "the operator"


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
        #
        # 🔴 2026-09-24 — TWO AXES, BOTH PRINTED.
        #
        # This line said "Parcel application: complete" from the answered-questions verdict
        # alone, one page above section E's own "[REVIEW] No operator-supplied map is attached".
        # A reviewer reading the header had no reason to keep reading, which is precisely the
        # failure mode: the header was the more confident of the two statements and the wrong
        # one. Evidence now rides beside it, always, and neither axis can claim the other.
        _status = parcel_application_status(parcel, osp=osp)
        _answers_state = _status["answers_state"].replace("_", " ")
        _answered = len(PARCEL_APPLICATION_CHECKS) - len(_status["answers_missing"])
        _line = (
            f"Parcel application \u2014 answers: {_answers_state} " f"({_answered} of {len(PARCEL_APPLICATION_CHECKS)})"
        )
        _evidence_missing = _status["evidence_missing"]
        if _evidence_missing:
            _labels = ", ".join(EVIDENCE_LABELS.get(k, k) for k in _evidence_missing)
            _count = len(_evidence_missing)
            _line += (
                f"  \u00b7  Supporting evidence: {_count} item" f"{'' if _count == 1 else 's'} outstanding ({_labels})"
            )
        else:
            _line += "  \u00b7  Supporting evidence: on file"
        from certifications.services.certified_parcel_branch import ROUTE_UNDETERMINED_SUMMARY

        _detail = _status.get("evidence_detail") or {}
        if _detail.get("certified_route_undetermined"):
            # Run 4, R4-01: the count above is what is on file, not the full set this agent asks for.
            _why = ROUTE_UNDETERMINED_SUMMARY.get(_detail.get("certified_route"), "certified route not determined")
            _line += f"  \u00b7  {_why[0].upper()}{_why[1:]}"
        entry = {"status_line": _line}
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
        if isinstance(na_attestation, dict) and na_attestation:
            # `by` is a user id and `at` a full ISO timestamp; printed raw they read "attested by 163
            # on 2026-08-21T11:28:47.145805+00:00" (production packet, 2026-10-29).
            who = _attester_name(na_attestation.get("by"))
            when = str(na_attestation.get("at") or "")[:10]
            stamp = f" (attested by {who}" + (f" on {when})" if when else ")")
        na_text = _en(module.na_label) or "Reviewed — does not apply to this operation."
        # The N/A label often opens with the same words ("Not applicable — no wild crops are harvested").
        for lead in ("Not applicable — ", "Not applicable: ", "Not applicable. "):
            if na_text.startswith(lead):
                na_text = na_text[len(lead) :]
                na_text = na_text[:1].upper() + na_text[1:]
                break
        story.append(Paragraph(_escape(f"Not applicable{stamp}: {na_text}"), styles["body"]))
    else:
        pairs = visible_questions(module, answers)
        # Where the "nothing answered" line goes, so it leads the questions it summarises instead of
        # following a list of them (review of back #249).
        body_start = len(story)
        answered_any = False
        evidence_bundles: dict = {}
        shown_pages: set = set()
        live_pages = {p.key for p in visible_pages(module, answers)}

        def open_page(page):
            """Print the page heading once, after the heading of every earlier page that does not
            apply. A page hidden by an answer was dropped silently, so the letters jumped (G3.0 went
            C to E; production specimen packet, 2026-10-29)."""
            if page.key in shown_pages:
                return
            for earlier in module.pages:
                if earlier.key == page.key:
                    break
                if earlier.key not in shown_pages and earlier.key not in live_pages:
                    story.append(Paragraph(_escape(_en(earlier.title)), styles["header"]))
                    story.append(Paragraph(_escape(_page_does_not_apply(module, earlier, answers)), styles["meta"]))
                    shown_pages.add(earlier.key)
            story.append(Paragraph(_escape(_en(page.title)), styles["header"]))
            shown_pages.add(page.key)

        # Where the plan's own agent asks a question Trazo leaves optional. Blank, it was printed
        # "(optional)", which told the reviewer the agent did not need it either. Farm-wide modules
        # only; a parcel's page is checked against its own route.
        from certifications.services.agent_question_refs import agent_asks, asks_sentence, blank_asked_questions

        asks = agent_asks(osp) if parcel is None else None
        asked_here = asks[1].get(module.key, {}) if asks else {}
        blank_asked = set(blank_asked_questions(module, {"answers": answers}, asked_here))

        def asked_words(question) -> str:
            # Only the rows that ask it: never an item the form prints optional.
            return asks_sentence(asks[0], asked_here[question.key])

        def open_line(page, question, words):
            open_page(page)
            story.append(Paragraph(f"<b>{_escape(_en(question.label))}</b>", styles["label"]))
            story.append(Paragraph(_escape(words), styles["meta"]))
            story.append(Spacer(1, 6))

        for page, question in pairs:
            # Embedded panels (§ 11 registry, approved inputs, the Parcel Application's
            # § 205.202 evidence) carry no `answers` value — they render from live records.
            # They were skipped wholesale until 2026-08-09, which left modules attesting to
            # "the records confirmed above" and "the materials list above" with nothing
            # above. ONE dispatch point: `test_every_embed_has_a_renderer` fails if a new
            # embed lands without a branch here.
            if question.embed:
                if parcel is not None:
                    rendered = _parcel_embed_flowables(question.embed, parcel, styles, osp=osp)
                elif question.embed == "s11_record_types":
                    rendered = _record_registry_flowables(osp, styles)
                elif question.embed == "approved_inputs":
                    rendered = _approved_inputs_flowables(osp, styles)
                elif question.embed == "post_harvest_facilities":
                    rendered = _post_harvest_facility_flowables(osp, styles)
                else:
                    rendered = []
                if rendered:
                    open_page(page)
                    answered_any = True
                    story.extend(rendered)
                continue
            if question.kind == "upload":
                # The files this packet carries for the requirement, by their ZIP path, and any it
                # could not carry, by name (OSP alignment audit T19). Printed only inside a packet
                # build: a module PDF downloaded on its own ships no files, so naming a path
                # there would point at nothing.
                from certifications.services.packet_attachments import current_manifest, state_words

                manifest = current_manifest()
                if parcel is not None:
                    # A parcel's map is reported in the map section, against this parcel.
                    entries = []
                else:
                    entries = manifest.for_requirement(f"{module.key}.{question.key}") if manifest else []
                if entries:
                    open_page(page)
                    answered_any = True
                    story.append(_question_label(module, page, question, styles))
                    for entry in entries:
                        story.append(Paragraph(_escape(f"• {state_words(entry)}"), styles["body"]))
                elif manifest is not None and parcel is None:
                    # Inside a packet build, a requirement with no file is open like any unanswered
                    # question (review of back #249). Outside one nothing is shipped, so nothing is said.
                    generated = _GENERATED_FOR_UPLOAD.get(f"{module.key}.{question.key}")
                    if generated:
                        open_page(page)
                        story.append(Paragraph(f"<b>{_escape(_en(question.label))}</b>", styles["label"]))
                        story.append(
                            Paragraph(
                                _escape(
                                    f"Generated in this packet as {generated}; no file of the operation's own is attached."
                                ),
                                styles["meta"],
                            )
                        )
                        story.append(Spacer(1, 6))
                    elif question.required:
                        open_page(page)
                        story.append(Paragraph(f"<b>{_escape(_en(question.label))}</b>", styles["label"]))
                        story.append(Paragraph("No file is attached for this in the packet.", styles["meta"]))
                        story.append(Spacer(1, 6))
                    elif question.key in asked_here:
                        open_line(page, question, f"No file attached. {asked_words(question)}")
                    else:
                        open_line(page, question, "No file attached (optional).")
                continue
            if question.kind == "info":
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
                # A question with no answer is named, never dropped: a module that printed only its
                # answers read as complete while the coverage page called the section unfinished, and
                # for an agent with no question register nothing else in the packet says which
                # question is open (production packet, 2026-10-29). A plain paragraph, not a
                # `QuestionLabel`: the question index reads those as the places answers are printed.
                if question.parcel_field:
                    continue
                if question.required:
                    open_page(page)
                    story.append(Paragraph(f"<b>{_escape(_en(question.label))}</b>", styles["label"]))
                    story.append(Paragraph("Not yet answered.", styles["meta"]))
                    story.append(Spacer(1, 6))
                elif question.key in blank_asked:
                    open_line(page, question, f"Not yet answered. {asked_words(question)}")
                elif f"{module.key}.{question.key}" not in _STANDS_IN_FOR_A_FILE:
                    open_line(page, question, "Not answered (optional).")
                continue
            open_page(page)
            answered_any = True
            story.append(_question_label(module, page, question, styles))
            story.append(Paragraph(_escape(_format_answer_en(question, value)), styles["body"]))
            # Declared on the options themselves: what the certifier should look at when this answer
            # is chosen, and whether an option that says a file is attached has one.
            for line in _option_review_lines(osp, module, question, value):
                story.append(Paragraph(_escape(line), styles["meta"]))
            for line in _answer_evidence_lines(osp, question, value, evidence_bundles):
                story.append(Paragraph(_escape(line), styles["meta"]))
            # An attestation stored before the gate existed can still be affirmative over an empty
            # list. The API refuses to write one now, but a plan attested earlier keeps it, and
            # printing a bare "Yes" under a section that says "no record types have been confirmed"
            # is the contradiction this whole fix is about. Qualify it rather than hide it: the
            # answer is the operator's and stays visible.
            if getattr(question, "attests_embed", None) and value is True:
                from certifications.services.attestation_gates import blocked_attestations

                if blocked_attestations(module, {question.key: True}, osp):
                    from certifications.services.attestation_gates import _EMBED_EMPTINESS
                    from certifications.services.required_records import describe_missing, missing_required

                    # The empty list is the older, plainer defect and keeps its own sentence.
                    is_empty = _EMBED_EMPTINESS.get(question.attests_embed, (lambda _osp: False, ""))[0]
                    missing = [] if is_empty(osp) else missing_required(osp)
                    story.append(
                        Paragraph(
                            _escape(
                                (
                                    "[REVIEW] This Yes was given before the statement covered every record "
                                    "the plan's activities require, and these are not confirmed: "
                                    f"{describe_missing(missing)}. It is not supported by the plan as it stands."
                                )
                                if missing
                                else (
                                    "[REVIEW] Nothing in the list above is confirmed, so this attestation "
                                    "is not supported by the plan as it stands."
                                )
                            ),
                            styles["meta"],
                        )
                    )
            # An option that has since been replaced still prints as it was chosen, so the plan
            # reads as answered. The question it answered was narrower than the one asked now.
            if not is_answered(effective_value(question, value)):
                story.append(
                    Paragraph(
                        "[REVIEW] Answered with an option this question no longer offers. The current "
                        "question asks more than that option said, and the operator has not yet "
                        "confirmed an answer to it.",
                        styles["meta"],
                    )
                )
            story.append(Spacer(1, 6))
        if not answered_any:
            story.insert(body_start, Paragraph("No answers recorded for this module yet.", styles["body"]))
        # Pages after the last one printed that do not apply, so the letters run to the end.
        for page in module.pages:
            if page.key not in shown_pages and page.key not in live_pages:
                story.append(Paragraph(_escape(_en(page.title)), styles["header"]))
                story.append(Paragraph(_escape(_page_does_not_apply(module, page, answers)), styles["meta"]))
                shown_pages.add(page.key)

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


def _count_phrase(n: int, noun: str, plural: str = "") -> str:
    """'1 addition', '3 additions', 'no deletions'. Not 'addition(s)', which is a form's grammar.
    `plural` for a noun that does not take an "s" ("entry" / "entries")."""
    many = plural or f"{noun}s"
    if not n:
        return f"no {many}"
    return f"{n} {noun if n == 1 else many}"


#: The § 205.406(a)(3) answer, kept beside the section attestations it resembles: a dated
#: statement by the operator that something is unchanged since the prior update. Not a
#: § 205.201(a) section, so it is never listed among them.
APPLICATION_INFO_KEY = "application_information"


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
    from certifications.services.annual_update_filing import packet_filing, renewal_packet_filing
    from certifications.services.operation_certificate import certificate_of_record

    est = osp.establishment
    filing = renewal_packet_filing(osp)
    other_filing = None
    if filing is None:
        # Scoped through `prior_osp` — the same relation `OSPAnnualUpdateViewSet.get_queryset`
        # scopes by, so the packet and the OSP screen agree on what "this operation has filed"
        # means. Ordered newest-year-first; ties broken by filing date, then id.
        other_filing = packet_filing(
            OSPAnnualUpdate.objects.filter(prior_osp__establishment=est).select_related("prior_osp", "new_osp")
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
    from subscriptions.pilot_operator import is_setup_operator

    responsible = (getattr(est, "contact_person", None) or "").strip()
    created_by = getattr(osp, "created_by", None)
    # A setup operator authored the plan as a recorder, never as the responsible person
    # (rehearsal 2026-10-18), so it is no fallback: the line stays unanswered instead.
    if not responsible and created_by is not None and not is_setup_operator(created_by):
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
        "trade_name": (getattr(company, "tradename", "") or "").strip(),
        "responsible_person": responsible,
        "responsible_person_is_named": bool((getattr(est, "contact_person", None) or "").strip()),
        "address": ", ".join(str(b).strip() for b in address_bits if b),
        "phone": getattr(est, "phone", None)
        or getattr(est, "contact_phone", None)
        or getattr(company, "contact_phone", None)
        or "",
        # CCOF's renewal contract and WSDA's AGR 2521 header both ask for an email; the copy sheet read
        # this same order on its own until the expert read of 2026-10-24.
        "email": getattr(est, "contact_email", None)
        or getattr(est, "email", None)
        or getattr(company, "contact_email", None)
        or "",
    }


def _contents_02s(own_register: bool) -> str:
    """The cover's line for 02s. It was missing from the contents, so the page saying where each
    renewal-form question is answered was not named on page one (production packet, 2026-10-29)."""
    if own_register:
        return (
            "02s. Renewal status: what happened to each revision of the year's filing, and the certifying "
            "agent's renewal forms, question by question, with where this packet answers each"
        )
    return "02s. Renewal status: what happened to each revision of the year's filing since it was signed or filed"


def _contents_06(own_register: bool) -> str:
    """The cover's line for 06, worded by whether Trazo holds a question register for the agent."""
    if own_register:
        return (
            "06. Question index: every question on the certifying agent's forms, in its order, with where "
            "this packet answers it or that it is still open"
        )
    return (
        "06. Question index: Trazo does not hold this certifying agent's form list, so it maps no "
        "questions; each module PDF names its own unanswered questions"
    )


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
        *([kv("Trade name (DBA)", ctx["trade_name"])] if ctx["trade_name"] else []),
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
            note=(
                None
                if ctx["responsible_person_is_named"] or not ctx["responsible_person"]
                else "plan author; no responsible person is named for the farm yet"
            ),
        ),
    ]
    if not ctx["responsible_person_is_named"]:
        # Two wordings, because the line may be the plan author's name or nothing at all.
        story.append(
            Paragraph(
                (
                    (
                        "§ 205.401(b) asks for the person responsible for the operation by name. Set the "
                        "responsible person when you edit the farm, so this line is the operation's own "
                        "answer rather than the plan author Trazo fell back to."
                    )
                    if ctx["responsible_person"]
                    else (
                        "§ 205.401(b) asks for the person responsible for the operation by name. None "
                        "is stated in Trazo: set the responsible person when you edit the farm."
                    )
                ),
                styles["meta"],
            )
        )
    story += [
        kv("Address", ctx["address"] or "—"),
        kv("Phone", ctx["phone"] or "—"),
        kv("Email", ctx["email"] or "—"),
        kv(
            "Certificate",
            f"{ctx['certificate_number'] or '—'}" + (f" — {ctx['certifier_name']}" if ctx["certifier_name"] else ""),
        ),
    ]
    # The agent's own identifier for the operation (Oregon Tilth's Client ID), printed only when it
    # was recorded against the agent this packet is for: another agent's ID on this cover would be a
    # number attributed to an agent that never issued it.
    est = osp.establishment
    if est.certifier_client_id and est.certifier_client_id_agent:
        from certifications.services.packet_coverage import packet_agent

        if packet_agent(osp).slug == est.certifier_client_id_agent:
            story.append(kv("Client ID", est.certifier_client_id, note="as issued by the certifying agent"))
    story += [
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
                    else f"continues v{filing.prior_osp.version_number} (no new plan version)"
                ),
            ),
            # Run 3, R3-08: counted as entries. A "None." entry under deletions read as "1 deletion".
            kv(
                "Entries under (a)(2)",
                f"{_count_phrase(len(filing.additions or []), 'addition entry', 'addition entries')}, "
                f"{_count_phrase(len(filing.deletions or []), 'deletion entry', 'deletion entries')}",
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
        Paragraph("Plan review — what the records show that the plan does not yet say", styles["header"]),
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

    from certifications.services.packet_coverage import packet_certifier

    own_register = packet_certifier(osp)[1]
    story += [
        Spacer(1, 10),
        Paragraph("Contents", styles["header"]),
        Paragraph("00. This cover", styles["body"]),
        Paragraph("01. Six-section narrative snapshot (7 CFR 205.201(a))", styles["body"]),
        Paragraph("02. Annual update — the § 205.406(a) filing", styles["body"]),
        Paragraph(_escape(_contents_02s(own_register)), styles["body"]),
        Paragraph(
            "03. § 205.400(f) change notifications filed against this plan or its earlier versions", styles["body"]
        ),
        Paragraph("04. What this packet covers, what it does not, and who authored it", styles["body"]),
        Paragraph(
            "05. Audit trail exhibit — the § 205.103(b)(2) document table and one lot traced field to sale",
            styles["body"],
        ),
        Paragraph(_escape(_contents_06(own_register)), styles["body"]),
        Paragraph("modules/ — one PDF per guided module, N/A attestations included", styles["body"]),
        Paragraph("parcels/ — one Parcel Application per parcel (§ 205.202)", styles["body"]),
        Paragraph("workbooks/ — Common OSP workbooks (field/crop, product list, materials, suppliers)", styles["body"]),
        Spacer(1, 14),
        # Run 3, R3-08: not every document is live. A filed annual update is the bytes filed, and an
        # earlier revision filed before Trazo froze copies is a reconstruction that says so.
        Paragraph(
            "Documents are generated from the operation's records when this packet is built, with one "
            "exception: a filed annual update (02, and annual-update/ revisions with a frozen copy) is the "
            "document as signed and filed, unchanged since. A revision filed before Trazo kept frozen copies "
            "is reconstructed from the records and is marked as not the filed document. Workbook cells the "
            "operation has not recorded remain blank for the operator to complete.",
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
    """Document 02, the § 205.406(a) filing this packet carries.

    A filed revision is the document as it was filed, byte for byte (`filed_pdf`). Anything that
    happened since (acknowledgement, a correction, a withdrawal, the agent's own forms) is in the
    separate 02s supplement and never written onto it. A draft, or a filing made before Trazo
    kept frozen copies, is rendered from the record and says which it is.
    """
    from certifications.services.annual_update_filing import filed_bytes

    ctx = _renewal_context(osp)
    filing = ctx["filing"]
    if filing is not None:
        frozen = filed_bytes(filing)
        if frozen is not None:
            return frozen
        return render_filing_pdf(filing)

    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="Annual Update")
    story = [Paragraph("Annual Update — Continuation of Certification", styles["title"])]
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
    spec = is_specimen(getattr(osp, "establishment", None))
    doc.build(
        story,
        onFirstPage=specimen_page_callback(letter, specimen=spec),
        onLaterPages=specimen_page_callback(letter, specimen=spec),
    )
    return buffer.getvalue()


def _filing_state_lines(filing, styles, freezing: bool = False) -> list:
    """Revision, filing and signature state as of the moment this document is rendered.

    `freezing` is True only while `file_filing` renders the copy it is about to freeze. At that
    moment the revision is filed and has no frozen bytes yet, which is otherwise exactly what a
    legacy row looks like; without the flag every new filing was frozen under the legacy
    heading ("not signed in Trazo") above its own signature (review of back #79).
    """
    lines = []
    # Any filed revision without its frozen bytes, whatever its `snapshot_state` says: the
    # heading must never be missing from a page that is not the filed document.
    if filing.submitted_at is not None and filing.filed_pdf is None and not freezing:
        lines.append(
            Paragraph(
                _escape(
                    "Filed before Trazo kept a frozen copy of each filing. This page is rendered from the "
                    f"records as they stand on {date.today().isoformat()}, not from the document that was "
                    "filed, and it was not signed in Trazo."
                ),
                styles["body"],
            )
        )
    if filing.submitted_at:
        method = filing.get_filing_method_display() if filing.filing_method else ""
        filed = filing.submitted_at.date().isoformat() + (f" ({method})" if method else "")
    else:
        filed = "draft — not yet filed"
    lines.append(Paragraph(f"<b>Filed:</b> {_escape(filed)}", styles["body"]))
    if filing.corrects_id:
        previous = filing.corrects
        when = (
            f"filed {previous.submitted_at.date().isoformat()}"
            if previous.submitted_at
            else (f"signed {previous.signed_at.date().isoformat()}" if previous.signed_at else "not filed")
        )
        lines.append(
            Paragraph(
                _escape(f"Revision {filing.revision_number}, correcting revision {previous.revision_number} ({when})."),
                styles["body"],
            )
        )
    return lines


def _application_info_sentence(filing) -> str:
    # The field is free JSON; a non-dict value (a list from an API client) reads as no attestation
    # rather than raising (review of back #115).
    attestation = filing.sections_unchanged_attestation
    unchanged = isinstance(attestation, dict) and attestation.get(APPLICATION_INFO_KEY) is True
    changes = (filing.application_info_changes or "").strip()
    if unchanged and changes:
        return (
            "The filing both attests that the application information is unchanged and lists changes: "
            f"{changes}. The two statements contradict each other."
        )
    if changes:
        return changes
    if unchanged:
        return (
            "No changes. The operator attests that the business name, address and telephone "
            "number, the person responsible for the operation and, for a company, the person "
            "authorized to act on its behalf are unchanged since the prior update."
        )
    return (
        "Not stated on this filing. Any change to the business name, address or telephone "
        "number, or to the person responsible for the operation, goes to the certifying "
        "agent with this update."
    )


def _agent_requested_sentence(filing) -> str:
    text = (filing.agent_requested_info or "").strip()
    if text and filing.agent_requested_info_none is True:
        return (
            "The filing both states that the agent asked for nothing further and lists information: "
            f"{text}. The two statements contradict each other."
        )
    if text:
        return text
    if filing.agent_requested_info_none is True:
        return "The operator states the certifying agent asked for no further information this year."
    return "Not stated on this filing."


def _recorded_by_clause(filing) -> str:
    """ " Recorded in Trazo by <account>." when the account that recorded the signature is not
    the signer named on it; "" when they are the same person or no account is on the row."""
    user = getattr(filing, "signed_by", None)
    if user is None:
        return ""
    account = (user.get_full_name() or "").strip() if hasattr(user, "get_full_name") else ""
    account = account or (getattr(user, "email", "") or "")
    if not account or account.strip().lower() == (filing.signer_name or "").strip().lower():
        return ""
    return f" Recorded in Trazo by {account}."


def _filing_signature_lines(filing, osp, styles) -> list:
    """Who signed, from the signature the server recorded. A draft gets lines to sign on; a
    filing that reached the agent without a signature in Trazo gets neither a name nor lines,
    because either would put a signature on a document nobody signed."""
    if filing.signed_at is not None:
        title = f", {filing.signer_title}" if filing.signer_title else ""
        return [
            Spacer(1, 0.14 * inch),
            Paragraph(
                _escape(
                    f"Signed in Trazo by {filing.signer_name or 'the account holder'}{title} on "
                    f"{filing.signed_at.date().isoformat()}.{_recorded_by_clause(filing)} "
                    f"Signed content: sha256 {filing.signed_content_sha256}."
                ),
                styles["body"],
            ),
        ]
    if filing.submitted_at is not None:
        return [
            Spacer(1, 0.14 * inch),
            Paragraph("No signature was recorded in Trazo for this filing.", styles["body"]),
        ]
    return signature_block(osp.establishment, styles["body"])


def _supporting_document_lines(filing, styles) -> list:
    """(a)(1) asks for the summary "supported by documentation": the files this revision names,
    each with where the renewal packet carries it. Signed with the filing, so on a filed revision
    this list is the one that was signed. Whether each file made it into a given packet is page
    04's to say; this page is the filing."""
    from certifications.services.packet_attachments import annual_update_document_path

    links = list(filing.supporting_links.select_related("document")) if filing.pk else []
    lines = [Spacer(1, 4), Paragraph("<b>Supporting documentation for (a)(1)</b>", styles["body"])]
    if not links:
        lines.append(Paragraph("No supporting documents are attached to this filing in Trazo.", styles["body"]))
        return lines
    for link in links:
        doc = link.document
        lines.append(
            Paragraph(
                _escape(
                    f"• {doc.title or 'Untitled document'} (in Documents since {doc.created_at.date().isoformat()}); "
                    f"renewal packet file {annual_update_document_path(doc)}"
                ),
                styles["body"],
            )
        )
    return lines


def render_filing_pdf(filing, freezing: bool = False) -> bytes:
    """One revision of a § 205.406(a) filing as a document.

    Rendered from the revision alone, so the same call freezes it at filing time
    (`annual_update_filing.file_filing`) and renders a draft or a legacy row live. The plan
    version it names is the filing's own route, not whichever plan the packet was built from.
    """
    from history.services.audit_export_service import _fmt_change_entries

    styles = _styles()
    osp = filing.new_osp or filing.prior_osp
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="Annual Update")
    story = [Paragraph("Annual Update — Continuation of Certification", styles["title"])]
    story += [
        Paragraph(
            _escape(
                f"{osp.establishment.name} · continuation for {filing.reporting_year} · "
                f"revision {filing.revision_number} · 7 CFR 205.406(a)(1)–(4)"
            ),
            styles["subtitle"],
        ),
        Spacer(1, 8),
    ]
    story += _filing_state_lines(filing, styles, freezing=freezing)
    story.append(
        Paragraph(
            "<b>Plan version:</b> "
            + _escape(
                f"v{filing.prior_osp.version_number} to v{filing.new_osp.version_number}"
                if filing.new_osp_id
                else f"continues v{filing.prior_osp.version_number}; no new plan version was made"
            ),
            styles["body"],
        )
    )
    # 🔴 2026-09-30 (audit T20): a filed update in Trazo is the operation's record of its
    # § 205.406(a) changes. The agent's renewal is its own form (OTCO's OSP Update Application
    # & Agreement, WSDA AGR 2516, CCOF's annual renewal), signed and filed with the agent.
    from certifications.services.packet_coverage import packet_agent

    agent_name = packet_agent(osp).name or "the certifying agent"
    story.append(
        Paragraph(
            _escape(
                "This is the operation's record of its § 205.406(a) update. It supports, and does "
                f"not replace, {agent_name}'s own renewal form."
            ),
            styles["body"],
        )
    )
    # Acknowledgement, corrections and withdrawal happen after filing. They are reported in the
    # 02s supplement, never here: this document is what was filed.
    if filing.corrects_id and (filing.correction_note or "").strip():
        # What THIS revision corrects is part of what is signed and filed, so it prints here, in the
        # operator's words (run 3, 2026-10-02). A reader of a correction sees what changed and why.
        story += [
            Spacer(1, 10),
            Paragraph(
                _escape(f"What revision {filing.revision_number} corrects in revision {filing.revision_number - 1}"),
                styles["header"],
            ),
            Paragraph(_escape(filing.correction_note.strip()), styles["body"]),
        ]
    # The continuation year IS the year the additions and deletions are intended for: a renewal
    # due 1 March 2026 continues 2026 and reports on the 2025 season (the field's definition since
    # 2026-09-12, cover "Continuation for {year}"). cb04c90 printed `+ 1` from the model's older
    # help text and the Calapooia revisions filed under it read "(2027)" on a 2026 continuation
    # (recordkeeping review F-07). The frozen bytes stay as filed; the ledger notes it.
    coming = filing.reporting_year
    story += [
        Spacer(1, 10),
        Paragraph("(a)(1) Summary of deviations, changes and modifications to the previous plan", styles["header"]),
        Paragraph(_escape(filing.changes_summary or "—"), styles["body"]),
    ]
    story += _supporting_document_lines(filing, styles)
    story += [
        Spacer(1, 8),
        # Run 3, R3-01: the year is stated, so a change already made cannot read as an intention.
        Paragraph(_escape(f"(a)(2) Additions intended for the coming year ({coming})"), styles["header"]),
    ]
    # `_fmt_change_entries` renders a LIST into one "; "-joined string (it was written for a
    # table cell). One call per entry keeps each addition on its own bullet here.
    adds = [_fmt_change_entries([a]) for a in (filing.additions or [])]
    adds = [a for a in adds if a]
    story += [Paragraph(_escape(f"• {a}"), styles["body"]) for a in adds] or [Paragraph("None stated.", styles["body"])]
    story += [
        Spacer(1, 8),
        Paragraph(_escape(f"(a)(2) Deletions intended for the coming year ({coming})"), styles["header"]),
    ]
    dels = [_fmt_change_entries([d]) for d in (filing.deletions or [])]
    dels = [d for d in dels if d]
    story += [Paragraph(_escape(f"• {d}"), styles["body"]) for d in dels] or [Paragraph("None stated.", styles["body"])]
    # (a)(3) and (a)(4) are the OPERATOR's statements or they are nothing. "No changes" prints
    # only when it was stated; an empty box is "not stated", never "none" (which would assert
    # what the operator never said).
    story += [
        Spacer(1, 8),
        Paragraph("(a)(3) Changes to the application information under § 205.401(b)", styles["header"]),
        Paragraph(_escape(_application_info_sentence(filing)), styles["body"]),
        Spacer(1, 8),
        Paragraph("(a)(4) Other information the certifying agent requires", styles["header"]),
        Paragraph(_escape(_agent_requested_sentence(filing)), styles["body"]),
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
    from certifications.services.renewal_sales import organic_sales_subtotal

    sales = organic_sales_subtotal(osp.establishment, filing)
    total, n_sales, n_priced = sales.total, sales.n_sales, sales.n_priced
    # "dated in calendar 2025" for the fallback year, "dated 2025-10-01 to 2026-09-30" for the period
    # the operator stated (Oregon Tilth asks for its own 12 months, kept the same each year).
    period = f"calendar {sales.label}" if not sales.stated else sales.label
    # Run 3, R3-02/R3-03: this said agents "ask for this figure". They do not: WSDA AGR 2521 asks for
    # income RECEIVED, services included; OTCO Step 6 asks for sales of everything on the certificate,
    # even if not sold as organic. The subtotal is a starting point the operator reconciles, so it is
    # named as one, and no agent's fee figure is claimed for it.
    story += [
        Spacer(1, 8),
        Paragraph(
            (
                f"Sales records, {sales.label} (period not over)"
                if sales.running
                else f"Sales records subtotal, {sales.label} (not reconciled)"
            ),
            styles["header"],
        ),
    ]
    # The sale amount is optional on a sales record (an operator may keep prices out of Trazo), so
    # the subtotal covers only the sales that carry one, and says how many do. Until 2026-10-17 a
    # filing whose sales had no amounts formatted None as money and the whole packet failed (500),
    # found in the pilot rehearsal the moment an annual update was saved.
    if sales.running:
        # A real renewal read this way on 2026-10-23: a 2027 continuation with no period stated
        # printed January to October 2026 as "calendar 2026". The year is not over, so no year's
        # figure is printed. Worded for any agent (expert read of 2026-10-24): 02 is the filing and
        # names no agent, and only Oregon Tilth asks for a 12-month period; CCOF asks for none and
        # WSDA's fee form wants the last calendar year.
        sales_sentence = (
            f"{period[0].upper() + period[1:]} is not over (as of {sales.as_of.isoformat()}), so no figure for it "
            f"is given; {_count_phrase(n_sales, 'sale')} invoiced as organic {'is' if n_sales == 1 else 'are'} "
            "dated in it so far. A figure is given once the year has ended, or for a 12-month sales period "
            "stated on this update."
        )
    elif not n_sales:
        sales_sentence = f"No sale invoiced as organic is dated {sales.label} in the operation's records."
    elif n_priced < n_sales:
        # Same rule as the audit export's sales table: a total over a partly filled amount column is
        # a smaller number than the truth, and this figure sits beside a fee form, so no total is
        # printed until every sale carries its amount (review of back #170).
        unpriced = n_sales - n_priced
        sales_sentence = (
            f"{_count_phrase(n_sales, 'sale')} invoiced as organic and dated in {period} "
            f"{'is' if n_sales == 1 else 'are'} in the operation's sales records in Trazo. "
            f"{_count_phrase(unpriced, 'sale')} {'records' if unpriced == 1 else 'record'} no amount received, "
            + (
                "so no subtotal is given: a total over the others would understate the year."
                if n_priced
                else "so there is no subtotal to report."
            )
        )
    elif sales.stated:
        sales_sentence = (
            f"${total:,.2f} across {_count_phrase(n_sales, 'sale')} invoiced as organic and dated "
            f"{sales.label}, the sales period stated on this update, from the operation's sales records in Trazo."
        )
    else:
        sales_sentence = (
            f"${total:,.2f} across {_count_phrase(n_sales, 'sale')} invoiced as organic and dated in "
            f"calendar {sales.label}, from the operation's sales records in Trazo. Fruit of the {sales.label} "
            "crop settled after 31 December is not in it."
        )
    story.append(Paragraph(_escape(sales_sentence), styles["body"]))
    # Only the operation's own agent's basis is named: a filing never names another agency's form
    # (review of back #91; the same rule doc 01 keeps).
    fee_basis = " " + (_fee_basis_sentence(osp) or "The certifying agent's fee form sets its own basis.")
    story.append(
        Paragraph(
            _escape(
                ("Any figure given here is a" if sales.running else "This is a")
                + " subtotal of sales records, not reconciled to the operation's books, and it is not any "
                f"certifying agent's fee figure.{fee_basis} Payment timing, service income and completeness are "
                "the operation's to reconcile."
            ),
            styles["meta"],
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
        *_filing_signature_lines(filing, osp, styles),
    ]
    spec = is_specimen(getattr(osp, "establishment", None))
    doc.build(
        story,
        onFirstPage=specimen_page_callback(letter, specimen=spec),
        onLaterPages=specimen_page_callback(letter, specimen=spec),
    )
    return buffer.getvalue()


def _revision_status_sentence(revision) -> str:
    if revision.withdrawn_at is not None:
        return f"withdrawn on {revision.withdrawn_at.date().isoformat()}" + (
            f": {revision.withdrawal_reason}" if revision.withdrawal_reason else ""
        )
    if revision.superseded_at is not None:
        return f"corrected; replaced as the year's filing on {revision.superseded_at.date().isoformat()}"
    if revision.submitted_at is not None:
        return "the current filing for the year"
    if revision.signed_at is not None:
        return "signed, not yet filed"
    return "draft, not signed"


_RENEWAL_ROLE_HEADINGS = {
    "annual_renewal": "Renewal application",
    "site_update": "Site update",
    "crop_update": "Crop update",
    "fee": "Renewal fee",
}


def _renewal_routing_flowables(osp, styles) -> list:
    """The agent's own renewal forms, each row with where its answer is in this packet.

    These forms are filed with the agent, on its paper or its site. Nothing here completes one: the
    rows say where to copy an answer from, and name the ones the operation answers there itself.
    """
    from certifications.services.packet_coverage import renewal_routing

    agent_name, forms = renewal_routing(osp)
    # Run 3, R3-08: "filed" read as a record of filing. These are forms to file; whether they were
    # filed is a fact this packet does not hold.
    story = [Spacer(1, 10), Paragraph("Renewal routing: forms to file with the certifying agent", styles["header"])]
    if not forms:
        story.append(
            Paragraph(
                "The certifying agent's own renewal forms are filed with it directly. This packet does not "
                "carry that agent's form numbering, so it does not list them; the annual update above is the "
                "operation's record of the year's changes to bring to them.",
                styles["body"],
            )
        )
        return story
    story.append(
        Paragraph(
            _escape(
                f"{agent_name} renews certification on its own forms, listed below. Each is filed with "
                f"{agent_name}, not by this packet. Beside each question is where its answer is in this packet, "
                "or that the operation answers it on the form."
            ),
            styles["body"],
        )
    )
    basis = _fee_basis_sentence(osp)
    if basis:
        # Run 4, R4-04: stated here, on the page that changes with the export, because 02 is frozen as
        # filed and may name no agent at all.
        story.append(
            Paragraph(
                _escape(
                    "Sales figure: the subtotal printed on 02 is a subtotal of the operation's sales records, not "
                    f"reconciled to its books and not this agent's fee figure. {basis}"
                ),
                styles["meta"],
            )
        )
    for form in forms:
        heading = _RENEWAL_ROLE_HEADINGS.get(form.role, form.role)
        name = form.title + (f" ({form.document_id})" if form.document_id and form.document_id != form.title else "")
        edition = f", {form.revision}" if form.revision else ""
        story += [Spacer(1, 6), Paragraph(_escape(f"{heading}: {name}{edition}"), styles["body"])]
        if form.reason:
            story.append(Paragraph(_escape(form.reason), styles["meta"]))
            continue
        how = _ACCEPTED_FORMAT_WORDING.get(form.accepted_format, "").format(agent=agent_name)
        if form.requires_signature:
            how = (how + " " if how else "") + f"It carries a signature the operation gives {agent_name}."
        if form.sent_with_renewal:
            how = (how + " " if how else "") + (
                f"{agent_name} sends this form with its renewal application and updates it regularly. Fill in "
                f"the copy {agent_name} sent: the rows below were read from an earlier copy it published, and "
                "that copy's items may differ."
            )
        if how:
            story.append(Paragraph(_escape(how), styles["meta"]))
        for row in form.rows:
            line = f"• {row.ref}: {row.standing}" + (f" ({row.where})" if row.where else "")
            if row.optional:
                line += " [optional on the form]"
            story.append(Paragraph(_escape(line), styles["body"]))
    return story


def _changed_sections_flowables(osp, styles) -> list:
    """Oregon Tilth's OSP Update Step 4: which plan sections changed, by the agent's form codes.

    In 02s, not 02: the list is computed from the plan versions on the day the packet is built,
    and 02 is the filing as it was signed. Printed only for an agent whose renewal form asks for
    the list (`packet_coverage._SECTION_LIST_AGENTS`).
    """
    from certifications.services.packet_coverage import changed_sections

    result = changed_sections(osp)
    if result is None:
        return []
    agent = result.agent_name
    story = [
        Spacer(1, 10),
        Paragraph("OSP Update Form Step 4: plan sections whose answers changed", styles["header"]),
    ]
    if result.state == "no_filing":
        story.append(
            Paragraph(
                "No annual update is linked to this plan, so there are no two plan versions to compare.",
                styles["body"],
            )
        )
        return story
    if result.state == "no_new_version":
        story.append(
            Paragraph(
                _escape(
                    f"The year's annual update did not create a new plan version; it is recorded against "
                    f"plan v{result.prior_version}. There is no second version to compare, so no section is "
                    "listed here."
                ),
                styles["body"],
            )
        )
        return story
    if result.state == "newer_version":
        story.append(
            Paragraph(
                _escape(
                    f"This packet is built from plan v{result.prior_version}, and the year's annual update moves "
                    f"to plan v{result.new_version}. The section comparison is printed in the packet built from "
                    f"plan v{result.new_version}, whose module files hold the changed answers."
                ),
                styles["body"],
            )
        )
        return story
    story.append(
        Paragraph(
            _escape(
                f"Compared from plan v{result.prior_version} to v{result.new_version}. Step 4 of {agent}'s OSP "
                "Update Form asks the operation to list its updated OSP sections and attach them. Listed below "
                "by the agent's form codes: each section whose answers differ between the two versions, and "
                "where those answers are in this packet. This compares stored answers and does not review the "
                "changes. The sections are still listed on the agent's form, with the agent's own forms attached."
            ),
            styles["body"],
        )
    )
    if not result.forms and not result.unmapped and not result.narratives:
        story.append(
            Paragraph(
                _escape(f"No section's answers differ between v{result.prior_version} and v{result.new_version}."),
                styles["body"],
            )
        )
    for label, files in result.forms:
        story.append(Paragraph(_escape(f"• {label}: answers changed in {', '.join(files)}"), styles["body"]))
    for label, path in result.unmapped:
        story.append(
            Paragraph(
                _escape(f"• {label}: answers changed in {path} (no form of the agent maps to this section)"),
                styles["body"],
            )
        )
    for label, path in result.narratives:
        story.append(
            Paragraph(
                _escape(f"• {label}: the operation's own narrative or confirmed record types changed in {path}"),
                styles["body"],
            )
        )
    # Land is not versioned with the plan, so the comparison above cannot show it. Step 4 names
    # "new land" in its own list, so the gap is stated rather than left as a silent absence, and
    # so are edits to a parcel already on the plan (review of back #216).
    parcel_forms = f" ({', '.join(result.parcel_forms)})" if result.parcel_forms else ""
    land = (
        "Land: parcels are kept with the operation, not with a plan version, so the comparison above "
        f"does not show new land, or edits to an existing parcel's application{parcel_forms} such as its "
        "crop history, buffers or map."
    )
    if result.since is None:
        land += f" Plan v{result.prior_version} has no submission or effective date to count from."
    else:
        since = f"{result.since.isoformat()}, the date plan v{result.prior_version} was {result.since_basis}"
        if result.parcels_begun:
            land += f" Parcels whose stated management start is on or after {since}: {', '.join(result.parcels_begun)}."
        else:
            land += f" No parcel states a management start on or after {since}."
        if result.parcels_unstated:
            land += f" Management start date not stated: {', '.join(result.parcels_unstated)}."
    story.append(Spacer(1, 4))
    story.append(Paragraph(_escape(land), styles["meta"]))
    return story


#: Per agent: (heading, what the form asks, the certificate's name for the parcel number).
_LAND_TABLE_WORDING = {
    "ccof": (
        "Crop Update (ORGB88): parcels, crops and acres",
        "CCOF's Crop Update asks, for each certified parcel, the crops current or planned within the next "
        "12 months and the acres. The form is filed with CCOF; copy from the rows below.",
        "CCOF parcel #",
    ),
    "wsda": (
        "Site Update Information (AGR 2516): sites, crops and acres",
        "AGR 2516 asks what changes for each site whose crop production information on the Certified "
        "Operation Profile does not match the plan for the coming year. It accepts production or planting "
        "records instead of the form if they show the site number and site name as on the certificate. "
        "Trazo does not hold WSDA's profile, so it does not say which sites changed: comparing the rows "
        "below with the profile is the operation's. If acreage leaves organic production, AGR 2516 also "
        "asks for a map of the new boundaries and the reason it was removed.",
        "WSDA site no.",
    ),
}


def _land_table_flowables(osp, styles) -> list:
    """CCOF ORGB88 / WSDA AGR 2516: each parcel already on the agent's certificate, its crops and acres.

    In 02s with the routing: it reads the land as it is on the day the packet is built, and 02 is
    the filing as signed. Printed only for an agent whose renewal asks for it (`LAND_TABLE_ROUTES`).
    """
    from certifications.services.renewal_land_table import land_table

    table = land_table(osp)
    if table is None:
        return []
    heading, asks, number_label = _LAND_TABLE_WORDING[table.agent]
    first, last = table.years
    story = [
        Spacer(1, 10),
        Paragraph(_escape(heading), styles["header"]),
        Paragraph(_escape(asks), styles["body"]),
        Paragraph(
            _escape(
                f"From this operation's records as of {table.as_of.isoformat()}: each parcel whose application "
                f"reports it as already on {table.agent_name}'s certificate, with the number that certificate "
                f"prints for it, the parcel's acreage, its land history for {first} and {last}, and the crops "
                "the operation states it plans for the next 12 months. The name is the parcel's name in Trazo; "
                "the form wants the name as on the certificate."
            ),
            styles["meta"],
        ),
    ]
    if not table.rows:
        story.append(
            Paragraph(
                _escape(f"No parcel's application reports it as already on {table.agent_name}'s certificate."),
                styles["body"],
            )
        )
    # "#01" under a "CCOF parcel #" label printed "CCOF parcel # #01".
    bare_label = number_label.rstrip("#").rstrip()
    for row in table.rows:
        number = (
            f"{bare_label} {row.number}"
            if row.number.startswith("#")
            else (
                f"{number_label} {row.number}"
                if row.number
                else f"{number_label} not recorded (add it on the parcel's application, F. Land history)"
            )
        )
        crops = [f"{year} {text}" for year, text in row.crops]
        crops += [f"{year} no crop recorded" for year in row.years_without_crop]
        crops.sort()
        line = f"• {row.name}, {number}, {row.acres:.1f} acres: {'; '.join(crops)}."
        line += (
            f" Planned, next 12 months: {row.planned.rstrip('.')}."
            if row.planned
            else " Planned crops for the next 12 months not stated (add them on the parcel's application, "
            "F. Land history)."
        )
        if row.conventional_years:
            years = ", ".join(str(year) for year in row.conventional_years)
            line += f" Marked conventional for {years}: if this acreage leaves organic production, say so to the agent."
        story.append(Paragraph(_escape(line), styles["body"]))
    if table.rows:
        story.append(
            Paragraph(
                "Acres are each parcel's total. Trazo does not record acreage per crop, so where a parcel carries "
                "more than one crop the acres for each are the operation's to state.",
                styles["meta"],
            )
        )
    for name, reason in table.excluded:
        story.append(Paragraph(_escape(f"Not in this table: {name}, {reason}."), styles["meta"]))
    return story


#: Each agent's own fee basis, in its own words. Printed only for that agent's packet: a document
#: never names another agency's form (review of back #91).
_FEE_BASIS = {
    "wsda": (
        "WSDA's Renewal Fee Form (AGR 2521), sent with its renewal application, sets the basis; the copy "
        "WSDA last published asked for income received in the previous calendar year, organic services "
        "included."
    ),
    "otco": (
        "Oregon Tilth's OSP Update Step 6 asks for gross sales of everything on the certificate, including "
        "products not sold as organic; a portion not sold as organic is excluded from the fee only by written "
        "petition to Oregon Tilth."
    ),
}


def _fee_basis_sentence(osp) -> str:
    """The packet's own agent's fee basis, or "" for an agent without one on file here."""
    from certifications.services.packet_coverage import packet_certifier

    agent, own = packet_certifier(osp)
    return _FEE_BASIS.get(agent, "") if own else ""


def _renewal_status_pdf(osp) -> bytes:
    """Document 02s: what happened to the year's filing after it was filed.

    Kept out of 02 on purpose. 02 is the filing as it was filed; an acknowledgement, a
    correction or a withdrawal is a later fact about it, and stamping it onto the filed document
    would change the document the agent received.
    """
    from certifications.models import OSPAnnualUpdate
    from certifications.services.annual_update_filing import packet_revision_filename, year_revisions

    styles = _styles()
    ctx = _renewal_context(osp)
    anchor_filing = ctx["filing"] or ctx.get("other_filing")
    if anchor_filing is None:
        # A packet whose only revisions are superseded or withdrawn still has a history to report.
        anchor_filing = (
            OSPAnnualUpdate.objects.filter(establishment=osp.establishment).order_by("-reporting_year", "-id").first()
        )
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="Renewal Status")
    story = [
        Paragraph("Renewal Status — Supplement to the Annual Update", styles["title"]),
        Paragraph(_escape(f"{osp.establishment.name} · as of {date.today().isoformat()}"), styles["subtitle"]),
        Spacer(1, 8),
        Paragraph(
            "This page is not part of any filing. It reports what has happened to each revision of the "
            "year's § 205.406(a) update since it was signed or filed. The filed documents themselves are "
            "unchanged.",
            styles["body"],
        ),
    ]
    revisions = year_revisions(anchor_filing)
    if not revisions:
        story += [
            Spacer(1, 8),
            Paragraph("No § 205.406(a) annual update is recorded for this operation.", styles["body"]),
        ]
    else:
        year = revisions[0].reporting_year
        story += [Spacer(1, 10), Paragraph(f"{year} annual update: revisions", styles["header"])]
        for revision in revisions:
            story.append(
                Paragraph(
                    _escape(f"Revision {revision.revision_number}: {_revision_status_sentence(revision)}."),
                    styles["body"],
                )
            )
            details = []
            if revision.signed_at is not None:
                title = f", {revision.signer_title}" if revision.signer_title else ""
                details.append(
                    f"Signed by {revision.signer_name or 'the account holder'}{title} on "
                    f"{revision.signed_at.date().isoformat()}.{_recorded_by_clause(revision)}"
                )
            elif revision.submitted_at is not None:
                details.append("No signature was recorded in Trazo.")
            if revision.submitted_at is not None:
                method = revision.get_filing_method_display() if revision.filing_method else ""
                details.append(
                    f"Filed {revision.submitted_at.date().isoformat()}"
                    + (f" by {method.lower()}" if method else "")
                    + "."
                )
            if revision.snapshot_state == OSPAnnualUpdate.SNAPSHOT_FROZEN:
                details.append(
                    f"Document as filed: {packet_revision_filename(revision)} (sha256 {revision.filed_sha256})."
                )
            elif revision.submitted_at is not None:
                details.append(
                    "Filed before Trazo kept a frozen copy of each filing; "
                    f"{packet_revision_filename(revision)} is rendered from current records, not the filed document."
                )
            if revision.certifier_acknowledged_at is not None:
                details.append(
                    f"Certifying agent acknowledged receipt on {revision.certifier_acknowledged_at.date().isoformat()}."
                )
            elif revision.submitted_at is not None:
                details.append("No acknowledgment from the certifying agent is recorded.")
            if revision.new_osp_id:
                details.append(
                    f"Linked plan versions: v{revision.prior_osp.version_number} to v{revision.new_osp.version_number}."
                )
            for detail in details:
                story.append(Paragraph(_escape(f"• {detail}"), styles["body"]))
            story.append(Spacer(1, 6))
    story += _renewal_routing_flowables(osp, styles)
    story += _changed_sections_flowables(osp, styles)
    story += _land_table_flowables(osp, styles)
    spec = is_specimen(getattr(osp, "establishment", None))
    doc.build(
        story,
        onFirstPage=specimen_page_callback(letter, specimen=spec),
        onLaterPages=specimen_page_callback(letter, specimen=spec),
    )
    return buffer.getvalue()


def lineage_change_notifications(osp) -> list:
    """Every § 205.400(f) notice filed against `osp` and its previous versions, oldest first.

    One reading for packet document 03 and the audit dossier (run 7, R7-02a: the dossier read the
    active version only, so a notice filed on v1 printed as "none on file" in a v3 dossier)."""
    from certifications.models import OSPChangeNotification

    lineage, cursor = [], osp
    while cursor is not None and cursor.pk not in lineage:
        lineage.append(cursor.pk)
        cursor = cursor.previous_version
    return list(
        OSPChangeNotification.objects.filter(osp_id__in=lineage)
        .select_related("osp", "parcel", "created_by")
        .order_by("date_notified", "created_at", "id")
    )


def _notice_removal_and_document(n, styles) -> list:
    """For a field removal, why the acreage left; for any notice, its file and where it is.

    WSDA AGR 2516 asks for both the reason and a map of the new boundaries, but 03 goes into every
    agent's packet and names no agent's form (review of back #91), so the lines are worded for any.

    The file is named by the path this packet wrote it under, or by why it is not in the ZIP, from the
    manifest of the build in progress: a page never names a file the reader will not find (T19).
    """
    from certifications.models import OSPChangeNotification
    from certifications.services.packet_attachments import ATTACHED, current_manifest, notice_document_path

    out = []
    if n.change_category == OSPChangeNotification.CATEGORY_FIELD_REMOVAL:
        reason = (getattr(n, "removal_reason", "") or "").strip()
        out.append(
            Paragraph(
                _escape(
                    f"Why the acreage left organic production: {reason}"
                    if reason
                    else "Why the acreage left organic production: not recorded in Trazo."
                ),
                styles["body"] if reason else styles["meta"],
            )
        )
    if n.supporting_document:
        manifest = current_manifest()
        shipped = manifest.for_source(f"notice:{n.pk}") if manifest else []
        if shipped and shipped[0].state != ATTACHED:
            line = f"Supporting document not in this packet: {shipped[0].detail}. It is kept in Trazo."
        else:
            line = f"Supporting document attached to this packet: {notice_document_path(n)}."
        out.append(Paragraph(_escape(line), styles["meta"]))
    elif n.change_category == OSPChangeNotification.CATEGORY_FIELD_REMOVAL:
        out.append(
            Paragraph(
                "No map of the new boundaries is attached to this notice.",
                styles["meta"],
            )
        )
    return out


def _change_notifications_pdf(osp) -> bytes:
    """Document 03 — every § 205.400(f) notice filed against this plan and its previous versions.

    § 205.406(a)(1) asks for the changes "supported by documentation"; these notices ARE the
    documentation, and until now they lived only on the OSP screen.
    """
    styles = _styles()
    notices = lineage_change_notifications(osp)
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
            *_notice_removal_and_document(n, styles),
            Paragraph(
                _escape(
                    f"Method: {n.get_method_display()} · Documentation: {n.get_documentation_timing_display()}"
                    # Run 3, R3-07: "not yet acknowledged" stated what the agent had not done; Trazo
                    # only knows what is recorded. And the field is a date: `.date()` raised on it.
                    + (
                        f" · Acknowledgment recorded {n.certifier_acknowledged_at.isoformat()}"
                        if n.certifier_acknowledged_at
                        else " · no acknowledgment recorded in Trazo"
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
            # 🔴 2026-09-30 (audit T22): this said the gap "is the handler's culls and shrink". No
            # cull or loss record exists anywhere in the data model; the pack-out figure shows a
            # difference, not its cause. State the record, name no cause.
            line += (
                f" Sales match the pack-out. The handler's pack-out records {fmt_total(shrink, balance.unit)} "
                "less than was harvested."
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
            f" \u00b7 {fmt_total(diff, balance.unit)} harvested is on no sale, pack-out or loss record in "
            "Trazo for this lot. State where it went."
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

    from certifications.services.audit_trail_exhibit import (
        OPERATOR_COMPLETES,
        buffer_dispositions,
        document_table,
        sample_trail,
    )

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
        if any(not row.linking_element for row in rows):
            # Only when a row actually leaves its link to the operator; otherwise it points at nothing.
            story.append(Spacer(1, 4))
            story.append(
                Paragraph(
                    "Rows whose linking element reads as the operator's own document are records Trazo does "
                    "not hold (weigh tickets, delivery slips, the operation's own forms); the operator states "
                    "the link on this page.",
                    styles["meta"],
                )
            )

    # The heading and its two lead lines travel with the trail: they sat alone at the foot of page 1.
    story += [
        Spacer(1, 10),
        Paragraph("Part B — Sample trail, one lot from field to sale", _sticks_to_next(styles["header"])),
    ]
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
                _sticks_to_next(styles["body"]),
            )
        )
        if trail.lot_id:
            story.append(
                Paragraph(
                    f"<b>Linking element — Lot ID:</b> {_escape(trail.lot_id)}",
                    _sticks_to_next(styles["body"]),
                )
            )
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
            story.extend(_sale_source_flowables(sale, styles))
        story.append(
            Paragraph(
                "Voided sales are not shown. Every line above is a dated record the operation logged; a "
                "link that is missing is reported as missing rather than supplied.",
                styles["meta"],
            )
        )
        story.extend(_lot_balance_flowables(trail.balance, styles))
        story.extend(_one_sale_traced_flowables(trail, styles))

    # Part C — every buffer-row pick on the operation, not only the traced lot's. The exhibit
    # walks ONE lot, and a farm whose buffer row sits on a different block than that lot showed
    # the operator's claim that buffer records are kept and not one of them (2026-09-12).
    dispositions = buffer_dispositions(establishment)
    if dispositions:
        story += [
            Spacer(1, 10),
            Paragraph("Part C — Buffer crop, and what became of it (7 CFR 205.202(c))", styles["header"]),
            Paragraph(
                "Crop from a buffer row may never be sold or represented as organic. Each line below is a dated "
                "harvest record and what it says became of the buffer-row crop, with the sales on that season "
                "that are not invoiced as organic. The quantity is the buffer quantity the record states; where "
                "it states none, none is shown, and the harvest record's own quantity stays with the lot above.",
                styles["meta"],
            ),
        ]
        for row in dispositions:
            head = " · ".join(x for x in (row.date, row.parcel, row.quantity, row.disposition) if x)
            story.append(Paragraph(_escape(f"• {head}"), styles["body"]))
            for when, buyer, quantity, invoice, organic in row.sales:
                bits = [x for x in (when, buyer, quantity) if x]
                if invoice:
                    bits.append(_labelled("invoice", invoice, _INVOICE_WRITTEN))
                bits.append("organic status on invoice: " + ("Yes" if organic else "No"))
                story.append(Paragraph(_escape("— " + " · ".join(bits)), styles["meta"]))
            if not row.sales:
                story.append(
                    Paragraph(
                        "— No sale outside the organic invoices is on record for this season. Where the buffer "
                        "crop was sold, the record proving it was not sold as organic belongs here.",
                        styles["meta"],
                    )
                )
            if row.evidence:
                story.append(Paragraph(_escape(f"— Documentation: {row.evidence}"), styles["meta"]))

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
def _one_sale_traced_flowables(trail, styles) -> list:
    """Part B2: one sale of the sample season walked back to the inputs, by the SAME
    `history.services.traceback.trace_sale` the operation runs on screen, so the page and the
    packet cannot tell a certifier two different chains. Part B stops at the sale; an inspector's
    trace-back does not, it reaches the inputs applied and their purchase records. Every line is a
    recorded fact; a missing link is stated, never supplied.
    """
    from history.models import SalesRecord
    from history.services.traceback import gap_sentence, trace_sale

    if not trail.season_id:
        return []
    # An organic sale first (that is the lot a certifier traces), the most recent one.
    sale = (
        SalesRecord.objects.live()
        .filter(production_id=trail.season_id)
        .select_related("production__parcel__establishment", "production__product", "production__crop_type")
        .order_by("-organic_on_invoice", "-sale_date", "-pk")
        .first()
    )
    if sale is None:
        return []
    t = trace_sale(sale).as_dict()

    def files(docs):
        return ", ".join(d["title"] for d in docs) if docs else "no file attached"

    out = [
        Spacer(1, 8),
        Paragraph("Part B2 — One sale traced back to the inputs applied", styles["header"]),
        Paragraph(
            "The walk an inspector makes at inspection, from one sale of the season above back to the "
            "harvest pick it names and every input applied that season, with the purchase identifiers "
            "and the files the operation holds. The same trace the operation runs in Trazo.",
            styles["meta"],
        ),
    ]
    s = t["sale"]
    bits = [x for x in (s["date"], s["buyer"], s["quantity"]) if x]
    # The operator sometimes types the label into the field ("Invoice 4471"); `_labelled` is how
    # Part B avoids printing "invoice Invoice 4471", and B2 must not regress it.
    if s["invoice"]:
        bits.append(_labelled("invoice", s["invoice"], _INVOICE_WRITTEN))
    if s["bol"]:
        bits.append(_labelled("BOL", s["bol"], _BOL_WRITTEN))
    # As Parts B and C state for every sale: whether the chain below is the organic lot or a
    # buffer-row sale (review of back #193; the pick prefers an organic sale, it cannot promise one).
    bits.append("organic status on invoice: " + ("Yes" if s["organic_on_invoice"] else "No"))
    if s["label_category"]:
        # The model's own display words, the ones Part B prints for the same sale.
        from history.models import ORGANIC_LABEL_CATEGORY_CHOICES

        bits.append(
            f"label claim: {dict(ORGANIC_LABEL_CATEGORY_CHOICES).get(s['label_category'], s['label_category'])}"
        )
    out.append(
        Paragraph(
            "<b>Sale:</b> " + _escape(" · ".join(bits)),
            styles["body"],
        )
    )
    out.append(Paragraph(_escape(f"    Files: {files(s['documents'])}"), styles["meta"]))
    if t["picks_linked"]:
        for p in t["picks"]:
            pbits = [x for x in (p["lot_code"] or "no lot code", p["date"], p["quantity"]) if x]
            if p["block"]:
                pbits.append(f"block {p['block']}")
            out.append(
                Paragraph(
                    "<b>Pick named on the sale:</b> " + _escape(" · ".join(pbits)),
                    styles["body"],
                )
            )
    else:
        out.append(
            Paragraph("<b>Pick named on the sale:</b> none. The season's picks are listed in Part B.", styles["body"])
        )
    out.append(Paragraph("<b>Inputs applied in the season</b>", styles["body"]))
    if not t["inputs"]:
        out.append(Paragraph("• No input is recorded for this season.", styles["meta"]))
    for r in t["inputs"]:
        ibits = [x for x in (r["date"], r["product"]) if x]
        if r["block"]:
            ibits.append(f"block {r['block']}")
        for label, key in (("supplier", "supplier"), ("invoice", "invoice"), ("lot", "lot")):
            if r[key] is None:
                continue  # the record type has no such field
            if not r[key]:
                ibits.append(f"{label} not recorded")
            elif key == "invoice":
                # Same anti-doubling guard as the sale's invoice ("Invoice WE-4471").
                ibits.append(_labelled(label, r[key], _INVOICE_WRITTEN))
            else:
                ibits.append(f"{label} {r[key]}")
        ibits.append(f"file: {files(r['documents'])}")
        # Sprays only: the days to the earliest pick NAMED ON THIS SALE on or after the spray, beside the
        # PHI the operation recorded (`traceback._set_days_to_pick` reads the sale's picks only). "The
        # next pick" read as the block's next pick, and "the first pick in this lot" as the season's
        # first; both can be sooner (packet reviews of 2026-10-29 and 2026-10-31).
        if r.get("days_to_pick") is not None:
            phi = f"PHI recorded: {r['phi_days']} days" if r["phi_days"] else "no PHI recorded"
            ibits.append(f"{r['days_to_pick']} days before the pick sold on this invoice ({phi})")
            if r["inside_phi"]:
                ibits.append("picked sooner than the recorded PHI")
        out.append(Paragraph(_escape("• " + " · ".join(ibits)), styles["meta"]))
    out.append(Paragraph("<b>Missing links in this chain</b>", styles["body"]))
    if t["gaps"]:
        for g in t["gaps"]:
            out.append(Paragraph(_escape("• " + gap_sentence(g, t["inputs"], t["picks"])), styles["meta"]))
    else:
        out.append(Paragraph("• None: every link in this chain is recorded.", styles["meta"]))
    return out


def _sale_source_flowables(sale, styles) -> list:
    """The documents behind one sale line (OSP alignment audit T22).

    The line above prints the invoice and BOL numbers as the operation typed them. A number is a
    record OF a document, not the document, so each sale says which files ride in this packet and,
    when none does, that only the number is recorded. A typed number is never presented as a source
    the packet holds.
    """
    from certifications.services.packet_attachments import current_manifest, state_words

    manifest = current_manifest()
    if manifest is None or not sale.get("id"):
        return []
    entries = manifest.for_sale(sale["id"])
    if entries:
        return [Paragraph(_escape(state_words(entry)), styles["meta_indent"]) for entry in entries]
    recorded = [label for label, key in (("invoice", "invoice"), ("bill of lading", "bol")) if sale.get(key)]
    if recorded:
        what = " and ".join(f"{label} number" for label in recorded)
        return [
            Paragraph(
                _escape(
                    f"The {what} {'is' if len(recorded) == 1 else 'are'} recorded as text; no source document is attached."
                ),
                styles["meta_indent"],
            )
        ]
    return [
        Paragraph(
            "No source document is attached and no invoice or bill of lading number is recorded.", styles["meta_indent"]
        )
    ]


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


#: How each open state reads on the coverage page, in the order the page lists them.
_OPEN_STATE_WORDING = (
    ("unanswered", "not yet answered"),
    ("unconfirmed", "answered on an earlier version of the question, not yet confirmed"),
    ("unresolved", "waiting on an earlier answer that decides whether it applies"),
    ("route_unresolved", "not determined for parcels whose route is unresolved"),
    ("partial", "answered in part: Trazo does not collect everything the form asks"),
    ("not_collected", "not collected by Trazo"),
    ("attachment_missing", "attachment not uploaded"),
    ("attachment_unreadable", "the file uploaded for it could not be read, so it is not in this packet"),
    (
        "attachment_held_outside_packet",
        "the file is kept in Trazo's document store, not in this packet (the packet's size limit was reached)",
    ),
    (
        "attachment_not_identified",
        "files are uploaded to this section but none is identified as this attachment, and none is in this packet",
    ),
    ("not_assessed", "not checked against this plan's answers"),
    ("unknown_reference", "not checked against this plan's answers"),
)


def _attachment_name(detail: str) -> str:
    """ "Upload your current label files" -> "your current label files"."""
    text = (detail or "").strip()
    return text[len("Upload ") :] if text.startswith("Upload ") else text


def _open_rows_sentence(open_rows) -> str:
    """ "Still open: A1, A3 not yet answered; C2 not collected by Trazo." Refs only, never a count of a total."""
    parts = []
    grouped: dict[str, list[str]] = {}
    unresolved_groups: dict[frozenset, list[str]] = {}
    for row in open_rows:
        ref = row.ref
        if row.state in ("attachment_unreadable", "attachment_held_outside_packet") and row.detail:
            ref = f"{row.ref} ({row.detail})"
        elif row.state in ("attachment_missing", "attachment_not_identified") and row.detail:
            ref = f"{row.ref} ({_attachment_name(row.detail)})"
        elif row.state == "route_unresolved":
            # Grouped by the SET of parcels the route is unresolved for, read from the row's own
            # judged parts, never re-parsed from the detail string (review of back #137: a comma
            # or colon in a parcel name broke the parse, and a union across rows paired every
            # ref with every parcel). Each group prints one clause (recordkeeping review S9).
            parcels = frozenset(
                part[1]
                for part in (getattr(row, "parts", None) or ())
                if len(part) >= 3 and part[2] == "route_unresolved"
            )
            unresolved_groups.setdefault(parcels, []).append(row.ref)
            continue
        grouped.setdefault(row.state, []).append(ref)
    seen_wording: dict[str, list[str]] = {}
    for state, wording in _OPEN_STATE_WORDING:
        if state in grouped:
            seen_wording.setdefault(wording, []).extend(grouped[state])
    for wording, refs in seen_wording.items():
        parts.append(f"{', '.join(refs)} {wording}")
    for parcels, refs in unresolved_groups.items():
        where = ", ".join(sorted(parcels)) if parcels else "parcels whose route is unresolved"
        parts.append(
            f"{', '.join(refs)} not determined for {where}: name each parcel's prior certifying agent on its "
            "Parcel Application (section F) and the route follows"
        )
    return "Still open: " + "; ".join(parts) + "."


def _route_skipped_sentence(rows) -> str:
    """ "Not asked on these parcels' route: 2.4, 2.5 (Home Field East, ...: C2 is not refiled ...)."

    Run 3, R3-04: a row the parcels' route does not ask is neither answered nor open. It is named apart,
    with the reason, so a reviewer can check the route instead of reading a demand the form never makes.
    """
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(row.detail or "", []).append(row.ref)
    parts = [f"{', '.join(refs)} ({reason})" if reason else ", ".join(refs) for reason, refs in grouped.items()]
    return "Not asked on these parcels' route: " + "; ".join(parts) + "."


def _optional_rows_sentence(rows) -> str:
    """ "Optional items not answered: I1, I2, J." The form marks them optional; they are still open."""
    return "Optional items not answered: " + ", ".join(row.ref for row in rows) + "."


_ACCEPTED_FORMAT_WORDING = {
    "agent_form": "Filed on {agent}'s own form.",
    "agent_web_form": "Filed through {agent}'s online form.",
    "alternative_records_with_required_fields": (
        "{agent} accepts the operation's own records in place of this form when they carry every field it asks."
    ),
}


def _filed_update_note(osp) -> str:
    """The filed § 205.406(a) update for this plan, stated as a record in Trazo, or ""."""
    from django.db.models import Q

    from certifications.models import OSPAnnualUpdate

    filing = (
        OSPAnnualUpdate.objects.filter(submitted_at__isnull=False)
        .filter(Q(new_osp=osp) | Q(prior_osp=osp))
        .order_by("-submitted_at")
        .first()
    )
    if filing is None:
        return ""
    return (
        f" The operation's {filing.reporting_year} annual update was filed in Trazo on "
        f"{filing.submitted_at:%B} {filing.submitted_at.day}, {filing.submitted_at.year}; "
        "it is the operation's record, not this form."
    )


def _coverage_registered_forms(story, styles, osp, certifier, agent_label, parcel_names) -> None:
    """The form list for an agent Trazo holds a register for: answered, in part, filed with the agent."""
    from certifications.services.packet_coverage import coverage_rows, form_coverage, unreviewed_form_count

    rows = coverage_rows(certifier)
    if not rows:
        story.append(
            Paragraph(
                "The form-by-form coverage list could not be read for this packet. The documents "
                "present are listed on the cover page.",
                styles["body"],
            )
        )
        return

    forms = form_coverage(osp, certifier)
    if not forms:
        # The register could not be read: list the packet's own files, unnumbered, and say so.
        story.append(Paragraph("Documents in this packet", styles["header"]))
        story.append(
            Paragraph(
                "The form-by-form numbering could not be read for this packet, so the documents below "
                "are listed by filename only. Their content is unchanged.",
                styles["meta"],
            )
        )
        for row in rows:
            if row.generated:
                story.append(
                    Paragraph(_escape(f"{row.form}: {_coverage_location(row.location, parcel_names)}"), styles["body"])
                )
        return

    story.append(
        Paragraph(
            _escape(
                f"Listed against {agent_label}'s own form numbering, the certifying agent on this "
                "operation's record. A form is listed as answered only when every question on it that "
                "applies to this operation has an answer in this plan. Items the form itself marks "
                "optional are named under the form when they have no answer."
            ),
            styles["meta"],
        )
    )

    def _named(form) -> str:
        return f"{form.form} ({form.document_id})" if form.document_id else form.form

    answered = [f for f in forms if f.standing == "answered"]
    in_part = [f for f in forms if f.standing == "in_part"]
    filed = [f for f in forms if f.standing == "filed_with_agent"]

    if answered:
        story.append(Paragraph("Forms this packet answers", styles["header"]))
        for form in answered:
            story.append(
                Paragraph(_escape(f"{_named(form)}: {_coverage_location(form.location, parcel_names)}"), styles["body"])
            )
            if form.route_skipped_rows:
                story.append(Paragraph(_escape(_route_skipped_sentence(form.route_skipped_rows)), styles["meta"]))
            if form.optional_open_rows:
                story.append(Paragraph(_escape(_optional_rows_sentence(form.optional_open_rows)), styles["meta"]))
    if in_part:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Forms this packet answers in part", styles["header"]))
        story.append(
            Paragraph(
                "The packet carries this plan's answers for these forms. The questions named under each "
                "one are still open, and the agent's own form is needed for them.",
                styles["meta"],
            )
        )
        for form in in_part:
            story.append(
                Paragraph(_escape(f"{_named(form)}: {_coverage_location(form.location, parcel_names)}"), styles["body"])
            )
            if form.open_rows:
                story.append(Paragraph(_escape(_open_rows_sentence(form.open_rows)), styles["meta"]))
            if form.route_skipped_rows:
                story.append(Paragraph(_escape(_route_skipped_sentence(form.route_skipped_rows)), styles["meta"]))
            if form.optional_open_rows:
                story.append(Paragraph(_escape(_optional_rows_sentence(form.optional_open_rows)), styles["meta"]))
    not_on_route = [f for f in forms if f.standing == "not_on_route"]
    if not_on_route:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Forms not filed for these parcels on their route", styles["header"]))
        story.append(
            Paragraph(
                "Each parcel follows the route its certification status takes on this agent's forms. These "
                "forms are not filed for any parcel on its route; nothing on them is asked or answered here.",
                styles["meta"],
            )
        )
        for form in not_on_route:
            reasons = sorted({row.detail for row in form.route_skipped_rows if row.detail})
            line = f"{_named(form)}: " + ("; ".join(reasons) if reasons else "not filed on these parcels' route") + "."
            story.append(Paragraph(_escape(line), styles["body"]))
    if filed:
        story.append(Spacer(1, 6))
        story.append(Paragraph(_escape(f"Forms the operation files with {agent_label}"), styles["header"]))
        story.append(
            Paragraph(
                "This packet supplies supporting material for these forms. It does not complete or replace " "them.",
                styles["meta"],
            )
        )
        update_note = _filed_update_note(osp)
        for form in filed:
            line = f"{_named(form)}: supporting material in {_coverage_location(form.location, parcel_names)}."
            if form.requires_signature:
                line += " It carries the operation's signature."
            if form.accepted_format:
                line += " " + _ACCEPTED_FORMAT_WORDING[form.accepted_format].format(agent=agent_label)
            if form.via_renewal_pages and update_note:
                line += update_note
            story.append(Paragraph(_escape(line), styles["body"]))

    listed = {(f.form, f.document_id) for f in forms}
    others = [r for r in rows if r.generated and (r.form, r.document_id) not in listed]
    if others:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Other documents in this packet", styles["header"]))
        for row in others:
            # A packet module no form of this agent claims still ships, and still has to be listed,
            # with no number rather than a borrowed one.
            named = f"{row.form} ({row.document_id})" if row.document_id else row.form
            story.append(
                Paragraph(_escape(f"{named}: {_coverage_location(row.location, parcel_names)}"), styles["body"])
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


def _coverage_fallback_documents(story, styles, stated_agent, parcel_names) -> None:
    """The packet's documents for an agent Trazo holds no register for, in Trazo's own words.

    🔴 2026-09-30 (audit T23). This page used to number an OCI or MOSA packet against CCOF's forms,
    tell the reviewer "only the numbering differs", and repeat CCOF's own scope reasons ("file the
    affidavit with CCOF directly"). The first claim was never checked (OCI's annual update has its
    own identity, scope, sales and declaration workflow) and the second sent the operation to the
    wrong agent. With no register for the agent, the page borrows no agent's numbering at all.
    """
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
    from certifications.services.packet_coverage import _module_location, _packet_module_keys

    agent = stated_agent.strip()
    story.append(Paragraph("Documents in this packet", styles["header"]))
    story.append(
        Paragraph(
            _escape(
                f"Trazo does not hold {agent}'s form list. These documents are supporting "
                f"material for {agent}'s own forms; ask {agent} which of its forms apply to this operation."
                if agent
                else "No certifying agent is named on this operation's records. These documents are "
                "supporting material for the agent's own forms; ask the agent which of its forms apply "
                "to this operation."
            ),
            styles["meta"],
        )
    )
    modules = dict(MODULES_BY_KEY)
    modules[PARCEL_APPLICATION.key] = PARCEL_APPLICATION
    for key in _packet_module_keys():
        location = _module_location(key)
        module = modules.get(key)
        if not location or module is None:
            continue
        title = module.title.get("en", key) if isinstance(module.title, dict) else str(module.title)
        story.append(Paragraph(_escape(f"{title}: {_coverage_location(location, parcel_names)}"), styles["body"]))


def _coverage_pdf(osp) -> bytes:
    """04 — what this packet covers, what it does not, and who authored it.

    CCOF's Guide routes by activity, so a reviewer already knows which forms a crop operation owes.
    Stating what is absent, and why, is the difference between a scope decision and an omission.
    """
    from certifications.services.packet_coverage import (
        exclusion_rows,
        outstanding_modules,
        packet_agent,
        packet_certifier,
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

    parcel_names = [p.name for p in _packet_parcels(osp.establishment)]
    if is_own_agent:
        _coverage_registered_forms(story, styles, osp, certifier, agent_label, parcel_names)
    else:
        _coverage_fallback_documents(story, styles, stated_agent, parcel_names)

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

    # 🔴 2026-09-30 (audit T23): the exclusions are one agent's scope file. For an operation whose
    # agent Trazo holds no register for, they were CCOF's, and told an OCI grower to file forms
    # "with CCOF directly". A fallback packet lists no agent's exclusions.
    exclusions = exclusion_rows(certifier) if is_own_agent else []
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

    pending = outstanding_modules(osp, with_codes=is_own_agent, with_reasons=True)
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

    ⛔ AN ACTIVE PLAN IS COMPILED IN MEMORY, NEVER WRITTEN (recordkeeping review F-06,
    2026-10-07). The active plan is the one on file with the certifying agent. Downloading the
    v3 packet of the Calapooia specimen moved `OrganicSystemPlan.updated_at` from 2026-08-21 to
    the download time and document 01 printed "Last updated: <today>" on a plan "Submitted
    2026-08-21": a read rewrote the on-file record. The 2026-08-28 one-packet-one-answer fix
    still holds, because the compiled narratives live on this instance for the rest of the
    build; they are just not persisted. Document 01 says so when the plan has no frozen
    submission copy (`generate_osp_snapshot_pdf`).
    """
    status = getattr(osp, "status", None)
    if status not in ("draft", "active"):
        return
    try:
        from certifications.services.osp_module_compiler import compile_modules_to_sections

        if compile_modules_to_sections(osp) and status == "draft":
            osp.save(update_fields=["sections", "updated_at"])
    except Exception:  # noqa: BLE001 — a stale narrative is bad; no packet at all is worse
        logger.exception("Could not refresh narratives before assembling the packet for OSP %s", osp.pk)


def generate_osp_packet(osp) -> bytes:
    """Assemble the renewal packet ZIP. Single source of packet content."""
    from certifications.services.packet_attachments import build_manifest, building
    from certifications.services.packet_index_recorder import document, recording

    _refresh_narratives_if_editable(osp)
    establishment = osp.establishment
    manifest = build_manifest(osp)
    out = io.BytesIO()
    with building(manifest), recording() as recorder, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:

        def write(path, data, filed=False):
            # Every document is kept by path for 06, the question index, which is built last and
            # reads them back to say where each form and question is (T24).
            zf.writestr(path, data)
            recorder.documents[path] = data
            if filed:
                recorder.filed.add(path)

        write("00-cover.pdf", _packet_cover_pdf(osp))
        # "01-organic-system-plan.pdf", not "01-narrative-snapshot.pdf" (2026-09-07). This file
        # IS the organic system plan — the § 205.201(a) narratives plus the § 205.401(d)
        # producer attestation — and it is the document a reviewer opens the ZIP looking for.
        # "Narrative snapshot" describes how we build it (a frozen copy of the narratives at
        # submission), which is our vocabulary, not theirs. The frozen-version meaning is not
        # lost: the page title says "Submission Snapshot" once the plan is submitted, and carries the version.
        write("01-organic-system-plan.pdf", generate_osp_snapshot_pdf(osp))
        # The two documents a renewal IS, and which the "renewal packet" did not contain until
        # 2026-08-23: the § 205.406(a) filing and the § 205.400(f) notices that support it.
        from certifications.services.annual_update_filing import filed_bytes, packet_revision_filename, year_revisions

        _ctx = _renewal_context(osp)
        write(
            "02-annual-update.pdf",
            _annual_update_pdf(osp),
            filed=bool(_ctx["filing"] is not None and filed_bytes(_ctx["filing"])),
        )
        write("02s-renewal-status-and-routing.pdf", _renewal_status_pdf(osp))
        # Every revision of the year as its own file: a filed one is its frozen bytes, so a
        # correction never hides the revision it corrected.
        for _revision in year_revisions(_ctx["filing"]):
            _frozen = filed_bytes(_revision)
            write(packet_revision_filename(_revision), _frozen or render_filing_pdf(_revision), filed=bool(_frozen))
        write("03-change-notifications.pdf", _change_notifications_pdf(osp))
        # 04 — scope. CCOF's Guide routes by activity, so what is missing is as readable as what
        # is present; this states it rather than leaving a reviewer to infer an omission.
        write("04-coverage-and-scope.pdf", _coverage_pdf(osp))
        # 05 — the § 205.103(b)(2) trace, generated (2026-09-09): the document table OTCO C12 Q6
        # asks for and the sample audit trail CCOF G8.0 B1 asks to attach.
        write("05-audit-trail-exhibit.pdf", _audit_trail_exhibit_pdf(osp))
        from certifications.services.packet_coverage import module_file_stem

        for module in MODULE_REGISTRY:
            path = f"modules/{module_file_stem(module)}.pdf"
            with document(path):
                write(path, generate_module_pdf(osp, module.key))
        for parcel in _packet_parcels(establishment):
            path = _parcel_application_filename(parcel)
            recorder.parcel_files[path] = parcel.name
            with document(path):
                write(path, generate_module_pdf(osp, PARCEL_APPLICATION.key, parcel=parcel))
        # The agent-neutral USDA sheets always; an agent's own sheet (OTCO FACT-04) only when the
        # packet is numbered to that agent — the coverage page applies the same filter.
        from certifications.services.packet_coverage import packet_certifier

        agent, is_own = packet_certifier(osp)
        for spec in workbooks_for(agent if is_own else None):
            workbook = build_workbook(establishment, spec.key, osp=osp)
            write(f"workbooks/{_workbook_filename(spec)}", workbook.getvalue())

        # 06 — the agent-ordered index, built last because it cites the pages above.
        from certifications.services.question_index import index_pdf

        zf.writestr("06-question-index.pdf", index_pdf(osp, recorder))

        # Every operator file (maps, affidavits, receipts, the files uploaded for a named
        # attachment, a sale's source documents, lot tags and label photos) was read once, before
        # any page was written, so the pages above name exactly what is written here. A file that
        # could not be read or did not fit is named on those pages and is not written.
        for _entry in manifest.attached():
            zf.writestr(_entry.zip_path, _entry.data)
    return out.getvalue()
