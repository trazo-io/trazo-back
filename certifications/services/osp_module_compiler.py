"""
Module answers → the six § 205.201(a) narratives (WS-2.3).

## The envelope

Each `OrganicSystemPlan.sections[key]` grows two sub-fields while `narrative` keeps its
meaning for every existing consumer (submit gate, padding detector, `section_completion`,
snapshot PDF, annual-update attestation, dossier, registry-sync diff — none of them change):

    {
      "narrative":            narrative_generated + "\n\n" + narrative_manual (composed),
      "narrative_generated":  deterministic prose compiled from module answers,
      "narrative_manual":     the operator's own text (legacy narratives migrate here),
      "last_updated":         set when the composed narrative changes,
      "last_compiled_at":     stamp of the last compile run,
      "compiled_content_version": osp_modules.CONTENT_VERSION at that run,
    }

## Compilation rules (all load-bearing)

- **Template-fill, never generation.** Each answered question with a `CompileRule` renders
  one sentence: the rule's EN template with the answer interpolated as the option labels the
  operator actually selected. Deterministic, reproducible, no model anywhere near it.
- **Everything composed is an operator statement.** Only operator-written answers exist in
  `module_responses` (the PUT action is the single writer), so compiled prose never asserts
  anything the operator didn't. An N/A module compiles to exactly one line naming the
  attestation and its date.
- **Hidden branches never compile.** Answers are filtered through the same
  `visible_questions()` the wizard and the completion validator use — a stale answer left
  behind by a collapsed branch (farmer switched "non-organic seed" back to "none") must not
  leak a sentence about commercial availability into a certifier-bound narrative.
- **EN only.** Narratives are certifier-facing; every existing PDF renders EN. The wizard
  UI is bilingual; the compiled artifact is not.
- **Legacy normalization.** A section that still carries only a bare `narrative` (pre-WS-2.3
  shape) treats that text as `narrative_manual` — the operator wrote it, so it is manual by
  definition. Same rule for incoming PATCHes from older clients (`normalize_incoming_sections`).

§ 205.201(a) makes the producer the author of the plan. Compiled prose is the producer's own
answers restated; the manual field stays theirs to extend, and nothing here ever deletes or
rewrites manual text.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from certifications.osp_modules import CONTENT_VERSION, MODULE_REGISTRY
from certifications.osp_modules.conditions import answer_value, visible_questions

logger = logging.getLogger(__name__)

COMPOSE_SEPARATOR = "\n\n"


def _option_labels_en(question) -> dict:
    return {o.value: (o.label.get("en") or o.value) for o in question.options}


def _unrecognised_option(value) -> str:
    """Render a stored option value that is not in the question's option list.

    🔴 2026-08-20 — `str(value)` printed the raw slug straight into a certifier PDF:
    "buffer_areas_flagged; roadside_utility_registration" appeared in the § 205.201(a)
    narrative snapshot and the G6.0 module PDF. An inspector reads machine identifiers with no
    way to tell whether the operation claimed something or the software lost a label.

    An option value that no longer exists in the registry means the answer was written by an
    older content version, an importer, or a hand edit — and none of those entitle the document
    to assert what it means. Same rule as `_organic_basis_label` in the audit export: name the
    stored value, but do not dress it up as a label the operator chose.
    """
    text = str(value).strip()
    if not text:
        return ""
    return f'"{text}" (unrecognised option — not in the current form)'


def _format_answer_en(question, value) -> str:
    """Render an answer as the EN text the operator saw when selecting it."""
    if question.kind == "boolean":
        return "Yes" if value else "No"
    if question.kind in ("radio", "select"):
        return _option_labels_en(question).get(value, _unrecognised_option(value))
    if question.kind == "checkbox_group":
        labels = _option_labels_en(question)
        if not isinstance(value, (list, tuple)):
            return _unrecognised_option(value)
        return "; ".join(labels.get(v, _unrecognised_option(v)) for v in value)
    return str(value).strip()


def _module_heading_en(module) -> str:
    title = module.title.get("en") or module.key
    return f"[{module.code} {title}]" if module.code else f"[{title}]"


def _tidy_sentence(sentence: str) -> str:
    """Collapse the punctuation an interpolated free-text answer duplicates.

    Most compile templates end in a period so a one-word answer reads as a sentence
    ("Split operation: No."). A farmer writing prose ends their own sentence with a period
    too, so the two collide: "…not a rescue treatment.." — on a document a certifier reads.
    Rather than police punctuation in every template or trim answers on the way in (which
    would edit the operator's own words in storage), normalize once at render time.
    """
    sentence = sentence.rstrip()
    for terminator in (".", "!", "?"):
        # ".." → "." but "…" and "etc.." → "etc." as well; ellipsis is left alone.
        while sentence.endswith(terminator * 2):
            sentence = sentence[:-1]
    return sentence.replace("..\n", ".\n")


def compile_module_contributions(osp) -> dict:
    """{section_key: [paragraph, ...]} from the current module answers.

    Pure function of (module_responses, registry) — no writes.
    """
    contributions: dict = {}
    responses = (osp.module_responses or {}).get("modules", {})

    for module in MODULE_REGISTRY:
        entry = responses.get(module.key) or {}
        answers = entry.get("answers") or {}

        if entry.get("not_applicable"):
            att = entry.get("na_attestation") or {}
            date = (att.get("at") or "")[:10]
            when = f" on {date}" if date else ""
            line = f"{_module_heading_en(module)}\n" f"Not applicable — reviewed and attested by the operator{when}."
            contributions.setdefault(module.default_section_key, []).append(line)
            continue

        if not answers:
            continue

        # Sentences grouped by target section; only visible questions compile.
        by_section: dict = {}
        for _page, question in visible_questions(module, answers):
            rule = question.compiles_to
            if rule is None:
                continue
            value = answer_value(answers, question.key)
            if value is None or (isinstance(value, (str, list, tuple, dict)) and not value):
                continue
            sentence = _tidy_sentence(rule.template.format(answer=_format_answer_en(question, value)))
            target = rule.section_key or module.default_section_key
            by_section.setdefault(target, []).append(sentence)

        for section_key, sentences in by_section.items():
            paragraph = _module_heading_en(module) + "\n" + "\n".join(sentences)
            contributions.setdefault(section_key, []).append(paragraph)

    _append_materials_registry(osp, contributions)
    _append_post_harvest_facilities(osp, contributions)
    return contributions


def _append_materials_registry(osp, contributions: dict) -> None:
    """Name every approved input in the (a)(2) narrative.

    § 205.201(a)(2) wants "a description of the … substances to be used as production
    inputs", and the audit snapshot enforces it by checking each registry entry against
    the `inputs_list` narrative — REVIEW at 1-3 unreferenced, FAIL at 4+.

    🔴 2026-08-21 — nothing wrote those names. The Materials Application module is
    attestations plus a structured panel, and no question anywhere in the 19 modules is a
    free-text field for the substances, so a farm that had entered its whole materials list
    correctly still read "8 registry entries unreferenced" on the face of its own packet:
    the document listed the inputs in one table and reported them as undescribed two pages
    earlier. Found filling a real OSP.

    The list IS the description — product name, manufacturer, and the basis on which the
    material appears — so the compiler states it in the narrative rather than asking the
    operator to retype a list they already entered. Nothing here is invented: every line comes
    from an entry the operator put on the plan, and each says what backs it. Since 2026-08-28
    that includes operator-authored rows with NO catalog listing, which is why neither this
    paragraph nor any row may describe the list as "resolved" or "verified" as a whole.

    Reads through `plan_materials()` — the single reading of the plan's materials — rather than
    querying the registries here. Two readings is precisely the defect that produced four
    disagreeing materials lists in one packet.
    """
    # An unsaved OSP has no pk, and Django raises on any M2M access against one. This runs on
    # the packet/snapshot path, where the standing rule is that a cross-check never takes the
    # document down — an OSP with no primary key simply has no registry to state.
    if not getattr(osp, "pk", None):
        return

    from certifications.services.plan_materials import plan_materials

    lines = []
    for row in plan_materials(osp):
        # `display()` already carries the manufacturer, the catalog identifier or the operator's
        # listing basis, and the [REVIEW] qualifier on a § 205.602 prohibited row.
        lines.append(f"{row.display()} — {row.source}.")

    if not lines:
        return
    # ⛔ The lead-in may not claim more than the rows support. It used to read "Each was
    # resolved against OMRI, the WSDA Materials List or the National List" — true while the only
    # way onto the list was a catalog match, and FALSE the moment operator-entered rows shipped
    # (caught on review before release, 2026-08-28). Each row now states its own basis, so the
    # sentence introduces them instead of vouching for them.
    paragraph = (
        "[Input materials on this plan]\n"
        "The following substances are used or planned as production inputs on this "
        "operation. Each line states the basis on which it appears — a catalog listing "
        "resolved by Trazo, a certifier approval, or the operator's own entry with no "
        "third-party listing:\n" + "\n".join(lines)
    )
    contributions.setdefault("inputs_list", []).append(paragraph)


def _append_post_harvest_facilities(osp, contributions: dict) -> None:
    """Name every off-farm handler and storage facility in the (a)(5) narrative.

    § 205.201(a)(5) wants the practices and physical barriers preventing commingling and
    contact with prohibited substances, and once a crop leaves the operation the answer is
    partly "these are the people who have it, and this is their certification". CCOF asks for
    that as a table (G6.1 §C, G6.2 §A); WSDA gates whole sections on it (J13, K1, L1).

    The record already existed — `PostHarvestFacility` carries name, address, certifier,
    certificate number and dates — and nothing read it into the plan. Same shape as the
    materials registry above and the same reason: the operator entered these facts once, so
    the plan states them rather than asking for them again as prose.

    Only the gate's own answer decides whether off-farm handling happens; this paragraph
    reports the records on file either way, because a facility on file and a "no" on the gate
    is exactly the contradiction a reviewer needs to see.
    """
    if not getattr(osp, "pk", None) or not getattr(osp, "establishment_id", None):
        return

    lines = []
    for facility in osp.establishment.post_harvest_facilities.all():
        name = (facility.name or "").strip()
        if not name:
            continue
        where = ", ".join(x for x in (facility.city, facility.state) if x)
        cert = (facility.certification_number or "").strip()
        certifier = (facility.certifier_name or "").strip()
        current = facility.cert_is_current
        if not cert and not certifier:
            status = "no organic certificate on file"
        elif current is True:
            status = "organic certificate current"
        elif current is False:
            status = "organic certificate expired or older than 15 months"
        else:
            status = "organic certificate date not stated"
        detail = ", ".join(
            x
            for x in (
                facility.get_facility_type_display(),
                facility.get_role_display() if facility.role else "",
                where,
                " ".join(y for y in (certifier, f"#{cert}" if cert else "") if y),
            )
            if x
        )
        lines.append(f"{name} — {detail} ({status}).")

    if not lines:
        return
    # States the RECORDS, not a conclusion about them. An operation that answered "no, nobody
    # off this operation handles our crop" may still carry facility rows from an earlier season,
    # and a paragraph reading "this operation's crop is handled off the farm by…" would contradict
    # its own gate answer over the producer's name. The gate's answer is compiled separately, from
    # the operator's own words; this paragraph is the file.
    paragraph = (
        "[Off-farm handlers and storage facilities]\n"
        "The following off-farm handlers and storage facilities are on file for this "
        "operation, with each organic certificate stated as the record supports it:\n" + "\n".join(lines)
    )
    contributions.setdefault("commingling_barriers", []).append(paragraph)


def _split_section(section: dict) -> dict:
    """Ensure a section dict carries the envelope, normalizing the legacy shape.

    Legacy = bare {"narrative": X}: the operator wrote X by hand (nothing else ever
    wrote narratives before WS-2.3), so X becomes narrative_manual.
    """
    section = dict(section or {})
    if "narrative_manual" not in section:
        section["narrative_manual"] = (section.get("narrative") or "").strip()
    if "narrative_generated" not in section:
        section["narrative_generated"] = ""
    return section


def _compose(generated: str, manual: str) -> str:
    parts = [p for p in ((generated or "").strip(), (manual or "").strip()) if p]
    return COMPOSE_SEPARATOR.join(parts)


def compile_modules_to_sections(osp) -> bool:
    """Recompile every section's generated narrative and recompose.

    Mutates `osp.sections` in place; returns True when anything changed (caller saves).
    Idempotent: same answers → same sections.
    """
    from certifications.models import OSP_SECTION_KEYS

    contributions = compile_module_contributions(osp)
    now = timezone.now().isoformat()
    changed = False
    sections = dict(osp.sections or {})

    for key in OSP_SECTION_KEYS:
        section = _split_section(sections.get(key))
        generated = COMPOSE_SEPARATOR.join(contributions.get(key, []))
        composed = _compose(generated, section["narrative_manual"])

        if section.get("narrative_generated") != generated or section.get("narrative") != composed:
            changed = True
            section["narrative_generated"] = generated
            section["narrative"] = composed
            section["last_updated"] = now
        section["last_compiled_at"] = now
        section["compiled_content_version"] = CONTENT_VERSION
        sections[key] = section

    osp.sections = sections
    return changed


def normalize_incoming_sections(stored_sections: dict, incoming_sections: dict) -> dict:
    """Route a client PATCH of `sections` into the manual field.

    The section editor (and any older client) writes `narrative`. Whatever the client
    sends as narrative IS manual text by definition — generated content has exactly one
    author (this compiler) and is recomputed after save, so a client echoing back the
    composed narrative must not smuggle generated prose into the manual field.

    Rules per section key:
      - incoming carries narrative_manual → take it verbatim (new clients);
      - incoming narrative == stored composed narrative → client echoed what it read;
        keep the stored manual unchanged;
      - otherwise the client edited the text: strip the stored GENERATED prefix if the
        client kept it, and store the remainder as manual.

    Known edge, accepted deliberately: if a legacy client edits INSIDE the generated
    prefix itself, the prefix no longer matches and the whole edited text lands in
    manual — the next compile then prepends fresh generated prose above it, so the
    farmer sees their edited copy plus the canonical compiled block. That is the
    honest outcome (generated prose has one author; edits to it belong to the
    operator's own text), and it disappears once the WS-2.4 editor writes
    narrative_manual directly.
    """
    normalized = {}
    for key, incoming in (incoming_sections or {}).items():
        incoming = dict(incoming or {})
        stored = _split_section((stored_sections or {}).get(key))

        if "narrative_manual" in incoming:
            manual = (incoming.get("narrative_manual") or "").strip()
        else:
            text = (incoming.get("narrative") or "").strip()
            if text == (stored.get("narrative") or "").strip():
                manual = stored["narrative_manual"]
            else:
                generated = (stored.get("narrative_generated") or "").strip()
                if generated and text.startswith(generated):
                    text = text[len(generated) :].strip()
                manual = text

        section = dict(stored)
        section["narrative_manual"] = manual
        section["narrative"] = _compose(section.get("narrative_generated", ""), manual)
        if "last_updated" in incoming:
            section["last_updated"] = incoming["last_updated"]
        normalized[key] = section
    return normalized
