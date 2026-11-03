"""Only a file that is actually in the ZIP answers an attachment, and every other file is named.

WHY THIS EXISTS
---------------
OSP alignment audit 2026-10, T19 and T22.
  * Uploaded label files never reached the packet; the label question could never close, and
    when it did reach a reviewer, nothing said which file was the label.
  * A sale's invoice and bill of lading travelled as numbers only, beside a trace that read as
    if the documents were held.
  * Maps, affidavits and receipts were read in loops that skipped any file they could not open,
    while page 04 counted the upload as present. A reviewer was told "attached" about a file the
    ZIP did not hold.

Since 2026-10-01 the packet decides every file once (`packet_attachments.build_manifest`):
attached, held outside the packet (size limit), or unreadable. Only attached answers.
"""

import io
import zipfile
from datetime import date, datetime

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.test import APITestCase

from certifications.models import OrganicSystemPlan
from certifications.services.osp_module_pdf import generate_osp_packet
from certifications.services.packet_answers import _Answers, row_answer_state
from certifications.services.packet_attachments import LABEL_REQUIREMENT, build_manifest, building
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from history.models import History, ProductionEvent, SalesRecord
from product.models import Parcel, Product
from subscriptions.testing import grant_compliance_exports
from users.models import User, WorksIn

from .test_packet_coverage_states_answers import _answer, _item
from .test_renewal_packet_contents import _pdf_text

LABEL_ITEM = _item("A1", LABEL_REQUIREMENT)


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Attachments Co")
        self.est = Establishment.objects.create(name="Attachments Farm", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=3.0)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", certifier_name="CCOF"
        )
        self.osp.module_responses = {
            "modules": {"g7_0_labeling": {"answers": {"product_leaves_as": _answer(["consumer_packaging"])}}}
        }
        self.osp.save(update_fields=["module_responses"])

    def _doc(self, title, content=b"%PDF-1.4 label artwork", **links):
        doc = GeneratedDocument(
            establishment=self.est,
            source="upload",
            folder="organic_system_plan",
            title=title,
            content_type="application/pdf",
            size_bytes=len(content),
            **links,
        )
        doc.file.save(f"{title}.pdf", ContentFile(content), save=True)
        return doc

    def _sold_season(self):
        season = History.objects.create(
            name="2026 blueberries",
            parcel=self.parcel,
            product=Product.objects.create(name="Blueberries"),
            start_date=timezone.make_aware(datetime(2026, 3, 1)),
            finish_date=timezone.make_aware(datetime(2026, 8, 20)),
            lot_id="NB-26-01",
        )
        ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.HARVESTING,
            description="first pick",
            date=timezone.make_aware(datetime(2026, 7, 14)),
            yield_quantity=6200,
            yield_unit="lb",
        )
        sale = SalesRecord.objects.create(
            production=season,
            sale_date=date(2026, 8, 25),
            buyer_name="Organically Grown Company",
            quantity=6000,
            quantity_unit="lb",
            invoice_number="INV-2026-0912",
            bill_of_lading="BOL-77120",
            organic_on_invoice=True,
        )
        return season, sale

    def _zip(self):
        return zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp)))

    def _label_state(self):
        with building(build_manifest(self.osp)):
            return row_answer_state(_Answers(self.osp), LABEL_ITEM)


class TheRequirementDecidesTests(_Farm):
    def test_a_file_uploaded_for_the_label_question_rides_in_labels_and_answers_it(self):
        doc = self._doc("Retail clamshell label", linked_section="g7_0_labeling", requirement=LABEL_REQUIREMENT)
        self.assertEqual(self._label_state().state, "answered")
        zf = self._zip()
        labels = [n for n in zf.namelist() if n.startswith("labels/")]
        self.assertEqual(len(labels), 1, zf.namelist())
        path = labels[0]
        self.assertTrue(path.startswith(f"labels/{doc.pk}-Retail clamshell label"))
        self.assertIn(path, _pdf_text(zf.read("modules/G7_0.pdf")))

    def test_a_file_uploaded_only_to_the_section_answers_nothing_and_ships_nothing(self):
        self._doc("Soil test", linked_section="g7_0_labeling")
        self.assertEqual(self._label_state().state, "attachment_not_identified")
        self.assertFalse([n for n in self._zip().namelist() if n.startswith("labels/")])

    def test_a_file_for_another_requirement_does_not_answer_the_label_question(self):
        self._doc(
            "Compost invoice",
            linked_section="g4_1_compost_manure",
            requirement="g4_1_compost_manure.purchased_compost_upload",
        )
        self.assertEqual(self._label_state().state, "attachment_missing")


