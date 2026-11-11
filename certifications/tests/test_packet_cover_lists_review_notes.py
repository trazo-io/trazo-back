"""The packet cover lists every review note its documents carry, grouped by file.

WHY THIS EXISTS
---------------
The overall review of 2026-11 (OV-PK-W07, OV-PK-C07, OV-PK-O08) read a first real orchard packet: 17
`[REVIEW]` lines spread over parcel applications, module PDFs, workbooks and coverage pages, and no page
that told the grower what to clear before sending. The certifier found them one at a time. The cover now
lists them, read back from the documents in the ZIP, so these tests read the ZIP too: the cover against
the documents it names, with pdfminer on the document side so the list is not checked against itself.
"""

import io
import zipfile
from datetime import date
from unittest import mock

from django.test import SimpleTestCase, TestCase

import openpyxl
from pdfminer.high_level import extract_text

from certifications.models import Certification, OrganicSystemPlan
from certifications.services import packet_review_notes
from certifications.services.osp_module_pdf import _packet_cover_pdf, generate_osp_packet
from certifications.services.packet_review_notes import MARK, DocumentNotes, collect, printable
from company.models import Company, Establishment
from product.models import Parcel

HEADING = "Before sending: review notes left in this packet"
NONE_LEFT = "No review notes are left in the packet's documents."
PARCEL_PAGE = "parcels/parcel-application-Home Block.pdf"
#: Printed on a parcel application when no boundary is recorded (`_parcel_embed_flowables`). Long enough
#: to wrap, so finding it whole on the cover proves the note was read past its first line.
NO_BOUNDARY = (
    "No field-boundary geometry is on file for this parcel, so no map could be drawn. Record the parcel "
    "boundary in Trazo, or attach your own map below."
)
#: The cover's own note when the plan leaves the split-operation question open (`_product_types_cover_lines`).
SPLIT_NOT_STATED = "The plan does not say whether the operation produces or handles non-organic product."


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _cover_block(cover: str) -> str:
    start = cover.index(HEADING)
    return cover[start : cover.index("Contents", start)]


class _Operation(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Review Notes Orchard LLC")
        self.est = Establishment.objects.create(name="Review Notes Orchard", company=company, state="OR")
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="RN-1",
            certifier_name="Oregon Tilth Certified Organic",
            effective_date=date(2020, 1, 1),
        )
        # No boundary and no map: the parcel application prints its map review notes.
        Parcel.objects.create(name="Home Block", establishment=self.est, area=4.0)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", certifier_name="Oregon Tilth Certified Organic"
        )

    def _cover_without_notes_of_its_own(self):
        """Say whether the operation is split, so the cover prints no note of its own."""
        self.est.has_split_operation = True
        self.est.save(update_fields=["has_split_operation"])


