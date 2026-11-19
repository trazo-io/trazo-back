"""Organic products bought in, and crops handled or branded by other operations, as the plan states them (2026-11-19).

CCOF G8.0 (ORGB33, V3 R2 10/23/2024) D1 asks the operation to mark every scenario that applies: it buys certified
organic seed, annual seedlings or planting stock; it sources certified organic crops or products for resale or
distribution; it sends certified organic crops to another operation for storage, handling or processing; it packs
into brands or labels owned by other operations; or none of these. The form sends each scenario to its own section
(G3.0, G6.5, G6.1 and G6.2, G7.0), and Trazo asks each fact there.

So the scenario list is not asked a second time, where it could disagree with those sections. G8.0 §D states each
scenario from the answers given there: yes, no, or not stated, with the answer it comes from. Nothing is read from
records, and a section not answered yet makes its scenario "not stated", never "no".
"""

from __future__ import annotations

from dataclasses import dataclass

from certifications.osp_modules.schema import text

YES = "yes"
NO = "no"
NOT_STATED = "not stated"

OFF_FARM_STORAGE = ("commercial_cold_off_farm", "certified_handler", "uncertified_facility")


@dataclass(frozen=True)
class Scenario:
    key: str
    label: dict
    state: str
    #: The answers the state comes from, in the words the module PDF prints.
    basis: tuple[str, ...]
    #: The modules where the scenario is answered, by code, in the order the plan's pages run.
    answered_in: tuple[str, ...]


def _answers(osp, module_key):
    from certifications.services.ofpp_scope import _answers as answers

    return answers(osp, module_key)


def _value(answers, key):
    from certifications.osp_modules.conditions import answer_value

    return answer_value(answers, key)


def _listed(value) -> list:
    if value in (None, "", [], ()):
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _seed_and_stock(osp) -> Scenario:
    from certifications.services.ofpp_scope import organic_seed_or_stock_from_outside

    state, named = organic_seed_or_stock_from_outside(osp)
    if named:
        basis = (f"G3.0 and G3.0b: {', '.join(named)}",)
    elif state == NO:
        basis = ("G3.0: none bought in",)
    else:
        basis = ("G3.0 not answered yet",)
    return Scenario(
        key="organic_seed_or_stock",
        label=text(
            "Buys certified organic seed, annual seedlings or planting stock",
            "Compra semilla, plántulas anuales o material de plantación orgánicos certificados",
        ),
        state=state,
        basis=basis,
        answered_in=("G3.0", "G3.0b"),
    )


def _resale(osp) -> Scenario:
    g65, _ = _answers(osp, "g6_5_sales_soe")
    value = _value(g65, "sales_soe_supplier_verification")
    if value == "yes":
        state, basis = YES, ("G6.5: buys in or co-markets organic product",)
    elif value == "no":
        state, basis = NO, ("G6.5: sells only what it grows",)
    else:
        state, basis = NOT_STATED, ("G6.5 not answered yet",)
    return Scenario(
        key="organic_product_for_resale",
        label=text(
            "Sources certified organic crops or products for resale or distribution",
            "Adquiere cultivos o productos orgánicos certificados para revender o distribuir",
        ),
        state=state,
        basis=basis,
        answered_in=("G6.5",),
    )


