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
from history.models import ChemicalEvent, History, ProductionEvent, SalesRecord, SoilManagementEvent
from history.serializers import (
    HistorySerializer,
    UpdateChemicalEventSerializer,
    UpdateProductionEventSerializer,
    UpdateSoilManagementEventSerializer,
)
from history.services.record_receipts import establishment_receipts, receipt_files, shared_from
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
                "history": event.history_id,
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
        harvest = ProductionEvent.objects.create(
            history=self.season, type=ProductionEvent.HARVESTING, description="pick", date=timezone.now()
        )
        refused = {
            "loose": post(),
            "on a sale": post(sales_record=sale.id),
            "on a harvest record": post(history=self.season.id, event_type=1, event_id=harvest.id),
        }
        for why, r in refused.items():
            with self.subTest(why):
                self.assertEqual(r.status_code, 400, r.content)
                self.assertIn("source_kind", r.json())
        self.assertEqual(post(history=self.season.id, event_type=2, event_id=self.spray.id).status_code, 201)


class SeedPurchaseReceiptTests(_ReceiptBase):
    """A seed or stock purchase record holds its receipt like a spray does (2026-10-24).

    A planting names its seed purchase (supplier, invoice, lot) and every certifier asks for the
    seed purchase records (CCOF G3.0, OTCO C3, WSDA 2121-A). Until this, a receipt could not be
    filed on one, so the trace never asked for it, the audit export never marked it and the
    packet's receipts/ folder never carried it.
    """

    def setUp(self):
        super().setUp()
        self.planting = ProductionEvent.objects.create(
            history=self.season,
            type=ProductionEvent.PLANTING,
            description="planting",
            date=timezone.now(),
            variety="Draper",
            seeds_source="commercial",
            seed_supplier_name="Fall Creek Farm & Nursery",
            seed_purchase_invoice="FC-26-1182",
            seed_lot_number="FC-DR-0412",
            seed_certification_status="certified_organic",
        )

    def _url(self):
        return f"/api/companies/{self.company.id}/establishments/{self.est.id}/documents/"

    def test_a_receipt_is_accepted_on_each_seed_purchase_subtype(self):
        for subtype in (ProductionEvent.PLANTING, ProductionEvent.TRANSPLANTING, ProductionEvent.SEED_SEARCH):
            with self.subTest(subtype):
                ev = ProductionEvent.objects.create(
                    history=self.season, type=subtype, description=subtype, date=timezone.now()
                )
                doc = self._fix_it_upload(ev, 1, f"Seed invoice {subtype}")
                self.assertEqual((doc.source_kind, doc.event_type, doc.event_id), ("receipt", 1, ev.id))

    def test_another_farms_record_gets_the_same_answer_whatever_its_subtype(self):
        """The subtype is checked after the farm scope: a foreign id is never asked "harvest or
        planting?", so the two refusals must be indistinguishable."""
        other_parcel = Parcel.objects.create(name="Second farm field", establishment=self.other_est, area=2.0)
        other_season = History.objects.create(name="Other", start_date=timezone.now(), parcel=other_parcel)
        foreign = {
            sub: ProductionEvent.objects.create(history=other_season, type=sub, description=sub, date=timezone.now())
            for sub in (ProductionEvent.PLANTING, ProductionEvent.HARVESTING)
        }
        bodies = {}
        for sub, ev in foreign.items():
            r = self.client.post(
                self._url(),
                {
                    "file": SimpleUploadedFile("r.pdf", b"%PDF-1.4 r", content_type="application/pdf"),
                    "folder": "uploads",
                    "source_kind": "receipt",
                    "event_type": 1,
                    "event_id": ev.id,
                },
            )
            self.assertEqual(r.status_code, 400, r.content)
            bodies[sub] = sorted(r.json())
        self.assertEqual(bodies[ProductionEvent.PLANTING], ["event_id"])
        self.assertEqual(bodies[ProductionEvent.HARVESTING], ["event_id"])

    def test_every_surface_sees_the_seed_receipt(self):
        from history.services.audit_export_service import AuditExportService

        svc = AuditExportService(self.season, certification_type="all")
        # Read something first: the invoice prints, unmarked, before the upload.
        before = _text(svc._build_seed_stock_section())
        self.assertIn("FC-26-1182", before)
        self.assertNotIn("[receipt on file]", before)

        doc = self._fix_it_upload(self.planting, 1, "Fall Creek invoice 1182")
        self.assertEqual(receipt_files([self.planting]), {(1, self.planting.pk): [doc]})
        self.assertEqual(establishment_receipts(self.est), [doc])
        self.assertEqual(
            UpdateProductionEventSerializer(self.planting).data["receipt_document_title"], "Fall Creek invoice 1182"
        )
        self.assertIn("FC-26-1182 [receipt on file]", _text(svc._build_seed_stock_section()))

    def test_the_packet_zip_carries_the_seed_receipt(self):
        from certifications.models import OrganicSystemPlan
        from certifications.services.osp_module_pdf import generate_osp_packet

        self._fix_it_upload(self.planting, 1, "Fall Creek invoice 1182")
        osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", effective_date=timezone.now().date()
        )
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        names = [n for n in zf.namelist() if n.startswith("receipts/")]
        self.assertEqual(len(names), 1, zf.namelist())
        self.assertIn("Fall Creek invoice 1182", names[0])

    def test_the_trace_asks_for_it_and_the_upload_closes_the_gap(self):
        sale = SalesRecord.objects.create(
            production=self.season, sale_date=timezone.now().date(), buyer_name="Cascade", quantity=10
        )
        gap = ("input_without_document", "seed", self.planting.id)

        def gaps():
            return {(g["code"], g["kind"], g["ref"]) for g in trace_sale(sale).as_dict()["gaps"]}

        self.assertIn(gap, gaps())
        self._fix_it_upload(self.planting, 1, "Fall Creek invoice 1182")
        self.assertNotIn(gap, gaps())

    def test_a_planting_that_bought_nothing_is_not_asked_for_a_receipt(self):
        """A lot or a status alone lists the seed row; a receipt is asked for only when the record
        names an invoice or a supplier, and never for farm-saved seed."""
        lot_only = ProductionEvent.objects.create(
            history=self.season,
            type=ProductionEvent.PLANTING,
            description="lot only",
            date=timezone.now(),
            seed_lot_number="OWN-25",
            seed_certification_status="certified_organic",
        )
        farm_saved = ProductionEvent.objects.create(
            history=self.season,
            type=ProductionEvent.PLANTING,
            description="farm saved",
            date=timezone.now(),
            seeds_source="farm_saved",
            seed_supplier_name="Our own 2025 crop",
        )
        sale = SalesRecord.objects.create(
            production=self.season, sale_date=timezone.now().date(), buyer_name="Cascade", quantity=10
        )
        trace = trace_sale(sale).as_dict()
        # Read something first: both rows are on the trace.
        seed_rows = {r["event_id"] for r in trace["inputs"] if r["kind"] == "seed"}
        self.assertTrue({lot_only.id, farm_saved.id} <= seed_rows)
        asked = {g["ref"] for g in trace["gaps"] if g["code"] == "input_without_document" and g["kind"] == "seed"}
        self.assertEqual(asked, {self.planting.id})

    def test_the_title_never_reaches_the_season_payload_consumers_get(self):
        """`HistorySerializer` is what the consumer `my_reviews` response returns per review; the
        title of a supplier invoice must never ride in it. The farm's edit serializer has it."""
        import json

        self._fix_it_upload(self.planting, 1, "Fall Creek invoice 1182")
        payload = json.dumps(HistorySerializer(self.season).data, default=str)
        # Read something first: the planting is in the payload.
        self.assertIn("Draper", payload)
        self.assertNotIn("receipt_document_title", payload)
        self.assertNotIn("Fall Creek invoice 1182", payload)
        self.assertEqual(
            UpdateProductionEventSerializer(self.planting).data["receipt_document_title"], "Fall Creek invoice 1182"
        )


