"""Identifier columns in the audit PDF must fit their own contents.

A comment in audit_export_service.py has asserted since 2026-08-01 that
"test_audit_pdf_column_fit.py holds this true". The file never existed. With nothing able to
reach the numbers — they were inline literals inside long render methods — two tables drifted
below the width of the identifiers they carry, and it took reading a generated packet to find
it:

    Invoice "YAS-2025-4417"  rendered as  "YAS-2025-441" / "7"
    Invoice "YAS-2025-4417"  rendered as  "YAS-2025-44"  / "17"   (traceability table)
    Lot     "NH2025-0412"    rendered as  "NH2025-0"     / "412"
    Date    "2025-03-23"     rendered as  "2025-03-2"    / "3"

That is the worst possible failure for these particular columns. ReportLab does not overflow a
long unbroken token — it SPLITS it — so the cell still looks like a value, just a different
one. An inspector cross-referencing "YAS-2025-441" against the supplier's records matches
nothing, and nothing in the document signals that a digit went missing. Truncation was made
opt-in on 2026-08-01 for exactly this reason; silent mid-token wrapping is the same defect
wearing a different hat.

Two rules, both enforced here:

  1. Every width list fits the printable frame (letter, 0.75in margins => 7.00in).
  2. Every column carrying an ATOMIC token is at least `stringWidth(token) + 6pt padding`.
     Prose columns (product, supplier, target pest) are MEANT to wrap and are exempt.

No database and no PDF parsing — the widths are now importable constants and ReportLab can
measure a string directly, so this runs anywhere.
"""

from django.test import SimpleTestCase

from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth

from history.services import audit_export_service as svc

#: letter (8.5in) less the 0.75in margins the document sets on both sides.
FRAME_WIDTH = 7.00 * inch

#: Table cell font. Matches the "cell" ParagraphStyle the tables render with.
CELL_FONT = "Helvetica"
CELL_FONT_SIZE = 7

#: ReportLab's default left+right cell padding (3pt each).
CELL_PADDING = 6

#: Worst-case atomic tokens these columns actually receive. Drawn from the showcase farm's
#: real records rather than invented, so the guard tracks the shape of live data.
WORST_CASE_TOKENS = {
    "Date": "2025-03-23",
    "Date Applied": "2025-03-23",
    "Purchase Date": "2025-03-10",
    "Invoice #": "YAS-2025-4417",
    "Lot #": "NH2025-04127",
}

#: Headers render BOLD, which is wider than the regular face used for values. Sizing a column
#: from a regular-weight measurement leaves the header itself wrapping.
HEADER_FONT = "Helvetica-Bold"

WIDTH_LISTS = {
    "MASS_BALANCE_PURCHASE_WIDTHS": svc.MASS_BALANCE_PURCHASE_WIDTHS,
    "INPUT_TRACEABILITY_WIDTHS_CA": svc.INPUT_TRACEABILITY_WIDTHS_CA,
    "INPUT_TRACEABILITY_WIDTHS_NON_CA": svc.INPUT_TRACEABILITY_WIDTHS_NON_CA,
}


