"""A water source is offered only when the words name one, outside the farm's own place names.

WHY THIS EXISTS (2026-10-17, found filming the crew short)
----------------------------------------------------------
A real crew note, "Regamos River Block esta mañana, dos horas con el goteo", came back from the model
as `water_source: river_stream`. The crew said drip and named no source; "River" is part of the
parcel's NAME. The prompt already said "null if not mentioned", and the model still read the place
name as the answer, the same class as "North Ridge block" -> `block_id: "Ridge Block"` (2026-09-01):
a value that passes every catalogue check because it IS in the catalogue, chosen from words that
were about something else. Accepted, it would print a false water source into the certifier record
and feed the irrigation carbon factor (`verified_emission_factors.py`, `river_stream`).

So the model's answer is advice and this is the rule: keep `water_source` only if, once the farm's
own parcel, block and establishment names are taken out of the transcript, a word for THAT source is
still there. Otherwise the answer is null, which the confirmer fills in themselves. A missed source
costs one tap; an invented one is a false record.

`other` is never offered by the machine: it carries nothing the speaker said, and a model asked for
a field it has no evidence for reaches for the catch-all (the `protection_method: "other"` case).

The cue lists are deliberately the same in every language and checked together: crews mix languages
("regamos con agua del canal", "watered from the pozo"), and a Spanish note naming an English parcel
is exactly the case that broke.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

#: How each source is said, accent-folded, in English, Spanish and Portuguese. Three kinds of cue:
#:   "pozo*"      a stem: any spoken word starting with it ("pozos", "canals", "reservatorio");
#:   "wells"      an exact word;
#:   "well water" a phrase: those words in that order, separated by spaces only, so a cue never
#:                matches across a full stop ("...the rain. Water came...") or inside a word
#:                ("rain waterlogged").
#: Left out on purpose, each because an ordinary sentence would keep an invented source:
#:   bare "well"   "Well, we irrigated the north block" (English filler; review of #166);
#:   "poco"        Portuguese "poço" folded, which is Spanish for "a little" ("regamos un poco");
#:   "lateral"     a drip lateral is tubing, not a canal ("cambiamos un lateral de goteo");
#:   "tratada"     "semillas tratadas" are treated seed, and "agua tratada" is usually mains water.
_CUES: dict[str, tuple[str, ...]] = {
    "river_stream": (
        "river*",
        "stream*",
        "creek*",
        "rio",
        "rios",
        "arroyo*",
        "quebrada*",
        "riacho*",
        "corrego*",
        "ribeirao*",
    ),
    "irrigation_canal": ("canal*", "ditch*", "acequia*", "vala", "valas"),
    "pond_reservoir": (
        "pond",
        "ponds",
        "reservoir*",
        "estanque*",
        "represa*",
        "tranque*",
        "embalse*",
        "lagoa",
        "lagoas",
        "acude*",
        "reservatorio*",
    ),
    "well_groundwater": (
        "wells",
        "well water",
        "water well",
        "the well",
        "our well",
        "a well",
        "well pump",
        "groundwater",
        "aquifer*",
        "borehole*",
        "pozo*",
        "perforacion*",
        "subterrane*",
        "acuifer*",
        "artesian*",
    ),
    "municipal": (
        "municipal",
        "city water",
        "town water",
        "red publica",
        "agua potable",
        "rede publica",
        "agua da rua",
    ),
    "rainwater_harvesting": ("rainwater", "rain water", "cistern*", "agua de lluvia", "agua da chuva"),
    "recycled_water": ("recycled", "reclaimed", "reciclad*", "reutiliz*", "reuso"),
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _without_place_names(folded: str, place_names: Iterable[str]) -> str:
    """The transcript with every whole-word occurrence of the farm's own names blanked out.

    Longest name first, so "River Block East" goes before "River Block" can leave "East" behind.
    """
    names = sorted({_fold(n).strip() for n in place_names if n and n.strip()}, key=len, reverse=True)
    for name in names:
        folded = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " ", folded)
    return folded


def _cue_pattern(cue: str) -> str:
    if cue.endswith("*"):
        return rf"(?<!\w){re.escape(cue[:-1])}\w*"
    words = [re.escape(w) for w in cue.split()]
    return r"(?<!\w)" + r"[ \t]+".join(words) + r"(?!\w)"


def source_was_said(value: str, transcript: str, place_names: Iterable[str] = ()) -> bool:
    """True when a word for `value` appears in `transcript` outside the farm's place names."""
    cues = _CUES.get(value)
    if not cues:
        return False
    spoken = _without_place_names(_fold(transcript), place_names)
    return any(re.search(_cue_pattern(cue), spoken) for cue in cues)


def gate(result: dict, transcript: str, place_names: Iterable[str] = ()) -> dict:
    """Null out a `water_source` the words do not support, on the top level and in `activity_fields`."""
    if not isinstance(result, dict):
        return result
    names = list(place_names or ())
    if result.get("water_source") and not source_was_said(str(result["water_source"]), transcript, names):
        result["water_source"] = None
    fields = result.get("activity_fields")
    if isinstance(fields, dict) and fields.get("water_source"):
        if not source_was_said(str(fields["water_source"]), transcript, names):
            fields.pop("water_source")
    return result