def _handled_or_stored_elsewhere(osp) -> Scenario:
    yes, no, unsure = [], [], []
    answered_handling = answered_storage = False

    g61, _ = _answers(osp, "g6_1_harvest_transport")
    handled = _value(g61, "handled_by_another_operation")
    if handled == "yes_certified":
        yes.append("G6.1: handled off the farm by a certified organic operation")
    elif handled == "yes_uncertified":
        yes.append("G6.1: handled off the farm by an operation that is not certified")
    elif handled == "yes_ownership_transfers":
        # CCOF G6.1 C1 ends the handling form at this answer: the crop is that operation's once delivered.
        no.append("G6.1: handled by another operation only after ownership passes to it")
    elif handled == "no":
        no.append("G6.1: nobody off the operation handles the crop")
    answered_handling = handled in ("yes_certified", "yes_uncertified", "yes_ownership_transfers", "no")

    g62, g62_na = _answers(osp, "g6_2_storage")
    locations = _listed(_value(g62, "storage_locations"))
    if g62_na:
        no.append("G6.2 marked not applicable")
        answered_storage = True
    elif locations:
        answered_storage = True
        if set(locations) & set(OFF_FARM_STORAGE):
            owns = _value(g62, "owns_crop_in_storage")
            if owns == "yes":
                yes.append("G6.2: stored off the farm while the operation still owns it")
            elif owns == "no":
                no.append("G6.2: stored off the farm only after ownership passes on delivery")
            elif _value(g62, "third_party_storage_contracted") is True:
                yes.append("G6.2: stored by another operation under contract")
            else:
                unsure.append("G6.2: stored off the farm, whether the operation still owns it there not stated")
        else:
            no.append("G6.2: stored on the farm only")

    if yes:
        state, basis = YES, yes
    elif unsure or not (answered_handling and answered_storage):
        not_yet = [
            f"{code} not answered yet"
            for code, done in (("G6.1", answered_handling), ("G6.2", answered_storage))
            if not done
        ]
        state, basis = NOT_STATED, no + unsure + not_yet
    else:
        state, basis = NO, no
    return Scenario(
        key="crop_to_another_operation",
        label=text(
            "Sends certified organic crops to another operation for storage, handling or processing",
            "Envía cultivos orgánicos certificados a otra operación para almacenarlos, manejarlos o procesarlos",
        ),
        state=state,
        basis=tuple(basis),
        answered_in=("G6.1", "G6.2"),
    )


def _brand_owners(osp) -> Scenario:
    g70, g70_na = _answers(osp, "g7_0_labeling")
    leaves_as = _listed(_value(g70, "product_leaves_as"))
    if "buyer_label" in leaves_as:
        state, basis = YES, ("G7.0: sold under the buyer's own label (private label or repack)",)
    elif g70_na:
        state, basis = NO, ("G7.0 marked not applicable",)
    elif leaves_as:
        state, basis = NO, ("G7.0: no product leaves under another company's label",)
    else:
        state, basis = NOT_STATED, ("G7.0 not answered yet",)
    return Scenario(
        key="packs_for_brand_owners",
        label=text(
            "Packs into brands or labels owned by other operations",
            "Empaca bajo marcas o etiquetas de otras operaciones",
        ),
        state=state,
        basis=basis,
        answered_in=("G7.0",),
    )


def sourcing_scenarios(osp) -> list[Scenario]:
    """The four scenarios, in the order CCOF G8.0 D1 lists them."""
    return [_seed_and_stock(osp), _resale(osp), _handled_or_stored_elsewhere(osp), _brand_owners(osp)]


def sourcing_scenario_lines(osp) -> tuple[list[str], list[str]]:
    """(the scenario lines, the [REVIEW] lines) G8.0 §D prints."""
    scenarios = sourcing_scenarios(osp)
    lines = []
    for s in scenarios:
        lines.append(f"{s.label['en']}: {s.state} ({'; '.join(s.basis)}).")
    if all(s.state == NO for s in scenarios):
        lines.append("None of these applies, as the plan states it.")

    reviews = []
    g80, _ = _answers(osp, "g8_0_record_keeping")
    sources = _value(g80, "sources_organic_products")
    bought = [s for s in scenarios[:2] if s.state == YES]
    if sources is False and bought:
        reviews.append(
            "[REVIEW] §B says the operation sources no organic agricultural products, but the plan states it "
            + " and ".join(
                f"{s.label['en'][0].lower()}{s.label['en'][1:]} ({' and '.join(s.answered_in)})" for s in bought
            )
            + "."
        )
    if sources is True and all(s.state == NO for s in scenarios[:2]):
        reviews.append(
            "[REVIEW] §B says the operation sources organic agricultural products, but G3.0, G3.0b and G6.5 name "
            "none bought in."
        )
    return lines, reviews
