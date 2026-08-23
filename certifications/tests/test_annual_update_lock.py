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

    def _make(self, submitted=None, acknowledged=None, year=2026):
        return OSPAnnualUpdate.objects.create(
            prior_osp=self.osp,
            reporting_year=year,
            changes_summary="Grandevo added in February; hedgerow completed.",
            additions=[],
            deletions=[],
            submitted_at=submitted,
            certifier_acknowledged_at=acknowledged,
        )

    # -- draft ---------------------------------------------------------
    def test_a_draft_is_freely_editable(self):
        upd = self._make()
        res = self.client.patch(self._url(upd), {"changes_summary": "Reworded before filing."}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        upd.refresh_from_db()
        self.assertEqual(upd.changes_summary, "Reworded before filing.")

    # -- submitted -----------------------------------------------------
    def test_a_submitted_filing_can_still_be_corrected(self):
        """The middle stage. A certifier asking for a correction must not hit a wall."""
        upd = self._make(submitted=datetime(2026, 8, 21, tzinfo=dt_timezone.utc))
        res = self.client.patch(
            self._url(upd), {"changes_summary": "Corrected at the certifier's request."}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    def test_the_filing_date_cannot_be_moved(self):
        """The regression. `submitted_at` was an ordinary writable field."""
        filed = datetime(2026, 8, 21, tzinfo=dt_timezone.utc)
        upd = self._make(submitted=filed)
        res = self.client.patch(self._url(upd), {"submitted_at": "2026-01-05T00:00:00Z"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("submitted_at", res.data)
        upd.refresh_from_db()
        self.assertEqual(upd.submitted_at, filed, "the filing date moved")

    def test_resending_the_same_filing_date_is_not_an_error(self):
        """A full PATCH echoes every field back. Rejecting an unchanged value would make the
        ordinary 'save again' path fail for no reason."""
        filed = datetime(2026, 8, 21, tzinfo=dt_timezone.utc)
        upd = self._make(submitted=filed)
        res = self.client.patch(
            self._url(upd),
            {"submitted_at": "2026-08-21T00:00:00Z", "changes_summary": "Edited."},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    def test_a_submitted_filing_can_be_withdrawn_to_draft(self):
        """Clearing the date is the withdraw path the sibling panel already allows before
        acknowledgment — not a date change."""
        upd = self._make(submitted=datetime(2026, 8, 21, tzinfo=dt_timezone.utc))
        res = self.client.patch(self._url(upd), {"submitted_at": None}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    # -- acknowledged --------------------------------------------------
    def test_an_acknowledged_filing_is_frozen(self):
        upd = self._make(
            submitted=datetime(2026, 8, 21, tzinfo=dt_timezone.utc),
            acknowledged=datetime(2026, 9, 3, tzinfo=dt_timezone.utc),
        )
        res = self.client.patch(self._url(upd), {"changes_summary": "Quietly rewritten."}, format="json")
        self.assertEqual(res.status_code, status.HTTP_423_LOCKED)
        self.assertFalse(res.data["correctable"])
        upd.refresh_from_db()
        self.assertIn("Grandevo", upd.changes_summary, "an acknowledged filing was rewritten")

    def test_an_acknowledged_filing_cannot_be_deleted(self):
        """Deleting would erase the operation's own evidence that it continued that year."""
        upd = self._make(
            submitted=datetime(2026, 8, 21, tzinfo=dt_timezone.utc),
            acknowledged=datetime(2026, 9, 3, tzinfo=dt_timezone.utc),
        )
        res = self.client.delete(self._url(upd))
        self.assertEqual(res.status_code, status.HTTP_423_LOCKED)
        self.assertTrue(OSPAnnualUpdate.objects.filter(pk=upd.pk).exists())

    def test_an_unacknowledged_filing_can_still_be_withdrawn(self):
        upd = self._make(submitted=datetime(2026, 8, 21, tzinfo=dt_timezone.utc))
        res = self.client.delete(self._url(upd))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(OSPAnnualUpdate.objects.filter(pk=upd.pk).exists())

    def test_the_lock_message_names_the_date_and_the_way_forward(self):
        """A 423 that does not say what to do next is just a wall."""
        upd = self._make(
            submitted=datetime(2026, 8, 21, tzinfo=dt_timezone.utc),
            acknowledged=datetime(2026, 9, 3, tzinfo=dt_timezone.utc),
        )
        detail = self.client.patch(self._url(upd), {"changes_summary": "x"}, format="json").data["detail"]
        self.assertIn("2026-09-03", detail)
        self.assertIn("file an update", detail)
