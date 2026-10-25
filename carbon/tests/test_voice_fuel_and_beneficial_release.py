"""Spoken fuel lands in `fuel_amount`; a beneficial release is not pollination (2026-10-25).

MEASURED by pasting notes into the activity wizard against the live parser (gpt-4o-mini):

  * "Mowed the cover crop between rows on both blocks, flail mower, 3 hours each, 5 gallons of
    diesel." -> fuel_amount null, the 5 gallons only in detected_amounts as category "fuel".
  * A fungicide note "...used 6 gallons of diesel." -> fuel_amount null, the 6 gallons as "volume".
  * "Released ladybugs on both blocks this morning, 2000 per acre" on a pest Beneficial Release ->
    event_type "pollination", and the 2000 came back as "lbs" on one run and as a count on the next.

The client now reads fuel from the words (trazo-app `spokenFuelAmount`), so the prompt is the
first line, not the only one. What CI can hold without spending a model call: every localised
prompt carries the three rules, the activity the farmer picked reaches the prompt, and the keyword
fallback (no OpenAI) answers a release correctly. The live behaviour is measured by
`audit_crew_messages` against the corpus entries added with this change.
"""

import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from carbon.services.ai_voice_processor import ACTIVITY_EXTRACTION_HINTS, AIVoiceProcessor

LANGUAGES = ("en-US", "es-419", "pt-BR")
RELEASE_NOTE = "Released ladybugs on both blocks this morning, 2000 per acre"


def _processor_returning(payload):
    client = MagicMock()
    message = MagicMock()
    message.content = json.dumps(payload)
    client.chat.completions.create.return_value.choices = [MagicMock(message=message)]
    processor = AIVoiceProcessor()
    processor.api_key = "test-key"
    processor.openai = client
    return processor, client


class FuelPromptTests(SimpleTestCase):
    def test_each_english_example_extracts_the_number_it_quotes(self):
        # Review of back #234: "used 6 gallons of diesel" was paired with {"value": 5}.
        prompt = AIVoiceProcessor()._get_system_prompt("en-US")
        self.assertIn('"used 6 gallons of diesel" on a spray is fuel_amount {"value": 6', prompt)
        self.assertNotIn('"used 6 gallons of diesel" on a spray is fuel_amount {"value": 5', prompt)

    def test_every_prompt_routes_diesel_to_fuel_amount(self):
        words = {"en-US": "diesel", "es-419": "diésel", "pt-BR": "diesel"}
        for language in LANGUAGES:
            prompt = AIVoiceProcessor()._get_system_prompt(language)
            line = next(row for row in prompt.splitlines() if row.startswith("- fuel_amount:"))
            self.assertIn(words[language], line, f"{language}: fuel_amount does not name diesel")

    def test_every_prompt_says_water_is_never_fuel(self):
        water = {"en-US": "100 gallons of water", "es-419": "100 galones de agua", "pt-BR": "100 galões de água"}
        for language in LANGUAGES:
            prompt = AIVoiceProcessor()._get_system_prompt(language)
            line = next(row for row in prompt.splitlines() if row.startswith("- fuel_amount:"))
            self.assertIn(water[language], line, f"{language}: tank water could be read as fuel")


