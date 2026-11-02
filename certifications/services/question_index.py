"""06-question-index.pdf: the packet seen in the agent's order (OSP alignment T24, Phase 5 slice 4).

For the packet's certifying agent: every registered form in the order the agent publishes them, and
every row in the form's official order, with every place in this packet where it is answered and
every part still open, together. A row answered for two parcels and open for a third lists all three.

WHAT AN ENTRY SAYS
------------------
Where an answer is printed (file, page, section, question label), or that a part is open and why.
Never that a question is satisfied, accepted or compliant: that is the agent's determination.

WHERE LOCATIONS COME FROM
-------------------------
* Module PDFs and parcel pages: the page each answered question's LABEL was drawn on, recorded by
  the label itself (`packet_index_recorder`), so a page break cannot separate the two.
* Generated documents (00-05) and workbooks the register routes a form to: the pages whose text
  names the form, read back from the built bytes.
* Filed documents (02 and the annual-update revisions): the same read-back on the filed bytes,
  marked "located in the filed document".
* Attachments: the ZIP path the packet writes for the requirement.
* A row with no answering question: the register's own `prints` text, labelled as not checked.

Module files and headings keep Trazo's codes; this index is the only agent-ordered view.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, replace

#: Where `annual_update_filing.packet_revision_filename` puts each revision of the year.
REVISION_DIR = "annual-update/"
STATED_BY_REGISTER = "location stated by the register, not checked against answers"
FILED_NOTE = "located in the filed document"
NO_REGISTER = (
    "Trazo does not hold this certifying agent's form list, so this index maps no form questions to "
    "pages. Document 04 lists what the packet contains, and each module PDF names the questions it has "
    "not answered yet."
)
DISCLAIMER = (
    "This index says where an answer is printed in this packet, or that it is still open. No entry "
    "says that a question is satisfied, accepted or compliant: every determination is the certifying "
    "agent's. Module files and headings keep Trazo's own codes; this page follows the form order below."
)


@dataclass(frozen=True)
class Location:
    file: str
    page: int | None = None
    section: str = ""
    label: str = ""
    parcel: str = ""
    note: str = ""
    #: "answer": the question's own label, drawn on that page. "heading": a heading the register cites
    #: for the row, found on that page by reading the document back.
    kind: str = "answer"

    def text(self) -> str:
        bits = [self.file + (f", p. {self.page}" if self.page else "")]
        if self.section:
            bits.append(self.section)
        if self.label:
            bits.append(f'"{self.label}"')
        out = ", ".join(bits)
        if self.parcel:
            out = f"{self.parcel}: {out}"
        if self.note:
            out += f" ({self.note})"
        return out


@dataclass(frozen=True)
class OpenPart:
    state: str
    detail: str = ""
    parcel: str = ""
    question: str = ""
    #: For a part that does not apply: the labels of the hidden questions, so the line says WHICH
    #: question does not apply. Without them a row read "Answered at ..." and then "does not apply"
    #: under the same item, as if the item itself did not apply (e2e run 2026-10-28, WSDA J1).
    subjects: tuple = ()


@dataclass
class IndexRow:
    ref: str
    asks: str
    state: str
    optional: bool = False
    locations: list = field(default_factory=list)
    open_parts: list = field(default_factory=list)
    register_prints: str = ""


@dataclass
class IndexForm:
    label: str
    document_id: str
    locations: list = field(default_factory=list)
    rows: list = field(default_factory=list)


@dataclass
class QuestionIndex:
    agent: str
    has_register: bool
    forms: list = field(default_factory=list)


# --- reading documents back -------------------------------------------------------------------


def _norm(text) -> str:
    return " ".join((text or "").split()).lower()


def page_texts(data: bytes) -> list:
    """Each page's text, normalised, in page order."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer

    out = []
    for layout in extract_pages(io.BytesIO(data)):
        chunks = [element.get_text() for element in layout if isinstance(element, LTTextContainer)]
        out.append(_norm(" ".join(chunks)))
    return out


def _needles(form) -> list:
    out = []
    for text in (getattr(form, "label", ""), getattr(form, "title", ""), getattr(form, "document_id", "")):
        text = _norm(text)
        if text and text not in out and len(text) >= 3:
            out.append(text)
    return out


