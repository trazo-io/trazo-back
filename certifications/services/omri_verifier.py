"""
OMRI / National List verifier — Sprint 3.

Resolves against Trazo's LOCAL catalog copies, never a live OMRI call. Verifies
chemical inputs against:

  1. A farmer-provided OMRI ID (OMRIProduct record) — farmer pasted from omri.org.
  2. The hardcoded National List (NationalListSubstance — 7 CFR 205.601/602).

Returns a `VerificationResult` compatible with the existing BaseCertificationVerifier
pattern (see usda_organic_verifier.py).

Statuses `verify` answers with, in the order it tries them:
    listing_match    -> an OMRI product the input identifies (the code off the certificate, or a name
                        exactly one product holds), or an allowed National List row (exact name, curated
                        alias, or the row's full name inside the input). A § 205.601 row the rule allows
                        only under a condition of use carries the rule's words in `notes`.
    delisted         -> the OMRI product identified, and Trazo's copy of OMRI's list no longer carries it.
    restricted_use   -> a § 205.602 row the rule prohibits except for one stated use (calcium chloride,
                        potassium chloride, sodium nitrate). Never "prohibited": the use may meet it.
    revoked          -> a prohibited row with no exception: § 205.602, or a § 205.105 synthetic.
    possible_match   -> nothing confirmed; `notes` names the National List rows and OMRI products the
                        name partially matches and chooses none, because a guess is a listing the grower
                        may not have applied.
    not_found        -> no match in either source (treat as self-reported only).
"""

import re
from typing import List, Optional
from urllib.parse import quote_plus

from certifications.models import NationalListSubstance, OMRIProduct, WSDAMaterial
from certifications.services.base_verifier import BaseCertificationVerifier, VerificationResult
from certifications.services.national_list_citations import use_condition

_ECFR_PART_205 = "https://www.ecfr.gov/current/title-7/subtitle-B/chapter-I/subchapter-M/part-205"

#: How many candidates a verdict names before saying how many more there are.
_SEVERAL_NAMED = 3


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _named(items, render) -> str:
    """The first few items rendered and joined, then a count of the rest."""
    named = "; ".join(render(item) for item in items[:_SEVERAL_NAMED])
    rest = len(items) - _SEVERAL_NAMED
    return f"{named}; and {rest} more" if rest > 0 else named


def _is_identity(product, normalized: str) -> bool:
    """True when what was typed IS this product: its OMRI code, or its exact name (with or without the
    "-O" OMRI appends to listed variants). Anything else is a candidate, however well it ranked."""
    name = (product.product_name or "").lower()
    return (product.omri_id or "").lower() == normalized or name in (normalized, normalized + "-o")


def _omri_candidates_note(operation_name: str, products) -> str:
    """The sentence a verdict carries for OMRI products the name matched but did not identify. It names a
    few, with their codes (two products can share a name), counts the rest, and chooses none.

    "In OMRI's catalogue", never "OMRI-listed": the candidates are the lookup's, which keep products OMRI
    has dropped (`delisted_on`, OV-MT-C04) so the grower can see the drop. A dropped product is marked
    where it is named and counted where it is not (review of PR 505)."""
    if not products:
        return ""

    def render(product):
        dropped = f", dropped from OMRI's list as of {product.delisted_on.isoformat()}" if product.delisted_on else ""
        return f"{product.product_name} (OMRI #{product.omri_id}{dropped})"

    named = _named(products, render)
    if len(products) == 1:
        return (
            f"One product in OMRI's catalogue matches '{operation_name}': {named}. It is a possible match, "
            "not a confirmed one: the grower checks it against the label."
        )
    dropped = sum(1 for product in products if product.delisted_on)
    dropped_note = f" {dropped} of them OMRI no longer lists." if dropped else ""
    return (
        f"{len(products)} products in OMRI's catalogue match '{operation_name}': {named}.{dropped_note} None is "
        "chosen here: the grower picks the one on the label."
    )


def _standing(substance) -> str:
    """What the rule says of a National List row, in a few words, for a suggestion."""
    if not substance.is_national_list_entry:
        return "a nonsynthetic substance with no National List entry"
    if substance.is_conditionally_permitted:
        return "prohibited except for one stated use"
    if (substance.status or "").lower() == "prohibited":
        return "prohibited"
    if substance.allowed_with_condition:
        return "allowed only under a condition of use"
    return "allowed"


