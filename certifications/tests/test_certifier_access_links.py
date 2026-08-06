"""Certifier review links — anonymous, read-only, revocable.

These links expose far more than the consumer QR page: supplier names and
invoices, purchase prices, applicator names, and open drift/nonconformance
findings. The tests below are the security contract, not nice-to-haves.

Design note pinned here: expired and revoked links return 404, never 410/403. A
distinct status would confirm to an unauthenticated caller that a token was once
real. The farmer sees the true state on their own authenticated dashboard.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import CertifierAccessLink, CertifierAccessLog, OrganicSystemPlan
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel, Product
from users.models import User, WorksIn


def make_operation_submission_ready(establishment, user):
    """Satisfy every OperationReadinessService blocker: OFPP, OSP, and records.

    Minting a certifier link now refuses over a submission blocker, so any test
    that exercises the happy path has to represent an operation a certifier would
    actually accept.
    """
    establishment.fraud_prevention_plan_uploaded = True
    establishment.ofpp_responsible_person = "Jose Ramirez"
    establishment.save(update_fields=["fraud_prevention_plan_uploaded", "ofpp_responsible_person"])

    # Sections must have real narrative: an OSP with every § 205.201(a) section empty
    # is now a submission BLOCKER, not a draft warning (2026-08-03 dossier review —
    # the PDF stamped itself DO-NOT-SUBMIT while readiness said ready=True).
    OrganicSystemPlan.objects.create(
        establishment=establishment,
        status="active",
        version_number=1,
        sections={
            "practices_procedures": {"narrative": "Cover crop, compost, drip irrigation.", "last_updated": None},
            "inputs_list": {"narrative": "Kocide 3000; composted green waste.", "last_updated": None},
            "monitoring_plan": {"narrative": "Supplier verification and annual review.", "last_updated": None},
            "recordkeeping_description": {"narrative": "Trazo event log, retained 5 years.", "last_updated": None},
            "commingling_barriers": {"narrative": "Single organic operation; no split.", "last_updated": None},
            "additional_certifier_info": {"narrative": "Land history affidavit on file.", "last_updated": None},
        },
    )

    parcel = Parcel.objects.create(name="North Block", establishment=establishment, area=10.0)
    product = Product.objects.create(name="Walnuts")
    History.objects.create(
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


class CertifierAccessLinkModelTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")

    def _link(self, **overrides):
        defaults = dict(
            establishment=self.establishment,
            token=CertifierAccessLink.generate_token(),
            expires_at=CertifierAccessLink.default_expiry(),
        )
        defaults.update(overrides)
        return CertifierAccessLink.objects.create(**defaults)

    def test_token_is_unguessable_and_unique(self):
        a = CertifierAccessLink.generate_token()
        b = CertifierAccessLink.generate_token()
        self.assertNotEqual(a, b)
        # secrets.token_urlsafe(32) yields ~43 chars.
        self.assertGreaterEqual(len(a), 40)

    def test_default_expiry_is_ninety_days_out(self):
        delta = CertifierAccessLink.default_expiry() - timezone.now()
        self.assertAlmostEqual(delta.days, CertifierAccessLink.DEFAULT_VALIDITY_DAYS, delta=1)

    def test_fresh_link_is_active(self):
        self.assertTrue(self._link().is_active)

    def test_expired_link_is_not_active(self):
        link = self._link(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(link.is_expired)
        self.assertFalse(link.is_active)

    def test_revoke_is_immediate_and_idempotent(self):
        link = self._link()
        link.revoke()
        self.assertTrue(link.is_revoked)
        self.assertFalse(link.is_active)

        first = link.revoked_at
        link.revoke()
        self.assertEqual(link.revoked_at, first, "re-revoking must not move the timestamp")


class CertifierReviewAnonymousAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(
            name="Home Ranch", company=self.company, state="CA", city="Springville"
        )
        self.link = CertifierAccessLink.objects.create(
            establishment=self.establishment,
            token=CertifierAccessLink.generate_token(),
            expires_at=CertifierAccessLink.default_expiry(),
            label="CCOF 2026 renewal",
        )

    def _meta_url(self, token):
        return f"/api/certifier-review/{token}/"

    def test_valid_link_returns_operation_context_without_authentication(self):
        response = self.client.get(self._meta_url(self.link.token))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["operation_name"], "Home Ranch")
        self.assertEqual(response.data["label"], "CCOF 2026 renewal")

    def test_metadata_never_exposes_the_token_or_internal_ids(self):
        response = self.client.get(self._meta_url(self.link.token))

        body = str(response.data)
        self.assertNotIn(self.link.token, body)
        self.assertNotIn("establishment_id", response.data)

    def test_unknown_token_is_404(self):
        self.assertEqual(self.client.get(self._meta_url("not-a-real-token")).status_code, 404)

    def test_expired_link_is_404_not_410(self):
        self.link.expires_at = timezone.now() - timedelta(seconds=1)
        self.link.save(update_fields=["expires_at"])

        # 404 deliberately: a 410 would confirm the token was once valid.
        self.assertEqual(self.client.get(self._meta_url(self.link.token)).status_code, 404)

    def test_revoked_link_is_404(self):
        self.link.revoke()

        self.assertEqual(self.client.get(self._meta_url(self.link.token)).status_code, 404)

    def test_every_open_is_logged_for_the_farmer(self):
        self.client.get(self._meta_url(self.link.token), HTTP_USER_AGENT="Inspector Browser 1.0")

        log = CertifierAccessLog.objects.get(link=self.link)
        self.assertEqual(log.action, "metadata")
        self.assertEqual(log.user_agent, "Inspector Browser 1.0")

    def test_revoked_link_access_is_not_logged(self):
        self.link.revoke()
        self.client.get(self._meta_url(self.link.token))

        self.assertEqual(CertifierAccessLog.objects.filter(link=self.link).count(), 0)

    def test_link_is_scoped_to_one_establishment(self):
        other_company = Company.objects.create(name="Someone Else Farms")
        other_est = Establishment.objects.create(name="Not Yours", company=other_company, state="CA")
        other_link = CertifierAccessLink.objects.create(
            establishment=other_est,
            token=CertifierAccessLink.generate_token(),
            expires_at=CertifierAccessLink.default_expiry(),
        )

        response = self.client.get(self._meta_url(other_link.token))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["operation_name"], "Not Yours")
        # And this operation's link must never surface the first one.
        self.assertNotEqual(response.data["operation_name"], "Home Ranch")

    def test_write_methods_are_rejected(self):
        url = self._meta_url(self.link.token)
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url, {})
                self.assertEqual(response.status_code, 405)


class CertifierReviewReadinessTests(TestCase):
    """The record-readiness findings the certifier page renders without a download.

    Added 2026-08-04 alongside the endpoint. `readiness_rows()` delegates to
    `AuditExportService.compliance_snapshot_rows()` per production, so these tests are about the
    ANONYMOUS DELIVERY of that data (scoping, filtering, logging, error handling) — the checks
    themselves are already covered by `test_audit_export_snapshot.py` and
    `test_record_completeness_snapshot.py`.
    """

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Walnuts")
        self.link = CertifierAccessLink.objects.create(
            establishment=self.establishment,
            token=CertifierAccessLink.generate_token(),
            expires_at=CertifierAccessLink.default_expiry(),
        )

    def _url(self, token):
        return f"/api/certifier-review/{token}/readiness/"

    def _make_production(self, name="2026 Walnuts"):
        return History.objects.create(
            name=name,
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=None,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def test_no_productions_returns_an_empty_but_valid_response(self):
        response = self.client.get(self._url(self.link.token))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["productions"], [])
        self.assertEqual(response.data["total_productions"], 0)
        self.assertEqual(response.data["total_findings"], 0)

    def test_a_blank_chemical_record_surfaces_as_a_finding(self):
        """The exact scenario the record-completeness registry exists to catch."""
        production = self._make_production()
        ChemicalEvent.objects.create(history=production, type="PE", date=timezone.now())

        response = self.client.get(self._url(self.link.token))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_productions"], 1)
        findings = response.data["productions"][0]["findings"]
        labels = [f["label"] for f in findings]
        self.assertIn("Record completeness — chemical (§ 205.103(b)(2))", labels)

    def test_complete_chemical_record_does_not_trigger_the_completeness_finding(self):
        """This `setUp` has no OSP/OFPP, so the operation carries OTHER findings regardless —
        the point here is narrower: a complete chemical record must not ALSO be flagged."""
        production = self._make_production()
        ChemicalEvent.objects.create(
            history=production,
            type="FE",
            commercial_name="Urea 46-0-0",
            volume="50",
            area="10",
            date=timezone.now(),
        )

        response = self.client.get(self._url(self.link.token))

        entry = next(p for p in response.data["productions"] if p["production_name"] == production.name)
        labels = [f["label"] for f in entry["findings"]]
        self.assertNotIn("Record completeness — chemical (§ 205.103(b)(2))", labels)

    def test_unknown_token_is_404(self):
        self.assertEqual(self.client.get(self._url("not-a-real-token")).status_code, 404)

    def test_expired_link_is_404(self):
        self.link.expires_at = timezone.now() - timedelta(seconds=1)
        self.link.save(update_fields=["expires_at"])

        self.assertEqual(self.client.get(self._url(self.link.token)).status_code, 404)

    def test_revoked_link_is_404(self):
        self.link.revoke()

        self.assertEqual(self.client.get(self._url(self.link.token)).status_code, 404)

    def test_open_is_logged_as_readiness_not_metadata(self):
        self.client.get(self._url(self.link.token), HTTP_USER_AGENT="Inspector Browser 1.0")

        log = CertifierAccessLog.objects.get(link=self.link)
        self.assertEqual(log.action, "readiness")
        self.assertEqual(log.user_agent, "Inspector Browser 1.0")

    def test_link_is_scoped_to_one_establishment(self):
        self._make_production()

        other_company = Company.objects.create(name="Someone Else Farms")
        other_est = Establishment.objects.create(name="Not Yours", company=other_company, state="CA")
        other_parcel = Parcel.objects.create(name="Other Block", establishment=other_est, area=5.0)
        History.objects.create(
            name="Not Yours 2026",
            start_date=timezone.now(),
            product=self.product,
            parcel=other_parcel,
            operator=None,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

        response = self.client.get(self._url(self.link.token))

        production_names = [p["production_name"] for p in response.data["productions"]]
        self.assertNotIn("Not Yours 2026", production_names)

    def test_readiness_and_dossier_agree_on_which_productions_are_in_scope(self):
        """Both read `OperationAuditExportService._productions()` — they must never disagree."""
        self._make_production("Season A")
        self._make_production("Season B")

        from history.services.operation_audit_export_service import OperationAuditExportService

        service = OperationAuditExportService(self.establishment, certification_type=self.link.certification_type)
        dossier_production_names = {p.name for p in service._productions()}

        response = self.client.get(self._url(self.link.token))
        readiness_production_names = {p["production_name"] for p in response.data["productions"]}

        self.assertTrue(readiness_production_names.issubset(dossier_production_names))


class CertifierLinkManagementTests(TestCase):
    """Farmer-side create/list/revoke. Tenant isolation is the contract."""

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")
        self.user = User.objects.create_user(email="grower@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role="CA")

        self.outsider = User.objects.create_user(email="outsider@test.com", password="x")
        self.other_company = Company.objects.create(name="Someone Else Farms")
        WorksIn.objects.create(user=self.outsider, company=self.other_company, role="CA")

        make_operation_submission_ready(self.establishment, self.user)

        self.url = f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/certifier-links/"

    def _as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_owner_can_mint_a_link_and_gets_the_token_back(self):
        response = self._as(self.user).post(self.url, {"label": "CCOF 2026 renewal"}, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["token"])
        self.assertTrue(response.data["is_active"])

    def test_expiry_defaults_when_not_supplied(self):
        response = self._as(self.user).post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNotNone(response.data["expires_at"])

    def test_client_cannot_choose_its_own_token(self):
        response = self._as(self.user).post(self.url, {"token": "guessable"}, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotEqual(response.data["token"], "guessable")

    def test_invalid_certification_type_is_rejected(self):
        response = self._as(self.user).post(self.url, {"certification_type": "nonsense"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("certification_type", response.data)

    def test_past_expiry_is_rejected(self):
        past = (timezone.now() - timedelta(days=1)).isoformat()
        response = self._as(self.user).post(self.url, {"expires_at": past}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("expires_at", response.data)

    def test_delete_revokes_and_preserves_the_access_log(self):
        created = self._as(self.user).post(self.url, {}, format="json").data
        link = CertifierAccessLink.objects.get(id=created["id"])
        CertifierAccessLog.objects.create(link=link, action="dossier")

        response = self._as(self.user).delete(f"{self.url}{link.id}/")

        self.assertEqual(response.status_code, 200)
        link.refresh_from_db()
        self.assertTrue(link.is_revoked)
        self.assertEqual(
            CertifierAccessLog.objects.filter(link=link).count(),
            1,
            "the log is evidence of who read the records — revocation must not erase it",
        )

    def test_another_company_cannot_list_these_links(self):
        self._as(self.user).post(self.url, {}, format="json")

        response = self._as(self.outsider).get(self.url)

        self.assertIn(response.status_code, (403, 404))

    def test_anonymous_cannot_manage_links(self):
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_viewer_role_cannot_mint_a_link(self):
        """A VIEWER can read the farm but must not be able to hand a third party
        the operation's supplier invoices and applicator names."""
        viewer = User.objects.create_user(email="viewer@test.com", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role="VW")

        response = self._as(viewer).post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_viewer_role_can_still_read_links(self):
        viewer = User.objects.create_user(email="viewer2@test.com", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role="VW")

        self.assertEqual(self._as(viewer).get(self.url).status_code, 200)


