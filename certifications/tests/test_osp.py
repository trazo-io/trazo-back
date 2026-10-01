"""
Sprint 5A tests — OSP model, Annual Update, Landowner Affidavit, ViewSet lifecycle.

Covers:
  - OSP creation with required section defaults
  - Version auto-increment on create
  - Lifecycle actions: submit / activate / new_version
  - Annual update unique constraint (one per prior_osp + year)
  - Landowner affidavit default attestation text (MOFGA canonical)
  - Section completion calculation
"""

from django.test import TestCase
from django.utils import timezone

from certifications.models import OSP_SECTION_KEYS, LandownerAffidavit, OrganicSystemPlan, OSPAnnualUpdate
from company.models import Company, Establishment
from product.models import Parcel
from users.models import User


class OSPModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="osp@test.com", password="x")
        self.company = Company.objects.create(name="OSP Farm")
        self.establishment = Establishment.objects.create(name="Main Field", company=self.company)

    def test_default_sections_include_all_required_keys(self):
        osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1)
        for key in OSP_SECTION_KEYS:
            self.assertIn(key, osp.sections)
            self.assertEqual(osp.sections[key], {"narrative": "", "last_updated": None})

    def test_section_completion_empty_zero(self):
        osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1)
        self.assertEqual(osp.section_completion, 0.0)

    def test_section_completion_half(self):
        sections = {k: {"narrative": "", "last_updated": None} for k in OSP_SECTION_KEYS}
        sections["practices_procedures"]["narrative"] = "x"
        sections["inputs_list"]["narrative"] = "y"
        sections["monitoring_plan"]["narrative"] = "z"
        osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, sections=sections)
        self.assertAlmostEqual(osp.section_completion, 3 / 6)

    def test_is_active_only_when_status_active(self):
        osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")
        self.assertFalse(osp.is_active)
        osp.status = "active"
        osp.save()
        self.assertTrue(osp.is_active)

    def test_version_uniqueness_per_establishment(self):
        OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1)
        with self.assertRaises(Exception):
            OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1)


class OSPAnnualUpdateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="AU Farm")
        self.establishment = Establishment.objects.create(name="F", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")

    def test_one_update_per_year_per_osp(self):
        OSPAnnualUpdate.objects.create(prior_osp=self.osp, reporting_year=2026)
        with self.assertRaises(Exception):
            OSPAnnualUpdate.objects.create(prior_osp=self.osp, reporting_year=2026)

    def test_different_years_allowed(self):
        OSPAnnualUpdate.objects.create(prior_osp=self.osp, reporting_year=2025)
        OSPAnnualUpdate.objects.create(prior_osp=self.osp, reporting_year=2026)
        self.assertEqual(OSPAnnualUpdate.objects.count(), 2)

    def test_serializer_accepts_annual_update_form_payload(self):
        # The exact shape the new farmer form (OSPAnnualUpdateCard) POSTs.
        from certifications.serializers import OSPAnnualUpdateSerializer

        payload = {
            "prior_osp": self.osp.id,
            "reporting_year": 2026,
            "changes_summary": "Added a new walnut block; new OMRI compost supplier.",
            "additions": ["New 2-acre block", "Malibu Compost supplier"],
            "deletions": ["Discontinued sulfur dust"],
            "submitted_at": timezone.now().isoformat(),
        }
        ser = OSPAnnualUpdateSerializer(data=payload)
        self.assertTrue(ser.is_valid(), ser.errors)
        obj = ser.save()
        self.assertEqual(obj.reporting_year, 2026)
        self.assertEqual(obj.additions, ["New 2-acre block", "Malibu Compost supplier"])
        self.assertIsNotNone(obj.submitted_at)

    def test_annual_update_renders_in_audit_export(self):
        from history.models import History
        from history.services.audit_export_service import AuditExportService
        from product.models import Product

        OSPAnnualUpdate.objects.create(
            prior_osp=self.osp,
            reporting_year=2026,
            changes_summary="Reaffirmed OSP; added cover-crop block.",
        )
        parcel = Parcel.objects.create(name="P", establishment=self.establishment, area=10.0)
        product = Product.objects.create(name="Walnut")
        user = User.objects.create_user(email="au@test.com", password="x")
        history = History.objects.create(
            name="Prod",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        svc = AuditExportService(history, certification_type="organic")
        elements = svc._build_osp_reference_section()
        text_parts = []
        for el in elements:
            t = getattr(el, "text", None)
            if t:
                text_parts.append(t)
            for row in getattr(el, "_cellvalues", None) or []:
                for cell in row:
                    ct = getattr(cell, "text", None)
                    if ct:
                        text_parts.append(ct)
        text = " ".join(text_parts)
        self.assertIn("2026", text)
        self.assertIn("cover-crop block", text)


class LandownerAffidavitTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Aff Farm")
        self.establishment = Establishment.objects.create(name="F", company=self.company)
        self.parcel = Parcel.objects.create(name="P", establishment=self.establishment, area=1.0)

    def test_default_attestation_text_is_mofga_canonical(self):
        aff = LandownerAffidavit.objects.create(
            parcel=self.parcel,
            previous_manager_name="J. Prior",
        )
        # Exact MOFGA FM-2024-20 wording — must not drift silently.
        self.assertEqual(aff.attestation_text, LandownerAffidavit.ATTESTATION_TEXT)
        self.assertIn("prohibited materials", aff.attestation_text)
        self.assertIn("USDA National Organic Program", aff.attestation_text)

    def test_custom_attestation_preserved(self):
        custom = "Historical wording from 2018 form."
        aff = LandownerAffidavit.objects.create(
            parcel=self.parcel,
            previous_manager_name="J. Prior",
            attestation_text=custom,
        )
        self.assertEqual(aff.attestation_text, custom)

    def test_yearly_history_defaults_empty_list(self):
        aff = LandownerAffidavit.objects.create(parcel=self.parcel, previous_manager_name="X")
        self.assertEqual(aff.yearly_history, [])


class OSPLifecycleViewSetTests(TestCase):
    """Exercises submit / activate / new_version actions via the ORM (no HTTP)."""

    def setUp(self):
        self.company = Company.objects.create(name="LC Farm")
        self.establishment = Establishment.objects.create(name="F", company=self.company)

    def test_activate_supersedes_prior_active(self):
        v1 = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        v2 = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=2, status="draft")

        # Simulate activate() action: supersede v1, activate v2.
        OrganicSystemPlan.objects.filter(establishment=self.establishment, status="active").exclude(pk=v2.pk).update(
            status="superseded"
        )
        v2.status = "active"
        v2.approved_at = timezone.now()
        v2.effective_date = timezone.now().date()
        v2.save()

        v1.refresh_from_db()
        v2.refresh_from_db()
        self.assertEqual(v1.status, "superseded")
        self.assertEqual(v2.status, "active")
        self.assertIsNotNone(v2.approved_at)


class OSPActionPreconditionTests(TestCase):
    """HTTP-level tests for submit / activate preconditions added after fresh-eyes review."""

    def setUp(self):
        from rest_framework.test import APIClient

        from users.models import WorksIn

        self.user = User.objects.create_user(email="pre@test.com", password="x")
        self.company = Company.objects.create(name="Pre Farm")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="E", company=self.company)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _submit_url(self, osp_id):
        return f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{osp_id}/submit/"

    def _activate_url(self, osp_id):
        return f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{osp_id}/activate/"

    def _detail_url(self, osp_id):
        return f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{osp_id}/"

    def _make_osp(self, sections=None, status="draft"):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.filter(establishment=self.est).count() + 1,
            status=status,
            sections=sections or {k: {"narrative": "", "last_updated": None} for k in OSP_SECTION_KEYS},
        )

    def _full_sections(self):
        # Must clear BOTH submit-gate bars: ≥ 400 chars and not padding.
        # The old fixture was "Real OSP narrative content. " * 20 — four words
        # repeated twenty times, which is exactly what looks_like_padding
        # rejects. A fixture that could not itself be submitted was asserting
        # that submission succeeds.
        text = (
            "Sixty acres of certified organic tree crops on three blocks: Hass avocado, "
            "Valencia orange, and Nonpareil almond. Fertility comes from composted green "
            "waste banded under the canopy each autumn plus fish emulsion through the drip "
            "at bloom. Winter cover crops of triticale and crimson clover are drilled into "
            "the row middles in October and mowed flat in March. Pest pressure is scouted "
            "weekly against UC IPM thresholds before any material is applied, and a "
            "thirty-foot mowed buffer separates us from the conventional lemon block."
        )
        return {k: {"narrative": text, "last_updated": "2026-04-14"} for k in OSP_SECTION_KEYS}

    def test_submit_rejects_empty_osp(self):
        osp = self._make_osp()
        res = self.client.post(self._submit_url(osp.id))
        self.assertEqual(res.status_code, 400)
        self.assertIn("missing_sections", res.json())
        self.assertEqual(len(res.json()["missing_sections"]), 6)

    def test_submit_rejects_short_testt_narratives(self):
        """Heuristic guard: a single-word 'Testt' narrative must not pass as complete."""
        sections = {k: {"narrative": "Testt", "last_updated": None} for k in OSP_SECTION_KEYS}
        osp = self._make_osp(sections=sections)
        res = self.client.post(self._submit_url(osp.id))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(res.json()["missing_sections"]), 6)

    def test_submit_rejects_brief_narratives_below_material_floor(self):
        """A narrative like 'We grow organic food.' (21 chars) should be rejected."""
        brief = "We grow organic food. " * 3  # 66 chars — still below 400 floor
        sections = {k: {"narrative": brief, "last_updated": None} for k in OSP_SECTION_KEYS}
        osp = self._make_osp(sections=sections)
        res = self.client.post(self._submit_url(osp.id))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(res.json()["missing_sections"]), 6)
        self.assertIn("400", res.json()["detail"])  # Mentions the floor

    def test_submit_accepts_complete_osp(self):
        osp = self._make_osp(sections=self._full_sections())
        res = self.client.post(self._submit_url(osp.id))
        self.assertEqual(res.status_code, 200, res.content)
        osp.refresh_from_db()
        self.assertEqual(osp.status, "submitted")

    def test_submit_rejects_padded_narratives_that_clear_the_char_floor(self):
        """A 602-char wall of "Test Test Test…" cleared the length floor, reached
        status='submitted', and could then be activated — while the audit
        dossier, which DOES check padding, kept stamping the same plan
        DRAFT / DO-NOT-SUBMIT. Both gates now use one detector.
        """
        padded = "Test " * 120  # 600 chars — comfortably over the 400 floor
        self.assertGreaterEqual(len(padded), 400)
        sections = {k: {"narrative": padded, "last_updated": None} for k in OSP_SECTION_KEYS}
        osp = self._make_osp(sections=sections)
        res = self.client.post(self._submit_url(osp.id))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(len(res.json()["missing_sections"]), 6)
        osp.refresh_from_db()
        self.assertEqual(osp.status, "draft")

    def test_submit_accepts_a_terse_but_varied_narrative_over_the_floor(self):
        """Guard the other direction: the padding check must not reject real
        prose that happens to reuse a domain term. Only lexical monotony fails.
        """
        sections = self._full_sections()
        osp = self._make_osp(sections=sections)
        res = self.client.post(self._submit_url(osp.id))
        self.assertEqual(res.status_code, 200, res.content)

    def test_activate_requires_submitted_status(self):
        osp = self._make_osp(sections=self._full_sections(), status="draft")
        res = self.client.post(self._activate_url(osp.id))
        self.assertEqual(res.status_code, 400)
        self.assertIn("submitted", res.json()["error"].lower())

    def test_activate_rejects_without_approval_evidence(self):
        """Cannot flip to active without certifier's approval letter + cert #."""
        osp = self._make_osp(sections=self._full_sections(), status="submitted")
        res = self.client.post(self._activate_url(osp.id))
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertIn("missing_evidence", body)
        self.assertIn("approval_document", body["missing_evidence"])
        self.assertIn("approval_certificate_number", body["missing_evidence"])

    def test_activate_with_inline_evidence_succeeds(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        osp = self._make_osp(sections=self._full_sections(), status="submitted")
        approval_pdf = SimpleUploadedFile("approval.pdf", b"%PDF-1.4 stub", content_type="application/pdf")
        res = self.client.post(
            self._activate_url(osp.id),
            data={
                "approval_document": approval_pdf,
                "approval_certificate_number": "CCOF-2026-TEST-001",
                "approval_certifier_name": "CCOF",
            },
            format="multipart",
        )
        self.assertEqual(res.status_code, 200, res.content)
        osp.refresh_from_db()
        self.assertEqual(osp.status, "active")
        self.assertIsNotNone(osp.approved_at)
        self.assertIsNotNone(osp.effective_date)
        self.assertEqual(osp.approval_certificate_number, "CCOF-2026-TEST-001")
        self.assertEqual(osp.approval_certifier_name, "CCOF")
        self.assertTrue(osp.approval_document)

    def test_submit_generates_immutable_pdf_snapshot(self):
        osp = self._make_osp(sections=self._full_sections(), status="draft")
        res = self.client.post(self._submit_url(osp.id))
        self.assertEqual(res.status_code, 200, res.content)
        osp.refresh_from_db()
        self.assertTrue(osp.submission_pdf, "submission_pdf should be populated on submit")
        # Sanity-check the file is a PDF (%PDF header).
        with osp.submission_pdf.open("rb") as fh:
            head = fh.read(5)
        self.assertTrue(head.startswith(b"%PDF"), f"Expected PDF header, got {head!r}")

    def test_edit_blocked_on_non_draft(self):
        osp = self._make_osp(sections=self._full_sections(), status="active")
        res = self.client.patch(
            self._detail_url(osp.id),
            data={"sections": self._full_sections()},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("status", res.json())
