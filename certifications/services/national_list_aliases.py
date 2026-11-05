"""Curated crosswalk from what farmers actually write to canonical National List entries.

WHY THIS EXISTS
---------------
7 CFR 205.601/.602 is a legal document with legal names. Farmers write field shorthand. Importing
a real organic walnut season (2026-08-07) classified only 12 of 40 inputs, and four of the misses
were substances that ARE seeded and ARE listed:

    farmer wrote            seeded as                          result
    "Sulfur"                "Elemental sulfur"                 unclassified
    "Pheromone (codlemone)" "Pheromones"                       unclassified
    "Boron"                 "Soluble boron products"           unclassified
    "Zinc sulfate"          "Zinc/copper/iron/... (sulfates)"  unclassified

Sulfur and pheromones are two of the commonest organic orchard inputs, so the certifier packet was
saying "self-reported" exactly where it could have cited § 205.601.

WHY NOT JUST MATCH FUZZILY
--------------------------
Because the risk is asymmetric, and the list itself is built to defeat it.

A MISSED match costs value: the record still shows the input, the packet says "self-reported".
A WRONG match is a compliance hazard: it asserts a substance is allowed under organic rules, on a
document a certifier reads, when it may not be for that use.

The seeded list makes the trap concrete. "Soap" is FOUR separate listings that differ by use —
Soap-based algicide/demossers § (a), Soap-based herbicides § (b), Ammonium soaps § (d),
Insecticidal soaps § (e). "Copper sulfate" is three — algicide § (a), insecticide § (e),
fungicide § (i). A substring matcher picks one at random and cites the wrong subsection.

So this table is deliberately NOT a fuzzy matcher. It is a hand-checked, one-to-one mapping, and
a term that could mean more than one listing is recorded in AMBIGUOUS_NEVER_AUTO_RESOLVE instead
of being guessed at.

MAINTENANCE
-----------
* Every alias maps to a `substance_name` that must EXIST in the seeded table. The test suite
  asserts this — an alias pointing at a missing row is a silent no-op, which is the failure mode
  this module exists to prevent.
* Add an alias only after reading the CFR text for that subsection. The comment on each entry is
  the citation that justifies it.
* If a term is ambiguous, it belongs in AMBIGUOUS_NEVER_AUTO_RESOLVE, not here. Those are for the
  farmer to confirm, not for Trazo to decide — which is also the § 205.201(a) posture, where the
  producer asserts and Trazo assists.
"""

from __future__ import annotations

