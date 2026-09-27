"""The extraction call has a deadline, and missing it degrades instead of raising (2026-09-26).

`AIVoiceProcessor` called `chat.completions.create` with no `timeout=`. That was survivable while
its only caller was a request thread with a farmer watching the spinner: the worst case was a slow
page. It stops being survivable the moment an inbound WhatsApp note is parsed in a background
daemon thread, because nobody is waiting on it and the thread is holding a database connection that
`connections.close_all()` only releases once the function returns.

The fallback is the point. A timeout must land in the same place an absent API key lands: the
keyword matcher, with `source == "pattern_matching_fallback"`. An extraction that raises would leave
an inbound note stuck in `transcribing` forever.
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from carbon.services.ai_voice_processor import AIVoiceProcessor


def _processor_with(client):
    """A processor wired to `client`, bypassing the API-key early return in __init__."""
    processor = AIVoiceProcessor()
    processor.api_key = "test-key"
    processor.openai = client
    return processor


@patch("carbon.services.ai_voice_processor.OPENAI_AVAILABLE", True)
class ExtractionCarriesADeadline(SimpleTestCase):
    """Every test here forces the module-level availability flag on.

    MEASURED 2026-09-26: without that patch this whole class was GREEN locally and RED in CI, and it
    had already been added to the CI allowlist, so it would have turned the build red on arrival.

    `OPENAI_AVAILABLE` is read ONCE at import time into a module global
    (`ai_voice_processor.py:32`) from a setting whose default is False, and `process_voice_input`
    returns the keyword fallback before touching the client when it is unset. A developer with
    OPENAI_AVAILABLE=True in their .env therefore saw the client called; CI, which has no .env, saw
    it skipped and the assertions fail. `override_settings` cannot help, because the global was
    already bound when the module was imported. Patching the global the code actually reads also
    makes the test independent of any environment, which is what a guard should be.
    """

    @override_settings(OPENAI_TIMEOUT_SECONDS=7.5)
    def test_the_configured_timeout_reaches_the_client(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("stop here, we only want the kwargs")
        _processor_with(client).process_voice_input("regamos el bloque 4", "apple", "es-419")

        self.assertTrue(client.chat.completions.create.called, "the client was never called")
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertIn("timeout", kwargs, "the extraction call has no deadline")
        self.assertEqual(kwargs["timeout"], 7.5)

    def test_the_default_is_a_real_number_not_none(self):
        # `timeout=None` is the SDK's "wait forever", so a default that resolves to None would
        # reintroduce the hang while still passing the assertion above.
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("stop")
        _processor_with(client).process_voice_input("we sprayed the east block", "apple")

        timeout = client.chat.completions.create.call_args.kwargs.get("timeout")
        self.assertIsNotNone(timeout)
        self.assertGreater(float(timeout), 0)

    def test_a_timeout_degrades_to_keyword_matching_and_does_not_raise(self):
        class Timeout(Exception):
            pass

        client = MagicMock()
        client.chat.completions.create.side_effect = Timeout("timed out")
        result = _processor_with(client).process_voice_input("we irrigated the east block", "apple")

        self.assertEqual(result["source"], "pattern_matching_fallback")
        # Still a usable suggestion, so a note reaches the supervisor rather than dying in the queue.
        self.assertIn("type", result)
        self.assertIn("original_transcript", result)

    def test_the_fallback_still_refuses_to_invent_a_date(self):
        # The timeout path is a second producer of the response, and it is bound by the same rule
        # as the model path: a machine never authors the day a record carries.
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("timed out")
        result = _processor_with(client).process_voice_input("we mowed the orchard floor", "apple")

        self.assertNotIn("date", result)
