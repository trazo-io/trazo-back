"""
Generate the human-readable conformance statement from the certifier registers.

The statement is generated and never hand-edited, so its counts cannot drift from the register the
way a hand-typed number does. `--check` re-generates into memory and compares, which is the CI
form: it fails when someone edits the register without regenerating, or edits the statement by hand.
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from certifications.services.certifier_register import (
    REGISTER_DIR,
    Form,
    ScopeEntry,
    blockers_by_root_cause,
    certifiers,
    load_forms,
    load_scope,
    load_unmapped,
    summarize,
)

OUTPUT_PATH = REGISTER_DIR / "CONFORMANCE.md"

STATUS_LABEL = {
    "covered": "Covered",
    "partial": "Partial",
    "not_covered": "Not covered",
    "out_of_scope": "Out of scope",
}
# Order matters: this is the order a reader should meet them in.
STATUS_ORDER = ("covered", "partial", "not_covered", "out_of_scope")
#: Rows that are not questions show their kind where a status would be, never a status.
KIND_LABEL = {"instruction": "Instruction (asks nothing)", "interpretation": "Trazo interpretation"}


def _cell(text: str | None) -> str:
    """Markdown table cells cannot contain a raw pipe or newline."""
    if not text:
        return "—"
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _questions_cell(item) -> str:
    bits = [f"`{q}`" for q in item.questions] + [f"`{m}`" for m in item.models]
    return " · ".join(bits) if bits else "—"


def _form_section(form: Form) -> list[str]:
    counts = {status: sum(1 for i in form.items if i.status == status) for status in STATUS_ORDER}
    tally = " · ".join(f"{STATUS_LABEL[s]} {counts[s]}" for s in STATUS_ORDER if counts[s])

    # 🔴 2026-09-06 — these two headings were hardcoded "CCOF" from when CCOF was the only
    # registered certifier, so every WSDA form in this document introduced WSDA's own questions
    # as CCOF's ("When CCOF requires it", "What CCOF asks" above AGR 2121-O). This document is
    # written for a certifying agent to read; attributing their form to their competitor is not
    # a typo. The Form already carries the certifier it was loaded from.
    agent = (form.certifier or "the certifier").upper()

    out = [
        f"### {form.label}",
        "",
        f"*{form.document_id} · {form.revision} · retrieved {form.retrieved}*  ",
        f"<{form.url}>",
        "",
    ]
    if form.guide_trigger:
        out += [f"**When {agent} requires it:** {form.guide_trigger}", ""]
    others = " · ".join(f"{KIND_LABEL[k]} {n}" for k in KIND_LABEL if (n := sum(1 for i in form.items if i.kind == k)))
    questions = sum(1 for i in form.items if i.kind == "question")
    out += [f"**{questions} questions** — {tally}" + (f" · not questions: {others}" if others else ""), ""]
    if form.register_status != "complete":
        out += ["> This form's register entry is a draft — treat absences as unreviewed, not as gaps.", ""]

    out += [
        f"| Ref | What {agent} asks | Status | Sev | Where it lives in Trazo | Note |",
        "|---|---|---|---|---|---|",
    ]
    for item in form.items:
        note = item.gap or item.reason or ""
        if item.fix and item.is_gap:
            note = f"{note} **Fix:** {item.fix}" if note else f"**Fix:** {item.fix}"
        out.append(
            "| {ref} | {asks} | {status} | {sev} | {where} | {note} |".format(
                ref=_cell(item.ref),
                asks=_cell(item.asks),
                status=KIND_LABEL.get(item.kind)
                or STATUS_LABEL[item.status] + (" (optional on the form)" if item.optional else ""),
                sev=item.severity or "—",
                where=_questions_cell(item),
                note=_cell(note),
            )
        )
    out.append("")
    return out


def render(forms: list[Form], scope: list[ScopeEntry]) -> str:
    # The totals describe the forms of operations Trazo serves. Forms that exist only for an
    # operation type Trazo has decided not to serve are counted apart, beside the totals, so no
    # total quietly includes them and none quietly drops them.
    unserved = [f for f in forms if not f.served]
    served = [f for f in forms if f.served]
    summary = summarize(served)
    by_status = summary["by_status"]
    by_sev = summary["by_severity"]

    lines = [
        "# Certifier conformance statement",
        "",
        "<!-- GENERATED FILE — do not edit.",
        "     Source: documentation/compliance/certifiers/<certifier>/forms/*.yaml",
        "     Regenerate: cd trazo-back && poetry run python manage.py certifier_conformance -->",
        "",
        "How Trazo lines up against each certifying agent's own Organic System Plan forms, "
        "question by question. Registered: " + ", ".join(c.upper() for c in certifiers()) + ".",
        "Generated from the conformance register, which is checked against the shipped OSP module",
        "registry by `certifications/tests/test_certifier_conformance_register.py` — a question that is",
        "renamed, removed or added without a decision fails that test rather than quietly making",
        "this document wrong.",
        "",
        "Statuses: **Covered** — the fact is capturable and reaches an artifact a certifier reads.",
        "**Partial** — captured but incomplete. **Not covered** — no home in the product today.",
        "**Out of scope** — deliberately not built, with the reason stated.",
        "",
        "Severity is about what a reviewer at that certifier does with it: **P0** the packet is bounced or",
        "asserts something untrue · **P1** a request for information · **P2** noticed, tolerated ·",
        "**P3** cosmetic.",
        "",
        "## Where we stand",
        "",
        f"| Forms registered | {summary['forms']} ({summary['complete_forms']} complete) |",
        "|---|---|",
        f"| Questions compared | {summary['by_kind']['question']} |",
        f"| Rows that are not questions (instructions, Trazo interpretations) | "
        f"{summary['by_kind']['instruction'] + summary['by_kind']['interpretation']} |",
        f"| Covered | {by_status['covered']} |",
        f"| Partial | {by_status['partial']} |",
        f"| Not covered | {by_status['not_covered']} |",
        f"| Out of scope (stated) | {by_status['out_of_scope']} |",
        f"| Blockers (P0) | {by_sev['P0']} |",
        f"| Request-for-information (P1) | {by_sev['P1']} |",
        f"| Minor (P2 / P3) | {by_sev['P2'] + by_sev['P3']} |",
        "",
    ]
    if unserved:
        apart = summarize(unserved)
        lines += [
            f"These totals cover the forms of operations Trazo serves. **{apart['forms']} more "
            f"form{'s' if apart['forms'] != 1 else ''} ({apart['by_kind']['question']} questions)** exist only for "
            "operation types Trazo has decided not to serve; they are counted under "
            "[Operation types Trazo does not serve](#operation-types-trazo-does-not-serve).",
            "",
        ]
    if summary["draft_forms"]:
        # Said in the same table as the totals, because a caveat that lives elsewhere is a
        # caveat nobody quoting the total will carry with it.
        # Singular matters: the count reached 1 on 2026-09-08, and "1 of these
        # 41 forms are draft" reads like a generator nobody proofreads — on the
        # one line a reader is meant to carry away with the totals.
        n = summary["draft_forms"]
        is_are = "is a draft register entry" if n == 1 else "are draft register entries"
        lines += [
            f"> ⚠️ **{n} of these {summary['forms']} forms {is_are}** "
            f"({summary['draft_items']} of {summary['items']} questions). A draft entry is "
            "outside the reverse-coverage check, and absences in it are unreviewed rather than "
            "established gaps — so the counts above describe "
            f"{summary['forms'] - n} fully reviewed forms and "
            f"{summary['items'] - summary['draft_items']} fully reviewed questions.",
            "",
        ]

    # Served forms only, like the headline count above it.
    grouped = blockers_by_root_cause(served)
    if grouped:
        rows = sum(len(v) for v in grouped.values())
        lines += [
            "## Blockers",
            "",
            f"{rows} blocker rows across **{len(grouped)} defects** — one defect usually breaks "
            "several questions across both certifiers, so the count that matters for planning is the"
            " defect count.",
            "",
        ]
        for cause, entries in grouped.items():
            where = ", ".join(f"{f.code or f.title} {i.ref}" for f, i in entries)
            lead = entries[0][1]
            lines += [
                f"**{cause.replace('-', ' ')}** — {where}",
                "",
                f"  {_cell(lead.gap)}",
                "",
                f"  *Fix: {_cell(lead.fix)}*",
                "",
            ]
            if len(entries) > 1:
                # Each row states the gap in its own form's terms; only the first is quoted here,
                # so say where the others are rather than letting this read as the whole story.
                lines += [
                    f"  Each of the {len(entries)} rows above states this in its own form's terms — "
                    "see the per-form tables below.",
                    "",
                ]

    lines += ["## By form", ""]
    for form in sorted(served, key=lambda f: (not f.required_of_every_grower, f.code or f.title)):
        lines += _form_section(form)

    if unserved:
        lines += [
            "## Operation types Trazo does not serve",
            "",
            "A business decision, dated, not a verdict on the questions: each question below keeps "
            "its own status, so the work is listed the day the decision changes.",
            "",
            "| Form | Why Trazo does not serve it | Decided | Questions |",
            "|---|---|---|---|",
        ]
        for form in sorted(unserved, key=lambda f: (f.certifier, f.code or f.title)):
            counts = summarize([form])
            tally = " · ".join(
                f"{STATUS_LABEL[st]} {counts['by_status'][st]}" for st in STATUS_ORDER if counts["by_status"][st]
            )
            lines.append(
                f"| {_cell(form.label)} | {_cell(form.not_served_basis)} | {form.not_served_decided} | {tally} |"
            )
        lines.append("")
        for form in sorted(unserved, key=lambda f: (f.certifier, f.code or f.title)):
            lines += _form_section(form)

    if scope:
        decisions = [e for e in scope if e.disposition == "decision"]
        gaps = [e for e in scope if e.disposition == "gap"]
        lines += [
            "## Forms Trazo does not register",
            "",
            "CCOF's Guide routes by activity, so what is absent is as readable as what is present.",
            "A **decision** is an answer; a **gap** is a debt, and names where it is triggered from.",
            "",
        ]
        if gaps:
            lines += ["### Gaps", "", "| Form | Triggered from | Why it matters |", "|---|---|---|"]
            for e in gaps:
                label = f"{e.form}" + (f" ({e.document_id})" if e.document_id else "")
                lines.append(f"| {_cell(label)} | {_cell(e.triggered_from)} | {_cell(e.reason)} |")
            lines.append("")
        if decisions:
            lines += ["### Deliberately not built", "", "| Form | Reason |", "|---|---|"]
            for e in decisions:
                label = f"{e.form}" + (f" ({e.document_id})" if e.document_id else "")
                lines.append(f"| {_cell(label)} | {_cell(e.reason)} |")
            lines.append("")

    # PER CERTIFIER, and for the same reason `test_no_question_is_both_cited_and_declared_unmapped`
    # is: "no CCOF form asks this" and "no WSDA form asks this" are different statements, and
    # merging them printed WSDA's declarations under a heading that named CCOF. The merged
    # `load_unmapped()` still exists for the guards, which want the flat set.
    lines += [
        "## What Trazo asks that the registered forms do not",
        "",
        "Not gaps — questions the federal Common OSP or the regulation itself asks for, which a",
        "certifier's own grower overlay leaves implicit. Stated per agent: a question one asks and",
        "the other does not is the most informative row here.",
        "",
    ]
    rendered_any = False
    for certifier in certifiers():
        per_agent = load_unmapped(certifier)
        if not per_agent:
            continue
        rendered_any = True
        agent = certifier.upper()
        lines += [
            f"### {agent}",
            "",
            f"| Question | Why it has no {agent} counterpart |",
            "|---|---|",
        ]
        for key, reason in sorted(per_agent.items()):
            lines.append(f"| `{key}` | {_cell(reason)} |")
        lines.append("")
    if not rendered_any:
        lines += ["*None recorded yet.*", ""]

    return "\n".join(lines)


class Command(BaseCommand):
    help = "Generate documentation/compliance/certifiers/CONFORMANCE.md from the certifier registers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="Do not write; exit non-zero if the committed statement is stale.",
        )
        parser.add_argument("--output", default=str(OUTPUT_PATH), help="Where to write the statement.")

    def handle(self, *args, **options):
        forms = load_forms()
        scope = load_scope()
        rendered = render(forms, scope)
        path = Path(options["output"])

        if options["check"]:
            current = path.read_text() if path.exists() else ""
            if current != rendered:
                self.stderr.write(
                    self.style.ERROR(f"{path.name} is stale. Run: poetry run python manage.py certifier_conformance")
                )
                raise SystemExit(1)
            self.stdout.write(self.style.SUCCESS(f"{path.name} is up to date."))
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered)
        summary = summarize([f for f in forms if f.served])
        apart = sum(1 for f in forms if not f.served)
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {path} — {summary['forms']} served form(s), {summary['by_kind']['question']} question(s), "
                f"{summary['by_severity']['P0']} blocker(s); {apart} form(s) for operations not served."
            )
        )
