"""
The certifier review link builds the dossier at most once per change (2026-09-05).

Before: every open regenerated the whole operation PDF inside the request — a minute on a
12-production farm, from an anonymous URL, against an edge that drops requests at ~100 s.
Now: same records → the filed build streams at once; changed records → 202 with a job the page
polls, then `?job=<id>` streams exactly the build it watched. The reviewer still never sees a
stale copy; they just stop paying for an identical rebuild.
"""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import CertifierAccessLink, CertifierAccessLog
from company.models import Company, Establishment
from documents.models import ExportJob
from documents.services.export_jobs import OPERATION_DOSSIER, run_worker_loop
from history.models import ChemicalEvent, Production
from product.models import Parcel, Product
from users.models import User


@override_settings(EXPORT_JOB_RUNNER="worker")
class CertifierDossierBuildTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="grower@test.com", password="x")
        self.company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")
        parcel = Parcel.objects.create(name="North Block", establishment=self.establishment, area=10.0)
        product = Product.objects.create(name="Navel Oranges")
        self.production = Production.objects.create(
            name="2026 Navels",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        ChemicalEvent.objects.create(
            history=self.production, type=ChemicalEvent.PESTICIDE, commercial_name="Entrust SC", date=timezone.now()
        )
        self.link = CertifierAccessLink.objects.create(
            establishment=self.establishment,
            token=CertifierAccessLink.generate_token(),
            expires_at=CertifierAccessLink.default_expiry(),
            certification_type="organic",
            audience="certifier",
            created_by=self.user,
        )

    def _dossier(self, **params):
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"/api/certifier-review/{self.link.token}/dossier/" + (f"?{query}" if query else "")

    def _status(self, job_id):
        return f"/api/certifier-review/{self.link.token}/dossier/status/?job={job_id}"

    def test_first_open_starts_one_build_and_says_so(self):
        first = self.client.get(self._dossier())
        self.assertEqual(first.status_code, 202, first.content[:200])
        self.assertEqual(first.data["status"], "queued")
        self.assertEqual(first.data["audience"], "certifier")

        second = self.client.get(self._dossier())
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.data["public_id"], first.data["public_id"], "two opens must share one build")
        self.assertEqual(ExportJob.objects.count(), 1)
        # Nothing was handed over yet, so nothing is logged as a dossier access.
        self.assertFalse(CertifierAccessLog.objects.filter(link=self.link, action="dossier").exists())

    def test_poll_then_fetch_the_build_that_was_watched(self):
        started = self.client.get(self._dossier())
        job_id = started.data["public_id"]

        polled = self.client.get(self._status(job_id))
        self.assertEqual(polled.status_code, 200)
        self.assertEqual(polled.data["status"], "queued")

        self.assertEqual(run_worker_loop(once=True), 1)

        done = self.client.get(self._status(job_id))
        self.assertEqual(done.data["status"], "succeeded", done.data.get("error"))
        self.assertIsNotNone(done.data["document_id"])

        pdf = self.client.get(self._dossier(job=job_id))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertIn("audit-dossier.pdf", pdf["Content-Disposition"])
        self.assertTrue(b"".join(pdf.streaming_content).startswith(b"%PDF"))
        self.assertEqual(CertifierAccessLog.objects.filter(link=self.link, action="dossier").count(), 1)

    def test_unchanged_records_stream_the_filed_build_at_once(self):
        self.client.get(self._dossier())
        run_worker_loop(once=True)

        again = self.client.get(self._dossier())
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again["Content-Type"], "application/pdf")
        self.assertEqual(ExportJob.objects.count(), 1, "an identical dossier must not be rebuilt")

    def test_changed_records_start_a_new_build(self):
        self.client.get(self._dossier())
        run_worker_loop(once=True)
        ChemicalEvent.objects.create(
            history=self.production, type=ChemicalEvent.PESTICIDE, commercial_name="Kocide 3000", date=timezone.now()
        )
        rebuilt = self.client.get(self._dossier())
        self.assertEqual(rebuilt.status_code, 202)
        self.assertEqual(ExportJob.objects.count(), 2)

    @override_settings(EXPORT_JOB_RUNNER="eager")
    def test_eager_runner_streams_in_the_same_request(self):
        response = self.client.get(self._dossier())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_a_build_for_another_farm_is_not_reachable_through_this_link(self):
        other_company = Company.objects.create(name="Someone Else")
        other = Establishment.objects.create(name="Not Yours", company=other_company, state="CA")
        job = ExportJob.objects.create(establishment=other, kind=OPERATION_DOSSIER, status="succeeded")
        self.assertEqual(self.client.get(self._dossier(job=job.public_id)).status_code, 404)
        self.assertEqual(self.client.get(self._status(job.public_id)).status_code, 404)

    def test_malformed_and_unknown_job_ids_are_404s(self):
        self.assertEqual(self.client.get(self._dossier(job="nope")).status_code, 404)
        self.assertEqual(self.client.get(self._status("nope")).status_code, 404)
        self.assertEqual(self.client.get(self._status("00000000-0000-0000-0000-000000000000")).status_code, 404)

    def test_failed_build_reads_neutrally_to_the_reviewer(self):
        job = ExportJob.objects.create(
            establishment=self.establishment,
            kind=OPERATION_DOSSIER,
            status="failed",
            error="Traceback: KeyError 'album' in _build_photos_section",
        )
        response = self.client.get(self._status(job.public_id))
        self.assertEqual(response.data["status"], "failed")
        self.assertNotIn("Traceback", response.data["error"])
        self.assertNotIn("KeyError", response.data["error"])

    def test_revoked_link_reaches_neither_route(self):
        self.link.revoked_at = timezone.now()
        self.link.save(update_fields=["revoked_at"])
        job = ExportJob.objects.create(establishment=self.establishment, kind=OPERATION_DOSSIER)
        self.assertEqual(self.client.get(self._dossier()).status_code, 404)
        self.assertEqual(self.client.get(self._status(job.public_id)).status_code, 404)

    def test_dead_build_is_reported_as_interrupted_on_poll(self):
        job = ExportJob.objects.create(
            establishment=self.establishment,
            kind=OPERATION_DOSSIER,
            status="running",
            started_at=timezone.now() - timedelta(hours=1),
            heartbeat_at=timezone.now() - timedelta(hours=1),
        )
        response = self.client.get(self._status(job.public_id))
        self.assertEqual(response.data["status"], "failed")

    def test_status_probe_without_a_job_answers_ready_or_starts_a_build(self):
        """The page asks the JSON route first, so a check never opens a PDF stream."""
        probe_url = f"/api/certifier-review/{self.link.token}/dossier/status/"
        started = self.client.get(probe_url)
        self.assertEqual(started.status_code, 202, started.content[:200])
        self.assertEqual(started.data["status"], "queued")
        joined = self.client.get(probe_url)
        self.assertEqual(joined.data["public_id"], started.data["public_id"])
        self.assertEqual(ExportJob.objects.count(), 1)
        # No PDF was streamed, so nothing is logged as a dossier access.
        self.assertFalse(CertifierAccessLog.objects.filter(link=self.link, action="dossier").exists())

        run_worker_loop(once=True)
        ready = self.client.get(probe_url)
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.data, {"status": "ready"})
        self.assertEqual(ExportJob.objects.count(), 1)

    def test_poll_route_uses_its_own_throttle_scope(self):
        from django.conf import settings

        from certifications.views import CertifierPollThrottle

        self.assertEqual(CertifierPollThrottle.scope, "certifier_poll")
        self.assertIn("certifier_poll", settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])
