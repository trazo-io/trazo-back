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
#: WSDA runs a registration programme for materials used in organic production and CCOF treats
#: it as co-equal with OMRI. Its own label, not OMRI's: they are different organisations
#: making different determinations, and a surface that blurred them would be naming a body
#: that never reviewed the product.
LABEL_INPUT_WSDA_LISTED = "WSDA Listed"
LABEL_INPUT_NATIONAL_LIST = "Allowed input · National List § 205.601"
# A § 205.601 entry the rule allows only under a condition of use: zinc and boron with a documented
# deficiency ((j)(7)), magnesium sulfate with a documented soil deficiency ((j)(6)), the fixed coppers
# used so copper does not build up in the soil ((i)(2)), boric acid for structural pest control only
# ((e)(3)). "Allowed input" alone told a shopper more than the rule does (overall review 2026-11,
# OV-MT-C01). Whether this application met the condition is the certifier's call, so the label names
# that there is one and stops. Typed by paragraph (`NationalListSubstance.allowed_with_condition`).
LABEL_INPUT_NATIONAL_LIST_WITH_CONDITION = "Allowed with a condition · National List § 205.601"
# 🔴 2026-08-20 — hardcoded "§ 205.602", which is wrong for most rows that reach it.
# § 205.602 lists NONSYNTHETIC substances prohibited in crop production (calcium chloride,
# rotenone, strychnine). A synthetic like glyphosate is barred by § 205.105(a) — it is simply
# not on § 205.601 — and is not "on the National List" at all. Printing § 205.602 beside
# glyphosate cites the wrong clause to a certifier and to a shopper, on the one label whose
# job is to be exact. The clause varies per row, so the shared label states the fact that is
# true of every row it covers; the packet already prints the actual `cfr_section` beside the
# substance name, which is where the citation belongs.
LABEL_INPUT_NATIONAL_LIST_PROHIBITED = "Prohibited substance · not allowed in organic production"
# A § 205.602 entry the CFR permits for ONE stated use (calcium chloride as a foliar spray for
# a calcium-uptake disorder; potassium chloride from a mined source). Neither "prohibited" nor
# "allowed" is true of these, and this module must not decide which by reading the farmer's
# free-text purpose against the annotation — that inference belongs to the certifier.
LABEL_INPUT_NATIONAL_LIST_CONDITIONAL = "Restricted use · National List § 205.602"
# The grower's own dropdown pick, said as a record, never as a verdict. Until the recordkeeping
# review (F-09, 2026-10-07) this read "Organic-approved · grower-reported": "Approved" led the
# chip for an answer nobody but the grower had given.
LABEL_INPUT_GROWER_REPORTED = "Recorded by the farm as allowed for organic use"
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


# ---------------------------------------------------------------------------
# Record evidence
# ---------------------------------------------------------------------------
#
# What an event record CONTAINS, said as a fact. Deliberately NOT a tier.
#
# Until 2026-09-02 this was a five-rung ladder — self_reported (50% trust) →
# photo_documented (65) → photo_verified (80) → data_verified (85) → certified (100) —
# computed independently in THREE places (``history.serializers.EventSerializer``,
# ``PublicHistorySerializer._get_verification_level_for_event`` and
# ``carbon.services.timeline_service.TimelineService._calculate_verification_level``), each
# with its own answer. The consumer card coloured the rungs teal → blue → green-with-a-tick →
# purple-with-a-star and the frontend helper carried the trust percentages as data.
#
# That is a self-created sustainability label with a numeric grade attached, which is the
# thing EU ECGT 2024/825 (effective 2026-09-27) bans and FTC 16 CFR 260.6 treats as an
# unqualified general claim. It is the same defect class as the transparency score, which was
# withheld from consumers in the 2026-06 claim-safety pivot; the ladder survived because it
# was expressed as a badge instead of a number.
#
# Two of the rungs were worse than merely self-graded:
#
#   * ``certified`` / ``data_verified`` were awarded for ``extra_data["blockchain_verified"]``.
#     ``BLOCKCHAIN_ENABLED`` is False and the add-on is withdrawn, so any row still carrying
#     that flag printed a blockchain claim — the exact thing ``may_claim_blockchain`` exists to
#     refuse. A per-event tier bypassed the chokepoint by not asking it.
#   * ``photo_verified`` claimed GPS metadata "verifies" the event. It verifies where a CAMERA
#     was, which is not whether the practice happened, and both rungs rendered the SAME words
#     ("Photo Documented") in different colours — the grade moved into the palette.
#
# So: two states, both descriptions of the record rather than judgements of it. Evidence a
# surface wants to show beyond this (photo count, an OMRI catalog match, a certificate number)
# is ADDITIVE and factual, and each has its own authority above.

