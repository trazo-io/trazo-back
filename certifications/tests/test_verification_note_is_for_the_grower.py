"""A certificate's verification note is for the grower, never a developer instruction
(recordkeeping review S10, F-26, 2026-10-07); the welcome mail subject carries no retired tagline
(F-30). Red on the old code on an assertion."""

from unittest import mock

from django.test import SimpleTestCase

from certifications.services.usda_organic_verifier import USDAOrganicVerifier


class VerificationNoteTests(SimpleTestCase):
    def test_an_empty_integrity_database_yields_a_grower_facing_note(self):
        verifier = USDAOrganicVerifier()
        with mock.patch("certifications.models.USDAOrganicOperation.objects") as objects:
            objects.count.return_value = 0
            result = verifier.verify("Calapooia Bend Farm", "OR", "OR-1")
        self.assertEqual(result.status, "self_reported")
        self.assertNotIn("manage.py", result.notes or "")
        self.assertNotIn("Run:", result.notes or "")
        self.assertIn("not available", result.notes or "")

    def test_the_welcome_subject_has_no_retired_tagline(self):
        import inspect

        from users import utils

        source = inspect.getsource(utils)
        self.assertNotIn("Agricultural Transparency Platform", source)
        self.assertIn("Welcome to Trazo", source)
