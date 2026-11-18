"""Put every retired SoilManagementEvent column back to NULL (history/retired_columns.py).

Run once after the deploy that stops reading and writing them, and before the deploy that takes
them out of the model:

    poetry run python manage.py clear_retired_soil_columns --report /tmp/soil-retire.json
    poetry run python manage.py clear_retired_soil_columns --report /tmp/soil-retire-apply.json --apply
    poetry run python manage.py clear_retired_soil_columns --report /tmp/soil-retire-check.json   # 0 rows

The DigitalOcean console has no Poetry: there, run the same lines as `python manage.py ...`.

Through `common.services.data_operations`: the applied report lists each cleared value and is
stored on its `DataOperationLog` row, so `--restore log:<id>` puts them back after the container
that wrote the file is gone. Only the retired columns are written (`.update()`: no save, no
signal, no carbon recalculation, no `auto_now`), and no event is created or deleted. The seal
hashes do not read these columns, so no seal changes.

Corrections (EventAmendment) that once targeted a retired column are not touched: they keep the
old and new value as text, and the dry run counts them so the record of them is visible.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from common.services import data_operations as ops
from history.retired_columns import RETIRED_SOIL_EVENT_COLUMNS

OPERATION = "clear_retired_soil_columns"
MODEL = "history.SoilManagementEvent"


def holding_a_value():
    """Rows where at least one retired column differs from its empty value."""
    condition = Q()
    for column, empty in RETIRED_SOIL_EVENT_COLUMNS.items():
        condition |= Q(**{f"{column}__isnull": False}) if empty is None else ~Q(**{column: empty})
    return condition


def plan():
    from history.models import SoilManagementEvent

    columns = list(RETIRED_SOIL_EVENT_COLUMNS)
    rows = SoilManagementEvent.objects.filter(holding_a_value()).order_by("pk").values("pk", *columns)
    for row in rows:
        held = {c: row[c] for c in columns if row[c] != RETIRED_SOIL_EVENT_COLUMNS[c]}
        if not held:
            continue
        yield ops.RowChange(
            model=MODEL,
            pk=row["pk"],
            before=held,
            after={c: RETIRED_SOIL_EVENT_COLUMNS[c] for c in held},
            reason="retired column: modelled figure with no reader, dropped by a later migration",
        )


def write(model_label, pk, values):
    from django.apps import apps

    unknown = set(values) - set(RETIRED_SOIL_EVENT_COLUMNS)
    if model_label != MODEL or unknown:
        raise CommandError(f"refusing to write {model_label} {sorted(unknown)}: not a retired soil event column")
    apps.get_model(model_label).objects.filter(pk=pk).update(**values)


def amendments_naming_a_retired_column():
    from history.models import EventAmendment

    return EventAmendment.objects.filter(field_name__in=list(RETIRED_SOIL_EVENT_COLUMNS)).count()


class Command(BaseCommand):
    help = "Reset the retired SoilManagementEvent columns to NULL (dry run unless --apply)."

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
        self.stdout.write(
            f"Corrections naming a retired column (left as they are): {amendments_naming_a_retired_column()}"
        )
        self.stdout.write(f"Report: {options['report']}")
        if options["apply"] and report.changes:
            from common.models import DataOperationLog

            log = DataOperationLog.objects.filter(operation=OPERATION).order_by("-pk").first()
            self.stdout.write(f"Logged as DataOperationLog {log.pk}; restore with --restore log:{log.pk}")
