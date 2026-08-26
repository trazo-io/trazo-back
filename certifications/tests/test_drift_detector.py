"""
Sprint 5.1 — OSP ↔ events drift detector tests.

Covers:
  - ChemicalEvent with OMRI FK in approved_inputs → no drift
  - ChemicalEvent with OMRI FK NOT in approved_inputs → drift_warning populated
  - ChemicalEvent with NationalListSubstance FK — approved / not approved
  - ChemicalEvent with only commercial_name (no FK) — matched / unmatched
  - No active OSP → existing drift_warning cleared on save
  - Save is never blocked (event persists regardless of drift)
  - SoilManagementEvent amendment drift (ORGANIC_MATTER / COMPOSTING)
  - Audit PDF Drift Findings: clean state + with-drift state render without errors
"""

from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan
from company.models import Company, Establishment
from history.models import ChemicalEvent, History, SoilManagementEvent
from product.models import Parcel


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class DriftDetectorSignalTests(TransactionTestCase):
    """Direct signal behavior — save an event, inspect drift_warning."""

    def setUp(self):
        self.company = Company.objects.create(name="Drift Farm")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.history = History.objects.create(
            name="Drift Production",
            start_date=timezone.now(),
            parcel=self.parcel,
        )

        self.nl_allowed = NationalListSubstance.objects.create(
            substance_name="Spinosad",
            substance_name_normalized="spinosad",
            cfr_section="205.601",
            subsection="e",
            status="allowed",
        )
        self.nl_other = NationalListSubstance.objects.create(
            substance_name="Hydrogen Peroxide",
            substance_name_normalized="hydrogen peroxide",
            cfr_section="205.601",
            subsection="i",
            status="allowed",
        )
        self.omri_allowed = OMRIProduct.objects.create(
            omri_id="OMRI-TEST-A",
            product_name="Neptunes Harvest Fish Fertilizer",
        )
        self.omri_other = OMRIProduct.objects.create(
            omri_id="OMRI-TEST-B",
            product_name="Avenger AG Herbicide",
        )

        self.active_osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )
        self.active_osp.approved_national_list_substances.add(self.nl_allowed)
        self.active_osp.approved_omri_products.add(self.omri_allowed)

    # --- ChemicalEvent -----------------------------------------------------

    def test_chemical_event_with_approved_omri_fk_no_drift(self):
        ev = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Fish fert",
            omri_product=self.omri_allowed,
            commercial_name="Neptunes Harvest Fish Fertilizer",
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_chemical_event_with_unapproved_omri_fk_drift(self):
        ev = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Oops, non-OSP input",
            omri_product=self.omri_other,
            commercial_name="Avenger AG Herbicide",
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["resolved_via"], "omri")
        self.assertEqual(ev.drift_warning["resolved_id"], self.omri_other.id)
        self.assertEqual(ev.drift_warning["osp_id"], self.active_osp.id)
        self.assertIn("OMRI", ev.drift_warning["reason"])

    def test_chemical_event_with_approved_national_list_fk_no_drift(self):
        ev = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Spinosad spray",
            national_list_substance=self.nl_allowed,
            commercial_name="Spinosad",
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_chemical_event_with_unapproved_national_list_fk_drift(self):
        ev = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="H2O2 wash",
            national_list_substance=self.nl_other,
            commercial_name="Hydrogen Peroxide",
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["resolved_via"], "national_list")

    def test_chemical_event_name_only_match(self):
        """commercial_name only, matches an approved item by name — no drift."""
        ev = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Name-only input",
            commercial_name="Spinosad",
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_chemical_event_name_only_unresolved_drift(self):
        ev = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Unknown input",
            commercial_name="Mystery Substance X",
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["resolved_via"], "unresolved")
        self.assertEqual(ev.drift_warning["input_label"], "Mystery Substance X")

    def test_no_active_osp_clears_existing_drift(self):
        ev = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Drift input",
            commercial_name="Mystery Substance X",
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)

        # Supersede the OSP — no active plan remains.
        self.active_osp.status = "superseded"
        self.active_osp.save()

        # Re-save event; signal reruns.
        ev.description = "Touched"
        ev.save()
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_chemical_event_save_never_blocks(self):
        """The detector is advisory — save must succeed even if drift fires."""
        ev = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Block test",
            commercial_name="Absolutely Not Approved",
        )
        self.assertIsNotNone(ev.pk)
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)

    # --- SoilManagementEvent ----------------------------------------------

    def test_soil_event_tillage_never_flags(self):
        """TILLAGE has no amendment — should never raise a drift warning."""
        ev = SoilManagementEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Tillage pass",
            type=SoilManagementEvent.TILLAGE,
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_soil_event_organic_matter_drift(self):
        ev = SoilManagementEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Compost application",
            type=SoilManagementEvent.ORGANIC_MATTER,
            amendment_type="compost",
            amendment_product_name="Unapproved Bat Guano",
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["input_label"], "Unapproved Bat Guano")

    def test_soil_event_organic_matter_approved_no_drift(self):
        ev = SoilManagementEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Approved compost",
            type=SoilManagementEvent.ORGANIC_MATTER,
            amendment_type="compost",
            amendment_product_name="Neptunes Harvest Fish Fertilizer",
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class DriftDetectorApprovedInputsActionsTests(TransactionTestCase):
    """Integration through the OSP ViewSet add/remove approved-input actions."""

    def setUp(self):
        self.company = Company.objects.create(name="Add/Remove Farm")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.parcel = Parcel.objects.create(name="P", establishment=self.establishment, area=1.0)
        self.history = History.objects.create(name="Prod", start_date=timezone.now(), parcel=self.parcel)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )
        self.omri = OMRIProduct.objects.create(omri_id="OMRI-X", product_name="Widget")

    def test_add_approved_input_clears_existing_drift(self):
        """Adding an OMRI that matches an existing drifted event should clear the flag."""
        ev = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Drifted",
            omri_product=self.omri,
            commercial_name="Widget",
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)

        # Approve the OMRI + recompute inline (service call mirrors the viewset path).
        self.osp.approved_omri_products.add(self.omri)
        from certifications.services.drift_detector import evaluate_chemical_event

        evaluate_chemical_event(ev)
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_remove_approved_input_reintroduces_drift(self):
        self.osp.approved_omri_products.add(self.omri)
        ev = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Initially approved",
            omri_product=self.omri,
            commercial_name="Widget",
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

        self.osp.approved_omri_products.remove(self.omri)
        from certifications.services.drift_detector import evaluate_chemical_event

        evaluate_chemical_event(ev)
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)

    def test_viewset_blocks_approved_input_edit_on_submitted_osp(self):
        """
        Sprint 5.1 hardening: once an OSP is 'submitted', the approval evidence
        is frozen for the certifier — viewset must reject add/remove until it
        transitions to 'active' (approved) or back to 'draft' (new version).
        """
        from rest_framework.exceptions import ValidationError

        from certifications.views import OrganicSystemPlanViewSet

        self.osp.status = "submitted"
        self.osp.save(update_fields=["status"])
        vs = OrganicSystemPlanViewSet()
        with self.assertRaises(ValidationError) as ctx:
            vs._ensure_approved_inputs_editable(self.osp)
        self.assertIn("submitted", str(ctx.exception))


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class OSPActivateDriftRecomputeTests(TransactionTestCase):
    """
    Activating a new OSP version can change which inputs are approved. Events
    stamped under the prior scope need to be re-evaluated against the new
    scope at activation time — otherwise stale drift findings linger and
    newly-unapproved inputs slip through unflagged.
    """

    def setUp(self):
        self.company = Company.objects.create(name="Activation Farm")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.parcel = Parcel.objects.create(name="P", establishment=self.establishment, area=1.0)
        self.history = History.objects.create(name="Prod", start_date=timezone.now(), parcel=self.parcel)
        self.omri = OMRIProduct.objects.create(omri_id="OMRI-ACT", product_name="Activation Widget")
        # OSP v1 is active and approves the OMRI product.
        self.v1 = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
            sections={
                key: {"narrative": "x" * 450, "last_updated": "2026-04-14"}
                for key in (
                    "practices_procedures",
                    "inputs_list",
                    "monitoring_plan",
                    "recordkeeping_description",
                    "commingling_barriers",
                    "additional_certifier_info",
                )
            },
        )
        self.v1.approved_omri_products.add(self.omri)
        # Event created under v1 → no drift.
        self.event = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Under v1",
            omri_product=self.omri,
            commercial_name="Activation Widget",
        )
        self.event.refresh_from_db()
        self.assertIsNone(self.event.drift_warning)

    def test_activating_new_version_without_input_reflags_drift(self):
        """
        A new 'submitted' OSP v2 that does NOT approve the OMRI becomes
        active. The existing event now violates the new scope and must be
        re-flagged by _recompute_drift_for_establishment.
        """
        from certifications.views import OrganicSystemPlanViewSet

        v2 = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=2,
            status="submitted",
            previous_version=self.v1,
            sections=self.v1.sections,
            approval_document="osp/approvals/dummy.pdf",
            approval_certificate_number="CERT-V2",
            approval_certifier_name="Test Certifier",
        )
        # Simulate the activate transition: supersede + activate + recompute.
        self.v1.status = "superseded"
        self.v1.save(update_fields=["status"])
        v2.status = "active"
        v2.approved_at = timezone.now()
        v2.effective_date = timezone.now().date()
        v2.save(update_fields=["status", "approved_at", "effective_date"])

        OrganicSystemPlanViewSet()._recompute_drift_for_establishment(self.establishment.id)
        self.event.refresh_from_db()
        self.assertIsNotNone(
            self.event.drift_warning,
            "Event approved under v1 must be re-flagged under v2's narrower scope.",
        )


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class OSPSubmissionPDFApprovedInputsTests(TransactionTestCase):
    """Sprint 5.1 hardening — submission PDF includes approved_inputs list."""

    def setUp(self):
        self.company = Company.objects.create(name="PDF Submit Farm")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="draft",
            submitted_at=timezone.now(),
            sections={
                key: {"narrative": "x" * 450, "last_updated": "2026-04-14"}
                for key in (
                    "practices_procedures",
                    "inputs_list",
                    "monitoring_plan",
                    "recordkeeping_description",
                    "commingling_barriers",
                    "additional_certifier_info",
                )
            },
        )
        self.nl = NationalListSubstance.objects.create(
            substance_name="Copper hydroxide",
            substance_name_normalized="copper hydroxide",
            cfr_section="205.601",
            status="allowed",
        )
        self.omri = OMRIProduct.objects.create(
            omri_id="OMRI-Z",
            product_name="Kocide 3000",
            manufacturer="Certis USA",
        )
        self.osp.approved_national_list_substances.add(self.nl)
        self.osp.approved_omri_products.add(self.omri)

    def test_submission_pdf_lists_approved_inputs(self):
        """
        Intercept SimpleDocTemplate.build to inspect the story flowables —
        ReportLab compresses PDF streams (ASCII85+FlateDecode) so grepping
        the rendered bytes is unreliable. We assert against the Paragraph
        text the generator appends before build().
        """
        from unittest.mock import patch

        from certifications.services import osp_pdf_snapshot

        captured = {}

        def fake_build(self, story, **kwargs):
            captured["story"] = story

        with patch.object(osp_pdf_snapshot.SimpleDocTemplate, "build", autospec=True, side_effect=fake_build):
            osp_pdf_snapshot.generate_osp_snapshot_pdf(self.osp)

        texts = [getattr(f, "text", "") for f in captured["story"]]
        joined = " ".join(texts)
        self.assertIn("Approved Inputs", joined)
        self.assertIn("Copper hydroxide", joined)
        self.assertIn("205.601", joined)
        self.assertIn("Kocide 3000", joined)
        self.assertIn("OMRI #OMRI-Z", joined)
        self.assertIn("Certis USA", joined)

    def test_submission_pdf_empty_inputs_shows_placeholder(self):
        """No approved_inputs → PDF still renders, with the fallback paragraph."""
        from unittest.mock import patch

        from certifications.services import osp_pdf_snapshot

        self.osp.approved_national_list_substances.clear()
        self.osp.approved_omri_products.clear()

        captured = {}

        def fake_build(self, story, **kwargs):
            captured["story"] = story

        with patch.object(osp_pdf_snapshot.SimpleDocTemplate, "build", autospec=True, side_effect=fake_build):
            osp_pdf_snapshot.generate_osp_snapshot_pdf(self.osp)

        joined = " ".join(getattr(f, "text", "") for f in captured["story"])
        self.assertIn("Approved Inputs", joined)
        self.assertIn("No structured inputs", joined)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class DriftFindingsPDFSectionTests(TransactionTestCase):
    """Smoke-test the audit_export_service drift section."""

    def setUp(self):
        self.company = Company.objects.create(name="PDF Farm")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.parcel = Parcel.objects.create(name="P", establishment=self.establishment, area=1.0)
        self.history = History.objects.create(
            name="PDF Prod",
            start_date=timezone.now(),
            parcel=self.parcel,
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )

    def _service(self):
        from history.services.audit_export_service import AuditExportService

        return AuditExportService(self.history, certification_type="organic")

    def _rendered(self):
        els = self._service()._build_drift_findings_section()
        self.assertTrue(len(els) >= 2)
        return " ".join(getattr(e, "text", "") for e in els if hasattr(e, "text"))

    def test_no_events_and_no_approved_inputs_is_not_a_clean_result(self):
        """An empty approved-inputs set clears nothing.

        This previously asserted "No drift findings" for an operation whose OSP had
        no material list at all — every comparison passed vacuously and the dossier
        printed it as a clean bill of health. Absence of evidence is not evidence of
        conformance (2026-08-03 dossier review).
        """
        texts = self._rendered()

        self.assertNotIn("No drift findings", texts)
        self.assertIn("could not be evaluated", texts)

    def test_no_events_with_an_approved_input_on_file_is_a_clean_result(self):
        """With a real material list to check against, a clean verdict is earned."""
        from certifications.models import NationalListSubstance

        substance = NationalListSubstance.objects.create(
            substance_name="Copper hydroxide",
            cfr_section="205.601",
        )
        self.osp.approved_national_list_substances.add(substance)

        texts = self._rendered()

        self.assertIn("No drift findings", texts)

    def test_drift_section_with_findings(self):
        """One drifted ChemicalEvent → section includes a table and no-clean-state text."""
        ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Drifted",
            commercial_name="Mystery Input",
        )
        els = self._service()._build_drift_findings_section()
        # Expect at least: header, warning paragraph, spacer, table, footnote.
        self.assertGreaterEqual(len(els), 4)
        texts = " ".join(getattr(e, "text", "") for e in els if hasattr(e, "text"))
        self.assertNotIn("No drift findings", texts)


