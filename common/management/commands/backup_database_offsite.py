"""Dump the production database and upload it to S3, outside DigitalOcean (OV-ST-C13, 2026-11-13).

WHY. DigitalOcean keeps 8 daily backups of `trazo-db`, all inside the same account as the database.
The restore drill of 2026-11-13 proved they restore (365 s, documented in
documentation/deployment/DATABASE-RESTORE-RUNBOOK.md), but an account that is suspended, compromised
or closed takes every one of them with it. This is the copy that survives that.

WHAT. `pg_dump --format=custom` to a temporary file, `pg_restore --list` on it so an unreadable dump
fails here rather than on the day it is needed, then one upload to `DB_BACKUP_BUCKET` under
`postgres/YYYY/MM/`, server-side encrypted. The bucket keeps 30 days (lifecycle) and is versioned.

CREDENTIALS. A dedicated IAM user allowed only `s3:PutObject` under `postgres/`. It cannot read,
list or delete, so a leaked app environment (or a compromised DigitalOcean account) can add files
but cannot erase the backups. NEVER use the app's own AWS keys here.

VERSION. The image's `postgresql-client` is Debian's, 17 on trixie (checked 2026-11-13), and
pg_dump refuses to dump a server NEWER than itself. Production is Postgres 16. If the database is
ever upgraded past the client, this command fails loudly; it does not write a partial dump. Restore
these dumps with pg_restore 17 or newer.

Runs daily from `run_due_maintenance` (registered in backend/scheduled_work.py), so a failure is
reported by the maintenance heartbeat. Unconfigured is a failure, not a skip: a backup that quietly
does not run is the thing this exists to prevent.
"""

import hashlib
import os
import subprocess
import tempfile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

KEY_PREFIX = "postgres/"
#: A dump smaller than this is a dump of nothing (the schema alone is far larger).
MIN_DUMP_BYTES = 100 * 1024
_TIMEOUT_SECONDS = 15 * 60


def _connection_env():
    """libpq settings for the default database, read from Django's own settings (no URL parsing)."""
    db = settings.DATABASES["default"]
    env = dict(os.environ)
    env.update(
        {
            "PGHOST": str(db.get("HOST") or ""),
            "PGPORT": str(db.get("PORT") or "5432"),
            "PGUSER": str(db.get("USER") or ""),
            "PGPASSWORD": str(db.get("PASSWORD") or ""),
            "PGDATABASE": str(db.get("NAME") or ""),
        }
    )
    sslmode = (db.get("OPTIONS") or {}).get("sslmode")
    if sslmode:
        env["PGSSLMODE"] = sslmode
    return env


def object_key(now=None) -> str:
    now = now or timezone.now()
    return f"{KEY_PREFIX}{now:%Y/%m}/trazo-db-{now:%Y%m%dT%H%M%SZ}.dump"


class Command(BaseCommand):
    help = "Dump the database (pg_dump, custom format) and upload it to the off-platform S3 bucket."

    def handle(self, *args, **options):
        bucket = settings.DB_BACKUP_BUCKET
        key_id = settings.DB_BACKUP_AWS_ACCESS_KEY_ID
        secret = settings.DB_BACKUP_AWS_SECRET_ACCESS_KEY
        if not (bucket and key_id and secret):
            raise CommandError(
                "Off-platform backup is not configured: set DB_BACKUP_BUCKET, DB_BACKUP_AWS_ACCESS_KEY_ID "
                "and DB_BACKUP_AWS_SECRET_ACCESS_KEY (the put-only IAM user, never the app's keys)."
            )
        if key_id == getattr(settings, "AWS_ACCESS_KEY_ID", None):
            raise CommandError("DB_BACKUP_AWS_ACCESS_KEY_ID is the app's own key; the backup needs the put-only user.")

        env = _connection_env()
        fd, path = tempfile.mkstemp(prefix="trazo-db-", suffix=".dump")
        os.close(fd)
        try:
            dump = subprocess.run(
                ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", f"--file={path}"],
                env=env,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
            )
            if dump.returncode != 0:
                raise CommandError(f"pg_dump failed ({dump.returncode}): {dump.stderr.strip()[:500]}")
            size = os.path.getsize(path)
            if size < MIN_DUMP_BYTES:
                raise CommandError(f"pg_dump wrote {size} bytes, too small to be this database; not uploaded.")
            listing = subprocess.run(
                ["pg_restore", "--list", path], capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
            )
            if listing.returncode != 0 or "TABLE DATA" not in listing.stdout:
                raise CommandError(f"pg_restore cannot read the dump; not uploaded: {listing.stderr.strip()[:500]}")

            digest = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    digest.update(chunk)

            import boto3

            client = boto3.client(
                "s3",
                region_name=settings.DB_BACKUP_AWS_REGION,
                aws_access_key_id=key_id,
                aws_secret_access_key=secret,
            )
            key = object_key()
            with open(path, "rb") as fh:
                client.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=fh,
                    ServerSideEncryption="AES256",
                    Metadata={"sha256": digest.hexdigest()},
                )
            self.stdout.write(f"uploaded s3://{bucket}/{key} ({size} bytes, sha256 {digest.hexdigest()[:12]})")
        finally:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
