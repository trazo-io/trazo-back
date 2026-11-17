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
from datetime import date

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


#: Where the § 205.601 annotations below were read: the eCFR versioner API, Title 7 up to date as of
#: 2026-11-03, fetched 2026-11-05. Compared with every eCFR version back to 2016-10-11: the words of
#: (i)(2), (i)(3) and (j)(6) are unchanged in all of them; (j)(7) took its wording from 83 FR 66559,
#: effective 2019-01-28 (it read "Soil deficiency must be documented by testing" before). The dash
#: after each name became an em dash on 2022-12-14; nothing else moved.
ANNOTATION_SOURCE = "eCFR 7 CFR 205.601, text current 2026-11-03"

_I2 = (
    "Coppers, fixed—copper hydroxide, copper oxide, copper oxychloride, includes products exempted from EPA "
    "tolerance, Provided, That, copper-based materials must be used in a manner that minimizes accumulation in the "
    "soil and shall not be used as herbicides."
)
_I3 = "Copper sulfate—Substance must be used in a manner that minimizes accumulation of copper in the soil."
_J6 = "Magnesium sulfate—allowed with a documented soil deficiency."
_J7 = (
    "Micronutrients—not to be used as a defoliant, herbicide, or desiccant. Those made from nitrates or chlorides "
    "are not allowed. Micronutrient deficiency must be documented by soil or tissue testing or other documented and "
    "verifiable method as approved by the certifying agent."
)

#: (section, catalogue row name) -> (the paragraph whose text this is, that paragraph verbatim).
#:
#: WHY (2026-11-05): the § 205.601 catalogue notes were paraphrases ("Minimize soil accumulation."),
#: and the boron row still carried the wording 83 FR 66559 replaced, so no § 205.601 note could be
#: printed as the rule's words. These are the § 205.601 rows whose condition a certifier's form asks
#: the grower to answer (WSDA AGR 2121 D4 and H5, OTCO C4 4.5-1, WSDA AGR 2196's restrictions
#: column). A row named here holds the rule's words; every other § 205.601 note stays descriptive and
#: is never offered as regulation text ("Per approved labeling." is a label term, not the rule).
#: The (j)(7)(i) and (ii) rows carry (j)(7)'s text: the annotation sits on (j)(7), not on its items.
ANNOTATIONS: dict[tuple[str, str], tuple[str, str]] = {
    ("205.601", "Copper hydroxide"): ("(i)(2)", _I2),
    ("205.601", "Copper oxide"): ("(i)(2)", _I2),
    ("205.601", "Copper oxychloride"): ("(i)(2)", _I2),
    ("205.601", "Copper sulfate (fungicide)"): ("(i)(3)", _I3),
    ("205.601", "Magnesium sulfate"): ("(j)(6)", _J6),
    ("205.601", "Soluble boron products"): ("(j)(7)", _J7),
    (
        "205.601",
        "Zinc/copper/iron/manganese/molybdenum/selenium/cobalt (sulfates, carbonates, oxides, silicates)",
    ): ("(j)(7)", _J7),
}

#: The paragraphs a certifier's restricted-materials questions turn on, verbatim, for printing beside
#: the grower's answer (`restricted_materials`). Same source as ANNOTATIONS; the § 205.602 text is
#: unchanged since 83 FR 66572 (2018-12-27). The § 205.601 introductory sentence is the one that
#: limits the (i) disease-control substances to when prevention is insufficient.
RULE_TEXT: dict[tuple[str, str], str] = {
    (
        "205.601",
        "introductory text",
    ): (
        "Substances allowed by this section, except disinfectants and sanitizers in paragraph (a) and those "
        "substances in paragraphs (c), (j), (k), (l), and (o) of this section, may only be used when the provisions "
        "set forth in § 205.206(a) through (d) prove insufficient to prevent or control the target pest."
    ),
    ("205.601", "(i)(2)"): _I2,
    ("205.601", "(i)(3)"): _I3,
    ("205.601", "(j)(6)"): _J6,
    ("205.601", "(j)(7)"): _J7,
    ("205.602", "(c)"): (
        "Calcium chloride, brine process is natural and prohibited for use except as a foliar spray to treat a "
        "physiological disorder associated with calcium uptake."
    ),
    ("205.602", "(e)"): (
        "Potassium chloride—unless derived from a mined source and applied in a manner that minimizes chloride "
        "accumulation in the soil."
    ),
    # Read from the eCFR versioner API, Title 7 issue of 2026-11-13 (2026-11-17); unchanged since 2019-01-28.
    ("205.602", "(h)"): (
        "Sodium nitrate—unless use is restricted to no more than 20% of the crop's total nitrogen requirement; use "
        "in spirulina production is unrestricted until October 21, 2005."
    ),
}