class SoilAmendmentCategoryEnumTests(TransactionTestCase):
    """A category enum is not an input name (2026-08-25).

    The soil classifier used to run the catalog matcher on `amendment_type`
    itself, so every on-farm "compost"/"mulch" event carried an "unresolved
    input" drift finding — 8 of the 23 findings on dev farm 167 were this.
    On-farm material needs no catalog listing; a PURCHASED product does, and
    its name lives in `amendment_product_name`.
    """

    def setUp(self):
        self.company = Company.objects.create(name="Enum Farm")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.history = History.objects.create(
            name="Enum Production",
            start_date=timezone.now(),
            parcel=self.parcel,
        )
        OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )

    def test_bare_category_enum_never_flags(self):
        for category in ("compost", "mulch", "manure", "other"):
            ev = SoilManagementEvent.objects.create(
                history=self.history,
                date=timezone.now(),
                description=f"{category} spread",
                type=SoilManagementEvent.ORGANIC_MATTER,
                amendment_type=category,
            )
            ev.refresh_from_db()
            self.assertIsNone(
                ev.drift_warning,
                f"bare '{category}' must not be treated as a product name",
            )

    def test_named_product_still_flags(self):
        ev = SoilManagementEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="purchased compost",
            type=SoilManagementEvent.COMPOSTING,
            amendment_type="compost",
            amendment_product_name="Mystery Compost Co Premium Blend",
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["input_label"], "Mystery Compost Co Premium Blend")


