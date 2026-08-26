"""
Consumer-page privacy helpers (Phase 3).

Single source of truth for parcel-location disclosure gating, used by both
the transparency endpoint (_build_public_parcel) and PublicParcelSerializer —
one policy, two payload shapes.
"""

import re

# Free-text establishment fields a farmer (or a seed script) can type anything into, and which
# ship on the ANONYMOUS consumer payload. 7 of 20 published productions were publishing:
#     "ROI Analysis: Annual Revenue: $18,200,000, Sustainability Investment: $2,730,000,
#      Premium Revenue: $6,370,000, ROI: 133.3%"
#     "...generating $18.2M annually with 45% premium pricing through verified
#      carbon-negative practices."
# That is the farm's P&L on a shopper's phone, and the copy is independently a problem:
# "premium pricing" and "verified carbon-negative" are both on the UNSAFE list in
# compliance.md (FTC 16 CFR 260.6).
#
# Redact rather than drop: the surrounding sentence is the grower's own marketing and is
# legitimately public — only the money and the unsupportable claims come out. Redaction is
# visible on purpose, so a grower who reads their own page can see why.
FINANCIAL_PATTERNS = [
    # $18,200,000 / $18.2M / $2.73 million
    re.compile(r"\$\s?\d[\d,\.]*\s*(?:[MmKkBb]\b|million|billion|thousand)?"),
    # "ROI: 133.3%", "ROI Analysis: ...", "Annual Revenue: ...", "Premium Revenue: ..."
    # The `[^.;]*` run stops at the decimal POINT, so "ROI: 133.3%" left a literal ".3%"
    # rendered to shoppers — a surviving fragment of the very figure being redacted.
    # The trailing group consumes the decimal tail.
    re.compile(r"\b(?:ROI|Return on Investment)\b[^.;]*(?:\.\d+\s*%?)?", re.IGNORECASE),
    re.compile(r"\b(?:annual|premium|gross|net)\s+revenue\b[^.;]*", re.IGNORECASE),
    re.compile(r"\bsustainability investment\b[^.;]*", re.IGNORECASE),
    # Unsupportable market/eco claims (compliance.md UNSAFE column)
    re.compile(r"\b\d+%\s*premium\s*pric\w*", re.IGNORECASE),
    re.compile(r"\bpremium pricing\b", re.IGNORECASE),
    re.compile(r"\bcarbon[- ]negative\b", re.IGNORECASE),
]

# Verification claims are handled SEPARATELY from financials because they must be
# NEGATION-AWARE — see `public_free_text`.
VERIFICATION_PATTERNS = [
    re.compile(r"\bblockchain[- ]?verif\w*[^.;,]*", re.IGNORECASE),
    # "USDA verified/certified" may only be claimed for an Organic Integrity Database match,
    # which this free-text field can never establish.
    re.compile(r"\bUSDA[- ](?:verified|certified)\b[^.;,]*", re.IGNORECASE),
    re.compile(r"\bthird[- ]party[- ]verif\w*[^.;,]*", re.IGNORECASE),
    # Bare "verified …", not just the specific pairings. Pattern ORDER matters: the
    # carbon-negative rule above rewrites "Verified carbon negative operations" into
    # "Verified operations", which a narrower `verified\s+(carbon|organic|…)` rule no longer
    # matches — the claim survived precisely because an earlier redaction had fired.
    # This field is farmer free text; it can never establish the USDA Organic Integrity
    # Database match that compliance.md requires before claiming verification.
    re.compile(r"\bverified\b[^.;,]*", re.IGNORECASE),
    re.compile(r"\bcertified\s+by\s+trazo\b[^.;,]*", re.IGNORECASE),
    # A CERT-SHAPED LABEL IS A CLAIM REGARDLESS OF WORD ORDER.
    #
    # Every rule above keys on a VERB ("verified", "certified by"), or on the exact
    # adjacency "USDA certified". Real farmer input is a NOUN PHRASE, and the adjacency
    # rule requires certified/verified immediately after USDA — so "USDA Organic
    # Certified" (the word "Organic" intervenes), "Certified Organic" and "Real Organic
    # Project Certified" all cleared the whole list untouched. Three demo seeders
    # shipped exactly those strings to shoppers.
    #
    # These stay in force even though the one production caller
    # (transparency_views.py's sustainability_practices) has been withdrawn: the
    # helper still guards `about`, `main_activities`, `location_highlights` and
    # `custom_message`, where a farmer can type the same claim in prose.
    # The trailing optional parenthetical consumes the certifier the farmer names in
    # brackets — "USDA Organic Certified (CCOF)" otherwise redacted down to a bare
    # "(CCOF)", which still puts an accrediting body's name on a shopper's screen.
    re.compile(r"\b(?:USDA|NOP)\b[^.;,]*\bcertifi\w*(?:\s*\([^)]*\))?", re.IGNORECASE),
    re.compile(r"\bcertifi\w+\s+organic\b[^.;,]*(?:\s*\([^)]*\))?", re.IGNORECASE),
    re.compile(r"\borganic\s+certifi\w+\b[^.;,]*(?:\s*\([^)]*\))?", re.IGNORECASE),
    # Named third-party schemes a free-text field cannot substantiate. Trazo holds no
    # licence to display these marks, and a database cross-reference exists only for
    # USDA Organic (see cert_logo_usage_standards).
    re.compile(
        r"\b(?:Real Organic Project|Rainforest Alliance|Fair Trade|Non-GMO Project|"
        r"GlobalG\.?A\.?P\.?|CCOF)\b[^.;,]*\bcertifi\w*(?:\s*\([^)]*\))?",
        re.IGNORECASE,
    ),
]


