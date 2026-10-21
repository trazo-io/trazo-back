"""A receipt filed ON a record from Documents counts as that record's receipt everywhere (2026-10-21).

The traceback's "Fix it here" opens Documents filed to the record and uploads with
`event_type` / `event_id`. The trace read that link and closed its gap; the record's own Receipt
field, the audit export's "[receipt on file]" and the renewal packet's receipts/ folder read only
`receipt_document`, so all three still said there was no receipt (measured on a local Fix-it
upload: the file was filed to the record, the record's receipt field stayed empty).

Each test uploads through the real Documents endpoint, the path the trace sends a farmer down,
and reads one surface. Another farm's file never counts, by either link.
"""

import io
import re
import zipfile

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from documents.models import GeneratedDocument
from history.models import ChemicalEvent, History, SalesRecord, SoilManagementEvent
from history.serializers import UpdateChemicalEventSerializer, UpdateSoilManagementEventSerializer
from history.services.record_receipts import establishment_receipts, receipt_files
from history.services.traceback import trace_sale
from product.models import Parcel
from subscriptions.testing import grant_compliance_exports
from users.models import User, WorksIn


def _text(flowables):
    out = []
    for f in flowables:
        if hasattr(f, "text"):
            out.append(re.sub(r"<[^>]+>", "", f.text))
        elif hasattr(f, "_cellvalues"):
            for row in f._cellvalues:
                for cell in row:
                    out.append(re.sub(r"<[^>]+>", "", getattr(cell, "text", str(cell))))
    return " ".join(out)