def _national_list_suggestions_note(operation_name: str) -> str:
    """The crop-production rows the lookup offers for a name that matched no row exactly, else "".

    A suggestion is not a citation (`national_list_basis`: a partial-name match may not be cited), so the
    verdict names them and says the name must match the listing to confirm one."""
    from certifications.services.reference_data_status import HANDLING_SECTIONS

    rows = [s for s in national_list_candidates_by_name(operation_name) if s.cfr_section not in HANDLING_SECTIONS]
    if not rows:
        return ""
    named = _named(
        rows, lambda s: f"{s.substance_name}" + (f", {s.citation}" if s.citation else "") + f", {_standing(s)}"
    )
    return (
        f"No National List entry is named '{operation_name}'. Entries whose names contain it: {named}. "
        "The substance on the label has to be named as the listing names it before the listing applies."
    )


#: OMRI's own published product-code shape: company letters, a hyphen, a product number.
#: Documented by OMRI at https://www.omri.org/using-omri-search — "Letters are used to
#: identify the company, and numbers identify each individual product." Verified 2026-09-06
#: against live certificates (dow-2900, moi-2794, tki-9178, nhf-0644, gus-5425, pfb-18591).
#:
#: A grower who has the OMRI certificate open in another tab pastes this code, not a brand
#: name. `verify_input` accepted it only through a SEPARATE `omri_id` query parameter that
#: the OSP panel never sent, so pasting "gus-4423" into the search box went down the NAME
#: matcher, tokenized to ["gus", "4423"], matched nothing, and told the grower their own
#: catalog code was not in the catalog.
OMRI_CODE_RE = re.compile(r"^[a-z]{2,6}-\d{1,7}$")


def looks_like_omri_code(value: str) -> bool:
    """True when the string is shaped like an OMRI product code rather than a product name."""
    return bool(OMRI_CODE_RE.match(_normalize(value)))


def omri_certificate_url(omri_id: str) -> str:
    """
    The public, free, per-product OMRI certificate for a product code.

    ⚠️ `https://www.omri.org/mfg/{omri_id}` — which this module used to emit — is the
    MANUFACTURER path handed a PRODUCT code, so it does not resolve to the product. The
    certificate URL decomposes the code on its hyphen: `dow-2900` -> `/mfg/dow/certificate/2900`.
    Zero padding is preserved and resolves (`nhf-0644`). Verified 2026-09-06.

    The certificate is the only place OMRI publishes a listing's EXPIRATION date — the
    downloadable PDF has no expiry column — so this link is what lets a reader check a
    claim Trazo's own snapshot cannot age out.
    """
    code = _normalize(omri_id)
    if not OMRI_CODE_RE.match(code):
        # Not a code we can decompose; fall back to a search the reader can still act on.
        return f"https://www.omri.org/omri-search?query={quote_plus(omri_id or '')}"
    letters, _, number = code.partition("-")
    return f"https://www.omri.org/mfg/{letters}/certificate/{number}"


#: Match tiers, best first. The tier is the FIRST sort key, so a weaker kind of match can
#: never displace a stronger one however many tokens it happened to cover.
#:
#:   4  anchored — tokens in order, the first landing on the product's first or second token
#:   3  contiguous — every token adjacent and in order, anywhere in the name
#:   2  anchored, with at least one token matched only by its prefix   (search only)
#:   1  contiguous, with at least one token matched only by its prefix (search only)
TIER_ANCHORED = 4
TIER_CONTIGUOUS = 3
TIER_ANCHORED_PREFIX = 2
TIER_CONTIGUOUS_PREFIX = 1


def _token_subsequence_score(farmer_tokens: list, product_tokens: list, allow_prefix: bool):
    """
    Score one catalog row against the farmer's tokens, or return None for no match.

    The rule both catalogs share: every farmer token must appear in the product's tokens
    **in order** (not necessarily contiguously), and the FIRST farmer token must land on one
    of the product's first two tokens — the brand anchor, which is what stops generic words
    like "organic fertilizer" from matching half the catalog.

    `allow_prefix` adds ONE thing: a farmer token may match by prefix rather than in full,
    so "Serenad" reaches "Serenade ASO" and "Neptun" reaches "Neptune's Harvest". A prefix
    hit scores in a STRICTLY LOWER TIER than a whole-token hit, so an exact match can never
    lose its place to a partial one.

    ⛔ `allow_prefix` is for the farmer-facing SEARCH only, never for the drift detector or
    the CDFA seeder. Prefix matching is by construction more permissive, and this repo's rule
    (`trazo-app/src/components/Compliance/InputVerifyHelper.tsx:23-25`) is that the fuzzy
    matcher "is right for search and wrong as a persisted claim". A search offers the grower
    a choice; a detector match becomes an assertion in a certifier packet.

    Returns `(tier, matched, -anchor, -len(product_tokens))` — sorted descending by the
    caller, with the row's pk appended as a stable tiebreak.
    """
    if not farmer_tokens or not product_tokens:
        return None

    best = None
    for score in (
        _anchored_subsequence(farmer_tokens, product_tokens, allow_prefix),
        _contiguous_run(farmer_tokens, product_tokens, allow_prefix),
    ):
        if score is not None and (best is None or score > best):
            best = score
    return best


