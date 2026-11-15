"""
Audit-export tests for the CCOF-grounded "bigger tasks" (2026-06-27):
- #3 Off-farm handler / facility certificate block (CCOF G6.1 15-month freshness
  -> DOCUMENTED / GAP / REVIEW).
- #4 OSP-approved-on-OSP input stamp in the chemical-log OMRI table.
"""

import re
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from certifications.models import OMRIProduct, OrganicSystemPlan, PostHarvestFacility
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


def _flowable_text(flowables):
    """Flatten Paragraph + Table flowables to a single searchable string."""
    out = []
    for f in flowables:
        if hasattr(f, "text"):
            out.append(re.sub(r"<[^>]+>", "", f.text))
        elif hasattr(f, "_cellvalues"):
            for row in f._cellvalues:
                for cell in row:
                    if hasattr(cell, "text"):
                        out.append(re.sub(r"<[^>]+>", "", cell.text))
    return " ".join(out)


class BiggerTasksAuditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="big@test.com", password="x")
        self.company = Company.objects.create(name="Big Farm")
        self.establishment = Establishment.objects.create(name="B1", company=self.company, state="California")
        self.parcel = Parcel.objects.create(name="BP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Walnut")
        self.history = Production.objects.create(
            name="BH1",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            is_outdoor=True,
        )

    def _facility(self, **kwargs):
        defaults = dict(
            establishment=self.establishment,
            name="Test Huller",
            facility_type="huller",
            state="California",
            certification_number="CCOF-H-1",
            certifier_name="CCOF",
        )
        defaults.update(kwargs)
        return PostHarvestFacility.objects.create(**defaults)

    # ---- #3 cert freshness (CCOF G6.1) ----

    def test_cert_current_within_15_months_is_true(self):
        f = self._facility(effective_date=timezone.now().date() - timedelta(days=30))
        self.assertIs(f.cert_is_current, True)

    def test_cert_older_than_15_months_is_false(self):
        f = self._facility(effective_date=timezone.now().date() - timedelta(days=600))
        self.assertIs(f.cert_is_current, False)

    def test_cert_expired_is_false(self):
        today = timezone.now().date()
        f = self._facility(effective_date=today - timedelta(days=10), expiry_date=today - timedelta(days=1))
        self.assertIs(f.cert_is_current, False)

    def test_cert_no_effective_date_is_none(self):
        f = self._facility(effective_date=None)
        self.assertIsNone(f.cert_is_current)

    # ---- #3 facility block render ----

    def test_facility_block_current_shows_documented(self):
        f = self._facility(effective_date=timezone.now().date() - timedelta(days=30))
        txt = _flowable_text(AuditExportService(self.history)._facility_cert_block(f))
        self.assertIn("Test Huller", txt)
        # Run 7 (R7-01): dates inside the window no longer print "DOCUMENTED"; they say what the
        # dates do and do not establish.
        self.assertIn("fall within the ~15-month window", txt)
        self.assertNotIn("DOCUMENTED", txt)
        self.assertNotIn("[REVIEW]", txt)

    def test_facility_block_stale_asks_for_a_current_copy_without_claiming_expiry(self):
        """A NOP certificate does not expire (§ 205.404(d)) — the copy on file goes stale.

        The flag used to read "expired or older than 15 months", contradicting this same
        document's Active Certification Summary footnote two pages earlier. It was also the
        only [GAP] in a packet that otherwise flags REVIEW / WARNING / NON-CONFORMANCE.
        """
        f = self._facility(effective_date=timezone.now().date() - timedelta(days=600))
        txt = _flowable_text(AuditExportService(self.history)._facility_cert_block(f))
        self.assertIn("[REVIEW]", txt)
        self.assertIn("more than 15 months old", txt)
        self.assertNotIn("expired", txt)
        self.assertNotIn("[GAP]", txt)

    # ---- #4 OSP-approved stamp ----

    def _osp_with_input(self, on_osp, status="active"):
        osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status=status,
            sections={},
            created_by=self.user,
        )
        omri = OMRIProduct.objects.create(omri_id="omri-test-1", product_name="Test Fish Fertilizer")
        if on_osp:
            osp.approved_omri_products.add(omri)
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Test Fish Fertilizer",
            omri_product=omri,
            date=timezone.now(),
        )
        return AuditExportService(self.history, certification_type="organic")

    def test_input_on_osp_shows_osp_approved(self):
        txt = _flowable_text(self._osp_with_input(on_osp=True)._build_chemical_log())
        # Header de-branded 2026-08-20: it read "OSP Approval (CCOF)" on every packet,
        # including a WSDA one. The OSP material list is a requirement across accredited
        # certifiers, so the column names the artifact, not one certifier.
        self.assertIn("OSP Approval", txt)
        self.assertNotIn("(CCOF)", txt)
        self.assertIn("OSP-approved", txt)

    def test_input_not_on_osp_shows_review_gap(self):
        txt = _flowable_text(self._osp_with_input(on_osp=False)._build_chemical_log())
        self.assertIn("not on OSP", txt)

    def test_an_input_on_a_draft_plan_is_never_called_approved(self):
        """Orchard specimen read (2026-11-14): with no active plan the column read the newest draft
        and printed "OSP-approved" beside every input on it, inputs with an unconfirmed basis
        included. Approval is a certifier's act; a draft only says what the operator listed."""
        txt = _flowable_text(self._osp_with_input(on_osp=True, status="draft")._build_chemical_log())
        self.assertNotIn("OSP-approved", txt)
        self.assertIn("On draft plan", txt)
        self.assertIn("plan v1, which is a draft, not approved", txt)
        self.assertIn("not that it is on the approved plan in force", txt)

    def test_an_input_on_a_submitted_plan_says_submitted(self):
        txt = _flowable_text(self._osp_with_input(on_osp=True, status="submitted")._build_chemical_log())
        self.assertNotIn("OSP-approved", txt)
        self.assertIn("On submitted plan", txt)
        self.assertIn("submitted to the certifier, not yet approved", txt)

    def test_a_superseded_plan_is_not_called_unapproved(self):
        """Review of #430: `activate()` supersedes a plan only once approval evidence is on file, so a
        superseded plan was approved. It is out of force, and the note says that and no more."""
        txt = _flowable_text(self._osp_with_input(on_osp=True, status="superseded")._build_chemical_log())
        self.assertNotIn("OSP-approved", txt)
        self.assertIn("On superseded plan", txt)
        self.assertIn("superseded by a later version, so it is not the plan in force", txt)
        self.assertNotIn("not approved", txt)

    def test_an_active_plan_prints_no_draft_disclosure(self):
        txt = _flowable_text(self._osp_with_input(on_osp=True)._build_chemical_log())
        self.assertNotIn("approved plan in force", txt)