class BeneficialReleasePromptTests(SimpleTestCase):
    def test_the_classifier_can_answer_beneficial_release_in_every_language(self):
        for language in LANGUAGES:
            prompt = AIVoiceProcessor()._get_system_prompt(language)
            enum_line = next(row for row in prompt.splitlines() if row.startswith("- event_type:"))
            self.assertIn("beneficial_release", enum_line.split("]")[0], f"{language}: not in the enum")

    def test_every_prompt_says_a_release_is_not_pollination(self):
        rule = {
            "en-US": "IS PEST MANAGEMENT, NOT POLLINATION",
            "es-419": "ES MANEJO DE PLAGAS, NO POLINIZACIÓN",
            "pt-BR": "É MANEJO DE PRAGAS, NÃO POLINIZAÇÃO",
        }
        for language in LANGUAGES:
            self.assertIn(rule[language], AIVoiceProcessor()._get_system_prompt(language))

    def test_every_prompt_says_an_insect_count_is_never_a_weight(self):
        rule = {
            "en-US": "A COUNT OF INSECTS IS NEVER A WEIGHT",
            "es-419": "UN CONTEO DE INSECTOS NUNCA ES UN PESO",
            "pt-BR": "UMA CONTAGEM DE INSETOS NUNCA É UM PESO",
        }
        for language in LANGUAGES:
            self.assertIn(rule[language], AIVoiceProcessor()._get_system_prompt(language))

    def test_the_picked_activity_has_a_hint_so_the_view_keeps_it(self):
        # carbon/views.py drops any known_activity that is not a key here. Without it the
        # Beneficial Release tile sends no context and the model guesses from "insects on a block".
        self.assertIn("beneficial_release", ACTIVITY_EXTRACTION_HINTS)
        self.assertIn("never a weight", ACTIVITY_EXTRACTION_HINTS["beneficial_release"])


@patch("carbon.services.ai_voice_processor.OPENAI_AVAILABLE", True)
class OnTheModelPathTests(SimpleTestCase):
    def test_the_picked_release_reaches_the_prompt(self):
        processor, client = _processor_returning(
            {"event_type": "beneficial_release", "description": "Released ladybugs", "confidence": 90}
        )
        result = processor.process_voice_input(RELEASE_NOTE, "walnut", "en-US", known_activity="beneficial_release")
        self.assertEqual(result["type"], "beneficial_release")
        sent = json.dumps(client.chat.completions.create.call_args.kwargs["messages"])
        self.assertIn('ALREADY chosen this activity in the form: \\"beneficial_release\\"', sent)
        self.assertIn("ladybugs, lacewings", sent)

    def test_a_fuel_amount_the_model_answers_reaches_the_client(self):
        processor, _ = _processor_returning(
            {
                "event_type": "mowing",
                "description": "Mowed cover crop",
                "confidence": 90,
                "detected_amounts": [{"value": 3, "unit": "hours", "category": "time"}],
                "fuel_amount": {"value": 5, "unit": "gallons"},
            }
        )
        result = processor.process_voice_input(
            "Mowed the cover crop between rows on both blocks, flail mower, 3 hours each, 5 gallons of diesel.",
            "walnut",
            "en-US",
            known_activity="mowing",
        )
        self.assertEqual(result["fuel_amount"], {"value": 5, "unit": "gallons"})


@patch("carbon.services.ai_voice_processor.OPENAI_AVAILABLE", False)
class KeywordFallbackTests(SimpleTestCase):
    def test_a_release_is_not_filed_as_pollination_without_the_model(self):
        result = AIVoiceProcessor().process_voice_input(RELEASE_NOTE, "walnut", "en-US")
        self.assertEqual(result["type"], "beneficial_release")

    def test_spanish_release(self):
        result = AIVoiceProcessor().process_voice_input(
            "Soltamos mariquitas en los dos bloques, 2000 por acre", "nogal", "es-419"
        )
        self.assertEqual(result["type"], "beneficial_release")

    def test_a_release_naming_its_target_pest_beats_pesticide(self):
        # Review of back #234: plural-only es/pt keywords scored 1 and tied with pesticide's
        # "plaga"/"praga", and a tie goes to whichever type the dict lists first.
        for text, language in (
            ("Soltamos crisopas contra la plaga de pulgón", "es-419"),
            ("Soltamos joaninhas contra a praga de pulgão", "pt-BR"),
        ):
            result = AIVoiceProcessor().process_voice_input(text, "nogal", language)
            self.assertEqual(result["type"], "beneficial_release", text)

    def test_hives_are_still_pollination(self):
        result = AIVoiceProcessor().process_voice_input("Put 24 hives in the almond block today", "almond", "en-US")
        self.assertEqual(result["type"], "pollination")