# A NEGATED mention is a DISCLAIMER, not a claim. "Practices are not independently verified"
# is honest disclosure — stripping the verb left "Practices are not independently", turning a
# useful disclaimer into a fragment. Mirrors the same rule in the cross-surface claim detector
# (`history/tests/test_cross_surface_claim_safety.py`); the two must stay consistent, or the
# sanitiser and the test that polices it will disagree about what a claim even is.
_NEGATION_WINDOW = 32
# Allows intervening words ("not INDEPENDENTLY verified", "not THIRD-PARTY verified") but
# never crosses a sentence boundary — otherwise "We do not spray. Verified organic." would
# read the earlier "not" as negating a fresh claim.
_NEGATION_RE = re.compile(r"\b(?:not|no|never|without|isn't|is not)\b[^.;!?]{0,24}$", re.IGNORECASE)


def _strip_unless_negated(text, pattern):
    """Remove pattern matches, leaving negated (disclaimer) mentions intact."""

    def replace(match):
        preceding = text[max(0, match.start() - _NEGATION_WINDOW) : match.start()]
        preceding = re.sub(r"[\"'\s,:;\-]+$", " ", preceding)
        return match.group(0) if _NEGATION_RE.search(preceding) else ""

    return pattern.sub(replace, text)


#: Fields whose value names a commercial counterparty that is DELIBERATELY WITHHELD from the
#: anonymous payload. `redact_own_vendor_names` removes those same names from free text on the
#: SAME event, so withholding the column is not defeated by the grower's own prose.
#:
#: Scoped to exactly the two supplier fields the serializer already strips as commercially
#: sensitive. `manufacturer` is deliberately NOT here: an input's maker is legitimate public
#: product information (the consumer card names the product itself), so redacting it out of a
#: description would mangle honest copy to protect something that was never withheld.
#: `applicator_name` is a PERSON and is certifier-only, but "[supplier withheld]" is the wrong
#: label for a human name — that needs its own treatment, not this one.
#: 2026-08-25: widened to the other two vendor columns the anonymous payload withholds.
#: `beneficial_supplier` (pest BR events) and `amendment_supplier_name` (soil) were stripped
#: as fields while the same names could ride out in the event's own prose — and the pest,
#: general and business descriptions were not routed through the redactor at all.
VENDOR_NAME_FIELDS = (
    "seed_supplier_name",
    "supplier_name",
    "beneficial_supplier",
    "amendment_supplier_name",
)

#: Words that are far too common in farm prose to use as a vendor match on their own. Without
#: this, a supplier stored as "Organic Seeds Inc" reduces to the stem "Organic" and redacts the
#: word out of every sentence on the card — "Certified [supplier withheld] planting stock".
_VENDOR_STEM_STOPWORDS = frozenset(
    {
        "organic",
        "certified",
        "natural",
        "valley",
        "green",
        "sun",
        "west",
        "north",
        "south",
        "east",
        "coast",
        "hill",
        "hills",
        "creek",
        "river",
        "premium",
        "quality",
        "family",
        "heritage",
        "pacific",
        "california",
        "american",
        "national",
        "united",
        "tree",
        "trees",
        "plant",
        "plants",
        "crop",
        "crops",
        "agri",
        "agro",
    }
)