def _anchored_subsequence(farmer_tokens: list, product_tokens: list, allow_prefix: bool):
    """The original rule: tokens in order, first one landing in the product's first two.

    Scores in the TOP tier because the anchor is a real signal — the grower led with the
    word the product leads with.
    """
    tier = TIER_ANCHORED
    pi = 0
    matched = 0
    anchor = None
    for ft in farmer_tokens:
        while pi < len(product_tokens):
            pt = product_tokens[pi]
            hit_full = pt == ft
            hit_prefix = allow_prefix and len(ft) >= 3 and pt.startswith(ft)
            if hit_full or hit_prefix:
                if not hit_full:
                    tier = TIER_ANCHORED_PREFIX
                if anchor is None:
                    anchor = pi
                matched += 1
                pi += 1
                break
            pi += 1
    if matched < len(farmer_tokens) or anchor is None or anchor > 1:
        return None
    return (tier, matched, -anchor, -len(product_tokens))


def _contiguous_run(farmer_tokens: list, product_tokens: list, allow_prefix: bool):
    """Every farmer token, adjacent and in order, ANYWHERE in the product name.

    🔴 2026-09-06 — this exists because the catalogues were rebuilt from the publishers'
    own files, and the publishers name products COMPANY-FIRST:

        Bayer Serenade ASO
        NovaSource Surround WP Agricultural Crop Protectant
        Down to Earth All Natural Fertilizers Feather Meal 12-0-0

    The hand-typed seed they replaced had brand-first names, so the anchor rule above held
    by accident. Against real names it stopped matching what a grower types off the bottle:
    "Serenade" and "Feather Meal" both returned NOTHING, and the drift detector — which
    calls the same matcher — began under-matching, which surfaces as false "unresolved"
    findings in a certifier packet.

    Contiguity is what makes this safe enough for the detector as well as for search:
    "feather meal 12" appearing as an unbroken run is a strong claim about identity, where
    the same tokens SCATTERED through a name are not (which is why the anchored rule permits
    scattering only when the grower led with the product's own first word).

    ⛔ A single-token run — the token merely appearing somewhere — is SEARCH ONLY. On the
    detector's path it would let an event named "Sulfur" resolve to any product with
    "Sulfur" in its name and wrongly CLEAR a § 205.400(f)(2) finding. Two tokens adjacent is
    evidence; one token anywhere is a coincidence.
    """
    if len(farmer_tokens) < 2 and not allow_prefix:
        return None

    span = len(farmer_tokens)
    for start in range(0, len(product_tokens) - span + 1):
        tier = TIER_CONTIGUOUS
        for offset, ft in enumerate(farmer_tokens):
            pt = product_tokens[start + offset]
            if pt == ft:
                continue
            if allow_prefix and len(ft) >= 3 and pt.startswith(ft):
                tier = TIER_CONTIGUOUS_PREFIX
                continue
            break
        else:
            # A run found earlier in the name is the better answer, and `start` is already
            # the first one found, so return immediately rather than scanning on.
            return (tier, span, -start, -len(product_tokens))
    return None


def _strip_omri_suffix(normalized: str) -> str:
    """
    Drop the trailing "-o" / " o" marker OMRI appends to "-O"-listed variants of
    products (e.g., "Kocide 3000-O" → "kocide 3000"). Farmers type the label
    name from the bottle, which almost never includes that suffix.
    """
    if normalized.endswith("-o"):
        return normalized[:-2].strip()
    if normalized.endswith(" o"):
        return normalized[:-2].strip()
    return normalized


def _name_tokens(s: str) -> list:
    """
    Tokenize a product/commercial name for matching. Strips:
      - parenthetical descriptors like "(Spinosad 22.5%)" that farmers copy
        off the label after the product name and are NOT part of product identity
      - possessive "'s" ("Neptune's" → "Neptune")
      - stylized apostrophes (curly → straight, then removed)
    Normalizes "&" → "and" and drops ≤1-char noise.

    So "Neptune's Harvest Fish & Seaweed (2-3-1)" ↔ "neptune harvest fish and
    seaweed 2 3 1" and "Kocide 3000 (Copper Hydroxide 46.1%)" ↔ "kocide 3000".
    """
    cleaned = (s or "").lower().replace("\u2019", "'")
    # Strip everything from the first "(" onward — product identity is before it.
    paren = cleaned.find("(")
    if paren > 0:
        cleaned = cleaned[:paren]
    cleaned = cleaned.replace("'s ", " ").replace("'s", "").replace("&", " and ").replace("'", "")
    return [t for t in re.split(r"[^a-z0-9]+", cleaned) if len(t) >= 2]


