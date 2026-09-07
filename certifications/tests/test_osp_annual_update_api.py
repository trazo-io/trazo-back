"""
HTTP-level tests for the § 205.406 annual-continuation endpoint:

    GET/POST /api/companies/{c}/establishments/{e}/osp-annual-updates/

Found by walking the pilot path as a new farmer (2026-07-30): filing the same
reporting year twice reached the database and returned a 500 IntegrityError page.
The UI guards against it, but that guard reads a client-side list — a second tab, a
retried request, or any non-UI caller bypassed it entirely.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from company.models import Company, Establishment
from users.models import User, WorksIn


class OSPAnnualUpdateAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="AU API Farm")
        self.user = User.objects.create_user(email="au-api@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Main", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")

        self.other_company = Company.objects.create(name="AU Other Farm")
        self.other_user = User.objects.create_user(email="au-other@test.com", password="x")
        WorksIn.objects.create(user=self.other_user, company=self.other_company, role=WorksIn.COMPANY_ADMIN)

    def _url(self, company=None, est=None):
        company = company or self.company
        est = est or self.est
        return f"/api/companies/{company.id}/establishments/{est.id}/osp-annual-updates/"

    def test_member_can_file_annual_update(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(
            self._url(),
            {
                "prior_osp": self.osp.id,
                "reporting_year": 2026,
                "changes_summary": "No material changes.",
                "sections_unchanged_attestation": {"practices_procedures": True},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content[:400])
        self.assertEqual(OSPAnnualUpdate.objects.filter(prior_osp=self.osp).count(), 1)

    def test_unchanged_recordkeeping_attestation_re_dates_carried_record_types(self):
        """The § 205.406(a)(1) filing IS the re-affirmation of carried § 11 answers.

        A renewal clones `sections`, so last year's § 11 ticks arrive marked
        `carried_from_version` — confirmed, but nobody has re-stated them this year. Attesting
        that the recordkeeping section is unchanged is that statement, dated, in the filing the
        regulation provides for. Without this hook the operator would have to say the same
        sentence twice, and the packet would keep printing "carried forward, not re-stated"
        after they had already said otherwise.
        """
        from certifications.services.common_osp_records import confirm, derive_record_types, mark_carried_forward

        confirm(self.osp, ["harvest_records"], user=self.user)
        self.osp.refresh_from_db()
        self.osp.sections = mark_carried_forward(self.osp.sections, 1)
        self.osp.save(update_fields=["sections"])

        self.client.force_authenticate(user=self.user)
        resp = self.client.post(
            self._url(),
            {
                "prior_osp": self.osp.id,
                "reporting_year": 2027,
                "changes_summary": "No material changes.",
                "sections_unchanged_attestation": {"recordkeeping_description": True},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content[:400])

        self.osp.refresh_from_db()
        row = next(r for r in derive_record_types(self.est, osp=self.osp) if r["key"] == "harvest_records")
        self.assertIsNone(row["carried_from_version"], "the attestation re-stated it for this year")
        self.assertTrue(row["confirmed"])

    def test_an_unchanged_attestation_cannot_confirm_a_record_type(self):
        """⛔ Re-dating an existing statement is not the same as making one.

        An operation that has confirmed nothing and files "recordkeeping unchanged" must end
        with nothing confirmed — otherwise the annual update would become the auto-attestation
        route the § 11 panel refuses at every other door.
        """
        from certifications.services.common_osp_records import derive_record_types

        self.client.force_authenticate(user=self.user)
        resp = self.client.post(
            self._url(),
            {
                "prior_osp": self.osp.id,
                "reporting_year": 2027,
                "sections_unchanged_attestation": {"recordkeeping_description": True},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content[:400])

        self.osp.refresh_from_db()
        confirmed = [r for r in derive_record_types(self.est, osp=self.osp) if r["confirmed"]]
        self.assertEqual(confirmed, [])

    def test_duplicate_year_returns_400_not_500(self):
        """The unique(prior_osp, reporting_year) constraint must surface as a field error."""
        self.client.force_authenticate(user=self.user)
        payload = {"prior_osp": self.osp.id, "reporting_year": 2026, "changes_summary": "first"}
        self.assertEqual(self.client.post(self._url(), payload, format="json").status_code, 201)

        resp = self.client.post(self._url(), {**payload, "changes_summary": "second"}, format="json")
        self.assertEqual(resp.status_code, 400, "duplicate year must be a validation error, not a 500")
        self.assertIn(b"already been filed", resp.content)
        self.assertEqual(OSPAnnualUpdate.objects.filter(prior_osp=self.osp).count(), 1)

    def test_editing_the_same_filing_does_not_trip_the_uniqueness_check(self):
        """A PATCH that keeps the year must not be rejected as a duplicate of itself."""
        self.client.force_authenticate(user=self.user)
        created = self.client.post(
            self._url(), {"prior_osp": self.osp.id, "reporting_year": 2026}, format="json"
        ).json()

        resp = self.client.patch(
            f"{self._url()}{created['id']}/",
            {"changes_summary": "revised narrative"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content[:400])

    def test_other_company_cannot_file_against_this_osp(self):
        self.client.force_authenticate(user=self.other_user)
        resp = self.client.post(
            self._url(),
            {"prior_osp": self.osp.id, "reporting_year": 2026},
            format="json",
        )
        self.assertIn(resp.status_code, (400, 403, 404), resp.content[:200])
        self.assertFalse(OSPAnnualUpdate.objects.filter(prior_osp=self.osp).exists())
