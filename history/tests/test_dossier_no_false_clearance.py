"""The dossier must never turn an absence of evidence into a clean result.

Every defect pinned here came out of reading a real 37-page operation dossier as a
certifier on 2026-08-03, and all four are the same failure: missing data rendering
as a positive finding.

  P0-1 the drift section reported "No drift findings. Every chemical input ...
       matched an entry on the establishment's active OSP approved-inputs list"
       while page 2 of the same PDF said the OSP was 0% filled and the OMRI table
       said an input was "Listed — not on OSP". Matching against an empty set is
       vacuously true.
  P0-2 two inputs the operator had recorded as "Not Organic Approved — Conventional
       use only" appeared in the input log of an ORGANIC production, and the
       findings section above them said there were none.
  P0-3 OperationReadinessService returned ready=True for that operation, so the
       certifier share guard would have minted a link to a dossier whose own front
       page said "DRAFT — NOT FOR CERTIFIER SUBMISSION".
  P0-4 the certification table printed "Verified (USDA OID)" next to a certifier
       that is not an accredited agent and has no OID source recorded.
"""

from django.test import TestCase
from django.utils import timezone

from certifications.models import Certification, OrganicSystemPlan
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.services.audit_export_service import AuditExportService
from history.services.operation_readiness_service import OperationReadinessService
from history.tests.test_pdf_field_coverage import flowable_text
from product.models import Parcel, Product
from users.models import User


class VerificationLabelTests(TestCase):
    """P0-4 — the OID claim is gated on the source that substantiates it."""

    def setUp(self):
        self.company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")

    def _label(self, cert):
        # _verification_label is defined inside the section builder, so exercise the
        # same rule the builder applies.
        if cert.verification_status == "verified":
            if getattr(cert, "verification_source", "") == Certification.DATABASE_VERIFICATION_SOURCE:
                return "Verified (USDA OID)"
            return "Self-Reported"
        return "Self-Reported"

    def test_verified_without_a_source_is_not_an_oid_claim(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
        )
        self.assertEqual(self._label(cert), "Self-Reported")
        # The PDF and the consumer surface must agree.
        self.assertEqual(cert.consumer_display_status, "self_reported")

    def test_verified_with_the_database_source_is_an_oid_claim(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            verification_source=Certification.DATABASE_VERIFICATION_SOURCE,
        )
        self.assertEqual(self._label(cert), "Verified (USDA OID)")
        self.assertEqual(cert.consumer_display_status, "verified_via_database")


class EmptyOSPIsABlockerTests(TestCase):
    """P0-3 — a materially empty plan cannot be shared with a certifier."""

    def setUp(self):
        self.company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(
            name="Home Ranch", company=self.company, state="CA", farming_method="Certified Organic"
        )
        self.establishment.fraud_prevention_plan_uploaded = True
        self.establishment.save(update_fields=["fraud_prevention_plan_uploaded"])
        self.user = User.objects.create_user(email="grower3@test.com", password="x")
        parcel = Parcel.objects.create(name="Block", establishment=self.establishment, area=10.0)
        product = Product.objects.create(name="Avocados")
        self.history = History.objects.create(
            name="2026 Avocados",
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
            production_method="organic",
        )

    def _readiness(self):
        return OperationReadinessService(self.establishment, "organic").evaluate()

    def test_osp_with_every_section_empty_blocks_sharing(self):
        OrganicSystemPlan.objects.create(establishment=self.establishment, status="draft", version_number=1)

        result = self._readiness()

        self.assertFalse(result["ready"])
        self.assertIn("osp", [b["key"] for b in result["blockers"]])

    def test_a_written_but_unsubmitted_osp_is_only_a_warning(self):
        OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            status="draft",
            version_number=1,
            sections={
                "practices_procedures": {"narrative": "Cover crop, compost, drip irrigation.", "last_updated": None},
                "inputs_list": {"narrative": "Kocide 3000, composted green waste.", "last_updated": None},
            },
        )

        result = self._readiness()

        self.assertNotIn("osp", [b["key"] for b in result["blockers"]])
        self.assertIn("osp", [w["key"] for w in result["warnings"]])


