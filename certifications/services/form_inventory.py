"""
The official question inventory of each registered certifier form, derived from the form itself.

The conformance register (`certifier_register.py`) says what Trazo does about each question on an
agent's form. Until 2026-09-30 nothing checked that the register's rows ARE the form's questions:
the rows were transcribed by hand, and the OSP alignment audit (2026-10, T26/T27) found rows that
folded several numbered questions into one, refs the form never prints, optional sections with no
row at all, and one form transcribed from an edition the agent had already replaced.

An inventory is derived from the source file (PDF, DOCX, or a captured web form) by `extract_items`, then reviewed by
hand. Every hand change is an `override` with a reason, so what came from the document and what
came from a person stay apart. The committed file holds the source file's sha256: the register
form must name the same hash and revision, and its question rows must match the inventory's
question items one to one (`certifications/tests/test_form_inventory.py`).

    documentation/compliance/certifiers/<agent>/inventory/<form-file-stem>.yaml

    source:   {file, url, sha256, revision, retrieved}
    extracted_by: "extract_form_inventory <EXTRACTOR_VERSION>"
    overrides: [{op: add|remove|rename|set, ref, ..., reason}]
    items:    [{ref, text, kind: question|instruction, optional: bool}]   # extracted + overrides

The source binaries are not committed (agent copyright; see `sources/*/MANIFEST.md`).
`manage.py verify_form_inventory --sources <dir>` re-derives every inventory whose source file is
in <dir> and fails on any difference, so a re-fetched form that changed cannot pass unnoticed.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import yaml

from certifications.services.certifier_register import REGISTER_DIR

EXTRACTOR_VERSION = 1
ITEM_KINDS = ("question", "instruction")
OVERRIDE_OPS = ("add", "remove", "rename", "set")


@dataclass(frozen=True)
class InventoryItem:
    ref: str
    text: str
    kind: str = "question"
    optional: bool = False


@dataclass(frozen=True)
class Inventory:
    path: Path
    source_file: str
    sha256: str
    revision: str
    items: tuple[InventoryItem, ...]
    overrides: tuple[dict, ...] = ()
    #: False when the items are not extracted at all and come only from overrides. Used by an
    #: umbrella form (WSDA AGR 2121 as a whole) whose sections are registered as forms of their own:
    #: its own content is the running header, and extracting the whole document would list every
    #: section's questions a second time.
    extracted: bool = True


def inventory_dir(agent: str) -> Path:
    return REGISTER_DIR / agent / "inventory"


def inventory_path(form_path: Path) -> Path:
    """The inventory of a register form: same agent, same file stem."""
    return form_path.parent.parent / "inventory" / form_path.name


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

_OPTIONAL = re.compile(r"\boptional\b", re.I)


def _first_sentence(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _pdf_lines(path: Path) -> list[str]:
    out = subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True, text=True)
    return out.stdout.splitlines()


def _dedupe(items: list[InventoryItem]) -> list[InventoryItem]:
    """A ref the form prints twice (WSDA 2121-R "7a") keeps both, the second marked "(2)".

    The mark is a placeholder for a person to replace with an override that describes the item;
    it is never meant to survive review, and the register test refuses it.
    """
    seen: dict[str, int] = {}
    out = []
    for item in items:
        n = seen.get(item.ref, 0) + 1
        seen[item.ref] = n
        out.append(item if n == 1 else InventoryItem(f"{item.ref} ({n})", item.text, item.kind, item.optional))
    return out


# CCOF: sections "A. Title", questions "1)", sub-questions "a)" and "i)" under a lettered one.
_CCOF_SECTION = re.compile(r"^\s{0,6}([A-Z])\.\s+(\S.*)$")
_CCOF_NUMBER = re.compile(r"^\s{0,8}(\d{1,2})\)\s+(\S.*)$")
_CCOF_LETTER = re.compile(r"^\s{0,14}([a-z])\)\s+(\S.*)$")
_CCOF_ROMAN = re.compile(r"^\s{0,18}(i{1,3}|iv|v|vi)\)\s+(\S.*)$")


def extract_ccof(lines: list[str]) -> list[InventoryItem]:
    items: list[InventoryItem] = []
    section = ""
    section_optional = False
    section_has_items = False
    section_text = ""
    number = ""
    letter = ""

    def close_section():
        if section and not section_has_items:
            # A section with no numbered question is one item under its letter. Whether it asks
            # anything is a reading, so it is a question until an override says otherwise.
            items.append(InventoryItem(section, _first_sentence(section_text), "question", section_optional))

    for line in lines:
        m = _CCOF_SECTION.match(line)
        if m:
            close_section()
            section, section_text = m.group(1), m.group(2)
            section_optional = bool(_OPTIONAL.search(m.group(2)))
            section_has_items = False
            number = letter = ""
            continue
        m = _CCOF_NUMBER.match(line)
        if m and section:
            number, letter = m.group(1), ""
            section_has_items = True
            items.append(InventoryItem(f"{section}{number}", _first_sentence(m.group(2)), "question", section_optional))
            continue
        # "i)" after "h)" is a letter; anywhere else it is a roman sub-item of the current letter.
        m = _CCOF_ROMAN.match(line)
        if m and letter and not (m.group(1) == "i" and letter == "h"):
            items.append(
                InventoryItem(
                    f"{section}{number}{letter}({m.group(1)})",
                    _first_sentence(m.group(2)),
                    "question",
                    section_optional,
                )
            )
            continue
        m = _CCOF_LETTER.match(line)
        if m and section and number:
            letter = m.group(1)
            items.append(
                InventoryItem(f"{section}{number}{letter}", _first_sentence(m.group(2)), "question", section_optional)
            )
            continue
    close_section()
    return _dedupe(items)


# WSDA: questions "1.", sub-questions "1a.", optional space flagged by its own wording.
_WSDA_NUMBER = re.compile(r"^\s{0,8}(\d{1,2})\.\s+(\S.*)$")
_WSDA_LETTER = re.compile(r"^\s{0,16}(\d{1,2}[a-z])\.\s+(\S.*)$")


def extract_wsda(lines: list[str]) -> list[InventoryItem]:
    items: list[InventoryItem] = []
    for line in lines:
        m = _WSDA_LETTER.match(line) or _WSDA_NUMBER.match(line)
        if not m:
            continue
        text = m.group(2)
        items.append(InventoryItem(m.group(1), _first_sentence(text), "question", bool(_OPTIONAL.search(text))))
    return _dedupe(items)


# OTCO: Word auto-numbering, rebuilt from numbering.xml because the visible "1)" and "A." are not
# in the document text.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _roman(n: int) -> str:
    vals = ((10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"))
    out = ""
    for v, s in vals:
        while n >= v:
            out, n = out + s, n - v
    return out


def _fmt(n: int, num_fmt: str) -> str:
    if num_fmt == "upperLetter":
        return chr(64 + n)
    if num_fmt == "lowerLetter":
        return chr(96 + n)
    if num_fmt == "lowerRoman":
        return _roman(n)
    if num_fmt == "upperRoman":
        return _roman(n).upper()
    return str(n)


def docx_paragraphs(path: Path) -> list[tuple[str, str]]:
    """[(visible auto-number label or "", paragraph text)] in document order."""
    with zipfile.ZipFile(path) as z:
        doc = ElementTree.fromstring(z.read("word/document.xml"))
        try:
            numbering = ElementTree.fromstring(z.read("word/numbering.xml"))
        except KeyError:
            numbering = None

    abstract: dict[str, dict[int, tuple[str, str, int]]] = {}
    num_to_abstract: dict[str, str] = {}
    overrides: dict[tuple[str, int], int] = {}
    used_nums: set[tuple[str, int]] = set()
    if numbering is not None:
        for a in numbering.findall(f"{_W}abstractNum"):
            levels = {}
            for lvl in a.findall(f"{_W}lvl"):
                ilvl = int(lvl.get(f"{_W}ilvl"))
                fmt = lvl.find(f"{_W}numFmt")
                txt = lvl.find(f"{_W}lvlText")
                start = lvl.find(f"{_W}start")
                levels[ilvl] = (
                    fmt.get(f"{_W}val") if fmt is not None else "decimal",
                    txt.get(f"{_W}val") if txt is not None else "",
                    int(start.get(f"{_W}val")) if start is not None else 1,
                )
            abstract[a.get(f"{_W}abstractNumId")] = levels
        for n in numbering.findall(f"{_W}num"):
            ref = n.find(f"{_W}abstractNumId")
            num_to_abstract[n.get(f"{_W}numId")] = ref.get(f"{_W}val")
            # A list instance can restart a level ("startOverride"); Word then prints from that
            # number the first time the instance is used, instead of continuing the shared list.
            for override in n.findall(f"{_W}lvlOverride"):
                start = override.find(f"{_W}startOverride")
                if start is not None:
                    overrides[(n.get(f"{_W}numId"), int(override.get(f"{_W}ilvl")))] = int(start.get(f"{_W}val"))

    counters: dict[str, dict[int, int]] = {}
    out = []
    for p in doc.iter(f"{_W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{_W}t")).strip()
        label = ""
        num_pr = p.find(f"{_W}pPr/{_W}numPr")
        if num_pr is not None and num_pr.find(f"{_W}numId") is not None:
            num_id = num_pr.find(f"{_W}numId").get(f"{_W}val")
            ilvl_el = num_pr.find(f"{_W}ilvl")
            ilvl = int(ilvl_el.get(f"{_W}val")) if ilvl_el is not None else 0
            levels = abstract.get(num_to_abstract.get(num_id, ""), {})
            if ilvl in levels and levels[ilvl][0] not in ("bullet", "none"):
                c = counters.setdefault(num_to_abstract[num_id], {})
                if (num_id, ilvl) in overrides and (num_id, ilvl) not in used_nums:
                    c[ilvl] = overrides[(num_id, ilvl)] - 1
                used_nums.add((num_id, ilvl))
                c[ilvl] = c.get(ilvl, levels[ilvl][2] - 1) + 1
                for deeper in [k for k in c if k > ilvl]:
                    del c[deeper]
                label = levels[ilvl][1]
                for k, (fmt, _t, start) in levels.items():
                    label = label.replace(f"%{k + 1}", _fmt(c.get(k, start), fmt))
        if text or label:
            out.append((label, text))
    return out


_OTCO_SECTION = re.compile(r"^([A-Z])\.\s+([A-Z][A-Z &/,()'-]{2,}.*)$")
_TYPED_NUMBER = re.compile(r"^(\d{1,2})\)\s*(\S.*)$")
_TYPED_LOWER = re.compile(r"^([a-z])\)\s*(\S.*)$")
_TYPED_UPPER = re.compile(r"^([A-Z])\.\s+(\S.*)$")


def extract_otco(paragraphs: list[tuple[str, str]]) -> list[InventoryItem]:
    """OTCO forms: sections "A. TITLE", questions "1)", sub-items "A." or "a)" -> "D-1", "D-1A", "F-1a".

    Word auto-numbers some items and types others, so both are read. A sub-item lettered under a
    section with no numbered question ("I. … A. Affirmations") is "I-A".
    """
    items: list[InventoryItem] = []
    section = ""
    section_text = ""
    section_has_items = False
    number = ""

    def close_section():
        if section and not section_has_items:
            items.append(InventoryItem(section, _first_sentence(section_text), "question", False))

    def add(ref, text):
        items.append(InventoryItem(ref, _first_sentence(text), "question", bool(_OPTIONAL.search(text))))

    for label, text in paragraphs:
        if not label:
            m = _OTCO_SECTION.match(text)
            if m:
                close_section()
                section, section_text, section_has_items, number = m.group(1), m.group(2), False, ""
                continue
        if not section:
            continue
        core = label.strip()
        body = text
        if not core:
            for pattern in (_TYPED_NUMBER, _TYPED_LOWER, _TYPED_UPPER):
                m = pattern.match(text)
                if m:
                    core = m.group(1) + (")" if pattern is not _TYPED_UPPER else ".")
                    body = m.group(2)
                    break
        if not core:
            continue
        mark = core.strip("().")
        if mark.isdigit():
            number = mark
            section_has_items = True
            add(f"{section}-{number}", body)
        elif re.fullmatch(r"[A-Za-z]", mark):
            section_has_items = True
            add(f"{section}-{number}{mark}" if number else f"{section}-{mark}", body)
    close_section()
    return _dedupe(items)


_REVISION_PATTERNS = (
    # A captured web form prints no revision; its edition is the day it was captured, which the
    # capture writes into its first line (`capture_gravity_form`).
    re.compile(r"<!-- captured (\d{4}-\d{2}-\d{2}) from "),
    # CCOF footer: "NOPB06, V2, R5, 06/29/2026" or "NOPB40, V2, 12/31/2023"
    re.compile(r"NOPB\d+,\s*(V\d+(?:,\s*R\d+)?,\s*\d{1,2}/\d{1,2}/\d{4})"),
    # WSDA footer: "AGR 2121 (R 02/25)"
    re.compile(r"AGR \d{4} \((R \d{2}/\d{2})\)"),
    # OTCO footer: "rev. 2026/03/25", "Rev. 2024/09/20", "REV. 2023/09/14", "rev 2025/08/27"
    re.compile(r"\b[Rr][Ee][Vv]\.?\s*(\d{4}/\d{2}/\d{2})"),
)


def source_text(source: Path) -> str:
    source = Path(source)
    if source.suffix.lower() == ".html":
        return source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".docx":
        with zipfile.ZipFile(source) as z:
            parts = [n for n in z.namelist() if re.fullmatch(r"word/(document|footer\d*|header\d*)\.xml", n)]
            # Word splits one visible string across runs ("rev. " | "2024/06/0" | "5"), so tags are
            # removed without adding space; only paragraph ends become line breaks.
            return "\n".join(re.sub(r"<[^>]+>", "", z.read(n).decode("utf8").replace("</w:p>", "\n")) for n in parts)
    return "\n".join(_pdf_lines(source))


def extract_revision(source: Path) -> str:
    """The revision stamp the source prints, read from the document, never from the register."""
    text = source_text(source)
    for pattern in _REVISION_PATTERNS:
        found = pattern.findall(text)
        if found:
            return re.sub(r"\s+", " ", found[0]).strip()
    return ""


def same_revision(register_revision: str, source_revision: str) -> bool:
    """Whether the register's revision names the source's stamp ("rev." and spacing aside).

    The register may say more than the stamp (WSDA's umbrella names two section stamps), never less.
    """

    def norm(value: str) -> str:
        return re.sub(r"[^0-9a-z/]", "", re.sub(r"\brev\.?", "", value.lower()))

    return bool(source_revision) and norm(source_revision) in norm(register_revision)


_OTCO_SUBSECTION = re.compile(r"^(\d{1,2}\.\d{1,2})$")
_TYPED_SUBSECTION = re.compile(r"^(\d{1,2}\.\d{1,2})\s+([A-Z].*)$")


def extract_otco_numbered(paragraphs: list[tuple[str, str]], bare: bool = False) -> list[InventoryItem]:
    """OTCO crop forms C2-C12: subsections "7.2", questions "1)", sub-items "a)" -> "7.2-1", "7.2-1a".

    A subsection with no numbered question is one item under its own number.
    """
    items: list[InventoryItem] = []
    # `bare`: the form prints no subsection number at all (OTCO C6), so refs are the question
    # numbers alone ("1", "2a"), never an invented "6.1".
    section = "" if not bare else "-"
    section_text = ""
    section_has_items = False
    number = ""

    def close_section():
        if section and section != "-" and not section_has_items:
            items.append(InventoryItem(section, _first_sentence(section_text), "question", False))

    def add(ref, text):
        if ref.startswith("--"):
            ref = ref[2:]
        items.append(InventoryItem(ref, _first_sentence(text), "question", bool(_OPTIONAL.search(text))))

    for label, text in paragraphs:
        core, body = label.strip(), text
        m = _OTCO_SUBSECTION.match(core) or (None if core else _TYPED_SUBSECTION.match(text))
        if m:
            close_section()
            section = m.group(1)
            section_text = text if core else m.group(2)
            section_has_items, number = False, ""
            continue
        if not section:
            continue
        if not core:
            for pattern in (_TYPED_NUMBER, _TYPED_LOWER):
                t = pattern.match(text)
                if t:
                    core, body = t.group(1) + ")", t.group(2)
                    break
        if not core:
            continue
        mark = core.strip("().")
        if mark.isdigit():
            number = mark
            section_has_items = True
            add(f"{section}-{number}", body)
        elif re.fullmatch(r"[a-z]", mark):
            # A subsection may letter its items with no numbered question above them.
            section_has_items = True
            add(f"{section}-{number}{mark}" if number else f"{section}-{mark}", body)
    close_section()
    return _dedupe(items)


_SECTION_HEADING = re.compile(r"^(?:Section|Step|STEP|SECTION)\s+(\d{1,2})[.:]?\s*(.*)$")


def extract_otco_sections(paragraphs: list[tuple[str, str]]) -> list[InventoryItem]:
    """OTCO forms headed "Section 1." (OFPP, OSP Update): questions "1)" and "a)" -> "1-1", "1-1a"."""
    items: list[InventoryItem] = []
    section = ""
    number = ""
    for label, text in paragraphs:
        m = None if label.strip() else _SECTION_HEADING.match(text)
        if m:
            section, number = m.group(1), ""
            continue
        if not section:
            continue
        core, body = label.strip(), text
        if not core:
            for pattern in (_TYPED_NUMBER, _TYPED_LOWER):
                t = pattern.match(text)
                if t:
                    core, body = t.group(1) + ")", t.group(2)
                    break
        if not core:
            continue
        mark = core.strip("().")
        if mark.isdigit():
            number = mark
            items.append(
                InventoryItem(f"{section}-{number}", _first_sentence(body), "question", bool(_OPTIONAL.search(body)))
            )
        elif re.fullmatch(r"[a-z]", mark):
            ref = f"{section}-{number}{mark}" if number else f"{section}-{mark}"
            items.append(InventoryItem(ref, _first_sentence(body), "question", bool(_OPTIONAL.search(body))))
    return _dedupe(items)


def derive_items(agent: str, source: Path, overrides, extraction: str = "", where: str = "") -> list[InventoryItem]:
    """The inventory's items: extracted from `source` (unless extraction is "none"), then overridden."""
    extracted = [] if extraction == "none" else extract_items(agent, source)
    return apply_overrides(extracted, list(overrides or ()), where)


def extract_items(agent: str, source: Path) -> list[InventoryItem]:
    source = Path(source)
    if source.suffix.lower() == ".html":
        return extract_gravity_form(source.read_text(encoding="utf-8"))
    if source.suffix.lower() == ".docx":
        paragraphs = docx_paragraphs(source)
        if any(_OTCO_SUBSECTION.match(label.strip()) for label, _text in paragraphs):
            return extract_otco_numbered(paragraphs)
        if any(not label.strip() and _SECTION_HEADING.match(text) for label, text in paragraphs):
            return extract_otco_sections(paragraphs)
        if not any(_OTCO_SECTION.match(text) for label, text in paragraphs if not label):
            return extract_otco_numbered(paragraphs, bare=True)
        return extract_otco(paragraphs)
    lines = _pdf_lines(source)
    if agent == "wsda":
        return extract_wsda(lines)
    return extract_ccof(lines)


# ---------------------------------------------------------------------------
# Web forms (CCOF's annual renewal contract is a Gravity Form on ccof.org/payments)
# ---------------------------------------------------------------------------

#: Gravity Forms markup that changes on every page load and says nothing about the questions: the
#: per-request state and nonce inputs, the anti-spam honeypot, the CAPTCHA. A capture keeps the
#: questions and drops these, so two captures of an unchanged form hash the same.
_GF_VOLATILE_TYPES = ("honeypot", "captcha", "hidden")


def _gf_fields(form_html: str, form_id: str) -> list[tuple[str, str, str]]:
    """(field id, gravity field type, field markup) in the order the form prints them."""
    parts = re.split(r'(?=<(?:div|fieldset) id="field_%s_\d+")' % re.escape(form_id), form_html)
    out = []
    for part in parts[1:]:
        head = re.match(r'<(?:div|fieldset) id="field_%s_(\d+)" class="([^"]*)"' % re.escape(form_id), part)
        if not head:
            continue
        kind = re.search(r"gfield--type-(\w+)", head.group(2))
        out.append((head.group(1), kind.group(1) if kind else "", part))
    return out


def capture_gravity_form(page_html: str, form_id: str, url: str, captured: str) -> str:
    """The one form `form_id` from a fetched page, without the parts that change per request.

    The first line records where and when it was captured; `extract_revision` reads the date from
    it, because a web form prints no revision of its own.
    """
    found = re.search(r"<form[^>]*id='gform_%s'.*?</form>" % re.escape(form_id), page_html, re.S)
    if not found:
        raise ValueError(f"No Gravity Form gform_{form_id} on the page")
    fields = [markup for _id, kind, markup in _gf_fields(found.group(0), form_id) if kind not in _GF_VOLATILE_TYPES]
    body = "\n".join(re.sub(r"<input type='hidden'[^>]*>", "", markup).strip() for markup in fields)
    return f"<!-- captured {captured} from {url} (Gravity Form gform_{form_id}) -->\n{body}\n"


def _gf_text(markup: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def _gf_label(markup: str) -> str:
    found = re.search(r"<legend[^>]*>(.*?)</legend>", markup, re.S) or re.search(
        r"<label class='gfield_label[^']*'[^>]*>(.*?)</label>", markup, re.S
    )
    label = _gf_text(found.group(1)) if found else ""
    return re.sub(r"\s*\(Required\)\s*$", "", label).strip()


def extract_gravity_form(capture: str) -> list[InventoryItem]:
    """A captured Gravity Form's items, in the order the form prints them.

    * a field the operation fills (radio, text, name, email, date, textarea, consent) is a
      question, referenced by its printed label; a field the form does not mark required is
      optional;
    * an HTML block is official text that asks nothing. A block that numbers its sentences
      (the renewal contract's terms, "1. You affirm ... 8. You agree ...") gives one instruction
      per number, referenced by that number; an unnumbered block is one instruction.
    """
    form_id = (re.search(r'id="field_(\d+)_\d+"', capture) or [None, ""])[1]
    items: list[InventoryItem] = []
    for _field_id, kind, markup in _gf_fields(capture, form_id):
        if kind in _GF_VOLATILE_TYPES:
            continue
        if kind == "html":
            text = _gf_text(markup)
            numbered = re.split(r"\s(?=\d{1,2}\.\s)", text)
            if len(numbered) > 2:
                for chunk in numbered[1:]:
                    number, _, body = chunk.partition(". ")
                    items.append(InventoryItem(number, _first_sentence(body), "instruction"))
            else:
                items.append(InventoryItem(_first_sentence(text, 60), _first_sentence(text), "instruction"))
            continue
        label = _gf_label(markup)
        if kind == "consent":
            choice = re.search(
                r"<label[^>]*class='gform-field-label gform-field-label--type-inline[^']*'[^>]*>(.*?)</label>",
                markup,
                re.S,
            )
            label = _gf_text(choice.group(1)) if choice else label
            label = re.sub(r"\s*\(Required\)\s*$", "", label).strip()
        required = "gfield_contains_required" in markup[:600]
        text = label
        if kind == "radio":
            choices = [
                _first_sentence(_gf_text(c), 120)
                for c in re.findall(r"<label for='choice_[^']*'[^>]*>(.*?)</label>", markup, re.S)
            ]
            if choices:
                text = f"{label}: " + " / ".join(choices)
        items.append(InventoryItem(label, text, "question", not required))
    return _dedupe(items)


# ---------------------------------------------------------------------------
# Overrides and the committed file
# ---------------------------------------------------------------------------


def apply_overrides(items: list[InventoryItem], overrides: list[dict], where: str = "") -> list[InventoryItem]:
    out = list(items)
    for o in overrides or ():
        op, ref, reason = o.get("op"), str(o.get("ref") or ""), str(o.get("reason") or "").strip()
        if op not in OVERRIDE_OPS or not ref or not reason:
            raise ValueError(f"{where}: every override needs an op from {OVERRIDE_OPS}, a ref and a reason: {o}")
        index = next((i for i, it in enumerate(out) if it.ref == ref), None)
        if op == "add":
            if index is not None:
                raise ValueError(f"{where}: override adds {ref!r}, which the extraction already has")
            new = InventoryItem(
                ref, str(o.get("text") or ""), str(o.get("kind") or "question"), bool(o.get("optional"))
            )
            after = o.get("after")
            pos = len(out) if after is None else next((i + 1 for i, it in enumerate(out) if it.ref == str(after)), None)
            if pos is None and after == "":
                pos = 0
            if pos is None:
                raise ValueError(f"{where}: override adds {ref!r} after {after!r}, which is not in the inventory")
            out.insert(pos, new)
            continue
        if index is None:
            raise ValueError(f"{where}: override {op}s {ref!r}, which the extraction does not have")
        item = out[index]
        if op == "remove":
            del out[index]
        elif op == "rename":
            target = str(o.get("to") or "")
            if not target:
                raise ValueError(f"{where}: override renames {ref!r} but names no `to`")
            if any(it.ref == target for i, it in enumerate(out) if i != index):
                raise ValueError(f"{where}: override renames {ref!r} to {target!r}, which another item already has")
            out[index] = InventoryItem(target, item.text, item.kind, item.optional)
        elif op == "set":
            out[index] = InventoryItem(
                item.ref,
                str(o.get("text", item.text)),
                str(o.get("kind", item.kind)),
                bool(o.get("optional", item.optional)),
            )
    return out


def _item_dict(item: InventoryItem) -> dict:
    out = {"ref": item.ref, "text": item.text, "kind": item.kind}
    if item.optional:
        out["optional"] = True
    return out


def write_inventory(
    path: Path, *, source: dict, items: list[InventoryItem], overrides: list[dict], extraction: str = ""
) -> None:
    payload = {"source": source, "extracted_by": f"extract_form_inventory {EXTRACTOR_VERSION}"}
    if extraction:
        payload["extraction"] = extraction
    payload["overrides"] = overrides or []
    payload["items"] = [_item_dict(i) for i in items]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=110))


