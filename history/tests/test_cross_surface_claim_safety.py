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

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, History, SoilManagementEvent
from history.services.claim_authority import (
    LABEL_BLOCKCHAIN_ABSENT,
    LABEL_INPUT_GROWER_REPORTED,
    LABEL_INPUT_NATIONAL_LIST,
    LABEL_INPUT_NATIONAL_LIST_PROHIBITED,
    LABEL_INPUT_OMRI_LISTED,
    LABEL_INPUT_UNCLASSIFIED,
    LABEL_SELF_REPORTED,
    ClaimDecision,
    may_claim_blockchain,
    may_claim_certifier_attestation,
    may_claim_input_listing,
    public_certifier_name,
)
from product.models import Parcel, Product
from users.models import User

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


# ---------------------------------------------------------------------------
# The detector above is a DENYLIST OF PHRASES ALREADY SEEN. That is why it did not stop the
# sixth leak.
#
# On 2026-08-09 the anonymous payload shipped `{"status": "omri_listed", "label": "OMRI
# Listed"}` for an input with no OMRI row and no National List row — the grower's dropdown,
# published in a third party's name. Every pattern above passed it, because "OMRI" had never
# appeared in a previous incident and a denylist can only ever encode the last one.
#
# So invert the question. On an ANONYMOUS payload, the name of an attesting body is not
# vocabulary — it is a claim about who checked this operation. Scan for the BODIES and the
# attesting verbs near them, and a novel phrasing is caught the first time rather than the
# second.
#
# Kept separate from `find_unsafe_claims` on purpose: this detector is only sound against a
# fixture with NO third-party verification. "Verified via USDA Organic Integrity Database" is
# the correct wording when a database match exists, and `claim_authority` must stay free to
# emit it — so this is never applied to the authority's own licensed labels.
# ---------------------------------------------------------------------------
ATTESTING_BODIES = re.compile(
    r"\b("
    r"OMRI|Organic Materials Review Institute"
    r"|WSDA|Washington State Department of Agriculture"
    r"|CDFA|California Department of Food and Agriculture"
    r"|CCOF|California Certified Organic Farmers"
    r"|Oregon Tilth|OTCO|MOSA|PCO|QAI|Ecocert|Control Union|SCS Global"
    r"|USDA|National Organic Program"
    r"|Trazo"
    r")\b",
    re.IGNORECASE,
)

# Words that turn a body's NAME into an assertion that the body vouched for this operation.
# "allowed", "permitted" and "sourced" are deliberately absent: "the USDA National List of
# substances allowed in organic crop production" and "EPA/USDA-sourced" are regulatory
# citations, which compliance.md marks SAFE. Citing a rule is not claiming an inspector.
ATTESTING_VERBS = re.compile(
    r"\b(listed|certified|verified|accredited|registered|endorsed|reviewed|inspected|audited|approved)\b",
    re.IGNORECASE,
)

# How far apart a body and a verb may sit and still read as one assertion. Wide enough for
# "Certified by a USDA-accredited certifying agent", short enough that two unrelated sentences
# in the same JSON string do not pair up.
_ATTESTATION_WINDOW = 48


