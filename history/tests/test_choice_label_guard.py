"""An unrecognised choice value must never print as a label in the certifier packet.

Django's `get_FOO_display()` returns the RAW VALUE when the stored string is not among the
field's choices, and Django enforces choices on neither `.save()` nor a DRF write. So a stray
value written by an importer, a management command or a hand edit reaches the packet as machine
text with no signal that a label went missing.

Third occurrence of this class in the export: `organic_approved = "True"` printed as a
§ 205.203(b) verification basis, an unrecognised OSP option printed as a chosen answer, and
`water_source = "district_canal"` printed in the Irrigation Records table.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import History, ProductionEvent
from history.services.audit_export_service import _choice_label
from product.models import Parcel, Product


class ChoiceLabelGuardTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Choice Co")
        est = Establishment.objects.create(name="Choice Farm", company=company)
        parcel = Parcel.objects.create(name="P", establishment=est, area=4.0)
        crop = CropType.objects.create(
            name="Apple",
            slug="apple-choice",
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
        history = History.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=60),
        )
        self.event = ProductionEvent.objects.create(
            history=history, type="IR", date=timezone.now(), description="Irrigation"
        )

    def test_a_valid_choice_renders_its_label(self):
        self.event.water_source = "irrigation_canal"
        self.assertEqual(_choice_label(self.event, "water_source"), "Irrigation Canal/District")

    def test_an_unrecognised_value_is_marked_not_printed_as_a_label(self):
        # `.update()` bypasses everything, exactly like an importer would.
        ProductionEvent.objects.filter(pk=self.event.pk).update(water_source="district_canal")
        self.event.refresh_from_db()
        out = _choice_label(self.event, "water_source")
        self.assertIn("district_canal", out, "the stored value must still be visible")
        self.assertIn("unrecognised", out, "and must be marked as not a real answer")

    def test_django_alone_would_have_leaked_it(self):
        """Pin the Django behaviour this guard exists for."""
        ProductionEvent.objects.filter(pk=self.event.pk).update(water_source="district_canal")
        self.event.refresh_from_db()
        self.assertEqual(self.event.get_water_source_display(), "district_canal")

    def test_blank_stays_blank_rather_than_becoming_a_flag(self):
        self.event.water_source = ""
        self.assertIsNone(_choice_label(self.event, "water_source"))

    def test_a_field_without_choices_is_passed_through(self):
        self.event.description = "Irrigation set"
        self.assertEqual(_choice_label(self.event, "description"), "Irrigation set")
