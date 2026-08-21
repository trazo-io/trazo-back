"""With no sales on file, the packet must not answer the sales questions with "No".

"Organic Identified on Invoice: No" states that the operator shipped organic product on
documents that failed to identify it as organic — a § 205.307(a) / SOE non-conformance. The
packet was printing it for a season whose crop was still on the tree, because the flag was
falsy and nothing distinguished "answered no" from "not asked yet".

Absence of an attestation is not a denial. It is the same rule the OSP N/A sections follow.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import History
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product


def _text(elements):
    out = []
    for el in elements:
        out.append(getattr(el, "text", "") or "")
        for row in getattr(el, "_cellvalues", None) or []:
            for cell in row:
                out.append(getattr(cell, "text", "") or "")
    return " ".join(out)


class NoSalesIsNotADenialTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Sales Co")
        est = Establishment.objects.create(name="Sales Farm", company=company)
        parcel = Parcel.objects.create(name="P", establishment=est, area=1.0)
        crop = CropType.objects.create(
            name="Walnut",
            slug="walnut-sales",
            category="tree_nut",
            description="d",
            typical_farm_size="1",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        product = Product.objects.create(name="Walnut")
        self.history = History.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=60),
        )

    def test_an_unsold_season_does_not_assert_a_labelling_failure(self):
        text = _text(AuditExportService(self.history, certification_type="organic")._build_mass_balance_section())
        self.assertIn("Organic Identified on Invoice", text)
        self.assertIn("no sales recorded", text)
        self.assertNotIn("Organic Identified on Invoice: No", text)

    def test_a_sold_season_still_answers_the_question(self):
        self.history.sold_to = "Sacramento Valley Hulling"
        self.history.save(update_fields=["sold_to"])
        text = _text(AuditExportService(self.history, certification_type="organic")._build_mass_balance_section())
        self.assertNotIn("no sales recorded", text)