def find_unlicensed_attestations(payload):
    """Every "<attesting body> <attested>" pairing in a payload, at any nesting depth.

    Returns the matched snippets. On a fixture with no third-party verification, ANY hit is a
    defect: the operation has nobody vouching for it, so no public string may name one.
    """
    blob = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    hits = []
    for body in ATTESTING_BODIES.finditer(blob):
        window = blob[body.start() : body.end() + _ATTESTATION_WINDOW]
        verb = ATTESTING_VERBS.search(window)
        if not verb:
            # Also look BEHIND: "Certified by a USDA-accredited agent" puts the verb first.
            behind = blob[max(0, body.start() - _ATTESTATION_WINDOW) : body.start()]
            verb = ATTESTING_VERBS.search(behind)
            if not verb:
                continue
            snippet = behind[verb.start() :] + body.group(0)
        else:
            snippet = window[: verb.end()]

        preceding = blob[max(0, body.start() - _NEGATION_WINDOW) : body.start()]
        preceding = re.sub(r"[\"'\s,:;\-]+$", " ", preceding)
        if _NEGATION_RE.search(preceding):
            continue
        hits.append(snippet.replace("\\", ""))
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

    def test_sustainability_practices_is_absent_from_the_transparency_payload(self):
        """The 5th occurrence of the self-reported-trust-signal defect (2026-08-07).

        `sustainability_practices` is a farmer-authored free-text LIST that shopper
        surfaces rendered as green leaf chips. Running it through
        `public_free_text_list()` was not enough: every verification pattern keyed on a
        VERB ("verified", "certified by") or on the exact adjacency "USDA certified", so
        the noun-shaped labels farmers actually write — "USDA Organic Certified",
        "Certified Organic", "Real Organic Project Certified" — passed through untouched.
        Three demo seeders shipped exactly those strings.

        A certification attestation with no database backing, styled as a trust signal,
        is the FTC 16 CFR 260.6 / EU ECGT 2024/825 defect. Certification claims have one
        authoritative home: the Certification table, gated by claim_authority.py.
        """
        import inspect

        from history import transparency_views

        source = inspect.getsource(transparency_views)
        self.assertNotIn(
            '"sustainability_practices":',
            source,
            "sustainability_practices is being published to the anonymous consumer payload",
        )

    def test_sustainability_practices_is_absent_from_the_public_carbon_payload(self):
        """The same field on the OTHER anonymous production endpoint.

        `carbon.views.PublicProductionViewSet` is reachable unauthenticated and builds
        its own establishment block. Fixing one surface and not the other is how this
        defect class keeps recurring on a surface nobody remembered.
        """
        import inspect

        from carbon import views as carbon_views

        source = inspect.getsource(carbon_views)
        self.assertNotIn(
            '"sustainability_practices": getattr(establishment',
            source,
            "sustainability_practices is being published on the public carbon endpoint",
        )

    def test_cert_shaped_labels_are_redacted_from_public_free_text(self):
        """The redaction gap that let the claim through, pinned.

        These are the literal strings the demo seeders shipped. Each must be removed
        while honest practice text and negated disclaimers survive intact.
        """
        from history.services.privacy import public_free_text

        for claim in (
            "USDA Organic Certified",
            "USDA Organic Certified (CCOF)",
            "Certified Organic",
            "Real Organic Project Certified",
            "Rainforest Alliance Certified",
        ):
            with self.subTest(claim=claim):
                self.assertIsNone(
                    public_free_text(claim),
                    f"cert-shaped label survived redaction: {claim!r}",
                )

        # Honest practice text must NOT be collateral damage — over-redaction would push
        # farmers back toward writing claims to get anything to render.
        for practice in (
            "Drip irrigation (95% efficiency)",
            "Cover cropping between rows",
            "Integrated Pest Management",
        ):
            with self.subTest(practice=practice):
                self.assertEqual(public_free_text(practice), practice)

        # A negated mention is a DISCLAIMER, not a claim.
        disclaimer = "Practices are not independently verified"
        self.assertEqual(public_free_text(disclaimer), disclaimer)

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


