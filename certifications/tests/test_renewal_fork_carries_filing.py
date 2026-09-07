"""A renewal fork must carry the § 205.406(a) filing it was made under.

WHY THIS EXISTS
---------------
Found 2026-09-07 on the demo operation. The packet download exports the WORKING plan — the
highest-numbered draft — and a grower who had filed the year's annual update on 21 August
opened `02-annual-update.pdf` in the packet they were about to send and read:

    No § 205.406(a) annual update is on file for this plan version.

The filing existed. `OSPAnnualUpdate.new_osp` — "the version this update produced" — was never
written by the product: the annual update card posts `prior_osp` only, and `new-version` cloned
sections, module responses, three approved-input registries and the hand-typed
`PlanMaterialEntry` rows without ever linking the filing to the version it had just created. So
`_renewal_context`'s first lookup (the filing whose `new_osp` is this plan) was reachable only
from fixtures, its fallback (the filing whose `prior_osp` is this plan) missed by one version,
and the one document the renewal packet exists to carry came out blank — silently, on the
document that goes to the certifying agent.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from certifications.services.osp_module_pdf import _annual_update_pdf, _packet_cover_pdf
from company.models import Company, Establishment
from users.models import User, WorksIn

from .test_renewal_packet_contents import _pdf_text


class _ForkFarm(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Fork Farms LLC")
        self.user = User.objects.create_user(email="fork@test.com", password="x", first_name="Ada", last_name="Reyes")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Fork Home Ranch", company=self.company)
        self.v1 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        self.client.force_authenticate(user=self.user)

    def _fork(self, source):
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}" f"/osps/{source.id}/new-version/"
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 201, resp.content[:400])
        return OrganicSystemPlan.objects.get(pk=resp.json()["id"])


class ForkCarriesTheFilingTests(_ForkFarm):
    def test_fork_links_the_open_filing_to_the_version_it_produced(self):
        filing = OSPAnnualUpdate.objects.create(
            prior_osp=self.v1,
            reporting_year=2026,
            changes_summary="Muddy Creek buffer widened to 45 ft.",
        )
        v2 = self._fork(self.v1)
        filing.refresh_from_db()
        self.assertEqual(filing.new_osp_id, v2.id)

    def test_packet_for_the_forked_version_carries_the_filing(self):
        """The regression itself: the document the operator sends, read back."""
        OSPAnnualUpdate.objects.create(
            prior_osp=self.v1,
            reporting_year=2026,
            changes_summary="Muddy Creek buffer widened to 45 ft.",
            additions=["Grandevo WDG — OMRI listed"],
        )
        v2 = self._fork(self.v1)
        text = _pdf_text(_annual_update_pdf(v2))
        self.assertIn("reporting year 2026", text)
        self.assertIn("Muddy Creek buffer widened to 45 ft", text)
        self.assertIn("v1 to v2", text)
        self.assertNotIn("No § 205.406(a) annual update is on file", text)

    def test_a_filing_that_already_produced_a_version_is_not_repointed(self):
        """`new_osp` is the hinge between two versions. Re-pointing it moves history.

        v1 -> v2 was last year's renewal. Forking v3 off v2 this year must not rewrite that
        filing to claim it produced v3.
        """
        v2 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=2, status="active")
        last_year = OSPAnnualUpdate.objects.create(
            prior_osp=v2, new_osp=v2, reporting_year=2025, changes_summary="Prior year."
        )
        v3 = self._fork(v2)
        last_year.refresh_from_db()
        self.assertEqual(last_year.new_osp_id, v2.id)
        self.assertNotEqual(last_year.new_osp_id, v3.id)

    def test_only_one_filing_is_carried_when_several_are_open(self):
        """The newest reporting year is the one this fork is being made under."""
        old = OSPAnnualUpdate.objects.create(prior_osp=self.v1, reporting_year=2025)
        new = OSPAnnualUpdate.objects.create(prior_osp=self.v1, reporting_year=2026)
        v2 = self._fork(self.v1)
        old.refresh_from_db()
        new.refresh_from_db()
        self.assertEqual(new.new_osp_id, v2.id)
        self.assertIsNone(old.new_osp_id)


class FilingAfterTheForkStillNamesTheDraftTests(_ForkFarm):
    """The other order, and the hole that moving `prior_osp` off the draft would have opened.

    § 205.406(a)(1) asks for the changes "to the previous plan", so the filing references the
    version the certifier holds — not the draft being prepared. Fix only the fork side and a
    filing written AFTER the fork names no draft at all, and the packet for the version the
    operator actually sends goes blank again. Both orders have to end in the same record.
    """

    def _file(self, prior, year=2026, **extra):
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osp-annual-updates/"
        payload = {"prior_osp": prior.id, "reporting_year": year, "changes_summary": "Buffer widened."}
        payload.update(extra)
        resp = self.client.post(url, payload, format="json")
        return resp

    def test_filing_made_after_the_fork_links_to_the_open_draft(self):
        v2 = self._fork(self.v1)
        resp = self._file(self.v1)
        self.assertEqual(resp.status_code, 201, resp.content[:400])
        filing = OSPAnnualUpdate.objects.get(pk=resp.json()["id"])
        self.assertEqual(filing.new_osp_id, v2.id)

    def test_the_packet_for_that_draft_carries_it(self):
        """The regression, read back off the document. Same assertion as the fork-first test —
        which is the point: the operator's order of work must not change the record."""
        v2 = self._fork(self.v1)
        self._file(self.v1)
        text = _pdf_text(_annual_update_pdf(v2))
        self.assertIn("reporting year 2026", text)
        self.assertIn("v1 to v2", text)
        self.assertNotIn("No § 205.406(a) annual update is on file", text)

    def test_no_draft_open_leaves_the_filing_unlinked(self):
        """§ 205.406 explicitly allows a pure "no material changes" attestation, which produces
        no version. A null `new_osp` is that case, not missing data — never invent a link."""
        resp = self._file(self.v1)
        filing = OSPAnnualUpdate.objects.get(pk=resp.json()["id"])
        self.assertIsNone(filing.new_osp_id)

    def test_an_older_abandoned_draft_is_not_claimed(self):
        """A draft BELOW the plan being continued is a fork the operation walked away from.

        v2 was started and abandoned; v3 became the plan on file some other way. The 2026
        filing against v3 produces nothing yet, and must not reach backwards for v2.
        """
        OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="draft", previous_version=self.v1
        )
        v3 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=3, status="active")
        resp = self._file(v3)
        self.assertEqual(resp.status_code, 201, resp.content[:400])
        filing = OSPAnnualUpdate.objects.get(pk=resp.json()["id"])
        self.assertIsNone(filing.new_osp_id)


