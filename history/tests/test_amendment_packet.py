"""The corrections table an inspector reads (2026-08-18).

The packet's existing change-history section lists WHICH fields changed and never their
values — "application rate changed" answers nothing an inspector asked. A correction to a
filed record is precisely the case where the values are the point, so corrections get
their own table carrying the original, the correction and the reason.

These tests render the real PDF, because the failure mode here is a section that silently
does not appear.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from company.models import Company
from history.amendments import apply_amendment
from history.constants import PRODUCTION_EVENT_TYPE
from history.models import History, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Establishment, Parcel
from users.models import User, WorksIn


class AmendmentPacketTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Packet Co")
        self.user = User.objects.create_user(email="packet@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Packet Farm", company=company, state="CA")
        parcel = Parcel.objects.create(name="Packet Parcel", establishment=est, area=5)
        self.history = History.objects.create(
            parcel=parcel,
            name="2026",
            finish_date=timezone.now() - timedelta(days=1),
            lot_id="LOT-1",
        )
        self.event = ProductionEvent.objects.create(
            history=self.history, type="HA", date=timezone.now(), yield_quantity=200
        )

    def _rows(self):
        svc = AuditExportService(self.history, certification_type="all")
        return svc._amendments_table()

    def test_no_corrections_renders_nothing(self):
        """An empty 'Corrections' heading invites a question its emptiness already answers."""
        self.assertEqual(self._rows(), [])

    def test_correction_renders_both_values_and_the_reason(self):
        apply_amendment(
            event=self.event,
            event_type=PRODUCTION_EVENT_TYPE,
            field_name="yield_quantity",
            new_value="2000",
            reason="Transcription error: scale ticket reads 2,000 lb.",
            user=self.user,
        )
        elements = self._rows()
        self.assertTrue(elements, "corrections table did not render")

        # Flatten every string the table carries, the way an inspector reads it.
        text = self._flatten(elements)
        self.assertIn("200", text)
        self.assertIn("2000", text)
        self.assertIn("Transcription error", text)
        self.assertIn("packet@test.com", text)

    def test_blank_original_is_labelled_not_left_empty(self):
        self.event.performed_by = ""
        self.event.save(update_fields=["performed_by"])
        apply_amendment(
            event=self.event,
            event_type=PRODUCTION_EVENT_TYPE,
            field_name="performed_by",
            new_value="J. Alvarez",
            reason="Operator was not recorded at the time.",
            user=self.user,
        )
        self.assertIn("(blank)", self._flatten(self._rows()))

    def test_table_is_wired_into_the_change_history_section(self):
        """A correctly-built table that no section calls renders nowhere.

        Not asserted through generate_pdf(): that refuses this fixture on an unrelated
        precondition (no OFPP on file, SOE 7 CFR 205.201(a)(3)), which would make this
        test report on the OFPP guard rather than on the corrections table.
        """
        apply_amendment(
            event=self.event,
            event_type=PRODUCTION_EVENT_TYPE,
            field_name="yield_quantity",
            new_value="2000",
            reason="Transcription error.",
            user=self.user,
        )
        svc = AuditExportService(self.history, certification_type="all")
        text = self._flatten(svc._build_change_history_section())
        self.assertIn("Documented Corrections", text)
        self.assertIn("2000", text)

    def test_actor_is_named_even_without_a_profile_name(self):
        """get_full_name() is first + " " + last, so a nameless user yields " " — truthy.

        A naive `get_full_name() or email` recorded a blank actor for every user who had
        not filled in their name.
        """
        self.assertEqual(self.user.get_full_name().strip(), "")
        a = apply_amendment(
            event=self.event,
            event_type=PRODUCTION_EVENT_TYPE,
            field_name="yield_quantity",
            new_value="2000",
            reason="Transcription error.",
            user=self.user,
        )
        self.assertEqual(a.amended_by_name, "packet@test.com")
        self.assertIn("packet@test.com", self._flatten(self._rows()))

    def test_table_fits_the_page_frame(self):
        """Seven columns must sum to the 7.00in frame, not overflow the right margin.

        This shipped at 7.30in — 0.30in outside the printable area, so the "By" column
        printed off-page. Caught only by rendering and measuring; the same wrong premise
        was corrected elsewhere in this file on 2026-08-17, which is why it is pinned now.
        """
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate

        apply_amendment(
            event=self.event,
            event_type=PRODUCTION_EVENT_TYPE,
            field_name="yield_quantity",
            new_value="2000",
            reason="Transcription error.",
            user=self.user,
        )
        table = [el for el in self._rows() if hasattr(el, "_colWidths") or hasattr(el, "_argW")]
        self.assertTrue(table, "no Table element in the corrections section")
        widths = getattr(table[0], "_colWidths", None) or getattr(table[0], "_argW")

        doc = SimpleDocTemplate("/dev/null", pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch)
        self.assertLessEqual(round(sum(widths), 2), round(doc.width, 2))

    def test_record_column_names_the_record_not_its_primary_key(self):
        """ "Event #423" is a pk: an inspector cannot cross-reference it to the packet.

        The rest of the dossier identifies records by kind and date, so a correction has
        to as well, or it cannot be traced back to what it corrected.
        """
        apply_amendment(
            event=self.event,
            event_type=PRODUCTION_EVENT_TYPE,
            field_name="yield_quantity",
            new_value="2000",
            reason="Transcription error.",
            user=self.user,
        )
        text = self._flatten(self._rows())
        self.assertIn("Production", text)
        self.assertIn(self.event.date.strftime("%Y-%m-%d"), text)
        self.assertNotIn("Event #", text)

    def test_record_label_carries_no_markup(self):
        """`_cell` escapes values, so a "<br/>" in this label prints literally.

        Seen in a rendered proof as "Sales & compliance<br/>2025-10-17". The escaping is
        deliberate operator-input protection and must not be routed around.
        """
        apply_amendment(
            event=self.event,
            event_type=PRODUCTION_EVENT_TYPE,
            field_name="yield_quantity",
            new_value="2000",
            reason="Transcription error.",
            user=self.user,
        )
        text = self._flatten(self._rows())
        self.assertNotIn("<br", text)
        self.assertNotIn("&lt;br", text)

    def _flatten(self, elements):
        out = []
        for el in elements:
            for attr in ("text",):
                v = getattr(el, attr, None)
                if isinstance(v, str):
                    out.append(v)
            rows = getattr(el, "_cellvalues", None)
            if rows:
                for row in rows:
                    for cell in row:
                        t = getattr(cell, "text", None)
                        out.append(t if isinstance(t, str) else str(cell))
        return " ".join(out)
