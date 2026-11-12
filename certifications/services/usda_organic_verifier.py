"""
USDA Organic Integrity Database verifier.

Verifies USDA Organic certifications against a local copy of the USDA
Organic Integrity Database, populated from the monthly bulk XLSX export.

Source: https://organic.ams.usda.gov/integrity/Reports/DataHistory
Import: poetry run python manage.py import_usda_organic_data

Note: The USDA migrated their web interface to Blazor/SignalR in 2025,
killing the old REST API. This verifier uses the bulk data export instead.
"""

import difflib
import logging
import re
from typing import List, Optional

from certifications.verification_notes import percent, render
from common.us_states import US_STATE_ABBREVS, US_STATE_NAMES

from .base_verifier import BaseCertificationVerifier, VerificationResult

logger = logging.getLogger(__name__)

# Fuzzy match confidence threshold.
# Raised from 0.75 to 0.90 (2026-03-21) to reduce false-positive "Verified" badges.
# At 0.75, names like "Smith Valley Farm LLC" could match "Smiths Farm Valley" —
# a legally distinct operation. 0.90 requires near-exact token agreement after
# stripping legal suffixes and common farm-name words.
FUZZY_MATCH_THRESHOLD = 0.90

# Words to strip from farm names for matching
STRIP_WORDS = {
    "llc",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "farm",
    "farms",
    "ranch",
    "ranches",
    "orchard",
    "orchards",
    "vineyard",
    "vineyards",
    "estate",
    "estates",
    "co",
    "company",
    "the",
    "and",
    "of",
    "dba",
    "ltd",
    "limited",
}