EVIDENCE_SELF_REPORTED = "self_reported"
EVIDENCE_PHOTO_DOCUMENTED = "photo_documented"

#: Every value the retired ladder could emit. Kept so guards can assert no surface revives
#: one, and so a stale row read from ``extra_data`` is recognisable rather than passed through.
RETIRED_EVIDENCE_LEVELS = frozenset({"photo_verified", "data_verified", "certified"})


def record_evidence_level(*, has_photos, photos_flagged=False):
    """What this event's record contains — ``self_reported`` or ``photo_documented``.

    Pure and keyword-only: the caller has already loaded the album (three call sites do it
    three different ways, and none of them can afford this function issuing its own queries),
    so it passes booleans rather than an event. That also makes the rule testable without a
    database.

    ``photos_flagged`` is the Vision-API verdict that every photo on the event is AI-generated,
    stock, or non-agricultural. Photos that fail it add nothing, so the record is described as
    what it is without them. Absence of a verdict is NOT a flag — an unscanned photo counts.
    """
    if has_photos and not photos_flagged:
        return EVIDENCE_PHOTO_DOCUMENTED
    return EVIDENCE_SELF_REPORTED


def _omri_listing_is_current(chemical_event) -> bool:
    """True only while OMRI still lists the product the FK points at.

    OMRI listings lapse: six of the 9,230 products on the 2026-09-05 Crop Products List were
    gone from the 2026-09-26 one, each returning HTTP 404 at its own certificate URL. Tier 1
    below reads "the input matched the OMRI catalog, so 'OMRI Listed' is earned" - and it
    stops being earned the day OMRI withdraws it. Until 2026-09-28 this tested only that the
    FK was SET, so a withdrawn product kept announcing "OMRI Listed" on the anonymous buyer
    page for as long as the row survived: an unearned certification-mark claim (FTC 16 CFR
    260.6; EU ECGT 2024/825), which is this module's founding defect class.

    A lapse is NOT evidence against the input. It falls through to the next tier exactly as a
    nonsynthetic catalogue row does, so WSDA, a 205.601 citation or the grower's own record
    still speak for it. Saying "no longer listed" on a shopper page would be the inverse
    error: OMRI stopped vouching, which is not a finding about the material.

    NEVER relax this to `omri_product_id` for want of a query. The related row is what carries
    `delisted_on`, and an event whose product cannot be resolved has not shown the listing is
    current. Callers on the public path select_related("omri_product", "wsda_material") so this costs nothing.
    """
    if not getattr(chemical_event, "omri_product_id", None):
        return False
    product = getattr(chemical_event, "omri_product", None)
    return product is not None and getattr(product, "delisted_on", None) is None


