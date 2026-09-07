"""
OSP ↔ Events Drift Detector — Sprint 5.1.

Compares each ChemicalEvent / SoilManagementEvent against the approved_inputs
list on the event's establishment's active OrganicSystemPlan. If the input
used on the event is not in the approved set, the event's `drift_warning`
JSONB field is populated with a structured finding the audit export PDF and
frontend badges can consume.

Design choices:
- Never blocks save. The inspector signal is "you may be in drift; document
  or get certifier approval" — farmers legitimately use inputs the OSP
  hasn't caught up to yet. An input used that is not on the OSP approved
  list is a *change in the operation* and falls under § 205.400(f)(2)
  (operation/practice change notification), NOT § 205.400(f)(1), which
  is reserved for application of a prohibited substance (actual drift or
  direct application of a § 205.602-prohibited input).
- Uses post_save + Model.objects.filter().update() to avoid recursion.
- No active OSP → no drift (drift_warning stays None). The compliance gap is
  recorded elsewhere (OSP lifecycle itself flags no-active-plan as incomplete).
- Resolves via three layers, cheapest first:
    1. Event has FK to OMRIProduct / NationalListSubstance → pk membership check
    2. Event has commercial_name / amendment_type → name match (case-insensitive)
       against approved OMRI products' commercial names and National List
       substance names
    3. Else → cannot classify; leave drift_warning alone
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

from django.db import transaction

logger = logging.getLogger(__name__)


#: The phrase every classifier uses for the plan it compared against. Centralised because a
#: PROVISIONAL finding is measured against a draft, and calling that "active" is false.
_PLAN_NOUN_ACTIVE = "active OSP"
_PLAN_NOUN_DRAFT = "draft OSP"

#: What an unlisted input actually breaches, which is NOT the same regulation in both cases.
#:
#:   filed plan  → § 205.400(f)(2). The operator has a certifier-approved plan and used
#:                 something outside it: that is a change in the operation the certifier must
#:                 be told about.
#:   draft plan  → § 205.201(a)(2). Nothing has been filed and no certifier has read it, so
#:                 there is no change to notify. What is true is narrower and purely internal:
#:                 the plan's own input list does not yet name this material.
#:
#: Stamping (f)(2) on a draft finding told a first-renewal grower to file a change notice
#: about a plan nobody has seen — the over-claim class this module exists to avoid.
CFR_FILED_PLAN = "7 CFR 205.400(f)(2)"
CFR_DRAFT_PLAN = "7 CFR 205.201(a)(2)"


def _osp_for_drift(establishment_id: int):
    """The plan to compare events against: the active one, else the newest draft.

    Returns ``(osp, provisional)`` — ``(None, False)`` when there is neither.

    🔴 Why the fallback exists. Activation requires certifier approval evidence (approval
    document + certificate number + certifier name, `views.py`), which is the CORRECT gate and
    is not loosened here. But it means a farm in its FIRST certification year cannot have an
    active plan until after the renewal it bought Trazo to prepare for — so the detector
    returned None for every event it logged, all season, and the packet reported that the
    input check had not run. That cohort is exactly who the October outreach names:
    "first-renewal farms facing their annual update this winter".

    For such a farm the draft is not a degraded active plan — it IS their plan, being written,
    and comparing their records against it is the reconciliation the annual update asks for.

    ⛔ A finding measured against a draft is PROVISIONAL and must say so, in three ways:
    a different regulation (see CFR_DRAFT_PLAN), a different action (add it to the plan, never
    "notify your certifier"), and the `provisional` flag on the payload so every reader can
    separate the two. Promotion is automatic: activation already calls
    `_recompute_drift_for_establishment`.
    """
    from certifications.models import OrganicSystemPlan

    active = _active_osp_for_establishment(establishment_id)
    if active is not None:
        return active, False
    draft = (
        OrganicSystemPlan.objects.filter(establishment_id=establishment_id, status="draft")
        .prefetch_related(
            "approved_national_list_substances",
            "approved_omri_products",
            "approved_wsda_materials",
            "plan_material_entries",
        )
        .order_by("-version_number")
        .first()
    )
    return (draft, True) if draft is not None else (None, False)


def _active_osp_for_establishment(establishment_id: int):
    """Returns the single active OrganicSystemPlan for an establishment, or None.

    Local import to avoid circular import between certifications.models and
    history.signals at app-load time.
    """
    from certifications.models import OrganicSystemPlan

    return (
        OrganicSystemPlan.objects.filter(establishment_id=establishment_id, status="active")
        .prefetch_related(
            "approved_national_list_substances",
            "approved_omri_products",
            "approved_wsda_materials",
            # The detector reads this now, and a farm-wide recompute walks every event —
            # without the prefetch that is one query per event just to ask the same question.
            "plan_material_entries",
        )
        .first()
    )


def _event_establishment_id(event) -> Optional[int]:
    """Walks event.history.parcel.establishment_id without blowing up on nulls."""
    history = getattr(event, "history", None)
    if history is None:
        return None
    parcel = getattr(history, "parcel", None)
    if parcel is None:
        return None
    return getattr(parcel, "establishment_id", None)


def _now_iso() -> str:
    """UTC ISO-8601 timestamp for per-lookup verification stamps."""
    return datetime.now(timezone.utc).isoformat()


def _build_drift_warning(
    *,
    osp,
    reason: str,
    reason_code: Optional[str] = None,
    reason_params: Optional[Dict[str, Any]] = None,
    input_label: str,
    resolved_via: str,
    resolved_id: Optional[int] = None,
    resolved_name: Optional[str] = None,
    cdfa_oim_status: Optional[Dict[str, Any]] = None,
    ca_dpr_permit_status: Optional[Dict[str, Any]] = None,
    omri_search_url: Optional[str] = None,
    omri_verified_at: Optional[str] = None,
    wsda_verified_at: Optional[str] = None,
    national_list_verified_at: Optional[str] = None,
    cdfa_oim_verified_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Canonical drift_warning payload shape. Keep stable — PDF + UI read it.

    Optional fields:
      - ``cdfa_oim_status``: CA-only sub-finding, ``{"status": ...}`` — one of
        ``registered`` / ``unknown`` (see the CDFA_OIM_* constants). It carries NO
        registration number: CDFA publishes none, so any number here would be
        invented. Set when the establishment is in California and the input
        resolved to a catalog row. Independent of OSP approval.
      - ``ca_dpr_permit_status``: CA-only sub-finding ({status, permit_number,
        county, expires}) for county-restricted materials — currently inert
        (empty keyword tuple, see ADR-008).
      - ``omri_search_url``: deep-link into omri.org for unresolved inputs so
        the farmer can verify manually (see
        feedback_omri_subscription_deferred).
      - ``omri_verified_at`` / ``wsda_verified_at`` /
        ``national_list_verified_at`` / ``cdfa_oim_verified_at``: UTC ISO-8601
        timestamps captured at the moment each catalog was queried for THIS
        finding. Satisfies § 205.103(b)(2) SOE "enhanced traceability" — an
        inspector can confirm when exactly a given drift finding was
        cross-referenced against the live source. Legacy findings (written
        before this fix) lack these keys and are rendered as "—" in the PDF.
    """
    # PROVISIONAL is derived from the plan itself, never passed in. A caller that had to
    # remember to set it would eventually forget, and the failure mode is a draft finding
    # wearing a filed plan's regulation — the exact over-claim this flag exists to prevent.
    provisional = (getattr(osp, "status", "") or "") != "active"
    if provisional:
        # The classifiers all say "not in active OSP approved inputs". Against a draft that
        # word is false, and it is the only word that is: one substitution keeps the eleven
        # call sites from each having to know which plan they were handed.
        reason = reason.replace(_PLAN_NOUN_ACTIVE, _PLAN_NOUN_DRAFT)
        # Some classifiers end their prose with a period and some do not; joining without
        # checking produced a run-on sentence in the packet.
        stem = reason.rstrip()
        if stem and not stem.endswith((".", "!", "?")):
            stem += "."
        reason = f"{stem} This plan is still a draft, so add the material to it before you submit."

    payload = {
        "detected_at": _now_iso(),
        "osp_id": osp.id,
        "osp_version": osp.version_number,
        "input_label": input_label,
        "reason": reason,
        # Measured against a draft: real detection, but nothing has been FILED, so this is not
        # yet a finding about the operation — it is the plan's own input list being incomplete.
        # Every reader (packet, dossier, banner) must be able to keep the two apart.
        "provisional": provisional,
        # Stable machine code + params so the UI can localize the finding; the
        # English prose above remains the packet text and the UI fallback for
        # legacy findings written before 2026-08-25.
        "reason_code": reason_code,
        "reason_params": reason_params or {},
        "resolved_via": resolved_via,
        "resolved_id": resolved_id,
        "resolved_name": resolved_name,
        "cfr_reference": CFR_DRAFT_PLAN if provisional else CFR_FILED_PLAN,
    }
    if cdfa_oim_status is not None:
        payload["cdfa_oim_status"] = cdfa_oim_status
    if ca_dpr_permit_status is not None:
        payload["ca_dpr_permit_status"] = ca_dpr_permit_status
    if omri_search_url is not None:
        payload["omri_search_url"] = omri_search_url
    if omri_verified_at is not None:
        payload["omri_verified_at"] = omri_verified_at
    if wsda_verified_at is not None:
        payload["wsda_verified_at"] = wsda_verified_at
    if national_list_verified_at is not None:
        payload["national_list_verified_at"] = national_list_verified_at
    if cdfa_oim_verified_at is not None:
        payload["cdfa_oim_verified_at"] = cdfa_oim_verified_at
    return payload


