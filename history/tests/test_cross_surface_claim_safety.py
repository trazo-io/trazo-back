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
from datetime import date
from types import SimpleNamespace

#: Distinguishes "the test said nothing about the product" from "the test said None".
#: Module level because a nested class body cannot see its enclosing class body's namespace.
_AUTO = object()

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

    def test_compare_products_consults_the_claim_authority_for_farming_method(self):
        """`compare_products` must decide "Organic" through the shared authority.

        🔴 2026-09-24 — this WAS a source grep for the literal `verification_status="verified"`.
        That literal is the RAW column an admin edit, an import or a fixture can set, so the
        guard pinned a filter that is not evidence of anything, and it could not tell a
        STRICTER implementation from the filter being deleted: replacing it with
        `consumer_certification_status(...) == "verified_via_database"` — which additionally
        refuses a fabricated operation — failed this test.

        A behavioural assertion lives in `CompareProductsFarmingMethodTests` below. What stays
        here is the structural half a `SimpleTestCase` can check without a database: the module
        must reach the verdict through the authority and must not re-derive it from the column.
        """
        import inspect

        from history import views_consumer

        source = inspect.getsource(views_consumer)
        # ⚠️ Strip comment lines before the negative assertion. The first cut of this test
        # tripped on the very comment that documents the fix, because that comment quotes the
        # old expression in order to explain what was wrong with it. A source guard that cannot
        # tell code from prose about code is a guard that punishes writing the prose.
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        self.assertIn(
            "consumer_certification_status",
            code,
            "compare_products must ask the shared authority whether a certificate may be "
            'presented as verified before flattening farming_method to the bare word "Organic"',
        )
        self.assertNotIn(
            'verification_status == "verified"',
            code,
            "farming_method must not be derived from the raw verification_status column — "
            "that value is set by admin edits, imports and fixtures and is not evidence that "
            "a USDA Organic Integrity Database match ever happened",
        )


