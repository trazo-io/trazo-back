"""A custom field on a soil event must survive the trip — and must never 500.

TWO DEFECTS, ONE SYMPTOM
------------------------
`SoilManagementTab.jsx` builds its payload with

    Object.entries(coreData).reduce((acc, [key, value]) => {
      acc[key] = value !== null && value !== undefined ? String(value) : value;
      ...

`String(value)` over EVERY key, to dodge Decimal serialization. `custom_fields` is part of
`coreData` (it is in the zod schema and written by `setValue`), and it is an ARRAY, so:

  * a populated list becomes the literal string "[object Object]"
  * an empty list becomes "" — falsy, so `validate_custom_fields` returns None and the field
    quietly disappears rather than erroring

The second defect is what turns the first into a 500 rather than a 400:
`validate_custom_fields` raises a bare `ValueError`, not `serializers.ValidationError`, and
`handle_custom_fields_input` does not wrap it. A ValueError escaping `to_internal_value()` is
not translated by DRF, so a malformed payload takes the whole request down with a server error
and a Sentry page, instead of telling the client what was wrong.

Both are fixed; this pins both. The serializer-level test is the one that matters — it is the
door every client comes through, including one we have not written yet.
"""

from django.test import TestCase
from django.utils import timezone

from rest_framework import serializers as drf_serializers

from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, Product
from users.models import User


class CustomFieldsBoundaryTests(TestCase):
    """The conversion happens at the SERIALIZER boundary, not in the validator.

    `validate_custom_fields` still raises plain ValueError by design — it is a pure function a
    management command can call without importing DRF. What must never happen is that error
    reaching the client as a 500, so the assertions below go through the serializer mixin that
    every request passes.
    """

    def _handler(self):
        # The WRITE serializer. `SoilManagementEventSerializer` is the read side and carries no
        # mixin — CustomFieldsMixin is on the eight Update* serializers, which is every path a
        # client can write through, so the boundary conversion covers all event types.
        from history.serializers import UpdateSoilManagementEventSerializer

        return UpdateSoilManagementEventSerializer()

    def test_a_stringified_array_is_a_client_error_not_a_server_error(self):
        """ "[object Object]" is exactly what a JS `String(array)` produces."""
        with self.assertRaises(drf_serializers.ValidationError):
            self._handler().handle_custom_fields_input({"custom_fields": "[object Object]"})

    def test_every_validator_failure_becomes_a_400(self):
        """All ten raise sites, reached through the door a client actually uses."""
        cases = [
            "[object Object]",  # not a list
            [{"label": "", "value": "x"}],  # empty label
            [{"label": "L" * 200, "value": "x"}],  # over-long label
            [{"label": "ok", "value": "x", "field_type": "bogus"}],  # bad type
            [{"label": "ok", "value": "x", "field_type": "link", "link_url": "ftp://x"}],
            [{"label": f"f{i}", "value": "x"} for i in range(11)],  # over the max
        ]
        for bad in cases:
            with self.assertRaises(
                drf_serializers.ValidationError,
                msg=f"{str(bad)[:40]} escaped as something other than a 400",
            ):
                self._handler().handle_custom_fields_input({"custom_fields": bad})

    def test_no_bare_valueerror_escapes(self):
        """The specific regression: a ValueError here is not translated by DRF, so it 500s."""
        try:
            self._handler().handle_custom_fields_input({"custom_fields": "[object Object]"})
        except drf_serializers.ValidationError:
            pass  # correct
        except ValueError:  # pragma: no cover
            self.fail("bare ValueError escapes to_internal_value() and returns a 500, not a 400")

    def test_a_real_list_still_validates(self):
        """The mirror: tightening the error path must not reject valid input."""
        out = self._handler().handle_custom_fields_input(
            {"custom_fields": [{"label": "Soil pH", "value": "7.2", "field_type": "text"}]}
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["label"], "Soil pH")

    def test_empty_stays_none(self):
        self.assertIsNone(self._handler().handle_custom_fields_input({"custom_fields": []}))
        self.assertIsNone(self._handler().handle_custom_fields_input({}))


class SoilEventCustomFieldsRoundTripTests(TestCase):
    """The field must reach the database, not merely fail to crash."""

    def setUp(self):
        self.user = User.objects.create_user(email="soilcf@test.com", password="x")
        company = Company.objects.create(name="Soil CF Co")
        establishment = Establishment.objects.create(name="SC1", company=company)
        parcel = Parcel.objects.create(name="Block 2", establishment=establishment, area=3)
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="Soil CF Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=False,
        )

    def test_a_custom_field_survives_into_extra_data(self):
        from history.serializers import UpdateSoilManagementEventSerializer

        payload = {
            "history": self.history.id,
            "type": "ST",
            "description": "Soil test",
            "date": timezone.now().isoformat(),
            "area_covered": "2.0",
            "area_unit": "acres",
            "custom_fields": [{"label": "Hardpan depth", "value": "18 in", "field_type": "text"}],
        }
        serializer = UpdateSoilManagementEventSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        event = serializer.save(created_by=self.user)
        stored = (event.extra_data or {}).get("custom_fields") or []
        self.assertEqual(
            [f.get("label") for f in stored],
            ["Hardpan depth"],
            "the custom field did not reach extra_data",
        )
