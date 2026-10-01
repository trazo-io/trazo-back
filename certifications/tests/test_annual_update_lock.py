"""A § 205.406 filing hardens as it travels. It used to harden not at all.

WHAT WAS WRONG
--------------
`OSPAnnualUpdateViewSet` was a plain `ModelViewSet`: no `perform_update`, no state check. A
filing the certifier had already received could be rewritten freely — and `submitted_at` with
it, so the record of WHEN an operation continued its certification could be moved after the
fact, including backwards onto a date it was not filed.

It is the most consequential of the three OSP records — the one actually submitted at renewal —
and it had the weakest protection of the three:

  * event records        refuse a post-close edit with 423 and route it through /amend
  * change notifications freeze once `certifier_acknowledged_at` is set
  * annual updates       froze never

WHY THE MIDDLE STAGE STAYS OPEN
-------------------------------
Freezing on submission would be truer to the sibling and wrong in practice: certifiers routinely
ask for a resubmission, and nothing in the product writes `certifier_acknowledged_at`, so a hard
freeze at submission would be a lock with no key. A submitted filing stays editable; what it
loses is the ability to move its own filing date, and every change is captured by auditlog,
which already registers this model.
WHY THE MIDDLE STAGE CLOSED (2026-10-01)
----------------------------------------
The open middle stage let the content of a FILED update change after filing, and document 02
was rendered from the live row, so the packet could no longer show what the agent received
(OSP alignment audit T20). A certifier's request for a resubmission is now a CORRECTION: the
next revision, signed and filed on its own, with the filed one kept byte for byte
(`test_annual_update_revisions`). The tiers are:

  draft   (not signed, not filed) -> editable and deletable
  signed  (signed_at set)         -> content edit 409, delete 423
  filed   (submitted_at set)      -> the same, plus a frozen document; withdrawn, never deleted

Filing state is never edited: `submitted_at` in a PATCH is refused outright, so a client that
believes it moved or cleared a filing date hears that it did not.
"""

from datetime import datetime
from datetime import timezone as dt_timezone

from rest_framework import status
from rest_framework.test import APITestCase

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from company.models import Company, Establishment
from users.models import User, WorksIn


class AnnualUpdateLockTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="lock@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Lock Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Lock Farm", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", created_by=self.user
        )
        self.client.force_authenticate(user=self.user)

    def _url(self, update):
        return f"/api/companies/{self.company.pk}/establishments/{self.est.pk}" f"/osp-annual-updates/{update.pk}/"

    def _make(self, submitted=None, acknowledged=None, signed=None, year=2026):
        return OSPAnnualUpdate.objects.create(
            prior_osp=self.osp,
            reporting_year=year,
            changes_summary="Grandevo added in February; hedgerow completed.",
            additions=[],
            deletions=[],
            submitted_at=submitted,
            signed_at=signed,
            certifier_acknowledged_at=acknowledged,
        )

    # -- draft ---------------------------------------------------------
    def test_a_draft_is_freely_editable(self):
        upd = self._make()
        res = self.client.patch(self._url(upd), {"changes_summary": "Reworded before filing."}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        upd.refresh_from_db()
        self.assertEqual(upd.changes_summary, "Reworded before filing.")

    def test_a_draft_can_be_deleted(self):
        upd = self._make()
        self.assertEqual(self.client.delete(self._url(upd)).status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(OSPAnnualUpdate.objects.filter(pk=upd.pk).exists())

    # -- signed --------------------------------------------------------
    def test_a_signed_draft_refuses_content_edits(self):
        upd = self._make(signed=datetime(2026, 8, 20, tzinfo=dt_timezone.utc))
        res = self.client.patch(self._url(upd), {"changes_summary": "Changed after signing."}, format="json")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        upd.refresh_from_db()
        self.assertIn("Grandevo", upd.changes_summary)

    # -- filed ---------------------------------------------------------
    def test_a_filed_update_refuses_content_edits(self):
        """Was the open middle stage: a filed update could be rewritten until acknowledged."""
        upd = self._make(submitted=datetime(2026, 8, 21, tzinfo=dt_timezone.utc))
        res = self.client.patch(
            self._url(upd), {"changes_summary": "Corrected at the certifier's request."}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(res.data["correctable"])
        upd.refresh_from_db()
        self.assertIn("Grandevo", upd.changes_summary, "a filed update was rewritten")

    def test_the_filing_date_cannot_be_moved_or_cleared_by_an_edit(self):
        """`submitted_at` was an ordinary writable field; then a validated one. Now the edit
        path does not carry it at all, on a draft or anywhere else."""
        upd = self._make()
        for value in ("2026-01-05T00:00:00Z", None):
            res = self.client.patch(self._url(upd), {"submitted_at": value}, format="json")
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("submitted_at", res.data)
        upd.refresh_from_db()
        self.assertIsNone(upd.submitted_at)

    def test_a_filed_update_cannot_be_deleted(self):
        """Was allowed before acknowledgement. Deleting erases the operation's own evidence that
        it filed for that year; a filing that should not stand is withdrawn instead."""
        upd = self._make(submitted=datetime(2026, 8, 21, tzinfo=dt_timezone.utc))
        res = self.client.delete(self._url(upd))
        self.assertEqual(res.status_code, status.HTTP_423_LOCKED)
        self.assertTrue(OSPAnnualUpdate.objects.filter(pk=upd.pk).exists())

    def test_an_acknowledged_filing_cannot_be_deleted(self):
        upd = self._make(
            submitted=datetime(2026, 8, 21, tzinfo=dt_timezone.utc),
            acknowledged=datetime(2026, 9, 3, tzinfo=dt_timezone.utc),
        )
        res = self.client.delete(self._url(upd))
        self.assertEqual(res.status_code, status.HTTP_423_LOCKED)
        self.assertTrue(OSPAnnualUpdate.objects.filter(pk=upd.pk).exists())

    def test_the_lock_message_names_the_state_and_the_way_forward(self):
        """A refusal that does not say what to do next is just a wall."""
        upd = self._make(submitted=datetime(2026, 8, 21, tzinfo=dt_timezone.utc))
        detail = self.client.patch(self._url(upd), {"changes_summary": "x"}, format="json").data["detail"]
        self.assertIn("2026-08-21", detail)
        self.assertIn("create a correction", detail)
