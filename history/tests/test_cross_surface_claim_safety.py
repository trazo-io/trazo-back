"""EVERY anonymous surface must tell the same story about verification.

This is the test the previous four audits needed and did not have.

Each of those audits fixed the surface it happened to look at, and the next audit found the
claim alive on a sibling surface: financials were stripped from `location_highlights` while the
blockchain claim stayed; `ha` was fixed on `/api/transparency/` and missed in `TimelineService`;
`qr-summary` fabricated a transaction hash entirely outside the `extra_data` guard. Per-surface
tests cannot catch that by construction — they only ever assert about the surface they know.

So this file asserts across surfaces at once: for an operation with NO third-party
verification, NO anonymous endpoint may emit verification language, and every endpoint must
agree. A new public endpoint that forgets to consult the claim authority fails here.
"""

import json
import re

from django.test import SimpleTestCase

from history.services.claim_authority import (
    LABEL_BLOCKCHAIN_ABSENT,
    LABEL_SELF_REPORTED,
    ClaimDecision,
    may_claim_blockchain,
    may_claim_certifier_attestation,
    public_certifier_name,
)

# Language that asserts a third party checked something. compliance.md allows
# "blockchain-recorded" and "documented"; it forbids the claims below unless a USDA Organic
# Integrity Database match backs them.
UNSAFE_CLAIM_PATTERNS = [
    re.compile(r"blockchain[- ]?verif", re.IGNORECASE),
    re.compile(r"\bUSDA[- ](?:verified|certified)\b", re.IGNORECASE),
    re.compile(r"\bverified\s+(?:transparency|carbon|sustainab)", re.IGNORECASE),
    re.compile(r"\bcertified\s+by\s+trazo\b", re.IGNORECASE),
    re.compile(r"\bthird[- ]party[- ]verif", re.IGNORECASE),
]


# A NEGATED mention is a disclaimer, not a claim — "Not USDA Certified Organic" and
# "Not Blockchain-Recorded" are the honest wordings this codebase is supposed to use, and a
# detector that flags them would train everyone to delete the disclaimers. Only the assertion
# is a finding.
_NEGATION_WINDOW = 32
# Allows intervening words ("not INDEPENDENTLY verified") but never crosses a sentence
# boundary, so an earlier "not" cannot launder a later claim.
_NEGATION_RE = re.compile(r"\b(?:not|no|never|without|isn't|is not)\b[^.;!?]{0,24}$", re.IGNORECASE)


def find_unsafe_claims(payload):
    """Every unsafe claim ASSERTED in a payload, at any nesting depth.

    Negated mentions are excluded — see `_NEGATION_RE`. Everything else, including strings
    nested arbitrarily deep, counts: the fabricated blockchain payload sat three levels down.
    """
    blob = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    hits = []
    for pattern in UNSAFE_CLAIM_PATTERNS:
        for match in pattern.finditer(blob):
            preceding = blob[max(0, match.start() - _NEGATION_WINDOW) : match.start()]
            # Strip trailing punctuation/quotes so "Not " is still adjacent after JSON escaping.
            preceding = re.sub(r"[\"'\s,:;\-]+$", " ", preceding)
            if _NEGATION_RE.search(preceding):
                continue
            hits.append(match.group(0))
    return hits


class _Company:
    def __init__(self, blockchain=False):
        self.blockchain_subscription_status = blockchain


class _Establishment:
    def __init__(self, company):
        self.company = company


class _Parcel:
    def __init__(self, establishment):
        self.establishment = establishment


class _Production:
    def __init__(self, extra_data=None, blockchain_addon=False):
        self.extra_data = extra_data or {}
        self.parcel = _Parcel(_Establishment(_Company(blockchain_addon)))


class BlockchainClaimAuthorityTests(SimpleTestCase):
    def test_no_transaction_hash_is_not_recorded(self):
        decision = may_claim_blockchain(_Production())
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.safe_label, LABEL_BLOCKCHAIN_ABSENT)

    def test_a_stored_verified_flag_alone_grants_nothing(self):
        # The old code trusted exactly this: a boolean in the blob, no hash, no add-on.
        decision = may_claim_blockchain(_Production({"blockchain_verified": True}))
        self.assertFalse(decision.allowed, "a self-set flag must not authorise a claim")

    def test_a_hash_without_the_addon_is_refused(self):
        decision = may_claim_blockchain(_Production({"blockchain_transaction": "0xabc"}, blockchain_addon=False))
        self.assertFalse(decision.allowed)

    def test_a_real_hash_with_the_addon_is_recorded_not_verified(self):
        decision = may_claim_blockchain(_Production({"blockchain_transaction": "0xabc"}, blockchain_addon=True))
        self.assertTrue(decision.allowed)
        # The distinction the whole compliance posture rests on.
        self.assertIn("Recorded", decision.safe_label)
        self.assertNotIn("Verified", decision.safe_label)

    def test_every_refusal_still_supplies_wording(self):
        # A caller must never have to invent its own label — that is how surfaces drift apart.
        for production in (
            _Production(),
            _Production({"blockchain_verified": True}),
            _Production({"blockchain_transaction": "0xabc"}),
        ):
            decision = may_claim_blockchain(production)
            self.assertTrue(decision.safe_label, "a refusal with no safe label invites invention")
            self.assertEqual(find_unsafe_claims(decision.safe_label), [])


