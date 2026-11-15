"""A cultural-control pest event must name the practice — on the WRITE path, not just in clean().

`PestManagementEvent.clean()` has required `cultural_practice` on a CU event since §E-4. DRF
never calls `full_clean()` on `objects.create()` / `update()`, so no write path ever ran it,
and a live rehearsal saved a CU event with a blank practice. Two things then went wrong on the
certifier packet at once: the Preventive Cultural Practices table printed "Practice: —" under
a § 205.206(a) heading, and the § 205.206(a) warning pointed the grower at `ipm_strategy`, a
different field.

§ 205.206(a) is documented by the SPECIFIC practice. "We did cultural control" supports nothing
at inspection; "December mummy shake" is the record that later justifies, under § 205.206(e),
applying a substance when the practice proved insufficient.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import PestManagementEvent, Production
from history.serializers import UpdatePestManagementEventSerializer
from product.models import Parcel, Product


class CulturalPracticeRequiredTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="CU Co")
        est = Establishment.objects.create(name="CU Farm", company=company)
        parcel = Parcel.objects.create(name="P", establishment=est, area=1.0)
        crop = CropType.objects.create(
            name="Walnut",
            slug="walnut-cu",
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
        self.history = Production.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=100),
        )

    def _payload(self, **over):
        base = {
            "history": self.history.pk,
            "date": timezone.now().isoformat(),
            "description": "Winter sanitation round",
            "type": PestManagementEvent.CULTURAL_CONTROL,
            "pest_species": "Cydia pomonella",
        }
        base.update(over)
        return base

    def test_a_cultural_control_event_without_a_practice_is_refused(self):
        serializer = UpdatePestManagementEventSerializer(data=self._payload())
        self.assertFalse(serializer.is_valid())
        self.assertIn("cultural_practice", serializer.errors)

    def test_naming_the_practice_lets_it_through(self):
        serializer = UpdatePestManagementEventSerializer(data=self._payload(cultural_practice="mummy_removal"))
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_a_monitoring_event_is_untouched(self):
        """The rule belongs to cultural control, not to every pest record."""
        serializer = UpdatePestManagementEventSerializer(data=self._payload(type="TM"))
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_a_partial_update_reads_the_practice_off_the_stored_row(self):
        event = PestManagementEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Winter sanitation round",
            type=PestManagementEvent.CULTURAL_CONTROL,
            cultural_practice="sanitation_shake",
        )
        serializer = UpdatePestManagementEventSerializer(event, data={"pest_species": "Cydia pomonella"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
