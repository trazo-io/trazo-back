"""Does a spoken or typed field report deny what it describes? Three answers, never a guess.

WHY THIS EXISTS (OSP alignment audit 2026-10, T29 and AUDIT §8)
---------------------------------------------------------------
"No apliqué nada hoy" or "didn't spray the north block" must never become an application, and the
extraction model had no instruction about negation at all. Oscar's rule (2026-10-01): a message that
denies everything, or denies some actions or parcels and affirms others, is MANUAL REVIEW. Neither
case is read as "nothing happened" and neither gets values offered; the confirmer reads the message
and types what they decide.

    none   no negation found: the extraction stands as an offer, as before
    all    every clause with content is negated
    mixed  some clauses negated, some not ("aplicamos en el A pero no en el B")

This is a deliberately conservative word check, not a parser: a sentence with any negation in it
loses the machine offer. A false "mixed" costs the confirmer some typing; a missed negation would put
an application on the record that never happened.

A REASON is not an action (Astra activity-capture audit AC-07, 2026-10-26). "Did not spray today,
too windy" split on the comma, and "too windy" counted as an affirmed clause, so a plain no-spray
note was reported as "some things were done and some were not". An un-negated clause now counts as
affirmed only when it carries an action word (`_ACTION_STEMS` / `_ACTION_WORDS`) or a number (a
quantity, a row, a block). Anything else is the reason or the circumstance of the clause next to it.
This changes only which banner the confirmer reads (ALL instead of MIXED). The values are withheld
either way, and the guard still writes nothing.
"""

from __future__ import annotations

import re
import unicodedata

NONE = "none"
ALL = "all"
MIXED = "mixed"

#: Clause boundaries: punctuation and contrastive or additive conjunctions in en/es/pt.
_SPLIT = re.compile(
    r"[.;:!?\n]+|,|\b(?:but|and then|then|and|pero|sino|aunque|y luego|luego|mas|y|e|mas|porem|entao|depois)\b",
    re.IGNORECASE,
)

#: Negation words, whole words after accent folding. "n't" is caught separately.
_NEGATIONS = {
    # English
    "no",
    "not",
    "never",
    "nothing",
    "none",
    "without",
    "nobody",
    "cannot",
    # Spanish
    "nunca",
    "nada",
    "ningun",
    "ninguno",
    "ninguna",
    "sin",
    "jamas",
    "tampoco",
    # Portuguese
    "nao",
    "nenhum",
    "nenhuma",
    "sem",
}

#: Words that carry no action on their own, so a clause of only these is not "content".
_FILLER = {"today", "hoy", "hoje", "yesterday", "ayer", "ontem", "ok", "okay", "si", "sim", "yes", "also", "tambien"}

#: Word starts that name a field action in en/es/pt, after accent folding. Matched as prefixes so
#: one stem covers the tenses a crew actually types ("aplic" = aplique, aplicamos, aplicaron).
#: Erring wide is the safe side: a reason clause that happens to match only keeps the old MIXED.
_ACTION_STEMS = (
    # English
    "spray",
    "appl",
    "irrigat",
    "fertili",
    "prun",
    "harvest",
    "pick",
    "seed",
    "sow",
    "mow",
    "till",
    "plow",
    "disk",
    "cultivat",
    "spread",
    "haul",
    "deliver",
    "ship",
    "releas",
    "thinn",
    "graz",
    "mulch",
    "compost",
    "weed",
    "fumigat",
    "treat",
    "dust",
    "install",
    "placed",
    "scout",
    "inspect",
    "sampl",
    "fed",
    "feed",
    # Spanish
    "fumig",
    "aplic",
    "roci",
    "rega",
    "regu",
    "fertiliz",
    "abon",
    "poda",
    "cosech",
    "sembr",
    "siembr",
    "plantam",
    "plantar",
    "plante",
    "cort",
    "desbroz",
    "rastr",
    "cultiv",
    "esparc",
    "entreg",
    "carg",
    "liber",
    "rale",
    "pastore",
    "deshierb",
    "desmalez",
    "trat",
    "ech",
    "muestre",
    "revis",
    # Portuguese
    "pulveriz",
    "irrig",
    "adub",
    "colh",
    "semea",
    "roca",
    "carreg",
    "levei",
    "levamos",
)

#: Short action words that are too ambiguous as prefixes.
#: "water" and "plant" are here as whole words, not stems, because "too much water" and "the plants
#: were wet" are reasons.
_ACTION_WORDS = {
    "ran",
    "run",
    "put",
    "used",
    "use",
    "added",
    "add",
    "laid",
    "watered",
    "watering",
    "planted",
    "planting",
    "puse",
    "pusimos",
    "pusieron",
}


def _fold(text: str) -> str:
    # Phone keyboards and WhatsApp send the typographic apostrophe (U+2019), which has no Unicode
    # decomposition: "didn’t" would split into "didn" + "t" and slip past the check (review of #88).
    text = (text or "").replace("\u2019", "'").replace("\u2018", "'").replace("\u02bc", "'")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _carries_an_action(clause: str, words: list[str]) -> bool:
    """True when an un-negated clause reports something done, not the reason for not doing it."""
    if re.search(r"\d", clause):
        return True
    return any(w in _ACTION_WORDS or w.startswith(_ACTION_STEMS) for w in words)


def classify(text: str, language: str = "") -> str:
    """NONE, ALL or MIXED for `text`, in any of English, Spanish and Portuguese.

    In Portuguese "no" is a contraction ("no talhão", in the field), not a negation, so it is only a
    negation word when the message is not Portuguese.
    """
    negations = _NEGATIONS - {"no"} if (language or "").lower().startswith("pt") else _NEGATIONS
    folded = _fold(text)
    negated = affirmed = 0
    for clause in _SPLIT.split(folded):
        if not clause:
            continue
        words = re.findall(r"[a-z']+", clause)
        content = [w for w in words if w not in _FILLER]
        if not content:
            continue
        is_negated = any(w in negations for w in words) or any(w.endswith("n't") for w in words)
        if is_negated:
            negated += 1
        elif _carries_an_action(clause, words):
            affirmed += 1
    if not negated:
        return NONE
    return MIXED if affirmed else ALL


#: Result keys that carry extracted values. All cleared when the message is not NONE.
_VALUE_KEYS_LIST = ("detected_amounts", "detected_products", "detected_systems")
_VALUE_KEYS_SCALAR = (
    "npk_ratio",
    "concentration",
    "commercial_name",
    "application_method",
    "water_source",
    "irrigation_method",
    "area_covered",
    "duration",
    "fuel_amount",
)


def guard(result: dict, transcript: str, language: str = "") -> dict:
    """Withhold every extracted value when the message negates anything. Returns `result`."""
    state = classify(transcript, language)
    result["negation"] = state
    if state == NONE:
        result.setdefault("manual_review", False)
        return result
    for key in _VALUE_KEYS_LIST:
        result[key] = []
    for key in _VALUE_KEYS_SCALAR:
        if key in result:
            result[key] = None
    result["activity_fields"] = {}
    # The model's own sentence about the activity and its guess of the activity go too: on a message
    # that denies the work, both describe something that may not have happened (review of #88).
    result["description"] = ""
    result["type"] = ""
    result["manual_review"] = True
    result["manual_review_reason"] = (
        "The message denies what it describes."
        if state == ALL
        else "The message says some things were done and some were not."
    )
    # The model's guess of the activity is withheld too: switching the form on a negated
    # message would be acting on it.
    result["type_withheld"] = True
    return result