def _resolve_omri_by_name(farmer_input: str):
    """
    Best-effort match of a farmer-typed commercial name against the seeded
    OMRIProduct catalog. Returns the matched `OMRIProduct` or None.

    Matching priority (stop at the first hit):
      1. Exact normalized match, with or without the "-O" suffix the OMRI
         catalog appends to OMRI-listed variants (e.g., "Kocide 3000-O").
      2. Subsequence match: every farmer token appears in the product's
         tokens in order (not necessarily contiguously). Handles catalog
         names with marketing words the farmer skips ("PyGanic Crop
         Protection EC 1.4 II" ↔ farmer "PyGanic EC 1.4"). Additional
         constraint: the FIRST farmer token must match one of the product's
         first two tokens — this is the brand anchor and prevents false
         positives from generic words like "organic fertilizer".
      3. Single-token fallback: farmer typed just one word that matches the
         product's first token (e.g., "Kocide" → Kocide 3000-O).

    Tiebreakers: more farmer tokens matched, earlier anchor position, shorter
    product name (prefer base product), lower pk (stable).
    """
    # ONE ranking, expressed once. This used to hold its own copy of the scoring loop below
    # `_omri_candidates_by_name`'s; two copies of a tiebreaker drift, and the day they disagree
    # the UI would offer a shortlist whose top row is not the row every other caller resolves
    # to. Delegating also means the drift detector and the farmer-facing lookup can never rank
    # differently.
    candidates = _omri_candidates_by_name(farmer_input)
    return candidates[0] if candidates else None


def _omri_candidates_by_name(farmer_input: str, allow_prefix: bool = False):
    """Every catalog row `_resolve_omri_by_name` considered, best first.

    Same ranking, plural answer. `_resolve_omri_by_name` exists to pick ONE row for search
    and for the drift detector, and picking one is right there. It is wrong the moment a
    grower is offered a one-tap "this is my product": typing "Neptune" satisfies seven rows
    (the catalog carries 2-4-1, 2-4-0.5, 2-3-1, 2-3-0.5, kelp meal, seaweed plant food and
    soluble powder), the "prefer the shorter name" tiebreaker returns the 2-4-1, and a grower
    holding a bottle of 2-3-1 would attach a listing for a product they did not apply.

    That is the failure `consumer-omri-listing-leak-2026-08-09` names by example
    ("Neptune's Harvest 2-3-1" -> "Fish Fertilizer 2-4-1", different product) and the reason
    the FK is only ever written by an operator's tap. A tap on an ambiguous guess is not a
    decision, so the caller must be able to SHOW the alternatives instead.

    Returns EVERY match, ranked, with no cap: `[]` when nothing matches, one row when the
    answer is unambiguous. It carried a `limit=6` default until 2026-09-02, which silently
    dropped the seventh Neptune's Harvest row AND made the caller's `len()` a truncated count
    presented to the grower as a total ("6 products match" when 7 did) — the same defect the
    shortlist exists to fix, one layer down. Capping for display is the caller's business, and
    the caller must then say that it capped.

    `allow_prefix` (2026-09-06) lets a farmer token match by prefix, so "Serenad" reaches
    "Serenade ASO". ⛔ It defaults OFF and must stay off for `_resolve_omri_by_name`, which is
    what the drift detector and `seed_cdfa_oim` call: a prefix hit is a search suggestion, and
    those two callers turn a hit into a persisted claim. Prefix hits also rank in a strictly
    lower tier than whole-token hits, so turning it on can never displace an exact answer.
    """
    normalized = _normalize(farmer_input)
    if not normalized:
        return []

    # Pass 0 — the grower pasted the OMRI product code off the certificate. That is the most
    # specific input this function can receive, so it answers before any name matching. It is
    # safe for the detector too: an exact code is an identity, not a guess.
    if looks_like_omri_code(normalized):
        by_code = OMRIProduct.objects.filter(omri_id__iexact=normalized).first()
        if by_code:
            return [by_code]
        # A well-formed code that is not in our subset is a MISS, not an invitation to go
        # guess a product name from "gus" and "4423".
        return []

    exact = list(
        OMRIProduct.objects.extra(
            where=["LOWER(product_name) = %s OR LOWER(product_name) = %s"],
            params=[normalized, normalized + "-o"],
        ).order_by("product_name", "pk")
    )
    if exact:
        # An exact hit is the answer, not a shortlist: never offer weaker matches beside it. But a
        # name is not always one product. 73 names in the committed catalogue belong to two to six
        # products ("Potassium humate" six times, "Fulvic acid" five, from different manufacturers),
        # and `.first()` here picked one of them by row order and reported one candidate (review of
        # PR 505). Every product holding the exact name is returned, so the grower picks by maker.
        return exact

    farmer_tokens = _name_tokens(farmer_input)
    if not farmer_tokens:
        return []

    candidates = []
    for pk, pname in OMRIProduct.objects.values_list("id", "product_name"):
        ptokens = _name_tokens(_strip_omri_suffix(_normalize(pname)))
        score = _token_subsequence_score(farmer_tokens, ptokens, allow_prefix)
        if score is not None:
            candidates.append(score + (-pk, pk))

    if not candidates:
        return []

    ordered_pks = [c[-1] for c in sorted(candidates, reverse=True)]
    by_pk = {o.pk: o for o in OMRIProduct.objects.filter(pk__in=ordered_pks)}
    return [by_pk[pk] for pk in ordered_pks if pk in by_pk]