def _establishment_is_in_california(event) -> bool:
    """Walks event → history → parcel → establishment.state for a CA match.

    Best-effort — returns False on any missing attribute. The CDFA OIM
    escalation is additive (never hides an existing finding) so a false
    negative (not flagging a CA farm) is safer than raising an exception.
    """
    try:
        establishment = event.history.parcel.establishment
    except AttributeError:
        return False
    state = (getattr(establishment, "state", "") or "").strip().upper()
    # Accept "CA" or "California" (various seed paths use either).
    return state in ("CA", "CALIFORNIA")


def _aosca_seed_search_url(variety: str) -> str:
    """Deep-link into AOSCA Organic Seed Finder — the NOP-endorsed seed
    variety DB (Handbook 5029). AOSCA doesn't offer an API; the search page
    accepts a query string and surfaces matching organic-certified varieties
    the farmer can consult during their commercial-availability search.

    Why deep-link rather than mirror: AOSCA does not publish a bulk CSV and
    scraping violates terms. Deep-link preserves provenance and points the
    farmer at the canonical source — consistent with the OMRI deep-link
    approach (see feedback_omri_subscription_deferred).
    """
    from urllib.parse import quote_plus

    return f"https://www.organicseedfinder.org/search.aspx?query={quote_plus(variety or '')}"


def _classify_seed_event(event, osp) -> Optional[Dict[str, Any]]:
    """Returns drift_warning dict for a Planting (type='PL') ProductionEvent
    if the seed certification status / supplier-search documentation is
    incomplete per § 205.204 and NOP 5029.

    Rules (from § 205.204(a) and NOP Handbook 5029):
      - certified_organic OR transitional → clean, no finding
      - non_organic_untreated → REQUIRES documented 3-supplier organic seed
        search (NOP 5029 a(1)). Missing search = finding.
      - non_organic_treated → PROHIBITED if treated with synthetic substances
        not on § 205.601. Always flag for reconciliation.
      - empty / unset → insufficient documentation to make a determination.

    Cover-crop seeds (SoilManagementEvent type='CC') go through a sibling
    handler that reads the same seed fields if they migrate onto that model.
    For now this single classifier covers the PL surface, which is where
    § 205.204 findings actually arise on a specialty-crop farm.
    """
    # Only planting events carry seed metadata relevant to § 205.204.
    if getattr(event, "type", None) != "PL":
        return None

    cert_status = (getattr(event, "seed_certification_status", "") or "").strip()
    # `variety` lives on CommonEvent and is the canonical per-planting cultivar.
    # `seeds_source` is a transparency enum (nursery / seed saver / commercial).
    # We prefer the farmer-typed variety for the AOSCA search URL.
    variety = (getattr(event, "variety", "") or "").strip()
    supplier = (getattr(event, "seed_supplier_name", "") or "").strip()
    search_attempts = getattr(event, "seed_search_attempts", None) or []

    # Clean cases — organic or transitional seed is compliant.
    if cert_status in ("certified_organic", "transitional"):
        return None

    label = variety or supplier or "planting event"
    aosca_url = _aosca_seed_search_url(variety or supplier)

    # Case 1: non-organic treated seed. § 205.204(a)(2) allows treated seed only
    # when the treatment substance is listed on § 205.601. We can't verify
    # the specific treatment here — we flag for reconciliation.
    if cert_status == "non_organic_treated":
        return _build_drift_warning(
            osp=osp,
            reason=(
                "Non-organic TREATED seed declared. § 205.204(a)(2) allows treated "
                "seed only if the treatment is on the National List (§ 205.601). "
                "Confirm seed treatment with certifier before harvest to avoid "
                "disqualification."
            ),
            reason_code="seed_treated",
            reason_params={"input": label},
            input_label=label,
            resolved_via="seed_treated_prohibited",
            resolved_name=label,
            omri_search_url=aosca_url,
        )

    # Case 2: non-organic untreated without the 3-supplier commercial-availability
    # search required by NOP 5029.
    if cert_status == "non_organic_untreated":
        if len(search_attempts) < 3:
            return _build_drift_warning(
                osp=osp,
                reason=(
                    "Non-organic untreated seed declared with "
                    f"{len(search_attempts)} of 3 required supplier searches. "
                    "NOP 5029 (§ 205.204(a)(1)) requires documented commercial-"
                    "availability search of 3+ organic seed suppliers."
                ),
                reason_code="seed_search_incomplete",
                reason_params={"input": label, "count": len(search_attempts)},
                input_label=label,
                resolved_via="seed_search_incomplete",
                resolved_name=label,
                omri_search_url=aosca_url,
            )
        return None

    # Case 3: certification status unset. The event was logged without the
    # field that determines regulatory classification — the compliance record
    # is incomplete.
    return _build_drift_warning(
        osp=osp,
        reason=(
            "Seed certification status not documented. § 205.204 requires "
            "each planting to record whether seed is organic, transitional, "
            "or non-organic."
        ),
        reason_code="seed_cert_missing",
        reason_params={"input": label},
        input_label=label,
        resolved_via="seed_certification_missing",
        resolved_name=label,
        omri_search_url=aosca_url,
    )


