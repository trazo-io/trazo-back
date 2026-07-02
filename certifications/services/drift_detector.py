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
      - ``cdfa_oim_status``: CA-only sub-finding ({status, cdfa_oim_reg_number}).
        Set when the establishment is in California and the resolved input
        lacks a CDFA OIM registration. Independent of OSP approval.
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
    payload = {
        "detected_at": _now_iso(),
        "osp_id": osp.id,
        "osp_version": osp.version_number,
        "input_label": input_label,
        "reason": reason,
        "resolved_via": resolved_via,
        "resolved_id": resolved_id,
        "resolved_name": resolved_name,
        "cfr_reference": "7 CFR 205.400(f)(2)",
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


def _resolved_input_cdfa_status(resolved_obj) -> Optional[Dict[str, Any]]:
    """Return a {status, cdfa_oim_reg_number} dict if the resolved object has
    CDFA OIM metadata, else None. Applies to OMRIProduct and WSDAMaterial."""
    if resolved_obj is None:
        return None
    is_registered = getattr(resolved_obj, "is_cdfa_oim_registered", False)
    reg = getattr(resolved_obj, "cdfa_oim_reg_number", None)
    if is_registered and reg:
        return {"status": "registered", "cdfa_oim_reg_number": reg}
    return {"status": "missing", "cdfa_oim_reg_number": None}


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
        """Build reason string when OSP-approved input has CDFA/DPR gaps.
        Returns None when neither gap is present."""
        parts = []
        if cdfa and cdfa.get("status") == "missing":
            parts.append(
                "CDFA OIM registration is missing — California state law "
                "requires OIM registration for fertilizing materials"
            )
        if dpr and dpr.get("status") == "missing":
            parts.append(
                "CA DPR restricted-materials permit missing — county Ag "
                "Commissioner permit required before application"
            )
        elif dpr and dpr.get("status") == "expired":
            parts.append(
                f"CA DPR permit #{dpr.get('permit_number')} expired on "
                f"{dpr.get('expires')} — renew before next application"
            )
        return "; ".join(parts) if parts else None

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
            issue_reason = _approved_issue_reason(cdfa, dpr)
            if issue_reason:
                return _build_drift_warning(
                    osp=osp,
                    reason=f"Input approved on OSP but {issue_reason}.",
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
        cdfa_ts = _now_iso()
        cdfa = _ca_sub(resolved)
        return _build_drift_warning(
            osp=osp,
            reason="OMRI product not in active OSP approved inputs",
            input_label=label,
            resolved_via="omri",
            resolved_id=event.omri_product_id,
            resolved_name=event.commercial_name,
            cdfa_oim_status=cdfa,
            ca_dpr_permit_status=_dpr_sub(label, resolved),
            omri_verified_at=omri_ts,
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
            issue_reason = _approved_issue_reason(None, dpr)
            if issue_reason:
                return _build_drift_warning(
                    osp=osp,
                    reason=f"Input approved on OSP but {issue_reason}.",
                    input_label=label,
                    resolved_via="national_list",
                    resolved_id=event.national_list_substance_id,
                    resolved_name=event.commercial_name,
                    ca_dpr_permit_status=dpr,
                    national_list_verified_at=nl_ts,
                )
            return None
        return _build_drift_warning(
            osp=osp,
            reason="National List substance not in active OSP approved inputs",
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
        issue_reason = _approved_issue_reason(cdfa, dpr)
        if issue_reason:
            return _build_drift_warning(
                osp=osp,
                reason=(
                    f"Input '{name}' is OSP-approved ({resolved_via.upper()}: {approved_name}) " f"but {issue_reason}."
                ),
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
            issue_reason = _approved_issue_reason(None, dpr)
            if issue_reason:
                return _build_drift_warning(
                    osp=osp,
                    reason=f"Input '{name}' is OSP-approved but {issue_reason}.",
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
    AMENDMENT_TYPES = {"OM", "CO"}  # ORGANIC_MATTER, COMPOSTING
    if event.type not in AMENDMENT_TYPES:
        return None

    amendment = (event.amendment_type or "").strip()
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

    if omri_approved or wsda_approved:
        approved_obj = resolved_omri if omri_approved else resolved_wsda
        resolved_via = "omri" if omri_approved else "wsda"
        approved_name = (
            approved_obj.product_name if omri_approved else approved_obj.brand_name  # type: ignore[union-attr]
        )
        cdfa_ts = _now_iso()
        cdfa = _ca_sub(approved_obj)
        if cdfa and cdfa.get("status") == "missing":
            return _build_drift_warning(
                osp=osp,
                reason=(
                    f"Soil amendment '{amendment}' is OSP-approved "
                    f"({resolved_via.upper()}: {approved_name}) but CDFA OIM "
                    "registration is missing — California state law requires "
                    "OIM registration for fertilizing materials."
                ),
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
        input_label=amendment,
        resolved_via="unresolved",
        resolved_name=amendment,
        omri_search_url=_omri_search_url(amendment),
        omri_verified_at=omri_ts,
        wsda_verified_at=wsda_ts,
        national_list_verified_at=nl_ts,
    )


def _evaluate(event, classifier):
    """Shared flow: resolve establishment → active OSP → classifier → persist.

    Writes drift_warning via .filter(pk=).update() so we don't recurse through
    post_save. Swallows all exceptions (drift detection must never break a save).
    """
    try:
        establishment_id = _event_establishment_id(event)
        if not establishment_id:
            return
        osp = _active_osp_for_establishment(establishment_id)
        if osp is None:
            # Clear any stale drift_warning if there's no longer an active OSP
            # to compare against — the warning belongs to an OSP that may be
            # superseded now. Keeps the audit export honest.
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

    post_save.connect(
        _chemical,
        sender=ChemicalEvent,
        dispatch_uid="drift_detector.chemical_event",
    )
    post_save.connect(
        _soil,
        sender=SoilManagementEvent,
        dispatch_uid="drift_detector.soil_event",
    )
    post_save.connect(
        _seed,
        sender=ProductionEvent,
        dispatch_uid="drift_detector.production_event",
    )
