"""
Whether THIS plan answers each question on a certifying agent's form.

The conformance register says where Trazo would answer a form question (`questions:` on each
item). That is a mapping, not an answer. The coverage page used to list a form as "generated" the
moment a module mapped to it, without reading one answer, so an operation that had filled in
nothing received a page telling its certifier that every form was in the packet (OSP alignment
audit 2026-10, T15). This module reads the operator's answers for each register item and says
what the packet can honestly claim about it.

The states are evidence states, not a grade. They are never totalled into a ratio or a
percentage; the page names the questions that are still open.

    answered                   every cited question is answered, and the register row is `covered`
    not_applicable             the question is hidden, and every trigger that hides it is answered
                               (the evidence is kept), or the module carries a recorded N/A
                               attestation
    partial                    every cited question is answered, but the register row itself is
                               `partial`: Trazo collects only part of what the form asks
    not_collected              the register row is `not_covered`: Trazo has nowhere to record it
    unanswered                 a visible cited question has no answer
    unconfirmed                a visible cited question holds only an option that has since been
                               replaced, so the stored answer does not answer what is asked now
    unresolved                 a cited question is hidden only because a question that decides
                               whether it applies has not been answered, so nobody has said it
                               does not apply
    attachment_missing         the form asks for a file and none is uploaded to that section
    attachment_not_identified  files are uploaded to that section, but none is linked to THIS
                               requirement, and none of them rides in the packet
    attachment_unreadable      a file IS linked to this requirement, but its bytes could not be
                               read while the packet was built, so it is not in the ZIP
    attachment_held_outside_packet
                               a file is linked to this requirement and readable, but the packet's
                               size limit was reached; it is named, not attached

An attachment is `answered` only by a file linked to the requirement AND, inside a packet build,
actually written into the ZIP (`packet_attachments`). Outside a build (the OSP screen) a linked
file counts, because nothing is being shipped there.
    not_assessed               the register row names no answering question (models or printed
                               output only), so nothing here can say it is answered
    not_on_route               a parcel-form row the route of every parcel does not ask (a form not
                               filed for existing certified acreage, or rows the form itself skips);
                               closed, and listed apart on page 04 with the route's reason
    route_unresolved           a parcel-form row on a parcel whose route is not determined (its
                               certifying agent is not recognised or not named); open, never skipped
    unknown_reference          the register cites a question that does not exist today

Only `answered` and `not_applicable` close a row. Everything else is open.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Panels that are answered by records, not typed: each has a state of its own on the coverage page.
#: Folded away like any other panel, the supplier panel would leave CCOF G3.0 A2 answered by the
#: seedling description alone, with no certificate on file (supplier register in the plan, 2026-11).
EVIDENCED_EMBEDS = frozenset(
    {"seedling_suppliers", "brand_owners", "sourced_products", "equipment_inventory", "crop_table"}
)

#: Parcel panels answered by rows the operator typed, judged per parcel from the count `_Answers.parcels`
#: puts under the panel's key. A table with no row is unanswered: the forms ask for at least one crop.
PARCEL_EMBED_STATES = {
    "crop_table": lambda values: (
        ("answered", "") if values.get("crop_table") else ("unanswered", "no crop is listed for this parcel")
    ),
}

#: States that close a register row. Anything else is listed as open on the coverage page.
CLOSED_STATES = frozenset({"answered", "not_applicable", "not_on_route"})

#: Worst state wins when a row cites several questions (or one question across several parcels).
_SEVERITY = (
    "unknown_reference",
    "attachment_missing",
    "attachment_unreadable",
    "attachment_held_outside_packet",
    "attachment_not_identified",
    # Before "unresolved": a retired-only answer is usually WHY the questions it gates are
    # unresolved, so a row citing both names the cause, not the symptom.
    "unconfirmed",
    "unresolved",
    "route_unresolved",
    "unanswered",
    "not_assessed",
    "answered",
    "not_applicable",
    # Last: a row asked of any parcel takes that parcel's state; only when no parcel's route asks it
    # is the row not on route.
    "not_on_route",
)


@dataclass(frozen=True)
class RowState:
    ref: str
    state: str
    #: Evidence for the state: the trigger answers that make a question not apply, or the
    #: requirement an attachment is missing for. Plain text, safe to print.
    detail: str = ""
    #: The form prints the item as optional. Still evaluated and still listed when open, but
    #: apart from the required questions, so neither an unanswered optional item keeps a form
    #: from being answered nor does an answered form hide it.
    optional: bool = False
    #: Every judged part behind `state`, unfolded: (module.question, parcel name or "", state,
    #: detail). The question index (Phase 5 slice 4) names each location and each open part; every
    #: other reader keeps using the folded `state`.
    parts: tuple = ()

    @property
    def is_open(self) -> bool:
        return self.state not in CLOSED_STATES


def _worst(states: list[tuple[str, str]]) -> tuple[str, str]:
    """(state, detail) with the highest severity; ties keep the first detail."""
    order = {s: i for i, s in enumerate(_SEVERITY)}
    return min(states, key=lambda pair: order.get(pair[0], 0))


def _question_and_page(module, question_key):
    for page in module.pages:
        for question in page.questions:
            if question.key == question_key:
                return page, question
    return None, None


def _trigger_answered(module, question_key: str, answers: dict) -> bool:
    """Whether a condition's trigger holds a current answer (retired options do not count)."""
    from certifications.osp_modules.conditions import answer_value, effective_value, is_answered

    _page, trigger = _question_and_page(module, question_key)
    return is_answered(effective_value(trigger, answer_value(answers, question_key)))