def _omri_search_url(farmer_input: str) -> str:
    """Deep-link into omri.org for unresolved inputs.

    Our local OMRI catalog is a reference subset (see seed_omri_minimal docstring);
    any name we can't match locally may still be listed upstream. Rather than
    silently flag these as unknown, we provide a one-click link the farmer can
    follow to verify on omri.org. Upgrade path documented in
    feedback_omri_subscription_deferred.
    """
    return f"https://www.omri.org/omri-search?query={quote_plus(farmer_input or '')}"


# CDFA OIM sub-finding states. THREE, not two (2026-09-06).
#
# `missing` used to be the DEFAULT for any product simply absent from Trazo's CDFA
# reference set, and it rendered — to the operator and into the certifier packet — as
# "CDFA OIM registration is missing — California state law requires OIM registration
# for fertilizing materials". That is an assertion that the operator broke state law,
# drawn from `certifications/data/cdfa_oim_seed.csv`: SEVENTEEN rows against a CDFA
# Registered OIM Products list that runs to thousands. Absence from our reference set
# is not evidence of non-registration.
#
# ⚠️ `CDFA_OIM_MISSING` IS NOT REACHABLE TODAY and nothing emits it. It is kept because
# it is the honest label for a case we do not yet have: a full ingest of the published
# CDFA list, where absence really would mean unregistered. Do not wire it up to
# anything short of that. Renderers still accept it so that drift_warning rows written
# before this change keep rendering — as the UNKNOWN wording, since that is what they
# actually meant.
CDFA_OIM_REGISTERED = "registered"
CDFA_OIM_UNKNOWN = "unknown"  # not in Trazo's CDFA reference set — we did not check
CDFA_OIM_MISSING = "missing"  # unreachable: needs the full published list first


def _resolved_input_cdfa_status(resolved_obj) -> Optional[Dict[str, Any]]:
    """Return a {status} dict for the resolved object's CDFA OIM standing, else None.

    Applies to OMRIProduct and WSDAMaterial. No registration NUMBER is carried: CDFA's
    published Registered OIM Products list has three columns — Firm, Product Name,
    Annotations — and no identifier, so every `CDFA-OIM-*` string in this codebase is
    invented and must never reach a reader.
    """
    if resolved_obj is None:
        return None
    if getattr(resolved_obj, "is_cdfa_oim_registered", False):
        return {"status": CDFA_OIM_REGISTERED}
    return {"status": CDFA_OIM_UNKNOWN}


# California Restricted Materials (3 CCR § 6400) — intentionally EMPTY.
#
# A prior version of this module carried a keyword tuple that flagged copper
# hydroxide, copper sulfate, copper oxychloride, "bordeaux", "kocide", sulfur,
# pyrethrin, spinosad, "entrust", and rotenone as California Restricted
# Materials requiring a county Ag Commissioner permit. That list was ENTIRELY
# FALSE POSITIVES. The authoritative CDPR active-ingredient profile for
# copper hydroxide states "California Restricted Material: No", and cross-
# reference against 3 CCR § 6400 confirms none of the above substances are
# designated restricted materials for the purposes of the county permit
# program.
#
# A correct restricted-materials check requires lookup by CDPR Chem Code
# against the published restricted-materials registry (see ADR-008 —
# "CA DPR Restricted Materials Adapter"). Until that adapter is built, the
# framework (permit fields on ChemicalEvent, _event_ca_dpr_permit_status
# helper, drift-finding sub-emission) remains intact but ``_input_is_ca_restricted``
# returns False for every input, so no CA DPR sub-finding is emitted. This
# prevents false-positive findings against NOP-allowed synthetics while
# leaving the scaffolding ready for the adapter.
CA_RESTRICTED_KEYWORDS: tuple = ()


def _input_is_ca_restricted(input_label: Optional[str], resolved_obj) -> bool:
    """Placeholder — always False until a real CDPR Chem Code adapter lands.

    See the comment above ``CA_RESTRICTED_KEYWORDS`` and ADR-008 for context.
    The function signature, callsites, and ChemicalEvent permit fields are
    kept in place so the future adapter is a drop-in replacement.
    """
    return False


def _event_ca_dpr_permit_status(event) -> Dict[str, Any]:
    """Returns {status, permit_number, county, expires} for the permit
    fields on the ChemicalEvent. Caller is responsible for having already
    confirmed the establishment is in CA and the input is restricted."""
    from datetime import date as _date

    permit = (getattr(event, "ca_dpr_permit_number", "") or "").strip()
    county = (getattr(event, "ca_dpr_permit_county", "") or "").strip()
    expires = getattr(event, "ca_dpr_permit_expires", None)
    expires_iso = expires.isoformat() if expires else None
    if not permit:
        return {"status": "missing", "permit_number": None, "county": None, "expires": None}
    if expires and expires < _date.today():
        return {
            "status": "expired",
            "permit_number": permit,
            "county": county or None,
            "expires": expires_iso,
        }
    return {
        "status": "present",
        "permit_number": permit,
        "county": county or None,
        "expires": expires_iso,
    }


