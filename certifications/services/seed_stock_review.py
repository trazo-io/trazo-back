"""Seed and planting-stock answers read against each other and against the plan's materials list.

The fact "what planting stock does this operation use, organic or not" is asked twice: G3.0 page A
`planting_stock_used` covers all planting stock (§ 205.2), and G3.0b `stock_organic_status` the perennial
stock established this plan period. CCOF G3.0 A3, OTCO C3 3.1-3 and WSDA AGR 2121 C2/C3 are each answered
by the pair, and nothing bound the two, so a mature orchard could answer "established perennials only" on
one page and "all nonorganic" on the other with no word on either. G3.0's `other_planting_stock_used`
(OTCO C3 3.1-4) is a part of the first answer and is read against it the same way.

Containment, not equality: G3.0 covers more than G3.0b (annual vegetative stock too), so G3.0 may name
a status G3.0b does not. What cannot hold is G3.0b naming a status G3.0 leaves out, or G3.0b describing
stock established this period while G3.0 says none was used or none was planted.

The listing statements: three answers say a material is not on the OSP inputs list yet (seed treatments,
treatments of nonorganic planting stock, grafting materials). Each prints its [REVIEW] line on the module
page and is listed on the plan review, so the operator sees it before filing. A "listed" answer the
records contradict is the attestation gate's (`attestation_gates`), as for the Materials Application.

Lines say what the answers state. They never decide which answer is right.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: G3.0b's status, and the G3.0 statuses it needs to be inside.
_STATUS_NEEDS = {
    "all_organic": {"organic"},
    "mixed": {"organic", "non_organic"},
    "all_nonorganic": {"non_organic"},
}
_STATUSES = {"organic", "non_organic"}
_NOTHING_PLANTED = {"none", "established_in_place"}


def _answers(osp, module_key) -> dict:
    """The module's answers; none when it is marked not applicable with an attestation."""
    from certifications.services.osp_module_pdf import _module_entry

    entry = _module_entry(osp, module_key)
    if entry.get("not_applicable") and entry.get("na_attestation"):
        return {}
    return entry.get("answers") or {}


def _value(answers, key):
    from certifications.osp_modules.conditions import answer_value

    return answer_value(answers, key)


def _listed(value) -> set:
    if value in (None, "", [], ()):
        return set()
    return set(value) if isinstance(value, (list, tuple)) else {value}


def _question(module_key, question_key):
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.services.packet_answers import _question_and_page

    module = MODULES_BY_KEY[module_key]
    page, question = _question_and_page(module, question_key)
    return module, page, question


def _said(module_key, question_key, values) -> str:
    """The chosen options' English labels, in the question's own order."""
    _module, _page, question = _question(module_key, question_key)
    labels = [o.label["en"] for o in question.options if o.value in values]
    return ", ".join(labels)


def _shown(module_key, question_key, answers) -> bool:
    from certifications.services.packet_answers import hidden_state

    module, page, question = _question(module_key, question_key)
    return hidden_state(module, page, question, answers) is None


def planting_stock_disagreements(osp) -> list[tuple[str, str]]:
    """(which G3.0 answer it concerns: "status" or "other", the sentence), one per disagreement."""
    seeds = _answers(osp, "g3_0_seeds")
    used = _listed(_value(seeds, "planting_stock_used"))
    if not used:
        return []
    out = []
    said = _said("g3_0_seeds", "planting_stock_used", used)
    status = _value(_answers(osp, "g3_2_planting_stock"), "stock_organic_status")
    if status in _STATUS_NEEDS:
        stated = _said("g3_2_planting_stock", "stock_organic_status", {status})
        if used & _NOTHING_PLANTED or _STATUS_NEEDS[status] - used:
            out.append(
                (
                    "status",
                    f'G3.0 answers planting stock "{said}", and G3.0b states the perennial planting stock '
                    f'established this plan period is "{stated}". The two answers disagree.',
                )
            )
    other = _listed(_value(seeds, "other_planting_stock_used")) & _STATUSES
    # Shown only while G3.0 names a status; a stored answer under a closed question is not read.
    if other and used & _STATUSES and other - used:
        out.append(
            (
                "other",
                f'G3.0 answers planting stock other than perennial nursery stock "'
                f'{_said("g3_0_seeds", "other_planting_stock_used", other)}", which its answer on all '
                f'planting stock ("{said}") does not include. The two answers disagree.',
            )
        )
    return out


