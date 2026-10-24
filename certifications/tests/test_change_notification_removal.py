"""Removed acreage carries its reason and its map into the packet.

WHY THIS EXISTS
---------------
WSDA's Site Update (AGR 2516): "If acreage is removed from organic production, include a map
identifying the new boundaries and include details on why the acreage was removed (transferred to
another grower, converted to conventional, etc.)". Read as a WSDA reviewer on 2026-10-24, Trazo
held neither: the notice's `supporting_document` was a writable field no screen uploaded to and no
packet carried, and there was no field for the reason.

Pinned here: a new field-removal notice cannot be recorded without its reason; a file filed with a
notice is written into the ZIP and 03 names it by that path; 03 says so when a removal has no map
or a legacy notice has no reason; and 03, which goes into every agent's packet, names no agent's
form for it.
"""

import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan, OSPChangeNotification
from certifications.services.osp_module_pdf import generate_osp_packet
from company.models import Company, Establishment
from users.models import User, WorksIn

from .test_renewal_packet_contents import _pdf_text

PDF = b"%PDF-1.4 new boundaries map"


class _Farm(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Removal Orchards LLC")
        self.user = User.objects.create_user(email="removal@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Removal Orchard", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            approval_certifier_name="Washington State Department of Agriculture",
        )
        self.client.force_authenticate(user=self.user)

    def _url(self):
        return f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{self.osp.id}/change-notifications/"

    def _packet(self):
        return zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp)))


class RecordingARemovalTests(_Farm):
    def test_a_removal_without_its_reason_is_refused_and_says_what_to_give(self):
        resp = self.client.post(
            self._url(), {"change_category": "field_removal", "description": "5 acres of Block C"}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("removal_reason", resp.data)
        self.assertFalse(OSPChangeNotification.objects.exists())

    def test_a_removal_with_its_reason_and_map_is_recorded(self):
        resp = self.client.post(
            self._url(),
            {
                "change_category": "field_removal",
                "description": "5 acres of Block C left organic production.",
                "removal_reason": "  Converted to conventional for a processor contract.  ",
                "supporting_document": SimpleUploadedFile("block-c-map.pdf", PDF, content_type="application/pdf"),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        notice = OSPChangeNotification.objects.get()
        self.assertEqual(notice.removal_reason, "Converted to conventional for a processor contract.")
        self.assertTrue(notice.supporting_document)

    def test_other_categories_need_no_reason(self):
        resp = self.client.post(
            self._url(), {"change_category": "acreage_field_addition", "description": "Added Block D."}, format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_a_file_type_the_packet_should_not_carry_is_refused(self):
        resp = self.client.post(
            self._url(),
            {
                "change_category": "acreage_field_addition",
                "description": "Added Block D.",
                "supporting_document": SimpleUploadedFile("map.exe", b"MZ", content_type="application/octet-stream"),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("supporting_document", resp.data)


class RemovalInThePacketTests(_Farm):
    def test_the_map_ships_in_the_zip_and_03_names_it_with_the_reason(self):
        notice = OSPChangeNotification.objects.create(
            osp=self.osp,
            change_category="field_removal",
            description="5 acres of Block C left organic production.",
            removal_reason="Transferred to another grower.",
            date_notified="2026-09-01",
            supporting_document=SimpleUploadedFile("block-c-map.pdf", PDF),
        )
        zf = self._packet()
        path = f"notices/{notice.pk}-field-removal.pdf"
        self.assertIn(path, zf.namelist())
        self.assertEqual(zf.read(path), PDF)
        text = _pdf_text(zf.read("03-change-notifications.pdf"))
        self.assertIn("Why the acreage left organic production: Transferred to another grower.", text)
        self.assertIn(f"Supporting document attached to this packet: {path}.", text)

    def test_a_legacy_removal_says_what_is_missing_and_names_no_agents_form(self):
        OSPChangeNotification.objects.create(
            osp=self.osp,
            change_category="field_removal",
            description="Block E removed.",
            date_notified="2026-02-01",
        )
        text = _pdf_text(self._packet().read("03-change-notifications.pdf"))
        self.assertIn("Why the acreage left organic production: not recorded in Trazo.", text)
        self.assertIn("No map of the new boundaries is attached to this notice.", text)
        self.assertNotIn("AGR 2516", text)
        self.assertNotIn("WSDA", text)
