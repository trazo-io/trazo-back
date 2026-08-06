"""Server-side guards for contact/postal fields.

Regression pins for the 2026-07-31 QA finding: both layers accepted anything that
fit the column, so `contact_phone = "call me maybe"` and `zip_code = "ABCDE"` were
stored and carried onto the OSP and the certifier audit packet.
"""

from django.core.exceptions import ValidationError
from django.test import TestCase

from common.validators import normalize_us_phone_digits, validate_us_phone, validate_us_zip


class ValidateUsPhoneTests(TestCase):
    def test_accepts_common_grower_formats(self):
        for value in [
            "(559) 555-0142",
            "559-555-0142",
            "559.555.0142",
            "5595550142",
            "559 555 0142",
            "+1-559-555-0987",  # the format used by the seed commands
            "+1 (559) 555-0142",
            "1-559-555-0142",
        ]:
            with self.subTest(value=value):
                validate_us_phone(value)  # must not raise

    def test_rejects_free_text(self):
        for value in ["call me maybe", "ask for Jose", "n/a", "-"]:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_us_phone(value)

    def test_rejects_wrong_digit_count(self):
        for value in ["12345", "555-0142", "5595550142999", "1"]:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_us_phone(value)

    def test_rejects_undialable_placeholders(self):
        # NANP forbids 0/1 as the first digit of the area or exchange code.
        for value in ["000-000-0000", "111-111-1111", "059-555-0142", "559-155-0142"]:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_us_phone(value)

    def test_blank_and_none_pass(self):
        # The model fields are optional; the validator must not make them required.
        validate_us_phone("")
        validate_us_phone(None)

    def test_normalizes_and_strips_country_code(self):
        self.assertEqual(normalize_us_phone_digits("+1 (559) 555-0142"), "5595550142")
        self.assertEqual(normalize_us_phone_digits("(559) 555-0142"), "5595550142")
        self.assertEqual(normalize_us_phone_digits(None), "")


class ValidateUsZipTests(TestCase):
    def test_accepts_zip_and_zip_plus_four(self):
        for value in ["93265", "93265-1234", "  93265  "]:
            with self.subTest(value=value):
                validate_us_zip(value)  # must not raise

    def test_rejects_non_numeric_and_wrong_length(self):
        for value in ["ABCDE", "9326", "932655", "93265-12", "93265 1234"]:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_us_zip(value)

    def test_blank_and_none_pass(self):
        validate_us_zip("")
        validate_us_zip(None)


class SerializerWiringTests(TestCase):
    """Pin that the mixin reaches the serializers the viewsets actually write with:
    CreateCompanySerializer (create), RetrieveCompanySerializer (update),
    UpdateEstablishmentSerializer, CreateParcelSerializer."""

    def test_company_create_rejects_garbage(self):
        from company.serializers import CreateCompanySerializer

        serializer = CreateCompanySerializer(
            data={
                "name": "Tule River Orchards LLC",
                "contact_email": "jose@example.com",
                "contact_phone": "call me maybe",
                "zip_code": "ABCDE",
                "state": "CA",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("contact_phone", serializer.errors)
        self.assertIn("zip_code", serializer.errors)

    def test_company_create_accepts_real_values(self):
        from company.serializers import CreateCompanySerializer

        serializer = CreateCompanySerializer(
            data={
                "name": "Tule River Orchards LLC",
                "contact_email": "jose@example.com",
                "contact_phone": "(559) 555-0142",
                "zip_code": "93265",
                "state": "CA",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_establishment_update_serializer_is_covered(self):
        from company.serializers import UpdateEstablishmentSerializer

        serializer = UpdateEstablishmentSerializer(
            data={"name": "Home Ranch", "phone": "nope", "zip_code": "nope"},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("phone", serializer.errors)
        self.assertIn("zip_code", serializer.errors)

    def test_parcel_serializer_is_covered(self):
        from product.serializers import CreateParcelSerializer

        serializer = CreateParcelSerializer(
            data={"name": "Block 1", "area": 17.2, "contact_phone": "call me maybe"},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("contact_phone", serializer.errors)


class LegacyValueGrandfatheringTests(TestCase):
    """44 rows predate this validation (phone "213213", zip "13"), and the company
    edit modal echoes stored values back on save. An unchanged bad value must not
    block an edit to some other field — but a NEW bad value still must."""

    def setUp(self):
        from company.models import Company

        self.company = Company.objects.create(
            name="Legacy Co",
            contact_phone="213213",  # invalid, pre-existing
            zip_code="13",  # invalid, pre-existing
        )

    def _update(self, data):
        from company.serializers import RetrieveCompanySerializer

        return RetrieveCompanySerializer(self.company, data=data, partial=True)

    def test_editing_another_field_does_not_trip_on_legacy_values(self):
        serializer = self._update(
            {
                "name": "Legacy Co Renamed",
                "contact_phone": "213213",  # echoed back unchanged
                "zip_code": "13",  # echoed back unchanged
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_omitting_the_fields_entirely_is_fine(self):
        serializer = self._update({"name": "Legacy Co Renamed"})

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_changing_to_a_new_bad_value_is_still_rejected(self):
        serializer = self._update({"contact_phone": "call me maybe"})

        self.assertFalse(serializer.is_valid())
        self.assertIn("contact_phone", serializer.errors)

    def test_changing_to_a_good_value_is_accepted(self):
        serializer = self._update({"contact_phone": "(559) 555-0142", "zip_code": "93265"})

        self.assertTrue(serializer.is_valid(), serializer.errors)
