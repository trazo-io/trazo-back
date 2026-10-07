"""The signature on an annual update names the operation's responsible person; the account
that recorded it is stated apart (recordkeeping review S7, F-23, 2026-10-07).

The packet cover printed "Responsible person: Laurel Brandt" and document 02 printed
"Signed in Trazo by Pass Owner": the account's name, a fact about the session, printed as
the operation's attestation. The signer is now the farm profile's contact person (else the account), never a payload
value; the account stays in `signed_by`, and the PDF says "Recorded in Trazo by <account>" when the two differ.

Each test here went red on the code before the fix, on an assertion.
"""

import io

from pdfminer.high_level import extract_text
from rest_framework import status
from rest_framework.test import APITestCase

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from certifications.services.osp_module_pdf import render_filing_pdf
from company.models import Company, Establishment
from users.models import User, WorksIn


def _pdf_text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class AnnualUpdateSignerTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@test.com", password="x", is_verified=True, first_name="Pass", last_name="Owner"
        )
        self.company = Company.objects.create(name="Signer Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(
            name="Signer Farm", company=self.company, contact_person="Laurel Brandt"
        )
        self.v1 = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", created_by=self.user
        )
        self.client.force_authenticate(user=self.user)

    def _base(self):
        return f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osp-annual-updates/"

    def _draft(self, year=2026):
        res = self.client.post(
            self._base(),
            {"prior_osp": self.v1.pk, "reporting_year": year, "changes_summary": "Hedgerow planted."},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:300])
        return OSPAnnualUpdate.objects.get(pk=res.json()["id"])

    def _sign(self, filing, **payload):
        res = self.client.post(f"{self._base()}{filing.pk}/sign/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:300])
        filing.refresh_from_db()
        return filing

    def test_the_default_signer_is_the_responsible_person_and_the_account_is_the_recorder(self):
        filing = self._sign(self._draft(), signer_title="Owner")
        self.assertEqual(filing.signer_name, "Laurel Brandt")
        self.assertEqual(filing.signed_by, self.user)
        text = _pdf_text(render_filing_pdf(filing))
        self.assertIn("Signed in Trazo by Laurel Brandt, Owner on", text)
        self.assertIn("Recorded in Trazo by Pass Owner.", text)

    def test_the_payload_still_cannot_name_the_signer(self):
        # The name is read from the farm profile, never from the request (the existing guard in
        # test_annual_update_revisions holds): change it on the profile, not in the sign box.
        filing = self._sign(self._draft(2027), signer_name="Someone Else")
        self.assertEqual(filing.signer_name, "Laurel Brandt")
        self.assertEqual(filing.signed_by, self.user)

    def test_without_a_responsible_person_the_account_signs_and_no_recorder_line_is_printed(self):
        Establishment.objects.filter(pk=self.est.pk).update(contact_person="")
        filing = self._sign(self._draft(2028))
        self.assertEqual(filing.signer_name, "Pass Owner")
        text = _pdf_text(render_filing_pdf(filing))
        self.assertIn("Signed in Trazo by Pass Owner on", text)
        self.assertNotIn("Recorded in Trazo by", text)
