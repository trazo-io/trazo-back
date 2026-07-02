"""
Export-only P2 fixes (2026-06 NOP-alignment audit):
- Block column added to the Pest Management + Irrigation Records tables (block_id was
  previously rendered only on the Production Events table).
- beneficial_insects_used surfaces in the pest Beneficial/Qty column (was dropped).
- OSPAnnualUpdate (§ 205.406 annual continuation) now rendered in the OSP reference
  section (previously the OSP section queried OrganicSystemPlan only and never showed it).
"""

from django.test import TestCase
from django.utils import timezone

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from company.models import Company, Establishment
from history.models import History, PestManagementEvent, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


def _section_text(elements):
    out = []
    for el in elements:
        text = getattr(el, "text", None)
        if text:
            out.append(text)
        for row in getattr(el, "_cellvalues", None) or []:
            for cell in row:
                ctext = getattr(cell, "text", None)
                if ctext:
                    out.append(ctext)
    return " ".join(out)


class _Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="exp@test.com", password="x")
        self.company = Company.objects.create(name="Exp Farm")
        self.establishment = Establishment.objects.create(name="EE1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="EP", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = History.objects.create(
            name="Exp Production",
            start_date=timezone.now(),
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
        )

    def _svc(self):
        return AuditExportService(self.history, certification_type="organic")


class PestBlockTests(_Base):
    def test_block_and_beneficial_insects_used_render(self):
        PestManagementEvent.objects.create(
            history=self.history,
            type="SC",
            date=timezone.now(),
            pest_species="California red scale",
            block_id="Block N",
            beneficial_insects_used="yes",
        )
        text = _section_text(self._svc()._build_pest_section())
        self.assertIn("Block", text)  # column header
        self.assertIn("Block N", text)  # value
        self.assertIn("Natural enemies: yes", text)  # beneficial_insects_used surfaced


class IrrigationBlockTests(_Base):
    def test_block_renders_on_irrigation_table(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="IR",
            date=timezone.now(),
            block_id="Block S",
            water_source="well",
            irrigation_method="drip",
        )
        text = _section_text(self._svc()._build_production_events())
        self.assertIn("Block S", text)


class OspAnnualUpdateTests(_Base):
    def test_missing_annual_update_fires_review(self):
        OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        text = _section_text(self._svc()._build_osp_reference_section())
        self.assertIn("Annual Continuation", text)
        self.assertIn("[REVIEW] 7 CFR 205.406", text)

    def test_annual_update_renders(self):
        osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        OSPAnnualUpdate.objects.create(prior_osp=osp, reporting_year=2026, changes_summary="Added new foliar input")
        text = _section_text(self._svc()._build_osp_reference_section())
        self.assertIn("Annual Continuation", text)
        self.assertIn("2026", text)
        self.assertIn("Added new foliar input", text)
        self.assertNotIn("[REVIEW] 7 CFR 205.406", text)