class NoFalseAllClearTests(TestCase):
    """P0-1 and P0-2 — the drift section's prose, rendered."""

    def setUp(self):
        self.company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")
        self.user = User.objects.create_user(email="grower4@test.com", password="x")
        parcel = Parcel.objects.create(name="Block", establishment=self.establishment, area=10.0)
        product = Product.objects.create(name="Avocados")
        self.history = History.objects.create(
            name="2026 Avocados",
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
            production_method="organic",
        )

    def _rendered(self):
        svc = AuditExportService(self.history, "organic")
        parts = []
        for el in svc._build_drift_findings_section():
            text = getattr(el, "text", None)
            if text:
                parts.append(str(text))
        return " ".join(parts)

    def test_empty_approved_inputs_does_not_report_no_findings(self):
        OrganicSystemPlan.objects.create(establishment=self.establishment, status="active", version_number=1)

        rendered = self._rendered()

        self.assertNotIn("No drift findings", rendered)
        self.assertIn("could not be evaluated", rendered)

    def test_conventional_only_input_on_organic_production_is_a_non_conformance(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Osmocote Plus 15-9-12",
            date=timezone.now(),
            organic_approved="not_organic",
        )

        rendered = self._rendered()

        self.assertIn("NON-CONFORMANCE", rendered)
        self.assertIn("205.105", rendered)
        self.assertNotIn("No drift findings", rendered)


class InspectorReadabilityTests(TestCase):
    """P1s from the same dossier review — things that made the packet read wrong."""

    def test_change_log_hides_orm_plumbing_from_the_certifier(self):
        """Raw reverse-relation and CRM columns were printed into a regulatory doc."""
        changes = {
            "commercial_name": ["a", "b"],
            "history_pestmanagementevent_events": [None, None],
            "favorited_by": [None, None],
            "buyer_doc_requests": [None, None],
            "cover_image_url": ["", "x"],
            "public_id": ["", "y"],
            "organic_approved": ["", "not_organic"],
        }

        rendered = AuditExportService._inspector_field_list(changes)

        self.assertIn("commercial name", rendered)
        self.assertIn("organic approved", rendered)
        for leaked in ("history_", "favorited_by", "buyer_doc_requests", "cover_image_url", "public_id"):
            self.assertNotIn(leaked, rendered)

    def test_change_log_says_so_when_only_internal_fields_changed(self):
        rendered = AuditExportService._inspector_field_list({"public_id": ["", "x"]})

        self.assertEqual(rendered, "(internal fields only)")

    def test_post_harvest_guidance_is_not_tree_nut_for_every_crop(self):
        """An avocado dossier asserted tree-nut hulling and drying steps."""
        steps = AuditExportService._POST_HARVEST_STEPS

        self.assertIn("hulled", steps["tree_nut"])
        self.assertNotIn("hulled", steps["tree_fruit"])
        self.assertNotIn("Tree-nut", steps["vegetable"])
        # Unknown category must not silently inherit tree-nut wording.
        self.assertNotIn("Tree-nut", AuditExportService._POST_HARVEST_DEFAULT)


class ProhibitedSoilAmendmentTests(TestCase):
    """Soil amendments carry the same ORGANIC_APPROVED choices as chemicals
    (7 CFR 205.203(b)). The first cut of the prohibited-input check queried only
    ChemicalEvent, so a prohibited amendment passed through untouched."""

    def setUp(self):
        company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=company, state="CA")
        user = User.objects.create_user(email="grower5@test.com", password="x")
        parcel = Parcel.objects.create(name="Block", establishment=self.establishment, area=10.0)
        product = Product.objects.create(name="Avocados")
        self.history = History.objects.create(
            name="2026 Avocados",
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
            production_method="organic",
        )

    def _rendered(self):
        svc = AuditExportService(self.history, "organic")
        return " ".join(
            str(getattr(el, "text", "")) for el in svc._build_drift_findings_section() if getattr(el, "text", None)
        )

    def test_conventional_only_amendment_is_a_non_conformance(self):
        from history.models import SoilManagementEvent

        SoilManagementEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            amendment_type="Synthetic urea",
            amendment_organic_approved="not_organic",
        )

        rendered = self._rendered()

        self.assertIn("NON-CONFORMANCE", rendered)
        self.assertIn("205.105", rendered)
        self.assertNotIn("No drift findings", rendered)

    def test_approved_amendment_is_not_flagged(self):
        from history.models import SoilManagementEvent

        SoilManagementEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            amendment_type="Composted green waste",
            amendment_organic_approved="omri_listed",
        )

        self.assertNotIn("NON-CONFORMANCE", self._rendered())


