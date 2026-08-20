"""Two rows about the OSP must be two different actions, not one counted twice.

The readiness card showed, together, "The Organic System Plan is still a draft" (whole
operation) and "Organic System Plan (§ 205.201) — v1 Draft (not yet submitted) — 66%
materially complete" (this season), and reported "2 open items". Both fired off the same
fact — `status` is not submitted/active — so a grower read one action twice and the headline
overstated what was left to do.

The season row's actual substance is section completeness. "66% materially complete" is a real
and separate signal, but naming no section gave nobody anything to do. It now names the
sections under the narrative floor, which is the only thing that makes it a distinct action.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from certifications.models import OrganicSystemPlan
from company.models import Company, Establishment
from history.models import History
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class OSPRowDistinctnessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="osprow@test.com", password="x")
        company = Company.objects.create(name="OSP Farm")
        self.est = Establishment.objects.create(name="O Block", company=company)
        parcel = Parcel.objects.create(name="P1", establishment=self.est, area=1.0)
        crop = CropType.objects.create(
            name="Walnuts", slug="walnuts-osprow", category="tree_nut", description="n",
            typical_farm_size="10", growing_season="s", harvest_season="h",
            emissions_per_hectare=0.0, industry_average=0.0, best_practice=0.0,
            carbon_credit_potential=0.0, typical_cost_per_hectare=0.0, has_soil_contact=True,
        )
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            parcel=parcel, product=product, crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
        )

    def _osp_row(self):
        rows = AuditExportService(self.history, certification_type="organic").compliance_snapshot_rows()
        return next(r for r in rows if r["label"] == "Organic System Plan (§ 205.201)")

    def test_a_thin_section_is_named_so_the_row_is_actionable(self):
        long_enough = "Real narrative describing the practice in specific terms. " * 12
        OrganicSystemPlan.objects.create(
            establishment=self.est,
            status="draft",
            version_number=1,
            sections={
                "practices_procedures": {"narrative": long_enough},
                "inputs_list": {"narrative": long_enough},
                "monitoring_plan": {"narrative": long_enough},
                "commingling_barriers": {"narrative": long_enough},
                # deliberately short
                "recordkeeping_description": {"narrative": "Short."},
                "additional_certifier_info": {"narrative": "Short."},
            },
        )
        detail = self._osp_row()["detail"]
        self.assertIn(
            "below the narrative floor",
            detail,
            "a percentage alone tells the grower nothing to do",
        )
        self.assertIn("Recordkeeping system (a)(4)", detail)
        self.assertIn("Additional certifier info (a)(6)", detail)

    def test_a_complete_plan_names_no_sections(self):
        long_enough = "Real narrative describing the practice in specific terms. " * 12
        OrganicSystemPlan.objects.create(
            establishment=self.est,
            status="draft",
            version_number=1,
            sections={k: {"narrative": long_enough} for k in (
                "practices_procedures", "inputs_list", "monitoring_plan",
                "recordkeeping_description", "commingling_barriers", "additional_certifier_info",
            )},
        )
        detail = self._osp_row()["detail"]
        self.assertNotIn("below the narrative floor", detail)
