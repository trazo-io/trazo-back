"""What changed in the operation AFTER this plan's answers were last written.

WHY THIS EXISTS
---------------
`new-version` copies every answer across — the dialog says so — and that is right: a renewal
starts from last year's plan. But nothing then said which of those answers the operation's own
records had since overtaken. A pilot's 2028 renewal was generated from a plan whose narratives
still read "our own six parcels", "86.9 acres", "when Grandevo went into the rotation this
February" — there were seven parcels and 96.7 acres by then, "this February" was two Februaries
earlier, and the rotation narrative named a crop on Bottom Ground A for 2027 that the 2027
season records contradicted. Every section was stamped "Last updated 2026-08-21" on a plan
submitted in February 2028. A certifier reads that as a plan nobody reviewed, and § 205.406(a)(1)
asks for exactly the changes that plan failed to mention.

WHAT IT DOES — AND DELIBERATELY DOES NOT
-----------------------------------------
It does not read the prose. Parsing "six parcels" out of a narrative and comparing it to a count
would be guessing at what the operator meant, and a wrong guess here is a false instruction on
a regulatory filing. Instead it uses the one thing every answer carries — its `at` timestamp —
and lists, from the operation's dated records, what happened after that: ground the operation
began managing, seasons started and closed, § 205.400(f) notices filed, materials added or
removed, certificates changed, affidavits signed, contamination incidents logged. It also names
any parcel whose NAME appears nowhere in the plan's text — a plain substring check, no more —
because a field the plan never mentions is the one thing a reviewer can decide about without
interpretation.

The output is a REVIEW LIST, not a verdict. It never blocks submission: the operator may have
read the section and decided it still holds. It is shown on the packet cover, returned from
the review endpoint, and echoed with the submit response, so it is in front of them at the
moment the decision is made.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from typing import List, Optional

from django.utils import timezone
from django.utils.dateparse import parse_datetime

#: A module whose newest answer is older than this, on a plan being submitted, is flagged as
#: "not revisited" regardless of what else changed — one renewal cycle.
STALE_AFTER_DAYS = 365


@dataclass
class ReviewFinding:
    code: str
    message: str
    count: int = 0
    details: List[str] = field(default_factory=list)
    #: The module this finding points the operator at, when there is one obvious home.
    module_key: Optional[str] = None


@dataclass
class PlanReview:
    answers_as_of: Optional[str]
    reference_date: str
    findings: List[ReviewFinding]
    stale_modules: List[dict]
    parcels_not_named: List[str]

    @property
    def is_clean(self) -> bool:
        return not self.findings and not self.stale_modules and not self.parcels_not_named

    def as_dict(self) -> dict:
        return {
            "answers_as_of": self.answers_as_of,
            "reference_date": self.reference_date,
            "is_clean": self.is_clean,
            "findings": [asdict(f) for f in self.findings],
            "stale_modules": self.stale_modules,
            "parcels_not_named": self.parcels_not_named,
        }


def _module_answer_times(osp) -> dict:
    """module_key -> newest answer timestamp (aware datetime), from module_responses."""
    out = {}
    modules = ((osp.module_responses or {}).get("modules") or {}) if isinstance(osp.module_responses, dict) else {}
    for key, entry in modules.items():
        answers = (entry or {}).get("answers") or {}
        newest = None
        for a in answers.values():
            at = (a or {}).get("at") if isinstance(a, dict) else None
            dt = parse_datetime(at) if isinstance(at, str) else None
            if dt is None:
                continue
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, dt_timezone.utc)
            if newest is None or dt > newest:
                newest = dt
        if newest is not None:
            out[key] = newest
    return out


def _plan_text(osp) -> str:
    """Every string the plan carries, lower-cased, for the parcel-name presence check."""
    chunks = []

    def walk(v):
        if isinstance(v, str):
            chunks.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(osp.sections or {})
    walk(osp.module_responses or {})
    return "\n".join(chunks).lower()


def _module_title(key: str) -> str:
    try:
        from certifications.osp_modules import MODULE_REGISTRY

        for m in MODULE_REGISTRY:
            if m.key == key:
                code = getattr(m, "code", None)
                title = getattr(m, "title", None)
                if isinstance(title, dict):
                    title = title.get("en") or next(iter(title.values()), "")
                if code and title:
                    return f"{code} {title}"
                return title or code or key
    except Exception:  # pragma: no cover — a registry hiccup must not break a renewal
        pass
    return key


def plan_review(osp, *, reference: Optional[datetime] = None) -> PlanReview:
    """Build the review. `reference` is the upper bound of the window and the date modules are
    aged against.

    Two callers, two references, deliberately:
      * the packet cover / filing documents pass nothing, so a plan that has been submitted is
        reviewed AS OF ITS FILING DATE — what the operator could have known when they filed —
        and a packet regenerated a year later does not list the next year's events;
      * the UI panel passes `timezone.now()`, because on an active plan it is the RUNNING list
        of what the next § 205.406 update will have to mention, and a list frozen at last
        February's filing would go stale the day after approval.
    """
    from certifications.models import (
        AdjoiningLandAffidavit,
        ApprovedInputChangeLog,
        Certification,
        LandownerAffidavit,
        OSPChangeNotification,
    )
    from history.models import GeneralEvent, History
    from product.models import Parcel

    establishment = osp.establishment
    reference = reference or osp.submitted_at or timezone.now()
    if timezone.is_naive(reference):
        reference = timezone.make_aware(reference, dt_timezone.utc)

    times = _module_answer_times(osp)
    answers_as_of = max(times.values()) if times else None
    findings: List[ReviewFinding] = []

    # ---- the lineage this plan continues: itself plus every previous version ----------------
    lineage_ids, cursor = [], osp
    while cursor is not None and cursor.pk not in lineage_ids:
        lineage_ids.append(cursor.pk)
        cursor = cursor.previous_version

    if answers_as_of is not None:
        since_d = answers_as_of.date()
        # Bounded ABOVE by the reference date too. For a draft that is now; for a plan already
        # submitted it is the filing date — so a packet regenerated a year later still shows
        # what the operator could have known when they filed, not the next year's events.
        until_d = reference.date()

        new_ground = list(
            Parcel.objects.filter(
                establishment=establishment, date_began_managing__gt=since_d, date_began_managing__lte=until_d
            ).order_by("name")
        )
        if new_ground:
            findings.append(
                ReviewFinding(
                    code="new_ground",
                    message="Ground the operation began managing after the plan's answers were written",
                    count=len(new_ground),
                    details=[f"{p.name} — began {p.date_began_managing.isoformat()}" for p in new_ground],
                    module_key="parcel_application",
                )
            )

        # `date_notified` is nullable (a § 205.400(f)(2) notice may be recorded before the
        # letter goes); an undated notice is placed by the day it was recorded so it is not
        # silently dropped from the window by a NULL comparison.
        from django.db.models import Q

        notices = list(
            OSPChangeNotification.objects.filter(osp_id__in=lineage_ids)
            .filter(
                Q(date_notified__gt=since_d, date_notified__lte=until_d)
                | Q(date_notified__isnull=True, created_at__gt=answers_as_of, created_at__lte=reference)
            )
            .select_related("parcel")
            .order_by("date_notified", "created_at")
        )
        if notices:
            findings.append(
                ReviewFinding(
                    code="change_notifications",
                    message="§ 205.400(f) change notifications filed after the plan's answers were written",
                    count=len(notices),
                    details=[
                        (
                            n.date_notified.isoformat()
                            if n.date_notified
                            else f"{n.created_at.date().isoformat()} (recorded)"
                        )
                        + f" — {n.get_change_category_display()}"
                        + (f" — {n.parcel.name}" if n.parcel_id else "")
                        for n in notices
                    ],
                )
            )

        seasons = History.objects.filter(parcel__establishment=establishment)
        closed = list(seasons.filter(finish_date__gt=answers_as_of, finish_date__lte=reference).order_by("finish_date"))
        started = list(seasons.filter(start_date__gt=answers_as_of, start_date__lte=reference).order_by("start_date"))
        if closed:
            findings.append(
                ReviewFinding(
                    code="seasons_closed",
                    message="Productions closed after the plan's answers were written",
                    count=len(closed),
                    details=[f"{h.name or 'Production'} — {h.finish_date.date().isoformat()}" for h in closed],
                    module_key="g4_0_rotation_soil",
                )
            )
        if started:
            findings.append(
                ReviewFinding(
                    code="seasons_started",
                    message="Productions started after the plan's answers were written",
                    count=len(started),
                    details=[f"{h.name or 'Production'} — {h.start_date.date().isoformat()}" for h in started],
                    module_key="g4_0_rotation_soil",
                )
            )

        input_changes = list(
            ApprovedInputChangeLog.objects.filter(
                osp_id__in=lineage_ids, changed_at__gt=answers_as_of, changed_at__lte=reference
            ).order_by("changed_at")
        )
        if input_changes:
            findings.append(
                ReviewFinding(
                    code="inputs_changed",
                    message="Materials added to or removed from the approved-inputs list after the answers",
                    count=len(input_changes),
                    details=[
                        f"{c.changed_at.date().isoformat()} — {c.get_action_display()} {c.target_name_at_change}"
                        for c in input_changes
                    ],
                    module_key="materials_application",
                )
            )

        # `created_at`, not `updated_at`: the USDA Organic Integrity verifier re-saves a certificate
        # on every run (verification_manager.py), so `updated_at` would have flagged every
        # certificate every day. A certificate ADDED since the answers is an unambiguous change.
        certs = list(
            Certification.objects.filter(
                establishment=establishment, created_at__gt=answers_as_of, created_at__lte=reference
            )
        )
        if certs:
            findings.append(
                ReviewFinding(
                    code="certifications_changed",
                    message="Certification records added after the plan's answers were written",
                    count=len(certs),
                    details=[f"{c.get_certification_type_display()} — {c.certifier_name or '—'}" for c in certs],
                    module_key="certification_contract",
                )
            )

        affidavits = (
            LandownerAffidavit.objects.filter(
                parcel__establishment=establishment, created_at__gt=answers_as_of, created_at__lte=reference
            ).count()
            + AdjoiningLandAffidavit.objects.filter(
                parcel__establishment=establishment, created_at__gt=answers_as_of, created_at__lte=reference
            ).count()
        )
        if affidavits:
            findings.append(
                ReviewFinding(
                    code="affidavits_added",
                    message="Land-history or adjoining-land affidavits signed after the answers",
                    count=affidavits,
                    module_key="parcel_application",
                )
            )

        incidents = list(
            GeneralEvent.objects.filter(
                history__parcel__establishment=establishment,
                is_contamination_incident=True,
                date__gt=answers_as_of,
                date__lte=reference,
            )
            .select_related("history__parcel")
            .order_by("date")
        )
        if incidents:
            findings.append(
                ReviewFinding(
                    code="contamination_incidents",
                    message="Contamination incidents recorded after the plan's answers were written",
                    count=len(incidents),
                    details=[
                        f"{e.date.date().isoformat()} — {e.history.parcel.name}: "
                        f"{(e.contamination_source or '').replace('_', ' ')}"
                        for e in incidents
                    ],
                    module_key="parcel_application",
                )
            )

    # ---- § 11 registry: what the records say vs what the plan claims -----------------------
    #
    # The asymmetry is the whole point, and only ONE direction is a problem. A row ticked with
    # no evidence is correct and common — weigh tickets and pool closings live in a drawer, and
    # the registry marks them "kept outside Trazo" for that reason. A row the operation has
    # LOGGED and not confirmed is different: the packet's recordkeeping section then tells the
    # certifier this operation does not keep harvest records, while the dossier in the same
    # envelope prints thirty-three of them. One document, two answers.
    #
    # Listed, never blocked, like everything else here: the operator may keep those records
    # under a name of their own, or may not consider the logs to be the record. But they should
    # decide that, rather than discover it in a reviewer's question.
    # Read the CONFIRMATIONS first — they are a dict on the plan, free. Deriving evidence is
    # not: `EvidenceBundle` loads every production on the operation and prefetches six event
    # relations, and this review now renders on the OSP landing page. Paying that on every visit
    # to answer a question about an untouched registry would be a straight regression on the
    # page a pilot opens most.
    try:
        from certifications.services.common_osp_records import RECORD_TYPES_BY_KEY, _confirmations, derive_record_types

        confirmations = _confirmations(osp)
    except Exception:  # noqa: BLE001 — a registry hiccup must never take the review down
        confirmations, RECORD_TYPES_BY_KEY = {}, {}  # noqa: N806

    # Only once the operator has actually engaged the registry. On a plan where NOTHING is
    # confirmed, every evidenced row is "contradicted" — thirty-one findings that say no more
    # than "you have not filled in G8.0 yet", which the module list and the packet's outstanding
    # -modules page both already say. A permanent finding nobody can clear is how a review list
    # becomes wallpaper, and this one has to stay readable for the case that matters: an
    # operator who worked through the registry and left a logged record type unticked.
    engaged = any(isinstance(e, dict) and e.get("confirmed") for e in confirmations.values())
    contradicted = []
    if engaged:
        try:
            contradicted = [r for r in derive_record_types(establishment, osp=osp) if r.get("suggested")]
        except Exception:  # noqa: BLE001
            contradicted = []
    if contradicted:
        findings.append(
            ReviewFinding(
                code="record_types_evidenced_not_confirmed",
                message="Your records show these, but the plan does not confirm you keep them",
                count=len(contradicted),
                details=[f"{r['label']} — {r['basis']}" for r in contradicted if r.get("basis")],
                module_key="g8_0_record_keeping",
            )
        )

    carried = [
        (key, entry)
        for key, entry in confirmations.items()
        if isinstance(entry, dict) and entry.get("carried_from_version") and key in RECORD_TYPES_BY_KEY
    ]
    if carried:
        findings.append(
            ReviewFinding(
                code="record_types_carried_forward",
                message=(
                    "Record types confirmed on an earlier plan and not re-stated on this one — "
                    "attest the recordkeeping section unchanged on your annual update, or re-tick them"
                ),
                count=len(carried),
                details=[
                    f"{RECORD_TYPES_BY_KEY[key].label} — carried from plan v{entry['carried_from_version']}"
                    for key, entry in carried
                ],
                module_key="g8_0_record_keeping",
            )
        )

    # ---- § 205.401(b) — the responsible person must be NAMED ----------------------------------
    if not (getattr(establishment, "contact_person", None) or "").strip():
        findings.append(
            ReviewFinding(
                code="responsible_person_missing",
                message="No contact person is set on the farm profile — § 205.401(b) asks for the "
                "responsible person by name",
                count=1,
                module_key="certification_contract",
            )
        )

    # ---- modules not revisited in a renewal cycle -----------------------------------------
    stale = []
    for key, newest in sorted(times.items(), key=lambda kv: kv[1]):
        age = (reference - newest).days
        if age > STALE_AFTER_DAYS:
            stale.append(
                {
                    "module_key": key,
                    "module": _module_title(key),
                    "answered_at": newest.date().isoformat(),
                    "days_before_submission": age,
                }
            )

    # ---- parcels the plan never names ----------------------------------------------------
    text = _plan_text(osp)
    not_named = [
        p.name
        for p in Parcel.objects.filter(establishment=establishment).order_by("name")
        if p.name and p.name.strip().lower() not in text
    ]

    return PlanReview(
        answers_as_of=answers_as_of.date().isoformat() if answers_as_of else None,
        reference_date=reference.date().isoformat(),
        findings=findings,
        stale_modules=stale,
        parcels_not_named=not_named,
    )
