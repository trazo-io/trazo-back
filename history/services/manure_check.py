"""
A pick that came sooner after a raw manure application than the harvest interval of 7 CFR 205.203(c)(1).

WHY (2026-11-15, overall review OV-RK-C02): the conformance register said the 90/120-day rule was
enforced from the harvest side, by `ProductionEvent._validate_raw_manure_harvest_interval`. That runs
only from the model's `clean()`, which no API save calls, so a harvest logged inside the interval was
compared with the manure date nowhere. The audit export compared the interval with the harvest date
the grower PLANNED on the soil record, never with the harvests recorded.

What this is, and is not:
  * arithmetic on the operation's own dates: a pick on or after a raw manure application on the same
    parcel, sooner than the interval; never a verdict on pathogens or food safety;
  * the parcel, not the production: manure spread in the fall under one season counts against a pick
    the next summer under another;
  * a pick on another block does not count when both records name a block (`phi_check`'s rule);
  * raw means neither compost shown to meet § 205.203(c)(2) nor documented NOP 5006 processed manure.
    A record labelled composted is exempt only with its C:N, temperature and method time inside the
    rule, as the model's old harvest check read it, or when it names a supplier or product (bought
    compost, whose figures are the supplier's, as the audit export reads it). A label alone is not
    evidence (review of back #446): undocumented "composted" or "processed" manure is read as raw, and
    the conflict says how it was recorded;
  * the interval is the longer of the wait the operation recorded on the manure record and the crop's
    minimum (`manure_interval.minimum_interval_days`): a farm that keeps 120 days on a tree crop is held
    to its own record, and a recorded wait shorter than the minimum never lowers it;
  * never refuses a record. A harvest that happened is a record (§ 205.103); the save response and the
    audit export say which pick and which application, so a mistyped date can be fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from history.services.phi_check import PICK_TYPES, _blocks_differ, _day


@dataclass(frozen=True)
class ManureConflict:
    application_id: int
    pick_id: int
    applied: date
    picked: date
    days: int
    interval_days: int
    #: How the manure record labels itself when it is read as raw anyway: "composted" or "processed_5006"
    #: with no evidence for the exemption, else "raw".
    recorded_as: str = "raw"

    def as_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "pick_id": self.pick_id,
            "applied": self.applied.isoformat(),
            "picked": self.picked.isoformat(),
            "days": self.days,
            "interval_days": self.interval_days,
            "recorded_as": self.recorded_as,
        }


def compost_meets_c2(event) -> bool:
    """C:N 25:1 to 40:1, 131 to 170 F, and the method's time at temperature (windrow 15 days and 5
    turnings; static aerated or in-vessel 3 days): § 205.203(c)(2) as the model's harvest check reads it."""
    cn = getattr(event, "compost_initial_cn_ratio", None)
    temp = getattr(event, "compost_peak_temp_f", None)
    duration = getattr(event, "compost_duration_days_at_temp", None) or 0
    turnings = getattr(event, "compost_turning_count", None) or 0
    method = getattr(event, "compost_method", None)
    if cn is None or temp is None or not (25.0 <= float(cn) <= 40.0) or not (131.0 <= float(temp) <= 170.0):
        return False
    if method == "windrow":
        return duration >= 15 and turnings >= 5
    if method in ("static_aerated", "in_vessel"):
        return duration >= 3
    return False


def raw_reading(event) -> str:
    """ "raw" when the record is read as raw manure, "composted" or "processed_5006" when its label claims
    an exemption the record does not support, or "" when it is exempt or carries no manure date."""
    if not getattr(event, "manure_application_date", None):
        return ""
    treatment = getattr(event, "manure_treatment", None)
    if treatment == "composted":
        from history.services.audit_export_service import _compost_is_purchased

        return "" if compost_meets_c2(event) or _compost_is_purchased(event) else "composted"
    if treatment == "processed_5006":
        documented = getattr(event, "processed_manure_temp_f", None) is not None or bool(
            (getattr(event, "processed_manure_attestation", None) or "").strip()
        )
        return "" if documented else "processed_5006"
    return "raw"


def is_raw(event) -> bool:
    """A soil record with a manure date that no exemption covers (`raw_reading`)."""
    return bool(raw_reading(event))


def interval_for(application, crop_type) -> int:
    from history.services.manure_interval import interval_days, minimum_interval_days

    recorded = interval_days(getattr(application, "manure_harvest_interval", None)) or 0
    return max(recorded, minimum_interval_days(crop_type))


def _raw_applications(parcel_id):
    from history.models import SoilManagementEvent

    rows = SoilManagementEvent.objects.filter(
        history__parcel_id=parcel_id, manure_application_date__isnull=False
    ).order_by("manure_application_date", "pk")
    return [r for r in rows if is_raw(r)]


def parcel_conflicts(parcel_id, *, application=None, pick=None) -> list[ManureConflict]:
    """Every pick on the parcel inside the interval of a raw manure application on it, earliest
    application first. `application` or `pick` narrows to the pairs one just-saved record takes part in."""
    from history.models import ProductionEvent

    if parcel_id is None:
        return []
    applications = _raw_applications(parcel_id)
    if application is not None:
        applications = [a for a in applications if a.pk == application.pk]
    picks = ProductionEvent.objects.filter(history__parcel_id=parcel_id, type__in=PICK_TYPES).select_related(
        "history__crop_type"
    )
    if pick is not None:
        picks = picks.filter(pk=pick.pk)
    picks = list(picks.order_by("date", "pk"))
    out = []
    for app in applications:
        applied = app.manure_application_date
        for p in picks:
            picked = _day(p.date)
            if picked is None or _blocks_differ(app.block_id, p.block_id):
                continue
            days = (picked - applied).days
            interval = interval_for(app, getattr(p.history, "crop_type", None))
            if 0 <= days < interval:
                out.append(
                    ManureConflict(
                        application_id=app.pk,
                        pick_id=p.pk,
                        applied=applied,
                        picked=picked,
                        days=days,
                        interval_days=interval,
                        recorded_as=raw_reading(app),
                    )
                )
    return out


def season_conflicts(history) -> list[ManureConflict]:
    """The parcel's conflicts whose pick is on this production (the audit export reads one production)."""
    if history is None:
        return []
    from history.models import ProductionEvent

    picks = set(ProductionEvent.objects.filter(history=history, type__in=PICK_TYPES).values_list("pk", flat=True))
    if not picks:
        return []
    return [c for c in parcel_conflicts(history.parcel_id) if c.pick_id in picks]


def conflicts_for_saved(event) -> list[dict] | None:
    """The raw-manure conflicts a just-saved record takes part in, for the save response; None for a
    record that is neither a pick nor a soil record with a manure date, so the response carries no key."""
    from history.models import ProductionEvent, SoilManagementEvent

    history = getattr(event, "history", None)
    if history is None:
        return None
    if isinstance(event, SoilManagementEvent) and getattr(event, "manure_application_date", None):
        found = parcel_conflicts(history.parcel_id, application=event)
    elif isinstance(event, ProductionEvent) and event.type in PICK_TYPES:
        found = parcel_conflicts(history.parcel_id, pick=event)
    else:
        return None
    return [c.as_dict() for c in found]