#: farmer's term (normalized) -> exact `NationalListSubstance.substance_name`
#:
#: Keys are matched after the same normalization the classifier uses, so write them lowercase and
#: without punctuation.
ALIASES: dict[str, str] = {
    # § 205.601(e)(6) elemental sulfur — insecticide/miticide; also (i)(9) plant disease and
    # (j)(2) as a soil amendment. A grower writing plain "sulfur" for a mite or mildew spray means
    # elemental sulfur; "lime sulfur" is a distinct listing and growers write it in full.
    "sulfur": "Elemental sulfur",
    "elemental sulphur": "Elemental sulfur",
    "sulphur": "Elemental sulfur",
    "micronized sulfur": "Elemental sulfur",
    "wettable sulfur": "Elemental sulfur",
    # § 205.601(f)(2) pheromones. "Pheromone traps" is a separate listing — a trap is a monitoring
    # device, not an application — so only the substance forms alias here.
    "pheromone": "Pheromones",
    "pheromone codlemone": "Pheromones",
    "codlemone": "Pheromones",
    "mating disruption": "Pheromones",
    "mating disruption pheromone": "Pheromones",
    # § 205.601(j)(7)(i) soluble boron products. Only one boron listing exists.
    "boron": "Soluble boron products",
    "soluble boron": "Soluble boron products",
    "borax": "Soluble boron products",
    "solubor": "Soluble boron products",
    # § 205.601(j)(7)(ii) micronutrient sulfates/carbonates/oxides/silicates. The one other zinc
    # listing, "Polyoxin D zinc salt", is a fungicide with a distinctive name nobody shortens to
    # "zinc sulfate".
    "zinc sulfate": "Zinc/copper/iron/manganese/molybdenum/selenium/cobalt "
    "(sulfates, carbonates, oxides, silicates)",
    "zinc sulphate": "Zinc/copper/iron/manganese/molybdenum/selenium/cobalt "
    "(sulfates, carbonates, oxides, silicates)",
    "manganese sulfate": "Zinc/copper/iron/manganese/molybdenum/selenium/cobalt "
    "(sulfates, carbonates, oxides, silicates)",
    "iron sulfate": "Zinc/copper/iron/manganese/molybdenum/selenium/cobalt "
    "(sulfates, carbonates, oxides, silicates)",
    # Microbial products (Bt): a nonsynthetic class, catalogued without a National List entry. The full binomial already
    # resolves through the classifier's reverse pass, but that pass requires >= 12 characters and a space — so the
    # shorthand every grower actually writes was blocked by the guard.
    "bt": "Microbial products (Bacillus thuringiensis, etc.)",
    "b t": "Microbial products (Bacillus thuringiensis, etc.)",
    "btk": "Microbial products (Bacillus thuringiensis, etc.)",
    "bacillus thuringiensis kurstaki": "Microbial products (Bacillus thuringiensis, etc.)",
    # 2026-08-21 — the SUBSPECIES forms. MEASURED, not assumed: the reverse pass needs the
    # farmer's text to be a substring of the listing, so a bare "Bacillus thuringiensis"
    # resolves and **"Bacillus thuringiensis subsp. kurstaki" does not** — appending the
    # subspecies, which is the precise and correct way to name the organism, made the entry
    # LESS placeable than the vague one. A grower writing the exact organism on their spray
    # record should not be the one who gets "Self-reported" in the packet.
    #
    # The subspecies matter agronomically (kurstaki is a caterpillar material and does
    # nothing to a beetle; tenebrionis is the potato-beetle one) and not at all to
    # the catalogue row, which names the class. So they all map to the class.
    "bacillus thuringiensis subsp kurstaki": "Microbial products (Bacillus thuringiensis, etc.)",
    "bacillus thuringiensis var kurstaki": "Microbial products (Bacillus thuringiensis, etc.)",
    "bt kurstaki": "Microbial products (Bacillus thuringiensis, etc.)",
    "bacillus thuringiensis subsp tenebrionis": "Microbial products (Bacillus thuringiensis, etc.)",
    "bacillus thuringiensis var tenebrionis": "Microbial products (Bacillus thuringiensis, etc.)",
    "bt tenebrionis": "Microbial products (Bacillus thuringiensis, etc.)",
    "bacillus thuringiensis subsp aizawai": "Microbial products (Bacillus thuringiensis, etc.)",
    "bt aizawai": "Microbial products (Bacillus thuringiensis, etc.)",
    "bacillus thuringiensis subsp israelensis": "Microbial products (Bacillus thuringiensis, etc.)",
    "bti": "Microbial products (Bacillus thuringiensis, etc.)",
    # § 205.601(e)(7) narrow range oils. Growers name them by season of use, not by the listing.
    "horticultural oil": "Horticultural oils",
    "hort oil": "Horticultural oils",
    "narrow range oil": "Horticultural oils",
    "dormant oil": "Horticultural oils",
    "summer oil": "Horticultural oils",
    "mineral oil": "Horticultural oils",
    # § 205.602(e) potassium chloride. "Muriate of potash" (MOP, 0-0-60) is the fertilizer trade name of
    # potassium chloride and nothing else; growers write it that way far more often than the chemical
    # name. Langbeinite ("sulfate of potash-magnesia", "K-Mag") is a different mined mineral and is
    # deliberately absent.
    "muriate of potash": "Potassium chloride",
    # § 205.601(j)(6) magnesium sulfate. Epsom salt is magnesium sulfate heptahydrate; WSDA annotates
    # every magnesium sulfate it lists "Deficiency must be documented", whatever its source.
    "epsom salt": "Magnesium sulfate",
    "epsom salts": "Magnesium sulfate",
    # Hydrogen peroxide is NOT here any more: it is two § 205.601 listings, (a) sanitizer and (i)
    # plant disease control, so its written forms are in AMBIGUOUS_NEVER_AUTO_RESOLVE below.
}


