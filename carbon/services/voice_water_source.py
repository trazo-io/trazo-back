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

#: Words that name each source, accent-folded, in English, Spanish and Portuguese. A word counts when
#: a spoken word STARTS with it, so plurals and inflections match ("canals", "pozos", "reservatorio").
#: Portuguese "poço" is left out on purpose: folded it is "poco", Spanish for "a little" ("regamos un
#: poco"), and a cue that common would keep almost any well the model invented.
_CUES: dict[str, tuple[str, ...]] = {
    "river_stream": ("river", "stream", "creek", "rio", "arroyo", "quebrada", "riacho", "corrego", "ribeirao"),
    "irrigation_canal": ("canal", "ditch", "acequia", "lateral", "vala"),
    "pond_reservoir": (
        "pond",
        "reservoir",
        "estanque",
        "represa",
        "tranque",
        "embalse",
        "lagoa",
        "acude",
        "reservatorio",
    ),
    "well_groundwater": ("well", "groundwater", "borehole", "pozo", "perforacion", "subterrane", "artesian"),
    "municipal": (
        "municipal",
        "city water",
        "town water",
        "red publica",
        "agua potable",
        "rede publica",
        "agua da rua",
    ),
    "rainwater_harvesting": ("rainwater", "rain water", "cistern", "agua de lluvia", "cisterna", "agua da chuva"),
    "recycled_water": ("recycled", "reclaimed", "reciclad", "reutiliz", "reuso", "tratada"),
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
        folded = re.sub(rf"(?<![\w]){re.escape(name)}(?![\w])", " ", folded)
    return folded


def source_was_said(value: str, transcript: str, place_names: Iterable[str] = ()) -> bool:
    """True when a word for `value` appears in `transcript` outside the farm's place names."""
    cues = _CUES.get(value)
    if not cues:
        return False
    spoken = _without_place_names(_fold(transcript), place_names)
    words = re.findall(r"\w+", spoken)
    joined = " ".join(words)
    for cue in cues:
        if " " in cue:
            if re.search(rf"(?<!\w){re.escape(cue)}", joined):
                return True
        elif any(word.startswith(cue) for word in words):
            return True
    return False


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
