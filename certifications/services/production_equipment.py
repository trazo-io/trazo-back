"""The farm equipment that contacts organic crops, each with what the plan can say of it (G6.0 page F).

CCOF G6.0 C2 and G6.1 B1, OTCO C9 9.1-1 and WSDA AGR 2121 I 1-2b ask for one table: the item,
whether it is dedicated to organic production, own / rent / borrow / custom hire, how it is cleaned
before organic use and with what, and whether it is rinsed. The register's API, the module PDF and
the coverage page all read `equipment_rows`, so they cannot disagree about which item is still open.

What an item owes depends on what the operation said of it. Every item needs its use, whether it is
dedicated and who owns it. An item that also works non-organic crops or land, or that comes from
outside the operation (rented, borrowed, custom hire), may carry residues in, so it also needs how
it is cleaned and whether it is rinsed (§ 205.272(a)). A dedicated item the operation owns owes no
cleaning statement.
"""

from __future__ import annotations

#: Row states. Only `complete` closes the item on the coverage page.
COMPLETE = "complete"
INCOMPLETE = "incomplete"

#: Ownership that brings an item in from outside the operation.
_FROM_OUTSIDE = frozenset({"rent", "borrow", "custom_hire"})


def needs_cleaning(item) -> bool:
    """Whether the item owes a cleaning statement: shared with non-organic work, or from outside."""
    return item.dedicated_organic is False or item.ownership in _FROM_OUTSIDE


#: What an item can leave unsaid, by code (the API's `missing`, translated by the app) and in the
#: words the plan and the coverage page print.
MISSING_FACTS = {
    "dedicated": "whether it is dedicated to organic production",
    "ownership": "whether it is owned, rented, borrowed or custom hired",
    "cleaning_method": "how it is cleaned before organic use",
    "rinsed": "whether it is rinsed",
}


def missing_codes(item) -> list[str]:
    """What the operation has not said of this item, in the order the table asks it."""
    missing = []
    if item.dedicated_organic is None:
        missing.append("dedicated")
    if not item.ownership:
        missing.append("ownership")
    if needs_cleaning(item):
        if not item.cleaning_method.strip():
            missing.append("cleaning_method")
        if item.rinsed is None:
            missing.append("rinsed")
    return missing


def missing_facts(item) -> list[str]:
    return [MISSING_FACTS[code] for code in missing_codes(item)]


def item_state(item) -> tuple[str, list[str]]:
    """(state, missing facts) for one item."""
    missing = missing_facts(item)
    return (INCOMPLETE if missing else COMPLETE), missing


def equipment_rows(establishment) -> list[dict]:
    """One row per item: {item, state, missing}."""
    if establishment is None:
        return []
    items = establishment.production_equipment.order_by("name", "pk")
    return [dict(item=item, **dict(zip(("state", "missing"), item_state(item)))) for item in items]


def _g6_0_entry(osp) -> dict:
    return ((osp.module_responses or {}).get("modules") or {}).get("g6_0_production") or {}


def equipment_shown(osp) -> bool:
    """Whether G6.0 prints the equipment table: the plan says equipment contacts organic crops, and
    the module is not attested not applicable."""
    from certifications.osp_modules.conditions import answer_value

    entry = _g6_0_entry(osp)
    if entry.get("not_applicable"):
        return False
    return answer_value(entry.get("answers") or {}, "uses_production_equipment") is True


def shared_answer_conflict(osp, rows: list[dict]) -> str:
    """A sentence when the plan's yes/no on shared equipment disagrees with the register, else ""."""
    from certifications.osp_modules.conditions import answer_value

    shared = answer_value(_g6_0_entry(osp).get("answers") or {}, "equipment_shared_with_nonorganic")
    shared_items = [row["item"].name for row in rows if row["item"].dedicated_organic is False]
    if shared is False and shared_items:
        return (
            "The plan says no equipment is also used on non-organic crops or land, and the register lists "
            + ", ".join(shared_items)
            + " as not dedicated to organic production."
        )
    if shared is True and rows and not shared_items:
        return (
            "The plan says some equipment is also used on non-organic crops or land, and every item in the "
            "register is listed as dedicated to organic production."
        )
    return ""