class FilesThatDoNotShipAreNamedTests(_Farm):
    def test_an_unreadable_file_is_named_not_attached_and_the_packet_still_builds(self):
        gone = self._doc("Label gone from storage", requirement=LABEL_REQUIREMENT)
        default_storage.delete(gone.file.name)
        empty = self._doc("Empty label", content=b"", requirement=LABEL_REQUIREMENT)
        empty.size_bytes = 0
        empty.save(update_fields=["size_bytes"])
        state = self._label_state()
        self.assertEqual(state.state, "attachment_unreadable")
        self.assertIn("Label gone from storage", state.detail)
        zf = self._zip()
        self.assertFalse([n for n in zf.namelist() if n.startswith("labels/")])
        coverage = _pdf_text(zf.read("04-coverage-and-scope.pdf"))
        self.assertIn("could not be read", coverage)
        module = _pdf_text(zf.read("modules/G7_0.pdf"))
        self.assertIn("Label gone from storage: not in this packet (could not be read from storage)", module)
        self.assertIn("Empty label: not in this packet (the stored file is empty)", module)

    @override_settings(PACKET_ATTACHMENT_BUDGET_BYTES=10)
    def test_a_file_past_the_size_limit_is_held_outside_named_and_not_answered(self):
        self._doc("Big label", content=b"x" * 100, requirement=LABEL_REQUIREMENT)
        state = self._label_state()
        self.assertEqual(state.state, "attachment_held_outside_packet")
        zf = self._zip()
        self.assertFalse([n for n in zf.namelist() if n.startswith("labels/")])
        self.assertIn("kept in Trazo's document store", _pdf_text(zf.read("04-coverage-and-scope.pdf")))

    def test_an_unreadable_parcel_map_is_not_reported_as_attached(self):
        """The Parcel Application used to say "attached to this packet" about a map the loop had
        silently failed to read."""
        doc = self._doc("North map", parcel=self.parcel, linked_section="parcel_application_map")
        default_storage.delete(doc.file.name)
        zf = self._zip()
        self.assertFalse([n for n in zf.namelist() if n.startswith("parcels/maps/")])
        parcel_pdf = next(n for n in zf.namelist() if n.startswith("parcels/parcel-application"))
        text = _pdf_text(zf.read(parcel_pdf))
        self.assertNotIn("attached to this packet", text)
        self.assertIn("is not in this packet", text)


class SaleSourcesTests(_Farm):
    def test_a_typed_number_is_never_presented_as_a_held_document(self):
        self._sold_season()
        text = _pdf_text(self._zip().read("05-audit-trail-exhibit.pdf"))
        self.assertIn(
            "invoice number and bill of lading number are recorded as text; no source document is attached", text
        )

    def test_an_attached_invoice_is_named_by_its_path_and_rides_in_the_zip(self):
        season, sale = self._sold_season()
        doc = self._doc("Invoice 0912", history=season, sales_record=sale, source_kind="invoice")
        zf = self._zip()
        path = f"audit-trail/sale-{sale.pk}/{doc.pk}-Invoice 0912.pdf"
        self.assertIn(path, zf.namelist())
        text = _pdf_text(zf.read("05-audit-trail-exhibit.pdf"))
        self.assertIn(path, text)
        self.assertNotIn("recorded as text", text)


class UploadLinksAreValidatedTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="att@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Upload Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        # A company with no subscription has no storage at all (`check_storage_quota`).
        grant_compliance_exports(self.company)
        self.est = Establishment.objects.create(name="Upload Farm", company=self.company)
        other_company = Company.objects.create(name="Other Co")
        other_est = Establishment.objects.create(name="Other Farm", company=other_company)
        other_parcel = Parcel.objects.create(name="Elsewhere", establishment=other_est, area=1.0)
        season = History.objects.create(name="Other season", parcel=other_parcel)
        self.foreign_sale = SalesRecord.objects.create(
            production=season, sale_date=date(2026, 8, 1), buyer_name="X", quantity=1, quantity_unit="lb"
        )
        self.client.force_authenticate(user=self.user)

    def _post(self, **fields):
        from django.core.files.uploadedfile import SimpleUploadedFile

        url = f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/documents/"
        return self.client.post(
            url,
            {"file": SimpleUploadedFile("label.pdf", b"%PDF-1.4 x", "application/pdf"), **fields},
            format="multipart",
        )

    def test_a_requirement_that_no_section_asks_for_is_refused(self):
        res = self._post(requirement="g7_0_labeling.not_a_question")
        self.assertEqual(res.status_code, 400, res.content[:300])
        self.assertIn("requirement", res.json())

    def test_a_real_requirement_is_stored(self):
        res = self._post(requirement=LABEL_REQUIREMENT, linked_section="g7_0_labeling")
        self.assertEqual(res.status_code, 201, res.content[:300])
        self.assertEqual(GeneratedDocument.objects.get(pk=res.json()["id"]).requirement, LABEL_REQUIREMENT)

    def test_another_farms_sale_cannot_be_linked(self):
        res = self._post(sales_record=self.foreign_sale.pk, source_kind="invoice")
        self.assertEqual(res.status_code, 400, res.content[:300])
        self.assertFalse(GeneratedDocument.objects.filter(sales_record=self.foreign_sale).exists())


class OneDocumentTwoRoutesTests(_Farm):
    """Review of back #81: a file uploaded for the label question AND linked to a sale was read,
    charged to the budget and written twice, because the dedup keyed on a path that differs between
    the two routes."""

    def test_it_ships_once_answers_the_label_and_is_named_on_the_sale(self):
        season, sale = self._sold_season()
        content = b"%PDF-1.4 " + b"x" * 90
        doc = self._doc(
            "Invoice with label",
            content=content,
            history=season,
            sales_record=sale,
            source_kind="invoice",
            requirement=LABEL_REQUIREMENT,
        )
        # Room for the file once, not twice: a double charge would hold the second copy outside.
        with override_settings(PACKET_ATTACHMENT_BUDGET_BYTES=len(content) + 10):
            manifest = build_manifest(self.osp)
            entries = [e for e in manifest.entries if e.source_id == f"doc:{doc.pk}"]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].state, "attached")
            self.assertEqual(self._label_state().state, "answered")
            zf = self._zip()
        copies = [n for n in zf.namelist() if f"/{doc.pk}-Invoice with label" in n]
        self.assertEqual(len(copies), 1, zf.namelist())
        exhibit = _pdf_text(zf.read("05-audit-trail-exhibit.pdf"))
        self.assertIn(copies[0], exhibit)
        self.assertNotIn("recorded as text", exhibit)


FACILITY_PEST_REQUIREMENT = "g9_0_facility_pest.facility_pest_records_upload"


class FacilityPestRecordsTests(_Farm):
    """G9.0 states which facility pest records are kept; until 2026-11-03 the packet could carry
    none of them, because no Trazo record type covers a structure. The upload is where the pest
    control company's service tickets and the trap logs attach."""

    def test_a_service_report_rides_in_the_packet_and_the_module_names_it(self):
        # The upload shows once the plan says which records are kept (not "none yet").
        self.osp.module_responses["modules"]["g9_0_facility_pest"] = {
            "answers": {"pest_control_records": _answer(["site_visit_reports", "monitoring_device_records"])}
        }
        self.osp.save(update_fields=["module_responses"])
        doc = self._doc(
            "Pest control service report, March",
            linked_section="g9_0_facility_pest",
            requirement=FACILITY_PEST_REQUIREMENT,
        )
        zf = self._zip()
        shipped = [n for n in zf.namelist() if str(doc.pk) in n and "Pest control service report" in n]
        self.assertEqual(len(shipped), 1, zf.namelist())
        self.assertIn("Pest control service report, March", _pdf_text(zf.read("modules/G9_0.pdf")))


class FacilityPestUploadIsAcceptedTests(UploadLinksAreValidatedTests):
    def test_the_facility_pest_records_requirement_is_stored(self):
        res = self._post(requirement=FACILITY_PEST_REQUIREMENT, linked_section="g9_0_facility_pest")
        self.assertEqual(res.status_code, 201, res.content[:300])
        self.assertEqual(GeneratedDocument.objects.get(pk=res.json()["id"]).requirement, FACILITY_PEST_REQUIREMENT)