def _classify_chemical_event(event, osp) -> Optional[Dict[str, Any]]:
    """Returns drift_warning dict if ChemicalEvent is out-of-OSP, else None.

    Additive layers surfaced independent of OSP approval:
      1. CA-only CDFA OIM registration (fertilizing materials only).
      2. CA-only DPR restricted-materials permit (county-restricted pesticides:
         copper, sulfur, pyrethrin, spinosad, rotenone).
      3. OMRI search deep-link for unresolved input names (the local OMRI
         catalog is a reference subset — see feedback_omri_subscription_deferred).

    A CA establishment applying a CDFA-unregistered fertilizer OR a DPR-restricted
    pesticide without a current permit still gets a finding even if the OSP has
    approved the input.
    """
    from certifications.models import OMRIProduct, WSDAMaterial

    approved_omri_ids = set(osp.approved_omri_products.values_list("id", flat=True))
    approved_nl_ids = set(osp.approved_national_list_substances.values_list("id", flat=True))
    approved_wsda_ids = set(osp.approved_wsda_materials.values_list("id", flat=True))
    is_ca = _establishment_is_in_california(event)

    def _ca_sub(resolved_obj):
        # Only attach the CA sub-finding for fertilizer/amendment categories —
        # CDFA OIM applies to fertilizing materials, not pesticides.
        if not is_ca or resolved_obj is None:
            return None
        category = (getattr(resolved_obj, "category", "") or "").lower()
        if "fertil" not in category and "amend" not in category and "inoculant" not in category:
            return None
        return _resolved_input_cdfa_status(resolved_obj)

    def _dpr_sub(label, resolved_obj):
        # CA DPR permit applies to county-restricted pesticides (copper, sulfur,
        # pyrethrin, spinosad, rotenone). Orthogonal to CDFA OIM (fertilizers).
        if not is_ca:
            return None
        if not _input_is_ca_restricted(label, resolved_obj):
            return None
        return _event_ca_dpr_permit_status(event)

    def _approved_issue_reason(cdfa, dpr):
        """Build the OSP-approved-but-flagged reason.
        Returns (prose, issue_codes, issue_params); prose is None when clean."""
        parts = []
        codes = []
        params: Dict[str, Any] = {}
        if cdfa and cdfa.get("status") == CDFA_OIM_UNKNOWN:
            # NOT "registration is missing". Trazo holds a 17-row slice of the CDFA
            # Registered OIM Products list; a product absent from it is unchecked, not
            # unregistered. Say which of those two this is.
            parts.append(
                "CDFA OIM registration was not checked — this product is not in "
                "Trazo's CDFA reference set, which covers only part of the CDFA "
                "Registered OIM Products list. Confirm registration with CDFA "
                "before applying it in California"
            )
            codes.append("cdfa_unknown")
        elif cdfa and cdfa.get("status") == CDFA_OIM_MISSING:
            # Unreachable today — see the CDFA_OIM_* constants. Kept so that legacy
            # drift_warning rows written before 2026-09-06 still carry a code.
            parts.append(
                "CDFA OIM registration is missing — California state law "
                "requires OIM registration for fertilizing materials"
            )
            codes.append("cdfa_missing")
        if dpr and dpr.get("status") == "missing":
            parts.append(
                "CA DPR restricted-materials permit missing — county Ag "
                "Commissioner permit required before application"
            )
            codes.append("dpr_missing")
        elif dpr and dpr.get("status") == "expired":
            parts.append(
                f"CA DPR permit #{dpr.get('permit_number')} expired on "
                f"{dpr.get('expires')} — renew before next application"
            )
            codes.append("dpr_expired")
            params["permitNumber"] = dpr.get("permit_number")
            params["expires"] = dpr.get("expires")
        return ("; ".join(parts) if parts else None), codes, params

    def _name_approval_clears(name):
        """Cross-catalog rescue for FK-classified events (2026-08-25).

        An event stamped with an NL substance (or an OMRI FK) used to be judged
        against THAT registry alone — so "Entrust SC", classified as Spinosad on
        save, was flagged "National List substance not in active OSP approved
        inputs" while "Entrust SC Naturalyte Insect Control" sat on the plan's
        approved OMRI list. One product, two registries, and the detector
        stopped at the wrong one. Same rule as Layer 2 below: ANY catalog
        approval clears the finding.

        Returns (approved_obj, via, approved_name, omri_ts, wsda_ts) or None.
        """
        if not name:
            return None
        from certifications.services.omri_verifier import _resolve_omri_by_name, _resolve_wsda_by_name

        o_ts = _now_iso()
        r_omri = _resolve_omri_by_name(name)
        w_ts = _now_iso()
        r_wsda = _resolve_wsda_by_name(name)
        if r_omri is not None and r_omri.id in approved_omri_ids:
            return (r_omri, "omri", r_omri.product_name, o_ts, w_ts)
        if r_wsda is not None and r_wsda.id in approved_wsda_ids:
            return (r_wsda, "wsda", r_wsda.brand_name, o_ts, w_ts)
        # The National List, which this rescue could not reach until 2026-09-07. The gap was
        # asymmetric and therefore easy to miss: the NL-FK branch below rescued INTO OMRI and
        # WSDA, but the OMRI-FK branch could not rescue into the National List — so a product
        # whose plan entry is the SUBSTANCE ("Elemental sulfur") kept flagging when the event
        # happened to carry an OMRI FK for the same material.
        r_nl = _resolve_national_list_by_name(name)
        if r_nl is not None and r_nl.id in approved_nl_ids:
            return (r_nl, "national_list", r_nl.substance_name, o_ts, w_ts)
        # The fourth source. `PlanMaterialEntry` shipped 2026-08-28 for exactly the materials
        # no catalog carries — CCOF NOPB41 §A names compost, manure, gypsum and limestone in
        # its own prompt — and the detector never learned about it, so those materials flagged
        # as unapproved on EVERY application, forever, while sitting on the plan the finding
        # said they were missing from. `views.py` even claimed adding one clears a warning.
        #
        # ⛔ EXACT normalized match only. `plan_materials.py` states the rule: these are the
        # operator's own words, and fuzzy-matching them "would quietly mark a material as
        # covered when nobody decided that it was".
        entry = _operator_entry_by_name(osp, name)
        if entry is not None:
            return (entry, "operator_entered", entry.product_name, o_ts, w_ts)
        return None

    def _rescued_approved_result(rescue, label):
        """Finding-or-None for an FK-flagged event rescued by a name-level OSP
        approval: None clears it outright; CA sub-findings still surface."""
        approved_obj, via, approved_name, o_ts, w_ts = rescue
        cdfa_ts = _now_iso()
        cdfa = _ca_sub(approved_obj)
        dpr = _dpr_sub(label, approved_obj)
        issue_prose, issue_codes, issue_params = _approved_issue_reason(cdfa, dpr)
        if issue_prose:
            return _build_drift_warning(
                osp=osp,
                reason=(f"Input '{label}' is OSP-approved ({via.upper()}: {approved_name}) " f"but {issue_prose}."),
                reason_code="approved_with_issues",
                reason_params={
                    "input": label,
                    "resolvedName": approved_name,
                    "issues": issue_codes,
                    **issue_params,
                },
                input_label=label,
                resolved_via=via,
                resolved_id=approved_obj.id,
                resolved_name=approved_name,
                cdfa_oim_status=cdfa,
                ca_dpr_permit_status=dpr,
                omri_verified_at=o_ts,
                wsda_verified_at=w_ts,
                cdfa_oim_verified_at=cdfa_ts if cdfa else None,
            )
        return None

    # Layer 1 — structured FK match (highest confidence). Per-finding
    # timestamps capture WHEN the FK cross-reference was performed so the
    # audit PDF can show which catalog state this finding reflects.
    if event.omri_product_id:
        omri_ts = _now_iso()
        resolved = OMRIProduct.objects.filter(pk=event.omri_product_id).first()
        if event.omri_product_id in approved_omri_ids:
            # Still surface the CA CDFA + DPR status even when OSP-approved.
            label = event.commercial_name or getattr(resolved, "product_name", "")
            cdfa_ts = _now_iso()
            cdfa = _ca_sub(resolved)
            dpr = _dpr_sub(label, resolved)
            issue_reason, issue_codes, issue_params = _approved_issue_reason(cdfa, dpr)
            if issue_reason:
                return _build_drift_warning(
                    osp=osp,
                    reason=f"Input approved on OSP but {issue_reason}.",
                    reason_code="approved_with_issues",
                    reason_params={
                        "input": label,
                        "resolvedName": getattr(resolved, "product_name", None),
                        "issues": issue_codes,
                        **issue_params,
                    },
                    input_label=label,
                    resolved_via="omri",
                    resolved_id=event.omri_product_id,
                    resolved_name=getattr(resolved, "product_name", None),
                    cdfa_oim_status=cdfa,
                    ca_dpr_permit_status=dpr,
                    omri_verified_at=omri_ts,
                    cdfa_oim_verified_at=cdfa_ts if cdfa else None,
                )
            return None
        label = event.commercial_name or f"OMRI #{event.omri_product_id}"
        # The linked OMRI product is not on the plan — but the same product may be
        # approved on the plan through its WSDA listing. Any catalog approval clears.
        rescue = _name_approval_clears((event.commercial_name or "").strip())
        if rescue:
            return _rescued_approved_result(rescue, label)
        cdfa_ts = _now_iso()
        cdfa = _ca_sub(resolved)
        return _build_drift_warning(
            osp=osp,
            reason="OMRI product not in active OSP approved inputs",
            reason_code="omri_not_in_osp",
            reason_params={"input": label},
            input_label=label,
            resolved_via="omri",
            resolved_id=event.omri_product_id,
            resolved_name=event.commercial_name,
            cdfa_oim_status=cdfa,
            ca_dpr_permit_status=_dpr_sub(label, resolved),
            omri_verified_at=omri_ts,
            cdfa_oim_verified_at=cdfa_ts if cdfa else None,
        )
    # The WSDA listing the operator attached in the input lookup. This branch did not exist
    # until 2026-09-07: `ChemicalEvent.wsda_material` was written by the grower's own tap and
    # then read by nothing, so the most structured evidence on the record was discarded and the
    # event fell through to fuzzy name matching. Its own help_text says why that matters — for
    # many WSDA brands the WSDA listing is the ONLY third-party listing that exists, so there
    # is no OMRI row for the name matcher to find and the event flagged as unresolved.
    if getattr(event, "wsda_material_id", None):
        wsda_ts = _now_iso()
        resolved = WSDAMaterial.objects.filter(pk=event.wsda_material_id).first()
        label = event.commercial_name or getattr(resolved, "brand_name", "") or f"WSDA #{event.wsda_material_id}"
        if event.wsda_material_id in approved_wsda_ids:
            cdfa_ts = _now_iso()
            cdfa = _ca_sub(resolved)
            dpr = _dpr_sub(label, resolved)
            issue_reason, issue_codes, issue_params = _approved_issue_reason(cdfa, dpr)
            if issue_reason:
                return _build_drift_warning(
                    osp=osp,
                    reason=f"Input approved on OSP but {issue_reason}.",
                    reason_code="approved_with_issues",
                    reason_params={
                        "input": label,
                        "resolvedName": getattr(resolved, "brand_name", None),
                        "issues": issue_codes,
                        **issue_params,
                    },
                    input_label=label,
                    resolved_via="wsda",
                    resolved_id=event.wsda_material_id,
                    resolved_name=getattr(resolved, "brand_name", None),
                    cdfa_oim_status=cdfa,
                    ca_dpr_permit_status=dpr,
                    wsda_verified_at=wsda_ts,
                    cdfa_oim_verified_at=cdfa_ts if cdfa else None,
                )
            return None
        # Same cross-registry rule as the other FK branches: ANY catalog approval clears.
        rescue = _name_approval_clears((event.commercial_name or "").strip())
        if rescue:
            return _rescued_approved_result(rescue, label)
        cdfa_ts = _now_iso()
        cdfa = _ca_sub(resolved)
        return _build_drift_warning(
            osp=osp,
            reason="WSDA material not in active OSP approved inputs",
            reason_code="wsda_not_in_osp",
            reason_params={"input": label, "resolvedName": getattr(resolved, "brand_name", None)},
            input_label=label,
            resolved_via="wsda",
            resolved_id=event.wsda_material_id,
            resolved_name=getattr(resolved, "brand_name", None),
            cdfa_oim_status=cdfa,
            ca_dpr_permit_status=_dpr_sub(label, resolved),
            wsda_verified_at=wsda_ts,
            cdfa_oim_verified_at=cdfa_ts if cdfa else None,
        )
    if event.national_list_substance_id:
        from certifications.models import NationalListSubstance

        nl_ts = _now_iso()
        nl_obj = NationalListSubstance.objects.filter(pk=event.national_list_substance_id).first()
        label = event.commercial_name or (
            getattr(nl_obj, "substance_name", None) or f"NationalListSubstance #{event.national_list_substance_id}"
        )
        if event.national_list_substance_id in approved_nl_ids:
            # OSP-approved National List substance — still surface DPR if applicable.
            dpr = _dpr_sub(label, nl_obj)
            issue_reason, issue_codes, issue_params = _approved_issue_reason(None, dpr)
            if issue_reason:
                return _build_drift_warning(
                    osp=osp,
                    reason=f"Input approved on OSP but {issue_reason}.",
                    reason_code="approved_with_issues",
                    reason_params={
                        "input": label,
                        "resolvedName": event.commercial_name,
                        "issues": issue_codes,
                        **issue_params,
                    },
                    input_label=label,
                    resolved_via="national_list",
                    resolved_id=event.national_list_substance_id,
                    resolved_name=event.commercial_name,
                    ca_dpr_permit_status=dpr,
                    national_list_verified_at=nl_ts,
                )
            return None
        # The stamped NL substance is not on the plan — but the PRODUCT may be
        # approved there via its OMRI or WSDA listing ("Entrust SC" → the plan's
        # "Entrust SC Naturalyte Insect Control"). Flagging without this check
        # told a farmer to notify their certifier about a material already on
        # their plan (live false positive, 2026-08-25, dev farm 167).
        rescue = _name_approval_clears((event.commercial_name or "").strip())
        if rescue:
            return _rescued_approved_result(rescue, label)
        return _build_drift_warning(
            osp=osp,
            reason="National List substance not in active OSP approved inputs",
            reason_code="nl_not_in_osp",
            reason_params={
                "input": label,
                "substance": getattr(nl_obj, "substance_name", None),
            },
            input_label=label,
            resolved_via="national_list",
            resolved_id=event.national_list_substance_id,
            resolved_name=event.commercial_name,
            ca_dpr_permit_status=_dpr_sub(label, nl_obj),
            national_list_verified_at=nl_ts,
        )

    # Layer 2 — name match via commercial_name against approved items' names.
    #
    # Resolution model (Phase 1 cross-catalog fix): a product may appear in
    # BOTH the OMRI and WSDA catalogs. If the farmer approved the product as
    # WSDA on the OSP, the finding MUST clear even though OMRI also resolves.
    # Previously OMRI-first priority produced a false-positive in that case.
    # We now resolve into BOTH catalogs up-front, check every resolution
    # against the OSP approved set, and clear on any match. If no catalog
    # match is OSP-approved, we emit a single finding using the highest-
    # confidence resolver (OMRI > WSDA > National List) so the farmer sees
    # the clearest guidance.
    name = (event.commercial_name or "").strip()
    if not name:
        return None

    from certifications.services.omri_verifier import _resolve_omri_by_name, _resolve_wsda_by_name

    # Capture per-lookup timestamps so each drift finding carries a § 205.103(b)(2)
    # audit-grade record of WHEN this specific event was cross-referenced against
    # each catalog. System-wide catalog-freshness stamps (_catalog_freshness_line
    # in audit_export_service) are necessary but not sufficient under SOE.
    omri_ts = _now_iso()
    resolved_omri = _resolve_omri_by_name(name)
    wsda_ts = _now_iso()
    resolved_wsda = _resolve_wsda_by_name(name)

    # Cross-catalog approval — ANY catalog approval clears the finding.
    omri_approved = resolved_omri is not None and resolved_omri.id in approved_omri_ids
    wsda_approved = resolved_wsda is not None and resolved_wsda.id in approved_wsda_ids

    # The fourth source, which no layer could see until 2026-09-07: a material the operator
    # typed onto their own materials list. Without it, compost, manure, gypsum and limestone —
    # the CCOF NOPB41 §A examples no catalogue carries — produced a § 205.400(f)(2) finding on
    # every single application, against the very plan they were sitting on.
    if _operator_entry_by_name(osp, name) is not None:
        return None

    if omri_approved or wsda_approved:
        # Use whichever catalog produced the approval for the CDFA sub-finding
        # display; prefer the approved side. (OMRI's CDFA metadata is
        # populated by the same seed_cdfa_oim command as WSDA, so either side
        # is equally authoritative for the sub-finding.)
        approved_obj = resolved_omri if omri_approved else resolved_wsda
        resolved_via = "omri" if omri_approved else "wsda"
        approved_name = (
            approved_obj.product_name if omri_approved else approved_obj.brand_name  # type: ignore[union-attr]
        )
        cdfa_ts = _now_iso()
        cdfa = _ca_sub(approved_obj)
        dpr = _dpr_sub(name, approved_obj)
        issue_reason, issue_codes, issue_params = _approved_issue_reason(cdfa, dpr)
        if issue_reason:
            return _build_drift_warning(
                osp=osp,
                reason=(
                    f"Input '{name}' is OSP-approved ({resolved_via.upper()}: {approved_name}) " f"but {issue_reason}."
                ),
                reason_code="approved_with_issues",
                reason_params={
                    "input": name,
                    "resolvedName": approved_name,
                    "issues": issue_codes,
                    **issue_params,
                },
                input_label=name,
                resolved_via=resolved_via,
                resolved_id=approved_obj.id,  # type: ignore[union-attr]
                resolved_name=approved_name,
                cdfa_oim_status=cdfa,
                ca_dpr_permit_status=dpr,
                omri_verified_at=omri_ts if resolved_omri is not None else None,
                wsda_verified_at=wsda_ts if resolved_wsda is not None else None,
                cdfa_oim_verified_at=cdfa_ts if cdfa else None,
            )
        return None

    if resolved_omri:
        cdfa_ts = _now_iso()
        cdfa = _ca_sub(resolved_omri)
        dpr = _dpr_sub(name, resolved_omri)
        return _build_drift_warning(
            osp=osp,
            reason=(
                f"Input '{name}' resolves to OMRI catalog '{resolved_omri.product_name}' "
                "but that product is not in the active OSP approved inputs."
            ),
            reason_code="name_omri_not_in_osp",
            reason_params={"input": name, "resolvedName": resolved_omri.product_name},
            input_label=name,
            resolved_via="omri",
            resolved_id=resolved_omri.id,
            resolved_name=resolved_omri.product_name,
            cdfa_oim_status=cdfa,
            ca_dpr_permit_status=dpr,
            omri_verified_at=omri_ts,
            wsda_verified_at=wsda_ts if resolved_wsda is not None else None,
            cdfa_oim_verified_at=cdfa_ts if cdfa else None,
        )

    if resolved_wsda:
        cdfa_ts = _now_iso()
        cdfa = _ca_sub(resolved_wsda)
        dpr = _dpr_sub(name, resolved_wsda)
        return _build_drift_warning(
            osp=osp,
            reason=(
                f"Input '{name}' resolves to WSDA Materials List entry "
                f"'{resolved_wsda.brand_name}' but that product is not in the "
                "active OSP approved inputs."
            ),
            reason_code="name_wsda_not_in_osp",
            reason_params={"input": name, "resolvedName": resolved_wsda.brand_name},
            input_label=name,
            resolved_via="wsda",
            resolved_id=resolved_wsda.id,
            resolved_name=resolved_wsda.brand_name,
            cdfa_oim_status=cdfa,
            ca_dpr_permit_status=dpr,
            omri_verified_at=omri_ts,
            wsda_verified_at=wsda_ts,
            cdfa_oim_verified_at=cdfa_ts if cdfa else None,
        )

    nl_ts = _now_iso()
    resolved_nl = _resolve_national_list_by_name(name)
    if resolved_nl:
        if resolved_nl.id in approved_nl_ids:
            # OSP-approved NL substance — still surface DPR if applicable.
            dpr = _dpr_sub(name, resolved_nl)
            issue_reason, issue_codes, issue_params = _approved_issue_reason(None, dpr)
            if issue_reason:
                return _build_drift_warning(
                    osp=osp,
                    reason=f"Input '{name}' is OSP-approved but {issue_reason}.",
                    reason_code="approved_with_issues",
                    reason_params={
                        "input": name,
                        "resolvedName": resolved_nl.substance_name,
                        "issues": issue_codes,
                        **issue_params,
                    },
                    input_label=name,
                    resolved_via="national_list",
                    resolved_id=resolved_nl.id,
                    resolved_name=resolved_nl.substance_name,
                    ca_dpr_permit_status=dpr,
                    omri_verified_at=omri_ts,
                    wsda_verified_at=wsda_ts,
                    national_list_verified_at=nl_ts,
                )
            return None
        return _build_drift_warning(
            osp=osp,
            reason=(
                f"Input '{name}' resolves to National List substance "
                f"'{resolved_nl.substance_name}' but that substance is not in the "
                "active OSP approved inputs."
            ),
            reason_code="name_nl_not_in_osp",
            reason_params={"input": name, "substance": resolved_nl.substance_name},
            input_label=name,
            resolved_via="national_list",
            resolved_id=resolved_nl.id,
            resolved_name=resolved_nl.substance_name,
            ca_dpr_permit_status=_dpr_sub(name, resolved_nl),
            omri_verified_at=omri_ts,
            wsda_verified_at=wsda_ts,
            national_list_verified_at=nl_ts,
        )

    return _build_drift_warning(
        osp=osp,
        reason=f"Input '{name}' not matched to any approved OSP input",
        reason_code="unresolved",
        reason_params={"input": name},
        input_label=name,
        resolved_via="unresolved",
        resolved_name=name,
        omri_search_url=_omri_search_url(name),
        ca_dpr_permit_status=_dpr_sub(name, None),
        omri_verified_at=omri_ts,
        wsda_verified_at=wsda_ts,
        national_list_verified_at=nl_ts,
    )


