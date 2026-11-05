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
