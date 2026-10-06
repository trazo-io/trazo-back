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

    # -- Run 8 (R8-28, Astra 2026-10-05): a 263-page recipient dossier had no outline, and its
    # Contents named productions without page numbers. Red before the change.

    @staticmethod
    def _outline(data):
        import io

        from pdfminer.pdfdocument import PDFDocument, PDFNoOutlines
        from pdfminer.pdfparser import PDFParser

        doc = PDFDocument(PDFParser(io.BytesIO(data)))
        try:
            return [(level, title) for level, title, *_ in doc.get_outlines()]
        except PDFNoOutlines:
            return []

    @staticmethod
    def _pages(data):
        import io
        import re

        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextContainer

        return [
            re.sub(r"\s+", " ", " ".join(el.get_text() for el in page if isinstance(el, LTTextContainer)))
            for page in extract_pages(io.BytesIO(data))
        ]

    def test_the_dossier_has_an_outline_with_every_parcel_and_production(self):
        data = OperationAuditExportService(self.establishment, certification_type="organic").generate_pdf().getvalue()
        outline = self._outline(data)
        top = [t for level, t in outline if level == 1]
        self.assertIn("Operation-Wide Records", top)
        self.assertIn("Parcel — Block A", top)
        self.assertIn("Parcel — Block B", top)
        productions = [t for level, t in outline if level == 2 and t.startswith("Production — ")]
        self.assertEqual(len(productions), 3, outline)
        self.assertTrue(any(level == 3 for level, _ in outline), "no section nested under a production")

    def test_contents_gives_the_page_each_production_starts_on(self):
        data = OperationAuditExportService(self.establishment, certification_type="organic").generate_pdf().getvalue()
        pages = self._pages(data)
        contents = next(p for p in pages if "Contents" in p and "Production Window" in p)
        starts = [i + 1 for i, p in enumerate(pages) if "Production — Navel Orange" in p]
        self.assertEqual(len(starts), 3)
        for page_no in starts:
            self.assertRegex(contents, rf"(?<!\d){page_no}(?!\d)", f"Contents does not name page {page_no}")
        self.assertNotIn("Page \u2014", contents)

    def test_a_production_export_has_an_outline_too(self):
        from history.services.audit_export_service import AuditExportService

        data = AuditExportService(self.p1, certification_type="organic").generate_pdf(strict_ofpp=False).getvalue()
        self.assertGreater(len(self._outline(data)), 3)

    def test_readiness_rows_carry_a_stable_key(self):
        from history.services.audit_export_service import AuditExportService, readiness_row_key

        rows = AuditExportService(self.p1, certification_type="organic").compliance_snapshot_rows()
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row.get("row_key"), readiness_row_key(row["label"]))
            self.assertRegex(row.get("row_key") or "", r"^[a-z0-9_]+$")
        self.assertEqual(
            readiness_row_key("Record completeness \u2014 chemical (\u00a7 205.103(b)(2))"),
            "record_completeness_chemical",
        )
        self.assertEqual(readiness_row_key("Raw manure interval (\u00a7 205.203(c)(1)(iii))"), "raw_manure_interval")


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
        # The operation dossier is a Compliance artifact (2026-08-14, subscriptions/gating.py).
        # Only the VICTIM company is subscribed: the cross-tenant case must still be denied by
        # tenant isolation, not by company A happening to lack a plan.
        from subscriptions.testing import grant_compliance_exports

        grant_compliance_exports(self.company_b)

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
