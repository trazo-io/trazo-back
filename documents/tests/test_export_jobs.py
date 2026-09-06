"""
Background document builds (documents/services/export_jobs.py).

What must hold:
  1. A build files its result through the same DMS seam as every generator, records the
     fingerprint it was built from, and tells the requester with a LINK — never the bytes.
  2. A finished build is reused while the records it was built from are unchanged, and only
     then — the certifier link's "always current" promise, kept by construction.
  3. Two requests for the same build share one job; a build whose process died is reported
     as interrupted, not left spinning.
  4. The HTTP doors carry the plan gate and tenant scoping of the inline export they replace.
"""

from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from documents.models import ExportJob, GeneratedDocument
from documents.services import export_jobs
from documents.services.export_jobs import (
    INTERRUPTED_MESSAGE,
    OPERATION_DOSSIER,
    enqueue,
    fresh_document,
    reap_stale,
    run_worker_loop,
)
from history.models import ChemicalEvent, History
from history.services.records_fingerprint import records_fingerprint, records_fingerprint_signals
from notifications.models import Notification
from product.models import Parcel, Product
from subscriptions.testing import grant_compliance_exports
from users.models import User, WorksIn


def _operation(name="Job Farm", with_plan=True):
    company = Company.objects.create(name=name)
    user = User.objects.create_user(email=f"{name.lower().replace(' ', '')}@test.com", password="x", first_name="Dana")
    WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
    establishment = Establishment.objects.create(name=f"{name} Ranch", company=company, state="CA")
    parcel = Parcel.objects.create(name="Block A", establishment=establishment, area=12.0)
    product = Product.objects.create(name="Walnuts")
    production = History.objects.create(
        name="2026 Walnuts",
        start_date=timezone.now(),
        product=product,
        parcel=parcel,
        operator=user,
        earning=0.0,
        production_amount=0.0,
        reputation=0.0,
        confidence_score=0.0,
        transparency_score=0.0,
        public_views=0,
        unique_visitors=0,
        is_outdoor=True,
        published=True,
    )
    ChemicalEvent.objects.create(
        history=production, type=ChemicalEvent.PESTICIDE, commercial_name="Entrust SC", date=timezone.now()
    )
    if with_plan:
        grant_compliance_exports(company)
    return company, user, establishment, production


@override_settings(EXPORT_JOB_RUNNER="eager")
class EagerBuildTests(TestCase):
    def setUp(self):
        self.company, self.user, self.establishment, self.production = _operation()
        # Account creation sends its own welcome/verification mail; only the build's mail counts.
        mail.outbox.clear()

    def test_build_files_the_document_and_tells_the_requester_with_a_link(self):
        job, created = enqueue(self.establishment, requested_by=self.user, audience="farmer", kind=OPERATION_DOSSIER)
        self.assertTrue(created)
        job.refresh_from_db()
        self.assertEqual(job.status, "succeeded", job.error)
        self.assertEqual(len(job.fingerprint), 64)
        self.assertIsNotNone(job.finished_at)

        doc = job.document
        self.assertIsNotNone(doc)
        self.assertEqual(doc.source, "operation_dossier")
        self.assertEqual(doc.folder, "exports")
        self.assertEqual(doc.created_by, self.user)
        with doc.file.open("rb") as fh:
            self.assertTrue(fh.read(8).startswith(b"%PDF"))

        note = Notification.objects.get(recipient=self.user)
        self.assertEqual(note.extra_data["kind"], "export_ready")
        self.assertEqual(note.extra_data["establishment_id"], self.establishment.pk)
        self.assertEqual(note.extra_data["document_id"], doc.pk)

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.user.email])
        self.assertIn(f"/admin/dashboard/farm/{self.establishment.pk}/documents", message.body)
        # A LINK, never the file: the dossier can run to tens of MB and an inbox copy of a
        # revocable certifier artifact is a copy nobody can revoke.
        self.assertEqual(message.attachments, [])

    def test_finished_build_is_reused_until_the_records_change(self):
        job, _ = enqueue(self.establishment, requested_by=self.user, kind=OPERATION_DOSSIER)
        job.refresh_from_db()
        self.assertEqual(fresh_document(self.establishment, kind=OPERATION_DOSSIER), job.document)

        ChemicalEvent.objects.create(
            history=self.production, type=ChemicalEvent.PESTICIDE, commercial_name="Kocide 3000", date=timezone.now()
        )
        self.assertIsNone(fresh_document(self.establishment, kind=OPERATION_DOSSIER))

    def test_window_is_part_of_the_key(self):
        job, _ = enqueue(self.establishment, requested_by=self.user, kind=OPERATION_DOSSIER)
        job.refresh_from_db()
        self.assertIsNone(
            fresh_document(
                self.establishment,
                kind=OPERATION_DOSSIER,
                period_start=timezone.now().date() - timedelta(days=365),
            )
        )

    def test_anonymous_certifier_build_notifies_nobody(self):
        job, _ = enqueue(self.establishment, requested_by=None, audience="certifier", kind=OPERATION_DOSSIER)
        job.refresh_from_db()
        self.assertEqual(job.status, "succeeded", job.error)
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(mail.outbox, [])

    def test_a_failing_builder_lands_on_the_row_not_the_caller(self):
        with mock.patch.dict(export_jobs.BUILDERS, {OPERATION_DOSSIER: mock.Mock(side_effect=RuntimeError("boom"))}):
            job, _ = enqueue(self.establishment, requested_by=self.user, kind=OPERATION_DOSSIER)
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIn("boom", job.error)
        self.assertIsNone(job.document)
        self.assertEqual(mail.outbox, [])