class CoverListsTheNotesInThePacketTests(_Operation):
    def test_the_cover_lists_each_document_that_prints_a_note_and_its_lines(self):
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp)))
        names = packet.namelist()
        # The cover is rendered last but is still the first file, and 06 still follows the workbooks.
        self.assertEqual(
            names[:4],
            [
                "00-cover.pdf",
                "01-organic-system-plan.pdf",
                "02-annual-update.pdf",
                "02s-renewal-status-and-routing.pdf",
            ],
        )
        last_workbook = max(i for i, n in enumerate(names) if n.startswith("workbooks/"))
        self.assertEqual(names[last_workbook + 1], "06-question-index.pdf")

        cover = _text(packet.read("00-cover.pdf"))
        block = _cover_block(cover)
        self.assertLess(cover.index("Plan review"), cover.index(HEADING))
        self.assertNotIn(NONE_LEFT, block)

        # Every document Trazo generated (this operation uploaded nothing) that prints the mark, read by
        # pdfminer and openpyxl rather than by the collector, is named on the cover; no other is. The cover
        # counts as one: the plan leaves the split question open, so the cover prints a note of its own.
        printing = ["00-cover.pdf"]
        self.assertIn(MARK, cover[: cover.index(HEADING)])
        self.assertIn("00-cover.pdf", block)
        self.assertIn(SPLIT_NOT_STATED, block)
        for name in names:
            if name in ("00-cover.pdf", "06-question-index.pdf"):
                continue
            data = packet.read(name)
            if name.endswith(".pdf"):
                text = _text(data)
            else:
                self.assertTrue(name.endswith(".xlsx"), name)
                book = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
                text = " ".join(str(v) for s in book.worksheets for r in s.iter_rows(values_only=True) for v in r if v)
            if MARK in text:
                printing.append(name)
            self.assertEqual(name in block, name in printing, name)
        self.assertIn(PARCEL_PAGE, printing)

        # The count, and the lines: each listed line is one the document prints. Reading the finished cover
        # finds only the notes printed in place, since its list carries no mark.
        notes = packet_review_notes.notes_in_pdf(packet.read(PARCEL_PAGE))
        self.assertGreaterEqual(len(notes), 2)
        total = sum(len(d.notes) for d in collect((n, packet.read(n)) for n in printing))
        self.assertIn(f"{total} review notes in {len(printing)} document", block)
        page = _text(packet.read(PARCEL_PAGE))
        for note in notes:
            self.assertIn(" ".join(note.split()), page)
            self.assertIn(printable(note), block)
        self.assertIn(NO_BOUNDARY, block)
        self.assertIn(NO_BOUNDARY, page)
        # The cover names the notes; it does not print a second copy of each mark.
        self.assertNotIn(MARK, block)

    def test_a_packet_with_no_notes_says_none_are_left(self):
        self._cover_without_notes_of_its_own()
        with mock.patch.object(packet_review_notes, "collect", return_value=[]) as collected:
            packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp)))
        # The collector was handed the documents built before the cover: not the cover, not 06.
        handed = [path for path, _data in collected.call_args.args[0]]
        self.assertIn(PARCEL_PAGE, handed)
        self.assertIn("01-organic-system-plan.pdf", handed)
        self.assertNotIn("00-cover.pdf", handed)
        self.assertNotIn("06-question-index.pdf", handed)
        block = _cover_block(_text(packet.read("00-cover.pdf")))
        self.assertIn(NONE_LEFT, block)
        self.assertNotIn("review notes in", block)


class CoverBlockWordingTests(_Operation):
    def setUp(self):
        super().setUp()
        self._cover_without_notes_of_its_own()

    def test_more_than_five_notes_are_counted_and_an_unreadable_file_is_named(self):
        long_note = f"{MARK} " + "word " * 80
        notes = [f"{MARK} Note number {i} for the operation." for i in range(1, 7)] + [long_note]
        cover = _text(
            _packet_cover_pdf(
                self.osp,
                review_notes=[
                    DocumentNotes("modules/G8_0.pdf", notes),
                    DocumentNotes("workbooks/Materials List.xlsx", unreadable=True),
                ],
            )
        )
        block = _cover_block(cover)
        self.assertIn("7 review notes in 1 document.", block)
        self.assertIn("modules/G8_0.pdf", block)
        for i in range(1, 6):
            self.assertIn(f"Note number {i} for the operation.", block)
        self.assertNotIn("Note number 6", block)
        self.assertIn("and 2 more", block)
        self.assertIn(
            "workbooks/Materials List.xlsx: this file could not be read, so any review notes in it are not listed here.",
            block,
        )
        self.assertLessEqual(len(printable(long_note)), packet_review_notes.MAX_NOTE_CHARS)
        self.assertTrue(printable(long_note).endswith("…"))

    def test_one_note_reads_in_the_singular(self):
        block = _cover_block(
            _text(_packet_cover_pdf(self.osp, review_notes=[DocumentNotes(PARCEL_PAGE, [f"{MARK} One note."])]))
        )
        self.assertIn("1 review note in 1 document. It is a question for the operation", block)

    def test_only_unreadable_files_never_reads_as_none_left(self):
        block = _cover_block(
            _text(_packet_cover_pdf(self.osp, review_notes=[DocumentNotes(PARCEL_PAGE, unreadable=True)]))
        )
        self.assertNotIn(NONE_LEFT, block)
        self.assertIn("No review notes were found in the documents that could be read.", block)

    def test_a_cover_rendered_on_its_own_prints_no_list(self):
        self.assertNotIn(HEADING, _text(_packet_cover_pdf(self.osp)))


