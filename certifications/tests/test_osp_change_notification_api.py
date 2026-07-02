"""
HTTP-level integration tests for the OSP change-notifications endpoint
(NOP 2615 / 7 CFR 205.400(f)):

    GET/POST /api/companies/{c}/establishments/{e}/osps/{osp}/change-notifications/

Covers the layer the model/serializer unit tests don't: the viewset action,
auth, company-scoped permission, created_by stamping, and GET round-trip.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan, OSPChangeNotification
from company.models import Company, Establishment
from users.models import User, WorksIn


class OSPChangeNotificationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="CN API Farm")
        self.user = User.objects.create_user(email="cn-api@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Main", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active"
        )
        # Second company for tenant-isolation check.
        self.other_company = Company.objects.create(name="Other Farm")
        self.other_user = User.objects.create_user(email="other@test.com", password="x")
        WorksIn.objects.create(user=self.other_user, company=self.other_company, role=WorksIn.COMPANY_ADMIN)

    def _url(self, company=None, est=None, osp=None):
        company = company or self.company
        est = est or self.est
        osp = osp or self.osp
        return f"/api/companies/{company.id}/establishments/{est.id}/osps/{osp.id}/change-notifications/"

    def test_member_can_create_and_created_by_is_stamped(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(
            self._url(),
            {
                "change_category": "acreage_field_addition",
                "description": "Added Block C to organic acreage.",
                "date_notified": "2026-03-01",
                "method": "written",
                "documentation_timing": "submitted_at_notification",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["cfr_reference"], "7 CFR 205.400(f)(2)")
        self.assertFalse(resp.data["is_immediate"])

        cn = OSPChangeNotification.objects.get(osp=self.osp)
        self.assertEqual(cn.change_category, "acreage_field_addition")
        self.assertEqual(cn.created_by, self.user)  # stamped from request.user
        self.assertEqual(cn.method, "written")

    def test_prohibited_substance_is_f1_immediate_over_api(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(
            self._url(),
            {
                "change_category": "prohibited_substance_application",
                "description": "Neighbor drift onto north buffer; reported same day.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["cfr_reference"], "7 CFR 205.400(f)(1)")
        self.assertTrue(resp.data["is_immediate"])

    def test_get_lists_notifications_newest_first(self):
        OSPChangeNotification.objects.create(
            osp=self.osp, change_category="field_removal", description="Older", date_notified="2026-01-01"
        )
        OSPChangeNotification.objects.create(
            osp=self.osp, change_category="new_retail_label", description="Newer", date_notified="2026-05-01"
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(resp.data), 2)
        self.assertEqual(resp.data[0]["description"], "Newer")  # ordering -date_notified

    def test_missing_category_is_rejected(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(
            self._url(), {"description": "no category"}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_non_member_cannot_create(self):
        # A user from another company must not write to this OSP's endpoint.
        self.client.force_authenticate(user=self.other_user)
        resp = self.client.post(
            self._url(),
            {"change_category": "field_removal", "description": "intrusion attempt"},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 404), resp.content)
        self.assertFalse(OSPChangeNotification.objects.filter(description="intrusion attempt").exists())
