"""A business event must not describe itself as something stronger than it is.

The consumer page keys its copy off `BusinessEvent.business_type`: the value "certification"
renders as a 🏆 **"Certification Achievement"** with the line "A third-party certification was
recorded for this crop", at HIGH impact.

`business_type` used to DEFAULT to "certification". So an annual inspection (`type="IN"`) or a
state registration renewal (`type="CM"`) saved without an explicit value was announced to
shoppers as a third-party certification the crop had achieved — a claim manufactured by a
database default, which is what FTC 16 CFR 260.6 reaches and the same class as the withdrawn
carbon-credits activity.

The model's own `clean()` would have caught it ("Certification type is required for
certification events") but DRF never calls `full_clean()`, so nothing ran it.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import BusinessEvent, History
from product.models import Parcel, Product


class BusinessTypeMatchesRecordTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Biz Co")
        est = Establishment.objects.create(name="Biz Farm", company=company)
        parcel = Parcel.objects.create(name="P", establishment=est, area=4.0)
        crop = CropType.objects.create(
            name="Apple",
            slug="apple-biz",
            category="tree_fruit",
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
        product = Product.objects.create(name="Apple")
        self.history = History.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=120),
        )

    def _event(self, type_, **kw):
        return BusinessEvent.objects.create(
            history=self.history, type=type_, date=timezone.now(), description=f"{type_} record", **kw
        )

    def test_an_inspection_is_not_announced_as_a_certification(self):
        ev = self._event("IN")
        self.assertEqual(ev.business_type, "verification")
        self.assertNotEqual(ev.business_type, "certification")

    def test_a_compliance_record_is_not_announced_as_a_certification(self):
        ev = self._event("CM")
        self.assertEqual(ev.business_type, "compliance")

    def test_a_certification_event_still_says_certification(self):
        ev = self._event("CE")
        self.assertEqual(ev.business_type, "certification")

    def test_an_explicit_value_from_the_caller_is_respected(self):
        """Derivation fills a gap; it never overrides what the farmer chose."""
        ev = self._event("IN", business_type="sustainability_audit")
        self.assertEqual(ev.business_type, "sustainability_audit")

    def test_an_unknown_subtype_falls_back_to_the_weakest_claim_not_the_strongest(self):
        """If we cannot tell what it is, it must not be a certification."""
        ev = self._event("CE")
        ev.type = "ZZ"
        ev.business_type = ""
        ev.save()
        self.assertEqual(ev.business_type, "compliance")

    def test_the_field_no_longer_carries_a_certification_default(self):
        """The default itself was the bug — pin it so it cannot come back."""
        field = BusinessEvent._meta.get_field("business_type")
        self.assertNotEqual(
            field.default,
            "certification",
            "a default of 'certification' manufactures an unearned third-party claim on the "
            "consumer page for every event saved without an explicit business_type",
        )
