"""How the app is told which language Deepgram listens in.

"locale" (default) pins recognition to the app's language. "multi" asks Deepgram to detect the
spoken language: it rescues Spanish spoken into the English app, which comes back empty when
pinned, but MEASURED 2026-09-10 in the real app it dropped a word from Spanish notes 5 runs in 5
(usually the block) where pinned es-419 was exact. So it is opt-in, switched by an env var on the
server without a frontend deploy.
"""

from pathlib import Path

from django.test import SimpleTestCase, override_settings

from carbon.views import voice_language_mode

_CARBON_VIEWS = Path(__file__).resolve().parents[1] / "views.py"
_BACKEND_SETTINGS = Path(__file__).resolve().parents[2] / "backend" / "settings"


class VoiceLanguageModeTests(SimpleTestCase):
    def test_pinned_to_the_app_language_is_the_default(self):
        with override_settings(DEEPGRAM_LANGUAGE_MODE="locale"):
            self.assertEqual(voice_language_mode(), "locale")

    def test_detection_is_opt_in(self):
        with override_settings(DEEPGRAM_LANGUAGE_MODE="multi"):
            self.assertEqual(voice_language_mode(), "multi")

    def test_env_var_spelling_is_forgiven(self):
        with override_settings(DEEPGRAM_LANGUAGE_MODE="  MULTI "):
            self.assertEqual(voice_language_mode(), "multi")

    def test_an_unrecognised_value_answers_the_default(self):
        # "es" is the plausible mistake — a language, not a mode. A typo must land on the
        # measured-accurate mode, never switch detection on by accident.
        for value in ("es", "en-US", "", "on", "auto"):
            with self.subTest(value=value), override_settings(DEEPGRAM_LANGUAGE_MODE=value):
                self.assertEqual(voice_language_mode(), "locale")

    def test_the_shipped_default_is_locale(self):
        """The DEFAULT in base.py, not the live setting — an environment may opt in on purpose."""
        base = (_BACKEND_SETTINGS / "base.py").read_text()
        self.assertIn(
            'DEEPGRAM_LANGUAGE_MODE = config("DEEPGRAM_LANGUAGE_MODE", default="locale")',
            base,
            "detection dropped the block from Spanish notes — it must not be the default",
        )

    def test_the_endpoint_serves_it(self):
        """The helper is only a switch if voice-config actually sends it."""
        views = _CARBON_VIEWS.read_text()
        start = views.index("def voice_config(")
        body = views[start : views.find("\ndef ", start + 1)]
        self.assertIn('"language_mode": voice_language_mode()', body)
