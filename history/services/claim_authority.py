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
