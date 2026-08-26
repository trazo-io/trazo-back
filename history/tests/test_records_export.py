"""The free records export — record ownership, no plan gating (2026-08-25).

Pins three things:
- an authenticated member of the company gets a complete ZIP of raw CSVs,
  WITHOUT any subscription (Starter-equivalent: no plan rows at all) — the
  export must never grow a `require_compliance_exports` gate;
- the ZIP actually contains the farm's records (a chemical event's commercial
  name appears in chemical_events.csv; JSON pockets ride along verbatim);
- anonymous callers and members of OTHER companies get nothing.
"""

import io
import zipfile

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import ChemicalEvent, History, SoilManagementEvent
from product.models import Parcel
from users.models import User, WorksIn


class RecordsExportTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Export Farm Co")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.history = History.objects.create(
            name="Export Season",
            start_date=timezone.now(),
            parcel=self.parcel,
        )
        ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="spray",
            commercial_name="Entrust SC",
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="soil test",
            type=SoilManagementEvent.SOIL_TEST,
            test_results={"lab_name": "Export Labs"},
        )

        self.owner = User.objects.create_user(email="owner@export.test", password="x")
        WorksIn.objects.create(user=self.owner, company=self.company, role=WorksIn.COMPANY_ADMIN)

        self.outsider = User.objects.create_user(email="outsider@export.test", password="x")
        other = Company.objects.create(name="Other Co")
        WorksIn.objects.create(user=self.outsider, company=other, role=WorksIn.COMPANY_ADMIN)

        self.url = f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/records-export/"

    def test_member_gets_full_zip_without_any_subscription(self):
        # No Plan/Subscription rows exist in this test DB — the export must not care.
        client = APIClient()
        client.force_authenticate(user=self.owner)
        response = client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("trazo-records-", response["Content-Disposition"])

        zf = zipfile.ZipFile(io.BytesIO(response.content))
        names = set(zf.namelist())
        for expected in (
            "chemical_events.csv",
            "soil_events.csv",
            "production_events.csv",
            "productions.csv",
            "parcels.csv",
            "sales_records.csv",
            "photos.csv",
            "README.txt",
        ):
            self.assertIn(expected, names)

        chem = zf.read("chemical_events.csv").decode("utf-8")
        self.assertIn("Entrust SC", chem)
        soil = zf.read("soil_events.csv").decode("utf-8")
        self.assertIn("Export Labs", soil, "JSON pockets must ride along verbatim")
        self.assertIn("205.103", zf.read("README.txt").decode("utf-8"))

    def test_anonymous_is_refused(self):
        response = APIClient().get(self.url)
        self.assertIn(response.status_code, (401, 403))

    def test_other_company_member_is_refused(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)
        response = client.get(self.url)
        self.assertIn(response.status_code, (403, 404))

    def test_no_compliance_gate_in_the_view(self):
        # The contract, pinned at the source level: the certifier artifacts are
        # gated; the raw export must never be.
        import inspect

        from history.views import RecordsExportViewSet

        source = inspect.getsource(RecordsExportViewSet)
        self.assertNotIn(
            "require_compliance_exports", source.replace("stay behind\n    `require_compliance_exports`", "")
        )
