"""Where each question label actually lands in the packet's PDFs (OSP alignment T24, Phase 5 slice 4).

A page number cannot be computed before ReportLab lays the page out, and a marker placed next to a
label can be separated from it by a page break. So the LABEL records itself: `QuestionLabel` is the
label paragraph, and it writes its page into the active recorder when it is drawn. If the label is
split across a page break, only the first fragment (where the label starts) carries the anchor.
`keepWithNext` keeps the label on the page of its first answer line.

Outside a packet build there is no recorder and nothing is recorded.
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass, field

from reportlab.platypus import Paragraph


@dataclass(frozen=True)
class LabelLocation:
    file: str
    page: int
    module: str
    question: str
    section: str
    label: str


@dataclass
class Recorder:
    labels: list = field(default_factory=list)
    #: The generated and filed documents' bytes, by ZIP path, read back to find where a form's
    #: section or heading is.
    documents: dict = field(default_factory=dict)
    #: ZIP paths whose bytes are a FILED document (frozen at submission), not generated now.
    filed: set = field(default_factory=set)
    #: Parcel page ZIP path -> parcel name.
    parcel_files: dict = field(default_factory=dict)
    current_file: str = ""
    #: The `question_index.QuestionIndex` built from this recording, once 06 is written.
    index: object = None

    def where(self, module_key, question_key) -> list:
        return [loc for loc in self.labels if loc.module == module_key and loc.question == question_key]


_RECORDER: contextvars.ContextVar = contextvars.ContextVar("packet_index_recorder", default=None)


def current_recorder():
    return _RECORDER.get()


@contextlib.contextmanager
def recording():
    """A recorder for one packet build. Nested inside another, it is the outer one, so a caller can
    read what the build recorded (the tests do)."""
    outer = current_recorder()
    if outer is not None:
        yield outer
        return
    recorder = Recorder()
    token = _RECORDER.set(recorder)
    try:
        yield recorder
    finally:
        _RECORDER.reset(token)


@contextlib.contextmanager
def document(path: str):
    """Labels drawn inside this block belong to the packet file at `path`."""
    recorder = current_recorder()
    if recorder is None:
        yield
        return
    previous, recorder.current_file = recorder.current_file, path
    try:
        yield
    finally:
        recorder.current_file = previous


class QuestionLabel(Paragraph):
    """A question's label paragraph that records the page it is drawn on."""

    def __init__(self, text, style, *args, anchor=None, **kwargs):
        super().__init__(text, style, *args, **kwargs)
        #: (module key, question key, section title, plain label) or None.
        self.anchor = anchor
        self.keepWithNext = True

    def split(self, availWidth, availHeight):
        parts = super().split(availWidth, availHeight)
        anchor = getattr(self, "anchor", None)
        for i, part in enumerate(parts):
            part.anchor = anchor if i == 0 else None
            part.keepWithNext = i == len(parts) - 1
        return parts

    def draw(self):
        super().draw()
        anchor = getattr(self, "anchor", None)
        recorder = current_recorder()
        if anchor is None or recorder is None or not recorder.current_file:
            return
        module_key, question_key, section, label = anchor
        recorder.labels.append(
            LabelLocation(
                file=recorder.current_file,
                page=self.canv.getPageNumber(),
                module=module_key,
                question=question_key,
                section=section,
                label=label,
            )
        )
