"""Every page Trazo generates into a demo farm's renewal packet carries the specimen mark.

WHY THIS EXISTS
---------------
2026-09-11, reading the specimen packet built for a WSDA grower: 43 of its 45 pages carried the
SPECIMEN wash, and pages 14-15, the audit trail exhibit, did not. Those are the most record-like
pages in the ZIP, one named lot walked from field to sale with its invoice and bill-of-lading
numbers. Printed on their own, they were a fabricated trace-back with nothing on them to say so.

`history/tests/test_specimen_marking.py` already walks the tree for document builders, but it
checks per FILE. `osp_module_pdf.py` consults `common.specimen` for its other documents, so the
exhibit passed on the strength of its neighbours. This test reads the OUTPUT instead, discovered
from the packet's own namelist, so a document added to the packet later is covered the day it
lands rather than when someone remembers to list it.

The real-farm direction is asserted too, over the same walk. Marking a real operation's records
as fabricated is the worse of the two failures (see `common/specimen.py`).
"""

import io
import zipfile

from django.test import TestCase

import openpyxl

from certifications.models import OrganicSystemPlan
from certifications.services.osp_module_pdf import generate_osp_packet
from common.specimen import SPECIMEN_TITLE
from company.models import Company, Establishment
from product.models import Parcel

#: Files the packet carries but did not generate: the operator's own uploads, attached as-is.
#: Trazo cannot draw on a scanned affidavit or a photographed map without altering the
#: operator's document, so these are out of scope here, by folder rather than by name.
_OPERATOR_UPLOAD_FOLDERS = (
    "parcels/maps/",
    "parcels/affidavits/",
    "receipts/",
    # 2026-10-01 (audit T19, T22): the operator's label files and label photos, files uploaded for
    # a named attachment, and a sale's source documents. Lot tag sheets are NOT here: Trazo
    # generates them, so `labels/lot-tags/` is checked like every other generated document.
    "labels/photos/",
    "attachments/",
    "audit-trail/",
)


def _is_operator_upload(name: str) -> bool:
    if name.startswith(_OPERATOR_UPLOAD_FOLDERS):
        return True
    # A label file uploaded for the label question sits directly under labels/.
    return name.startswith("labels/") and name.count("/") == 1


def _pdf_pages(data: bytes) -> list:
    from pdfminer.high_level import extract_text

    pages = []
    for index in range(500):
        try:
            text = extract_text(io.BytesIO(data), page_numbers=[index])
        except Exception:
            break
        if not text:
            break
        pages.append(text)
    return pages


def _workbook_text(data: bytes) -> str:
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
    return "\n".join(
        str(cell) for sheet in workbook.worksheets for row in sheet.iter_rows(values_only=True) for cell in row if cell
    )


class PacketSpecimenEveryDocumentTests(TestCase):
    def _packet(self, is_demo: bool) -> zipfile.ZipFile:
        company = Company.objects.create(name=f"Marking Co {is_demo}")
        establishment = Establishment.objects.create(
            name=f"Marking Farm {is_demo}", company=company, state="WA", is_demo=is_demo
        )
        Parcel.objects.create(name="Home Block", establishment=establishment, area=4.0)
        osp = OrganicSystemPlan.objects.create(establishment=establishment, version_number=1, status="draft")
        return zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))

    def _generated(self, packet: zipfile.ZipFile) -> list:
        return [
            name for name in packet.namelist() if name.endswith((".pdf", ".xlsx")) and not _is_operator_upload(name)
        ]

    def test_every_page_of_every_generated_document_is_marked(self):
        packet = self._packet(is_demo=True)
        names = self._generated(packet)
        # Non-vacuous: the walk must have reached the documents, including the one that was missed.
        self.assertGreater(len([n for n in names if n.endswith(".pdf")]), 10)
        self.assertIn("05-audit-trail-exhibit.pdf", names)

        unmarked = []
        for name in names:
            data = packet.read(name)
            if name.endswith(".xlsx"):
                if SPECIMEN_TITLE not in _workbook_text(data):
                    unmarked.append(name)
                continue
            pages = _pdf_pages(data)
            self.assertTrue(pages, f"{name}: no page text extracted, so this check would pass vacuously")
            unmarked += [f"{name} p{i}" for i, text in enumerate(pages, 1) if "SPECIMEN" not in text]

        self.assertEqual(
            unmarked,
            [],
            "these pages of a fabricated operation's packet carry no specimen mark. Packets are "
            "printed and forwarded a document at a time, so every page has to say it on its own.",
        )

    def test_no_page_of_a_real_farms_packet_is_marked(self):
        packet = self._packet(is_demo=False)
        marked = []
        for name in self._generated(packet):
            data = packet.read(name)
            if name.endswith(".xlsx"):
                text = _workbook_text(data)
                if "SPECIMEN" in text or "FABRICATED" in text:
                    marked.append(name)
                continue
            marked += [
                f"{name} p{i}"
                for i, text in enumerate(_pdf_pages(data), 1)
                if "SPECIMEN" in text or "FABRICATED" in text
            ]
        self.assertEqual(marked, [], "a real operation's packet was marked as fabricated")
