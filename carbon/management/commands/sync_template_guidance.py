"""Bring stored template wording in line with the seeder, row by stable identity (run 8, R8-23).

`create_comprehensive_production_templates_v2` only ever creates rows (`get_or_create`), so a
wording fix in its definitions never reaches a database that already has the templates. Run 8
found guidance there that stated rules the regulation does not ("NOP limits copper to 3
lb/acre/year"), blanket "NOP approved / compliant" claims, "Third-party verified" consumer
messages and a USDA-verified factor claim. This command updates existing rows to the seeder's
current definitions.

Identity, never text: an EventTemplate is found by (production template slug, `template_key`);
a ProductionTemplate by its slug. A row whose wording changes gets `content_version + 1`.
Season-plan items keep the name and description they copied when they were built, and record
the version they came from; nothing here edits them.

Dry run by default with a per-row JSON report; `--apply` saves and logs a DataOperationLog row;
a second dry run reports nothing; `--restore <report>` puts the previous wording back. See
`common/services/data_operations.py`.

    manage.py sync_template_guidance --report /tmp/r8-templates.json
    manage.py sync_template_guidance --report /tmp/r8-templates.json --apply
    manage.py sync_template_guidance --report /tmp/r8-templates-check.json   # expect 0 changes; never reuse the applied report's path
    manage.py sync_template_guidance --restore /tmp/r8-templates.json
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from common.services import data_operations as ops

OPERATION = "r8_sync_template_guidance"

#: Wording fields only. Measurements, ordering and carbon data are not this command's business.
EVENT_FIELDS = ("description", "efficiency_tips", "consumer_message", "backend_event_fields")
TEMPLATE_FIELDS = ("description", "compliance_notes", "premium_pricing_potential")


def _canon(value):
    return json.dumps(value, sort_keys=True, default=str)


def _definitions():
    """(template slug, template defaults, event definitions) for every template the seeder makes."""
    from carbon.management.commands import create_comprehensive_production_templates_v2 as seeder
    from carbon.models import CropType

    for crop_type in CropType.objects.filter(is_active=True).order_by("slug"):
        crop_data = seeder.CROP_CUSTOMIZATIONS.get(crop_type.slug)
        if crop_data is None:
            continue
        yield (
            f"{crop_type.slug}_conventional_v3",
            seeder.conventional_template_defaults(crop_type, crop_data),
            seeder.conventional_events_for(crop_type, crop_data),
        )
        overrides = seeder.ORGANIC_OVERRIDES.get(crop_type.slug)
        if overrides:
            yield (
                f"{crop_type.slug}_organic_v3",
                seeder.organic_template_defaults(crop_type),
                seeder.organic_events_for(crop_type, crop_data, overrides),
            )


def plan():
    from carbon.management.commands.create_comprehensive_production_templates_v2 import template_key_for
    from carbon.models import EventTemplate, ProductionTemplate

    for slug, template_defaults, events in _definitions():
        template = ProductionTemplate.objects.filter(slug=slug).first()
        if template is None:
            continue  # creating templates is the seeder's job, not this command's
        before = {f: getattr(template, f) for f in TEMPLATE_FIELDS}
        after = {f: template_defaults.get(f, before[f]) for f in TEMPLATE_FIELDS}
        if _canon(before) != _canon(after):
            yield ops.RowChange(
                model="carbon.ProductionTemplate",
                pk=template.pk,
                before={**before, "_label": slug},
                after={**after, "_label": slug},
                reason="template wording differs from the seeder's current definition",
            )
        for event_data in events:
            key = template_key_for(event_data)
            row = EventTemplate.objects.filter(production_template=template, template_key=key).first()
            if row is None:
                continue
            before = {f: getattr(row, f) for f in EVENT_FIELDS}
            after = {f: event_data.get(f, before[f]) for f in EVENT_FIELDS}
            if _canon(before) == _canon(after):
                continue
            yield ops.RowChange(
                model="carbon.EventTemplate",
                pk=row.pk,
                before={**before, "content_version": row.content_version, "_label": f"{slug}/{key}"},
                after={**after, "content_version": row.content_version + 1, "_label": f"{slug}/{key}"},
                reason="event wording differs from the seeder's current definition",
            )


def write(model_label, pk, values):
    from django.apps import apps

    apps.get_model(model_label).objects.filter(pk=pk).update(**values)


class Command(BaseCommand):
    help = "Update stored template wording to the seeder's, by template_key. Dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--report", default="", help="Where to write the JSON report.")
        parser.add_argument("--apply", action="store_true", help="Save the changes and log the operation.")
        parser.add_argument("--restore", default="", help="Put back the previous wording from this report.")
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