class CompareProductsFarmingMethodTests(TestCase):
    """The behavioural half: what `compare_products` actually returns, per certificate state.

    Written 2026-09-24 to replace a source grep. Three states, because they are three different
    facts and only one of them earns the bare word "Organic":
      registry-verified  a real farm matched against Trazo's copy of the USDA Organic Integrity
                         Database. The only state that earns it.
      producer-reported  a real certificate on file that Trazo has NOT matched.
      specimen           `Establishment.is_demo` — the operation itself is invented.
    """

    def _build(self, label, *, is_demo, verification_source, certified=True):
        from certifications.models import Certification
        from product.models import Parcel, Product
        from users.models import User

        user = User.objects.create_user(email=f"cmp-{label}@test.com", password="x")
        company = Company.objects.create(name=f"Cmp Co {label}")
        establishment = Establishment.objects.create(
            name=f"Cmp Farm {label}", company=company, state="OR", is_demo=is_demo
        )
        parcel = Parcel.objects.create(name=f"Blk {label}", establishment=establishment, area=2.0)
        product = Product.objects.create(name=f"Berries {label}")
        history = History.objects.create(
            name=f"Season {label}",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=10.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        # ⛔ Written the way a PRE-correction fixture wrote it: the raw column says "verified"
        # in every state. That is the point — the runtime has to refuse the claim anyway.
        if certified:
            Certification.objects.create(
                establishment=establishment,
                certification_type="usda_organic",
                certifier_name="CCOF Certification Services, LLC",
                expiry_date=timezone.now().date().replace(year=timezone.now().year + 2),
                verification_status="verified",
                verification_source=verification_source,
            )
        return user, history

    def _farming_method(self, user, history):
        """POST the comparison and return the row for `history`.

        ⚠️ `ProductComparisonSerializer` requires at least TWO products, so every call carries an
        uncertified control alongside the subject. The control doubles as a floor: if it ever
        comes back "Organic", the verdict is not being computed per establishment at all.
        """
        from rest_framework.test import APIClient

        _, control = self._build("control", is_demo=False, verification_source="", certified=False)

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(
            "/api/consumer/dashboard/compare_products/",
            {"products": [str(history.public_id), str(control.public_id)]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content[:400])
        rows = {r["public_id"]: r for r in resp.json().get("products", [])}
        self.assertIn(str(control.public_id), rows, resp.json())
        self.assertEqual(
            rows[str(control.public_id)]["farming_method"],
            "Conventional",
            "the uncertified control must never read Organic",
        )
        self.assertIn(str(history.public_id), rows, resp.json())
        return rows[str(history.public_id)]

    def test_a_registry_matched_certificate_earns_the_bare_word_organic(self):
        user, history = self._build("verified", is_demo=False, verification_source="usda_organic_integrity_db")
        row = self._farming_method(user, history)
        self.assertEqual(row["farming_method"], "Organic")
        self.assertIn("USDA Organic (verified)", row["certifications"])

    def test_a_producer_reported_certificate_does_not(self):
        user, history = self._build("selfrep", is_demo=False, verification_source="")
        row = self._farming_method(user, history)
        self.assertEqual(row["farming_method"], "Conventional")
        self.assertNotIn("(verified)", " | ".join(row["certifications"]))

    def test_a_fabricated_operation_does_not(self):
        user, history = self._build("specimen", is_demo=True, verification_source="usda_organic_integrity_db")
        row = self._farming_method(user, history)
        self.assertEqual(row["farming_method"], "Conventional")
        self.assertNotIn("(verified)", " | ".join(row["certifications"]))


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

    @staticmethod
    def _omri_product(delisted_on=None):
        """The catalog row the FK points at. `delisted_on` says whether it is still listed."""
        return SimpleNamespace(delisted_on=delisted_on)

    class _Event:
        def __init__(
            self,
            organic_approved="",
            omri_product_id=None,
            national_list_substance=None,
            omri_product=_AUTO,
        ):
            self.organic_approved = organic_approved
            self.omri_product_id = omri_product_id
            self.national_list_substance = national_list_substance
            # A test that sets a classification means a confirmed one (Phase 5 slice 1).
            self.national_list_basis = "operator" if national_list_substance is not None else ""
            # A real ChemicalEvent always resolves `omri_product` when the id is set, so the
            # double does too unless a test is deliberately posing an unresolvable one.
            if omri_product is _AUTO:
                omri_product = SimpleNamespace(delisted_on=None) if omri_product_id else None
            self.omri_product = omri_product
            self.extra_data = {}

    def test_grower_dropdown_alone_never_earns_the_omri_label(self):
        decision = may_claim_input_listing(self._Event(organic_approved="omri_listed"))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.safe_label, LABEL_INPUT_GROWER_REPORTED)
        self.assertNotIn("OMRI", decision.safe_label)

    def test_a_current_catalog_match_does_earn_it(self):
        decision = may_claim_input_listing(self._Event(organic_approved="", omri_product_id=42))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.safe_label, LABEL_INPUT_OMRI_LISTED)

    def test_a_withdrawn_listing_no_longer_earns_it(self):
        """OMRI listings lapse. Six of the 9,230 products on the 2026-09-05 Crop Products
        List were gone from the 2026-09-26 one. This tested only that the FK was SET, so a
        withdrawn product kept announcing "OMRI Listed" on the anonymous buyer page: an
        unearned certification-mark claim, which is this module's founding defect class."""
        decision = may_claim_input_listing(
            self._Event(
                organic_approved="",
                omri_product_id=42,
                omri_product=self._omri_product(delisted_on=date(2026, 9, 26)),
            )
        )
        self.assertFalse(decision.allowed)
        self.assertNotIn("OMRI", decision.safe_label)

    def test_a_withdrawn_listing_falls_through_rather_than_accusing(self):
        """A lapse is not evidence AGAINST the input. Saying "no longer listed" on a shopper
        page would be the inverse error: OMRI stopped vouching, which is not a finding about
        the material. It falls to what else is actually known."""
        decision = may_claim_input_listing(
            self._Event(
                organic_approved="",
                omri_product_id=42,
                omri_product=self._omri_product(delisted_on=date(2026, 9, 26)),
            )
        )
        self.assertEqual(decision.safe_label, LABEL_INPUT_UNCLASSIFIED)
        for word in ("withdraw", "delisted", "no longer", "removed", "conventional"):
            self.assertNotIn(word, decision.safe_label.lower())

    def test_an_unresolvable_product_does_not_earn_the_claim(self):
        """NEVER claim from the id alone. The related row is what carries `delisted_on`; an
        event whose product cannot be resolved has not shown the listing is current."""
        decision = may_claim_input_listing(self._Event(organic_approved="", omri_product_id=42, omri_product=None))
        self.assertFalse(decision.allowed)
        self.assertNotIn("OMRI", decision.safe_label)

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
        self.assertIn("Prohibited", decision.safe_label)
        # The clause is NOT asserted here any more, and deliberately so. This label covers
        # both § 205.602 (nonsynthetics prohibited in crop production) and § 205.105
        # (synthetics not on § 205.601 — glyphosate and friends, which are not on the
        # National List at all), so a hardcoded "§ 205.602" cited the wrong clause for most
        # rows that reach it. The row's actual `cfr_section` is printed beside the substance
        # name in the packet, which is where a citation can be accurate.
        self.assertNotIn("205.602", decision.safe_label)

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


