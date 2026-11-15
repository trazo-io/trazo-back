"""
Phase 1 drift-detector coverage — WSDA + CDFA OIM + OMRI deep-link.

Mirrors the pattern in test_drift_detector.py but focused on the new sources
added in the Phase 1 CA pilot gate:
  - WSDA resolution (fuzzy name match against WSDAMaterial)
  - CA-only CDFA OIM "missing" sub-finding for fertilizer categories
  - OMRI deep-link URL populated on unresolved names
  - eCFR revision persists with hash drift detection
"""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from certifications.models import (
    NationalListRevision,
    NationalListSubstance,
    OMRIProduct,
    OrganicSystemPlan,
    WSDAMaterial,
)
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production, SoilManagementEvent
from product.models import Parcel


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class Phase1DriftTests(TransactionTestCase):
    """End-to-end signal tests for the new Phase 1 sources."""

    def setUp(self):
        self.company = Company.objects.create(name="Phase1 Farm")
        self.establishment = Establishment.objects.create(
            name="CA Ranch",
            company=self.company,
            state="CA",
        )
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.history = Production.objects.create(
            name="Phase1 Production",
            start_date=timezone.now(),
            parcel=self.parcel,
        )

        # Seed catalogs.
        self.wsda_regalia = WSDAMaterial.objects.create(
            wsda_id="WSDA-REG-TEST-1",
            brand_name="Regalia Biofungicide",
            manufacturer="Marrone Bio",
            category="pesticide",
        )
        self.wsda_nep = WSDAMaterial.objects.create(
            wsda_id="WSDA-REG-TEST-2",
            brand_name="Neptune's Harvest Fish & Seaweed 2-3-1",
            manufacturer="Neptune's Harvest",
            category="fertilizer",
            is_cdfa_oim_registered=True,
            cdfa_oim_reg_number="CDFA-OIM-NH-231",
        )
        self.wsda_unregistered_fert = WSDAMaterial.objects.create(
            wsda_id="WSDA-REG-TEST-3",
            brand_name="Mystery Brand Fish 4-4-1",
            manufacturer="Mystery Co",
            category="fertilizer",
            is_cdfa_oim_registered=False,
        )

        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )

    def test_wsda_approval_clears_drift_on_chemical(self):
        """Chemical event with WSDA-only product in OSP approved set resolves cleanly."""
        self.osp.approved_wsda_materials.add(self.wsda_regalia)

        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Regalia Biofungicide",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_wsda_not_approved_flags_drift_with_wsda_resolved_via(self):
        """Chemical event matching a WSDA product NOT on approved list → drift with resolved_via='wsda'."""
        # No OSP approval for Regalia at all — resolver finds WSDA first and
        # emits drift with resolved_via='wsda'.
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Regalia Biofungicide",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["resolved_via"], "wsda")

    def test_ca_cdfa_unknown_is_surfaced_without_asserting_a_violation(self):
        """CA establishment + fertilizer amendment resolving to a row Trazo does not hold
        as CDFA-registered → the sub-finding says UNCHECKED, never "missing".

        Trazo's CDFA reference set is 17 rows of a list that runs to thousands, so absence
        from it is not evidence of non-registration (2026-09-06).
        """
        self.osp.approved_wsda_materials.add(self.wsda_unregistered_fert)

        ev = SoilManagementEvent.objects.create(
            history=self.history,
            type="OM",
            amendment_type="compost",
            amendment_product_name="Mystery Brand Fish 4-4-1",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning.get("cdfa_oim_status", {}).get("status"), "unknown")
        self.assertEqual(ev.drift_warning["reason_params"]["issues"], ["cdfa_unknown"])
        self.assertIn("was not checked", ev.drift_warning["reason"])
        self.assertNotIn("registration is missing", ev.drift_warning["reason"])
        # No invented registration number rides along in the payload.
        self.assertNotIn("cdfa_oim_reg_number", ev.drift_warning["cdfa_oim_status"])

    def test_ca_cdfa_registered_clears_when_osp_approved(self):
        """OSP-approved WSDA product WITH CDFA registration on CA farm → no drift at all."""
        self.osp.approved_wsda_materials.add(self.wsda_nep)

        ev = SoilManagementEvent.objects.create(
            history=self.history,
            type="OM",
            amendment_type="compost",
            amendment_product_name="Neptune's Harvest Fish & Seaweed 2-3-1",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_unresolved_name_gets_omri_search_url(self):
        """Totally unknown input name → drift_warning with resolved_via='unresolved' AND omri_search_url populated."""
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Nonexistent Super Spray 99",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["resolved_via"], "unresolved")
        self.assertIn("omri.org/omri-search", ev.drift_warning["omri_search_url"])
        self.assertIn(
            "Nonexistent+Super+Spray",
            ev.drift_warning["omri_search_url"],
        )

    def test_wsda_approval_clears_drift_when_product_also_in_omri(self):
        """Regression: a product listed in BOTH OMRI and WSDA, approved on the OSP
        as WSDA only, must NOT fire a false-positive drift via the OMRI resolver.
        """
        # Same brand name exists in both catalogs (pre-existing omri_seed.csv has
        # 'Regalia Biofungicide'; we seeded WSDA's Regalia in setUp).
        OMRIProduct.objects.create(
            omri_id="OMRI-REG-DUP",
            product_name="Regalia Biofungicide",
        )
        # Only WSDA entry is approved on the OSP.
        self.osp.approved_wsda_materials.add(self.wsda_regalia)

        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Regalia Biofungicide",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        # Before the cross-catalog fix this would fire resolved_via='omri'
        # because the OMRI resolver wins at Layer 2. After the fix, WSDA
        # approval clears the finding.
        self.assertIsNone(ev.drift_warning)

    def test_non_ca_establishment_does_not_emit_cdfa_finding(self):
        """Establishment not in CA → CDFA OIM sub-finding is never surfaced."""
        self.establishment.state = "OR"
        self.establishment.save()
        self.osp.approved_wsda_materials.add(self.wsda_unregistered_fert)

        ev = SoilManagementEvent.objects.create(
            history=self.history,
            type="OM",
            amendment_type="compost",
            amendment_product_name="Mystery Brand Fish 4-4-1",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        # OSP-approved + no CA escalation → no drift at all.
        self.assertIsNone(ev.drift_warning)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class SeedSourceDriftTests(TransactionTestCase):
    """Phase 2 — seed source drift classifier (§ 205.204 / NOP 5029).

    These tests exercise the signal path (CREATE/UPDATE ProductionEvent with
    type='PL') so the full transaction.on_commit + post_save chain runs, not
    just the classifier in isolation.
    """

    def setUp(self):
        self.company = Company.objects.create(name="Seed Farm")
        self.establishment = Establishment.objects.create(name="Seed Ranch", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.history = Production.objects.create(
            name="Seed Production",
            start_date=timezone.now(),
            parcel=self.parcel,
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )

    def _make_pl_event(self, **extra):
        from history.models import ProductionEvent

        return ProductionEvent.objects.create(
            history=self.history,
            type="PL",
            date=timezone.now(),
            **extra,
        )

    def test_certified_organic_seed_clears_drift(self):
        from history.models import ProductionEvent

        ev = self._make_pl_event(seed_certification_status="certified_organic", variety="Heirloom Tomato")
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_missing_certification_flags_finding(self):
        ev = self._make_pl_event(variety="Carrot")
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["resolved_via"], "seed_certification_missing")
        self.assertIn("organicseedfinder.org", ev.drift_warning["omri_search_url"])

    def test_non_organic_untreated_without_3_searches_flags(self):
        ev = self._make_pl_event(
            seed_certification_status="non_organic_untreated",
            variety="Romaine",
            seed_search_attempts=[{"supplier": "A"}, {"supplier": "B"}],
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["resolved_via"], "seed_search_incomplete")

    def test_non_organic_untreated_with_3_searches_clears(self):
        ev = self._make_pl_event(
            seed_certification_status="non_organic_untreated",
            variety="Romaine",
            seed_search_attempts=[
                {"supplier": "A"},
                {"supplier": "B"},
                {"supplier": "C"},
            ],
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_non_organic_treated_always_flags(self):
        ev = self._make_pl_event(seed_certification_status="non_organic_treated", variety="Corn")
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["resolved_via"], "seed_treated_prohibited")

    def test_non_pl_subtype_does_not_emit_seed_finding(self):
        """Irrigation, harvest, pruning events must not trigger § 205.204 findings
        even when they happen to have seed_certification_status populated by a
        careless import."""
        from history.models import ProductionEvent

        ev = ProductionEvent.objects.create(
            history=self.history,
            type="IR",
            date=timezone.now(),
            seed_certification_status="",
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)


class ECFRSyncTests(TransactionTestCase):
    """eCFR sync command — hash-based drift detection on repeated runs."""

    @patch("certifications.management.commands.sync_national_list_ecfr.requests.get")
    def test_sync_persists_revision_and_detects_hash_change(self, mock_get):
        from django.core.management import call_command

        # First run — no previous revision, change_detected=True.
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = "<DIV8>§ 205.601 content v1</DIV8>"
        call_command("sync_national_list_ecfr", "--date", "2025-01-01")

        revisions = NationalListRevision.objects.order_by("id")
        self.assertGreaterEqual(revisions.count(), 2)  # 601 + 602
        for r in revisions:
            self.assertTrue(r.change_detected)
            self.assertGreater(r.response_bytes, 0)

        # Second run — identical body, change_detected=False.
        call_command("sync_national_list_ecfr", "--date", "2025-01-02")
        latest_601 = NationalListRevision.objects.filter(cfr_section="205.601").order_by("-fetched_at").first()
        self.assertFalse(latest_601.change_detected)

        # Third run — upstream body changed → change_detected=True again.
        mock_get.return_value.text = "<DIV8>§ 205.601 content v2 — updated</DIV8>"
        call_command("sync_national_list_ecfr", "--date", "2025-01-03")
        newest_601 = NationalListRevision.objects.filter(cfr_section="205.601").order_by("-fetched_at").first()
        self.assertTrue(newest_601.change_detected)