def _resolve_national_list_by_name(farmer_input: str):
    """Mirror of _resolve_omri_by_name for NationalListSubstance.

    Kept in this module (not omri_verifier) to avoid importing the verifier
    module into the signal path — we only need the thin NL lookup here. The
    normalization helpers live in omri_verifier and are imported lazily.
    """
    from certifications.models import NationalListSubstance
    from certifications.services.omri_verifier import _name_tokens, _normalize

    normalized = _normalize(farmer_input)
    if not normalized:
        return None

    # 1) Exact normalized match against the pre-normalized column.
    exact = NationalListSubstance.objects.filter(substance_name_normalized=normalized).first()
    if exact:
        return exact

    farmer_tokens = _name_tokens(farmer_input)
    if not farmer_tokens:
        return None

    # 2) Containment with ≥5 chars, same guard rails as the existing verifier.
    MIN_MATCH_LEN = 5
    candidates = []
    for pk, nl_norm in NationalListSubstance.objects.values_list("id", "substance_name_normalized"):
        if len(nl_norm) >= MIN_MATCH_LEN and nl_norm in normalized:
            candidates.append((len(nl_norm), pk))
    if candidates:
        best_pk = max(candidates)[1]
        return NationalListSubstance.objects.filter(pk=best_pk).first()
    return None