def load_inventory(path: Path) -> Inventory:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    source = raw.get("source") or {}
    where = Path(path).name
    for key in ("file", "sha256", "revision"):
        if not source.get(key):
            raise ValueError(f"{where}: source.{key} is required")
    if not re.fullmatch(r"[0-9a-f]{64}", str(source["sha256"])):
        raise ValueError(f"{where}: source.sha256 is not a sha256")
    items = []
    seen = set()
    for raw_item in raw.get("items") or []:
        item = InventoryItem(
            str(raw_item["ref"]),
            str(raw_item.get("text") or ""),
            str(raw_item.get("kind") or "question"),
            bool(raw_item.get("optional")),
        )
        if item.kind not in ITEM_KINDS:
            raise ValueError(f"{where} [{item.ref}]: kind must be one of {ITEM_KINDS}")
        if item.ref in seen:
            raise ValueError(f"{where}: duplicate ref {item.ref!r}")
        seen.add(item.ref)
        items.append(item)
    overrides = tuple(raw.get("overrides") or ())
    for o in overrides:
        if not str(o.get("reason") or "").strip():
            raise ValueError(f"{where}: override without a reason: {o}")
    return Inventory(
        path=Path(path),
        source_file=str(source["file"]),
        sha256=str(source["sha256"]),
        revision=str(source["revision"]),
        items=tuple(items),
        overrides=overrides,
        extracted=raw.get("extraction") != "none",
    )
