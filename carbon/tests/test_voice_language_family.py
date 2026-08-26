"""B3 — a Spanish transcript must reach the Spanish prompt.

The front end's Spanish locale is ``es-419`` (Latin America). The GPT prompt variants in
``ai_voice_processor`` are filed under ``es-ES``, and the fallback keyword sets under
``es``. Before 2026-08-25 the lookup was an exact-match ``prompts.get(language, ...)``, so
``es-419`` fell through to the ENGLISH prompt and the English keyword set — silently, since
that fallback is also the ordinary success path for English.

This was invisible from either side alone: the front end "sent a language" and the backend
"had a Spanish prompt". Only the tag mismatch between them was wrong.
"""

from django.test import SimpleTestCase

from carbon.services.ai_voice_processor import AIVoiceProcessor, keyword_key_for, prompt_key_for


class LanguageFamilyResolutionTests(SimpleTestCase):
    def test_app_spanish_locale_resolves_to_the_spanish_prompt(self):
        """es-419 is the locale the app actually ships; it must not answer in English."""
        self.assertEqual(prompt_key_for("es-419"), "es-ES")
        self.assertEqual(keyword_key_for("es-419"), "es")

    def test_any_spanish_region_resolves_to_spanish(self):
        for tag in ("es", "es-ES", "es-MX", "es-419", "ES-419"):
            with self.subTest(tag=tag):
                self.assertEqual(prompt_key_for(tag), "es-ES")
                self.assertEqual(keyword_key_for(tag), "es")

    def test_portuguese_regions_resolve_to_portuguese(self):
        for tag in ("pt", "pt-BR", "pt-PT"):
            with self.subTest(tag=tag):
                self.assertEqual(prompt_key_for(tag), "pt-BR")
                self.assertEqual(keyword_key_for(tag), "pt")

    def test_english_and_unknown_languages_fall_back_to_english(self):
        for tag in ("en", "en-US", "en-GB", "de-DE", "", None):
            with self.subTest(tag=tag):
                self.assertEqual(prompt_key_for(tag), "en-US")
                self.assertEqual(keyword_key_for(tag), "keywords")

    def test_the_resolved_prompt_is_really_a_different_string(self):
        """Anti-vacuity: resolution is pointless if the Spanish prompt is the English one.

        A key lookup that returns the right key proves nothing about the text behind it.
        """
        processor = AIVoiceProcessor()
        english = processor._get_system_prompt("en-US")
        spanish = processor._get_system_prompt("es-419")
        portuguese = processor._get_system_prompt("pt-BR")

        self.assertNotEqual(english, spanish)
        self.assertNotEqual(english, portuguese)
        self.assertTrue(spanish.strip())

        extraction_en = processor._create_extraction_prompt("hola", "almonds", "en-US")
        extraction_es = processor._create_extraction_prompt("hola", "almonds", "es-419")
        self.assertNotEqual(extraction_en, extraction_es)
