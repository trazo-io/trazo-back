"""The farm's own record of its certifier's inspections and the items the agent sent (2026-11-08).

§ 205.662(a) gives a certified operation a written notice with "the date by which the certified
operation must rebut or correct each noncompliance and submit supporting documentation"; (b) is the
agent's written resolution. WSDA AGR 2262 5a(i) asks for the date of the last organic inspection;
CCOF's contract D6 and OTCO O1 D-1E / D-7 ask for the letters and the corrective actions. Until this
slice the only places for any of it were a Documents upload and the annual update's free text.
"""

from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from auditlog.models import LogEntry
from rest_framework.test import APIClient

from certifications.models import CertifierInspection, CertifierNotice
from certifications.services.certifier_notices import (
    OPEN,
    RESOLUTION_STATED_NO_COPY,
    RESOLVED,
    RESPOND_BY_PASSED_NO_RESPONSE,
    RESPONSE_SENT,
    notice_status,
    unresolved,
)
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from subscriptions.testing import grant_compliance_exports
from users.models import User, WorksIn

CCOF = "CCOF Certification Services, LLC"


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Inspected Orchards")
        self.user = User.objects.create_user(email="inspections@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        # A document upload needs a subscription row (storage accounting); the records themselves do not.
        grant_compliance_exports(self.company)
        self.est = Establishment.objects.create(name="Home Orchard", company=self.company, state="WA")
        self.other_est = Establishment.objects.create(name="North Orchard", company=self.company, state="WA")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def base(self, est=None, company=None):
        est = est or self.est
        company = company or self.company
        return f"/api/companies/{company.id}/establishments/{est.id}/"

    def upload(self, est=None, title="Inspection report"):
        r = self.client.post(
            self.base(est) + "documents/",
            {
                "file": SimpleUploadedFile("copy.pdf", b"%PDF-1.4 certifier copy", content_type="application/pdf"),
                "title": title,
                "folder": "certifications",
            },
        )
        self.assertEqual(r.status_code, 201, r.content)
        return GeneratedDocument.objects.get(pk=r.json()["id"])

    def inspection(self, **fields):
        data = {"inspected_on": "2026-07-14", "certifying_agent": CCOF, **fields}
        r = self.client.post(self.base() + "certifier-inspections/", data, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return CertifierInspection.objects.get(pk=r.json()["id"])

    def notice(self, **fields):
        data = {"kind": "notice_of_noncompliance", "description": "Buffer records missing for block 4", **fields}
        r = self.client.post(self.base() + "certifier-notices/", data, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return CertifierNotice.objects.get(pk=r.json()["id"])

    def delete_doc(self, doc):
        return self.client.delete(self.base() + f"documents/{doc.id}/")

    def outsider(self):
        user = User.objects.create_user(email="other@inspections.test", password="x")
        other = Company.objects.create(name="Elsewhere")
        WorksIn.objects.create(user=user, company=other, role=WorksIn.COMPANY_ADMIN)
        return user


class InspectionTenancyTests(_Farm):
    def test_another_company_reaches_nothing(self):
        inspection = self.inspection()
        self.client.force_authenticate(self.outsider())
        url = self.base() + "certifier-inspections/"
        self.assertIn(self.client.get(url).status_code, (403, 404))
        self.assertIn(self.client.get(f"{url}{inspection.id}/").status_code, (403, 404))
        r = self.client.patch(f"{url}{inspection.id}/", {"inspector_name": "Mine now"}, format="json")
        self.assertIn(r.status_code, (403, 404))
        self.assertIn(self.client.delete(f"{url}{inspection.id}/").status_code, (403, 404))
        inspection.refresh_from_db()
        self.assertEqual(inspection.inspector_name, "")
        self.assertTrue(CertifierInspection.objects.filter(pk=inspection.pk).exists())

    def test_another_farms_document_fails_like_a_missing_one(self):
        theirs = self.upload(est=self.other_est)
        url = self.base() + "certifier-inspections/"
        foreign = self.client.post(url, {"inspected_on": "2026-07-14", "report_document": theirs.id}, format="json")
        missing = self.client.post(url, {"inspected_on": "2026-07-14", "report_document": 999999}, format="json")
        self.assertEqual(foreign.status_code, 400)
        self.assertEqual(
            str(foreign.json()).replace(str(theirs.id), "<id>"), str(missing.json()).replace("999999", "<id>")
        )
        self.assertFalse(CertifierInspection.objects.exists())

    def test_a_viewer_is_refused(self):
        viewer = User.objects.create_user(email="viewer@inspections.test", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.get(self.base() + "certifier-inspections/").status_code, 403)

    def test_another_farm_of_the_same_company_lists_only_its_own(self):
        self.inspection()
        r = self.client.get(self.base(self.other_est) + "certifier-inspections/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json() if isinstance(r.json(), list) else r.json()["results"], [])


class NoticeTenancyTests(_Farm):
    def test_another_company_reaches_nothing(self):
        notice = self.notice()
        self.client.force_authenticate(self.outsider())
        url = self.base() + "certifier-notices/"
        self.assertIn(self.client.get(url).status_code, (403, 404))
        self.assertIn(self.client.get(f"{url}{notice.id}/").status_code, (403, 404))
        r = self.client.patch(f"{url}{notice.id}/", {"response_text": "Mine now"}, format="json")
        self.assertIn(r.status_code, (403, 404))
        notice.refresh_from_db()
        self.assertEqual(notice.response_text, "")

    def test_another_farms_files_and_inspection_fail_like_missing_ones(self):
        theirs = self.upload(est=self.other_est)
        their_inspection = CertifierInspection.objects.create(establishment=self.other_est, inspected_on=date.today())
        url = self.base() + "certifier-notices/"
        base = {"kind": "notice_of_noncompliance", "description": "x"}
        for field, foreign_value, missing_value in (
            ("notice_document", theirs.id, 999999),
            ("resolution_document", theirs.id, 999999),
            ("response_document_ids", [theirs.id], [999999]),
            ("inspection", their_inspection.id, 999999),
        ):
            with self.subTest(field=field):
                foreign = self.client.post(url, {**base, field: foreign_value}, format="json")
                missing = self.client.post(url, {**base, field: missing_value}, format="json")
                self.assertEqual(foreign.status_code, 400, foreign.content)
                ids = (str(theirs.id), str(their_inspection.id))
                foreign_text = str(foreign.json())
                for i in ids:
                    foreign_text = foreign_text.replace(i, "<id>")
                self.assertEqual(foreign_text, str(missing.json()).replace("999999", "<id>"))
        self.assertFalse(CertifierNotice.objects.exists())


class InspectionRecordTests(_Farm):
    def test_an_inspection_with_its_report(self):
        report = self.upload()
        inspection = self.inspection(
            inspector_name="  Dana   Ruiz ", inspection_kind="annual", report_document=report.id
        )
        self.assertEqual(inspection.inspector_name, "Dana Ruiz")
        self.assertEqual(inspection.report_document, report)
        row = self.client.get(self.base() + f"certifier-inspections/{inspection.id}/").json()
        self.assertEqual(row["report_document_title"], "Inspection report")
        self.assertEqual(row["inspection_kind_display"], "Annual inspection")
        self.assertEqual(row["notice_count"], 0)

    def test_the_report_cannot_be_deleted_from_documents(self):
        report = self.upload()
        self.inspection(report_document=report.id)
        r = self.delete_doc(report)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "inspection_document_in_use")
        self.assertTrue(GeneratedDocument.objects.filter(pk=report.pk).exists())

    def test_an_inspection_with_items_under_it_is_not_deleted(self):
        inspection = self.inspection()
        self.notice(inspection=inspection.id)
        r = self.client.delete(self.base() + f"certifier-inspections/{inspection.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "inspection_has_notices")
        self.assertTrue(CertifierInspection.objects.filter(pk=inspection.pk).exists())

    def test_an_inspection_alone_can_be_deleted(self):
        inspection = self.inspection()
        r = self.client.delete(self.base() + f"certifier-inspections/{inspection.id}/")
        self.assertEqual(r.status_code, 204)


class NoticeRecordTests(_Farm):
    def test_an_other_item_needs_the_agents_own_word(self):
        r = self.client.post(
            self.base() + "certifier-notices/", {"kind": "other_item", "description": "x"}, format="json"
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("agent_label", r.json())
        notice = self.notice(kind="other_item", agent_label="Issue of concern")
        self.assertEqual(notice.agent_label, "Issue of concern")

    def test_a_notice_of_noncompliance_carries_no_label_of_its_own(self):
        notice = self.notice(kind="other_item", agent_label="Issue of concern")
        r = self.client.patch(
            self.base() + f"certifier-notices/{notice.id}/", {"kind": "notice_of_noncompliance"}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.content)
        notice.refresh_from_db()
        self.assertEqual(notice.agent_label, "")

    def test_a_blank_description_is_refused(self):
        r = self.client.post(
            self.base() + "certifier-notices/", {"kind": "notice_of_noncompliance", "description": "  "}, format="json"
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("description", r.json())

    def test_response_documents_keep_the_order_they_were_given(self):
        first, second = self.upload(title="Buffer map"), self.upload(title="Harvest log")
        notice = self.notice(response_document_ids=[second.id, first.id])
        row = self.client.get(self.base() + f"certifier-notices/{notice.id}/").json()
        self.assertEqual([d["title"] for d in row["response_documents"]], ["Harvest log", "Buffer map"])
        self.client.patch(
            self.base() + f"certifier-notices/{notice.id}/", {"response_document_ids": [first.id]}, format="json"
        )
        row = self.client.get(self.base() + f"certifier-notices/{notice.id}/").json()
        self.assertEqual([d["title"] for d in row["response_documents"]], ["Buffer map"])

    def test_every_file_of_a_notice_is_held_against_delete(self):
        letter, sent, resolution = self.upload(title="Letter"), self.upload(title="Sent"), self.upload(title="Res")
        self.notice(
            notice_document=letter.id,
            response_document_ids=[sent.id],
            resolution_document=resolution.id,
            resolution_received_on="2026-09-01",
        )
        for doc in (letter, sent, resolution):
            with self.subTest(doc=doc.title):
                r = self.delete_doc(doc)
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json()["code"], "notice_document_in_use")
                self.assertTrue(GeneratedDocument.objects.filter(pk=doc.pk).exists())

    def test_the_served_status_is_derived(self):
        resolution = self.upload(title="Resolution")
        notice = self.notice()
        url = self.base() + f"certifier-notices/{notice.id}/"
        self.assertEqual(self.client.get(url).json()["status"], OPEN)
        self.client.patch(url, {"response_kind": "corrected", "response_sent_on": "2026-08-01"}, format="json")
        self.assertEqual(self.client.get(url).json()["status"], RESPONSE_SENT)
        self.client.patch(url, {"resolution_received_on": "2026-09-01"}, format="json")
        self.assertEqual(self.client.get(url).json()["status"], RESOLUTION_STATED_NO_COPY)
        self.client.patch(url, {"resolution_document": resolution.id}, format="json")
        self.assertEqual(self.client.get(url).json()["status"], RESOLVED)

    def test_a_change_to_a_response_is_logged(self):
        notice = self.notice()
        self.client.patch(
            self.base() + f"certifier-notices/{notice.id}/", {"response_text": "Buffer log filed"}, format="json"
        )
        entries = LogEntry.objects.get_for_object(notice)
        self.assertTrue(any("response_text" in (e.changes_dict or {}) for e in entries))


class _N:
    """A notice as `notice_status` reads it, without a database."""

    def __init__(self, **fields):
        self.resolution_document_id = None
        self.resolution_received_on = None
        self.response_kind = ""
        self.response_text = ""
        self.response_sent_on = None
        self.respond_by = None
        self.__dict__.update(fields)


class NoticeStatusTests(SimpleTestCase):
    TODAY = date(2026, 11, 8)

    def status(self, **fields):
        return notice_status(_N(**fields), self.TODAY)

    def test_only_an_attached_resolution_notice_reads_as_resolved(self):
        self.assertEqual(self.status(resolution_document_id=7), RESOLVED)
        self.assertEqual(self.status(resolution_received_on=self.TODAY), RESOLUTION_STATED_NO_COPY)

    def test_a_passed_date_with_no_response(self):
        self.assertEqual(self.status(respond_by=self.TODAY - timedelta(days=1)), RESPOND_BY_PASSED_NO_RESPONSE)
        self.assertEqual(self.status(respond_by=self.TODAY), OPEN)
        self.assertEqual(self.status(respond_by=self.TODAY + timedelta(days=30)), OPEN)

    def test_any_recorded_response_counts_as_sent(self):
        past = self.TODAY - timedelta(days=1)
        self.assertEqual(self.status(respond_by=past, response_kind="rebutted"), RESPONSE_SENT)
        self.assertEqual(self.status(respond_by=past, response_text="Filed the log"), RESPONSE_SENT)
        self.assertEqual(self.status(respond_by=past, response_sent_on=past), RESPONSE_SENT)
        self.assertEqual(self.status(respond_by=past, response_text="   "), RESPOND_BY_PASSED_NO_RESPONSE)

    def test_unresolved_keeps_everything_but_attached_resolutions(self):
        a, b, c = _N(resolution_document_id=1), _N(resolution_received_on=self.TODAY), _N()
        self.assertEqual(unresolved([a, b, c], self.TODAY), [b, c])
