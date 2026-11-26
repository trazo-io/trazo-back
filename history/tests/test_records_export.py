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
from datetime import date

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import ChemicalEvent, Production, SoilManagementEvent
from product.models import Parcel
from users.models import User, WorksIn


class RecordsExportTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Export Farm Co")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.history = Production.objects.create(
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


class RecordsExportCoversParcelAndSupplierRecordsTests(TestCase):
    """M7-S14: a file called complete left out field history, planned crops, both affidavits and
    the supplier register. Every row is the requesting company's; another company's never appears."""

    def _farm(self, name):
        company = Company.objects.create(name=f"{name} Co")
        est = Establishment.objects.create(name=name, company=company)
        parcel = Parcel.objects.create(name=f"{name} parcel", establishment=est, area=5.0)
        return company, est, parcel

    def _seed(self, est, parcel, tag):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from certifications.models import AdjoiningLandAffidavit, LandownerAffidavit, Supplier, SupplierCertificate
        from documents.models import GeneratedDocument
        from product.models import ParcelCropHistory, ParcelPlannedCrop

        ParcelCropHistory.objects.create(parcel=parcel, year=2024, crop_grown=f"Crop {tag}")
        ParcelPlannedCrop.objects.create(parcel=parcel, crop=f"Planned {tag}")
        LandownerAffidavit.objects.create(parcel=parcel, previous_manager_name=f"Manager {tag}")
        AdjoiningLandAffidavit.objects.create(
            parcel=parcel, neighbor_name=f"Neighbour {tag}", signed_document=f"adjoining_land_affidavits/{tag}.pdf"
        )
        supplier = Supplier.objects.create(establishment=est, name=f"Supplier {tag}", certifier_name=f"Certifier {tag}")
        doc = GeneratedDocument.objects.create(
            establishment=est,
            folder="uploads",
            source="upload",
            title=f"Cert {tag}",
            file=SimpleUploadedFile(f"cert-{tag}.pdf", b"x", content_type="application/pdf"),
        )
        SupplierCertificate.objects.create(supplier=supplier, document=doc, issued_on=date(2026, 1, 5))

    def test_each_family_has_a_csv_with_only_this_companys_rows(self):
        from history.services.records_export import export_establishment_records_zip

        _company, est, parcel = self._farm("Mine")
        _other_company, other_est, other_parcel = self._farm("Theirs")
        self._seed(est, parcel, "MINE")
        self._seed(other_est, other_parcel, "THEIRS")

        zf = zipfile.ZipFile(io.BytesIO(export_establishment_records_zip(est)))
        expected = {
            "parcel_crop_history.csv": "Crop MINE",
            "parcel_planned_crops.csv": "Planned MINE",
            "landowner_affidavits.csv": "Manager MINE",
            "adjoining_land_affidavits.csv": "Neighbour MINE",
            "suppliers.csv": "Supplier MINE",
            "supplier_certificates.csv": "2026-01-05",
        }
        for name, needle in expected.items():
            self.assertIn(name, zf.namelist())
            body = zf.read(name).decode("utf-8")
            self.assertIn(needle, body, name)
            self.assertNotIn("THEIRS", body, f"{name} leaked another company's row")
        self.assertEqual(len(zf.read("supplier_certificates.csv").decode().strip().splitlines()), 2)
        self.assertIn("adjoining_land_affidavits/MINE.pdf", zf.read("adjoining_land_affidavits.csv").decode("utf-8"))

    def test_the_readme_no_longer_lists_them_as_missing(self):
        from history.services.records_export import export_establishment_records_zip

        _company, est, _parcel = self._farm("Readme")
        readme = zipfile.ZipFile(io.BytesIO(export_establishment_records_zip(est))).read("README.txt").decode("utf-8")
        not_in = readme.split("Not in this export")[1].lower()
        for word in ("supplier", "affidavit", "crop history", "planned crop"):
            self.assertNotIn(word, not_in)
        self.assertIn("suppliers.csv", readme)