class ColumnFitTests(SimpleTestCase):
    def test_every_table_fits_the_printable_frame(self):
        for name, widths in WIDTH_LISTS.items():
            with self.subTest(table=name):
                total = sum(widths)
                self.assertLessEqual(
                    round(total, 4),
                    FRAME_WIDTH,
                    f"{name} totals {total / inch:.2f}in against a {FRAME_WIDTH / inch:.2f}in "
                    f"frame — ReportLab will squeeze every column to compensate.",
                )

    def test_identifier_columns_fit_their_worst_case_token(self):
        """The rule that was being asserted but never checked."""
        for name, columns in svc.IDENTIFIER_COLUMNS.items():
            widths = WIDTH_LISTS[name]
            for index, label in columns.items():
                with self.subTest(table=name, column=label):
                    token = WORST_CASE_TOKENS[label]
                    needed = stringWidth(token, CELL_FONT, CELL_FONT_SIZE) + CELL_PADDING
                    self.assertGreaterEqual(
                        widths[index],
                        needed,
                        f"{name}[{index}] ({label}) is {widths[index] / inch:.3f}in but "
                        f'"{token}" needs {needed / inch:.3f}in. ReportLab will SPLIT the '
                        f"token mid-value rather than overflow, so the cell will show a "
                        f"different identifier than the one on file.",
                    )

    def test_every_column_fits_its_own_header_word(self):
        """Headers are atomic too — and they are BOLD.

        A header is a single developer-authored word per line; it cannot wrap gracefully, so
        "Qty Purchased" rendering as "Qty Purchas / ed" is the same defect as a split invoice
        number. This nearly recurred on 2026-08-18: two columns were sized from a
        REGULAR-weight measurement of "Purchased" (0.47in) when the header actually draws at
        0.52in bold, leaving them 0.01in short.

        Checks the widest single word, not the whole header — multi-word headers are expected
        to wrap between words.
        """
        for name, headers in svc.TABLE_HEADERS.items():
            widths = WIDTH_LISTS[name]
            self.assertEqual(
                len(headers),
                len(widths),
                f"{name} has {len(widths)} columns but {len(headers)} headers — the guard "
                f"would be comparing the wrong pairs.",
            )
            for index, (width, header) in enumerate(zip(widths, headers)):
                widest_word = max(stringWidth(w, HEADER_FONT, CELL_FONT_SIZE) for w in header.split())
                with self.subTest(table=name, column=header):
                    self.assertGreaterEqual(
                        width,
                        widest_word + CELL_PADDING,
                        f"{name}[{index}] ({header}) is {width / inch:.3f}in but its widest "
                        f"header word needs {(widest_word + CELL_PADDING) / inch:.3f}in in bold.",
                    )

    def test_the_identifier_index_map_matches_the_lists(self):
        """Guards the guard: an index that points past the end tests nothing.

        If a column is inserted and IDENTIFIER_COLUMNS is not updated, the indices silently
        start describing the wrong columns — and the assertions above would keep passing while
        measuring a prose column.
        """
        for name, columns in svc.IDENTIFIER_COLUMNS.items():
            widths = WIDTH_LISTS[name]
            headers = svc.TABLE_HEADERS[name]
            for index, label in columns.items():
                with self.subTest(table=name, column=label):
                    self.assertLess(index, len(widths), f"{name} has no column {index}")
                    self.assertIn(label, WORST_CASE_TOKENS, f"no worst-case token for '{label}'")
                    # The map must describe the SAME column the header list does. Bounds
                    # alone are not enough: inserting a column shifts every later index, and
                    # the assertions above would keep passing while silently measuring a
                    # prose column against an identifier token.
                    self.assertEqual(
                        headers[index],
                        label,
                        f"{name}[{index}] is '{headers[index]}' but IDENTIFIER_COLUMNS calls "
                        f"it '{label}' — a column was inserted without updating the map.",
                    )

    def test_the_two_traceability_variants_stay_in_lockstep(self):
        """CA is the non-CA table plus one column, and nothing else.

        The render code builds one header list and appends "CA DPR Permit" for California, so
        any other difference between the two width lists means one of them no longer matches
        what is drawn. This is the shape of the defect found on 2026-08-18: the non-CA list
        carried EIGHT widths against NINE headers, because "Cert #" was appended
        unconditionally by the builder but never given a width.
        """
        ca_headers = svc.TABLE_HEADERS["INPUT_TRACEABILITY_WIDTHS_CA"]
        non_ca_headers = svc.TABLE_HEADERS["INPUT_TRACEABILITY_WIDTHS_NON_CA"]
        self.assertEqual(ca_headers, non_ca_headers + ["CA DPR Permit"])
        self.assertEqual(
            len(svc.INPUT_TRACEABILITY_WIDTHS_CA),
            len(svc.INPUT_TRACEABILITY_WIDTHS_NON_CA) + 1,
        )

    def test_prose_columns_are_not_claimed_as_identifiers(self):
        """Product / Supplier / Applicator wrap on word boundaries and must stay exempt.

        Listing one as an identifier would demand it fit its longest value on one line, which
        for "Neptune's Harvest Organic Fish and Seaweed Fertilizer 2-3-1" is absurd and would
        push the table past the frame.
        """
        claimed = {label for columns in svc.IDENTIFIER_COLUMNS.values() for label in columns.values()}
        for prose in ("Product", "Supplier", "Applicator", "Type"):
            self.assertNotIn(prose, claimed)
