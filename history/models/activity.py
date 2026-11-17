"""One identity per activity record, whatever table holds it."""

from django.db import models


class Activity(models.Model):
    """The identity of one activity record, whichever of the eight event tables holds it.

    `CommonEvent` is abstract, so each event table has its own id sequence and the same id can be
    a GeneralEvent, a ChemicalEvent and a ProductionEvent at once: the 2026-11 baseline census
    counted 100 such collisions in production, and six tables point at events only through a loose
    `(event_type, event_id)` pair no foreign key can check. An Activity row is the one identity a
    record has across tables, so those pairs (and CarbonEntry) can become real foreign keys.

    Additive by design (schema remodel plan): no event pk changes, so seals, the audit trail, raw
    CHECK constraints and every existing reference keep working. The id sequence starts at
    1,000,001 (migration 0250), above every event id in use, so an Activity id can never be
    mistaken for an event id of the same number.

    An Activity is never deleted. When its event is deleted it is marked `deleted_at` (a
    tombstone), so a correction or a confirmation that pointed at the record still resolves to
    "this record existed and was deleted" rather than to nothing, or to a reused id.
    """

    #: The event code (history/taxonomy.py): which table holds the record.
    kind = models.PositiveSmallIntegerField(db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "history_activity"

    def __str__(self) -> str:
        return f"Activity {self.pk} (kind {self.kind}{', deleted' if self.deleted_at else ''})"
