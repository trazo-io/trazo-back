"""Which activity a CarbonEntry was computed from (schema remodel plan, CarbonEntry slice).

Until 2026-11 a CarbonEntry named its event only in TEXT: the description
"Auto-calculated from <Class>(ID=<id>) event: <method>" (written since 2026-02-12) and, before
that, only the registry id "REG-<Class>-<id>". Readers matched that text with `icontains`, which
had four live defects (CarbonEntry audit, 2026-11-05):

- a pre-February card fell back to the season's newest entry whose description merely named the
  class, i.e. ANOTHER event's figure;
- the API lets a user write `description` and `registry_verification_id`, so an offset whose text
  says "ProductionEvent(ID=5)" became event 5's figure, and re-saving event 5 deleted it;
- the delete cleanup ignored the registry id, so REG-only entries outlived their event;
- duplicates resolved in a different order on each path.

`CarbonEntry.activity` is now the link, and readers go through `entries_for_event`. The text is
still written (it is shown and exported), and it is still how an UNLINKED row is linked, under
the strict rule in `named_event` + `linkable_q`, which the backfill migration
(carbon 0047) freezes a copy of and the census (`common/services/census.py`) reuses.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from django.db.models import Exists, OuterRef, Q

#: Exactly what `EventCarbonCalculator.create_carbon_entry_from_event` writes. Anchored: a
#: description that merely CONTAINS the pattern (a user's text, a suffix appended by a fix
#: command is fine because the prefix stays) names nothing.
AUTO_DESCRIPTION = re.compile(r"^Auto-calculated from ([A-Z][A-Za-z]+Event)\(ID=(\d+)\) event:")
#: What the same writer put in the description before 2026-02-12 (no id).
LEGACY_DESCRIPTION = re.compile(r"^Auto-calculated from ([A-Z][A-Za-z]+Event) event:")
REGISTRY_ID = re.compile(r"^REG-([A-Z][A-Za-z]+Event)-(\d+)$")

#: A row a user CREATED through the API: its text is the user's, so it proves nothing. Every API
#: creation path logs this action (CarbonEntryViewSet, both offset endpoints, the secure
#: serializer). An EDIT does not count: a row the writer created and a user later edited
#: (evidence, an audit date) is still that event's entry, and must be found, replaced on the
#: event's next save and removed with it (review of back #315).
USER_ACTIONS = ("create",)


def named_event(description: str, registry_id: str) -> Optional[Tuple[str, int]]:
    """The (model name, pk) the writer's text names, or None when it names none or disagrees.

    - the current shape: the description names it, and a registry id, if it has the writer's
      shape, must name the same event;
    - the pre-February shape: the registry id names it, unless the description is the writer's
      id-less sentence for ANOTHER class. The description is not required to have that shape: it
      is edited by fix commands and by hand (`recompute_soil_carbon` treats such a row as its
      event's, changed). A registry id a user wrote is excluded by `user_created`, not here.
    """
    described = AUTO_DESCRIPTION.match(description or "")
    registered = REGISTRY_ID.match(registry_id or "")
    if described:
        named = (described.group(1), int(described.group(2)))
        if registered and (registered.group(1), int(registered.group(2))) != named:
            return None
        return named
    if registered:
        legacy = LEGACY_DESCRIPTION.match(description or "")
        if legacy and legacy.group(1) != registered.group(1):
            return None
        return registered.group(1), int(registered.group(2))
    return None


def user_created():
    """Exists() over a user's create audit row for the outer CarbonEntry."""
    from carbon.models import CarbonAuditLog

    return Exists(
        CarbonAuditLog.objects.filter(carbon_entry=OuterRef("pk"), action__in=USER_ACTIONS, user__isnull=False)
    )


def _text_q(class_name: str, pk: int) -> Q:
    """Rows whose text has one of the writer's shapes for this event (prefilter for SQL)."""
    current = Q(description__startswith=f"Auto-calculated from {class_name}(ID={pk}) event:")
    return current | Q(registry_verification_id=f"REG-{class_name}-{pk}")


def unlinked_rows_naming(event):
    """UNLINKED entries the writer's text ties to this event, under the strict rule.

    Same production as the event, and never a row a user created through the API.
    """
    from carbon.models import CarbonEntry

    name = type(event).__name__
    candidates = (
        CarbonEntry.objects.filter(activity__isnull=True, production_id=event.history_id)
        .filter(_text_q(name, event.pk))
        .exclude(user_created())
        .values_list("pk", "description", "registry_verification_id")
    )
    return [pk for pk, d, r in candidates if named_event(d, r) == (name, event.pk)]


def entries_for_event(event, link: bool = True):
    """The CarbonEntry rows computed from this event: by the link, plus any unlinked straggler the
    strict rule ties to it.

    With `link` (signals, an applying command) the stragglers are linked first (`.update()`, the
    link only). With `link=False` (a dry run, a report) nothing is written.
    """
    from carbon.models import CarbonEntry

    activity_id = getattr(event, "activity_id", None)
    stragglers = unlinked_rows_naming(event)
    if activity_id is None:
        return CarbonEntry.objects.filter(pk__in=stragglers)
    if link:
        if stragglers:
            CarbonEntry.objects.filter(pk__in=stragglers, activity__isnull=True).update(activity_id=activity_id)
        return CarbonEntry.objects.filter(activity_id=activity_id)
    return CarbonEntry.objects.filter(Q(activity_id=activity_id) | Q(pk__in=stragglers))


def link_all_unlinked(apply: bool = True) -> dict:
    """Link every unlinked entry the strict rule ties to a live event. Idempotent.

    The same rule as migration carbon 0047, for the rows written between that migration and the
    code that sets the link (run `manage.py link_carbon_entries` after the deploy) and for rows a
    rollback restores. Returns counts; links nothing when `apply` is False.
    """
    from carbon.models import CarbonEntry
    from history.taxonomy import BY_MODEL_NAME

    rows = (
        CarbonEntry.objects.filter(activity__isnull=True)
        .filter(Q(description__startswith="Auto-calculated from ") | Q(registry_verification_id__startswith="REG-"))
        .annotate(created_by_user=user_created())
        .values_list("pk", "production_id", "description", "registry_verification_id", "created_by_user")
    )
    wanted, counts = {}, {"named": 0, "user_created": 0, "event_gone": 0, "other_production": 0, "linked": 0}
    for pk, production_id, description, registry_id, by_user in rows:
        named = named_event(description, registry_id)
        if named is None or named[0] not in BY_MODEL_NAME:
            continue
        counts["named"] += 1
        if by_user:
            counts["user_created"] += 1
            continue
        wanted.setdefault(named[0], []).append((pk, named[1], production_id))
    for name, items in wanted.items():
        model = BY_MODEL_NAME[name].model
        events = dict(
            (pk, (activity_id, history_id))
            for pk, activity_id, history_id in model.objects.filter(pk__in=[e for _, e, _ in items]).values_list(
                "pk", "activity_id", "history_id"
            )
        )
        for pk, event_pk, production_id in items:
            found = events.get(event_pk)
            if found is None or found[0] is None:
                counts["event_gone"] += 1
            elif found[1] != production_id:
                counts["other_production"] += 1
            else:
                counts["linked"] += 1
                if apply:
                    CarbonEntry.objects.filter(pk=pk, activity__isnull=True).update(activity_id=found[0])
    return counts