@override_settings(EXPORT_JOB_RUNNER="worker")
class QueueSemanticsTests(TestCase):
    def setUp(self):
        self.company, self.user, self.establishment, self.production = _operation()

    def test_duplicate_requests_share_one_queued_job(self):
        first, created_first = enqueue(self.establishment, requested_by=self.user, kind=OPERATION_DOSSIER)
        second, created_second = enqueue(self.establishment, requested_by=self.user, kind=OPERATION_DOSSIER)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ExportJob.objects.count(), 1)
        self.assertEqual(first.status, "queued")

    def test_worker_drains_the_queue(self):
        job, _ = enqueue(self.establishment, requested_by=self.user, kind=OPERATION_DOSSIER)
        self.assertEqual(job.status, "queued")
        self.assertEqual(run_worker_loop(once=True), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, "succeeded", job.error)
        self.assertIsNotNone(job.document)
        self.assertEqual(run_worker_loop(once=True), 0)

    def test_stale_running_job_is_reported_as_interrupted(self):
        job = ExportJob.objects.create(
            establishment=self.establishment,
            kind=OPERATION_DOSSIER,
            status="running",
            started_at=timezone.now() - timedelta(minutes=40),
            heartbeat_at=timezone.now() - timedelta(minutes=30),
        )
        live = ExportJob.objects.create(
            establishment=self.establishment,
            kind=OPERATION_DOSSIER,
            certification_type="all",
            status="running",
            started_at=timezone.now(),
            heartbeat_at=timezone.now(),
        )
        self.assertEqual(reap_stale(), 1)
        job.refresh_from_db()
        live.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error, INTERRUPTED_MESSAGE)
        self.assertEqual(live.status, "running")

    @override_settings(EXPORT_JOB_RUNNER="thread")
    def test_thread_runner_starts_after_the_enqueue_commits(self):
        with mock.patch.object(export_jobs, "_start_thread") as start:
            with self.captureOnCommitCallbacks(execute=True):
                job, _ = enqueue(self.establishment, requested_by=self.user, kind=OPERATION_DOSSIER)
        start.assert_called_once_with(job.pk)

    def test_unknown_runner_is_a_loud_error(self):
        with override_settings(EXPORT_JOB_RUNNER="carrier-pigeon"):
            with self.assertRaises(ValueError):
                enqueue(self.establishment, requested_by=self.user, kind=OPERATION_DOSSIER)


class RecordsFingerprintTests(TestCase):
    def setUp(self):
        self.company, self.user, self.establishment, self.production = _operation()

    def test_stable_when_nothing_changed(self):
        self.assertEqual(records_fingerprint(self.establishment), records_fingerprint(self.establishment))

    def test_moves_on_a_new_event(self):
        before = records_fingerprint(self.establishment)
        ChemicalEvent.objects.create(
            history=self.production, type=ChemicalEvent.PESTICIDE, commercial_name="Kocide 3000", date=timezone.now()
        )
        self.assertNotEqual(before, records_fingerprint(self.establishment))

    def test_moves_on_an_edit_to_an_existing_event(self):
        """Events carry no updated_at; the audit log is what sees the edit."""
        from auditlog.models import LogEntry

        event = ChemicalEvent.objects.get(history=self.production)
        self.assertTrue(
            LogEntry.objects.get_for_object(event).exists(),
            "auditlog is not capturing ChemicalEvent writes in this test run — the edit signal is gone",
        )
        before = records_fingerprint(self.establishment)
        event.commercial_name = "Entrust SC (corrected)"
        event.save()
        self.assertNotEqual(before, records_fingerprint(self.establishment))

    def test_moves_on_a_deleted_event(self):
        before = records_fingerprint(self.establishment)
        ChemicalEvent.objects.get(history=self.production).delete()
        self.assertNotEqual(before, records_fingerprint(self.establishment))

    def test_moves_on_a_farm_or_parcel_edit(self):
        before = records_fingerprint(self.establishment)
        parcel = Parcel.objects.get(establishment=self.establishment)
        parcel.name = "Block A (renamed)"
        parcel.save()
        after_parcel = records_fingerprint(self.establishment)
        self.assertNotEqual(before, after_parcel)
        self.establishment.name = "Renamed Ranch"
        self.establishment.save()
        self.assertNotEqual(after_parcel, records_fingerprint(self.establishment))

    def test_does_not_move_for_another_farm(self):
        before = records_fingerprint(self.establishment)
        _operation(name="Neighbour")
        self.assertEqual(before, records_fingerprint(self.establishment))

    def test_signals_name_what_moved(self):
        before = records_fingerprint_signals(self.establishment)
        ChemicalEvent.objects.create(
            history=self.production, type=ChemicalEvent.PESTICIDE, commercial_name="Kocide 3000", date=timezone.now()
        )
        after = records_fingerprint_signals(self.establishment)
        moved = sorted(k for k in before if before[k] != after[k])
        self.assertEqual(moved, ["events.ChemicalEvent"])


