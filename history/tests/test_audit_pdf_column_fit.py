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

from common.field_registry import AMOUNT_DETERMINATION, HARVEST_DESTINATION
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
    "Lot": "HAS-BLOCK2-20260410",
}

#: Headers render BOLD, which is wider than the regular face used for values. Sizing a column
#: from a regular-weight measurement leaves the header itself wrapping.
HEADER_FONT = "Helvetica-Bold"

WIDTH_LISTS = {
    "MASS_BALANCE_PURCHASE_WIDTHS": svc.MASS_BALANCE_PURCHASE_WIDTHS,
    "INPUT_TRACEABILITY_WIDTHS_CA": svc.INPUT_TRACEABILITY_WIDTHS_CA,
    "INPUT_TRACEABILITY_WIDTHS_NON_CA": svc.INPUT_TRACEABILITY_WIDTHS_NON_CA,
    # 2026-08-19: these three were inline literals inside their render methods, so nothing
    # here could reach them — and the Production Events Date column was splitting
    # "2026-02-04" into "2026-02-0" / "4" on every row of a live packet.
    "PRODUCTION_EVENT_WIDTHS_CARBON": svc.PRODUCTION_EVENT_WIDTHS_CARBON,
    "PRODUCTION_EVENT_WIDTHS_PLAIN": svc.PRODUCTION_EVENT_WIDTHS_PLAIN,
    "HARVEST_ANALYTICS_WIDTHS": svc.HARVEST_ANALYTICS_WIDTHS,
    "PEST_EVENT_WIDTHS": svc.PEST_EVENT_WIDTHS,
    # 2026-11-11: lifted out of `_build_chemical_log` (see WORST_CASE_WORDS below).
    "APPLICATION_LOG_WIDTHS_CERTIFIED": svc.APPLICATION_LOG_WIDTHS_CERTIFIED,
    "APPLICATION_LOG_WIDTHS_PLAIN": svc.APPLICATION_LOG_WIDTHS_PLAIN,
}