class NoClaimFromAGuessTests(TestCase):
    """OSP alignment audit, Phase 5 slice 1 (2026-10-02): no classification, citation or claim from a
    partial-name match, and none from a classification whose basis was never recorded."""

    @classmethod
    def setUpTestData(cls):
        from certifications.models import NationalListSubstance

        cls.copper = NationalListSubstance.objects.create(
            substance_name="Copper hydroxide",
            substance_name_normalized="copper hydroxide",
            cfr_section="205.601",
            subsection="i",
            category="disease_control",
            status="allowed",
        )
        cls.rotenone = NationalListSubstance.objects.create(
            substance_name="Rotenone", substance_name_normalized="rotenone", cfr_section="205.602", status="prohibited"
        )

    def setUp(self):
        from django.utils import timezone

        from company.models import Company, Establishment
        from history.models import History
        from product.models import Parcel, Product
        from users.models import User

        self.user = User.objects.create_user(email="guess@test.com", password="x")
        company = Company.objects.create(name="Guess Farm")
        est = Establishment.objects.create(name="Guess Field", company=company)
        parcel = Parcel.objects.create(name="P", establishment=est, area=1.0)
        self.history = History.objects.create(
            name="H",
            start_date=timezone.now(),
            product=Product.objects.create(name="Pear"),
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _event(self, **kwargs):
        from django.utils import timezone

        from history.models import ChemicalEvent

        return ChemicalEvent.objects.create(
            history=self.history, created_by=self.user, description="spray", date=timezone.now(), **kwargs
        )

    def test_a_partial_name_is_a_suggestion_and_never_cited(self):
        from history.services.claim_authority import may_claim_input_listing
        from history.services.national_list_basis import confirmed_national_list_substance

        event = self._event(commercial_name="Copper Hydroxide 25% WP")
        self.assertIsNone(event.national_list_substance)
        self.assertEqual(event.national_list_suggestion, self.copper)
        self.assertIsNone(confirmed_national_list_substance(event))
        self.assertNotIn("205.601", may_claim_input_listing(event).safe_label)

    def test_an_exact_name_is_a_classification_with_its_basis(self):
        event = self._event(commercial_name="Copper hydroxide")
        self.assertEqual((event.national_list_substance, event.national_list_basis), (self.copper, "exact"))

    def test_a_classification_with_no_recorded_basis_is_legacy_and_claims_nothing(self):
        from history.services.claim_authority import may_claim_input_listing
        from history.services.claim_resolver import ORGANIC_APPROVED_VALUES  # noqa: F401  (module import check)

        event = self._event(commercial_name="Mystery", national_list_substance=self.rotenone)
        event.refresh_from_db()
        self.assertEqual(event.national_list_substance, self.rotenone, "the stored value is kept")
        self.assertEqual(event.national_list_basis, "legacy_unverified")
        decision = may_claim_input_listing(event)
        self.assertNotIn("Prohibited", decision.safe_label, "a legacy classification accused the input")
        # Saving again never reclassifies or relabels it.
        event.commercial_name = "Copper hydroxide"
        event.save()
        event.refresh_from_db()
        self.assertEqual(
            (event.national_list_substance, event.national_list_basis), (self.rotenone, "legacy_unverified")
        )

    def test_the_dossier_prints_a_legacy_classification_as_not_verified(self):
        from history.services.national_list_basis import LEGACY_NOTE, unconfirmed_national_list

        event = self._event(commercial_name="Mystery", national_list_substance=self.copper)
        event.refresh_from_db()
        substance, note = unconfirmed_national_list(event)
        self.assertEqual((substance, note), (self.copper, LEGACY_NOTE))

    def test_the_operator_basis_is_recorded_only_when_the_operator_sets_or_changes_it(self):
        from history.serializers import UpdateChemicalEventSerializer

        event = self._event(commercial_name="Mystery", national_list_substance=self.copper)
        event.refresh_from_db()
        self.assertEqual(event.national_list_basis, "legacy_unverified")

        same = UpdateChemicalEventSerializer(event, data={"national_list_substance": self.copper.pk}, partial=True)
        self.assertTrue(same.is_valid(), same.errors)
        same.save()
        event.refresh_from_db()
        self.assertEqual(event.national_list_basis, "legacy_unverified", "an unchanged round-trip relabelled it")

        change = UpdateChemicalEventSerializer(event, data={"national_list_substance": self.rotenone.pk}, partial=True)
        self.assertTrue(change.is_valid(), change.errors)
        change.save()
        event.refresh_from_db()
        self.assertEqual((event.national_list_substance, event.national_list_basis), (self.rotenone, "operator"))

        clear = UpdateChemicalEventSerializer(event, data={"national_list_substance": None}, partial=True)
        self.assertTrue(clear.is_valid(), clear.errors)
        clear.save()
        event.refresh_from_db()
        self.assertIsNone(event.national_list_substance)
        self.assertNotEqual(event.national_list_basis, "operator")

    def test_the_migration_marks_every_stored_classification_legacy_and_keeps_its_value(self):
        import importlib

        from django.apps import apps as global_apps

        from history.models import ChemicalEvent

        with_fk = self._event(commercial_name="Copper hydroxide")
        without = self._event(commercial_name="Mystery Brew")
        ChemicalEvent.objects.filter(pk=with_fk.pk).update(national_list_basis="")
        migration = importlib.import_module("history.migrations.0240_national_list_basis")
        migration.mark_legacy(global_apps, None)
        with_fk.refresh_from_db()
        without.refresh_from_db()
        self.assertEqual(
            (with_fk.national_list_substance, with_fk.national_list_basis), (self.copper, "legacy_unverified")
        )
        self.assertEqual((without.national_list_substance, without.national_list_basis), (None, ""))

    def test_the_provenance_report_counts_and_writes_nothing(self):
        import io

        from django.core.management import call_command

        from history.models import ChemicalEvent

        self._event(commercial_name="Copper hydroxide")
        self._event(commercial_name="Mystery", national_list_substance=self.rotenone)
        before = list(
            ChemicalEvent.objects.order_by("pk").values_list("pk", "national_list_substance_id", "national_list_basis")
        )
        out = io.StringIO()
        call_command("report_national_list_provenance", stdout=out)
        self.assertIn("Stored National List classifications: 2", out.getvalue())
        self.assertIn("would reach 1", out.getvalue())
        after = list(
            ChemicalEvent.objects.order_by("pk").values_list("pk", "national_list_substance_id", "national_list_basis")
        )
        self.assertEqual(before, after)

    def test_a_partial_name_never_clears_a_drift_finding_and_is_only_noted(self):
        from django.utils import timezone

        from certifications.models import OMRIProduct, OrganicSystemPlan

        omri = OMRIProduct.objects.create(omri_id="ent-0001", product_name="Entrust SC Naturalyte Insect Control")
        osp = OrganicSystemPlan.objects.create(
            establishment=self.history.parcel.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )
        osp.approved_omri_products.add(omri)
        with self.captureOnCommitCallbacks(execute=True):
            partial = self._event(commercial_name="Entrust SC")
        partial.refresh_from_db()
        self.assertIsNotNone(partial.drift_warning, "a partial-name hit cleared the finding")
        self.assertEqual(partial.drift_warning["reason_code"], "unresolved")
        self.assertIn("Possible match, not confirmed", partial.drift_warning["reason"])
        with self.captureOnCommitCallbacks(execute=True):
            exact = self._event(commercial_name="Entrust SC Naturalyte Insect Control")
        exact.refresh_from_db()
        self.assertIsNone(exact.drift_warning, "an exact approved name must still clear")

    def test_recompute_drift_restores_a_finding_a_partial_name_had_cleared(self):
        import io

        from django.core.management import call_command
        from django.utils import timezone

        from certifications.models import OMRIProduct, OrganicSystemPlan
        from history.models import ChemicalEvent

        omri = OMRIProduct.objects.create(omri_id="ent-0002", product_name="Entrust SC Naturalyte Insect Control")
        osp = OrganicSystemPlan.objects.create(
            establishment=self.history.parcel.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )
        osp.approved_omri_products.add(omri)
        event = self._event(commercial_name="Entrust SC")
        ChemicalEvent.objects.filter(pk=event.pk).update(drift_warning=None)  # as the old rule stored it
        out = io.StringIO()
        call_command("recompute_drift", establishment=self.history.parcel.establishment.pk, stdout=out)
        event.refresh_from_db()
        self.assertIsNotNone(event.drift_warning, "the stored finding was not re-evaluated")
        self.assertEqual(event.drift_warning["reason_code"], "unresolved")
        self.assertIn("Findings: 0 before, 1 after", out.getvalue())

    def test_no_reader_turns_the_raw_field_into_a_statement(self):
        """Every reader goes through `history.services.national_list_basis`. A new file reading
        `national_list_substance` directly is either a reviewed writer or a regression."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        allowed = {
            "history/models.py",
            "history/signals.py",
            "history/serializers.py",
            "history/services/national_list_basis.py",
            "history/services/claim_authority.py",  # docstring only; reads through the helper
            "history/management/commands/seed_showcase_walnut_farm.py",  # seeds (legacy basis)
            "history/management/commands/seed_calapooia_bend.py",
            "history/management/commands/report_national_list_provenance.py",
            "certifications/models.py",  # PlanMaterialEntry's own field
            "certifications/serializers.py",  # PlanMaterialEntry
            "certifications/views.py",  # verify-input suggestion payload; plan entry rows
            "certifications/services/osp_fork.py",  # PlanMaterialEntry clone
            "certifications/services/plan_materials.py",  # PlanMaterialEntry
            "certifications/services/catalog_integrity.py",  # PlanMaterialEntry
            "certifications/services/drift_detector.py",  # reads through the helper, then the id
        }
        pattern = re.compile(r"(?<![a-z_])national_list_substance(?![a-z_s])")
        offenders = []
        for folder in ("history", "certifications", "product", "common", "carbon"):
            for path in (root / folder).rglob("*.py"):
                rel = path.relative_to(root).as_posix()
                if "/tests/" in rel or "/migrations/" in rel or ".claude" in rel:
                    continue
                if pattern.search(path.read_text()) and rel not in allowed:
                    offenders.append(rel)
        self.assertEqual(offenders, [], "read the classification through national_list_basis")