@override_settings(EXPORT_JOB_RUNNER="worker")
class ExportJobEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company, self.user, self.establishment, self.production = _operation()
        self.url = f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/export-jobs/"

    def _status_url(self, public_id):
        return f"{self.url}{public_id}/"

    def test_member_starts_a_build_and_polls_it(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url, {"kind": "operation_dossier", "certification": "organic"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "queued")
        self.assertFalse(response.data["is_terminal"])
        public_id = response.data["public_id"]

        again = self.client.post(self.url, {"kind": "operation_dossier"}, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data["public_id"], public_id, "a second click must join the queued build")

        polled = self.client.get(self._status_url(public_id))
        self.assertEqual(polled.status_code, 200)
        self.assertEqual(polled.data["status"], "queued")
        self.assertIsNone(polled.data["document_id"])

    @override_settings(EXPORT_JOB_RUNNER="eager")
    def test_finished_build_points_at_a_downloadable_document(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url, {"kind": "operation_dossier"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "succeeded", response.data.get("error"))
        doc_id = response.data["document_id"]
        self.assertIsNotNone(doc_id)
        download = self.client.get(
            f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/documents/{doc_id}/download/"
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["Content-Type"], "application/pdf")

    def test_window_is_validated(self):
        self.client.force_authenticate(user=self.user)
        bad = self.client.post(self.url, {"start": "2026-13-01"}, format="json")
        self.assertEqual(bad.status_code, 400)
        inverted = self.client.post(self.url, {"start": "2026-06-01", "end": "2026-01-01"}, format="json")
        self.assertEqual(inverted.status_code, 400)
        ok = self.client.post(self.url, {"start": "2025-10-01", "end": "2026-09-30"}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertEqual(ok.data["period_start"], "2025-10-01")
        self.assertEqual(ok.data["period_end"], "2026-09-30")

    def test_unknown_kind_and_certification_are_rejected(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.post(self.url, {"kind": "tax-return"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"certification": "iso9001"}, format="json").status_code, 400)

    def test_malformed_job_id_is_a_404_not_a_500(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(f"{self.url}not-a-uuid-at-all-not-a-uuid-at-all-x/").status_code, 404)

    def test_non_member_cannot_start_or_read_another_companys_build(self):
        _, outsider, _, _ = _operation(name="Outsider")
        self.client.force_authenticate(user=outsider)
        self.assertIn(self.client.post(self.url, {"kind": "operation_dossier"}, format="json").status_code, (403, 404))
        job = ExportJob.objects.create(establishment=self.establishment, kind=OPERATION_DOSSIER)
        self.assertIn(self.client.get(self._status_url(job.public_id)).status_code, (403, 404))

    def test_unauthenticated_is_denied(self):
        self.assertIn(self.client.post(self.url, {"kind": "operation_dossier"}, format="json").status_code, (401, 403))

    def test_starter_farm_meets_the_same_gate_as_the_inline_export(self):
        company, user, establishment, _ = _operation(name="Starter", with_plan=False)
        self.client.force_authenticate(user=user)
        url = f"/api/companies/{company.id}/establishments/{establishment.id}/export-jobs/"
        response = self.client.post(url, {"kind": "operation_dossier"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ExportJob.objects.filter(establishment=establishment).count(), 0)

    def test_status_read_reaps_a_dead_build(self):
        self.client.force_authenticate(user=self.user)
        job = ExportJob.objects.create(
            establishment=self.establishment,
            kind=OPERATION_DOSSIER,
            status="running",
            started_at=timezone.now() - timedelta(hours=1),
            heartbeat_at=timezone.now() - timedelta(hours=1),
        )
        polled = self.client.get(self._status_url(job.public_id))
        self.assertEqual(polled.data["status"], "failed")
        self.assertEqual(polled.data["error"], INTERRUPTED_MESSAGE)


class ExportJobSerializerContractTests(TestCase):
    def test_the_bytes_never_travel_through_the_status_payload(self):
        from documents.serializers import ExportJobSerializer

        fields = set(ExportJobSerializer.Meta.fields)
        self.assertIn("document_id", fields)
        self.assertNotIn("document", fields)
        self.assertNotIn("file", fields)
        self.assertTrue({"status", "progress_current", "progress_total", "progress_label", "error"} <= fields)


class GeneratedDocumentSourceTests(TestCase):
    def test_operation_dossier_is_a_known_source(self):
        self.assertIn("operation_dossier", dict(GeneratedDocument.SOURCE_CHOICES))