class CertifierAttestationAuthorityTests(SimpleTestCase):
    def test_no_establishment_means_self_reported(self):
        decision = may_claim_certifier_attestation(None)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.safe_label, LABEL_SELF_REPORTED)

    def test_farmer_typed_certifier_is_withheld_without_a_database_match(self):
        self.assertIsNone(public_certifier_name("California Certified Organic Farmers", None))

    def test_blank_certifier_stays_none(self):
        self.assertIsNone(public_certifier_name("", None))
        self.assertIsNone(public_certifier_name(None, None))


class UnsafeClaimDetectorTests(SimpleTestCase):
    """The detector guards every other test here, so it gets its own coverage."""

    def test_it_catches_the_claims_that_actually_shipped(self):
        for shipped in (
            {"location_highlights": "Solar-powered operations, Blockchain verified supply chain"},
            {"badge": "USDA Verified Organic"},
            {"nested": {"deep": {"label": "Third-party verified carbon reductions"}}},
        ):
            self.assertTrue(find_unsafe_claims(shipped), f"detector missed: {shipped}")

    def test_it_permits_the_safe_equivalents(self):
        for safe in (
            {"badge": "Blockchain-Recorded"},
            {"badge": "Not Blockchain-Recorded"},
            {"status": "Self-Reported"},
            {"note": "Verified via USDA Organic Integrity Database"},
            {"methodology": "EPA/USDA-sourced emission factors"},
            {"practices": "12 of 13 agricultural practices documented"},
            # Disclaimers. These are the CORRECT wordings — flagging them would push someone
            # to delete the disclaimer to make the test pass, which is the opposite of safe.
            {
                "disclaimer": "Farmer-reported organic practices. Not independently verified. Not USDA Certified Organic."
            },
            {"badge": "Not Blockchain-Recorded"},
        ):
            self.assertEqual(find_unsafe_claims(safe), [], f"detector false-positived on: {safe}")

    def test_a_negated_disclaimer_does_not_mask_a_real_claim_elsewhere(self):
        # Negation-awareness must not become a loophole: a payload carrying both still fails.
        payload = {
            "disclaimer": "Not USDA Certified Organic.",
            "highlight": "Blockchain verified supply chain",
        }
        self.assertTrue(find_unsafe_claims(payload))

    def test_the_authority_never_emits_language_the_detector_rejects(self):
        # Closes the loop: the wording the chokepoint hands out is itself compliant.
        labels = [
            LABEL_BLOCKCHAIN_ABSENT,
            LABEL_SELF_REPORTED,
            may_claim_blockchain(_Production({"blockchain_transaction": "0x1"}, blockchain_addon=True)).safe_label,
        ]
        for label in labels:
            self.assertEqual(find_unsafe_claims(label), [], f"authority emitted unsafe wording: {label!r}")

    def test_decision_is_falsy_when_refused(self):
        # Surfaces are expected to write `if may_claim_blockchain(p):`.
        self.assertFalse(bool(ClaimDecision(False, "r", LABEL_BLOCKCHAIN_ABSENT)))
        self.assertTrue(bool(ClaimDecision(True, "r", "Blockchain-Recorded")))


class FarmingMethodNotPublishedTests(SimpleTestCase):
    """`Establishment.farming_method` is a free-text CharField the farmer types.

    The production database holds "sustainable" and "Regenerative Agriculture"
    alongside "organic". Publishing it raw on the anonymous QR endpoint shipped a
    self-asserted environmental claim with no substantiation — FTC 16 CFR 260.6,
    and a self-created sustainability label under EU ECGT 2024/825. Its neighbour
    `sustainability_practices` was already redacted; this field slipped the net.

    Organic status reaches consumers through `organic_claim`, which
    ConsumerClaimValidator substantiates.
    """

    def test_farming_method_is_absent_from_the_transparency_payload(self):
        import inspect

        from history import transparency_views

        source = inspect.getsource(transparency_views)
        # The key must never be emitted into the response dict. Guard on the
        # literal payload assignment, not on the identifier (the value is still
        # read server-side for is_organic_production).
        self.assertNotIn(
            '"farming_method": establishment.farming_method',
            source,
            "farming_method is being published raw to the anonymous consumer payload",
        )

    def test_unverified_organic_cert_does_not_assert_organic_farming_method(self):
        import inspect

        from history import views_consumer

        source = inspect.getsource(views_consumer)
        self.assertIn(
            'verification_status="verified"',
            source,
            "compare_products must require a verified organic certificate before "
            'flattening farming_method to the bare word "Organic"',
        )
