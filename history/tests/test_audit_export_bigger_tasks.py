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
from history.models import ChemicalEvent, History
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
        self.history = History.objects.create(
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
        self.assertIn("DOCUMENTED", txt)
        self.assertNotIn("[GAP]", txt)

    def test_facility_block_stale_shows_gap(self):
        f = self._facility(effective_date=timezone.now().date() - timedelta(days=600))
        txt = _flowable_text(AuditExportService(self.history)._facility_cert_block(f))
        self.assertIn("[GAP]", txt)

    # ---- #4 OSP-approved stamp ----

    def _osp_with_input(self, on_osp):
        osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
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
        self.assertIn("OSP Approval (CCOF)", txt)
        self.assertIn("OSP-approved", txt)

    def test_input_not_on_osp_shows_review_gap(self):
        txt = _flowable_text(self._osp_with_input(on_osp=False)._build_chemical_log())
        self.assertIn("not on OSP", txt)