class CertifierDossierDownloadTests(TestCase):
    """The link must actually deliver the audit dossier, not just metadata."""

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")
        self.link = CertifierAccessLink.objects.create(
            establishment=self.establishment,
            token=CertifierAccessLink.generate_token(),
            expires_at=CertifierAccessLink.default_expiry(),
        )

    def _url(self, token):
        return f"/api/certifier-review/{token}/dossier/"

    def test_valid_link_streams_a_pdf_without_authentication(self):
        response = self.client.get(self._url(self.link.token))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        body = b"".join(response.streaming_content)
        self.assertTrue(body.startswith(b"%PDF"), "must be a real PDF, not an error page")

    def test_download_is_logged_separately_from_opening(self):
        self.client.get(self._url(self.link.token))

        log = CertifierAccessLog.objects.get(link=self.link)
        self.assertEqual(log.action, "dossier")

    def test_revoked_link_cannot_download(self):
        self.link.revoke()

        self.assertEqual(self.client.get(self._url(self.link.token)).status_code, 404)

    def test_expired_link_cannot_download(self):
        self.link.expires_at = timezone.now() - timedelta(seconds=1)
        self.link.save(update_fields=["expires_at"])

        self.assertEqual(self.client.get(self._url(self.link.token)).status_code, 404)


