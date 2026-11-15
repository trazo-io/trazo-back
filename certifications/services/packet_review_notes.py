"""The review notes a packet's own documents carry, read back from their bytes for the cover.

WHY THIS EXISTS
---------------
The overall review of 2026-11 (OV-PK-W07, OV-PK-C07, OV-PK-O08) read a first real orchard packet and
found 17 `[REVIEW]` lines spread over its parcel applications, module PDFs, workbooks and coverage
pages, with no page telling the grower what to clear before sending. The cover now lists them, grouped
by file, so the grower sees them before the packet leaves and a certifier reads one honest list instead
of finding them one page at a time. The lines themselves stay where they are.

They are read from the bytes that go into the ZIP, not collected where they are written, so the list is
what the certifier will actually read: a line built and never drawn is not listed, and a line printed by
a helper added next year is.

WHAT IS READ
------------
PDFs and workbooks Trazo generates for this packet, handed in by `generate_osp_packet`: 01 to 05, the
annual-update revisions (a filed revision's frozen bytes included, since Trazo generated them when the
update was filed and the certifier reads them in this packet like any other page), the module PDFs,
the parcel applications and the workbooks. The cover's own notes are taken from its paragraphs as it is
built (`_packet_cover_pdf`). Not read: the operator's own files (maps, affidavits, certificates, label
photos, stored lot tags), which carry no Trazo text, and 06, which is built after the cover because it
cites the cover's pages (its builder writes no note).

HOW A NOTE IS READ FROM A PDF
-----------------------------
pypdfium2 (pinned in requirements.txt; pdfplumber depends on it) gives each character with its box. A
page whose text has no `[REVIEW]` is skipped after one text call. On a page that has one, characters are
grouped into segments, one line of one column (a table row's cells are separate segments), and a note
runs from its `[REVIEW]` segment onto the segment directly below it while that segment:

* starts at the same left edge, in the same font size, one line spacing down (a table row's padding or a
  paragraph's space before it is more than that), or is the first line of that column on the next page
  when nothing in the column is below the note on its own page (a paragraph split by a page break); and
* continues a wrapped line: the first word of the line below would not have fitted on the line above,
  measured against the widest line starting at that edge on the page. A line that ends a sentence also
  ends the note, so a note whose sentence happens to end at the margin is cut there rather than run into
  the next paragraph.

Text before the mark on its first line stays with it: a post-harvest facility's certificate line names the
certificate before its "[REVIEW] certificate date not stated", and that is what says which item the note
is about.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MARK = "[REVIEW]"

#: The longest note the cover prints. A longer one is cut at a word and ends with an ellipsis.
MAX_NOTE_CHARS = 220

_SPLIT_AT_MARK = re.compile(r"(?=" + re.escape(MARK) + r")")


@dataclass
class DocumentNotes:
    """One packet document's review notes, in the order they print, each once."""

    path: str
    notes: list = field(default_factory=list)
    #: The file could not be read, so any notes it carries are not in `notes`.
    unreadable: bool = False


#: The cover's heading for the list. The question index stops reading the cover at it: the list quotes
#: other documents' notes, whose words ("address", "certificate") must not read as the cover's own
#: headings (review of back #387).
REVIEW_NOTES_HEADING = "Before sending: review notes left in this packet"


def collect(documents) -> list:
    """`DocumentNotes` for each document that carries a note or could not be read, in packet order.

    `documents` is (ZIP path, bytes) pairs. PDFs and workbooks are read; any other file is skipped. A file
    that cannot be read is logged and reported as unreadable, never raised: the packet is still built.
    """
    out = []
    for path, data in documents:
        if path.endswith(".pdf"):
            reader = notes_in_pdf
        elif path.endswith(".xlsx"):
            reader = notes_in_workbook
        else:
            continue
        try:
            notes = reader(data)
        except Exception:  # noqa: BLE001 - the list helps the grower; it must never cost them the packet
            logger.exception("Could not read the review notes in packet document %s", path)
            out.append(DocumentNotes(path, unreadable=True))
            continue
        if notes:
            out.append(DocumentNotes(path, notes))
    return out