class CollectorTests(TestCase):
    def test_a_file_that_cannot_be_read_is_reported_not_raised(self):
        with self.assertLogs("certifications.services.packet_review_notes", level="ERROR"):
            found = collect([("modules/broken.pdf", b"not a pdf"), ("attachments/photo.jpg", b"\xff\xd8")])
        self.assertEqual([(d.path, d.unreadable, d.notes) for d in found], [("modules/broken.pdf", True, [])])

    def test_workbook_cells_are_read(self):
        book = openpyxl.Workbook()
        book.active["F7"] = (
            "Restriction, 205.601: as stated. [REVIEW] The material, its restriction or the plan has changed "
            "since this was stated."
        )
        book.active["F8"] = "No note here."
        out = io.BytesIO()
        book.save(out)
        self.assertEqual(
            collect([("workbooks/Materials List.xlsx", out.getvalue())])[0].notes,
            [
                "Restriction, 205.601: as stated. [REVIEW] The material, its restriction or the plan has changed "
                "since this was stated."
            ],
        )


class ReviewOfBack387Tests(SimpleTestCase):
    """The two defects the review of back #387 found, each pinned on the smallest input."""

    @staticmethod
    def _seg(text, x0, x1, bottom, first_word_x1=None, height=10.0):
        from certifications.services.packet_review_notes import _Segment

        return _Segment(text=text, x0=x0, x1=x1, bottom=bottom, height=height, first_word_x1=first_word_x1 or x0 + 20)

    def test_a_short_note_line_never_takes_in_the_paragraph_below(self):
        from certifications.services.packet_review_notes import _wraps_onto

        full = self._seg("A full body line that runs to the right edge of the frame", 72, 540, 700)
        note = self._seg("[REVIEW] Certificate date not recorded", 72, 300, 650)
        below = self._seg("An unrelated paragraph starts here", 72, 400, 638)
        self.assertFalse(_wraps_onto(note, below, [full, note, below]))

    def test_a_full_note_line_still_wraps(self):
        from certifications.services.packet_review_notes import _wraps_onto

        full = self._seg("A full body line that runs to the right edge of the frame", 72, 540, 700)
        note = self._seg("[REVIEW] A note long enough to fill the line up to the", 72, 530, 650)
        below = self._seg("margin and carry on", 72, 160, 638, first_word_x1=110)
        self.assertTrue(_wraps_onto(note, below, [full, note, below]))

    def test_a_note_that_is_the_widest_line_of_its_column_does_not_take_in_the_next_paragraph(self):
        # The case the review described: measured with the note line itself, the edge was the note's
        # own end and every line below "wrapped".
        from certifications.services.packet_review_notes import _wraps_onto

        other = self._seg("A short meta line", 72, 250, 700)
        note = self._seg("[REVIEW] Certificate date not recorded", 72, 300, 650)
        below = self._seg("An unrelated meta paragraph", 72, 200, 638)
        self.assertFalse(_wraps_onto(note, below, [other, note, below]))

    def test_with_no_other_line_to_measure_nothing_is_joined(self):
        from certifications.services.packet_review_notes import _wraps_onto

        note = self._seg("[REVIEW] The only line in its column", 72, 300, 650)
        below = self._seg("Something else", 72, 200, 638)
        self.assertFalse(_wraps_onto(note, below, [note, below]))

    def test_the_question_index_stops_reading_the_cover_at_the_list(self):
        from certifications.services.packet_review_notes import REVIEW_NOTES_HEADING
        from certifications.services.question_index import _cover_without_review_notes, _norm

        pages = [
            _norm("Operation Legal name: Render Co Address: OR"),
            _norm(f"Plan review ... {REVIEW_NOTES_HEADING} [REVIEW] The operation's address on file has no zip"),
            _norm("[REVIEW] another address note"),
        ]
        cut = _cover_without_review_notes(pages)
        self.assertEqual(len(cut), 3, "page numbers are kept")
        self.assertIn("address", cut[0])
        self.assertNotIn("address", cut[1])
        self.assertEqual(cut[2], "")
