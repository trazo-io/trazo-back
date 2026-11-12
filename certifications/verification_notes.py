"""The notes the Organic Integrity Database check writes under a certificate, as codes.

WHY (settings audit leftover, 2026-11-12). `Certification.verification_notes` is English text
written by the verifier, and the app printed it as is, so a Spanish reader saw "Found 504 organic
operations in Oregon but none matched 'Test' above 90% confidence" under their certificate. The
carbon notes had the same problem and got a `note_code` (2026-11-09).

HOW. Every note is written from a template here, and the serializer reads the stored text back
into a code plus parameters with the same template. That covers notes already stored without a
data migration, and the app words the note in the reader's language from the code. English stays in
the database because the certifier-facing PDFs and the admin read it.

NEVER change a template's wording without keeping the old one parseable: stored notes were written
with it. `test_verification_notes.py` round-trips every template and pins the app's copy for each
code (`trazo-app/src/components/Certifications/__tests__/verificationNoteHasCopy.test.ts`).
"""

import re
from typing import Dict, Optional, Tuple

_SELF_REPORTED_TAIL = " The certification stays self-reported until the operator's own entry is confirmed."

TEMPLATES: Dict[str, str] = {
    "not_loaded": "Automatic check against the USDA Organic Integrity Database is not available yet.",
    "no_automated_check": "No automated verification available for this certification type",
    "no_operations_in_state": "No organic operations found in state '{state}'",
    "no_match": "Found {count} organic operations in {state} but none matched '{name}' above {threshold}% confidence",
    "matched": "Matched '{op_name}' with {confidence}% confidence",
    "possible_name_similar": (
        "Possible database entry '{op_name}' ({similarity}% name similarity); "
        "not confirmed: the names are similar, not the same." + _SELF_REPORTED_TAIL
    ),
    "possible_name_shared": (
        "Possible database entry '{op_name}' ({similarity}% name similarity); "
        "not confirmed: {same_name_count} operations in the state carry this name." + _SELF_REPORTED_TAIL
    ),
    "possible_certifier_differs": (
        "Possible database entry '{op_name}' ({similarity}% name similarity); "
        "not confirmed: the database lists certifier '{db_certifier}', the farm recorded '{farm_certifier}'."
        + _SELF_REPORTED_TAIL
    ),
    # Review of #406: the database row has no certifier. Its own code, so no English sentinel
    # ("none") travels as a parameter into a translated sentence.
    "possible_certifier_missing": (
        "Possible database entry '{op_name}' ({similarity}% name similarity); "
        "not confirmed: the database lists no certifier, the farm recorded '{farm_certifier}'." + _SELF_REPORTED_TAIL
    ),
}

_NUMERIC = {"count", "threshold", "confidence", "similarity", "same_name_count"}


def _pattern(template: str) -> "re.Pattern":
    parts = re.split(r"(\{[a-z_]+\})", template)
    out = []
    for part in parts:
        m = re.fullmatch(r"\{([a-z_]+)\}", part)
        if m:
            name = m.group(1)
            out.append(f"(?P<{name}>\\d+)" if name in _NUMERIC else f"(?P<{name}>.*?)")
        else:
            out.append(re.escape(part))
    return re.compile("^" + "".join(out) + "$", re.DOTALL)


_PATTERNS = {code: _pattern(t) for code, t in TEMPLATES.items()}


def render(code: str, **params) -> str:
    """The English note for `code`. Percentages are whole numbers (90, not 0.9)."""
    return TEMPLATES[code].format(**params)


def percent(fraction: float) -> int:
    return int(round(fraction * 100))


def parse(text: Optional[str]) -> Tuple[Optional[str], dict]:
    """(code, params) for a stored note, or (None, {}) for text no template wrote."""
    if not text:
        return None, {}
    text = text.strip()
    for code, pattern in _PATTERNS.items():
        m = pattern.match(text)
        if m:
            params = {k: int(v) if k in _NUMERIC else v for k, v in m.groupdict().items()}
            # Notes written before `possible_certifier_missing` existed said certifier 'none'.
            if code == "possible_certifier_differs" and params.get("db_certifier") == "none":
                params.pop("db_certifier")
                return "possible_certifier_missing", params
            return code, params
    return None, {}