class FilingMustContinueThePlanOnFileTests(_ForkFarm):
    """A filing against a draft says "the changes to v4" about a plan nobody has seen.

    It read correctly on screen — the packet for v4 found it through the `prior_osp` branch —
    and was wrong in the lineage an inspector follows.
    """

    def _file(self, prior, year=2026):
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osp-annual-updates/"
        return self.client.post(
            url, {"prior_osp": prior.id, "reporting_year": year, "changes_summary": "x"}, format="json"
        )

    def test_a_draft_prior_osp_is_refused_when_a_filed_version_exists(self):
        draft = self._fork(self.v1)
        resp = self._file(draft)
        self.assertEqual(resp.status_code, 400, resp.content[:400])
        self.assertIn("prior_osp", resp.json())

    def test_the_plan_on_file_is_accepted(self):
        self._fork(self.v1)
        resp = self._file(self.v1)
        self.assertEqual(resp.status_code, 201, resp.content[:400])

    def test_an_operation_whose_only_plan_is_a_draft_may_still_file(self):
        """Not yet certified, so § 205.406 does not bind it — but refusing the row would leave
        it with no way to record one at all, and 13 such filings already exist."""
        est = Establishment.objects.create(name="First Season", company=self.company)
        draft = OrganicSystemPlan.objects.create(establishment=est, version_number=1, status="draft")
        url = f"/api/companies/{self.company.id}/establishments/{est.id}/osp-annual-updates/"
        resp = self.client.post(
            url, {"prior_osp": draft.id, "reporting_year": 2026, "changes_summary": "x"}, format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.content[:400])

    def test_an_existing_draft_backed_filing_can_still_be_edited(self):
        """Create-only. A row already on file is a record, not a form to re-validate."""
        draft = self._fork(self.v1)
        filing = OSPAnnualUpdate.objects.create(prior_osp=draft, reporting_year=2026)
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}" f"/osp-annual-updates/{filing.id}/"
        resp = self.client.patch(url, {"changes_summary": "Corrected."}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content[:400])


class EmptyFilingPageNamesWhatIsMissingTests(_ForkFarm):
    """ "No update on file" and "your update is recorded against v1" are different facts.

    Only the first is an action item, and printing it alone sent a grower who HAD filed looking
    for a filing they had already made.
    """

    def test_empty_page_names_the_version_it_belongs_to(self):
        v2 = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="draft", previous_version=self.v1
        )
        text = _pdf_text(_annual_update_pdf(v2))
        self.assertIn("No § 205.406(a) annual update is on file for OSP v2", text)
        self.assertIn("OSP v2 (draft — not yet submitted)", text)

    def test_empty_page_names_the_filing_that_does_exist(self):
        OSPAnnualUpdate.objects.create(prior_osp=self.v1, reporting_year=2026, changes_summary="x")
        v2 = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="draft", previous_version=self.v1
        )
        text = _pdf_text(_annual_update_pdf(v2))
        self.assertIn("2026 update", text)
        self.assertIn("recorded against v1", text)
        self.assertIn("It continues that year, not this plan version", text)

    def test_an_operation_that_never_filed_is_not_told_about_a_filing(self):
        v2 = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="draft", previous_version=self.v1
        )
        text = _pdf_text(_annual_update_pdf(v2))
        self.assertNotIn("most recent annual update on file", text)

    def test_another_operations_filing_is_never_named(self):
        other_company = Company.objects.create(name="Neighbour Farms LLC")
        other_est = Establishment.objects.create(name="Neighbour", company=other_company)
        other_v1 = OrganicSystemPlan.objects.create(establishment=other_est, version_number=1, status="active")
        OSPAnnualUpdate.objects.create(prior_osp=other_v1, reporting_year=2026, changes_summary="Theirs.")
        v2 = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="draft", previous_version=self.v1
        )
        text = _pdf_text(_annual_update_pdf(v2))
        self.assertNotIn("most recent annual update on file", text)


class DraftPacketSaysItIsADraftTests(_ForkFarm):
    """The packet button exports the version the operator is WORKING on — right during a
    renewal, and wrong to hand a certifier unlabelled. "Plan submitted: not yet submitted",
    eleven rows down the cover, is not a label."""

    def test_cover_marks_a_draft_version(self):
        v2 = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="draft", previous_version=self.v1
        )
        cover = _pdf_text(_packet_cover_pdf(v2))
        self.assertIn("This plan version is a draft and has not been submitted", cover)
        self.assertIn("OSP v2 (draft — not yet submitted)", cover)

    def test_cover_does_not_mark_a_plan_on_file(self):
        cover = _pdf_text(_packet_cover_pdf(self.v1))
        self.assertNotIn("This plan version is a draft", cover)
        self.assertIn("OSP v1 (active)", cover)
