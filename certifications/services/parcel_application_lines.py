"""Lines the parcel application page prints beside an answer: facts the answer points at, held elsewhere.

Each function states what is on file. None of them rules on eligibility or compliance; where an answer and
the records disagree the line says so with `[REVIEW]`, and the determination stays the certifying agent's.

* `operation_export_lines`: WSDA AGR 2264 ref 9 asks per site whether crops may reach Canada. Trazo asks
  once for the operation (G8.0) and prints that answer on every parcel's page.
* `parcel_answer_lines`: the operation's address behind "same as the operation" (CCOF ORGB49 A3, WSDA AGR
  2264 ref 2, OTCO C2 2.1), where container production is described (CCOF ORGB49 A9 sends the operator to
  G3.1), the transition arithmetic behind the status applied for (WSDA AGR 2264 ref 4), and the treated
  seed planted here (WSDA AGR 2264 ref 11).
"""

from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta

from certifications.osp_modules.conditions import answer_value, effective_value, is_answered

#: Months from the last prohibited application, per status applied for (WSDA AGR 2264 ref 4's own figures).
_STATUS_MONTHS = {"organic": 36, "transitional": 12}


def module_answer_state(osp, module_key: str) -> str:
    """How far a farm-wide module is answered on the plan, as the end of a sentence.

    ", which the operation marks not applicable." / "; it is not answered yet." / "; N required question(s)
    there are not answered yet." / "." Never "answered" for a module nobody has touched (review of back #368).
    """
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.osp_modules.conditions import missing_required

    entry = ((getattr(osp, "module_responses", None) or {}).get("modules") or {}).get(module_key) or {}
    answers = entry.get("answers") or {}
    if entry.get("not_applicable"):
        return ", which the operation marks not applicable."
    if not answers:
        return "; it is not answered yet."
    missing = missing_required(MODULES_BY_KEY[module_key], answers)
    if missing:
        return (
            f"; {len(missing)} required question{'s' if len(missing) != 1 else ''} there "
            f"{'are' if len(missing) != 1 else 'is'} not answered yet."
        )
    return "."


def module_pointer(osp, module_key: str, topic: str) -> str:
    """ "<topic> is asked in <code> <title>[ (modules/<file>.pdf)]<state>", the path named only inside a packet
    build, and the sentence marked when a changed-sections packet leaves that file out."""
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.services.packet_attachments import current_manifest
    from certifications.services.packet_coverage import module_file_stem
    from certifications.services.packet_scope import mark_omitted

    module = MODULES_BY_KEY[module_key]
    title = module.title.get("en", module_key) if isinstance(module.title, dict) else str(module.title)
    where = f"{module.code} {title}".strip()
    if current_manifest() is not None:
        where += f" (modules/{module_file_stem(module)}.pdf)"
    return mark_omitted(f"{topic} is asked in {where}{module_answer_state(osp, module_key)}")


def operation_export_lines(osp) -> list[str]:
    """The operation's export answer (G8.0), printed on a parcel's page."""
    lead = "Export is asked once for the operation, in G8.0 Record Keeping"
    if osp is None:
        return [lead + "."]
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.services.osp_module_compiler import _format_answer_en

    module = MODULES_BY_KEY["g8_0_record_keeping"]
    entry = ((osp.module_responses or {}).get("modules") or {}).get(module.key) or {}
    answers = entry.get("answers") or {}
    activity_q = next(q for page in module.pages for q in page.questions if q.key == "import_export_activity")
    stored = answer_value(answers, "import_export_activity")
    if entry.get("not_applicable"):
        return [lead + ", which the operation marks not applicable."]
    if not is_answered(stored):
        return [lead + "; it is not answered yet."]
    lines = [f"{lead}. The operation's answer: {_format_answer_en(activity_q, stored)}."]
    if not is_answered(effective_value(activity_q, stored)):
        # The retired "Neither" said nothing about export by a buyer, broker or trader (audit T17).
        lines.append(
            "[REVIEW] That answer predates the question about export by a buyer, broker or trader, so it does "
            "not say whether crops from this parcel may be exported that way."
        )
        return lines
    destinations = answer_value(answers, "export_destinations")
    chosen = set(stored) if isinstance(stored, (list, tuple)) else {stored}
    if chosen & {"export", "indirect_export"}:
        lines.append(
            f"Countries named: {destinations}."
            if is_answered(destinations)
            else "No destination countries are named on the plan."
        )
    return lines


def parcel_answer_lines(osp, question_key: str, value, answers: dict, parcel) -> list[str]:
    """Lines under one answered parcel-application question."""
    if question_key == "location_same_as_operation" and value == "yes":
        return _operation_address_lines(parcel)
    if question_key == "container_production" and value is True and osp is not None:
        return [
            module_pointer(
                osp,
                "g3_1_container_greenhouse",
                "Container and greenhouse production (containers, growing media, structures and their materials)",
            )
        ]
    if question_key == "certification_status_requested" and value in _STATUS_MONTHS:
        return _status_arithmetic_lines(value, answers, parcel)
    if question_key == "treated_seed_planted" and value == "yes":
        lines = [
            "[REVIEW] Treated seed was planted on this parcel while under the operation's management; the "
            "certifying agent checks each treatment named here against the National List."
        ]
        if not is_answered(answer_value(answers, "treated_seed_detail")):
            lines.append("[REVIEW] No treatment brand or planting date is given.")
        return lines
    return []


def _operation_address_lines(parcel) -> list[str]:
    est = parcel.establishment
    parts = {
        "city": (est.city or "").strip(),
        "state": (est.state or "").strip(),
        "ZIP code": (est.zip_code or "").strip(),
        "country": (est.country or "").strip(),
    }
    place = ", ".join(p for p in (parts["city"], " ".join(x for x in (parts["state"], parts["ZIP code"]) if x)) if p)
    if parts["country"]:
        place = f"{place}, {parts['country']}" if place else parts["country"]
    lines = [f"The operation's address on file: {place}." if place else "The operation's address on file is blank."]
    blank = [name for name, v in parts.items() if not v]
    if blank:
        lines.append(
            f"[REVIEW] The operation's address on file has no {_join(blank, 'or')}, so this parcel's "
            f"{_join(blank, 'and')} {'is' if len(blank) == 1 else 'are'} not stated anywhere."
        )
    return lines


def _status_arithmetic_lines(status: str, answers: dict, parcel) -> list[str]:
    """The records' last prohibited application against the expected harvest, for the status applied for.

    Arithmetic, never a ruling: the line is printed only when the records put the end of the window after
    the date the operator expects to harvest."""
    harvest_raw = answer_value(answers, "expected_first_organic_harvest")
    try:
        harvest = date.fromisoformat(str(harvest_raw)[:10]) if harvest_raw else None
    except ValueError:
        harvest = None
    if harvest is None:
        return []
    from product.services.transition_status_service import compute_transition_status

    try:
        last = compute_transition_status(parcel).last_prohibited_date
    except Exception:  # noqa: BLE001 — a status that cannot be computed must not sink the page
        return []
    if last is None:
        return []
    months = _STATUS_MONTHS[status]
    window_end = last + relativedelta(months=months)
    if window_end <= harvest:
        return []
    return [
        f"[REVIEW] The records date the last prohibited application on this parcel {last.isoformat()}; "
        f"{months} months from it is {window_end.isoformat()}, after the expected first harvest "
        f"({harvest.isoformat()})."
    ]


def _join(words: list[str], conjunction: str) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + f" {conjunction} " + words[-1]
