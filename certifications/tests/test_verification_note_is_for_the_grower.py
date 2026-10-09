"""A certificate's verification note is for the grower, never a developer instruction
(recordkeeping review S10, F-26, 2026-10-07); the welcome mail subject carries no retired tagline
(F-30). Red on the old code on an assertion."""

import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

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


class ClearDeveloperNoteOperationTests(TestCase):
    """Review of back #139: the stated remediation (`reevaluate_certification_verification`)
    cannot clear the rows, so this operation does, through data_operations."""

    def _cert(self, notes):
        from certifications.models import Certification
        from company.models import Company, Establishment

        company = Company.objects.create(name="Note Co")
        est = Establishment.objects.create(name="Note Farm", company=company, state="OR")
        return Certification.objects.create(
            establishment=est,
            certification_type="usda_organic",
            certifier_name="Oregon Tilth",
            certification_number="OR-9",
            verification_status="self_reported",
            verification_notes=notes,
        )

    def test_dry_run_apply_and_restore(self):
        from certifications.management.commands.clear_developer_verification_note import NEW_NOTE, OLD_NOTE

        stale = self._cert(OLD_NOTE)
        untouched = self._cert("Verified via USDA Organic Integrity Database")
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / "dry.json"
            call_command("clear_developer_verification_note", report=str(report))
            stale.refresh_from_db()
            self.assertEqual(stale.verification_notes, OLD_NOTE, "a dry run saves nothing")
            applied = Path(d) / "apply.json"
            call_command("clear_developer_verification_note", report=str(applied), apply=True, run_by="test")
            stale.refresh_from_db()
            untouched.refresh_from_db()
            self.assertEqual(stale.verification_notes, NEW_NOTE)
            self.assertEqual(untouched.verification_notes, "Verified via USDA Organic Integrity Database")
            call_command("clear_developer_verification_note", restore=str(applied), run_by="test")
            stale.refresh_from_db()
            self.assertEqual(stale.verification_notes, OLD_NOTE)
