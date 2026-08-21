"""A chemical event's numeric twins must be derived from what the form actually sends.

`ChemicalEvent` carries one fact in two columns: `volume` / `area` (legacy CharFields, what
the event wizard posts) and `volume_numeric` / `area_numeric` (what every COMPUTATION reads —
the certifier packet's rate-per-area, the audit CSV, the CA PUR export, record completeness).

Nothing derived the second pair on write. The seeded demo events set them directly, so the
packet printed a correct "oz/acre" rate for demo data and nothing at all for a spray a farmer
had entered through the wizard — the two looked like different features rather than a bug.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.serializers import UpdateChemicalEventSerializer
from product.models import Parcel, Product
from users.models import User


class ChemicalNumericTwinTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="twin@t.test", password="x")
        company = Company.objects.create(name="Twin Co")
        est = Establishment.objects.create(name="Twin Farm", company=company)
        parcel = Parcel.objects.create(name="P", establishment=est, area=1.0)
        crop = CropType.objects.create(
            name="Walnut",
            slug="walnut-twin",
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
            start_date=timezone.now() - timedelta(days=100),
        )

    def _create(self, payload):
        base = {
            "history": self.history.pk,
            "type": "FU",
            "date": timezone.now().isoformat(),
            "commercial_name": "Kocide 3000-O",
            "description": "Copper fungicide at bloom",
        }
        base.update(payload)
        serializer = UpdateChemicalEventSerializer(data=base)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save()

    def test_the_wizards_payload_shape_populates_both_twins(self):
        """volume_applied / area_treated + units — exactly what ChemicalTab posts."""
        event = self._create({"volume_applied": "8", "volume_unit": "oz", "area_treated": "12.5", "area_unit": "acres"})
        event.refresh_from_db()
        self.assertEqual(float(event.volume_numeric), 8.0)
        self.assertEqual(float(event.area_numeric), 12.5)
        self.assertEqual(event.volume_unit, "oz")
        self.assertEqual(event.area_unit, "acres")

    def test_an_explicit_numeric_value_is_not_overwritten(self):
        """Derivation fills a GAP. A caller that knows the number still wins."""
        event = self._create(
            {
                "volume_applied": "8",
                "volume_numeric": "9.25",
                "volume_unit": "oz",
                "area_treated": "12.5",
                "area_unit": "acres",
            }
        )
        event.refresh_from_db()
        self.assertEqual(float(event.volume_numeric), 9.25)

    def test_a_combined_string_still_parses(self):
        event = self._create({"volume_applied": "400 kg/ha", "area_treated": "10 ha"})
        event.refresh_from_db()
        self.assertEqual(float(event.volume_numeric), 400.0)
        self.assertEqual(float(event.area_numeric), 10.0)

    def test_no_value_leaves_the_twin_null_rather_than_zero(self):
        """A blank is not a zero — a 0-acre spray would read as a real measurement."""
        event = self._create({"commercial_name": "Serenade ASO"})
        event.refresh_from_db()
        self.assertIsNone(event.volume_numeric)
        self.assertIsNone(event.area_numeric)