class USDAOrganicVerifier(BaseCertificationVerifier):
    """
    Verifies certifications against a local copy of the USDA Organic
    Integrity Database (populated from monthly bulk XLSX export).
    """

    @property
    def verifier_name(self) -> str:
        return "USDA Organic Integrity Database"

    @property
    def source_identifier(self) -> str:
        return "usda_organic_integrity_db"

    @property
    def supported_certification_types(self) -> List[str]:
        return ["usda_organic"]

    def verify(
        self,
        operation_name: str,
        state: str,
        certification_number: Optional[str] = None,
        **kwargs,
    ) -> VerificationResult:
        """
        Verify a farm's USDA Organic certification against the local database.
        """
        from certifications.models import USDAOrganicOperation

        # Check if we have data loaded
        record_count = USDAOrganicOperation.objects.count()
        if record_count == 0:
            # The operator's instruction goes to the log, never to the certificate's note: that
            # note is printed to the grower under the certificate (recordkeeping review F-26).
            logger.warning("USDA Organic Integrity Database not loaded; run: python manage.py import_usda_organic_data")
            return VerificationResult(
                found=False,
                status="self_reported",
                notes=render("not_loaded"),
            )

        # Normalize the state — USDA uses full names ("California" not "CA")
        state_full = self._normalize_state_to_full(state)

        # Search by state first, then fuzzy match name
        candidates = USDAOrganicOperation.objects.filter(state__iexact=state_full)

        if not candidates.exists():
            # Try abbreviation in case DB has mixed formats
            state_abbrev = self._normalize_state_to_abbrev(state)
            candidates = USDAOrganicOperation.objects.filter(state__iexact=state_abbrev)

        if not candidates.exists():
            return VerificationResult(
                found=False,
                status="not_found",
                notes=render("no_operations_in_state", state=state_full),
            )

        # Fuzzy match against the normalized name
        normalized_search = self._normalize_name(operation_name)
        operation_name_lower = operation_name.lower().strip()

        best_match = None
        best_confidence = 0.0

        # Strategy 1: Direct name search (case-insensitive, on raw name)
        # This catches exact or near-exact matches like "Earthbound Farm" -> "Earthbound Farm, LLC"
        from django.db.models import Q

        direct_matches = candidates.filter(
            Q(op_name__icontains=operation_name_lower) | Q(op_name_normalized__icontains=normalized_search)
        )

        if not direct_matches.exists():
            # Strategy 2: Word-based search on individual significant words
            search_words = normalized_search.split()
            q = Q()
            for word in search_words[:3]:
                if len(word) >= 3:
                    q |= Q(op_name_normalized__icontains=word)
                    q |= Q(op_name__icontains=word)
            if q:
                direct_matches = candidates.filter(q)

        for op in direct_matches[:500]:
            # Step 1: Match on normalized names (stripped of LLC, Farm, etc.)
            norm_confidence = difflib.SequenceMatcher(None, normalized_search, op.op_name_normalized).ratio()

            if norm_confidence < FUZZY_MATCH_THRESHOLD:
                continue

            # Step 2: Verify on original names to prevent false positives
            # e.g., "Green Valley Farm" vs "Green Valley Vineyards, Inc."
            # normalize to the same "green valley" but the originals are clearly different.
            # Require at least 0.50 similarity on original names as a sanity check.
            raw_confidence = difflib.SequenceMatcher(
                None,
                operation_name.lower().strip(),
                op.op_name.lower().strip(),
            ).ratio()

            # Combined confidence: weighted average (normalized 60%, raw 40%)
            # This rewards exact normalized matches but penalizes raw name divergence
            combined = (norm_confidence * 0.6) + (raw_confidence * 0.4)

            if combined > best_confidence:
                best_confidence = combined
                best_match = op

        if best_match is None or best_confidence < FUZZY_MATCH_THRESHOLD:
            return VerificationResult(
                found=False,
                status="not_found",
                notes=render(
                    "no_match",
                    count=candidates.count(),
                    state=state_full,
                    name=operation_name,
                    threshold=percent(FUZZY_MATCH_THRESHOLD),
                ),
            )

        # Run 8: a fuzzy score finds a candidate, it does not confirm one. "verified" needs a
        # confirmed entry: exactly one operation in the state whose normalized name equals the
        # farm's, and, when the farm recorded its certifying agent, the same agent. The bulk
        # export Trazo imports carries no certificate or operation number, so the name, state and
        # agent are the whole of what can be confirmed. Anything weaker is a possible match.
        result = self._build_result(best_match, best_confidence)
        if result.status == "verified":
            confirmed, code, params = self._confirmed(
                candidates, best_match, normalized_search, kwargs.get("certifier_name")
            )
            if not confirmed:
                result.status = "possible_match"
                result.notes = render(code, op_name=best_match.op_name, similarity=percent(best_confidence), **params)
        return result

    @staticmethod
    def _confirmed(candidates, op, normalized_search, certifier_name):
        """Whether `op` is confirmed as this farm's entry: (bool, note code, its params when not)."""
        if not normalized_search or op.op_name_normalized != normalized_search:
            return False, "possible_name_similar", {}
        same_name = candidates.filter(op_name_normalized=normalized_search).count()
        if same_name != 1:
            return False, "possible_name_shared", {"same_name_count": same_name}
        if certifier_name:
            # Review of back #119: "WSDA" and "Washington State Department of Agriculture" are
            # the same agent. Resolve both through the exact crosswalk first; fall back to the
            # name comparison only when either side is not a known agent.
            from certifications.certifying_agents import agent_for_name

            ours_agent, theirs_agent = agent_for_name(certifier_name), agent_for_name(op.certifier_name or "")
            ours = USDAOrganicVerifier._normalize_name(certifier_name)
            theirs = USDAOrganicVerifier._normalize_name(op.certifier_name or "")
            if ours_agent is not None and theirs_agent is not None:
                same = ours_agent is theirs_agent
            else:
                same = bool(theirs) and (ours in theirs or theirs in ours)
            if not same:
                if not op.certifier_name:
                    return False, "possible_certifier_missing", {"farm_certifier": certifier_name}
                return (
                    False,
                    "possible_certifier_differs",
                    {"db_certifier": op.certifier_name, "farm_certifier": certifier_name},
                )
        return True, "", {}

    def health_check(self) -> bool:
        """Check if we have USDA data loaded."""
        try:
            from certifications.models import USDAOrganicOperation

            count = USDAOrganicOperation.objects.count()
            if count == 0:
                logger.warning("USDA Organic data not loaded. Run import_usda_organic_data.")
                return False
            return True
        except Exception:
            return False

    def _build_result(self, op, confidence: float) -> VerificationResult:
        """Convert a USDAOrganicOperation record to a VerificationResult."""
        status_lower = (op.status or "").lower()

        if status_lower == "certified":
            status = "verified"
        elif status_lower in ("surrendered", "revoked"):
            status = "revoked"
        elif status_lower == "suspended":
            status = "suspended"
        else:
            # Run 8: an unrecognised status is not evidence of certification.
            status = "self_reported"

        # Build scope string
        scopes = []
        if op.scope_crops:
            scopes.append(f"Crops: {op.scope_crops}")
        if op.scope_livestock:
            scopes.append(f"Livestock: {op.scope_livestock}")
        if op.scope_handling:
            scopes.append(f"Handling: {op.scope_handling}")
        if op.scope_wild_crops:
            scopes.append(f"Wild Crops: {op.scope_wild_crops}")

        # Parse certified products
        items = []
        if op.certified_products:
            items = [p.strip() for p in op.certified_products.split(",") if p.strip()]

        source_url = "https://organic.ams.usda.gov/integrity/"

        return VerificationResult(
            found=True,
            status=status,
            certifier_name=op.certifier_name or None,
            effective_date=op.status_effective_date or None,
            certification_scope=", ".join(scopes) if scopes else None,
            certified_items=items,
            source_url=source_url,
            raw_response={
                "op_name": op.op_name,
                "state": op.state,
                "status": op.status,
                "certifier": op.certifier_name,
                "snapshot_date": str(op.data_snapshot_date),
            },
            confidence_score=confidence,
            notes=render("matched", op_name=op.op_name, confidence=percent(confidence)),
        )

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a farm name for fuzzy matching."""
        name = name.lower().strip()
        name = re.sub(r"[^\w\s]", "", name)
        words = [w for w in name.split() if w not in STRIP_WORDS]
        return " ".join(words).strip()

    @staticmethod
    def _normalize_state_to_full(state: str) -> str:
        """Convert a state to full name (USDA uses full names)."""
        state = state.strip()
        if len(state) == 2:
            return US_STATE_NAMES.get(state.upper(), state)
        # Already full name
        return state

    @staticmethod
    def _normalize_state_to_abbrev(state: str) -> str:
        """Convert a state to 2-letter abbreviation."""
        state = state.strip()
        if len(state) == 2:
            return state.upper()
        return US_STATE_ABBREVS.get(state.lower(), state.upper()[:2])
