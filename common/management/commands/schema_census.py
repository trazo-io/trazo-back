"""Take a read-only census of every stored row, and optionally compare it with an earlier one.

Phase 1 of the schema remodel plan: the baseline every later migration is checked against.

    manage.py schema_census --label before-phase-2 --store
    manage.py schema_census --label after-phase-2 --store --compare storage:ops/census/<key>.json

`--store` writes the full census to the PRIVATE records storage (S3 in production, signed URLs,
never under a public prefix), because a production console runs in a container whose disk does not
survive the deploy the census is meant to bracket. `--out` writes a local copy as well. The summary
(counts and verdicts, no row digests) always goes to stdout, followed by the census SHA-256.

`--compare` exits non-zero when the earlier census shows anything the later one lost: a table, a
column, a row, a seal that verified, or audit-trail entries. Changed and new rows are listed, not
failed: users keep writing on a live system.
"""

import hashlib
import json

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from backend.storage import is_public_media_key, private_records_storage
from common.services import census as svc

STORAGE_PREFIX = "ops/census/"
STORAGE_REF = "storage:"


def _load(ref: str):
    if ref.startswith(STORAGE_REF):
        key = ref[len(STORAGE_REF) :]
        storage = private_records_storage()
        if not storage.exists(key):
            raise CommandError(f"{ref}: no such census in private storage")
        with storage.open(key, "rb") as handle:
            return json.loads(handle.read().decode("utf-8"))
    with open(ref, encoding="utf-8") as handle:
        return json.load(handle)


class Command(BaseCommand):
    help = "Read-only census of every stored row (Phase 1 of the schema remodel plan)."

    def add_arguments(self, parser):
        parser.add_argument("--label", default="", help="What this census brackets, e.g. before-phase-2.")
        parser.add_argument("--store", action="store_true", help="Save the full census to private storage.")
        parser.add_argument("--out", default="", help="Also write the full census to this local path.")
        parser.add_argument(
            "--compare",
            default="",
            help="An earlier census to compare against: a local path or storage:<key>.",
        )
        parser.add_argument(
            "--renames",
            default="",
            help='JSON object of declared model renames, e.g. {"history.History": "history.Production"}.',
        )

    def handle(self, *args, **options):
        # A census of a database the code has not finished migrating describes tables the models
        # do not match, and it fails halfway on the first one that is missing. Refuse up front.
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            names = [f"{m.app_label}.{m.name}" for m, _backwards in pending[:5]]
            raise CommandError(
                f"{len(pending)} migrations are not applied to this database (e.g. {names}). "
                "Take the census with the code the database is migrated to."
            )
        renames = json.loads(options["renames"]) if options["renames"] else {}
        before = _load(options["compare"]) if options["compare"] else None

        census = svc.take_census(label=options["label"])
        text = svc.to_json(census)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

        if options["out"]:
            with open(options["out"], "w", encoding="utf-8") as handle:
                handle.write(text)
        stored_key = ""
        if options["store"]:
            stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
            safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in options["label"]) or "census"
            key = f"{STORAGE_PREFIX}{stamp}-{safe_label}-{digest[:12]}.json"
            if is_public_media_key(key):  # belt and braces: the prefix list is a privacy decision
                raise CommandError(f"{key} would sit under a public media prefix; refusing to store it")
            stored_key = private_records_storage().save(key, ContentFile(text.encode("utf-8")))

        self.stdout.write(json.dumps(svc.summary(census), indent=1, sort_keys=True))
        self.stdout.write(f"census_sha256 {digest}")
        if stored_key:
            self.stdout.write(f"stored {STORAGE_REF}{stored_key}")

        if before is not None:
            result = svc.compare(before, census, renames=renames)
            self.stdout.write(json.dumps(result, indent=1, sort_keys=True))
            if not result["ok"]:
                raise CommandError(f"census lost data against {options['compare']}: {len(result['losses'])} losses")