class PhotoReuseDedupTests(TestCase):
    """The reuse detector deduped on the rendered LABEL ("category · date"), so two
    distinct events sharing a category and a date collapsed into one entry and real
    reuse between them went unreported."""

    def test_same_category_same_date_events_are_counted_separately(self):
        from common.models import Gallery, GalleryImage

        company = Company.objects.create(name="Tule River Orchards")
        establishment = Establishment.objects.create(name="Home Ranch", company=company, state="CA")
        user = User.objects.create_user(email="grower6@test.com", password="x")
        parcel = Parcel.objects.create(name="Block", establishment=establishment, area=10.0)
        product = Product.objects.create(name="Avocados")
        history = History.objects.create(
            name="2026 Avocados",
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
        shared_url = "https://example.test/one-photo.jpg"
        when = timezone.now()
        events = []
        for name in ("Spray A", "Spray B"):
            gallery = Gallery.objects.create()
            GalleryImage.objects.create(gallery=gallery, image_url=shared_url)
            events.append(
                ChemicalEvent.objects.create(
                    history=history,
                    date=when,
                    commercial_name=name,
                    album=gallery,
                )
            )

        svc = AuditExportService(history, "organic")
        rendered = " ".join(
            str(getattr(el, "text", ""))
            for el in svc._photo_reuse_findings([("Chemical Applications", events)])
            if getattr(el, "text", None)
        )

        self.assertIn("Photo evidence reuse", rendered)


class PaddingDefeatsLengthFloorTests(TestCase):
    """A character floor measures length, not content.

    2026-08-04: the OSP was filled with the word "Test" repeated to 602 characters
    per section. That cleared the 400-char material floor, the dossier reported
    "100% of § 205.201(a)(1)-(6) substantively filled", the DRAFT / DO-NOT-SUBMIT
    banner disappeared, and OperationReadinessService reopened the share guard —
    all in one attempt.
    """

    def test_repeated_word_padding_is_detected(self):
        from history.services.audit_export_service import looks_like_padding

        self.assertTrue(looks_like_padding("Test " * 120))
        self.assertTrue(looks_like_padding("lorem ipsum " * 40))

    def test_real_narrative_is_not_flagged(self):
        from history.services.audit_export_service import looks_like_padding

        narrative = (
            "Cover crops are planted in the orchard middles each November and mowed before "
            "bloom. Compost is applied at five tons per hectare in September. Irrigation is "
            "drip, scheduled from soil-moisture sensors, and buffer zones of eight metres are "
            "maintained along the northern boundary where a conventional grower farms."
        )
        self.assertFalse(looks_like_padding(narrative))

    def test_terse_answers_are_never_judged_by_diversity(self):
        from history.services.audit_export_service import looks_like_padding

        # Below the token minimum, so a short real answer can never be flagged.
        for value in ("No material changes.", "None this year.", "Lime", ""):
            with self.subTest(value=value):
                self.assertFalse(looks_like_padding(value))

    def test_documented_limitation_single_run_of_noise(self):
        """Keyboard noise in one token is NOT caught, and the code says so.

        Pinning it so the guarantee is not overstated in future.
        """
        from history.services.audit_export_service import looks_like_padding

        self.assertFalse(looks_like_padding("tetreterterrtret"))

    def test_padded_osp_still_blocks_sharing(self):
        company = Company.objects.create(name="Padded Co")
        establishment = Establishment.objects.create(
            name="Padded Ranch", company=company, state="CA", farming_method="Certified Organic"
        )
        establishment.fraud_prevention_plan_uploaded = True
        establishment.save(update_fields=["fraud_prevention_plan_uploaded"])
        user = User.objects.create_user(email="padded@test.com", password="x")
        parcel = Parcel.objects.create(name="Block", establishment=establishment, area=10.0)
        product = Product.objects.create(name="Avocados")
        History.objects.create(
            name="2026 Avocados",
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
        from certifications.models import OSP_SECTION_KEYS

        OrganicSystemPlan.objects.create(
            establishment=establishment,
            status="draft",
            version_number=1,
            sections={k: {"narrative": "Test " * 120, "last_updated": None} for k in OSP_SECTION_KEYS},
        )

        result = OperationReadinessService(establishment, "organic").evaluate()

        self.assertFalse(result["ready"])
        self.assertIn("osp", [b["key"] for b in result["blockers"]])


class AttestationSupportTests(TestCase):
    """An attestation the operation's own packet contradicts.

    A certifier read of a completed packet (2026-08-09) found G3.0b attesting that
    "planting stock suppliers are listed on the Supplier List" while that workbook had
    zero rows, and Materials Application making four "all materials are entered"
    statements against an empty approved-inputs list. Nothing was falsified — the
    workbooks are honest about blanks — but a reviewer cross-checks each attestation
    against the document that should corroborate it, and the operator had no way to see
    the mismatch before sending.

    A WARNING, never a blocker: the producer authors the plan (§ 205.201(a)).
    """

    def setUp(self):
        self.company = Company.objects.create(name="Attestation Orchards")
        self.establishment = Establishment.objects.create(
            name="Attest Ranch", company=self.company, state="CA", farming_method="Certified Organic"
        )
        self.plan = OrganicSystemPlan.objects.create(establishment=self.establishment, status="draft", version_number=1)

    def _check(self):
        return OperationReadinessService(self.establishment, "organic")._check_attestation_support()

    def _attest(self, module_key, question_key):
        self.plan.module_responses = {
            "schema_version": 1,
            "modules": {module_key: {"answers": {question_key: {"value": True}}}},
        }
        self.plan.save(update_fields=["module_responses"])

    def test_unsupported_materials_attestation_warns(self):
        self._attest("materials_application", "materials_list_complete")
        result = self._check()
        self.assertEqual(result["status"], "warning")
        self.assertIn("no materials are on the approved list", result["detail"])

    def test_unsupported_supplier_attestation_warns(self):
        self._attest("g3_2_planting_stock", "suppliers_on_supplier_list")
        result = self._check()
        self.assertEqual(result["status"], "warning")
        self.assertIn("Supplier List is empty", result["detail"])

    def test_no_attestation_no_warning(self):
        self.assertEqual(self._check()["status"], "ok")

    def test_never_blocks_a_submission(self):
        """The producer authors the plan — Trazo reports, it does not refuse."""
        self._attest("materials_application", "materials_list_complete")
        verdict = OperationReadinessService(self.establishment, "organic").evaluate()
        self.assertNotIn(
            "attestation_support",
            [b["key"] for b in verdict["blockers"]],
        )
        self.assertIn("attestation_support", [w["key"] for w in verdict["warnings"]])


class DraftOSPIsNotAnActiveOneTests(TestCase):
    """P0-5 (2026-09-06) — "No drift findings … the establishment's active OSP".

    The packet's `active_osp` lookup had no status filter, so a DRAFT plan with approved
    inputs satisfied it. The detector, which does filter on status="active", never ran
    against that plan and CLEARS any finding when there is no active one — so the packet
    read zero findings off a check that had not happened and printed a clean verdict
    naming an active OSP that did not exist.
    """

    def setUp(self):
        self.company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")
        self.user = User.objects.create_user(email="drafted@test.com", password="x")
        parcel = Parcel.objects.create(name="Block", establishment=self.establishment, area=10.0)
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="2026 Walnuts",
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
            production_method="organic",
        )

    def _rendered(self):
        svc = AuditExportService(self.history, "organic")
        return " ".join(str(getattr(el, "text", "")) for el in svc._build_drift_findings_section())

    def _draft_osp_with_inputs(self, status):
        from certifications.models import OMRIProduct

        osp = OrganicSystemPlan.objects.create(establishment=self.establishment, status=status, version_number=1)
        osp.approved_omri_products.add(OMRIProduct.objects.create(omri_id="dow-2900", product_name="Entrust SC"))
        return osp

    def test_a_draft_osp_with_inputs_does_not_produce_no_drift_findings(self):
        self._draft_osp_with_inputs("draft")

        rendered = self._rendered()

        self.assertNotIn("No drift findings", rendered)
        self.assertIn("NOT CHECKED", rendered)
        self.assertIn("absence of", rendered)

    def test_a_submitted_osp_is_not_an_active_one_either(self):
        self._draft_osp_with_inputs("submitted")
        self.assertNotIn("No drift findings", self._rendered())

    def test_no_osp_at_all_says_the_check_did_not_run(self):
        rendered = self._rendered()
        self.assertIn("NOT CHECKED", rendered)
        self.assertIn("no Organic System Plan of any status is on file", rendered)

    def test_an_active_osp_with_inputs_still_reports_the_clean_verdict(self):
        self._draft_osp_with_inputs("active")
        self.assertIn("No drift findings", self._rendered())

    def test_the_subset_disclaimer_prints_on_the_no_findings_branch_too(self):
        """The clean verdict is the one a certifier most readily accepts — it may not be
        the only one that omits what it was measured against."""
        self._draft_osp_with_inputs("active")

        rendered = self._rendered()

        self.assertIn("No drift findings", rendered)
        self.assertIn("OMRI reference subset", rendered)
        self.assertIn("authoritative database", rendered)

    def test_the_subset_disclaimer_prints_when_the_check_could_not_run(self):
        self.assertIn("OMRI reference subset", self._rendered())

    def test_no_fabricated_wsda_identifier_reaches_the_osp_reference_section(self):
        from certifications.models import WSDAMaterial

        osp = OrganicSystemPlan.objects.create(establishment=self.establishment, status="active", version_number=1)
        osp.approved_wsda_materials.add(
            WSDAMaterial.objects.create(
                wsda_id="WSDA-REG-BIOAG-2025-001",
                brand_name="Feather Meal 13-0-0",
                manufacturer="BioAg",
            ),
            WSDAMaterial.objects.create(wsda_id="1123", brand_name="Kaligreen", manufacturer="OHP"),
        )

        svc = AuditExportService(self.history, "organic")
        rendered = " ".join(str(getattr(el, "text", "")) for el in svc._build_osp_reference_section())

        self.assertIn("Feather Meal 13-0-0", rendered)
        self.assertNotIn("WSDA-REG", rendered)
        self.assertNotIn("WSDA #", rendered)
        self.assertIn("WSDA Product #1123", rendered)


class CatalogFreshnessTests(TestCase):
    """A failed IngestionRun is not a synced catalog.

    The line filtered on nothing, so a run with status="error" or "skipped" printed
    exactly like a success: "Input catalogs last synced: National List (eCFR) 2026-09-05".
    """

    def setUp(self):
        company = Company.objects.create(name="Freshness Farm")
        establishment = Establishment.objects.create(name="Home", company=company, state="CA")
        parcel = Parcel.objects.create(name="P", establishment=establishment, area=1.0)
        product = Product.objects.create(name="Olives")
        user = User.objects.create_user(email="fresh@test.com", password="x")
        self.history = History.objects.create(
            name="2026 Olives",
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
        self.svc = AuditExportService(self.history, "organic")

    def test_a_failed_run_is_never_printed_as_a_sync(self):
        from certifications.models import IngestionRun

        IngestionRun.objects.create(source="national_list_ecfr", status="error", message="HTTP 404")

        line = self.svc._catalog_freshness_line()

        self.assertNotIn("Input catalogs last synced: National List (eCFR)", line)
        self.assertIn("National List (eCFR) — last attempt", line)
        self.assertIn("no successful sync on record", line)

    def test_a_skipped_run_is_not_a_sync_either(self):
        from certifications.models import IngestionRun

        IngestionRun.objects.create(source="omri", status="skipped", message="--skip flag")

        line = self.svc._catalog_freshness_line()

        self.assertIn("OMRI — last attempt", line)
        self.assertIn("no successful sync on record", line)

    def test_a_catalog_that_never_ran_is_named_not_dropped(self):
        line = self.svc._catalog_freshness_line()
        for label in ("OMRI", "WSDA", "CDFA OIM", "National List (eCFR)"):
            self.assertIn(f"{label} — never synced", line)
        self.assertNotIn("last synced", line)

    def test_a_successful_run_still_prints_its_date(self):
        from certifications.models import IngestionRun

        run = IngestionRun.objects.create(source="omri", status="ok")

        line = self.svc._catalog_freshness_line()

        self.assertIn(f"OMRI {run.ran_at.date().isoformat()}", line)

    def test_a_later_failure_does_not_hide_behind_an_earlier_success(self):
        from certifications.models import IngestionRun

        ok = IngestionRun.objects.create(source="wsda", status="ok")
        IngestionRun.objects.create(source="wsda", status="error", message="boom")

        line = self.svc._catalog_freshness_line()

        self.assertIn(f"WSDA {ok.ran_at.date().isoformat()}", line)
        self.assertIn("the date above is the last attempt that succeeded", line)


class NoInventedRegistrationInTheDriftTableTests(TestCase):
    """`[CA: CDFA OIM CDFA-OIM-DTE-FM]` was a Trazo string printed as a CA registration,
    and `[CA: CDFA OIM missing]` asserted a state-law violation from a 17-row file."""

    def setUp(self):
        company = Company.objects.create(name="CA Orchards")
        self.establishment = Establishment.objects.create(name="Home", company=company, state="CA")
        parcel = Parcel.objects.create(name="P", establishment=self.establishment, area=1.0)
        product = Product.objects.create(name="Almonds")
        user = User.objects.create_user(email="ca@test.com", password="x")
        self.history = History.objects.create(
            name="2026 Almonds",
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
            production_method="organic",
        )
        OrganicSystemPlan.objects.create(establishment=self.establishment, status="active", version_number=1)

    def _rendered_with(self, cdfa_status):
        event = ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Down To Earth Feather Meal",
            date=timezone.now(),
        )
        ChemicalEvent.objects.filter(pk=event.pk).update(
            drift_warning={
                "input_label": "Down To Earth Feather Meal",
                "reason": "not on the plan",
                "resolved_via": "unresolved",
                "cdfa_oim_status": cdfa_status,
            }
        )
        svc = AuditExportService(self.history, "organic")
        return flowable_text(svc._build_drift_findings_section())

    def test_a_registered_row_prints_the_word_not_a_number(self):
        rendered = self._rendered_with({"status": "registered", "cdfa_oim_reg_number": "CDFA-OIM-DTE-FM"})
        self.assertIn("CDFA OIM registered", rendered)
        self.assertNotIn("CDFA-OIM", rendered)

    def test_an_unknown_row_says_not_checked_never_missing(self):
        rendered = self._rendered_with({"status": "unknown"})
        self.assertIn("not checked", rendered)
        self.assertNotIn("CDFA OIM missing", rendered)

    def test_a_legacy_missing_row_renders_as_not_checked_too(self):
        """Rows written before 2026-09-06 carry the old default and meant the same thing."""
        rendered = self._rendered_with({"status": "missing", "cdfa_oim_reg_number": None})
        self.assertIn("not checked", rendered)
        self.assertNotIn("CDFA OIM missing", rendered)