#: Why an unanswered retired question, and anything under it, does not apply. Words, not "<question> =
#: <answer>" pieces: the question index prints a piece without " = " as written.
RETIRED_EVIDENCE = "this question was replaced by others that ask it in more detail"


def hidden_state(module, page, question, answers: dict, _depth: int = 0) -> tuple[str, str] | None:
    """None when the question shows; else ("not_applicable", evidence) or ("unresolved", triggers).

    The same rule as `conditions.visible_questions`, which is transitive: the question is hidden by a
    condition that FAILS, or by a condition whose trigger is itself hidden, whatever the trigger
    still holds. A failing condition whose trigger is answered is evidence the question does not
    apply. A trigger hidden because it does not apply passes its evidence down. A failing condition
    whose trigger is unanswered, or a trigger hidden only while something upstream is unanswered,
    decides nothing yet.
    """
    from certifications.osp_modules.conditions import answer_value, effective_value, evaluate, is_answered

    # A retired question is shown only while it still holds an answer (`Question.retired`, as
    # `conditions._visibility` has it). Unanswered, it does not apply: it was replaced by questions that
    # ask more, so a row citing both reads as answered once the new ones are (review of back #343).
    if getattr(question, "retired", False) and not is_answered(
        effective_value(question, answer_value(answers, question.key))
    ):
        # Words, not a "<question> = <answer>" piece: the question index prints it as written.
        return "not_applicable", RETIRED_EVIDENCE

    conditions = tuple(page.visible_when) + tuple(question.visible_when)
    # Each trigger's own state first. Conditions read only earlier questions (`validate_module`), so
    # the walk ends; the cap only guards a module that skipped validation.
    upstream = {}
    for c in conditions:
        if c.question in upstream:
            continue
        trigger_page, trigger = _question_and_page(module, c.question)
        if trigger is None or trigger is question or _depth > 50:
            upstream[c.question] = None
            continue
        upstream[c.question] = hidden_state(module, trigger_page, trigger, answers, _depth=_depth + 1)
    failing = [c for c in conditions if not evaluate(c, answers)]
    # Only a trigger that is SHOWN decides: a hidden one holds a stale answer, which says nothing about
    # this question (review of #277: an "other" box closed on the stale frequency left under a gate the
    # grower had since un-ticked). A trigger holding only a retired option has not been answered as it
    # is asked now, so it decides nothing either: the question stays open, never "does not apply".
    decided = [c for c in failing if upstream[c.question] is None and _trigger_answered(module, c.question, answers)]
    if decided:
        evidence = "; ".join(f"{c.question} = {answer_value(answers, c.question)!r}" for c in decided)
        return "not_applicable", evidence
    # A trigger that is itself hidden hides what it gates. When it does not apply, neither does this
    # question: the "other" box under a question the operation was never asked is not waiting on
    # anyone (2026-11-08: G6.5's transport "other" boxes read "unresolved" on a farm that buys nothing
    # in), and a stale answer left under a gate that now hides it applies to nothing (2026-11-03).
    for c in conditions:
        hidden = upstream[c.question]
        if hidden is not None and hidden[0] == "not_applicable":
            # The upstream evidence as it is: "<question> = <answer>" pieces, the one shape the question
            # index turns into words (review of #270: a wrapper printed a raw key and a stray quote).
            return "not_applicable", hidden[1]
    waiting = {c.question for c in failing} | {key for key, state in upstream.items() if state is not None}
    # The page's OR gate (`ModulePage.visible_when_any`, as `conditions._visibility` reads it): it passes
    # when one member passes on a shown trigger. When none does, the page does not apply only if EVERY
    # member is decided (its trigger shown and answered, or itself not applicable); otherwise it waits.
    any_group = tuple(getattr(page, "visible_when_any", ()))
    if any_group:
        member_state = {}
        for c in any_group:
            if c.question not in member_state:
                trigger_page, trigger = _question_and_page(module, c.question)
                member_state[c.question] = (
                    None
                    if trigger is None or trigger is question or _depth > 50
                    else hidden_state(module, trigger_page, trigger, answers, _depth=_depth + 1)
                )
        if not any(member_state[c.question] is None and evaluate(c, answers) for c in any_group):
            decided_any = all(
                (member_state[c.question] is None and _trigger_answered(module, c.question, answers))
                or (member_state[c.question] is not None and member_state[c.question][0] == "not_applicable")
                for c in any_group
            )
            # Decided against, the page cannot show whatever its other conditions hold.
            if decided_any:
                pieces = []
                for c in any_group:
                    state = member_state[c.question]
                    piece = state[1] if state is not None else f"{c.question} = {answer_value(answers, c.question)!r}"
                    if piece not in pieces:
                        pieces.append(piece)
                return "not_applicable", "; ".join(pieces)
            waiting |= {c.question for c in any_group}
    if waiting:
        return "unresolved", ", ".join(sorted(waiting))
    return None


