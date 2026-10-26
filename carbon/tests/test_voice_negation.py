"""A crew or farmer message that denies what it describes never becomes an offer (OSP audit T29).

Oscar's rule (2026-10-01): a message that negates everything, or negates some actions or parcels and
affirms others, goes to MANUAL REVIEW with no values offered. Neither is read as "nothing happened".
Checked on both extraction paths: the model (mocked to return amounts anyway, the failure being
guarded against) and the keyword fallback.
"""

import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from carbon.services.ai_voice_processor import AIVoiceProcessor
from carbon.services.voice_negation import ALL, MIXED, NONE, classify


class ClassifyTests(SimpleTestCase):
    def test_all_negated(self):
        for text in (
            "didn't spray today",
            "we did not apply anything on block 3",
            "no apliqué nada hoy",
            "no se aplicó nada en el bloque norte",
        ):
            self.assertEqual(classify(text), ALL, text)
        self.assertEqual(classify("não apliquei nada hoje", "pt-BR"), ALL)

    def test_mixed_action(self):
        for text in (
            "sprayed row 1, didn't spray row 2",
            "regamos el bloque A pero no aplicamos fertilizante",
        ):
            self.assertEqual(classify(text), MIXED, text)
        self.assertEqual(classify("irrigamos o talhão 1 mas não adubamos", "pt-BR"), MIXED)

    def test_mixed_parcel(self):
        for text in (
            "applied compost on block A but not on block B",
            "aplicamos compost en el A pero no en el B",
        ):
            self.assertEqual(classify(text), MIXED, text)
        self.assertEqual(classify("aplicamos no talhão 1 e não no talhão 2", "pt-BR"), MIXED)

    def test_portuguese_no_is_in_the_not_a_negation(self):
        self.assertEqual(classify("aplicamos composto no talhão 1", "pt-BR"), NONE)

    def test_a_reason_after_a_denial_is_not_an_affirmed_action(self):
        # Astra activity-capture audit AC-07 (2026-10-26): the comma split made "too windy" an
        # affirmed clause, so a plain no-spray note read as "some things were done".
        for text in (
            "Did not spray today, too windy",
            "No fumigamos hoy, mucho viento",
            "didn't spray, rain coming",
            "no regamos, el suelo estaba mojado",
        ):
            self.assertEqual(classify(text), ALL, text)

    def test_an_action_or_a_number_after_a_denial_is_still_mixed(self):
        for text in (
            "Did not spray row 2, sprayed row 1",
            "No fumigamos el bloque A, aplicamos cobre en el B",
            "didn't spray the north block, row 4 got 2 gallons",
        ):
            self.assertEqual(classify(text), MIXED, text)

    def test_an_unrecognised_clause_after_a_denial_stays_mixed(self):
        # Review on #239: only a plain reason flips MIXED to ALL. A crop noun ("apples",
        # "cultivo") or an elliptical second location ("si en el B") is not a recognised reason,
        # so it keeps the conservative MIXED rather than claiming the note denies everything.
        for text in (
            "Did not spray today, apples still wet",
            "no regamos hoy, el cultivo estaba mojado",
            "no aplicamos en el bloque a, si en el b",
            "didn't spray the north block, just the south one",
        ):
            self.assertEqual(classify(text), MIXED, text)

    def test_plain_reports_are_not_negated(self):
        for text in ("irrigated block 4 for two hours", "regamos el bloque 4 esta mañana, dos horas"):
            self.assertEqual(classify(text), NONE, text)
        self.assertEqual(classify("colhemos ontem no talhão 3", "pt-BR"), NONE)


def _processor_returning(payload):
    client = MagicMock()
    message = MagicMock()
    message.content = json.dumps(payload)
    client.chat.completions.create.return_value.choices = [MagicMock(message=message)]
    processor = AIVoiceProcessor()
    processor.api_key = "test-key"
    processor.openai = client
    return processor


