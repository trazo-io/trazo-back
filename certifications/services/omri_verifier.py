"""
OMRI / National List verifier — Sprint 3.

Resolves against Trazo's LOCAL catalog copies, never a live OMRI call. Verifies
chemical inputs against:

  1. A farmer-provided OMRI ID (OMRIProduct record) — farmer pasted from omri.org.
  2. The hardcoded National List (NationalListSubstance — 7 CFR 205.601/602).

Returns a `VerificationResult` compatible with the existing BaseCertificationVerifier
pattern (see usda_organic_verifier.py).

Classification priority:
    omri_listed         -> OMRIProduct record present (farmer-confirmed)
    nop_allowed         -> Substance matches NationalListSubstance with status=allowed
    nop_prohibited      -> Substance matches NationalListSubstance with status=prohibited
    not_found           -> No match in either source (treat as self-reported only)
"""

import re
from typing import List, Optional
from urllib.parse import quote_plus

from certifications.models import NationalListSubstance, OMRIProduct, WSDAMaterial
from certifications.services.base_verifier import BaseCertificationVerifier, VerificationResult


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


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

    exact = OMRIProduct.objects.extra(
        where=["LOWER(product_name) = %s OR LOWER(product_name) = %s"],
        params=[normalized, normalized + "-o"],
    ).first()
    if exact:
        # An exact hit is the answer, not a shortlist — never offer alternatives to it.
        return [exact]

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
    if exact:
        return exact

    rows = list(NationalListSubstance.objects.values_list("id", "substance_name_normalized"))

    forward = [(pk, n) for pk, n in rows if len(n) >= 5 and n in normalized]
    reverse = [(pk, n) for pk, n in rows if len(normalized) >= 3 and normalized in n and (pk, n) not in forward]

    ordered_pks = [pk for pk, _ in sorted(forward, key=lambda pair: (-len(pair[1]), pair[0]))]
    ordered_pks += [pk for pk, _ in sorted(reverse, key=lambda pair: (len(pair[1]), pair[0]))]
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
                return VerificationResult(
                    found=True,
                    status="listing_match",  # run 8: a listing describes a material, never a verification
                    certifier_name="OMRI (farmer-reported)",
                    source_url=omri_certificate_url(omri.omri_id),
                    confidence_score=0.9,  # farmer-confirmed, not Trazo-verified
                    notes=(
                        f"OMRI ID {omri.omri_id} ({omri.product_name}) — farmer-reported. "
                        f"Inspector should cross-check at omri.org."
                    ),
                )

        # 2) OMRI catalog lookup by product name (seeded from the official OMRI
        # Crop Products List PDF — see seed_omri_minimal.py). OMRI is more
        # specific than the National List, so a hit here shortcuts NL matching.
        omri_by_name = _resolve_omri_by_name(operation_name)
        if omri_by_name:
            return VerificationResult(
                found=True,
                status="listing_match",  # run 8: a listing describes a material, never a verification
                certifier_name="OMRI (catalog match)",
                source_url=omri_certificate_url(omri_by_name.omri_id),
                confidence_score=0.85,  # catalog hit, one step weaker than farmer-pasted ID
                notes=(
                    f"Matched OMRI catalog: {omri_by_name.product_name} "
                    f"(OMRI #{omri_by_name.omri_id}). Inspector should cross-check at omri.org."
                ),
            )

        # 3) National List lookup by name (allowed list first, then prohibited).
        normalized = _normalize(operation_name)
        if not normalized:
            return VerificationResult(found=False, status="not_found", notes="No name provided.")

        # Crop rows only: this verifies a crop input, and § 205.605/606 list HANDLING substances.
        from certifications.services.reference_data_status import national_list_crop_rows

        crop_rows = national_list_crop_rows()

        # Exact normalized match is the strongest signal.
        exact = crop_rows.filter(substance_name_normalized=normalized).first()
        if exact:
            return self._build_nl_result(exact, confidence=1.0, match_type="exact")

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

        return VerificationResult(
            found=False,
            status="not_found",
            notes=(
                f"'{operation_name}' not found on the National List and no OMRI ID provided. "
                f"Inspector will treat as self-reported only."
            ),
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
            return VerificationResult(
                found=True,
                status="listing_match",  # run 8: a listing describes a material, never a verification
                certifier_name=f"7 CFR {entry.cfr_section}{entry.subsection or ''}",
                source_url="https://www.ecfr.gov/current/title-7/subtitle-B/chapter-I/subchapter-M/part-205",
                confidence_score=confidence,
                notes=(
                    f"Matched National List ({match_type}): {entry.substance_name}. " f"{entry.restriction_notes or ''}"
                ).strip(),
            )
        return VerificationResult(
            found=True,
            status="revoked",  # prohibited substance
            certifier_name=f"7 CFR {entry.cfr_section}",
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