#: Terms that map to MORE THAN ONE listing, distinguished by use. Never auto-resolve these — the
#: farmer has to say which one, because the citation differs and a wrong subsection is a false
#: compliance claim. Kept as data rather than a comment so the test suite can assert that none of
#: them has quietly been added to ALIASES.
AMBIGUOUS_NEVER_AUTO_RESOLVE: dict[str, tuple[str, ...]] = {
    "soap": (
        "Soap-based algicide/demossers",
        "Soap-based herbicides",
        "Ammonium soaps",
        "Insecticidal soaps",
    ),
    "soaps": (
        "Soap-based algicide/demossers",
        "Soap-based herbicides",
        "Ammonium soaps",
        "Insecticidal soaps",
    ),
    # 2026-08-21 — the CHEMICAL name of a soap, which is why it looks like a safe alias and is
    # not. Potassium salts of fatty acids are the active in M-Pede (an insecticidal soap) AND
    # in the soap-based herbicides listed under a different subsection. Auto-resolving it would
    # pick a § citation for the operator; which one it is depends on what they sprayed it FOR,
    # and only they know that.
    "potassium salts of fatty acids": (
        "Soap-based herbicides",
        "Ammonium soaps",
        "Insecticidal soaps",
    ),
    "potassium salts of fatty acid": (
        "Soap-based herbicides",
        "Ammonium soaps",
        "Insecticidal soaps",
    ),
    "copper sulfate": (
        "Copper sulfate (algicide)",
        "Copper sulfate (insecticide)",
        "Copper sulfate (fungicide)",
    ),
    "copper": (
        "Copper sulfate (algicide)",
        "Copper sulfate (insecticide)",
        "Copper sulfate (fungicide)",
        "Copper hydroxide",
        "Copper oxide",
        "Copper oxychloride",
    ),
    "peracetic acid": (
        "Peracetic acid",
        "Peracetic acid (fire blight)",
    ),
    # § 205.601(a) algicide/disinfectant/sanitizer and § 205.601(i) plant disease control. These
    # used to auto-resolve to one row, under a comment citing (i)(5), while the row they reached
    # had been overwritten by whichever seed entry ran last.
    "hydrogen peroxide": (
        "Hydrogen peroxide",
        "Hydrogen peroxide (disease control)",
    ),
    "h2o2": (
        "Hydrogen peroxide",
        "Hydrogen peroxide (disease control)",
    ),
    "hydrogen dioxide": (
        "Hydrogen peroxide",
        "Hydrogen peroxide (disease control)",
    ),
}


def canonical_key(term: str | None) -> str:
    """Reduce a term to its lookup key: lowercase, punctuation dropped, whitespace collapsed.

    `omri_verifier._normalize` only lowercases, so "Pheromone (codlemone)" stayed
    "pheromone (codlemone)" and missed a table written in plain words. Farmers put the active
    ingredient in brackets constantly — it is how COG Pro's own demo data reads — so the
    parenthesised form has to reduce to the same key as the bare one.

    This only ever makes lookup MORE likely to hit the curated table. It cannot invent a match:
    a reduced term that is absent from both tables still returns None.
    """
    if not term:
        return ""
    out = []
    for ch in str(term).lower():
        out.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    return " ".join("".join(out).split())


# Both tables are written in natural form above; reduce once at import so lookup is a dict hit.
_ALIAS_INDEX: dict[str, str] = {canonical_key(k): v for k, v in ALIASES.items()}
_AMBIGUOUS_INDEX: frozenset = frozenset(canonical_key(k) for k in AMBIGUOUS_NEVER_AUTO_RESOLVE)


def resolve_alias(term: str | None) -> str | None:
    """Canonical `substance_name` for a farmer's term, or None.

    Returns None for anything ambiguous or unknown. None means "ask", not "prohibited" — the
    caller must not read a miss as a compliance judgement.
    """
    key = canonical_key(term)
    if not key or key in _AMBIGUOUS_INDEX:
        return None
    return _ALIAS_INDEX.get(key)
