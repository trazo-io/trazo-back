"""
Clone an existing production (History) and all its events, marking the clone as finished+published.

Usage:
    poetry run python manage.py clone_production <production_id> [--name "Clone Name"]

This creates a duplicate production with:
- All events cloned (all 8 event types)
- finish_date set to now
- published=True (visible on consumer ProductDetail page)
- Original production untouched
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from history.models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    History,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)

EVENT_MODELS = [
    ("weather", WeatherEvent, "history_weatherevent_events"),
    ("chemical", ChemicalEvent, "history_chemicalevent_events"),
    ("production", ProductionEvent, "history_productionevent_events"),
    ("general", GeneralEvent, "history_generalevent_events"),
    ("equipment", EquipmentEvent, "history_equipmentevent_events"),
    ("soil_management", SoilManagementEvent, "history_soilmanagementevent_events"),
    ("pest_management", PestManagementEvent, "history_pestmanagementevent_events"),
    ("business", BusinessEvent, "history_businessevent_events"),
]


class Command(BaseCommand):
    help = "Clone a production with all events and mark as finished+published"

    def add_arguments(self, parser):
        parser.add_argument("production_id", type=int, help="ID of the production to clone")
        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="Name for the cloned production (default: original name + ' [Test Clone]')",
        )

    def handle(self, *args, **options):
        production_id = options["production_id"]

        try:
            original = History.objects.get(pk=production_id)
        except History.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Production {production_id} not found"))
            return

        parcel_name = original.parcel.name if original.parcel else "Unknown"
        self.stdout.write(f"Cloning production #{original.pk}: {original.name} (Parcel: {parcel_name})")

        # Clone the History object
        clone = History()
        for field in original._meta.fields:
            # `public_id` is the QR identity and unique: the clone mints its own (copying it made
            # every clone fail with a duplicate key).
            if field.name in ("id", "public_id"):
                continue
            setattr(clone, field.name, getattr(original, field.name))

        # Set clone-specific fields
        clone.name = options["name"] or f"{original.name or 'Production'} [Test Clone]"
        clone.finish_date = timezone.now()
        clone.published = True
        clone.public_views = 0
        clone.unique_visitors = 0
        # Don't copy the album FK to avoid shared references
        clone.album = original.album
        clone.save()

        self.stdout.write(self.style.SUCCESS(f"  Created clone #{clone.pk}: {clone.name}"))

        # Clone all events
        total_events = 0
        for label, model_class, related_name in EVENT_MODELS:
            events = getattr(original, related_name).all()
            count = events.count()
            if count == 0:
                continue

            for event in events:
                clone_event = model_class()
                for field in event._meta.fields:
                    # A clone is a new record: it gets its own identity (Activity) on save.
                    if field.name in ("id", "activity"):
                        continue
                    setattr(clone_event, field.name, getattr(event, field.name))
                clone_event.history = clone
                # Share the same album (photos) - no need to duplicate images
                clone_event.save()

            total_events += count

        # The clone carries the original's seal, a hash over the ORIGINAL's events, which can
        # never verify over the clones (the QR page reads it as tampered). Seal it over its own.
        if isinstance(clone.extra_data, dict) and clone.extra_data.get("finalization_hash"):
            from history.seals import seal

            seal(clone)
            self.stdout.write(f"  Cloned {count} {label} event(s)")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone! Clone #{clone.pk} created with {total_events} events.\n"
                f"  - finished: {clone.finish_date}\n"
                f"  - published: {clone.published}\n"
                f"  - Consumer URL: /production/{clone.pk}"
            )
        )
