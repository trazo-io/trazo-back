"""The OSP section a certifier reads must not be cut off under a heading saying "verbatim".

The packet prints the six § 205.201(a) narratives under
"Section narratives — verbatim content filed with the certifier". Until 2026-08-19 they were
passed through a 2400-character cap, and a perfectly ordinary plan blew through it: four of six
sections on a walnut orchard ended mid-word — "Owl or raptor boxes …", "under §…",
"district o…". The plan is the single document the whole packet references; printing a
truncated copy of it and calling that verbatim is the worst place in the export to do so.

The cap itself is kept — a 500 KB paste would hang the renderer — but at a size no real
narrative reaches, and when it fires it says so instead of trailing an ellipsis that reads
like the end of a sentence.
"""

from django.test import TestCase

from history.services.audit_export_service import AuditExportService


class NarrativeTruncationTests(TestCase):
    def _svc(self):
        return AuditExportService.__new__(AuditExportService)

    def test_a_realistic_osp_section_is_rendered_whole(self):
        # The compiled module answers alone exceed the old 2400-char cap before an operator
        # writes a word; 4,300 is what this project's own demo farm produced for (a)(1).
        narrative = "Real narrative describing the practice in specific terms. " * 75
        self.assertGreater(len(narrative), 4000)

        rendered = self._svc()._safe_narrative(narrative)
        self.assertNotIn("…", rendered, "a real OSP section must not be abbreviated")
        self.assertNotIn("TRUNCATED", rendered)
        # every sentence survived
        self.assertEqual(rendered.count("Real narrative"), 75)

    def test_a_pathological_paste_is_still_capped_and_says_so(self):
        rendered = self._svc()._safe_narrative("x" * 60_000)
        self.assertIn("TRUNCATED FOR PRINT", rendered)
        self.assertIn("60,000 characters filed", rendered)
        self.assertLess(len(rendered), 60_000 + 500)

    def test_markup_is_still_escaped(self):
        rendered = self._svc()._safe_narrative("<script>alert(1)</script> & <b>x</b>")
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&amp;", rendered)
