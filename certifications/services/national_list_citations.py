"""
Where 7 CFR lists each substance in Trazo's National List catalogue, to the paragraph.

Read from the eCFR text of 7 CFR 205.601, 205.602 and 205.605(b), current as of 2026-11-02 (the
sections were last amended 2025-03-21). Keyed by the catalogue's own row name, not matched by text,
so a row the table does not name is reported (`test_national_list_citations`), never guessed.

WHY (2026-11-04): every National List line in the certifier packet printed a bare "§ 205.601", and
the catalogue's one stored letter per substance was wrong for several: elemental sulfur is listed in
§ 205.601(e)(5), (h)(2), (i)(10) and (j)(2), and the catalogue filed it under (e) alone, so sulfur
applied as a soil amendment would have been cited as an insecticide. "Pheromone traps" was filed
under (e); the rule lists pheromones in (f). A WSDA reviewer read of the specimen packet asked for
the paragraph, and the paragraph is only right when it comes from the rule.

Two readings:
  * `citation_letter` -- "§ 205.601(e)" when the rule lists the substance under one lettered
    paragraph, else the bare section. This is what `NationalListSubstance.citation` returns, and it
    stays inside the set of citations the buyer page accepts.
  * `citation_with_uses` -- every paragraph with the use the rule lists it under, for the
    certifier's materials list: "§ 205.601(e)(5) insecticide, (h)(2) slug or snail bait, ...".
"""

from __future__ import annotations

import re

SOURCE = "eCFR 7 CFR 205.601, 205.602 and 205.605(b), text current 2026-11-02, last amended 2025-03-21"

#: § 205.601 paragraph letter -> the use the rule lists under it, shortened from the rule's own
#: heading ("(e) As insecticides (including acaricides or mite control)").
USES_601 = {
    "a": "algicide, disinfectant or sanitizer",
    "b": "herbicide or weed barrier",
    "c": "compost feedstock",
    "d": "animal repellent",
    "e": "insecticide",
    "f": "insect management",
    "g": "rodenticide",
    "h": "slug or snail bait",
    "i": "crop disease control",
    "j": "crop or soil amendment",
    "k": "plant growth regulator",
    "l": "floating agent in postharvest handling",
    "m": "synthetic inert ingredient",
    "n": "seed preparation",
    "o": "production aid",
}

