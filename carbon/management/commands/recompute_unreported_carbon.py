"""Re-check stored production-event carbon against the run-8 rule: unknown is not zero.

Run 8 (R8-04, 2026-10-05): a cleanout saved with no fuel showed 129 kg CO2e, because the
calculator borrowed the parcel's area and charged a per-hectare diesel estimate on it; other
records with nothing reported were stored as 0. The calculator now answers `not_estimated` when
the record holds nothing to count from, and marks per-hectare figures `area_estimate`. Entries
stored under the old rule keep their numbers until this command re-checks them.

For every production event:
  * the calculator now says `not_estimated` and an entry exists: the entry (with every row
    that would be deleted with it) is removed and the event carries `not_estimated`;
  * the figure is a per-hectare estimate and the entry still reads as factor-based: it is
    re-labelled `area_estimate` and loses the EPA/USDA flag.

Dry run by default: a JSON report of every change, nothing saved. `--apply` saves and logs a
`DataOperationLog` row; a second dry run then reports nothing; `--restore <report>` puts every
row back, the deleted entries and their dependent rows included. See
`common/services/data_operations.py`.

    manage.py recompute_unreported_carbon --report /tmp/r8-carbon.json
    manage.py recompute_unreported_carbon --report /tmp/r8-carbon.json --apply
    manage.py recompute_unreported_carbon --restore /tmp/r8-carbon.json
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from common.services import data_operations as ops

OPERATION = "r8_recompute_unreported_carbon"


def _entries_for(event):
    from carbon.models import CarbonEntry

    by_pattern = CarbonEntry.objects.filter(
        production=event.history, description__icontains=f"ProductionEvent(ID={event.id})"
    )
    if by_pattern.exists():
        return by_pattern
    return CarbonEntry.objects.filter(
        production=event.history, registry_verification_id=f"REG-ProductionEvent-{event.id}"
    )


def _dump_with_dependents(queryset) -> str:
    """The entries and every row Django would delete with them, as fixture JSON."""
    from django.core import serializers
    from django.db.models.deletion import Collector

    collector = Collector(using=queryset.db)
    collector.collect(list(queryset))
    rows = [obj for model_rows in collector.data.values() for obj in model_rows]
    return serializers.serialize("json", rows)


def plan():
    from carbon.services.event_carbon_calculator import EventCarbonCalculator
    from history.models import ProductionEvent

    calculator = EventCarbonCalculator()
    for event in ProductionEvent.objects.select_related("history__parcel").order_by("pk"):
        if not event.history_id:
            continue
        result = calculator.calculate_production_event_impact(event)
        entries = _entries_for(event)
        current_status = (event.extra_data or {}).get("carbon_calculation")
        if result.get("not_estimated"):
            if not entries.exists() and isinstance(current_status, dict) and current_status.get("co2e") is None:
                continue
            yield ops.RowChange(
                model="history.ProductionEvent",
                pk=event.pk,
                before={
                    "carbon_entries_fixture": _dump_with_dependents(entries),
                    "carbon_calculation": current_status,
                    "_label": "stored_figure",
                    "_amounts": [e.amount for e in entries],
                },
                after={
                    "carbon_entries_fixture": "[]",
                    "carbon_calculation": {
                        "co2e": None,
                        "calculation_method": "not_estimated",
                        "calculation_basis": "not_estimated",
                        "verification_status": "not_estimated",
                        "usda_factors_based": False,
                        "reason": result.get("limitations", ""),
                    },
                    "_label": "not_estimated",
                },
                reason=result.get("limitations", "") or "nothing recorded to count from",
            )
        elif result.get("verification_status") == "area_estimate":
            for entry in entries.exclude(verification_status="area_estimate"):
                yield ops.RowChange(
                    model="carbon.CarbonEntry",
                    pk=entry.pk,
                    before={
                        "verification_status": entry.verification_status,
                        "usda_factors_based": entry.usda_factors_based,
                        "_label": "factor_based",
                    },
                    after={
                        "verification_status": "area_estimate",
                        "usda_factors_based": False,
                        "_label": "area_estimate",
                    },
                    reason="per-hectare estimate from the recorded area; no fuel recorded",
                )


def write(model_label, pk, values):
    from django.apps import apps
    from django.core import serializers

    if model_label == "carbon.CarbonEntry":
        apps.get_model(model_label).objects.filter(pk=pk).update(**values)
        return
    event_model = apps.get_model(model_label)
    event = event_model.objects.get(pk=pk)
    _entries_for(event).delete()
    for obj in serializers.deserialize("json", values["carbon_entries_fixture"]):
        obj.save()
    extra = dict(event.extra_data or {})
    if values.get("carbon_calculation") is None:
        extra.pop("carbon_calculation", None)
    else:
        extra["carbon_calculation"] = values["carbon_calculation"]
    event_model.objects.filter(pk=pk).update(extra_data=extra)


class Command(BaseCommand):
    help = "Re-check stored production-event carbon: not_estimated and area_estimate. Dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--report", default="", help="Where to write the JSON report.")
        parser.add_argument("--apply", action="store_true", help="Save the changes and log the operation.")
        parser.add_argument("--restore", default="", help="Put back the 'before' state from this report.")
        parser.add_argument("--run-by", default="", help="Who ran it, recorded in the log.")

    def handle(self, *args, **options):
        if options["restore"]:
            report = ops.restore(report_path=options["restore"], write=write, run_by=options["run_by"])
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