#: Corporate suffixes to shed when deriving the distinctive part of a vendor name, so that a
#: stored "Brokaw Nursery, Saticoy CA" also matches a prose mention of "Brokaw Nursery" or
#: "Brokaw". Order matters: longest first.
_VENDOR_NOISE = re.compile(
    r"(?i),.*$|\b(inc|llc|ltd|co|corp|company|nursery|nurseries|seeds?|supply|farms?|ranch|"
    r"orchards?|growers?|brothers|bros)\b\.?",
)

_REDACTED = "[supplier withheld]"


def redact_own_vendor_names(text, event):
    """Remove the vendors named on THIS event from a public free-text string.

    🔴 2026-08-15, measured on the live anonymous endpoint. `seed_supplier_name` was correctly
    stripped from the payload — and the same nursery was published verbatim inside
    `description`:

        seed_supplier_name : (stripped)
        description        : "Ordered and received organic Hass avocado nursery stock from
                              Saticoy Grove Nursery for replanting 28 trees..."

    The regression test that guards this passed throughout, because it asserted the absence of
    the FULL stored string ("Brokaw Nursery, Saticoy CA") while the prose named the vendor
    without the city. Withholding a column means nothing if the same fact rides out in the
    sentence beside it.

    Scoped deliberately to names the operator already recorded on this event: a general-purpose
    company-name detector would redact crop varieties, place names and the farm's own brand.
    """
    if not isinstance(text, str) or not text:
        return text
    for field_name in VENDOR_NAME_FIELDS:
        raw = getattr(event, field_name, None)
        if not isinstance(raw, str) or not raw.strip():
            continue
        candidates = {raw.strip()}
        # The name without its address tail: "Saticoy Grove Nursery, Saticoy CA"
        #                                 -> "Saticoy Grove Nursery"
        # This one matters most: prose almost always names the business without the city, and
        # matching it whole avoids leaving a dangling "Nursery" behind in the sentence.
        head = raw.split(",")[0].strip()
        if len(head) >= 4:
            candidates.add(head)
        # The distinctive stem: "Saticoy Grove Nursery" -> "Saticoy Grove".
        stem = _VENDOR_NOISE.sub("", raw).strip(" ,.-")
        # Guard against over-matching. A 1-3 character stem ("CA") would hit ordinary words, and
        # a single common word ("Organic", "Valley") is worse still — it survives inside normal
        # sentences. A multi-word stem is specific enough to be safe on its own.
        if len(stem) >= 4 and (" " in stem or stem.lower() not in _VENDOR_STEM_STOPWORDS):
            candidates.add(stem)
        # Longest first, so the fullest form wins and shorter forms only mop up what is left.
        for candidate in sorted(candidates, key=len, reverse=True):
            # Word boundaries (lookarounds, so a candidate that starts or ends on
            # punctuation still matches): without them a supplier named "Test"
            # turned "tested" into "[supplier withheld]ed" — the redaction must
            # remove the NAME, never the middle of an unrelated word.
            text = re.sub(rf"(?<!\w){re.escape(candidate)}(?!\w)", _REDACTED, text, flags=re.IGNORECASE)
    # Collapse a redaction that swallowed part of a name and left its tail behind
    # ("[supplier withheld] Nursery" -> "[supplier withheld]").
    text = re.sub(
        rf"{re.escape(_REDACTED)}(\s+(?:nursery|nurseries|seeds?|supply|farms?|inc|llc|ltd|co)\b\.?)+",
        _REDACTED,
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s{2,}", " ", text).strip()


def public_free_text(value):
    """Strip farm financials and unsupportable market claims from a public free-text field."""
    if not isinstance(value, str) or not value:
        return value
    cleaned = value
    for pattern in FINANCIAL_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    for pattern in VERIFICATION_PATTERNS:
        # Evaluated against the ORIGINAL offsets of `cleaned` at each step, so a preceding
        # negation is still visible even after the financial pass has removed text.
        cleaned = _strip_unless_negated(cleaned, pattern)
    # Tidy the punctuation the removals leave behind.
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;])", r"\1", cleaned)
    cleaned = re.sub(r"([,;])\s*(?=[,.;])", "", cleaned)
    cleaned = re.sub(r"(?:^|(?<=\.))\s*[,;]\s*", " ", cleaned)
    # Removing a whole sentence leaves its terminator behind next to the previous one
    # ("We do not spray.." after "Verified organic." is redacted).
    cleaned = re.sub(r"\.\s*\.+", ".", cleaned)
    return cleaned.strip(" ,;-") or None


