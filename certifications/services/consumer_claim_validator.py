"""
Consumer Claim Validator — Sprint 5A.

Gates what organic/transitional language the consumer QR page is allowed to display
for a production. This is the primary FTC exposure point in Trazo: a farm still in
transition could technically flip History.production_method='organic' and surface
"Organic" on a QR page, which would violate:

  - 7 CFR 205.100(c)(1): operations producing products sold as "organic" must be
    certified.
  - 7 CFR 205.300(a): products may not be labeled/represented as organic without
    certification.
  - 16 CFR 260.6(d) (FTC Green Guides): marketers should not use environmental
    certifications/seals that do not convey the basis for the certification.
  - 16 CFR 260.6(c): third-party certification does not eliminate substantiation duty.

Verified sources:
  - eCFR 7 CFR 205.300: https://www.ecfr.gov/current/title-7/part-205/section-205.300
  - Cornell LII 16 CFR 260.6: https://www.law.cornell.edu/cfr/text/16/260.6
  - AMS NOP Labeling Guidance: https://www.ams.usda.gov/rules-regulations/organic/labeling

This service is the single source of truth for "what can the QR page say?" It is
called from history/transparency_views.py before certification_data is serialized.
"""

from dataclasses import asdict, dataclass
from typing import List, Optional

from django.utils import timezone

ORGANIC_CERT_TYPE = "usda_organic"

# FTC 16 CFR 260.6(d) requires disclosing the basis for any environmental claim.
# Keep disclaimers terse and factually accurate — these render on consumer QR pages.
DISCLAIMER_CERTIFIED = (
    "Certified by a USDA-accredited certifying agent. " "Verification via USDA Organic Integrity Database."
)
# 🔴 2026-08-30. The disclaimer above names a specific act — a match against the USDA Organic
# Integrity Database — and every production holding an active `usda_organic` certificate got it,
# whether or not that match had ever been performed.
#
# `Certification.consumer_display_status` already refuses exactly this: a row whose
# `verification_status` is "verified" but whose `verification_source` is not the OID falls back
# to the honest `self_reported` label, "rather than silently upgrading a farmer attestation into
# a third-party verification" (16 CFR 260.6). That gate landed on the certifications LIST and
# never on this validator, so one public payload asserted both at once — Solana Verde on
# consumer.trazo.io served `certifications[].status: self_reported` with
# `verification_source_url: null`, beside an `organic_claim` claiming OID verification.
#
# The fix is the disclaimer, not the label. "USDA Certified Organic" describes the OPERATION and
# stays true for any farm holding a certificate; "Verification via …" describes something TRAZO
# did, and may only be said when Trazo did it. Collapsing the unsubstantiated case into
# DISCLAIMER_SELF_REPORTED would have been the opposite error: that text ends "Not USDA Certified
# Organic", which is false about a farm that holds a certificate.
#
# The negation leads. This string renders inside a badge popover that clamps, and a qualification
# that survives truncation only in its second sentence is not a qualification: cut mid-string,
# "…Certified by a USDA-accredited certifying agent. Verification via the USDA Organic Integrity
# Datab…" is indistinguishable from the affirmative claim. Same reasoning as the materials-list
# rule that a "none unlisted" answer must never read as "listed".
DISCLAIMER_CERTIFIED_ON_FILE = (
    "Not verified by Trazo against the USDA Organic Integrity Database. Certified by a "
    "USDA-accredited certifying agent, per the certificate on file for this operation."
)
DISCLAIMER_TRANSITIONING = (
    "This farm is in transition to organic certification under 7 CFR 205.202(b). "
    "Product may not be labeled or sold as organic until certification is complete."
)
DISCLAIMER_SELF_REPORTED = (
    "Farmer-reported organic practices. Not independently verified. " "Not USDA Certified Organic."
)
DISCLAIMER_CONVENTIONAL = "This production is not certified organic. Practices documented by the farmer."

