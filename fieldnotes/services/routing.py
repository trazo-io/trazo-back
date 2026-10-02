"""Which form a crew note should open: a ROUTING HINT for the inbox, never a classification.

OSP alignment audit 2026-10, T29, Oscar's boundary (2026-10-01): a note that mentions an application
is logged through the application form, by the confirmer, and stays waiting until that form saves.
This hint only decides which button the inbox shows. The rule that keeps machine values off an
application follows the record's selected type on the server (`confirmation.is_application`), so a
note this list misses is still protected once the confirmer picks an application.
"""

from __future__ import annotations

import re
import unicodedata

APPLICATION = "application"

#: Word stems, matched at the start of a word after accent folding. Published so a reviewer can see
#: exactly what routes a note, in English, Spanish and Portuguese. Ambiguous stems are left out on
#: purpose: "lime" is also a fruit and "roci" also matches "rocio" (dew).
APPLICATION_STEMS = (
    # English
    "spray",
    "applied",
    "apply",
    "applying",
    "herbicid",
    "fungicid",
    "insecticid",
    "pesticid",
    "fertiliz",
    "fertilis",
    "fumigat",
    # Spanish
    "aplic",
    "apliq",
    "fumig",
    "rocie",
    "rociamos",
    "rociar",
    "rociad",
    "asperj",
    "herbicid",
    "fungicid",
    "insecticid",
    "plaguicid",
    "fertiliz",
    "abon",
    # Portuguese
    "pulveriz",
    "apliquei",
    "aplicamos",
    "adub",
    "defensiv",
    "agrotox",
)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def suggested_route(words: str) -> str:
    """APPLICATION when the message mentions applying a material, else ""."""
    folded = " " + _fold(words) + " "
    for stem in APPLICATION_STEMS:
        if re.search(r"(?<![a-z])" + re.escape(stem), folded):
            return APPLICATION
    return ""
