"""An unanswered "certifier notified?" question is not a No (OV-RK-C15, 2026-11-25).

WHY. `GeneralEvent.certifier_notified` was a BooleanField with `default=False`, and the incident
form's switch rendered off when nobody touched it. A grower who logged a contamination incident
and skipped the question filed a dossier whose incident log said "No": the certifier was not
notified, an answer nobody gave and one § 205.400(f)(1) makes serious. The field now has three
states: True, False, and None for not answered. Rows stored before the change keep False.

HOW. The dossier's incident log cell and its CSV notes are rendered for each state. The model
default is asserted directly, because a default of False would make every check below pass on a
row the test never meant to answer.
"""

import csv
import io
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import GeneralEvent, Production
from history.services.audit_export_service import AuditExportService
from history.tests.test_pdf_field_coverage import flowable_text
from product.models import Parcel, Product
from users.models import User


class CertifierNotifiedHasThreeStates(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="rk-c15@test.com", password="x")
        company = Company.objects.create(name="RK C15 Farm")
        establishment = Establishment.objects.create(name="RK", company=company, state="WA")
        parcel = Parcel.objects.create(name="North", establishment=establishment, area=4.0)
        self.now = timezone.now()
        self.history = Production.objects.create(
            name="RK C15 season",
            start_date=self.now - timedelta(days=120),
            product=Product.objects.create(name="Apple"),
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _incident(self, **answer):
        return GeneralEvent.objects.create(
            history=self.history,
            date=self.now,
            name="Drift at the west fence",
            is_contamination_incident=True,
            contamination_source="spray_drift",
            corrective_action_taken="Rows 1-2 held from organic sale.",
            **answer,
        )

    def _service(self):
        return AuditExportService(self.history, certification_type="organic")

    def _incident_log_row(self):
        """The incident log's data row, read from the table that carries its header."""
        for el in self._service()._build_soe_compliance_section():
            rows = getattr(el, "_cellvalues", None) or []
            texts = [[getattr(c, "text", str(c)) for c in row] for row in rows]
            if texts and any("Corrective" in t for t in texts[0]) and len(texts) > 1:
                return texts[1]
        self.fail("the contamination incident log did not render")

    def _csv_incident_row(self):
        """The incident's row as a dict keyed by the CSV header, so a shifted column cannot pass."""
        rows = list(csv.reader(io.StringIO(self._service().generate_csv().getvalue().decode("utf-8-sig"))))
        start = next(i for i, r in enumerate(rows) if r[:2] == ["Date", "Event Category"])
        header = rows[start]
        incident = next(r for r in rows[start + 1 :] if len(r) > 1 and r[1] == "Contamination Incident")
        self.assertEqual(len(incident), len(header), "the incident row does not line up with the header")
        return dict(zip(header, incident))

    def _csv_notes(self):
        return self._csv_incident_row()["Notes"]

    def test_the_default_is_not_answered(self):
        self.assertIsNone(self._incident().certifier_notified)

    def test_an_unanswered_question_prints_not_answered(self):
        self._incident()
        self.assertEqual(self._incident_log_row()[-1], "Not answered")
        self.assertIn("Certifier notified: not answered", self._csv_notes())

    def test_a_no_still_prints_no(self):
        self._incident(certifier_notified=False)
        self.assertEqual(self._incident_log_row()[-1], "No")
        self.assertIn("Certifier notified: No", self._csv_notes())

    def test_a_yes_prints_the_date(self):
        self._incident(certifier_notified=True, certifier_notification_date=date(2026, 6, 2))
        cell = self._incident_log_row()[-1]
        self.assertTrue(cell.startswith("Yes ("), cell)
        self.assertNotIn("not answered", self._csv_notes())

    def test_the_incident_notes_land_in_the_notes_column(self):
        """The General row was one column short, so its notes printed under Carbon (dropped)."""
        self._incident(certifier_notified=False)
        row = self._csv_incident_row()
        self.assertIn("Source: Spray Drift from Adjacent Land", row["Notes"])
        self.assertIn("Rows 1-2 held from organic sale.", row["Notes"])
        self.assertEqual(row["Method"], "")

    def test_the_soe_section_is_read(self):
        """Non-vacuity: the helpers above must find a rendered section to read."""
        self._incident()
        self.assertIn("Contamination Incident Log", flowable_text(self._service()._build_soe_compliance_section()))
