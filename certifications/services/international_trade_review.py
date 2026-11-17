"""G8.0 page C (import and export) read against itself, the plan's materials list and the records.

WSDA AGR 2121 §Q ends with "Critical Variances: Canada": may the crops reach Canada, directly or through a
buyer, and is sodium nitrate used. § 205.602(h) allows sodium nitrate up to 20% of a crop's total nitrogen
requirement; Canada does not accept as organic the crops grown with it. OTCO C8 8.4-4 asks how exported
products meet the destination's equivalency arrangement, the same fact seen from the export side.

Two answers can be read against something else:
  * "No crops may reach Canada" beside the Canada attestation named among the certificates the
    destinations require (`export_certificate_types`);
  * "No sodium nitrate" beside a sodium nitrate material on the plan's own list, records of applications
    classified as sodium nitrate (`restricted_materials`), or fertilizer records whose nitrogen source is
    recorded as mined or natural, restricted, the choice whose label gives sodium nitrate as its example.

Lines say what the answers and records state, never which one is right, and never that a crop may or may
not go to Canada.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MODULE = "g8_0_record_keeping"

#: `ChemicalEvent.nitrogen_source`, the choice whose label gives sodium (Chilean) nitrate and its 20% limit as the
#: example. Read as its own line, never as a sodium nitrate classification: the record names a class, not a product.
MINED_NITROGEN = "mined_natural"


def _answers(osp) -> dict:
    from certifications.services.seed_stock_review import _answers as module_answers

    return module_answers(osp, MODULE)


def _shown(question_key, answers) -> bool:
    from certifications.services.seed_stock_review import _shown as shown

    return shown(MODULE, question_key, answers)


def _value(answers, key):
    from certifications.osp_modules.conditions import answer_value

    return answer_value(answers, key)


def mined_nitrogen_records(bundle) -> list:
    """Fertilizer records whose nitrogen source is recorded as mined or natural, oldest first, leaving out
    the ones already classified as sodium nitrate (they are counted on that line)."""
    from certifications.services.restricted_materials import SODIUM_NITRATE, logged_applications

    # Keyed by model as well as pk: the classified list holds soil amendments beside chemical records, and the
    # two tables number their rows independently (review of back #471).
    classified = {(type(e), e.pk) for e in logged_applications(bundle, SODIUM_NITRATE)}
    found = [
        e
        for e in bundle.chemical
        if (getattr(e, "nitrogen_source", "") or "") == MINED_NITROGEN and (type(e), e.pk) not in classified
    ]
    return sorted(found, key=lambda e: (e.date is None, e.date))


def _mined_line(events) -> str:
    from certifications.services.osp_prefill import _date_span
    from certifications.services.restricted_materials import _names

    return (
        f"The records in Trazo show {len(events)} fertilizer application(s) whose nitrogen source is recorded as "
        f"mined or natural, restricted (the record form gives sodium nitrate as its example){_date_span(events)}: "
        f"{_names(events)}."
    )


def _bundle(osp, bundles: dict):
    from certifications.services.common_osp_records import EvidenceBundle

    if "bundle" not in bundles:
        bundles["bundle"] = EvidenceBundle(osp.establishment)
    return bundles["bundle"]


def canada_disagreement(osp, answers=None) -> str:
    """The sentence when "no crops may reach Canada" sits beside the Canada attestation, else ""."""
    answers = _answers(osp) if answers is None else answers
    if _value(answers, "canada_export_possible") is not False or not _shown("canada_export_possible", answers):
        return ""
    certificates = _value(answers, "export_certificate_types")
    if not isinstance(certificates, (list, tuple)) or "canada" not in certificates:
        return ""
    if not _shown("export_certificate_types", answers):
        return ""
    return (
        "G8.0 answers that no crops or products are expected to reach Canada, and names the Canada organic "
        "equivalence attestation among the certificates its destinations require. The two answers disagree."
    )


def sodium_nitrate_contradictions(osp, bundles: dict, answers=None) -> list[str]:
    """What the plan's list and the records show against "sodium nitrate is not used"."""
    from certifications.services.osp_prefill import _date_span
    from certifications.services.restricted_materials import (
        SODIUM_NITRATE,
        _names,
        logged_applications,
        plan_materials_of_class,
    )

    answers = _answers(osp) if answers is None else answers
    if _value(answers, "sodium_nitrate_used") is not False or not _shown("sodium_nitrate_used", answers):
        return []
    out = []
    matched, _omri_only = plan_materials_of_class(osp, SODIUM_NITRATE)
    if matched:
        names = ", ".join(f"{material.name} ({material.source})" for material, _how in matched)
        out.append(f"G8.0 answers that sodium nitrate is not used, and this plan's materials list holds {names}.")
    bundle = _bundle(osp, bundles)
    events = logged_applications(bundle, SODIUM_NITRATE)
    if events:
        out.append(
            f"G8.0 answers that sodium nitrate is not used, and the records in Trazo show {len(events)} "
            f"application(s) of products classified as sodium nitrate{_date_span(events)}: {_names(events)}."
        )
    mined = mined_nitrogen_records(bundle)
    if mined:
        out.append("G8.0 answers that sodium nitrate is not used. " + _mined_line(mined))
    return out


def trade_disagreements(osp) -> list[str]:
    """Every sentence the plan review lists under `international_trade_answers_disagree`."""
    answers = _answers(osp)
    out = []
    canada = canada_disagreement(osp, answers)
    if canada:
        out.append(canada)
    try:
        out += sodium_nitrate_contradictions(osp, {}, answers)
    except Exception:  # noqa: BLE001 (a comparison that cannot be made must not sink the review)
        logger.exception("Sodium nitrate answer could not be read against the list and records")
        out.append("The sodium nitrate answer could not be read against the materials list and the records.")
    return out


def answer_lines(osp, question_key, value, bundles: dict) -> list[str]:
    """[REVIEW] lines printed under one G8.0 page C answer in its module PDF.

    The sodium nitrate rule, the plan's list and the classified records print from `restricted_materials`
    (the same reader as G4.0's restricted materials); these are the lines only this page has."""
    if question_key == "canada_export_possible":
        sentence = canada_disagreement(osp)
        return [f"[REVIEW] {sentence}"] if sentence else []
    if question_key != "sodium_nitrate_used":
        return []
    answers = _answers(osp)
    if value is True and _value(answers, "canada_export_possible") is True:
        return [
            "[REVIEW] The plan states sodium nitrate is used and that crops or products may reach Canada, which "
            "does not accept as organic the crops produced with it. How the two are kept apart is answered "
            "below."
        ]
    if value is False:
        try:
            mined = mined_nitrogen_records(_bundle(osp, bundles))
        except Exception:  # noqa: BLE001 (a reading that fails must not sink the packet)
            logger.exception("Mined nitrogen records could not be read")
            return ["In Trazo: the fertilizer records for this answer could not be read."]
        if mined:
            return ["[REVIEW] " + _mined_line(mined)]
    return []
