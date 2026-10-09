"""
Lot-level claim resolver — Phase 3 of the consumer QR claim-safety plan.

ConsumerClaimValidator (certifications app) answers the FARM-level question:
"may this operation be represented as organic?" This module answers the
LOT-level question the live page exposed (a USDA-certified fixture rendering
"2 of 5 inputs organic-approved" under the seal): "may THIS production lot be
represented as organic?"

Per 7 CFR 205.105 / 205.300, a lot from a certified operation must not be
represented as organic when prohibited substances were applied to it, when the
certificate was not valid at harvest, or when the certificate does not cover
crops. The resolver is intentionally conservative: it only ever DOWNGRADES a
farm-level "certified_organic" claim; it never upgrades anything.

It also emits the evidence-status object every consumer claim carries
(certified | verified | documented | self_reported, plus scope and as_of) so
the QR page and the audit export read the same resolution — one input, two
outputs.
"""

from dataclasses import asdict, dataclass, field
from typing import List, Optional

from django.utils import timezone

from common.field_registry import ORGANIC_APPROVED_OK_VALUES

# ChemicalEvent.organic_approved values that mark an input as explicitly
# prohibited for organic production. Null/blank means "farmer didn't classify"
# — that is an unknown, not a violation, and must not strip the claim.
#
# Deliberately NARROWER than field_registry.ORGANIC_PROHIBITED_VALUES, which the
# transition clock uses: "transitional" is not organic-approved and so resets a
# § 205.202(b) clock, but it is also not a consumer-facing claim violation.
PROHIBITED_INPUT_VALUES = {"not_organic", "no"}

# Values that affirmatively clear an input for organic use. Shared with the
# transition clock — a locally-maintained copy of this list is how an OMRI-listed
# fungicide came to be counted as a prohibited substance (see field_registry).
ORGANIC_APPROVED_VALUES = ORGANIC_APPROVED_OK_VALUES


def event_organic_classification(event) -> str:
    """
    organic_approved with the same extra_data fallback the public serializer
    uses (legacy rows stored it as extra_data.organic_certification /
    .organic_approved before the model field existed). Keeping the fallback
    here means the lot gate and the chip resolver see the same value the
    payload renders.
    """
    value = (getattr(event, "organic_approved", "") or "").strip()
    if value:
        return value
    extra = getattr(event, "extra_data", None)
    if isinstance(extra, dict):
        return str(extra.get("organic_certification") or extra.get("organic_approved") or "").strip()
    return ""


def event_is_restricted_use(event) -> bool:
    """restricted_use_pesticide with the legacy extra_data fallback."""
    if getattr(event, "restricted_use_pesticide", False):
        return True
    extra = getattr(event, "extra_data", None)
    return bool(isinstance(extra, dict) and extra.get("restricted_use_pesticide"))