def _resolve_wsda_by_name(farmer_input: str):
    """
    Match a farmer-typed commercial name against the WSDAMaterial catalog.

    Uses the same token-subsequence + brand-anchor matcher as
    `_resolve_omri_by_name` — kept separate rather than generalized because
    (a) WSDAMaterial's name column is `brand_name` not `product_name`, and
    (b) WSDA does NOT use the "-O" OMRI suffix convention, so the
    `_strip_omri_suffix` step is skipped.
    """
    candidates = _wsda_candidates_by_name(farmer_input)
    return candidates[0] if candidates else None


def _wsda_candidates_by_name(farmer_input: str, allow_prefix: bool = False):
    """Every WSDA row the query matched, best first — the plural answer.

    WSDA had only the singular resolver until 2026-09-06, which is why searching "Serenade"
    returned exactly one brand while the catalog held several: the shortlist fix that landed
    for OMRI (see `_omri_candidates_by_name`) was never ported here, and a grower could not
    see — let alone pick — the row that was actually on their plan.

    Same ranking as OMRI, one difference kept from the singular version: WSDA does not use
    the "-O" suffix convention, so `_strip_omri_suffix` is not applied to `brand_name`.
    """
    normalized = _normalize(farmer_input)
    if not normalized:
        return []

    exact = WSDAMaterial.objects.extra(
        where=["LOWER(brand_name) = %s"],
        params=[normalized],
    ).first()
    if exact:
        return [exact]

    farmer_tokens = _name_tokens(farmer_input)
    if not farmer_tokens:
        return []

    candidates = []
    for pk, bname in WSDAMaterial.objects.values_list("id", "brand_name"):
        ptokens = _name_tokens(_normalize(bname))
        score = _token_subsequence_score(farmer_tokens, ptokens, allow_prefix)
        if score is not None:
            candidates.append(score + (-pk, pk))

    if not candidates:
        return []

    ordered_pks = [c[-1] for c in sorted(candidates, reverse=True)]
    by_pk = {m.pk: m for m in WSDAMaterial.objects.filter(pk__in=ordered_pks)}
    return [by_pk[pk] for pk in ordered_pks if pk in by_pk]


