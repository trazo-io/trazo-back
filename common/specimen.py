"""One place that decides whether an exported document describes a REAL operation.

WHY THIS EXISTS
---------------
Until 2026-08-21 every artifact Trazo exports — the certifier audit packet, its CSV twin,
the operation-wide packet, the OSP module PDFs, the CA PUR filing — carried no marking of
any kind. A packet generated from Calapooia Bend Farm, an operation invented for a pilot
rehearsal, was not merely *similar* to a real grower's organic records: it was the same
kind of document, with the same cover, the same CFR citations, the same handler
certificates and the same § 205.103 audit trail.

Those documents get forwarded, excerpted, printed a section at a time and filed. We intend
to hand them to independent inspectors and, from October, to certifier reviewers. An
unmarked synthetic one is a document that can be mistaken for a real operation's legal
records — and in the PUR case, for a pesticide-use report filed with a county agricultural
commissioner.

WHY ONE MODULE AND NOT SEVEN PATCHES
------------------------------------
Because the dominant defect class in this codebase is "fixed on the audited surface, alive
on its sibling" — 6 of the 9 defects in the two-farm certifier sweep, and the annotation
rule that had to be repeated in five places. Marking the packet PDF and not its CSV would
have reproduced, exactly, the bug where the CSV never got the PDF's state gate.

So the predicate, the wording and the drawing all live here, and
`history/tests/test_specimen_marking.py` walks the export surfaces and asserts each one
consults this module.

THE DEFAULT IS THE LOAD-BEARING PART
------------------------------------
`Establishment.is_demo` defaults to False and `is_specimen()` resolves anything it cannot
read to False. The two ways to be wrong are not symmetric:

* Failing to mark a synthetic packet restores the pre-2026-08-21 status quo.
* Marking a REAL packet tells a certifier that a legitimate operation's § 205.103 records
  are a demonstration, which invites them to reject the farmer's filing.

So this module never guesses toward marking.
"""

from __future__ import annotations

SPECIMEN_TITLE = "SPECIMEN — FABRICATED RECORDS"

SPECIMEN_BODY = (
    "This document was generated from invented data for demonstration and testing. It "
    "documents no real operation, no real harvest and no real handler, and it is not a "
    "7 CFR 205.103 record of any certified operation. Do not file, forward or rely on it "
    "as evidence of compliance."
)

#: Single-line form, for CSV headers, filenames and anywhere markup is not available.
SPECIMEN_LINE = f"{SPECIMEN_TITLE} — {SPECIMEN_BODY}"


def is_specimen(establishment) -> bool:
    """True when this farm's records are fabricated.

    Accepts anything with an `is_demo` attribute, or None. Never raises: an export must not
    fail because the marking check could not read its own subject, and it must not mark on
    uncertainty (see module docstring).
    """
    try:
        return bool(getattr(establishment, "is_demo", False))
    except Exception:  # pragma: no cover - defensive; getattr on a broken proxy
        return False


def establishment_of(obj):
    """Best-effort walk from a production / OSP / establishment to its Establishment.

    The export surfaces are constructed from different roots — `AuditExportService` takes a
    production, `OperationAuditExportService` and the PUR builder take an establishment, the
    OSP renderers take an OSP. One resolver keeps the call sites uniform, so wiring a new
    surface is one import rather than a fresh traversal invented per file.
    """
    if obj is None:
        return None
    # Already an establishment.
    if hasattr(obj, "is_demo"):
        return obj
    for path in (("establishment",), ("parcel", "establishment")):
        cur = obj
        for attr in path:
            cur = getattr(cur, attr, None)
            if cur is None:
                break
        if cur is not None and hasattr(cur, "is_demo"):
            return cur
    return None


def draw_specimen_watermark(canvas, pagesize) -> None:
    """Diagonal SPECIMEN wash across one page.

    Call from a ReportLab page callback, which fires at page BEGIN — so this lands UNDER the
    flowables and cannot obscure a line a reviewer needs to read.

    On EVERY page, never the cover alone: packets are excerpted, forwarded and filed a
    section at a time, so the mark has to survive someone printing page 14 on its own.
    """
    from reportlab.lib import colors

    width, height = pagesize
    canvas.saveState()
    try:
        canvas.setFillColor(colors.HexColor("#C62828"))
        canvas.setFillAlpha(0.12)
        canvas.translate(width / 2.0, height / 2.0)
        canvas.rotate(38)
        canvas.setFont("Helvetica-Bold", 58)
        canvas.drawCentredString(0, 0, "SPECIMEN")
        canvas.setFont("Helvetica-Bold", 14)
        canvas.drawCentredString(0, -32, "FABRICATED RECORDS — NOT A REAL OPERATION")
    finally:
        canvas.restoreState()


def specimen_page_callback(pagesize, base_callback=None, specimen=True):
    """Wrap an existing per-page callback so it also draws the wash.

    A factory closing over the flag rather than module-level state: background work here runs
    on `threading.Thread(daemon=True)` (.claude/rules/backend.md), so two exports can be
    mid-build in one process, and a module global would let one export's watermark bleed onto
    another farm's pages — i.e. tell a reviewer that a real operation's records are a demo.
    """

    def _draw(canvas, doc):
        if base_callback is not None:
            base_callback(canvas, doc)
        if specimen:
            draw_specimen_watermark(canvas, pagesize)

    return _draw