@dataclass
class LotOrganicEligibility:
    """
    Outcome of the lot-level organic eligibility check.

    eligible:
        True  — lot may carry the farm's organic representation
        False — lot must NOT be represented as organic (reason in status)
        None  — not applicable (farm is not certified organic; nothing to gate)
    status:
        "eligible" | "prohibited_input" | "cert_not_valid_at_harvest"
        | "crop_not_in_scope" | "not_applicable"
    """

    eligible: Optional[bool]
    status: str
    display_label: str
    detail: str
    prohibited_inputs: List[str] = field(default_factory=list)
    unclassified_input_count: int = 0
    checked_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def resolve_lot_organic_eligibility(history, cert) -> LotOrganicEligibility:
    """
    Gate the farm-level organic claim down to this production lot.

    Args:
        history: history.models.History (the production lot).
        cert: the active verified USDA Organic Certification record used for
              the farm-level claim (from ConsumerClaimValidator), or None.

    Checks, in order of severity:
      1. Prohibited inputs — any ChemicalEvent on this lot explicitly marked
         not-organic (7 CFR 205.105).
      2. Certificate validity at harvest — the cert must have been effective
         on the harvest date (finish_date; falls back to today for in-progress
         productions).
      3. Crop scope — the certificate must cover crops (a handling-only or
         livestock-only certificate does not certify produce lots).

    Unclassified inputs (organic_approved null/blank) are surfaced as a count
    but never fail the check — absence of classification is not evidence of a
    violation.
    """
    now_iso = timezone.now().isoformat()

    if cert is None:
        return LotOrganicEligibility(
            eligible=None,
            status="not_applicable",
            display_label="",
            detail="Farm is not certified organic; no lot-level gate applies.",
            checked_at=now_iso,
        )

    # --- 1. Prohibited inputs on this lot -----------------------------------
    # Two signals, same verdict the audit PDF's cross-check engine uses:
    # farmer classification (organic_approved) and the National List match
    # (7 CFR 205.602 — a "prohibited" substance match overrides whatever the
    # farmer self-reported).
    chemical_events = list(history.history_chemicalevent_events.all())

    def _is_prohibited(e):
        if event_organic_classification(e) in PROHIBITED_INPUT_VALUES:
            return True
        # Phase 5 slice 1: a lot is never marked not-organic on a guessed or legacy classification.
        from history.services.national_list_basis import confirmed_national_list_substance

        nl = confirmed_national_list_substance(e)
        if nl is None or getattr(nl, "status", None) != "prohibited":
            return False
        # 🔴 2026-08-20 — not every § 205.602 entry is an absolute bar. Three of them are
        # conditional: the CFR prohibits the substance EXCEPT for one named use. Calcium
        # chloride (brine process) is prohibited "except as a foliar spray to treat a
        # physiological disorder associated with calcium uptake" — which is exactly what a
        # Honeycrisp block's bitter-pit calcium programme is, and every organic Honeycrisp
        # grower in Washington runs one.
        #
        # Failing the lot on that match would revoke the whole lot-level organic claim of a
        # legitimately certified operation and publish "this lot: not represented as organic"
        # to shoppers over a compliant practice. A false negative here is not the safe
        # direction — it is a public accusation the farm did not earn.
        #
        # Whether the recorded purpose actually meets the condition is a certifier judgement
        # over farmer-written free text, so the consumer gate does not attempt it; the
        # certifier packet raises these under its [REVIEW] note instead, where a human reads
        # the annotation beside the recorded use.
        return not getattr(nl, "is_conditionally_permitted", False)

    prohibited = [
        (e.commercial_name or e.get_type_display() or "Unnamed input") for e in chemical_events if _is_prohibited(e)
    ]
    unclassified = sum(1 for e in chemical_events if not event_organic_classification(e))

    if prohibited:
        return LotOrganicEligibility(
            eligible=False,
            status="prohibited_input",
            display_label="Farm certified organic — this lot: not represented as organic",
            detail=(
                "One or more inputs applied to this lot are classified as not approved "
                "for organic production (7 CFR 205.105)."
            ),
            prohibited_inputs=prohibited,
            unclassified_input_count=unclassified,
            checked_at=now_iso,
        )

    # --- 2. Certificate validity at harvest ---------------------------------
    harvest_date = history.finish_date.date() if history.finish_date else timezone.now().date()
    effective = getattr(cert, "effective_date", None)
    expiry = getattr(cert, "expiry_date", None)
    if (effective and harvest_date < effective) or (expiry and harvest_date > expiry):
        return LotOrganicEligibility(
            eligible=False,
            status="cert_not_valid_at_harvest",
            display_label="Farm certified organic — certificate not valid at this lot's harvest",
            detail=(
                f"Harvest {harvest_date.isoformat()} falls outside the certificate window " f"({effective} – {expiry})."
            ),
            unclassified_input_count=unclassified,
            checked_at=now_iso,
        )

    # --- 3. Crop scope -------------------------------------------------------
    scope = (getattr(cert, "certification_scope", "") or "").lower()
    if scope and "crop" not in scope:
        return LotOrganicEligibility(
            eligible=False,
            status="crop_not_in_scope",
            display_label="Farm certified organic — certificate does not cover crops",
            detail=f"Certificate scope is '{cert.certification_scope}'; produce lots are not covered.",
            unclassified_input_count=unclassified,
            checked_at=now_iso,
        )

    return LotOrganicEligibility(
        eligible=True,
        status="eligible",
        display_label="USDA Certified Organic",
        detail="Certificate valid at harvest, crop scope covered, no prohibited inputs on this lot.",
        unclassified_input_count=unclassified,
        checked_at=now_iso,
    )


# --- Evidence-status objects -------------------------------------------------

# Tier vocabulary shared by the QR page and the audit export. Order matters:
# it is the trust hierarchy the UI renders (deep green → gray).
EVIDENCE_TIERS = ("certified", "verified", "documented", "self_reported")