#: Where RULE_WORDS_601 was read: the eCFR versioner API, Title 7 issue of 2026-11-12, fetched
#: 2026-11-16. § 205.601 was last amended 2025-03-21, so this is the text ANNOTATION_SOURCE read too.
RULE_WORDS_SOURCE = "eCFR 7 CFR 205.601, Title 7 issue of 2026-11-12"

_A2 = (
    "Chlorine materials—For pre-harvest use, residual chlorine levels in the water in direct crop contact or as "
    "water from cleaning irrigation systems applied to soil must not exceed the maximum residual disinfectant limit "
    "under the Safe Drinking Water Act, except that chlorine products may be used in edible sprout production "
    "according to EPA label directions."
)
_SILICA = (
    "Aqueous potassium silicate (CAS #-1312-76-1)—the silica, used in the manufacture of potassium silicate, must be "
    "sourced from naturally occurring sand."
)

#: § 205.601 paragraph -> the words its entry carries beyond the substance's name, verbatim.
#:
#: WHY (2026-11-16, overall review OV-MT-C01): the input lookup and the buyer chip said "allowed" for
#: every § 205.601 hit, and most entries allow the substance only as their words say: zinc and boron
#: need a documented deficiency ((j)(7)), boric acid is for structural pest control with no contact
#: with crops ((e)(3)). The stored `restriction_notes` are paraphrases for all but the ANNOTATIONS
#: rows, so a surface that quotes the rule reads it from here.
#:
#: An item's words are its own; the words of the entry above it apply too ((a)(2) to every chlorine
#: material, (j)(7) to both micronutrient rows), and `rule_words` joins them parent first. Paragraph
#: headings ("(e) As insecticides") are uses, not words, and are left out. Entries whose words are only
#: a CAS number are left out.
RULE_WORDS_601: dict[str, str] = {
    "(a)(2)": _A2,
    "(a)(2)(iii)": "Hypochlorous acid—generated from electrolyzed water.",
    "(a)(2)(iv)": "Potassium hypochlorite—for use in water for irrigation purposes.",
    "(a)(3)": (
        "Copper sulfate—for use as an algicide in aquatic rice systems, is limited to one application per field "
        "during any 24-month period. Application rates are limited to those which do not increase baseline soil test "
        "values for copper over a timeframe agreed upon by the producer and accredited certifying agent."
    ),
    "(a)(5)": "Ozone gas—for use as an irrigation system cleaner only.",
    "(a)(6)": (
        "Peracetic acid—for use in disinfecting equipment, seed, and asexually propagated planting material. Also "
        "permitted in hydrogen peroxide formulations as allowed in § 205.601(a) at concentration of no more than 6% "
        "as indicated on the pesticide product label."
    ),
    "(a)(8)": (
        "Sodium carbonate peroxyhydrate (CAS #-15630-89-4)—Federal law restricts the use of this substance in food "
        "crop production to approved food uses identified on the product label."
    ),
    "(b)(1)": (
        "Herbicides, soap-based—for use in farmstead maintenance (roadways, ditches, right of ways, building "
        "perimeters) and ornamental crops."
    ),
    "(b)(2)(i)": "Newspaper or other recycled paper, without glossy or colored inks.",
    "(b)(2)(ii)": "Plastic mulch and covers (petroleum-based other than polyvinyl chloride (PVC)).",
    "(b)(2)(iii)": (
        "Biodegradable biobased mulch film as defined in § 205.2. Must be produced without organisms or feedstock "
        "derived from excluded methods."
    ),
    "(c)": "As compost feedstocks—Newspapers or other recycled paper, without glossy or colored inks.",
    "(d)": (
        "As animal repellents—Soaps, ammonium—for use as a large animal repellant only, no contact with soil or "
        "edible portion of crop."
    ),
    "(e)(1)": "Ammonium carbonate—for use as bait in insect traps only, no direct contact with crop or soil.",
    "(e)(2)": _SILICA,
    "(e)(3)": "Boric acid—structural pest control, no direct contact with organic food or crops.",
    "(e)(4)": (
        "Copper sulfate—for use as tadpole shrimp control in aquatic rice production, is limited to one application "
        "per field during any 24-month period. Application rates are limited to levels which do not increase baseline "
        "soil test values for copper over a timeframe agreed upon by the producer and accredited certifying agent."
    ),
    "(e)(6)": "Lime sulfur—including calcium polysulfide.",
    "(e)(7)": "Oils, horticultural—narrow range oils as dormant, suffocating, and summer oils.",
    "(e)(10)": "Sucrose octanoate esters (CAS #s—42922-74-7; 58064-47-4)—in accordance with approved labeling.",
    "(i)(1)": _SILICA,
    "(i)(2)": _I2,
    "(i)(3)": _I3,
    "(i)(7)": "Oils, horticultural, narrow range oils as dormant, suffocating, and summer oils.",
    "(i)(8)": (
        "Peracetic acid—for use to control fire blight bacteria. Also permitted in hydrogen peroxide formulations as "
        "allowed in § 205.601(i) at concentration of no more than 6% as indicated on the pesticide product label."
    ),
    "(j)(1)": (
        "Aquatic plant extracts (other than hydrolyzed)—Extraction process is limited to the use of potassium "
        "hydroxide or sodium hydroxide; solvent amount used is limited to that amount necessary for extraction."
    ),
    "(j)(3)": "Humic acids—naturally occurring deposits, water and alkali extracts only.",
    "(j)(4)": "Lignin sulfonate—chelating agent, dust suppressant.",
    "(j)(5)": (
        "Magnesium oxide (CAS # 1309-48-4)—for use only to control the viscosity of a clay suspension agent for "
        "humates."
    ),
    "(j)(6)": _J6,
    "(j)(7)": _J7,
    "(j)(8)": (
        "Liquid fish products—can be pH adjusted with sulfuric, citric or phosphoric acid. The amount of acid used "
        "shall not exceed the minimum needed to lower the pH to 3.5."
    ),
    "(j)(10)": (
        "Squid byproducts—from food waste processing only. Can be pH adjusted with sulfuric, citric, or phosphoric "
        "acid. The amount of acid used shall not exceed the minimum needed to lower the pH to 3.5."
    ),
    "(j)(11)": (
        "Sulfurous acid (CAS # 7782-99-2) for on-farm generation of substance utilizing 99% purity elemental sulfur "
        "per paragraph (j)(2) of this section."
    ),
    "(k)(1)": "Ethylene gas—for regulation of pineapple flowering.",
    "(k)(2)": "Fatty alcohols (C6, C8, C10, and/or C12)—for sucker control in organic tobacco production.",
    "(l)": "As floating agents in postharvest handling. Sodium silicate—for tree fruit and fiber processing.",
    "(m)(2)": "EPA List 3—Inerts of unknown toxicity—for use only in passive pheromone dispensers.",
    "(n)": "Seed preparations. Hydrogen chloride (CAS # 7647-01-0)—for delinting cotton seed for planting.",
    "(o)(1)": (
        "Microcrystalline cheesewax (CAS #'s 64742-42-3, 8009-03-08, and 8002-74-2)—for use in log grown mushroom "
        "production. Must be made without either ethylene-propylene co-polymer or synthetic colors."
    ),
    "(o)(2)": (
        "Paper-based crop planting aids as defined in § 205.2. Virgin or recycled paper without glossy paper or "
        "colored inks."
    ),
}

