"""
CA DPR Restricted Materials Permit drift-detector tests.

**Status (2026-04-16)**: class-level skipped pending a real CDPR Chem Code
adapter. The prior implementation used a keyword tuple that was verified to
contain entirely false positives (copper hydroxide, copper sulfate, sulfur,
pyrethrin, spinosad, rotenone are NOT California Restricted Materials under
3 CCR § 6400; CDPR explicitly states "California Restricted Material: No" for
copper hydroxide). See ``documentation/adr/008-ca-dpr-restricted-materials-adapter.md``
for the rationale and the shape of the future adapter.

The original assertions are retained below (class-level skip) so that the
test scaffolding is a drop-in when the adapter lands. One positive test in
``EmptyRestrictedListBehaviourTests`` guards the current empty-tuple
contract.
"""

import unittest
from datetime import date, timedelta

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from certifications.models import OMRIProduct, OrganicSystemPlan
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from product.models import Parcel


@unittest.skip("Deferred — see ADR-008: CA DPR Restricted Materials Adapter")
@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CADPRPermitDriftTests(TransactionTestCase):
    """
    Pre-empty-tuple behaviour, preserved for the future adapter.

    Every test below assumes ``CA_RESTRICTED_KEYWORDS`` contains copper
    hydroxide / Kocide-family keywords. With the tuple empty, none of the
    drift_warning ``ca_dpr_permit_status`` sub-findings are emitted, so every
    assertion fails. The class-level skip preserves the intent without the
    noise.
    """

    def setUp(self):
        self.company = Company.objects.create(name="DPR Farm")
        self.establishment = Establishment.objects.create(name="CA Ranch", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.history = Production.objects.create(
            name="DPR Production",
            start_date=timezone.now(),
            parcel=self.parcel,
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )
        self.omri_kocide = OMRIProduct.objects.create(
            omri_id="OMRI-TEST-KOC",
            product_name="Kocide 3000",
        )

    def test_ca_farm_restricted_input_no_permit_is_missing(self):
        self.osp.approved_omri_products.add(self.omri_kocide)
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Kocide 3000",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        dpr = ev.drift_warning.get("ca_dpr_permit_status")
        self.assertIsNotNone(dpr)
        self.assertEqual(dpr["status"], "missing")

    def test_ca_farm_restricted_input_with_valid_permit_clears(self):
        self.osp.approved_omri_products.add(self.omri_kocide)
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Kocide 3000",
            ca_dpr_permit_number="SD-2026-00147",
            ca_dpr_permit_county="San Diego",
            ca_dpr_permit_expires=date.today() + timedelta(days=180),
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_ca_farm_expired_permit_fires_drift(self):
        self.osp.approved_omri_products.add(self.omri_kocide)
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Kocide 3000",
            ca_dpr_permit_number="SD-2024-EXPIRED",
            ca_dpr_permit_county="San Diego",
            ca_dpr_permit_expires=date.today() - timedelta(days=30),
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        dpr = ev.drift_warning.get("ca_dpr_permit_status")
        self.assertEqual(dpr["status"], "expired")
        self.assertEqual(dpr["permit_number"], "SD-2024-EXPIRED")

    def test_non_ca_farm_restricted_input_no_dpr_finding(self):
        self.establishment.state = "OR"
        self.establishment.save()
        self.osp.approved_omri_products.add(self.omri_kocide)
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Kocide 3000",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_ca_farm_non_restricted_input_no_dpr_finding(self):
        non_restricted = OMRIProduct.objects.create(
            omri_id="OMRI-TEST-FISH",
            product_name="Neptune's Harvest Fish 2-3-1",
        )
        self.osp.approved_omri_products.add(non_restricted)
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Neptune's Harvest Fish 2-3-1",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_ca_farm_unresolved_restricted_input_still_flags_dpr(self):
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Sulfur dust (unknown brand)",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        dpr = ev.drift_warning.get("ca_dpr_permit_status")
        self.assertIsNotNone(dpr)
        self.assertEqual(dpr["status"], "missing")

    def test_keyword_match_is_case_insensitive(self):
        self.osp.approved_omri_products.add(self.omri_kocide)
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="KOCIDE 3000",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["ca_dpr_permit_status"]["status"], "missing")

    def test_nl_substance_name_contributes_to_keyword_match(self):
        from certifications.models import NationalListSubstance
        from certifications.services.omri_verifier import _normalize

        nl = NationalListSubstance.objects.create(
            substance_name="Copper hydroxide",
            substance_name_normalized=_normalize("Copper hydroxide"),
            cfr_section="205.601",
            status="allowed",
        )
        self.osp.approved_national_list_substances.add(nl)
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Generic fungicide",
            national_list_substance=nl,
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["ca_dpr_permit_status"]["status"], "missing")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class EmptyRestrictedListBehaviourTests(TransactionTestCase):
    """
    Guards the current ADR-008 contract: with ``CA_RESTRICTED_KEYWORDS``
    empty, the drift detector must NOT emit a ``ca_dpr_permit_status``
    sub-finding for inputs that the prior keyword list would have caught
    (copper hydroxide, Kocide, sulfur, spinosad, etc.) — regardless of
    whether the farm is in CA and regardless of OSP approval status.

    This test fails if anyone re-populates the keyword tuple without first
    shipping a real CDPR Chem Code adapter (ADR-008).
    """

    def setUp(self):
        self.company = Company.objects.create(name="Empty-Tuple Farm")
        self.establishment = Establishment.objects.create(name="CA Test Ranch", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.history = Production.objects.create(
            name="Empty-Tuple Production",
            start_date=timezone.now(),
            parcel=self.parcel,
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )
        self.omri_kocide = OMRIProduct.objects.create(
            omri_id="OMRI-ADR008",
            product_name="Kocide 3000",
        )
        self.osp.approved_omri_products.add(self.omri_kocide)

    def test_keyword_tuple_is_empty(self):
        from certifications.services.drift_detector import CA_RESTRICTED_KEYWORDS

        # If anyone re-populates this without shipping ADR-008's real
        # adapter, this assertion — plus the other tests in this class —
        # should fail, forcing review of the false-positive history.
        self.assertEqual(CA_RESTRICTED_KEYWORDS, ())

    def test_kocide_on_ca_farm_emits_no_dpr_subfinding(self):
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Kocide 3000",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        # OSP-approved Kocide on a CA farm with empty keyword tuple: no
        # drift_warning at all (OSP approval clears drift; no DPR sub-finding
        # since the input no longer classifies as restricted).
        self.assertIsNone(ev.drift_warning)

    def test_unresolved_sulfur_on_ca_farm_no_dpr_subfinding(self):
        # Even for an UNRESOLVED input (drift_warning WILL fire for the
        # unresolved reason), the DPR sub-payload must be absent because the
        # input doesn't classify as restricted anymore.
        ev = ChemicalEvent.objects.create(
            history=self.history,
            type="PS",
            commercial_name="Sulfur dust (unknown brand)",
            date=timezone.now(),
        )
        ev.refresh_from_db()
        self.assertIsNotNone(ev.drift_warning)  # unresolved → drift still fires
        self.assertIsNone(ev.drift_warning.get("ca_dpr_permit_status"))