def _operator_entry_by_name(osp, farmer_input: str):
    """The operator's own materials-list row matching this input name, or None.

    The fourth source on a plan (`PlanMaterialEntry`, 2026-08-28) — the compost, manure,
    gypsum and limestone CCOF NOPB41 §A asks for by name and no catalog can supply. The
    detector could not see it until 2026-09-07, so those materials flagged as unapproved on
    every application while sitting on the very plan the finding said they were missing from.

    ⛔ EXACT normalized match, never fuzzy. `plan_materials.py` states the reason: these are
    the operator's own words, and a fuzzy match "would quietly mark a material as covered when
    nobody decided that it was" — the invention class this codebase keeps removing. A brand
    the operator typed slightly differently should flag, and be reconciled by a human.
    """
    from certifications.services.omri_verifier import _normalize

    normalized = _normalize(farmer_input)
    if not normalized:
        return None
    for entry in osp.plan_material_entries.all():
        if _normalize(entry.product_name) == normalized:
            return entry
    return None


def _classify_soil_event(event, osp) -> Optional[Dict[str, Any]]:
    """SoilManagementEvent has no FKs to the approved-input tables, so drift
    detection is name-based against `amendment_type`. Narrower than chemical
    events — many soil events (tillage, cover crop, soil test) carry no
    amendment input at all and should not flag drift.
    """
    # Only soil events that materially add an amendment need OSP approval.
    # Types without an amendment (SOIL_TEST, PH_ADJUSTMENT done via naturally
    # occurring materials tracked separately, TILLAGE, COVER_CROP, GRAZING)
    # can't drift via amendment_type.
    # 🔴 PA added 2026-09-07. The activity form renders `amendment_product_name` for
    # ['PA', 'OM', 'CC', 'CO'] (`config/events/soilEvent.ts`), so a pH-adjustment product was
    # recorded and then never checked against anything — and PA is precisely where the
    # National List materials live: lime, gypsum and elemental sulfur are all § 205.601
    # entries. A grower could log a pH amendment that is not on their plan and the packet
    # would report no finding.
    #
    # ⛔ CC (cover crop) is deliberately NOT here. Its product name is a seed mix, which is
    # § 205.204 territory handled by `evaluate_seed_event` — seed is not in the OMRI/WSDA
    # input catalogues, so running this matcher over it would resolve to nothing every time
    # and manufacture an "unresolved input" finding on every cover-crop planting.
    AMENDMENT_TYPES = {"OM", "CO", "PA"}  # ORGANIC_MATTER, COMPOSTING, PH_ADJUSTMENT
    if event.type not in AMENDMENT_TYPES:
        return None

    # The PRODUCT name is what can drift against a catalog. `amendment_type` is a
    # category enum ("compost", "mulch", "manure", "other") — running the matcher on
    # those words flagged on-farm compost as an "unresolved input" farm-wide
    # (2026-08-25, recompute on dev farm 167). A category needs no OMRI listing; a
    # purchased product does, and its name lives in `amendment_product_name`.
    amendment = (event.amendment_product_name or "").strip()
    if not amendment:
        return None

    from certifications.services.omri_verifier import _resolve_omri_by_name, _resolve_wsda_by_name

    approved_omri_ids = set(osp.approved_omri_products.values_list("id", flat=True))
    approved_nl_ids = set(osp.approved_national_list_substances.values_list("id", flat=True))
    approved_wsda_ids = set(osp.approved_wsda_materials.values_list("id", flat=True))
    is_ca = _establishment_is_in_california(event)

    def _ca_sub(resolved_obj):
        # Soil amendments default to fertilizing-material CDFA OIM scope, so
        # we don't filter by category here the way the chemical classifier does.
        if not is_ca or resolved_obj is None:
            return None
        return _resolved_input_cdfa_status(resolved_obj)

    # Cross-catalog approval — same fix as the chemical classifier. A soil
    # amendment on BOTH OMRI and WSDA is cleared by a single OSP approval
    # on either side.
    omri_ts = _now_iso()
    resolved_omri = _resolve_omri_by_name(amendment)
    wsda_ts = _now_iso()
    resolved_wsda = _resolve_wsda_by_name(amendment)

    omri_approved = resolved_omri is not None and resolved_omri.id in approved_omri_ids
    wsda_approved = resolved_wsda is not None and resolved_wsda.id in approved_wsda_ids

    # The other two sources on the plan, which this classifier could not see until 2026-09-07.
    # Both matter more here than on the chemical side: a pH amendment IS usually a National
    # List substance (lime, gypsum, elemental sulfur), and on-farm compost and manure are
    # exactly the operator-entered rows no catalogue carries.
    resolved_nl = _resolve_national_list_by_name(amendment)
    if resolved_nl is not None and resolved_nl.id in approved_nl_ids:
        return None
    if _operator_entry_by_name(osp, amendment) is not None:
        return None

    if omri_approved or wsda_approved:
        approved_obj = resolved_omri if omri_approved else resolved_wsda
        resolved_via = "omri" if omri_approved else "wsda"
        approved_name = (
            approved_obj.product_name if omri_approved else approved_obj.brand_name  # type: ignore[union-attr]
        )
        cdfa_ts = _now_iso()
        cdfa = _ca_sub(approved_obj)
        if cdfa and cdfa.get("status") == CDFA_OIM_UNKNOWN:
            return _build_drift_warning(
                osp=osp,
                reason=(
                    f"Soil amendment '{amendment}' is OSP-approved "
                    f"({resolved_via.upper()}: {approved_name}). CDFA OIM "
                    "registration was not checked — this product is not in Trazo's "
                    "CDFA reference set, which covers only part of the CDFA "
                    "Registered OIM Products list. Confirm registration with CDFA "
                    "before applying it in California."
                ),
                reason_code="approved_with_issues",
                reason_params={
                    "input": amendment,
                    "resolvedName": approved_name,
                    "issues": ["cdfa_unknown"],
                },
                input_label=amendment,
                resolved_via=resolved_via,
                resolved_id=approved_obj.id,  # type: ignore[union-attr]
                resolved_name=approved_name,
                cdfa_oim_status=cdfa,
                omri_verified_at=omri_ts if resolved_omri is not None else None,
                wsda_verified_at=wsda_ts if resolved_wsda is not None else None,
                cdfa_oim_verified_at=cdfa_ts,
            )
        return None

    if resolved_omri:
        cdfa_ts = _now_iso()
        cdfa = _ca_sub(resolved_omri)
        return _build_drift_warning(
            osp=osp,
            reason=(
                f"Soil amendment '{amendment}' resolves to OMRI catalog "
                f"'{resolved_omri.product_name}' but that product is not in the "
                "active OSP approved inputs."
            ),
            reason_code="name_omri_not_in_osp",
            reason_params={"input": amendment, "resolvedName": resolved_omri.product_name},
            input_label=amendment,
            resolved_via="omri",
            resolved_id=resolved_omri.id,
            resolved_name=resolved_omri.product_name,
            cdfa_oim_status=cdfa,
            omri_verified_at=omri_ts,
            wsda_verified_at=wsda_ts if resolved_wsda is not None else None,
            cdfa_oim_verified_at=cdfa_ts if cdfa else None,
        )

    if resolved_wsda:
        cdfa_ts = _now_iso()
        cdfa = _ca_sub(resolved_wsda)
        return _build_drift_warning(
            osp=osp,
            reason=(
                f"Soil amendment '{amendment}' resolves to WSDA Materials List "
                f"entry '{resolved_wsda.brand_name}' but that product is not in "
                "the active OSP approved inputs."
            ),
            reason_code="name_wsda_not_in_osp",
            reason_params={"input": amendment, "resolvedName": resolved_wsda.brand_name},
            input_label=amendment,
            resolved_via="wsda",
            resolved_id=resolved_wsda.id,
            resolved_name=resolved_wsda.brand_name,
            cdfa_oim_status=cdfa,
            omri_verified_at=omri_ts,
            wsda_verified_at=wsda_ts,
            cdfa_oim_verified_at=cdfa_ts if cdfa else None,
        )

    nl_ts = _now_iso()
    resolved_nl = _resolve_national_list_by_name(amendment)
    if resolved_nl:
        if resolved_nl.id in approved_nl_ids:
            return None
        return _build_drift_warning(
            osp=osp,
            reason=(
                f"Soil amendment '{amendment}' resolves to National List "
                f"substance '{resolved_nl.substance_name}' but that substance is "
                "not in the active OSP approved inputs."
            ),
            reason_code="name_nl_not_in_osp",
            reason_params={"input": amendment, "substance": resolved_nl.substance_name},
            input_label=amendment,
            resolved_via="national_list",
            resolved_id=resolved_nl.id,
            resolved_name=resolved_nl.substance_name,
            omri_verified_at=omri_ts,
            wsda_verified_at=wsda_ts,
            national_list_verified_at=nl_ts,
        )

    return _build_drift_warning(
        osp=osp,
        reason=f"Soil amendment '{amendment}' not in active OSP approved inputs",
        reason_code="unresolved",
        reason_params={"input": amendment},
        input_label=amendment,
        resolved_via="unresolved",
        resolved_name=amendment,
        omri_search_url=_omri_search_url(amendment),
        omri_verified_at=omri_ts,
        wsda_verified_at=wsda_ts,
        national_list_verified_at=nl_ts,
    )


