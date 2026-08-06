"""
Operation-wide audit export — one combined dossier across all parcels × productions.
"""

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.services.operation_audit_export_service import OperationAuditExportService
from product.models import Parcel, Product
from users.models import User, WorksIn


class OperationAuditExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="op@test.com", password="x")
        self.company = Company.objects.create(name="Op Farm")
        self.establishment = Establishment.objects.create(name="Tres Robles", company=self.company, state="CA")
        self.product = Product.objects.create(name="Navel Orange")
        # Two parcels; parcel A has two productions, parcel B has one.
        self.parcel_a = Parcel.objects.create(name="Block A", establishment=self.establishment, area=20.0)
        self.parcel_b = Parcel.objects.create(name="Block B", establishment=self.establishment, area=15.0)
        self.p1 = self._history("A 2025-2026", self.parcel_a)
        self.p2 = self._history("A 2024-2025", self.parcel_a)
        self.p3 = self._history("B 2025-2026", self.parcel_b)
        # An event on p1 so production-level sections render real content.
        ChemicalEvent.objects.create(
            history=self.p1, type=ChemicalEvent.PESTICIDE, commercial_name="Entrust SC", date=timezone.now()
        )

    def _history(self, name, parcel):
        return History.objects.create(
            name=name,
            start_date=timezone.now(),
            product=self.product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def test_generates_combined_pdf_across_parcels_and_productions(self):
        svc = OperationAuditExportService(self.establishment, certification_type="organic")
        prods = svc._productions()
        self.assertEqual(len(prods), 3)
        self.assertEqual(len(svc._group_by_parcel(prods)), 2)  # two parcels
        data = svc.generate_pdf().getvalue()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn(b"%%EOF", data[-1024:])
        self.assertGreater(len(data), 2000)

    def test_empty_operation_emits_cover_only_pdf_without_crash(self):
        empty_est = Establishment.objects.create(name="Empty", company=self.company, state="CA")
        svc = OperationAuditExportService(empty_est, certification_type="organic")
        self.assertEqual(svc._productions(), [])
        data = svc.generate_pdf().getvalue()  # must NOT raise
        self.assertTrue(data.startswith(b"%PDF"))

    def test_all_cert_type_also_generates(self):
        svc = OperationAuditExportService(self.establishment, certification_type="all")
        data = svc.generate_pdf().getvalue()
        self.assertTrue(data.startswith(b"%PDF"))


class OperationAuditExportPermissionTests(TestCase):
    """The endpoint inherits CompanyNestedViewSet's tenant-scoped perms — a user who is NOT a
    member of the URL company must be denied (regression for the IDOR where an
    [IsAuthenticated] override let any logged-in user export any company's dossier)."""

    def setUp(self):
        self.client = APIClient()
        # Company A + its member.
        self.company_a = Company.objects.create(name="Company A")
        self.member = User.objects.create_user(email="member-a@test.com", password="x")
        WorksIn.objects.create(user=self.member, company=self.company_a, role=WorksIn.COMPANY_ADMIN)
        # Company B (the victim) + establishment.
        self.company_b = Company.objects.create(name="Company B")
        self.outsider = User.objects.create_user(email="outsider@test.com", password="x")
        self.est_b = Establishment.objects.create(name="B Farm", company=self.company_b, state="CA")

    def _url(self, company, est):
        return f"/api/companies/{company.id}/establishments/{est.id}/operation-audit-export/"

    def test_non_member_cannot_export_other_companys_operation(self):
        self.client.force_authenticate(user=self.member)  # member of A, NOT B
        resp = self.client.get(self._url(self.company_b, self.est_b))
        self.assertIn(resp.status_code, (403, 404), f"cross-tenant export was not denied: {resp.status_code}")

    def test_unauthenticated_is_denied(self):
        resp = self.client.get(self._url(self.company_b, self.est_b))
        self.assertIn(resp.status_code, (401, 403))

    def test_member_can_export_own_operation(self):
        WorksIn.objects.create(user=self.outsider, company=self.company_b, role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(user=self.outsider)
        resp = self.client.get(self._url(self.company_b, self.est_b))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
