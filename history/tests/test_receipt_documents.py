"""Receipt files travel with the record (2026-08-25).

The purchase fields carried only a typed invoice NUMBER; the uploaded receipt
lived in Documents, unlinked, and the packet could not show it — the inspector
had to ask the farmer to courier the paper behind the number. Pins:

- the event → document link round-trips through the Update serializer,
  including the read-only title;
- a document from ANOTHER operation is refused (cross-tenant scope is the
  whole game on a bare FK);
- the packet ZIP carries the referenced file under receipts/;
- the audit PDF marks the purchase row "[receipt on file]".
"""

import io
import zipfile

from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from documents.models import GeneratedDocument
from history.models import ChemicalEvent, History
from history.serializers import UpdateChemicalEventSerializer
from product.models import Parcel


class ReceiptDocumentTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Receipt Farm")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.history = History.objects.create(
            name="Receipt Season",
            start_date=timezone.now(),
            parcel=self.parcel,
        )
        self.doc = GeneratedDocument.objects.create(
            establishment=self.establishment,
            source="upload",
            folder="uploads",
            title="Wilbur-Ellis invoice 0142",
            file=ContentFile(b"receipt-bytes", name="invoice-0142.pdf"),
            content_type="application/pdf",
            size_bytes=13,
        )

        other_company = Company.objects.create(name="Other Co")
        other_est = Establishment.objects.create(name="Elsewhere", company=other_company)
        self.foreign_doc = GeneratedDocument.objects.create(
            establishment=other_est,
            source="upload",
            folder="uploads",
            title="Not yours",
            file=ContentFile(b"x", name="foreign.pdf"),
            content_type="application/pdf",
            size_bytes=1,
        )

    def _payload(self, **extra):
        base = {
            "history": self.history.id,
            "date": timezone.now().isoformat(),
            "description": "spray",
            "commercial_name": "Entrust SC",
            "way_of_application": "foliar",
        }
        base.update(extra)
        return base

    def test_link_round_trips_with_title(self):
        ser = UpdateChemicalEventSerializer(data=self._payload(receipt_document=self.doc.id))
        self.assertTrue(ser.is_valid(), ser.errors)
        ev = ser.save()
        data = UpdateChemicalEventSerializer(ev).data
        self.assertEqual(data["receipt_document"], self.doc.id)
        self.assertEqual(data["receipt_document_title"], "Wilbur-Ellis invoice 0142")

    def test_foreign_document_refused_by_user_scope_without_history(self):
        # The normal create path posts `parcels`, not `history` — the season is
        # resolved AFTER validation — so this gate must not depend on history:
        # a member of another company naming this farm's receipt id is refused
        # purely on membership (fresh-eyes hole, 2026-08-25).
        from rest_framework.test import APIRequestFactory

        from users.models import User, WorksIn

        outsider = User.objects.create_user(email="outsider@receipt.test", password="x")
        other_company = Company.objects.create(name="Attacker Co")
        WorksIn.objects.create(user=outsider, company=other_company, role=WorksIn.COMPANY_ADMIN)

        request = APIRequestFactory().post("/")
        request.user = outsider
        payload = self._payload(receipt_document=self.doc.id)
        payload.pop("history")
        ser = UpdateChemicalEventSerializer(data=payload, context={"request": request})
        ser.is_valid()
        self.assertIn("receipt_document", ser.errors)

    def test_foreign_document_refused(self):
        ser = UpdateChemicalEventSerializer(data=self._payload(receipt_document=self.foreign_doc.id))
        self.assertFalse(ser.is_valid())
        self.assertIn("receipt_document", ser.errors)

    def test_packet_zip_carries_the_receipt_file(self):
        from certifications.models import OrganicSystemPlan
        from certifications.services.osp_module_pdf import generate_osp_packet

        ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="spray",
            commercial_name="Entrust SC",
            receipt_document=self.doc,
        )
        osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )
        payload = generate_osp_packet(osp)
        zf = zipfile.ZipFile(io.BytesIO(payload))
        receipt_names = [n for n in zf.namelist() if n.startswith("receipts/")]
        self.assertEqual(len(receipt_names), 1, zf.namelist())
        self.assertIn("Wilbur-Ellis invoice 0142", receipt_names[0])
        self.assertEqual(zf.read(receipt_names[0]), b"receipt-bytes")

    def test_audit_tables_carry_the_receipt_marker(self):
        # Behaviour, not source text: the chemical purchase table marks a row whose record holds
        # the receipt in its own field. (A receipt filed ON the record from Documents is pinned in
        # test_receipt_filed_on_record.)
        from history.services.audit_export_service import AuditExportService

        ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="spray",
            commercial_name="Entrust SC",
            purchase_invoice="WE-0142",
            receipt_document=self.doc,
        )
        flat = " ".join(
            getattr(cell, "text", "")
            for f in AuditExportService(self.history, certification_type="all")._build_chemical_log()
            for row in getattr(f, "_cellvalues", [])
            for cell in row
        )
        self.assertIn("WE-0142 [receipt on file]", flat)
