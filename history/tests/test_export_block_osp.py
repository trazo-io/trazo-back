"""
Export-only P2 fixes (2026-06 NOP-alignment audit):
- Block column added to the Pest Management + Irrigation Records tables (block_id was
  previously rendered only on the Production Events table).
- beneficial_insects_used surfaces in the pest Beneficial/Qty column (was dropped).
- OSPAnnualUpdate (§ 205.406 annual continuation) now rendered in the OSP reference
  section (previously the OSP section queried OrganicSystemPlan only and never showed it).
"""

from datetime import date, timedelta

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
    def _certify(self, effective):
        """Give the operation a NOP certificate — § 205.406 binds certified operations only."""
        from certifications.models import Certification

        return Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certification_number="CCOF-TEST-1",
            certifier_name="CCOF",
            effective_date=effective,
        )

    def test_missing_annual_update_fires_review(self):
        self._certify(date(2020, 1, 1))
        OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        text = _section_text(self._svc()._build_osp_reference_section())
        self.assertIn("Annual Continuation", text)
        self.assertIn("[REVIEW] 7 CFR 205.406", text)

    def test_an_uncertified_applicant_is_not_flagged_for_a_continuation(self):
        """§ 205.406 binds a CERTIFIED operation.

        An operation seeking initial certification owes a § 205.401 application, not a
        continuation. Amber against it is the cry-wolf pattern: nothing the grower can do
        today would clear it, and it teaches the reader to skim past the flags that matter.
        """
        OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        text = _section_text(self._svc()._build_osp_reference_section())
        self.assertNotIn("[REVIEW] 7 CFR 205.406", text)
        self.assertIn("§ 205.401 application", text)

    def test_a_first_year_operation_is_told_when_the_first_update_falls_due(self):
        """Not yet due is not the same as missing — and the date is the useful part."""
        self._certify(date.today() - timedelta(days=30))
        OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        text = _section_text(self._svc()._build_osp_reference_section())
        self.assertNotIn("[REVIEW] 7 CFR 205.406", text)
        self.assertIn("falls due on", text)

    def test_a_non_nop_certificate_does_not_create_the_duty(self):
        """A Non-GMO or GlobalG.A.P. certificate puts nobody under 7 CFR Part 205."""
        from certifications.models import Certification

        Certification.objects.create(
            establishment=self.establishment,
            certification_type="global_gap",
            certification_number="GG-1",
            certifier_name="SCS",
            effective_date=date(2019, 1, 1),
        )
        OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        text = _section_text(self._svc()._build_osp_reference_section())
        self.assertNotIn("[REVIEW] 7 CFR 205.406", text)

    def test_annual_update_renders(self):
        # Year must match the production's own year — the exporter selects the filing that
        # covers the period under review, not simply the newest one on file.
        year = self.history.start_date.year
        osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        # Filed: a draft revision is correctly flagged "not filed" (§ 205.406), which this test is not about.
        OSPAnnualUpdate.objects.create(
            prior_osp=osp, reporting_year=year, changes_summary="Added new foliar input", submitted_at=timezone.now()
        )
        text = _section_text(self._svc()._build_osp_reference_section())
        self.assertIn("Annual Continuation", text)
        self.assertIn(str(year), text)
        self.assertIn("Added new foliar input", text)
        self.assertNotIn("[REVIEW] 7 CFR 205.406", text)

    def test_annual_update_for_wrong_year_is_flagged_not_passed_off(self):
        """
        A filing from another year must not silently stand in for the year under review.
        It renders for reference but still fires the § 205.406 REVIEW flag.
        """
        year = self.history.start_date.year
        osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        OSPAnnualUpdate.objects.create(prior_osp=osp, reporting_year=year - 2, changes_summary="Two seasons ago")
        text = _section_text(self._svc()._build_osp_reference_section())
        self.assertIn(str(year - 2), text)
        self.assertIn("[REVIEW] 7 CFR 205.406", text)
        self.assertIn("does not reaffirm the OSP for the year under review", text)

    def test_sections_unchanged_attestation_renders(self):
        """Per-section attestation must reach the PDF — it was captured but never rendered."""
        year = self.history.start_date.year
        osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        OSPAnnualUpdate.objects.create(
            prior_osp=osp,
            reporting_year=year,
            sections_unchanged_attestation={
                "practices_procedures": True,
                "monitoring_plan": True,
            },
        )
        text = _section_text(self._svc()._build_osp_reference_section())
        self.assertIn("Sections Attested Unchanged", text)
        self.assertIn("Practices Procedures", text)
        self.assertIn("Monitoring Plan", text)
        # Sections the operator did not affirm are reported as NOT ATTESTED, never as
        # "changed" — the data cannot distinguish "it changed" from "never answered",
        # and only the weaker claim is defensible on a compliance document.
        self.assertIn("Sections Not Attested", text)
        self.assertIn("Inputs List", text)
        self.assertNotIn("Sections With Changes", text)

    def test_no_attestation_does_not_claim_all_sections_changed(self):
        """
        A farmer who never touches the attestation widget must not have every section
        reported to the certifier — the row is suppressed entirely.
        """
        year = self.history.start_date.year
        osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        OSPAnnualUpdate.objects.create(
            prior_osp=osp, reporting_year=year, changes_summary="Narrative only", sections_unchanged_attestation={}
        )
        text = _section_text(self._svc()._build_osp_reference_section())
        self.assertIn("Narrative only", text)
        self.assertNotIn("Sections Not Attested", text)
        self.assertNotIn("Sections With Changes", text)

    def test_a_revoked_certification_carries_no_continuation_duty(self):
        """§ 205.406 attaches to a CERTIFIED operation. A revoked one is not one.

        The prose still distinguishes this from "never certified" — they are different facts
        and a reader needs to know which they are looking at.
        """
        cert = self._certify(date(2020, 1, 1))
        cert.verification_status = "revoked"
        cert.save(update_fields=["verification_status"])
        OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="active")
        text = _section_text(self._svc()._build_osp_reference_section())
        self.assertNotIn("[REVIEW] 7 CFR 205.406", text)
        self.assertIn("currently active", text)
        self.assertNotIn("§ 205.401 application", text)
