"""The voice suggestion must not carry a date the machine invented (2026-09-16).

Both return paths of `AIVoiceProcessor` used to stamp `time.strftime("%Y-%m-%d")`:
`_structure_ai_response` (the LLM path) and `_fallback_processing` (the keyword path). That is
the SERVER's date, not the farm's -- Django pushes `settings.TIME_ZONE` into the process and
calls `time.tzset()`, and `TIME_ZONE = "UTC"`, so a 17:30 US/Pacific utterance was stamped with
tomorrow. Trazo's growers are in Washington and California, i.e. every evening entry was wrong.

It was LATENT, not live: `voiceDataMapper.ts` never writes a `date` override, so
`overriddenFields` could not carry one, and the render gate has no `date` form field either. The
wizard takes its own date from `nowLocalDateTimeInput()`, the farmer's browser clock. Nothing
read the server's value.

Latent is not safe. `cleanEventData` in the activity wizard is a passthrough with no allowlist,
so the first time anyone spreads this payload into the form -- which is exactly what a
transcript-seeding or messaging-intake path invites -- an invented day lands on a real column.
The date drives pre-harvest intervals, the CA PUR application date (box 17/18) and the
7 CFR 205.103(b)(2) trace-back, and a record dated a day nobody worked is the
backdated-glyphosate class all over again.

So the contract is the absence of the key, and absence is exactly the kind of thing that comes
back silently. These tests are the tripwire.

NOTE: this module must stay in the backend CI allowlist (`.github/workflows/ci.yml`). CI names each
test module explicitly; a module that is not named never runs, and a guard that never runs is
decoration.
"""

from django.test import SimpleTestCase

from carbon.services.ai_voice_processor import AIVoiceProcessor


class VoiceSuggestionCarriesNoInventedDate(SimpleTestCase):
    """Neither return path may emit a `date`. Asserted against the real functions, not a mock."""

    def setUp(self):
        self.processor = AIVoiceProcessor()

    def test_the_llm_path_emits_no_date(self):
        structured = self.processor._structure_ai_response(
            {"event_type": "irrigation", "description": "ran drip on block 4", "confidence": 90},
            "ran drip on block 4 this evening",
            12.0,
        )
        self.assertNotIn(
            "date",
            structured,
            "The LLM path is emitting a date again. The farmer authors the date in the wizard; "
            "a server clock in UTC is not the farm's day.",
        )

    def test_the_keyword_fallback_emits_no_date(self):
        """The no-OpenAI branch. It ran on every request before OPENAI_AVAILABLE was set in prod."""
        fallback = self.processor._fallback_processing("watered block four", "apple", "en-US")
        self.assertNotIn(
            "date",
            fallback,
            "The keyword fallback is emitting a date again. Same reasoning as the LLM path.",
        )

    def test_neither_path_emits_any_other_machine_authored_day(self):
        """A rename is the obvious way this regresses: `event_date`, `activity_date`, `day`."""
        structured = self.processor._structure_ai_response(
            {"event_type": "harvest", "description": "picked block 2"}, "picked block 2", 1.0
        )
        fallback = self.processor._fallback_processing("picked block two", "apple", "en-US")
        forbidden = {"date", "event_date", "activity_date", "performed_on", "day", "occurred_at"}
        for payload, which in ((structured, "LLM path"), (fallback, "keyword fallback")):
            leaked = forbidden.intersection(payload)
            self.assertEqual(
                leaked,
                set(),
                f"The {which} is emitting a machine-authored day: {sorted(leaked)}. "
                "Only the farmer authors a record's date.",
            )