def _evaluate(event, classifier):
    """Shared flow: resolve establishment → plan (active, else newest draft) → classify → persist.

    Writes drift_warning via .filter(pk=).update() so we don't recurse through
    post_save. Swallows all exceptions (drift detection must never break a save).
    """
    try:
        establishment_id = _event_establishment_id(event)
        if not establishment_id:
            return
        osp, _provisional = _osp_for_drift(establishment_id)
        if osp is None:
            # Clear any stale drift_warning if there is no longer ANY plan to compare
            # against — the warning belongs to an OSP that may be withdrawn or superseded
            # now. Keeps the audit export honest.
            if event.drift_warning is not None:
                type(event).objects.filter(pk=event.pk).update(drift_warning=None)
            return
        warning = classifier(event, osp)
        # Only write when the value actually changes — spares auditlog noise.
        if warning != event.drift_warning:
            type(event).objects.filter(pk=event.pk).update(drift_warning=warning)
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "Drift detector failed for event pk=%s of type=%s (non-blocking)",
            getattr(event, "pk", None),
            type(event).__name__,
        )


def evaluate_chemical_event(event):
    _evaluate(event, _classify_chemical_event)


def evaluate_soil_event(event):
    _evaluate(event, _classify_soil_event)


def evaluate_seed_event(event):
    """Only PL-subtype ProductionEvents carry § 205.204 seed metadata.

    _evaluate() handles the OSP / no-OSP branching uniformly; the classifier
    early-returns None for non-PL subtypes so drift_warning on irrigation /
    harvest / pruning stays untouched.
    """
    _evaluate(event, _classify_seed_event)