def national_list_candidates_by_name(query: str, limit: int = 25):
    """
    Every National List substance the farmer's query could mean, best first.

    ⚠️ Farmer-facing SEARCH only. The drift detector deliberately keeps its own stricter
    resolver (`drift_detector._resolve_national_list_by_name`: exact, then forward
    containment) because a save-time match becomes an assertion. This function is more
    generous on purpose — it is offering the grower a choice, not making one.

    Three passes, each a strictly weaker signal than the last, ranked in that order:
      1. exact normalized name;
      2. FORWARD containment — the substance name appears inside what the farmer typed
         ("Kocide 3000 (Copper Hydroxide 46.1%)" contains "copper hydroxide"), longest and
         therefore most specific substance first;
      3. REVERSE containment — what the farmer typed appears inside the substance name
         ("copper" -> "copper sulfate", "copper hydroxide"), shortest first.

    Pass 3 is why this returns a LIST. The singular resolver in `verify_input` collapsed it
    with `min(..., key=len)`, so typing "copper" produced exactly one of the several copper
    entries on § 205.601 and hid the rest — and the one it produced was chosen by name length,
    which is not a fact about the grower's product.
    """
    normalized = _normalize(query)
    if not normalized:
        return []

    # Every section that lists the name, not the first. "Hydrogen peroxide" is on § 205.601 for
    # crop production AND on § 205.605 for post-harvest handling, and which listing covers the
    # grower's use is theirs to pick — `.first()` would always hide the handling row (2026-09-10).
    # Detectors keep their own singular resolver, where the model ordering puts § 205.601 first.
    exact = list(NationalListSubstance.objects.filter(substance_name_normalized=normalized))
    # A substance listed under more than one subsection is seeded as one row per listing, the
    # extra ones qualified by use: "Peracetic acid" (a) and "Peracetic acid (fire blight)" (i),
    # "Hydrogen peroxide" (a) and "Hydrogen peroxide (disease control)" (i). The exact name alone
    # returned only the unqualified row and hid the other listings, so the grower could not pick
    # the subsection that covers their use. The qualified rows follow the exact ones.
    variants = list(NationalListSubstance.objects.filter(substance_name_normalized__startswith=f"{normalized} ("))
    if exact or variants:
        return exact + variants

    # The curated alias table the saved record is classified by (`history/signals.py`, the drift
    # detector). "zinc sulfate", "Solubor" and "borax" are how a grower names the § 205.601(j)(7)
    # rows, and none of them is contained in, or contains, the catalogue's row name, so until
    # 2026-11-16 the lookup answered "no match" for the inputs whose condition (a documented
    # deficiency) it most needs to show (overall review OV-MT-C01). An ambiguous term resolves to
    # nothing here, exactly as on save.
    #
    # The alias hit LEADS the list and never replaces it. The table answers one row for save-time
    # classification, and this function offers the grower a choice: "sulfur" is "Elemental sulfur"
    # to the classifier, but the grower typing it may hold lime sulfur or sulfurous acid, and a list
    # of one reads as unambiguous to `verify_input` (review of back #453).
    from certifications.services.national_list_aliases import resolve_alias

    canonical = resolve_alias(query)
    aliased_pks = (
        list(NationalListSubstance.objects.filter(substance_name=canonical).values_list("id", flat=True))
        if canonical
        else []
    )

    rows = list(NationalListSubstance.objects.values_list("id", "substance_name_normalized"))

    forward = [(pk, n) for pk, n in rows if len(n) >= 5 and n in normalized]
    reverse = [(pk, n) for pk, n in rows if len(normalized) >= 3 and normalized in n and (pk, n) not in forward]

    ordered_pks = list(aliased_pks)
    ordered_pks += [pk for pk, _ in sorted(forward, key=lambda pair: (-len(pair[1]), pair[0])) if pk not in aliased_pks]
    ordered_pks += [pk for pk, _ in sorted(reverse, key=lambda pair: (len(pair[1]), pair[0])) if pk not in aliased_pks]
    ordered_pks = ordered_pks[:limit]

    by_pk = {s.pk: s for s in NationalListSubstance.objects.filter(pk__in=ordered_pks)}
    return [by_pk[pk] for pk in ordered_pks if pk in by_pk]