# Only these keys of Parcel.map_metadata may reach a public payload.
#
# WHY (2026-08-02 audit): the POLYGON was gated by location_disclosure_level while the JSON
# blob beside it was returned verbatim, so an "exact" parcel published
#     soil_health_score: 92, biodiversity_score: 92, water_efficiency_rating: "A+",
#     yield_vs_conventional: "+85%", soil_carbon_increase: "+56%", carbon_credits_eligible: true
# on the anonymous consumer endpoint. Those are self-assigned grades — precisely the
# self-created sustainability label the 2026-06 score demotion removed from consumer surfaces
# (Trazo Test #5, EU ECGT 2024/825, FTC 16 CFR 260.6).
#
# map_metadata is free-form JSON a farmer's tooling can write anything into, so this is an
# ALLOW-list, not a block-list — the same lesson as the extra_data sanitizer. It carries what a
# MAP needs and nothing else; a new scoring key added upstream cannot leak by default.
PUBLIC_MAP_METADATA_KEYS = frozenset(
    {
        "center",
        "zoom",
        "bounds",
        "approximate",
        "area",
        "area_unit",
        "perimeter",
        "shape",
        "map_type",
    }
)


def public_map_metadata(meta):
    """Filter Parcel.map_metadata down to the map-rendering keys. Non-dicts become None."""
    if not isinstance(meta, dict):
        return None
    filtered = {k: v for k, v in meta.items() if k in PUBLIC_MAP_METADATA_KEYS}
    return filtered or None


def public_free_text_list(values):
    """Redact a farmer-authored list of short labels.

    Unlike prose, a list entry is a LABEL — redacting part of one leaves a fragment that is
    worse than nothing: "Carbon-negative certified" became "certified", which still implies a
    certification while naming neither the claim nor the body. So an entry that loses anything
    to redaction is dropped whole; entries that survive intact are kept as written.
    """
    if not isinstance(values, (list, tuple)):
        return public_free_text(values) if isinstance(values, str) else values

    kept = []
    for value in values:
        if not isinstance(value, str):
            kept.append(value)
            continue
        if public_free_text(value) == value.strip():
            kept.append(value)
    return kept or None


def public_parcel_geo(parcel) -> dict:
    """
    Geo fields a public payload may carry for this parcel, per the farmer's
    Parcel.location_disclosure_level:
      exact       — full polygon + map metadata
      approximate — no boundary; center rounded to 2 decimals (~1 km), zoom
                    capped so the map can't be zoomed onto the field
      hidden      — nothing

    Returns {"polygon": ..., "map_metadata": ..., "level": str}.
    """
    # Fail CLOSED. This used to default to "exact", so a parcel arriving without the column
    # set — a blank string, a stub object, a pre-0013 fixture — published the full field
    # polygon. Grandfathered parcels carry "exact" in the DB (migration 0013 wrote it
    # explicitly), so nothing legitimate depends on the fallback; the only rows it can reach
    # are the ones whose disclosure level is unknown, and an unknown level must not publish a
    # boundary. Matches Parcel.location_disclosure_level's own model default.
    level = getattr(parcel, "location_disclosure_level", "approximate") or "approximate"

    if level == "exact":
        return {
            "polygon": parcel.polygon,
            "map_metadata": public_map_metadata(parcel.map_metadata),
            "level": level,
        }

    if level == "approximate":
        meta = parcel.map_metadata if isinstance(parcel.map_metadata, dict) else {}
        center = meta.get("center") if isinstance(meta.get("center"), dict) else None
        approx_meta = None
        # map_metadata is free-form JSON; malformed values must degrade to
        # "no map" on the public endpoint, never to a 500.
        try:
            if center and center.get("lat") is not None and center.get("lng") is not None:
                approx_meta = {
                    "center": {
                        "lat": round(float(center["lat"]), 2),
                        "lng": round(float(center["lng"]), 2),
                    },
                    "zoom": min(int(float(meta.get("zoom") or 13)), 13),
                    "approximate": True,
                }
        except (TypeError, ValueError):
            approx_meta = None
        return {"polygon": None, "map_metadata": approx_meta, "level": level}

    return {"polygon": None, "map_metadata": None, "level": level}
