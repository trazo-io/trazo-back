"""`POST /api/carbon/entries/`: what it refuses, and what it no longer writes.

Three defects in one create path, found 2026-11-07:

* Every entry tied to a production ended in a 500. The gate read `user.subscription_plan`, which
  User does not have, then raised `permissions.PermissionDenied`, which does not exist in
  rest_framework.permissions, so the AttributeError won over the message it was carrying, which
  sold a "premium" plan that does not exist. The refusal stays (those entries are computed from
  activities), now as a 403 with the true reason.
* A `raw_amount` + `crop_type` payload went to `coolfarm_service.calculate_emissions`, which
  CoolFarmService does not define. The error was swallowed. Had it run, it would have stamped the
  entry "factors_verified" with data_source "USDA Agricultural Research Service", the blanket
  attribution compliance.md forbids. The branch is gone.
* `entries/calculate_emissions/` called the same missing method and answered 500 to every
  request. It is retired (see test_retired_claim_routes_stay_retired).
"""

from django.contrib.auth import get_user_model
from django.utils import timezone

from rest_framework.test import APITestCase

from carbon.models import CarbonAuditLog, CarbonEntry
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel
from users.models import WorksIn


class CarbonEntriesCreatePathTests(APITestCase):
    def setUp(self):
        company = Company.objects.create(name="Entries Co")
        self.est = Establishment.objects.create(name="Entries Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=self.est, area=1)
        self.season = History.objects.create(parcel=parcel, name="2026", start_date=timezone.now())
        CarbonEntry.objects.all().delete()  # whatever the save receivers wrote
        user = get_user_model().objects.create_user(email="entries@example.com", password="x")
        WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)  # may write
        self.client.force_authenticate(user)

    def _post(self, **extra):
        payload = {
            "type": "emission",
            "amount": 12.5,
            "year": timezone.now().year,
            "description": "Diesel for the pump",
            "establishment_id": self.est.pk,
            **extra,
        }
        return self.client.post("/api/carbon/entries/", payload, format="json")

    def test_an_entry_for_a_production_is_refused_with_the_true_reason(self):
        response = self._post(production_id=self.season.pk)
        self.assertEqual(response.status_code, 403, response.content)
        detail = str(response.json().get("detail", ""))
        self.assertIn("computed from its activities", detail)
        for sold in ("premium", "Upgrade", "plan"):
            self.assertNotIn(sold, detail)
        self.assertFalse(CarbonEntry.objects.exists())

    def test_an_establishment_entry_is_still_created(self):
        response = self._post()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(CarbonEntry.objects.get().establishment_id, self.est.pk)

    def test_raw_amount_no_longer_reaches_a_usda_attribution(self):
        response = self._post(raw_amount=40, crop_type="citrus", inputs={"diesel": 10})
        self.assertEqual(response.status_code, 201, response.content)
        entry = CarbonEntry.objects.get()
        self.assertNotEqual(entry.data_source, "USDA Agricultural Research Service")
        self.assertNotIn("verified", entry.verification_status)
        self.assertEqual(entry.amount, 12.5)  # the typed amount, not a replacement from a calculator

    def _row(self, **extra):
        return {
            "type": "emission",
            "amount": 3.0,
            "year": timezone.now().year,
            "description": "Diesel",
            "establishment_id": self.est.pk,
            **extra,
        }

    def test_bulk_create_writes_every_row_and_one_audit_row_each(self):
        """It saves a list, so the audit log has to walk the list (review of #338)."""
        response = self.client.post("/api/carbon/entries/bulk_create/", [self._row(), self._row()], format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(CarbonEntry.objects.count(), 2)
        self.assertEqual(
            sorted(CarbonAuditLog.objects.values_list("carbon_entry_id", flat=True)),
            sorted(CarbonEntry.objects.values_list("pk", flat=True)),
        )

    def test_bulk_create_with_a_production_row_writes_nothing(self):
        rows = [self._row(), self._row(production_id=self.season.pk)]
        response = self.client.post("/api/carbon/entries/bulk_create/", rows, format="json")
        self.assertEqual(response.status_code, 403, response.content)
        self.assertFalse(CarbonEntry.objects.exists())