_CLAIM_STATUS_TO_TIER = {
    "certified_organic": "certified",
    "transitioning": "documented",
    "self_reported": "self_reported",
    "conventional": "documented",
    # A fabricated operation takes the LOWEST tier in the hierarchy. Not "documented": that word
    # says records exist and were kept, which is the one thing a specimen's records are not.
    # Added 2026-09-16 with STATUS_SPECIMEN; without a row here the `.get(status, "documented")`
    # default would have quietly promoted a specimen above self-reported.
    "specimen": "self_reported",
}


def build_organic_claim_evidence(organic_claim: dict, lot_eligibility: LotOrganicEligibility) -> dict:
    """
    Evidence-status object for the organic claim:
        { tier, source, scope, as_of }

    scope is "production_lot" only when the lot-level gate affirmatively
    passed; a certified farm with an ineligible (or ungated) lot stays
    "farm" — the page must not imply lot-level certification it can't back.
    """
    status = (organic_claim or {}).get("status", "conventional")
    tier = _CLAIM_STATUS_TO_TIER.get(status, "documented")
    if status == "certified_organic" and lot_eligibility.eligible is False:
        # Certified farm, ineligible lot: the lot claim degrades to documented
        # practices; the farm-level cert is still real and stays in `source`.
        tier = "documented"

    # 🔴 2026-08-30 — `source` names where the evidence CAME FROM, so it may only name the USDA
    # Organic Integrity Database when a match against it actually happened. It was derived from
    # `status == "certified_organic"` alone, which means "an active usda_organic certificate row
    # exists" — a row a manual admin edit, a data import or a fixture can create. Trazo really
    # does run OID matching (`USDAOrganicVerifier` against the mirrored monthly export), which is
    # exactly why naming it unearned matters: the claim is credible.
    #
    # `oid_matched` is computed once by ConsumerClaimValidator and travels on the claim. Reading
    # it here rather than re-deriving keeps this the fourth surface that consults one authority
    # instead of the fourth surface with its own opinion.
    oid_matched = bool((organic_claim or {}).get("oid_matched"))
    # A specimen operation's "source" must not name a record that does not exist. The validator
    # already forces `oid_matched` False for one, which stops the registry line; this stops the
    # fallback from asserting a certificate on file for an invented farm.
    specimen = bool((organic_claim or {}).get("specimen"))
    if specimen:
        source = "Demonstration data, not a real certificate or registry check"
    elif status == "certified_organic":
        source = "USDA Organic Integrity Database" if oid_matched else "Certificate on file for the operation"
    else:
        source = "Farmer-reported records"

    return {
        "tier": tier,
        "source": source,
        "scope": ("production_lot" if status == "certified_organic" and lot_eligibility.eligible is True else "farm"),
        "as_of": timezone.now().isoformat(),
    }