#: (section, catalogue row name) -> the paragraphs that list it. Where the catalogue splits one
#: substance into rows by use ("Copper sulfate (algicide)", "... (insecticide)", "... (fungicide)";
#: "Hydrogen peroxide" and "Hydrogen peroxide (disease control)"), each row carries its own use's
#: paragraph. Where it keeps one row, the row carries every paragraph the rule lists it under.
PARAGRAPHS: dict[tuple[str, str], tuple[str, ...]] = {
    # § 205.601(a) algicides, disinfectants and sanitizers
    ("205.601", "Ethanol"): ("(a)(1)(i)",),
    ("205.601", "Isopropanol"): ("(a)(1)(ii)",),
    ("205.601", "Calcium hypochlorite"): ("(a)(2)(i)",),
    ("205.601", "Chlorine dioxide"): ("(a)(2)(ii)",),
    ("205.601", "Hypochlorous acid (from electrolyzed water)"): ("(a)(2)(iii)",),
    ("205.601", "Potassium hypochlorite"): ("(a)(2)(iv)",),
    ("205.601", "Sodium hypochlorite"): ("(a)(2)(v)",),
    ("205.601", "Copper sulfate (algicide)"): ("(a)(3)",),
    ("205.601", "Hydrogen peroxide"): ("(a)(4)",),
    ("205.601", "Ozone gas"): ("(a)(5)",),
    ("205.601", "Peracetic acid"): ("(a)(6)",),
    ("205.601", "Soap-based algicide/demossers"): ("(a)(7)",),
    ("205.601", "Sodium carbonate peroxyhydrate"): ("(a)(8)",),
    # (b) herbicides and weed barriers
    ("205.601", "Soap-based herbicides"): ("(b)(1)",),
    ("205.601", "Newspaper or recycled paper mulch"): ("(b)(2)(i)",),
    ("205.601", "Plastic mulch (petroleum-based, non-PVC)"): ("(b)(2)(ii)",),
    ("205.601", "Biodegradable biobased mulch film"): ("(b)(2)(iii)",),
    # (c) compost feedstocks, (d) animal repellents
    ("205.601", "Newspaper or recycled paper"): ("(c)",),
    ("205.601", "Ammonium soaps"): ("(d)",),
    # (e) insecticides
    ("205.601", "Ammonium carbonate"): ("(e)(1)",),
    ("205.601", "Aqueous potassium silicate"): ("(e)(2)", "(i)(1)"),
    ("205.601", "Boric acid"): ("(e)(3)",),
    ("205.601", "Copper sulfate (insecticide)"): ("(e)(4)",),
    ("205.601", "Elemental sulfur"): ("(e)(5)", "(h)(2)", "(i)(10)", "(j)(2)"),
    ("205.601", "Lime sulfur"): ("(e)(6)", "(i)(6)"),
    ("205.601", "Horticultural oils"): ("(e)(7)", "(i)(7)"),
    ("205.601", "Insecticidal soaps"): ("(e)(8)",),
    ("205.601", "Sticky traps/barriers"): ("(e)(9)",),
    ("205.601", "Sucrose octanoate esters"): ("(e)(10)",),
    # The catalogue filed this row under (e); the rule lists pheromones under (f) only.
    ("205.601", "Pheromone traps"): ("(f)",),
    # (f) insect management, (g) rodenticides, (h) slug or snail bait
    ("205.601", "Pheromones"): ("(f)",),
    ("205.601", "Vitamin D3"): ("(g)",),
    ("205.601", "Ferric phosphate"): ("(h)(1)",),
    # (i) crop disease control
    ("205.601", "Copper hydroxide"): ("(i)(2)",),
    ("205.601", "Copper oxide"): ("(i)(2)",),
    ("205.601", "Copper oxychloride"): ("(i)(2)",),
    ("205.601", "Copper sulfate (fungicide)"): ("(i)(3)",),
    ("205.601", "Hydrated lime"): ("(i)(4)",),
    ("205.601", "Hydrogen peroxide (disease control)"): ("(i)(5)",),
    ("205.601", "Peracetic acid (fire blight)"): ("(i)(8)",),
    ("205.601", "Potassium bicarbonate"): ("(i)(9)",),
    ("205.601", "Polyoxin D zinc salt"): ("(i)(11)",),
    # (j) crop or soil amendments
    ("205.601", "Aquatic plant extracts (non-hydrolyzed)"): ("(j)(1)",),
    ("205.601", "Humic acids"): ("(j)(3)",),
    ("205.601", "Lignin sulfonate"): ("(j)(4)",),
    ("205.601", "Magnesium oxide"): ("(j)(5)",),
    ("205.601", "Magnesium sulfate"): ("(j)(6)",),
    ("205.601", "Soluble boron products"): ("(j)(7)(i)",),
    (
        "205.601",
        "Zinc/copper/iron/manganese/molybdenum/selenium/cobalt (sulfates, carbonates, oxides, silicates)",
    ): ("(j)(7)(ii)",),
    ("205.601", "Liquid fish products"): ("(j)(8)",),
    ("205.601", "Vitamins C and E"): ("(j)(9)",),
    ("205.601", "Squid byproducts"): ("(j)(10)",),
    ("205.601", "Sulfurous acid"): ("(j)(11)",),
    # (k) plant growth regulators, (l) floating agents, (m) inerts, (n) seed, (o) production aids
    ("205.601", "Ethylene gas"): ("(k)(1)",),
    ("205.601", "Fatty alcohols (C6, C8, C10, C12)"): ("(k)(2)",),
    ("205.601", "Sodium silicate"): ("(l)",),
    ("205.601", "EPA List 4 inerts (Minimal Concern)"): ("(m)(1)",),
    ("205.601", "EPA List 3 inerts (Unknown Toxicity)"): ("(m)(2)",),
    ("205.601", "Hydrogen chloride"): ("(n)",),
    ("205.601", "Microcrystalline cheesewax"): ("(o)(1)",),
    ("205.601", "Paper-based crop planting aids"): ("(o)(2)",),
    # § 205.602 nonsynthetics prohibited in crop production
    ("205.602", "Ash from manure burning"): ("(a)",),
    ("205.602", "Arsenic"): ("(b)",),
    ("205.602", "Calcium chloride (brine process)"): ("(c)",),
    ("205.602", "Lead salts"): ("(d)",),
    ("205.602", "Potassium chloride"): ("(e)",),
    ("205.602", "Rotenone"): ("(f)",),
    ("205.602", "Sodium fluoaluminate (mined)"): ("(g)",),
    ("205.602", "Sodium nitrate"): ("(h)",),
    ("205.602", "Strychnine"): ("(i)",),
    ("205.602", "Tobacco dust (nicotine sulfate)"): ("(j)",),
    # § 205.605(b) synthetics allowed in handling: the post-harvest sanitizers
    ("205.605", "Acidified sodium chlorite"): ("(b)(1)",),
    ("205.605", "Calcium hypochlorite"): ("(b)(12)(i)",),
    ("205.605", "Chlorine dioxide"): ("(b)(12)(ii)",),
    ("205.605", "Hypochlorous acid (generated from electrolyzed water)"): ("(b)(12)(iii)",),
    ("205.605", "Sodium hypochlorite"): ("(b)(12)(iv)",),
    ("205.605", "Hydrogen peroxide"): ("(b)(17)",),
    ("205.605", "Ozone"): ("(b)(21)",),
    ("205.605", "Peracetic acid/Peroxyacetic acid"): ("(b)(22)",),
}


def _key(name) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


_BY_KEY = {(section, _key(name)): paragraphs for (section, name), paragraphs in PARAGRAPHS.items()}


def paragraphs(substance) -> tuple[str, ...]:
    """The paragraphs of the substance's section that list it, or () when the table does not name
    the row."""
    return _BY_KEY.get((getattr(substance, "cfr_section", ""), _key(getattr(substance, "substance_name", ""))), ())


def citation_letter(substance) -> str | None:
    """ "§ 205.601(e)" when the rule lists the substance under one lettered paragraph, "§ 205.601"
    when under several. None when the table does not name the row, so the caller keeps its own."""
    found = paragraphs(substance)
    if not found:
        return None
    letters = {p[1] for p in found}
    section = substance.cfr_section
    return f"§ {section}({letters.pop()})" if len(letters) == 1 else f"§ {section}"


def citation_with_uses(substance) -> str:
    """Every paragraph that lists the substance, each with the use the rule lists it under:
    "§ 205.601(e)(5) insecticide, (h)(2) slug or snail bait, (i)(10) crop disease control, (j)(2)
    crop or soil amendment". "" when the table does not name the row."""
    found = paragraphs(substance)
    if not found:
        return ""
    section = substance.cfr_section
    parts = []
    for paragraph in found:
        use = USES_601.get(paragraph[1], "") if section == "205.601" else ""
        parts.append(f"{paragraph} {use}" if use else paragraph)
    return f"§ {section}{', '.join(parts)}"