#: The widest single WORD each prose column of the application log prints, from real values:
#: the showcase farm's records, CHEMICAL_TYPE_LABELS and `_organic_basis_cell`. A prose column
#: wraps between words, but ReportLab SPLITS a word wider than the column, and on 2026-11-11 the
#: landing page's preview of this table read "hydroxi / de", "s / pinosad", "(Xanthomona / s"
#: and "grower-s / elected". Keyed by header so both variants are checked by the same list.
WORST_CASE_WORDS = {
    "Product": ["Naturalyte", "Fertilizer", "Seaweed"],
    "NPK / Conc.": ["hydroxide", "spinosad"],
    "Target / Purpose": ["(Xanthomonas", "orangeworm", "transitella)", "arboricola", "protectant"],
    "Organic Status": ["Organic-approved", "grower-selected,", "grower-reported", "Self-reported"],
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

    def test_prose_columns_hold_their_widest_word(self):
        """Prose wraps between words, never inside one.

        Columns that print a closed vocabulary take EVERY word of it from the source, not a
        hand-picked sample: the first cut listed three Method words, missed "incorporation",
        "Hand-placed" and "Fumigation", and passed while those split (review of back #390).
        """
        vocabularies = {
            "Type": svc.CHEMICAL_TYPE_LABELS.values(),
            "Method": svc.APPLICATION_METHOD_LABELS.values(),
        }
        words_for = {
            header: [*WORST_CASE_WORDS.get(header, []), *(w for label in labels for w in str(label).split())]
            for header, labels in vocabularies.items()
        }
        for name in ("APPLICATION_LOG_WIDTHS_CERTIFIED", "APPLICATION_LOG_WIDTHS_PLAIN"):
            widths = WIDTH_LISTS[name]
            for index, header in enumerate(svc.TABLE_HEADERS[name]):
                for word in words_for.get(header, WORST_CASE_WORDS.get(header, [])):
                    needed = stringWidth(word, CELL_FONT, CELL_FONT_SIZE) + CELL_PADDING
                    with self.subTest(table=name, column=header, word=word):
                        self.assertGreaterEqual(
                            widths[index],
                            needed,
                            f"{name}[{index}] ({header}) is {widths[index] / inch:.3f}in but "
                            f'"{word}" needs {needed / inch:.3f}in, so ReportLab splits it.',
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


class EveryTableInTheFileFitsTheFrameTests(SimpleTestCase):
    """The frame rule, applied to tables whose widths are still inline literals.

    The registered WIDTH_LISTS above are the tables whose columns carry atomic identifiers,
    and only those can be checked token-by-token. But `colWidths` is written inline at 20-odd
    other call sites, and an inline list is invisible to a constant-based guard — which is how
    the Production Events table sat 2.2pt under an ISO date and split every row of a live
    packet before anyone noticed.

    So this walks the module's own AST, finds every `Table(..., colWidths=[...])` whose
    elements are `N * inch` literals, and holds the one rule that applies to all of them:
    a table wider than the frame makes ReportLab squeeze EVERY column, so one careless
    addition silently narrows eleven other columns that were correct.
    """

    @staticmethod
    def _inches(node):
        import ast

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            parts = [node.left, node.right]
            nums = [p.value for p in parts if isinstance(p, ast.Constant) and isinstance(p.value, (int, float))]
            names = [p.id for p in parts if isinstance(p, ast.Name)]
            if len(nums) == 1 and names == ["inch"]:
                return nums[0]
        return None

    def test_no_inline_colwidths_list_exceeds_the_frame(self):
        import ast
        import io

        path = svc.__file__.replace(".pyc", ".py")
        tree = ast.parse(io.open(path, encoding="utf-8").read())

        checked = 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Table"):
                continue
            for kw in node.keywords:
                if kw.arg != "colWidths" or not isinstance(kw.value, ast.List):
                    continue
                values = [self._inches(e) for e in kw.value.elts]
                if any(v is None for v in values):
                    continue  # computed width — not something this guard can measure
                checked += 1
                total = sum(values)
                with self.subTest(line=node.lineno):
                    self.assertLessEqual(
                        round(total, 4),
                        7.0,
                        f"audit_export_service.py:{node.lineno} — a {len(values)}-column table "
                        f"totals {total:.2f}in against a 7.00in frame.",
                    )
        # If the walk stops finding tables, the guard has quietly stopped guarding.
        self.assertGreater(checked, 15, "AST walk found almost no inline colWidths lists — has the shape changed?")


class EnumColumnsFitTheirVocabularyTests(SimpleTestCase):
    """A column fed by a FIXED vocabulary can be sized exactly — so it must be.

    The pest table's Type column renders PEST_TYPE_LABELS and nothing else. At 0.52in it could
    not hold "Identification" (0.63in) or "Implementation" (0.75in), and a live packet printed
    "Pest Iden / tification" and "Threshold Assessm / ent". Unlike a product name or a farmer's
    note, there is no uncertainty here about what the cell will contain.
    """

    #: table name -> {column index: the label vocabulary it renders}
    ENUM_COLUMNS = {
        "PEST_EVENT_WIDTHS": {1: svc.PEST_TYPE_LABELS},
        "HARVEST_ANALYTICS_WIDTHS": {
            5: dict(AMOUNT_DETERMINATION),
            9: dict(HARVEST_DESTINATION),
        },
    }

    def test_every_enum_column_fits_its_widest_label_word(self):
        for name, columns in self.ENUM_COLUMNS.items():
            widths = WIDTH_LISTS[name]
            for index, labels in columns.items():
                for label in labels.values():
                    for word in str(label).split():
                        needed = stringWidth(word, CELL_FONT, CELL_FONT_SIZE) + CELL_PADDING
                        with self.subTest(table=name, column=index, word=word):
                            self.assertGreaterEqual(
                                widths[index],
                                needed,
                                f"{name}[{index}] is {widths[index] / inch:.3f}in but the label "
                                f'word "{word}" needs {needed / inch:.3f}in — ReportLab will '
                                f"split it mid-word.",
                            )
