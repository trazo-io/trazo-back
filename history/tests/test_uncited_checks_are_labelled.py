"""A house preference must not be presented as a regulatory gap.

Every row `compliance_snapshot_rows()` emits carries a CFR citation in its label — except
"Documentation depth", which has none, because there is no rule behind it. The NOP does not
require photographs: § 205.103(b) asks for records sufficient to demonstrate compliance and
does not enumerate them, and USDA's own crop documentation forms use a dated photograph as an
example of evidencing ONE practice (buffer marking), not as a general obligation. The
ten-photo floor is Trazo's.

The card renders every non-PASS row identically — amber, "Needs attention". If an uncited
preference reads the same as § 205.203(c)(2), a grower is told their packet fails a
requirement that does not exist, on a card whose footer promises these are "documentation
checks on your records in Trazo, not a compliance decision".
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import Production
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class UncitedCheckLabellingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="uncited@test.com", password="x")
        company = Company.objects.create(name="Uncited Farm")
        est = Establishment.objects.create(name="U Block", company=company)
        parcel = Parcel.objects.create(name="P1", establishment=est, area=1.0)
        crop = CropType.objects.create(
            name="Walnuts",
            slug="walnuts-uncited",
            category="tree_nut",
            description="n",
            typical_farm_size="10",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        product = Product.objects.create(name="Walnuts")
        self.history = Production.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
        )

    def _rows(self):
        return AuditExportService(self.history, certification_type="organic").compliance_snapshot_rows()

    def test_the_photo_row_is_informational_not_a_certifier_finding(self):
        """It must never be REVIEW: REVIEW is what puts a row in the readiness card's action
        list, in amber, beside § 205.203(c)(2), on a card titled "Before your certifier
        packet". There is no photo requirement to fall short of."""
        row = next(r for r in self._rows() if r["label"] == "Documentation depth")
        self.assertEqual(
            row["status"],
            "INFO",
            "the fixture has no photos; the row should report that as INFO, not as a finding",
        )
        self.assertIn("not required by the NOP", row["detail"])

    def test_the_photo_row_never_reaches_the_readiness_card_as_an_action(self):
        from company.views import ACTIONABLE_READINESS_STATUSES

        row = next(r for r in self._rows() if r["label"] == "Documentation depth")
        self.assertNotIn(
            row["status"],
            ACTIONABLE_READINESS_STATUSES,
            "a photo count is not something a certifier asks a grower to fix",
        )

    def test_every_other_non_pass_row_carries_a_citation(self):
        """If a new uncited check appears, it has to be labelled deliberately."""
        uncited = [r["label"] for r in self._rows() if "§" not in r["label"] and r["label"] != "Documentation depth"]
        self.assertEqual(
            uncited,
            [],
            f"these snapshot rows carry no CFR citation and no recommendation caveat: {uncited}. "
            "Either cite the rule or say it is a Trazo recommendation.",
        )