def printable(note: str) -> str:
    """A note as the cover prints it: without the mark (the cover's heading says what every line is, and
    a second copy of each mark would double any count of them), cut to `MAX_NOTE_CHARS`."""
    text = " ".join(note.replace(MARK, " ").split())
    if len(text) <= MAX_NOTE_CHARS:
        return text
    cut = text[: MAX_NOTE_CHARS - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:") + "…"


def notes_in_workbook(data: bytes) -> list:
    """The notes in a workbook's cells (the materials list's restriction column carries them)."""
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True)
    try:
        notes = []
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                notes += [n for value in row if isinstance(value, str) and MARK in value for n in split_notes(value)]
    finally:
        workbook.close()
    return list(dict.fromkeys(notes))


def notes_in_pdf(data: bytes) -> list:
    """The notes a PDF prints, in page order."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        pages = {}

        def segments(number):
            # Read once, and only for a page with a mark or the page after one whose note runs to its foot.
            if number not in pages:
                pages[number] = _read_page(pdf, number, _segments)
            return pages[number]

        notes, used = [], set()
        for number in range(len(pdf)):
            if MARK not in _read_page(pdf, number, lambda textpage: textpage.get_text_range()):
                continue
            for k, segment in enumerate(segments(number)):
                if (number, k) in used or MARK not in segment.text:
                    continue
                used.add((number, k))
                parts, at = [segment.text], (number, k)
                # Upward first: a note whose mark sits on a wrapped line starts on the lines above it, and
                # those name the item the note is about ("Calcium chloride ... reason for use: Foliar spray
                # for bitter pit on Honeycrisp. in use [REVIEW] restricted use: ...").
                above_at = (number, k)
                while True:
                    above = _line_above(above_at, segments)
                    if above is None or (number, above) in used:
                        break
                    line = segments(number)[above]
                    if MARK in line.text or not _wraps_onto(line, segments(number)[above_at[1]], segments(number)):
                        break
                    used.add((number, above))
                    parts.insert(0, line.text)
                    above_at = (number, above)
                while True:
                    below = _line_below(at, segments, len(pdf))
                    if below is None or below in used:
                        break
                    line = segments(below[0])[below[1]]
                    if line.text.startswith(MARK) or not _wraps_onto(segments(at[0])[at[1]], line, segments(at[0])):
                        break
                    used.add(below)
                    parts.append(line.text)
                    at = below
                notes += split_notes(" ".join(parts))
    finally:
        pdf.close()
    return _without_repeats(notes)


def _without_repeats(notes) -> list:
    """The notes once each, in order. A note that is the tail of another (the same table row printed on two
    pages, one read from its first line and one from a wrapped line) is the same note: the longer is kept."""
    kept = list(dict.fromkeys(notes))
    return [n for n in kept if not any(other != n and other.endswith(n) for other in kept)]


def _read_page(pdf, number, read):
    page = pdf[number]
    textpage = page.get_textpage()
    try:
        return read(textpage)
    finally:
        textpage.close()
        page.close()


@dataclass
class _Segment:
    """One line of one column: a paragraph's line, or one cell's line in a table row."""

    text: str
    x0: float
    x1: float
    bottom: float
    height: float
    #: Where the segment's first word ends, to tell whether it would have fitted on the line above.
    first_word_x1: float


def _segments(textpage) -> list:
    """The page's characters as segments. Loose boxes span the font's full height, so a line's boxes share
    a bottom and a height whatever its letters, and abut across a space: a gap means another column."""
    import pypdfium2.raw as pdfium_c

    segments, run = [], []

    def close():
        boxed = [(ch, box) for ch, box in run if box is not None]
        while boxed and boxed[-1][0].isspace():
            boxed.pop()
        if boxed:
            first_word = boxed
            for k, (ch, _box) in enumerate(boxed):
                if ch.isspace():
                    first_word = boxed[:k]
                    break
            segments.append(
                _Segment(
                    text=" ".join("".join(ch for ch, _box in run).split()),
                    x0=boxed[0][1][0],
                    x1=boxed[-1][1][2],
                    bottom=min(box[1] for _ch, box in boxed),
                    height=max(box[3] for _ch, box in boxed) - min(box[1] for _ch, box in boxed),
                    first_word_x1=(first_word or boxed)[-1][1][2],
                )
            )
        run.clear()

    previous = None
    for i in range(textpage.count_chars()):
        ch = chr(pdfium_c.FPDFText_GetUnicode(textpage, i) or 32)
        if ch in "\r\n":
            close()
            previous = None
            continue
        if pdfium_c.FPDFText_IsGenerated(textpage, i) == 1:
            run.append((" ", None))
            continue
        box = textpage.get_charbox(i, loose=True)
        if previous is not None:
            size = max(previous[3] - previous[1], box[3] - box[1])
            if box[0] - previous[2] > 0.45 * size or box[0] < previous[0] - 1 or abs(box[1] - previous[1]) > size / 2:
                close()
        run.append((ch, box))
        previous = box
    close()
    return segments


def _same_column(a, b) -> bool:
    """Same left edge and same font size."""
    return abs(a.x0 - b.x0) <= 1.5 and abs(a.height - b.height) <= 0.15 * a.height


def _line_below(at, segments, page_count):
    """(page, index) of the line that would continue the segment at `at`: the one a line spacing below it
    at its left edge and in its size or, when nothing in that column is below it on its page (a paragraph
    split by a page break), the first line of that column on the next page."""
    number, k = at
    current = segments(number)[k]
    best, best_step, lower = None, None, False
    for index, other in enumerate(segments(number)):
        if index == k or not _same_column(current, other):
            continue
        step = current.bottom - other.bottom
        lower = lower or step > 0
        if 0.9 * current.height <= step <= 1.4 * current.height and (best_step is None or step < best_step):
            best, best_step = index, step
    if best is not None:
        return (number, best)
    if lower or number + 1 >= page_count:
        return None
    top = [(other.bottom, index) for index, other in enumerate(segments(number + 1)) if _same_column(current, other)]
    return (number + 1, max(top)[1]) if top else None


def _line_above(at, segments):
    """Index of the segment a line spacing above the one at `at`, at its left edge and in its size, on the
    same page, or None. The mirror of `_line_below` without the page-break case."""
    number, k = at
    current = segments(number)[k]
    best, best_step = None, None
    for index, other in enumerate(segments(number)):
        if index == k or not _same_column(current, other):
            continue
        step = other.bottom - current.bottom
        if 0.9 * current.height <= step <= 1.4 * current.height and (best_step is None or step < best_step):
            best, best_step = index, step
    return best


def _wraps_onto(current, below, segments) -> bool:
    """Whether `below` continues `current` as a wrapped line rather than starting a new paragraph.

    A line wrapped when the next word would not have fitted: `current`'s end, a space and `below`'s first
    word reach past the right edge its column runs to. The edge is measured on the column's OTHER lines
    (same left edge, similar size), never on `current` itself: measured with it, a note that was the widest
    line in its column always "wrapped", and an unrelated paragraph below was glued onto the note (review of
    back #387). Not on the whole page either: a page number or a right-aligned header sits past the text
    frame and would hide every real wrap. When no other line of the column reaches within half a line
    height of `current`'s end, nothing shows that `current` is a full line, so nothing is joined: a note's
    tail left off the cover list is better than someone else's sentence added to it.
    """
    if current.text.endswith((".", "?", "!")):
        return False
    column = [
        s.x1
        for s in segments
        if s is not current and s is not below and abs(s.x0 - current.x0) <= 1.5 and s.height <= 2 * current.height
    ]
    if not column or max(column) < current.x1 - 0.5 * current.height:
        return False
    space = 0.25 * current.height
    return current.x1 + space + (below.first_word_x1 - below.x0) > max(column) - 1


def split_notes(text: str) -> list:
    """One note per mark. Text before the first mark is the item the note is about and stays with it."""
    pieces = _SPLIT_AT_MARK.split(" ".join(text.split()))
    if len(pieces) > 1 and MARK not in pieces[0]:
        pieces = [pieces[0] + pieces[1]] + pieces[2:]
    return [p.strip() for p in pieces if MARK in p and p.replace(MARK, "").strip()]
