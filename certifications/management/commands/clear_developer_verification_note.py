"""Clear the developer instruction that an empty USDA Organic Integrity Database once wrote
into `Certification.verification_notes` (recordkeeping review F-26, 2026-10-07).

`reevaluate_certification_verification` cannot do this (review of back #139): it refuses to run
while the database is empty, the very condition that wrote the note, and it only re-plans rows
already `verified`. This operation rewrites exactly the rows that hold the old string, through
`common.services.data_operations`: dry run by default, `--apply` to save, `--restore <report>`
to put the old text back.
"""

from django.core.management.base import BaseCommand, CommandError

from certifications.verification_notes import render
from common.services import data_operations as ops

OPERATION = "clear_developer_verification_note"
OLD_NOTE = "USDA Organic Integrity Database not loaded. Run: python manage.py import_usda_organic_data"
NEW_NOTE = render("not_loaded")


def plan():
    from certifications.models import Certification

    for cert in Certification.objects.filter(verification_notes__contains="import_usda_organic_data").order_by("pk"):
        yield ops.RowChange(
            model="certifications.Certification",
            pk=cert.pk,
            before={"verification_notes": cert.verification_notes, "_label": "developer_note"},
            after={"verification_notes": NEW_NOTE, "_label": "grower_note"},
            reason="an operator instruction was stored as the certificate's verification note",
        )


def write(model_label, pk, values):
    from django.apps import apps

    apps.get_model(model_label).objects.filter(pk=pk).update(**values)


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--report", default="", help="Where to write the JSON report.")
        parser.add_argument("--apply", action="store_true", help="Save the changes and log the operation.")
        parser.add_argument("--restore", default="", help="Put back the 'before' state from this report.")
        parser.add_argument("--run-by", default="", help="Who ran it, recorded in the log.")

    def handle(self, *args, **options):
        if options["restore"]:
            report = ops.restore(
                operation=OPERATION, report_path=options["restore"], write=write, run_by=options["run_by"]
            )
            self.stdout.write(f"Restored {len(report.changes)} row(s) from {options['restore']}.")
            return
        if not options["report"]:
            raise CommandError("Give --report <path>: the report is the record of what changed and the rollback.")
        report = ops.run(
            operation=OPERATION,
            plan=plan,
            write=write,
            report_path=options["report"],
            apply=options["apply"],
            run_by=options["run_by"],
        )
        mode = "Applied" if options["apply"] else "Dry run, nothing saved"
        self.stdout.write(f"{mode}: {len(report.changes)} row(s) would change. Report: {options['report']}")
