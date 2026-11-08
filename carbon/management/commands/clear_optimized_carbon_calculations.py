"""Delete every OptimizedCarbonCalculation row, with a report that can put them all back.

`calculate-event-carbon/` wrote one row per uncached call: a performance log carrying the result's
self-assigned 0-100 `efficiency_score`, the retired score concept. Nothing ever read a row (no
view, serializer, admin, export or ranking query), and since the change that added this command
nothing writes one. Production held 471 on 2026-11-08. The model retires in the next migration,
which refuses to run while a row is left; this command empties the table first, through
`common/services/data_operations` so the rows are not lost:

    python manage.py clear_optimized_carbon_calculations --report /tmp/occ.json           # dry run
    python manage.py clear_optimized_carbon_calculations --report /tmp/occ-apply.json --apply
    python manage.py clear_optimized_carbon_calculations --report /tmp/occ-check.json      # 0 rows

Each row's "before" is a serialized copy of the whole row, so `--restore log:<id>` (the report text
lives on the DataOperationLog row; a container's disk does not survive a deploy) recreates every
row with its own primary key. That holds only until the retiring migration drops the model: after
it, `apps.get_model(MODEL)` cannot resolve and this command cannot restore anything. Restore, if at
all, BEFORE that migration ships (review of #347).
"""

from django.core import serializers
from django.core.management.base import BaseCommand, CommandError

from common.services import data_operations as ops

OPERATION = "clear_optimized_carbon_calculations"
MODEL = "carbon.OptimizedCarbonCalculation"


def plan():
    from django.apps import apps

    model = apps.get_model(MODEL)
    for row in model.objects.order_by("pk"):
        yield ops.RowChange(
            model=MODEL,
            pk=row.pk,
            before={"row": serializers.serialize("json", [row]), "_label": "stored"},
            after={"_label": "deleted"},
            reason="a performance log carrying a retired 0-100 score; nothing reads it",
        )


def write(model_label, pk, values):
    from django.apps import apps

    if model_label != MODEL:
        raise CommandError(f"{OPERATION} writes {MODEL} only, not {model_label}.")
    if "row" in values:  # restore: recreate the row with its own primary key
        for obj in serializers.deserialize("json", values["row"]):
            obj.save()
        return
    apps.get_model(model_label).objects.filter(pk=pk).delete()


class Command(BaseCommand):
    help = "Delete every OptimizedCarbonCalculation row (a retired score log). Dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--report", default="", help="Where to write the JSON report.")
        parser.add_argument("--apply", action="store_true", help="Delete the rows and log the operation.")
        parser.add_argument("--restore", default="", help="Recreate the rows from this report, or log:<id>.")
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
        for key, n in sorted(report.counts.items()):
            self.stdout.write(f"  {key}: {n}")
