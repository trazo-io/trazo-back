"""Put every retired CarbonEntry column back to its default (carbon/retired_columns.py).

Run once after the deploy that stops writing them, and before the deploy that drops them:

    python manage.py clear_retired_carbon_columns --report /tmp/retire.json
    python manage.py clear_retired_carbon_columns --report /tmp/retire-apply.json --apply
    python manage.py clear_retired_carbon_columns --report /tmp/retire-check.json   # 0 rows

Through `common.services.data_operations`: the applied report lists each cleared value and is
stored on its `DataOperationLog` row, so `--restore log:<id>` puts them back after the container
that wrote the file is gone. Only the retired columns are written (`.update()`: no save, no
signal, no `auto_now`), and no CarbonEntry is created or deleted.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from carbon.retired_columns import RETIRED_CARBON_ENTRY_COLUMNS
from common.services import data_operations as ops

OPERATION = "clear_retired_carbon_columns"
MODEL = "carbon.CarbonEntry"


def holding_a_value():
    """Rows where at least one retired column differs from its default."""
    condition = Q()
    for column, empty in RETIRED_CARBON_ENTRY_COLUMNS.items():
        condition |= ~Q(**{column: empty})
    return condition


def plan():
    from carbon.models import CarbonEntry

    columns = list(RETIRED_CARBON_ENTRY_COLUMNS)
    for row in CarbonEntry.objects.filter(holding_a_value()).order_by("pk").values("pk", *columns):
        held = {c: row[c] for c in columns if row[c] != RETIRED_CARBON_ENTRY_COLUMNS[c]}
        if not held:
            continue
        yield ops.RowChange(
            model=MODEL,
            pk=row["pk"],
            before=held,
            after={c: RETIRED_CARBON_ENTRY_COLUMNS[c] for c in held},
            reason="retired column: no reader, dropped by the next migration",
        )


def write(model_label, pk, values):
    from django.apps import apps

    unknown = set(values) - set(RETIRED_CARBON_ENTRY_COLUMNS)
    if model_label != MODEL or unknown:
        raise CommandError(f"refusing to write {model_label} {sorted(unknown)}: not a retired CarbonEntry column")
    apps.get_model(model_label).objects.filter(pk=pk).update(**values)


class Command(BaseCommand):
    help = "Reset the retired CarbonEntry columns to their defaults (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--report", default="", help="Where to write the JSON report.")
        parser.add_argument("--apply", action="store_true", help="Save the changes and log the operation.")
        parser.add_argument("--restore", default="", help="Put the values back from this report, or log:<id>.")
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
        per_column = {}
        for change in report.changes:
            for column in change.before:
                per_column[column] = per_column.get(column, 0) + 1
        mode = "Applied" if options["apply"] else "Dry run, nothing saved"
        self.stdout.write(f"{mode}: {len(report.changes)} row(s). Values per column: {per_column or 'none'}.")
        self.stdout.write(f"Report: {options['report']}")
        if options["apply"] and report.changes:
            from common.models import DataOperationLog

            log = DataOperationLog.objects.filter(operation=OPERATION).order_by("-pk").first()
            self.stdout.write(f"Logged as DataOperationLog {log.pk}; restore with --restore log:{log.pk}")