#: react-intl message id for each disclaimer above.
#:
#: The docstring on `display_label_key` below explains why a server-composed English string
#: cannot be translated and therefore cannot be the source of truth on a bilingual consumer
#: page. `disclaimer` had exactly the same defect and no key: OrganicClaimBadge renders
#: `{claim.disclaimer}` raw, so an es-419 shopper read the whole page in Spanish and then hit
#: "Farmer-reported organic practices. Not independently verified." in English — on the one
#: line of the page whose entire job is to qualify a regulated claim under 16 CFR 260.6(d).
#: A qualification the reader cannot read does not qualify anything.
#:
#: Keyed BY THE STRING rather than by `status`, because the two are not one-to-one: a single
#: status (`certified_organic`) now carries two different disclaimers depending on whether the
#: OID match actually happened, and keying on status would have silently given both the same
#: message id — reintroducing the claim this whole change removed.
DISCLAIMER_MESSAGE_IDS = {
    DISCLAIMER_CERTIFIED: "consumer.claim.disclaimer.certified",
    DISCLAIMER_CERTIFIED_ON_FILE: "consumer.claim.disclaimer.certifiedOnFile",
    DISCLAIMER_TRANSITIONING: "consumer.claim.disclaimer.transitioning",
    DISCLAIMER_SELF_REPORTED: "consumer.claim.disclaimer.selfReported",
    DISCLAIMER_CONVENTIONAL: "consumer.claim.disclaimer.conventional",
}


@dataclass
class ConsumerClaimResult:
    """
    Structured outcome of the organic-claim evaluation for a production.

    Fields:
      can_display_organic          True iff an active USDA Organic cert exists
      can_display_transitioning    True iff in 36-month transition window
      display_label                Human-readable label for the QR page
      disclaimer                   Required disclosure per 16 CFR 260.6(d)
      status                       Machine key — "certified_organic" | "transitioning"
                                     | "self_reported" | "conventional"
      status_color                 UI hint — "green" | "yellow" | "gray"
      reason                       Diagnostic explanation (admin/debug)
      transition_complete_date     ISO date or None
      days_remaining               int or None
      display_label_key            react-intl message id for `display_label`
      disclaimer_key               react-intl message id for `disclaimer`
      display_label_params         interpolation values for that message

    On `display_label` vs `display_label_key`
    ----------------------------------------
    `display_label` is composed here, server-side, in English. Trazo's consumer QR page is
    bilingual (en-US / es-419), so a server-composed string can never be translated — it
    rendered as a bare English phrase in the middle of an otherwise Spanish page
    ("Organic practices (farmer-reported)"), which is both a UX defect and, on a
    claim-bearing surface, the wrong place to be sloppy.

    The key + params are therefore the SOURCE OF TRUTH for what a consumer sees; the
    English `display_label` is retained as a fallback for older clients, the audit trail,
    and any non-UI consumer of this payload. Keep the two in sync.
    """

    can_display_organic: bool
    can_display_transitioning: bool
    display_label: str
    disclaimer: str
    status: str
    status_color: str
    reason: str
    transition_complete_date: Optional[str] = None
    days_remaining: Optional[int] = None
    display_label_key: Optional[str] = None
    display_label_params: Optional[dict] = None
    disclaimer_key: Optional[str] = None

    def to_dict(self, *, include_diagnostics: bool = False) -> dict:
        """Serialise for a response body.

        ``reason`` is a DIAGNOSTIC string — it interpolates row primary keys and raw field
        names ("Active Certification #144 (verification_status=verified, expiry=2028-07-31)",
        "Parcel 42 in transition; ..."). It was shipping verbatim on the anonymous
        ``/api/transparency/<uuid>/`` payload, which is the same class of internal-operator
        leak as ``drift_warning``: no consumer surface reads it, and it hands anyone who opens
        devtools a map of internal identifiers.

        Callers that want it — admin views, logs, tests asserting WHY a verdict was reached —
        pass ``include_diagnostics=True`` explicitly.
        """
        data = asdict(self)
        # Derived here, not passed in at each of the five construction sites. A key that has to
        # be remembered alongside its string is a key that will eventually disagree with it —
        # and a disclaimer whose translation says something other than its English is worse
        # than one that is merely untranslated.
        data["disclaimer_key"] = self.disclaimer_key or DISCLAIMER_MESSAGE_IDS.get(self.disclaimer)
        if not include_diagnostics:
            data.pop("reason", None)
        return data


