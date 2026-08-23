"""Every character that reaches a ReportLab Paragraph must be one Helvetica can draw.

ReportLab's base-14 Helvetica carries cp1252 and nothing else, and a character outside it is
not boxed or dropped — the glyph at that byte is drawn instead. Rendered and read back on
2026-08-23: "→" printed as "ﬁ", "≤" as "£", "✓" as "3", "✗" as "7", "≥" as "‡". A certifier read
"≤ 0.5 ac" as "£ 0.5 ac". `glyph_safe` sits in every XML-escape helper the PDF services use.
"""

import io

from django.test import SimpleTestCase

from common.pdf_text import glyph_safe


class GlyphSafeTests(SimpleTestCase):
    def test_meaningful_symbols_keep_their_meaning(self):
        self.assertEqual(glyph_safe("soft/overripe → WVF process"), "soft/overripe -> WVF process")
        self.assertEqual(
            glyph_safe("rows ≤ 0.5 ac, count ≥ 3, ≠ last year"), "rows <= 0.5 ac, count >= 3, != last year"
        )
        self.assertEqual(glyph_safe("✓ cleaned ✗ not sanitised"), "[x] cleaned [ ] not sanitised")
        self.assertEqual(glyph_safe("−2 °C"), "-2 °C")

    def test_cp1252_text_passes_through_untouched(self):
        text = "Añejo — 12 lb/ac … sown 9 Feb • 3½ in. • ±0.5 • €45 • Brandt’s “Duke”"
        self.assertEqual(glyph_safe(text), text)

    def test_pictographs_are_dropped_and_unknowns_become_a_visible_mark(self):
        self.assertEqual(glyph_safe("Sprayed 🚜 block 3"), "Sprayed  block 3")
        self.assertEqual(glyph_safe("Яблоко"), "??????")  # Cyrillic: visibly unknown, never a wrong glyph

    def test_ascii_is_the_fast_path_and_none_is_empty(self):
        self.assertEqual(glyph_safe("plain"), "plain")
        self.assertEqual(glyph_safe(None), "")
        self.assertEqual(glyph_safe(12.5), "12.5")

    def test_rendered_pdf_no_longer_carries_the_wrong_glyphs(self):
        """The proof is the page, not the string: render through the real escape helper."""
        from pdfminer.high_level import extract_text
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate

        from history.services.audit_export_service import _esc

        text = "colour break → Entrust; rows ≤ 0.5 ac; ✓ cleaned"
        buf = io.BytesIO()
        SimpleDocTemplate(buf, pagesize=letter).build([Paragraph(_esc(text), getSampleStyleSheet()["Normal"])])
        out = extract_text(io.BytesIO(buf.getvalue()))
        for wrong in ("ﬁ", "£", "3 cleaned"):
            self.assertNotIn(wrong, out)
        self.assertIn("colour break -> Entrust; rows <= 0.5 ac; [x] cleaned", " ".join(out.split()))
