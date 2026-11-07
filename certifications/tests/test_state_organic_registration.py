"""
State Organic Program (CDFA SOP) producer-registration tests
(2026-06 NOP-alignment audit, P0 A1).

CA producers selling > $5,000/yr organic must register annually with the CDFA
State Organic Program before their first organic sale (CA Food & Ag Code
§§ 46000-46029) — distinct from CDFA OIM input-material registration, which was
the only thing Trazo modeled before. These tests cover the model's currency
logic, the serializer round-trip, and the certifier audit-export section
(missing / current / expired).
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from reportlab.platypus import Table

from certifications.models import StateOrganicRegistration
from certifications.serializers import StateOrganicRegistrationSerializer
from company.models import Company, Establishment
from history.models import History
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


def _para_text(elements):
    """Join the text of every flowable that carries a .text (Paragraphs)."""
    return " ".join(getattr(el, "text", "") or "" for el in elements)


def _has_table(elements):
    return any(isinstance(el, Table) for el in elements)


class StateOrganicRegistrationModelTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="SOP Farm")
        self.establishment = Establishment.objects.create(name="SOP1", company=self.company)

    def _reg(self, **kw):
        defaults = dict(establishment=self.establishment, status="registered")
        defaults.update(kw)
        return StateOrganicRegistration.objects.create(**defaults)

    def test_is_current_registered_future_renewal(self):
        reg = self._reg(renewal_date=timezone.now().date() + timedelta(days=200))
        self.assertTrue(reg.is_current)

    def test_is_current_registered_no_renewal(self):
        reg = self._reg(renewal_date=None)
        self.assertTrue(reg.is_current)

    def test_not_current_registered_past_renewal(self):
        reg = self._reg(renewal_date=timezone.now().date() - timedelta(days=1))
        self.assertFalse(reg.is_current)

    def test_not_current_pending(self):
        reg = self._reg(status="pending")
        self.assertFalse(reg.is_current)

    def test_exempt_with_its_registration_number_is_current(self):
        reg = self._reg(status="exempt", registration_number="12-123456")
        self.assertTrue(reg.is_current)

    def test_exempt_without_a_registration_number_is_not_current(self):
        """Food & Agr. Code § 46013.1(a): exempt from certification only, still required to register."""
        reg = self._reg(status="exempt")
        self.assertFalse(reg.is_current)


class StateOrganicRegistrationSerializerTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="SOP Farm")
        self.establishment = Establishment.objects.create(name="SOP1", company=self.company)

    def test_create_and_is_current_exposed(self):
        data = {
            "establishment": self.establishment.id,
            "state": "CA",
            "operation_type": "producer",
            "status": "registered",
            "registration_number": "TUL-2026-0042",
            "county": "Tulare",
            "commodities": ["Navel orange", "Lemon"],
            "prior_year_organic_gross_sales": "125000.00",
            "registration_date": (timezone.now().date() - timedelta(days=30)).isoformat(),
            "renewal_date": (timezone.now().date() + timedelta(days=200)).isoformat(),
        }
        ser = StateOrganicRegistrationSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)
        reg = ser.save()
        self.assertEqual(reg.registration_number, "TUL-2026-0042")
        out = StateOrganicRegistrationSerializer(reg).data
        self.assertTrue(out["is_current"])
        self.assertEqual(out["status_display"], "Registered")
        self.assertEqual(out["operation_type_display"], "Producer / Grower")
        self.assertEqual(out["commodities"], ["Navel orange", "Lemon"])


class StateOrganicRegistrationExportSectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="sopexport@test.com", password="x")
        self.company = Company.objects.create(name="SOP Export Farm")
        self.establishment = Establishment.objects.create(name="SOP-E1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="SOP-P", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = History.objects.create(
            name="SOP Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _section(self):
        svc = AuditExportService(self.history, certification_type="organic")
        return svc._build_state_organic_registration_section()

    def test_missing_registration_fires_review_flag(self):
        text = _para_text(self._section())
        self.assertIn("[REVIEW] CDFA State Organic Program", text)

    def test_current_registration_renders_table_no_review(self):
        StateOrganicRegistration.objects.create(
            establishment=self.establishment,
            status="registered",
            registration_number="TUL-2026-0042",
            county="Tulare",
            commodities=["Navel orange"],
            registration_date=timezone.now().date() - timedelta(days=30),
            renewal_date=timezone.now().date() + timedelta(days=200),
        )
        elements = self._section()
        self.assertTrue(_has_table(elements))
        self.assertNotIn("[REVIEW]", _para_text(elements))

    def test_expired_registration_fires_review_flag(self):
        StateOrganicRegistration.objects.create(
            establishment=self.establishment,
            status="registered",
            registration_number="TUL-2025-0001",
            registration_date=timezone.now().date() - timedelta(days=400),
            renewal_date=timezone.now().date() - timedelta(days=10),
        )
        text = _para_text(self._section())
        self.assertIn("[REVIEW] CDFA State Organic Program", text)

    def test_non_ca_operation_does_not_fire_review_flag(self):
        """A known non-CA organic operation with no CDFA registration must NOT get a
        false-positive CDFA REVIEW flag — the requirement is California state law."""
        self.establishment.state = "OR"
        self.establishment.save(update_fields=["state"])
        text = _para_text(self._section())
        self.assertNotIn("[REVIEW]", text)
        self.assertIn("may not apply", text)

    def test_exempt_over_5000_fires_threshold_flag(self):
        """An 'exempt' registration whose prior-year organic sales exceed $5,000 must
        flag that the exemption no longer applies (must register + certify)."""
        StateOrganicRegistration.objects.create(
            establishment=self.establishment,
            status="exempt",
            registration_number="EX-2026-1",
            county="Tulare",
            prior_year_organic_gross_sales="42000.00",
            registration_date=timezone.now().date() - timedelta(days=30),
        )
        text = _para_text(self._section())
        self.assertIn("$5,000 exemption exceeded", text)

    def test_exempt_under_5000_no_threshold_flag(self):
        StateOrganicRegistration.objects.create(
            establishment=self.establishment,
            status="exempt",
            registration_number="EX-2026-2",
            prior_year_organic_gross_sales="3000.00",
            registration_date=timezone.now().date() - timedelta(days=30),
        )
        text = _para_text(self._section())
        self.assertNotIn("exemption exceeded", text)

    def test_csv_organic_export_includes_state_registration_block(self):
        """The organic CSV certifier handoff must carry the CDFA SOP block (parity
        with the PDF), including the $5,000-exceeded flag."""
        StateOrganicRegistration.objects.create(
            establishment=self.establishment,
            status="exempt",
            registration_number="EX-CSV-1",
            county="Tulare",
            prior_year_organic_gross_sales="42000.00",
            registration_date=timezone.now().date() - timedelta(days=30),
        )
        svc = AuditExportService(self.history, certification_type="organic")
        csv_text = svc.generate_csv().read().decode("utf-8-sig")
        self.assertIn("STATE ORGANIC PROGRAM REGISTRATION", csv_text)
        self.assertIn("EX-CSV-1", csv_text)
        self.assertIn("$5,000 exemption exceeded", csv_text)

    def test_osp_record_inventory_counts_live_records(self):
        """The OSP (a)(4) record-inventory query must return real counts (guards
        against a wrong field name being silently swallowed to an empty appendix)."""
        from datetime import datetime

        from certifications.services.osp_pdf_snapshot import _record_inventory
        from history.models import ChemicalEvent

        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            date=timezone.make_aware(datetime(2026, 6, 15, 7, 0)),
        )
        inventory = _record_inventory(self.establishment)
        labels = {row[0]: row[1] for row in inventory}
        # self.history is one production record; the chemical event is one spray record.
        self.assertEqual(labels.get("Production records"), 1)
        self.assertEqual(labels.get("Chemical / spray records"), 1)
