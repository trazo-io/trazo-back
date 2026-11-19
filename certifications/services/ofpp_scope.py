"""Why an OTCO plan answers the whole fraud prevention module, and the three facts OFPP 1-3 turns on.

Oregon Tilth's Organic Fraud Prevention Plan (rev 2025/08/27, source hash re-checked 2026-11-16), item
1-3: "If you grow perennial crops or harvest wild crops, do you buy certified organic products like
seeds or planting stock?" A No lets the operation mark the plan not applicable and stop. G2.0 follows
the federal Common OSP Section 2, which offers no not-applicable (§ 205.201(a)(3) applies to every
certified operation), so the same grower answers all four pages, briefly. Without a word on the page a
reviewer may read the extra pages as the operation misjudging its own scope (register row 1-3).

So an OTCO plan's G2.0 page says the module is answered in full on purpose, and states the three
facts from the plan's own answers: yes, no, or not stated, with where each comes from. It never
concludes that the plan would be not applicable; the reviewer reads the facts against OTCO's rule.
"""

from __future__ import annotations

OFPP_SCOPE_AGENTS = frozenset({"otco"})

#: Where certified organic seed, seedlings or planting stock came from, in the words the note prints.
#: OFPP 1-3 asks what the operation BUYS: seed saved on the farm, seedlings grown here and stock it
#: propagates itself are its own, not a supply chain (review of back #459).
SEED_FROM_OUTSIDE = {
    "seed_companies": "organic seed from seed companies",
    "contract_provided": "organic seed supplied under contract",
    "other": "organic seed from another source",
}
STOCK_FROM_OUTSIDE = {
    "nursery": "organic planting stock from a nursery",
    "contract_provided": "organic planting stock produced for it under contract",
    "other": "organic planting stock from another source",
}
ORGANIC_SEED = frozenset({"organic_untreated", "organic_treated"})


def _answers(osp, module_key) -> tuple[dict, bool]:
    from certifications.services.osp_module_pdf import _module_entry

    entry = _module_entry(osp, module_key)
    attested_na = bool(entry.get("not_applicable")) and bool(entry.get("na_attestation"))
    # An attested not-applicable module holds no answers, whatever it stored before the election
    # (review of back #459: an earlier organic seed answer printed "yes" beside G3.0 marked N/A).
    return ({} if attested_na else entry.get("answers") or {}), attested_na


def _value(answers, key):
    from certifications.osp_modules.conditions import answer_value

    return answer_value(answers, key)


def _listed(value) -> list:
    if value in (None, "", [], ()):
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def scope_facts(osp) -> list[tuple[str, str, str]]:
    """(fact, "yes" | "no" | "not stated", where it comes from), in OFPP 1-3's order."""
    g4, _ = _answers(osp, "g4_0_rotation_soil")
    systems = _listed(_value(g4, "system_type"))
    perennial = ("yes" if "perennial" in systems else "no") if systems else "not stated"

    contract, _ = _answers(osp, "certification_contract")
    scopes = _listed(_value(contract, "contract_scopes"))
    _w2, w2_na = _answers(osp, "w2_0_wild_crop")
    if "wild_crops" in scopes:
        wild, wild_from = "yes", "certification scope"
    elif scopes or w2_na:
        wild = "no"
        wild_from = " and ".join(
            x for x in ("certification scope" if scopes else "", "W2.0 marked not applicable" if w2_na else "") if x
        )
    else:
        wild, wild_from = "not stated", "certification scope"

    organic, named = organic_seed_or_stock_from_outside(osp)
    organic_from = "G3.0 and G3.0b" + (f": {', '.join(named)}" if named else "")

    return [
        ("Perennial crops grown", perennial, "G4.0 system type"),
        ("Wild crops harvested", wild, wild_from),
        ("Certified organic seed, seedlings or planting stock from outside the farm", organic, organic_from),
    ]


def organic_seed_or_stock_from_outside(osp) -> tuple[str, list[str]]:
    """("yes" | "no" | "not stated", what the plan names) for certified organic seed, annual seedlings or planting
    stock bought from outside the farm, from G3.0 and G3.0b. OTCO OFPP 1-3 and CCOF G8.0 D1 both ask it."""
    g3, g3_na = _answers(osp, "g3_0_seeds")
    g32, _g32_na = _answers(osp, "g3_2_planting_stock")
    outside, unsure = [], []

    seeds = set(_listed(_value(g3, "seeds_used")))
    if seeds & ORGANIC_SEED:
        sources = _listed(_value(g3, "seed_source"))
        if not sources:
            unsure.append("organic seed, its source not stated")
        outside += [SEED_FROM_OUTSIDE[v] for v in sources if v in SEED_FROM_OUTSIDE]

    if "purchased_organic" in _listed(_value(g3, "seedlings_used")):
        outside.append("purchased organic seedlings")

    organic_stock = "organic" in _listed(_value(g3, "planting_stock_used")) or _value(g32, "stock_organic_status") in (
        "all_organic",
        "mixed",
    )
    if organic_stock:
        sources = _listed(_value(g32, "stock_source"))
        if not sources:
            unsure.append("organic planting stock, its source not stated")
        outside += [STOCK_FROM_OUTSIDE[v] for v in sources if v in STOCK_FROM_OUTSIDE]

    outside, unsure = list(dict.fromkeys(outside)), list(dict.fromkeys(unsure))
    # G3.0 decides a "no": G3.0b not applying says only that no perennial stock went in this period.
    answered = g3_na or any(_listed(_value(g3, k)) for k in ("seeds_used", "seedlings_used", "planting_stock_used"))
    if outside:
        return "yes", outside
    if unsure or not answered:
        return "not stated", unsure
    return "no", []


def ofpp_scope_note(osp) -> list[str]:
    """The G2.0 page's lines for an OTCO plan; [] for any other agent."""
    from certifications.services.packet_coverage import packet_agent

    if (packet_agent(osp).slug or "") not in OFPP_SCOPE_AGENTS:
        return []
    lines = [
        "Oregon Tilth's OFPP item 1-3 lets an operation that grows perennial crops or harvests wild crops, and "
        "buys no certified organic seed or planting stock, mark its fraud prevention plan not applicable. This "
        "plan answers the module in full on purpose: the federal Common OSP Section 2 asks it of every certified "
        "operation (§ 205.201(a)(3)), so short answers here describe a small supply chain, not a misjudged "
        "scope. The facts item 1-3 turns on, as this plan states them:"
    ]
    for fact, state, source in scope_facts(osp):
        lines.append(f"{fact}: {state} ({source}).")
    return lines
