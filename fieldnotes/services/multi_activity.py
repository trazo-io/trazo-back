"""Does one crew message describe more than one job?

WHY THIS EXISTS. MEASURED 2026-10-19 over the labelled corpus: of six messages holding two
activities, the extractor flagged none. It returned the FIRST activity at confidence 90 with
`manual_review` false, and the second job vanished with nothing on any screen to say so. A crew
member who writes "we irrigated block 2 and then pruned block 3" has reported two records and
will reasonably assume both were filed.

⛔ THIS DECIDES NOTHING. It raises a caution on the inbox card and nothing else. The confirmer
still picks the activity, the block and the day, exactly as before. That is deliberate: the only
safe failure here is a caution nobody needed, and the only cost of a miss is today's behaviour.

WHY NOT THE EXTRACTOR. Asking the model costs a call per note at arrival, when most notes are
read minutes later and some never, and it would put a model's opinion on the card before a human
has seen the words. Counting families is deterministic, free, explainable to a farmer, and
reproducible in a test.

⚠️ NOT THE VOICE FALLBACK PARSER, and not a classifier. `carbon/services/ai_voice_processor.py`
holds a much larger keyword table used to BUILD a record when the model is unavailable, and crew
messages are deliberately never read by it (no negation guard, and the words are somebody else's).
This table is small and high-precision on purpose: its only question is "is there more than one
family of work in this sentence", and a word that cannot answer that is left out. `tractor`,
`bloque` and `horas` appear in both single-job and two-job messages, so they are absent.
"""

import re
import unicodedata

#: One entry per family of work, holding only words that NAME that work. Tuned against
#: `fieldnotes/corpus/crew_messages.json` and measured by `test_multi_activity.py`.
ACTIVITY_FAMILIES = {
    # "irrigated", never the stem "irrigat": "the irrigation pump" names the EQUIPMENT, not the
    # work, and the stem read "Replaced the filter on the irrigation pump" as two jobs.
    "irrigation": ["rega", "riego", "irrigated", "irrigating", "watered"],
    "fertilization": ["fertiliz", "urea", "compost", "estiercol", "manure", "abono"],
    "spray": ["fumig", "azufre", "sulfur", "cobre", "copper", "sprayed", "herbicid", "fungicid"],
    "pruning": ["poda", "prune", "pruned", "pruning"],
    "mowing": ["desbroz", "mow", "mowed", "mulching"],
    "harvest": ["cosech", "harvest", "picked", "shook", "pizca"],
    "cultivation": ["rastre", "arado", "cultivat", "weeded", "deshierb", "disced"],
    "equipment": ["limpiamos", "limpiar", "washed", "flushed", "lavamos", "replaced"],
    "transport": ["entregu", "hauled", "delivered", "descascaradora"],
    "thinning": ["rale", "thinned", "thinning"],
    "planting": ["sembr", "planted", "injert", "grafted", "transplant"],
    "frost": ["helada", "wind machine", "frost fan"],
    "pollination": ["colmena", "hive", "polinizac", "pollination"],
    "scouting": ["trampas", "traps", "scouted", "monitore"],
}

#: ⛔ WORDS DELIBERATELY ABSENT, each because it produced a false caution on the corpus:
#:
#:   aplicar / aplique / spray  a generic application verb. "Aplique compost" is fertilization and
#:                              "aplicamos azufre" is a spray, so the verb cannot tell them apart
#:                              and flagged four single-job messages as two.
#:   goteo / drip               an irrigation METHOD. "Flushed the drip lines" is one equipment
#:                              job; with `drip` present it read as equipment plus irrigation.
#:   tractor / horas / bloque   present in single-job and two-job messages alike.
#:
#: MEASURED on `crew_messages.json`, which is why these are named rather than guessed. `arado`
#: also had to stop matching inside `descascaradora`, hence the word boundary below.


def _fold(text):
    """Lowercase and strip accents, because a phone keyboard in a field produces both."""
    lowered = (text or "").lower()
    return "".join(c for c in unicodedata.normalize("NFD", lowered) if unicodedata.category(c) != "Mn")


def families_mentioned(text):
    """Every family of work this message names, as a sorted list.

    Matched at a WORD BOUNDARY, never as a bare substring. `arado` sits inside `descascaradora`,
    so a plain `in` read "I took the load to the huller" as ploughing plus transport and cautioned
    a single-job message. Needles are stems, so the boundary is on the left only: `rega` must
    still catch `regamos` and `regaron`.
    """
    folded = _fold(text)
    found = set()
    for family, needles in ACTIVITY_FAMILIES.items():
        for needle in needles:
            if re.search(r"\b" + re.escape(_fold(needle)), folded):
                found.add(family)
                break
    return sorted(found)


def mentions_multiple_activities(text):
    """True when the message names two or more families of work.

    ⚠️ TWO BLOCKS IS NOT TWO JOBS. "Took soil samples from block 2 and block 3" is one activity
    across two parcels and must not raise this: the confirmer logs it once. Only a second FAMILY
    counts, which is why this reads the work and never the conjunction.
    """
    return len(families_mentioned(text)) > 1