MODEL_ANSWER = {
    "event_type": "fertilization",
    "confidence": 90,
    "detected_amounts": [{"value": 200, "unit": "lbs", "category": "weight"}],
    "detected_products": ["feather meal"],
    "commercial_name": "Feather Meal",
    "area_covered": {"value": 2, "unit": "acres"},
    "activity_fields": {"amendment_amount": "200 lb"},
    "description": "Applied feather meal",
}


@patch("carbon.services.ai_voice_processor.OPENAI_AVAILABLE", True)
class GuardOnTheModelPathTests(SimpleTestCase):
    def test_a_denial_offers_nothing_even_when_the_model_answers(self):
        result = _processor_returning(MODEL_ANSWER).process_voice_input("no apliqué nada hoy", "apples", "es-419")
        self.assertEqual(result.get("negation"), ALL)
        self.assertTrue(result.get("manual_review"))
        self.assertEqual(result["detected_amounts"], [])
        self.assertEqual(result["detected_products"], [])
        self.assertIsNone(result["commercial_name"])
        self.assertEqual(result["activity_fields"], {})
        self.assertTrue(result["type_withheld"])

    def test_a_mixed_message_is_manual_review_not_nothing_happened(self):
        result = _processor_returning(MODEL_ANSWER).process_voice_input(
            "applied compost on block A but not on block B", "apples", "en-US"
        )
        self.assertEqual(result.get("negation"), MIXED)
        self.assertTrue(result.get("manual_review"))
        self.assertIn("some things were done and some were not", result["manual_review_reason"])
        self.assertEqual(result["detected_amounts"], [])

    def test_a_plain_report_keeps_its_offer(self):
        result = _processor_returning(MODEL_ANSWER).process_voice_input(
            "applied feather meal on block A", "apples", "en-US"
        )
        self.assertEqual(result.get("negation"), NONE)
        self.assertFalse(result.get("manual_review"))
        self.assertTrue(result["detected_amounts"])

    def test_the_prompt_tells_the_model_about_negation(self):
        self.assertIn("NEGATION", AIVoiceProcessor()._get_system_prompt("es-419"))


class GuardOnTheFallbackPathTests(SimpleTestCase):
    def test_the_keyword_fallback_is_guarded_too(self):
        processor = AIVoiceProcessor()
        processor.api_key = None
        result = processor.process_voice_input("didn't spray 2 gallons of copper today", "apples", "en-US")
        self.assertEqual(result.get("negation"), ALL)
        self.assertEqual(result["detected_amounts"], [])


@patch("carbon.services.ai_voice_processor.OPENAI_AVAILABLE", True)
class ReasonClauseStillWithholdsTests(SimpleTestCase):
    def test_a_denial_with_a_reason_offers_nothing(self):
        # AC-07: the banner changes from mixed to all; the guard still withholds every value.
        result = _processor_returning(MODEL_ANSWER).process_voice_input(
            "Did not spray today, too windy", "apples", "en-US"
        )
        self.assertEqual(result.get("negation"), ALL)
        self.assertTrue(result.get("manual_review"))
        self.assertIn("denies what it describes", result["manual_review_reason"])
        self.assertEqual(result["detected_amounts"], [])
        self.assertEqual(result["detected_products"], [])
        self.assertIsNone(result["commercial_name"])
        self.assertEqual(result["activity_fields"], {})
        self.assertEqual(result["description"], "")
        self.assertTrue(result["type_withheld"])


class ReviewOfBack88Tests(SimpleTestCase):
    def test_a_typographic_apostrophe_is_still_a_negation(self):
        self.assertEqual(classify("didn’t spray the north block"), ALL)
        self.assertEqual(classify("we sprayed block A but didn’t spray block B"), MIXED)

    def test_porem_splits_a_portuguese_clause(self):
        self.assertEqual(classify("aplicamos no talhão 1 porém não no talhão 2", "pt-BR"), MIXED)

    @patch("carbon.services.ai_voice_processor.OPENAI_AVAILABLE", True)
    def test_a_negated_message_keeps_no_description_or_type(self):
        result = _processor_returning(MODEL_ANSWER).process_voice_input("no apliqué nada hoy", "apples", "es-419")
        self.assertEqual(result.get("description"), "")
        self.assertEqual(result.get("type"), "")
