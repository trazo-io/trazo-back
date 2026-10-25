"""Load an intake CSV (Trazo's own schema) as records on a farm: preview first, then commit.

The operator path behind "send me your binder photos or your spreadsheet, you'll see a preview
before anything is saved". The operator reads the grower's documents, uploads them on the farm's
Documents page, writes one CSV in the schema (`documentation/reference/record-intake-schema.md`),
and runs this:

    # 1. Dry run: what would be recorded, what waits, and why. Writes nothing.
    poetry run python manage.py import_records --file coldwater.csv --farm 21 --created-by oscar+coldwater@trazo.io

    # 2. File the preview PDF in the farm's documents and email it to the grower.
    poetry run python manage.py import_records --file coldwater.csv --farm 21 --created-by ... --file-preview

    # 3. The grower replies ok (or with corrections: fix the CSV and go back to 1).
    poetry run python manage.py import_records --file coldwater.csv --farm 21 --created-by ... --commit

`--commit` refuses a CSV whose preview was never filed: the batch id is the hash of the file, so
what is written is byte-for-byte what the grower was shown. A corrected CSV is a new batch and
needs its own preview; rows already recorded from the same document and row are skipped, so the
second run writes only the fixes.
"""

import hashlib
import io
import tempfile
import uuid
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from company.models import Establishment
from documents.models import GeneratedDocument
from documents.services.filing import file_document
from history.services.record_intake import build_plan, execute, plan_fingerprint
from history.services.record_intake_preview import render_preview_pdf
from subscriptions.pilot_operator import is_setup_operator
from users.models import WorksIn

PREVIEW_SOURCE = "import_preview"


def batch_tag(batch):
    return f"import-batch:{batch}"


def plan_tag(fingerprint):
    return f"import-plan:{fingerprint}"


class Command(BaseCommand):
    help = (
        "Load an intake CSV as records on a farm (dry run unless --commit; --file-preview files the grower's preview)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="The intake CSV")
        parser.add_argument("--farm", type=int, required=True, help="Establishment id")
        parser.add_argument(
            "--created-by",
            required=True,
            help="Email of the operator running the import; written to every record's created_by.",
        )
        parser.add_argument(
            "--file-preview",
            action="store_true",
            help="File the preview PDF in the farm's documents (the copy the grower is sent).",
        )
        parser.add_argument("--preview-out", help="Also write the preview PDF to this path (default: a temp file).")
        parser.add_argument(
            "--commit", action="store_true", help="Write the records. Requires a filed preview of this file."
        )
        parser.add_argument("--limit", type=int, default=60, help="Importable rows to print (default 60)")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"No such file: {path}")
        farm = Establishment.objects.select_related("company").filter(id=options["farm"]).first()
        if farm is None:
            raise CommandError(f"No farm with id {options['farm']}.")
        operator = get_user_model().objects.filter(email__iexact=options["created_by"]).first()
        if operator is None:
            raise CommandError(f"No account with email {options['created_by']!r}.")
        if not WorksIn.objects.filter(user=operator, company=farm.company).exists():
            raise CommandError(
                f"{operator.email} is not a member of {farm.company.name}; records need an author who is."
            )

        raw = path.read_bytes()
        batch = hashlib.sha256(raw).hexdigest()[:12]
        plan = build_plan(io.BytesIO(raw), farm)
        if plan.error:
            raise CommandError(plan.error)
        fingerprint = plan_fingerprint(plan)

        self.stdout.write(self.style.MIGRATE_HEADING(f"{farm.name} ({farm.company.name}) · batch {batch}"))
        self.stdout.write(
            f"  operator: {operator.email} · setup operator: {'yes' if is_setup_operator(operator) else 'no'}"
        )
        documents = self._documents(plan, farm)
        for doc in documents:
            self.stdout.write(f"  source: {doc.title} (uploaded {doc.created_at:%Y-%m-%d})")

        self.stdout.write("")
        for row in plan.importable[: options["limit"]]:
            p = row.payload
            fan = f" ({len(p['parcels'])} records, shared group)" if len(p["parcels"]) > 1 else ""
            self.stdout.write(f"  + {p['source_locator']}: {row.summary}{fan}")
            if p.get("classification"):
                line = f"      {p['classification']}"
                self.stdout.write(self.style.WARNING("WARNING " + line.strip()) if p.get("warning") else line)
        if len(plan.importable) > options["limit"]:
            self.stdout.write(f"  … {len(plan.importable) - options['limit']} more")
        # Skips in full, never summarised: each is a row of the grower's sheet that will not
        # become a record until someone answers for it.
        for row in plan.skipped:
            label = row.payload.get("source_locator") or f"line {row.line}"
            self.stdout.write(self.style.WARNING(f"  - {label}: {row.reason}"))

        records = sum(len(r.payload["parcels"]) for r in plan.importable)
        self.stdout.write("")
        self.stdout.write(f"  {len(plan.importable)} rows → {records} records · {len(plan.skipped)} rows wait")

        if options["commit"]:
            # Two tags, both required. The file hash says the grower was shown THIS file; the plan
            # fingerprint says the farm still resolves it the same way. `build_plan` reads parcels
            # and seasons at call time, so a parcel created between the preview and the commit
            # would turn a row the grower saw refused into a record they never saw (review of
            # back #233).
            filed = GeneratedDocument.objects.filter(
                establishment=farm, source=PREVIEW_SOURCE, tags__contains=[batch_tag(batch)]
            )
            if not filed.exists():
                raise CommandError(
                    f"No filed preview for batch {batch}. Run with --file-preview, send the PDF to the grower, "
                    "and commit only the file they approved."
                )
            if not filed.filter(tags__contains=[plan_tag(fingerprint)]).exists():
                raise CommandError(
                    "The farm has changed since the preview (a parcel, a season or an earlier import), so "
                    "the same file would load differently now. Run --file-preview again and send the new "
                    "preview before committing."
                )
            result = execute(plan, farm, operator, batch)
            self.stdout.write(
                self.style.SUCCESS(f"Done. {result['created']} records written, {result['skipped']} rows waiting.")
            )
            return

        pdf = render_preview_pdf(plan, farm, documents, batch, operator)
        out = (
            Path(options["preview_out"])
            if options.get("preview_out")
            else (Path(tempfile.gettempdir()) / f"trazo-import-preview-{farm.id}-{batch}.pdf")
        )
        out.write_bytes(pdf)
        self.stdout.write(f"  preview: {out}")
        if options["file_preview"]:
            doc = file_document(
                establishment=farm,
                source=PREVIEW_SOURCE,
                folder="exports",
                title=f"Import preview {batch}, {len(plan.importable)} rows",
                filename=f"import-preview-{batch}.pdf",
                content=pdf,
                content_type="application/pdf",
                created_by=operator,
                tags=["import-preview", batch_tag(batch), plan_tag(fingerprint)],
            )
            if doc is None:
                raise CommandError("Filing the preview failed; see the log.")
            self.stdout.write(self.style.SUCCESS(f"  filed: {doc.title} ({doc.public_id})"))
        self.stdout.write(
            self.style.WARNING(
                "DRY RUN, nothing written. Send the preview; re-run with --commit once the grower answers ok."
            )
        )

    @staticmethod
    def _documents(plan, farm):
        ids = {r.payload.get("source_doc") for r in plan.rows if r.payload.get("source_doc")}
        valid = []
        for value in ids:
            try:
                valid.append(uuid.UUID(str(value)))
            except ValueError:
                continue
        return list(GeneratedDocument.objects.filter(establishment=farm, public_id__in=valid).order_by("created_at"))
