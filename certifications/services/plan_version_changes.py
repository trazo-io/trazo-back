"""
Which sections of the plan changed between two versions, read from the versions themselves.

Oregon Tilth's OSP Update Form Step 4 asks the operation to "list updated OSP sections and attach"
them. The § 205.406(a)(2) additions and deletions on the annual update cannot answer that: the
annual-update card stores them as the operator's free-text lines, so there is no section to read.
The two plan versions the update moved between can. `osp_fork.fork_plan` copies every answer, the
three catalogue lists and the operator's materials rows into the new version, so anything that
differs between them is a change the operator made to the new version.

What counts as a change:

  * a module's answers: the VALUE of each answer and the module's not-applicable election. Each
    stored answer also carries the time it was written (`at`), and re-saving the same value moves
    it, so comparing whole answer dicts would report a section the operator only re-saved.
    Status, completion stamps and definition version are bookkeeping and are not compared.
  * the materials list: the approved National List / OMRI / WSDA entries and the operator's own
    `PlanMaterialEntry` rows, compared by content. The rows are copied on fork, so their ids and
    `created_by` always differ and say nothing about the plan.

  * the § 205.201(a) sections: the operator's own narrative and which record types the
    operator confirmed (`changed_section_keys`). Both are edited without touching a module.

`section_differences` is all of the above per § 205.201(a) section, kept apart by kind. It is what
an "unchanged" attestation on the year's filing is checked against when it is signed or filed.

What it does not see: land. Parcels belong to the establishment, not to a plan version, so a
parcel added this year, or an existing parcel's crop history, buffers or map edited, is the same
in both versions' packets. `parcels_begun_since` is the separate, operator-stated reading of new
land; edits to an existing parcel are stated as not compared.

This is a comparison of stored answers. It does not review a change or judge whether one needs
the agent's approval.
"""

from __future__ import annotations

from datetime import date

#: The module whose content includes the catalogue lists and `PlanMaterialEntry` rows.
MATERIALS_MODULE_KEY = "materials_application"

#: `PlanMaterialEntry` fields that are the operator's statement about a material. `id`, `osp`,
#: `created_by` and timestamps change on every fork and are left out.
_MATERIAL_ENTRY_FIELDS = (
    "product_name",
    "manufacturer",
    "category",
    "reason_for_use",
    "status",
    "listing_basis",
    "omri_product_id",
    "wsda_material_id",
    "national_list_substance_id",
    "certifier_letter_reference",
    "notes",
    "agent_review",
    "agent_review_date",
    "agent_review_reference",
    "agent_review_agent",
    "agent_review_use",
    "label_document_id",
)


def _module_content(osp, key: str) -> tuple:
    """(not-applicable election, {question: value}) for one module, with write times removed."""
    module = ((osp.module_responses or {}).get("modules") or {}).get(key) or {}
    answers = {}
    for question, answer in (module.get("answers") or {}).items():
        value = answer.get("value") if isinstance(answer, dict) else answer
        # An answer cleared back to empty is the same plan as one never given.
        if value in (None, "", [], {}):
            continue
        answers[question] = value
    return bool(module.get("not_applicable")), answers


def _materials_content(osp) -> tuple:
    entries = sorted(
        tuple("" if value is None else str(value).strip() for value in row)
        for row in osp.plan_material_entries.values_list(*_MATERIAL_ENTRY_FIELDS)
    )
    return (
        sorted(osp.approved_national_list_substances.values_list("pk", flat=True)),
        sorted(osp.approved_omri_products.values_list("pk", flat=True)),
        sorted(osp.approved_wsda_materials.values_list("pk", flat=True)),
        entries,
    )


def changed_module_keys(prior, new) -> list[str]:
    """Keys of the modules whose content differs between `prior` and `new`, in packet order."""
    from certifications.osp_modules import MODULE_REGISTRY

    materials_changed = _materials_content(prior) != _materials_content(new)
    changed = []
    for module in MODULE_REGISTRY:
        if _module_content(prior, module.key) != _module_content(new, module.key) or (
            module.key == MATERIALS_MODULE_KEY and materials_changed
        ):
            changed.append(module.key)
    return changed


def _answer_changes_by_section(prior, new) -> dict[str, list]:
    """{§ 205.201(a) section key: [modules whose changed answers compile into it]}.

    Question by question, not module by module: G6.0 writes most of its answers into (a)(1) and its
    split-operation answers into (a)(5), and a changed tillage answer must not mark commingling as
    changed. A changed not-applicable election counts against the module's default section. (Until
    2026-11-11 this was `sections_whose_answers_changed`, which 02s alone read, with the materials
    list added as (a)(2); `section_differences` now holds both, with the other two kinds.)
    """
    from certifications.osp_modules import MODULE_REGISTRY

    changed: dict[str, list] = {}
    for module in MODULE_REGISTRY:
        before, after = _module_content(prior, module.key), _module_content(new, module.key)
        if before == after:
            continue
        sections: set[str] = set()
        for page in module.pages:
            for question in page.questions:
                if before[1].get(question.key) != after[1].get(question.key):
                    rule = question.compiles_to
                    sections.add(
                        (rule.section_key if rule and rule.section_key else None) or module.default_section_key
                    )
        if before[0] != after[0]:
            sections.add(module.default_section_key)
        for key in sections:
            changed.setdefault(key, []).append(module)
    return changed


