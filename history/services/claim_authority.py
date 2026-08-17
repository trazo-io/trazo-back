"""Single server-side authority for what a PUBLIC surface may claim.

WHY THIS EXISTS
---------------
Four independent audits between 2026-07-31 and 2026-08-03 each found the same defect class —
a public surface asserting a verification the data does not support — and each instance had
already been "fixed" on a *different* surface:

* ``location_highlights`` had its financials stripped (2026-08-02) and kept shipping
  "Blockchain verified supply chain".
* Hardcoded ``ha`` was fixed on ``/api/transparency/`` (2026-07-31) and missed in
  ``TimelineService``.
* ``qr-summary`` returned ``"verified": True`` with a transaction hash that was literally
  ``sha256(f"fallback_{pk}")`` for farms with no blockchain add-on.
* ``PublicHistorySerializer`` publishes ``verified_certifier_name`` — a FARMER-TYPED form
  field whose ``verified_`` prefix is a naming lie.

The common cause is not any one bug: it is that every public surface decides *locally* whether
it may say "verified". Patching the audited surface leaves the next one, so the finding recurs.
This module is the chokepoint. A surface must ASK rather than decide.

REGULATORY BASIS
----------------
``compliance.md``: "blockchain-recorded" is SAFE, "blockchain-verified" is NOT; "verified" may
be claimed only for a USDA Organic Integrity Database match. FTC 16 CFR 260.6 (general
environmental benefit claims); EU ECGT Directive 2024/825, effective 2026-09-27, which bans
self-created sustainability labels lacking third-party verification.

USAGE
-----
    from history.services.claim_authority import may_claim_blockchain, public_certifier_name

    decision = may_claim_blockchain(production)
    payload["blockchain_verified"] = decision.allowed
    payload["blockchain_label"] = decision.safe_label

Organic claims already have an authority — ``ConsumerClaimValidator`` plus
``resolve_lot_organic_eligibility`` — and this module deliberately delegates to it rather than
building a second opinion. What it adds is the two claim families that had no gate at all.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# The only verification_source that constitutes third-party verification. Anything else is the
# operation's own attestation, however it is labelled in the database.
DATABASE_VERIFICATION_SOURCE = "usda_organic_integrity_db"

# Safe labels. Never returns a bare "Verified".
LABEL_BLOCKCHAIN_RECORDED = "Blockchain-Recorded"
LABEL_BLOCKCHAIN_ABSENT = "Not Blockchain-Recorded"
LABEL_SELF_REPORTED = "Self-Reported"
LABEL_DATABASE_VERIFIED = "Verified via USDA Organic Integrity Database"

# Input-listing labels. "OMRI Listed" names a real third-party program run by a real
# organisation; it is a certification-mark claim, not an adjective. It may be said only when
# the input is matched to an OMRIProduct row. The other two labels state what is actually
# known: a National List citation is a REGULATORY fact about a substance (7 CFR 205.601), and
# a grower's dropdown pick is the grower's own record.
LABEL_INPUT_OMRI_LISTED = "OMRI Listed"
LABEL_INPUT_NATIONAL_LIST = "Allowed input · National List § 205.601"
LABEL_INPUT_NATIONAL_LIST_PROHIBITED = "Prohibited substance · National List § 205.602"
LABEL_INPUT_GROWER_REPORTED = "Organic-approved · grower-reported"
LABEL_INPUT_UNCLASSIFIED = "Documented"


@dataclass(frozen=True)
class ClaimDecision:
    """Whether a public surface may assert a claim, and the wording it may use instead.

    ``reason`` is for logs and tests, never for consumers. ``safe_label`` is the only string a
    surface should render; it is never None when ``allowed`` is False, so a caller has no
    excuse to invent its own wording.
    """

    allowed: bool
    reason: str
    safe_label: str

    def __bool__(self):
        return self.allowed


def may_claim_blockchain(production):
    """May a public surface represent this production as blockchain-recorded?

    Requires BOTH a real on-chain transaction AND an active add-on. A missing or failed
    lookup is NOT a licence to synthesise one — the fabricated-hash bug lived in exactly that
    branch. Absence of evidence resolves to "not recorded", never to "verified".
    """
    tx_hash = _transaction_hash(production)
    if not tx_hash:
        return ClaimDecision(False, "no on-chain transaction hash", LABEL_BLOCKCHAIN_ABSENT)

    if not _has_blockchain_addon(production):
        # A transaction hash with no subscription is stale, seeded, or test data — we would not
        # have submitted for an operation that is not paying for the add-on. Refuse.
        #
        # This fails CLOSED on purpose. The harms are asymmetric: over-claiming is the FTC /
        # ECGT exposure this module exists to prevent, while under-claiming only costs a badge
        # and is immediately visible to the grower, who will say so. But log it — a paying
        # customer silently losing a badge must be discoverable, not invisible.
        logger.warning(
            "Blockchain claim refused for production %s: transaction hash present but "
            "company has no active blockchain add-on.",
            getattr(production, "id", "?"),
        )
        return ClaimDecision(False, "no active blockchain add-on", LABEL_BLOCKCHAIN_ABSENT)

    # Note the wording: RECORDED, not VERIFIED. The chain proves the record was not altered
    # after submission; it says nothing about whether the farming practice occurred.
    return ClaimDecision(True, "on-chain transaction present", LABEL_BLOCKCHAIN_RECORDED)


def may_claim_input_listing(chemical_event):
    """What may a public surface say about this input's organic standing?

    Found 2026-08-09 on the wire: ``/api/transparency/<uuid>/`` shipped
    ``input_status: {"status": "omri_listed", "label": "OMRI Listed"}`` for an input with
    ``omri_product_id = None`` AND ``national_list_substance_id = None`` — no catalog evidence
    of any kind. The consumer card rendered it as a green chip whose tooltip read *"approved
    for organic farming by the listed certification body."* The only input was the grower's
    ``organic_approved`` dropdown.

    That is the module's founding defect class in its sharpest form: the surface decided
    locally that a self-report could be spoken in a third party's name. OMRI is a real
    organisation running a real listing program, so this is not vague puffery — it is an
    unearned certification-mark claim (FTC 16 CFR 260.6; EU ECGT 2024/825).

    Evidence tiers, strongest first. Each says only what is actually known:

    1. ``omri_product`` FK  → the input matched the OMRI catalog. "OMRI Listed" is earned.
    2. ``national_list_substance`` (allowed) → a 7 CFR 205.601 citation. This is a REGULATORY
       fact about the substance, not a listing by any certifier, so it must not be spoken as
       "OMRI Listed" — § 205.601 lists substances, OMRI lists branded products, and the two
       are different assertions.
    3. grower's dropdown only → the grower's own record, labelled as such.
    4. nothing → "Documented". Absence of classification is not evidence of a conventional
       input (the inverse error), so this never says "conventional".

    A § 205.602 PROHIBITED match gets its own label rather than sharing the allowed one — the
    citation alone is not the verdict, and "Allowed input · National List" on a prohibited
    substance would be the inverse of this module's purpose.
    """
    if chemical_event is None:
        return ClaimDecision(False, "no event", LABEL_INPUT_UNCLASSIFIED)

    if getattr(chemical_event, "omri_product_id", None):
        return ClaimDecision(True, "OMRI catalog match on file", LABEL_INPUT_OMRI_LISTED)

    nl = getattr(chemical_event, "national_list_substance", None)
    if nl is not None:
        if getattr(nl, "status", None) == "prohibited":
            return ClaimDecision(False, "National List prohibited match", LABEL_INPUT_NATIONAL_LIST_PROHIBITED)
        return ClaimDecision(False, "National List citation, not an OMRI listing", LABEL_INPUT_NATIONAL_LIST)

    # Import here: claim_resolver imports this module, and the reverse import at module scope
    # would be circular.
    from history.services.claim_resolver import ORGANIC_APPROVED_VALUES, event_organic_classification

    if event_organic_classification(chemical_event) in ORGANIC_APPROVED_VALUES:
        return ClaimDecision(False, "grower dropdown only, no catalog match", LABEL_INPUT_GROWER_REPORTED)

    return ClaimDecision(False, "no organic classification", LABEL_INPUT_UNCLASSIFIED)


def may_claim_certifier_attestation(establishment, certification_type=None):
    """May a public surface present a named certifier as having attested this operation?

    Only a Certification row that is (a) ``verified`` and (b) sourced from the USDA Organic
    Integrity Database qualifies. A farmer-entered ``verification_status`` is the operation's
    own claim about itself — the field name does not make it third-party evidence.
    """
    if establishment is None:
        return ClaimDecision(False, "no establishment", LABEL_SELF_REPORTED)

    try:
        from django.utils import timezone

        from certifications.models import Certification

        qs = Certification.objects.filter(
            establishment=establishment,
            verification_status="verified",
            verification_source=DATABASE_VERIFICATION_SOURCE,
        ).exclude(expiry_date__lt=timezone.now().date())
        normalised = _normalise_certification_type(certification_type)
        if normalised:
            qs = qs.filter(certification_type=normalised)
        if qs.exists():
            return ClaimDecision(True, "USDA OID match on file", LABEL_DATABASE_VERIFIED)
    except Exception:
        # A lookup failure must fail CLOSED. The whole point of this module is that an error
        # path never becomes a licence to claim.
        return ClaimDecision(False, "certification lookup failed", LABEL_SELF_REPORTED)

    return ClaimDecision(False, "no database-verified certification", LABEL_SELF_REPORTED)


def public_certifier_name(certifier_name, establishment, certification_type=None):
    """The certifier name a public surface may show, or None.

    ``verified_certifier_name`` on a business event is free text the grower typed. Publishing
    it beside a certificate number reads as third-party attestation, which is exactly the
    representation ECGT 2024/825 and FTC 16 CFR 260.6 govern. Withhold unless the operation
    has a database-verified certification to back it.
    """
    if not certifier_name or not str(certifier_name).strip():
        return None
    if may_claim_certifier_attestation(establishment, certification_type).allowed:
        return str(certifier_name).strip()
    return None


# BusinessEvent and Certification use DIFFERENT vocabularies for the same certification:
# the event stores "organic_usda", the certification stores "usda_organic". Filtering the
# certification table with the event's raw value therefore matched NOTHING, which made this
# gate permanently closed — it would have withheld the certifier name even from an operation
# with a genuine USDA Organic Integrity Database match, i.e. exactly the case it must allow.
_CERT_TYPE_ALIASES = {
    "organic_usda": "usda_organic",
    "usda_organic": "usda_organic",
    "global_gap": "global_gap",
    "ccof": "ccof",
}


def _normalise_certification_type(value):
    """Map an event's certification_type onto the Certification vocabulary.

    Returns None for an unknown value, which drops the type constraint rather than
    guaranteeing a miss. That is safe: `verification_source == usda_organic_integrity_db` is
    only ever set by the USDA Organic import, so the remaining filters still require real
    third-party evidence.
    """
    if not value:
        return None
    return _CERT_TYPE_ALIASES.get(str(value).strip().lower())


def _transaction_hash(production):
    """The on-chain TRANSACTION hash, or None.

    Both keys are in live use (`blockchain_transaction` on 23 published productions,
    `blockchain_tx_hash` on 3), so reading only the first silently downgraded records that were
    genuinely submitted.

    Deliberately NOT accepted: `blockchain_hash`, `blockchain_data_hash`,
    `blockchain_record_hash`. Those are CONTENT digests — a hash of the record's own data. They
    prove nothing about whether anything reached a chain, and treating a digest as evidence of
    on-chain recording is the same category error as the fabricated `sha256("fallback_<pk>")`
    hash this module was written to stop.
    """
    extra = getattr(production, "extra_data", None)
    if not isinstance(extra, dict):
        return None
    for key in ("blockchain_transaction", "blockchain_tx_hash"):
        value = extra.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return None


def _has_blockchain_addon(production):
    """Blockchain is a $15/mo add-on; without it there is nothing legitimate to point at."""
    try:
        company = production.parcel.establishment.company
    except AttributeError:
        return False
    return bool(getattr(company, "blockchain_subscription_status", False))


# ---------------------------------------------------------------------------
# Container labelling — 7 CFR 205.307
# ---------------------------------------------------------------------------
#
# Added 2026-08-10 (USDA alignment audit, P4). Every finding that audit raised sat on a
# surface this module did NOT cover, and the reason is that the module only ever answered
# one question: "may this PAGE say verified?" (§ 205.311 / FTC / ECGT). The printed lot tag
# is a different legal instrument under a different subpart — a physical nonretail container
# label — and nothing gated it.
#
# What the tag was doing:
#   * `lot = history.lot_id or "—"`, drawn as `LOT {lot}`. Measured on the live database,
#     72 of 115 published productions (63%) have no lot_id, so the majority of tags printed
#     the literal string "LOT —". § 205.307(a)(2) requires "the production lot number,
#     shipping identification, or other unique information that links the container to audit
#     trail documentation". An em-dash is none of the three.
#   * On any failure of the organic gate it dropped the organic line and logged a warning the
#     producer never sees. But § 205.307(a)(1) is a POSITIVE requirement — a certified
#     operation's container must identify the product as organic — so silence produces a
#     non-compliant label just as surely as over-claiming does.
#
# Note the asymmetry with the rest of this module. Elsewhere, failing closed is free: a
# missing badge costs a pixel. Here BOTH directions are non-compliant, so the decision has to
# carry a blocker the caller is obliged to show, rather than a label it may quietly skip.

LABEL_CONTAINER_ORGANIC = "Certified organic by {certifier}"
LABEL_CONTAINER_ORGANIC_NO_AGENT = "Certified organic"


@dataclass(frozen=True)
class ContainerLabelDecision:
    """Whether a compliant § 205.307 nonretail container label can be produced.

    ``may_print`` False means the caller MUST refuse to generate the tag — not print a
    placeholder. ``blocker`` is producer-facing (unlike ``ClaimDecision.reason``, which is
    for logs): the grower is the only person who can fix the underlying data, so they have to
    be told. ``organic_line`` is the § 205.307(a)(1) identification, already gated by the
    lot-level organic resolver; ``warning`` is set when that identification is withheld from
    an operation that holds a verified certificate — the case that used to vanish into a log.
    """

    may_print: bool
    lot_id: str
    organic_line: str
    blocker: str
    warning: str
    reason: str

    def __bool__(self):
        return self.may_print


def may_label_container(history, cert=None):
    """May a nonretail container label be printed for this production, and carrying what?

    § 205.307(a)(2) is treated as a hard precondition: with no lot identifier there is no
    compliant tag to print, so we refuse rather than emit a placeholder. § 205.307(a)(1) is
    resolved through the SAME lot-level organic gate the consumer page and the audit PDF use
    — one vocabulary across surfaces, which is the whole point of this module.

    ``cert`` may be passed by callers that already resolved it; omitted, it is looked up.
    """
    lot_id = (getattr(history, "lot_id", None) or "").strip()
    if not lot_id:
        return ContainerLabelDecision(
            may_print=False,
            lot_id="",
            organic_line="",
            blocker=(
                "This production has no lot ID. 7 CFR 205.307(a)(2) requires every nonretail "
                "container to carry a lot number or other unique identifier linking it to your "
                "records, so a compliant tag cannot be produced yet. Lot IDs are assigned when a "
                "production is finished."
            ),
            warning="",
            reason="no lot_id",
        )

    establishment = getattr(getattr(history, "parcel", None), "establishment", None)

    if cert is None and establishment is not None:
        try:
            from certifications.services.consumer_claim_validator import ConsumerClaimValidator

            cert = ConsumerClaimValidator()._get_active_usda_organic_cert(establishment)
        except Exception:
            logger.warning(
                "Container label: certificate lookup failed for history %s", getattr(history, "id", "?"), exc_info=True
            )
            cert = None

    if cert is None:
        # Not certified organic. A tag with no organic identification is CORRECT here —
        # § 205.307(a)(1) only binds certified organic product.
        return ContainerLabelDecision(
            may_print=True,
            lot_id=lot_id,
            organic_line="",
            blocker="",
            warning="",
            reason="no active USDA organic certificate; organic identification not applicable",
        )

    try:
        from history.services.claim_resolver import resolve_lot_organic_eligibility

        eligibility = resolve_lot_organic_eligibility(history, cert)
    except Exception:
        logger.warning(
            "Container label: lot organic gate failed for history %s", getattr(history, "id", "?"), exc_info=True
        )
        eligibility = None

    if eligibility is not None and eligibility.eligible is True:
        certifier = (getattr(cert, "certifier_name", "") or "").split(" (")[0].strip()
        line = LABEL_CONTAINER_ORGANIC.format(certifier=certifier) if certifier else LABEL_CONTAINER_ORGANIC_NO_AGENT
        return ContainerLabelDecision(
            may_print=True,
            lot_id=lot_id,
            organic_line=line,
            blocker="",
            warning="",
            reason="lot eligible under active certificate",
        )

    # Certificate on file, but this lot did not pass the gate. Printing the organic line
    # would over-claim; omitting it silently leaves a certified operation shipping containers
    # that § 205.307(a)(1) says must be identified. Print the tag, and say so out loud.
    detail = getattr(eligibility, "detail", "") or "the lot-level organic check did not pass"
    return ContainerLabelDecision(
        may_print=True,
        lot_id=lot_id,
        organic_line="",
        blocker="",
        warning=(
            "Organic identification has been left off these tags because "
            f"{detail[0].lower() + detail[1:] if detail else detail} "
            "7 CFR 205.307(a)(1) requires certified organic product to be identified as organic "
            "on its shipping containers. Resolve this before the containers ship, or use tags "
            "that do not represent the product as organic."
        ),
        reason="certificate present but lot not eligible",
    )