def _pages_naming(texts, needles) -> list:
    pages = []
    for number, text in enumerate(texts, start=1):
        if any(re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", text) for n in needles):
            pages.append(number)
    return pages


def _form_document_locations(form, recorder, texts_cache) -> list:
    """Where the generated, filed and workbook documents the register routes this form to name it."""
    out = []
    needles = _needles(form)
    for path in getattr(form, "packet_documents", ()) or ():
        if path.startswith("workbooks/"):
            data = recorder.documents.get(path)
            sheets = _sheet_names(data) if data else []
            out.append(Location(path, section=("sheet " + ", ".join(sheets)) if sheets else ""))
            continue
        targets = [path]
        if path == "02-annual-update.pdf":
            targets += sorted(p for p in recorder.documents if p.startswith(REVISION_DIR))
        for target in targets:
            data = recorder.documents.get(target)
            if data is None:
                continue
            if target not in texts_cache:
                texts_cache[target] = page_texts(data)
            filed = target in recorder.filed
            pages = _pages_naming(texts_cache[target], needles)
            if not pages:
                out.append(
                    Location(target, note=("filed document; " if filed else "") + "its text does not name this form")
                )
            for page in pages:
                out.append(Location(target, page=page, note=FILED_NOTE if filed else ""))
    return out


_QUOTED = re.compile(r"\"([^\"]+)\"|'([^']+)'")
_PATH = re.compile(r"(?<![\w/])((?:annual-update/)?[0-9]{2}s?-[a-z0-9-]+\.pdf)")


def _cited_headings(prints: str) -> list:
    """[(packet file, heading)] for each document the register's `prints` cites with a quoted
    heading. The quoted text is cut at a placeholder (<...>) or an ellipsis: only literal text is
    searched for."""
    out = []
    for segment in re.split(r";", prints or ""):
        path = _PATH.search(segment)
        if not path:
            continue
        for match in _QUOTED.finditer(segment):
            heading = re.split(r"<|\u2026|\.\.\.", match.group(1) or match.group(2))[0].strip(" :;,")
            if len(heading) >= 6:
                out.append((path.group(1), heading))
    return out


def _heading_locations(prints, recorder, texts_cache) -> list:
    """Where each heading the register cites for a row is, read back from the built or filed bytes.
    02 includes every filed revision of the year, each marked as the filed document."""
    out = []
    for path, heading in _cited_headings(prints):
        targets = [path]
        if path == "02-annual-update.pdf":
            targets += sorted(p for p in recorder.documents if p.startswith(REVISION_DIR))
        needle = _norm(heading)
        for target in targets:
            data = recorder.documents.get(target)
            if data is None:
                continue
            if target not in texts_cache:
                texts_cache[target] = page_texts(data)
            for number, text in enumerate(texts_cache[target], start=1):
                if needle in text:
                    out.append(
                        Location(
                            target,
                            page=number,
                            section=heading,
                            note=FILED_NOTE if target in recorder.filed else "",
                            kind="heading",
                        )
                    )
    return out


def _sheet_names(data: bytes) -> list:
    from openpyxl import load_workbook

    try:
        return list(load_workbook(io.BytesIO(data), read_only=True).sheetnames)
    except Exception:  # noqa: BLE001 - an unreadable workbook still has a file location
        return []


# --- form order -------------------------------------------------------------------------------


def agent_form_order(certifier: str, forms) -> list:
    """The forms in the order the agent publishes them (`published_inventory.yaml`); forms the
    inventory does not list follow, by label."""
    from certifications.services.certifier_register import load_published_inventory

    order = {f.document_id: i for i, f in enumerate(load_published_inventory(certifier))}
    # Sections of one document (WSDA AGR 2121 A-S) share its id: the umbrella form, which has no
    # section code, comes first, then the sections (run 6, R6-04).
    return sorted(forms, key=lambda f: (order.get(f.document_id, len(order)), bool(getattr(f, "code", "")), f.label))


def order_source(certifier: str) -> str:
    """Where the form order comes from, as the register records it."""
    import yaml

    from certifications.services.certifier_register import published_inventory_path

    try:
        meta = yaml.safe_load(published_inventory_path(certifier).read_text()) or {}
    except (OSError, yaml.YAMLError):
        return ""
    source, retrieved = meta.get("source") or "", meta.get("retrieved") or ""
    if not source:
        return ""
    return f"the agent's forms list at {source}" + (f", as retrieved {retrieved}" if retrieved else "")


# --- the index --------------------------------------------------------------------------------


def _short(text, limit=140) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _question_locations(question_key, parcel, recorder, manifest) -> list:
    module_key, _, qkey = question_key.partition(".")
    out = []
    for loc in recorder.where(module_key, qkey):
        if parcel and not loc.file.startswith("parcels/"):
            continue
        if parcel and recorder.parcel_files.get(loc.file) != parcel:
            continue
        out.append(Location(loc.file, page=loc.page, section=loc.section, label=loc.label, parcel=parcel))
    if not out:
        # A changed-sections packet leaves an unchanged module out, so its labels were never drawn.
        # The answer exists, in a file this packet does not carry: say where, and that it is absent,
        # rather than leave the row reading as if nothing answered it.
        from certifications.services.packet_scope import current_scope

        scope = current_scope()
        for module in scope.omitted if scope.changed_only else ():
            if module.key == module_key:
                out.append(Location(module.path, label=_question_label(question_key), note=scope.omitted_note()))
    if manifest is not None:
        # A per-parcel upload (the parcel's map) prints no label of its own; the file IS the answer,
        # so it is cited under that parcel's name, never left as a row with no parcel.
        for entry in manifest.for_requirement(question_key):
            if not getattr(entry, "zip_path", "") or getattr(entry, "state", "") != "attached":
                continue
            if parcel and getattr(entry, "parcel", "") != parcel:
                continue
            out.append(Location(entry.zip_path, section="attachment", parcel=parcel))
    return out


def _question_label(question_key) -> str:
    """The English label of a cited question, as the module PDFs print it; the key if it has none."""
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
    from certifications.services.osp_module_pdf import _en

    module_key, _, key = question_key.partition(".")
    module = PARCEL_APPLICATION if module_key == PARCEL_APPLICATION.key else MODULES_BY_KEY.get(module_key)
    for page in getattr(module, "pages", ()) or ():
        for question in page.questions:
            if question.key == key:
                return _en(question.label) or key
    return key


def _trigger_words(question_key, detail) -> str:
    """ "treated_lumber = 'no'" as the reader sees it: the trigger question's label and its answer,
    formatted the way the module PDFs print that answer (option labels, Yes/No), never as stored keys."""
    import ast

    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
    from certifications.services.osp_module_pdf import _en, _format_answer_en

    modules = dict(MODULES_BY_KEY, **{PARCEL_APPLICATION.key: PARCEL_APPLICATION})
    module = modules.get(question_key.partition(".")[0])
    questions = {q.key: q for page in (getattr(module, "pages", ()) or ()) for q in page.questions}
    out = []
    for piece in (detail or "").split("; "):
        key, sep, raw = piece.partition(" = ")
        if not sep:
            out.append(piece)
            continue
        question = questions.get(key.strip())
        try:
            value = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            value = raw.strip("'\"")
        if question is None:
            out.append(f"{key.strip()} answered {value}")
            continue
        answer = _format_answer_en(question, value)
        out.append(f'"{_en(question.label)}" answered {answer}')
    return "; ".join(p for p in out if p)


def index_row(state, item, recorder, manifest, texts_cache) -> IndexRow:
    """One register row: every answered location and every other part, each with its parcel.

    A part that does not apply is kept and printed with the answer that decides it (run 6, R6-01):
    dropping it left the register's placeholder standing in for a decided question."""
    row = IndexRow(ref=state.ref, asks=_short(getattr(item, "asks", "")), state=state.state, optional=state.optional)
    if state.parts:
        for question_key, parcel, part_state, part_detail in state.parts:
            if part_state == "answered":
                row.locations.extend(_question_locations(question_key, parcel, recorder, manifest))
            elif part_state == "not_applicable":
                row.open_parts.append(
                    OpenPart(
                        part_state,
                        _trigger_words(question_key, part_detail),
                        parcel,
                        question_key,
                        subjects=(_question_label(question_key),),
                    )
                )
            else:
                row.open_parts.append(OpenPart(part_state, part_detail, parcel, question_key))
        if state.state == "partial":
            row.open_parts.append(OpenPart("partial"))
        # Two register questions decided by the same trigger print one line per parcel, not two
        # identical ones (run 6b polish).
        # Their hidden questions are all named on that one line.
        unique: dict = {}
        for part in row.open_parts:
            marker = (part.parcel, part.state, part.detail)
            kept = unique.get(marker)
            if kept is None:
                unique[marker] = part
            else:
                extra = tuple(s for s in part.subjects if s not in kept.subjects)
                unique[marker] = replace(kept, subjects=kept.subjects + extra)
        row.open_parts = list(unique.values())
    elif state.state != "answered":
        row.open_parts.append(OpenPart(state.state, state.detail))
    prints = " ".join(str(getattr(item, "prints", "") or "").split())
    if not row.locations and prints:
        row.locations.extend(_heading_locations(prints, recorder, texts_cache))
    # The register's own text stands in only when the packet gives nothing else for the row.
    if not (row.locations or row.open_parts) and prints and prints not in ("—", "-"):
        from certifications.services.packet_scope import mark_omitted

        row.register_prints = mark_omitted(prints)
    return row


def build_index(osp, recorder) -> QuestionIndex:
    from certifications.services.certifier_register import load_forms
    from certifications.services.packet_answers import form_answer_states
    from certifications.services.packet_attachments import current_manifest
    from certifications.services.packet_coverage import packet_agent, packet_certifier

    certifier, is_own = packet_certifier(osp)
    if not is_own:
        return QuestionIndex(agent=packet_agent(osp).name, has_register=False)
    forms = agent_form_order(certifier, load_forms(certifier))
    states = form_answer_states(osp, forms)
    manifest = current_manifest()
    texts_cache: dict = {}
    index = QuestionIndex(agent=certifier, has_register=True)
    for form in forms:
        entry = IndexForm(label=form.label, document_id=form.document_id)
        entry.locations = _form_document_locations(form, recorder, texts_cache)
        items = {item.ref: item for item in form.items}
        for state in states.get(id(form), []):
            entry.rows.append(index_row(state, items.get(state.ref), recorder, manifest, texts_cache))
        index.forms.append(entry)
    return index


# --- the PDF ----------------------------------------------------------------------------------

_STATE_WORDS = {
    "not_on_route": "not asked on this route",
    "not_applicable": "does not apply",
}


def _state_words(state) -> str:
    from certifications.services.osp_module_pdf import _OPEN_STATE_WORDING

    return dict(_OPEN_STATE_WORDING).get(state) or _STATE_WORDS.get(state) or state.replace("_", " ")


def index_pdf(osp, recorder) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    from certifications.services.osp_module_pdf import _escape, _styles

    index = build_index(osp, recorder)
    recorder.index = index
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="Question index")
    agent_label = {"ccof": "CCOF", "wsda": "WSDA", "otco": "Oregon Tilth"}.get(index.agent, index.agent)
    story = [
        Paragraph("Question index", styles["title"]),
        Paragraph(_escape(f"{osp.establishment.name} · OSP v{osp.version_number} · {agent_label}"), styles["subtitle"]),
    ]
    # The disclaimer speaks of entries and "the form order below"; a page with no register has
    # neither (production specimen packet, 2026-10-29).
    if index.has_register:
        story += [Paragraph(_escape(DISCLAIMER), styles["body"]), Spacer(1, 8)]
    if not index.has_register:
        story.append(Paragraph(_escape(NO_REGISTER), styles["body"]))
    else:
        source = order_source(index.agent)
        story.append(
            Paragraph(
                _escape(
                    "Forms are in Trazo's registered order"
                    + (f", taken from {source}" if source else "")
                    + "; rows follow each form's official order."
                ),
                styles["body"],
            )
        )
    # One outline entry per form: the index runs to 33 pages on the OTCO register and a reviewer
    # looking for C11 had to page through it (recordkeeping review F-17, 2026-10-07).
    from history.services.audit_export_service import OutlinedHeading

    for form in index.forms:
        story.append(OutlinedHeading(_escape(form.label), styles["header"], level=0))
        for loc in form.locations:
            # Named only when the document's text names the form; otherwise it is the document the
            # register relates the form to (run 6, R6-04).
            lead = "Form named in" if loc.page else "Related packet document"
            story.append(Paragraph(_escape(f"{lead}: {loc.text()}"), styles["body"]))
        for row in form.rows:
            head = f"{row.ref}: {row.asks}" + (" (optional)" if row.optional else "")
            story.append(Paragraph(f"<b>{_escape(head)}</b>", styles["body"]))
            for loc in row.locations:
                lead = "Answered at" if loc.kind == "answer" else "Cited heading found at"
                story.append(Paragraph(_escape(f"• {lead} {loc.text()}"), styles["body"]))
            for part in row.open_parts:
                who = f"{part.parcel}: " if part.parcel else ""
                detail = f" ({part.detail})" if part.detail else ""
                subjects = "; ".join(f'"{label}"' for label in part.subjects)
                subjects = f"{subjects}: " if subjects else ""
                story.append(Paragraph(_escape(f"• {who}{subjects}{_state_words(part.state)}{detail}"), styles["body"]))
            if row.register_prints:
                story.append(Paragraph(_escape(f"• {row.register_prints} ({STATED_BY_REGISTER})"), styles["body"]))
            if not (row.locations or row.open_parts or row.register_prints):
                story.append(Paragraph(_escape("• No location recorded in this packet."), styles["body"]))
    # The same specimen mark as every sibling document: this page cites every record by file and page.
    from common.specimen import is_specimen, specimen_page_callback

    spec = is_specimen(getattr(osp, "establishment", None))
    doc.build(
        story,
        onFirstPage=specimen_page_callback(letter, specimen=spec),
        onLaterPages=specimen_page_callback(letter, specimen=spec),
    )
    return buffer.getvalue()
