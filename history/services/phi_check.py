"""
A pick that came sooner after a spray than the pre-harvest interval (PHI) the operation recorded.

WHY (2026-11-05): a spray's PHI was printed beside it (the audit chemical log, the CSV) and compared
with a pick in exactly one place, the sale trace (`traceback._set_days_to_pick`), for the picks on
the one sale being traced. Nothing compared a season's picks with its sprays when a record was
saved, or on the season's readiness card, so a pick inside a PHI was found by an inspector reading
dates side by side, if at all.

What this is, and is not:
  * arithmetic on the operation's own dates against the PHI the operation itself recorded; never a
    reading of the label, and never a verdict on residue or safety;
  * a pick on the same production (`History`), on or after the spray, sooner than its PHI;
  * a pick on another block does not count when both records name a block (the sale trace's rule);
  * an application with no PHI recorded, or a PHI of zero, has nothing to compare and is skipped,
    never reported as "inside";
  * buffer-row picks (`BU`) count: the PHI is about the crop picked, whatever it is sold as.

`inside_phi` is the one predicate; the sale trace uses it too, so the two cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

#: The readiness row's label. Its citation is FIFRA's, not the organic rule's: the PHI is a term of the
#: product's labeling (7 U.S.C. § 136j(a)(2)(G)).
PHI_ROW_LABEL = "Pre-harvest intervals (7 U.S.C. § 136j(a)(2)(G))"

#: Production event types that are a pick: a harvest, and a harvest of buffer rows (§ 205.202(c)).
PICK_TYPES = ("HA", "BU")


def inside_phi(days_after: int | None, phi_days) -> bool:
    """True when a pick `days_after` the spray came sooner than the recorded PHI."""
    if days_after is None or phi_days in (None, ""):
        return False
    phi = Decimal(str(phi_days))
    return phi > 0 and 0 <= days_after < phi


def _day(value) -> date | None:
    """The calendar day of an event's date. A `datetime` is also a `date`, so it is tested first. Read
    on the server's clock (UTC), the same day the sale trace's `_iso` prints, so the two agree."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.date()
    return value


@dataclass(frozen=True)
class PhiConflict:
    application_id: int
    pick_id: int
    product: str
    applied: date
    phi_days: Decimal
    picked: date
    days: int

    def as_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "pick_id": self.pick_id,
            "product": self.product,
            "applied": self.applied.isoformat(),
            "phi_days": format(self.phi_days.normalize(), "f"),
            "picked": self.picked.isoformat(),
            "days": self.days,
        }


def _blocks_differ(a, b) -> bool:
    a = (a or "").strip() if isinstance(a, str) else a
    b = (b or "").strip() if isinstance(b, str) else b
    return bool(a) and bool(b) and a != b


def season_conflicts(history, *, application=None, pick=None) -> list[PhiConflict]:
    """Every pick on `history` inside the PHI of a spray on it, earliest spray first.

    `application` or `pick` narrows to the pairs that one just-saved record takes part in, which is
    what the save response reports.
    """
    from history.models import ChemicalEvent, ProductionEvent

    sprays = ChemicalEvent.objects.filter(history=history, phi_days__gt=0).order_by("date", "pk")
    picks = list(ProductionEvent.objects.filter(history=history, type__in=PICK_TYPES).order_by("date", "pk"))
    if application is not None:
        sprays = sprays.filter(pk=application.pk)
    if pick is not None:
        picks = [p for p in picks if p.pk == pick.pk]
    out = []
    for spray in sprays:
        applied = _day(spray.date)
        if applied is None:
            continue
        for p in picks:
            picked = _day(p.date)
            if picked is None or _blocks_differ(spray.block_id, p.block_id):
                continue
            days = (picked - applied).days
            if inside_phi(days, spray.phi_days):
                out.append(
                    PhiConflict(
                        application_id=spray.pk,
                        pick_id=p.pk,
                        product=(spray.commercial_name or "").strip() or "an application with no product name",
                        applied=applied,
                        phi_days=Decimal(str(spray.phi_days)),
                        picked=picked,
                        days=days,
                    )
                )
    return out


def conflicts_for_saved(event) -> list[dict] | None:
    """The PHI conflicts a just-saved record takes part in, for the save response; None for a record
    that is neither a spray nor a pick, so the response carries no key for it."""
    from history.models import ChemicalEvent, ProductionEvent

    history = getattr(event, "history", None)
    if history is None:
        return None
    if isinstance(event, ChemicalEvent):
        found = season_conflicts(history, application=event)
    elif isinstance(event, ProductionEvent) and event.type in PICK_TYPES:
        found = season_conflicts(history, pick=event)
    else:
        return None
    return [c.as_dict() for c in found]