def attach_signals():
    """Wire post_save handlers. Called from history.apps.HistoryConfig.ready()."""
    from django.db.models.signals import post_save

    from history.models import ChemicalEvent, ProductionEvent, SoilManagementEvent

    def _chemical(sender, instance, **kwargs):
        # Defer until the surrounding transaction commits so M2Ms / relations
        # from the caller's transaction.atomic() block are visible.
        transaction.on_commit(lambda: evaluate_chemical_event(instance))

    def _soil(sender, instance, **kwargs):
        transaction.on_commit(lambda: evaluate_soil_event(instance))

    def _seed(sender, instance, **kwargs):
        transaction.on_commit(lambda: evaluate_seed_event(instance))

    # weak=False is REQUIRED: these receivers are module-local closures with no other
    # strong reference once attach_signals() returns. With Django's default weak=True the
    # signal keeps only a weak ref, so the next GC cycle collects them and drift detection
    # silently stops firing on save. (This is why the drift never stamped in tests and would
    # intermittently die in a long-running server.)
    post_save.connect(
        _chemical,
        sender=ChemicalEvent,
        dispatch_uid="drift_detector.chemical_event",
        weak=False,
    )
    post_save.connect(
        _soil,
        sender=SoilManagementEvent,
        dispatch_uid="drift_detector.soil_event",
        weak=False,
    )
    post_save.connect(
        _seed,
        sender=ProductionEvent,
        dispatch_uid="drift_detector.production_event",
        weak=False,
    )