def question_state(
    module,
    question_key: str,
    answers: dict,
    *,
    na_attested: bool,
    section_uploads: int,
    identified_uploads: int = 0,
    not_shipped: tuple[str, str] | None = None,
):
    """(state, detail) for one question of one module against one set of answers.

    `identified_uploads` counts files linked to THIS requirement (a parcel's own map); only those
    answer an attachment. `section_uploads` counts files linked to the section as a whole.
    """
    from certifications.osp_modules.conditions import answer_value, effective_value, is_answered

    page, question = _question_and_page(module, question_key)
    if question is None:
        return "unknown_reference", question_key
    if na_attested and module.allows_not_applicable:
        return "not_applicable", "the operation attested this section does not apply"
    if question.kind == "info":
        return "not_assessed", ""

    hidden = hidden_state(module, page, question, answers)
    if hidden is not None:
        return hidden

    if question.kind == "upload":
        label = question.label.get("en", question_key) if isinstance(question.label, dict) else str(question.label)
        if identified_uploads:
            return "answered", ""
        if not_shipped is not None:
            # Linked to this requirement, so not "missing"; but not in the ZIP either.
            return not_shipped
        return ("attachment_not_identified" if section_uploads else "attachment_missing"), label

    value = answer_value(answers, question_key)
    if is_answered(effective_value(question, value)):
        return "answered", ""
    if is_answered(value):
        # Only a retired option is stored: given before the question asked what it asks now.
        return "unconfirmed", ""
    return "unanswered", ""


