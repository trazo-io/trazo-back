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
    evaluate,
    is_answered,
    visible_pages,
    visible_questions,
)
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.common_osp_workbooks import build_workbook, workbooks_for
from certifications.services.osp_module_compiler import _format_answer_en
from certifications.services.osp_pdf_snapshot import SECTION_LABELS, _styles, generate_osp_snapshot_pdf, signature_block
from certifications.services.restricted_materials import module_lines as restricted_material_lines

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


def _lot_code_key_flowables(osp, module, question, value, styles) -> list:
    """G8.0 `lot_code_key` as CCOF G8.0 B2's Code / Signifies table, when every line reads as one row.

    Empty when the answer does not split cleanly; the caller then prints it as written.
    """
    if module.key != "g8_0_record_keeping" or question.key != "lot_code_key":
        return []
    from reportlab.platypus import Table, TableStyle

    from certifications.services.lot_code_key import key_rows

    rows = key_rows(value)
    if not rows:
        return []
    data = [[Paragraph("<b>Code</b>", styles["meta"]), Paragraph("<b>Signifies</b>", styles["meta"])]]
    data += [
        [Paragraph(_escape(code), styles["meta"]), Paragraph(_escape(meaning), styles["meta"])]
        for code, meaning in rows
    ]
    table = Table(data, colWidths=[1.6 * inch, 5.0 * inch], repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2EFDA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return [table, Spacer(1, 4)]


def _lot_key_and_trace_lines(osp, module, question, value, answers) -> list:
    """Lines a reviewer needs beside two G8.0 §B answers.

    `lot_code_key`: lot numbers on the operation's own production records, so the key can be read
    against them (or the fact that none is recorded). `trace_mechanisms`: a [REVIEW] when the plan
    names no lot numbering and nothing else that traces a sale back to the field (§ 205.103(b)(2)).
    """
    if module.key != "g8_0_record_keeping":
        return []
    if question.key == "lot_code_key":
        from certifications.services.lot_code_key import recorded_lot_ids

        lots = recorded_lot_ids(osp.establishment)
        if not lots:
            return ["No lot number is recorded on this operation's production records yet."]
        return ["Lot numbers on this operation's production records, most recent first: " + ", ".join(lots) + "."]
    if question.key == "trace_mechanisms":
        chosen = value if isinstance(value, (list, tuple)) else [value]
        if list(chosen) == ["lot_numbers_only"] and answer_value(answers, "lot_numbering") == "none":
            return [
                "[REVIEW] The plan says no lot numbering is used and nothing besides lot numbers traces a sale "
                "back to the field, so it names no way to trace product (§ 205.103(b)(2))."
            ]
    return []


def _cover_certificate_value(ctx) -> str:
    """The cover's certificate line. A certificate recorded on the farm profile without its number reads as
    recorded, not as a dash (first-run audit, 2026-11-21); the agent always comes from the same record."""
    number = ctx.get("certificate_number") or ""
    if number:
        return number + (f" — {ctx['certifier_name']}" if ctx.get("certifier_name") else "")
    unnumbered = ctx.get("certificate_unnumbered_agent")
    if unnumbered is not None:
        return "recorded on the farm profile, number not recorded" + (f" ({unnumbered})" if unnumbered else "")
    return "—"


def _treated_lumber_parcel_lines(osp, module, question, value) -> list:
    """A plan that says no treated lumber is present, beside a parcel application in the same packet
    that says treated lumber is there: in contact with crops or soil (`Parcel.treated_lumber_present`),
    or an installation touching neither (`treated_lumber_noncontact_present`)."""
    if module.key != "g6_0_production" or question.key != "treated_lumber_any" or value is not False:
        return []
    lines = []
    parcels = list(_packet_parcels(osp.establishment))
    contact = [p.name for p in parcels if p.treated_lumber_present]
    if contact:
        lines.append(
            "[REVIEW] The parcel application for " + ", ".join(contact) + " says treated lumber is in contact "
            "with crops or soil."
        )
    other = [
        p.name
        for p in parcels
        # Only under an answered No: the installation question is asked only then (null since 2026-11-21).
        if p.treated_lumber_present is False
        and (p.application_answers or {}).get("treated_lumber_noncontact_present") is True
    ]
    if other:
        lines.append(
            "[REVIEW] The parcel application for " + ", ".join(other) + " says a treated-lumber installation "
            "is within the parcel's boundaries."
        )
    return lines


def _map_element_lines(osp, module, question, value, parcel) -> list:
    """Under the operator's list of what their parcel map shows: what the plan's agent asks the map to
    show that the operator did not mark (`certifications.services.parcel_map_elements`)."""
    if module.key != "parcel_application" or question.key != "map_elements_shown" or parcel is None:
        return []
    from certifications.services.packet_attachments import ATTACHED, PARCEL_MAP_REQUIREMENT, current_manifest
    from certifications.services.packet_coverage import packet_certifier
    from certifications.services.parcel_map_elements import unmarked_line
    from product.services.parcel_application_status import parcel_application_values

    lines = []
    # The list describes the operator's map. Without that map in the reviewer's hands it describes a
    # document they cannot check (browser pass 2026-11-08: a parcel with no upload printed the list
    # straight under "No operator-supplied map is attached"). Inside a packet the manifest decides.
    manifest = current_manifest()
    if manifest is not None:
        held = any(e.state == ATTACHED for e in manifest.for_requirement(PARCEL_MAP_REQUIREMENT, parcel_id=parcel.pk))
    else:
        held = bool(parcel_map_documents(parcel))
    if not held:
        lines.append(
            "[REVIEW] No operator-supplied map is in this packet, so this list describes a map the reviewer "
            "does not hold."
        )
    agent, own = packet_certifier(osp)
    line = unmarked_line(value, parcel_application_values(parcel), osp, agent if own else None)
    return lines + ([line] if line else [])


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


def _answer_as_it_stands(module, question, value, answers, osp, cache: dict) -> str:
    """The answer as printed: the operator's words, and for a Yes the records now refuse, that fact.

    The write path refuses a Yes the records contradict (`attestation_gates`): the G8.0 records
    statement over records the plan requires but nobody confirmed, and the Materials Application
    "listed" statements while the records name products the list does not hold. A Yes stored before
    those gates still printed bare, above or beside the note saying otherwise, so the page read as
    the operator affirming what the same page disproved (reviewer reads, 2026-11-04). It is still the
    operator's answer and stays visible; it just says it no longer stands. Computed once per module.
    """
    from certifications.services.attestation_gates import affirms

    text = _format_answer_en(question, value)
    if not affirms(question.key, value):
        return text
    if getattr(question, "attests_embed", None):
        # The embed attestation already prints its own note right below, naming what is not
        # confirmed and saying the Yes is not supported; saying it twice reads as two findings
        # (review of back #305).
        return text
    if "keys" not in cache:
        from certifications.services.attestation_gates import blocked_attestations

        cache["keys"] = blocked_attestations(module, answers, osp)
    if question.key in cache["keys"]:
        return f"{text}, as answered before the records showed otherwise; it is not supported by the plan as it stands."
    return text


def _unlisted_category_lines(osp, question, value, bundles: dict) -> list[str]:
    """A [REVIEW] line beside a Materials Application "Yes" whose category of logged products is
    not all on the plan's list under the same name.

    The Yes is the operator's statement and prints as given. Beside it the reviewer sees the
    products the records name for that category that the list does not hold by name, which is
    the comparison the statement is about (OTCO C5 5.1-6, CCOF ORGB41 "Only materials included in
    your OSP Materials List may be used"). It says what is known and no more: a brand can be covered
    by a substance entry the operator has not tied to it yet.
    """
    from certifications.services.osp_prefill import MATERIALS_CATEGORIES, materials_category, unlisted_category_products

    category = materials_category(question.key)
    if value is not True or category is None:
        return []
    from certifications.services.common_osp_records import EvidenceBundle

    try:
        if "bundle" not in bundles:
            bundles["bundle"] = EvidenceBundle(osp.establishment)
        unlisted = unlisted_category_products(osp, bundles["bundle"], question.key)
    except Exception:  # noqa: BLE001 (a comparison that cannot be made must not sink the packet)
        logger.exception("Logged products could not be compared with the list for %s", question.key)
        return ["[REVIEW] The logged products could not be compared with the materials list."]
    if not unlisted:
        return []
    shown = unlisted[:12]
    listed = ", ".join(shown) + (f", and {len(unlisted) - len(shown)} more" if len(unlisted) > len(shown) else "")
    label = MATERIALS_CATEGORIES[category][1]
    return [
        f"[REVIEW] The records name {len(unlisted)} {label} product(s) that this plan's materials "
        f"list does not hold by name, and that no current decision on the plan ties to a listed "
        f"product: {listed}."
    ]


def _module_for_key(module_key: str):
    if module_key == PARCEL_APPLICATION.key:
        return PARCEL_APPLICATION
    module = _REGISTRY_BY_KEY.get(module_key)
    if module is None:
        raise ValueError(f"Unknown OSP module: {module_key!r}")
    return module


def module_document_title(module_key: str, parcel=None) -> str:
    """The title a module PDF carries on the Documents shelf: "OSP module PDF — G3.0 Seeds &
    Planting Stock", or "OSP module PDF — Parcel Application (East Block)".

    It used to print the registry key ("g3_0_seeds", "parcel_application"), which is an
    identifier, not a name a grower or a certifier has ever seen. The code and title are the
    ones the module's own PDF heading prints, so the shelf row and the file it opens agree.
    Stored English, like every other generated title on the shelf.
    """
    module = _module_for_key(module_key)
    name = _en(module.title)
    label = f"{module.code} {name}" if module.code else name
    where = f" ({parcel.name})" if parcel is not None else ""
    return f"OSP module PDF — {label}{where}"


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


def seedling_supplier_lines(row, buys_certified: bool = False) -> list[str]:
    """What G3.0a prints under one supplier (`supplier_certificates.seedling_suppliers`).

    The same words as the audit export's supplier cell: never "verified" or "expired". A copy is the
    operation's own record, and whether an old copy still proves the supplier's status on the day
    is the certifier's call (205.404(d)), so those print for review.
    """
    from history.services import supplier_certificates as sc

    supplier = row["supplier"] or {}
    who = ", ".join(
        x
        for x in (
            supplier.get("certifier"),
            supplier.get("nop_operation_id") and f"NOP ID {supplier['nop_operation_id']}",
        )
        if x
    )
    n = row["purchases"]
    latest = row["latest"].isoformat() if row["latest"] else "date not recorded"
    lines = [f"{n} transplant purchase{'s' if n != 1 else ''} recorded, latest {latest}." + (f" {who}." if who else "")]
    cert = row["certificate"]
    status = row["status"]
    # The coverage page's rule, so a supplier it holds open is the one flagged here.
    owes = sc.needs_certificate(row, buys_certified)
    if status == sc.COVERING:
        lines.append(f"Organic certificate issued {cert.issued_on.isoformat()} covers the latest purchase.")
    elif status == sc.STALE:
        lines.append(
            f"[REVIEW] The newest certificate copy before the latest purchase was issued "
            f"{cert.issued_on.isoformat()}, more than 15 months earlier."
        )
    elif status == sc.POSTDATES_PURCHASE:
        lines.append(
            f"[REVIEW] The certificate copy on file was issued {cert.issued_on.isoformat()}, after the latest purchase."
        )
    elif status == sc.NOT_CERTIFIED:
        lines.append("Recorded in the supplier register as not a certified organic operation.")
        if owes:
            lines.append("[REVIEW] A purchase from this supplier is recorded as certified organic stock.")
    elif status == sc.NONE_ON_FILE:
        lines.append(
            ("[REVIEW] " if owes else "") + "No copy of this supplier's organic certificate is on file in Trazo."
        )
    else:
        lines.append(
            ("[REVIEW] " if owes else "")
            + "This name is not in the operation's supplier register, so no certificate copy is tied to it."
        )
    if row["not_covered"] and owes:
        k = row["not_covered"]
        lines.append(
            f"[REVIEW] {k} earlier purchase{'s' if k != 1 else ''} from this supplier "
            f"{'is' if k == 1 else 'are'} not covered by a certificate copy on file."
        )
    if cert is not None:
        from certifications.services.packet_attachments import current_manifest, supplier_certificate_source

        manifest = current_manifest()
        if manifest is None:
            lines.append("A copy is held in Trazo; it is not included in this document.")
        else:
            entries = manifest.for_source(supplier_certificate_source(cert))
            if entries and entries[0].state == "attached":
                lines.append(f"Copy in this packet: {entries[0].zip_path}")
            elif entries:
                lines.append(f"Copy not in this packet ({entries[0].detail}).")
            else:
                lines.append("Copy not in this packet.")
    return lines


def _material_wsda_annotation_lines(osp, row) -> list:
    """The line under a WSDA-listed material giving WSDA's own annotation for it, and how the operator
    states it is met (2026-11-17).

    WSDA's list states that registered products must be used in accordance with all noted annotations,
    and WSDA AGR 2196 asks how each material's restrictions are met. Until this line the packet printed
    "Deficiency must be documented." nowhere, for 140 of the products a grower could list. A product
    WSDA prints NONE for gets no line: NONE is not "no restrictions", and the label is not on file here.
    The operator's answer is quoted only from a current statement that answers this annotation: one made
    against it, or one transcribed from the WSDA listing in the annotation's words."""
    from certifications.models import PlanMaterialRestrictionStatement as PRS
    from certifications.services.material_restrictions import (
        CURRENT,
        _wsda_source,
        answers_wsda_annotation,
        material_ref,
        statement_state,
        wsda_list_restriction,
    )

    kind, mid, _name = material_ref(row)
    held = wsda_list_restriction(osp, kind, mid) if kind else None
    if held is None:
        return []
    answers = [
        st.how_met.strip()
        for st in PRS.objects.filter(osp=osp, material_kind=kind, material_id=mid, superseded_at__isnull=True).order_by(
            "stated_at", "id"
        )
        if answers_wsda_annotation(st, held) and (st.how_met or "").strip() and statement_state(st, osp) == CURRENT
    ]
    met = f'How the operator states it is met: "{"; ".join(answers)}".' if answers else "How it is met: not stated."
    return [f"{_wsda_source(held['citation'], held['effective_date'])}: \"{held['text']}\" {met}"]


def _material_label_lines(row, labels_asked: bool) -> list:
    """The line under one material about its label or container photo.

    OTCO C11 11.1: "Labels or photos of container are attached for each product that is not OMRI or
    WSDA listed." A label on file is stated wherever it is, under any agent; its absence is stated
    only where the plan's agent asks for one, and only for a product its listing does not cover.
    Only a file the packet actually carries is given as in it (`packet_attachments`).
    """
    if row.label_document_id:
        from certifications.services.packet_attachments import current_manifest

        manifest = current_manifest()
        if manifest is None:
            return ["Label or container photo: held in Trazo; not included in this document."]
        entries = manifest.for_source(f"doc:{row.label_document_id}")
        if entries and entries[0].state == "attached":
            return [f"Label or container photo in this packet: {entries[0].zip_path}"]
        if entries:
            return [f"Label or container photo: not in this packet ({entries[0].detail})."]
        return ["Label or container photo: not in this packet."]
    if labels_asked and row.needs_label:
        return ["Label or container photo: none on file (C11 11.1 asks for one for a product not OMRI or WSDA listed)."]
    return []


def _seedling_supplier_flowables(osp, styles) -> list:
    """The suppliers the operation's transplant purchases name, each with its certificate state.

    CCOF G3.0 A2, OTCO C3 3.1-2 and WSDA 2121-B 1/1a ask for the certificate of each supplier of
    purchased seedlings. Until 2026-11 a certificate was a plan-level upload tied to no supplier, so
    nothing said which supplier's copy was on file.
    """
    from history.services.supplier_certificates import buys_certified_seedlings, seedling_suppliers

    rows = seedling_suppliers(osp.establishment) if osp.establishment_id else []
    buys = buys_certified_seedlings(osp)
    if not rows:
        return [
            Paragraph("No transplant purchase naming a supplier is recorded in Trazo.", styles["body"]),
            Spacer(1, 6),
        ]
    out = [Paragraph("<b>Seedling suppliers on the transplant records</b>", _sticks_to_next(_style(styles, "body")))]
    for row in rows:
        out.append(Paragraph(f"<b>{_escape(row['name'])}</b>", _sticks_to_next(_style(styles, "body"))))
        for line in seedling_supplier_lines(row, buys):
            out.append(Paragraph(_escape(line), styles["meta"]))
    out.append(
        Paragraph(
            "Certificates are the copies this operation filed in Trazo and the dates printed on them. They "
            "are the operation's records, not a check against the USDA Organic Integrity Database.",
            styles["meta"],
        )
    )
    out.append(Spacer(1, 6))
    return out


def sourced_product_lines(row) -> list[str]:
    """What G6.5 prints under one sourcing supplier (`sourced_products.sourcing_rows`)."""
    from certifications.services import sourced_products as sp

    supplier = row["supplier"]
    products = [x.strip() for x in supplier.sourced_products.splitlines() if x.strip()]
    lines = ["Bought in: " + "; ".join(products) + "."]
    who = ", ".join(
        x for x in (supplier.certifier_name, supplier.nop_operation_id and f"NOP ID {supplier.nop_operation_id}") if x
    )
    state = row["state"]
    document = row["document"]
    if supplier.organic_status == "certified":
        lines.append("Certified organic operation" + (f" ({who})." if who else "."))
        if state == sp.CERTIFICATE_MISSING:
            lines.append("[REVIEW] No copy of this supplier's organic certificate is on file in Trazo.")
        else:
            from certifications.services.sourced_products import newest_certificate

            newest = newest_certificate(supplier)
            if state == sp.CERTIFICATE_OLD:
                lines.append(
                    f"[REVIEW] The newest certificate copy on file was issued {newest.issued_on.isoformat()}, more "
                    "than 15 months ago."
                )
            else:
                lines.append(f"Organic certificate copy issued {newest.issued_on.isoformat()} is on file.")
    elif supplier.organic_status == "not_certified":
        lines.append("Not a certified organic operation (a broker or distributor).")
        if supplier.source_operation.strip():
            lines.append(f"Sources from: {supplier.source_operation.strip()}.")
        else:
            lines.append("[REVIEW] The certified operation this supplier sources from is not named.")
        if state == sp.AFFIDAVIT_MISSING:
            lines.append("[REVIEW] No Exempt Handler Affidavit from this supplier is on file in Trazo.")
        else:
            lines.append("Its Exempt Handler Affidavit is on file.")
    else:
        lines.append("[REVIEW] Whether this supplier is a certified organic operation is not stated.")
    if document is not None:
        from certifications.services.packet_attachments import ATTACHED, current_manifest

        manifest = current_manifest()
        if manifest is None:
            lines.append("A copy is held in Trazo; it is not included in this document.")
        else:
            entries = manifest.for_source(sp.document_source(document))
            if entries and entries[0].state == ATTACHED:
                lines.append(f"Copy in this packet: {entries[0].zip_path}")
            else:
                lines.append(
                    f"Copy not in this packet ({entries[0].detail})." if entries else "Copy not in this packet."
                )
    return lines


def _sourced_product_flowables(osp, styles) -> list:
    """The suppliers the operation buys organic product from: CCOF G6.5 A1/A2, OTCO C12 12.2-4.

    Until 2026-11 G6.5 asked only "Do you buy or resell organic product from anyone else?" and how
    certificates are verified, in prose, with no supplier, product or copy behind it.
    """
    from certifications.services.sourced_products import sourcing_rows

    rows = sourcing_rows(osp.establishment) if osp.establishment_id else []
    if not rows:
        return [
            Paragraph(
                _escape(
                    "[REVIEW] The plan says the operation buys in or co-markets organic product, and no supplier "
                    "of it is recorded in the supplier register."
                ),
                styles["body"],
            ),
            Spacer(1, 6),
        ]
    out = [
        Paragraph("<b>Suppliers of bought-in organic product</b>", _sticks_to_next(_style(styles, "body"))),
        _register_table(
            ("Supplier", "As recorded in the supplier register"),
            _TWO_COLUMN_WIDTHS,
            [([[row["supplier"].name], sourced_product_lines(row)], []) for row in rows],
            styles,
        ),
        Spacer(1, 4),
    ]
    out.append(
        Paragraph(
            "Certificates and affidavits are the copies this operation filed in Trazo. They are the operation's "
            "records, not a check against the USDA Organic Integrity Database.",
            styles["meta"],
        )
    )
    out.append(Spacer(1, 6))
    return out


def brand_owner_lines(row, agreement: str) -> list[str]:
    """What G7.0 page C prints under one brand owner (`brand_owners.brand_owner_rows`)."""
    from certifications.services import brand_owners as bo

    owner = row["owner"]
    lines = []
    if owner.brand_names.strip():
        lines.append(f"Brands: {'; '.join(x.strip() for x in owner.brand_names.splitlines() if x.strip())}.")
    who = ", ".join(
        x for x in (owner.certifier_name, owner.nop_operation_id and f"NOP ID {owner.nop_operation_id}") if x
    )
    state = row["state"]
    if owner.certification_status == "certified":
        lines.append("Certified organic operation" + (f" ({who})." if who else "."))
        if state == bo.CERTIFICATE_MISSING:
            lines.append("[REVIEW] No copy of this brand owner's organic certificate is on file in Trazo.")
        elif state == bo.CERTIFICATE_OLD:
            issued = owner.certificate_issued_on.isoformat() if owner.certificate_issued_on else "an unstated date"
            lines.append(f"[REVIEW] The certificate copy on file was issued {issued}, more than 15 months ago.")
        else:
            lines.append(f"Organic certificate copy issued {owner.certificate_issued_on.isoformat()} is on file.")
    elif owner.certification_status == "not_certified":
        lines.append("Not a certified organic operation.")
        if state == bo.AGREEMENT_MISSING:
            lines.append(
                f"[REVIEW] Packing into an uncertified brand owner's label needs the {agreement}; none is on file in Trazo."
            )
        else:
            lines.append(f"The {agreement} is on file.")
    else:
        lines.append("[REVIEW] Whether this brand owner is a certified organic operation is not stated.")
    products = [x.strip() for x in owner.products.splitlines() if x.strip()]
    if products:
        lines.append("Products packed under this brand, with each label's organic claim: " + "; ".join(products) + ".")
    else:
        lines.append("The products packed under this brand are not listed.")
    document = row["document"]
    if document is not None:
        from certifications.services.packet_attachments import ATTACHED, current_manifest

        manifest = current_manifest()
        if manifest is None:
            lines.append("A copy is held in Trazo; it is not included in this document.")
        else:
            entries = manifest.for_source(bo.document_source(document))
            if entries and entries[0].state == ATTACHED:
                lines.append(f"Copy in this packet: {entries[0].zip_path}")
            else:
                lines.append(
                    f"Copy not in this packet ({entries[0].detail})." if entries else "Copy not in this packet."
                )
    return lines


def _register_table(header, widths, items, styles):
    """One ruled table for a register the plan prints (equipment, brand owners, suppliers).

    `items` is a list of (cells, notes): `cells` holds one list of lines per column, `notes` the
    lines printed across the full width under that item ([REVIEW] lines, the operator's notes).
    The header repeats on every page and an item never splits from its notes or across a page
    break: the loose-line lists these replaced ran one item into the next and left half an item at
    a page foot with nothing saying whose lines continued overleaf (specimen packet, 2026-11-03).
    """
    from reportlab.platypus import Table, TableStyle

    meta = _style(styles, "meta")

    def cell(lines, bold=False):
        text = "<br/>".join(_escape(x) for x in lines if x)
        return Paragraph(f"<b>{text}</b>" if bold else text, meta)

    data = [[cell([h], bold=True) for h in header]]
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    spans = []
    for cells, notes in items:
        first = len(data)
        data.append([cell(lines, bold=(i == 0)) for i, lines in enumerate(cells)])
        if notes:
            data.append([cell(notes)] + [""] * (len(header) - 1))
            commands.append(("SPAN", (0, first + 1), (-1, first + 1)))
            commands.append(("TOPPADDING", (0, first + 1), (-1, first + 1), 0))
        last = len(data) - 1
        spans.append((first, last))
        commands.append(("NOSPLIT", (0, first), (-1, last)))
        commands.append(("LINEBELOW", (0, last), (-1, last), 0.25, colors.grey))

    def build(split_in_row=0):
        table = Table(data, colWidths=[w * inch for w in widths], repeatRows=1, hAlign="LEFT", splitInRow=split_in_row)
        table.setStyle(TableStyle(commands))
        return table

    # A row cannot break across pages, so an item taller than a page (a pasted procedure in one cell)
    # raised LayoutError and failed the whole packet (review of #276). Only then may a row split, as
    # a last resort: ReportLab still tries every whole-item break first, but a table allowed to split
    # inside a row would also split an item that merely starts at a page foot, so it is not the default.
    probe = build()
    probe.wrap(sum(widths) * inch, _TALLER_THAN_A_PAGE * 10)
    heights = probe._rowHeights
    if any(sum(heights[a : b + 1]) > _TALLER_THAN_A_PAGE for a, b in spans):
        return build(split_in_row=1)
    return probe


#: An item taller than this cannot sit whole on one page under the table's header: the module PDF's
#: frame is 9.5 in (letter, 0.75 in margins), less the header row and the frame's padding.
_TALLER_THAN_A_PAGE = 8.5 * inch

#: The supplier and brand-owner tables: the name, then what the register holds, in sentences too
#: long for columns of their own (certificate state, the copy's place in the packet, products).
_TWO_COLUMN_WIDTHS = (1.7, 5.1)

#: G6.0 page F's equipment table, in the columns CCOF G6.0 C2, OTCO C9 9.1 and WSDA AGR 2121 I ask.
EQUIPMENT_COLUMNS = (
    "Equipment",
    "Used for",
    "Dedicated to organic",
    "Ownership",
    "Cleaning before organic use",
    "Rinsed",
)
_EQUIPMENT_WIDTHS = (1.3, 0.8, 0.8, 0.75, 2.15, 1.0)


def equipment_cells(row) -> list[list[str]]:
    """One item's cells under `EQUIPMENT_COLUMNS` (`production_equipment.equipment_rows`).

    A fact the item owes and lacks reads "Not stated"; its [REVIEW] line is in `equipment_notes`. A
    cleaning fact the item does not owe (dedicated and owned) reads "None stated", never "not
    needed": that is what the register holds, not a ruling on the item.
    """
    from certifications.services.production_equipment import needs_cleaning

    item = row["item"]
    owes = needs_cleaning(item)
    unstated = "Not stated" if owes else "None stated"
    dedicated = {True: "Yes", False: "No, also non-organic"}.get(item.dedicated_organic, "Not stated")
    cleaning = [item.cleaning_method.strip() or unstated]
    if item.cleaning_materials.strip():
        cleaning.append(f"Materials: {item.cleaning_materials.strip()}")
    rinsed = [{True: "Yes", False: "No"}.get(item.rinsed, unstated)]
    # The operator's own words print even when the yes/no is blank (review of #275).
    if item.rinse_detail.strip():
        rinsed.append(item.rinse_detail.strip())
    return [
        [item.name],
        [item.get_use_display()],
        [dedicated],
        [item.get_ownership_display() if item.ownership else "Not stated"],
        cleaning,
        rinsed,
    ]


def equipment_notes(row) -> list[str]:
    """The full-width lines under one item: a [REVIEW] line per fact it owes and lacks, then its notes."""
    from certifications.services.production_equipment import missing_facts

    item = row["item"]
    lines = [f"[REVIEW] {fact[0].upper()}{fact[1:]} is not stated." for fact in missing_facts(item)]
    if item.notes.strip():
        lines.append(f"Notes: {item.notes.strip()}")
    return lines


def _equipment_flowables(osp, styles) -> list:
    """The equipment that contacts organic crops: CCOF G6.0 C2 and G6.1 B1, OTCO C9 9.1-1, WSDA I 1-2b.

    Until 2026-11 cleaning facts lived only on Equipment-Maintenance events, so no plan printed the
    table every agent asks for.
    """
    from certifications.services.production_equipment import equipment_rows, shared_answer_conflict

    rows = equipment_rows(osp.establishment) if osp.establishment_id else []
    if not rows:
        return [
            Paragraph(
                _escape(
                    "[REVIEW] The plan says farm equipment contacts organic crops, and no equipment is recorded "
                    "in the equipment register."
                ),
                styles["body"],
            ),
            Spacer(1, 6),
        ]
    out = [
        Paragraph("<b>Equipment that contacts organic crops</b>", _sticks_to_next(_style(styles, "body"))),
        _register_table(
            EQUIPMENT_COLUMNS,
            _EQUIPMENT_WIDTHS,
            [(equipment_cells(row), equipment_notes(row)) for row in rows],
            styles,
        ),
        Spacer(1, 4),
    ]
    conflict = shared_answer_conflict(osp, rows)
    if conflict:
        out.append(Paragraph(_escape(f"[REVIEW] {conflict}"), styles["meta"]))
    out.append(
        Paragraph(
            "Each item is as the operation entered it in its equipment register. Cleaning activities are "
            "logged separately in Trazo.",
            styles["meta"],
        )
    )
    out.append(Spacer(1, 6))
    return out


#: OTCO O1 §B's columns for each person: name and title, phone, email, and (for the responsibly connected) the
#: connection. The roles column says which of O1's lists the person belongs to.
OPERATION_CONTACT_COLUMNS = ("Name and title", "Roles", "Phone", "Email", "Connection")


def operation_contact_lines(establishment) -> tuple[list, list]:
    """(table rows, lines under the table) for the operation's named people. Every blank cell is "Not stated";
    a missing primary contact, legally responsible contact or responsibly connected person is a review line."""
    contacts = list(establishment.operation_contacts.all().order_by("pk"))
    rows = []
    for c in contacts:
        connection = ""
        if c.is_responsibly_connected:
            connection = (
                (c.connection_other or "Other, not described")
                if c.connection == "other"
                else (c.get_connection_display() if c.connection else "Not stated")
            )
        rows.append(
            (
                [
                    [c.name + (f", {c.title}" if c.title else "")],
                    ["; ".join(c.role_labels()) or "No role marked"],
                    [c.phone or "Not stated"],
                    [c.email or "Not stated"],
                    [connection or "—"],
                ],
                [],
            )
        )
    lines = []
    if not contacts:
        lines.append("[REVIEW] No person is named to the certifying agent.")
        return rows, lines
    for flag, words in (
        ("is_legally_responsible", "legally responsible contact"),
        ("is_primary_contact", "primary contact"),
        ("is_responsibly_connected", "responsibly connected person (7 CFR 205.2)"),
    ):
        if not any(getattr(c, flag) for c in contacts):
            lines.append(f"[REVIEW] No {words} is named.")
    return rows, lines


def _operation_contact_flowables(osp, styles) -> list:
    rows, lines = operation_contact_lines(osp.establishment)
    out = []
    if rows:
        out.append(_register_table(OPERATION_CONTACT_COLUMNS, (1.6, 1.6, 1.0, 1.6, 1.0), rows, styles))
        out.append(Spacer(1, 4))
    for line in lines:
        out.append(Paragraph(_escape(line), _style(styles, "meta")))
    return out


def _brand_owner_flowables(osp, styles) -> list:
    """The companies whose brands the operation packs into: CCOF G7.0 C, OTCO C8 8.3, WSDA N 6-7.

    Until 2026-11 the plan said only that some crop is "sold under the buyer's own label", with no
    owner, status or copy behind it.
    """
    from certifications.services.brand_owners import agreement_name, brand_owner_rows

    rows = brand_owner_rows(osp.establishment) if osp.establishment_id else []
    if not rows:
        return [
            Paragraph(
                _escape(
                    "[REVIEW] The plan says some crop leaves under a buyer's label, and no brand owner is recorded "
                    "in the brand-owner register."
                ),
                styles["body"],
            ),
            Spacer(1, 6),
        ]
    agreement = agreement_name(osp)
    out = [
        Paragraph("<b>Brand owners this operation packs for</b>", _sticks_to_next(_style(styles, "body"))),
        _register_table(
            ("Brand owner", "As recorded in the brand-owner register"),
            _TWO_COLUMN_WIDTHS,
            [([[row["owner"].name], brand_owner_lines(row, agreement)], []) for row in rows],
            styles,
        ),
        Spacer(1, 4),
    ]
    out.append(
        Paragraph(
            "Certificates and agreements are the copies this operation filed in Trazo. They are the operation's "
            "records, not a check against the USDA Organic Integrity Database.",
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
    # The operation's own facilities print on their own table (`_own_facility_flowables`): they have no
    # certificate of their own, and the [REVIEW] below would call the farm's own cooler uncertified.
    facilities = (
        list(osp.establishment.post_harvest_facilities.exclude(operated_by="this_operation"))
        if osp.establishment_id
        else []
    )
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
    from certifications.services.facility_crops import crops_by_facility, crops_sentence

    crops = crops_by_facility(osp.establishment)
    out = [Paragraph("<b>Off-farm handlers and storage facilities</b>", _sticks_to_next(_style(styles, "body")))]
    for facility in facilities:
        where = ", ".join(x for x in (facility.address, facility.city, facility.state, facility.postal_code) if x)
        role = facility.get_role_display() if facility.role else ""
        head = f"{facility.name} — {facility.get_facility_type_display()}" + (f" ({role})" if role else "")
        out.append(Paragraph(f"• {_escape(head)}", _sticks_to_next(_style(styles, "body"))))
        if where:
            out.append(Paragraph(_escape(where), styles["meta"]))

        current = facility.cert_is_current
        if facility.certificate_on_record:
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
        # CCOF G6.1 C2 and G6.2 A2, OTCO C7 7.7-2 and 7.10-2: which crops go to this facility. Read from
        # the production records linked to it; what those cannot say (detail, packaging form) is the
        # operator's own line below (2026.11.09).
        recorded = crops.get(facility.pk) or []
        detail = [x.strip() for x in (facility.products_detail or "").splitlines() if x.strip()]
        if recorded:
            out.append(
                Paragraph(
                    _escape(f"Crops on the production records linked to this facility: {crops_sentence(recorded)}."),
                    styles["meta"],
                )
            )
        if detail:
            out.append(
                Paragraph(
                    _escape(
                        "Products, as the operation describes them: " + "; ".join(d.rstrip(".") for d in detail) + "."
                    ),
                    styles["meta"],
                )
            )
        products = _facility_product_table(facility, styles)
        out.extend(products)
        if not recorded and not detail and not products:
            out.append(
                Paragraph(
                    _escape(
                        "[REVIEW] No production record is linked to this facility and no products are described, "
                        "so the plan does not show which crops it handles or stores."
                    ),
                    styles["meta"],
                )
            )
        # What happens there, in the terms of WSDA's Additional Facilities and Third-Parties form
        # (AGR 2519), as the operation picked them; and, for a facility with no certificate on file, how
        # the operation says it is exempt (§ 205.101). Both the operation's statements.
        from certifications.facility_activities import ACTIVITY_KEYS, ACTIVITY_LABELS

        activities = [ACTIVITY_LABELS[k] for k in ACTIVITY_KEYS if k in (facility.activities or [])]
        if activities:
            out.append(
                Paragraph(_escape("Activities at this facility: " + "; ".join(activities) + "."), styles["meta"])
            )
        exemption = (facility.exemption_basis or "").strip()
        if exemption and not facility.certificate_on_record:
            out.append(
                Paragraph(
                    _escape(f"How the operation states it is exempt from certification (§ 205.101): {exemption}"),
                    styles["meta"],
                )
            )
    out.append(Spacer(1, 6))
    return out


def _own_facility_flowables(osp, styles) -> list:
    """The operation's own handling and storage facilities (CCOF G6.4 A1; OTCO C7 7.1, 7.2-1, 7.7-2).

    Each prints its name, type, role and full address, that it is covered by the operation's own certificate
    (OTCO's OWN class), its layout (named by its packet path when the packet carries it), and the crops on the
    production records linked to it. Nothing about a certificate of its own: it has none.
    """
    from certifications.services.facility_crops import crops_by_facility, crops_sentence
    from certifications.services.own_facilities import own_facilities, own_facility_line

    facilities = list(own_facilities(osp.establishment)) if osp.establishment_id else []
    if not facilities:
        return [
            Paragraph("No facility operated by this operation is recorded.", styles["body"]),
            Spacer(1, 6),
        ]
    from certifications.services.packet_attachments import current_manifest, facility_layout_source, state_words

    crops = crops_by_facility(osp.establishment)
    manifest = current_manifest()
    out = [Paragraph("<b>Facilities operated by this operation</b>", _sticks_to_next(_style(styles, "body")))]
    for facility in facilities:
        out.append(Paragraph(_escape(f"• {own_facility_line(facility)}"), styles["body"]))
        if facility.layout_document:
            entries = manifest.for_source(facility_layout_source(facility)) if manifest else []
            if entries:
                out.append(Paragraph(_escape(state_words(entries[0])), styles["meta"]))
        recorded = crops.get(facility.pk) or []
        detail = [x.strip() for x in (facility.products_detail or "").splitlines() if x.strip()]
        if recorded:
            out.append(
                Paragraph(
                    _escape(f"Crops on the production records linked to this facility: {crops_sentence(recorded)}."),
                    styles["meta"],
                )
            )
        if detail:
            out.append(
                Paragraph(
                    _escape(
                        "Products, as the operation describes them: " + "; ".join(d.rstrip(".") for d in detail) + "."
                    ),
                    styles["meta"],
                )
            )
        out.extend(_facility_product_table(facility, styles))
    out.append(Spacer(1, 6))
    return out


def _facility_product_table(facility, styles) -> list:
    """The facility's product rows (CCOF G6.1 C2, OTCO C7 7.10-2), one table row each, in the operator's words.

    Under a multi-ingredient product, where its ingredient statement is in the packet, or a [REVIEW] that none
    is on file. Nothing when the facility has no product rows: the lines above say what the records show.
    """
    from certifications.services import facility_products as fp
    from certifications.services.packet_attachments import current_manifest

    products = fp.products_of(facility)
    if not products:
        return []
    manifest = current_manifest()
    items = [(fp.product_cells(p), fp.product_notes(p, manifest)) for p in products]
    return [_register_table(fp.HEADER, fp.WIDTHS, items, styles)]


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
        c11_table_asked,
        labels_asked_for,
        none_used_contradictions,
        plan_materials,
        post_harvest_listing_review,
    )

    answers = _module_entry(osp, "materials_application").get("answers") or {}
    rows = plan_materials(osp)
    labels_asked = labels_asked_for(osp)
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
    if c11_table_asked(osp):
        out += _c11_table_flowables(osp, rows, styles, labels_asked)
    else:
        out += _grouped_materials_flowables(osp, rows, styles, labels_asked)

    # A logged wash-water sanitizer the plan lists only under § 205.601, or under nothing.
    for line in post_harvest_listing_review(osp):
        out.append(Paragraph(_escape(line), styles["meta"]))
    return out + _materials_sections_after_list(osp, rows, answers, styles)


def _grouped_materials_flowables(osp, rows, styles, labels_asked) -> list:
    """The list grouped by where each material is listed, one line per material."""
    out = []
    out.append(
        Paragraph(
            "Each row: product — manufacturer — listing — reason for use — use (in use, intended for use "
            "or no longer used) — the agent's review, where the operator recorded one; a National List "
            "substance with no product row also says so. A cell the plan does not hold is stated as not "
            "stated, never left blank. A line under a row gives WSDA's annotation for a WSDA-listed product, "
            "and its label or container photo, where one is on file or the agent asks for one.",
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
            for line in _material_wsda_annotation_lines(osp, row) + _material_label_lines(row, labels_asked):
                out.append(Paragraph(_escape(line), styles["meta_indent"]))
    return out


def _c11_table_flowables(osp, rows, styles, labels_asked) -> list:
    """The list in OTCO C11's own four columns, for a plan filed with OTCO.

    C11 offers "I have attached my own list with this information", and the information is its table:
    full product name with formulation, full manufacturer name, third party review agency (OMRI, WSDA
    or OTHER) and intended use. The grouped list printed the first two and the listing, and no
    intended use, so the attached list was missing columns the form names (2026-11-16). Every fact
    the grouped line carried is still here: the listing in the review cell, reason and use in the
    intended use cell, and the agent's review, [REVIEW] lines and label line under the row.
    """
    from certifications.services.plan_materials import (
        c11_product_cell,
        c11_review_cell,
        c11_use_cell,
        materials_changes_since_filing,
    )

    changes = materials_changes_since_filing(osp)
    added_on = {" ".join(name.split()).lower(): day for name, day in (changes or {}).get("added", [])}
    out = [
        Paragraph(
            "In the columns of OTCO's C11 Crop Materials List. A cell the plan does not hold is stated as not "
            "stated. The review agency is the listing the operator attached (OMRI or WSDA), or the agency the "
            "operator names; Trazo names no reviewer. Under a row: the agent's review as the operator recorded "
            "it, any [REVIEW] line, WSDA's annotation for a WSDA-listed product, and its label or container photo.",
            styles["meta"],
        )
    ]
    items = []
    for row in rows:
        notes = list(row.review_notes())
        if row.agent_review:
            notes.append(row.agent_review)
        notes += _material_wsda_annotation_lines(osp, row)
        notes += _material_label_lines(row, labels_asked)
        day = added_on.get(" ".join(row.name.split()).lower())
        if day:
            notes.append(f"Added to the list on {day}, after the plan was filed on {changes['since']}.")
        items.append(
            (
                [
                    c11_product_cell(row),
                    [row.manufacturer or "not stated"],
                    c11_review_cell(row),
                    c11_use_cell(row),
                ],
                notes,
            )
        )
    out.append(
        _register_table(
            ["Full product name", "Manufacturer", "Third party review agency", "Intended use"],
            [2.0, 1.5, 1.7, 1.8],
            items,
            styles,
        )
    )
    if changes is not None:
        out.append(Spacer(1, 4))
        if changes["added"] or changes["removed"]:
            if changes["added"]:
                listed = "; ".join(f"{name} ({day})" for name, day in changes["added"])
                out.append(
                    Paragraph(
                        _escape(
                            f"Added to the Materials List since the plan was filed on {changes['since']}: {listed}."
                        ),
                        styles["meta"],
                    )
                )
            if changes["removed"]:
                listed = "; ".join(f"{name} ({day})" for name, day in changes["removed"])
                out.append(
                    Paragraph(
                        _escape(
                            f"Taken off the Materials List since the plan was filed on {changes['since']}: {listed}."
                        ),
                        styles["meta"],
                    )
                )
        else:
            out.append(
                Paragraph(
                    _escape(
                        f"No material was added to or taken off the list since the plan was filed on {changes['since']}."
                    ),
                    styles["meta"],
                )
            )
    return out


def _materials_sections_after_list(osp, rows, answers, styles) -> list:
    """The per-category sections, facility pest control, and the checks that follow the list."""
    from certifications.services.plan_materials import none_used_contradictions

    out = []
    # CCOF Materials Application §C, "Crop Management Tools and Production Aids": seed treatments, growing
    # media and adjuvants, each with product, manufacturer and reason for use. Printed again under §C's own
    # heading from the rows the operator filed under that category, as §D below. Only when rows exist.
    production_aids = [r for r in rows if r.category == "production_aid"]
    if production_aids:
        out.append(Spacer(1, 4))
        out.append(
            Paragraph(
                "<b>Crop production aids</b>: seed treatments, growing media, adjuvants",
                styles["body"],
            )
        )
        for row in production_aids:
            out.append(Paragraph(f"• {_escape(row.display(stated_absences=True))}", styles["body"]))

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

    out += _facility_pest_flowables(osp, styles)

    for line in none_used_contradictions(osp, answers):
        out.append(Paragraph(_escape(line), styles["meta"]))

    # State the disagreement instead of leaving the reader to find it. The packet used to print
    # this list beside an event-derived workbook that held different products, under five
    # attestations that everything in use was "entered in this list".
    out += _unmatched_logged_flowables(osp, styles)
    out += _withdrawn_by_operator_flowables(osp, styles)
    out.append(Spacer(1, 6))
    return out


def _facility_pest_flowables(osp, styles) -> list:
    """CCOF Materials Application §F (by National List type) and §G (materials outside those types), from the
    rows filed under facility pest control. Only when there are such rows: the G9.0 answer is the N/A, and its
    disagreement with the list is stated on G9.0 (`facility_pest.tier_review_lines`)."""
    from reportlab.platypus import Table, TableStyle

    from certifications.services.facility_pest import entry_review_lines, facility_entries, section_f, section_g

    entries = facility_entries(osp)
    if not entries:
        return []
    out = [
        Spacer(1, 4),
        Paragraph(
            "<b>Pest control in handling and storage facilities, by National List type</b> (§ 205.271(c))",
            _sticks_to_next(styles["body"]),
        ),
    ]
    head = ["National List type", "Used", "Products", "Where used", "Fumigation or fogging"]
    data = [[Paragraph(f"<b>{h}</b>", styles["meta"]) for h in head]]
    for row in section_f(entries):
        cells = [
            row.label,
            "Yes" if row.used else "No",
            "; ".join(row.products) if row.used else "",
            ("; ".join(row.where_used) or "not stated") if row.used else "",
            row.fumigation if row.used else "",
        ]
        data.append([Paragraph(_escape(c), styles["meta"]) for c in cells])
    table = Table(data, colWidths=[1.6 * inch, 0.5 * inch, 1.8 * inch, 1.8 * inch, 1.0 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2EFDA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    out.append(table)
    others = section_g(entries)
    out.append(Spacer(1, 4))
    out.append(
        Paragraph(
            "<b>Pest control materials that are not a National List type</b> (§ 205.271(d))",
            _sticks_to_next(styles["body"]),
        )
    )
    if not others:
        out.append(Paragraph("None is filed.", styles["meta"]))
    for e in others:
        fum = {True: "applied by fumigation or fogging", False: "not applied by fumigation or fogging"}.get(
            e.applied_by_fumigation, "fumigation or fogging not stated"
        )
        agreement = e.agent_review_statement or "no agreement with the certifying agent recorded"
        bits = [
            e.product_name,
            f"used in {e.where_used}" if (e.where_used or "").strip() else "where used not stated",
            fum,
            agreement,
        ]
        out.append(Paragraph(_escape("• " + "; ".join(bits)), styles["body"]))
    for line in entry_review_lines(entries):
        out.append(Paragraph(_escape(line), styles["meta"]))
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
#: The signed statement a container parcel files (CCOF ORGB49 §G "For container systems"), uploaded against the
#: parcel and shipped under parcels/container-statements/.
CONTAINER_STATEMENT_SECTION = "parcel_application_container_statement"


def container_statement_documents(parcel):
    """Signed container statements for one parcel, newest first."""
    try:
        return list(parcel.documents.filter(linked_section=CONTAINER_STATEMENT_SECTION).order_by("-created_at"))
    except Exception:  # noqa: BLE001 — a document lookup must never take the packet down
        logger.exception("Could not load container statements for parcel %s", getattr(parcel, "pk", None))
        return []


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


def _empty_review_window_sentence(review) -> str:
    """The plan review's window has no days in it: the newest answer is on or after the date the
    review runs to. Each date is printed as what it is (review of back #284: the first version
    printed the review's end date as the newest answer's)."""
    newest, end = str(review.answers_as_of)[:10], str(review.reference_date)[:10]
    if newest == end:
        return f"The plan's newest answer is dated {end}, the date this review runs to, so there is no later period to check."
    return (
        f"The plan's newest answer ({newest}) is later than the date this review runs to ({end}), so there is no "
        "period after it to check."
    )


def _entries_phrase(entries, singular: str, plural: str) -> str:
    """'3 addition entries', or '1 deletion entry, stating none' when every entry says "None"."""
    from history.services.audit_export_service import _fmt_change_entries

    entries = list(entries or [])
    phrase = _count_phrase(len(entries), singular, plural)
    texts = [(_fmt_change_entries([e]) or "").strip().lower() for e in entries]
    if texts and all(t.startswith("none") for t in texts):
        phrase += ", stating none"
    return phrase


def _another_agent_sentence(other, plan_agent_name: str) -> str:
    """What the cover and 02s say when the certificate on file is another agent's (2026-11-04).

    Only a known, different agent is stated as different. A name Trazo cannot match may be the plan's
    agent spelled another way, so it is set beside the plan's agent without a verdict (review of #284).
    """
    certificate = other.certificate
    then = (
        f"An operation changing certifying agent applies to the new agent; the renewal forms named in this "
        f"packet are for an operation {plan_agent_name} already certifies."
    )
    if other.confirmed:
        return (
            f"This certificate was issued by {certificate.agent}. The plan names {plan_agent_name} as its "
            f"certifying agent, which did not issue it. {then}"
        )
    return (
        f"This certificate names {certificate.agent} as its certifying agent and the plan names "
        f"{plan_agent_name}; Trazo does not recognise the first name, so it cannot say whether they are the "
        f"same agent. If they are not: {then[0].lower()}{then[1:]}"
    )


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

    elif embed == "location_coordinates":
        # CCOF ORGB49 A5, WSDA AGR 2264 ref 2, OTCO C2 2.1: coordinates in the location section, from
        # the same computation as the map caption. A parcel with no boundary says so rather than
        # printing nothing (the caption was the only place a coordinate reached the page).
        from certifications.services.parcel_map import parcel_boundary_centre

        centre = parcel_boundary_centre(parcel)
        out.append(
            Paragraph(
                _escape(
                    f"Boundary centre: {centre[0]:.6f}, {centre[1]:.6f} (computed from the boundary drawn on the "
                    "parcel map)."
                    if centre is not None
                    else "No boundary is drawn on the parcel map, so no coordinates are computed for this parcel."
                ),
                styles["body"],
            )
        )

    elif embed == "crop_table":
        # CCOF ORGB49 A8, WSDA AGR 2264 ref 8, OTCO C2 2.1 10): the crops the operator listed, with acres,
        # then the area on file and where the figures or the open seasons disagree with the list.
        # An orchard parcel's table adds block, rootstock, year planted and bearing status (planned_crop_table).
        from certifications.services.parcel_application_lines import planned_crop_lines, planned_crop_table
        from product.services.parcel_application_status import parcel_application_values

        header, widths, rows = planned_crop_table(parcel)
        if rows:
            out.append(_register_table(header, widths, rows, styles))
            out.append(Spacer(1, 4))
        for line in planned_crop_lines(parcel, parcel_application_values(parcel)):
            out.append(Paragraph(_escape(line), styles["meta" if line.startswith("[REVIEW]") else "body"]))

    elif embed == "container_statement":
        # CCOF ORGB49 §G: the signed statement itself. Named by its packet path inside a packet build; outside one
        # nothing ships, so the line says whether one is on file.
        from certifications.services.certified_parcel_branch import ATTACHED as PACKET_ATTACHED
        from certifications.services.certified_parcel_branch import _file_state
        from certifications.services.packet_attachments import current_manifest

        docs = container_statement_documents(parcel)
        if not docs:
            text = "[REVIEW] No signed container statement is on file for this parcel."
        elif current_manifest() is None:
            text = f"Signed container statement on file: {docs[0].title}."
        else:
            # The manifest decides: a file it could not read or held outside the budget is not "attached"
            # (review of back PR 402; the map embed's own T19 rule).
            state, path, detail = _file_state(docs[0], "container-statements")
            text = (
                f"Signed container statement attached: {path}."
                if state == PACKET_ATTACHED
                else f"[REVIEW] The signed container statement is uploaded to Trazo but not in this packet ({detail})."
            )
        out.append(Paragraph(_escape(text), styles["meta" if text.startswith("[REVIEW]") else "body"]))

    elif embed == "operation_export_answer":
        from certifications.services.parcel_application_lines import operation_export_lines

        for line in operation_export_lines(osp):
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
            elif row.get("adjacent_is_organic") is False:
                # CCOF ORGB49 D1 asks "Organic? (Y/N)" per border. A "no" the operator gave printed
                # nothing until 2026-11-06, the same on paper as a border nobody answered.
                bits.append("adjoining land is not certified organic")
            if row.get("crop_grown_in_buffer"):
                # State the crop, NOT its organic status. "never sold as organic" had the packet
                # asserting the exact fact § 205.202(c) asks the operator to PROVE, on the strength
                # of a free-text parcel field. What became of the crop is evidenced by the
                # buffer-use disposition records, not by this line.
                bits.append(f"crop grown in buffer: {row['crop_grown_in_buffer']}")
            elif row.get("buffer_crop_grown") is True:
                bits.append("a crop is grown in the buffer (crop not named)")
            elif row.get("buffer_crop_grown") is False:
                bits.append("no crop grown in the buffer")
            if row.get("prohibited_use_distance_ft") is not None:
                distance = row["prohibited_use_distance_ft"]
                distance = int(distance) if float(distance).is_integer() else distance
                bits.append(f"{distance} ft from prohibited-material applications")
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
        from product.services.land_history import (
            format_acres,
            land_history_planting,
            land_history_rows,
            land_history_span,
        )

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
            bits = [str(row.year)]
            # CCOF ORGB49 F7 asks each use with a from-to month range; OTCO C2 2.4 lets a history start mid-year.
            span = land_history_span(row)
            if span:
                bits.append(span)
            bits.append(crop)
            if row.production_method_display:
                bits.append(row.production_method_display.lower())
            if row.acres is not None:
                bits.append(f"{format_acres(row.acres)} acres")
            if row.cover_crop:
                bits.append(f"cover crop: {row.cover_crop}")
            planting = land_history_planting(row)
            if planting:
                bits.append(planting)
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
                            r.signed.isoformat()
                            if r.signed
                            else ("unsigned" if r.role != CURRENT_MANAGER or r.affidavit is not None else "—")
                        ),
                        meta,
                    ),
                    Paragraph(
                        _escape(
                            "attached"
                            if r.attachment
                            else ("not attached" if r.role != CURRENT_MANAGER or r.affidavit is not None else "—")
                        ),
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
        # OTCO C2 2.5 asks the current manager to sign as well; the operation's own affidavit, once signed and
        # attached, is that signature. Its absence is stated, never implied by a dash.
        if current.affidavit is None:
            out.append(
                Paragraph(
                    _escape(f"{current.name} has no signed affidavit of its own for its period on file."),
                    meta,
                )
            )
        for r in [current] + prior:
            bits = []
            if r.attachment:
                bits.append("signed affidavit attached at " + r.attachment)
            if r.legal_description:
                bits.append("land as described by signer: " + r.legal_description)
            if r.landowner:
                bits.append("landowner: " + r.landowner)
            if bits:
                out.append(Paragraph(_escape(f"{r.name}: " + "; ".join(bits)), meta))
            # What the signer stated beside the table (CCOF Affidavit B, C; WSDA AGR 2262 refs 1, 3, 5a, 5b, 6)
            # and their own materials table (CCOF Affidavit D; WSDA AGR 2262 refs 7, 8). Printed here because
            # the parcel page is where a reviewer reads the land history; it lived in the audit dossier only.
            if r.affidavit is not None:
                from certifications.services.parcel_land_history import (
                    AFFIDAVIT_ROW_COLUMNS,
                    affidavit_row_cells,
                    affidavit_signer_lines,
                )

                lines = affidavit_signer_lines(r.affidavit)
                cells = affidavit_row_cells(r.affidavit)
                if lines or cells:
                    out.append(Paragraph(_escape(f"Stated by {r.name}:"), _sticks_to_next(meta)))
                for line in lines:
                    out.append(Paragraph(_escape(f"• {line}"), meta))
                if cells:
                    out.append(
                        _register_table(
                            AFFIDAVIT_ROW_COLUMNS,
                            (0.45, 0.85, 0.85, 0.5, 1.2, 1.0, 0.85, 0.85),
                            [([[c] for c in row], []) for row in cells],
                            styles,
                        )
                    )
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
                "A signed affidavit, a prior manager's or the operation's own, where one is attached, is in "
                "the packet's parcels/affidavits/ folder. Dates are as each signer stated them.",
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
            out.append(
                Paragraph(
                    "This is the operation's certificate. The parcels it covers are listed on the certificate "
                    "itself.",
                    _style(styles, "meta"),
                )
            )
        else:
            from certifications.services.operation_certificate import (
                never_certified,
                recorded_without_number,
                unnumbered_from_another_agent,
            )

            unnumbered = recorded_without_number(parcel.establishment_id)
            if unnumbered is not None:
                # A certificate recorded without its number is not "no certificate" (first-run audit, 2026-11-21).
                held = f"from {unnumbered} " if unnumbered else ""
                said = (
                    f"The farm profile records this operation's organic certificate {held}without its number, so "
                    "no certificate number is printed here. The parcel is stated above as currently certified; the "
                    "certifying agent's own record governs."
                )
                plan_agent = unnumbered_from_another_agent(osp, unnumbered) if osp is not None else ""
                if plan_agent:
                    said += f" [REVIEW] That certificate is from {unnumbered}; this plan names {plan_agent}."
            else:
                said = (
                    "No certificate is on file for this operation in Trazo. The parcel is stated above as "
                    "currently certified; the certifying agent's own record governs."
                )
                # Walkthrough 2026-11-20, W3: this sentence sat on a parcel stated "currently certified" while
                # the cover, reading `never_certified`, called the plan a first application, and no review note
                # joined the two, so the cover's list of notes was silent about it. When Trazo holds nothing
                # that says the operation was ever certified, the gap is a note with its remedy. Otherwise (a
                # lapsed certification row, or an approved plan without a certificate number) the plain
                # sentence stays: the cover reads that operation as renewing too.
                if parcel.establishment_id and never_certified(parcel.establishment_id):
                    said = (
                        "No certificate is on file for this operation in Trazo. [REVIEW] The parcel is stated above "
                        "as currently certified, but Trazo prepares this plan as a first application. Add the "
                        "certificate to the farm profile, or correct the answer above. The certifying agent's own "
                        "record governs."
                    )
            out.append(Paragraph(_escape(said), styles["body"]))

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
    # The fact is "no signed copy attached" (`row_without_signed_document`): the row can carry the
    # signer's own signing date, and "not signed" beside it contradicted the table (re-grade 2026-11-19).
    "affidavit_document": "landowner affidavit recorded; no signed copy attached",
    "land_history_window": "part of the 36-month window is not accounted for by a declaration or affidavit",
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
    "livestock",
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


#: Embeds printed under their question's label, so the question index can point at them. The older parcel
#: embeds print their own headings and keep them.
_LABELLED_EMBEDS = {
    "location_coordinates",
    "operation_export_answer",
    "crop_table",
    "container_statement",
    "operation_contacts",
    "sourcing_scenarios",
}


#: Optional "kept elsewhere, say where" questions that stand in for a file. The certified-parcel card
#: already prints each file's state ("none attached or referenced"), so listing the blank reference
#: as an open question says the same thing twice.
_STANDS_IN_FOR_A_FILE = {
    "parcel_application.certificate_reference",
    "parcel_application.continuity_reference",
}

#: Upload requirements the packet answers with a document it generates, so an empty upload is not an
#: open question. The question's own coaching says the exhibit is already in the packet.
# A module whose "Not applicable" attests a state a reviewer must still look at. G7.0's reads "sold unlabeled
# in bulk, and its organic identity is carried only on sales documents ... never on ... a container marking",
# which § 205.307(a)(1) does not allow for nonretail containers; the matching `product_leaves_as` option has
# printed this review since 2026-10-26, the attestation printed nothing (CCOF G7.0 A1). Rewording the label
# would change what plans already attested say, so the line is added beside it instead.
_NA_REVIEW = {
    "g7_0_labeling": (
        "Product leaves in nonretail containers that carry no organic identification. Nonretail containers must "
        "identify the product as organic (§ 205.307(a)(1)), unless they hold retail-packaged product whose "
        "organic label is visible (§ 205.307(c))."
    ),
}

_GENERATED_FOR_UPLOAD = {"g8_0_record_keeping.audit_trail_exhibit": "05-audit-trail-exhibit.pdf"}


def _unanswered_gate(module, key, answers, asked, seen=None):
    """The label of the unanswered question that could still show the hidden question `key`, or None when
    an answered condition rules it out. Follows hidden gates down to an asked one."""
    seen = set() if seen is None else seen
    if key in seen:
        return None
    seen.add(key)
    page_of = {q.key: p for p in module.pages for q in p.questions}
    questions = {q.key: q for p in module.pages for q in p.questions}
    question, page = questions.get(key), page_of.get(key)
    if question is None:
        return None

    def label(k):
        return _en(questions[k].label).rstrip("?.: ")

    pending = None
    for cond in tuple(question.visible_when or ()) + tuple(getattr(page, "visible_when", ()) or ()):
        if cond.question in asked:
            if answer_value(answers, cond.question) in (None, "", []):
                pending = pending or label(cond.question)
            elif not evaluate(cond, answers):
                return None
        else:
            below = _unanswered_gate(module, cond.question, answers, asked, seen)
            if below is None:
                return None
            pending = pending or below
    any_conds = tuple(getattr(page, "visible_when_any", ()) or ())
    if any_conds and not any(c.question in asked and evaluate(c, answers) for c in any_conds):
        either = None
        for cond in any_conds:
            if cond.question in asked:
                if answer_value(answers, cond.question) in (None, "", []):
                    either = either or label(cond.question)
            else:
                either = either or _unanswered_gate(module, cond.question, answers, asked, seen)
        if either is None:
            return None
        pending = pending or either
    return pending


def _page_does_not_apply(module, page, answers) -> str:
    """Why a page of the module is not printed, worded from the conditions that hide it: every one of
    `visible_when`, and one of `visible_when_any` (the page's OR gate, 2026.11.25; review of back #352,
    which first left this reader on the AND list alone and printed a gated page as not applying)."""
    conds = tuple(getattr(page, "visible_when", ()) or ())
    any_conds = tuple(getattr(page, "visible_when_any", ()) or ())
    if not conds and not any_conds:
        return "Does not apply to this operation."
    questions = {q.key: q for p in module.pages for q in p.questions}

    def phrase(cond):
        """("open", label) when the deciding question is unanswered, ("phrase", words), or None."""
        trigger = questions.get(cond.question)
        if trigger is None:
            return None
        label = _en(trigger.label).rstrip("?.: ")
        if answer_value(answers, cond.question) in (None, "", []):
            # Hidden because the deciding question is open, not because the answer rules it out.
            return "open", label
        names = {o.value: _en(o.label) for o in trigger.options}
        values = cond.value if isinstance(cond.value, (list, tuple)) else [cond.value]
        shown = " or ".join(names.get(v, str(v)) for v in values if v is not None)
        words = {
            "truthy": f"the answer to “{label}” is Yes",
            "falsy": f"the answer to “{label}” is No",
            "includes": f"the answer to “{label}” includes {shown}",
            "includes_any": f"the answer to “{label}” includes {shown}",
            "eq": f"the answer to “{label}” is {shown}",
            "one_of": f"the answer to “{label}” is {shown}",
            "ne": f"the answer to “{label}” is not {shown}",
            "not_includes": f"the answer to “{label}” does not include {shown}",
        }.get(cond.op)
        return ("phrase", words) if words else None

    phrases = []
    for cond in conds:
        found = phrase(cond)
        if found and found[0] == "open":
            return f"Not shown until “{found[1]}” is answered."
        if found:
            phrases.append(found[1])
    if any_conds:
        # A member whose deciding question is itself hidden is not asked. If its own gate is answered against
        # it, it can never open the page and is skipped: without that, "never certified" left the Operation
        # profile's page C reading "Not shown until 'suspended' is answered" for a question that operation is
        # never asked (2026-11-09). If its gate is still unanswered it can, so the page waits on that gate
        # (review of back #363).
        asked = {q.key for _p, q in visible_questions(module, answers)}
        either = []
        for cond in any_conds:
            if cond.question not in asked:
                gate = _unanswered_gate(module, cond.question, answers, asked)
                if gate:
                    return f"Not shown until “{gate}” is answered."
                continue
            found = phrase(cond)
            if found and found[0] == "open":
                # One member unanswered decides nothing yet: it could still open the page.
                return f"Not shown until “{found[1]}” is answered."
            if found:
                either.append(found[1])
        if either:
            phrases.append(" or ".join(either))
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
    if module.key == "g2_0_fraud_prevention":
        # OTCO OFPP 1-3: why an OTCO plan answers the whole module, and the facts its gate turns on.
        from certifications.services.ofpp_scope import ofpp_scope_note

        note = ofpp_scope_note(osp)
        for i, line in enumerate(note):
            story.append(Paragraph(_escape(line), styles["meta"] if i else styles["body"]))
        if note:
            story.append(Spacer(1, 10))

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
        if module.key in _NA_REVIEW:
            story.append(Paragraph(_escape(f"[REVIEW] {_NA_REVIEW[module.key]}"), styles["meta"]))
        if module.key == "g3_1_container_greenhouse":
            # CCOF G3.1's "None of these" set against the plan and the records that say otherwise.
            from certifications.services.structure_production import na_contradictions

            for line in na_contradictions(osp):
                story.append(Paragraph(_escape(line), styles["meta"]))
        if module.key == "g4_1_compost_manure":
            # "None of these are used" (CCOF G4.1 A1) set against the soil records that name compost or manure.
            from certifications.services.compost_manure_review import none_used_lines

            for line in none_used_lines(osp, "not_applicable"):
                story.append(Paragraph(_escape(line), styles["meta"]))
        if module.key == "g6_2_storage":
            # "Product is never stored" set against G6.1 and the facilities on file (blind re-grade 2026-11-19).
            from certifications.services.plan_contradictions import storage_na_contradictions

            for line in storage_na_contradictions(osp):
                story.append(Paragraph(_escape(line), styles["meta"]))
    else:
        pairs = visible_questions(module, answers)
        # Where the "nothing answered" line goes, so it leads the questions it summarises instead of
        # following a list of them (review of back #249).
        body_start = len(story)
        answered_any = False
        evidence_bundles: dict = {}
        # Which stored Yes answers the records now refuse, computed once (`_answer_as_it_stands`).
        refused_cache: dict = {}
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
                elif question.embed == "on_farm_facilities":
                    rendered = _own_facility_flowables(osp, styles)
                elif question.embed == "seedling_suppliers":
                    rendered = _seedling_supplier_flowables(osp, styles)
                elif question.embed == "operation_contacts":
                    rendered = _operation_contact_flowables(osp, styles)
                elif question.embed == "brand_owners":
                    rendered = _brand_owner_flowables(osp, styles)
                elif question.embed == "sourced_products":
                    rendered = _sourced_product_flowables(osp, styles)
                elif question.embed == "equipment_inventory":
                    rendered = _equipment_flowables(osp, styles)
                elif question.embed == "facility_pest_pointer":
                    rendered = [Paragraph(_escape(line), styles["body"]) for line in _facility_pest_pointer(osp)]
                elif question.embed == "packaging_pointer":
                    rendered = [Paragraph(_escape(line), styles["body"]) for line in _packaging_pointer(osp)]
                elif question.embed == "sourcing_scenarios":
                    from certifications.services.sourcing_scenarios import sourcing_scenario_lines

                    lines, reviews = sourcing_scenario_lines(osp)
                    rendered = [Paragraph(_escape(line), styles["body"]) for line in lines]
                    rendered += [Paragraph(_escape(line), styles["meta"]) for line in reviews]
                else:
                    rendered = []
                if rendered:
                    open_page(page)
                    answered_any = True
                    if question.embed in _LABELLED_EMBEDS:
                        story.append(_question_label(module, page, question, styles))
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
                # A bound column is printed by its own section when blank (identity, tenure), except the
                # two parcel yes/no statements: nothing else names them, and since 2026-11-21 a new parcel
                # holds no answer to either instead of a default "No".
                if question.parcel_field and question.kind != "boolean":
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
            key_table = _lot_code_key_flowables(osp, module, question, value, styles)
            if key_table:
                story.extend(key_table)
            else:
                story.append(
                    Paragraph(
                        _escape(_answer_as_it_stands(module, question, value, answers, osp, refused_cache)),
                        styles["body"],
                    )
                )
            for line in _lot_key_and_trace_lines(osp, module, question, value, answers):
                story.append(Paragraph(_escape(line), styles["meta"]))
            if question.key == "materials_list_complete" and question.key in refused_cache.get("keys", {}):
                # The four category statements carry their own line (`_unlisted_category_lines`);
                # the whole-list one did not, and printed a qualified Yes with no reason beside it.
                from certifications.services.attestation_gates import unlisted_products

                unlisted = unlisted_products(question.key, osp)
                shown = ", ".join(unlisted[:12]) + (f", and {len(unlisted) - 12} more" if len(unlisted) > 12 else "")
                story.append(
                    Paragraph(
                        _escape(
                            f"The records name {len(unlisted)} product(s) that this plan's materials list does not "
                            f"hold by name, and that no current decision on the plan ties to a listed product: {shown}."
                        ),
                        styles["meta"],
                    )
                )
            # Declared on the options themselves: what the certifier should look at when this answer
            # is chosen, and whether an option that says a file is attached has one.
            for line in _option_review_lines(osp, module, question, value):
                story.append(Paragraph(_escape(line), styles["meta"]))
            for line in _treated_lumber_parcel_lines(osp, module, question, value):
                story.append(Paragraph(_escape(line), styles["meta"]))
            for line in _map_element_lines(osp, module, question, value, parcel):
                story.append(Paragraph(_escape(line), styles["meta"]))
            if parcel is not None:
                from certifications.services.parcel_application_lines import parcel_answer_lines

                for line in parcel_answer_lines(osp, question.key, value, answers, parcel):
                    story.append(Paragraph(_escape(line), styles["meta"]))
            if module.key == "g3_1_container_greenhouse":
                from certifications.services.structure_production import answer_contradictions

                for line in answer_contradictions(question.key, value, answers):
                    story.append(Paragraph(_escape(line), styles["meta"]))
            if module.key in ("g3_0_seeds", "g3_2_planting_stock"):
                from certifications.services.seed_stock_review import answer_lines

                for line in answer_lines(osp, module.key, question.key, value, evidence_bundles):
                    story.append(Paragraph(_escape(line), styles["meta"]))
            if module.key == "g4_1_compost_manure" and question.key == "materials_applied" and value == ["none"]:
                from certifications.services.compost_manure_review import none_used_lines

                for line in none_used_lines(osp, "none"):
                    story.append(Paragraph(_escape(line), styles["meta"]))
            if module.key == "g8_0_record_keeping":
                from certifications.services.international_trade_review import answer_lines as trade_lines

                for line in trade_lines(osp, question.key, value, evidence_bundles):
                    story.append(Paragraph(_escape(line), styles["meta"]))
            if module.key == "g6_4_handling" and question.key == "simple_handling_disqualifiers":
                for line in g6_4_all_organic_lines(osp):
                    story.append(Paragraph(_escape(line), styles["meta"]))
            if module.key == "certification_contract":
                # The history answers set against the certificate on file and the parcels (blind re-grade 2026-11-19).
                from certifications.services.plan_contradictions import history_answer_lines

                for line in history_answer_lines(osp, question.key, value):
                    story.append(Paragraph(_escape(line), styles["meta"]))
            if module.key == "g6_2_storage" and question.key == "storage_pest_control_materials_used":
                for line in _facility_pest_pointer(osp):
                    story.append(Paragraph(_escape(line), styles["meta"]))
            if module.key == "g9_0_facility_pest" and question.key == "material_tier":
                from certifications.services.facility_pest import facility_entries, tier_review_lines

                for line in tier_review_lines(value, facility_entries(osp)):
                    story.append(Paragraph(_escape(line), styles["meta"]))
            for line in _answer_evidence_lines(osp, question, value, evidence_bundles):
                story.append(Paragraph(_escape(line), styles["meta"]))
            for line in _unlisted_category_lines(osp, question, value, evidence_bundles):
                story.append(Paragraph(_escape(line), styles["meta"]))
            # The National List materials allowed only under a condition (WSDA AGR 2121 D4-D6a, H5;
            # OTCO C4 4.5-1): the rule's words, the plan's materials of the class, and a No the
            # records contradict.
            for line in restricted_material_lines(osp, module, question, value, answers, evidence_bundles):
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


def _agent_name(osp, *, starts_sentence: bool = False) -> str:
    from certifications.services.packet_coverage import packet_agent

    name = packet_agent(osp).name or "the certifying agent"
    return name[:1].upper() + name[1:] if starts_sentence else name


def _agent_file_sentence(filing, osp, *, then: str = "so this packet lists no changes against it.") -> str:
    """The year one statement: the agent holds a plan filed before Trazo, and Trazo has no copy.

    Overall review 2026-11 (OV-PK-C01/W03/O02): a first year in Trazo compared nothing against the
    plan the agent holds and never said so, so an empty change list read as "nothing changed". Printed
    only when the operation stated it (`prior_plan_basis`), never inferred for a filing signed before
    the question existed.
    """
    return (
        f"Plan v{filing.prior_osp.version_number} is the operation's first plan version in Trazo. "
        f"{_agent_name(osp, starts_sentence=True)} holds the plan the operation filed with it before Trazo, and Trazo has no copy "
        f"of that plan, {then}"
    )


def _stated_module_line(module) -> str:
    title = (module.title or {}).get("en", module.key) if isinstance(module.title, dict) else str(module.title)
    return f"{module.code} {title}".strip()


_NOT_IN_REGISTRY = "not a section of the plan in Trazo today"


def _stated_lines(filing, location=None) -> list[str]:
    """Each section `filing` states changed, one line each, in plan order; a stored key the module
    registry no longer knows last, as stored (`stated_keys_not_in_registry`). `location(key)` adds
    where the section's current answers are."""
    from certifications.services.plan_version_changes import stated_keys_not_in_registry, stated_modules

    lines = [
        f"{_stated_module_line(m)}: {location(m.key)}" if location else _stated_module_line(m)
        for m in stated_modules(filing)
    ]
    return lines + [f"{key} ({_NOT_IN_REGISTRY})" for key in stated_keys_not_in_registry(filing)]


def _stated_changes_lines(filing, osp, styles) -> list:
    """02: what the operation states changed against the plan on file with its agent, signed with the
    filing. Printed only when stated; "not stated" prints nothing, never "nothing changed"."""
    if not filing.states_agent_file_changes:
        return []
    agent = _agent_name(osp)
    story = [
        Spacer(1, 8),
        Paragraph(
            _escape(f"Changed since the plan on file with {agent} (the operation's statement)"), styles["header"]
        ),
    ]
    lines = _stated_lines(filing)
    if lines:
        story += [Paragraph(_escape(f"• {line}"), styles["body"]) for line in lines]
    else:
        story.append(
            Paragraph(
                _escape(f"Nothing in the plan on file with {agent} changed, as the operation states."), styles["body"]
            )
        )
    return story


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
    from certifications.services.operation_certificate import never_certified, recorded_without_number

    return {
        "filing": filing,
        "other_filing": other_filing,
        # A first-time applicant (§ 205.401): no certificate, approved plan or filed update on
        # record. The cover, 02 and 02s then stop demanding a § 205.406(a) update and stop
        # calling the packet a renewal. A filing on record always means False.
        "never_certified": filing is None and other_filing is None and never_certified(est.id),
        "certificate_number": certificate_number,
        "certifier_name": certifier_name,
        # A certificate recorded without its number (2026-11-21): its agent, or "" / None.
        "certificate_unnumbered_agent": recorded_without_number(est.id) if not certificate_number else None,
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


def _changed_only_cover_flowables(scope, styles) -> list:
    """The cover's statement that this packet carries only the changed module PDFs, and which not.

    Printed first, above the operation details: a reviewer must know before opening the ZIP that
    an absent module is a choice and not an omission. The wording says what the operation asked
    for and never that the certifying agent accepts it; that is the agent's decision.
    """
    if not scope.changed_only:
        return []
    old, new = f"v{scope.prior_version}", f"v{scope.new_version}"
    story = [
        Paragraph("Changed sections only", styles["header"]),
        Paragraph(
            _escape(
                f"This packet carries only the plan sections whose answers changed between plan {old} and plan "
                f"{new}, for a renewal form that asks the operation to list its updated plan sections and attach "
                "them. Whether the certifying agent accepts a packet without the unchanged sections is the "
                "agent's decision; the full packet, with every module, can be built from the same plan."
            ),
            styles["body"],
        ),
        Paragraph(
            "Always included, whatever changed: this cover, 01 the organic system plan, 02 the annual update, "
            "02s the renewal status, the year's annual-update revisions, 03 change notifications, 04 coverage "
            "and scope, 05 the audit trail exhibit, 06 the question index, every Parcel Application, the "
            "workbooks and every attached operator file.",
            styles["body"],
        ),
        Paragraph(
            _escape(f"Module PDFs included because their answers changed ({len(scope.included)}):"),
            styles["body"],
        ),
    ]
    if scope.included:
        story += [Paragraph(_escape(f"• {m.label} ({m.path})"), styles["meta"]) for m in scope.included]
    else:
        story.append(
            Paragraph(
                "• None. No module's answers changed; what changed is the operation's own § 205.201(a) "
                "narrative, in 01.",
                styles["meta"],
            )
        )
    if scope.narratives:
        story.append(
            Paragraph(
                _escape(
                    "§ 205.201(a) sections whose own narrative or confirmed record types changed, in 01: "
                    + "; ".join(scope.narratives)
                    + "."
                ),
                styles["body"],
            )
        )
    if scope.live:
        story.append(
            Paragraph(
                _escape(
                    f"Module PDFs included because they show the operation's current records, which are not "
                    f"compared between plan versions ({len(scope.live)}). Their stored answers are the same in "
                    f"plan {old} and plan {new}; the records they show may not be:"
                ),
                styles["body"],
            )
        )
        story += [Paragraph(_escape(f"• {m.label} ({m.path})"), styles["meta"]) for m in scope.live]
    story.append(
        Paragraph(
            _escape(
                f"Module PDFs left out because their answers are the same in plan {old} and plan {new} "
                f"({len(scope.omitted)}):"
            ),
            styles["body"],
        )
    )
    for m in scope.omitted:
        story.append(Paragraph(_escape(f"• {m.label} ({m.path})"), styles["meta"]))
    # Uploads are not compared and travel as in the full packet. The module PDF that names them is
    # not in this ZIP, so they are named here: no file ships that no document in the packet names.
    from certifications.services.packet_attachments import current_manifest
    from certifications.services.packet_scope import files_for_omitted

    carried = files_for_omitted(scope, current_manifest())
    if carried:
        story.append(
            Paragraph(
                "Files uploaded for a left-out module's questions are not compared between versions and are "
                "carried as in the full packet:",
                styles["body"],
            )
        )
        for m, paths in carried:
            story.append(Paragraph(_escape(f"• {m.label}: {', '.join(paths)}"), styles["meta"]))
    story += [
        Paragraph(
            "What the comparison does not see: land. Parcels are kept with the operation, not with a plan "
            "version, so new land and edits to an existing parcel (its crop history, buffers or map) are not "
            "compared. Every Parcel Application is included for that reason. The workbooks and operator files "
            "are read from the operation's records, not from a plan version, and are included too. The "
            "comparison reads stored answers; it does not review the changes.",
            styles["meta"],
        ),
        Spacer(1, 8),
    ]
    return story


CA_REGISTRATION_LABEL = "California organic registration (CDFA)"
CDPH_REGISTRATION_LABEL = "California organic registration (CDPH)"
_CA_REGISTRATION_LABELS = {"cdfa": CA_REGISTRATION_LABEL, "cdph": CDPH_REGISTRATION_LABEL}


def _state_registration_cover_lines(est, kv, styles) -> list:
    """CCOF Certification Contract E1 and E2, and OTCO O1 E-1 and E-2, ask a California operation for its
    organic registration number: CDFA's for crops and raw-ag handling, CDPH's for processed products. The
    number was recorded (`StateOrganicRegistration`) and printed in the audit dossier, but never in the
    renewal packet, so both agents' forms went out without it. Printed for a California operation, or for
    any operation that has one on file; nothing for an operation elsewhere with none, because the
    requirement is California's alone.

    One line per agency, from that agency's latest row (2026-11-15): a CDPH number printed under CDFA's
    name would put it in the wrong box of both forms.
    """
    from certifications.models import StateOrganicRegistration
    from common.us_states import resolve_establishment_state

    latest = {reg.registering_agency: reg for reg in StateOrganicRegistration.latest_per_agency(est, state="CA")}
    if not latest:
        if resolve_establishment_state(est) != "CA":
            return []
        return [
            kv(CA_REGISTRATION_LABEL, "none on file"),
            Paragraph(
                "[REVIEW] CCOF's and Oregon Tilth's forms ask a California operation for its organic "
                "registration number: CDFA's, or CDPH's for processed products. Add it under State Organic "
                "Program Registration on the Organic System Plan page.",
                styles["meta"],
            ),
        ]
    lines = []
    for agency in ("cdfa", "cdph"):
        reg = latest.get(agency)
        if reg is None:
            continue
        details = [reg.get_status_display()]
        if reg.county:
            details.append(f"{reg.county} County")
        if reg.renewal_date:
            details.append(f"renewal date {reg.renewal_date.isoformat()}")
        lines.append(
            kv(
                _CA_REGISTRATION_LABELS[agency],
                reg.registration_number or "number not recorded",
                note=", ".join(details),
            )
        )
        # The model's own reason first (one wording with the audit dossier); a registered row with no
        # number is current there but still leaves both agents' forms blank.
        problem = reg.not_current_reason or (
            "The registration number is not recorded." if not reg.registration_number else None
        )
        if problem is not None:
            lines.append(
                Paragraph(_escape(f"[REVIEW] {problem} Update it before the forms are filed."), styles["meta"])
            )
    return lines


PRODUCT_TYPES_LABEL = "Organic and non-organic product"


def _product_types_cover_lines(osp, kv, styles) -> list:
    """CCOF Certification Contract D1 and OTCO O1 A-2: "Both organic and nonorganic product(s)" or
    "Organic product(s) only". Both forms ask it on page one and the packet never said it; the answer
    is G6.0's split declaration (§ 205.2: an operation that produces or handles both), with where the
    non-organic product comes from beside it, so a buffer-crop-only farm is read as one.
    """
    from certifications.services.split_operation import (
        DECLARED_NO,
        DECLARED_YES,
        nonorganic_product_sources,
        plan_g2_lists_split_production,
        plan_split_declaration,
    )

    declaration = plan_split_declaration(osp)
    if declaration == DECLARED_YES:
        sources = nonorganic_product_sources(osp)
        note = (
            "non-organic product from: " + "; ".join(s[0].lower() + s[1:] for s in sources)
            if sources
            else "the plan does not say where the non-organic product comes from"
        )
        return [kv(PRODUCT_TYPES_LABEL, "Both organic and nonorganic product(s)", note=note)]
    if declaration == DECLARED_NO:
        lines = [kv(PRODUCT_TYPES_LABEL, "Organic product(s) only")]
        if plan_g2_lists_split_production(osp):
            lines.append(
                Paragraph(
                    "[REVIEW] The plan's fraud-prevention answers say the operation produces or sells both "
                    "organic and nonorganic product, and its production answers say it does not. Correct the "
                    "one that is wrong before the forms are filed.",
                    styles["meta"],
                )
            )
        return lines
    return [
        kv(PRODUCT_TYPES_LABEL, "not stated in the plan"),
        Paragraph(
            "[REVIEW] The plan does not say whether the operation produces or handles non-organic product. "
            "Answer the split-operation question in Production, section A.",
            styles["meta"],
        ),
    ]


#: How many of one document's review notes the cover prints before "and N more".
_COVER_NOTES_PER_DOCUMENT = 5


def _review_notes_cover_flowables(documents, styles) -> list:
    """The cover's list of the review notes left in the packet's documents (overall review 2026-11,
    OV-PK-W07, OV-PK-C07, OV-PK-O08: a first orchard packet carried 17 `[REVIEW]` lines across its files
    and nothing said where). `documents` is `packet_review_notes.collect()` over the documents built
    before the cover. The notes stay in their documents; this says where they are."""
    from certifications.services.packet_review_notes import REVIEW_NOTES_HEADING, printable

    out = [Spacer(1, 8), Paragraph(REVIEW_NOTES_HEADING, styles["header"])]
    found = [d for d in documents if d.notes]
    unreadable = [d for d in documents if d.unreadable]
    total = sum(len(d.notes) for d in found)
    if not total:
        out.append(
            Paragraph(
                (
                    "No review notes were found in the documents that could be read."
                    if unreadable
                    else "No review notes are left in the packet's documents."
                ),
                styles["body"],
            )
        )
    else:
        lead = f"{_count_phrase(total, 'review note')} in {_count_phrase(len(found), 'document')}. " + (
            "It is a question for the operation to settle or explain before the packet is sent; it is listed "
            "here so it is not found one page at a time."
            if total == 1
            else "Each is a question for the operation to settle or explain before the packet is sent; they are "
            "listed here so nothing is found one page at a time."
        )
        out.append(Paragraph(_escape(lead), styles["body"]))
    for d in found:
        out.append(Paragraph(f"<b>{_escape(d.path)}</b>", styles["meta"]))
        for note in d.notes[:_COVER_NOTES_PER_DOCUMENT]:
            out.append(Paragraph(_escape(f"• {printable(note)}"), styles["meta"]))
        if len(d.notes) > _COVER_NOTES_PER_DOCUMENT:
            out.append(Paragraph(_escape(f"• and {len(d.notes) - _COVER_NOTES_PER_DOCUMENT} more"), styles["meta"]))
    for d in unreadable:
        out.append(
            Paragraph(
                _escape(f"{d.path}: this file could not be read, so any review notes in it are not listed here."),
                styles["meta"],
            )
        )
    return out


def _packet_cover_pdf(osp, review_notes=None) -> bytes:
    """The cover a certifier reads first.

    Was four lines — name, version, today's date, a contents list — which is a cover for a
    document set, not for a renewal. A renewal cover is read for WHICH operation (certificate
    number, certifier, the § 205.401(b) responsible person), WHICH year it continues, and WHAT
    changed; none of that was on it, and the § 205.406 filing the packet exists to carry was not
    in the packet at all. It also now carries the plan review — the list of things the
    operation's own records did after the plan's answers were written — because that is the
    one page where the operator will see it before the packet leaves.

    `review_notes` is the packet's `packet_review_notes.collect()` result, listed after the plan
    review. None (a cover rendered on its own, outside a packet build) prints no list: there are no
    other documents to read.
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

    from certifications.services.packet_scope import current_scope

    scope = current_scope()
    applicant = ctx.get("never_certified", False)
    if filing:
        year_line = f"Continuation for {filing.reporting_year}"
    elif applicant:
        year_line = "No certificate on file"
    else:
        year_line = "Continuation year not filed"
    scope_line = " · Changed sections only" if scope.changed_only else ""
    story = [
        Paragraph(
            "Organic System Plan packet" if applicant else "Organic System Plan — Renewal Packet",
            styles["title"],
        ),
        Paragraph(
            _escape(f"{osp.establishment.name} · {_plan_version_label(osp)} · {year_line}{scope_line}"),
            styles["subtitle"],
        ),
        Spacer(1, 8),
    ]
    story += _changed_only_cover_flowables(scope, styles)
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
                        "§ 205.401(b) asks for the name of the person completing the application and, for a "
                        "company, the person authorized to act on its behalf. Set the "
                        "responsible person when you edit the farm, so this line is the operation's own "
                        "answer rather than the plan author Trazo fell back to."
                    )
                    if ctx["responsible_person"]
                    else (
                        "§ 205.401(b) asks for the name of the person completing the application and, for a "
                        "company, the person authorized to act on its behalf. None is stated in "
                        "Trazo: set the responsible person when you edit the farm."
                    )
                ),
                styles["meta"],
            )
        )
    story += [
        kv("Address", ctx["address"] or "—"),
        kv("Phone", ctx["phone"] or "—"),
        kv("Email", ctx["email"] or "—"),
        kv("Certificate", _cover_certificate_value(ctx)),
    ]
    from certifications.services.operation_certificate import certificate_from_another_agent
    from certifications.services.packet_coverage import packet_agent

    unnumbered = ctx.get("certificate_unnumbered_agent")
    if unnumbered:
        from certifications.services.operation_certificate import unnumbered_from_another_agent

        plan_agent = unnumbered_from_another_agent(osp, unnumbered)
        if plan_agent:
            story.append(
                Paragraph(
                    _escape(
                        f"[REVIEW] The certificate recorded without its number is from {unnumbered}; this plan "
                        f"names {plan_agent}."
                    ),
                    styles["meta"],
                )
            )
    other = certificate_from_another_agent(osp)
    if other is not None:
        # The plan names a different agent than the one that issued the certificate on file: the
        # operation is moving agents, and this packet is not a renewal with the issuing agent.
        story.append(Paragraph(_escape(_another_agent_sentence(other, packet_agent(osp).name)), styles["meta"]))
    # The agent's own identifier for the operation (Oregon Tilth's Client ID), printed only when it
    # was recorded against the agent this packet is for: another agent's ID on this cover would be a
    # number attributed to an agent that never issued it.
    est = osp.establishment
    if est.certifier_client_id and est.certifier_client_id_agent:
        from certifications.services.packet_coverage import packet_agent

        if packet_agent(osp).slug == est.certifier_client_id_agent:
            story.append(kv("Client ID", est.certifier_client_id, note="as issued by the certifying agent"))
    story += _product_types_cover_lines(osp, kv, styles)
    story += _state_registration_cover_lines(est, kv, styles)
    story += [
        kv("Plan submitted", osp.submitted_at.date().isoformat() if osp.submitted_at else "not yet submitted"),
        kv("Packet generated", date.today().isoformat()),
        Spacer(1, 8),
        Paragraph(
            "Certification status" if applicant else "Continuation of certification (7 CFR 205.406)",
            styles["header"],
        ),
    ]
    if applicant:
        story.append(
            Paragraph(
                "No organic certificate is on file in Trazo for this operation, so no § 205.406(a) annual "
                "update applies: that update continues a certification that already exists. A first "
                "application is made under § 205.401 on the certifying agent's own application forms. "
                "This packet supports that application and does not replace it.",
                styles["body"],
            )
        )
    elif filing:
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
            # 2026-11-04 (reviewer reads): "1 deletion entry" beside 02's "None. No input ..." still
            # read as a contradiction, so an entry that states none says so.
            kv(
                "Entries under (a)(2)",
                f"{_entries_phrase(filing.additions, 'addition entry', 'addition entries')}, "
                f"{_entries_phrase(filing.deletions, 'deletion entry', 'deletion entries')}",
            ),
            Paragraph(
                "The filing itself — the change summary, additions and deletions — is document 02 in this packet.",
                styles["meta"],
            ),
        ]
        if filing.states_agent_file_changes:
            # Review of back #439: with a statement on 02 and 02s, "lists no changes" would contradict them.
            sentence = _agent_file_sentence(
                filing,
                osp,
                then=(
                    "so what changed against it is the operation's own statement on its annual update "
                    "(document 02), not a comparison Trazo made."
                ),
            )
            story.append(Paragraph(_escape(sentence), styles["meta"]))
        elif filing.holds_no_agent_copy:
            story.append(Paragraph(_escape(_agent_file_sentence(filing, osp)), styles["meta"]))
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
                    # A window from a date to itself checks nothing; say so rather than call it clean
                    # (reviewer reads, 2026-11-04).
                    _empty_review_window_sentence(review)
                    if review.answers_as_of and str(review.answers_as_of)[:10] >= str(review.reference_date)[:10]
                    else "No operation change is recorded between the plan's newest answer and "
                    f"{review.reference_date}."
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

    if review_notes is not None:
        # The cover's own notes (state registration, product types) are printed above and listed here
        # too, so the count covers the whole packet, this page included.
        from certifications.services.packet_review_notes import MARK, DocumentNotes, split_notes

        own = [t for t in (f.getPlainText() for f in story if isinstance(f, Paragraph)) if MARK in t]
        own = list(dict.fromkeys(n for t in own for n in split_notes(t)))
        story += _review_notes_cover_flowables(
            ([DocumentNotes("00-cover.pdf", own)] if own else []) + list(review_notes), styles
        )

    from certifications.services.packet_coverage import packet_certifier

    own_register = packet_certifier(osp)[1]
    story += [
        Spacer(1, 10),
        Paragraph("Contents", styles["header"]),
        Paragraph("00. This cover", styles["body"]),
        Paragraph("01. Six-section narrative snapshot (7 CFR 205.201(a))", styles["body"]),
        Paragraph(
            (
                "02. Annual update: none applies, no certificate is on file"
                if applicant
                else "02. Annual update — the § 205.406(a) filing"
            ),
            styles["body"],
        ),
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
        Paragraph(
            (
                _escape(
                    f"modules/: only the modules whose answers changed between plan v{scope.prior_version} and "
                    f"v{scope.new_version}, and those that show the operation's current records "
                    f"({len(scope.included) + len(scope.live)} of "
                    f"{len(scope.included) + len(scope.live) + len(scope.omitted)}); the ones left out are "
                    "named under Changed sections only"
                )
                if scope.changed_only
                else "modules/ — one PDF per guided module, N/A attestations included"
            ),
            styles["body"],
        ),
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
    if ctx.get("never_certified", False):
        # A first-time applicant has nothing to continue (§ 205.401, not § 205.406).
        absent = (
            "No annual update applies to this operation: no organic certificate is on file in Trazo, "
            "and § 205.406(a) continues a certification that already exists. Nothing on this page is a "
            "filing."
        )
    else:
        absent = (
            f"No § 205.406(a) annual update is on file for OSP v{osp.version_number}. The packet "
            "cannot stand in for the filing: record the year's changes, planned additions and "
            "deletions, and file it before the packet is sent."
        )
    story += [
        Paragraph(_escape(f"{osp.establishment.name} · {_plan_version_label(osp)}"), styles["subtitle"]),
        Spacer(1, 10),
        Paragraph(_escape(absent), styles["body"]),
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
    # What the changes below are measured against, as the operation stated it (signed with the rest).
    if filing.holds_no_agent_copy:
        story.append(
            Paragraph(
                _escape(
                    _agent_file_sentence(
                        filing,
                        osp,
                        then="so the changes below are the operation's own account against that plan, not a "
                        "comparison Trazo made.",
                    )
                ),
                styles["body"],
            )
        )
    elif filing.prior_plan_basis == filing.PRIOR_BASIS_TRAZO_VERSION:
        story.append(
            Paragraph(
                _escape(
                    f"{_agent_name(osp, starts_sentence=True)} received plan v{filing.prior_osp.version_number} from Trazo "
                    "(the operation's statement)."
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
    story += _stated_changes_lines(filing, osp, styles)
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
        since = f"the plan on file with {_agent_name(osp)}" if filing.holds_no_agent_copy else "the prior plan"
        story += [Spacer(1, 8), Paragraph(_escape(f"Sections attested unchanged since {since}"), styles["header"])]
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
            f"{sales.label}, the sales period stated on this update, from the operation's sales records in Trazo. "
            "Each sale counts by the date on its sale record, not by when it was paid."
        )
    else:
        sales_sentence = (
            f"${total:,.2f} across {_count_phrase(n_sales, 'sale')} invoiced as organic and dated in "
            f"calendar {sales.label}, from the operation's sales records in Trazo. Each sale counts by the date "
            "on its sale record, not by when it was paid."
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
            "Producer attestation: the information above is true, complete and accurate to "
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


def _renewal_routing_flowables(osp, styles, filing=None) -> list:
    """The agent's own renewal forms, each row with where its answer is in this packet.

    These forms are filed with the agent, on its paper or its site. Nothing here completes one: the
    rows say where to copy an answer from, and name the ones the operation answers there itself.
    """
    from certifications.services.packet_coverage import renewal_routing
    from certifications.services.packet_scope import mark_omitted

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
    from certifications.services.operation_certificate import certificate_from_another_agent

    other = certificate_from_another_agent(osp)
    if other is not None:
        story.append(Paragraph(_escape(_another_agent_sentence(other, agent_name)), styles["meta"]))
    basis = _fee_basis_sentence(osp)
    if basis:
        # Run 4, R4-04: stated here, on the page that changes with the export, because 02 is frozen as
        # filed and may name no agent at all. 02 prints its sales subtotal only when a filing exists.
        # 02 prints a subtotal only for a filing whose sales year is over and whose every sale carries
        # an amount (`_annual_update`); otherwise it says why it gives none. This line cites the subtotal
        # only when 02 prints one. "Filed against this plan version", because an update linked to another
        # version can be on file and named on 02 without its sales section (`other_filing`).
        if filing is None:
            lead = "No annual update is filed against this plan version, so 02 carries no sales subtotal."
        else:
            from certifications.services.renewal_sales import organic_sales_subtotal

            sales = organic_sales_subtotal(osp.establishment, filing)
            if not sales.running and sales.n_sales and sales.n_priced == sales.n_sales:
                lead = (
                    "the subtotal printed on 02 is a subtotal of the operation's sales records, not reconciled to "
                    "its books and not this agent's fee figure."
                )
            else:
                lead = "02 gives no sales subtotal for this filing; its sales section says why."
        story.append(Paragraph(_escape(f"Sales figure: {lead} {basis}"), styles["meta"]))
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
        # Indented under its question, with a gap before the next one, so a reviewer reading down
        # the page can tell which answer belongs to which question.
        from reportlab.lib.styles import ParagraphStyle

        where_style = ParagraphStyle("routing_where", parent=styles["meta"], leftIndent=10, spaceAfter=5)
        ask_style = _sticks_to_next(styles["body"])
        for row in form.rows:
            # What the form asks, then where the answer is. The ref alone sent a reviewer to the form
            # to learn what "4a" was (renewal audit, 2026-11-04).
            story.append(Paragraph(_escape(f"• {_routing_question(row)}"), ask_style))
            line = row.standing + (f": {row.where}" if row.where else "")
            # Skipped when the standing already says so: "optional; ... [optional on the form]".
            if row.optional and "optional" not in row.standing:
                line += " [optional on the form]"
            # A changed-sections packet leaves unchanged module files out: a row citing one says so.
            story.append(Paragraph(_escape(mark_omitted(line)), where_style))
    return story


def _routing_question(row) -> str:
    """The row's ref and what the form asks, without saying the ref twice.

    Many register rows are named after the form's own label ("Operation Name", "Step 1: Request
    Renewal", "Table (site, name, changes)"), and the ask begins with that label, so "ref: asks"
    printed "Operation Name: Operation Name (required)."
    """
    lead = row.ref.split(" (", 1)[0].strip().lower()
    if lead and row.asks.lower().startswith(lead):
        return row.asks
    return f"{row.ref}: {row.asks}"


def _agent_file_flowables(filing, osp, styles) -> list:
    """The year one statement on 02s, for every agent: the plan the changes are measured against is
    one Trazo has never seen, so no section list is computed against it.

    Printed for every agent, not only those whose renewal form asks for a list
    (`packet_coverage._SECTION_LIST_AGENTS`): CCOF asks for changed sections on its own forms and WSDA
    for section updates to its living plan, and a packet that says nothing about either reads as
    "nothing changed" (overall review 2026-11, OV-PK-C01, OV-PK-W03).
    """
    from certifications.services.packet_coverage import _module_location

    if filing is None or not filing.holds_no_agent_copy:
        return []
    agent = _agent_name(osp)
    send = f"Send the changed sections the way {agent}'s renewal asks, on {agent}'s own forms."
    story = [
        Spacer(1, 10),
        Paragraph(_escape(f"Changes against the plan on file with {agent}"), styles["header"]),
    ]
    if not filing.states_agent_file_changes:
        story.append(
            Paragraph(
                _escape(
                    _agent_file_sentence(
                        filing, osp, then="so this packet cannot list which sections changed against it."
                    )
                    + " The year's changes are the ones the operation states on its annual update (document 02). "
                    + send
                ),
                styles["body"],
            )
        )
        return story
    story.append(
        Paragraph(
            _escape(
                _agent_file_sentence(
                    filing, osp, then="so what follows is the operation's own statement, not a comparison Trazo made."
                )
            ),
            styles["body"],
        )
    )
    if not _stated_lines(filing):
        story.append(
            Paragraph(
                _escape(f"The operation states that nothing in the plan on file with {agent} changed."), styles["body"]
            )
        )
        return story
    new = filing.new_osp
    if new is not None and new.pk != osp.pk:
        # Review of back #439: this packet's module files hold v{prior}'s answers, not the year's change.
        story.append(
            Paragraph(
                _escape(
                    f"Sections the operation states changed. This packet is built from plan v{osp.version_number}, "
                    f"and the year's annual update moves to plan v{new.version_number}: their current answers are "
                    f"in the module files of the packet built from plan v{new.version_number}."
                ),
                styles["body"],
            )
        )
        story += [Paragraph(_escape(f"• {line}"), styles["body"]) for line in _stated_lines(filing)]
    else:
        story.append(
            Paragraph(
                _escape("Sections the operation states changed, and where their current answers are in this packet:"),
                styles["body"],
            )
        )
        story += [Paragraph(_escape(f"• {line}"), styles["body"]) for line in _stated_lines(filing, _module_location)]
    story.append(Paragraph(_escape(send), styles["body"]))
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
        Paragraph(
            (
                "OSP Update Form Step 4: plan sections the operation states changed"
                if result.state == "stated"
                else "OSP Update Form Step 4: plan sections whose answers changed"
            ),
            styles["header"],
        ),
    ]
    if result.state == "no_filing":
        story.append(
            Paragraph(
                "No annual update is linked to this plan, so there are no two plan versions to compare.",
                styles["body"],
            )
        )
        return story
    if result.state == "first_version":
        story.append(
            Paragraph(
                _escape(
                    f"None listed from Trazo: the plan on file with {agent} predates plan v{result.prior_version}, "
                    "the first plan version in Trazo (see above). List the updated sections on the form yourself."
                ),
                styles["body"],
            )
        )
        return story
    if result.state == "stated":
        story.append(
            Paragraph(
                _escape(
                    f"Listed from the operation's statement on its annual update, by {agent}'s form codes: Trazo has no "
                    f"copy of the plan on file with {agent} to compare (see above). The sections are still listed on "
                    "the agent's form, with the agent's own forms attached."
                ),
                styles["body"],
            )
        )
        if not result.forms and not result.unmapped:
            story.append(
                Paragraph(_escape("The operation states that nothing in the plan on file changed."), styles["body"])
            )
        for label, files in result.forms:
            story.append(
                Paragraph(_escape(f"• {label}: stated changed; current answers in {', '.join(files)}"), styles["body"])
            )
        for label, path in result.unmapped:
            where = f"current answers in {path} (no form of the agent maps to it)" if path else _NOT_IN_REGISTRY
            story.append(Paragraph(_escape(f"• {label}: stated changed; {where}"), styles["body"]))
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
        listed = (
            "The sections the operation states changed are listed"
            if result.stated
            else "The section comparison is printed"
        )
        story.append(
            Paragraph(
                _escape(
                    f"This packet is built from plan v{result.prior_version}, and the year's annual update moves "
                    f"to plan v{result.new_version}. {listed} in the packet built from "
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
    # Not the basis an earlier published copy gave: WSDA updates the form, sends it with the renewal
    # application and asked Trazo not to reproduce it (reply received by 2026-11-09; overall review 2026-11, OV-PK-W01).
    "wsda": (
        "WSDA's Renewal Fee Form (AGR 2521), sent with its renewal application, sets the basis; WSDA updates "
        "the form regularly and does not publish it."
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


def _unchanged_but_changed_flowables(filing, osp, styles) -> list:
    """Sections the year's filing attests unchanged that differ between the plan versions.

    The filing (02) is the operator's statement as filed and is not rewritten. The supplement, which
    reports what is true today, sets the two side by side (CCOF, WSDA and OTCO reviewer reads,
    2026-11-04: commingling attested unchanged while split and parallel production went from No to
    Yes). Compared from the plan the filing continues to the plan this packet is built from, with
    `plan_version_changes.section_differences`, the comparison signing is refused on
    (OV-PK-O01), so a revision signed since then prints here only when the plan moved after it.
    """
    if filing is None:
        return []
    attestation = filing.sections_unchanged_attestation
    if not isinstance(attestation, dict):
        return []
    attested = {key for key, val in attestation.items() if val is True and key != APPLICATION_INFO_KEY}
    if not attested:
        return []
    from certifications.services.plan_version_changes import section_differences

    new = filing.new_osp or osp
    if new is None or new.pk == filing.prior_osp_id:
        return []
    try:
        differences = section_differences(filing.prior_osp, new)
    except Exception:  # noqa: BLE001 (a supplement must build without this comparison)
        logger.exception("Could not compare plan versions for the unchanged attestation on OSP %s", osp.pk)
        return []
    changed = [key for key in differences if key in attested]
    if not changed:
        return []
    story = [
        Spacer(1, 10),
        Paragraph("Sections attested unchanged that changed", styles["header"]),
        Paragraph(
            _escape(
                f"The filing attests these sections unchanged since the prior plan, but they differ between plan "
                f"v{filing.prior_osp.version_number} and v{new.version_number}. The filing is the operator's "
                "statement and is not changed here."
            ),
            styles["body"],
        ),
    ]
    for key in changed:
        clause, label = SECTION_LABELS.get(key, (None, key.replace("_", " ")))
        what = ", ".join(_DIFFERS_IN_SUPPLEMENT.get(kind, kind) for kind in differences[key]["differs"])
        line = f"§ 205.201{clause}: {label} ({what})" if clause else f"{label} ({what})"
        story.append(Paragraph(_escape(f"• {line}"), styles["body"]))
    return story


#: How 02s names each kind of difference (`plan_version_changes.DIFFERS_*`), in the third person:
#: the certifier reads it.
_DIFFERS_IN_SUPPLEMENT = {
    "answers": "answers",
    "materials": "materials list",
    "narrative": "the operator's own narrative",
    "record_types": "record types confirmed",
}


def _inspection_file_line(label: str, doc) -> str:
    """Where one inspection-record file is: its path in this ZIP, or why it is not in it. Read from
    the manifest of the build in progress, so the page never names a file the reader will not find."""
    from certifications.services.packet_attachments import ATTACHED, current_manifest, inspection_document_source

    manifest = current_manifest()
    shipped = manifest.for_source(inspection_document_source(doc)) if manifest else []
    if shipped and shipped[0].state == ATTACHED:
        return f"{label}: attached to this packet as {shipped[0].zip_path}."
    if shipped:
        return f"{label}: on file in Trazo, not in this packet ({shipped[0].detail})."
    return f"{label}: on file in Trazo, not in this packet."


_INSPECTION_STATUS_WORDS = {
    "resolved": "The certifying agent's resolution notice is on file.",
    "resolution_stated_no_copy": (
        "A resolution date of {resolved} is recorded; the certifying agent's resolution notice is not attached."
    ),
    "respond_by_passed_no_response": "The rebut-or-correct date has passed and no response is recorded.",
    "response_sent": "A response is recorded. No resolution notice from the certifying agent is recorded yet.",
    "open": "No response is recorded yet.",
}


def _certifier_inspection_flowables(osp, styles) -> list:
    """02s: the operation's own record of its certifier's inspections and of the items the agent
    sent (7 CFR 205.662), with its responses.

    Every line is what the operation recorded; nothing here is a finding by Trazo, and an empty
    record says it is empty in Trazo, never that the operation has no noncompliance.
    """
    from certifications.services.certifier_notices import RESOLVED_LISTED_FOR_DAYS, notice_status, packet_records

    latest, inspections, notices = packet_records(osp.establishment)
    out = [
        Spacer(1, 10),
        Paragraph("Certifier inspections and notices (operation's record)", styles["header"]),
        Paragraph(
            _escape(
                "As recorded by the operation in Trazo; Trazo receives nothing from the certifying agent. "
                "Listed: the most recent inspection, every item with no resolution notice attached, and "
                f"items resolved in the last {RESOLVED_LISTED_FOR_DAYS} days."
            ),
            styles["meta"],
        ),
    ]
    if latest is None:
        out.append(Paragraph("No inspection is recorded in Trazo.", styles["body"]))
    else:
        out.append(
            Paragraph(
                _escape(f"Date of the last organic inspection: {latest.inspected_on.isoformat()}."), styles["body"]
            )
        )
    for inspection in inspections:
        parts = [f"Inspection on {inspection.inspected_on.isoformat()}"]
        if inspection.certifying_agent:
            parts.append(f"by {inspection.certifying_agent}")
        line = " ".join(parts)
        extras = []
        if inspection.inspection_kind:
            extras.append(inspection.get_inspection_kind_display().lower())
        if inspection.inspector_name:
            extras.append(f"inspector {inspection.inspector_name}")
        if extras:
            line += f" ({', '.join(extras)})"
        out.append(Paragraph(_escape(f"• {line}."), styles["body"]))
        if inspection.report_document_id:
            out.append(
                Paragraph(
                    _escape(_inspection_file_line("Inspection report", inspection.report_document)), styles["meta"]
                )
            )
        else:
            out.append(Paragraph("Inspection report: not attached in Trazo.", styles["meta"]))
    if not notices:
        # `notices` is windowed (resolved items older than the window drop out), so an empty list is
        # not an empty record: say which it is (review of back #354).
        from certifications.models import CertifierNotice

        older = CertifierNotice.objects.filter(establishment=osp.establishment).count()
        if older:
            out.append(
                Paragraph(
                    _escape(
                        "No item from the certifying agent is open or was resolved in the last "
                        f"{RESOLVED_LISTED_FOR_DAYS} days. {older} older resolved "
                        f"{'item is' if older == 1 else 'items are'} kept in Trazo and not listed here."
                    ),
                    styles["body"],
                )
            )
        else:
            out.append(Paragraph("No item from the certifying agent is recorded in Trazo.", styles["body"]))
        return out
    open_count = sum(1 for n in notices if n.kind == "notice_of_noncompliance" and notice_status(n) != "resolved")
    out.append(
        Paragraph(
            _escape("Notices of noncompliance with no resolution notice attached, as recorded: " f"{open_count}."),
            styles["body"],
        )
    )
    for notice in notices:
        name = notice.agent_label if notice.kind == "other_item" else "Notice of noncompliance (§ 205.662(a))"
        heading = name + (f", dated {notice.received_on.isoformat()}" if notice.received_on else "")
        if notice.inspection_id:
            heading += f", from the inspection on {notice.inspection.inspected_on.isoformat()}"
        out.append(Paragraph(_escape(f"• {heading}: {notice.description}"), styles["body"]))
        lines = []
        if notice.notice_document_id:
            lines.append(_inspection_file_line("The agent's letter", notice.notice_document))
        if notice.respond_by:
            lines.append(f"Rebut or correct by {notice.respond_by.isoformat()} (§ 205.662(a)(3)).")
        if notice.response_kind or (notice.response_text or "").strip() or notice.response_sent_on:
            response = notice.get_response_kind_display() if notice.response_kind else "Response"
            if notice.response_sent_on:
                response += f", sent {notice.response_sent_on.isoformat()}"
            text = (notice.response_text or "").strip()
            lines.append(f"{response}: {text}" if text else f"{response}.")
        for link in notice.response_links.all():
            lines.append(_inspection_file_line("Sent with the response", link.document))
        if notice.resolution_document_id:
            lines.append(_inspection_file_line("Resolution notice (§ 205.662(b))", notice.resolution_document))
        resolved = notice.resolution_received_on.isoformat() if notice.resolution_received_on else ""
        lines.append(_INSPECTION_STATUS_WORDS[notice_status(notice)].format(resolved=resolved))
        for line in lines:
            out.append(Paragraph(_escape(line), styles["meta"]))
    return out


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
        if ctx.get("never_certified", False):
            story.append(
                Paragraph(
                    "No organic certificate is on file in Trazo for this operation either. Any forms "
                    "listed below are the certifying agent's renewal forms; a first application under "
                    "§ 205.401 uses the agent's application forms instead.",
                    styles["body"],
                )
            )
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
    story += _unchanged_but_changed_flowables(ctx["filing"], osp, styles)
    story += _renewal_routing_flowables(osp, styles, filing=ctx["filing"])
    story += _certifier_inspection_flowables(osp, styles)
    story += _agent_file_flowables(ctx["filing"], osp, styles)
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
    """Part B step 5: harvested minus sold for the traced lot, stated or explained.

    The sentence is `audit_trail_exhibit.balance_statement`, the one the dossier's Output
    Reconciliation prints too (overall review 2026-11, OV-FJ-C24)."""
    from certifications.services.audit_trail_exhibit import balance_statement

    out = [Paragraph("<b>5. Balance</b> \u2014 harvested minus sold, for this lot", styles["body"])]
    text, review = balance_statement(balance)
    if balance is None or balance.difference is None:
        out.append(Paragraph(_escape(f"{text} The operator states the balance on this page."), styles["meta"]))
        return out
    out.append(Paragraph(_escape(f"[REVIEW] {text}" if review else text), styles["body"]))
    out.extend(_buffer_crop_flowables(balance, styles))
    return out


def _buffer_crop_flowables(balance, styles) -> list:
    """The § 205.202(c) buffer crop, stated beside the organic balance it is kept out of."""
    from certifications.services.audit_trail_exhibit import buffer_statement

    text = buffer_statement(balance)
    return [Paragraph(_escape(text), styles["meta"])] if text else []


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
            if row.stated_by_operator:
                # The operator's own words about their own document, marked as theirs: every other
                # stated link is a fact about how Trazo's records connect.
                link = f"{link} (as stated by the operator)"
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
                    "the link on this page, or once in module G8.0 §A, where it prints from then on.",
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
        story.append(
            Paragraph(
                "<b>1. Planting records</b> (link: parcel and season; the planting is recorded on the season)",
                styles["body"],
            )
        )
        if trail.plantings:
            for pl in trail.plantings:
                bits = [pl["date"] or "undated", pl["kind"]]
                if pl["block"]:
                    bits.append(f"block {pl['block']}")
                if pl["rootstock"]:
                    bits.append(f"rootstock {pl['rootstock']}")
                if pl["source"]:
                    bits.append(f"seed or stock: {pl['source']}")
                if pl["supplier"]:
                    bits.append(f"supplier {pl['supplier']}")
                if pl["lot"]:
                    bits.append(f"lot {pl['lot']}")
                story.append(Paragraph(_escape("• " + " · ".join(bits)), styles["meta"]))
        else:
            # A perennial block is planted once, not each season, so its season usually has none.
            story.append(
                Paragraph(
                    "• No planting or transplanting record is on this season. A perennial planting is "
                    "recorded on the season it went in.",
                    styles["meta"],
                )
            )
        story.append(Paragraph("<b>2. Harvest records</b> — link: Lot ID + harvest date + parcel", styles["body"]))
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
            Paragraph("<b>3. Storage</b> — link: storage location on the harvest record + Lot ID", styles["body"])
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
                "<b>4. Sales records</b> — link: invoice / bill of lading number + Lot ID + buyer; organic status as identified on the invoice",
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
    from certifications.services.packet_scope import mark_omitted

    # A changed-sections packet leaves unchanged module files out: a location naming one says so.
    location = mark_omitted(location)
    if PARCEL_APPLICATION_LOCATION not in location:
        return location
    listed = ", ".join(parcel_names) if parcel_names else "none recorded"
    return location.replace(PARCEL_APPLICATION_LOCATION, f"parcels/, one Parcel Application per parcel ({listed})")


#: How each open state reads on the coverage page, in the order the page lists them.
_OPEN_STATE_WORDING = (
    ("unanswered", "not yet answered"),
    ("unconfirmed", "answered on an earlier version of the question, not yet confirmed"),
    ("pending", "answered as not yet known by the operation"),
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


def _printed_rows_sentence(printed_rows) -> str:
    """ "Printed from your records, not checked against this plan's answers: A5 (00-cover.pdf: Address)."

    Covered rows that cite no answering question (`packet_answers.stated_in_packet`). They sat in the
    "Still open" sentence, under a heading telling the grower the agent's own form was needed for them,
    while the packet printed them (overall review 2026-11, OV-PK-C04, O06, W06). Named apart, with
    the location the register states, and never as answered: nothing read this plan's answers for them.
    """
    from certifications.services.packet_scope import mark_omitted

    grouped: dict[str, list[str]] = {}
    for ref, where in printed_rows:
        grouped.setdefault(where, []).append(ref)
    parts = [f"{', '.join(refs)} ({mark_omitted(where)})" for where, refs in grouped.items()]
    return "Printed from your records, not checked against this plan's answers: " + "; ".join(parts) + "."


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


def _coverage_registered_forms(story, styles, osp, certifier, agent_label, parcel_names, printed_check=None) -> None:
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

    forms = form_coverage(osp, certifier, printed_check=printed_check)
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
                "optional are named under the form when they have no answer. The certifying agent "
                "decides whether it accepts these pages in place of its own forms; until it says so, "
                "the grower completes the agent's form, copying from these pages."
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
        # Not "Forms this packet answers" (review finding OV-PK-C02, 2026-11): no certifier has
        # said it accepts these pages in place of its forms, and an optional item may still be
        # open, so the heading claims the questions, not the form, and never "in full".
        story.append(Paragraph("Forms whose questions this packet answers", styles["header"]))
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
            if form.printed_rows:
                story.append(Paragraph(_escape(_printed_rows_sentence(form.printed_rows)), styles["meta"]))
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
    wrong agent. With no register for the agent, the page maps no document to any agent's forms.

    The module documents still carry the Common OSP section codes (G4.1 and the rest) in their
    headings, footers and file names, and until 2026-11-18 this page listed those files without a
    word on the codes, while the app told the grower the packet "borrows no agent's form numbers"
    (overall review 2026-11, OV-PK-F05). The page now says whose codes they are.
    """
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
    from certifications.services.packet_coverage import _module_location, _packet_module_keys, module_file_stem

    agent = stated_agent.strip()
    modules = dict(MODULES_BY_KEY)
    modules[PARCEL_APPLICATION.key] = PARCEL_APPLICATION
    # A file name writes the code with "_" for "." (G2_0.pdf), so the page quotes both spellings,
    # and only from modules whose file is named by their code.
    coded = [
        modules[key]
        for key in _packet_module_keys()
        if key in modules
        and modules[key].code
        and module_file_stem(modules[key]) == modules[key].code.replace(".", "_")
    ][:2]
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
    if coded:
        whose = f"{agent}'s" if agent else "the agent's"
        headings = ", ".join(m.code for m in coded)
        files = ", ".join(module_file_stem(m) for m in coded)
        story.append(
            Paragraph(
                _escape(
                    f"The codes in each document's heading ({headings} and so on), written {files} in the file "
                    f"names below, are the Common OSP's section codes, not {whose} form numbers."
                ),
                styles["meta"],
            )
        )
    for key in _packet_module_keys():
        location = _module_location(key)
        module = modules.get(key)
        if not location or module is None:
            continue
        title = module.title.get("en", key) if isinstance(module.title, dict) else str(module.title)
        story.append(Paragraph(_escape(f"{title}: {_coverage_location(location, parcel_names)}"), styles["body"]))


def _coverage_pdf(osp, printed_check=None) -> bytes:
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
        _coverage_registered_forms(story, styles, osp, certifier, agent_label, parcel_names, printed_check)
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


def generate_osp_packet(osp, scope=None) -> bytes:
    """Assemble the renewal packet ZIP. Single source of packet content.

    `scope` is a `packet_scope.PacketScope`: None (or the full scope) carries every module PDF; a
    changed-sections scope carries only the module PDFs whose answers changed, and every other
    document as the full packet does (see `packet_scope` for what stays in and why).
    """
    from certifications.services.packet_attachments import build_manifest, building
    from certifications.services.packet_index_recorder import document, recording
    from certifications.services.packet_scope import scoped

    _refresh_narratives_if_editable(osp)
    establishment = osp.establishment
    manifest = build_manifest(osp)
    out = io.BytesIO()
    # The ZIP's entries, in the order they are written at the end. The cover is the first entry but is
    # rendered after the documents it lists the review notes of, so `write(..., first=True)` puts it
    # at the front when it is ready.
    entries = []
    with (
        scoped(scope),
        building(manifest),
        recording() as recorder,
    ):

        def write(path, data, filed=False, first=False):
            # Every document is kept by path for 06, the question index, which is built last and
            # reads them back to say where each form and question is (T24).
            if first:
                entries.insert(0, [path, data])
            else:
                entries.append([path, data])
            recorder.documents[path] = data
            if filed:
                recorder.filed.add(path)

        # "01-organic-system-plan.pdf", not "01-narrative-snapshot.pdf" (2026-09-07). This file
        # IS the organic system plan: the § 205.201(a) narratives plus the
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
            # A changed-sections packet leaves an unchanged module out; the cover names it.
            if scope is not None and not scope.carries_module(module.key):
                continue
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

        # The cover, rendered now so it can list the review notes every document above carries
        # (overall review 2026-11, OV-PK-W07). It is kept for 06 like the others, and still written first.
        from certifications.services.packet_review_notes import collect

        write("00-cover.pdf", _packet_cover_pdf(osp, review_notes=collect(list(entries))), first=True)

        # 04 again, in its own place, now that every document it can point at is built. A covered row
        # that cites no answering question is named as printed only where its cited headings are found
        # in these bytes; the first render kept such rows open (review of back #518). That render fed
        # the cover's review notes, and this one adds none.
        from certifications.services.question_index import printed_locations

        _texts: dict = {}
        _coverage = _coverage_pdf(osp, printed_check=lambda item: bool(printed_locations(item, recorder, _texts)))
        for _entry in entries:
            if _entry[0] == "04-coverage-and-scope.pdf":
                _entry[1] = _coverage
        recorder.documents["04-coverage-and-scope.pdf"] = _coverage

        # 06, the agent-ordered index, built last because it cites the pages above (the cover's included).
        from certifications.services.question_index import index_pdf

        write("06-question-index.pdf", index_pdf(osp, recorder))

        # Every operator file (maps, affidavits, receipts, the files uploaded for a named
        # attachment, a sale's source documents, lot tags and label photos) was read once, before
        # any page was written, so the pages above name exactly what is written here. A file that
        # could not be read or did not fit is named on those pages and is not written.
        for _entry in manifest.attached():
            entries.append([_entry.zip_path, _entry.data])
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in entries:
            zf.writestr(path, data)
    return out.getvalue()


def _packaging_pointer(osp) -> list[str]:
    """Where packaging free of prohibited substances is asked, and the answer there (CCOF G6.4 C1, 2026-11-18).

    CCOF asks it on its handling form; Trazo asks it once, on G6.1 §B. The line names the module as `module_pointer`
    does, then prints G6.1's own answer as given, or says it is not answered yet. Nothing is inferred from records.
    """
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.osp_modules.conditions import answer_value
    from certifications.services.osp_module_compiler import _format_answer_en
    from certifications.services.parcel_application_lines import module_pointer

    lines = [module_pointer(osp, "g6_1_harvest_transport", "Whether all packaging is free of prohibited substances")]
    module = MODULES_BY_KEY["g6_1_harvest_transport"]
    entry = ((osp.module_responses or {}).get("modules") or {}).get(module.key) or {}
    value = answer_value(entry.get("answers") or {}, "packaging_free_of_prohibited")
    if value not in (None, "", []) and not entry.get("not_applicable"):
        question = next(q for page in module.pages for q in page.questions if q.key == "packaging_free_of_prohibited")
        lines.append(f"G6.1 answers: {_format_answer_en(question, value)}.")
    return lines


def g6_4_all_organic_lines(osp) -> list[str]:
    """CCOF G6.4's first condition, an all-organic operation, set against G6.0's split operation. CCOF only: WSDA L
    and OTCO C7 ask post-harvest handling of any operation (blind re-grade 2026-11-19, CCOF G6.4 preamble)."""
    from certifications.osp_modules.conditions import answer_value
    from certifications.services.packet_coverage import packet_agent

    if packet_agent(osp).slug != "ccof":
        return []
    entry = ((osp.module_responses or {}).get("modules") or {}).get("g6_0_production") or {}
    if entry.get("not_applicable") or answer_value(entry.get("answers") or {}, "split_operation") is not True:
        return []
    return [
        "[REVIEW] G6.0 states the operation produces or handles both organic and nonorganic crops or products. "
        "CCOF's G6.4 (ORGB36) is for an all-organic operation handling only its own organic product, and points any "
        "other operation to the Handler OSP forms."
    ]


def _facility_pest_pointer(osp) -> list[str]:
    """Where facility pest management is asked, and how far G9.0 is answered (CCOF G6.2 B3 to B9).

    CCOF asks prevention, controls, materials, product protection and records on its storage form; Trazo asks them
    once, in G9.0. The line says where, and states G9.0 as it stands: marked not applicable, not answered yet, or with
    required questions still open. It never says "answered" for a section nobody has touched (review of back #368).
    The file path is named only inside a packet build, and a changed-sections packet that leaves G9.0 out says so.
    """
    from certifications.services.parcel_application_lines import module_pointer

    return [
        module_pointer(
            osp,
            "g9_0_facility_pest",
            "Facility pest management (target pests, prevention, physical controls, materials, how product is "
            "protected and the records kept)",
        )
    ]