class OMRIProductVerifier(BaseCertificationVerifier):
    """Cross-reference chemical inputs against OMRI (farmer-confirmed) + National List."""

    @property
    def verifier_name(self) -> str:
        return "OMRI + National List (7 CFR 205.601/602)"

    @property
    def source_identifier(self) -> str:
        return "omri_national_list"

    @property
    def supported_certification_types(self) -> List[str]:
        return ["omri_listed", "nop_allowed", "nop_prohibited"]

    def verify(
        self,
        operation_name: str,
        state: str = "",
        certification_number: Optional[str] = None,
        **kwargs,
    ) -> VerificationResult:
        """
        operation_name here = the chemical's commercial_name or active_ingredient.
        certification_number = optional farmer-provided OMRI ID (e.g., "OMRI-01234").

        Returns the strongest match found.
        """
        # 1) Direct OMRI ID lookup (farmer-confirmed).
        if certification_number:
            omri = OMRIProduct.objects.filter(omri_id__iexact=certification_number.strip()).first()
            if omri:
                return self._build_omri_result(
                    omri,
                    certifier_name="OMRI (farmer-reported)",
                    confidence=0.9,  # farmer-confirmed, not Trazo-verified
                    lead=f"OMRI ID {omri.omri_id} ({omri.product_name}), farmer-reported.",
                )

        normalized = _normalize(operation_name)
        if not normalized:
            return VerificationResult(found=False, status="not_found", notes="No name provided.")

        # 2) OMRI catalog lookup by product name (seeded from the official OMRI Crop Products List
        # PDF, see seed_omri_minimal.py). Only an IDENTITY answers before the National List: the code
        # off the certificate, or a product name typed exactly that one product holds. Until 2026-11
        # any name match did, with `found: True` for the top-ranked row: "Neptune" named the 2-4-1
        # among seven Neptune's Harvest products, and "Potassium chloride" named one fertilizer whose
        # name contains the words, so the § 205.602(e) condition never answered (overall review
        # 2026-11, OV-MT-C14, and its review). Every other match is a candidate the grower picks from,
        # counted the way the lookup counts them (`allow_prefix=True`, as `verify_input` calls it).
        omri_matches = _omri_candidates_by_name(operation_name, allow_prefix=True)
        if len(omri_matches) == 1 and _is_identity(omri_matches[0], normalized):
            product = omri_matches[0]
            return self._build_omri_result(
                product,
                certifier_name="OMRI (catalog match)",
                confidence=0.85,  # catalog hit, one step weaker than farmer-pasted ID
                lead=f"Matched OMRI catalog: {product.product_name} (OMRI #{product.omri_id}).",
            )
        omri_note = _omri_candidates_note(operation_name, omri_matches)

        # 3) National List lookup by name. A substance match is a statement about the substance, so
        # it answers even when the name also matched OMRI products, and says that it did.
        listed = self._match_national_list(operation_name)
        if listed is not None:
            if omri_note:
                listed.notes = f"{listed.notes} {omri_note}".strip()
                if not listed.found:
                    # A nonsynthetic row (spinosad, Bt) has no listing to confirm, so its own answer is
                    # `not_found`; with OMRI candidates beside it, the answer is that one of them may be the
                    # evidence, which is what `possible_match` says (review of PR 505).
                    listed.status = "possible_match"
            return listed

        # Nothing confirmed. Name what the lookup would offer, so the verdict and the lookup's fields in
        # the same response do not disagree ("calcium chloride" is not the listing's name, and the
        # lookup offers § 205.602(c) for it), and choose none of it.
        possible = " ".join(note for note in (_national_list_suggestions_note(operation_name), omri_note) if note)
        if possible:
            return VerificationResult(found=False, status="possible_match", notes=possible)
        return VerificationResult(
            found=False,
            status="not_found",
            notes=(
                f"'{operation_name}' not found on the National List and no OMRI ID provided. "
                f"Inspector will treat as self-reported only."
            ),
        )

    def _match_national_list(self, operation_name: str) -> Optional[VerificationResult]:
        """The crop-production National List row the name matches, as a result; None when none does."""
        normalized = _normalize(operation_name)
        # Crop rows only: this verifies a crop input, and § 205.605/606 list HANDLING substances.
        from certifications.services.reference_data_status import national_list_crop_rows

        crop_rows = national_list_crop_rows()

        # Exact normalized match is the strongest signal.
        exact = crop_rows.filter(substance_name_normalized=normalized).first()
        if exact:
            return self._build_nl_result(exact, confidence=1.0, match_type="exact")

        # The curated crosswalk, in the same place the save path consults it
        # (`history.signals.auto_classify_chemical_against_national_list`): "zinc sulfate", "boron" and
        # "sulfur" are how growers name the § 205.601 rows, and a saved record is classified by them, so
        # the verdict answering "not found" for the same name disagreed with the record it describes.
        from certifications.services.national_list_aliases import resolve_alias

        canonical = resolve_alias(normalized)
        if canonical:
            aliased = crop_rows.filter(substance_name=canonical).first()
            if aliased:
                return self._build_nl_result(aliased, confidence=0.9, match_type="alias")

        # Containment match — ONE DIRECTION ONLY: full NL substance name must appear
        # inside the farmer's input. (The inverse — farmer's generic word inside an NL
        # substance name — causes false positives like "hydroxide" -> "Copper hydroxide"
        # when the farmer actually meant "Sodium hydroxide", which is NOT on the list.)
        # We also require the NL name to be >=5 chars to avoid trivial-word hits.
        MIN_MATCH_LEN = 5
        candidate_names = crop_rows.values_list("substance_name_normalized", flat=True)
        matches = [n for n in candidate_names if len(n) >= MIN_MATCH_LEN and n in normalized]
        if matches:
            # Prefer the longest (most specific) match — e.g., "copper sulfate" beats "copper"
            best = max(matches, key=len)
            contains = crop_rows.filter(substance_name_normalized=best).first()
            if contains:
                return self._build_nl_result(contains, confidence=0.75, match_type="contained")
        return None

    def _build_omri_result(self, product: OMRIProduct, certifier_name: str, confidence: float, lead: str):
        """One OMRI product, named. A product OMRI has dropped is `delisted`, never a listing match: the
        lookup's `omri_product_delisted_on` already said so (OV-MT-C04) while this verdict did not."""
        if product.delisted_on:
            return VerificationResult(
                found=True,
                status="delisted",
                certifier_name=certifier_name,
                source_url=omri_certificate_url(product.omri_id),
                confidence_score=confidence,
                notes=(
                    f"{lead} OMRI no longer lists it: the first OMRI list Trazo loaded without it is dated "
                    f"{product.delisted_on.isoformat()}. Check the product's certificate at omri.org."
                ),
            )
        return VerificationResult(
            found=True,
            status="listing_match",  # run 8: a listing describes a material, never a verification
            certifier_name=certifier_name,
            source_url=omri_certificate_url(product.omri_id),
            confidence_score=confidence,
            notes=f"{lead} Inspector should cross-check at omri.org.",
        )

    def _build_nl_result(self, entry: NationalListSubstance, confidence: float, match_type: str) -> VerificationResult:
        if not entry.is_national_list_entry:
            # A nonsynthetic catalogue row (spinosad, Bt, d-limonene) is allowed without any listing,
            # which is exactly why there is nothing to verify. "verified" beside a "7 CFR" citation
            # here named a listing that does not exist (eCFR check, 2026-09-10).
            return VerificationResult(
                found=False,
                status="not_found",
                confidence_score=confidence,
                notes=(
                    f"Matched {entry.substance_name} ({match_type}), a nonsynthetic substance: allowed in organic "
                    "crop production without a National List entry, so there is no listing to verify it against. "
                    "An OMRI or WSDA listing of the product, or the certifier's review, is the evidence."
                ),
            )
        if entry.status == "allowed":
            notes = f"Matched National List ({match_type}): {entry.substance_name}."
            # The typed paragraph table decides (`national_list_citations.USE_CONDITION_601`), and the
            # words are the rule's, verbatim: "Minimize soil accumulation." beside copper hydroxide was
            # a paraphrase with no condition in it (OV-MT-C01, carried to this verdict by OV-MT-C14).
            condition = use_condition(entry)
            if condition:
                paragraph, words = condition
                notes += (
                    f" Allowed only under a condition of use. The rule's words, § {entry.cfr_section}{paragraph}: "
                    f"{words} The record of each use must show it met that condition."
                )
            elif entry.restriction_notes:
                notes += f" {entry.restriction_notes}"
            return VerificationResult(
                found=True,
                status="listing_match",  # run 8: a listing describes a material, never a verification
                certifier_name=f"7 CFR {entry.citation}",
                source_url=_ECFR_PART_205,
                confidence_score=confidence,
                notes=notes,
            )
        if entry.is_conditionally_permitted:
            # § 205.602(c), (e), (h): prohibited EXCEPT for one stated use. "PROHIBITED ... disqualifies
            # the crop from organic sale" told an orchard spraying calcium chloride for bitter pit, which
            # the rule names as the allowed use, that it had lost organic status. Whether a use met the
            # condition is not knowable here, so the verdict states the condition and stops. The quote is
            # the rule's whole entry (`RULE_TEXT`); the stored note is an excerpt of it.
            from certifications.services.national_list_citations import RULE_TEXT

            words = (
                RULE_TEXT.get((entry.cfr_section, f"({entry.subsection})")) or (entry.restriction_notes or "").strip()
            )
            quoted = f' The rule, {entry.citation}: "{words}"' if words else f" See {entry.citation}."
            return VerificationResult(
                found=True,
                status="restricted_use",
                certifier_name=f"7 CFR {entry.citation}",
                source_url=_ECFR_PART_205,
                confidence_score=confidence,
                notes=(
                    f"Matched National List ({match_type}): {entry.substance_name}, prohibited except for the use "
                    f"the rule names.{quoted} The record of each use must show it met that condition."
                ),
            )
        return VerificationResult(
            found=True,
            status="revoked",  # prohibited substance
            certifier_name=f"7 CFR {entry.citation}",
            confidence_score=confidence,
            notes=(
                f"PROHIBITED substance matched ({match_type}): {entry.substance_name}. "
                f"Use disqualifies the crop from organic sale. {entry.restriction_notes or ''}"
            ).strip(),
        )

    def health_check(self) -> bool:
        """True when the crop-production National List is loaded — not merely any row.

        All data is local, so "reachable" means "seeded". The handling rows migration 0038 adds
        to every database do not count: see `reference_data_status.national_list_crop_rows`.
        """
        from certifications.services.reference_data_status import national_list_crop_rows

        return national_list_crop_rows().exists()