#: What can differ in one § 205.201(a) section between two plan versions. Each is one of the
#: comparisons above; nothing here compares anything they do not.
DIFFERS_ANSWERS = "answers"  # a module answer, or a not-applicable election, compiled into it
DIFFERS_MATERIALS = "materials"  # the plan's materials list ((a)(2) only)
DIFFERS_NARRATIVE = "narrative"  # the operator's own narrative for the section
DIFFERS_RECORD_TYPES = "record_types"  # which record types the operator confirmed, and their labels


def stated_modules(filing) -> list:
    """The modules `filing` states changed against the plan on file with its agent, in registry order.

    Empty unless the operation holds no Trazo copy of that plan (`holds_no_agent_copy`): there the
    statement stands in for the comparison this module makes between two Trazo versions, and is never
    presented as one.
    """
    from certifications.osp_modules import MODULE_REGISTRY

    if filing is None or not filing.holds_no_agent_copy:
        return []
    keys = set(filing.agent_file_changed_modules or [])
    return [module for module in MODULE_REGISTRY if module.key in keys]


def stated_keys_not_in_registry(filing) -> list[str]:
    """Keys `filing` states changed that the module registry no longer knows, as stored.

    The serializer refuses an unknown key, so this is empty unless a module was renamed or retired
    after the statement was saved. Readers print these as stored: dropping them would turn a list of
    changes into what reads as the operation's "nothing changed" (review of back #439).
    """
    from certifications.osp_modules import MODULES_BY_KEY

    if filing is None or not filing.holds_no_agent_copy:
        return []
    return sorted({key for key in filing.agent_file_changed_modules or [] if key not in MODULES_BY_KEY})


def section_differences(prior, new) -> dict[str, dict]:
    """{section key: {"differs": [...], "modules": [Module, ...]}} for every § 205.201(a) section
    whose content differs between `prior` and `new`, in regulation order.

    The module answers compiled into each section (`_answer_changes_by_section`), the materials list
    for (a)(2), and `changed_section_keys`, kept apart by kind so a reader can be told what moved. Used where an "unchanged" attestation is checked against the
    plan versions before it is signed (overall review 2026-11, OV-PK-O01); the 02s supplement
    reads the same function, so the packet never names a difference the signing step let through
    or the other way round.
    """
    from certifications.models import OSP_SECTION_KEYS

    by_section = _answer_changes_by_section(prior, new)
    materials_changed = _materials_content(prior) != _materials_content(new)
    differences: dict[str, dict] = {}
    for key in OSP_SECTION_KEYS:
        differs = []
        if key in by_section:
            differs.append(DIFFERS_ANSWERS)
        if key == "inputs_list" and materials_changed:
            differs.append(DIFFERS_MATERIALS)
        narrative_before, records_before = _section_content(prior, key)
        narrative_after, records_after = _section_content(new, key)
        if narrative_before != narrative_after:
            differs.append(DIFFERS_NARRATIVE)
        if records_before != records_after:
            differs.append(DIFFERS_RECORD_TYPES)
        if differs:
            differences[key] = {"differs": differs, "modules": by_section.get(key, [])}
    return differences


def _section_content(osp, key: str) -> tuple:
    """(the operator's own narrative, {record type: label} confirmed) for one § 205.201(a) section.

    The generated narrative is left out: it is compiled from module answers, which
    `changed_module_keys` already compares. The manual narrative is PATCHed on its own, without
    any module answer moving (review of back #216). A bare legacy `narrative` is the operator's
    text, the compiler's own rule. Of the § 11 confirmations only what was confirmed, and under
    which label, is compared: the fork marks each one `carried_from_version` and a re-tick
    re-dates it, neither of which changes what the plan says.
    """
    from certifications.services.common_osp_records import CONFIRMATIONS_KEY

    section = (osp.sections or {}).get(key) or {}
    if not isinstance(section, dict):
        return "", {}
    manual = section.get("narrative_manual")
    if manual is None:
        manual = section.get("narrative") or ""
    confirmed = {
        record: (entry.get("label") or "")
        for record, entry in (section.get(CONFIRMATIONS_KEY) or {}).items()
        if isinstance(entry, dict) and entry.get("confirmed")
    }
    return manual.strip(), confirmed


def changed_section_keys(prior, new) -> list[str]:
    """§ 205.201(a) section keys whose operator-written content differs, in regulation order."""
    from certifications.models import OSP_SECTION_KEYS

    return [key for key in OSP_SECTION_KEYS if _section_content(prior, key) != _section_content(new, key)]


def plan_reference_date(osp) -> tuple[date | None, str]:
    """(the date a plan version counts from, how the plan states it): submitted, else effective."""
    if osp.submitted_at is not None:
        return osp.submitted_at.date(), "submitted"
    if osp.effective_date is not None:
        return osp.effective_date, "effective"
    return None, ""


def parcels_begun_since(establishment, since: date) -> tuple[list, list]:
    """(parcels whose stated management start is on or after `since`, parcels that state none).

    `date_began_managing` is the operator's own answer (the CCOF land-history affidavit date). A
    parcel without one is reported as not stated, never as not new.
    """
    parcels = list(establishment.parcels.order_by("name", "id"))
    begun = [p for p in parcels if p.date_began_managing is not None and p.date_began_managing >= since]
    unstated = [p for p in parcels if p.date_began_managing is None]
    return begun, unstated
