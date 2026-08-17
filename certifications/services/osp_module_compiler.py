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


def _format_answer_en(question, value) -> str:
    """Render an answer as the EN text the operator saw when selecting it."""
    if question.kind == "boolean":
        return "Yes" if value else "No"
    if question.kind in ("radio", "select"):
        return _option_labels_en(question).get(value, str(value))
    if question.kind == "checkbox_group":
        labels = _option_labels_en(question)
        if not isinstance(value, (list, tuple)):
            return str(value)
        return "; ".join(labels.get(v, str(v)) for v in value)
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

    return contributions


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