class PreShareReadinessTests(TestCase):
    """A farmer must not be able to send their certifier a dossier that will fail.

    The dossier already stamps DO-NOT-SUBMIT, but by the time it does, the URL has
    been sent and the reviewer has opened it. The moment to stop is before sharing.
    """

    def setUp(self):
        self.company = Company.objects.create(name="Tule River Orchards")
        # farming_method marks this as an operation the NOP checks apply to; without
        # an organic signal the OFPP/OSP requirements are correctly skipped.
        self.establishment = Establishment.objects.create(
            name="Home Ranch", company=self.company, state="CA", farming_method="Certified Organic"
        )
        self.user = User.objects.create_user(email="grower2@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role="CA")
        self.url = f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/certifier-links/"

    def _client(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        return client

    def test_blocked_operation_cannot_mint_a_link(self):
        # Nothing set up: no OFPP, no OSP, no records.
        response = self._client().post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("blockers", response.data)
        keys = {b["key"] for b in response.data["blockers"]}
        self.assertEqual(keys, {"ofpp", "osp", "records"})

    def test_every_blocker_names_a_concrete_fix(self):
        response = self._client().post(self.url, {}, format="json")

        for blocker in response.data["blockers"]:
            with self.subTest(key=blocker["key"]):
                self.assertTrue(blocker["fix"], "a blocker without an action is a puzzle, not a task")

    def test_ready_operation_can_mint(self):
        make_operation_submission_ready(self.establishment, self.user)

        response = self._client().post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 201, response.data)

    def test_readiness_endpoint_reports_blockers_before_anything_is_shared(self):
        response = self._client().get(f"{self.url}readiness/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["ready"])
        self.assertEqual(len(response.data["blockers"]), 3)

    def test_readiness_endpoint_reports_ready(self):
        make_operation_submission_ready(self.establishment, self.user)

        response = self._client().get(f"{self.url}readiness/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ready"])
        self.assertEqual(response.data["blockers"], [])

    def test_suspicious_ofpp_filename_is_a_blocker_even_though_uploaded(self):
        from django.core.files.base import ContentFile

        make_operation_submission_ready(self.establishment, self.user)
        self.establishment.fraud_prevention_plan_document.save(
            "factura-2026.pdf", ContentFile(b"not a plan"), save=True
        )

        response = self._client().get(f"{self.url}readiness/")

        self.assertFalse(response.data["ready"])
        self.assertEqual([b["key"] for b in response.data["blockers"]], ["ofpp"])

    def test_non_organic_profile_does_not_demand_an_ofpp(self):
        # The SOE fraud-prevention requirement is NOP-scoped; a GlobalG.A.P.
        # dossier must not be blocked over it.
        make_operation_submission_ready(self.establishment, self.user)
        self.establishment.fraud_prevention_plan_uploaded = False
        self.establishment.save(update_fields=["fraud_prevention_plan_uploaded"])

        response = self._client().get(f"{self.url}readiness/?certification_type=globalgap")

        self.assertTrue(response.data["ready"], response.data["blockers"])


class ReadinessScopeTests(TestCase):
    """The NOP checks must only fire for operations actually in the NOP system.

    Two bugs this pins:
      1. `_check_osp` was not profile-gated, so a GlobalG.A.P. dossier was blocked
         over a missing Organic System Plan — a 7 CFR 205.201 artifact that has
         nothing to do with food safety. A non-organic operation could therefore
         never share records at all.
      2. A conventional grower's dashboard announced that their Organic Fraud
         Prevention Plan was missing — a requirement they are not subject to.
    """

    def setUp(self):
        self.company = Company.objects.create(name="Conventional Co")
        self.establishment = Establishment.objects.create(name="Plain Farm", company=self.company, state="CA")
        self.user = User.objects.create_user(email="conv@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role="CA")
        self.url = f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/certifier-links/"

        # Records exist; only the NOP artifacts are absent.
        parcel = Parcel.objects.create(name="Field", establishment=self.establishment, area=5.0)
        product = Product.objects.create(name="Table Grapes")
        History.objects.create(
            name="2026 Grapes",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
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

    def _client(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        return client

    def test_conventional_operation_is_not_judged_against_nop(self):
        response = self._client().get(f"{self.url}readiness/")

        self.assertFalse(response.data["applicable"])
        self.assertTrue(response.data["ready"])
        self.assertEqual(response.data["blockers"], [])

    def test_conventional_operation_can_still_share_records(self):
        # The whole point: a non-organic grower must not be locked out of sharing.
        response = self._client().post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 201, response.data)

    def test_globalgap_profile_is_not_blocked_by_a_missing_osp(self):
        response = self._client().get(f"{self.url}readiness/?certification_type=globalgap")

        self.assertFalse(response.data["applicable"])
        self.assertNotIn("osp", [b["key"] for b in response.data["blockers"]])

    def test_farming_method_marks_an_operation_as_organic(self):
        self.establishment.farming_method = "Certified Organic"
        self.establishment.save(update_fields=["farming_method"])

        response = self._client().get(f"{self.url}readiness/")

        self.assertTrue(response.data["applicable"])
        self.assertIn("ofpp", [b["key"] for b in response.data["blockers"]])

    def test_an_osp_alone_marks_an_operation_as_organic(self):
        OrganicSystemPlan.objects.create(establishment=self.establishment, status="draft", version_number=1)

        response = self._client().get(f"{self.url}readiness/")

        self.assertTrue(response.data["applicable"])

    def test_readiness_is_not_readable_by_another_company(self):
        outsider = User.objects.create_user(email="nosy@test.com", password="x")
        other = Company.objects.create(name="Nosy Farms")
        WorksIn.objects.create(user=outsider, company=other, role="CA")
        client = APIClient()
        client.force_authenticate(user=outsider)

        response = client.get(f"{self.url}readiness/")

        self.assertIn(response.status_code, (403, 404))
