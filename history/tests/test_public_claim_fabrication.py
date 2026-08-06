"""A public surface must never fabricate a verification it does not have.

Two P0s found on 2026-08-03 by an anonymous audit of the consumer surfaces:

1. `qr-summary`'s blockchain fallback returned ``"verified": True`` with a synthetic
   transaction hash — literally ``sha256(f"fallback_{pk}")`` — and an etherscan.io URL for a
   transaction that does not exist, on network "ethereum_testnet" (Trazo records on Polygon).
   It was served anonymously for farms with NO blockchain add-on and a NULL tx_hash.

2. `public_free_text` stripped only financial patterns, so an establishment's free-text
   "Location Highlights" shipped **"Blockchain verified supply chain"** to shoppers — on the
   same page that correctly renders "Not Blockchain-Recorded".

Both are fabricated third-party verification claims: UNSAFE per compliance.md, FTC 16 CFR
260.6, and EU ECGT 2024/825 (live 2026-09-27).
"""

import hashlib
import re

from django.test import SimpleTestCase

from history.services.privacy import public_free_text


class BlockchainFallbackHonestyTests(SimpleTestCase):
    """The fabricated hash was deterministic, so it can be pinned exactly."""

    def _forbidden_hash(self, pk):
        return "0x" + hashlib.sha256(f"fallback_{pk}".encode()).hexdigest()

    def test_the_fabricated_hash_recipe_is_gone_from_the_source(self):
        # Pin the recipe itself: any reintroduction of a synthesised hash fails here, whatever
        # the surrounding code shape.
        for path in ("carbon/views.py",):
            with open(path) as handle:
                source = handle.read()
            self.assertNotIn(
                'hashlib.sha256(f"fallback_',
                source,
                f"{path} synthesises a fake blockchain transaction hash",
            )

    def test_no_public_view_claims_verified_on_a_fallback_branch(self):
        with open("carbon/views.py") as handle:
            source = handle.read()
        # "fallback_data": True was the marker on the fabricating payloads.
        self.assertNotIn('"fallback_data": True', source)
        self.assertNotIn('"network": "ethereum_testnet"', source)

    def test_the_hash_recipe_would_have_been_detectable(self):
        # Documents how the fabrication was proven, so the check above is understood.
        self.assertEqual(
            self._forbidden_hash(543),
            "0xd3a26f766b99a001f4fd1e4b2fe09fc5845f35c9b808b909c255bbf7902559f7",
        )


class PublicFreeTextVerificationClaimTests(SimpleTestCase):
    def test_blockchain_verification_claim_is_stripped(self):
        self.assertIsNone(public_free_text("Blockchain verified supply chain"))

    def test_the_real_establishment_string_keeps_only_the_factual_practices(self):
        raw = (
            "Solar-powered operations, Beneficial insect habitat, Carbon demonstration plots, "
            "Blockchain verified supply chain, ROI Analysis: Annual Revenue: $18,200,000, "
            "Sustainability Investment: $2,730,000, Premium Revenue: $6,370,000, ROI: 133.3%"
        )
        cleaned = public_free_text(raw)
        self.assertEqual(
            cleaned,
            "Solar-powered operations, Beneficial insect habitat, Carbon demonstration plots",
        )
        # No fragment of the redacted figure may survive — ".3%" used to be rendered.
        self.assertNotIn("%", cleaned)
        self.assertNotIn("$", cleaned)

    def test_safe_blockchain_language_is_preserved(self):
        # compliance.md: "blockchain-recorded" is SAFE; only "verified" is not. Over-stripping
        # would delete accurate copy.
        self.assertEqual(public_free_text("Blockchain-recorded events"), "Blockchain-recorded events")

    def test_usda_and_third_party_verification_claims_are_stripped(self):
        for claim in (
            "USDA verified organic practices",
            "USDA certified sustainable",
            "Third-party verified carbon reductions",
            "Verified carbon negative operations",
            "Certified by Trazo",
        ):
            cleaned = public_free_text(claim) or ""
            self.assertNotRegex(
                cleaned,
                re.compile(r"verif|certified by trazo", re.IGNORECASE),
                f"{claim!r} still asserts verification after sanitising: {cleaned!r}",
            )

    def test_a_negated_disclaimer_survives_intact(self):
        # "Practices are not independently verified" is honest disclosure. An earlier version
        # of this sanitiser cut the verb and left "Practices are not independently" — the
        # redaction destroyed the disclaimer instead of the claim.
        for disclaimer in (
            "Practices are not independently verified",
            "Not USDA Certified Organic",
            "This lot is not third-party verified",
        ):
            self.assertEqual(public_free_text(disclaimer), disclaimer)

    def test_a_negation_cannot_launder_a_later_claim(self):
        # The negation window must not cross a sentence boundary, or an unrelated earlier
        # "not" would license the next sentence's claim.
        cleaned = public_free_text("We do not spray. Verified organic.")
        self.assertNotIn("Verified organic", cleaned)
        self.assertEqual(cleaned, "We do not spray.")

    def test_ordinary_farm_copy_is_untouched(self):
        for benign in (
            "Solar-powered operations, Beneficial insect habitat",
            "Family owned since 1962. Cover cropped every winter.",
            "Drip irrigated orchard on sandy loam.",
        ):
            self.assertEqual(public_free_text(benign), benign)
