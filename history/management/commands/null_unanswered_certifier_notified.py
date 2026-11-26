"""Store "not answered" for the certifier question the old switch could not leave blank (OV-RK-C15).

Until history 0268 (2026-11-26) `GeneralEvent.certifier_notified` was non-null with
`default=False`, and the incident form asked it with a switch that read as off when nobody
touched it. A stored False with no notification date is therefore unknown: the record does not
say whether the grower answered No or never answered. Trazo's rule for an unknown is null, never
a default, so this operation rewrites those rows to None, and the dossier prints "Not answered"
for them instead of "No".

Rows it leaves alone: True (an answer), and False with a notification date (contradictory, and
not this operation's to resolve). A False saved after the release by the three-answer form is a
real No that this criterion cannot tell apart from an old one, which is why the dry-run report
lists every row with its event date and farm for review before `--apply`.

Through `common.services.data_operations`: dry run by default, `--apply` to save and log,
`--restore <report>` or `--restore log:<id>` to put the False values back.
"""

from django.core.management.base import BaseCommand, CommandError

from common.services import data_operations as ops

OPERATION = "null_unanswered_certifier_notified"


def plan():
    from history.models import GeneralEvent

    rows = (
        GeneralEvent.objects.filter(certifier_notified=False, certifier_notification_date__isnull=True)
        .select_related("history__parcel__establishment")
        .order_by("pk")
    )
    for ev in rows:
        parcel = getattr(ev.history, "parcel", None) if ev.history_id else None
        establishment = getattr(parcel, "establishment", None) if parcel else None
        yield ops.RowChange(
            model="history.GeneralEvent",
            pk=ev.pk,
            before={
                "certifier_notified": False,
                "_incident": bool(ev.is_contamination_incident),
                "_event_date": ev.date.date().isoformat() if ev.date else None,
                "_establishment": getattr(establishment, "name", None),
            },
            after={"certifier_notified": None},
            reason=(
                "a contamination incident whose certifier question was saved by the old switch: unknown, not No"
                if ev.is_contamination_incident
                else "not an incident: the False was the column default, never an answer"
            ),
        )


def write(model_label, pk, values):
    from django.apps import apps

    apps.get_model(model_label).objects.filter(pk=pk).update(**values)


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--report", default="", help="Where to write the JSON report.")
        parser.add_argument("--apply", action="store_true", help="Save the changes and log the operation.")
        parser.add_argument("--restore", default="", help="Put back the 'before' state from this report or log:<id>.")
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
        incidents = sum(1 for c in report.changes if c.before.get("_incident"))
        mode = "Applied" if options["apply"] else "Dry run, nothing saved"
        self.stdout.write(
            f"{mode}: {len(report.changes)} row(s) would change ({incidents} contamination incident(s), "
            f"{len(report.changes) - incidents} other general event(s)). Report: {options['report']}"
        )