class ConsumerClaimValidator:
    """
    Evaluates what organic claim a consumer QR page may display for a production.

    Usage:
        result = ConsumerClaimValidator().validate(history)
        response["organic_claim"] = result.to_dict()  # diagnostics excluded by default

    Logic priority (strongest signal wins):
        1. Active verified USDA Organic Certification -> "certified_organic"
        2. In 36-month transition window (per 7 CFR 205.202(b))  -> "transitioning"
        3. History.production_method in {organic, regenerative, biodynamic}
           but no cert and no transition record -> "self_reported"
        4. Otherwise -> "conventional"
    """

    # History.production_method values that imply organic-adjacent claims.
    # See history/models.py:78-84. Treat these as "claimed organic" without a cert.
    SELF_REPORTED_ORGANIC_METHODS = {"organic", "regenerative", "biodynamic"}

    def validate(self, history) -> ConsumerClaimResult:
        """
        Evaluate the organic-claim status for a History (production).

        Args:
            history: history.models.History instance. Must have parcel + establishment
                     loaded (caller is responsible — this service does no queries on
                     those relations beyond what Django lazy-loads).

        Returns:
            ConsumerClaimResult with display-ready fields.
        """
        establishment = history.parcel.establishment if history.parcel else None
        if establishment is None:
            return self._conventional_result(reason="No establishment linked to this production.")

        # Priority 1 — active verified USDA Organic cert.
        cert = self._get_active_usda_organic_cert(establishment)
        if cert is not None:
            # One authority for "did the OID match actually happen", shared with the
            # certifications list rendered a few inches away on the same page. Reading the
            # model's own property rather than re-deriving it from `verification_source` is the
            # point: two copies of this rule is how the page came to contradict itself.
            oid_matched = cert.consumer_display_status == "verified_via_database"
            return ConsumerClaimResult(
                can_display_organic=True,
                can_display_transitioning=False,
                display_label="USDA Certified Organic",
                display_label_key="consumer.claim.certifiedOrganic",
                disclaimer=(DISCLAIMER_CERTIFIED if oid_matched else DISCLAIMER_CERTIFIED_ON_FILE),
                status="certified_organic",
                status_color="green",
                reason=(
                    f"Active Certification #{cert.id} "
                    f"(verification_status={cert.verification_status}, "
                    f"consumer_display_status={cert.consumer_display_status}, "
                    f"expiry={cert.expiry_date})."
                ),
            )

        # Priority 2 — transitioning (per 7 CFR 205.202(b)).
        transition = self._get_transition_status(history.parcel)
        if transition is not None and self._is_in_transition_window(transition):
            months_in = self._months_since_last_prohibited(transition)
            label = (
                f"Transitioning to Organic — {months_in} of 36 months documented"
                if months_in is not None
                else "Transitioning to Organic"
            )
            return ConsumerClaimResult(
                can_display_organic=False,
                can_display_transitioning=True,
                display_label=label,
                display_label_key=(
                    "consumer.claim.transitioningWithMonths"
                    if months_in is not None
                    else "consumer.claim.transitioning"
                ),
                display_label_params=({"months": months_in} if months_in is not None else None),
                disclaimer=DISCLAIMER_TRANSITIONING,
                status="transitioning",
                status_color="yellow",
                reason=(
                    f"Parcel {transition.parcel_id} in transition; "
                    f"complete date {transition.transition_complete_date}, "
                    f"{transition.days_remaining} days remaining."
                ),
                transition_complete_date=(
                    transition.transition_complete_date.isoformat() if transition.transition_complete_date else None
                ),
                days_remaining=transition.days_remaining,
            )

        # Priority 3 — farmer claims organic-adjacent method without certification.
        method = (history.production_method or "").lower()
        if method in self.SELF_REPORTED_ORGANIC_METHODS:
            method_display = method.capitalize()
            return ConsumerClaimResult(
                can_display_organic=False,
                can_display_transitioning=False,
                display_label=f"{method_display} practices (farmer-reported)",
                # `method` is a controlled enum (SELF_REPORTED_ORGANIC_METHODS), not free
                # text, so it is safe to interpolate — but it is still an ENGLISH word, so
                # the method name gets its own key rather than being passed through raw.
                display_label_key="consumer.claim.selfReportedPractices",
                display_label_params={"methodKey": f"consumer.claim.method.{method}"},
                disclaimer=DISCLAIMER_SELF_REPORTED,
                status="self_reported",
                status_color="gray",
                reason=(
                    f"History.production_method='{method}' with no active USDA "
                    f"Organic cert and no transition record."
                ),
            )

        # Priority 4 — conventional.
        return self._conventional_result(
            reason=f"production_method='{method or 'conventional'}', no cert, no transition."
        )

    # ---- helpers ----------------------------------------------------------

    def _conventional_result(self, reason: str) -> ConsumerClaimResult:
        return ConsumerClaimResult(
            can_display_organic=False,
            can_display_transitioning=False,
            display_label="Conventional",
            display_label_key="consumer.claim.conventional",
            disclaimer=DISCLAIMER_CONVENTIONAL,
            status="conventional",
            status_color="gray",
            reason=reason,
        )

    def _get_active_usda_organic_cert(self, establishment):
        """
        Returns the establishment's active verified USDA Organic Certification, or None.

        "Active" per Certification.is_active semantics (models.py:151-158): not expired,
        not revoked, not suspended. We additionally require verification_status='verified'
        because self-reported organic claims must not surface the USDA Organic badge
        (7 CFR 205.300 / 260.6(d)).

        Note on cert_type='usda_organic' specifically: Trazo models CCOF / Oregon Tilth /
        Real Organic Project etc. as separate certification_type values (see
        constants.py CERTIFICATION_TYPE_CHOICES). In reality, CCOF and Oregon Tilth are
        USDA-accredited certifying agents that issue the USDA Organic certification —
        a CCOF-type cert in Trazo should also have a usda_organic-type cert if the
        farm is certified organic. We intentionally require the explicit usda_organic
        record here because FTC/NOP enforcement treats the USDA badge as a claim
        that must map to an actual USDA cert record, not be inferred from a
        certifier-named record. Farms need to add the usda_organic cert explicitly
        to surface the badge — this is the conservative, compliant reading.
        """
        from certifications.models import Certification

        today = timezone.now().date()
        cert = (
            Certification.objects.filter(
                establishment=establishment,
                certification_type=ORGANIC_CERT_TYPE,
                verification_status="verified",
            )
            .exclude(expiry_date__lt=today)
            .order_by("-effective_date", "-created_at")
            .first()
        )
        return cert

    def _get_transition_status(self, parcel):
        """Lazy import to avoid a hard dep from certifications -> product."""
        if parcel is None:
            return None
        try:
            from product.services.transition_status_service import compute_transition_status

            return compute_transition_status(parcel)
        except Exception:
            # Transition calc is a derived signal; never block the QR page on a failure.
            return None

    def _is_in_transition_window(self, transition) -> bool:
        """
        True iff there is a prohibited-substance record AND the 36-month clock has
        not yet elapsed. is_eligible=True means transition is complete but no cert
        issued — that is still "self-reported" territory, not "transitioning."
        """
        return (
            transition.last_prohibited_date is not None
            and transition.transition_complete_date is not None
            and not transition.is_eligible
        )

    def _months_since_last_prohibited(self, transition) -> Optional[int]:
        if transition.last_prohibited_date is None:
            return None
        today = timezone.now().date()
        months = (today.year - transition.last_prohibited_date.year) * 12
        months += today.month - transition.last_prohibited_date.month
        # Clamp to [0, 36] — we never show "-3 months" or "40 months documented."
        return max(0, min(36, months))


def filter_certifications_for_consumer(certifications: List) -> List:
    """
    Strips from the certification list any USDA Organic cert that is not verified +
    active. Intended to run alongside ConsumerClaimValidator so a self-reported
    organic cert never surfaces as a badge on the QR page.

    Other certification types are then put to `claim_authority.may_publish_certification_type`,
    which withholds any whose LABEL asserts a general environmental benefit with no issuing
    body behind it. This used to read "non-USDA Organic certs pass through unchanged" — true,
    and the reason this surface would have leaked a "Carbon Neutral Certification" badge that
    the anonymous event payload had already been taught to withhold. A chokepoint that only
    one of two public surfaces consults is not a chokepoint.

    Returns a new list.
    """
    # Local import: `history.services.claim_authority` reaches back into `certifications.models`
    # for the attestation gate, so importing it at module scope closes a cycle.
    from history.services.claim_authority import may_publish_certification_type

    today = timezone.now().date()
    out = []
    for cert in certifications:
        if cert.certification_type == ORGANIC_CERT_TYPE:
            if cert.verification_status != "verified":
                continue
            if cert.expiry_date and cert.expiry_date < today:
                continue
        elif not may_publish_certification_type(cert.certification_type).allowed:
            continue
        out.append(cert)
    return out
