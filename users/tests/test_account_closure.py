"""Closing an account exports everything, then leaves nothing behind (OV-CLM-C06, 2026-11-11).

The privacy policy (7.1) and the terms (13) say: on a confirmed request, send the farm an export of
its records and uploaded files, take published pages down at once, and delete the account and its
data within 30 days. `close_account` is what makes that true. These tests build one company with
the things a plain `Company.delete()` would have left behind (files in storage, an event photo album,
a crew recording at Twilio, audit-log entries carrying an email address) and check each is gone,
while a second company and a user who also works there are untouched.
"""

import io
import json
import shutil
import tempfile
import zipfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from auditlog.models import LogEntry

from backend.storage import private_records_storage
from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from common.models import DataOperationLog, Gallery, GalleryImage
from common.services import account_closure
from company.models import Company
from documents.models import GeneratedDocument
from fieldnotes.models import FieldNote
from history.models import History
from product.models import Establishment, Parcel
from users.models import WorksIn

User = get_user_model()
MEDIA = tempfile.mkdtemp(prefix="closure-test-")


def _first_choice(model, field):
    return model._meta.get_field(field).choices[0][0]


@override_settings(MEDIA_ROOT=MEDIA)
class AccountClosureTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.company = Company.objects.create(name="Closing Orchards LLC")
        self.other = Company.objects.create(name="Staying Farms")

        self.owner = User.objects.create_user(email="owner@closing.example", password="pw-for-tests-only")
        self.shared = User.objects.create_user(email="consultant@both.example", password="pw-for-tests-only")
        self.stayer = User.objects.create_user(email="stayer@staying.example", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.owner, company=self.company, role=WorksIn.COMPANY_ADMIN)
        WorksIn.objects.create(user=self.shared, company=self.company, role=WorksIn.COMPANY_ADMIN)
        WorksIn.objects.create(user=self.shared, company=self.other, role=WorksIn.COMPANY_ADMIN)
        WorksIn.objects.create(user=self.stayer, company=self.other, role=WorksIn.COMPANY_ADMIN)

        self.farm = Establishment.objects.create(name="North Block", company=self.company)
        parcel = Parcel.objects.create(name="Block 4", establishment=self.farm, area=1)
        album = Gallery.objects.create()
        photo = album.images.create(image=ContentFile(b"jpeg-bytes", name="spray.jpg"))
        self.photo_name = photo.image.name
        default_storage.save("gallery_images/raw-upload.jpg", ContentFile(b"raw"))
        GalleryImage.objects.filter(pk=photo.pk).update(s3_key="gallery_images/raw-upload.jpg")
        self.album_id = album.pk
        # Inside the five-year window: the product refuses to delete this season record by record.
        self.season = History.objects.create(
            parcel=parcel,
            name="2026 apples",
            finish_date=timezone.now() - timedelta(days=30),
            retention_until=timezone.now().date() + timedelta(days=5 * 365),
            published=True,
            album=album,
        )
        doc = GeneratedDocument.objects.create(
            establishment=self.farm,
            folder=_first_choice(GeneratedDocument, "folder"),
            source=_first_choice(GeneratedDocument, "source"),
            title="Spray invoice",
            file=ContentFile(b"%PDF-invoice", name="invoice.pdf"),
        )
        self.doc_name = doc.file.name
        self.note = FieldNote.objects.create(
            company=self.company,
            sender_phone="+14155550199",
            sender_display_name="Miguel",
            provider=FieldNote.TWILIO,
            provider_message_id="MM-closure-1",
            kind=FieldNote.VOICE,
            provider_media_ref="https://api.twilio.com/media/ME1",
            status=FieldNote.PENDING,
        )

        # A filed annual update: PROTECT keeps an ordinary delete from erasing it (real data hit this).
        osp = OrganicSystemPlan.objects.create(
            establishment=self.farm, version_number=1, status="active", submitted_at=timezone.now()
        )
        self.filing = OSPAnnualUpdate.objects.create(
            prior_osp=osp, reporting_year=2027, changes_summary="No changes to the plan this year."
        )

        other_farm = Establishment.objects.create(name="South Block", company=self.other)
        Parcel.objects.create(name="Block 9", establishment=other_farm, area=1)

    def _export(self):
        return call_command("close_account", company=self.company.pk, export=True, stdout=io.StringIO())

    def _apply(self, name="Closing Orchards LLC"):
        with patch("fieldnotes.services.transcribe.delete_media", return_value=True) as deleted:
            out = io.StringIO()
            call_command("close_account", company=self.company.pk, apply=True, confirm_name=name, stdout=out)
        return deleted, out.getvalue()

    def test_dry_run_counts_and_changes_nothing(self):
        out = io.StringIO()
        call_command("close_account", company=self.company.pk, stdout=out)
        text = out.getvalue()
        report = json.loads(text[text.index("{") : text.rindex("}") + 1])
        self.assertEqual(report["deleted_users"], 1)
        self.assertEqual(report["kept_users"], 1)
        self.assertEqual(report["published_seasons"], 1)
        self.assertEqual(report["recordings_at_provider"], 1)
        self.assertGreaterEqual(report["files"], 3)
        self.assertIn("history.Production", report["rows"])
        self.assertTrue(report["protected_rows_included"], "the filed annual update was not reached")
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())
        # The dry run is logged nowhere and carries no personal data on screen.
        self.assertNotIn("owner@closing.example", text)
        self.assertFalse(DataOperationLog.objects.filter(operation="close_account").exists())

    def test_apply_refuses_without_an_export(self):
        with self.assertRaisesMessage(CommandError, "No closure export"):
            self._apply()
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())
        self.assertTrue(History.objects.get(pk=self.season.pk).published)

    def test_apply_refuses_a_wrong_name(self):
        self._export()
        with self.assertRaisesMessage(CommandError, "does not match"):
            self._apply(name="Closing Orchards")
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    def test_export_holds_the_records_the_files_and_the_retention_note(self):
        self._export()
        key = account_closure.find_export(self.company)
        self.assertIsNotNone(key)
        with private_records_storage().open(key, "rb") as fh:
            bundle = zipfile.ZipFile(io.BytesIO(fh.read()))
        names = bundle.namelist()
        self.assertIn(f"records/farm-{self.farm.pk}.zip", names)
        self.assertIn(f"files/{self.doc_name}", names)
        self.assertIn(f"files/{self.photo_name}", names)
        self.assertEqual(bundle.read(f"files/{self.doc_name}"), b"%PDF-invoice")
        manifest = json.loads(bundle.read("manifest.json"))
        self.assertIn("205.103(b)(4)", manifest["note"])
        self.assertEqual(manifest["files_missing_from_storage"], [])

    def test_apply_deletes_everything_only_this_company_owns(self):
        self._export()
        owner_pk = self.owner.pk
        season_pk = self.season.pk
        audit_before = LogEntry.objects.filter(object_pk=str(season_pk)).count()
        deleted_media, _ = self._apply()

        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())
        self.assertFalse(History.objects.filter(pk=season_pk).exists())
        self.assertFalse(User.objects.filter(pk=owner_pk).exists())
        self.assertFalse(Gallery.objects.filter(pk=self.album_id).exists(), "the album outlived its record")
        self.assertFalse(FieldNote.objects.filter(pk=self.note.pk).exists())
        self.assertFalse(OSPAnnualUpdate.objects.filter(pk=self.filing.pk).exists())
        deleted_media.assert_called_once()

        # Files: nothing left in storage for the deleted rows.
        self.assertFalse(private_records_storage().exists(self.doc_name))
        self.assertFalse(default_storage.exists(self.photo_name))
        self.assertFalse(default_storage.exists("gallery_images/raw-upload.jpg"))

        # Audit log: entries about the deleted rows are gone, and deleting wrote none back.
        self.assertGreater(audit_before, 0, "ANTI-VACUITY: the season had audit entries to remove")
        self.assertFalse(LogEntry.objects.filter(object_pk=str(season_pk)).exists())
        self.assertFalse(LogEntry.objects.filter(actor_email="owner@closing.example").exists())
        self.assertFalse(LogEntry.objects.filter(action=LogEntry.Action.DELETE).exists())

        # The operation log keeps counts, never a name or an address.
        log = DataOperationLog.objects.get(operation="close_account")
        self.assertEqual(log.counts["company_id"], self.company.pk)
        self.assertNotIn("Closing Orchards", json.dumps(log.counts))
        self.assertNotIn("@", json.dumps(log.counts))

    def test_apply_leaves_the_other_company_and_the_shared_user(self):
        self._export()
        self._apply()
        self.assertTrue(Company.objects.filter(pk=self.other.pk).exists())
        self.assertTrue(Parcel.objects.filter(establishment__company=self.other).exists())
        self.assertTrue(User.objects.filter(pk=self.stayer.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.shared.pk).exists())
        self.assertEqual(
            list(WorksIn.objects.filter(user=self.shared).values_list("company_id", flat=True)), [self.other.pk]
        )

    def test_pages_come_down_even_when_the_delete_fails_and_recordings_stay(self):
        self._export()
        with patch.object(account_closure.Collector, "delete", side_effect=RuntimeError("boom")):
            with patch("fieldnotes.services.transcribe.delete_media", return_value=True) as deleted:
                with self.assertRaises(RuntimeError):
                    call_command(
                        "close_account",
                        company=self.company.pk,
                        apply=True,
                        confirm_name="Closing Orchards LLC",
                        stdout=io.StringIO(),
                    )
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())
        self.assertFalse(History.objects.get(pk=self.season.pk).published)
        # Review of #398: the recording is deleted only after the rows are, never before.
        deleted.assert_not_called()

    def test_export_refuses_when_a_file_cannot_be_read(self):
        """Review of #398: an export with a hole must not exist, or apply would delete the hole."""
        private_records_storage().delete(self.doc_name)
        with self.assertRaisesMessage(CommandError, "could not be read"):
            self._export()
        self.assertIsNone(account_closure.find_export(self.company))
        call_command(
            "close_account", company=self.company.pk, export=True, allow_missing_files=True, stdout=io.StringIO()
        )
        manifest = account_closure.read_manifest(account_closure.find_export(self.company))
        self.assertEqual(manifest["files_missing_from_storage"], [self.doc_name])
        self.assertTrue(manifest["missing_files_accepted"])

    def test_apply_refuses_when_records_changed_after_the_export(self):
        """Review of #398: a record added between --export and --apply was never exported."""
        self._export()
        Parcel.objects.create(name="Block 5, planted after the export", establishment=self.farm, area=1)
        with self.assertRaisesMessage(CommandError, "changed since the export"):
            self._apply()
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())
        self.assertTrue(History.objects.get(pk=self.season.pk).published, "refused before anything changed")

    def test_exports_are_purged_after_thirty_days(self):
        self._export()
        key = account_closure.find_export(self.company)
        storage = private_records_storage()
        with patch.object(FileSystemStorage, "get_modified_time", return_value=timezone.now() - timedelta(days=29)):
            call_command("purge_closure_exports", stdout=io.StringIO())
        self.assertTrue(storage.exists(key))
        with patch.object(FileSystemStorage, "get_modified_time", return_value=timezone.now() - timedelta(days=31)):
            call_command("purge_closure_exports", stdout=io.StringIO())
        self.assertFalse(storage.exists(key))

    def test_protect_is_restored_after_collecting(self):
        """The closure swaps PROTECT for a counted cascade only while it collects."""
        from django.db.models import PROTECT, ProtectedError

        account_closure.plan(self.company)
        fields = [
            f
            for f in OSPAnnualUpdate._meta.concrete_fields
            if f.is_relation and getattr(f.remote_field, "on_delete", None) is PROTECT
        ]
        self.assertTrue(fields, "ANTI-VACUITY: OSPAnnualUpdate has a PROTECT relation")
        with self.assertRaises(ProtectedError):
            self.company.delete()
