"""The daily off-platform database backup (OV-ST-C13, 2026-11-13).

pg_dump and S3 are faked: these pin what the command refuses and what it sends. The real path was
proved by the restore drill and is checked in production by the maintenance heartbeat.
"""

import io
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from common.management.commands import backup_database_offsite as cmd

CONFIGURED = {
    "DB_BACKUP_BUCKET": "trazo-db-backups-test",
    "DB_BACKUP_AWS_REGION": "us-east-2",
    "DB_BACKUP_AWS_ACCESS_KEY_ID": "AKIA-BACKUP-ONLY",
    "DB_BACKUP_AWS_SECRET_ACCESS_KEY": "backup-secret",
    "AWS_ACCESS_KEY_ID": "AKIA-THE-APP",
}


def _fake_run(dump_bytes=b"x" * (cmd.MIN_DUMP_BYTES + 1), dump_code=0, list_code=0, listing="TABLE DATA public x\n"):
    seen = {}

    def run(args, **kwargs):
        if args[0] == "pg_dump":
            seen["dump_env"] = kwargs["env"]
            path = [a for a in args if a.startswith("--file=")][0].split("=", 1)[1]
            seen["path"] = path
            with open(path, "wb") as fh:
                fh.write(dump_bytes)
            return SimpleNamespace(returncode=dump_code, stdout="", stderr="pg_dump: boom" if dump_code else "")
        if args[0] == "pg_restore":
            return SimpleNamespace(returncode=list_code, stdout=listing, stderr="")
        raise AssertionError(args)

    return run, seen


@override_settings(**CONFIGURED)
class OffsiteBackupTests(SimpleTestCase):
    def _call(self, run):
        client = MagicMock()
        with patch.object(cmd.subprocess, "run", side_effect=run), patch("boto3.client", return_value=client) as make:
            call_command("backup_database_offsite", stdout=io.StringIO())
        return client, make

    def test_uploads_an_encrypted_dump_with_the_put_only_user(self):
        run, seen = _fake_run()
        client, make = self._call(run)
        make.assert_called_once()
        self.assertEqual(make.call_args.kwargs["aws_access_key_id"], "AKIA-BACKUP-ONLY")
        put = client.put_object.call_args.kwargs
        self.assertEqual(put["Bucket"], "trazo-db-backups-test")
        self.assertTrue(put["Key"].startswith("postgres/") and put["Key"].endswith(".dump"))
        self.assertEqual(put.get("ServerSideEncryption"), "AES256", "uploaded without server-side encryption")
        self.assertEqual(len(put["Metadata"]["sha256"]), 64)
        self.assertFalse(os.path.exists(seen["path"]), "the dump was left on the container's disk")

    def test_unconfigured_fails_the_run_instead_of_skipping(self):
        run, _ = _fake_run()
        with override_settings(DB_BACKUP_BUCKET=""):
            with self.assertRaisesMessage(CommandError, "not configured"):
                self._call(run)

    def test_refuses_the_apps_own_aws_key(self):
        run, _ = _fake_run()
        with override_settings(DB_BACKUP_AWS_ACCESS_KEY_ID="AKIA-THE-APP"):
            with self.assertRaisesMessage(CommandError, "app's own key"):
                self._call(run)

    def test_a_failed_dump_uploads_nothing(self):
        run, seen = _fake_run(dump_code=1)
        client = MagicMock()
        with patch.object(cmd.subprocess, "run", side_effect=run), patch("boto3.client", return_value=client):
            with self.assertRaisesMessage(CommandError, "pg_dump failed"):
                call_command("backup_database_offsite", stdout=io.StringIO())
        client.put_object.assert_not_called()
        self.assertFalse(os.path.exists(seen["path"]))

    def test_a_tiny_dump_is_not_uploaded(self):
        run, _ = _fake_run(dump_bytes=b"tiny")
        client = MagicMock()
        with patch.object(cmd.subprocess, "run", side_effect=run), patch("boto3.client", return_value=client):
            with self.assertRaisesMessage(CommandError, "too small"):
                call_command("backup_database_offsite", stdout=io.StringIO())
        client.put_object.assert_not_called()

    def test_an_unreadable_dump_is_not_uploaded(self):
        run, _ = _fake_run(list_code=1, listing="")
        client = MagicMock()
        with patch.object(cmd.subprocess, "run", side_effect=run), patch("boto3.client", return_value=client):
            with self.assertRaisesMessage(CommandError, "cannot read the dump"):
                call_command("backup_database_offsite", stdout=io.StringIO())
        client.put_object.assert_not_called()

    def test_the_password_goes_by_environment_never_on_the_command_line(self):
        run, seen = _fake_run()
        with override_settings(
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": "defaultdb",
                    "USER": "doadmin",
                    "PASSWORD": "s3cret",
                    "HOST": "db.example",
                    "PORT": "25060",
                    "OPTIONS": {"sslmode": "require"},
                }
            }
        ):
            with patch.object(cmd.subprocess, "run", side_effect=run) as ran, patch("boto3.client"):
                call_command("backup_database_offsite", stdout=io.StringIO())
        self.assertEqual(seen["dump_env"]["PGPASSWORD"], "s3cret")
        self.assertEqual(seen["dump_env"]["PGSSLMODE"], "require")
        for call in ran.call_args_list:
            self.assertNotIn("s3cret", " ".join(call.args[0]))
