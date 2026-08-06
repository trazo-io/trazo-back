"""Server-side guards and canonicalization for the `state` field.

Regression pins for the US-expansion audit: `state` was a free-text CharField
with no choices, so 35 of 105 live rows held "California" rather than "CA" and
every regional lookup (irrigation depth, precipitation, USDA regional factors,
the CA-only compliance surfaces) missed on them. Three separate carbon call
sites papered over it by falling back to "CA", which meant a Florida farm was
costed as Californian.
"""

from django.core.exceptions import ValidationError
from django.test import TestCase

from common.validators import validate_us_state


class ValidateUsStateTests(TestCase):
    def test_accepts_codes_in_any_case(self):
        for value in ["CA", "ca", "  fl  ", "NY"]:
            with self.subTest(value=value):
                validate_us_state(value)  # must not raise

    def test_accepts_full_names(self):
        for value in ["California", "florida", "New York", "District of Columbia"]:
            with self.subTest(value=value):
                validate_us_state(value)

    def test_rejects_unresolvable(self):
        for value in ["Test State", "sad", "XX", "Calif", "Baja California"]:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_us_state(value)

    def test_blank_and_none_pass(self):
        # The model field is optional; the validator must not make it required.
        validate_us_state("")
        validate_us_state(None)


class SerializerWiringTests(TestCase):
    """Pin that the mixin reaches the serializers the viewsets actually write with."""

    def test_company_create_rejects_unresolvable_state(self):
        from company.serializers import CreateCompanySerializer

        serializer = CreateCompanySerializer(data={"name": "Tule River Orchards LLC", "state": "Test State"})

        self.assertFalse(serializer.is_valid())
        self.assertIn("state", serializer.errors)

    def test_company_create_canonicalizes_full_name(self):
        from company.serializers import CreateCompanySerializer

        serializer = CreateCompanySerializer(data={"name": "Tule River Orchards LLC", "state": "California"})

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["state"], "CA")

    def test_establishment_update_canonicalizes_and_rejects(self):
        from company.serializers import UpdateEstablishmentSerializer

        good = UpdateEstablishmentSerializer(data={"name": "Home Ranch", "state": "florida"}, partial=True)
        self.assertTrue(good.is_valid(), good.errors)
        self.assertEqual(good.validated_data["state"], "FL")

        bad = UpdateEstablishmentSerializer(data={"name": "Home Ranch", "state": "nope"}, partial=True)
        self.assertFalse(bad.is_valid())
        self.assertIn("state", bad.errors)


class LegacyValueGrandfatheringTests(TestCase):
    """Some stored states are not US states at all — "Salto" is a Uruguayan
    department on a real row. The edit modal echoes every stored value back on
    save, so an unchanged unresolvable value must not block an edit to another
    field, while a NEW unresolvable value still must be rejected."""

    def setUp(self):
        from company.models import Company

        self.company = Company.objects.create(name="Guarino", state="Salto")

    def _update(self, data):
        from company.serializers import RetrieveCompanySerializer

        return RetrieveCompanySerializer(self.company, data=data, partial=True)

    def test_editing_another_field_does_not_trip_on_the_legacy_state(self):
        serializer = self._update({"name": "Guarino Renamed", "state": "Salto"})

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_omitting_the_field_entirely_is_fine(self):
        serializer = self._update({"name": "Guarino Renamed"})

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_changing_to_a_new_unresolvable_value_is_still_rejected(self):
        serializer = self._update({"state": "Montevideo"})

        self.assertFalse(serializer.is_valid())
        self.assertIn("state", serializer.errors)

    def test_changing_to_a_real_state_is_accepted_and_canonicalized(self):
        serializer = self._update({"state": "Oregon"})

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["state"], "OR")
