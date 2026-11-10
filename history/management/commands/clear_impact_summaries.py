"""Delete every stored `UserImpactSummary` row, so history 0256 can retire the model.

The signed-in consumer dashboard counts a shopper's scans live since 2026-11-10 and no longer
reads or writes these rows. What a row held was either derivable from the shopper's scans (scan
and review counts, first and last scan dates) or a retired claim: `total_carbon_offset_kg` (the
scanned seasons' emissions, labelled as an offset), `miles_driving_offset`, `trees_equivalent`,
`sustainable_farms_found`, `better_choices_made`, and seeded points, levels and achievements.

Through `common.services.data_operations`: dry run by default, `--apply` deletes the rows and logs
every column of every row in the report stored on the `DataOperationLog` row, `--restore
log:<id>` puts them back with their stored values (`last_updated` included). Restoring works
until 0256 takes the model out of the state; after that the report stays on the log row.
"""

from django.core.management.base import BaseCommand, CommandError

from common.services import data_operations as ops

OPERATION = "clear_impact_summaries"
MODEL = "history.UserImpactSummary"


def _columns(row):
    return {f.attname: getattr(row, f.attname) for f in row._meta.concrete_fields if not f.primary_key}


def plan():
    from history.models_consumer import UserImpactSummary

    for row in UserImpactSummary.objects.order_by("pk"):
        yield ops.RowChange(
            model=MODEL,
            pk=row.pk,
            before={**_columns(row), "_label": "stored"},
            after={"_label": "deleted"},
            reason="a cache of counts derivable from the shopper's scans plus retired claim fields; "
            "the model retires in history 0256",
        )


def write(model_label, pk, values):
    """No values deletes the row; values put it back exactly as the report holds it."""
    from django.apps import apps

    model = apps.get_model(model_label)
    if not values:
        model.objects.filter(pk=pk).delete()
        return
    if not model.objects.filter(pk=pk).exists():
        model.objects.create(pk=pk, **values)
    # `update()` skips `auto_now`, so `last_updated` comes back as stored, not as now.
    model.objects.filter(pk=pk).update(**values)


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--report", default="", help="Where to write the JSON report.")
        parser.add_argument("--apply", action="store_true", help="Delete the rows and log the operation.")
        parser.add_argument("--restore", default="", help="Put the rows back from this report, or log:<id>.")
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