#: The § 205.601 paragraphs whose words limit HOW, WHERE or ON WHAT the substance may be used, or ask
#: for a record before it is used. A use can fall outside these, so no surface may call such a row plain
#: "allowed".
#:
#: Every other paragraph in RULE_WORDS_601 says what QUALIFIES as the substance, which the product
#: either is or is not: silica from sand ((e)(2), (i)(1)), papers without glossy inks ((b)(2)(i), (c),
#: (o)(2)), plastic other than PVC ((b)(2)(ii)), film without excluded methods ((b)(2)(iii)), electrolyzed
#: water ((a)(2)(iii)), "including calcium polysulfide" ((e)(6)), narrow range oils ((e)(7), (i)(7)), an
#: extraction method ((j)(1)), natural deposits ((j)(3)) and the acid that adjusts fish and squid pH
#: ((j)(8), (j)(10)). Those rows stay "allowed" and their words are still shown.
#:
#: Typed by paragraph, never read from the prose: the same rule as `NationalListSubstance.annotation_kind`.
USE_CONDITION_601: frozenset[str] = frozenset(
    {
        "(a)(2)",  # residual chlorine limit in water touching the crop
        "(a)(2)(iv)",  # irrigation water only
        "(a)(3)",  # aquatic rice algicide, one application per 24 months
        "(a)(5)",  # irrigation system cleaner only
        "(a)(6)",  # equipment, seed and planting material only
        "(a)(8)",  # the label's approved food uses only
        "(b)(1)",  # farmstead maintenance and ornamental crops only
        "(d)",  # large animal repellent, no contact with soil or crop
        "(e)(1)",  # trap bait only, no contact with crop or soil
        "(e)(3)",  # structural pest control, no contact with food or crops
        "(e)(4)",  # aquatic rice tadpole shrimp, one application per 24 months
        "(e)(10)",  # per approved labeling
        "(i)(2)",  # minimise copper in the soil; never as a herbicide
        "(i)(3)",  # minimise copper in the soil
        "(i)(8)",  # fire blight only
        "(j)(4)",  # chelating agent or dust suppressant
        "(j)(5)",  # clay suspension viscosity for humates only
        "(j)(6)",  # documented soil deficiency
        "(j)(7)",  # documented deficiency; not a defoliant, herbicide or desiccant
        "(j)(11)",  # on-farm generation from 99% sulfur
        "(k)(1)",  # pineapple flowering only
        "(k)(2)",  # tobacco sucker control only
        "(l)",  # tree fruit and fiber processing only
        "(m)(2)",  # passive pheromone dispensers only
        "(n)",  # cotton seed delinting only
        "(o)(1)",  # log-grown mushrooms only
    }
)

