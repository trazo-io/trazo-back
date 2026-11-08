"""The certifier inspection record in the renewal packet: document 02s and inspections/ (2026-11-08).

02s is not part of any filing, so a live record can print there without changing a signed document.
It lists the most recent inspection (WSDA AGR 2262 5a(i)), every item with no resolution notice
attached (OTCO O1 D-1E), and items resolved in the last year, each with the agent's letter, the
operation's response and files, and the § 205.662(b) resolution notice, attached under inspections/.
Every line is what the operation recorded: an empty record says "in Trazo", never "no noncompliance".
"""

import io
import zipfile
from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.test import TestCase

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import CertifierInspection, CertifierNotice, OrganicSystemPlan
from certifications.services.certifier_notices import RESOLVED_LISTED_FOR_DAYS, packet_records
from certifications.services.osp_module_pdf import generate_osp_packet
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from subscriptions.testing import grant_compliance_exports

CCOF = "CCOF Certification Services, LLC"
STATUS = "02s-renewal-status-and-routing.pdf"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Packet(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Inspected Orchards")
        grant_compliance_exports(self.company)
        self.est = Establishment.objects.create(name="Home Orchard", company=self.company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            certifier_name=CCOF,
            module_responses={"schema_version": 1, "parcel_modules": {}, "modules": {}},
        )

    def doc(self, title, body=b"%PDF-1.4 certifier copy"):
        doc = GeneratedDocument(
            establishment=self.est,
            folder="certifications",
            source="upload",
            title=title,
            content_type="application/pdf",
        )
        doc.file.save(f"{title}.pdf", ContentFile(body), save=False)
        doc.save()
        return doc

    def packet(self):
        data = generate_osp_packet(self.osp)
        zf = zipfile.ZipFile(io.BytesIO(data))
        return zf, _text(zf.read(STATUS))


class EmptyRecordTests(_Packet):
    def test_an_empty_record_says_so_in_trazo_never_that_there_is_no_noncompliance(self):
        _zf, text = self.packet()
        self.assertIn("Certifier inspections and notices (operation's record)", text)
        self.assertIn("No inspection is recorded in Trazo.", text)
        self.assertIn("No item from the certifying agent is recorded in Trazo.", text)
        self.assertNotIn("no noncompliance", text.lower())


class RecordInPacketTests(_Packet):
    def setUp(self):
        super().setUp()
        self.report = self.doc("Inspection report 2026")
        self.letter = self.doc("Notice letter")
        self.sent = self.doc("Buffer log")
        self.inspection = CertifierInspection.objects.create(
            establishment=self.est,
            inspected_on=date(2026, 7, 14),
            certifying_agent=CCOF,
            inspector_name="Dana Ruiz",
            inspection_kind="annual",
            report_document=self.report,
        )
        CertifierInspection.objects.create(establishment=self.est, inspected_on=date(2025, 7, 2), certifying_agent=CCOF)
        self.notice = CertifierNotice.objects.create(
            establishment=self.est,
            inspection=self.inspection,
            kind="notice_of_noncompliance",
            received_on=date(2026, 8, 1),
            description="Buffer records missing for block 4",
            notice_document=self.letter,
            respond_by=date(2026, 9, 1),
            response_kind="corrected",
            response_text="Buffer log filed",
            response_sent_on=date(2026, 8, 20),
        )
        self.notice.replace_response_documents([self.sent])

    def test_02s_lists_the_last_inspection_and_the_open_notice(self):
        zf, text = self.packet()
        self.assertIn("Date of the last organic inspection: 2026-07-14.", text)
        self.assertIn(f"Inspection on 2026-07-14 by {CCOF} (annual inspection, inspector Dana Ruiz).", text)
        # The older inspection has nothing under it and is not the latest: not listed.
        self.assertNotIn("Inspection on 2025-07-02", text)
        self.assertIn("Notices of noncompliance with no resolution notice attached, as recorded: 1.", text)
        self.assertIn("Buffer records missing for block 4", text)
        self.assertIn("Rebut or correct by 2026-09-01 (§ 205.662(a)(3)).", text)
        self.assertIn("Corrected, sent 2026-08-20: Buffer log filed", text)
        self.assertIn("No resolution notice from the certifying agent is recorded yet.", text)

    def test_every_file_rides_under_inspections_and_02s_names_its_path(self):
        zf, text = self.packet()
        names = set(zf.namelist())
        for doc in (self.report, self.letter, self.sent):
            path = f"inspections/{'report' if doc == self.report else 'letter' if doc == self.letter else 'response'}-{doc.pk}.pdf"
            self.assertIn(path, names)
            self.assertIn(path, text)
            self.assertEqual(zf.read(path), b"%PDF-1.4 certifier copy")

    def test_only_an_attached_resolution_notice_reads_resolved(self):
        self.notice.resolution_received_on = date.today()
        self.notice.save()
        _zf, text = self.packet()
        self.assertIn("is recorded; the certifying agent's resolution notice is not attached.", text)
        self.assertIn("as recorded: 1.", text)
        self.notice.resolution_document = self.doc("Resolution")
        self.notice.save()
        zf, text = self.packet()
        self.assertIn("The certifying agent's resolution notice is on file.", text)
        self.assertIn("as recorded: 0.", text)
        self.assertIn(f"inspections/resolution-{self.notice.resolution_document_id}.pdf", zf.namelist())

    def test_an_other_item_prints_the_agents_own_word(self):
        CertifierNotice.objects.create(
            establishment=self.est, kind="other_item", agent_label="Issue of concern", description="Bin labels faded"
        )
        _zf, text = self.packet()
        self.assertIn("Issue of concern: Bin labels faded", text)
        # Not counted as a notice of noncompliance.
        self.assertIn("as recorded: 1.", text)


class SelectionTests(_Packet):
    def test_old_resolved_items_drop_out_open_ones_never_do(self):
        today = date(2026, 11, 8)
        old = today - timedelta(days=RESOLVED_LISTED_FOR_DAYS + 30)
        resolution = self.doc("Old resolution")
        stale_resolved = CertifierNotice.objects.create(
            establishment=self.est,
            kind="notice_of_noncompliance",
            description="old, resolved",
            resolution_received_on=old,
            resolution_document=resolution,
        )
        recent_resolved = CertifierNotice.objects.create(
            establishment=self.est,
            kind="notice_of_noncompliance",
            description="recent, resolved",
            resolution_received_on=today - timedelta(days=10),
            resolution_document=resolution,
        )
        old_open = CertifierNotice.objects.create(
            establishment=self.est, kind="notice_of_noncompliance", description="old, open", received_on=old
        )
        _latest, _inspections, notices = packet_records(self.est, today)
        self.assertNotIn(stale_resolved, notices)
        self.assertIn(recent_resolved, notices)
        self.assertIn(old_open, notices)

    def test_another_farm_record_never_prints(self):
        other = Establishment.objects.create(name="North Orchard", company=self.company, state="WA")
        CertifierNotice.objects.create(establishment=other, kind="notice_of_noncompliance", description="North only")
        CertifierInspection.objects.create(establishment=other, inspected_on=date(2026, 6, 1))
        _zf, text = self.packet()
        self.assertNotIn("North only", text)
        self.assertNotIn("2026-06-01", text)


class NoAnonymousReadTests(_Packet):
    def test_neither_route_answers_without_a_login(self):
        client = APIClient()
        base = f"/api/companies/{self.company.id}/establishments/{self.est.id}/"
        for route in ("certifier-inspections/", "certifier-notices/"):
            with self.subTest(route=route):
                self.assertIn(client.get(base + route).status_code, (401, 403))