class InputListingAuthorityTests(SimpleTestCase):
    """ "OMRI Listed" is a third party's name, not an adjective.

    Found on the wire 2026-08-09: ``/api/transparency/<uuid>/`` shipped
    ``input_status: {"status": "omri_listed", "label": "OMRI Listed"}`` for an input with no
    OMRI row and no National List row — the only evidence was the grower's dropdown — and the
    consumer chip rendered it green with the tooltip "approved for organic farming by the
    listed certification body".

    Same root cause as the four audits above: a surface deciding locally what it may claim.
    """

    class _Substance:
        def __init__(self, status="allowed"):
            self.status = status

    class _Event:
        def __init__(self, organic_approved="", omri_product_id=None, national_list_substance=None):
            self.organic_approved = organic_approved
            self.omri_product_id = omri_product_id
            self.national_list_substance = national_list_substance
            self.extra_data = {}

    def test_grower_dropdown_alone_never_earns_the_omri_label(self):
        decision = may_claim_input_listing(self._Event(organic_approved="omri_listed"))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.safe_label, LABEL_INPUT_GROWER_REPORTED)
        self.assertNotIn("OMRI", decision.safe_label)

    def test_a_catalog_match_does_earn_it(self):
        decision = may_claim_input_listing(self._Event(organic_approved="", omri_product_id=42))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.safe_label, LABEL_INPUT_OMRI_LISTED)

    def test_a_national_list_citation_is_not_an_omri_listing(self):
        # § 205.601 lists SUBSTANCES; OMRI lists branded PRODUCTS. Citing one while naming the
        # other is the same category error in a different direction.
        decision = may_claim_input_listing(
            self._Event(organic_approved="omri_listed", national_list_substance=self._Substance())
        )
        self.assertFalse(decision.allowed)
        self.assertNotIn("OMRI", decision.safe_label)
        self.assertIn("205.601", decision.safe_label)

    def test_a_prohibited_substance_is_never_labelled_allowed(self):
        decision = may_claim_input_listing(
            self._Event(
                organic_approved="omri_listed",
                national_list_substance=self._Substance(status="prohibited"),
            )
        )
        self.assertFalse(decision.allowed)
        self.assertNotIn("Allowed", decision.safe_label)
        self.assertIn("205.602", decision.safe_label)

    def test_no_classification_is_documented_not_conventional(self):
        # The inverse error: absence of a classification is not evidence the input was
        # conventional.
        decision = may_claim_input_listing(self._Event())
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.safe_label, LABEL_INPUT_UNCLASSIFIED)

    def test_the_chip_resolver_publishes_the_authority_wording(self):
        from history.services.claim_resolver import resolve_input_status

        self.assertEqual(
            resolve_input_status(self._Event(organic_approved="omri_listed"))["label"],
            LABEL_INPUT_GROWER_REPORTED,
        )
        self.assertEqual(
            resolve_input_status(self._Event(omri_product_id=7))["status"],
            "omri_listed",
        )
        prohibited = resolve_input_status(
            self._Event(
                organic_approved="omri_listed",
                national_list_substance=self._Substance(status="prohibited"),
            )
        )
        self.assertEqual(prohibited["status"], "conventional_documented")

    def test_no_input_label_trips_the_unsafe_detector(self):
        for label in (
            LABEL_INPUT_OMRI_LISTED,
            LABEL_INPUT_NATIONAL_LIST,
            LABEL_INPUT_NATIONAL_LIST_PROHIBITED,
            LABEL_INPUT_GROWER_REPORTED,
            LABEL_INPUT_UNCLASSIFIED,
        ):
            with self.subTest(label=label):
                self.assertEqual(find_unsafe_claims({"label": label}), [])


class AttestationDetectorTests(SimpleTestCase):
    """The entity detector must catch every leak the phrase denylist has ever been taught.

    Each string below actually shipped. The point of the test is that the detector catches
    them WITHOUT having been told about them individually — a denylist needs an incident
    first, and that is how six of these happened.
    """

    # Claims that NAME a body. These are the entity detector's job.
    BODY_LEAKS = [
        # 2026-08-09 — the sixth: a dropdown published in OMRI's name.
        '{"status": "omri_listed", "label": "OMRI Listed"}',
        "OMRI / Organic-approved",
        "{approved} of {total} crop inputs are OMRI/National List-approved for organic use",
        # Earlier incidents, each of which needed its own pattern added at the time.
        "USDA Certified Organic",
        "Certified by Trazo",
        # Phrasings nobody has shipped yet — the ones a denylist would miss next.
        "WSDA Registered Material",
        "Reviewed by CCOF",
        "Certified by a USDA-accredited certifying agent",
        "Ecocert approved input",
    ]

    # Claims that name no body at all — "blockchain" is a technology, not an attester. The
    # entity detector cannot see these and is not meant to; they are the phrase denylist's
    # job. The two detectors are complementary, NOT one a superset of the other, and writing
    # this test as if they were is what caught the misconception.
    BODYLESS_LEAKS = [
        "Blockchain verified supply chain",
        "Verified transparency score",
    ]

    def test_the_entity_detector_catches_every_leak_that_names_a_body(self):
        for leak in self.BODY_LEAKS:
            with self.subTest(leak=leak):
                self.assertTrue(
                    find_unlicensed_attestations(leak),
                    f"attesting body asserted with no licence and not detected: {leak!r}",
                )

    def test_every_shipped_leak_is_caught_by_at_least_one_detector(self):
        # The assertion that actually matters: nothing that has ever shipped gets through the
        # pair. Which detector catches it is an implementation detail.
        for leak in self.BODY_LEAKS + self.BODYLESS_LEAKS:
            with self.subTest(leak=leak):
                self.assertTrue(
                    find_unsafe_claims(leak) or find_unlicensed_attestations(leak),
                    f"claim passed BOTH detectors: {leak!r}",
                )

    def test_it_permits_regulatory_citation(self):
        # Citing a RULE is not claiming an inspector. These are the wordings compliance.md
        # marks SAFE, and a detector that flagged them would train everyone to delete the
        # honest phrasing — the same failure mode the negation window exists to prevent.
        for safe in [
            "Allowed input · National List § 205.601",
            "The USDA National List of substances allowed in organic crop production",
            "Emission factors are EPA/USDA-sourced",
            "Organic-approved · grower-reported",
            "The grower recorded all 4 chemical inputs as approved for organic use",
            "Documented",
        ]:
            with self.subTest(safe=safe):
                self.assertEqual(find_unlicensed_attestations(safe), [], safe)

    def test_a_negated_mention_is_a_disclaimer(self):
        for disclaimer in [
            "Not USDA Certified Organic",
            "This farm is not certified by CCOF",
            "No OMRI listing was found for this product",
        ]:
            with self.subTest(disclaimer=disclaimer):
                self.assertEqual(find_unlicensed_attestations(disclaimer), [], disclaimer)

    def test_it_reaches_arbitrarily_deep_nesting(self):
        # The fabricated blockchain payload sat three levels down; the OMRI label sat inside a
        # timeline array. A top-level scan would have missed both.
        buried = {"standard_view": {"timeline": [{"a": {"input_status": {"label": "OMRI Listed"}}}]}}
        self.assertTrue(find_unlicensed_attestations(buried))

    def test_the_authority_labels_pass_the_entity_detector_too(self):
        # Every wording claim_authority may put on an UNVERIFIED surface must survive the
        # stricter detector — otherwise the module that exists to keep surfaces honest would
        # itself be the thing tripping the sweep.
        for label in (
            LABEL_BLOCKCHAIN_ABSENT,
            LABEL_INPUT_NATIONAL_LIST,
            LABEL_INPUT_NATIONAL_LIST_PROHIBITED,
            LABEL_INPUT_GROWER_REPORTED,
            LABEL_INPUT_UNCLASSIFIED,
            LABEL_SELF_REPORTED,
        ):
            with self.subTest(label=label):
                self.assertEqual(find_unlicensed_attestations(label), [], label)


