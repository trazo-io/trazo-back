"""A parcel's NAME is never its water source (2026-10-17).

The real crew note "Regamos River Block esta mañana, dos horas con el goteo" came back from the model
as `water_source: river_stream`. The crew said drip and named no source; "River" is the parcel. The
gate in `carbon/services/voice_water_source.py` keeps a source only if its words appear outside the
farm's own place names. Checked on the model path (mocked to return the bad answer, the failure being
guarded against), on `activity_fields`, and through the endpoint, which must feed the gate the
company's real parcel names from the database.
"""

import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from rest_framework.test import APITestCase

from carbon.services.ai_voice_processor import AIVoiceProcessor
from carbon.services.voice_water_source import gate, source_was_said

CREW_NOTE = "Regamos River Block esta mañana, dos horas con el goteo"


def _processor_returning(payload):
    client = MagicMock()
    message = MagicMock()
    message.content = json.dumps(payload)
    client.chat.completions.create.return_value.choices = [MagicMock(message=message)]
    processor = AIVoiceProcessor()
    processor.api_key = "test-key"
    processor.openai = client
    return processor


# What the model actually answered for CREW_NOTE in production, 2026-10-17.
MODEL_ANSWER = {
    "event_type": "irrigation",
    "description": "Irrigated River Block for two hours with drip",
    "confidence": 90,
    "water_source": "river_stream",
    "irrigation_method": "drip",
    "duration": 2,
}


class SourceWasSaidTests(SimpleTestCase):
    def test_a_parcel_name_is_not_a_river(self):
        self.assertFalse(source_was_said("river_stream", CREW_NOTE, ["River Block"]))

    def test_without_the_farms_names_the_word_is_still_there(self):
        # Proves the check READ the word: the same sentence passes when nobody says it is a place.
        self.assertTrue(source_was_said("river_stream", CREW_NOTE, []))

    def test_a_river_named_beside_the_place_still_counts(self):
        self.assertTrue(source_was_said("river_stream", "watered River Block from the river", ["River Block"]))

    def test_spanish_and_mixed_language_sources(self):
        self.assertTrue(source_was_said("irrigation_canal", "regamos el bloque 2 con agua del canal", []))
        self.assertTrue(source_was_said("well_groundwater", "watered the east block from the pozo", []))
        self.assertTrue(source_was_said("pond_reservoir", "regamos desde el tranque", []))

    def test_accents_and_case_do_not_hide_a_place_name(self):
        self.assertFalse(source_was_said("river_stream", "regamos RÍO VIEJO hoy", ["Rio Viejo"]))

    def test_the_longest_name_is_removed_first(self):
        self.assertFalse(
            source_was_said("pond_reservoir", "irrigated Pond Field East", ["Pond Field", "Pond Field East"])
        )

    def test_a_little_is_not_a_well(self):
        # Portuguese "poço" folds to "poco", which is Spanish for "a little".
        self.assertFalse(source_was_said("well_groundwater", "regamos un poco el bloque 3", []))

    def test_other_is_never_offered_by_the_machine(self):
        self.assertFalse(source_was_said("other", "regamos con agua de otra fuente", []))


class GateTests(SimpleTestCase):
    def test_the_top_level_value_is_nulled(self):
        result = gate({"water_source": "river_stream", "irrigation_method": "drip"}, CREW_NOTE, ["River Block"])
        self.assertIsNone(result["water_source"])
        self.assertEqual(result["irrigation_method"], "drip")

    def test_the_activity_fields_value_is_dropped(self):
        result = gate({"activity_fields": {"water_source": "river_stream", "duration": 2}}, CREW_NOTE, ["River Block"])
        self.assertNotIn("water_source", result["activity_fields"])
        self.assertEqual(result["activity_fields"]["duration"], 2)

    def test_a_source_that_was_said_survives(self):
        result = gate({"water_source": "irrigation_canal"}, "regamos con agua del canal", ["River Block"])
        self.assertEqual(result["water_source"], "irrigation_canal")


@patch("carbon.services.ai_voice_processor.OPENAI_AVAILABLE", True)
class OnTheModelPathTests(SimpleTestCase):
    def test_the_crew_note_offers_drip_and_no_source(self):
        result = _processor_returning(MODEL_ANSWER).process_voice_input(
            CREW_NOTE, "apple", "es-419", place_names=["River Block", "Calapooia Bend Farm"]
        )
        self.assertIsNone(result["water_source"])
        self.assertEqual(result["irrigation_method"], "drip")

    def test_block_options_the_form_sent_count_as_place_names(self):
        requested = [{"name": "block_id", "label": "Block", "type": "enum", "options": ["River Block"]}]
        result = _processor_returning(MODEL_ANSWER).process_voice_input(
            CREW_NOTE, "apple", "es-419", requested_fields=requested
        )
        self.assertIsNone(result["water_source"])

    def test_the_prompt_says_a_name_is_not_a_source(self):
        for language in ("en-US", "es-419", "pt-BR"):
            self.assertIn("River Block", AIVoiceProcessor()._get_system_prompt(language))


class TheEndpointUsesTheFarmsOwnNames(APITestCase):
    def test_the_companys_parcel_and_farm_names_reach_the_gate(self):
        from django.contrib.auth import get_user_model

        from company.models import Company, Establishment
        from product.models import Parcel

        user = get_user_model().objects.create_user(email="ws@t.test", password="pw-for-tests-only")
        company = Company.objects.create(name="Water Co")
        user.companies.add(company)
        farm = Establishment.objects.create(name="Calapooia Bend Farm", company=company, state="OR")
        Parcel.objects.create(name="River Block", establishment=farm, area=2.0)
        other = Company.objects.create(name="Elsewhere Co")
        Parcel.objects.create(
            name="Creek Orchard", establishment=Establishment.objects.create(name="Far", company=other), area=1.0
        )
        self.client.force_authenticate(user=user)

        with (
            patch("company.models.Company.has_feature", return_value=True),
            patch("users.models.User.get_active_company", return_value=company),
            patch(
                "carbon.services.ai_voice_processor.process_voice_with_ai", return_value={"water_source": None}
            ) as parse,
        ):
            res = self.client.post(
                "/api/carbon/process-voice-event/",
                {"transcript": CREW_NOTE, "crop_type": "apple", "language": "es-419"},
                format="json",
            )

        self.assertEqual(res.status_code, 200, res.data)
        place_names = parse.call_args.args[5]
        self.assertIn("River Block", place_names)
        self.assertIn("Calapooia Bend Farm", place_names)
        # Another company's naming is not this farm's naming.
        self.assertNotIn("Creek Orchard", place_names)
