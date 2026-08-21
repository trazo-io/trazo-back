"""Change-log actor identities wrap at the "@" and survive hostile characters.

Under § 205.103 this column IS the attribution, and ReportLab splits an unbroken token
wherever the column runs out — "paula.reyes@blueoakwalnut.e" over "xample" reads as a
different person with nothing marking the break.

The cell is a hand-built Paragraph, which is the shape that FAILS THE WHOLE EXPORT on an
unclosed tag, so the escaping is part of the contract, not a nicety.
"""

from django.test import SimpleTestCase

from history.services.audit_export_service import AuditExportService


class ActorCellTests(SimpleTestCase):
    def setUp(self):
        self.svc = AuditExportService.__new__(AuditExportService)
        self.svc._styles = AuditExportService._build_styles(self.svc)

    def _text(self, actor):
        return self.svc._actor_cell(actor).text

    def test_an_email_breaks_at_the_at_sign(self):
        self.assertEqual(
            self._text("paula.reyes@blueoakwalnut.example"),
            "paula.reyes<br/>@blueoakwalnut.example",
        )

    def test_a_non_email_actor_is_left_alone(self):
        self.assertIn("system (background task)", self._text("system (background task)"))

    def test_markup_in_an_address_cannot_break_the_export(self):
        text = self._text("bob&sons<b>@ranch<lot>.example")
        self.assertNotIn("<b>", text)
        self.assertIn("&amp;", text)
        self.assertIn("&lt;", text)

    def test_nothing_recorded_renders_the_dash_not_a_stray_at_sign(self):
        self.assertNotIn("@", self._text(""))
        self.assertNotIn("@", self._text(None))
