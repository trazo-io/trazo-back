"""
OMRI / National List verifier — Sprint 3.

Does NOT hit the OMRI website (paid subscription / ToS restricted). Instead, verifies
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

from certifications.models import NationalListSubstance, OMRIProduct, WSDAMaterial
from certifications.services.base_verifier import BaseCertificationVerifier, VerificationResult


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


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


def _omri_candidates_by_name(farmer_input: str):
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
    """
    normalized = _normalize(farmer_input)
    if not normalized:
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
        if not ptokens:
            continue

        if len(farmer_tokens) == 1:
            if ptokens[0] == farmer_tokens[0]:
                candidates.append((1, 0, -len(ptokens), -pk, pk))
            continue

        pi = 0
        matched = 0
        anchor = None
        for ft in farmer_tokens:
            while pi < len(ptokens):
                if ptokens[pi] == ft:
                    if anchor is None:
                        anchor = pi
                    matched += 1
                    pi += 1
                    break
                pi += 1
        if matched < len(farmer_tokens):
            continue
        if anchor is None or anchor > 1:
            continue
        candidates.append((matched, -anchor, -len(ptokens), -pk, pk))

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
    normalized = _normalize(farmer_input)
    if not normalized:
        return None

    exact = WSDAMaterial.objects.extra(
        where=["LOWER(brand_name) = %s"],
        params=[normalized],
    ).first()
    if exact:
        return exact

    farmer_tokens = _name_tokens(farmer_input)
    if not farmer_tokens:
        return None

    candidates = []
    for pk, bname in WSDAMaterial.objects.values_list("id", "brand_name"):
        ptokens = _name_tokens(_normalize(bname))
        if not ptokens:
            continue

        if len(farmer_tokens) == 1:
            if ptokens[0] == farmer_tokens[0]:
                candidates.append((1, 0, -len(ptokens), -pk, pk))
            continue

        pi = 0
        matched = 0
        anchor = None
        for ft in farmer_tokens:
            while pi < len(ptokens):
                if ptokens[pi] == ft:
                    if anchor is None:
                        anchor = pi
                    matched += 1
                    pi += 1
                    break
                pi += 1
        if matched < len(farmer_tokens):
            continue
        if anchor is None or anchor > 1:
            continue
        candidates.append((matched, -anchor, -len(ptokens), -pk, pk))

    if candidates:
        return WSDAMaterial.objects.filter(pk=max(candidates)[-1]).first()
    return None


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
                    status="verified",
                    certifier_name="OMRI (farmer-reported)",
                    source_url=f"https://www.omri.org/mfg/{omri.omri_id}",
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
                status="verified",
                certifier_name="OMRI (catalog match)",
                source_url=f"https://www.omri.org/mfg/{omri_by_name.omri_id}",
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

        # Exact normalized match is the strongest signal.
        exact = NationalListSubstance.objects.filter(substance_name_normalized=normalized).first()
        if exact:
            return self._build_nl_result(exact, confidence=1.0, match_type="exact")

        # Containment match — ONE DIRECTION ONLY: full NL substance name must appear
        # inside the farmer's input. (The inverse — farmer's generic word inside an NL
        # substance name — causes false positives like "hydroxide" -> "Copper hydroxide"
        # when the farmer actually meant "Sodium hydroxide", which is NOT on the list.)
        # We also require the NL name to be >=5 chars to avoid trivial-word hits.
        MIN_MATCH_LEN = 5
        candidate_names = NationalListSubstance.objects.values_list("substance_name_normalized", flat=True)
        matches = [n for n in candidate_names if len(n) >= MIN_MATCH_LEN and n in normalized]
        if matches:
            # Prefer the longest (most specific) match — e.g., "copper sulfate" beats "copper"
            best = max(matches, key=len)
            contains = NationalListSubstance.objects.filter(substance_name_normalized=best).first()
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
        if entry.status == "allowed":
            return VerificationResult(
                found=True,
                status="verified",
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
        """All data is local; this is always 'reachable' as long as the DB is up."""
        return NationalListSubstance.objects.exists()