class _ReceiptBase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Calapooia Bend Farm LLC")
        self.user = User.objects.create_user(email="laurel@receipts.test", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        grant_compliance_exports(self.company)
        self.est = Establishment.objects.create(name="Home", company=self.company, state="OR")
        # The same company's second farm: its files must never count on this farm's records.
        self.other_est = Establishment.objects.create(name="Second farm", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="Home Field West", establishment=self.est, area=4.0)
        self.season = History.objects.create(
            name="Draper 2026", start_date=timezone.now(), parcel=self.parcel, lot_id="CBF-26-HFW"
        )
        self.spray = ChemicalEvent.objects.create(
            history=self.season,
            date=timezone.now(),
            description="spray",
            commercial_name="Rex Lime Sulfur",
            supplier_name="Wilco Ag",
            purchase_invoice="WILCO-2026-02991",
            chemical_lot_number="RLS-26-011",
        )
        self.compost = SoilManagementEvent.objects.create(
            history=self.season,
            date=timezone.now(),
            description="compost",
            amendment_product_name="Royal Compost",
            amendment_supplier_name="Royal Organics",
            amendment_purchase_invoice="RC-0320",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _fix_it_upload(self, event, event_type, title, source_kind="receipt"):
        """The upload the trace's "Fix it here" makes: filed to the season AND the record."""
        r = self.client.post(
            f"/api/companies/{self.company.id}/establishments/{self.est.id}/documents/",
            {
                "file": SimpleUploadedFile(f"{title}.pdf", b"%PDF-1.4 receipt", content_type="application/pdf"),
                "title": title,
                "folder": "uploads",
                "history": self.season.id,
                "event_type": event_type,
                "event_id": event.id,
                "source_kind": source_kind,
            },
        )
        self.assertEqual(r.status_code, 201, r.content)
        return GeneratedDocument.objects.get(pk=r.json()["id"])


class ReceiptFiledOnRecordTests(_ReceiptBase):
    def test_the_upload_is_filed_on_the_record_and_leaves_its_field_alone(self):
        doc = self._fix_it_upload(self.spray, 2, "Wilco receipt 02991")
        self.assertEqual((doc.event_type, doc.event_id, doc.history_id), (2, self.spray.id, self.season.id))
        self.spray.refresh_from_db()
        # Read-side only: filing evidence never rewrites the record.
        self.assertIsNone(self.spray.receipt_document_id)

    def test_the_records_receipt_field_shows_it(self):
        self._fix_it_upload(self.spray, 2, "Wilco receipt 02991")
        self._fix_it_upload(self.compost, 5, "Royal compost receipt")
        self.assertEqual(
            UpdateChemicalEventSerializer(self.spray).data["receipt_document_title"], "Wilco receipt 02991"
        )
        self.assertEqual(
            UpdateSoilManagementEventSerializer(self.compost).data["receipt_document_title"], "Royal compost receipt"
        )

    def test_the_packet_zip_carries_it_under_receipts(self):
        from certifications.models import OrganicSystemPlan
        from certifications.services.osp_module_pdf import generate_osp_packet

        self._fix_it_upload(self.spray, 2, "Wilco receipt 02991")
        osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", effective_date=timezone.now().date()
        )
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        names = [n for n in zf.namelist() if n.startswith("receipts/")]
        self.assertEqual(len(names), 1, zf.namelist())
        self.assertIn("Wilco receipt 02991", names[0])
        self.assertEqual(zf.read(names[0]), b"%PDF-1.4 receipt")

    def test_both_audit_purchase_tables_mark_it_on_file(self):
        from history.services.audit_export_service import AuditExportService

        svc = AuditExportService(self.season, certification_type="all")
        # Read something first: the rows print, and neither is marked before the uploads.
        before = _text(svc._build_chemical_log()) + _text(
            svc._build_amendment_purchase_subtable(list(self.season.history_soilmanagementevent_events.all()))
        )
        self.assertIn("WILCO-2026-02991", before)
        self.assertIn("RC-0320", before)
        self.assertNotIn("[receipt on file]", before)

        self._fix_it_upload(self.spray, 2, "Wilco receipt 02991")
        self._fix_it_upload(self.compost, 5, "Royal compost receipt")
        chem = _text(svc._build_chemical_log())
        soil = _text(svc._build_amendment_purchase_subtable(list(self.season.history_soilmanagementevent_events.all())))
        self.assertIn("WILCO-2026-02991 [receipt on file]", chem)
        self.assertIn("RC-0320 [receipt on file]", soil)

    def test_the_trace_agrees(self):
        sale = SalesRecord.objects.create(
            production=self.season, sale_date=timezone.now().date(), buyer_name="Cascade", quantity=10
        )
        self._fix_it_upload(self.spray, 2, "Wilco receipt 02991")
        trace = trace_sale(sale).as_dict()
        [row] = [r for r in trace["inputs"] if (r["kind"], r["event_id"]) == ("chemical", self.spray.id)]
        self.assertEqual([d["title"] for d in row["documents"]], ["Wilco receipt 02991"])
        self.assertNotIn(
            ("input_without_document", "chemical", self.spray.id),
            {(g["code"], g["kind"], g["ref"]) for g in trace["gaps"]},
        )

    def test_another_farms_file_counts_by_neither_link(self):
        def foreign(title):
            return GeneratedDocument.objects.create(
                establishment=self.other_est,
                source="upload",
                folder="uploads",
                title=title,
                file=ContentFile(b"x", name=f"{title}.pdf"),
            )

        # By the record's field (the company-only check on create could let it through) ...
        ChemicalEvent.objects.filter(pk=self.spray.pk).update(receipt_document=foreign("Second farm invoice"))
        # ... and by a filing link that names this farm's record from the other farm's shelf.
        f = foreign("Second farm upload")
        GeneratedDocument.objects.filter(pk=f.pk).update(event_type=5, event_id=self.compost.pk)
        self.spray.refresh_from_db()

        self.assertEqual(receipt_files([self.spray, self.compost]), {})
        self.assertEqual(establishment_receipts(self.est), [])
        self.assertIsNone(UpdateChemicalEventSerializer(self.spray).data["receipt_document_title"])

    def test_the_field_and_a_filed_file_are_each_listed_once(self):
        doc = self._fix_it_upload(self.spray, 2, "Wilco receipt 02991")
        ChemicalEvent.objects.filter(pk=self.spray.pk).update(receipt_document=doc)
        self.spray.refresh_from_db()
        self.assertEqual(receipt_files([self.spray]), {(2, self.spray.pk): [doc]})
        self.assertEqual(establishment_receipts(self.est), [doc])


class NotEveryFileOnARecordIsAReceipt(_ReceiptBase):
    """Review of back #207: the same link files a soil test's lab report or a photo. Only a file
    filed AS a purchase receipt is the record's receipt; the rest are attachments."""

    def test_a_lab_report_on_the_record_counts_as_no_receipt_anywhere(self):
        from history.services.audit_export_service import AuditExportService

        self._fix_it_upload(self.compost, 5, "Soil lab report", source_kind="")
        self._fix_it_upload(self.spray, 2, "Spray photo", source_kind="other")
        self.assertEqual(receipt_files([self.spray, self.compost]), {})
        self.assertEqual(establishment_receipts(self.est), [])
        self.assertIsNone(UpdateSoilManagementEventSerializer(self.compost).data["receipt_document_title"])
        svc = AuditExportService(self.season, certification_type="all")
        soil = _text(svc._build_amendment_purchase_subtable(list(self.season.history_soilmanagementevent_events.all())))
        self.assertIn("RC-0320", soil)
        self.assertNotIn("[receipt on file]", soil)

    def test_a_receipt_is_filed_on_a_spray_or_amendment_record_only(self):
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/documents/"

        def post(**extra):
            f = SimpleUploadedFile("r.pdf", b"%PDF-1.4 r", content_type="application/pdf")
            return self.client.post(url, {"file": f, "folder": "uploads", "source_kind": "receipt", **extra})

        sale = SalesRecord.objects.create(
            production=self.season, sale_date=timezone.now().date(), buyer_name="Cascade", quantity=10
        )
        refused = {
            "loose": post(),
            "on a sale": post(sales_record=sale.id),
            "on a harvest record": post(history=self.season.id, event_type=1, event_id=1),
        }
        for why, r in refused.items():
            with self.subTest(why):
                self.assertEqual(r.status_code, 400, r.content)
                self.assertIn("source_kind", r.json())
        self.assertEqual(post(history=self.season.id, event_type=2, event_id=self.spray.id).status_code, 201)
