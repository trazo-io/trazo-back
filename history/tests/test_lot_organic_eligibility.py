"""
Tests for the Phase 3 lot-level organic eligibility resolver.

The live audit found a USDA-certified fixture rendering "2 of 5 inputs
organic-approved" beneath the organic seal — the farm-cert vs lot-claim gap.
resolve_lot_organic_eligibility() closes it: a lot from a certified farm may
only carry the organic representation when the certificate was valid at
harvest, covers crops, and no prohibited inputs were applied (7 CFR 205.105 /
205.300). These tests cover the four plan-mandated scenarios (clean pass,
prohibited input, cert window, crop scope) plus the evidence-status and
input-status builders.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from certifications.models import Certification
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.services.claim_resolver import (
    build_organic_claim_evidence,
    resolve_input_status,
    resolve_lot_organic_eligibility,
)
from product.models import Parcel, Product
from users.models import User


class LotOrganicEligibilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="lot@test.com", password="x")
        self.company = Company.objects.create(name="Lot Farm")
        self.establishment = Establishment.objects.create(name="L1", company=self.company)
        self.parcel = Parcel.objects.create(name="LP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Avocado")
        today = timezone.now()
        self.history = History.objects.create(
            name="Lot Eligibility Test Production",
            start_date=today - timedelta(days=120),
            finish_date=today - timedelta(days=10),
            product=self.product,
            parcel=self.parcel,
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
        self.cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name="CCOF",
            verification_status="verified",
            certification_scope="Crops",
            effective_date=(today - timedelta(days=400)).date(),
            expiry_date=(today + timedelta(days=200)).date(),
        )

    def _chemical(self, **kwargs):
        defaults = {
            "history": self.history,
            "type": ChemicalEvent.FERTILIZER,
            "commercial_name": "Test Input",
            "date": timezone.now() - timedelta(days=30),
        }
        defaults.update(kwargs)
        return ChemicalEvent.objects.create(**defaults)

    # --- Scenario 1: clean pass ---------------------------------------------

    def test_clean_pass(self):
        self._chemical(commercial_name="Compost Tea", organic_approved="omri_listed")
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertTrue(result.eligible)
        self.assertEqual(result.status, "eligible")
        self.assertEqual(result.prohibited_inputs, [])

    # --- Scenario 2: prohibited input ----------------------------------------

    def test_prohibited_input_strips_eligibility(self):
        self._chemical(commercial_name="Glyphosate Pro", organic_approved="not_organic")
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertFalse(result.eligible)
        self.assertEqual(result.status, "prohibited_input")
        self.assertIn("Glyphosate Pro", result.prohibited_inputs)

    def test_prohibited_no_value_also_strips(self):
        self._chemical(commercial_name="Synthetic X", organic_approved="no")
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertFalse(result.eligible)
        self.assertEqual(result.status, "prohibited_input")

    def test_national_list_prohibited_overrides_self_report(self):
        # 7 CFR 205.602 — a National List "prohibited" match strips eligibility
        # even when the farmer self-reported the input as organic-approved.
        # Same signal the audit PDF cross-check engine uses.
        from certifications.models import NationalListSubstance

        substance = NationalListSubstance.objects.create(
            substance_name="Arsenic",
            substance_name_normalized="arsenic",
            cfr_section="205.602",
            status="prohibited",
        )
        self._chemical(
            commercial_name="Legacy Arsenical",
            organic_approved="omri_listed",
            national_list_substance=substance,
        )
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertFalse(result.eligible)
        self.assertEqual(result.status, "prohibited_input")
        self.assertIn("Legacy Arsenical", result.prohibited_inputs)

    def test_unclassified_inputs_do_not_strip(self):
        # Absence of classification is unknown, not a violation.
        self._chemical(commercial_name="Mystery Input", organic_approved=None)
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertTrue(result.eligible)
        self.assertEqual(result.unclassified_input_count, 1)

    def test_extra_data_classification_also_strips(self):
        # Legacy rows stored the classification in extra_data before the model
        # field existed — the gate must read the same fallback the public
        # serializer renders.
        self._chemical(
            commercial_name="Legacy Synthetic",
            organic_approved=None,
            extra_data={"organic_approved": "not_organic"},
        )
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertFalse(result.eligible)
        self.assertEqual(result.status, "prohibited_input")
        self.assertIn("Legacy Synthetic", result.prohibited_inputs)

    # --- Scenario 3: cert window vs harvest -----------------------------------

    def test_cert_expired_before_harvest(self):
        self.cert.expiry_date = (timezone.now() - timedelta(days=60)).date()
        self.cert.save()
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertFalse(result.eligible)
        self.assertEqual(result.status, "cert_not_valid_at_harvest")

    def test_cert_effective_after_harvest(self):
        self.cert.effective_date = (timezone.now() + timedelta(days=5)).date()
        self.cert.save()
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertFalse(result.eligible)
        self.assertEqual(result.status, "cert_not_valid_at_harvest")

    def test_in_progress_production_uses_today(self):
        self.history.finish_date = None
        self.history.save()
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertTrue(result.eligible)

    # --- Scenario 4: crop scope ------------------------------------------------

    def test_handling_only_cert_not_eligible(self):
        self.cert.certification_scope = "Handling"
        self.cert.save()
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertFalse(result.eligible)
        self.assertEqual(result.status, "crop_not_in_scope")

    def test_blank_scope_passes(self):
        # Most OID records don't populate scope on our Certification rows;
        # blank must not fail the gate.
        self.cert.certification_scope = ""
        self.cert.save()
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertTrue(result.eligible)

    # --- No cert: gate not applicable -----------------------------------------

    def test_no_cert_is_not_applicable(self):
        result = resolve_lot_organic_eligibility(self.history, None)
        self.assertIsNone(result.eligible)
        self.assertEqual(result.status, "not_applicable")

    # --- Prohibited input wins over cert-window failure ------------------------

    def test_prohibited_input_checked_first(self):
        self.cert.expiry_date = (timezone.now() - timedelta(days=60)).date()
        self.cert.save()
        self._chemical(commercial_name="Glyphosate Pro", organic_approved="not_organic")
        result = resolve_lot_organic_eligibility(self.history, self.cert)
        self.assertEqual(result.status, "prohibited_input")


class OrganicClaimEvidenceTests(TestCase):
    def _eligibility(self, eligible, status="eligible"):
        from history.services.claim_resolver import LotOrganicEligibility

        return LotOrganicEligibility(eligible=eligible, status=status, display_label="", detail="")

    def test_certified_eligible_lot_scope(self):
        """⚠️ `oid_matched` is REQUIRED for the OID source, and this test used to omit it.

        Until 2026-08-30 `source` was derived from `status == "certified_organic"` alone —
        which only means an active certificate ROW exists, something a manual admin edit, a
        data import or a fixture can create. `claim_resolver` now names the USDA Organic
        Integrity Database only when a match against it actually happened.

        This assertion was written against the old behaviour and kept passing a claim with no
        match behind it. Obeying it would have restored the unearned claim, so the fixture
        gains the flag it was always supposed to carry. See `.claude/rules/compliance.md`:
        "verified" is only for real OID matches.
        """
        evidence = build_organic_claim_evidence(
            {"status": "certified_organic", "oid_matched": True}, self._eligibility(True)
        )
        self.assertEqual(evidence["tier"], "certified")
        self.assertEqual(evidence["scope"], "production_lot")
        self.assertEqual(evidence["source"], "USDA Organic Integrity Database")

    def test_certified_without_an_oid_match_does_not_name_the_database(self):
        """The half the old test could not see: a certificate row is not a database match."""
        evidence = build_organic_claim_evidence({"status": "certified_organic"}, self._eligibility(True))
        self.assertEqual(evidence["source"], "Certificate on file for the operation")
        self.assertNotIn("Integrity Database", evidence["source"])

    def test_certified_ineligible_lot_degrades_to_documented(self):
        evidence = build_organic_claim_evidence(
            {"status": "certified_organic"}, self._eligibility(False, "prohibited_input")
        )
        self.assertEqual(evidence["tier"], "documented")
        self.assertEqual(evidence["scope"], "farm")

    def test_self_reported_stays_self_reported(self):
        evidence = build_organic_claim_evidence({"status": "self_reported"}, self._eligibility(None, "not_applicable"))
        self.assertEqual(evidence["tier"], "self_reported")
        self.assertEqual(evidence["source"], "Farmer-reported records")
        self.assertEqual(evidence["scope"], "farm")

    def test_transitioning_is_documented(self):
        evidence = build_organic_claim_evidence({"status": "transitioning"}, self._eligibility(None, "not_applicable"))
        self.assertEqual(evidence["tier"], "documented")


class InputStatusResolverTests(TestCase):
    class FakeEvent:
        def __init__(
            self,
            organic_approved=None,
            restricted_use_pesticide=False,
            extra_data=None,
            omri_product_id=None,
        ):
            self.organic_approved = organic_approved
            self.restricted_use_pesticide = restricted_use_pesticide
            self.extra_data = extra_data
            self.omri_product_id = omri_product_id

    def test_the_dropdown_alone_does_not_produce_an_omri_status(self):
        # Changed 2026-08-09. This test previously asserted that
        # organic_approved="omri_listed" yields status "omri_listed" — i.e. it asserted the
        # defect: the grower's dropdown pick published as a listing by OMRI, a real
        # third-party program, on the anonymous payload. See
        # claim_authority.may_claim_input_listing. Only a catalog FK earns that status.
        status = resolve_input_status(self.FakeEvent(organic_approved="omri_listed"))
        self.assertEqual(status["status"], "organic_approved")
        self.assertNotIn("OMRI", status["label"])

    def test_organic_approved_values(self):
        for value in ("usda_nop_approved", "organic_equivalent", "yes"):
            status = resolve_input_status(self.FakeEvent(organic_approved=value))
            self.assertEqual(status["status"], "organic_approved", value)

    def test_restricted_use_is_reported_as_conventional_not_as_rup(self):
        # Was `test_restricted_use_wins`, asserting status "restricted_use" — a string the
        # resolver has not been able to return since 2026-08-02, so this test was already
        # failing before the 2026-08-09 claim-authority change and is not a regression from
        # it. Restricted-use is an APPLICATOR-licensing category (40 CFR 152.175), not a
        # consumer-facing residue signal, so it is deliberately not a public chip; what the
        # consumer sees is that the input is conventional and documented.
        status = resolve_input_status(self.FakeEvent(organic_approved="omri_listed", restricted_use_pesticide=True))
        self.assertEqual(status["status"], "conventional_documented")

    def test_restricted_use_does_not_override_a_real_catalog_match(self):
        status = resolve_input_status(self.FakeEvent(omri_product_id=42, restricted_use_pesticide=True))
        self.assertEqual(status["status"], "omri_listed")

    def test_not_organic_is_conventional_documented(self):
        status = resolve_input_status(self.FakeEvent(organic_approved="not_organic"))
        self.assertEqual(status["status"], "conventional_documented")

    def test_blank_is_unclassified(self):
        status = resolve_input_status(self.FakeEvent(organic_approved=""))
        self.assertEqual(status["status"], "unclassified")

    def test_extra_data_fallbacks(self):
        # Legacy rows: classification / RUP flag only in extra_data — the
        # resolver must see what the public serializer renders.
        status = resolve_input_status(self.FakeEvent(extra_data={"organic_certification": "omri_listed"}))
        self.assertEqual(status["status"], "organic_approved")
        status = resolve_input_status(self.FakeEvent(extra_data={"restricted_use_pesticide": True}))
        self.assertEqual(status["status"], "conventional_documented")

    def test_omri_catalog_match_wins_over_blank_classification(self):
        # A linked OMRI product record (Sprint 3 catalog) is stronger evidence
        # than the farmer's dropdown — blank classification + match = OMRI.
        status = resolve_input_status(self.FakeEvent(omri_product_id=42))
        self.assertEqual(status["status"], "omri_listed")
