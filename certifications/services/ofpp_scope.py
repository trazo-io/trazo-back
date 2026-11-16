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

#: G3.0 answers that put certified organic seed, seedlings or planting stock on the plan, with the
#: words the note prints for each.
ORGANIC_SEED = {"organic_untreated": "organic seed", "organic_treated": "organic seed"}
ORGANIC_SEEDLINGS = {"purchased_organic": "purchased organic seedlings", "own_organic": "organic seedlings grown here"}
ORGANIC_STOCK = {"organic": "organic planting stock"}
ORGANIC_STOCK_STATUS = {
    "all_organic": "certified organic planting stock",
    "mixed": "some certified organic planting stock",
}


def _answers(osp, module_key) -> tuple[dict, bool]:
    from certifications.services.osp_module_pdf import _module_entry

    entry = _module_entry(osp, module_key)
    attested_na = bool(entry.get("not_applicable")) and bool(entry.get("na_attestation"))
    return entry.get("answers") or {}, attested_na


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

    g3, g3_na = _answers(osp, "g3_0_seeds")
    g32, _g32_na = _answers(osp, "g3_2_planting_stock")
    named, answered = [], False
    for key, words in (
        ("seeds_used", ORGANIC_SEED),
        ("seedlings_used", ORGANIC_SEEDLINGS),
        ("planting_stock_used", ORGANIC_STOCK),
    ):
        chosen = _listed(_value(g3, key))
        answered = answered or bool(chosen)
        named += [words[v] for v in chosen if v in words]
    status = _value(g32, "stock_organic_status")
    # G3.0 decides a "no": G3.2 not applying says only that no perennial stock went in this period.
    answered = answered or g3_na
    if status in ORGANIC_STOCK_STATUS:
        named.append(ORGANIC_STOCK_STATUS[status])
    named = list(dict.fromkeys(named))
    if named:
        organic = "yes"
    elif answered:
        organic = "no"
    else:
        organic = "not stated"
    organic_from = "G3.0 and G3.2" + (f": {', '.join(named)}" if named else "")

    return [
        ("Perennial crops grown", perennial, "G4.0 system type"),
        ("Wild crops harvested", wild, wild_from),
        ("Certified organic seed, seedlings or planting stock on this plan", organic, organic_from),
    ]


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