class GroupReceiptTests(_ReceiptBase):
    """One activity logged on several parcels is one purchase (`application_group`): a receipt filed
    on one of its records is the receipt of every record of the group on the same farm, and says
    where it was filed."""

    def setUp(self):
        import uuid

        super().setUp()
        self.group = uuid.uuid4()
        self.records = []
        for name in ("Home Field West", "Home Field East", "Upper Terrace"):
            parcel = (
                self.parcel
                if name == "Home Field West"
                else Parcel.objects.create(name=name, establishment=self.est, area=2.0)
            )
            season = (
                self.season
                if parcel == self.parcel
                else History.objects.create(name=f"Draper 2026 {name}", start_date=timezone.now(), parcel=parcel)
            )
            ev = ProductionEvent.objects.create(
                history=season,
                type=ProductionEvent.PLANTING,
                description="planting",
                date=timezone.now(),
                seed_supplier_name="Fall Creek Farm & Nursery",
                seed_purchase_invoice="FC-26-1182",
            )
            ProductionEvent.objects.filter(pk=ev.pk).update(application_group=self.group)
            ev.refresh_from_db()
            self.records.append(ev)
        # The same UUID on another farm's record: never a sibling of these.
        other_parcel = Parcel.objects.create(name="Second farm field", establishment=self.other_est, area=2.0)
        other_season = History.objects.create(name="Other", start_date=timezone.now(), parcel=other_parcel)
        self.foreign = ProductionEvent.objects.create(
            history=other_season, type=ProductionEvent.PLANTING, description="p", date=timezone.now()
        )
        ProductionEvent.objects.filter(pk=self.foreign.pk).update(application_group=self.group)
        self.foreign.refresh_from_db()

    def test_one_upload_is_the_receipt_of_every_record_of_the_group(self):
        doc = self._fix_it_upload(self.records[0], 1, "Fall Creek invoice 1182")
        files = receipt_files([*self.records, self.foreign])
        self.assertEqual(set(files), {(1, ev.pk) for ev in self.records})
        self.assertTrue(all(found == [doc] for found in files.values()))
        # Where it lives: nothing on the record it was filed on, that parcel on the others.
        self.assertEqual(shared_from(files, self.records[0]), ())
        self.assertEqual(shared_from(files, self.records[1]), ("Home Field West",))
        self.assertEqual(shared_from(files, self.records[2]), ("Home Field West",))

    def test_another_farms_record_with_the_same_group_neither_lends_nor_borrows(self):
        f = GeneratedDocument.objects.create(
            establishment=self.other_est,
            source="upload",
            folder="uploads",
            title="Second farm invoice",
            source_kind="receipt",
            file=ContentFile(b"x", name="second.pdf"),
            event_type=1,
            event_id=self.foreign.pk,
        )
        # The other farm's file, filed on its own record of the same UUID, lends nothing here ...
        self.assertEqual(receipt_files(self.records), {})
        # ... and this farm's upload lends nothing there: the other record keeps only its own.
        self._fix_it_upload(self.records[1], 1, "Fall Creek invoice 1182")
        self.assertEqual(receipt_files([self.foreign]), {(1, self.foreign.pk): [f]})

    def test_the_trace_shows_where_a_shared_receipt_was_filed(self):
        self._fix_it_upload(self.records[0], 1, "Fall Creek invoice 1182")
        season = self.records[1].history
        sale = SalesRecord.objects.create(
            production=season, sale_date=timezone.now().date(), buyer_name="Cascade", quantity=10
        )
        trace = trace_sale(sale).as_dict()
        [row] = [r for r in trace["inputs"] if (r["kind"], r["event_id"]) == ("seed", self.records[1].id)]
        self.assertEqual(
            [(d["title"], d["kind"], d.get("filed_on")) for d in row["documents"]],
            [("Fall Creek invoice 1182", "receipt", ["Home Field West"])],
        )
        self.assertNotIn(
            ("input_without_document", "seed", self.records[1].id),
            {(g["code"], g["kind"], g["ref"]) for g in trace["gaps"]},
        )

    def test_the_audit_export_names_where_it_was_filed(self):
        from history.services.audit_export_service import AuditExportService

        self._fix_it_upload(self.records[0], 1, "Fall Creek invoice 1182")
        own = _text(AuditExportService(self.season, certification_type="all")._build_seed_stock_section())
        other = _text(AuditExportService(self.records[1].history, certification_type="all")._build_seed_stock_section())
        self.assertIn("FC-26-1182 [receipt on file]", own)
        self.assertNotIn("filed on", own)
        self.assertIn("FC-26-1182 [receipt on file, filed on Home Field West]", other)

    def test_a_spray_group_shares_its_receipt_the_same_way(self):
        import uuid

        group = uuid.uuid4()
        east = Parcel.objects.create(name="Spray East", establishment=self.est, area=2.0)
        east_season = History.objects.create(name="East", start_date=timezone.now(), parcel=east)
        twin = ChemicalEvent.objects.create(
            history=east_season,
            date=timezone.now(),
            description="spray",
            commercial_name="Rex Lime Sulfur",
            purchase_invoice="WILCO-2026-02991",
        )
        ChemicalEvent.objects.filter(pk__in=[self.spray.pk, twin.pk]).update(application_group=group)
        self.spray.refresh_from_db()
        twin.refresh_from_db()
        doc = self._fix_it_upload(self.spray, 2, "Wilco receipt 02991")
        files = receipt_files([self.spray, twin])
        self.assertEqual(files.get((2, twin.pk)), [doc])
        self.assertEqual(shared_from(files, twin), ("Home Field West",))