class LiveAnonymousPayloadSweepTests(TestCase):
    """Scan the REAL response bytes of every anonymous endpoint. No hand-written strings.

    This is the gap the first five audits left. Everything above asserts about strings a test
    author thought to type, or about a field a test author knew existed — so a claim on a
    field nobody listed was invisible by construction. That is precisely how the OMRI label
    survived a claim-authority module, a cross-surface sweep, and four audits: it lived on
    `input_status`, a key no test enumerated.

    Here the fixture is an operation with NOTHING vouching for it — no certification row, no
    blockchain add-on — whose grower nonetheless picked the strongest organic value in every
    dropdown, which is exactly the shape that produced the leak. Then the payload is fetched
    and scanned whole. A future endpoint that invents a new claim key fails without anyone
    adding it to a list.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="sweep@test.com", password="x")
        self.company = Company.objects.create(name="Claim Sweep Farms")
        self.establishment = Establishment.objects.create(name="Claim Sweep Estate", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="CS1", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="Claim Sweep Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        # The grower claims the most, and nothing backs it: no OMRI row, no National List row,
        # no certification. Every affirmative string in the payload is therefore self-reported.
        ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            commercial_name="Neptune's Harvest Fish & Seaweed 2-3-1",
            organic_approved="omri_listed",
            type="FE",
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            type="OM",
            amendment_organic_approved="omri_listed",
        )

    def _anonymous_payloads(self):
        """Every anonymous endpoint that renders this production, with its raw bytes."""
        public_id = self.history.public_id
        for name, url in [
            ("transparency", f"/api/transparency/{public_id}/"),
            ("verify-blockchain", f"/api/transparency/{public_id}/verify-blockchain/"),
            ("public_history", f"/api/histories/{public_id}/public_history/"),
        ]:
            resp = self.client.get(url)
            # A 404/405 means the endpoint does not serve this shape; only 200s carry claims.
            if resp.status_code == 200:
                yield name, resp.content.decode("utf-8")

    def test_no_anonymous_endpoint_names_an_attester_for_an_unverified_operation(self):
        checked = 0
        for name, blob in self._anonymous_payloads():
            checked += 1
            with self.subTest(endpoint=name):
                self.assertEqual(
                    find_unlicensed_attestations(blob),
                    [],
                    f"{name} named an attesting body for an operation nobody has attested",
                )
        self.assertGreater(checked, 0, "sweep matched no anonymous endpoint — the test is vacuous")

    def test_no_anonymous_endpoint_emits_known_unsafe_language(self):
        for name, blob in self._anonymous_payloads():
            with self.subTest(endpoint=name):
                self.assertEqual(find_unsafe_claims(blob), [], f"{name} emitted unsafe claim language")
