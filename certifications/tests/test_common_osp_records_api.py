"""
API tests for the Common OSP § 11 record-types endpoint.

GET  /api/companies/{c}/establishments/{e}/osps/{id}/record-types/
POST same URL — the operator's confirmation.

The endpoint exists to put § 11 evidence in front of a farmer WITHOUT answering § 11 for them.
Two properties matter more than any individual row and are pinned below:

  1. evidence never arrives pre-confirmed (§ 205.201(a): the producer authors the plan), and
  2. confirming is a company-scoped WRITE, so a read-only viewer or a non-member cannot assert
     anything on a farm's behalf.
"""

from datetime import date

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from company.models import Company, Establishment
from history.models import History, ProductionEvent
from product.models import Parcel, Product
from users.models import User, WorksIn


class CommonOSPRecordTypesAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Sierra Walnut Co")
        self.user = User.objects.create_user(email="grower@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        # `state` is load-bearing on this fixture — several compliance paths key off it.
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")
        self.client.force_authenticate(user=self.user)

    def _url(self, company=None, establishment=None, osp=None):
        company = company or self.company
        establishment = establishment or self.establishment
        osp = osp or self.osp
        return f"/api/companies/{company.id}/establishments/{establishment.id}/osps/{osp.id}/record-types/"

    def _add_harvest_event(self):
        # `start_date` is required in practice — History.__str__ formats it unconditionally, so
        # omitting it fails at save time inside Django's error reporting rather than at the DB.
        product = Product.objects.create(name="Walnut")
        parcel = Parcel.objects.create(name="Block 1", establishment=self.establishment, area=40.0)
        history = History.objects.create(
            name="2026 Season", parcel=parcel, product=product, start_date=date(2026, 3, 1)
        )
        ProductionEvent.objects.create(history=history, type="HA", date=date(2026, 9, 15))

    # --- GET -------------------------------------------------------------------------

    def test_get_returns_every_record_type_with_a_summary(self):
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertIn("summary", response.data)
        self.assertEqual(len(response.data["record_types"]), 38)
        # Verbatim USDA labels — the generated section must read like the certifier's form.
        labels = [r["label"] for r in response.data["record_types"]]
        self.assertIn("Shared equipment cleaning log", labels)

    def test_every_row_carries_a_cfr_citation(self):
        response = self.client.get(self._url())

        for row in response.data["record_types"]:
            self.assertRegex(row["cfr_cite"], r"^7 CFR 205\.")

    def test_evidence_is_derived_from_logged_events(self):
        before = self._row(self.client.get(self._url()), "harvest_records")
        self.assertEqual(before["status"], "not_evidenced_in_trazo")

        self._add_harvest_event()

        after = self._row(self.client.get(self._url()), "harvest_records")
        self.assertEqual(after["status"], "evidenced_in_trazo")
        self.assertEqual(after["count"], 1)

    def test_no_row_reports_a_failed_evidence_check(self):
        """A broken evidence rule must never masquerade as 'no records found'."""
        self._add_harvest_event()
        response = self.client.get(self._url())

        broken = [r["key"] for r in response.data["record_types"] if r["status"] == "evidence_check_failed"]
        self.assertEqual(broken, [])

    # --- 🔴 the boundary ---------------------------------------------------------------

    def test_evidence_is_never_returned_pre_confirmed(self):
        """§ 205.201(a) — the producer authors the plan. Trazo observing records is not the
        operator asserting they maintain them."""
        self._add_harvest_event()
        row = self._row(self.client.get(self._url()), "harvest_records")

        self.assertEqual(row["status"], "evidenced_in_trazo")
        self.assertFalse(row["confirmed"])
        self.assertTrue(row["suggested"], "evidenced-but-unconfirmed must be a suggestion")

    def test_summary_exposes_no_score_grade_or_percentage(self):
        response = self.client.get(self._url())

        for key in response.data["summary"]:
            for banned in ("score", "grade", "percent", "complete", "compliant"):
                self.assertNotIn(banned, key.lower())

    # --- POST ------------------------------------------------------------------------

    def test_post_records_the_operators_confirmation(self):
        response = self.client.post(self._url(), {"keys": ["harvest_records"]}, format="json")

        self.assertEqual(response.status_code, 200)
        row = self._row(response, "harvest_records")
        self.assertTrue(row["confirmed"])
        self.assertFalse(row["suggested"], "a confirmed row is an answer, not a suggestion")
        self.assertIsNotNone(row["confirmed_at"])

    def test_operator_may_confirm_a_record_type_trazo_cannot_see(self):
        """Weigh tickets live in a drawer. The operator's word is the answer, not our evidence."""
        response = self.client.post(self._url(), {"keys": ["weigh_tickets"]}, format="json")

        row = self._row(response, "weigh_tickets")
        self.assertTrue(row["confirmed"])
        self.assertEqual(row["status"], "not_evidenced_in_trazo")

    def test_post_can_unconfirm(self):
        self.client.post(self._url(), {"keys": ["harvest_records"]}, format="json")
        response = self.client.post(self._url(), {"keys": ["harvest_records"], "confirmed": False}, format="json")

        self.assertFalse(self._row(response, "harvest_records")["confirmed"])

    def test_unknown_key_is_rejected_rather_than_silently_ignored(self):
        """The service ignores unknown keys (forward compatibility); the API must not — a typo
        from a client should surface, not vanish into a no-op the caller reads as success."""
        response = self.client.post(self._url(), {"keys": ["not_a_record_type"]}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_empty_or_malformed_keys_rejected(self):
        self.assertEqual(self.client.post(self._url(), {"keys": []}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self._url(), {}, format="json").status_code, 400)

    def test_confirmed_flag_must_be_boolean(self):
        response = self.client.post(self._url(), {"keys": ["harvest_records"], "confirmed": "yes"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_confirmation_does_not_clobber_other_osp_sections(self):
        self.osp.sections["practices_procedures"] = {"narrative": "Keep me", "last_updated": None}
        self.osp.save(update_fields=["sections"])

        self.client.post(self._url(), {"keys": ["harvest_records"]}, format="json")

        self.osp.refresh_from_db()
        self.assertEqual(self.osp.sections["practices_procedures"]["narrative"], "Keep me")

    def test_cannot_confirm_on_a_submitted_plan(self):
        """A submitted plan is what the certifier already received. Confirming a § 11 box on it
        would silently change that record — the panel disables the controls, and the API must
        not rely on the UI to enforce it."""
        self.osp.status = "submitted"
        self.osp.save(update_fields=["status"])

        response = self.client.post(self._url(), {"keys": ["harvest_records"]}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.data)

    def test_cannot_confirm_on_a_superseded_plan(self):
        self.osp.status = "superseded"
        self.osp.save(update_fields=["status"])

        self.assertEqual(self.client.post(self._url(), {"keys": ["harvest_records"]}, format="json").status_code, 400)

    def test_active_plan_remains_confirmable(self):
        """An active plan is the live one — the operator keeps maintaining it through the year."""
        self.osp.status = "active"
        self.osp.save(update_fields=["status"])

        response = self.client.post(self._url(), {"keys": ["harvest_records"]}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._row(response, "harvest_records")["confirmed"])

    def test_reading_a_submitted_plan_still_works(self):
        """Read-only access must survive: the certifier packet still needs to show the answers."""
        self.osp.status = "submitted"
        self.osp.save(update_fields=["status"])

        self.assertEqual(self.client.get(self._url()).status_code, 200)

    # --- tenancy ---------------------------------------------------------------------

    def test_non_member_cannot_read_another_companys_record_types(self):
        other_company = Company.objects.create(name="Other Co")
        other_est = Establishment.objects.create(name="Other Farm", company=other_company, state="CA")
        other_osp = OrganicSystemPlan.objects.create(establishment=other_est, version_number=1, status="draft")

        response = self.client.get(self._url(other_company, other_est, other_osp))

        self.assertIn(response.status_code, (403, 404))

    def test_read_only_viewer_cannot_confirm(self):
        """Confirming is an attestation to a certifier — it must require write access."""
        viewer = User.objects.create_user(email="viewer@test.com", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.client.force_authenticate(user=viewer)

        response = self.client.post(self._url(), {"keys": ["harvest_records"]}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_read_or_confirm(self):
        self.client.force_authenticate(user=None)

        self.assertIn(self.client.get(self._url()).status_code, (401, 403))
        self.assertIn(
            self.client.post(self._url(), {"keys": ["harvest_records"]}, format="json").status_code,
            (401, 403),
        )

    # --- helper ----------------------------------------------------------------------

    def _row(self, response, key):
        return next(r for r in response.data["record_types"] if r["key"] == key)
