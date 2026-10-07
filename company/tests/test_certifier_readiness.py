"""`certifier-readiness` — the farm dashboard's headline.

Serves the same rows page 1 of the NOP audit PDF prints
(`AuditExportService.compliance_snapshot_rows`), so the dashboard and the certifier packet
cannot disagree. These tests pin the contract that makes that safe: same source, PASS rows
excluded, tenant-scoped, and readable by any role rather than write-gated.
"""

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import History, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class CertifierReadinessTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        # The view itself no longer caches (see the note in certifier_readiness — the old key
        # was keyed on a `updated_at` that event logging never writes). Kept because the test
        # settings share a cache, so DRF's per-IP throttle counters otherwise accumulate across
        # runs and turn these into order-dependent 429s.
        cache.clear()

        self.user = User.objects.create_user(email="readiness@test.com", password="x")
        self.company = Company.objects.create(name="Readiness Farm")
        # `state` is required: saving an event builds a USDAComplianceRecord whose `state`
        # column is NOT NULL with no default.
        self.establishment = Establishment.objects.create(name="R1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="RP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Walnuts")
        self.user.companies.add(self.company)

        self.finished = self._production(name="2025 season", finished=True)
        ProductionEvent.objects.create(history=self.finished, type="PL", date=timezone.now())

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _production(self, *, name, finished):
        return History.objects.create(
            name=name,
            start_date=timezone.now() - timezone.timedelta(days=200),
            finish_date=timezone.now() - timezone.timedelta(days=5) if finished else None,
            product=self.product,
            parcel=self.parcel,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=finished,
        )

    def _url(self, company_id=None, establishment_id=None):
        return "/api/companies/%s/establishments/%s/certifier-readiness/" % (
            company_id or self.company.id,
            establishment_id or self.establishment.id,
        )

    def test_returns_only_rows_needing_attention(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()

        self.assertGreater(body["checked_count"], 0, "no compliance rows were evaluated")
        self.assertEqual(body["outstanding_count"], len(body["findings"]))
        for finding in body["findings"]:
            self.assertIn(finding["status"], ("REVIEW", "FAIL"), "a PASS row was served as an action item")

    def test_matches_the_audit_pdf_rows_exactly(self):
        """One source of truth with the certifier packet — and one definition of "actionable".

        The card and the PDF read the same `compliance_snapshot_rows()`. They differ in what
        they SHOW, deliberately: the packet prints every row so a certifier can see what Trazo
        did and did not assess, while the card is a to-do list and only REVIEW / FAIL is
        something the grower can act on. `NA`, `NOT ASSESSED` and `INFO` are none of those —
        serving them as findings is the cry-wolf pattern that put amber on a farm with nothing
        to fix. The filter is `ACTIONABLE_READINESS_STATUSES` in company/views.py; this test
        used to spell it `!= "PASS"`, which quietly included all three.
        """
        from company.views import ACTIONABLE_READINESS_STATUSES

        expected = [
            r for r in AuditExportService(self.finished, certification_type="organic").compliance_snapshot_rows()
        ]
        body = self.client.get(self._url()).json()

        self.assertEqual(body["checked_count"], len(expected))
        self.assertEqual(
            [f["label"] for f in body["findings"]],
            [r["label"] for r in expected if r["status"] in ACTIONABLE_READINESS_STATUSES],
            "dashboard findings diverged from the audit export's snapshot rows",
        )
        # Guard the filter itself: a non-actionable row must never reach the card, and if the
        # fixture stops producing one this assertion says so rather than passing vacuously.
        non_actionable = [
            r for r in expected if r["status"] not in ACTIONABLE_READINESS_STATUSES and r["status"] != "PASS"
        ]
        self.assertTrue(non_actionable, "fixture no longer exercises a non-actionable status")
        served = {f["label"] for f in body["findings"]}
        for row in non_actionable:
            self.assertNotIn(row["label"], served, f'{row["status"]} row served as an action item')

    def test_scopes_to_the_most_recent_finished_season(self):
        newer_unfinished = self._production(name="2026 season", finished=False)
        body = self.client.get(self._url()).json()
        self.assertEqual(
            body["production"]["id"],
            self.finished.id,
            "picked an unfinished season over the finished one",
        )
        self.assertNotEqual(body["production"]["id"], newer_unfinished.id)

    def test_the_production_names_its_parcel_so_rows_can_link_to_the_record(self):
        body = self.client.get(self._url()).json()
        self.assertEqual(body["production"]["parcel_id"], self.parcel.id)

    def test_farm_with_no_productions_returns_empty_not_error(self):
        empty_est = Establishment.objects.create(name="R2", company=self.company, state="CA")
        resp = self.client.get(self._url(establishment_id=empty_est.id))
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        self.assertIsNone(body["production"])
        self.assertEqual(body["findings"], [])
        self.assertEqual(body["outstanding_count"], 0)

    def test_anonymous_is_rejected(self):
        resp = APIClient().get(self._url())
        self.assertIn(resp.status_code, (401, 403))

    def test_other_tenant_cannot_read(self):
        other_company = Company.objects.create(name="Other Readiness Farm")
        other_user = User.objects.create_user(email="other-readiness@test.com", password="x")
        other_user.companies.add(other_company)

        client = APIClient()
        client.force_authenticate(other_user)
        # Their own company id, someone else's establishment: must not resolve.
        resp = client.get(self._url(company_id=other_company.id))
        self.assertEqual(resp.status_code, 404, "an establishment leaked across tenants")
