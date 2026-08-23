"""An OSP's status moves through its actions, never through a PATCH.

WHY THIS EXISTS
---------------
`OrganicSystemPlanSerializer` exposed `status` and `submitted_at` as ordinary writable fields.
`perform_update` only refuses edits to plans that have ALREADY left draft, so on a draft a
plain `PATCH {"status": "submitted"}` succeeded — and skipped everything the `submit` action
exists to do: the § 205.201(a) narrative floor, the module recompile, and the frozen
`submission_pdf`, which the submit docstring itself calls "the exact content the certifier
receives" and whose absence is "a silent gap the inspector can't detect". `activate` then
activated the snapshot-less plan without complaint.

Found 2026-08-23 by replaying a pilot's renewal through the API exactly as written: two
"submitted" plans, no snapshot on either, one of them active and approved.

The UI only ever PATCHes `sections`; nothing legitimate wrote status that way.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from certifications.models import OSP_SECTION_KEYS, OrganicSystemPlan
from company.models import Company, Establishment
from users.models import User, WorksIn


class OSPStatusNotPatchableTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="osp-status@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Status Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Status Farm", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            created_by=self.user,
            sections={k: {"narrative": ""} for k in OSP_SECTION_KEYS},
        )
        self.client.force_authenticate(user=self.user)
        self.url = f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{self.osp.pk}/"

    def test_patching_status_to_submitted_does_not_submit(self):
        """The bypass: a draft with EMPTY narratives must not become 'submitted' by PATCH."""
        res = self.client.patch(
            self.url, {"status": "submitted", "submitted_at": "2027-02-08T09:00:00Z"}, format="json"
        )
        # DRF ignores read-only fields rather than erroring, so the request itself is fine —
        # what matters is that nothing moved.
        self.assertIn(res.status_code, (status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST), res.data)
        self.osp.refresh_from_db()
        self.assertEqual(self.osp.status, "draft", "PATCH must not change an OSP's status")
        self.assertIsNone(self.osp.submitted_at, "PATCH must not set the filing date")
        self.assertFalse(bool(self.osp.submission_pdf), "no snapshot — so it must not read as submitted")

    def test_submit_action_still_enforces_the_narrative_floor(self):
        """The door the PATCH went around still works as the gate."""
        res = self.client.post(self.url + "submit/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.data)
        self.assertEqual(res.data.get("error"), "OSP is incomplete")
        self.osp.refresh_from_db()
        self.assertEqual(self.osp.status, "draft")

    def test_sections_remain_patchable_on_a_draft(self):
        """The one thing the UI does PATCH must keep working."""
        sections = {k: {"narrative": f"narrative for {k}"} for k in OSP_SECTION_KEYS}
        res = self.client.patch(self.url, {"sections": sections}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.osp.refresh_from_db()
        self.assertEqual(
            (
                self.osp.sections["recordkeeping_description"]["narrative_manual"]
                if "narrative_manual" in self.osp.sections["recordkeeping_description"]
                else self.osp.sections["recordkeeping_description"]["narrative"]
            ),
            "narrative for recordkeeping_description",
        )
