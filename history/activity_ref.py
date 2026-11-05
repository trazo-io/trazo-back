"""Resolve a loose `(event_type, event_id)` pair to the record's Activity identity.

Six tables point at an event only through such a pair (schema remodel plan). Each now carries a
real foreign key to `history.Activity` next to it, written by every writer. This is the one
lookup the writers that only hold the pair, and the save() safety nets, use.
"""

from __future__ import annotations

from typing import Optional

from history.taxonomy import BY_CODE


def activity_id_for(event_type, event_id) -> Optional[int]:
    """The Activity id of event `event_id` in table `event_type`, or None when it does not exist.

    None, never a guess: a pair whose event is gone stays unlinked, and the census counts it.
    """
    if event_type is None or event_id is None:
        return None
    kind = BY_CODE.get(int(event_type))
    if kind is None:
        return None
    return kind.model.objects.filter(pk=event_id).values_list("activity_id", flat=True).first()


def sync_activity_link(instance, type_attr: str, id_attr: str, fk_attname: str) -> None:
    """Set `instance.<fk_attname>` from its pair before a save, without losing a tombstone link.

    - The pair is empty: no link.
    - The pair names a live event: that event's identity.
    - The pair names no live event: if the pair is the one already stored, keep the link. The
      event was deleted after the link was written, and the link now names its tombstone, which
      is exactly what the identity table exists to keep (review of back #306: re-deriving here
      nulled it on the next PATCH of a document's title). If the pair changed to one that names
      nothing, there is nothing to link.
    """
    event_type, event_id = getattr(instance, type_attr), getattr(instance, id_attr)
    if event_type is None or event_id is None:
        setattr(instance, fk_attname, None)
        return
    resolved = activity_id_for(event_type, event_id)
    if resolved is not None:
        setattr(instance, fk_attname, resolved)
        return
    if instance.pk is not None:
        stored = type(instance).objects.filter(pk=instance.pk).values_list(type_attr, id_attr).first()
        if stored == (event_type, event_id):
            return  # unchanged pair, deleted event: keep the tombstone link
    setattr(instance, fk_attname, None)
