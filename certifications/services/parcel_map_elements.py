"""What the operator's parcel map shows, element by element.

CCOF ORGB49 §E, WSDA AGR 2264 (Map) and OTCO C2 2.3 each require an 8.5x11 map with every
application and each lists what it must show. The lists overlap and differ: only WSDA asks for
the operation's name printed on the map, only CCOF for total acreage and natural resources, only
OTCO for organic and non-organic areas and the irrigation valves. Trazo ships the operator's own
map in the packet (`parcels/maps/`) and cannot read it, so the Parcel Application asks the
operator which elements it shows (`map_elements_shown`), one list for all three agents.

The answer is the operator's statement about their map. It is printed as given, and the packet
names what the plan's agent asks for that the operator did not mark, as a [REVIEW] line for the
reviewer holding the map. It never says the map meets a list: whether it does is the agent's
determination.

An element that only applies to some parcels (livestock, treated lumber, split operations, an
irrigation system shared with prohibited materials) is named as unmarked only when the plan says
it applies, so a grower with no livestock is not told their map lacks fences.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

ALL_AGENTS = frozenset({"ccof", "otco", "wsda"})


@dataclass(frozen=True)
class MapElement:
    value: str
    en: str
    es: str
    #: The registered agents whose map list names this element.
    agents: frozenset
    #: Only named as unmarked when this returns True for (parcel answers, plan). None: always.
    applies: Callable | None = None


def _livestock(parcel_answers, osp) -> bool:
    return parcel_answers.get("livestock_present") == "yes"


def _treated_lumber(parcel_answers, osp) -> bool:
    return parcel_answers.get("treated_lumber_present") is True or (
        parcel_answers.get("treated_lumber_noncontact_present") is True
    )


def _plan_answer(osp, module_key: str, question_key: str):
    from certifications.osp_modules.conditions import answer_value

    if osp is None:
        return None
    modules = (getattr(osp, "module_responses", None) or {}).get("modules") or {}
    answers = (modules.get(module_key) or {}).get("answers") or {}
    return answer_value(answers, question_key)


def _split_operation(parcel_answers, osp) -> bool:
    return _plan_answer(osp, "g6_0_production", "split_operation") is True


PIPING_DIAGRAM_REQUIREMENT = "g4_2_natural_resources.irrigation_piping_map_upload"


def _shared_irrigation_without_diagram(parcel_answers, osp) -> bool:
    # OTCO accepts the valves on the map "or a separate diagram": the natural resources module
    # already takes that diagram, so a filed one answers this element.
    if _plan_answer(osp, "g4_2_natural_resources", "shared_irrigation_with_prohibited") is not True:
        return False
    from certifications.services.packet_attachments import ATTACHED, current_manifest

    # Inside a packet the manifest decides, as for every upload: a filed diagram the ZIP could not
    # carry is not one the reviewer holds.
    manifest = current_manifest()
    if manifest is not None:
        return not any(e.state == ATTACHED for e in manifest.for_requirement(PIPING_DIAGRAM_REQUIREMENT))
    return not osp.establishment.documents.filter(requirement=PIPING_DIAGRAM_REQUIREMENT).exists()


MAP_ELEMENTS: tuple[MapElement, ...] = (
    MapElement("north_arrow", "A north arrow", "Una flecha norte", frozenset({"ccof", "otco"})),
    MapElement("boundaries", "The parcel's boundaries", "Los límites de la parcela", ALL_AGENTS),
    MapElement(
        "operation_name",
        "The operation's name, printed on the map",
        "El nombre de la operación, impreso en el mapa",
        frozenset({"wsda"}),
    ),
    MapElement(
        "parcel_name",
        "This parcel's name or code, printed on the map",
        "El nombre o código de esta parcela, impreso en el mapa",
        frozenset({"otco", "wsda"}),
    ),
    MapElement("total_acreage", "Total acreage", "La superficie total", frozenset({"ccof"})),
    MapElement(
        "block_identifiers",
        "Permanent identifiers for blocks, lots or greenhouses",
        "Identificadores permanentes de bloques, lotes o invernaderos",
        frozenset({"ccof"}),
    ),
    MapElement(
        "crop_locations",
        "Where each crop grows (and the varieties, for perennial crops)",
        "Dónde crece cada cultivo (y las variedades, en cultivos perennes)",
        frozenset({"wsda"}),
    ),
    MapElement(
        "roads_landmarks",
        "The nearest public roads or landmarks",
        "Los caminos públicos o puntos de referencia más cercanos",
        frozenset({"ccof", "otco"}),
    ),
    MapElement(
        "buildings_operation_areas",
        "Buildings and other operation areas (storage, seedling production, post-harvest handling)",
        "Edificios y otras áreas de la operación (almacenamiento, producción de plántulas, manejo poscosecha)",
        frozenset({"ccof", "otco"}),
    ),
    MapElement(
        "organic_nonorganic_areas",
        "Organic and non-organic production or handling areas",
        "Las áreas de producción o manejo orgánicas y no orgánicas",
        frozenset({"otco"}),
        _split_operation,
    ),
    MapElement(
        "adjacent_land_uses",
        "Adjacent land uses, labeled, including land managed by others",
        "Los usos de la tierra colindante, rotulados, incluida la tierra que manejan otros",
        frozenset({"ccof", "wsda"}),
    ),
    MapElement(
        "buffer_zones",
        "Buffer zones: where they are, how wide, and any crop grown in them",
        "Las zonas de amortiguamiento: dónde están, su ancho y cualquier cultivo que crezca en ellas",
        ALL_AGENTS,
    ),
    MapElement(
        "natural_resources",
        "Natural resources (waterways, woodlands, windbreaks)",
        "Recursos naturales (cursos de agua, bosques, cortavientos)",
        frozenset({"ccof"}),
    ),
    MapElement(
        "livestock",
        "For livestock: fences, shade and water",
        "Para el ganado: cercos, sombra y agua",
        frozenset({"ccof", "wsda"}),
        _livestock,
    ),
    MapElement(
        "treated_lumber",
        "Existing treated-lumber installations",
        "Las instalaciones existentes de madera tratada",
        frozenset({"ccof", "otco"}),
        _treated_lumber,
    ),
    MapElement(
        "irrigation_piping",
        "Irrigation valves and backflow prevention devices",
        "Las válvulas de riego y los dispositivos de prevención de reflujo",
        frozenset({"otco"}),
        _shared_irrigation_without_diagram,
    ),
)

MAP_ELEMENTS_BY_VALUE = {e.value: e for e in MAP_ELEMENTS}


def unmarked_elements(chosen, parcel_answers: dict, osp, agent: str | None) -> list[MapElement]:
    """The elements this plan's agent asks for that the operator did not mark, in list order.

    `agent` is the register slug the packet speaks for, or None when the plan's agent has no
    register (then every element any registered agent asks for is named: the reviewer's own
    list is unknown, and leaving one out would read as not asked).
    """
    picked = set(chosen) if isinstance(chosen, (list, tuple)) else set()
    out = []
    for element in MAP_ELEMENTS:
        if element.value in picked:
            continue
        if agent in ALL_AGENTS and agent not in element.agents:
            continue
        if element.applies is not None and not element.applies(parcel_answers, osp):
            continue
        out.append(element)
    return out


def unmarked_line(chosen, parcel_answers: dict, osp, agent: str | None) -> str:
    missing = unmarked_elements(chosen, parcel_answers, osp, agent)
    if not missing:
        return ""
    return (
        "[REVIEW] The operator does not mark these as shown on the parcel map: "
        + "; ".join(e.en[:1].lower() + e.en[1:] for e in missing)
        + "."
    )