def _wsda_listing_is_current(chemical_event) -> bool:
    """True only while WSDA still lists the product the FK points at (overall review 2026-11, OV-MT-C04).

    The same rule as `_omri_listing_is_current`, for the catalog that had no drop marker until
    2026-11-18: a product WSDA removes from a later edition kept announcing "WSDA Listed" on the buyer
    page for as long as the row survived. A lapse is not evidence against the input; the event falls
    through to the next tier. Public callers select_related("wsda_material").
    """
    if not getattr(chemical_event, "wsda_material_id", None):
        return False
    material = getattr(chemical_event, "wsda_material", None)
    return material is not None and getattr(material, "delisted_on", None) is None


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
    2. ``wsda_material`` FK → the input matched the WSDA Materials List. Co-equal evidence
       (CCOF accepts either), and spoken in WSDA's own name — never as "OMRI Listed", because
       OMRI did not review it. Added 2026-09-02: the basis was already selectable in the form
       and already in the dossier's third-party set, so a WSDA-listed input could be CLAIMED
       and never BACKED — it printed "grower-selected, no listing on file" forever, and the
       buyer page dropped it to grower-reported. For 23 of 42 seeded WSDA brands there is no
       OMRI row at all, which also created a quiet pressure to attach a neighbouring OMRI
       listing to earn the better chip.
    3. ``national_list_substance`` (allowed) → a 7 CFR 205.601 citation. This is a REGULATORY
       fact about the substance, not a listing by any certifier, so it must not be spoken as
       "OMRI Listed" — § 205.601 lists substances, OMRI lists branded products, and the two
       are different assertions.
    4. grower's dropdown only → the grower's own record, labelled as such.
    5. nothing → "Documented". Absence of classification is not evidence of a conventional
       input (the inverse error), so this never says "conventional".

    A § 205.602 PROHIBITED match gets its own label rather than sharing the allowed one — the
    citation alone is not the verdict, and "Allowed input · National List" on a prohibited
    substance would be the inverse of this module's purpose.
    """
    if chemical_event is None:
        return ClaimDecision(False, "no event", LABEL_INPUT_UNCLASSIFIED)

    if _omri_listing_is_current(chemical_event):
        return ClaimDecision(True, "OMRI catalog match on file", LABEL_INPUT_OMRI_LISTED)

    if _wsda_listing_is_current(chemical_event):
        return ClaimDecision(True, "WSDA Materials List match on file", LABEL_INPUT_WSDA_LISTED)

    # Phase 5 slice 1: only a confirmed classification (exact, alias, operator) is evidence here; a
    # legacy row or a partial-name suggestion is not, and the event falls through to what the grower
    # recorded.
    from history.services.national_list_basis import confirmed_national_list_substance

    nl = confirmed_national_list_substance(chemical_event)
    # 🔴 2026-09-10 — a NONSYNTHETIC catalogue row (spinosad, Bt, d-limonene) is Trazo's own
    # classification, not a listing: the regulation lists no nonsynthetic it allows. The three
    # were filed at § 205.601 and so earned "Allowed input · National List § 205.601" on the
    # buyer page — a regulatory citation that does not exist. Such a row is no evidence here at
    # all; the event falls through to what the grower recorded, as if nothing had matched.
    if nl is not None and getattr(nl, "is_national_list_entry", True):
        if getattr(nl, "status", None) == "prohibited":
            # 🔴 2026-08-20 — some § 205.602 entries are conditional, not absolute, and calling
            # a compliant use "prohibited" on the shopper-facing page is the inverse error this
            # module exists to prevent: it publishes a nonconformance the farm did not commit.
            # (Live case: a Honeycrisp block's seven-spray calcium programme for bitter pit,
            # which is precisely the exception § 205.602(c) writes out.) The honest claim names
            # the listing and its condition and stops there — the operation's recorded purpose
            # is free text, so whether it MEETS the condition is a certifier's call.
            if getattr(nl, "is_conditionally_permitted", False):
                return ClaimDecision(
                    False,
                    "National List conditional listing — allowance depends on the recorded use",
                    LABEL_INPUT_NATIONAL_LIST_CONDITIONAL,
                )
            return ClaimDecision(False, "National List prohibited match", LABEL_INPUT_NATIONAL_LIST_PROHIBITED)
        if getattr(nl, "allowed_with_condition", False):
            return ClaimDecision(
                False,
                "National List § 205.601 listing that carries a condition of use",
                LABEL_INPUT_NATIONAL_LIST_WITH_CONDITION,
            )
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


# ---------------------------------------------------------------------------
# Which certification types a public surface may NAME at all.
# ---------------------------------------------------------------------------
#
# Every other gate in this module asks "is this verified?". This one asks a question that had
# no gate: "may this be published at all?" — because for one family of claims the honest
# answer to the first question does not cure the second.
#
# `may_claim_certifier_attestation` correctly labels a non-USDA certification "Self-Reported".
# That is the right treatment for "Rainforest Alliance" — a named programme, a checkable fact,
# qualified as the operation's own statement. It is NOT sufficient for "Carbon Neutral
# Certification": FTC 16 CFR 260.4 governs general environmental benefit claims themselves,
# not merely their attribution, and ECGT 2024/825 (2026-09-27) bans self-created sustainability
# labels outright. "Carbon Neutral — Self-Reported" is still a net-zero claim on a product page.
#
# THE LINE DRAWN, so future entries are decided by a rule rather than case by case:
#   publishable — the label names an issuing body ("Rainforest Alliance", "Fair Trade
#                 Certified", "CCOF") or a specific, checkable attribute ("Non-GMO",
#                 "Kosher", "GlobalG.A.P."). Stating that a certificate exists is a fact.
#   withheld    — the label asserts a general environmental benefit or a net position with no
#                 issuing body attached. That is a claim about outcomes, and Trazo has no
#                 evidence for it.
#
# RECORDING IS UNTOUCHED. The operation may still log any of these — its § 205.103 records are
# its own, and an inspector may want them. Only the consumer surface withholds.
_WITHHELD_CERTIFICATION_TYPES = {
    "carbon_neutral": (
        "'Carbon neutral' is a general environmental benefit claim (16 CFR 260.4) and the exact "
        "phrase compliance.md marks UNSAFE. It also contradicts Trazo's own stated methodology "
        "— direct operational emissions, not a full LCA — so publishing it beside Trazo's own "
        "figures reads as Trazo substantiating a neutrality claim it cannot compute."
    ),
    "sustainable_agriculture": (
        "'Sustainable Agriculture Standard' names no issuing body, so there is nothing for a "
        "shopper to check it against. An unattributed sustainability label is precisely the "
        "self-created label ECGT 2024/825 bans; a named programme is a fact and stays."
    ),
}

# Exhaustive over BOTH vocabularies — BusinessEvent.CERTIFICATION_TYPE_CHOICES and
# certifications.constants.CERTIFICATION_TYPE_CHOICES, which diverged and are not
# interconvertible (see _CERT_TYPE_ALIASES). A caller may hold either, and a gate that
# recognised only one would pass the other straight through as "unknown".
_PUBLISHABLE_CERTIFICATION_TYPES = frozenset(
    {
        # BusinessEvent vocabulary
        "organic_usda",
        "regenerative",
        # ROP on the BusinessEvent side (added to CERTIFICATION_TYPE_CHOICES 2026-08-21 without
        # being classified here, so the guard flagged it and every ROP record was silently
        # withheld). Same issuing body as "real_organic_project" below — the Real Organic
        # Project is a third-party add-on standard with a public directory, i.e. checkable.
        "real_organic",
        "cng",
        "non_gmo",
        "rainforest_alliance",
        # Narrow and resource-specific rather than a general benefit claim — the closest call
        # in this list. Revisit if the displayed label ever generalises beyond water.
        "water_stewardship",
        "global_gap",
        "fair_trade",
        "food_safety",
        "kosher",
        # certifications app vocabulary
        "usda_organic",
        "real_organic_project",
        "roc",
        "korean_organic",
        "non_gmo_project",
        "sqf",
        # 2026-08-27. Both name an issuing body with a public directory, which is the line
        # this list draws: a shopper can go and check them. (`ccof` left this set the same
        # day — not because CCOF is unpublishable, but because it stopped being a
        # certification TYPE at all. It is a certifying AGENT and now travels in
        # `certifier_name`, where `public_certifier_name()` governs it.)
        "primus_gfs",
        "salmon_safe",
        "other",
    }
)


# ---------------------------------------------------------------------------
# Which production subtypes a consumer surface may show at all.
# ---------------------------------------------------------------------------
#
# Some activities are records for an INSPECTOR and are actively misleading to a shopper. The
# four below were verified against real events on 2026-08-19; the structured fields are already
# withheld from the anonymous payload, but the farmer-authored name/description/observation are
# not, and for these subtypes that free text IS the disclosure:
#
#   BU  "Buffer rows cut, sold conventional"  — correct under § 205.202(c), which REQUIRES
#       buffer crop to be sold non-organic. To a shopper it reads as an admission that part of
#       what they are holding was not organic, and it is about a different crop entirely.
#   SS  "none could supply certified organic"  — the § 205.204(a)(1) commercial-unavailability
#       allowance, which reads as "not fully organic" without the regulation beside it.
#   EM  "Huller line purge before organic run" — reveals a split operation and conventional
#       product on the same line, out of the context that makes it a compliance STRENGTH.
#   TP  "Load to Sac Valley Hulling"          — names the operation's processor. Who handles a
#       farm's crop is commercial information, and publishing it is the supplier-chain leak
#       class this module already guards for inputs.
#
# Withholding is not hiding a problem: each of these is evidence of CORRECT practice, and each
# is read as its opposite by an audience that does not have the CFR open. They stay in the
# certifier packet, which is where they persuade.
_CONSUMER_WITHHELD_PRODUCTION_SUBTYPES = {
    "BU": "buffer-zone disposition reads as a non-organic admission out of § 205.202(c) context",
    "SS": "commercial-unavailability search reads as 'not fully organic' without § 205.204(a)(1)",
    "EM": "cleanout/purge narrative reveals split-operation handling out of context",
    "TP": "transport names the operation's handler — commercial supply-chain information",
}


def may_publish_production_subtype(subtype):
    """May a consumer surface show an event of this production subtype?

    Allow-by-default, unlike `may_publish_certification_type`, and deliberately so: the
    subtypes here are the ordinary field activities a QR page exists to show — planting,
    irrigation, harvest — and defaulting those to withheld would empty the page every time a
    new one is added. What is enumerated is the small set whose free text misleads, and
    `test_consumer_production_subtypes` pins that set against the model vocabulary so a new
    subtype forces a decision to be recorded rather than defaulted silently.
    """
    key = str(subtype).strip().upper() if subtype else ""
    if key in _CONSUMER_WITHHELD_PRODUCTION_SUBTYPES:
        return ClaimDecision(False, _CONSUMER_WITHHELD_PRODUCTION_SUBTYPES[key], LABEL_SELF_REPORTED)
    return ClaimDecision(True, "ordinary field activity", LABEL_SELF_REPORTED)


def may_publish_certification_type(certification_type):
    """May a public surface name this certification type at all?

    Fails CLOSED on anything unrecognised. That is the whole design: a denylist would encode
    only the incident that prompted it, so a certification type added later would publish
    itself by default and the next audit would find the same class of defect one row down.
    Here an unclassified value is withheld until someone classifies it, and
    `test_claim_authority_certification_types` fails the moment either model vocabulary grows
    a value this module has not seen — so the decision cannot be skipped, only made.
    """
    if not certification_type:
        return ClaimDecision(False, "no certification type", LABEL_SELF_REPORTED)

    key = str(certification_type).strip().lower()
    if key in _WITHHELD_CERTIFICATION_TYPES:
        return ClaimDecision(False, _WITHHELD_CERTIFICATION_TYPES[key], LABEL_SELF_REPORTED)
    if key in _PUBLISHABLE_CERTIFICATION_TYPES:
        return ClaimDecision(True, "named programme or specific attribute", LABEL_SELF_REPORTED)

    logger.warning(
        "may_publish_certification_type: unclassified certification type %r withheld from public "
        "surfaces. Classify it in claim_authority.py.",
        key,
    )
    return ClaimDecision(False, "unclassified certification type", LABEL_SELF_REPORTED)


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
    "real_organic": "real_organic_project",
    "real_organic_project": "real_organic_project",
    "usda_organic": "usda_organic",
    "global_gap": "global_gap",
    # 2026-08-27: "ccof" was an identity mapping onto a Certification type that no longer
    # exists. A legacy BusinessEvent still carrying it means USDA Organic, which is where
    # migration 0031 moved every Certification row it named.
    "ccof": "usda_organic",
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