class UpdateSerializerLabFlattenTests(TransactionTestCase):
    """The retrieve payload must carry the lab results the consumer card shows.

    2026-08-25: soil lab values live in the `test_results` JSON. The full
    serializer flattens them (LAB_RESULT_FIELDS) for the public card, but
    `EventViewSet.retrieve` answers with UpdateSoilManagementEventSerializer,
    which did not — so the producer's "full record" modal showed LESS than the
    consumer card (Laboratorio visible to shoppers, absent from the modal).
    """

    def setUp(self):
        self.company = Company.objects.create(name="Lab Farm")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.history = History.objects.create(
            name="Lab Production",
            start_date=timezone.now(),
            parcel=self.parcel,
        )

    def test_update_serializer_flattens_test_results(self):
        from history.serializers import UpdateSoilManagementEventSerializer

        ev = SoilManagementEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Annual soil test",
            type=SoilManagementEvent.SOIL_TEST,
            test_results={
                "lab_name": "A&L Western Laboratories, Portland OR",
                "sample_id": "AL-25-04411",
                "nitrogen": 15,
                "cec": 12,
            },
        )
        data = UpdateSoilManagementEventSerializer(ev).data
        self.assertEqual(data["lab_name"], "A&L Western Laboratories, Portland OR")
        self.assertEqual(data["lab_sample_id"], "AL-25-04411")
        self.assertEqual(data["lab_nitrogen"], 15)
        self.assertEqual(data["lab_cec"], 12)


class UpdateSerializerFallbackChannelTests(TransactionTestCase):
    """Every retrieve payload must carry the channels the display registry
    resolves values from: top-level model fields, `extra_data`, and (for soil)
    the flattened `test_results`. Registry fields that are not model columns
    live in extra_data — drop it from a serializer and every such field goes
    invisible on the detail modal while still showing on the consumer card.
    """

    def test_every_update_serializer_carries_extra_data_and_observation(self):
        from history import serializers as hs

        for cls in (
            hs.UpdateWeatherEventSerializer,
            hs.UpdateProductionEventSerializer,
            hs.UpdateChemicalEventSerializer,
            hs.UpdateGeneralEventSerializer,
            hs.UpdateSoilManagementEventSerializer,
            hs.UpdatePestManagementEventSerializer,
            hs.UpdateBusinessEventSerializer,
        ):
            fields = set(cls().fields.keys())
            self.assertIn("extra_data", fields, cls.__name__)
            self.assertIn("observation", fields, cls.__name__)