def resolve_input_status(chemical_event) -> dict:
    """
    Server-side input-status resolution for the consumer "Crop Inputs" chips —
    the frontend currently re-derives this client-side; serving it keeps the
    chip vocabulary in one place and lets the audit export reuse it.

        status: omri_listed | national_list_allowed | national_list_conditional
                | organic_approved | conventional_documented | unclassified

    The organic side of the vocabulary is NOT decided here — it is asked of
    ``claim_authority.may_claim_input_listing``. Until 2026-08-09 this function
    treated the farmer's ``organic_approved == "omri_listed"`` dropdown as
    equivalent to a catalog match and published the label "OMRI Listed" on the
    anonymous payload for inputs with no OMRI row and no National List row at
    all. Deciding locally what a public surface may claim is the exact defect
    class ``claim_authority`` exists to end; this function now only orders
    severity (prohibited/restricted beat organic) and maps to a chip status.
    """
    from history.services.claim_authority import (
        LABEL_INPUT_GROWER_REPORTED,
        LABEL_INPUT_NATIONAL_LIST,
        LABEL_INPUT_NATIONAL_LIST_CONDITIONAL,
        LABEL_INPUT_NATIONAL_LIST_PROHIBITED,
        LABEL_INPUT_OMRI_LISTED,
        LABEL_INPUT_WSDA_LISTED,
        _omri_listing_is_current,
        may_claim_input_listing,
    )

    organic = event_organic_classification(chemical_event)
    restricted = event_is_restricted_use(chemical_event)
    listing = may_claim_input_listing(chemical_event)
    # A linked catalog record — OMRI or WSDA — is stronger evidence than the farmer's dropdown
    # pick. Named for what it holds, not for one of the two catalogs: it gained the WSDA arm on
    # 2026-09-02 and a reader who trusted the old name `has_omri_match` would have concluded
    # the restricted-use branch below still tests OMRI alone.
    # A WITHDRAWN OMRI listing is not third-party evidence any more, so it must not hold the
    # restricted-use branch open either. Same reading as the label above, which is the point
    # of routing both through `claim_authority`.
    has_catalog_match = _omri_listing_is_current(chemical_event) or bool(
        getattr(chemical_event, "wsda_material_id", None)
    )

    # NOTE (2026-08-02): `restricted_use` is intentionally NOT a public chip status.
    # `restricted_use_pesticide` is stripped from the consumer payload
    # (PublicHistorySerializer._CERTIFIER_ONLY_EVENT_FIELDS) precisely because RUP is an
    # APPLICATOR-licensing category under 40 CFR 152.175 — it says who may buy and apply the
    # product, not that residue reaches a shopper. Re-publishing it here as
    # "Restricted use — licensed applicator" put that same implication back in words, which is
    # worse than the field it replaced. A restricted-use product that is not organic-approved
    # is a conventional input, and the chip says so; the certifier PDF carries the RUP flag.
    #
    # Restricted-use still outranks the organic tier, but the test is now "is there real
    # third-party evidence" (has_catalog_match) rather than "did the farmer pick omri_listed".
    # A grower's dropbox pick must not suppress the restricted-use ordering.
    if restricted and not has_catalog_match:
        status = "conventional_documented"
        label = "Conventional input · documented"
    elif listing.safe_label == LABEL_INPUT_NATIONAL_LIST_CONDITIONAL and organic not in PROHIBITED_INPUT_VALUES:
        # A § 205.602 entry the CFR permits for one stated use. Chipping it
        # "Conventional input · documented" told shoppers an organic block had used a
        # conventional input when the regulation writes that exact use out as allowed;
        # chipping it "allowed" would overclaim in the other direction. Say what is known:
        # it is listed, the listing carries a condition. The grower's own "not organic" pick
        # still outranks this — a farmer saying the input was not organic-approved is a
        # first-party statement no regulatory citation should soften.
        status = "national_list_conditional"
        label = LABEL_INPUT_NATIONAL_LIST_CONDITIONAL
    elif organic in PROHIBITED_INPUT_VALUES or listing.safe_label == LABEL_INPUT_NATIONAL_LIST_PROHIBITED:
        # Checked BEFORE the organic tiers: an explicitly not-organic input whose substance
        # happens to carry a § 205.601 citation must not be chipped as an allowed input, and a
        # § 205.602 prohibited match outranks whatever the grower picked from the dropdown.
        status = "conventional_documented"
        label = "Conventional input · documented"
    elif listing.safe_label == LABEL_INPUT_OMRI_LISTED:
        status = "omri_listed"
        label = LABEL_INPUT_OMRI_LISTED
    elif listing.safe_label == LABEL_INPUT_WSDA_LISTED:
        status = "wsda_listed"
        label = LABEL_INPUT_WSDA_LISTED
    elif listing.safe_label == LABEL_INPUT_NATIONAL_LIST:
        status = "national_list_allowed"
        label = LABEL_INPUT_NATIONAL_LIST
    elif listing.safe_label == LABEL_INPUT_GROWER_REPORTED:
        status = "organic_approved"
        label = LABEL_INPUT_GROWER_REPORTED
    else:
        status = "unclassified"
        label = "Documented"

    result = {"status": status, "label": label}
    if status == "organic_approved":
        # A National List substance LINKED to the record on a legacy (unconfirmed) basis is not
        # evidence for the chip, but it is on the record, and the tooltip that said "Trazo did not
        # find it in the OMRI or National List catalogs" was false for it (recordkeeping review
        # F-09). Named with its state. NOT a name suggestion (review of back #133): a suggestion
        # is a substring hit nobody linked, and a public page never names a listing Trazo guessed.
        # NOT a prohibited substance either: beside an "allowed for organic use" chip it would
        # read as a contradiction with nothing to disambiguate; the certifier dossier carries it.
        from history.services.national_list_basis import legacy_linked_national_list

        substance = legacy_linked_national_list(chemical_event)
        if substance is not None and getattr(substance, "status", "") == "allowed":
            result["national_list_link"] = {
                "substance": getattr(substance, "substance_name", "") or "",
                "cfr_section": getattr(substance, "cfr_section", "") or "",
                "basis": "not_confirmed",
            }
    return result
