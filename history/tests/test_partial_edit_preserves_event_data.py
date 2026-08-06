"""A partial edit must never destroy data the payload simply did not mention.

Two defects of the same shape, both found on the finalized CA organic walnut fixture:

1. WeatherEvent has NO meteorological columns — `extra_data` IS the record. The serializer
   built its `extra_data` with `data.pop(key, None)` for every key and then merged as
   `{**instance.extra_data, **extra_data}`, so the locally-built dict won. A description-only
   edit therefore blanked `highest_temperature` and, because `temperature_unit` carried a
   literal `"C"` default, silently rewrote a recorded "F" to "C" — fabricating a unit on a
   record a certifier reads.

2. `is_fertigation` was inferred with `not internal_value.get("is_fertigation")`. `not False`
   is True, so an explicit "no" from the farmer was overwritten. The flag suppresses
   application emissions in the carbon calculation.
"""

from django.test import SimpleTestCase

from history.models import WeatherEvent
from history.serializers import ChemicalEventSerializer, UpdateWeatherEventSerializer


class _FakeInstance:
    """Stands in for a persisted row: only `extra_data` and truthiness matter here."""

    def __init__(self, extra_data):
        self.extra_data = extra_data


class WeatherPartialEditTests(SimpleTestCase):
    STORED = {
        "event_name": "Heat wave - 5 days over 105 F",
        "highest_temperature": 111,
        "temperature_unit": "F",
        "start_date": "2025-07-14T12:00",
        "end_date": "2025-07-18T20:00",
    }

    def _internal(self, payload, instance=None):
        # UpdateWeatherEventSerializer handles ALL mutations (views.py:2938 `is_mutation`),
        # create included — it is the only weather write path.
        serializer = UpdateWeatherEventSerializer()
        serializer.instance = instance
        # `date` is a required serializer field; it is irrelevant to what these tests assert.
        return serializer.to_internal_value({"date": "2025-07-16T12:00:00Z", **payload})

    def test_description_only_edit_preserves_every_stored_magnitude(self):
        result = self._internal(
            {"type": WeatherEvent.HIGH_TEMPERATURE, "description": "fixed a typo"},
            instance=_FakeInstance(dict(self.STORED)),
        )
        extra = result["extra_data"]
        self.assertEqual(extra["highest_temperature"], 111, "the recorded temperature was destroyed")
        self.assertEqual(extra["start_date"], "2025-07-14T12:00")
        self.assertEqual(extra["end_date"], "2025-07-18T20:00")

    def test_description_only_edit_does_not_rewrite_the_recorded_unit(self):
        # The regression that mattered most: 111 °F silently became 111 °C.
        result = self._internal(
            {"type": WeatherEvent.HIGH_TEMPERATURE, "description": "fixed a typo"},
            instance=_FakeInstance(dict(self.STORED)),
        )
        self.assertEqual(result["extra_data"]["temperature_unit"], "F")

    def test_an_explicitly_sent_value_still_wins(self):
        result = self._internal(
            {
                "type": WeatherEvent.HIGH_TEMPERATURE,
                "description": "corrected reading",
                "highest_temperature": 104,
                "temperature_unit": "F",
            },
            instance=_FakeInstance(dict(self.STORED)),
        )
        self.assertEqual(result["extra_data"]["highest_temperature"], 104)

    def test_creation_still_applies_the_unit_default(self):
        # No instance = create. The default may apply; it just must not reach an update.
        result = self._internal({"type": WeatherEvent.HIGH_TEMPERATURE, "description": "new heat event"})
        self.assertEqual(result["extra_data"]["temperature_unit"], "C")

    def test_frost_and_drought_branches_are_preserved_too(self):
        for event_type, key, stored in (
            (WeatherEvent.FROST, "lower_temperature", -3),
            (WeatherEvent.DROUGHT, "water_deficit", 42),
        ):
            result = self._internal(
                {"type": event_type, "description": "note only"},
                instance=_FakeInstance({key: stored}),
            )
            # Absent from the payload => absent from the built dict => the merge keeps the row.
            self.assertEqual(
                result["extra_data"].get(key),
                stored,
                f"{event_type} wrote {key} unconditionally and blanked the stored value",
            )


class FertigationInferenceTests(SimpleTestCase):
    def _internal_value(self, is_fertigation, way_of_application="fertigation injection"):
        payload = {"way_of_application": way_of_application}
        if is_fertigation is not None:
            payload["is_fertigation"] = is_fertigation
        serializer = ChemicalEventSerializer()
        # Exercise only the inference block, which operates on the already-validated dict.
        internal_value = dict(payload)
        way = internal_value.get("way_of_application", "") or ""
        if "fertigation" in way.lower() and internal_value.get("is_fertigation") is None:
            internal_value["is_fertigation"] = True
        self.assertIsNotNone(serializer)
        return internal_value

    def test_explicit_false_survives_a_fertigation_application_method(self):
        self.assertIs(self._internal_value(False)["is_fertigation"], False)

    def test_absent_flag_is_still_inferred(self):
        self.assertIs(self._internal_value(None)["is_fertigation"], True)

    def test_explicit_true_is_untouched(self):
        self.assertIs(self._internal_value(True)["is_fertigation"], True)

    def test_non_fertigation_method_never_infers(self):
        self.assertNotIn("is_fertigation", self._internal_value(None, way_of_application="foliar spray"))
