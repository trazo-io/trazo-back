"""
Tenant-isolation regression for the certification viewsets.

The 5 cert viewsets (Certification / OSP / OSPAnnualUpdate / LandownerAffidavit /
StateOrganicRegistration) previously overrode get_permissions → [IsAuthenticated()] for write
actions, bypassing CompanyNestedViewSet's company-membership check. Combined with unvalidated
FK fields, any authenticated user could inject a record referencing another company's object.

Fix: (1) writes inherit the secure company-scoped perms (CA/FM member of the URL company);
(2) the payload FKs (prior_osp / parcel / establishment) are scoped to the URL establishment.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from company.models import Company, Establishment
from product.models import Parcel
from users.models import User, WorksIn


class CertViewSetTenantIsolationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Company A (the caller's org) — user is a Company Admin.
        self.company_a = Company.objects.create(name="Company A")
        self.user_a = User.objects.create_user(email="ca-a@test.com", password="x")
        WorksIn.objects.create(user=self.user_a, company=self.company_a, role=WorksIn.COMPANY_ADMIN)
        self.est_a = Establishment.objects.create(name="A Farm", company=self.company_a)
        self.osp_a = OrganicSystemPlan.objects.create(establishment=self.est_a, version_number=1, status="active")
        # Company B (the victim) — its own OSP, establishment, parcel.
        self.company_b = Company.objects.create(name="Company B")
        self.est_b = Establishment.objects.create(name="B Farm", company=self.company_b)
        self.osp_b = OrganicSystemPlan.objects.create(establishment=self.est_b, version_number=1, status="active")
        self.parcel_b = Parcel.objects.create(name="B Parcel", establishment=self.est_b, area=10.0)

    def _annual_url(self, company, est):
        return f"/api/companies/{company.id}/establishments/{est.id}/osp-annual-updates/"

    # --- Permission: non-member cannot write another company's endpoint ---
    def test_non_member_cannot_create_annual_update(self):
        self.client.force_authenticate(user=self.user_a)  # member of A only
        resp = self.client.post(
            self._annual_url(self.company_b, self.est_b),
            {"prior_osp": self.osp_b.id, "reporting_year": 2026},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 404), f"cross-company write not denied: {resp.status_code}")

    def test_viewer_cannot_create_annual_update(self):
        viewer = User.objects.create_user(email="viewer-a@test.com", password="x")
        WorksIn.objects.create(user=viewer, company=self.company_a, role=WorksIn.VIEWER)
        self.client.force_authenticate(user=viewer)
        resp = self.client.post(
            self._annual_url(self.company_a, self.est_a),
            {"prior_osp": self.osp_a.id, "reporting_year": 2026},
            format="json",
        )
        self.assertEqual(resp.status_code, 403, "read-only viewer was allowed to write")

    # --- FK scoping: a member of A cannot reference B's objects ---
    def test_cannot_reference_other_establishments_osp(self):
        self.client.force_authenticate(user=self.user_a)
        resp = self.client.post(
            self._annual_url(self.company_a, self.est_a),
            {"prior_osp": self.osp_b.id, "reporting_year": 2026},  # B's OSP, A's URL
            format="json",
        )
        self.assertEqual(resp.status_code, 400, "foreign prior_osp was accepted")

    def test_affidavit_cannot_reference_other_establishments_parcel(self):
        self.client.force_authenticate(user=self.user_a)
        url = f"/api/companies/{self.company_a.id}/establishments/{self.est_a.id}/affidavits/"
        resp = self.client.post(
            url,
            {"parcel": self.parcel_b.id, "previous_manager_name": "X"},  # B's parcel, A's URL
            format="json",
        )
        self.assertEqual(resp.status_code, 400, "foreign parcel was accepted")

    def test_registration_cannot_reference_other_establishment(self):
        self.client.force_authenticate(user=self.user_a)
        url = f"/api/companies/{self.company_a.id}/establishments/{self.est_a.id}/state-organic-registrations/"
        resp = self.client.post(
            url,
            {"establishment": self.est_b.id, "state": "CA", "operation_type": "producer", "status": "registered"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, "foreign establishment was accepted")

    # --- Positive: a member CAN file against their own establishment ---
    def test_member_can_create_own_annual_update(self):
        self.client.force_authenticate(user=self.user_a)
        resp = self.client.post(
            self._annual_url(self.company_a, self.est_a),
            {"prior_osp": self.osp_a.id, "reporting_year": 2026, "changes_summary": "No changes"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
