"""A transcribed record says so where a certifier reads it, and nowhere a shopper does.

The dossier PDF and its CSV twin are read by the same reviewer, so the line prints on both
(six of nine defects in the 2026-08-20 sweep were "fixed on one surface, alive on its sibling").
The source document itself is already on the shelf as an upload; the Attached Documents index
now says how many records were read from it. The buyer page never carries the pointer.
"""

import csv
import io
from pathlib import Path

from pdfminer.high_level import extract_text

from history.services.audit_export_service import AuditExportService
from history.services.cogpro_import import build_plan as cogpro_plan
from history.services.cogpro_import import execute as cogpro_execute
from history.services.record_intake import execute
from history.tests.test_record_intake import BATCH, IntakeFarm

COGPRO = Path(__file__).parent / "fixtures" / "cogpro"
SENTENCE = "Transcribed by Oscar Munoz (Trazo setup) from Spray and field log 2026, sheet row 12"


def _pdf_text(service):
    pdf_bytes = service.generate_pdf(strict_photos=False, strict_ofpp=False)
    pdf_bytes = pdf_bytes.getvalue() if hasattr(pdf_bytes, "getvalue") else pdf_bytes
    return " ".join(extract_text(io.BytesIO(pdf_bytes)).split())


def _csv_rows(service):
    return [r for r in csv.reader(io.StringIO(service.generate_csv().getvalue().decode("utf-8-sig"))) if r]


class TranscriptionProvenanceTests(IntakeFarm):
    def setUp(self):
        super().setUp()
        execute(self.fixture(), self.farm, self.operator, BATCH)

    def test_the_dossier_notes_tables_name_the_document_and_the_row(self):
        text = _pdf_text(AuditExportService(self.seasons["Block 1"]))
        self.assertIn("Source document", text)
        self.assertIn("Transcribed by Oscar Munoz", text)
        # An application (Surround WP, sheet row 12), a production record (irrigation, row 19), a
        # harvest (row 20) and a soil amendment (compost, row 17) all print it.
        for locator in ("sheet row 12", "sheet row 19", "sheet row 20", "sheet row 17"):
            self.assertIn(locator, text, locator)

    def test_the_audit_csv_notes_cell_carries_the_whole_sentence(self):
        rows = _csv_rows(AuditExportService(self.seasons["Block 1"]))
        carrying = [r for r in rows if any(SENTENCE in cell for cell in r)]
        self.assertEqual(len(carrying), 1, "exactly the Surround WP row")
        self.assertIn("Surround WP", carrying[0])
        production_rows = [r for r in rows if any("sheet row 19" in cell for cell in r)]
        self.assertEqual(len(production_rows), 1, "the irrigation record's Notes cell")

    def test_the_attached_documents_index_lists_the_sheet_with_its_record_count(self):
        # Block 1 took 8 of the 26 records: rows 3, 4, 5, 7, 12, 17, 19 and 20.
        text = _pdf_text(AuditExportService(self.seasons["Block 1"]))
        self.assertIn("Spray and field log 2026", text)
        self.assertIn("source of 8 transcribed record(s)", text)

    def test_the_buyer_page_never_carries_source(self):
        from history.serializers import PublicHistorySerializer

        keys = PublicHistorySerializer.ALLOWED_EXTRA_DATA_KEYS
        self.assertIn("active_ingredient", keys, "positive control: the allow-list was read")
        self.assertNotIn("source", keys)

    def test_a_cogpro_row_prints_imported_from_with_its_line(self):
        with open(COGPRO / "fertility.csv", "rb") as fh:
            cogpro_execute(
                cogpro_plan(fh), self.seasons["Block 2"], created_by=self.operator, source_title="fertility.csv"
            )
        text = _pdf_text(AuditExportService(self.seasons["Block 2"]))
        self.assertIn("Imported by Oscar Munoz", text)
        self.assertIn("COG Pro export fertility.csv, line", text)
