"""Remove the carbon entries weather records used to carry.

Weather records carry no carbon (owner decision 2026-10-21; see
`EventCarbonCalculator.calculate_weather_event_impact`). Saving a weather event already removes
its own entry (`history.signals`); this removes the rest in one pass.

A DRY RUN by default: it prints what it would remove, per company, and changes nothing.
`--apply` deletes, in one transaction. Take a database backup first: carbon totals shown to
growers and buyers drop by the amounts printed.

    poetry run python manage.py remove_weather_carbon_entries
    poetry run python manage.py remove_weather_carbon_entries --apply
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from carbon.models import CarbonEntry

# Every shape a weather event's entry was written in:
# - the save receiver (EventCarbonCalculator.create_carbon_entry_from_event): a
#   `REG-WeatherEvent-<id>` registry id, or `WeatherEvent(ID=<id>)` in the description;
# - the backfill and demo seeders (create_comprehensive_carbon_entries, seed_comprehensive_demo_v2):
#   "Auto-calculated from WeatherEvent: <method>". Their `REG-EVENT-<id>-<year>` id is no use
#   here, event ids repeat across event tables.
WEATHER_ENTRIES = (
    Q(activity__kind=0)  # linked to a weather activity (carbon/event_link.py)
    | Q(registry_verification_id__startswith="REG-WeatherEvent-")
    | Q(description__icontains="WeatherEvent(ID=")
    | Q(description__startswith="Auto-calculated from WeatherEvent")
)


class Command(BaseCommand):
    help = "Remove the carbon entries of weather records (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Delete the entries (default: dry run).")

    def handle(self, *args, **options):
        entries = CarbonEntry.objects.filter(WEATHER_ENTRIES).select_related("establishment__company")
        per_company = defaultdict(lambda: {"count": 0, "kg": 0.0})
        for entry in entries:
            company = entry.establishment.company.name if entry.establishment_id else "(no farm)"
            per_company[company]["count"] += 1
            per_company[company]["kg"] += entry.amount or 0.0

        total = sum(row["count"] for row in per_company.values())
        for company, row in sorted(per_company.items()):
            self.stdout.write(f"{company}: {row['count']} entries, {row['kg']:.2f} kg CO2e")
        self.stdout.write(f"Total: {total} weather carbon entries.")

        if not options["apply"]:
            self.stdout.write("Dry run: nothing removed. Re-run with --apply, after a backup.")
            return
        with transaction.atomic():
            deleted, per_model = entries.delete()
        # `deleted` also counts cascaded children (audit logs, compliance records); report the
        # entries themselves, the number the dry run printed.
        removed = per_model.get("carbon.CarbonEntry", deleted)
        self.stdout.write(self.style.SUCCESS(f"Removed {removed} weather carbon entries."))