class _Answers:
    """The operator's answers for one plan, read once per coverage page."""

    def __init__(self, osp):
        from certifications.osp_modules import MODULES_BY_KEY
        from certifications.osp_modules.parcel_application import PARCEL_APPLICATION

        self.osp = osp
        self.modules = dict(MODULES_BY_KEY)
        self.modules[PARCEL_APPLICATION.key] = PARCEL_APPLICATION
        self.parcel_key = PARCEL_APPLICATION.key
        self.responses = (osp.module_responses or {}).get("modules", {}) or {}
        self._uploads: dict[str, int] | None = None
        self._parcels: list | None = None

    def uploads(self, module_key: str) -> int:
        if self._uploads is None:
            from django.db.models import Count

            from documents.models import GeneratedDocument

            rows = (
                GeneratedDocument.objects.filter(establishment_id=self.osp.establishment_id, source="upload")
                .exclude(linked_section="")
                .values("linked_section")
                .annotate(n=Count("id"))
            )
            self._uploads = {row["linked_section"]: row["n"] for row in rows}
        return self._uploads.get(module_key, 0)

    def parcels(self) -> list:
        if self._parcels is None:
            from certifications.services.osp_module_pdf import parcel_map_documents
            from product.services.parcel_application_status import parcel_application_values

            parcels = self.osp.establishment.parcels.order_by("id")
            # A parcel map is uploaded against that parcel's map requirement
            # (linked_section=PARCEL_MAP_SECTION) and the packet carries it under parcels/maps/, so
            # it is the one upload here that is identified with its requirement.
            from certifications.services.certified_parcel_branch import assess_for_plan
            from certifications.services.packet_attachments import PARCEL_MAP_REQUIREMENT

            out = []
            for parcel in parcels:
                maps = len(parcel_map_documents(parcel))
                attached, not_shipped = self.attachment(PARCEL_MAP_REQUIREMENT, parcel_id=parcel.pk, linked=maps)
                # Run 3, R3-04: the parcel's route under THIS plan's agent, the same assessment its
                # pages print, so a row the route skips is never listed as still open.
                route = assess_for_plan(parcel, self.osp)
                values = parcel_application_values(parcel)
                # The planned-crop table is rows on a model, not an answer: its count rides in the values
                # under the embed's key so the per-parcel loop can judge it (`PARCEL_EMBED_STATES`).
                values["crop_table"] = parcel.planned_crops.count()
                out.append((parcel.name, values, maps, attached, not_shipped, route))
            self._parcels = out
        return self._parcels

    def row_off_route(self, document_id: str, ref: str) -> tuple[str, str] | None:
        """("not_on_route", reasons) when NO parcel's route asks this row of a parcel form, else None.

        Read before anything else about the row, so a row Trazo does not collect, or one that names no
        question, is not listed as open on a form the route does not file (run 3, R3-04).
        """
        from certifications.services.certified_parcel_branch import NOT_ON_ROUTE, form_on_route

        parcels = self.parcels()
        if not parcels:
            return None
        skipped: dict[str, list[str]] = {}
        for name, _values, _maps, _attached, _not_shipped, route in parcels:
            on_route, reason = form_on_route(route, document_id, ref)
            if on_route != NOT_ON_ROUTE:
                return None
            skipped.setdefault(reason, []).append(name)
        return "not_on_route", "; ".join(f"{', '.join(names)}: {reason}" for reason, names in skipped.items())

    def attachment(self, requirement: str, parcel_id=None, linked: int | None = None):
        """(files that answer `requirement`, the not-shipped state or None).

        Inside a packet build the manifest decides: only files written into the ZIP answer.
        Outside one, a file linked to the requirement does.
        """
        from certifications.services.packet_attachments import ATTACHED, UNREADABLE, current_manifest

        manifest = current_manifest()
        if manifest is None:
            if linked is None:
                from documents.models import GeneratedDocument

                linked = GeneratedDocument.objects.filter(
                    establishment_id=self.osp.establishment_id, requirement=requirement
                ).count()
            return linked, None
        entries = manifest.for_requirement(requirement, parcel_id=parcel_id)
        attached = sum(1 for e in entries if e.state == ATTACHED)
        if attached or not entries:
            return attached, None
        names = ", ".join(e.label for e in entries)
        if any(e.state == UNREADABLE for e in entries):
            return 0, ("attachment_unreadable", names)
        return 0, ("attachment_held_outside_packet", names)

    def value_of(self, cited_key: str):
        """(found, value) for a farm-wide module question; per-parcel questions are not read here."""
        from certifications.osp_modules.conditions import answer_value

        module_key, _, question_key = cited_key.partition(".")
        if module_key not in self.modules or module_key == self.parcel_key:
            return False, None
        entry = self.responses.get(module_key) or {}
        return True, answer_value(entry.get("answers") or {}, question_key)

    def is_info(self, cited_key: str) -> bool:
        """True for a cited panel, table or notice: shown to the operator, never answered."""
        module_key, _, question_key = cited_key.partition(".")
        module = self.modules.get(module_key)
        if module is None:
            return False
        _page, question = _question_and_page(module, question_key)
        return question is not None and question.kind == "info" and question.embed not in EVIDENCED_EMBEDS

    def sourced_product_state(self) -> tuple[str, str]:
        """(state, detail) for G6.5's sourcing panel: answered only when every sourcing supplier has its
        copy (a current certificate, or the Exempt Handler Affidavit and the operation it sources from)
        and, in a packet build, that copy is in the ZIP."""
        from certifications.services import sourced_products as sp
        from certifications.services.packet_attachments import ATTACHED, current_manifest

        rows = sp.sourcing_rows(self.osp.establishment)
        if not rows:
            return "attachment_missing", "no supplier of bought-in organic product is recorded"
        missing = [row["supplier"].name for row in rows if row["state"] != sp.ON_FILE]
        if missing:
            return "attachment_missing", "no current certificate or affidavit for " + ", ".join(missing)
        manifest = current_manifest()
        if manifest is not None:
            outside = []
            for row in rows:
                entries = manifest.for_source(sp.document_source(row["document"]))
                if not entries or entries[0].state != ATTACHED:
                    outside.append((row["supplier"].name, entries[0].state if entries else ""))
            if outside:
                state = (
                    "attachment_unreadable"
                    if any(s == "unreadable" for _n, s in outside)
                    else "attachment_held_outside_packet"
                )
                return state, ", ".join(name for name, _s in outside)
        return "answered", ""

    def equipment_state(self) -> tuple[str, str]:
        """(state, detail) for G6.0's equipment panel: answered only when the register lists equipment
        and every item says what the table asks of it (`production_equipment.item_state`)."""
        from certifications.services import production_equipment as pe

        rows = pe.equipment_rows(self.osp.establishment)
        if not rows:
            return "unanswered", "no equipment is recorded in the equipment register"
        open_items = [
            f"{row['item'].name} ({'; '.join(row['missing'])})" for row in rows if row["state"] != pe.COMPLETE
        ]
        if open_items:
            return "unanswered", "not stated for " + ", ".join(open_items)
        return "answered", ""

    def brand_owner_state(self) -> tuple[str, str]:
        """(state, detail) for G7.0's brand-owner panel: answered only when every brand owner has the
        copy it owes (certificate or agreement) and, in a packet build, that copy is in the ZIP."""
        from certifications.services import brand_owners as bo
        from certifications.services.packet_attachments import ATTACHED, current_manifest

        rows = bo.brand_owner_rows(self.osp.establishment)
        if not rows:
            return "attachment_missing", "no brand owner is recorded"
        missing = [row["owner"].name for row in rows if row["state"] != bo.ON_FILE]
        if missing:
            return "attachment_missing", "no current certificate or agreement copy for " + ", ".join(missing)
        manifest = current_manifest()
        if manifest is not None:
            outside = []
            for row in rows:
                entries = manifest.for_source(bo.document_source(row["document"]))
                if not entries or entries[0].state != ATTACHED:
                    outside.append((row["owner"].name, entries[0].state if entries else ""))
            if outside:
                state = (
                    "attachment_unreadable"
                    if any(s == "unreadable" for _n, s in outside)
                    else "attachment_held_outside_packet"
                )
                return state, ", ".join(name for name, _s in outside)
        return "answered", ""

    def seedling_supplier_state(self) -> tuple[str, str]:
        """(state, detail) for the G3.0a supplier panel: answered only when every supplier named on a
        transplant purchase has a copy that covers its purchases, and, inside a packet build, that
        copy is in the ZIP. Asked only of a plan that buys certified organic seedlings."""
        from certifications.services.packet_attachments import ATTACHED, current_manifest, supplier_certificate_source
        from history.services import supplier_certificates as sc

        found, used = self.value_of("g3_0_seeds.seedlings_used")
        buys = sc.buys_certified_seedlings(self.osp)
        rows = sc.seedling_suppliers(self.osp.establishment)
        owing = [row for row in rows if sc.needs_certificate(row, buys)]
        # The records decide before the typed answer can close the row: a transplant purchase
        # recorded as certified organic owes a copy whatever G3.0 says (review of back #265).
        if not owing:
            if not found or used in (None, "", []):
                return "unresolved", "g3_0_seeds.seedlings_used"
            if not buys:
                return "not_applicable", f"g3_0_seeds.seedlings_used = {used!r}"
            if not rows:
                return "attachment_missing", "no transplant purchase naming a supplier is recorded"
        manifest = current_manifest()
        missing, outside = [], []
        for row in owing:
            if row["status"] != sc.COVERING or row["not_covered"]:
                missing.append(row["name"])
                continue
            if manifest is not None:
                entries = manifest.for_source(supplier_certificate_source(row["certificate"]))
                if not entries or entries[0].state != ATTACHED:
                    outside.append(
                        (row["name"], entries[0].state if entries else "", entries[0].detail if entries else "")
                    )
        if missing:
            return "attachment_missing", "no certificate copy covers the purchases from " + ", ".join(missing)
        if outside:
            state = (
                "attachment_unreadable"
                if any(s == "unreadable" for _n, s, _d in outside)
                else ("attachment_held_outside_packet")
            )
            return state, ", ".join(name for name, _s, _d in outside)
        return "answered", ""

    def state_of(self, cited_key: str, document_id: str = "", ref: str = "") -> tuple[str, str]:
        state, detail, _parts = self.state_and_parts(cited_key, document_id, ref)
        return state, detail

    def state_and_parts(self, cited_key: str, document_id: str = "", ref: str = "") -> tuple[str, str, list]:
        """(folded state, detail, [(parcel name or "", state, detail)]). A farm-wide question has one
        part; a parcel question has one per parcel, so no parcel's result is lost in the fold."""
        module_key, _, question_key = cited_key.partition(".")
        module = self.modules.get(module_key)
        if module is None or not question_key:
            return "unknown_reference", cited_key, [("", "unknown_reference", cited_key)]
        if module_key == self.parcel_key:
            from certifications.services.certified_parcel_branch import (
                NOT_ON_ROUTE,
                ROUTE_UNRESOLVED,
                UNRESOLVED_REASON,
                form_on_route,
            )

            parcels = self.parcels()
            if not parcels:
                return "unanswered", "no parcel is recorded", [("", "unanswered", "no parcel is recorded")]
            states, skipped, unresolved, parts = [], {}, [], []
            for name, values, maps, attached, not_shipped, route in parcels:
                on_route, reason = form_on_route(route, document_id, ref)
                if on_route == NOT_ON_ROUTE:
                    skipped.setdefault(reason, []).append(name)
                    states.append(("not_on_route", ""))
                    parts.append((name, "not_on_route", reason))
                    continue
                if question_key in PARCEL_EMBED_STATES:
                    state = PARCEL_EMBED_STATES[question_key](values)
                else:
                    state = question_state(
                        module,
                        question_key,
                        values,
                        na_attested=False,
                        section_uploads=maps,
                        identified_uploads=attached if question_key == "map_upload" else 0,
                        not_shipped=not_shipped if question_key == "map_upload" else None,
                    )
                if on_route == ROUTE_UNRESOLVED and state[0] not in CLOSED_STATES:
                    unresolved.append(name)
                    state = ("route_unresolved", "")
                    parts.append((name, "route_unresolved", UNRESOLVED_REASON))
                else:
                    parts.append((name, state[0], state[1]))
                states.append(state)
            state, detail = _worst(states)
            if state == "not_on_route":
                detail = "; ".join(f"{', '.join(names)}: {reason}" for reason, names in skipped.items())
            elif state == "route_unresolved":
                detail = f"{', '.join(unresolved)}: {UNRESOLVED_REASON}"
            return state, detail, parts
        entry = self.responses.get(module_key) or {}
        # A module N/A closes its questions only with the attestation that says who made it.
        na_attested = bool(entry.get("not_applicable")) and bool(entry.get("na_attestation"))
        _page, question = _question_and_page(module, question_key)
        if question is not None and getattr(question, "attests_embed", None):
            # A Yes the gate would refuse today (an empty list, or a required record not
            # confirmed) was given to an earlier, narrower statement. It stays printed as given and
            # counts as unanswered here until the operator confirms it (OSP alignment audit T17-F1).
            from certifications.osp_modules.conditions import answer_value
            from certifications.services.attestation_gates import blocked_attestations

            answers = entry.get("answers") or {}
            if answer_value(answers, question_key) is True and blocked_attestations(
                module, {question_key: True}, self.osp
            ):
                detail = "the records list no longer supports this Yes"
                return "unconfirmed", detail, [("", "unconfirmed", detail)]
        if (
            question is not None
            and question.embed in EVIDENCED_EMBEDS
            and not (na_attested and module.allows_not_applicable)
        ):
            if question.embed in ("brand_owners", "sourced_products", "equipment_inventory"):
                # A gated page: hidden by an answered trigger it does not apply, hidden by an unanswered
                # one it is unresolved. Only a page that shows is judged on the register.
                hidden = hidden_state(module, _page, question, entry.get("answers") or {})
                if hidden is not None:
                    return hidden[0], hidden[1], [("", hidden[0], hidden[1])]
                state, detail = {
                    "brand_owners": self.brand_owner_state,
                    "sourced_products": self.sourced_product_state,
                    "equipment_inventory": self.equipment_state,
                }[question.embed]()
            else:
                state, detail = self.seedling_supplier_state()
            return state, detail, [("", state, detail)]
        identified, not_shipped = 0, None
        if question is not None and question.kind == "upload":
            identified, not_shipped = self.attachment(cited_key)
        state, detail = question_state(
            module,
            question_key,
            entry.get("answers") or {},
            na_attested=na_attested,
            section_uploads=self.uploads(module_key),
            identified_uploads=identified,
            not_shipped=not_shipped,
        )
        return state, detail, [("", state, detail)]