def listing_gaps(osp) -> list[str]:
    """The plan's own statements that a material is not on the OSP inputs list yet."""
    out = []
    seeds = _answers(osp, "g3_0_seeds")
    if _value(seeds, "treatments_on_inputs_list") is False and _shown("g3_0_seeds", "treatments_on_inputs_list", seeds):
        out.append("G3.0 Seed treatments: not every seed treatment material is on the OSP inputs list yet")
    if _value(seeds, "grafts_stock") == "yes_not_listed" and _shown("g3_0_seeds", "grafts_stock", seeds):
        out.append("G3.0 Grafting: not every grafting material is on the OSP inputs list yet")
    stock = _answers(osp, "g3_2_planting_stock")
    if _value(stock, "stock_treatments") == "treated_not_listed" and _shown(
        "g3_2_planting_stock", "stock_treatments", stock
    ):
        out.append(
            "G3.0b Using nonorganic stock: not every treatment material on the nonorganic planting stock is on "
            "the OSP inputs list yet"
        )
    return out


def _unlisted_names_line(osp, question_key, bundles: dict) -> list[str]:
    """The treatments the records name for this statement that the materials list does not hold."""
    from certifications.services.common_osp_records import EvidenceBundle
    from certifications.services.osp_prefill import MATERIALS_CATEGORIES, materials_category, unlisted_category_products

    try:
        if "bundle" not in bundles:
            bundles["bundle"] = EvidenceBundle(osp.establishment)
        unlisted = unlisted_category_products(osp, bundles["bundle"], question_key)
    except Exception:  # noqa: BLE001 (a comparison that cannot be made must not sink the packet)
        logger.exception("Logged treatments could not be compared with the list for %s", question_key)
        return ["[REVIEW] The logged treatments could not be compared with the materials list."]
    if not unlisted:
        return []
    shown = unlisted[:12]
    named = ", ".join(shown) + (f", and {len(unlisted) - len(shown)} more" if len(unlisted) > len(shown) else "")
    label = MATERIALS_CATEGORIES[materials_category(question_key)][1]
    return [
        f"[REVIEW] The records name {len(unlisted)} {label} product(s) that this plan's materials list does not "
        f"hold by name, and that no current decision on the plan ties to a listed product: {named}."
    ]


def answer_lines(osp, module_key, question_key, value, bundles: dict) -> list[str]:
    """[REVIEW] lines printed under one G3.0 or G3.0b answer in its module PDF."""
    where = {
        ("g3_0_seeds", "planting_stock_used"): "status",
        ("g3_0_seeds", "other_planting_stock_used"): "other",
        ("g3_2_planting_stock", "stock_organic_status"): "status",
    }.get((module_key, question_key))
    if where:
        return [f"[REVIEW] {sentence}" for kind, sentence in planting_stock_disagreements(osp) if kind == where]
    if module_key == "g3_0_seeds" and question_key == "treatments_on_inputs_list" and value is False:
        # A "Yes" the records contradict carries its line from the Materials Application reader.
        return [
            "[REVIEW] The answer is No: not every seed treatment material is on this plan's materials list yet. "
            "§ 205.201(a)(2) asks the plan to list each substance used in organic production."
        ] + _unlisted_names_line(osp, question_key, bundles)
    if module_key == "g3_2_planting_stock" and question_key == "stock_treatments":
        if value in ("treated_listed", "treated_not_listed"):
            return _unlisted_names_line(osp, question_key, bundles)
    return []
