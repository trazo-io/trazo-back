"""A setup operator enters a grower's records; it never signs or submits for the grower.

The pilot checklist told the operator "The grower checks them before anything is filed", and
nothing made it true. The operator account is a Company Admin like the grower, so it could:

    sign the annual update    `sign_filing` records the farm profile's contact person, the
                              grower, as the signer: a statement to the certifier in the
                              grower's name that the grower never made
    submit the OSP            freezes the PDF "the certifier receives"

Both are refused now, in the service for signing (every caller, before `default_signer_name` is
reached; review of back #176) and in the view for submit. Recording that a SIGNED revision was
filed stays open: by then the grower has signed it.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OSP_SECTION_KEYS, OrganicSystemPlan, OSPAnnualUpdate
from certifications.services.annual_update_filing import FilingStateError, sign_filing
from company.models import Company, Establishment
from users.models import User, WorksIn
from users.serializers import WorksInSerializer


class _PilotFarm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Attest Co")
        self.est = Establishment.objects.create(
            name="Attest Farm", company=self.company, contact_person="Laurel Brandt"
        )
        # The attached-account case: no setup suffix on the name, only the flag.
        self.operator = User.objects.create_user(
            email="oscar+attest@trazo.test", password="x", first_name="Oscar", last_name="Munoz"
        )
        self.grower = User.objects.create_user(
            email="laurel@farm.test", password="x", first_name="Laurel", last_name="Brandt"
        )
        WorksIn.objects.create(
            user=self.operator, company=self.company, role=WorksIn.COMPANY_ADMIN, is_setup_operator=True
        )
        WorksIn.objects.create(user=self.grower, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.client = APIClient()

    def _as(self, user):
        self.client.force_authenticate(user=user)


class AnnualUpdateSignTests(_PilotFarm):
    def setUp(self):
        super().setUp()
        self.v1 = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", created_by=self.operator
        )
        self.filing = OSPAnnualUpdate.objects.create(
            prior_osp=self.v1,
            reporting_year=2027,
            changes_summary="Hedgerow planted.",
            prior_plan_basis=OSPAnnualUpdate.PRIOR_BASIS_TRAZO_VERSION,
        )

    def _sign_url(self):
        return (
            f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/"
            f"osp-annual-updates/{self.filing.pk}/sign/"
        )

    def test_the_setup_operator_cannot_sign(self):
        self._as(self.operator)
        res = self.client.post(self._sign_url(), {}, format="json")
        self.assertEqual(res.status_code, 403, res.content[:300])
        self.assertIn("the grower signs in to their account", res.json()["error"])
        self.filing.refresh_from_db()
        self.assertIsNone(self.filing.signed_at)
        self.assertEqual(self.filing.signer_name, "")

    def test_the_grower_signs(self):
        self._as(self.grower)
        res = self.client.post(self._sign_url(), {}, format="json")
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.filing.refresh_from_db()
        self.assertEqual(self.filing.signed_by, self.grower)
        self.assertEqual(self.filing.signer_name, "Laurel Brandt")

    def test_the_service_refuses_for_every_caller(self):
        # Not only the view: a seeder or a future endpoint calling sign_filing is refused too.
        with self.assertRaises(FilingStateError) as ctx:
            sign_filing(self.filing, self.operator)
        self.assertEqual(ctx.exception.status_code, 403)


class OSPSubmitTests(_PilotFarm):
    def setUp(self):
        super().setUp()
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            sections={k: {"narrative": "", "last_updated": None} for k in OSP_SECTION_KEYS},
        )

    def _submit_url(self):
        return f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{self.osp.pk}/submit/"

    def test_the_setup_operator_cannot_submit(self):
        self._as(self.operator)
        res = self.client.post(self._submit_url())
        self.assertEqual(res.status_code, 403, res.content[:300])
        self.assertIn("submitting the Organic System Plan", res.json()["error"])
        self.osp.refresh_from_db()
        self.assertEqual(self.osp.status, "draft")

    def test_the_grower_reaches_the_submit_gate(self):
        # Empty sections: the ordinary refusal, which proves the grower got past the operator check.
        self._as(self.grower)
        res = self.client.post(self._submit_url())
        self.assertEqual(res.status_code, 400, res.content[:300])
        self.assertIn("missing_sections", res.json())


class MembershipPayloadTests(_PilotFarm):
    def test_the_app_is_told_which_account_is_the_setup_operator(self):
        self.assertTrue(WorksInSerializer(WorksIn.objects.get(user=self.operator)).data["is_setup_operator"])
        self.assertFalse(WorksInSerializer(WorksIn.objects.get(user=self.grower)).data["is_setup_operator"])