def _applies(answers: _Answers, item) -> tuple[str, str] | None:
    """None when the item applies; else ("not_applicable", evidence) or ("unresolved", triggers).

    The same rule a module question's visibility follows: only a failing condition decides, and it
    decides only when its trigger is answered. A requirement whose trigger nobody has answered has
    not been shown not to apply, so it stays open.
    """
    from certifications.osp_modules.conditions import evaluate
    from certifications.osp_modules.schema import Condition

    decided, undecided = [], []
    for key, op, value in item.applies_when:
        module_key, _, question_key = key.partition(".")
        found, stored = answers.value_of(key)
        module = answers.modules.get(module_key)
        # A trigger an answered gate above it hides: the requirement does not apply, for the same
        # reason the trigger is not asked (a farm with no equipment is never asked whether its
        # equipment is shared), and whatever the trigger still holds from before the gate closed
        # (2026-11-03: visibility is transitive). The chain-walk is `hidden_state`'s, as for a question.
        hidden = None
        if found and module is not None:
            page, trigger = _question_and_page(module, question_key)
            if trigger is not None:
                entry = answers.responses.get(module_key) or {}
                hidden = hidden_state(module, page, trigger, entry.get("answers") or {})
        if hidden is not None and hidden[0] == "not_applicable":
            # The upstream evidence as it is ("<question> = <answer>"), the one shape the question
            # index turns into words (review of #270).
            decided.append(hidden[1])
            continue
        if hidden is not None:
            # Hidden until something upstream is answered: not decided either way.
            undecided.append((key, stored))
            continue
        if found and evaluate(Condition(question_key, op, value), {question_key: stored}):
            continue
        current = found and module is not None and _trigger_answered(module, question_key, {question_key: stored})
        if current:
            decided.append(f"{key} = {stored!r}")
        else:
            undecided.append((key, stored))
    if decided:
        return "not_applicable", "; ".join(decided)
    if undecided:
        return "unresolved", ", ".join(sorted(key for key, _ in undecided))
    return None