#: The date the text in force took effect, where Trazo knows it; None is unknown, never guessed.
ANNOTATION_EFFECTIVE: dict[str, date | None] = {
    "(i)(2)": None,
    "(i)(3)": None,
    "(j)(6)": None,
    "(j)(7)": date(2019, 1, 28),
}


def annotation_note(paragraph_text: str) -> str:
    """The condition as the catalogue stores it, first letter capitalised (the convention of the
    § 205.602 rows, migration 0039).

    The condition is the paragraph's proviso where it has one ("Provided, That, ..."): in (i)(2) the
    words between the name and the proviso list the forms the entry covers, which is not a condition
    (review of back #310). Otherwise it is everything after the substance's name."""
    if "Provided, That, " in paragraph_text:
        rest = paragraph_text.split("Provided, That, ", 1)[1].strip()
    else:
        rest = paragraph_text.split("—", 1)[1].strip()
    return rest[:1].upper() + rest[1:]


#: (section, catalogue row name) -> the note a row named in ANNOTATIONS stores in `restriction_notes`.
ANNOTATION_NOTES = {key: annotation_note(text) for key, (_, text) in ANNOTATIONS.items()}


def _key(name) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


_BY_KEY = {(section, _key(name)): paragraphs for (section, name), paragraphs in PARAGRAPHS.items()}
_ANNOTATION_BY_KEY = {(section, _key(name)): value for (section, name), value in ANNOTATIONS.items()}


def held_annotation(substance) -> tuple[str, str] | None:
    """(paragraph, note) when the substance's stored note is the rule's own annotation, else None.

    The stored note must still be the held text: a row edited since reads as not held."""
    found = _ANNOTATION_BY_KEY.get(
        (getattr(substance, "cfr_section", ""), _key(getattr(substance, "substance_name", "")))
    )
    if found is None:
        return None
    paragraph, text = found
    note = annotation_note(text)
    if (getattr(substance, "restriction_notes", None) or "").strip() != note:
        return None
    return paragraph, note


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


def citation_paragraphs(substance) -> str:
    """Every paragraph that lists the substance, without the uses: "§ 205.601(e)(6), (i)(6)". For a
    screen read in any language; "" when the table does not name the row."""
    found = paragraphs(substance)
    return f"§ {substance.cfr_section}{', '.join(found)}" if found else ""


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


def _chain(paragraph: str) -> list[str]:
    """The paragraph and the entries above it, outermost first: "(a)(2)(iv)" -> ["(a)", "(a)(2)",
    "(a)(2)(iv)"]."""
    parts = re.findall(r"\([^)]*\)", paragraph)
    return ["".join(parts[: i + 1]) for i in range(len(parts))]


def _words_for(paragraph: str) -> tuple[str, str] | None:
    """(the deepest paragraph whose words apply, the words joined parent first), or None."""
    held = [p for p in _chain(paragraph) if p in RULE_WORDS_601]
    if not held:
        return None
    return held[-1], " ".join(RULE_WORDS_601[p] for p in held)


def rule_words(substance) -> tuple[str, str] | None:
    """(paragraph, verbatim words) for a § 205.601 row whose entry carries words beyond its name.

    A row the rule lists under several paragraphs answers with the first that carries words; None for
    any other section, or a row PARAGRAPHS does not name."""
    if getattr(substance, "cfr_section", "") != "205.601":
        return None
    for paragraph in paragraphs(substance):
        found = _words_for(paragraph)
        if found:
            return found
    return None


def use_condition(substance) -> tuple[str, str] | None:
    """(paragraph, verbatim words) when the rule allows this § 205.601 row only under a condition of
    use (USE_CONDITION_601), else None. Rows whose words only say what qualifies as the substance
    answer None here and still answer `rule_words`."""
    if getattr(substance, "cfr_section", "") != "205.601":
        return None
    for paragraph in paragraphs(substance):
        if any(p in USE_CONDITION_601 for p in _chain(paragraph)):
            return _words_for(paragraph)
    return None