def row_answer_state(answers: _Answers, item, document_id: str = "") -> RowState | None:
    """The state of one register item for this plan.

    None for a row that is not an official question (an instruction or a Trazo interpretation),
    and for an out-of-scope question: neither is something this plan answers.
    """
    if getattr(item, "kind", "question") != "question" or item.status == "out_of_scope":
        return None
    optional = bool(getattr(item, "optional", False))
    if document_id:
        off_route = answers.row_off_route(document_id, item.ref)
        if off_route is not None:
            return RowState(item.ref, off_route[0], off_route[1], optional=optional)
    if getattr(item, "applies_when", ()):
        decided = _applies(answers, item)
        if decided is not None:
            return RowState(item.ref, decided[0], decided[1], optional=optional)
    if item.status == "not_covered":
        return RowState(item.ref, "not_collected", optional=optional)
    if not item.questions:
        return RowState(item.ref, "not_assessed", optional=optional)
    # A panel, table or notice (kind `info`) has no answer of its own, so it is `not_assessed`
    # always. Folded beside real questions it kept the row open whatever the operator answered
    # (WSDA J13 citing the off-farm handler table, e2e run 2026-10-28). It decides the row only
    # when the row cites nothing else.
    cited = [key for key in item.questions if not answers.is_info(key)] or list(item.questions)
    folded, parts = [], []
    for key in cited:
        state, detail, key_parts = answers.state_and_parts(key, document_id, item.ref)
        folded.append((state, detail))
        parts.extend((key, parcel, part_state, part_detail) for parcel, part_state, part_detail in key_parts)
    state, detail = _worst(folded)
    if state == "answered" and item.status != "covered":
        return RowState(item.ref, "partial", optional=optional, parts=tuple(parts))
    return RowState(item.ref, state, detail, optional=optional, parts=tuple(parts))


def form_answer_states(osp, forms) -> dict:
    """{id(form): [RowState, ...]} for every form, in-scope rows only, in register order."""
    answers = _Answers(osp)
    out: dict = {}
    for form in forms:
        states = [row_answer_state(answers, item, getattr(form, "document_id", "") or "") for item in form.items]
        out[id(form)] = [s for s in states if s is not None]
    return out


def form_is_answered(states: list[RowState]) -> bool:
    """True only when at least one REQUIRED row was checked and every required row is closed.

    Optional items never decide it either way; the page lists the open ones beside the form.

    A form whose rows are all `not_assessed` or out of scope has been checked against nothing,
    and "answered" would be a claim with no evidence under it. `not_assessed` is an open state, so
    only the empty case needs its own line.
    """
    # A row no parcel's route asks is closed, but it answers nothing: a form that is all such rows is
    # not "answered" (run 3, R3-04).
    required = [s for s in states if not s.optional and s.state != "not_on_route"]
    if not required:
        # Only optional items were checked: nothing the agent requires has been answered here.
        return False
    return all(not s.is_open for s in required)
